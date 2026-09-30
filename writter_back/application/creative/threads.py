"""人物职责、关系、秘密及伏笔使用既有实体与计划ID，状态需有归档证据。"""

from datetime import datetime, timezone

from application.creative.artifacts import json_text
from application.creative.errors import CreativePause
from application.creative.evidence import validate_foreshadow_transition
from application.creative.patches import invalidate_patch
from application.prompts.template_loader import render_prompt
from service.value_objects.creative import Foreshadow, Secret


async def initialize_plan_threads(work, state):
    slots = (state.get("novel_plan") or {}).get("chapter_slots") or []
    due = {key: slot["chapter_number"] for slot in slots for key in slot.get("payoff_ids", [])}
    for slot in slots:
        for key in slot.get("setup_ids", []):
            if await work.latest("foreshadow", key):
                continue
            item = Foreshadow(
                foreshadow_id=key, origin="planned", description=f"计划第{slot['chapter_number']}章预埋：{key}",
                arc_ids=slot.get("arc_ids", []), due_chapter=due.get(key), core=True,
            )
            await work.save("foreshadow", key, item.model_dump(mode="json"), status="planned", source="system")
    await _initialize_secrets(work, state)


async def _initialize_secrets(work, state):
    for character in (state.get("total_outline") or {}).get("main_characters", []):
        truth = str((character.get("profile") or {}).get("secret") or "")
        if not truth:
            continue
        key = f"character:{character['character_id']}:secret"
        if await work.latest("secret", key):
            continue
        secret = Secret(secret_id=key, truth=truth, character_ids=[character["character_id"]],
                        known_by=[], reveal_conditions=["归档正文实际揭示后确认"])
        await work.save("secret", key, secret.model_dump(mode="json"), status="planned", source="system")


async def update_narrative_threads(work, chapter, completed, proof_builder):
    """归档后的伏笔识别使用原文证据；后续接续由服务器记录当前构思时间。"""
    key = f"threads:{completed}:v{chapter['version']}"
    patch = await work.latest("decision", key)
    latest = {(r["kind"], r["key"]): r for r in await work.records() if r["kind"] in {"foreshadow", "secret", "relationship"}}
    if patch is None or patch["status"] == "invalid":
        characters = {r["key"]: r["payload"].get("name") for r in await work.records("character")}
        result = await work.generate(
            render_prompt("creative/threads.txt", threads=json_text(list(latest.values())),
                          characters=json_text(characters), content=chapter["content"]),
            {"updates": "array"},
        )
        patch = await work.save("decision", key, result, previous=patch, inputs={"chapter": chapter["version"]})
    try:
        for change in patch["payload"]["updates"]:
            await _apply_thread_change(work, change, latest, chapter, completed, proof_builder)
    except (ValueError, CreativePause) as error:
        await invalidate_patch(work, patch, error)
        raise


async def _apply_thread_change(work, change, latest, chapter, completed, proof_builder):
    kind, key = change.get("kind"), change.get("key")
    if kind not in {"foreshadow", "secret", "relationship"} or not isinstance(key, str):
        raise CreativePause("thread_contract", "叙事变化类型或ID无效")
    previous = latest.get((kind, key))
    if previous and previous["input_versions"].get("through_chapter") == completed:
        return
    proofs = proof_builder(change.get("evidence") or [], chapter)
    payload = await _thread_payload(work, kind, key, change.get("changes") or {}, previous, proofs)
    await work.save(kind, key, payload, previous=previous, evidence=proofs,
                    status=payload.get("status", "observed"), inputs={"through_chapter": completed, "chapter": chapter["version"]})


async def _thread_payload(work, kind, key, changes, previous, proofs):
    old = previous["payload"] if previous else {}
    combined = [*old.get("evidence", []), *[p.model_dump(mode="json") for p in proofs]]
    if kind == "foreshadow":
        allowed = {"description", "status", "resolution", "character_ids", "arc_ids", "core", "due_chapter", "origin"}
        if set(changes) - allowed:
            raise CreativePause("foreshadow_fields", "伏笔变化尝试修改未授权字段")
        base = old or {"foreshadow_id": key, "origin": "retrospective", "conceived_at": datetime.now(timezone.utc).isoformat()}
        item = Foreshadow.model_validate({**base, **changes, "evidence": combined})
        if previous:
            validate_foreshadow_transition(Foreshadow.model_validate(old), item)
        elif item.origin != "retrospective":
            raise CreativePause("backdated_setup", "后续接续不得伪造成提前规划")
        return item.model_dump(mode="json")
    if kind == "secret":
        if not previous or set(changes) - {"known_by", "reader_revealed"}:
            raise CreativePause("secret_fields", "不能通过状态更新新增或改写真相")
        existing = {r["key"] for r in await work.records("character")}
        if not set(changes.get("known_by", old.get("known_by", []))).issubset(existing):
            raise CreativePause("secret_identity", "秘密知情者必须引用已准入的人物ID")
        return Secret.model_validate({**old, **changes, "evidence": combined}).model_dump(mode="json")
    ids = changes.get("character_ids") or old.get("character_ids") or []
    existing = {r["key"] for r in await work.records("character")}
    if len(ids) != 2 or len(set(ids)) != 2 or not set(ids).issubset(existing):
        raise CreativePause("relationship_identity", "关系必须关联两个已准入且不同的人物ID")
    return {"character_ids": ids, "description": str(changes.get("description") or ""),
            "arc_ids": changes.get("arc_ids", []), "evidence": combined, "status": "observed"}


async def check_final_payoffs(work):
    latest = {r["key"]: r for r in await work.records("foreshadow")}
    unresolved = [r["key"] for r in latest.values() if r["payload"].get("core")
                  and r["status"] in {"seeded", "reinforced", "partial"} and not r["payload"].get("resolution")]
    if unresolved:
        raise CreativePause("unresolved_core_payoff", "核心伏笔尚未兑现或解释：" + "、".join(unresolved))
