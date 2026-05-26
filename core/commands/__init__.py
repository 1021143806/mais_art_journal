"""/dr 命令注册与分发"""

from .dispatcher import CommandDispatcher, DispatcherContext
from .registry import CommandResult, SubCommandRegistry, SubCommandSpec, subcommand

__all__ = [
    "CommandDispatcher",
    "DispatcherContext",
    "SubCommandRegistry",
    "SubCommandSpec",
    "CommandResult",
    "subcommand",
]
