"""Pipeline Step 协议 + 共享上下文"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..api_clients import BaseApiClient
    from ..utils import CacheManager, ImageProcessor
    from ..utils.request_context import RequestContext
    from ...plugin import MaisArtPlugin
    from .request import GenerationRequest
    from .result import StepResult


@dataclass
class PipelineContext:
    """流水线共享上下文（按一次请求构造）"""

    plugin: "MaisArtPlugin"
    cache: "CacheManager"
    image_processor: "ImageProcessor"
    client_factory: Callable[[str], "BaseApiClient"]
    request_ctx: "RequestContext"
    """旧 utils（ImageProcessor / CacheManager）期望的鸭子上下文，含 get_config + log_prefix"""


@runtime_checkable
class PipelineStep(Protocol):
    """Pipeline 中的一个步骤

    实现类应当：
    - 设置 name 类属性
    - 实现 async run(req, ctx) -> Optional[StepResult]
    - 返回 None 等价于 StepResult.cont()
    """

    name: str

    async def run(
        self,
        req: "GenerationRequest",
        ctx: PipelineContext,
    ) -> Optional["StepResult"]:
        ...


class BaseStep:
    """便利基类：提供默认 name = 类名，子类只需实现 run"""

    name: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            cls.name = cls.__name__

    async def run(self, req: "GenerationRequest", ctx: PipelineContext) -> Optional["StepResult"]:
        raise NotImplementedError
