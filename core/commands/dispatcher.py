"""/dr 命令分发器

负责：
- 插件总开关检查（禁用时只允许 /dr on）
- 帮助渲染（rest 空 / rest == "help"）
- 子命令查表分发（admin 权限检查）
- fallback：风格 / 自然语言生成

SDK 2.x 中 host 把 user_id / group_id / group_name / user_nickname 直接平铺进
Command handler 的 kwargs，message 是 RPC 序列化后的 dict。dispatcher 不再
试图从 message 上 getattr 取这些字段，而是由调用方（plugin.handle_dr）从
kwargs 取好后传进来。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..state import runtime_state
from .registry import CommandResult, SubCommandRegistry

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin

logger = logging.getLogger("plugin.mais_art_journal.dispatcher")


@dataclass
class DispatcherContext:
    """一次 /dr 调用的上下文"""

    plugin: "MaisArtPlugin"
    stream_id: str
    chat_id: str
    message: Any
    is_admin: bool
    log_prefix: str
    prefix: str = "/dr"
    user_id: str = ""
    group_id: str = ""
    user_nickname: str = ""
    group_name: str = ""


class CommandDispatcher:
    """单一入口：分发 /dr <head> <tail>"""

    def __init__(self, plugin: "MaisArtPlugin"):
        self.plugin = plugin
        # 强制 import handlers 包以触发 @subcommand 装饰器注册
        from . import handlers  # noqa: F401

    async def dispatch(
        self,
        stream_id: str,
        message: Any,
        rest: str,
        *,
        user_id: str = "",
        group_id: str = "",
        user_nickname: str = "",
        group_name: str = "",
    ) -> CommandResult:
        chat_id = stream_id or ""
        dctx = DispatcherContext(
            plugin=self.plugin,
            stream_id=stream_id,
            chat_id=chat_id,
            message=message,
            is_admin=self._is_admin(user_id),
            log_prefix=self._log_prefix(group_name, user_nickname),
            prefix=self._resolved_prefix(),
            user_id=user_id,
            group_id=group_id,
            user_nickname=user_nickname,
            group_name=group_name,
        )

        head = rest.split(maxsplit=1)[0].lower() if rest else ""

        # 插件总开关例外：禁用时只允许 /dr on
        global_enabled = self.plugin.config.plugin.enabled
        if not runtime_state.is_plugin_enabled(chat_id, global_enabled):
            if head != "on":
                logger.info(f"{dctx.log_prefix} 插件在当前聊天流已禁用")
                return False, "插件已禁用", True

        # 空 / help → 内置帮助（head==help 时无论后面跟什么参数都走帮助）
        if not rest or head == "help":
            from .help_renderer import render_help
            return await render_help(dctx)

        tail = ""
        if " " in rest:
            tail = rest.split(maxsplit=1)[1].strip()

        spec = SubCommandRegistry.get(head)
        if spec:
            if spec.admin and not dctx.is_admin:
                await self.plugin.ctx.send.text("你无权使用此命令", stream_id)
                return False, "无权限", True
            return await spec.handler(self.plugin, dctx, tail)

        # fallback：风格 / 自然语言
        from .generate import handle_generate
        return await handle_generate(self.plugin, dctx, rest)

    # ==================== 上下文辅助 ====================

    def _resolved_prefix(self) -> str:
        """读取 basic.command_prefix，统一带 / 形式；读取失败回退到 /dr"""
        try:
            prefix = (self.plugin.config.basic.command_prefix or "/dr").strip()
        except Exception:
            prefix = "/dr"
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        return prefix

    def _is_admin(self, user_id: str) -> bool:
        if not user_id:
            return False
        try:
            admins = [str(a) for a in (self.plugin.config.basic.admin_users or [])]
        except Exception:
            return False
        return str(user_id) in admins

    def _log_prefix(self, group_name: str, user_nickname: str) -> str:
        if group_name:
            return f"[{group_name}]"
        if user_nickname:
            return f"[{user_nickname} 的 私聊]"
        return f"[MaisArt {self._resolved_prefix()}]"
