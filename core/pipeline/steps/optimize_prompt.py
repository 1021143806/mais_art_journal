"""Step: 通用提示词优化

- 自拍模式跳过（由 BuildSelfiePrompt 内部按 scene_only=True 走优化）
- 优化器关闭时跳过
- 失败时保留原始 description（optimize_prompt 内部已经容错）
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ...utils import optimize_prompt
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.optimize")


class OptimizePrompt(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if req.is_selfie:
            # 自拍模式由 BuildSelfiePrompt 内部走 scene_only=True
            return None

        if not ctx.plugin.config.basic.prompt_optimizer_enabled:
            return None

        if not req.description.strip():
            return None

        logger.info(f"{req.log_prefix} 开始优化提示词: {req.description[:50]}...")
        ok, optimized = await optimize_prompt(
            ctx.plugin.ctx,
            req.description,
            log_prefix=req.log_prefix,
            scene_only=False,
            llm_task=ctx.plugin.config.basic.llm_task_name or "utils",
        )
        if ok and optimized:
            logger.info(f"{req.log_prefix} 提示词优化完成: {optimized[:80]}...")
            req.description = optimized
        else:
            logger.warning(f"{req.log_prefix} 提示词优化失败，使用原始描述")
        return None
