"""Bind planning generation to admitted intent rather than historical plan prose."""

from application.character_source_names import engine_name_view
from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.prompts.template_loader import render_prompt


async def planning_author_truth(state, config):
    if state.get("author_mode") != "autonomous_v1":
        return None
    work = await workspace(config)
    selection = await work.latest("selection", "accepted")
    if not selection or selection["status"] != "accepted":
        raise CreativePause("plan_generation_source", "整书规划缺少已接受的立项来源")
    payload = selection["payload"]
    projected = await engine_name_view(work, state, {
        "brief": payload.get("brief") or {}, "engine": payload.get("engine") or {},
    })
    return {
        "selection_version": selection["version"],
        "author_constraints": {
            key: value for key, value in work.session["config"].items()
            if key not in {"budget", "sources", "research_queries"}
        },
        **projected,
    }


def planning_volume_view(author_truth, volume):
    if author_truth is None:
        return volume
    return {key: value for key, value in volume.items() if key not in {"setup_ids", "payoff_ids"}}


def _blueprint_view(author_truth, blueprint):
    if not blueprint:
        return {}
    return {
        **blueprint,
        "volumes": [planning_volume_view(author_truth, volume) for volume in blueprint["volumes"]],
    }


def planning_generation_rules(author_truth, blueprint=None, prior_slots=()):
    if author_truth is None:
        return ""
    fields = ("chapter_number", "story_function", "must_happen", "planned_state_delta")
    history = [{key: slot[key] for key in fields if key in slot} for slot in prior_slots]
    return "\n" + render_prompt(
        "creative/plan_generation_consistency_v1.txt", include_active_rules=False,
        context=json_text({
            "author_truth": author_truth, "blueprint": _blueprint_view(author_truth, blueprint),
            "prior_planned_events": history,
        }),
    )


def _foreshadow_ledger(prior_slots):
    ledger = {}
    for slot in prior_slots:
        for source, target in (("setup_ids", "setup_chapters"), ("payoff_ids", "payoff_chapters")):
            for identity in slot.get(source) or []:
                entry = ledger.setdefault(str(identity), {"setup_chapters": [], "payoff_chapters": []})
                entry[target].append(int(slot["chapter_number"]))
    return ledger


def planning_reference_rules(generation, volume):
    if generation.get("author_truth") is None:
        return ""
    prior = sorted(
        (slot for slot in generation["chapter_slots"]
         if int(slot["chapter_number"]) < volume.start_chapter),
        key=lambda slot: int(slot["chapter_number"]),
    )
    arcs = generation["blueprint"]["arcs"]
    allowed = {
        str(chapter): [
            arc["arc_id"] for arc in arcs
            if int(arc["start_chapter"]) <= chapter <= int(arc["end_chapter"])
        ]
        for chapter in range(volume.start_chapter, volume.end_chapter + 1)
    }
    return "\n" + render_prompt(
        "creative/plan_reference_contract_v1.txt", include_active_rules=False,
        context=json_text({
            "prior_foreshadowing": _foreshadow_ledger(prior),
            "arc_ids_by_chapter": allowed,
        }),
    )
