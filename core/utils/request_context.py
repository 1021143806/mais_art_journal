"""请求级上下文适配器

替代旧版 BaseCommand 在 helper 模块中的 self.action 角色：
- 把 plugin.get_plugin_config_data() 的嵌套字典包装为 get_config(key, default)
- 暴露 plugin.ctx（PluginContext）和 log_prefix
- 提供 ImageProcessor 等 helper 期望的 message 字段

每次 Tool/Command 触发时由插件入口构造，传给 ImageProcessor/CacheManager/BaseApiClient 等 helper。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from maibot_sdk import MaiBotPlugin
    from maibot_sdk.context import PluginContext


class RequestContext:
    """组件请求上下文（替代旧 BaseCommand 实例）"""

    def __init__(
        self,
        plugin: "MaiBotPlugin",
        *,
        log_prefix: str = "",
        command_message: Any = None,
        chat_id: str = "",
        stream_id: str = "",
    ):
        self.plugin = plugin
        self.log_prefix = log_prefix
        self.message = command_message
        self.chat_id = chat_id
        self.stream_id = stream_id or chat_id

    @property
    def ctx(self) -> "PluginContext":
        return self.plugin.ctx

    def get_config(self, key: str, default: Any = None) -> Any:
        """嵌套 dot-path 配置读取，兼容旧 BaseAction.get_config 行为"""
        config = self.plugin.get_plugin_config_data()
        parts = key.split(".")
        current: Any = config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current if current is not None else default
