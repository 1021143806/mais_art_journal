"""图片数据处理工具

统一 base64 vs URL 图片数据的解析逻辑，消除 pic_action / pic_command 中的重复。
"""

import asyncio
import logging
from typing import Tuple, Callable

from .shared_constants import BASE64_IMAGE_PREFIXES

logger = logging.getLogger("plugin.mais_art_journal.image_send")


async def resolve_image_data(
    image_data: str,
    download_fn: Callable[[str], Tuple[bool, str]],
    log_prefix: str = "",
) -> Tuple[bool, str]:
    """将图片数据统一为 base64 格式

    如果 image_data 已是 base64 编码则原样返回；
    如果是 URL 则通过 download_fn 下载并转为 base64。

    Args:
        image_data: base64 字符串或图片 URL
        download_fn: 同步下载函数，签名 (url) -> (success, base64_or_error)
        log_prefix: 日志前缀

    Returns:
        (success, base64_data_or_error_message)
    """
    if image_data.startswith(BASE64_IMAGE_PREFIXES):
        return True, image_data

    # URL: 下载并转为 base64
    try:
        encode_success, encode_result = await asyncio.to_thread(download_fn, image_data)
        if encode_success:
            return True, encode_result
        else:
            logger.warning(f"{log_prefix} 图片下载失败: {encode_result}")
            return False, f"图片下载失败: {encode_result}"
    except Exception as e:
        logger.error(f"{log_prefix} 图片下载编码失败: {e!r}")
        return False, "图片下载失败"
