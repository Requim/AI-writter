"""自动推进的有限修复预算，不替代事实与目标验收。"""

from collections import Counter
from uuid import UUID

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
    confirmations = _fact_confirmation_attempts(state, baseline, current)
    completed = current - baseline - len(confirmations)
    if confirmations:
        if completed >= maximum:
            raise AutomaticRecoveryExhausted("质量审读自动修复已达上限，当前草稿已保留，未跳过验收归档")
        attempts = dict(recovery.get("attempts") or {})
        attempts["质量审读"] = max(int(attempts.get("质量审读") or 0), completed + 1)
        recovery.update(chapter=chapter, attempts=attempts, quality_accounting={
            "version": 1, "completed": completed, "requested": completed + 1,
            "maximum": maximum, "fact_confirmation_attempts": confirmations,
        })
        return {"automatic_recovery": recovery}
    attempts = {**(recovery.get("attempts") or {}), "质量审读": completed}
    recovery.update(chapter=chapter, attempts=attempts)
    return recovery_update({**state, "automatic_recovery": recovery}, "质量审读", maximum)


def quality_progress_update(state: dict, proof: dict) -> dict:
    """Progress authorization changes the stop rule, never past fact/spend counts."""
    chapter = int(state.get("current_chapter_index") or 0)
    previous = state.get("automatic_recovery") or {}
    current = int(state.get("revision_attempts") or 0)
    recovery = dict(previous) if previous.get("chapter") == chapter else {
        "quality_revision_baseline": current if "chapter" in previous else 0}
    baseline = min(current, int(recovery.get("quality_revision_baseline") or 0))
    confirmations = _fact_confirmation_attempts(state, baseline, current)
    completed = current - baseline - len(confirmations)
    attempts = dict(recovery.get("attempts") or {})
    attempts["质量审读"] = max(int(attempts.get("质量审读") or 0), completed + 1)
    recovery.update(chapter=chapter, quality_revision_baseline=baseline, attempts=attempts,
        quality_accounting={"version": 2, "mode": "progress_v1", "completed": completed,
            "requested": completed + 1, "fact_confirmation_attempts": confirmations},
        repair_progress=proof)
    return {"automatic_recovery": recovery}


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _fact_confirmation(entry: dict) -> bool:
    proof = entry.get("fact_staging_rebind")
    if not isinstance(proof, dict):
        return False
    try:
        UUID(proof.get("proposal_id"))
    except (ValueError, TypeError, AttributeError):
        return False
    return (entry.get("issues_before") == []
        and _valid_hash(entry.get("before_hash"))
        and entry.get("before_hash") == entry.get("after_hash")
        and _valid_hash(proof.get("source_hash"))
        and proof["source_hash"] != entry["before_hash"]
        and _valid_hash(proof.get("fact_report_digest")))


def _fact_confirmation_attempts(state: dict, baseline: int, current: int) -> list[int]:
    if state.get("author_mode") != "autonomous_v1":
        return []
    from application.goal_contract import current_goal_contract

    contract = current_goal_contract(state)
    if contract is None:
        return []
    history = [entry for entry in state.get("revision_history") or []
        if isinstance(entry, dict) and entry.get("goal_contract_id") == contract["id"]
        and type(entry.get("attempt")) is int and baseline < entry["attempt"] <= current]
    counts = Counter(entry["attempt"] for entry in history)
    return sorted(entry["attempt"] for entry in history
        if counts[entry["attempt"]] == 1 and _fact_confirmation(entry))
