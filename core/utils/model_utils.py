"""模型配置工具函数

提供负面提示词合并、Gemini / OpenAI-Chat 尺寸注入等纯函数能力。
模型配置查找（按 id）请使用 `core.config.get_model_config`，本模块不再提供。
"""
import logging
from typing import Dict, Any

logger = logging.getLogger("plugin.mais_art_journal.model_utils")


def merge_negative_prompt(
    model_config: Dict[str, Any],
    extra_negative: str,
) -> Dict[str, Any]:
    """
    将额外的负面提示词合并进 model_config。
    返回浅拷贝，不修改原 dict。
    """
    if not extra_negative:
        return model_config
    config = dict(model_config)
    existing = config.get("negative_prompt_add", "")
    if existing:
        config["negative_prompt_add"] = f"{existing}, {extra_negative}"
    else:
        config["negative_prompt_add"] = extra_negative
    return config


# 这些 API 格式需要把 LLM 选的尺寸（如 1024x1024）保留下来，
# 后续在客户端里转成 Gemini 风格的 aspect_ratio + resolution
_FORMATS_NEEDING_LLM_SIZE = {"gemini", "openai-chat"}


def inject_llm_original_size(
    model_config: Dict[str, Any],
    llm_original_size: str,
) -> Dict[str, Any]:
    """
    对 Gemini / OpenAI-Chat 格式，注入 _llm_original_size。返回浅拷贝，不修改原 dict。其他格式直接返回原 dict。
    """
    api_format = model_config.get("format", "openai")
    if api_format in _FORMATS_NEEDING_LLM_SIZE and llm_original_size:
        config = dict(model_config)
        config["_llm_original_size"] = llm_original_size
        return config
    return model_config
