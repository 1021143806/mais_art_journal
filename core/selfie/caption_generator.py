"""配文生成器

为自拍图片生成配文：
- 基于当前活动/日程 + MaiBot 完整人设（昵称 / 人设描述 / 兴趣 / 表达风格）自然生成
- 通过 ctx.llm.generate 调用主 LLM
- 通过 ctx.config.get 读取主程序 bot.nickname / personality.* 字段
- 生成失败返回空字符串，由调用方决定是否发布

字段对齐说明：
    与 autonomous_planning_plugin v4 的 ``_prefetch_bot_profile`` 字段集保持一致
    （personality / reply_style / interest / bot_name），并保留本插件特色的
    ``multiple_reply_style`` + ``multiple_probability`` 随机替换。
"""

import datetime
import logging
import random
from typing import TYPE_CHECKING, Dict

from .schedule_provider import ActivityInfo

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

logger = logging.getLogger("plugin.mais_art_journal.caption")


async def _get_reply_style(ctx: "PluginContext") -> str:
    """获取表达风格，按概率走 multiple_reply_style 随机替换"""
    reply_style = await ctx.config.get("personality.reply_style", "")

    multi_styles = await ctx.config.get("personality.multiple_reply_style", [])
    probability_raw = await ctx.config.get("personality.multiple_probability", 0.0)
    try:
        probability = float(probability_raw or 0.0)
    except (TypeError, ValueError):
        probability = 0.0

    if multi_styles and probability > 0 and random.random() < probability:
        try:
            reply_style = random.choice(list(multi_styles))
        except Exception:
            pass

    return str(reply_style or "")


async def _get_bot_profile(ctx: "PluginContext") -> Dict[str, str]:
    """统一拉取 bot 完整人设字段

    对齐 autonomous_planning_plugin v4 ``_prefetch_bot_profile``：
        ``bot.nickname`` / ``personality.personality`` / ``personality.interest`` /
        ``personality.reply_style``（含 multiple_reply_style 随机）。

    全部字段缺失时不抛异常，由调用方决定是否生成配文。
    """
    try:
        bot_name = await ctx.config.get("bot.nickname", "")
        personality = await ctx.config.get("personality.personality", "")
        interest = await ctx.config.get("personality.interest", "")
        reply_style = await _get_reply_style(ctx)
    except Exception as exc:
        logger.warning(f"拉取 bot_profile 失败，使用空人设: {exc}")
        bot_name = personality = interest = reply_style = ""

    return {
        "bot_name": str(bot_name or ""),
        "personality": str(personality or ""),
        "interest": str(interest or ""),
        "reply_style": str(reply_style or ""),
    }


def _build_caption_prompt(
    activity_info: ActivityInfo,
    bot_profile: Dict[str, str],
) -> str:
    """构建配文生成 prompt（覆盖 bot 昵称/人设/兴趣/表达风格四元组）"""
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")

    bot_name = bot_profile.get("bot_name", "").strip() or "麦麦"
    personality = bot_profile.get("personality", "").strip() or "一个有趣的人"
    reply_style = bot_profile.get("reply_style", "").strip() or "自然亲切"
    interest = bot_profile.get("interest", "").strip()

    self_intro_lines = [
        f"你是 {bot_name}。",
        f"你的人设：{personality}",
    ]
    if interest:
        self_intro_lines.append(f"你的兴趣偏好：{interest}")
    self_intro_lines.append(f"你的说话风格：{reply_style}")
    self_intro = "\n".join(self_intro_lines)

    prompt = f"""{self_intro}

现在是{time_str}，你当前的状态：{activity_info.description}

你刚拍了一张自拍，准备发到社交媒体上，请写一段配文。

要求：
1. 用你自己的口吻和说话习惯来写，保持你平时的语气
2. 配文应该和你当前正在做的事有关联
3. 可以适当结合你的兴趣偏好（如果合适的话），让配文更有"你"的味道
4. 简短自然，像平时发朋友圈/说说一样（15-50字）
5. 可以适当用语气词、颜文字，但不要刻意堆砌
6. 不要用 hashtag、不要 @ 任何人
7. 不要在配文里自报姓名（"我是XXX"这种），昵称只是你自我认知的一部分
8. 只输出配文内容，不要输出其他任何东西

配文："""

    return prompt


async def generate_caption(
    ctx: "PluginContext",
    activity_info: ActivityInfo,
    llm_task: str = "utils",
) -> str:
    """为自拍生成配文

    基于当前活动 + bot 完整人设（昵称/人设/兴趣/表达风格）由 LLM 自然生成。
    生成失败返回空字符串。

    Args:
        ctx: PluginContext
        activity_info: 当前活动信息
        llm_task: 调用 ctx.llm.generate 时使用的任务名

    Returns:
        配文文本，失败时返回空字符串
    """
    bot_profile = await _get_bot_profile(ctx)

    try:
        prompt = _build_caption_prompt(activity_info, bot_profile)

        result = await ctx.llm.generate(
            prompt=prompt,
            model=llm_task,
            temperature=0.85,
            max_tokens=8192,
        )

        success = False
        caption_raw = ""
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            caption_raw = str(result.get("response") or result.get("content") or "")

        if not (success and caption_raw):
            logger.warning("LLM 返回空响应，配文生成失败")
            return ""

        # 清理输出
        caption = caption_raw.strip().strip('"').strip("'").strip("「").strip("」")
        # 限制长度
        if len(caption) > 80:
            caption = caption[:77] + "..."
        if len(caption) < 2:
            logger.warning("LLM 返回配文过短，视为失败")
            return ""

        # 完整性检查：配文应以标点或表情结尾，否则可能被截断
        valid_endings = ("。", "！", "？", "~", "～", "…", ")", "）",
                         "」", "'", '"', "♪", "☆", "♡",
                         "呢", "哦", "啊", "呀", "吧", "了", "嘛", "哈", "噢", "耶")
        if len(caption) >= 8 and not caption.endswith(valid_endings):
            # 尝试截断到最后一个完整句子
            for punct in ("。", "！", "？", "~", "～", "…"):
                last_pos = caption.rfind(punct)
                if last_pos > 0:
                    caption = caption[:last_pos + 1]
                    break

        bot_name_display = bot_profile.get("bot_name") or "<未配置 bot.nickname>"
        logger.info(f"LLM 生成配文（bot={bot_name_display}）: {caption}")
        return caption

    except Exception as e:
        logger.error(f"LLM 配文生成失败: {e}")
        return ""
