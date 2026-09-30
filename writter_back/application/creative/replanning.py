"""自主改纲的接受门禁，与现有计划版本事务协作。"""

from application.creative.artifacts import workspace
from application.creative.policy import validate_replan, window_number
from application.creative.replan_audit import audit_replan


async def validate_autonomous_plan(state, config, proposed, proposal_id):
    """只有受约束的新模式可自动接受改纲，旧模式人工门禁不改变。"""
    if state.get("author_mode") != "autonomous_v1":
        return
    previous = state.get("novel_plan")
    if not previous:
        return
    generation = state.get("plan_generation") or {}
    if generation.get("mode") == "volume_detail" and not state.get("plan_replan_request"):
        return
    work = await workspace(config)
    records = await work.records("replan")
    accepted = [r for r in records if r["status"] == "accepted" and r["key"] != str(proposal_id)]
    chapter = int(state.get("current_chapter_index") or 0) + 1
    proposed_data = proposed.to_dict()
    changes_ending = previous["ending_contract"] != proposed_data["ending_contract"]
    validate_replan(
        chapter=chapter, total=proposed.scale.target_chapters,
        ending_changes=sum(bool(r["payload"].get("changes_ending")) for r in accepted),
        changes_ending=changes_ending,
        accepted_windows=[r["payload"]["window"] for r in accepted],
        scale_changed=previous["scale"] != proposed_data["scale"],
    )
    await audit_replan(work, previous, proposed_data, proposal_id)
    if not await work.latest("replan", str(proposal_id)):
        await work.save("replan", str(proposal_id), {
            "window": window_number(chapter), "changes_ending": changes_ending,
            "previous_plan_version": previous["version"], "chapter_number": chapter,
            "character_versions": {r["key"]: r["version"] for r in await work.records("character")},
            "foreshadow_versions": {r["key"]: r["version"] for r in await work.records("foreshadow")},
            "reader_versions": {r["key"]: r["version"] for r in await work.records("reader_state")},
        }, status="proposed", source="system", inputs={"plan": previous["version"]})


async def record_autonomous_acceptance(state, config, accepted, proposal_id):
    if state.get("author_mode") != "autonomous_v1":
        return {}
    work = await workspace(config)
    prior = await work.latest("replan", str(proposal_id))
    if prior and prior["status"] != "accepted":
        await work.save("replan", str(proposal_id), {**prior["payload"], "accepted_plan_version": accepted.version},
                        previous=prior, status="accepted", source="system")
    return {
        "tactical_window": None, "tactical_window_persisted": False,
        "memory_retrieved_for_chapter": None, "creative_decision_for_chapter": None,
    }
