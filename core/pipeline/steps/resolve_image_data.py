"""Step: 把 URL / data URI 统一解析为 base64

- 缓存命中跳过（已有 resolved_image_data）
- URL：下载（带代理）转 base64
- data:image/... → 提取 base64
- 纯 base64 → 透传
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ...utils import resolve_image_data
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext

logger = logging.getLogger("plugin.mais_art_journal.step.resolve_image")


class ResolveImageData(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if req.cache_hit:
            return None

        plugin = ctx.plugin
        proxy_url: Optional[str] = None
        if plugin.config.proxy.enabled:
            proxy_url = plugin.config.proxy.url

        def _download_fn(image_url: str):
            return ctx.image_processor.download_and_encode_base64(image_url, proxy_url=proxy_url)

        if not req.parsed_image_data:
            return StepResult.fail(error="无可解析的图片数据", user_message="API 返回数据格式错误")

        ok, resolved = await resolve_image_data(req.parsed_image_data, _download_fn, req.log_prefix)
        if not ok:
            return StepResult.fail(
                error=f"图片处理失败: {resolved}",
                user_message=f"图片处理失败：{resolved}",
            )

        req.resolved_image_data = resolved
        return None
