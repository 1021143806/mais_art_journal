"""/dr selfie 子命令：日程开关 + 风格切换"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...state import runtime_state
from ..registry import CommandResult, subcommand

if TYPE_CHECKING:
    from ...plugin import MaisArtPlugin
    from ..dispatcher import DispatcherContext

logger = logging.getLogger("plugin.mais_art_journal.cmd.selfie")

_VALID_STYLES = {"standard", "mirror", "photo"}
_STYLE_LABELS = {"standard": "标准自拍", "mirror": "对镜自拍", "photo": "第三人称照片"}


@subcommand("selfie", admin=True)
async def cmd_selfie(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr selfie on|off|standard|mirror|photo"""
    action = (args or "").strip().lower()

    if action in ("on", "off"):
        enabled = action == "on"
        runtime_state.set_selfie_schedule_enabled(dctx.chat_id, enabled)
        status = "启用" if enabled else "禁用"
        await plugin.ctx.send.text(f"自拍日程增强已{status}", dctx.stream_id)
        return True, f"自拍日程增强{status}成功", True

    if action in _VALID_STYLES:
        runtime_state.set_selfie_style(dctx.chat_id, action)
        label = _STYLE_LABELS[action]
        await plugin.ctx.send.text(f"自拍风格已切换为: {label}（{action}）", dctx.stream_id)
        return True, f"自拍风格切换为{action}", True

    await plugin.ctx.send.text(
        f"格式：{dctx.prefix} selfie on|off（日程增强）或 "
        f"{dctx.prefix} selfie standard|mirror|photo（自拍风格）",
        dctx.stream_id,
    )
    return False, "参数无效", True
