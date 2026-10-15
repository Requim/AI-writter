"""Owner-authorized first-chapter extension with immutable review provenance."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from application.creative.errors import CreativeConflict
from application.creative.scoped_goal_repair import failed_repair_goal
from infrastructure.database.creative_commands import record_control, replay_control
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.creative_repository import _digest, lock_creative_novel, row_dict
from infrastructure.database.models import TenantModel
from infrastructure.database.runtime_models import WorkflowEventModel
from service.value_objects.creative_budget import model_spent


class GoalRepairUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    expected_total: int = Field(ge=1)
    expected_spent: int = Field(ge=0, le=64)
    chapter: Literal[1]
    chapter_hard: Literal[72]
    additional_goal_repairs: Literal[1]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    goal_id: str = Field(pattern=r"^ch1:must:[1-9][0-9]*$")
    event_sequence: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


async def _review_evidence(session, context, novel_id, payload):
    event = await session.scalar(select(WorkflowEventModel).where(
        WorkflowEventModel.tenant_id == context.tenant_id, WorkflowEventModel.novel_id == novel_id,
        WorkflowEventModel.payload["type"].astext == "quality",
        WorkflowEventModel.payload["node"].astext == "reflection_node",
    ).order_by(WorkflowEventModel.sequence.desc()).limit(1))
    if event is None or event.sequence != payload.event_sequence:
        raise CreativeConflict("授权审读报告不存在或已被更新")
    gate = event.payload.get("data") or {}
    if not failed_repair_goal(gate, payload.model_dump(mode="json")):
        raise ValueError("只允许修复当前审读唯一失败且有原文证据的必达事件")
    return gate, {"sequence": event.sequence, "run_id": str(event.run_id), "digest": _digest(event.payload)}


def _validate_budget(row, payload, tenant):
    if (row is None or row.version != payload.expected_version
        or row.limits["total"] != payload.expected_total
        or row.counters.get("chapter:1", 0) != payload.expected_spent):
        raise CreativeConflict("预算版本、总额或第一章消耗已更新")
    if "chapter_extension" in row.limits or row.config.get("goal_repair"):
        raise CreativeConflict("第一章定向修订已授权，不能叠加或重置")
    if ("policy" not in row.limits or row.limits["total"] > tenant.autonomous_request_limit
        or model_spent(row.counters) > row.limits["total"]):
        raise ValueError("授权不能突破整书与租户预算")


async def authorize_goal_repair(repo, context, novel_id, payload, key):
    async with repo.sessions.begin() as session:
        await lock_creative_novel(session, context.tenant_id, novel_id)
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id, CreativeSessionModel.novel_id == novel_id,
        ).with_for_update())
        command = {"operation": "scoped_goal_repair", "actor_id": str(context.user_id),
            **payload.model_dump(mode="json")}
        previous = await replay_control(session, context.tenant_id, novel_id, key, command)
        if previous is not None:
            return previous
        tenant = await session.get(TenantModel, context.tenant_id)
        _validate_budget(row, payload, tenant)
        gate, evidence = await _review_evidence(session, context, novel_id, payload)
        control_id = _digest(command)
        row.limits = {**row.limits, "chapter_extension": {
            "chapter": 1, "chapter_hard": 72, "control_id": control_id}}
        row.config = {**row.config, "goal_repair": {
            **payload.model_dump(mode="json"), "id": control_id, "gate": gate, "evidence": evidence}}
        row.version += 1
        await session.flush()
        result = row_dict(row)
        record_control(session, context.tenant_id, novel_id, key, command, result)
        return result
