from typing import Any

from pydantic import BaseModel, StrictBool, ValidationError


class PlanFulfillment(BaseModel):
    must_happen_covered: list[Any]
    missing_required_events: list[Any]
    state_delta_fulfilled: StrictBool
    deferred_items: list[Any]
    volume_boundary_breached: StrictBool
    core_arc_breached: StrictBool
    ending_contract_breached: StrictBool
    scale_change_required: StrictBool
    notes: str = ""


class TacticalFulfillment(BaseModel):
    tactical_goal_fulfilled: StrictBool
    approach_followed: StrictBool
    exit_hook_established: StrictBool
    deviations: list[Any]
    notes: str = ""


def normalize_fulfillment(value: Any, model: type[BaseModel]) -> dict[str, Any]:
    """校验模型兑现报告；缺失或错型保持未知，不生成成功事实。"""
    try:
        parsed = model.model_validate(value)
    except ValidationError as exc:
        invalid = sorted({str(error["loc"][0]) if error["loc"] else "report" for error in exc.errors()})
        return {"status": "unknown", "invalid_fields": invalid, "notes": "兑现报告不完整，需重新审阅"}
    return {**parsed.model_dump(), "status": "reviewed", "invalid_fields": []}


def fulfillment_passes(plan: dict, tactical: dict) -> bool:
    """只认可完整报告明确确认的计划和近期推进结果。"""
    if plan.get("status") != "reviewed" or tactical.get("status") != "reviewed":
        return False
    breaches = ("volume_boundary_breached", "core_arc_breached", "ending_contract_breached", "scale_change_required")
    goals = ("tactical_goal_fulfilled", "approach_followed", "exit_hook_established")
    return (
        plan["state_delta_fulfilled"] is True
        and not any(plan[field] for field in breaches)
        and not plan["missing_required_events"]
        and not plan["deferred_items"]
        and all(tactical[field] is True for field in goals)
        and not tactical["deviations"]
    )
