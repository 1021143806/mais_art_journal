"""Step: 解析 API 响应为统一字符串

ImageProcessor.process_api_response 将 dict/str 等返回值提取出可用的
URL / base64 / data URI 字符串。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.parse_response")


class ParseResponse(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if req.cache_hit:
            return None

        data = ctx.image_processor.process_api_response(req.raw_api_result)
        if not data:
            logger.warning(f"{req.log_prefix} API 返回数据无法解析")
            return StepResult.fail(
                error="API返回数据格式错误",
                user_message="图片生成API返回了无法处理的数据格式",
            )

        req.parsed_image_data = data
        return None
