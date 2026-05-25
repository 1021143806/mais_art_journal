"""Step: 解析模型 ID

- 缺失 model_id 时按 source 选 action / command 全局默认
- runtime_state 按聊天流覆盖
- 模型禁用检查 → fail
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ...state import runtime_state
from ..result import StepResult
from ..step import BaseStep

if TYPE_CHECKING:
    from ..request import GenerationRequest
    from ..step import PipelineContext


class ResolveModel(BaseStep):
    async def run(self, req: "GenerationRequest", ctx: "PipelineContext") -> Optional[StepResult]:
        if not req.model_id:
            plugin = ctx.plugin
            if req.source in ("cmd_style", "cmd_natural"):
                global_default = plugin.config.basic.pic_command_model
                req.model_id = runtime_state.get_command_default_model(req.chat_id, global_default)
            elif req.source == "auto_selfie":
                req.model_id = plugin.config.selfie.selfie_model
            elif req.source == "standalone":
                req.model_id = plugin.config.basic.default_model
            else:  # action
                global_default = plugin.config.basic.default_model
                req.model_id = runtime_state.get_action_default_model(req.chat_id, global_default)

        if req.source != "standalone" and not runtime_state.is_model_enabled(req.chat_id, req.model_id):
            return StepResult.fail(
                error=f"模型 {req.model_id} 已禁用",
                user_message=f"模型 {req.model_id} 当前不可用",
            )

        return None
