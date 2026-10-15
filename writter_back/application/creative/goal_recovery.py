"""Restore lost goal sources only when persisted author truth matches the bound contract."""

from application.errors import QualityGateReviewRequired
from application.goal_contract import compile_goal_contract


async def restore_goal_brief(state: dict, values: dict) -> tuple[dict, dict]:
    outlines = state.get("chapter_outlines") or []
    contract = outlines[-1].get("goal_contract") if outlines else None
    if not contract:
        return state, {}
    expected_brief = contract["source"]["brief"]
    total = state.get("total_outline") or {}
    brief = state.get("creative_brief") or total.get("creative_brief") or {}
    if not (expected_brief.keys() - brief.keys()):
        return state, {}
    repository = values.get("novel_repository")
    if repository is None:
        raise QualityGateReviewRequired("目标来源缺失且无法从已保存作品复核")
    novel = await repository.find_by_id(values["tenant_id"], values["novel_id"])
    if novel is None or (str(novel.tenant_id), str(novel.id)) != (
        str(values["tenant_id"]), str(values["novel_id"]),
    ):
        raise QualityGateReviewRequired("目标来源恢复的作品归属不匹配")
    saved = getattr(getattr(novel, "total_outline", None), "creative_brief", None)
    if not isinstance(saved, dict):
        raise QualityGateReviewRequired("已保存作品没有可复核的目标来源")
    restored = {**saved, **brief}
    update = {"creative_brief": restored, "total_outline": {**total, "creative_brief": {**saved,
        **(total.get("creative_brief") or {})}}}
    candidate = {**state, **update}
    if compile_goal_contract(candidate) != contract:
        raise QualityGateReviewRequired("已保存作品目标与原契约不匹配，不能自动恢复")
    return candidate, update
