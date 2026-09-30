"""将角色职责、未来角色槽与已接受的剧情弧关联，规划不冒充事实。"""

from application.creative.artifacts import json_text
from application.creative.errors import CreativePause
from application.creative.evidence import content_hash
from application.prompts.template_loader import render_prompt
from service.value_objects.creative import ArcDuty, CharacterNarrative, RoleSlot


async def align_cast_to_plan(work, state):
    """每个计划版本只生成一次绑定，恢复时逐项复用已写入结果。"""
    plan = state.get("novel_plan") or {}
    characters = {r["key"]: r for r in await work.records("character")}
    slots = {r["key"]: r for r in await work.records("role_slot")}
    key = f"cast_plan:{plan.get('version', 0)}:{content_hash(json_text(sorted(characters)))[:12]}"
    binding = await work.latest("decision", key)
    if not binding:
        payload = await work.generate(render_prompt(
            "creative/cast.txt", plan=json_text(plan),
            characters=json_text(list(characters.values())), slots=json_text(list(slots.values())),
        ), {"characters": "array", "slots": "array"})
        validate_cast_binding(payload, plan, characters, slots)
        binding = await work.save("decision", key, payload, inputs={"plan": plan["version"]})
    for assignment in binding["payload"]["characters"]:
        await _apply_duties(work, assignment, characters, plan["version"])
    for assignment in binding["payload"]["slots"]:
        await _apply_slot(work, assignment, slots, plan["version"])


def validate_cast_binding(payload, plan, characters, slots):
    arcs = {arc["arc_id"] for arc in plan.get("arcs", [])}
    assignments = payload.get("characters") or []
    if {item.get("character_id") for item in assignments} != set(characters) or len(assignments) != len(characters):
        raise CreativePause("cast_coverage", "人物主线绑定必须逐一覆盖已准入角色")
    for item in assignments:
        duties = [ArcDuty.model_validate(d) for d in item["arc_duties"]]
        if any(d.arc_id not in arcs or d.status != "planned" for d in duties):
            raise CreativePause("cast_arc_identity", "计划只能新增已接受剧情弧中的计划职责")
        if characters[item["character_id"]]["payload"]["role"] == "core" and not duties:
            raise CreativePause("core_duty_missing", "核心人物必须承担主线职责")
    mapped = payload.get("slots") or []
    if {item.get("slot_id") for item in mapped} != set(slots) or len(mapped) != len(slots):
        raise CreativePause("slot_coverage", "未来角色槽必须绑定到已接受的剧情弧")
    for raw in mapped:
        slot = RoleSlot.model_validate({**slots[raw["slot_id"]]["payload"], **raw})
        if not set(slot.arc_ids).issubset(arcs) or slot.entrance_end > plan["scale"]["target_chapters"]:
            raise CreativePause("slot_plan_scope", "未来人物的剧情弧或登场窗口超出计划")
        if slot.character_id != slots[slot.slot_id]["payload"].get("character_id"):
            raise CreativePause("slot_identity", "剧情弧绑定不能替换已具体化角色")


async def _apply_duties(work, assignment, characters, version):
    previous = characters[assignment["character_id"]]
    if previous["input_versions"].get("cast_plan") == version:
        return
    card = CharacterNarrative.model_validate(previous["payload"])
    duties = {(d.arc_id, d.function): d for d in card.arc_duties}
    for raw in assignment["arc_duties"]:
        duty = ArcDuty.model_validate(raw)
        duties.setdefault((duty.arc_id, duty.function), duty)
    updated = card.model_copy(update={"arc_duties": list(duties.values())})
    await work.save("character", previous["key"], updated.model_dump(mode="json"),
                    previous=previous, source="system", status=card.narrative_status,
                    inputs={**previous["input_versions"], "cast_plan": version})


async def _apply_slot(work, assignment, slots, version):
    previous = slots[assignment["slot_id"]]
    if previous["input_versions"].get("cast_plan") == version:
        return
    updated = RoleSlot.model_validate({**previous["payload"], **assignment})
    await work.save("role_slot", updated.slot_id, updated.model_dump(mode="json"),
                    previous=previous, source="system", status="planned", inputs={"cast_plan": version})


async def bind_introduced_slot(work, raw):
    slot_id = raw.get("role_slot_id")
    if not slot_id:
        return
    previous = await work.latest("role_slot", slot_id)
    if previous is None:
        raise CreativePause("unknown_role_slot", "新人物引用了不存在的功能槽")
    if previous["payload"].get("character_id") == raw["character_id"]:
        return
    if previous["payload"].get("character_id"):
        raise CreativePause("occupied_role_slot", "角色功能槽已经绑定其他身份")
    slot = RoleSlot.model_validate({**previous["payload"], "character_id": raw["character_id"],
                                   "existing_character_decision": raw["existing_character_decision"]})
    await work.save("role_slot", slot_id, slot.model_dump(mode="json"), previous=previous,
                    status="planned", source="system", inputs=previous["input_versions"])
