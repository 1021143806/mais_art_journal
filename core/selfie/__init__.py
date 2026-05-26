"""自拍子系统：日程读取 + 配文生成 + 自动自拍后台任务

注意：避免在顶层 import auto_selfie_task，防止与 prompts 模块的循环依赖。
外部调用方请使用完整路径 `from .core.selfie.auto_selfie_task import AutoSelfieTask`。
"""
