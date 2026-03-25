import traceback
import base64
import os
import time as time_module
from typing import Tuple, Optional, Dict, Any

from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ActionActivationType, ChatMode
from src.common.logger import get_logger

from .api_clients import get_client_class
from .utils import (
    ImageProcessor, CacheManager, validate_image_size, get_image_size,
    runtime_state,
    get_model_config, merge_negative_prompt, inject_llm_original_size,
    resolve_image_data, schedule_auto_recall, optimize_prompt,
)

logger = get_logger("mais_art")

class MaisArtAction(BaseAction):
    """统一的图片生成动作，智能检测文生图或图生图"""

    # 激活设置
    activation_type = ActionActivationType.ALWAYS  # 默认激活类型
    focus_activation_type = ActionActivationType.ALWAYS  # Focus模式使用LLM判定，精确理解需求
    normal_activation_type = ActionActivationType.KEYWORD  # Normal模式使用关键词激活，快速响应
    mode_enable = ChatMode.ALL
    parallel_action = True

    # 动作基本信息
    action_name = "draw_picture"
    action_description = (
        "智能图片生成：根据描述生成图片（文生图）或基于现有图片进行修改（图生图）。"
        "自动检测用户是否提供了输入图片来决定使用文生图还是图生图模式。"
        "支持多种API格式：OpenAI、豆包、Gemini、硅基流动、魔搭社区、砂糖云(NovelAI)、ComfyUI、梦羽AI等。"
    )

    # 关键词设置（用于Normal模式）
    activation_keywords = [
        # 文生图关键词
        "画", "绘制", "生成图片", "画图", "draw", "paint", "图片生成", "创作",
        # 图生图关键词
        "图生图", "修改图片", "基于这张图", "img2img", "重画", "改图", "图片修改",
        "改成", "换成", "变成", "转换成", "风格", "画风", "改风格", "换风格",
        "这张图", "这个图", "图片风格", "改画风", "重新画", "再画", "重做",
        # 自拍关键词
        "自拍", "selfie", "拍照", "对镜自拍", "镜子自拍", "照镜子"
    ]

    # LLM判定提示词（用于Focus模式）
    ALWAYS_prompt = """
判定是否需要使用图片生成动作的条件：

**核心原则：只有在用户明确对你提出画图请求时才使用。在群聊中，必须是用户@你或点名叫你来画图。**

**文生图场景：**
1. 用户明确@你的名字或叫你的名字，要求画图、生成图片或创作图像
2. 用户在私聊中直接要求你画某个内容

**图生图场景：**
1. 用户发送了图片并@你的名字，要求基于该图片进行修改或重新生成
2. 用户明确@你并提到"图生图"、"修改图片"、"基于这张图"等关键词

**自拍场景：**
1. 用户明确@你或叫你的名字，要求你自拍、拍照
2. 用户在私聊中要求你自拍

**绝对不要使用的情况：**
1. 群聊中用户没有@你或叫你的名字，即使消息内容涉及画图
2. 其他机器人的命令（如/nai、/sd、/mj等），这些是发给其他机器人的，不是对你的请求
3. 用户只是在描述场景或事物，并没有要求你画图
4. 纯文字聊天和问答
5. 只是提到"图片"、"画"等词但不是在要求你生成
6. 谈论已存在的图片或照片（仅讨论不修改）
7. 技术讨论中提到绘图概念但无生成需求
8. 用户明确表示不需要图片时
9. 刚刚成功生成过图片，避免频繁请求
10. 你主动想画图但用户没有要求——不要自作主张
"""

    keyword_case_sensitive = False

    # 动作参数定义（简化版，提示词优化由独立模块处理）
    action_parameters = {
        "description": "从用户消息中提取的图片描述文本（例如：用户说'画一只小猫'，则填写'一只小猫'）。必填参数。",
        "model_id": "要使用的模型ID（如model1、model2、model3等，默认使用default_model配置的模型）",
        "strength": "图生图强度，0.1-1.0之间，值越高变化越大（仅图生图时使用，可选，默认0.7）",
        "size": "图片尺寸，如512x512、1024x1024等（可选，不指定则使用模型默认尺寸）",
        "selfie_mode": "是否启用自拍模式（true/false，可选，默认false）。启用后会自动添加自拍场景和手部动作",
        "selfie_style": "自拍风格，可选值：standard（标准自拍，前置摄像头视角），mirror（对镜自拍，室内镜子场景），photo（第三人称照片，他人拍摄视角，自然姿态）。仅在selfie_mode=true时生效，可选，默认standard",
        "free_hand_action": "自由手部动作描述（英文）。如果指定此参数，将使用此动作而不是随机生成。仅在selfie_mode=true时生效，可选"
    }

    # 动作使用场景
    action_require = [
        "当用户明确对你提出生成或修改图片请求时使用，不要频率太高",
        "群聊中必须是用户@你或叫你名字要求画图才使用，不要响应发给其他机器人的命令（如/nai、/sd等）",
        "自动检测是否有输入图片来决定文生图或图生图模式",
        "重点：不要连续发，如果你在前10句内已经发送过[图片]或者[表情包]或记录出现过类似描述的[图片]，就不要选择此动作",
        "支持指定模型：用户可以通过'用模型1画'、'model2生成'等方式指定特定模型",
        "自拍模式选择：用户要求'自拍/拍个自拍'时用standard；要求'照镜子/对镜拍'时用mirror；要求'拍张照片/画一张你在XX的照片/第三人称'等非自拍视角时用photo"
    ]
    associated_types = ["text", "image"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_processor = ImageProcessor(self)
        self.cache_manager = CacheManager(self)
        self._api_clients = {}  # 缓存不同格式的API客户端

    def _get_api_client(self, api_format: str):
        """获取指定格式的API客户端（带缓存）"""
        if api_format not in self._api_clients:
            client_class = get_client_class(api_format)
            self._api_clients[api_format] = client_class(self)
        return self._api_clients[api_format]

    async def execute(self) -> Tuple[bool, Optional[str]]:
        """执行统一图片生成动作"""
        logger.info(f"{self.log_prefix} 执行统一图片生成动作")

        # 懒启动自动自拍任务（如果插件初始化时事件循环未就绪）
        try:
            from src.plugin_system.core.plugin_manager import plugin_manager
            plugin_instance = plugin_manager.get_plugin_instance("mais_art_journal")
            if plugin_instance and hasattr(plugin_instance, 'try_start_auto_selfie'):
                plugin_instance.try_start_auto_selfie()
        except Exception:
            pass

        # 检查是否是 /dr 命令消息，如果是则跳过（由 Command 组件处理）
        if self.action_message and self.action_message.processed_plain_text:
            message_text = self.action_message.processed_plain_text.strip()
            if message_text.startswith("/dr ") or message_text == "/dr":
                logger.info(f"{self.log_prefix} 检测到 /dr 命令，跳过 Action 处理（由 Command 组件处理）")
                return False, "跳过 /dr 命令"

        # 检查插件是否在当前聊天流启用
        global_enabled = self.get_config("plugin.enabled", True)
        if not runtime_state.is_plugin_enabled(self.chat_id, global_enabled):
            logger.info(f"{self.log_prefix} 插件在当前聊天流已禁用")
            return False, "插件已禁用"

        # 获取参数
        description = self.action_data.get("description", "").strip()
        model_id = self.action_data.get("model_id", "").strip()
        strength = self.action_data.get("strength", 0.7)
        size = self.action_data.get("size", "").strip()
        selfie_mode_raw = self.action_data.get("selfie_mode", False)
        selfie_mode = selfie_mode_raw in (True, "true", "True", 1, "1")
        selfie_style_llm = self.action_data.get("selfie_style", "").strip().lower()
        free_hand_action = self.action_data.get("free_hand_action", "").strip()

        # 自拍风格优先级：运行时命令设置 > LLM 指定 > 全局配置
        global_style = self.get_config("selfie.default_style", "standard")
        runtime_style = runtime_state.get_selfie_style(self.chat_id, None)
        if runtime_style is not None:
            selfie_style = runtime_style
        elif selfie_style_llm in ("standard", "mirror", "photo"):
            selfie_style = selfie_style_llm
        else:
            selfie_style = global_style

        # 如果没有指定模型，使用运行时状态的默认模型
        if not model_id:
            global_default = self.get_config("generation.default_model", "model1")
            model_id = runtime_state.get_action_default_model(self.chat_id, global_default)

        # 检查模型是否在当前聊天流启用
        if not runtime_state.is_model_enabled(self.chat_id, model_id):
            logger.warning(f"{self.log_prefix} 模型 {model_id} 在当前聊天流已禁用")
            await self.send_text(f"模型 {model_id} 当前不可用")
            return False, f"模型 {model_id} 已禁用"

        # 参数验证和后备提取
        if not description:
            # 尝试从action_message中提取描述
            extracted_description = self._extract_description_from_message()
            if extracted_description:
                description = extracted_description
                logger.info(f"{self.log_prefix} 从消息中提取到图片描述: {description}")
            else:
                logger.warning(f"{self.log_prefix} 图片描述为空，无法生成图片。")
                await self.send_text("你需要告诉我想要画什么样的图片哦~ 比如说'画一只可爱的小猫'")
                return False, "图片描述为空"

        # 清理和验证描述
        if len(description) > 1000:
            description = description[:1000]
            logger.info(f"{self.log_prefix} 图片描述过长，已截断至1000字符")

        # 提示词优化（自拍模式仅优化场景/环境，不生成角色外观）
        optimizer_enabled = self.get_config("prompt_optimizer.enabled", True)
        if optimizer_enabled:
            scene_only = bool(selfie_mode)
            mode_label = "场景提示词" if scene_only else "提示词"
            logger.info(f"{self.log_prefix} 开始优化{mode_label}: {description[:50]}...")
            success, optimized_prompt = await optimize_prompt(description, self.log_prefix, scene_only=scene_only)
            if success:
                logger.info(f"{self.log_prefix} {mode_label}优化完成: {optimized_prompt[:80]}...")
                description = optimized_prompt
            else:
                logger.warning(f"{self.log_prefix} {mode_label}优化失败，使用原始描述: {description[:50]}...")

        # 验证strength参数
        try:
            strength = float(strength)
            if not (0.1 <= strength <= 1.0):
                strength = 0.7
        except (ValueError, TypeError):
            strength = 0.7

        # 处理自拍模式
        selfie_negative_prompt = None
        if selfie_mode:
            # 检查自拍功能是否启用
            selfie_enabled = self.get_config("selfie.enabled", True)
            if not selfie_enabled:
                await self.send_text("自拍功能暂未启用~")
                return False, "自拍功能未启用"

            logger.info(f"{self.log_prefix} 启用自拍模式，风格: {selfie_style}")

            # 尝试获取日程活动信息（增强场景上下文）
            activity_scene = None
            global_selfie_schedule = self.get_config("selfie.schedule_enabled", True)
            selfie_schedule_on = runtime_state.is_selfie_schedule_enabled(self.chat_id, global_selfie_schedule)
            if selfie_schedule_on:
                try:
                    from .selfie.schedule_provider import get_schedule_provider
                    from .selfie.scene_action_generator import generate_scene_with_llm, get_action_for_activity
                    provider = get_schedule_provider()
                    if provider:
                        activity = await provider.get_current_activity()
                        if activity:
                            # 优先使用 LLM 生成场景（与自动自拍一致），失败时回退到确定性映射
                            activity_scene = await generate_scene_with_llm(activity, selfie_style)
                            if activity_scene:
                                logger.info(f"{self.log_prefix} LLM 生成日程场景: {activity.activity_type.value}")
                            else:
                                activity_scene = get_action_for_activity(activity)
                                logger.info(f"{self.log_prefix} LLM 失败，使用确定性映射: {activity.activity_type.value}")
                except Exception as e:
                    logger.debug(f"{self.log_prefix} 获取日程活动失败（非必要）: {e}")

            description, selfie_negative_prompt = await self._process_selfie_prompt(description, selfie_style, free_hand_action, model_id, activity_scene)
            logger.info(f"{self.log_prefix} 自拍模式处理后的提示词: {description[:100]}...")

            # 检查是否配置了参考图片
            reference_image = self._get_selfie_reference_image()
            if reference_image:
                # 检查模型是否支持图生图
                model_config = self._get_model_config(model_id)
                if model_config and model_config.get("support_img2img", True):
                    logger.info(f"{self.log_prefix} 使用自拍参考图片进行图生图")
                    return await self._execute_unified_generation(description, model_id, size, strength or 0.6, reference_image, extra_negative_prompt=selfie_negative_prompt)
                else:
                    logger.warning(f"{self.log_prefix} 模型 {model_id} 不支持图生图，自拍回退为文生图模式")
            # 无参考图或模型不支持，继续使用文生图（带负面提示词）

        # 收集自拍模式的额外负面提示词（如果启用了自拍模式）
        extra_neg = selfie_negative_prompt if selfie_mode else None

        # **智能检测：判断是文生图还是图生图**
        input_image_base64 = await self.image_processor.get_recent_image()
        is_img2img_mode = input_image_base64 is not None

        if is_img2img_mode:
            # 检查指定模型是否支持图生图
            model_config = self._get_model_config(model_id)
            if model_config and not model_config.get("support_img2img", True):
                logger.warning(f"{self.log_prefix} 模型 {model_id} 不支持图生图，转为文生图模式")
                await self.send_text(f"当前模型 {model_id} 不支持图生图功能，将为您生成新图片")
                return await self._execute_unified_generation(description, model_id, size, None, None, extra_negative_prompt=extra_neg)

            logger.info(f"{self.log_prefix} 检测到输入图片，使用图生图模式")
            return await self._execute_unified_generation(description, model_id, size, strength, input_image_base64, extra_negative_prompt=extra_neg)
        else:
            logger.info(f"{self.log_prefix} 未检测到输入图片，使用文生图模式")
            return await self._execute_unified_generation(description, model_id, size, None, None, extra_negative_prompt=extra_neg)

    async def _execute_unified_generation(self, description: str, model_id: str, size: str, strength: float = None, input_image_base64: str = None, extra_negative_prompt: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """统一的图片生成执行方法

        Args:
            model_id: 模型ID，如 model1、model2
            extra_negative_prompt: 额外负面提示词（如自拍模式的手部质量负面提示词），会合并到模型配置的 negative_prompt_add
        """

        # 获取模型配置
        model_config = self._get_model_config(model_id)
        if not model_config:
            error_msg = f"指定的模型 '{model_id}' 不存在或配置无效，请检查配置文件。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} 模型配置获取失败: {model_id}")
            return False, "模型配置无效"

        # 配置验证
        http_base_url = model_config.get("base_url")
        http_api_key = model_config.get("api_key")
        api_format = model_config.get("format", "openai")
        
        # 检查base_url
        if not http_base_url:
            error_msg = "抱歉，图片生成功能所需的HTTP配置（如API地址）不完整，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} HTTP调用配置缺失: base_url.")
            return False, "HTTP配置不完整"
        
        # 检查api_key（comfyui格式允许为空）
        if api_format != "comfyui" and not http_api_key:
            error_msg = "抱歉，图片生成功能所需的HTTP配置（如API密钥）不完整，无法提供服务。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} HTTP调用配置缺失: api_key.")
            return False, "HTTP配置不完整"

        # API密钥验证（comfyui格式不需要API密钥）
        if api_format != "comfyui" and ("YOUR_API_KEY_HERE" in http_api_key or "xxxxxxxxxxxxxx" in http_api_key):
            error_msg = "图片生成功能尚未配置，请设置正确的API密钥。"
            await self.send_text(error_msg)
            logger.error(f"{self.log_prefix} API密钥未配置")
            return False, "API密钥未配置"

        # 获取模型配置参数
        model_name = model_config.get("model", "default-model")

        # 合并额外的负面提示词（如自拍手部质量负面提示词）
        if extra_negative_prompt:
            model_config = merge_negative_prompt(model_config, extra_negative_prompt)
            logger.info(f"{self.log_prefix} 合并额外负面提示词: {extra_negative_prompt[:80]}...")

        # 使用统一的尺寸处理逻辑
        image_size, llm_original_size = get_image_size(model_config, size, self.log_prefix)

        # 验证图片尺寸格式
        if not self._validate_image_size(image_size):
            logger.warning(f"{self.log_prefix} 无效的图片尺寸: {image_size}，使用模型默认值")
            image_size = model_config.get("default_size", "1024x1024")

        # 检查缓存
        is_img2img = input_image_base64 is not None
        cached_result = self.cache_manager.get_cached_result(description, model_name, image_size, strength, is_img2img)

        if cached_result:
            logger.info(f"{self.log_prefix} 使用缓存的图片结果")
            enable_debug = self.get_config("components.enable_debug_info", False)
            if enable_debug:
                await self.send_text("我之前画过类似的图片，用之前的结果~")
            send_success = await self.send_image(cached_result)
            if send_success:
                return True, "图片已发送(缓存)"
            else:
                self.cache_manager.remove_cached_result(description, model_name, image_size, strength, is_img2img)

        # 显示处理信息
        enable_debug = self.get_config("components.enable_debug_info", False)
        if enable_debug:
            mode_text = "图生图" if is_img2img else "文生图"
            await self.send_text(
                f"收到！正在为您使用 {model_id or '默认'} 模型进行{mode_text}，描述: '{description}'，请稍候...（模型: {model_name}, 尺寸: {image_size}）"
            )

        try:
            # 对于 Gemini/Zai 格式，将原始 LLM 尺寸添加到 model_config 中
            model_config = inject_llm_original_size(model_config, llm_original_size)

            # 获取重试次数配置
            max_retries = self.get_config("components.max_retries", 2)

            # 获取对应格式的API客户端并调用
            api_client = self._get_api_client(api_format)
            success, result = await api_client.generate_image(
                prompt=description,
                model_config=model_config,
                size=image_size,
                strength=strength,
                input_image_base64=input_image_base64,
                max_retries=max_retries
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} 异步请求执行失败: {e!r}", exc_info=True)
            traceback.print_exc()
            success = False
            result = f"图片生成服务遇到意外问题: {str(e)[:100]}"

        if success:
            final_image_data = self.image_processor.process_api_response(result)

            if final_image_data:
                resolved_ok, resolved_data = await resolve_image_data(
                    final_image_data, self._download_and_encode_base64, self.log_prefix
                )
                if resolved_ok:
                    send_timestamp = time_module.time()
                    send_success = await self.send_image(resolved_data)
                    if send_success:
                        mode_text = "图生图" if is_img2img else "文生图"
                        if enable_debug:
                            await self.send_text(f"{mode_text}完成！")
                        self.cache_manager.cache_result(description, model_name, image_size, strength, is_img2img, resolved_data)
                        await self._schedule_auto_recall_for_recent_message(model_config, model_id, send_timestamp)
                        return True, f"{mode_text}已成功生成并发送"
                    else:
                        await self.send_text("图片已处理完成，但发送失败了")
                        return False, "图片发送失败"
                else:
                    await self.send_text(f"图片处理失败：{resolved_data}")
                    return False, f"图片处理失败: {resolved_data}"
            else:
                await self.send_text("图片生成API返回了无法处理的数据格式")
                return False, "API返回数据格式错误"
        else:
            mode_text = "图生图" if is_img2img else "文生图"
            await self.send_text(f"哎呀，{mode_text}时遇到问题：{result}")
            return False, f"{mode_text}失败: {result}"

    def _get_model_config(self, model_id: str = None) -> Dict[str, Any]:
        """获取指定模型的配置，支持热重载"""
        if not model_id:
            model_id = self.get_config("generation.default_model", "model1")
        default_model_id = self.get_config("generation.default_model", "model1")
        return get_model_config(self.get_config, model_id, default_model_id, self.log_prefix) or {}

    def _download_and_encode_base64(self, image_url: str) -> Tuple[bool, str]:
        """下载图片并转换为base64（带代理支持）"""
        proxy_url = None
        if self.get_config("proxy.enabled", False):
            proxy_url = self.get_config("proxy.url", "http://127.0.0.1:7890")
        return self.image_processor.download_and_encode_base64(image_url, proxy_url=proxy_url)

    def _validate_image_size(self, size: str) -> bool:
        """验证图片尺寸格式是否正确（委托给size_utils）"""
        return validate_image_size(size)

    async def _process_selfie_prompt(self, description: str, selfie_style: str, free_hand_action: str, model_id: str, activity_scene: dict = None) -> Tuple[str, str]:
        """处理自拍模式的提示词生成

        Args:
            description: 用户提供的描述
            selfie_style: 自拍风格（standard/mirror/photo）
            free_hand_action: LLM生成的手部动作（可选）
            model_id: 模型ID（保留参数，用于后续扩展）
            activity_scene: 日程活动场景数据（含 hand_action, environment, expression, lighting），无日程时为 None

        Returns:
            (prompt, negative_prompt) 元组：处理后的正面提示词和负面提示词
        """
        import random
        from .selfie.scene_action_generator import (
            build_hand_prompt_for_style,
            get_negative_prompt_for_style,
            get_scene_prompt_for_style,
            sanitize_hand_action_for_style,
        )

        # 1. 添加强制主体设置（含手部质量引导）
        forced_subject = "(1girl:1.4), (solo:1.3), (perfect hands:1.2), (correct anatomy:1.1)"

        # 2. 从独立的selfie配置中获取Bot的默认形象特征（不再从模型配置中获取）
        bot_appearance = self.get_config("selfie.prompt_prefix", "").strip()

        # 3. 自拍风格特定的场景设置
        selfie_scene = get_scene_prompt_for_style(selfie_style)

        # 4. 选择手部动作（优先级：LLM参数 > 日程场景 > LLM按描述生成 > 风格动作池兜底）
        if free_hand_action:
            hand_action = free_hand_action
            logger.info(f"{self.log_prefix} 使用LLM生成的手部动作: {free_hand_action}")
        elif activity_scene and activity_scene.get("hand_action"):
            hand_action = activity_scene["hand_action"]
            logger.info(f"{self.log_prefix} 使用日程活动动作: {hand_action}")
        else:
            hand_action = None
            # 描述足够具体时才调 LLM 生成手部动作，太短/太泛直接走动作池
            # 注意此处 description 可能是优化器处理后的英文，也可能是优化失败的中文原文
            # 英文: "cafe, warm" ≈10字符; 中文: "在咖啡厅" = 4字符
            # 用 3 个中文字 / 6 个英文字符 作为阈值
            desc_clean = description.strip().strip(",. 、，。")
            desc_long_enough = len(desc_clean) > 3 if any('\u4e00' <= c <= '\u9fff' for c in desc_clean) else len(desc_clean) > 6
            if desc_long_enough:
                try:
                    from .selfie.scene_action_generator import generate_hand_action_with_llm
                    hand_action = await generate_hand_action_with_llm(description, selfie_style)
                    if hand_action:
                        logger.info(f"{self.log_prefix} LLM 生成{selfie_style}风格手部动作: {hand_action[:60]}")
                except Exception as e:
                    logger.debug(f"{self.log_prefix} LLM 手部动作生成失败: {e}")
            # LLM 未调用或失败，从动作池兜底
            if not hand_action:
                hand_action = random.choice(self._get_hand_actions_for_style(selfie_style))
                logger.info(f"{self.log_prefix} 动作池随机{selfie_style}风格: {hand_action}")

        hand_action = sanitize_hand_action_for_style(hand_action, selfie_style)
        hand_prompt = build_hand_prompt_for_style(hand_action, selfie_style)

        # 5. 组装完整提示词
        prompt_parts = [forced_subject]

        if bot_appearance:
            prompt_parts.append(bot_appearance)

        # 日程活动的表情和光线（如果有）
        if activity_scene:
            if activity_scene.get("expression"):
                prompt_parts.append(f"({activity_scene['expression']}:1.2)")
            if activity_scene.get("lighting"):
                prompt_parts.append(activity_scene["lighting"])

        if hand_prompt:
            prompt_parts.append(hand_prompt)

        # 日程活动的环境（如果有，补充到自拍场景之前）
        if activity_scene and activity_scene.get("environment"):
            prompt_parts.append(activity_scene["environment"])

        prompt_parts.append(selfie_scene)
        prompt_parts.append(description)

        # 6. 合并并去重
        final_prompt = ", ".join(prompt_parts)

        # 简单的去重处理（避免重复关键词）
        keywords = [kw.strip() for kw in final_prompt.split(',')]
        seen = set()
        unique_keywords = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen and kw:
                seen.add(kw_lower)
                unique_keywords.append(kw)

        final_prompt = ", ".join(unique_keywords)

        base_negative = self.get_config("selfie.negative_prompt", "").strip()
        selfie_negative_prompt = get_negative_prompt_for_style(selfie_style, base_negative)

        logger.info(f"{self.log_prefix} 自拍模式最终提示词: {final_prompt[:200]}...")
        logger.info(f"{self.log_prefix} 自拍模式负面提示词: {selfie_negative_prompt[:150]}...")
        return final_prompt, selfie_negative_prompt

    # ---- 风格专用手部动作池 ----
    # standard: 一只手举手机（画面外），只有另一只手空闲，仅单手动作
    _STANDARD_HAND_ACTIONS = [
        "peace sign, v sign",
        "waving hand, friendly gesture",
        "thumbs up, positive gesture",
        "finger heart, cute gesture",
        "touching cheek gently, soft expression",
        "hand near chin, thinking pose",
        "one hand playing with hair, casual",
        "hand on hip, confident pose",
        "adjusting hair, elegant gesture",
        "resting chin on hand, relaxed",
        "finger on lips, secretive",
        "hand on chest, gentle",
        "tucking hair behind ear, elegant",
        "touching necklace, delicate gesture",
        "hand near eye level, cute gesture",
        "cat paw gesture, playful",
        "saluting, playful military pose",
        "hand covering mouth slightly, shy smile",
        "blowing kiss, romantic",
        "index finger pointing up, idea pose",
        "hand cupping own cheek, adorable",
        "hand resting on collarbone, graceful",
        "pinching own cheek, playful",
    ]

    # mirror: 一只手拿手机对着镜子拍（画面内可见），另一只手空闲，全身或半身
    _MIRROR_HAND_ACTIONS = [
        "hand on hip, confident pose",
        "hand in hair, adjusting hairstyle",
        "hand on waist, model pose",
        "fixing collar, neat appearance",
        "adjusting earring, elegant detail",
        "hand touching shoulder, graceful",
        "hand behind head, relaxed pose",
        "one hand on thigh, standing pose",
        "hand resting at side, natural",
        "hand lightly touching mirror, playful",
        "fixing skirt, adjusting outfit",
        "hand on bag strap, casual",
        "brushing bangs aside, stylish",
        "hand in pocket, cool pose",
        "hand on chin, thoughtful pose",
        "adjusting glasses, intellectual",
        "checking watch, elegant gesture",
        "holding strand of hair, delicate",
        "hand near face, model pose",
        "touching hat brim, fashionable",
    ]

    # photo: 他人拍摄视角，双手都自由，可以有更自然丰富的全身姿态
    _PHOTO_HAND_ACTIONS = [
        "standing naturally, relaxed posture",
        "walking casually, relaxed posture",
        "one hand in hair wind blowing, dynamic",
        "arms at sides, natural standing",
        "holding coffee cup, cafe scene",
        "one hand lightly holding bag strap, casual pose",
        "holding bag, walking pose",
        "leaning on railing, one hand resting",
        "sitting naturally, relaxed posture",
        "hand on hat, windy day",
        "holding flower, smelling gently",
        "hand shielding eyes from sun, looking afar",
        "carrying a small bag, casual walk",
        "holding book to chest, scholarly",
        "one hand waving at camera, candid",
        "leaning against wall, arms relaxed",
        "holding umbrella, rainy atmosphere",
        "looking back over shoulder, candid",
        "sitting on bench, legs crossed, elegant",
    ]

    @staticmethod
    def _get_hand_actions_for_style(selfie_style: str) -> list:
        """根据自拍风格返回对应的手部动作池"""
        if selfie_style == "mirror":
            return MaisArtAction._MIRROR_HAND_ACTIONS
        elif selfie_style == "photo":
            return MaisArtAction._PHOTO_HAND_ACTIONS
        else:
            return MaisArtAction._STANDARD_HAND_ACTIONS

    def _get_selfie_reference_image(self) -> Optional[str]:
        """获取自拍参考图片的base64编码

        Returns:
            图片的base64编码，如果不存在则返回None
        """
        image_path = self.get_config("selfie.reference_image_path", "").strip()
        if not image_path:
            return None

        try:
            # 处理相对路径（相对于插件目录）
            if not os.path.isabs(image_path):
                plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                image_path = os.path.join(plugin_dir, image_path)

            if os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                image_base64 = base64.b64encode(image_data).decode('utf-8')
                logger.info(f"{self.log_prefix} 从文件加载自拍参考图片: {image_path}")
                return image_base64
            else:
                logger.warning(f"{self.log_prefix} 自拍参考图片文件不存在: {image_path}")
                return None
        except Exception as e:
            logger.error(f"{self.log_prefix} 加载自拍参考图片失败: {e}")
            return None

    async def _schedule_auto_recall_for_recent_message(self, model_config: Dict[str, Any] = None, model_id: str = None, send_timestamp: float = 0.0):
        """安排最近发送消息的自动撤回"""
        global_enabled = self.get_config("auto_recall.enabled", False)
        if not global_enabled or not model_config:
            return

        delay_seconds = model_config.get("auto_recall_delay", 0)
        if delay_seconds <= 0:
            return

        if model_id and not runtime_state.is_recall_enabled(self.chat_id, model_id, global_enabled):
            logger.info(f"{self.log_prefix} 模型 {model_id} 撤回已在当前聊天流禁用")
            return

        await schedule_auto_recall(self.chat_id, delay_seconds, self.log_prefix, self.send_command, send_timestamp)

    async def _generate_image_only(
        self,
        description: str,
        model_id: str = None,
        size: str = "",
        strength: float = None,
        input_image_base64: str = None,
        extra_negative_prompt: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """仅生成图片，不发送消息、不撤回、不缓存

        与 _execute_unified_generation() 共享核心逻辑，但适用于自动自拍等
        需要拿到图片数据而不直接发送的场景。

        Args:
            description: 图片描述/提示词
            model_id: 模型ID，默认使用 generation.default_model
            size: 图片尺寸，留空使用模型默认值
            strength: 图生图强度
            input_image_base64: 输入图片的 base64（图生图用）
            extra_negative_prompt: 额外负面提示词

        Returns:
            (success, image_data): success 为 True 时 image_data 是 base64 或 URL 字符串
        """
        if not model_id:
            model_id = self.get_config("generation.default_model", "model1")

        # 获取模型配置
        model_config = self._get_model_config(model_id)
        if not model_config:
            logger.error(f"{self.log_prefix} [image_only] 模型配置获取失败: {model_id}")
            return False, f"模型 '{model_id}' 不存在或配置无效"

        # 配置验证
        http_base_url = model_config.get("base_url")
        http_api_key = model_config.get("api_key")
        api_format = model_config.get("format", "openai")
        
        # 检查base_url
        if not http_base_url:
            return False, "HTTP配置不完整"
        
        # 检查api_key（comfyui格式允许为空）
        if api_format != "comfyui" and not http_api_key:
            return False, "HTTP配置不完整"
        
        # API密钥验证（仅对需要api_key的格式）
        if api_format != "comfyui" and ("YOUR_API_KEY_HERE" in http_api_key or "xxxxxxxxxxxxxx" in http_api_key):
            return False, "API密钥未配置"

        # 合并额外负面提示词
        if extra_negative_prompt:
            model_config = merge_negative_prompt(model_config, extra_negative_prompt)

        # 处理尺寸
        image_size, llm_original_size = get_image_size(model_config, size, self.log_prefix)
        if not self._validate_image_size(image_size):
            image_size = model_config.get("default_size", "1024x1024")

        # Gemini/Zai 尺寸处理
        model_config = inject_llm_original_size(model_config, llm_original_size)

        max_retries = self.get_config("components.max_retries", 2)

        try:
            api_client = self._get_api_client(api_format)
            success, result = await api_client.generate_image(
                prompt=description,
                model_config=model_config,
                size=image_size,
                strength=strength,
                input_image_base64=input_image_base64,
                max_retries=max_retries,
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} [image_only] 生图异常: {e!r}")
            return False, f"生图异常: {str(e)[:100]}"

        if not success:
            return False, result

        # 处理返回数据
        final_image_data = self.image_processor.process_api_response(result)
        if not final_image_data:
            return False, "API返回数据格式错误"

        # 如果是 URL，下载并转为 base64
        return await resolve_image_data(
            final_image_data, self._download_and_encode_base64,
            f"{self.log_prefix} [image_only]"
        )

    def _extract_description_from_message(self) -> str:
        """从用户消息中提取图片描述

        Returns:
            str: 提取的图片描述，如果无法提取则返回空字符串
        """
        if not self.action_message:
            return ""
            
        # 获取消息文本
        message_text = (self.action_message.processed_plain_text or
                       self.action_message.display_message or
                       self.action_message.raw_message or "").strip()
        
        if not message_text:
            return ""
            
        import re
        
        # 移除常见的画图相关前缀
        patterns_to_remove = [
            r'^画',           # "画"
            r'^绘制',         # "绘制"
            r'^生成图片',     # "生成图片"
            r'^画图',         # "画图"
            r'^帮我画',       # "帮我画"
            r'^请画',         # "请画"
            r'^能不能画',     # "能不能画"
            r'^可以画',       # "可以画"
            r'^画一个',       # "画一个"
            r'^画一只',       # "画一只"
            r'^画张',         # "画张"
            r'^画幅',         # "画幅"
            r'^图[：:]',      # "图："或"图:"
            r'^生成图片[：:]', # "生成图片："或"生成图片:"
            r'^[：:]',        # 单独的冒号
            r'^用\s*模型\s*\S+\s*',       # "用模型3" / "用 模型 abc"
            r'^用\s*model\s*\S+\s*',      # "用model2" / "用 model abc"
        ]
        
        cleaned_text = message_text
        for pattern in patterns_to_remove:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
        
        # 移除常见的后缀
        suffix_patterns = [
            r'图片$',         # "图片"
            r'图$',           # "图"
            r'一下$',         # "一下"
            r'呗$',           # "呗"
            r'吧$',           # "吧"
        ]
        
        for pattern in suffix_patterns:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
        
        # 清理空白字符
        cleaned_text = cleaned_text.strip()
        
        # 如果清理后为空，返回原消息（可能是简单的描述）
        if not cleaned_text:
            cleaned_text = message_text
            
        # 限制长度，避免过长的描述
        if len(cleaned_text) > 100:
            cleaned_text = cleaned_text[:100]
            
        return cleaned_text

