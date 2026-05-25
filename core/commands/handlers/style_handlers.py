"""/dr 风格管理子命令：styles / style"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...config import get_style_prompt, list_styles, resolve_style_alias
from ..registry import CommandResult, subcommand

if TYPE_CHECKING:
    from ...plugin import MaisArtPlugin
    from ..dispatcher import DispatcherContext

logger = logging.getLogger("plugin.mais_art_journal.cmd.style")


@subcommand("styles", admin=False)
async def cmd_styles(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr styles — 列出所有可用风格"""
    styles = list_styles(plugin)
    if not styles:
        await plugin.ctx.send.text("未找到任何风格配置", dctx.stream_id)
        return False, "无风格配置", True

    lines = ["🎨 可用风格列表：\n"]
    for style in styles:
        name = style.get("name")
        if not name:
            continue
        aliases_raw = (style.get("aliases") or "").strip()
        alias_list = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []
        alias_text = f" (别名: {', '.join(alias_list)})" if alias_list else ""
        lines.append(f"• {name}{alias_text}")
    lines.append("\n💡 使用方法: /dr <风格名>")

    await plugin.ctx.send.text("\n".join(lines), dctx.stream_id)
    return True, "风格列表查询成功", True


@subcommand("style", admin=True)
async def cmd_style(plugin: "MaisArtPlugin", dctx: "DispatcherContext", args: str) -> CommandResult:
    """/dr style <风格名> — 显示风格详情"""
    style_name = (args or "").strip()
    if not style_name:
        await plugin.ctx.send.text("请指定风格名，格式：/dr style <风格名>", dctx.stream_id)
        return False, "缺少风格名参数", True

    actual = resolve_style_alias(plugin, style_name)
    if not actual:
        await plugin.ctx.send.text(
            f"风格 '{style_name}' 不存在，请使用 /dr styles 查看可用风格", dctx.stream_id,
        )
        return False, f"风格 '{style_name}' 不存在", True

    style_prompt = get_style_prompt(plugin, actual)
    if not style_prompt:
        await plugin.ctx.send.text(
            f"风格 '{style_name}' 不存在，请使用 /dr styles 查看可用风格", dctx.stream_id,
        )
        return False, f"风格 '{style_name}' 不存在", True

    # 取该风格的别名
    aliases: list[str] = []
    for style in list_styles(plugin):
        if style.get("name") == actual:
            aliases_raw = (style.get("aliases") or "").strip()
            if aliases_raw:
                aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
            break

    lines = [
        f"🎨 风格详情：{actual}\n",
        "📝 完整提示词：",
        f"{style_prompt}\n",
    ]
    if aliases:
        lines.append(f"🏷️ 别名: {', '.join(aliases)}\n")
    lines.extend([
        "💡 使用方法：",
        f"/dr {style_name}",
        "\n⚠️ 注意：需要先发送一张图片作为输入",
    ])
    await plugin.ctx.send.text("\n".join(lines), dctx.stream_id)
    return True, "风格详情查询成功", True
