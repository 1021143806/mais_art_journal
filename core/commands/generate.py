"""/dr 通配 fallback：风格名 / 自然语言生成

dispatcher 在子命令查表未命中时进入这里。
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

from ..config import get_model_config, get_style_prompt, resolve_style_alias
from ..pipeline import (
    GenerationRequest,
    build_natural_command_pipeline,
    build_style_command_pipeline,
    make_pipeline_context,
)
from ..state import runtime_state
from ..utils import ImageProcessor
from ..utils.request_context import RequestContext
from .registry import CommandResult

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin
    from .dispatcher import DispatcherContext

logger = logging.getLogger("plugin.mais_art_journal.cmd.generate")


_RESERVED = {"list", "models", "config", "set", "reset", "on", "off",
             "model", "recall", "default", "selfie", "styles", "style", "help"}

_ACTION_WORDS = ["画", "生成", "绘制", "创作", "制作", "画成", "变成", "改成", "用", "来", "帮我", "给我"]


# 单例缓存：每条 pipeline 在进程内只创建一次
_STYLE_PIPELINE = None
_NATURAL_PIPELINE = None


def _get_style_pipeline():
    global _STYLE_PIPELINE
    if _STYLE_PIPELINE is None:
        _STYLE_PIPELINE = build_style_command_pipeline()
    return _STYLE_PIPELINE


def _get_natural_pipeline():
    global _NATURAL_PIPELINE
    if _NATURAL_PIPELINE is None:
        _NATURAL_PIPELINE = build_natural_command_pipeline()
    return _NATURAL_PIPELINE


async def handle_generate(plugin: "MaisArtPlugin", dctx: "DispatcherContext", content: str) -> CommandResult:
    """fallback 入口：先尝试风格，否则按自然语言"""
    if not content:
        await plugin.ctx.send.text(
            f"请指定风格或描述，格式：{dctx.prefix} <风格> 或 {dctx.prefix} <描述>\n"
            f"可用：{dctx.prefix} styles 查看风格列表",
            dctx.stream_id,
        )
        return False, "缺少内容参数", True

    if content.lower() in _RESERVED:
        await plugin.ctx.send.text(f"'{content}' 是保留词，请使用其他名称", dctx.stream_id)
        return False, f"使用了保留词: {content}", True

    # 1. 先尝试匹配风格
    actual_style = resolve_style_alias(plugin, content)
    style_prompt = get_style_prompt(plugin, actual_style) if actual_style else None
    if style_prompt and actual_style:
        logger.info(f"{dctx.log_prefix} 识别为风格模式: {content}")
        return await _execute_style_mode(plugin, dctx, content, actual_style, style_prompt)

    # 2. 自然语言检测
    has_action_word = any(w in content for w in _ACTION_WORDS)
    if has_action_word or len(content) > 6:
        logger.info(f"{dctx.log_prefix} 识别为自然语言模式: {content}")
        return await _execute_natural_mode(plugin, dctx, content)

    await plugin.ctx.send.text(
        f"风格 '{content}' 不存在，使用 {dctx.prefix} styles 查看所有风格", dctx.stream_id,
    )
    return False, f"风格 '{content}' 不存在", True


# ==================== 风格模式 ====================

async def _execute_style_mode(
    plugin: "MaisArtPlugin",
    dctx: "DispatcherContext",
    style_label: str,
    actual_style: str,
    style_prompt: str,
) -> CommandResult:
    chat_id, stream_id = dctx.chat_id, dctx.stream_id
    global_command_model = plugin.config.basic.pic_command_model
    model_id = runtime_state.get_command_default_model(chat_id, global_command_model)

    if not runtime_state.is_model_enabled(chat_id, model_id):
        await plugin.ctx.send.text(f"模型 {model_id} 当前不可用", stream_id)
        return False, f"模型 {model_id} 已禁用", True

    model_cfg = get_model_config(plugin, model_id)
    if not model_cfg:
        await plugin.ctx.send.text(f"模型 '{model_id}' 不存在", stream_id)
        return False, "模型配置不存在", True

    # 风格模式必须有输入图
    request_ctx = RequestContext(
        plugin, log_prefix=dctx.log_prefix, command_message=dctx.message,
        chat_id=chat_id, stream_id=stream_id,
    )
    image_processor = ImageProcessor(request_ctx)
    input_image = await image_processor.get_recent_image()
    if not input_image:
        await plugin.ctx.send.text("请先发送图片", stream_id)
        return False, "未找到输入图片", True

    if not model_cfg.get("support_img2img", True):
        await plugin.ctx.send.text(f"模型 {model_id} 不支持图生图", stream_id)
        return False, f"模型 {model_id} 不支持图生图", True

    if plugin.config.basic.enable_debug_info:
        await plugin.ctx.send.text(f"使用风格：{style_label}", stream_id)

    req = GenerationRequest(
        description=style_prompt,
        model_id=model_id,
        strength=0.7,
        input_image_base64=input_image,
        send_image=True,
        update_cache=True,
        schedule_recall=True,
        debug_info=plugin.config.basic.enable_debug_info,
        stream_id=stream_id,
        chat_id=chat_id,
        log_prefix=dctx.log_prefix,
        command_message=dctx.message,
        source="cmd_style",
    )
    ctx = make_pipeline_context(plugin, req)
    out = await _get_style_pipeline().run(req, ctx)

    if not out.success:
        return False, f"图生图失败: {out.error}", True
    return True, "图生图命令执行成功", True


# ==================== 自然语言模式 ====================

async def _execute_natural_mode(
    plugin: "MaisArtPlugin",
    dctx: "DispatcherContext",
    description: str,
) -> CommandResult:
    chat_id, stream_id = dctx.chat_id, dctx.stream_id

    # 从描述中提取模型 ID（"用model2画…"等）
    extracted = _extract_model_id(description)
    if extracted:
        model_id = extracted
        description = _remove_model_pattern(description)
        logger.info(f"{dctx.log_prefix} 从描述中提取模型ID: {model_id}")
    else:
        global_command_model = plugin.config.basic.pic_command_model
        model_id = runtime_state.get_command_default_model(chat_id, global_command_model)

    if not runtime_state.is_model_enabled(chat_id, model_id):
        await plugin.ctx.send.text(f"模型 {model_id} 当前不可用", stream_id)
        return False, f"模型 {model_id} 已禁用", True

    model_cfg = get_model_config(plugin, model_id)
    if not model_cfg:
        await plugin.ctx.send.text(f"模型 '{model_id}' 不存在", stream_id)
        return False, "模型配置不存在", True

    # 检测输入图
    request_ctx = RequestContext(
        plugin, log_prefix=dctx.log_prefix, command_message=dctx.message,
        chat_id=chat_id, stream_id=stream_id,
    )
    image_processor = ImageProcessor(request_ctx)
    input_image = await image_processor.get_recent_image()

    req = GenerationRequest(
        description=description,
        model_id=model_id,
        strength=0.7 if input_image else None,
        input_image_base64=input_image,
        send_image=True,
        update_cache=True,
        schedule_recall=True,
        debug_info=plugin.config.basic.enable_debug_info,
        stream_id=stream_id,
        chat_id=chat_id,
        log_prefix=dctx.log_prefix,
        command_message=dctx.message,
        source="cmd_natural",
    )
    ctx = make_pipeline_context(plugin, req)
    out = await _get_natural_pipeline().run(req, ctx)

    mode_text = "图生图" if input_image else "文生图"
    if not out.success:
        return False, f"{mode_text}失败: {out.error}", True
    return True, f"{mode_text}命令执行成功", True


# ==================== 工具 ====================

_MODEL_ID_PATTERNS = [
    re.compile(r'(?:用|使用)\s*(model\d+)', re.IGNORECASE),
    re.compile(r'(?:用|使用)\s*(?:模型|型号)\s*(\d+)', re.IGNORECASE),
    re.compile(r'^(model\d+)', re.IGNORECASE),
]


def _extract_model_id(description: str) -> Optional[str]:
    for pat in _MODEL_ID_PATTERNS:
        match = pat.search(description)
        if match:
            mid = match.group(1)
            if mid.isdigit():
                mid = f"model{mid}"
            return mid.lower()
    return None


_MODEL_PATTERN_REMOVE = [
    re.compile(r'(?:用|使用)\s*model\d+\s*(?:画|生成|创作)?', re.IGNORECASE),
    re.compile(r'(?:用|使用)\s*(?:模型|型号)\s*\d+\s*(?:画|生成|创作)?', re.IGNORECASE),
    re.compile(r'^model\d+\s*(?:画|生成|创作)?', re.IGNORECASE),
]


def _remove_model_pattern(description: str) -> str:
    for pat in _MODEL_PATTERN_REMOVE:
        description = pat.sub("", description)
    return description.strip()
