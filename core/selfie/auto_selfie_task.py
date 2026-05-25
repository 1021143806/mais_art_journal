"""自动自拍后台任务

定时执行自拍流程：
1. 从 ScheduleProvider 获取当前活动
2. 用 prompts.selfie_prompt_builder.build_for_activity 生成 prompt + negative
3. 走 build_auto_selfie_pipeline() 出图
4. 用 caption_generator 生成配文
5. 通过 ctx.api.call("Rabbit-Jia-Er.MaiTrace.send_feed_api") 发布到 QQ 空间说说

特性：
- 可配置间隔（如每 2 小时）
- 安静时段控制
- 无日程数据 → 跳过
- 连续失败指数退避
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import TYPE_CHECKING, Optional

from ..config import get_model_config
from ..pipeline import GenerationRequest, build_auto_selfie_pipeline, make_pipeline_context
from ..prompts import build_auto_selfie_prompt
from ..utils import is_in_time_range
from .caption_generator import generate_caption
from .schedule_provider import get_schedule_provider

if TYPE_CHECKING:
    from ..plugin import MaisArtPlugin

logger = logging.getLogger("plugin.mais_art_journal.auto_selfie")


class AutoSelfieTask:
    """自动自拍后台定时任务"""

    # 连续失败达到此次数后，等待时间翻倍
    _MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, plugin: "MaisArtPlugin"):
        self.plugin = plugin
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._pipeline = build_auto_selfie_pipeline()

    async def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.task = asyncio.create_task(self._selfie_loop())
        logger.info("自动自拍任务已启动")

    async def stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("自动自拍任务已停止")

    # ==================== 主循环 ====================

    def _is_quiet_hours(self) -> bool:
        quiet_start = self.plugin.config.selfie.quiet_hours_start or "00:00"
        quiet_end = self.plugin.config.selfie.quiet_hours_end or "07:00"
        return is_in_time_range(quiet_start, quiet_end)

    async def _selfie_loop(self) -> None:
        await asyncio.sleep(30)  # 启动延迟，避免和主程序抢资源

        interval = max(int(self.plugin.config.selfie.interval_minutes or 120), 10)
        interval_seconds = interval * 60

        while self.is_running:
            try:
                if self._is_quiet_hours():
                    logger.debug("当前在安静时段，跳过自拍")
                else:
                    await self._execute_selfie()
                    self._consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_failures += 1
                logger.error(f"自拍任务执行出错 (连续第{self._consecutive_failures}次): {e}")

            backoff_multiplier = 2 ** (self._consecutive_failures // self._MAX_CONSECUTIVE_FAILURES)
            sleep_seconds = interval_seconds * backoff_multiplier
            if backoff_multiplier > 1:
                logger.warning(
                    f"连续失败 {self._consecutive_failures} 次，下次自拍间隔延长至 {sleep_seconds // 60} 分钟"
                )
            await asyncio.sleep(sleep_seconds)

    # ==================== 单次自拍 ====================

    async def _execute_selfie(self) -> None:
        logger.info("开始执行自动自拍流程...")

        # 1. 获取当前活动
        provider = get_schedule_provider(ctx=self.plugin.ctx, chat_id="global")
        activity = await provider.get_current_activity() if provider else None
        if not activity:
            logger.info("未获取到当前活动信息，跳过本次自拍")
            return

        logger.info(f"当前活动: {activity.description} ({activity.activity_type.value})")

        # 2. 生成自拍提示词（LLM 失败则跳过）
        selfie_style = self.plugin.config.selfie.default_style
        bot_appearance = self.plugin.config.selfie.prompt_prefix or ""
        base_negative = self.plugin.config.selfie.negative_prompt or ""
        llm_task = self.plugin.config.basic.llm_task_name or "utils"

        prompt_result = await build_auto_selfie_prompt(
            ctx=self.plugin.ctx,
            activity_info=activity,
            selfie_style=selfie_style,
            bot_appearance=bot_appearance,
            base_negative=base_negative,
            llm_task=llm_task,
            log_prefix="[AutoSelfie]",
        )
        if prompt_result is None:
            logger.warning("LLM 自拍提示词生成失败，跳过本次自拍")
            return

        # 3. 走 pipeline 生图（不发送 / 不缓存 / 不撤回）
        selfie_model = self.plugin.config.selfie.selfie_model or "model1"
        model_cfg = get_model_config(self.plugin, selfie_model)
        if not model_cfg:
            logger.error(f"模型配置获取失败: {selfie_model}")
            return

        reference_image = self._load_reference_image()
        input_image_b64: Optional[str] = None
        strength: Optional[float] = None
        if reference_image and model_cfg.get("support_img2img", True):
            input_image_b64 = reference_image
            strength = 0.6
            logger.info("使用参考图片进行图生图自拍")
        elif reference_image:
            logger.warning(f"模型 {selfie_model} 不支持图生图，回退文生图")

        req = GenerationRequest(
            description=prompt_result.prompt,
            model_id=selfie_model,
            size=model_cfg.get("default_size", "1024x1024"),
            strength=strength,
            input_image_base64=input_image_b64,
            extra_negative_prompt=prompt_result.negative_prompt,
            send_image=False,
            update_cache=False,
            schedule_recall=False,
            debug_info=False,
            silent_img2img_fallback=True,
            stream_id="",
            chat_id="",
            log_prefix="[AutoSelfie]",
            source="auto_selfie",
        )
        ctx = make_pipeline_context(self.plugin, req)
        out = await self._pipeline.run(req, ctx)

        if not out.success or not out.resolved_image_data:
            logger.error(f"自拍图片生成失败: {out.error or '无图片数据'}")
            raise RuntimeError(f"自拍生图失败: {out.error or '未知错误'}")

        logger.info(f"自拍图片生成成功，数据长度: {len(out.resolved_image_data)}")

        # 4. 配文
        caption = ""
        if self.plugin.config.selfie.caption_enabled:
            caption = await generate_caption(self.plugin.ctx, activity, llm_task=llm_task)
            if not caption:
                logger.warning("配文生成失败，跳过本次自拍发布")
                return
            logger.info(f"配文: {caption}")

        # 5. 发布到 QQ 空间
        await self._publish_to_qzone(out.resolved_image_data, caption)

    # ==================== 工具 ====================

    def _load_reference_image(self) -> Optional[str]:
        path = (self.plugin.config.selfie.reference_image_path or "").strip()
        if not path:
            return None
        try:
            if not os.path.isabs(path):
                path = os.path.join(self.plugin.plugin_dir, path)
            if not os.path.exists(path):
                logger.warning(f"[AutoSelfie] 自拍参考图片文件不存在: {path}")
                return None
            with open(path, "rb") as f:
                data = f.read()
            logger.info(f"[AutoSelfie] 从文件加载自拍参考图片: {path}")
            return base64.b64encode(data).decode("utf-8")
        except Exception as e:
            logger.error(f"[AutoSelfie] 加载自拍参考图片失败: {e}")
            return None

    async def _publish_to_qzone(self, image_data: str, caption: str) -> None:
        """通过 MaiTrace 插件暴露的 send_feed_api 发说说

        MaiTrace v3+ API 契约（plugins/MaiTrace/handlers/apis.py）：
            ctx.api.call(
                "Rabbit-Jia-Er.MaiTrace.send_feed_api",
                message=<str>,
                images=<list[str]>,   # base64 字符串列表，不含 data:image/... 前缀
            ) -> {"result": bool, "message": str}

        pipeline 出来的 image_data 已经是纯 base64 字符串（ResolveImageData step 保证），
        直接透传即可。MaiTrace 内部会 b64decode 成 bytes 再上传 QQ 空间。

        当 MaiTrace 未安装 / 未启用 / 未授权 api.call 时，本方法捕获异常仅 warning，
        不影响自动自拍主流程。
        """
        try:
            image_b64 = await self._normalize_to_base64(image_data)
            if not image_b64:
                logger.error("图片数据无效，无法发布到 QQ 空间")
                return

            try:
                result = await self.plugin.ctx.api.call(
                    "Rabbit-Jia-Er.MaiTrace.send_feed_api",
                    message=caption,
                    images=[image_b64],
                )
            except Exception as exc:
                logger.warning(
                    f"调用 MaiTrace.send_feed_api 失败"
                    f"（MaiTrace 未安装 / 未启用 / api.call 未授权?）: {exc}"
                )
                return

            if not isinstance(result, dict):
                logger.warning(f"MaiTrace.send_feed_api 返回非字典: {result!r}")
                return

            if result.get("result"):
                logger.info(f"自拍已发布到 QQ 空间: {result.get('message', '')}")
            else:
                logger.error(f"发布自拍到 QQ 空间失败: {result.get('message', '未知错误')}")

        except Exception as e:
            logger.error(f"发布自拍到 QQ 空间异常: {e}", exc_info=True)

    @staticmethod
    async def _normalize_to_base64(image_data: str) -> Optional[str]:
        """把 image_data 统一成纯 base64 字符串

        pipeline 的 ResolveImageData step 保证 ``out.resolved_image_data`` 已经是纯 base64，
        本方法只是对 URL / data URI 形态做兜底（理论上不会触发）。
        """
        if not image_data:
            return None
        if image_data.startswith(("http://", "https://")):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(image_data)
                    resp.raise_for_status()
                    return base64.b64encode(resp.content).decode("utf-8")
            except Exception as exc:
                logger.error(f"image_data 是 URL 但下载失败: {exc}")
                return None
        if image_data.startswith("data:image/") and ";base64," in image_data:
            return image_data.split(";base64,", 1)[1]
        # 纯 base64 字符串，直接返回
        return image_data
