"""Step: 合并额外负面提示词

- 优先使用 extra_negative_prompt（外部传入）
- 否则使用自拍模式产生的 selfie_negative_prompt
- 合并到 model_config 的 negative_prompt_add
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ...utils import merge_negative_prompt
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.merge_neg")


class MergeNegativePrompt(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.resolved_model_config:
            return None

        extra = req.extra_negative_prompt or req.selfie_negative_prompt
        if not extra:
            return None

        req.resolved_model_config = merge_negative_prompt(req.resolved_model_config, extra)
        logger.info(f"{req.log_prefix} 合并额外负面提示词: {extra[:80]}...")
        return None
