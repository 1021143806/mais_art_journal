"""风格注册表

封装 plugin.config.styles 列表的访问。从 v4.1.0 开始 styles 是 List[StylePreset]，
每项含 name / aliases (逗号分隔) / prompt。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin


def _coerce_styles(value: Any) -> List[Dict[str, Any]]:
    """list[StylePreset | dict] 或 dict[name, prompt] 归一化为 list[dict{name, aliases, prompt}]"""
    if isinstance(value, list):
        out: List[Dict[str, Any]] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, dict):
                out.append(dict(item))
            elif hasattr(item, "model_dump"):
                out.append(item.model_dump(mode="python"))
        return out
    if isinstance(value, dict):
        # v4.0.0 旧形态：{name: prompt}
        out: List[Dict[str, Any]] = []
        for name, prompt in value.items():
            out.append({"name": str(name), "aliases": "", "prompt": str(prompt or "")})
        return out
    return []


def _read_styles_items(plugin: "MaisArtPlugin") -> List[Dict[str, Any]]:
    """读取 plugin.config.styles.items 列表，兼容多种历史形态"""
    section = plugin.get_config("styles", None)
    if section is None:
        return []

    # 标准形态：dict 含 items 列表（v4.1.1+ StylesSection）
    if isinstance(section, dict) and "items" in section:
        return _coerce_styles(section.get("items"))

    # v4.1.0 中间形态：直接是 List[StylePreset]
    # v4.0.0 旧形态：Dict[str, str]
    return _coerce_styles(section)


def list_styles(plugin: "MaisArtPlugin") -> List[Dict[str, Any]]:
    """返回所有风格预设的 dict 列表"""
    styles = _read_styles_items(plugin)

    # 兼容 v4.0.0：旧 [style_aliases] 节作为顶层 dict 时，合并到 aliases 字段
    aliases_map = plugin.get_config("style_aliases", None)
    if isinstance(aliases_map, dict) and aliases_map:
        for style in styles:
            n = style.get("name")
            if n and not style.get("aliases") and isinstance(aliases_map.get(n), str):
                style["aliases"] = aliases_map[n]
    return styles


def resolve_style_alias(plugin: "MaisArtPlugin", input_name: str) -> Optional[str]:
    """根据用户输入（英文名或中文别名）解析出实际的风格 name；找不到返回 None"""
    if not input_name:
        return None
    needle = input_name.strip()
    if not needle:
        return None

    for style in list_styles(plugin):
        name = style.get("name") or ""
        if name == needle:
            return name
        aliases = style.get("aliases") or ""
        if isinstance(aliases, str) and aliases.strip():
            alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
            if needle in alias_list:
                return name
    return None


def get_style_prompt(plugin: "MaisArtPlugin", style_name: str) -> Optional[str]:
    """按 name 查找风格 prompt；查不到返回 None"""
    if not style_name:
        return None
    for style in list_styles(plugin):
        if style.get("name") == style_name:
            prompt = style.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
            return None
    return None


def get_style_aliases(plugin: "MaisArtPlugin", style_name: str) -> List[str]:
    """返回某个风格的所有中文别名"""
    for style in list_styles(plugin):
        if style.get("name") == style_name:
            aliases = style.get("aliases") or ""
            if isinstance(aliases, str) and aliases.strip():
                return [a.strip() for a in aliases.split(",") if a.strip()]
            break
    return []
