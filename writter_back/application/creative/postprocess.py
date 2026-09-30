"""归档后从真实正文提取读者及人物状态；失败不重写上一章。"""

from typing import Literal
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.creative.evidence import content_hash, validate_character_transition, verify_evidence
from application.creative.projection import project_context
from application.creative.narrative import initialize_cast
from application.creative.threads import update_narrative_threads, check_final_payoffs
from application.creative.lifecycle import validate_center_updates, validate_lifecycle
from application.creative.patches import invalidate_patch
from application.prompts.template_loader import render_prompt
from application.streaming import emit_workflow_event
from service.value_objects.creative import CharacterNarrative, TextEvidence

READER_SCHEMA = {
    "known": "array", "misunderstandings": "array", "expectations": "array",
    "emotions": "array", "fatigue": "array", "paid_promises": "array", "open_promises": "array",
    "evidence": "array",
}


async def creative_postprocess_node(state: dict, config: RunnableConfig) -> Command[Literal["plan_reconciliation_node", "creative_recap_node"]]:
    """所有生成结果先单独持久化，重新进入只补齐缺失后处理成果。"""
    work = await workspace(config)
    completed = int(state.get("current_chapter_index") or 0)
    chapters = await work.repository.chapters(work.tenant_id, work.novel_id, completed)
    if not chapters:
        raise CreativePause("archived_chapter_missing", "后处理找不到归档正文")
    chapter = chapters[-1]
    key = f"{chapter['id']}:v{chapter['version']}"
    receipt = await work.latest("postprocess", key)
    if not receipt:
        emit_workflow_event("creative", {"kind": "postprocess", "status": "pending", "chapter_number": completed}, "creative_postprocess_node")
        await initialize_cast(work, state)
        await _reader_state(work, chapter, completed)
        await update_narrative_threads(work, chapter, completed, _proofs)
        await _character_updates(work, chapter, completed)
        if completed == state.get("target_total_chapters"):
            await check_final_payoffs(work)
        receipt = await work.save("postprocess", key, {
            "chapter_number": completed, "chapter_id": chapter["id"],
            "chapter_version": chapter["version"], "content_hash": content_hash(chapter["content"]),
        }, status="completed", source="system")
    await work.repository.advance(work.tenant_id, work.novel_id, "writing")
    return Command(
        goto="creative_recap_node" if completed % 5 == 0 or completed == state.get("target_total_chapters") else "plan_reconciliation_node",
        update={"creative_postprocessed_through": completed, "last_persisted_chapter": chapter},
    )


async def _reader_state(work, chapter, completed):
    key = f"{completed}:v{chapter['version']}"
    if await work.latest("reader_state", key):
        return
    previous = [r for r in await work.records("reader_state") if r["payload"].get("through_chapter", 0) < completed]
    context = project_context("reader", {
        "chapters": [chapter], "reader_state": previous[-1]["payload"] if previous else {},
    })
    result = await work.generate(
        "你是只看到已完成正文的模拟试读者。记录理解、误解、期待、情绪、疲劳、已兑现/未兑现承诺。"
        "不能访问作者真相或未来大纲。evidence填写当前章的start与quote原文片段；至少一条。"
        "评分不是真人验证。返回：" + json_text(READER_SCHEMA) + "\n正文与此前读者状态：" + json_text(context),
        READER_SCHEMA,
    )
    proofs = _proofs(result.pop("evidence", []), chapter)
    result["through_chapter"] = completed
    result["evidence"] = [p.model_dump(mode="json") for p in proofs]
    await work.save("reader_state", key, result, status="simulated", evidence=proofs,
                    inputs={"chapter": chapter["version"]})


def _proofs(raw, chapter):
    proofs = []
    for item in raw:
        quote = str(item.get("quote") or "")
        start = item.get("start")
        if type(start) is not int and quote and chapter["content"].count(quote) == 1:
            start = chapter["content"].find(quote)
        if type(start) is not int:
            raise ValueError("正文证据必须指定精确字符起点")
        proof = TextEvidence(
            chapter_id=UUID(chapter["id"]), chapter_version=chapter["version"],
            chapter_number=chapter["chapter_index"] + 1, content_hash=content_hash(chapter["content"]),
            start=start, end=start + len(quote), quote=quote,
        )
        verify_evidence(proof, chapter)
        proofs.append(proof)
    if not proofs:
        raise CreativePause("evidence_missing", "状态更新缺少可定位的归档正文证据")
    return proofs


async def _character_updates(work, chapter, completed):
    key = f"character_patch:{completed}:v{chapter['version']}"
    patch = await work.latest("decision", key)
    latest = {r["key"]: r for r in await work.records("character")}
    if not patch or patch["status"] == "invalid":
        result = await work.generate(
            render_prompt("creative/lifecycle.txt", characters=json_text([r["payload"] for r in latest.values()]),
                          content=chapter["content"]),
            {"updates": "array"},
        )
        patch = await work.save("decision", key, result, previous=patch, inputs={"chapter": chapter["version"]})
    try:
        validate_center_updates(patch["payload"]["updates"], latest)
        for change in patch["payload"]["updates"]:
            await _apply_character_patch(work, change, latest, chapter, completed)
    except (ValueError, CreativePause) as error:
        await invalidate_patch(work, patch, error)
        raise


async def _apply_character_patch(work, change, latest, chapter, completed):
    old = latest.get(change.get("character_id"))
    if old is None:
        raise CreativePause("unknown_character", "人物变化引用了未准入角色ID")
    if old["input_versions"].get("through_chapter") == completed:
        return
    allowed = {"goal", "belief", "knowledge", "allegiance", "narrative_status", "perceived_life_status",
               "life_status", "name", "aliases", "role", "narrative_center", "arc_duties"}
    changes = change.get("changes") or {}
    if set(changes) - allowed:
        raise CreativePause("unauthorized_character_change", "人物状态更新越过允许字段")
    proofs = _proofs(change.get("evidence") or [], chapter)
    previous = CharacterNarrative.model_validate(old["payload"])
    current = CharacterNarrative.model_validate({**old["payload"], **changes,
        "evidence": [*old["payload"].get("evidence", []), *[p.model_dump(mode="json") for p in proofs]]})
    validate_character_transition(previous, current)
    await validate_lifecycle(work, previous, current, change, proofs, completed)
    await work.save("character", old["key"], current.model_dump(mode="json"),
                    previous=old, status=current.narrative_status, evidence=proofs,
                    inputs={"through_chapter": completed, "chapter": chapter["version"]})
