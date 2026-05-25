"""Pipeline Step 的返回类型

每个 Step.run 返回 None（等价于 continue）或一个 StepResult：
- continue: 继续下一步
- skip_remaining: 跳出循环但仍当成功
- fail: 终止 pipeline，标记失败并发送 user_message
- done: 终止 pipeline，标记成功
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


StepAction = Literal["continue", "skip_remaining", "fail", "done"]


@dataclass
class StepResult:
    action: StepAction
    error: Optional[str] = None
    user_message: Optional[str] = None

    # ---- 工厂方法 ----
    @classmethod
    def cont(cls) -> "StepResult":
        return cls(action="continue")

    @classmethod
    def skip_remaining(cls, user_message: Optional[str] = None) -> "StepResult":
        return cls(action="skip_remaining", user_message=user_message)

    @classmethod
    def fail(cls, error: str, user_message: Optional[str] = None) -> "StepResult":
        return cls(action="fail", error=error, user_message=user_message)

    @classmethod
    def done(cls, user_message: Optional[str] = None) -> "StepResult":
        return cls(action="done", user_message=user_message)
