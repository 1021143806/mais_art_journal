"""工具函数统一入口"""

from .shared_constants import (
    BASE64_IMAGE_PREFIXES,
    ANTI_DUAL_HANDS_PROMPT,
    SELFIE_HAND_NEGATIVE,
    ANTI_DUAL_PHONE_PROMPT,
    PHOTO_NO_PHONE_PROMPT,
)
from .model_utils import merge_negative_prompt, inject_llm_original_size
from .image_utils import ImageProcessor
from .image_send_utils import resolve_image_data
from .size_utils import (
    validate_image_size, get_image_size, get_image_size_async,
    pixel_size_to_gemini_aspect, parse_pixel_size,
)
from .cache_manager import CacheManager
from .time_utils import to_minutes, is_in_time_range
from .recall_utils import schedule_auto_recall
from .prompt_optimizer import optimize_prompt
from .request_context import RequestContext

# 兼容 re-export：runtime_state 现已迁至 core.state.runtime_state，但保留旧导出路径
from ..state.runtime_state import runtime_state, RuntimeStateManager  # noqa: F401
