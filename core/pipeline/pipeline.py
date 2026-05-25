"""Pipeline 主循环

按顺序执行 steps，按 StepResult 控制流程。
异常会被捕获并写入 req.error；失败时若有 user_message 会自动发送到 stream_id。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from ..api_clients.base_client import NonRetryableError
from .result import StepResult

if TYPE_CHECKING:
    from .request import GenerationRequest
    from .step import PipelineContext, PipelineStep

logger = logging.getLogger("plugin.mais_art_journal.pipeline")


class Pipeline:
    """串行执行一组 Step"""

    def __init__(self, steps: List["PipelineStep"], name: str = "pipeline"):
        self.steps = steps
        self.name = name

    async def run(
        self,
        req: "GenerationRequest",
        ctx: "PipelineContext",
    ) -> "GenerationRequest":
        for step in self.steps:
            try:
                result = await step.run(req, ctx)
            except NonRetryableError as e:
                req.success = False
                req.error = str(e)
                logger.warning(f"{req.log_prefix} pipeline {self.name} 在 {step.name} 遇到不可重试错误: {e}")
                return req
            except Exception as e:
                req.success = False
                req.error = repr(e)
                logger.exception(f"{req.log_prefix} pipeline {self.name} 在 {step.name} 抛出异常")
                return req

            if result is None:
                continue

            if result.action == "continue":
                continue
            if result.action == "skip_remaining":
                break
            if result.action == "fail":
                if result.user_message and req.stream_id:
                    try:
                        await ctx.plugin.ctx.send.text(result.user_message, req.stream_id)
                    except Exception as e:
                        logger.warning(f"{req.log_prefix} 发送失败信息失败: {e}")
                req.success = False
                req.error = result.error
                req.user_message = result.user_message
                return req
            if result.action == "done":
                req.success = True
                req.user_message = result.user_message
                return req

        req.success = True
        return req
