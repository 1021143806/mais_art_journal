from typing import List, Tuple, Type, Dict, Any
import asyncio
import os

from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.component_types import ComponentInfo
from src.plugin_system import register_plugin
from src.plugin_system.base.config_types import (
    ConfigField,
    ConfigSection,
    ConfigLayout,
    ConfigTab,
)

from .core.pic_action import MaisArtAction
from .core.pic_command import PicGenerationCommand, PicConfigCommand, PicStyleCommand
from .core.config_manager import EnhancedConfigManager


@register_plugin
class MaisArtJournalPlugin(BasePlugin):
    """麦麦绘卷（Claude MAInet）- 智能多模型图片生成插件，支持文生图和图生图"""

    # 插件基本信息
    plugin_name = "mais_art_journal"
    plugin_version = "3.4.0"
    plugin_author = "Ptrel，Rabbit"
    enable_plugin = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name = "config.toml"

    # 配置节元数据
    config_section_descriptions = {
        # ---- basic 标签页 ----
        "plugin": ConfigSection(
            title="插件启用配置",
            icon="info",
            order=1
        ),
        "generation": ConfigSection(
            title="图片生成默认配置",
            icon="image",
            order=2
        ),
        "components": ConfigSection(
            title="组件启用配置",
            icon="puzzle-piece",
            order=3
        ),
        # ---- network 标签页 ----
        "proxy": ConfigSection(
            title="代理设置",
            icon="globe",
            order=4
        ),
        "cache": ConfigSection(
            title="结果缓存配置",
            icon="database",
            order=5
        ),
        # ---- features 标签页 ----
        "selfie": ConfigSection(
            title="自拍模式配置",
            icon="camera",
            order=6
        ),
        "auto_selfie": ConfigSection(
            title="自动自拍配置",
            description="定时自动生成自拍并发布到QQ空间（需安装 Maizone 插件和 autonomous_planning 插件）",
            icon="camera",
            order=7
        ),
        "auto_recall": ConfigSection(
            title="自动撤回配置",
            icon="trash",
            order=8
        ),
        "prompt_optimizer": ConfigSection(
            title="提示词优化器",
            description="使用 MaiBot 主 LLM 将用户描述优化为专业绘画提示词",
            icon="wand-2",
            order=9
        ),
        # ---- styles 标签页 ----
        "styles": ConfigSection(
            title="风格定义",
            description="预设风格的提示词。添加更多风格请直接编辑 config.toml，格式：风格英文名 = \"提示词\"",
            icon="palette",
            order=10
        ),
        "style_aliases": ConfigSection(
            title="风格别名",
            description="风格的中文别名映射。添加更多别名请直接编辑 config.toml",
            icon="tag",
            order=11
        ),
        # ---- models 标签页 ----
        "models": ConfigSection(
            title="多模型配置",
            description="添加更多模型请直接编辑 config.toml，复制 [models.model1] 整节并改名为 model2、model3 等",
            icon="cpu",
            order=12
        ),
        "models.model1": ConfigSection(
            title="模型1配置",
            icon="box",
            order=13
        ),
    }

    # 自定义布局：标签页
    config_layout = ConfigLayout(
        type="tabs",
        tabs=[
            ConfigTab(
                id="basic",
                title="基础设置",
                sections=["plugin", "generation", "components"],
                icon="settings"
            ),
            ConfigTab(
                id="network",
                title="网络配置",
                sections=["proxy", "cache"],
                icon="wifi"
            ),
            ConfigTab(
                id="features",
                title="功能配置",
                sections=["selfie", "auto_selfie", "auto_recall", "prompt_optimizer"],
                icon="zap"
            ),
            ConfigTab(
                id="styles",
                title="风格管理",
                sections=["styles", "style_aliases"],
                icon="palette"
            ),
            ConfigTab(
                id="models",
                title="模型管理",
                sections=["models", "models.model1"],
                icon="cpu"
            ),
        ]
    )

    # 配置Schema
    config_schema = {
        "plugin": {
            "name": ConfigField(
                type=str,
                default="麦麦绘卷",
                description="麦麦绘卷（Claude MAInet）— 智能多模型图片生成插件，支持文生图/图生图自动识别",
                label="插件名称",
                required=True,
                disabled=True,
                order=1
            ),
            "config_version": ConfigField(
                type=str,
                default="3.4.0",
                description="插件配置版本号",
                label="配置版本",
                disabled=True,
                order=2
            ),
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用插件，开启后可使用画图和风格转换功能",
                label="启用插件",
                order=3
            )
        },
        "generation": {
            "default_model": ConfigField(
                type=str,
                default="model1",
                description="默认使用的模型ID，用于智能图片生成。支持文生图和图生图自动识别",
                label="默认模型",
                hint="对应模型管理中的模型ID（如model1、model2）",
                example="model1",
                placeholder="model1",
                order=1
            ),
        },
        "cache": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用结果缓存，相同参数的请求会复用之前的结果",
                label="启用缓存",
                order=1
            ),
            "max_size": ConfigField(
                type=int,
                default=10,
                description="最大缓存数量，超出后删除最旧的缓存",
                label="最大缓存数",
                min=1,
                max=100,
                depends_on="cache.enabled",
                depends_value=True,
                order=2
            ),
        },
        "components": {
            "enable_unified_generation": ConfigField(
                type=bool,
                default=True,
                description="是否启用智能图片生成Action，支持文生图和图生图自动识别",
                label="智能生图",
                order=1
            ),
            "enable_pic_command": ConfigField(
                type=bool,
                default=True,
                description="是否启用 /dr 图片生成命令，支持风格化图生图和自然语言文/图生图",
                label="图片生成命令",
                order=2
            ),
            "enable_pic_config": ConfigField(
                type=bool,
                default=True,
                description="是否启用模型配置管理命令，支持/dr list、/dr set等",
                label="配置管理",
                order=3
            ),
            "enable_pic_style": ConfigField(
                type=bool,
                default=True,
                description="是否启用风格管理命令，支持/dr styles、/dr style等",
                label="风格管理",
                order=4
            ),
            "pic_command_model": ConfigField(
                type=str,
                default="model1",
                description="Command组件使用的模型ID，可通过/dr set命令动态切换",
                label="Command模型",
                placeholder="model1",
                order=5
            ),
            "enable_debug_info": ConfigField(
                type=bool,
                default=False,
                description="是否启用调试信息显示，关闭后仅显示图片结果和错误信息",
                label="调试信息",
                order=6
            ),
            "enable_verbose_debug": ConfigField(
                type=bool,
                default=False,
                description="是否启用详细调试信息，启用后会发送完整的调试信息以及打印完整的 POST 报文",
                label="详细调试",
                order=7
            ),
            "admin_users": ConfigField(
                type=list,
                default=[],
                description="有权限使用配置管理命令的管理员用户列表，请填写字符串形式的用户ID",
                label="管理员列表",
                hint="字符串形式的用户ID，如 [\"12345\", \"67890\"]",
                item_type="string",
                placeholder="[\"用户ID1\", \"用户ID2\"]",
                order=8
            ),
            "max_retries": ConfigField(
                type=int,
                default=2,
                description="API调用失败时的重试次数，建议2-5次。设置为0表示不重试",
                label="重试次数",
                min=0,
                max=10,
                order=9
            )
        },
        "proxy": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用代理。开启后所有API请求将通过代理服务器",
                label="启用代理",
                order=1
            ),
            "url": ConfigField(
                type=str,
                default="http://127.0.0.1:7890",
                description="代理服务器地址，格式：http://host:port。支持HTTP/HTTPS/SOCKS5代理",
                label="代理地址",
                hint="支持 HTTP、HTTPS、SOCKS5 代理",
                example="http://127.0.0.1:7890",
                placeholder="http://127.0.0.1:7890",
                depends_on="proxy.enabled",
                depends_value=True,
                order=2
            ),
            "timeout": ConfigField(
                type=int,
                default=60,
                description="代理连接超时时间（秒），建议30-120秒",
                label="超时时间",
                min=10,
                max=300,
                depends_on="proxy.enabled",
                depends_value=True,
                order=3
            )
        },
        "styles": {
            "cartoon": ConfigField(
                type=str,
                default="cartoon style, anime style, colorful, vibrant colors, clean lines",
                description="卡通风格提示词",
                label="卡通风格",
                input_type="textarea",
                rows=3,
                order=1
            )
        },
        "style_aliases": {
            "cartoon": ConfigField(
                type=str,
                default="卡通",
                description="cartoon 风格的中文别名，支持多别名用逗号分隔",
                label="卡通别名",
                placeholder="卡通,动漫",
                order=1
            )
        },
        "selfie": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用自拍模式功能",
                label="启用自拍",
                order=1
            ),
            "reference_image_path": ConfigField(
                type=str,
                default="",
                description="自拍参考图片路径（相对于插件目录或绝对路径）。配置后自动使用图生图模式，留空则使用纯文生图。若模型不支持图生图会自动回退",
                label="参考图片",
                placeholder="images/reference.png",
                depends_on="selfie.enabled",
                depends_value=True,
                order=2
            ),
            "prompt_prefix": ConfigField(
                type=str,
                default="",
                description="自拍模式专用提示词前缀。用于添加Bot的默认形象特征（发色、瞳色、服装风格等）。例如：'blue hair, red eyes, school uniform, 1girl'",
                label="提示词前缀",
                input_type="textarea",
                rows=2,
                placeholder="blue hair, red eyes, school uniform, 1girl",
                depends_on="selfie.enabled",
                depends_value=True,
                order=3
            ),
            "negative_prompt": ConfigField(
                type=str,
                default="",
                description="自拍模式基础负面提示词。所有风格自动附加手部质量负面提示词，standard 风格额外附加防双手拿手机提示词。此处可添加额外的负面提示词",
                label="负面提示词",
                input_type="textarea",
                rows=3,
                placeholder="lowres, bad anatomy, bad hands, extra fingers",
                depends_on="selfie.enabled",
                depends_value=True,
                order=4
            ),
            "schedule_enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用日程增强自拍。开启后手动自拍会结合日程活动数据生成更贴合情境的场景（需安装 autonomous_planning 插件）。可通过 /dr selfie on|off 按聊天流覆盖",
                label="日程增强",
                depends_on="selfie.enabled",
                depends_value=True,
                order=5
            ),
            "default_style": ConfigField(
                type=str,
                default="standard",
                description="自拍默认风格（手动和自动自拍共用）：standard(前置自拍)/mirror(对镜自拍)/photo(第三人称照片)。可通过 /dr selfie standard|mirror|photo 按聊天流覆盖",
                label="默认自拍风格",
                choices=["standard", "mirror", "photo"],
                depends_on="selfie.enabled",
                depends_value=True,
                order=6
            )
        },
        "auto_recall": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用自动撤回功能（总开关）。关闭后所有模型的撤回都不生效",
                label="启用撤回",
                order=1
            )
        },
        "prompt_optimizer": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用提示词优化器。开启后会使用 MaiBot 主 LLM 将用户描述优化为专业英文提示词",
                label="启用优化器",
                order=1
            )
        },
        "auto_selfie": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用自动自拍。需同时安装 autonomous_planning 插件（提供日程数据）和 Maizone 插件（发布到QQ空间）。无日程数据时自动跳过",
                label="启用自动自拍",
                order=1
            ),
            "interval_minutes": ConfigField(
                type=int,
                default=120,
                description="自拍间隔（分钟），建议60-240",
                label="自拍间隔",
                min=10,
                max=1440,
                depends_on="auto_selfie.enabled",
                depends_value=True,
                order=2
            ),
            "selfie_model": ConfigField(
                type=str,
                default="model1",
                description="自拍使用的模型ID（对应模型管理中的配置）",
                label="自拍模型",
                placeholder="model1",
                depends_on="auto_selfie.enabled",
                depends_value=True,
                order=3
            ),
            "quiet_hours_start": ConfigField(
                type=str,
                default="00:00",
                description="安静时段开始时间（HH:MM），此时段内不发送自拍",
                label="安静开始",
                example="00:00",
                placeholder="00:00",
                depends_on="auto_selfie.enabled",
                depends_value=True,
                order=4
            ),
            "quiet_hours_end": ConfigField(
                type=str,
                default="07:00",
                description="安静时段结束时间（HH:MM）",
                label="安静结束",
                placeholder="07:00",
                depends_on="auto_selfie.enabled",
                depends_value=True,
                order=5
            ),
            "caption_enabled": ConfigField(
                type=bool,
                default=True,
                description="是否为自拍生成配文",
                label="生成配文",
                depends_on="auto_selfie.enabled",
                depends_value=True,
                order=6
            ),
        },
        "models": {},
        # 基础模型配置模板
        "models.model1": {
            "name": ConfigField(
                type=str,
                default="魔搭潦草模型",
                description="模型显示名称，在模型列表中展示，版本更新后请手动从 old 目录恢复配置",
                label="模型名称",
                group="connection",
                order=1
            ),
            "base_url": ConfigField(
                type=str,
                default="https://api-inference.modelscope.cn/v1",
                description="API服务地址。示例: OpenAI=https://api.openai.com/v1, 硅基流动=https://api.siliconflow.cn/v1, 豆包=https://ark.cn-beijing.volces.com/api/v3, 魔搭=https://api-inference.modelscope.cn/v1, Gemini=https://generativelanguage.googleapis.com",
                label="API地址",
                example="https://api.siliconflow.cn/v1",
                required=True,
                placeholder="https://api.example.com/v1",
                group="connection",
                order=2
            ),
            "api_key": ConfigField(
                type=str,
                default="Bearer xxxxxxxxxxxxxxxxxxxxxx",
                description="API密钥。统一填写 'Bearer xxx' 格式即可，doubao/gemini/shatangyun 等 SDK 格式会自动去除 Bearer 前缀",
                label="API密钥",
                hint="统一使用 'Bearer xxx' 格式",
                input_type="password",
                required=True,
                placeholder="Bearer sk-xxx",
                group="connection",
                order=3
            ),
            "format": ConfigField(
                type=str,
                default="openai",
                description="API格式。openai=通用格式，openai-chat=Chat Completions生图，doubao=豆包，gemini=Gemini，modelscope=魔搭，shatangyun=砂糖云(NovelAI)，mengyuai=梦羽AI，zai=Zai(Gemini转发)，comfyui=本地ComfyUI工作流",
                label="API格式",
                choices=["openai", "openai-chat", "gemini", "doubao", "modelscope", "shatangyun", "mengyuai", "zai", "comfyui"],
                required=True,
                group="connection",
                order=4
            ),
            "model": ConfigField(
                type=str,
                default="cancel13/liaocao",
                description="模型标识。梦羽AI 格式填模型索引数字（如 0）。ComfyUI 格式填工作流文件名（如 workflow.json），工作流放在插件 workflow/ 目录下，也可填绝对路径",
                label="模型标识",
                placeholder="model-name / 0 / workflow.json",
                required=True,
                group="connection",
                order=5
            ),
            "fixed_size_enabled": ConfigField(
                type=bool,
                default=False,
                description="是否固定图片尺寸。开启后强制使用 default_size，关闭则由 MaiBot LLM 根据内容自动选择。豆包格式建议开启",
                label="固定尺寸",
                group="params",
                order=6
            ),
            "default_size": ConfigField(
                type=str,
                default="1024x1024",
                description="默认图片尺寸。像素格式: 1024x1024。Gemini/Zai 填宽高比: 16:9 或 16:9-2K。豆包填分辨率等级: 2K（seededit 填 adaptive）",
                label="默认尺寸",
                hint="像素/宽高比/分辨率等级，按 API 要求填写",
                placeholder="1024x1024 / 16:9-2K / 2K",
                group="params",
                order=7
            ),
            "seed": ConfigField(
                type=int,
                default=-1,
                description="随机种子，固定值可确保结果可复现。-1 表示每次随机，同时对于不支持此参数的模型，设为-1时请求将不包含此参数",
                label="随机种子",
                min=-1,
                max=2147483647,
                group="params",
                order=8
            ),
            "guidance_scale": ConfigField(
                type=float,
                default=2.5,
                description="引导强度（CFG）。值越高越严格遵循提示词。豆包 seededit 推荐 5.5，硅基流动/魔搭推荐 2.5-7.5。对于不支持此参数的模型（如Gemini），可设为-1，请求时将不包含此参数",
                label="引导强度",
                min=-1.0,
                max=20.0,
                step=0.5,
                group="params",
                order=9
            ),
            "num_inference_steps": ConfigField(
                type=int,
                default=20,
                description="推理步数，影响质量和速度。推荐20-50。对于不支持此参数的模型（如Gemini），可设为-1，请求时将不包含此参数",
                label="推理步数",
                min=-1,
                max=150,
                group="params",
                order=10
            ),
            "watermark": ConfigField(
                type=bool,
                default=True,
                description="是否添加水印",
                label="水印",
                group="params",
                order=11
            ),
            "custom_prompt_add": ConfigField(
                type=str,
                default=", Nordic picture book art style, minimalist flat design, liaocao",
                description="正面提示词增强，自动添加到用户描述后",
                label="正面增强词",
                input_type="textarea",
                rows=2,
                group="prompts",
                order=12
            ),
            "negative_prompt_add": ConfigField(
                type=str,
                default="Pornography,nudity,lowres, bad anatomy, bad hands, text, error",
                description="负面提示词，避免不良内容。豆包/Gemini 格式不支持此参数可留空",
                label="负面提示词",
                input_type="textarea",
                rows=2,
                group="prompts",
                order=13
            ),
            "artist": ConfigField(
                type=str,
                default="",
                description="艺术家风格标签（砂糖云专用）。留空则不添加",
                label="艺术家标签",
                group="prompts",
                order=14
            ),
            "support_img2img": ConfigField(
                type=bool,
                default=True,
                description="该模型是否支持图生图功能。设为false时会自动降级为文生图",
                label="支持图生图",
                group="prompts",
                order=15
            ),
            "auto_recall_delay": ConfigField(
                type=int,
                default=0,
                description="自动撤回延时（秒）。大于0时启用撤回，0表示不撤回。需先在「自动撤回配置」中开启总开关",
                label="撤回延时",
                hint="需先在「自动撤回配置」中开启总开关",
                min=0,
                max=120,
                group="prompts",
                order=16
            ),
            # ---- 平台专用参数 ----
            "cfg": ConfigField(
                type=float,
                default=0,
                description="砂糖云专用：CFG Rescale 参数（与引导强度不同），默认0",
                label="CFG Rescale",
                hint="仅砂糖云格式生效",
                min=0.0,
                max=1.0,
                step=0.1,
                group="platform",
                order=20
            ),
            "sampler": ConfigField(
                type=str,
                default="k_euler_ancestral",
                description="砂糖云专用：采样器名称",
                label="采样器",
                hint="仅砂糖云格式生效",
                choices=["k_euler_ancestral", "k_euler", "k_dpmpp_2s_ancestral", "k_dpmpp_2m_sde", "k_dpmpp_2m", "k_dpmpp_sde"],
                group="platform",
                order=21
            ),
            "nocache": ConfigField(
                type=int,
                default=0,
                description="砂糖云专用：是否禁用缓存，0=使用缓存，1=禁用",
                label="禁用缓存",
                hint="仅砂糖云格式生效",
                min=0,
                max=1,
                group="platform",
                order=22
            ),
            "noise_schedule": ConfigField(
                type=str,
                default="karras",
                description="砂糖云专用：噪声调度方案",
                label="噪声调度",
                hint="仅砂糖云格式生效",
                choices=["karras", "native", "exponential", "polyexponential"],
                group="platform",
                order=23
            ),
        },
    }

    def __init__(self, plugin_dir: str):
        """初始化插件，集成增强配置管理器"""
        import toml
        # 在父类初始化前读取原始配置文件
        config_path = os.path.join(plugin_dir, self.config_file_name)
        original_config = None
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    original_config = toml.load(f)
                print(f"[MaisArtJournal] 读取原始配置文件: {config_path}")
            except Exception as e:
                print(f"[MaisArtJournal] 读取原始配置失败: {e}")
        
        # 先调用父类初始化，这会加载配置并可能触发 MaiBot 迁移
        super().__init__(plugin_dir)
        
        # 初始化增强配置管理器
        self.enhanced_config_manager = EnhancedConfigManager(plugin_dir, self.config_file_name)
        
        # 检查并更新配置（如果需要），传入原始配置
        self._enhance_config_management(original_config)

        # 初始化自动自拍任务
        self._auto_selfie_task = None
        self._auto_selfie_pending = False
        if self.get_config("auto_selfie.enabled", False):
            from .core.selfie import AutoSelfieTask
            self._auto_selfie_task = AutoSelfieTask(self)
            try:
                asyncio.create_task(self._start_auto_selfie_after_delay())
            except RuntimeError:
                # 事件循环未就绪，标记待启动，在首次组件执行时懒启动
                self._auto_selfie_pending = True
                print("[MaisArtJournal] 事件循环未就绪，自动自拍任务将在首次执行时懒启动")

    async def _start_auto_selfie_after_delay(self):
        """延迟启动自动自拍任务"""
        await asyncio.sleep(15)
        if self._auto_selfie_task:
            await self._auto_selfie_task.start()
            self._auto_selfie_pending = False

    def try_start_auto_selfie(self):
        """尝试懒启动自动自拍任务（供组件首次执行时调用）"""
        if not self._auto_selfie_pending or not self._auto_selfie_task:
            return
        try:
            asyncio.create_task(self._start_auto_selfie_after_delay())
            self._auto_selfie_pending = False
        except RuntimeError:
            pass  # 仍无事件循环，下次再试

    def _enhance_config_management(self, original_config=None):
        """增强配置管理：备份、版本检查、智能合并
        
        Args:
            original_config: 从磁盘读取的原始配置（在父类初始化前读取），用于恢复用户自定义值
        """
        # 获取期望的配置版本
        expected_version = self._get_expected_config_version()
        
        # 将config_schema转换为EnhancedConfigManager需要的格式
        schema_for_manager = self._convert_schema_for_manager()
        
        # 生成默认配置结构
        default_config = self._generate_default_config_from_schema()
        
        # 确定要使用的旧配置：优先使用传入的原始配置，其次从备份文件加载
        old_config = original_config
        if old_config is None:
            old_dir = os.path.join(self.plugin_dir, "old")
            if os.path.exists(old_dir):
                import toml
                # 查找最新的备份文件（按时间戳排序），包括 auto_backup、new_backup 和 backup 文件
                backup_files = []
                for fname in os.listdir(old_dir):
                    if (fname.startswith(self.config_file_name + ".backup_") or
                        fname.startswith(self.config_file_name + ".new_backup_") or
                        fname.startswith(self.config_file_name + ".auto_backup_")) and fname.endswith(".toml"):
                        backup_files.append(fname)
                if backup_files:
                    # 按时间戳排序（文件名中包含 _YYYYMMDD_HHMMSS）
                    backup_files.sort(reverse=True)
                    latest_backup = os.path.join(old_dir, backup_files[0])
                    try:
                        with open(latest_backup, "r", encoding="utf-8") as f:
                            old_config = toml.load(f)
                        print(f"[MaisArtJournal] 从备份文件加载原始配置: {backup_files[0]}")
                    except Exception as e:
                        print(f"[MaisArtJournal] 加载备份文件失败: {e}")
        
        # 版本不同时才备份（版本更新前 update_config_if_needed 会自动备份）
        current_config = self.enhanced_config_manager.load_config()
        if current_config:
            current_version = self.enhanced_config_manager.get_config_version(current_config)
            if current_version != expected_version:
                print(f"[MaisArtJournal] 配置版本 v{current_version} != v{expected_version}，创建备份")
                self.enhanced_config_manager.backup_config(current_version)
            else:
                print(f"[MaisArtJournal] 配置版本 v{current_version} 已是最新，跳过备份")
        
        # 使用增强配置管理器检查并更新配置
        # 传入旧配置（如果存在）以恢复用户自定义值
        updated_config = self.enhanced_config_manager.update_config_if_needed(
            expected_version=expected_version,
            default_config=default_config,
            schema=schema_for_manager,
            old_config=old_config
        )
        
        # 如果配置有更新，更新self.config
        if updated_config and updated_config != self.config:
            self.config = updated_config
            # 同时更新enable_plugin状态
            if "plugin" in self.config and "enabled" in self.config["plugin"]:
                self.enable_plugin = self.config["plugin"]["enabled"]
    
    def _get_expected_config_version(self) -> str:
        """获取期望的配置版本号"""
        if "plugin" in self.config_schema and isinstance(self.config_schema["plugin"], dict):
            config_version_field = self.config_schema["plugin"].get("config_version")
            if isinstance(config_version_field, ConfigField):
                return config_version_field.default
        return "1.0.0"
    
    def _convert_schema_for_manager(self) -> Dict[str, Any]:
        """将ConfigField格式的schema转换为EnhancedConfigManager需要的格式"""
        schema_for_manager = {}
        
        for section, fields in self.config_schema.items():
            if not isinstance(fields, dict):
                continue
                
            section_schema = {}
            for field_name, field in fields.items():
                if isinstance(field, ConfigField):
                    section_schema[field_name] = {
                        "description": field.description,
                        "default": field.default,
                        "required": field.required,
                        "choices": field.choices if field.choices else None,
                        "example": field.example
                    }
            
            schema_for_manager[section] = section_schema
        
        return schema_for_manager
    
    def _generate_default_config_from_schema(self) -> Dict[str, Any]:
        """从schema生成默认配置结构"""
        default_config = {}
        
        for section, fields in self.config_schema.items():
            if not isinstance(fields, dict):
                continue
                
            section_config = {}
            for field_name, field in fields.items():
                if isinstance(field, ConfigField):
                    section_config[field_name] = field.default
            
            default_config[section] = section_config
        
        return default_config

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        enable_unified_generation = self.get_config("components.enable_unified_generation", True)
        enable_pic_command = self.get_config("components.enable_pic_command", True)
        enable_pic_config = self.get_config("components.enable_pic_config", True)
        enable_pic_style = self.get_config("components.enable_pic_style", True)
        components = []

        if enable_unified_generation:
            components.append((MaisArtAction.get_action_info(), MaisArtAction))

        # 优先注册更具体的配置管理命令，避免被通用风格命令拦截
        if enable_pic_config:
            components.append((PicConfigCommand.get_command_info(), PicConfigCommand))

        if enable_pic_style:
            components.append((PicStyleCommand.get_command_info(), PicStyleCommand))

        # 最后注册通用的风格命令，以免覆盖特定命令
        if enable_pic_command:
            components.append((PicGenerationCommand.get_command_info(), PicGenerationCommand))

        return components
