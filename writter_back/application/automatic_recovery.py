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
    metadata = dict(previous) if previous.get("chapter") == chapter else {}
    if "chapter" in previous and previous["chapter"] != chapter and "revision_attempts" in state:
        metadata["quality_revision_baseline"] = int(state.get("revision_attempts") or 0)
    return {"automatic_recovery": {**metadata, "chapter": chapter, "attempts": attempts}}


def quality_retry_update(state: dict) -> dict:
    """显式重试开启新一轮有限审读预算，保留累计修订与事实预算。"""
    chapter = int(state.get("current_chapter_index") or 0)
    previous = state.get("automatic_recovery") or {}
    recovery = dict(previous) if previous.get("chapter") == chapter else {}
    attempts = dict(recovery.get("attempts") or {})
    attempts.pop("质量审读", None)
    attempts.pop("审读重试", None)
    recovery.update(
        chapter=chapter, attempts=attempts,
        quality_revision_baseline=int(state.get("revision_attempts") or 0),
    )
    return {"automatic_recovery": recovery}


def quality_revision_update(state: dict, maximum: int) -> dict:
    """按已完成修订扣减预算，重复调度不额外占用一次修订。"""
    chapter = int(state.get("current_chapter_index") or 0)
    previous = state.get("automatic_recovery") or {}
    recovery: dict = dict(previous) if previous.get("chapter") == chapter else {
        "quality_revision_baseline": int(state.get("revision_attempts") or 0) if "chapter" in previous else 0,
    }
    current = int(state.get("revision_attempts") or 0)
    baseline = min(current, int(recovery.get("quality_revision_baseline") or 0))
    recovery["quality_revision_baseline"] = baseline
    completed = current - baseline
    attempts = {**(recovery.get("attempts") or {}), "质量审读": completed}
    recovery.update(chapter=chapter, attempts=attempts)
    return recovery_update({**state, "automatic_recovery": recovery}, "质量审读", maximum)
