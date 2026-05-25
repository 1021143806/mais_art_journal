"""自拍提示词构造器（独立模块）

聚合：
- 三种自拍风格的手部动作池
- 风格场景模板 / 负面提示词扩展
- LLM 生成手部动作（按风格约束）
- sanitize（屏蔽与风格冲突的手机/双手关键词）
- 公共 API：build(...) 手动自拍主入口
                build_for_activity(...) 自动自拍主入口
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..utils.shared_constants import (
    ANTI_DUAL_PHONE_PROMPT,
    PHOTO_NO_PHONE_PROMPT,
    SELFIE_HAND_NEGATIVE,
)
from .prompt_optimizer import optimize_prompt
from .scene_action_llm import build_scene_llm_prompt, generate_scene_with_llm

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

    from ..selfie.schedule_provider import ActivityInfo

logger = logging.getLogger("plugin.mais_art_journal.selfie_builder")


# ==================== 三种风格的手部动作池 ====================

_STANDARD_HAND_ACTIONS: List[str] = [
    "peace sign with one hand, v sign",
    "waving with one hand, friendly gesture",
    "thumbs up with one hand, positive gesture",
    "finger heart with one hand, cute gesture",
    "touching own cheek gently with one hand, soft expression",
    "hand near chin, thinking pose",
    "playing with hair with one hand, casual",
    "one hand on hip, confident pose",
    "adjusting hair with one hand, elegant gesture",
    "resting chin on one hand, relaxed",
    "one finger on lips, secretive",
    "one hand on chest, gentle",
    "tucking hair behind ear with one hand, elegant",
    "touching necklace with one hand, delicate gesture",
    "one hand near eye level, cute gesture",
    "cat paw gesture with one hand, playful",
    "saluting with one hand, playful military pose",
    "one hand covering mouth slightly, shy smile",
    "blowing kiss with one hand, romantic",
    "index finger pointing up with one hand, idea pose",
    "cupping own cheek with one hand, adorable",
    "one hand resting on collarbone, graceful",
    "pinching own cheek with one hand, playful",
]

_MIRROR_HAND_ACTIONS: List[str] = [
    "one hand on hip, confident mirror pose",
    "one hand in hair, adjusting hairstyle in mirror",
    "one hand on waist, model pose",
    "fixing collar with one hand, neat appearance",
    "adjusting earring with one hand, elegant detail",
    "one hand touching shoulder, graceful",
    "one hand behind head, relaxed mirror pose",
    "one hand on thigh, standing pose",
    "one hand resting at side, natural",
    "one hand lightly touching mirror frame, playful",
    "fixing skirt with one hand, adjusting outfit",
    "one hand on bag strap, casual",
    "brushing bangs aside with one hand, stylish",
    "one hand in pocket, cool pose",
    "one hand on chin, thoughtful mirror pose",
    "adjusting glasses with one hand, intellectual",
    "checking watch with one hand, elegant gesture",
    "holding strand of hair with one hand, delicate",
    "one hand near face, model pose",
    "touching hat brim with one hand, fashionable",
]

_PHOTO_HAND_ACTIONS: List[str] = [
    "standing naturally with arms relaxed at sides, calm posture",
    "walking casually with natural arm swing, relaxed movement",
    "wind blowing through hair, one hand gently touching hair, dynamic",
    "arms hanging naturally at sides, standing pose",
    "holding coffee cup with both hands, cozy cafe scene",
    "one hand lightly holding bag strap, casual walking pose",
    "carrying small bag in one hand, natural walk",
    "leaning on railing with both arms resting, relaxed",
    "sitting naturally with hands on lap, relaxed posture",
    "holding hat brim with one hand, windy day",
    "holding flower bouquet with both hands, smelling gently",
    "one hand shielding eyes from sun, looking into distance",
    "carrying tote bag in one hand, casual stroll",
    "holding book to chest with both hands, scholarly",
    "waving at camera with one hand, candid moment",
    "leaning against wall with arms crossed loosely, relaxed",
    "holding umbrella with one hand, rainy atmosphere",
    "looking back over shoulder with natural arm position, candid",
    "sitting on bench with legs crossed, hands resting on knee, elegant",
    "hands clasped in front, gentle standing pose",
]


# ==================== 风格场景模板 / 负面扩展 ====================

_STYLE_SCENE_PROMPTS: Dict[str, str] = {
    "standard": (
        "(selfie:1.7), (front camera view:1.6), (POV selfie angle:1.6), "
        "(one hand holding phone outside frame:1.9), (phone completely out of frame:1.8), (phone not visible:1.8), "
        "(arm extended toward camera off-screen:1.7), (camera held at arm's length:1.6), "
        "(looking directly at camera:1.5), (slight high angle:1.4), "
        "(upper body shot:1.4), (cowboy shot:1.3), "
        "(centered face composition:1.5), (close-up portrait:1.3), "
        "(phone camera perspective:1.4), (intimate framing:1.3), "
        "(casual selfie atmosphere:1.3), (personal photo:1.2)"
    ),
    "mirror": (
        "(mirror selfie:1.8), (full body reflection in mirror:1.7), "
        "(one hand holding phone visible in mirror reflection:1.8), (phone screen glowing in mirror:1.5), "
        "(natural standing pose:1.5), (relaxed posture:1.4), "
        "(looking at phone screen in mirror:1.4), (casual mirror pose:1.4), "
        "(indoor mirror scene:1.4), (bathroom mirror:1.3), (bedroom full-length mirror:1.3), "
        "(mirror frame visible:1.3), (reflection composition:1.5), "
        "(standing naturally in front of mirror:1.5), (full body visible:1.4), "
        "(mirror background:1.3), (everyday mirror moment:1.3)"
    ),
    "photo": (
        "(third-person photograph:1.8), (external camera viewpoint:1.7), "
        "(professional photo composition:1.5), (candid shot:1.5), "
        "(photographer taking photo:1.6), (subject not holding camera:1.8), "
        "(no phone in hands:1.9), (no phone visible anywhere:1.8), (phone-free hands:1.8), "
        "(natural relaxed pose:1.6), (organic body language:1.5), "
        "(full body shot:1.4), (environmental portrait:1.4), "
        "(looking at camera or away:1.3), (outdoor or indoor scene:1.3), "
        "(depth of field:1.4), (bokeh background:1.3), "
        "(lifestyle photography:1.4), (natural moment:1.4), "
        "(photoshoot atmosphere:1.3), (portrait photography:1.3)"
    ),
}

_STYLE_NEGATIVE_EXTRAS: Dict[str, List[str]] = {
    "standard": [
        ANTI_DUAL_PHONE_PROMPT,
        "(mirror selfie:1.6), (reflection in mirror:1.6), (phone visible in frame:1.8), (phone in shot:1.8), "
        "(holding phone visibly:1.8), (phone in hand visible:1.8), (device in frame:1.7), "
        "(third-person shot:1.6), (full body shot:1.5), "
        "(both hands in frame:1.7), (two hands visible:1.7), (hands together:1.7), "
        "(professional photography:1.4), (external camera:1.5), (depth of field:1.4), "
        "(mirror:1.5), (reflection:1.5), (full-length mirror:1.5), "
        "(phone screen visible:1.7), (smartphone in picture:1.8)"
    ],
    "mirror": [
        "(front camera view:1.5), (POV selfie:1.5), (arm extended toward camera:1.6), "
        "(third-person shot:1.6), (external photographer:1.5), "
        "(phone off-screen:1.5), (invisible phone:1.5), (phone outside mirror:1.6), "
        "(close-up face only:1.4), (upper body only:1.4), "
        "(both hands free:1.7), (no phone in hand:1.6), (hands together:1.7), (two-hand gesture:1.7), "
        "(stiff pose:1.5), (unnatural stance:1.5), (awkward posture:1.5), "
        "(outdoor scene:1.4), (no mirror:1.6), (without mirror:1.6)"
    ],
    "photo": [
        PHOTO_NO_PHONE_PROMPT,
        "(selfie:1.8), (mirror selfie:1.8), (front camera view:1.7), (POV selfie:1.7), "
        "(arm extended toward camera:1.7), (selfie angle:1.7), (high angle selfie:1.6), "
        "(mirror reflection:1.7), (phone in hand:1.9), (holding phone:1.9), (holding device:1.9), "
        "(phone visible:1.9), (smartphone in shot:1.9), (device in hands:1.9), "
        "(selfie stick:1.8), (taking selfie:1.8), (self-portrait:1.6), "
        "(phone camera perspective:1.7), (arm reaching to camera:1.7)"
    ],
}


# ==================== sanitize patterns ====================

_PHONE_LIKE_PATTERN = re.compile(
    r"\b(phone|smartphone|cellphone|mobile(?:\s+phone)?|device|camera|iphone|android|selfie(?:\s+stick)?)\b",
    flags=re.IGNORECASE,
)
_MULTI_HAND_PATTERN = re.compile(
    r"\b(both hands?|two hands?|hands\b|two-handed|interlocked fingers|crossed arms?|arms?\s+(?:stretched|spread|raised|wide|extended))\b",
    flags=re.IGNORECASE,
)
_SELFIE_POSE_PATTERN = re.compile(
    r"\b(arm extended|reaching toward camera|toward camera|selfie pose|taking selfie)\b",
    flags=re.IGNORECASE,
)
_STYLE_ACTION_FALLBACKS: Dict[str, str] = {
    "standard": "one hand resting near face, gentle expression",
    "mirror": "one hand on hip, natural mirror standing pose",
    "photo": "standing naturally with hands relaxed at sides, calm posture",
}


# ==================== 公开工具函数 ====================

def get_hand_actions_for_style(selfie_style: str) -> List[str]:
    if selfie_style == "mirror":
        return _MIRROR_HAND_ACTIONS
    if selfie_style == "photo":
        return _PHOTO_HAND_ACTIONS
    return _STANDARD_HAND_ACTIONS


def get_scene_prompt_for_style(selfie_style: str = "standard") -> str:
    return _STYLE_SCENE_PROMPTS.get(selfie_style, _STYLE_SCENE_PROMPTS["standard"])


def sanitize_hand_action_for_style(hand_action: Optional[str], selfie_style: str = "standard") -> Optional[str]:
    """按自拍风格清洗手部动作，避免注入冲突的持机姿态"""
    if not hand_action:
        return hand_action
    cleaned = hand_action.strip()
    if not cleaned:
        return None

    if selfie_style in ("standard", "mirror"):
        if _PHONE_LIKE_PATTERN.search(cleaned) or _MULTI_HAND_PATTERN.search(cleaned):
            return _STYLE_ACTION_FALLBACKS[selfie_style]
        return cleaned

    if selfie_style == "photo":
        if _PHONE_LIKE_PATTERN.search(cleaned) or _SELFIE_POSE_PATTERN.search(cleaned):
            return _STYLE_ACTION_FALLBACKS[selfie_style]
        return cleaned

    return cleaned


def build_hand_prompt_for_style(hand_action: Optional[str], selfie_style: str = "standard") -> Optional[str]:
    """将动作描述包装成贴合自拍模式的提示词片段"""
    cleaned = sanitize_hand_action_for_style(hand_action, selfie_style)
    if not cleaned:
        return None

    if selfie_style == "standard":
        return (
            f"(visible free hand: {cleaned}:1.6), "
            "(one hand holding phone completely outside frame:1.9), "
            "(phone held off-screen:1.9), (phone not visible anywhere:1.8), "
            "(only one hand visible in frame:1.8), "
            "(single hand gesture:1.7), "
            "(other arm extended holding phone beyond frame edge:1.7), "
            "(arm reaching out of frame:1.6), "
            "(no phone in picture:1.8), (device outside shot:1.7)"
        )
    if selfie_style == "mirror":
        return (
            f"(free hand: {cleaned}:1.6), "
            "(one hand holding phone in mirror reflection:1.8), "
            "(phone visible only in mirror:1.7), "
            "(natural relaxed posture:1.5), "
            "(casual standing pose:1.5), "
            "(other hand posing naturally:1.5), "
            "(single free hand gesture:1.5), "
            "(comfortable mirror stance:1.4)"
        )
    return (
        f"(natural pose: {cleaned}:1.5), "
        "(hands completely free from devices:1.9), "
        "(no phone in hands:1.9), "
        "(no phone visible anywhere in frame:1.9), "
        "(phone-free composition:1.8), "
        "(relaxed natural body language:1.5), "
        "(organic movement:1.4), "
        "(third-person perspective:1.6), "
        "(no selfie pose:1.8), (no self-photography:1.7)"
    )


def get_negative_prompt_for_style(selfie_style: str, base_negative: str = "") -> str:
    """组装风格专属的负面提示词"""
    parts: List[str] = []
    if base_negative:
        parts.append(base_negative)
    parts.append(SELFIE_HAND_NEGATIVE)
    parts.extend(_STYLE_NEGATIVE_EXTRAS.get(selfie_style, _STYLE_NEGATIVE_EXTRAS["standard"]))
    return ", ".join(parts)


# ==================== LLM 生成手部动作（手动自拍场景） ====================

async def generate_hand_action_with_llm(
    ctx: "PluginContext",
    description: str,
    selfie_style: str = "standard",
    llm_task: str = "utils",
) -> Optional[str]:
    """复用场景 LLM prompt，只取 action 字段"""
    try:
        system_prompt = build_scene_llm_prompt(selfie_style)
        prompt = f"{system_prompt}\n\nActivity: {description}"

        result = await ctx.llm.generate(prompt=prompt, model=llm_task, temperature=0.7, max_tokens=8192)
        success, response, model_name = False, "", ""
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            response = str(result.get("response") or result.get("content") or "")
            model_name = str(result.get("model") or result.get("model_name") or "")

        if not (success and response):
            return None

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        scene = json.loads(cleaned)
        action = scene.get("action")
        if not isinstance(action, str) or not action.strip():
            return None

        logger.info(f"LLM 手部动作生成成功 (模型: {model_name}): {action[:60]}")
        return action.strip()
    except json.JSONDecodeError as e:
        logger.warning(f"手部动作 JSON 解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"手部动作 LLM 生成异常: {e}")
        return None


# ==================== 主入口 ====================

@dataclass
class SelfiePromptResult:
    prompt: str
    negative_prompt: str


def _dedupe_keywords(text: str) -> str:
    """按英文逗号去重关键词，保持首次出现顺序"""
    seen: set = set()
    unique: List[str] = []
    for kw in text.split(","):
        kw_clean = kw.strip()
        if not kw_clean:
            continue
        kw_lower = kw_clean.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique.append(kw_clean)
    return ", ".join(unique)


def _description_long_enough(description: str) -> bool:
    """描述是否足够具体，足以触发 LLM 生成手部动作"""
    desc_clean = description.strip().strip(",. 、，。")
    if any("一" <= c <= "鿿" for c in desc_clean):
        return len(desc_clean) > 3
    return len(desc_clean) > 6


async def build(
    *,
    ctx: "PluginContext",
    selfie_style: str,
    description: str,
    free_hand_action: str = "",
    activity_scene: Optional[Dict[str, Any]] = None,
    bot_appearance: str = "",
    base_negative: str = "",
    log_prefix: str = "[selfie_builder]",
    run_scene_optimizer: bool = True,
    llm_task: str = "utils",
) -> SelfiePromptResult:
    """手动自拍主入口

    1. 用 scene_only=True 优化用户描述（保留场景，不破坏角色外观）
    2. 选 hand_action：free_hand_action > activity_scene.hand_action > LLM > 动作池
    3. sanitize_hand_action_for_style
    4. 拼装最终 prompt 并去重
    5. 计算负面提示词
    """
    # 1. 场景优化（仅在描述非空且优化器启用时）
    if run_scene_optimizer and description.strip():
        ok, optimized = await optimize_prompt(
            ctx, description, log_prefix=log_prefix, scene_only=True, llm_task=llm_task,
        )
        if ok and optimized:
            logger.info(f"{log_prefix} 自拍场景提示词优化完成: {optimized[:80]}...")
            description = optimized

    # 2. 选择手部动作
    if free_hand_action:
        hand_action: Optional[str] = free_hand_action
        logger.info(f"{log_prefix} 使用 LLM 给出的 free_hand_action: {free_hand_action}")
    elif activity_scene and activity_scene.get("hand_action"):
        hand_action = activity_scene["hand_action"]
        logger.info(f"{log_prefix} 使用日程活动动作: {hand_action}")
    else:
        hand_action = None
        if _description_long_enough(description):
            try:
                hand_action = await generate_hand_action_with_llm(
                    ctx, description, selfie_style, llm_task=llm_task,
                )
                if hand_action:
                    logger.info(f"{log_prefix} LLM 生成 {selfie_style} 手部动作: {hand_action[:60]}")
            except Exception as e:
                logger.debug(f"{log_prefix} LLM 手部动作生成失败: {e}")
        if not hand_action:
            hand_action = random.choice(get_hand_actions_for_style(selfie_style))
            logger.info(f"{log_prefix} 动作池随机 {selfie_style} 风格: {hand_action}")

    hand_action = sanitize_hand_action_for_style(hand_action, selfie_style)
    hand_prompt = build_hand_prompt_for_style(hand_action, selfie_style)

    # 3. 拼装
    parts: List[str] = [
        "(1girl:1.5), (solo:1.6), (perfect hands:1.5), (correct anatomy:1.4), "
        "(5 fingers:1.4), (anatomically correct hands:1.4), "
        "(normal hands:1.4), (well-formed hands:1.4)"
    ]
    if bot_appearance:
        parts.append(bot_appearance)
    if activity_scene:
        if activity_scene.get("expression"):
            parts.append(f"({activity_scene['expression']}:1.2)")
        if activity_scene.get("lighting"):
            parts.append(activity_scene["lighting"])
    if hand_prompt:
        parts.append(hand_prompt)
    if activity_scene and activity_scene.get("environment"):
        parts.append(activity_scene["environment"])
    parts.append(get_scene_prompt_for_style(selfie_style))
    if description:
        parts.append(description)

    prompt = _dedupe_keywords(", ".join(parts))
    negative_prompt = get_negative_prompt_for_style(selfie_style, base_negative)

    logger.info(f"{log_prefix} 自拍最终提示词: {prompt[:200]}...")
    logger.info(f"{log_prefix} 自拍负面提示词: {negative_prompt[:150]}...")
    return SelfiePromptResult(prompt=prompt, negative_prompt=negative_prompt)


async def build_for_activity(
    *,
    ctx: "PluginContext",
    activity_info: "ActivityInfo",
    selfie_style: str = "standard",
    bot_appearance: str = "",
    base_negative: str = "",
    log_prefix: str = "[auto_selfie_builder]",
    llm_task: str = "utils",
) -> Optional[SelfiePromptResult]:
    """自动自拍主入口

    完全依赖 LLM 生成场景；LLM 失败 → 返回 None（调用方应跳过本次自拍）
    """
    scene = await generate_scene_with_llm(ctx, activity_info, selfie_style, llm_task=llm_task)
    if not scene:
        logger.warning(f"{log_prefix} LLM 场景生成失败，取消本次自拍提示词生成")
        return None

    hand_action = sanitize_hand_action_for_style(scene.get("hand_action"), selfie_style)
    hand_prompt = build_hand_prompt_for_style(hand_action, selfie_style)

    parts: List[str] = [
        "(1girl:1.5), (solo:1.6), (perfect hands:1.5), (correct anatomy:1.4), "
        "(5 fingers:1.4), (anatomically correct hands:1.4), "
        "(normal hands:1.4), (well-formed hands:1.4)"
    ]
    if bot_appearance:
        parts.append(bot_appearance)
    if scene.get("expression"):
        parts.append(f"({scene['expression']}:1.2)")
    if hand_prompt:
        parts.append(hand_prompt)
    if scene.get("environment"):
        parts.append(scene["environment"])
    if scene.get("lighting"):
        parts.append(scene["lighting"])
    parts.append(get_scene_prompt_for_style(selfie_style))

    prompt = _dedupe_keywords(", ".join([p for p in parts if p and p.strip()]))
    negative_prompt = get_negative_prompt_for_style(selfie_style, base_negative)

    logger.info(f"{log_prefix} 自动自拍提示词: {prompt[:150]}...")
    return SelfiePromptResult(prompt=prompt, negative_prompt=negative_prompt)
