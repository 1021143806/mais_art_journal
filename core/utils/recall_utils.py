"""自动撤回工具

- 记录发送时间戳，精确筛选消息
- 轮询多次获取消息 ID（应对平台回调延迟）
- 只匹配图片消息，避免误撤回文字
- 区分真实 ID 和占位 ID，占位 ID 会二次解析
"""

import asyncio
import logging
import time as time_module
from typing import TYPE_CHECKING, Callable, Awaitable, Any, Optional

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

logger = logging.getLogger("plugin.mais_art_journal.recall")

# ==================== 消息匹配工具 ====================

def _msg_get(msg, key, default=None):
    """统一从 dict 或对象属性读取字段"""
    if isinstance(msg, dict):
        return msg.get(key, default)
    return getattr(msg, key, default)


def _is_image_message(msg) -> bool:
    """判断消息是否为图片消息"""
    # 方法1：检查 message_segment
    seg = _msg_get(msg, "message_segment")
    if seg is not None:
        seg_type = _msg_get(seg, "type")
        if seg_type in ("image", "imageurl", "emoji"):
            return True
        # 递归检查 seglist
        if seg_type == "seglist":
            data = _msg_get(seg, "data")
            if data and isinstance(data, (list, tuple)):
                for child in data:
                    child_type = _msg_get(child, "type")
                    if child_type in ("image", "imageurl", "emoji"):
                        return True

    # 方法2：检查 is_picid 标记
    if _msg_get(msg, "is_picid", False):
        return True

    # 方法3：检查文本特征
    text = _msg_get(msg, "processed_plain_text") or _msg_get(msg, "raw_message") or ""

    text_lower = str(text).strip().lower()
    image_prefixes = ("[图片", "[image", "[imageurl", "[picid", "picid:")
    for prefix in image_prefixes:
        if text_lower.startswith(prefix):
            return True

    return False


def _extract_user_id(msg) -> Optional[str]:
    """从消息中提取发送者用户 ID"""
    # message_info.user_info.user_id
    msg_info = _msg_get(msg, "message_info")
    if msg_info:
        user_info = _msg_get(msg_info, "user_info")
        if user_info:
            uid = _msg_get(user_info, "user_id")
            if uid:
                return str(uid)

    # user_info.user_id（直接属性）
    user_info = _msg_get(msg, "user_info")
    if user_info:
        uid = _msg_get(user_info, "user_id")
        if uid:
            return str(uid)

    # 直接 user_id
    uid = _msg_get(msg, "user_id")
    if uid:
        return str(uid)

    return None


def _get_message_time(msg) -> float:
    """获取消息的时间戳"""
    t = _msg_get(msg, "time")
    if t is not None:
        return float(t)
    t = _msg_get(msg, "timestamp")
    if t is not None:
        return float(t)
    return 0.0


# ==================== 核心逻辑 ====================

async def _find_bot_image_message_id(
    ctx: "PluginContext",
    chat_id: str,
    send_timestamp: float,
    log_prefix: str,
    poll_attempts: int = 5,
    poll_interval: float = 0.5,
) -> Optional[str]:
    """轮询查找 Bot 发送的图片消息 ID

    Args:
        ctx: PluginContext（用于读 bot.qq_account 和查消息）
        chat_id: 聊天流 ID
        send_timestamp: 图片发送时的时间戳
        log_prefix: 日志前缀
        poll_attempts: 轮询次数
        poll_interval: 每次轮询间隔（秒）

    Returns:
        消息 ID 字符串，找不到返回 None
    """
    # 读取 bot QQ 号；取不到时降级为只按时间窗口匹配最近图片消息
    bot_id_raw = await ctx.config.get("bot.qq_account", "")
    bot_id = str(bot_id_raw) if bot_id_raw else ""
    placeholder_id = None

    for attempt in range(poll_attempts):
        try:
            messages = await ctx.message.get_by_time_in_chat(
                chat_id=chat_id,
                start_time=send_timestamp - 2,
                end_time=time_module.time() + 1,
                limit=10,
                limit_mode="latest",
            )
        except Exception as e:
            logger.debug(f"{log_prefix} 查询消息失败 (第{attempt + 1}次): {e}")
            await asyncio.sleep(poll_interval)
            continue

        if not isinstance(messages, list):
            messages = []

        # 倒序遍历（最新的在前）
        for msg in reversed(messages):
            # 只匹配图片消息
            if not _is_image_message(msg):
                continue

            # 只匹配 Bot 自己发的（拿不到 bot_id 时跳过该过滤）
            sender_id = _extract_user_id(msg)
            if bot_id:
                if sender_id and sender_id != bot_id:
                    continue
                if not sender_id:
                    # 无法确认发送者，宁可不撤回也不误撤回
                    continue

            # 检查时间：必须在发送时间之后
            msg_time = _get_message_time(msg)
            if msg_time > 0 and msg_time < send_timestamp - 1:
                continue

            mid = str(_get_message_id(msg))
            if not mid:
                continue

            # 优先选真实 ID（纯数字），占位 ID 作为后备
            if mid.isdigit():
                logger.info(
                    f"{log_prefix} 找到目标消息 ID: {mid} (第{attempt + 1}次轮询)"
                )
                return mid
            elif not mid.startswith("send_api_"):
                # 非标准格式但也非占位符，可以尝试
                logger.info(
                    f"{log_prefix} 找到非标准消息 ID: {mid} (第{attempt + 1}次轮询)"
                )
                return mid
            else:
                placeholder_id = mid

        if attempt < poll_attempts - 1:
            await asyncio.sleep(poll_interval)

    if placeholder_id:
        logger.warning(f"{log_prefix} 仅找到占位消息 ID: {placeholder_id}")
    else:
        logger.warning(f"{log_prefix} 未找到 Bot 的图片消息 ID")

    return placeholder_id


def _get_message_id(msg) -> str:
    """从消息对象兼容性提取 message_id"""
    mid = ""
    if isinstance(msg, dict):
        mid = msg.get("message_id") or msg.get("id") or ""
    else:
        mid = getattr(msg, "message_id", "") or getattr(msg, "id", "")
    return str(mid or "")


async def schedule_auto_recall(
    ctx: "PluginContext",
    chat_id: str,
    delay_seconds: int,
    log_prefix: str,
    send_timestamp: float = 0.0,
):
    """安排消息自动撤回后台任务

    Args:
        ctx: PluginContext（用于查消息历史和读 bot 配置）
        chat_id: 聊天流 ID
        delay_seconds: 撤回延时（秒）
        log_prefix: 日志前缀
        send_timestamp: 图片发送时的时间戳（time.time()），
            0 表示使用当前时间
    """
    if send_timestamp <= 0:
        send_timestamp = time_module.time()

    async def _recall_task():
        try:
            # 等待消息入库
            await asyncio.sleep(1.0)

            # 轮询获取消息 ID
            target_message_id = await _find_bot_image_message_id(
                ctx, chat_id, send_timestamp, log_prefix
            )

            if not target_message_id:
                logger.warning(f"{log_prefix} 无法获取消息 ID，放弃撤回")
                return

            logger.info(
                f"{log_prefix} 安排自动撤回，延时: {delay_seconds}秒，消息ID: {target_message_id}"
            )

            # 等待撤回延时
            await asyncio.sleep(delay_seconds)

            # 如果之前拿到的是占位 ID，再尝试解析一次真实 ID
            if target_message_id.startswith("send_api_"):
                resolved = await _find_bot_image_message_id(
                    ctx, chat_id, send_timestamp, log_prefix,
                    poll_attempts=3, poll_interval=1.0,
                )
                if resolved and not resolved.startswith("send_api_"):
                    logger.info(f"{log_prefix} 占位 ID 解析为真实 ID: {resolved}")
                    target_message_id = resolved

            # 尝试撤回
            success = await _try_recall_message(
                target_message_id, ctx, log_prefix
            )
            if not success:
                logger.warning(
                    f"{log_prefix} 自动撤回失败，消息ID: {target_message_id}"
                )

        except asyncio.CancelledError:
            logger.debug(f"{log_prefix} 自动撤回任务被取消")
        except Exception as e:
            logger.error(f"{log_prefix} 自动撤回异常: {e}")

    asyncio.create_task(_recall_task())


async def _try_recall_message(
    message_id: str,
    ctx: "PluginContext",
    log_prefix: str,
) -> bool:
    """尝试撤回消息

    使用 ctx.api.call 调用 NapCat 适配器的 delete_msg API。
    """
    # message_id 优先用数字（NapCat 的 number 形式更可靠），失败时回退字符串
    candidates: list[Any] = []
    try:
        candidates.append(int(message_id))
    except (TypeError, ValueError):
        pass
    candidates.append(str(message_id))

    for mid in candidates:
        try:
            # 使用 NapCat 适配器的 API
            result = await ctx.api.call(
                "adapter.napcat.message.delete_msg",
                message_id=mid
            )
        except Exception as e:
            logger.debug(f"{log_prefix} delete_msg({mid!r}) 调用异常: {e}")
            continue

        if _is_recall_success(result):
            logger.info(f"{log_prefix} 撤回成功，message_id={mid!r}")
            return True
        logger.debug(f"{log_prefix} delete_msg({mid!r}) 返回非成功: {result!r}")

    return False


def _is_recall_success(result: Any) -> bool:
    """判定 send.command 返回值是否表示成功

    SDK 的 send.command 在 host 端被归一化为 bool（cap.send.command 走的是
    `_BOOLEAN_SUCCESS_CAPABILITIES`）；但适配器实现可能直接透传 dict，所以
    这里两种都识别。
    """
    if isinstance(result, bool):
        return result
    if isinstance(result, dict):
        if result.get("success") is True:
            return True
        status = str(result.get("status", "")).lower()
        if status in ("ok", "success"):
            return True
        if result.get("retcode") == 0 or result.get("code") == 0:
            return True
    return False
