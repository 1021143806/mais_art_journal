"""运行时状态子系统

按聊天流隔离的内存状态：插件开关、模型禁用集合、撤回开关、默认模型、自拍配置覆盖。
重启后归零，长时间不活跃自动清理。
"""

from .runtime_state import RuntimeStateManager, runtime_state

__all__ = ["RuntimeStateManager", "runtime_state"]
