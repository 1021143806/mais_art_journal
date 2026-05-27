"""/dr 开关类子命令：on / off / model / recall"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...config import get_model_config
from ...state import runtime_state
from ..registry import CommandResult, subcommand

if TYPE_CHECKING:
    from ...plugin import MaisArtPlugin
    from ..dispatcher import DispatcherContext

logger = logging.getLogger("plugin.mais_art_journal.cmd.toggle")


@subcommand("on", admin=True)
async def cmd_on(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr on — 在当前聊天流启用插件（dispatcher 已确保禁用状态下也可执行）"""
    runtime_state.set_plugin_enabled(dctx.chat_id, True)
    await plugin.ctx.send.text("已启用", dctx.stream_id)
    return True, "插件已启用", True


@subcommand("off", admin=True)
async def cmd_off(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr off — 在当前聊天流禁用插件"""
    runtime_state.set_plugin_enabled(dctx.chat_id, False)
    await plugin.ctx.send.text("已禁用", dctx.stream_id)
    return True, "插件已禁用", True


@subcommand("model", admin=True)
async def cmd_model(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr model on|off <模型ID>"""
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await plugin.ctx.send.text(f"格式：{dctx.prefix} model on|off <模型ID>", dctx.stream_id)
        return False, "参数不足", True

    action, model_id = parts[0].lower(), parts[1].strip()
    if action not in ("on", "off"):
        await plugin.ctx.send.text(f"格式：{dctx.prefix} model on|off <模型ID>", dctx.stream_id)
        return False, "无效的操作", True

    if not get_model_config(plugin, model_id):
        await plugin.ctx.send.text(f"模型 '{model_id}' 不存在", dctx.stream_id)
        return False, "模型不存在", True

    enabled = action == "on"
    runtime_state.set_model_enabled(dctx.chat_id, model_id, enabled)
    status = "启用" if enabled else "禁用"
    await plugin.ctx.send.text(f"{model_id} 已{status}", dctx.stream_id)
    return True, f"模型{status}成功", True


@subcommand("recall", admin=True)
async def cmd_recall(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr recall on|off <模型ID>"""
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await plugin.ctx.send.text(f"格式：{dctx.prefix} recall on|off <模型ID>", dctx.stream_id)
        return False, "参数不足", True

    action, model_id = parts[0].lower(), parts[1].strip()
    if action not in ("on", "off"):
        await plugin.ctx.send.text(f"格式：{dctx.prefix} recall on|off <模型ID>", dctx.stream_id)
        return False, "无效的操作", True

    if not get_model_config(plugin, model_id):
        await plugin.ctx.send.text(f"模型 '{model_id}' 不存在", dctx.stream_id)
        return False, "模型不存在", True

    enabled = action == "on"
    runtime_state.set_recall_enabled(dctx.chat_id, model_id, enabled)
    status = "启用" if enabled else "禁用"
    await plugin.ctx.send.text(f"{model_id} 撤回已{status}", dctx.stream_id)
    return True, f"撤回{status}成功", True
