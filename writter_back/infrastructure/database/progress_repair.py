"""Book-scoped owner opt-in; authorization cannot alter physical budgets."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from application.creative.errors import CreativeConflict
from infrastructure.database.creative_commands import record_control, replay_control
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.creative_repository import _digest, lock_creative_novel, row_dict
from infrastructure.database.models import TenantModel
from infrastructure.database.runtime_models import WorkflowEventModel
from service.value_objects.creative_budget import ProgressRepairPolicy, model_spent


class RepairPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    expected_total: int = Field(ge=1)
    expected_spent: int = Field(ge=0)
    mode: Literal["progress_v1"]
    chapter: int = Field(ge=1, le=200)
    event_sequence: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


async def _initial_review(session, context, novel_id, payload):
    event = await session.scalar(select(WorkflowEventModel).where(
        WorkflowEventModel.tenant_id == context.tenant_id, WorkflowEventModel.novel_id == novel_id,
        WorkflowEventModel.payload["type"].astext == "quality",
        WorkflowEventModel.payload["node"].astext == "reflection_node",
    ).order_by(WorkflowEventModel.sequence.desc()).limit(1))
    if event is None or event.sequence != payload.event_sequence:
        raise CreativeConflict("定向审读报告不存在或已更新")
    gate = event.payload.get("data") or {}
    report = gate.get("goal_acceptance") or {}
    issues = gate.get("issues") or []
    if (gate.get("chapter_number") != payload.chapter or gate.get("decision") != "patch"
        or report.get("status") != "passed" or report.get("content_hash") != payload.content_hash
        or report.get("contract_id") != payload.contract_id
        or not any(row.get("priority_action") == "must_fix" and row.get("evidence_valid") is True
            and not row.get("issue_resolved") for row in issues)):
        raise ValueError("当前定向修订必须基于完整目标通过的真实问题报告")
    return {"chapter": payload.chapter, "content_hash": payload.content_hash,
        "contract_id": payload.contract_id, "gate": gate,
        "event_sequence": event.sequence, "event_digest": _digest(event.payload)}


def _validate_activation(row, tenant, payload):
    if (row is None or row.version != payload.expected_version or row.limits["total"] != payload.expected_total
        or row.counters.get(f"chapter:{payload.chapter}", 0) != payload.expected_spent):
        raise CreativeConflict("预算版本、总额或已发生消耗已更新")
    if row.config.get("repair_policy"):
        raise CreativeConflict("当前作品修订策略已启用，不能重复重置授权")
    if ("policy" not in row.limits or row.limits["total"] > tenant.autonomous_request_limit
        or model_spent(row.counters) > row.limits["total"]):
        raise ValueError("修订策略不能突破原始整书和租户预算")


async def activate_repair_policy(repo, context, novel_id, payload, key):
    async with repo.sessions.begin() as session:
        await lock_creative_novel(session, context.tenant_id, novel_id)
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id, CreativeSessionModel.novel_id == novel_id,
        ).with_for_update())
        command = {"operation": "repair_policy", "actor_id": str(context.user_id), **payload.model_dump(mode="json")}
        previous = await replay_control(session, context.tenant_id, novel_id, key, command)
        if previous is not None:
            return previous
        _validate_activation(row, await session.get(TenantModel, context.tenant_id), payload)
        initial = await _initial_review(session, context, novel_id, payload)
        policy = ProgressRepairPolicy(mode=payload.mode).model_dump(mode="json")
        row.config = {**row.config, "repair_policy": policy, "repair_policy_review": initial}
        row.version += 1
        await session.flush()
        result = row_dict(row)
        record_control(session, context.tenant_id, novel_id, key, command, result)
        return result
