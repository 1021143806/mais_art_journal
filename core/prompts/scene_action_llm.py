"""场景 LLM 生成 + 确定性映射兜底（自动自拍 + 手动自拍日程增强共用）"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

    from ..selfie.schedule_provider import ActivityInfo

logger = logging.getLogger("plugin.mais_art_journal.scene_llm")


# ==================== 确定性映射（LLM 失败时的兜底） ====================

ACTIVITY_ACTIONS: Dict[str, str] = {
    "sleeping": "lying down, hugging pillow, cozy",
    "waking_up": "stretching, yawning, messy hair",
    "eating": "holding chopsticks, eating",
    "working": "typing on laptop, focused",
    "studying": "holding book, reading",
    "exercising": "stretching, athletic, holding water bottle",
    "relaxing": "lying on couch, relaxed, listening to music",
    "socializing": "making peace sign, happy, laughing",
    "commuting": "holding bag, walking, wearing earbuds",
    "hobby": "holding camera, creative",
    "self_care": "applying makeup, mirror",
    "other": "standing, casual pose, natural",
}

ACTIVITY_ENVIRONMENTS: Dict[str, str] = {
    "sleeping": "bedroom, dim lighting, cozy atmosphere, bed",
    "waking_up": "bedroom, morning light, curtains, warm sunlight",
    "eating": "dining room, table setting",
    "working": "office desk, computer screen",
    "studying": "library, bookshelves, desk lamp",
    "exercising": "gym, fitness equipment",
    "relaxing": "living room, sofa, afternoon sun",
    "socializing": "outdoor cafe, bright atmosphere",
    "commuting": "city street, urban",
    "hobby": "art studio, creative space",
    "self_care": "bathroom, mirror, vanity",
    "other": "indoor, natural lighting",
}

ACTIVITY_EXPRESSIONS: Dict[str, str] = {
    "sleeping": "peaceful expression, closed eyes",
    "waking_up": "drowsy expression, half-open eyes",
    "eating": "happy expression, enjoying food",
    "working": "focused expression, serious",
    "studying": "focused, thoughtful expression",
    "exercising": "energetic expression, determined",
    "relaxing": "relaxed smile, content",
    "socializing": "bright smile, happy",
    "commuting": "calm expression",
    "hobby": "excited, passionate",
    "self_care": "gentle smile, self-care",
    "other": "natural smile",
}

ACTIVITY_LIGHTING: Dict[str, str] = {
    "sleeping": "dim warm light, night lamp",
    "waking_up": "soft morning light, golden hour",
    "eating": "warm indoor lighting",
    "working": "office lighting, even illumination",
    "studying": "desk lamp, focused light",
    "exercising": "bright natural light",
    "relaxing": "soft afternoon light, warm ambient light",
    "socializing": "bright cheerful lighting",
    "commuting": "morning sunlight",
    "hobby": "creative studio lighting",
    "self_care": "bathroom lighting, mirror reflection",
    "other": "natural lighting",
}


# ==================== LLM 场景生成 prompt（按风格约束） ====================

_SCENE_LLM_PROMPT_BASE = """You are a selfie scene tag generator for anime image generation (Stable Diffusion).
Given a character's current activity description, output a JSON object with 4 keys:
- action: physical pose/gesture/hand position (3-8 English tags)
- environment: background and surroundings (3-8 English tags)
- expression: facial expression (2-5 English tags)
- lighting: light conditions (2-4 English tags)

Rules:
1. Output ONLY valid JSON, no markdown, no explanations
2. All values must be English tags suitable for Stable Diffusion
3. Do NOT include character appearance (hair, eyes, clothing)
4. Tags should feel natural for the scenario
5. Keep tags concise and descriptive
6. IMPORTANT for action: prefer simple, AI-friendly gestures. AVOID complex multi-finger details (e.g. heart shape with hands, interlocked fingers) as they cause generation artifacts"""

_SCENE_STYLE_HINTS = {
    "standard": """
7. STYLE CONSTRAINT - Standard selfie (front camera):
   - ONE hand is holding the phone OFF-SCREEN (invisible, arm extended toward camera)
   - ONLY ONE hand is visible and free in the frame
   - Action MUST be a SINGLE-HAND gesture using the free hand only
   - Examples: peace sign with one hand, touching hair with one hand, hand on chin, waving with one hand
   - FORBIDDEN: two hands together, both hands visible, hands touching each other, any gesture requiring both hands
   - The visible hand should be at face/upper body level, natural and relaxed""",

    "mirror": """
7. STYLE CONSTRAINT - Mirror selfie (reflection):
   - ONE hand holds the phone (visible in mirror reflection)
   - ONLY the OTHER hand is free for posing
   - Action should be single-hand poses suitable for mirror reflection
   - Examples: hand on hip, adjusting hair with one hand, fixing collar, hand in pocket, hand on waist
   - FORBIDDEN: both hands free, two-hand gestures, hands together
   - The free hand should complement the mirror pose naturally""",

    "photo": """
7. STYLE CONSTRAINT - Third-person photo (external camera):
   - Someone else is taking the photo, NOT a selfie
   - Subject's hands are COMPLETELY FREE from any devices
   - BOTH hands can be used naturally, but prefer calm, elegant poses
   - Examples: hands at sides, one hand in hair (wind blowing), holding a prop (coffee/book/bag), leaning pose
   - FORBIDDEN: phone, smartphone, camera, selfie stick in subject's hands; arm extended toward camera; selfie pose
   - Prefer full-body or upper-body natural poses, avoid exaggerated gestures""",
}

_SCENE_LLM_EXAMPLES = """
Examples:

Activity: 在书房看轻小说
{"action": "holding book, reading, relaxed pose", "environment": "study room, bookshelf, warm interior", "expression": "content smile, absorbed", "lighting": "desk lamp, warm indoor light"}

Activity: 在厨房做早饭
{"action": "holding spatula, cooking", "environment": "kitchen, stove, morning atmosphere", "expression": "happy smile, focused on cooking", "lighting": "morning light through window, bright kitchen"}

Activity: 在公园散步
{"action": "walking, casual stroll", "environment": "park, trees, pathway, flowers", "expression": "peaceful smile, relaxed", "lighting": "soft natural sunlight, dappled light"}

Now generate for the following activity:"""


def build_scene_llm_prompt(selfie_style: str) -> str:
    """组装带风格约束的 LLM 场景生成 prompt"""
    style_hint = _SCENE_STYLE_HINTS.get(selfie_style, _SCENE_STYLE_HINTS["standard"])
    return f"{_SCENE_LLM_PROMPT_BASE}{style_hint}{_SCENE_LLM_EXAMPLES}"


# ==================== 公共 API ====================

async def generate_scene_with_llm(
    ctx: "PluginContext",
    activity_info: "ActivityInfo",
    selfie_style: str = "standard",
    llm_task: str = "utils",
) -> Optional[Dict[str, str]]:
    """LLM 根据活动描述生成英文 SD 场景标签

    Returns: 包含 hand_action / environment / expression / lighting 的字典，失败返回 None
    """
    try:
        system_prompt = build_scene_llm_prompt(selfie_style)
        prompt = f"{system_prompt}\n\nActivity: {activity_info.description}"

        result = await ctx.llm.generate(prompt=prompt, model=llm_task, temperature=0.7, max_tokens=8192)

        success, response, model_name = False, "", ""
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            response = str(result.get("response") or result.get("content") or "")
            model_name = str(result.get("model") or result.get("model_name") or "")

        if not (success and response):
            logger.warning("LLM 场景生成返回空响应")
            return None

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        scene = json.loads(cleaned)
        required_keys = {"action", "environment", "expression", "lighting"}
        if not required_keys.issubset(scene.keys()):
            logger.warning(f"LLM 场景缺少字段: {required_keys - set(scene.keys())}")
            return None

        for key in required_keys:
            if not isinstance(scene[key], str) or not scene[key].strip():
                logger.warning(f"LLM 场景字段 {key} 无效: {scene.get(key)}")
                return None

        logger.info(f"LLM 场景生成成功 (模型: {model_name}): action={scene['action'][:50]}")
        return {
            "hand_action": scene["action"],
            "environment": scene["environment"],
            "expression": scene["expression"],
            "lighting": scene["lighting"],
        }

    except json.JSONDecodeError as e:
        logger.warning(f"LLM 场景 JSON 解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM 场景生成异常: {e}")
        return None


def get_action_for_activity(activity_info: "ActivityInfo") -> Dict[str, str]:
    """LLM 失败时的确定性场景兜底（手动自拍日程增强用）"""
    key = activity_info.activity_type.value
    return {
        "hand_action": ACTIVITY_ACTIONS.get(key, ACTIVITY_ACTIONS["other"]),
        "environment": ACTIVITY_ENVIRONMENTS.get(key, ACTIVITY_ENVIRONMENTS["other"]),
        "expression": ACTIVITY_EXPRESSIONS.get(key, ACTIVITY_EXPRESSIONS["other"]),
        "lighting": ACTIVITY_LIGHTING.get(key, ACTIVITY_LIGHTING["other"]),
    }
