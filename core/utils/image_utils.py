import base64
import urllib.request
import traceback
import logging
from typing import Any, Optional, Tuple, List

from maim_message import Seg

logger = logging.getLogger("plugin.mais_art_journal.image")


class ImageProcessor:
    """图片处理工具类

    构造时接收 RequestContext（或鸭子类型），需要：
    - log_prefix
    - 可选：message（Command 路径触发消息 dict；Tool 路径为 None）
    - 可选：ctx（PluginContext，用于 get_by_id 回拉 reply 目标消息）
    - 可选：chat_id（用于 get_by_id 时定位会话）
    """

    def __init__(self, action_instance):
        self.action = action_instance
        self.log_prefix = getattr(action_instance, "log_prefix", "[MaisArt]")
        self._ctx = getattr(action_instance, "ctx", None)
        self._chat_id = getattr(action_instance, "chat_id", "") or getattr(action_instance, "stream_id", "")

    # ==================== 当前消息内提取 ====================

    @staticmethod
    def _current_message_obj(action: Any) -> Any:
        """返回 command 路径的触发消息 dict；Tool 路径无 message 时为 None"""
        return getattr(action, "message", None)

    def _extract_image_from_current_dict(self, message: dict) -> Optional[str]:
        """从 SDK 2.x RPC 序列化的 dict 消息里直接抓 base64

        host 给 command 入口 include_binary_data=False，绝大多数情况下
        image 段不会带 binary_data_base64；找到 hash 时返回 ``hash:<v>`` 让上层
        再通过 ctx.message.get_by_id(include_binary_data=True) 回填。
        """
        raw = message.get("raw_message")
        if not isinstance(raw, list):
            return None

        first_hash: Optional[str] = None
        target_msg_id: Optional[str] = None

        for seg in raw:
            if not isinstance(seg, dict):
                continue
            stype = str(seg.get("type") or "").lower()

            if stype in ("image", "emoji"):
                b64 = seg.get("binary_data_base64")
                if isinstance(b64, str) and b64:
                    logger.info(f"{self.log_prefix} 从当前消息段直接取到图片 base64")
                    return b64
                if first_hash is None:
                    raw_hash = seg.get("hash") or seg.get("data")
                    if isinstance(raw_hash, str) and raw_hash:
                        first_hash = raw_hash

            elif stype == "reply":
                data = seg.get("data") or {}
                if isinstance(data, dict):
                    tid = data.get("target_message_id")
                    if isinstance(tid, str) and tid:
                        target_msg_id = tid

        if first_hash:
            return f"hash::{first_hash}"
        if target_msg_id:
            return f"reply::{target_msg_id}"
        return None

    def _extract_image_from_legacy_seg(self, message: Any) -> Optional[str]:
        """兼容 message_segment 树 / SessionMessage.raw_message.components 的老对象形态"""
        # 老 Seg 树
        seg = getattr(message, "message_segment", None)
        if seg is not None:
            for b64 in self.find_and_return_emoji_in_message(seg):
                if isinstance(b64, str) and b64:
                    return b64

        # SessionMessage.raw_message.components
        raw_msg = getattr(message, "raw_message", None)
        components = getattr(raw_msg, "components", None) if raw_msg is not None else None
        if isinstance(components, (list, tuple)):
            for comp in components:
                cls_name = type(comp).__name__
                if cls_name in ("ImageComponent", "EmojiComponent"):
                    binary = getattr(comp, "binary_data", None)
                    if isinstance(binary, (bytes, bytearray)) and binary:
                        return base64.b64encode(bytes(binary)).decode("utf-8")
                    content = getattr(comp, "content", None)
                    if isinstance(content, str) and content:
                        return content
        return None

    # ==================== ctx capability 路径 ====================

    async def _fetch_image_by_message_id(self, message_id: str) -> Optional[str]:
        """通过 ctx.message.get_by_id(include_binary_data=True) 拉回完整消息并抓图"""
        if self._ctx is None or not message_id:
            return None
        try:
            full = await self._ctx.message.get_by_id(
                message_id=message_id,
                chat_id=self._chat_id or "",
                include_binary_data=True,
            )
        except Exception as e:
            logger.debug(f"{self.log_prefix} get_by_id 失败 ({message_id}): {e}")
            return None
        if not isinstance(full, dict):
            return None
        return self._scan_raw_for_binary(full.get("raw_message"))

    async def fetch_image_by_triggering_id(
        self,
        triggering_message_id: Optional[str],
    ) -> Optional[str]:
        """Tool 路径专用：依据 LLM 透传的 msg_id 100% 锁定触发消息抓图。

        查找顺序：
        1. 触发消息自身含 image/emoji 段 → 直接返回
        2. 触发消息含 reply（看 reply_to 快捷字段，缺则扫 raw_message 的 reply 段）
           → 拉被引用消息再抓图
        """
        if self._ctx is None or not triggering_message_id:
            return None

        try:
            message = await self._ctx.message.get_by_id(
                message_id=triggering_message_id,
                chat_id=self._chat_id or "",
                include_binary_data=True,
            )
        except Exception as e:
            logger.debug(f"{self.log_prefix} get_by_id 失败 ({triggering_message_id}): {e}")
            return None
        if not isinstance(message, dict):
            return None

        b64 = self._scan_raw_for_binary(message.get("raw_message"))
        if b64:
            logger.info(f"{self.log_prefix} 触发消息含图，按 msg_id 直接命中")
            return b64

        target_id = str(message.get("reply_to") or "").strip()
        if not target_id:
            for seg in message.get("raw_message") or []:
                if not isinstance(seg, dict):
                    continue
                if str(seg.get("type") or "").lower() != "reply":
                    continue
                data = seg.get("data") or {}
                if isinstance(data, dict):
                    target_id = str(data.get("target_message_id") or "").strip()
                if target_id:
                    break

        if target_id:
            logger.info(f"{self.log_prefix} 触发消息引用了 {target_id}，拉被引用消息取图")
            return await self._fetch_image_by_message_id(target_id)

        return None

    @staticmethod
    def _scan_raw_for_binary(raw: Any) -> Optional[str]:
        """从 raw_message（list[dict]）中找带 binary_data_base64 的 image/emoji 段"""
        if not isinstance(raw, list):
            return None
        for seg in raw:
            if not isinstance(seg, dict):
                continue
            stype = str(seg.get("type") or "").lower()
            if stype not in ("image", "emoji"):
                continue
            b64 = seg.get("binary_data_base64")
            if isinstance(b64, str) and b64:
                return b64
        return None

    # ==================== 主入口 ====================

    async def get_recent_image(self) -> Optional[str]:
        """严格模式：仅从触发消息本身解析图片（base64），找不到返回 None。

        查找顺序：
        1. 当前消息含 image/emoji 段（直接 base64 或 hash → get_by_id 回填）
        2. 当前消息含 reply 段 → 拉被引用消息取图

        不再扫描聊天历史——LLM Tool 路径 SDK 未暴露触发 message_id，无法 100% 定位用户消息；
        命令路径直接走 dctx.message。
        """
        try:
            message = self._current_message_obj(self.action)

            if message is None:
                logger.info(f"{self.log_prefix} 无触发消息上下文（Tool 路径），跳过图生图检测")
                return None

            if isinstance(message, dict):
                hit = self._extract_image_from_current_dict(message)
                if hit and not hit.startswith(("hash::", "reply::")):
                    logger.info(f"{self.log_prefix} 从当前消息段直接取到图片（{len(hit)} bytes b64）")
                    return hit
                if hit and hit.startswith("hash::"):
                    msg_id = message.get("message_id")
                    h = hit.removeprefix("hash::")
                    logger.info(f"{self.log_prefix} 当前消息有图片 hash={h[:16]}…，回拉本条消息取 binary")
                    if isinstance(msg_id, str) and msg_id:
                        refetched = await self._fetch_image_by_message_id(msg_id)
                        if refetched:
                            return refetched
                if hit and hit.startswith("reply::"):
                    target_id = hit.removeprefix("reply::")
                    logger.info(f"{self.log_prefix} 检测到引用消息 target_message_id={target_id}，拉取被引用消息取图")
                    refetched = await self._fetch_image_by_message_id(target_id)
                    if refetched:
                        return refetched
                    logger.warning(f"{self.log_prefix} 被引用消息 {target_id} 取图失败")
            else:
                hit = self._extract_image_from_legacy_seg(message)
                if hit:
                    return hit

            logger.info(f"{self.log_prefix} 触发消息中未找到图片，走文生图")
            return None

        except Exception as e:
            logger.error(f"{self.log_prefix} 获取图片失败: {e!r}", exc_info=True)
            return None

    # ==================== 兼容旧 API ====================

    def find_and_return_emoji_in_message(self, message_segments) -> List[str]:
        """从消息中查找并返回表情包/图片的 base64 数据列表（老 Seg 树兼容）"""
        emoji_base64_list: List[str] = []

        if isinstance(message_segments, Seg):
            if message_segments.type in ("emoji", "image"):
                if isinstance(message_segments.data, str):
                    emoji_base64_list.append(message_segments.data)
            elif message_segments.type == "seglist":
                emoji_base64_list.extend(self.find_and_return_emoji_in_message(message_segments.data))
            return emoji_base64_list

        if isinstance(message_segments, (list, tuple)):
            for seg in message_segments:
                if not isinstance(seg, Seg):
                    continue
                if seg.type in ("emoji", "image"):
                    if isinstance(seg.data, str):
                        emoji_base64_list.append(seg.data)
                elif seg.type == "seglist":
                    emoji_base64_list.extend(self.find_and_return_emoji_in_message(seg.data))
        return emoji_base64_list

    # ==================== 通用工具 ====================

    def download_and_encode_base64(self, image_url: str, proxy_url: str = None) -> Tuple[bool, str]:
        """下载图片或处理 Base64 数据 URL

        Args:
            image_url: 图片 URL 或 data:image/ 数据 URL
            proxy_url: 代理地址（如 http://127.0.0.1:7890），为空则直连
        """
        logger.info(f"{self.log_prefix} (B64) 处理图片: {image_url[:50]}...")

        try:
            if image_url.startswith('data:image/'):
                logger.info(f"{self.log_prefix} (B64) 检测到 Base64 数据 URL")
                if ';base64,' in image_url:
                    base64_data = image_url.split(';base64,', 1)[1]
                    logger.info(f"{self.log_prefix} (B64) 提取完成, 长度: {len(base64_data)}")
                    return True, base64_data
                error_msg = "Base64 数据 URL 格式不正确"
                logger.error(f"{self.log_prefix} (B64) {error_msg}")
                return False, error_msg

            if proxy_url:
                import requests
                logger.info(f"{self.log_prefix} (B64) 下载 HTTP 图片 (proxy: {proxy_url})")
                resp = requests.get(image_url, timeout=180, proxies={"http": proxy_url, "https": proxy_url})
                if resp.status_code == 200:
                    base64_encoded_image = base64.b64encode(resp.content).decode("utf-8")
                    logger.info(f"{self.log_prefix} (B64) 下载编码完成, 长度: {len(base64_encoded_image)}")
                    return True, base64_encoded_image
                error_msg = f"下载图片失败 (状态: {resp.status_code})"
                logger.error(f"{self.log_prefix} (B64) {error_msg} URL: {image_url[:30]}...")
                return False, error_msg

            logger.info(f"{self.log_prefix} (B64) 下载 HTTP 图片")
            with urllib.request.urlopen(image_url, timeout=180) as response:
                if response.status == 200:
                    image_bytes = response.read()
                    base64_encoded_image = base64.b64encode(image_bytes).decode("utf-8")
                    logger.info(f"{self.log_prefix} (B64) 下载编码完成, 长度: {len(base64_encoded_image)}")
                    return True, base64_encoded_image
                error_msg = f"下载图片失败 (状态: {response.status})"
                logger.error(f"{self.log_prefix} (B64) {error_msg} URL: {image_url[:30]}...")
                return False, error_msg

        except Exception as e:
            logger.error(f"{self.log_prefix} (B64) 处理图片时错误: {e!r}", exc_info=True)
            traceback.print_exc()
            return False, f"处理图片时发生错误: {str(e)[:50]}"

    def process_api_response(self, result) -> Optional[str]:
        """统一处理 API 响应，提取图片数据"""
        try:
            if isinstance(result, str):
                return result

            if isinstance(result, dict):
                for key in ['url', 'image', 'b64_json', 'data']:
                    if key in result and result[key]:
                        return result[key]

                if 'output' in result and isinstance(result['output'], dict):
                    output = result['output']
                    for key in ['image_url', 'images']:
                        if key in output:
                            data = output[key]
                            return data[0] if isinstance(data, list) and data else data

            return None
        except Exception as e:
            logger.error(f"{self.log_prefix} 处理 API 响应失败: {str(e)[:50]}")
            return None
