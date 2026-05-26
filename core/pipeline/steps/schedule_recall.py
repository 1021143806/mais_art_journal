"""Step: 调度自动撤回

- schedule_recall=False / send_image=False / cache_hit 时跳过
- auto_recall.enabled + 模型 auto_recall_delay + runtime_state.is_recall_enabled 三重校验
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from ...state import runtime_state
from ...utils import schedule_auto_recall
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.recall")


class ScheduleRecall(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.schedule_recall or not req.send_image or req.cache_hit:
            return None
        if not req.resolved_model_config or not req.stream_id:
            return None

        plugin = ctx.plugin
        global_enabled = plugin.config.basic.auto_recall_enabled
        if not global_enabled:
            return None

        delay_seconds = int(req.resolved_model_config.get("auto_recall_delay") or 0)
        if delay_seconds <= 0:
            return None

        if req.model_id and not runtime_state.is_recall_enabled(req.chat_id, req.model_id, global_enabled):
            logger.info(f"{req.log_prefix} 模型 {req.model_id} 撤回已在当前聊天流禁用")
            return None

        await schedule_auto_recall(
            plugin.ctx, req.chat_id, delay_seconds, req.log_prefix, req.send_timestamp,
        )
        return None
