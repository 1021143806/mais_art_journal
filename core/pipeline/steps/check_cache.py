"""Step: 缓存查找

- update_cache=False 时跳过
- 命中：写 resolved_image_data + cache_hit=True，debug 时发提示
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.cache")


class CheckCache(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.update_cache or not req.resolved_model_config:
            return None

        model_name = req.resolved_model_config.get("model", "default-model")
        hit = ctx.cache.get_cached_result(
            req.description, model_name, req.final_size, req.strength, req.is_img2img,
        )
        if not hit:
            return None

        req.resolved_image_data = hit
        req.cache_hit = True
        logger.info(f"{req.log_prefix} 使用缓存的图片结果")

        if req.debug_info and req.stream_id:
            try:
                await ctx.plugin.ctx.send.text("我之前画过类似的图片，用之前的结果~", req.stream_id)
            except Exception as e:
                logger.warning(f"{req.log_prefix} 发送缓存提示失败: {e}")
        return None
