"""运行时状态管理器

按聊天流分别管理插件状态，支持：
- 插件开关
- 模型开关
- 撤回开关
- 默认模型设置
- 自动清理长时间不活跃的聊天流状态
"""
import logging
import time
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger("plugin.mais_art_journal.state")

# 聊天流状态在无访问后保留的最大时长（秒），默认 24 小时
_STATE_TTL_SECONDS = 24 * 60 * 60
# 每次清理扫描的间隔（秒），避免频繁遍历
_CLEANUP_INTERVAL_SECONDS = 30 * 60


@dataclass
class ChatStreamState:
    """单个聊天流的状态"""
    plugin_enabled: Optional[bool] = None
    disabled_models: Set[str] = field(default_factory=set)
    recall_disabled_models: Set[str] = field(default_factory=set)
    action_default_model: Optional[str] = None
    command_default_model: Optional[str] = None
    selfie_schedule_enabled: Optional[bool] = None
    selfie_style: Optional[str] = None
    last_access: float = field(default_factory=time.time)


class RuntimeStateManager:
    """运行时状态管理器（单例）

    按聊天流ID分别管理状态，所有状态仅在内存中保持，重启后重置。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._states: Dict[str, ChatStreamState] = {}
            cls._instance._last_cleanup: float = time.time()
        return cls._instance

    def _get_state(self, chat_id: str) -> ChatStreamState:
        if chat_id not in self._states:
            self._states[chat_id] = ChatStreamState()
        state = self._states[chat_id]
        state.last_access = time.time()
        self._maybe_cleanup()
        return state

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = now
        expired = [
            cid for cid, s in self._states.items()
            if now - s.last_access > _STATE_TTL_SECONDS and not self._has_custom_settings(s)
        ]
        for cid in expired:
            del self._states[cid]
        if expired:
            logger.debug(f"[RuntimeState] 清理了 {len(expired)} 个不活跃的聊天流状态")

    @staticmethod
    def _has_custom_settings(state: ChatStreamState) -> bool:
        return (
            state.plugin_enabled is not None
            or state.disabled_models
            or state.recall_disabled_models
            or state.action_default_model is not None
            or state.command_default_model is not None
            or state.selfie_schedule_enabled is not None
            or state.selfie_style is not None
        )

    # ==================== 插件开关 ====================

    def is_plugin_enabled(self, chat_id: str, global_enabled: bool) -> bool:
        state = self._get_state(chat_id)
        if state.plugin_enabled is not None:
            return state.plugin_enabled
        return global_enabled

    def set_plugin_enabled(self, chat_id: str, enabled: bool) -> None:
        state = self._get_state(chat_id)
        state.plugin_enabled = enabled
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 插件状态设置为: {enabled}")

    def reset_plugin_enabled(self, chat_id: str) -> None:
        state = self._get_state(chat_id)
        state.plugin_enabled = None
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 插件状态已重置为全局配置")

    # ==================== 模型开关 ====================

    def is_model_enabled(self, chat_id: str, model_id: str) -> bool:
        state = self._get_state(chat_id)
        return model_id not in state.disabled_models

    def set_model_enabled(self, chat_id: str, model_id: str, enabled: bool) -> None:
        state = self._get_state(chat_id)
        if enabled:
            state.disabled_models.discard(model_id)
            logger.info(f"[RuntimeState] 聊天流 {chat_id} 模型 {model_id} 已启用")
        else:
            state.disabled_models.add(model_id)
            logger.info(f"[RuntimeState] 聊天流 {chat_id} 模型 {model_id} 已禁用")

    def get_disabled_models(self, chat_id: str) -> Set[str]:
        state = self._get_state(chat_id)
        return state.disabled_models.copy()

    # ==================== 撤回开关 ====================

    def is_recall_enabled(self, chat_id: str, model_id: str, global_enabled: bool) -> bool:
        if not global_enabled:
            return False
        state = self._get_state(chat_id)
        return model_id not in state.recall_disabled_models

    def set_recall_enabled(self, chat_id: str, model_id: str, enabled: bool) -> None:
        state = self._get_state(chat_id)
        if enabled:
            state.recall_disabled_models.discard(model_id)
            logger.info(f"[RuntimeState] 聊天流 {chat_id} 模型 {model_id} 撤回已启用")
        else:
            state.recall_disabled_models.add(model_id)
            logger.info(f"[RuntimeState] 聊天流 {chat_id} 模型 {model_id} 撤回已禁用")

    def get_recall_disabled_models(self, chat_id: str) -> Set[str]:
        state = self._get_state(chat_id)
        return state.recall_disabled_models.copy()

    # ==================== 默认模型 ====================

    def get_action_default_model(self, chat_id: str, global_default: str) -> str:
        state = self._get_state(chat_id)
        if state.action_default_model is not None:
            return state.action_default_model
        return global_default

    def set_action_default_model(self, chat_id: str, model_id: str) -> None:
        state = self._get_state(chat_id)
        state.action_default_model = model_id
        logger.info(f"[RuntimeState] 聊天流 {chat_id} Action默认模型设置为: {model_id}")

    def reset_action_default_model(self, chat_id: str) -> None:
        state = self._get_state(chat_id)
        state.action_default_model = None
        logger.info(f"[RuntimeState] 聊天流 {chat_id} Action默认模型已重置为全局配置")

    def get_command_default_model(self, chat_id: str, global_default: str) -> str:
        state = self._get_state(chat_id)
        if state.command_default_model is not None:
            return state.command_default_model
        return global_default

    def set_command_default_model(self, chat_id: str, model_id: str) -> None:
        state = self._get_state(chat_id)
        state.command_default_model = model_id
        logger.info(f"[RuntimeState] 聊天流 {chat_id} Command默认模型设置为: {model_id}")

    def reset_command_default_model(self, chat_id: str) -> None:
        state = self._get_state(chat_id)
        state.command_default_model = None
        logger.info(f"[RuntimeState] 聊天流 {chat_id} Command默认模型已重置为全局配置")

    # ==================== 自拍日程开关 ====================

    def is_selfie_schedule_enabled(self, chat_id: str, global_enabled: bool) -> bool:
        state = self._get_state(chat_id)
        if state.selfie_schedule_enabled is not None:
            return state.selfie_schedule_enabled
        return global_enabled

    def set_selfie_schedule_enabled(self, chat_id: str, enabled: bool) -> None:
        state = self._get_state(chat_id)
        state.selfie_schedule_enabled = enabled
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 自拍日程增强设置为: {enabled}")

    def reset_selfie_schedule_enabled(self, chat_id: str) -> None:
        state = self._get_state(chat_id)
        state.selfie_schedule_enabled = None
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 自拍日程增强已重置为全局配置")

    # ==================== 自拍风格 ====================

    _VALID_SELFIE_STYLES = {"standard", "mirror", "photo"}

    def get_selfie_style(self, chat_id: str, global_default: Optional[str] = None) -> Optional[str]:
        state = self._get_state(chat_id)
        if state.selfie_style is not None:
            return state.selfie_style
        return global_default

    def set_selfie_style(self, chat_id: str, style: str) -> None:
        state = self._get_state(chat_id)
        state.selfie_style = style
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 自拍风格设置为: {style}")

    def reset_selfie_style(self, chat_id: str) -> None:
        state = self._get_state(chat_id)
        state.selfie_style = None
        logger.info(f"[RuntimeState] 聊天流 {chat_id} 自拍风格已重置为全局配置")

    # ==================== 状态重置 ====================

    def reset_chat_state(self, chat_id: str) -> None:
        if chat_id in self._states:
            del self._states[chat_id]
            logger.info(f"[RuntimeState] 聊天流 {chat_id} 所有状态已重置")

    def get_chat_state_summary(self, chat_id: str) -> Dict[str, Any]:
        state = self._get_state(chat_id)
        return {
            "plugin_enabled": state.plugin_enabled,
            "disabled_models": list(state.disabled_models),
            "recall_disabled_models": list(state.recall_disabled_models),
            "action_default_model": state.action_default_model,
            "command_default_model": state.command_default_model,
            "selfie_schedule_enabled": state.selfie_schedule_enabled,
            "selfie_style": state.selfie_style,
        }


# 全局单例
runtime_state = RuntimeStateManager()
