"""API 客户端上下文

给 API 客户端一个最小接口集（log_prefix + get_config + proxy）。

设计原则：
- 不依赖 SDK PluginContext，便于独立 / 桩测 / 外部插件调用
- 与 `RequestContext`、`ImageGenerationService` 等业务上下文解耦
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ProxyConfig:
    """代理设置"""

    enabled: bool
    url: str
    timeout: int = 60


class ClientContext:
    """API 客户端依赖"""

    def __init__(
        self,
        *,
        log_prefix: str = "[MaisArt]",
        proxy: Optional[ProxyConfig] = None,
        config_getter: Optional[Callable[[str, Any], Any]] = None,
    ):
        self.log_prefix = log_prefix
        self._proxy = proxy
        self._get = config_getter or (lambda _key, default=None: default)

    def get_config(self, key: str, default: Any = None) -> Any:
        """嵌套 dot-path 配置读取，与旧 BaseAction.get_config 行为一致"""
        try:
            return self._get(key, default)
        except Exception:
            return default

    def get_proxy_config(self) -> Optional[dict]:
        """返回 requests/urllib 友好的代理配置（启用时返回 dict，否则 None）"""
        if not self._proxy or not self._proxy.enabled:
            return None
        return {
            "http": self._proxy.url,
            "https": self._proxy.url,
            "timeout": self._proxy.timeout,
        }


def build_client_context_from_plugin(
    plugin: Any,
    *,
    log_prefix: str = "[MaisArt]",
) -> ClientContext:
    """从 MaisArtPlugin 实例构造 ClientContext

    Args:
        plugin: 持有 .config.proxy / .get_config 的插件实例
        log_prefix: 日志前缀
    """
    proxy_cfg = getattr(getattr(plugin, "config", None), "proxy", None)
    proxy: Optional[ProxyConfig] = None
    if proxy_cfg is not None:
        proxy = ProxyConfig(
            enabled=bool(getattr(proxy_cfg, "enabled", False)),
            url=str(getattr(proxy_cfg, "url", "http://127.0.0.1:7890") or "http://127.0.0.1:7890"),
            timeout=int(getattr(proxy_cfg, "timeout", 60) or 60),
        )

    getter = getattr(plugin, "get_config", None)
    if not callable(getter):
        getter = lambda _k, default=None: default

    return ClientContext(log_prefix=log_prefix, proxy=proxy, config_getter=getter)


def build_client_context_from_extra(
    extra_config: Optional[dict],
    *,
    log_prefix: str = "[standalone]",
) -> ClientContext:
    """从 generate_image_standalone 的 extra_config 字典构造 ClientContext

    extra_config 形如 {"proxy": {"enabled": True, "url": "...", "timeout": 60}}，
    扁平 dot-path（"proxy.enabled"）也会被 get_config 处理。
    """
    proxy: Optional[ProxyConfig] = None
    if isinstance(extra_config, dict):
        proxy_section = extra_config.get("proxy")
        if isinstance(proxy_section, dict) and proxy_section.get("enabled"):
            proxy = ProxyConfig(
                enabled=True,
                url=str(proxy_section.get("url", "http://127.0.0.1:7890") or "http://127.0.0.1:7890"),
                timeout=int(proxy_section.get("timeout", 60) or 60),
            )

    def _flat_get(key: str, default: Any = None) -> Any:
        obj: Any = extra_config or {}
        for part in key.split("."):
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                return default
            if obj is None:
                return default
        return obj

    return ClientContext(log_prefix=log_prefix, proxy=proxy, config_getter=_flat_get)
