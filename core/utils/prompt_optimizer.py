"""提示词优化器模块

使用 MaiBot 主 LLM 将用户描述优化为专业的绘画提示词。
SDK 2.x：通过 ctx.llm.generate 调用，由 Host 决定使用哪个模型。
"""
import logging
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

logger = logging.getLogger("plugin.mais_art_journal.optimizer")

# 提示词优化系统提示词
OPTIMIZER_SYSTEM_PROMPT = """You are a professional AI art prompt engineer. Your task is to convert user descriptions into high-quality English prompts for image generation models (Stable Diffusion, DALL-E, etc.).

## Rules:
1. Output ONLY the English prompt, no explanations or translations
2. Use comma-separated tags/phrases in professional art terminology
3. Follow structure: subject, action/pose, scene/background, lighting, style, quality tags
4. Use weight syntax for emphasis: (keyword:1.2) for important elements, (keyword:1.4) for very important
5. Keep prompts concise but descriptive (50-150 words ideal)
6. Always end with quality tags: masterpiece, best quality, high resolution, detailed
7. Focus on visual elements that can be rendered: colors, composition, lighting, atmosphere
8. Avoid abstract concepts or emotions that cannot be directly visualized
9. Use specific, concrete descriptors rather than vague terms
10. For anatomy (hands, faces, body), use proper anatomical terms

## Examples:

Input: 海边的女孩
Output: (1girl:1.3), solo, standing on beach, ocean waves in background, (sunset sky:1.2), orange and pink clouds, warm golden lighting, summer dress flowing in wind, wind blowing through hair, peaceful serene expression, looking at horizon, (beautiful detailed face:1.2), masterpiece, best quality, high resolution, detailed

Input: 可爱的猫咪睡觉
Output: (cute cat:1.3), sleeping peacefully, curled up on soft fluffy blanket, (fluffy fur:1.2), closed eyes, content expression, warm cozy indoor lighting, comfortable atmosphere, (detailed fur texture:1.2), soft focus background, masterpiece, best quality, high resolution, detailed

Input: 赛博朋克城市
Output: (cyberpunk cityscape:1.4), neon lights, futuristic skyscrapers, flying cars in sky, (rain:1.2), reflective wet streets, holographic advertisements, (purple and blue color scheme:1.3), atmospheric fog, cinematic lighting, night scene, (detailed architecture:1.2), masterpiece, best quality, high resolution, detailed

Input: 森林中的精灵
Output: (forest elf:1.3), 1girl, (pointed ears:1.2), standing in ancient forest, surrounded by tall trees, (dappled sunlight through leaves:1.3), magical atmosphere, (glowing particles:1.2), fantasy setting, elegant pose, (detailed face:1.2), flowing dress, nature background, masterpiece, best quality, high resolution, detailed

Now convert the following description to an English prompt:"""

# 自拍场景专用提示词：只生成场景/环境/光线/氛围，不生成角色外观
SELFIE_SCENE_SYSTEM_PROMPT = """You are a scene description assistant for selfie image generation. The character's appearance is already defined separately. Your task is to convert the user's description into English tags describing ONLY the scene, environment, lighting, mood, and atmosphere.

## Rules:
1. Output ONLY English tags, no explanations
2. Use comma-separated tags/phrases
3. NEVER include character appearance (hair color, eye color, clothing, body type, facial features, etc.)
4. NEVER include character names or franchise references
5. Focus on: background, environment, lighting, weather, mood, atmosphere, time of day, location details
6. Keep it concise (20-60 words)
7. If the description is just "selfie" or similar with no scene info, output a simple generic scene
8. Use specific, visual descriptors for the environment
9. Include lighting conditions that enhance the mood

## Examples:

Input: 在海边自拍
Output: beach background, ocean waves, (golden sunset:1.2), warm sunlight, sand, gentle sea breeze, summer atmosphere, horizon line, coastal scenery

Input: 图书馆学习
Output: library interior, wooden bookshelves in background, (warm ambient lighting:1.2), quiet peaceful atmosphere, study desk, soft focus background, academic setting

Input: 来张自拍
Output: casual indoor setting, soft natural lighting, clean simple background, comfortable atmosphere

Input: 下雨天在咖啡店
Output: coffee shop interior, (rain drops on window:1.2), warm cozy atmosphere, soft indoor lighting, blurred rainy background through glass, bokeh effect, comfortable cafe setting

Input: 公园散步
Output: park scenery, trees and greenery, natural outdoor lighting, (dappled sunlight through leaves:1.2), pathway, flowers, peaceful atmosphere, spring or summer day

Now convert the following description to English scene tags:"""


def _clean_response(response: str) -> str:
    """清理 LLM 响应：移除可能的前缀、首尾引号、多余空白"""
    result = response.strip()

    prefixes_to_remove = ["Output:", "output:", "Prompt:", "prompt:"]
    for prefix in prefixes_to_remove:
        if result.startswith(prefix):
            result = result[len(prefix):].strip()

    if (result.startswith('"') and result.endswith('"')) or \
       (result.startswith("'") and result.endswith("'")):
        result = result[1:-1]

    result = " ".join(result.split())
    return result


async def optimize_prompt(
    ctx: "PluginContext",
    user_description: str,
    log_prefix: str = "[PromptOptimizer]",
    scene_only: bool = False,
    llm_task: str = "utils",
) -> Tuple[bool, str]:
    """优化用户描述为专业绘画提示词

    Args:
        ctx: PluginContext（SDK 上下文）
        user_description: 用户原始描述（中文或英文）
        log_prefix: 日志前缀
        scene_only: 仅生成场景/环境描述（自拍模式用，不包含角色外观）
        llm_task: 调用 ctx.llm.generate 时使用的任务名，对应 MaiBot model_task_config 字段

    Returns:
        Tuple[bool, str]: (是否成功, 优化后的提示词或原始描述)
    """
    if not user_description or not user_description.strip():
        return False, "描述不能为空"

    system_prompt = SELFIE_SCENE_SYSTEM_PROMPT if scene_only else OPTIMIZER_SYSTEM_PROMPT
    full_prompt = f"{system_prompt}\n\nInput: {user_description.strip()}\nOutput:"
    mode_label = "场景提示词" if scene_only else "提示词"

    logger.info(f"{log_prefix} 开始优化{mode_label}: {user_description[:50]}...")

    try:
        result = await ctx.llm.generate(
            prompt=full_prompt,
            model=llm_task,
            temperature=0.7,
            max_tokens=8192,
        )

        response = ""
        model_name = ""
        success = False
        if isinstance(result, dict):
            success = bool(result.get("success", True))
            response = str(result.get("response") or result.get("content") or "")
            model_name = str(result.get("model") or result.get("model_name") or "")

        if success and response:
            optimized = _clean_response(response)
            logger.info(f"{log_prefix} 优化成功 (模型: {model_name}): {optimized[:80]}...")
            return True, optimized

        logger.warning(f"{log_prefix} LLM 返回空响应，降级使用原始描述")
        return True, user_description

    except Exception as e:
        logger.error(f"{log_prefix} 优化失败: {e}，使用原始描述")
        return True, user_description
