"""
日程适配层

提供统一的日程/活动信息接口：
- ApiScheduleProvider: 通过 ctx.api.call 调用 autonomous_planning_plugin v4 暴露的
  ``xuqian13.autonomous-planning-plugin-v4.get_current_activity`` API（推荐）
- PlanningPluginProvider: 兼容旧版（v3 及以前）— 直接读 SQLite（不推荐，依赖对方
  的 schema，且在 SDK 子进程里需要文件路径推断成功）
- get_schedule_provider(ctx=None): 工厂函数
    * 传 ctx → 返回 ApiScheduleProvider（运行时调用 API，不可用时再回退到 SQLite）
    * 不传 ctx → 直接走 SQLite 旧路径
"""

import datetime
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from maibot_sdk.context import PluginContext

logger = logging.getLogger("plugin.mais_art_journal.schedule")

# 对外暴露的 autonomous_planning v4 API 全名
_PLANNING_API_NAME = "xuqian13.autonomous-planning-plugin-v4.get_current_activity"


class ActivityType(Enum):
    """活动类型枚举"""
    SLEEPING = "sleeping"
    WAKING_UP = "waking_up"
    EATING = "eating"
    WORKING = "working"
    STUDYING = "studying"
    EXERCISING = "exercising"
    RELAXING = "relaxing"
    SOCIALIZING = "socializing"
    COMMUTING = "commuting"
    HOBBY = "hobby"
    SELF_CARE = "self_care"
    OTHER = "other"


@dataclass
class ActivityInfo:
    """活动信息数据类 - 统一的活动描述格式"""
    activity_type: ActivityType
    description: str          # 活动描述（中文）
    mood: str = "neutral"     # 情绪
    time_point: str = ""      # 时间点 "HH:MM"


# ==================== 活动类型映射（API + SQLite 共用） ====================

_TYPE_KEYWORD_MAP: Dict[str, ActivityType] = {
    # 英文关键词
    "work": ActivityType.WORKING,
    "study": ActivityType.STUDYING,
    "exercise": ActivityType.EXERCISING,
    "eat": ActivityType.EATING,
    "meal": ActivityType.EATING,
    "rest": ActivityType.RELAXING,
    "relax": ActivityType.RELAXING,
    "social": ActivityType.SOCIALIZING,
    "hobby": ActivityType.HOBBY,
    "sleep": ActivityType.SLEEPING,
    "self_care": ActivityType.SELF_CARE,
    "commut": ActivityType.COMMUTING,
    # 中文关键词
    "工作": ActivityType.WORKING,
    "办公": ActivityType.WORKING,
    "会议": ActivityType.WORKING,
    "学习": ActivityType.STUDYING,
    "阅读": ActivityType.STUDYING,
    "读书": ActivityType.STUDYING,
    "审阅": ActivityType.STUDYING,
    "看书": ActivityType.STUDYING,
    "研究": ActivityType.STUDYING,
    "运动": ActivityType.EXERCISING,
    "锻炼": ActivityType.EXERCISING,
    "健身": ActivityType.EXERCISING,
    "散步": ActivityType.EXERCISING,
    "吃": ActivityType.EATING,
    "餐": ActivityType.EATING,
    "料理": ActivityType.EATING,
    "烹饪": ActivityType.EATING,
    "休息": ActivityType.RELAXING,
    "放松": ActivityType.RELAXING,
    "泡澡": ActivityType.RELAXING,
    "泡浴": ActivityType.RELAXING,
    "聊天": ActivityType.SOCIALIZING,
    "交流": ActivityType.SOCIALIZING,
    "社交": ActivityType.SOCIALIZING,
    "睡": ActivityType.SLEEPING,
    "梦": ActivityType.SLEEPING,
    "入眠": ActivityType.SLEEPING,
    "午休": ActivityType.SLEEPING,
    "小憩": ActivityType.SLEEPING,
    "梳妆": ActivityType.SELF_CARE,
    "打扮": ActivityType.SELF_CARE,
    "化妆": ActivityType.SELF_CARE,
    "护肤": ActivityType.SELF_CARE,
    "通勤": ActivityType.COMMUTING,
    "赶路": ActivityType.COMMUTING,
    "出行": ActivityType.COMMUTING,
}


def _classify_activity(*hints: str) -> ActivityType:
    """根据多个候选字段（goal_type / name / description）猜活动类型，找不到返回 OTHER"""
    haystack = " ".join((h or "") for h in hints).lower()
    if not haystack.strip():
        return ActivityType.OTHER
    for key, atype in _TYPE_KEYWORD_MAP.items():
        if key in haystack:
            return atype
    return ActivityType.OTHER


# ==================== Provider 基类 ====================

class ScheduleProvider:
    """日程提供者基类"""

    async def get_current_activity(self) -> Optional[ActivityInfo]:
        """获取当前时间对应的活动信息"""
        raise NotImplementedError


# ==================== API 路径（推荐） ====================

class ApiScheduleProvider(ScheduleProvider):
    """通过 SDK API 调用 autonomous_planning_plugin v4 取当前活动

    优点：完全走 SDK 能力代理，不耦合对方的 SQLite 表结构，不依赖文件路径推断；
    当对方插件未加载 / 未到 v4 / API 不可见时调用会失败，本类自动回退到
    SQLite provider（如果能找到 db 文件）。
    """

    def __init__(self, ctx: "PluginContext", chat_id: str = "global"):
        self._ctx = ctx
        self._chat_id = chat_id or "global"
        # 懒加载的 SQLite fallback
        self._sqlite_fallback: Optional[PlanningPluginProvider] = None
        self._sqlite_fallback_inited: bool = False

    async def get_current_activity(self) -> Optional[ActivityInfo]:
        snapshot = await self._call_api()
        if snapshot is not None:
            return self._snapshot_to_activity(snapshot)
        # API 调用失败 → 回退 SQLite
        fallback = self._get_sqlite_fallback()
        if fallback is not None:
            logger.info("autonomous_planning API 不可用，回退到 SQLite 直读")
            return await fallback.get_current_activity()
        return None

    async def _call_api(self) -> Optional[Dict[str, Any]]:
        try:
            result = await self._ctx.api.call(_PLANNING_API_NAME, chat_id=self._chat_id)
        except Exception as exc:
            logger.debug(f"调用 autonomous_planning API 失败: {exc}")
            return None
        if not isinstance(result, dict):
            return None
        if result.get("error"):
            logger.debug(f"autonomous_planning API 返回错误: {result.get('error')}")
            return None
        return result

    @staticmethod
    def _snapshot_to_activity(snapshot: Dict[str, Any]) -> Optional[ActivityInfo]:
        """把 v4 API 返回结构映射成本插件用的 ActivityInfo"""
        if not snapshot.get("has_activity"):
            return None
        activity = snapshot.get("activity")
        if not isinstance(activity, dict):
            return None

        name = str(activity.get("name") or "").strip()
        description = str(activity.get("description") or "").strip() or name or "日常活动"
        goal_type = str(activity.get("goal_type") or "").strip()
        activity_type = _classify_activity(goal_type, name, description)

        # 用 time_window 的开始时间作为 time_point；缺失就用 as_of 截到 HH:MM
        time_window = str(activity.get("time_window") or "").strip()
        time_point = ""
        if time_window and "-" in time_window:
            time_point = time_window.split("-", 1)[0].strip()
        if not time_point:
            as_of = str(snapshot.get("as_of") or "")
            # 期望 ISO 形如 2026-05-25T14:30:00+08:00
            if "T" in as_of:
                time_point = as_of.split("T", 1)[1][:5]
        if not time_point:
            time_point = datetime.datetime.now().strftime("%H:%M")

        return ActivityInfo(
            activity_type=activity_type,
            description=description,
            mood="neutral",
            time_point=time_point,
        )

    def _get_sqlite_fallback(self) -> Optional["PlanningPluginProvider"]:
        if self._sqlite_fallback_inited:
            return self._sqlite_fallback
        self._sqlite_fallback_inited = True
        self._sqlite_fallback = _build_sqlite_provider()
        return self._sqlite_fallback


# ==================== SQLite 直读路径（fallback） ====================

class PlanningPluginProvider(ScheduleProvider):
    """
    从 autonomous_planning 插件的 SQLite 数据库读取日程（fallback / 老版本兼容）

    goals 表结构关键字段：
    - goal_id, name, description, goal_type, status, created_at
    - parameters (JSON): 包含 time_window: [start_minutes, end_minutes]
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        logger.info(f"PlanningPluginProvider (SQLite fallback) 初始化, db: {db_path}")

    async def get_current_activity(self) -> Optional[ActivityInfo]:
        try:
            if not os.path.exists(self.db_path):
                return None

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            now = datetime.datetime.now()
            current_time_str = now.strftime("%H:%M")
            today_str = now.strftime("%Y-%m-%d")
            current_minutes = now.hour * 60 + now.minute

            rows = []
            try:
                cursor.execute("""
                    SELECT * FROM goals
                    WHERE status = 'active'
                    AND substr(created_at, 1, 10) = ?
                    ORDER BY created_at DESC
                    LIMIT 20
                """, (today_str,))
                rows = cursor.fetchall()
            except Exception:
                pass

            if not rows:
                logger.debug("今天没有活跃目标，回退到最近的活跃记录")
                cursor.execute("""
                    SELECT * FROM goals
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                    LIMIT 20
                """)
                rows = cursor.fetchall()

            conn.close()

            if not rows:
                return None

            for row in rows:
                row_dict = dict(row)
                time_window = self._extract_time_window(row_dict)
                if time_window and len(time_window) == 2:
                    start_min, end_min = int(time_window[0]), int(time_window[1])
                    if self._is_minutes_in_range(current_minutes, start_min, end_min):
                        return self._row_to_activity(row_dict, current_time_str)

            first = dict(rows[0])
            return self._row_to_activity(first, current_time_str)

        except Exception as e:
            logger.error(f"PlanningPluginProvider 查询失败: {e}")
            return None

    @staticmethod
    def _extract_time_window(row: dict) -> Optional[List[int]]:
        params_raw = row.get("parameters")
        if not params_raw:
            return None
        try:
            params = json.loads(params_raw) if isinstance(params_raw, str) else params_raw
            return params.get("time_window")
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _row_to_activity(row: dict, current_time: str) -> ActivityInfo:
        description = row.get("description", "") or row.get("name", "") or "日常活动"
        goal_type = row.get("goal_type", "") or ""
        activity_type = _classify_activity(goal_type, description)
        return ActivityInfo(
            activity_type=activity_type,
            description=description,
            mood="neutral",
            time_point=current_time,
        )

    @staticmethod
    def _is_minutes_in_range(current: int, start: int, end: int) -> bool:
        if end < start:
            return current >= start or current <= end
        return start <= current <= end


# ==================== 工厂 ====================

def _build_sqlite_provider(
    planning_db_search_dirs: Optional[list] = None,
) -> Optional[PlanningPluginProvider]:
    """搜索 autonomous_planning 的 SQLite db；找不到返回 None"""
    if planning_db_search_dirs is None:
        # __file__ = plugins/mais_art_journal/core/selfie/schedule_provider.py
        # 需要回到 plugins/ 目录（4 层 dirname）
        plugins_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        planning_db_search_dirs = [
            os.path.join(plugins_dir, "xuqian13_autonomous-planning-plugin-v4"),
            os.path.join(plugins_dir, "autonomous_planning_plugin"),
            os.path.join(plugins_dir, "autonomous_planning"),
        ]

    for search_dir in planning_db_search_dirs:
        if not os.path.isdir(search_dir):
            continue
        check_dirs = [search_dir, os.path.join(search_dir, "data"), os.path.join(search_dir, "database")]
        for check_dir in check_dirs:
            if not os.path.isdir(check_dir):
                continue
            for fname in os.listdir(check_dir):
                if fname.endswith((".db", ".sqlite", ".sqlite3")):
                    db_path = os.path.join(check_dir, fname)
                    try:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='goals'")
                        if cursor.fetchone():
                            conn.close()
                            logger.info(f"找到 autonomous_planning 数据库: {db_path}")
                            return PlanningPluginProvider(db_path)
                        conn.close()
                    except Exception:
                        pass
    return None


def get_schedule_provider(
    ctx: Optional["PluginContext"] = None,
    chat_id: str = "global",
    planning_db_search_dirs: Optional[list] = None,
) -> Optional[ScheduleProvider]:
    """工厂函数：返回可用的日程 provider

    Args:
        ctx: SDK PluginContext；传入后走 API 调用路径（内置 SQLite fallback）
        chat_id: API 调用时使用的会话作用域，默认 ``global``
        planning_db_search_dirs: 仅 ctx=None 时使用，搜索 SQLite db 的目录列表

    Returns:
        ScheduleProvider 实例；ctx 为空且 SQLite 也找不到时返回 None
    """
    if ctx is not None:
        return ApiScheduleProvider(ctx, chat_id=chat_id)

    fallback = _build_sqlite_provider(planning_db_search_dirs)
    if fallback is None:
        logger.warning("未找到 autonomous_planning 数据库（且未提供 ctx）")
    return fallback
