"""子命令注册系统

@subcommand 装饰器 + 单例 SubCommandRegistry。
所有 handler 在模块 import 时通过装饰器注册自身。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional, Tuple

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin
    from .dispatcher import DispatcherContext


# /dr 子命令的返回元组：(success, log_message, intercept_message)
CommandResult = Tuple[bool, Optional[str], bool]

SubCommandHandler = Callable[
    ["MaisArtPlugin", "DispatcherContext", str],
    Awaitable[CommandResult],
]


@dataclass(frozen=True)
class SubCommandSpec:
    name: str
    aliases: tuple[str, ...]
    admin: bool
    handler: SubCommandHandler


class SubCommandRegistry:
    """所有 @subcommand 装饰过的处理器集合（单例）"""

    _entries: Dict[str, SubCommandSpec] = {}

    @classmethod
    def register(cls, spec: SubCommandSpec) -> None:
        cls._entries[spec.name.lower()] = spec
        for alias in spec.aliases:
            cls._entries[alias.lower()] = spec

    @classmethod
    def get(cls, head: str) -> Optional[SubCommandSpec]:
        return cls._entries.get(head.lower())

    @classmethod
    def primary_names(cls) -> list[str]:
        """主名（非别名）有序去重列表，用于帮助文案"""
        seen: set = set()
        names: list[str] = []
        for spec in cls._entries.values():
            if spec.name not in seen:
                seen.add(spec.name)
                names.append(spec.name)
        return names


def subcommand(name: str, *, aliases: tuple[str, ...] = (), admin: bool = False):
    """声明一个 /dr 子命令处理器

    Usage:
        @subcommand("list", aliases=("models",), admin=False)
        async def cmd_list(plugin, dctx, args: str) -> CommandResult:
            ...
    """
    def deco(fn: SubCommandHandler) -> SubCommandHandler:
        SubCommandRegistry.register(SubCommandSpec(name, tuple(aliases), admin, fn))
        return fn
    return deco
