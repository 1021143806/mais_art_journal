"""Step: 协商图片尺寸

- 用 get_image_size_async 处理 fixed_size_enabled / LLM 选择 / 默认值
- validate_image_size 校验最终尺寸；非法时回退 default_size
- 把 llm_chosen_size 注入 model_config，供 Gemini / openai-chat 等需要宽高比转换的格式使用
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ...utils import get_image_size_async, inject_llm_original_size, validate_image_size
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext


class ResolveSize(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.resolved_model_config:
            return StepResult.fail(error="模型配置缺失，无法协商尺寸")

        image_size, llm_size = await get_image_size_async(
            req.resolved_model_config,
            description=req.description,
            llm_size=req.size or None,
            log_prefix=req.log_prefix,
            ctx=ctx.plugin.ctx,
            llm_task=ctx.plugin.config.basic.llm_task_name or "utils",
        )

        if not validate_image_size(image_size):
            image_size = req.resolved_model_config.get("default_size", "1024x1024")

        req.final_size = image_size
        req.llm_chosen_size = llm_size
        req.resolved_model_config = inject_llm_original_size(req.resolved_model_config, llm_size)
        return None
