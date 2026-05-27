"""Step: 发送图片

- send_image=False 时跳过（auto_selfie / standalone 用）
- 记录 send_timestamp 供撤回调度使用
- debug 模式下补一句"完成"提示
"""
from __future__ import annotations

import logging
import time as time_module
from typing import TYPE_CHECKING, Optional

from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.send")


class SendImage(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.send_image:
            return None

        if not req.resolved_image_data:
            return StepResult.fail(error="无图片数据可发送", user_message="图片数据缺失")

        if not req.stream_id:
            return StepResult.fail(error="缺少 stream_id", user_message=None)

        req.send_timestamp = time_module.time()
        try:
            sent = await ctx.plugin.ctx.send.image(req.resolved_image_data, req.stream_id)
        except Exception as e:
            logger.error(f"{req.log_prefix} 发送图片异常: {e!r}")
            return StepResult.fail(error=f"发送图片异常: {e!r}", user_message="图片已处理完成，但发送失败了")

        if not sent:
            return StepResult.fail(error="发送图片返回 falsy", user_message="图片已处理完成，但发送失败了")

        mode_text = "图生图" if req.is_img2img else "文生图"
        if req.debug_info and not req.cache_hit and req.source in ("tool", "cmd_style", "cmd_natural"):
            try:
                await ctx.plugin.ctx.send.text(f"{mode_text}完成！", req.stream_id)
            except Exception as e:
                logger.warning(f"{req.log_prefix} 发送完成提示失败: {e}")

        return None
