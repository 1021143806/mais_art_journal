"""配置文件备份与版本管理

SDK 2.x 下 SDK 自带配置合并，本模块只负责升级时把旧 config.toml 拷到 old/。
"""

import datetime
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger("plugin.mais_art_journal.config_backup")


def backup_config_if_version_changed(
    plugin_dir: str,
    config_file_name: str,
    expected_version: str,
    current_version: Optional[str],
) -> None:
    """版本号不一致时备份当前 config.toml 到 old/ 子目录"""
    if not plugin_dir:
        return

    if current_version and str(current_version).strip() == str(expected_version).strip():
        return

    config_path = os.path.join(plugin_dir, config_file_name)
    if not os.path.exists(config_path):
        return

    old_dir = os.path.join(plugin_dir, "old")
    try:
        os.makedirs(old_dir, exist_ok=True)
    except OSError as e:
        logger.warning(f"创建备份目录失败: {old_dir} -> {e}")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    version_tag = (str(current_version).strip() or "unknown").replace("/", "_")
    backup_name = f"{config_file_name}.backup_{version_tag}_{timestamp}.toml"
    backup_path = os.path.join(old_dir, backup_name)

    try:
        shutil.copy2(config_path, backup_path)
        logger.info(
            f"配置版本变更 {current_version!r} -> {expected_version!r}，已备份到 {backup_path}"
        )
    except OSError as e:
        logger.warning(f"备份配置文件失败: {e}")
