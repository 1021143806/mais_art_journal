"""API客户端模块

支持多种图片生成API：
- OpenAI 格式 (OpenAI, 硅基流动, NewAPI, 智谱 GLM, 模力方舟 gitee 等)
- OpenAI Chat 格式 (通过 chat/completions 接口生图；兼容Gemini 转发代理)
- Doubao 豆包格式
- Gemini 格式
- Modelscope 魔搭格式
- Shatangyun 砂糖云格式 (NovelAI)
- Mengyuai 梦羽AI格式
- ComfyUI 格式 (本地ComfyUI工作流)
- DashScope 阿里百炼格式 (通义千问 / 万相 / Z-Image / 可灵)
"""

from typing import Dict, Any, Tuple, Optional

from .base_client import BaseApiClient
from .client_context import ClientContext, ProxyConfig, build_client_context_from_plugin, build_client_context_from_extra
from .openai_client import OpenAIClient
from .openai_chat_client import OpenAIChatClient
from .doubao_client import DoubaoClient
from .gemini_client import GeminiClient
from .modelscope_client import ModelscopeClient
from .shatangyun_client import ShatangyunClient
from .mengyuai_client import MengyuaiClient
from .comfyui_client import ComfyUIClient
from .dashscope_client import DashScopeClient

__all__ = [
    'BaseApiClient',
    'ClientContext',
    'ProxyConfig',
    'build_client_context_from_plugin',
    'build_client_context_from_extra',
    'OpenAIClient',
    'OpenAIChatClient',
    'DoubaoClient',
    'GeminiClient',
    'ModelscopeClient',
    'ShatangyunClient',
    'MengyuaiClient',
    'ComfyUIClient',
    'DashScopeClient',
    'ApiClient',
    'get_client_class',
    'generate_image_standalone',
]


# API格式到客户端类的映射
CLIENT_MAPPING = {
    'openai': OpenAIClient,
    'openai-chat': OpenAIChatClient,
    'doubao': DoubaoClient,
    'gemini': GeminiClient,
    'modelscope': ModelscopeClient,
    'shatangyun': ShatangyunClient,
    'mengyuai': MengyuaiClient,
    'comfyui': ComfyUIClient,
    'dashscope': DashScopeClient,
}


def get_client_class(api_format: str):
    """根据API格式获取对应的客户端类

    Args:
        api_format: API格式名称

    Returns:
        客户端类，如果不存在则返回OpenAIClient作为默认
    """
    return CLIENT_MAPPING.get(api_format.lower(), OpenAIClient)


class ApiClient:
    """统一的API客户端包装类（兼容入口）

    保留给旧 image_generation.py / command_handlers.py 使用，
    内部接受 ClientContext 或任何 duck-typed（get_config + log_prefix）对象。
    新代码请直接 `get_client_class(api_format)(client_ctx)`。
    """

    def __init__(self, client_ctx):
        self.ctx = client_ctx
        self._clients = {}  # 缓存客户端实例

    def _get_client(self, api_format: str):
        """获取指定格式的客户端实例（带缓存）"""
        if api_format not in self._clients:
            client_class = get_client_class(api_format)
            self._clients[api_format] = client_class(self.ctx)
        return self._clients[api_format]

    async def generate_image(
        self,
        prompt: str,
        model_config: dict,
        size: str,
        strength: float = None,
        input_image_base64: str = None,
        max_retries: int = 2,
    ):
        api_format = model_config.get("format", "openai")
        client = self._get_client(api_format)
        return await client.generate_image(
            prompt=prompt,
            model_config=model_config,
            size=size,
            strength=strength,
            input_image_base64=input_image_base64,
            max_retries=max_retries,
        )


async def generate_image_standalone(
    prompt: str,
    model_config: Dict[str, Any],
    size: str = "1024x1024",
    negative_prompt: Optional[str] = None,
    strength: Optional[float] = None,
    input_image_base64: Optional[str] = None,
    max_retries: int = 2,
    extra_config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """独立的图片生成接口，不依赖 Action / Plugin 实例

    供外部插件（如 MaiTrace）或 AutoSelfieTask 直接调用，只做图片生成、不发送消息。

    Args:
        prompt: 提示词
        model_config: 模型配置字典，必须包含 base_url, api_key, format, model 等字段
        size: 图片尺寸，默认 "1024x1024"
        negative_prompt: 额外负面提示词，会合并到 model_config 的 negative_prompt_add
        strength: 图生图强度（0.0-1.0），仅图生图时使用
        input_image_base64: 输入图片的 base64 编码（图生图用）
        max_retries: 最大重试次数
        extra_config: 额外配置（如 proxy 设置），格式同 config.toml 结构

    Returns:
        (success, image_data): success 为 True 时 image_data 是 base64 或 URL
    """
    import logging
    from ..utils import merge_negative_prompt
    _logger = logging.getLogger("plugin.mais_art_journal.standalone")

    merged_config = merge_negative_prompt(model_config, negative_prompt) if negative_prompt else model_config

    client_ctx = build_client_context_from_extra(extra_config, log_prefix="[standalone]")
    api_format = merged_config.get("format", "openai")
    client_class = get_client_class(api_format)
    client = client_class(client_ctx)

    _logger.info(
        f"[standalone] 独立生图: format={api_format}, "
        f"model={merged_config.get('model', '?')}, size={size}"
    )

    try:
        success, result = await client.generate_image(
            prompt=prompt,
            model_config=merged_config,
            size=size,
            strength=strength,
            input_image_base64=input_image_base64,
            max_retries=max_retries,
        )
        if success:
            _logger.info(f"[standalone] 生图成功，数据长度: {len(result) if result else 0}")
        else:
            _logger.warning(f"[standalone] 生图失败: {result}")
        return success, result
    except Exception as e:
        _logger.error(f"[standalone] 生图异常: {e!r}")
        return False, f"独立生图异常: {str(e)[:100]}"

