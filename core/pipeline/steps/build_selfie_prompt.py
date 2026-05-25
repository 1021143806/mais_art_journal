"""Step: 构造自拍提示词

- 非自拍直接跳过
- selfie.enabled=False → fail
- 委托给 prompts.selfie_prompt_builder.build() 完成动作池 / LLM 手部动作 / 场景 / 负面
- 把结果写回 req.description + req.selfie_negative_prompt
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.selfie_prompt")


class BuildSelfiePrompt(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.is_selfie:
            return None

        plugin = ctx.plugin
        if not plugin.config.selfie.enabled:
            return StepResult.fail(error="自拍功能未启用", user_message="自拍功能暂未启用~")

        from ...prompts.selfie_prompt_builder import build as build_selfie_prompt

        logger.info(f"{req.log_prefix} 启用自拍模式，风格: {req.selfie_style}")
        result = await build_selfie_prompt(
            ctx=plugin.ctx,
            selfie_style=req.selfie_style,
            description=req.description,
            free_hand_action=req.free_hand_action,
            activity_scene=req.activity_scene,
            bot_appearance=plugin.config.selfie.prompt_prefix or "",
            base_negative=plugin.config.selfie.negative_prompt or "",
            log_prefix=req.log_prefix,
            run_scene_optimizer=plugin.config.basic.prompt_optimizer_enabled,
            llm_task=plugin.config.basic.llm_task_name or "utils",
        )

        req.description = result.prompt
        req.selfie_negative_prompt = result.negative_prompt
        logger.info(f"{req.log_prefix} 自拍提示词构造完成: {req.description[:100]}...")
        return None
