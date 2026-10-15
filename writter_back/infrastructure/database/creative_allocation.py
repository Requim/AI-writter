"""Atomic persistent cycle holds, kept separately from physical spend."""

from uuid import UUID

from sqlalchemy import select

from application.creative.errors import CreativePause
from application.goal_contract import fingerprint
from infrastructure.database.creative_models import CreativeRecordModel, CreativeSessionModel
from service.value_objects.creative_budget import ElasticBudgetPolicy, ProgressRepairPolicy, budget_capacity


async def locked_session(session, tenant, novel):
    from infrastructure.database.creative_repository import _check_feature, lock_creative_novel

    await lock_creative_novel(session, tenant, novel)
    row = await session.scalar(select(CreativeSessionModel).where(
        CreativeSessionModel.tenant_id == tenant, CreativeSessionModel.novel_id == novel,
    ).with_for_update())
    if row is None:
        raise CreativePause("session_missing", "缺少持久化创作会话")
    await _check_feature(session, tenant)
    return row


def round_audit(session, row, current, operation):
    key = f"budget-round:{current['id']}:{operation}"
    payload = {**current, "operation": operation}
    session.add(CreativeRecordModel(
        tenant_id=row.tenant_id, novel_id=row.novel_id, kind="control",
        key=key, version=1, idempotency_key=key, digest=fingerprint(payload),
        payload=payload, status="accepted", source="system", input_versions={}, evidence=[],
    ))


def _round_size(row, policy, purpose):
    if purpose == "repair_progress":
        approved = row.config.get("repair_policy")
        if approved is None:
            raise CreativePause("repair_policy_missing", "当前作品未授权按进展修订")
        progress = ProgressRepairPolicy.model_validate(approved)
        return progress.local_preferred, progress.local_minimum
    size = {"repair": policy.repair_round, "review": policy.review_round,
        "repair_local": policy.local_repair_round}[purpose]
    return size, policy.repair_minimum if purpose == "repair" else size


async def _require_fresh_round(session, row, bucket, source, purpose):
    purposes = ("repair", "repair_local", "repair_progress") if purpose.startswith("repair") else (purpose,)
    keys = [f"budget-round:{fingerprint({'bucket': bucket, 'source': source, 'purpose': item})}:begin"
        for item in purposes]
    prior = await session.scalar(select(CreativeRecordModel.id).where(
        CreativeRecordModel.tenant_id == row.tenant_id, CreativeRecordModel.novel_id == row.novel_id,
        CreativeRecordModel.idempotency_key.in_(keys),
    ))
    if prior:
        raise CreativePause("budget_no_progress", "同一正文的已结束预算轮次不能重复领取额度")


async def begin_budget_round(repository, tenant_id, novel_id, bucket, source, purpose):
    if purpose not in {"review", "repair", "repair_local", "repair_progress"}:
        raise ValueError("未知预算轮次用途")
    async with repository.sessions.begin() as session:
        row = await locked_session(session, UUID(tenant_id), UUID(novel_id))
        if "policy" not in row.limits:
            return
        policy = ElasticBudgetPolicy.model_validate(row.limits["policy"])
        size, minimum = _round_size(row, policy, purpose)
        identity = fingerprint({"bucket": bucket, "source": source, "purpose": purpose})
        current = row.limits.get("round") or {}
        if current.get("status") == "active" and current.get("bucket") == bucket:
            if current["id"] == identity or purpose == "review":
                return dict(current)
        await _require_fresh_round(session, row, bucket, source, purpose)
        available = budget_capacity(row.limits, row.counters, bucket, include_round=False)
        if available < minimum:
            raise CreativePause("budget_exhausted", f"{bucket} 剩余可分配额度{available}，不足完整{purpose}轮次至少所需{minimum}")
        size = min(size, available)
        if current.get("status") == "active":
            round_audit(session, row, {**current, "status": "released"}, "release")
        current = {"id": identity, "bucket": bucket, "source": source,
            "purpose": purpose, "size": size, "remaining": size, "status": "active"}
        row.limits = {**row.limits, "round": current}
        round_audit(session, row, current, "begin")
        return dict(current)


async def release_budget_round(repository, tenant_id, novel_id, bucket):
    async with repository.sessions.begin() as session:
        row = await locked_session(session, UUID(tenant_id), UUID(novel_id))
        current = row.limits.get("round") or {}
        if current.get("status") != "active" or current.get("bucket") != bucket:
            return
        current = {**current, "status": "released"}
        row.limits = {**row.limits, "round": current}
        round_audit(session, row, current, "release")


def request_allocation(limits, counters, bucket):
    """Return updated hold and a reservation receipt; neither refunds spend."""
    current = limits.get("round") or {}
    policy = limits.get("policy") or {}
    metadata = {"policy": policy.get("mode", "fixed_v1"), "bucket": bucket,
        "soft_threshold_exceeded": counters.get(bucket, 0) > limits.get(bucket.split(":")[0], 0)}
    if current.get("status") == "active" and current.get("bucket") == bucket:
        limits = {**limits, "round": {**current, "remaining": current["remaining"] - 1}}
        metadata.update(round_id=current["id"], purpose=current["purpose"])
    return limits, {"budget": metadata}
