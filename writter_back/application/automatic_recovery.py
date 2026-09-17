"""自动推进的有限修复预算，不替代事实与目标验收。"""

from application.errors import AutomaticRecoveryExhausted


def recovery_update(state: dict, stage: str, maximum: int = 2) -> dict:
    """按章节持久化修复次数，断线或恢复不得重置预算。"""
    chapter = int(state.get("current_chapter_index") or 0)
    previous = state.get("automatic_recovery") or {}
    attempts = dict(previous.get("attempts") or {}) if previous.get("chapter") == chapter else {}
    count = int(attempts.get(stage) or 0)
    if count >= maximum:
        raise AutomaticRecoveryExhausted(
            f"{stage}自动修复已达上限，当前草稿已保留，未跳过验收归档"
        )
    attempts[stage] = count + 1
    return {"automatic_recovery": {"chapter": chapter, "attempts": attempts}}
