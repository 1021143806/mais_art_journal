"""图片生成 Pipeline / Step 编排"""

from .factories import (
    build_action_pipeline,
    build_auto_selfie_pipeline,
    build_natural_command_pipeline,
    build_request_from_action_kwargs,
    build_standalone_pipeline,
    build_style_command_pipeline,
    make_pipeline_context,
)
from .pipeline import Pipeline
from .request import GenerationRequest
from .result import StepResult
from .step import BaseStep, PipelineContext, PipelineStep

__all__ = [
    "Pipeline",
    "GenerationRequest",
    "StepResult",
    "PipelineStep",
    "PipelineContext",
    "BaseStep",
    "build_action_pipeline",
    "build_style_command_pipeline",
    "build_natural_command_pipeline",
    "build_auto_selfie_pipeline",
    "build_standalone_pipeline",
    "build_request_from_action_kwargs",
    "make_pipeline_context",
]
