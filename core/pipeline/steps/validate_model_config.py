"""Step: 校验模型配置

- 通过 model_registry 找配置
- 检查 base_url / api_key（comfyui 允许 api_key 为空）
- 占位密钥 → fail
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ...config import get_model_config
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext


PLACEHOLDER_TOKENS = ("YOUR_API_KEY_HERE", "xxxxxxxxxxxxxx")


class ValidateModelConfig(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        cfg = get_model_config(ctx.plugin, req.model_id)
        if not cfg:
            return StepResult.fail(
                error=f"模型 {req.model_id!r} 不存在或配置无效",
                user_message=f"指定的模型 '{req.model_id}' 不存在或配置无效，请检查配置文件。",
            )

        api_format = cfg.get("format", "openai")
        base_url = cfg.get("base_url") or ""
        api_key = cfg.get("api_key") or ""

        if not base_url:
            return StepResult.fail(
                error="缺少 base_url",
                user_message="抱歉，图片生成功能所需的HTTP配置（如API地址）不完整，无法提供服务。",
            )

        if api_format != "comfyui":
            if not api_key:
                return StepResult.fail(
                    error="缺少 api_key",
                    user_message="抱歉，图片生成功能所需的HTTP配置（如API密钥）不完整，无法提供服务。",
                )
            if any(token in api_key for token in PLACEHOLDER_TOKENS):
                return StepResult.fail(
                    error="API 密钥未配置",
                    user_message="图片生成功能尚未配置，请设置正确的API密钥。",
                )

        req.resolved_model_config = cfg
        req.api_format = api_format
        return None
