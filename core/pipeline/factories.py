"""Pipeline 工厂 + 请求构造器 + 上下文构造器

入口（5 个）：
- build_action_pipeline()            智能 Tool 全流程
- build_style_command_pipeline()     /dr <风格>
- build_natural_command_pipeline()   /dr <自然语言>
- build_auto_selfie_pipeline()       自动自拍后台任务
- build_standalone_pipeline()        generate_image_standalone 内部备用

辅助：
- build_request_from_tool_kwargs    把 @Tool 注入的 kwargs 解析成 GenerationRequest
- make_pipeline_context              构造 PipelineContext（cache / image_processor / client_factory / request_ctx）
"""
from __future__ import annotations

import base64
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..api_clients import build_client_context_from_plugin, get_client_class
from ..state import runtime_state
from ..utils import CacheManager, ImageProcessor
from ..utils.request_context import RequestContext
from .pipeline import Pipeline
from .request import GenerationRequest
from .step import PipelineContext
from .steps import (
    BuildSelfiePrompt,
    CallApi,
    CheckCache,
    DetectImg2ImgFallback,
    MergeNegativePrompt,
    OptimizePrompt,
    ParseResponse,
    ResolveImageData,
    ResolveModel,
    ResolveSize,
    ScheduleRecall,
    SendImage,
    UpdateCache,
    ValidateModelConfig,
)

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin

logger = logging.getLogger("plugin.mais_art_journal.factories")


# ==================== 5 个 Pipeline 工厂 ====================

def build_action_pipeline() -> Pipeline:
    """@Tool draw_picture 全流程（智能文/图生图 + 自拍判定）"""
    return Pipeline(
        [
            ResolveModel(),
            ValidateModelConfig(),
            ResolveSize(),
            OptimizePrompt(),
            BuildSelfiePrompt(),
            MergeNegativePrompt(),
            DetectImg2ImgFallback(),
            CheckCache(),
            CallApi(),
            ParseResponse(),
            ResolveImageData(),
            SendImage(),
            UpdateCache(),
            ScheduleRecall(),
        ],
        name="action",
    )


def build_style_command_pipeline() -> Pipeline:
    """/dr <风格>：style_prompt 已就位，不再做通用 OptimizePrompt"""
    return Pipeline(
        [
            ResolveModel(),
            ValidateModelConfig(),
            ResolveSize(),
            MergeNegativePrompt(),
            DetectImg2ImgFallback(),
            CheckCache(),
            CallApi(),
            ParseResponse(),
            ResolveImageData(),
            SendImage(),
            UpdateCache(),
            ScheduleRecall(),
        ],
        name="cmd_style",
    )


def build_natural_command_pipeline() -> Pipeline:
    """/dr <自然语言>：含 OptimizePrompt，但不走自拍分支"""
    return Pipeline(
        [
            ResolveModel(),
            ValidateModelConfig(),
            ResolveSize(),
            OptimizePrompt(),
            MergeNegativePrompt(),
            DetectImg2ImgFallback(),
            CheckCache(),
            CallApi(),
            ParseResponse(),
            ResolveImageData(),
            SendImage(),
            UpdateCache(),
            ScheduleRecall(),
        ],
        name="cmd_natural",
    )


def build_auto_selfie_pipeline() -> Pipeline:
    """自动自拍后台任务：prompt 已构造好，不发不缓不撤"""
    return Pipeline(
        [
            ResolveModel(),
            ValidateModelConfig(),
            ResolveSize(),
            MergeNegativePrompt(),
            DetectImg2ImgFallback(),
            CallApi(),
            ParseResponse(),
            ResolveImageData(),
        ],
        name="auto_selfie",
    )


def build_standalone_pipeline() -> Pipeline:
    """generate_image_standalone 内部备用编排（当前直接走 api_clients 入口）"""
    return Pipeline(
        [
            ValidateModelConfig(),
            ResolveSize(),
            MergeNegativePrompt(),
            CallApi(),
            ParseResponse(),
            ResolveImageData(),
        ],
        name="standalone",
    )


# ==================== PipelineContext 构造 ====================

def make_pipeline_context(plugin: "MaisArtPlugin", req: GenerationRequest) -> PipelineContext:
    """构造一次请求的 PipelineContext"""
    request_ctx = RequestContext(
        plugin,
        log_prefix=req.log_prefix,
        command_message=req.command_message,
        chat_id=req.chat_id,
        stream_id=req.stream_id,
    )

    cache = CacheManager(request_ctx)
    image_processor = ImageProcessor(request_ctx)

    # 按 api_format 缓存 client 实例（一次请求一份）
    client_ctx = build_client_context_from_plugin(plugin, log_prefix=req.log_prefix)
    client_cache: Dict[str, Any] = {}

    def client_factory(api_format: str):
        key = (api_format or "openai").lower()
        if key not in client_cache:
            client_cache[key] = get_client_class(key)(client_ctx)
        return client_cache[key]

    return PipelineContext(
        plugin=plugin,
        cache=cache,
        image_processor=image_processor,
        client_factory=client_factory,
        request_ctx=request_ctx,
    )


# ==================== GenerationRequest 构造 ====================


def _arg_get(kwargs: Dict[str, Any], key: str, default: Any = None) -> Any:
    """从 Tool kwargs 顶层取参数；空字符串视为缺失。

    SDK 2.x 的 @Tool 把 function_args 直接展开成 kwargs（含 stream_id/chat_id 等
    上下文）。
    """
    val = kwargs.get(key)
    if val not in (None, ""):
        return val
    return default


def _build_log_prefix(kwargs: Dict[str, Any]) -> str:
    """优先用群名/昵称，缺失时用群号/QQ号兜底。Tool 路径下宿主只传 id。"""
    group_name = kwargs.get("group_name")
    user_nickname = kwargs.get("user_nickname")
    group_id = str(kwargs.get("group_id") or "").strip()
    user_id = str(kwargs.get("user_id") or "").strip()
    if group_name or group_id:
        return f"[{group_name or '群' + group_id}]"
    if user_nickname or user_id:
        return f"[{user_nickname or 'QQ' + user_id} 的 私聊]"
    return "[MaisArt]"


def _load_selfie_reference_image(plugin: "MaisArtPlugin", log_prefix: str) -> Optional[str]:
    """加载 selfie.reference_image_path 指定的参考图，返回 base64 或 None"""
    path = (plugin.config.selfie.reference_image_path or "").strip()
    if not path:
        return None

    try:
        if not os.path.isabs(path):
            path = os.path.join(plugin.plugin_dir, path)
        if not os.path.exists(path):
            logger.warning(f"{log_prefix} 自拍参考图片文件不存在: {path}")
            return None
        with open(path, "rb") as f:
            data = f.read()
        logger.info(f"{log_prefix} 从文件加载自拍参考图片: {path}")
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        logger.error(f"{log_prefix} 加载自拍参考图片失败: {e}")
        return None


async def build_request_from_tool_kwargs(
    plugin: "MaisArtPlugin",
    kwargs: Dict[str, Any],
) -> Optional[GenerationRequest]:
    """从 @Tool 注入的 kwargs 构造 GenerationRequest

    SDK 2.x 下 host 调用 Tool 时把 function_args 平铺进 kwargs，并附带
    stream_id / chat_id / group_id / user_id / platform 等上下文字段。
    host 不会自动注入触发消息 id——但 LLM 看得到 chat history 里每条用户消息的
    <message msg_id="..."> 前缀，因此插件在 Tool schema 里声明 msg_id 参数，
    LLM 调用时会自动把"触发本次工具调用的那条用户消息 id"填进来。
    据此即可 100% 锁定原始消息，支持图生图——见 ImageProcessor.fetch_image_by_triggering_id。

    返回 None 表示早退（插件被禁用 / 描述为空 / 模型禁用等已外层处理过的场景），
    调用方应直接返回 (False, msg)。
    """
    stream_id: str = str(kwargs.get("stream_id") or "")
    chat_id: str = str(kwargs.get("chat_id") or stream_id)
    log_prefix = _build_log_prefix(kwargs)

    # 插件总开关
    global_enabled = plugin.config.plugin.enabled
    if not runtime_state.is_plugin_enabled(chat_id, global_enabled):
        logger.info(f"{log_prefix} 插件在当前聊天流已禁用")
        return None  # 静默跳过

    # 提取参数（Tool 路径直接从 kwargs 取）
    description = str(_arg_get(kwargs, "description", "") or "").strip()
    model_id = str(_arg_get(kwargs, "model_id", "") or "").strip()
    strength_raw = _arg_get(kwargs, "strength", 0.7)
    size = str(_arg_get(kwargs, "size", "") or "").strip()

    selfie_mode_raw = _arg_get(kwargs, "selfie_mode", False)
    is_selfie = selfie_mode_raw in (True, "true", "True", 1, "1")
    selfie_style_llm = str(_arg_get(kwargs, "selfie_style", "") or "").strip().lower()
    free_hand_action = str(_arg_get(kwargs, "free_hand_action", "") or "").strip()

    # 自拍风格优先级：运行时 > LLM > 全局
    global_style = plugin.config.selfie.default_style
    runtime_style = runtime_state.get_selfie_style(chat_id, None)
    if runtime_style is not None:
        selfie_style = runtime_style
    elif selfie_style_llm in ("standard", "mirror", "photo"):
        selfie_style = selfie_style_llm
    else:
        selfie_style = global_style

    if not description:
        # LLM 必须通过 Tool 的 description 参数明确告诉我们要画什么
        if stream_id:
            try:
                await plugin.ctx.send.text(
                    "你需要告诉我想要画什么样的图片哦~ 比如说'画一只可爱的小猫'",
                    stream_id,
                )
            except Exception as e:
                logger.warning(f"{log_prefix} 发送空描述提示失败: {e}")
        return None

    if len(description) > 1000:
        description = description[:1000]

    # strength 校验
    try:
        strength: Optional[float] = float(strength_raw)
        if not (0.1 <= strength <= 1.0):
            strength = 0.7
    except (ValueError, TypeError):
        strength = 0.7

    # 输入图：
    # - 自拍模式：可用本地参考图（图生图自拍）
    # - 非自拍模式：依据 host 注入的 triggering_message_id 锁定触发消息抓图，
    #   有图 → 图生图；没图（包括框架未注入字段）→ 文生图。
    input_image_base64: Optional[str] = None
    silent_fallback = False
    activity_scene: Optional[Dict[str, Any]] = None

    if is_selfie:
        # 日程场景增强
        global_schedule = plugin.config.selfie.schedule_enabled
        if runtime_state.is_selfie_schedule_enabled(chat_id, global_schedule):
            try:
                from ..selfie.schedule_provider import get_schedule_provider
                from ..prompts.scene_action_llm import generate_scene_with_llm, get_action_for_activity
                provider = get_schedule_provider(ctx=plugin.ctx, chat_id="global")
                if provider:
                    activity = await provider.get_current_activity()
                    if activity:
                        activity_scene = await generate_scene_with_llm(
                            plugin.ctx, activity, selfie_style,
                            llm_task=plugin.config.basic.llm_task_name or "utils",
                        )
                        if activity_scene:
                            logger.info(f"{log_prefix} LLM 生成日程场景: {activity.activity_type.value}")
                        else:
                            activity_scene = get_action_for_activity(activity)
                            logger.info(f"{log_prefix} LLM 失败，使用确定性映射: {activity.activity_type.value}")
            except Exception as e:
                logger.debug(f"{log_prefix} 获取日程活动失败（非必要）: {e}")

        # 参考图（图生图自拍）
        reference_image = _load_selfie_reference_image(plugin, log_prefix)
        if reference_image:
            input_image_base64 = reference_image
            silent_fallback = True
            if strength is None or strength > 0.6:
                strength = 0.6
    else:
        triggering_msg_id = str(_arg_get(kwargs, "msg_id", "") or "").strip()
        if triggering_msg_id:
            request_ctx = RequestContext(
                plugin, log_prefix=log_prefix,
                chat_id=chat_id, stream_id=stream_id,
            )
            image_processor = ImageProcessor(request_ctx)
            input_image_base64 = await image_processor.fetch_image_by_triggering_id(
                triggering_msg_id,
            )
        else:
            logger.debug(f"{log_prefix} LLM 未填 msg_id 参数，跳过图生图检测")

    is_img2img = input_image_base64 is not None
    if not is_img2img:
        strength = None

    return GenerationRequest(
        description=description,
        model_id=model_id,
        size=size,
        strength=strength,
        input_image_base64=input_image_base64,
        is_selfie=is_selfie,
        selfie_style=selfie_style,  # type: ignore[arg-type]
        free_hand_action=free_hand_action,
        activity_scene=activity_scene,
        send_image=True,
        update_cache=True,
        schedule_recall=True,
        debug_info=plugin.config.basic.enable_debug_info,
        silent_img2img_fallback=silent_fallback,
        stream_id=stream_id,
        chat_id=chat_id,
        log_prefix=log_prefix,
        source="tool",
    )
