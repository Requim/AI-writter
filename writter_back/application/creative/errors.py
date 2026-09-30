"""可恢复的自主创作边界错误。"""


class CreativePause(RuntimeError):
    """必需条件不满足时暂停，不能静默降级为旧模式。"""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class CreativeConflict(ValueError):
    """幂等键复用或输入版本过期。"""
