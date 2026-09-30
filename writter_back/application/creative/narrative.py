"""人物主线决策，未来角色槽位和一次受控重规划入口。"""

from typing import Literal
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.creative.policy import choose_route, window_number
from application.creative.runtime import active_creative_rules
from application.creative.names import refill_name_pool
from application.creative.threads import initialize_plan_threads
from application.creative.cast import align_cast_to_plan, bind_introduced_slot
from application.creative.direct_feedback import dispatch_author_feedback, file_fact_feedback
from service.value_objects.creative import CharacterNarrative, RoleSlot

DECISION_SCHEMA = {
    "critical_turn": "boolean", "routes": "array", "current_action": "object",
    "chapter_intent": "object", "character_ids": "array", "arc_ids": "array",
    "due_foreshadow_ids": "array", "reason": "string",
}


async def creative_decision_node(state: dict, config: RunnableConfig) -> Command[Literal["router_agent", "novel_plan_initialize_node"]]:
    """在细纲前判断人物行动；无合理路线可拒绝，不强迫人物配合计划。"""
    work = await workspace(config)
    await file_fact_feedback(work)
    instruction = await dispatch_author_feedback(work, state)
    if instruction:
        return instruction
    await initialize_cast(work, state)
    await initialize_plan_threads(work, state)
    await align_cast_to_plan(work, state)
    chapter = int(state.get("current_chapter_index") or 0) + 1
    version = int((state.get("novel_plan") or {}).get("version") or 0)
    key = f"{chapter}:plan{version}"
    saved = await work.latest("decision", key)
    if not saved:
        saved = await _generate_decision(work, state, chapter, version, key)
    result = saved["payload"]
    if result["route_result"]["status"] == "no_feasible_route":
        return await _replan_once(work, state, chapter, result)
    total = await refill_name_pool(work, state, chapter)
    return Command(goto="router_agent", update={"creative_decision_for_chapter": chapter, "total_outline": total})


async def initialize_cast(work, state):
    total = state.get("total_outline") or {}
    for raw in total.get("main_characters", []):
        key = raw.get("character_id")
        if not key:
            raise CreativePause("character_identity", "自主模式人物必须使用稳定ID")
        if not await work.latest("character", key):
            card = _initial_character(raw, work.novel_id)
            await work.save("character", key, card.model_dump(mode="json"), status="planned", source="system")
        await bind_introduced_slot(work, raw)
    selection = await work.latest("selection", "accepted")
    if selection:
        await _initialize_slots(work, selection["payload"])


def _initial_character(raw, novel_id):
    profile = raw.get("profile") or {}
    return CharacterNarrative(
        character_id=raw["character_id"], story_entity_id=uuid5(UUID(novel_id), "character:" + raw["character_id"]),
        name=raw["name"], role="core" if raw.get("role_type") in {"protagonist", "antagonist", "core"} else "supporting",
        narrative_center=raw.get("role_type") == "protagonist",
        goal=str(profile.get("external_goal") or ""), lack=str(profile.get("internal_lack") or ""),
        belief=str(profile.get("false_belief") or ""), red_line=str(profile.get("moral_red_line") or ""),
        abilities=_strings(profile.get("abilities")), limits=_strings(profile.get("limitations")),
        voice=str(profile.get("speech_fingerprint") or profile.get("speech_style") or profile.get("speech_pattern") or ""),
    )


def _strings(value):
    return [str(item) for item in value] if isinstance(value, list) else [str(value)] if value else []


async def _initialize_slots(work, selection):
    if not await work.latest("engine", "main"):
        await work.save("engine", "main", selection["engine"], status="accepted", source="system")
    for raw in selection.get("future_roles", []):
        slot = RoleSlot.model_validate(raw)
        if not await work.latest("role_slot", slot.slot_id):
            await work.save("role_slot", slot.slot_id, slot.model_dump(mode="json"), status="planned", source="system")


async def _generate_decision(work, state, chapter, version, key):
    records = await work.records()
    latest = {(r["kind"], r["key"]): r for r in records}
    window = window_number(chapter)
    used = any(r["kind"] == "decision" and r["payload"].get("comparison_window") == window for r in latest.values())
    prompt = (
        "按人物当下动机、知识、能力及主线职责决定本章行动。critical_turn为关键转折。"
        "关键转折最多比较2条routes，写feasible、hard_constraints_pass、motivation、opponent_response、cost、consequence。"
        "非关键转折只填写current_action同样字段。没有合理行动可以全部feasible=false，禁止强改人物。"
        f"本窗口已比较路线={used}；已比较时必须critical_turn=false、routes=[]，只检查当前行动可行性。\n"
        "返回契约：" + json_text(DECISION_SCHEMA) + "\n当前章：" + str(chapter)
        + "\n既有叙事版本：" + json_text([r for r in latest.values() if r["kind"] in {"character", "role_slot", "relationship", "foreshadow"}])
        + "\n本章计划：" + json_text(_current_slot(state, chapter)) + active_creative_rules.get()
    )
    result = await work.generate(prompt, DECISION_SCHEMA)
    if result["critical_turn"] and used:
        raise CreativePause("route_window", "本窗口已比较过关键路线，不能继续分叉")
    routes = result["routes"] if result["critical_turn"] else [result["current_action"]]
    result["route_result"] = choose_route(routes)
    result["chapter_number"] = chapter
    if result["critical_turn"]:
        result["comparison_window"] = window
    return await work.save("decision", key, result, inputs={"plan": version}, status=result["route_result"]["status"])


def _current_slot(state, chapter):
    return next((s for s in (state.get("novel_plan") or {}).get("chapter_slots", []) if s.get("chapter_number") == chapter), {})


async def _replan_once(work, state, chapter, decision):
    key = f"route_replan:{chapter}"
    prior = await work.latest("decision", key)
    if prior:
        raise CreativePause("no_feasible_route", "一次受控重规划后人物仍无合理行动，创作暂停")
    await work.save("decision", key, {"chapter_number": chapter, "reason": decision["reason"]}, source="system")
    return Command(goto="novel_plan_initialize_node", update={
        "plan_replan_request": {
            "expected_version": state["novel_plan"]["version"], "scope": "future",
            "instruction": "人物无合理行动，须在硬约束、正文、规模和锁定窗口不变前提下调整：" + decision["reason"],
            "trigger": "autonomous_route",
        },
        "plan_generation": None, "pending_proposal": None,
        "tactical_window": None, "memory_retrieved_for_chapter": None,
    })
