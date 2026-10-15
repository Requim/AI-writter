"""创作开发：三个不同方案、十节点发动机、隔离试稿和自动立项。"""

from typing import Literal
from langchain_core.runnables import RunnableConfig

from langgraph.types import Command

from application.creative.artifacts import CreativeWorkspace, json_text, workspace
from application.creative.errors import CreativePause
from application.creative.evidence import content_hash
from application.creative.policy import select_candidate, validate_engine
from application.creative.role_slots import planned_role_slots
from application.prompts.creative_brief_prompts import CREATIVE_BRIEF_SCHEMA
from application.prompts.template_loader import render_prompt
from application.reader_comprehension import (
    pilot_reader_request, preserve_reader_confusion, reader_archive_ready, reader_receipt,
    reader_receipt_valid, require_opening_evidence,
)
from application.errors import StructuredOutputInvalidError
from application.streaming import emit_workflow_event
from config import settings
from infrastructure.research.tavily import TavilyResearchAdapter

CANDIDATE_SCHEMA = {
    "brief": CREATIVE_BRIEF_SCHEMA, "narrative_mode": "string",
    "differentiation": "object", "engine": "object", "future_roles": "array",
}
BLIND_SCHEMA = {"continue_reading": "number", "clarity": "number", "payoff": "number",
               "quality_pass": "boolean", "evidence": "array", "issues": "array"}
PLAN_SCHEMA = {"sustainability": "number", "repetition_risk": "number", "complexity": "number",
               "hard_constraints_pass": "boolean", "issues": "array"}


async def creative_development_node(state: dict, config: RunnableConfig) -> Command[Literal["creative_development_node", "genre_strategy_node"]]:
    """一次只完成一个可缓存步骤，避免节点重启时整段重新生成。"""
    work = await workspace(config)
    selection = await work.latest("selection", "accepted")
    if selection:
        return _selected_command(selection, state)
    if await _prepare_source(work):
        return _again("research")
    candidates = [await work.latest("candidate", str(index)) for index in range(1, 4)]
    if await _resume_inception_repair(work, candidates, state):
        return _again("inception_repair")
    missing = next((index for index, item in enumerate(candidates, 1) if item is None), None)
    if missing:
        await _candidate(work, missing, candidates, state)
        return _again("candidate")
    shortlist = await work.latest("evaluation", "shortlist")
    if not shortlist:
        await _shortlist(work, candidates)
        return _again("shortlist")
    chosen = [candidates[index - 1] for index in shortlist["payload"]["indices"]]
    if await _pilot_or_evaluation(work, chosen, state):
        return _again("pilot_evaluation")
    return await _select_or_repair(work, chosen, candidates, state)


def _again(stage: str) -> Command:
    emit_workflow_event("creative", {"kind": "development", "status": "candidate", "stage": stage}, "creative_development_node")
    return Command(goto="creative_development_node", update={"creative_stage": stage})


async def _prepare_source(work: CreativeWorkspace) -> bool:
    config = work.session["config"]
    for index, source in enumerate(config.get("sources", [])):
        if not await work.latest("source", f"user:{index}"):
            await work.save("source", f"user:{index}", source, status="available", source="author")
            return True
    for index, query in enumerate(config.get("research_queries", [])):
        if await work.latest("source", f"search:{index}"):
            continue
        existing = await work.records("source")
        count = sum(len(r["payload"].get("results", [r["payload"]])) for r in existing)
        if count >= 20:
            raise CreativePause("source_limit", "每书最多20份资料，请减少检索或合并资料")
        request_id = await work.repository.reserve(work.tenant_id, work.novel_id, "preparation_search", "research")
        sources = await TavilyResearchAdapter(settings.TAVILY_API_KEY).search(query)
        await work.repository.finish_request(work.tenant_id, work.novel_id, request_id, {})
        await work.save("source", f"search:{index}", {
            "query": query, "results": [source.model_dump(mode="json") for source in sources[:20 - count]],
        }, status="unverified_observation", source="research")
        return True
    return False


async def _candidate(work, index, candidates, state, previous=None):
    sources = await work.records("source")
    prompt = render_prompt(
        "creative/candidate.txt", schema=json_text(CANDIDATE_SCHEMA), index=index,
        config=json_text(_author_constraints(work)),
        chapters=state.get("target_total_chapters"), brief=json_text(state.get("creative_brief") or {}),
        seed=json_text({k: state.get(k) for k in ("novel_type", "title", "summary")}),
        other_candidates=json_text([c["payload"].get("brief", {}) for c in candidates if c]),
        sources=json_text([s["payload"] for s in sources])[:24000],
    )
    if previous:
        prompt += "\n这是唯一一次立项修复，请解决试读和规划问题：" + json_text(await work.records("evaluation"))
    schema = CANDIDATE_SCHEMA
    if state.get("reader_quality_version") == 1:
        prompt += "\n" + render_prompt("creative/reader_premise_v1.txt", include_active_rules=False)
        schema = {**schema, "brief": {**CREATIVE_BRIEF_SCHEMA, "reader_entry": "object"}}
    result = await work.generate(prompt, schema)
    slots = planned_role_slots(
        result.get("future_roles", []),
        int(state.get("target_total_chapters") or work.session["limits"]["chapters"]),
    )
    result["future_roles"] = [slot.model_dump(mode="json") for slot in slots]
    result["engine_issues"] = validate_engine(result.get("engine") or {})
    result["market_evidence_status"] = "unknown"
    mode = work.session["config"]["narrative_mode"]
    if mode != "auto":
        result["narrative_mode"] = mode
    if result.get("narrative_mode") not in {"stable", "ensemble_relay"}:
        raise CreativePause("invalid_narrative_mode", "立项未选择有效叙事模式")
    await work.save("candidate", str(index), result, previous=previous)


async def _shortlist(work, candidates):
    result = await work.generate(
        "从三个不同方案中粗筛两个进入隔离试写。只比较故事发动机及差异，不声称存在市场销量证据。"
        "返回indices(两个不同的1-3整数)及reason。\n" + json_text([c["payload"] for c in candidates]),
        {"indices": "array", "reason": "string"},
    )
    indices = result.get("indices", [])
    if len(indices) != 2 or len(set(indices)) != 2 or any(type(i) is not int or i not in range(1, 4) for i in indices):
        raise CreativePause("invalid_shortlist", "粗筛结果没有两个有效且不同的候选")
    await work.save("evaluation", "shortlist", result)


async def _pilot_or_evaluation(work, candidates, state):
    for candidate in candidates:
        key = f"{candidate['key']}:v{candidate['version']}"
        pilot = await work.latest("pilot", key)
        if not pilot:
            text = await work.llm.generate(
                render_prompt("creative/pilot.txt", context=json_text(_pilot_context(
                    candidate["payload"], reader_quality_version=state.get("reader_quality_version", 0)))),
            )
            await work.save("pilot", key, {"text": text, "candidate_key": candidate["key"]},
                            status="isolated", inputs={"candidate": candidate["version"]})
            return True
        blind = await work.latest("evaluation", f"blind:{key}")
        current_reader_state = {**state, "current_chapter_index": 0, "reader_history": []}
        stale_reader = (state.get("reader_quality_version") == 1 and blind and not reader_receipt_valid(
            blind["payload"].get("reader_comprehension_receipt"), current_reader_state,
            pilot["payload"]["text"], scope="pilot"))
        if not blind or stale_reader:
            text = pilot["payload"]["text"]
            result = await _blind_pilot(work, state, text)
            _validate_pilot_review(result, text)
            if state.get("reader_quality_version") == 1 and not reader_archive_ready(
                {**state, "current_chapter_index": 0, "reader_history": [],
                 "reader_comprehension_receipt": result["reader_comprehension_receipt"]}, text, scope="pilot"
            ):
                result["validation_issues"].append("reader_comprehension_failed")
                result["quality_pass"] = False
            await work.save("evaluation", f"blind:{key}", result, status="simulated", previous=blind)
            return True
        if not await work.latest("evaluation", f"plan:{key}"):
            result = await work.generate(
                render_prompt("creative/plan_review.txt", include_active_rules=False,
                              schema=json_text(PLAN_SCHEMA), context=json_text({
                                  "scale": {"target_chapters": state.get("target_total_chapters"),
                                            "target_total_words": state.get("target_total_words")},
                                  "author_constraints": _author_constraints(work),
                                  "candidate": candidate["payload"],
                              })), PLAN_SCHEMA,
            )
            await work.save("evaluation", f"plan:{key}", result, status="simulated")
            return True
    return False


def _preserve_pilot_result(previous, current):
    preserve_reader_confusion(previous.get("reader_report"),
                              current["reader_comprehension_receipt"]["report"])
    if previous.get("quality_pass") is False and current.get("quality_pass") is not False:
        raise StructuredOutputInvalidError("格式纠正不能把试稿质量不通过改为通过")


async def _blind_pilot(work, state, text):
    schema = BLIND_SCHEMA
    if state.get("reader_quality_version") != 1:
        prompt = render_prompt("creative/blind_review.txt", include_active_rules=False,
                               schema=json_text(schema), text=text)
        return await work.generate(prompt, schema)
    reader_state = {**state, "current_chapter_index": 0, "reader_history": []}
    schema = {**schema, "reader_report": "object"}
    prompt, binding = pilot_reader_request(reader_state, text, schema)
    error = None
    failures = []
    for attempt in range(2):
        result = None
        try:
            result = await work.generate(prompt, schema, max_attempts=1)
            result["reader_comprehension_receipt"] = reader_receipt(
                result.get("reader_report"), reader_state, text, binding=binding)
            if attempt and failures[0]["report"]:
                _preserve_pilot_result(failures[0]["report"], result)
            if attempt == 0:
                require_opening_evidence(result["reader_comprehension_receipt"], reader_state, text)
            if failures:
                result["protocol_correction_attempts"] = failures
            return result
        except StructuredOutputInvalidError as exc:
            error = exc
            failures.append({"error": str(exc), "report": result})
        if attempt == 0:
            prompt += ("\n只纠正一次格式和原文证据，不改变不清楚的结论：" + str(error)
                       + "\n上一次报告（待纠正数据）：" + json_text(result))
    key = "blind_protocol_failure:" + content_hash(text)
    previous = await work.latest("evaluation", key)
    await work.save("evaluation", key, {"attempts": failures}, status="invalid", previous=previous)
    raise CreativePause("reader_report_invalid", "试稿理解报告格式仍无效，已保留试稿") from error


def _author_constraints(work):
    return {k: v for k, v in work.session["config"].items()
            if k not in {"sources", "budget", "research_queries", "author_profile_id", "author_profile_version"}}


def _validate_pilot_review(result, text):
    result["model_quality_pass"] = result.get("quality_pass") is True
    issues = []
    if not result["model_quality_pass"]:
        issues.append("model_quality_rejected")
    if not 3000 <= len(text) <= 7000:
        issues.append("pilot_length_out_of_range")
    if not _has_pilot_evidence(result, text):
        issues.append("invalid_pilot_evidence")
    result["validation_issues"] = issues
    result["quality_pass"] = not issues


def _has_pilot_evidence(report, text):
    evidence = report.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    quotes = [item.get("quote") if isinstance(item, dict) else item for item in evidence]
    return all(isinstance(quote, str) and quote.strip() and quote in text for quote in quotes)


async def _candidate_score(work, candidate):
    key = f"{candidate['key']}:v{candidate['version']}"
    blind = (await work.latest("evaluation", f"blind:{key}"))["payload"]
    plan = (await work.latest("evaluation", f"plan:{key}"))["payload"]
    return {
        "index": int(candidate["key"]), "candidate_version": candidate["version"],
        "scores": {**{k: blind[k] for k in ("continue_reading", "clarity", "payoff")}, "sustainability": plan["sustainability"]},
        "quality_pass": blind["quality_pass"] and not candidate["payload"]["engine_issues"],
        "hard_constraints_pass": plan["hard_constraints_pass"],
        "repetition_risk": plan["repetition_risk"], "complexity": plan["complexity"],
        "evaluation_source": "blind_pilot_and_independent_plan",
    }


def _pilot_context(candidate, *, reader_quality_version=0):
    brief = candidate["brief"]
    nodes = candidate["engine"].get("conflict_nodes") or []
    context = {
        "tone": brief.get("tone"), "setting_context": brief.get("setting_context"),
        "protagonist_drive": brief.get("protagonist_drive"),
        "reader_promise": brief.get("reader_promise"),
        "core_conflict": brief.get("core_conflict"),
        "opening_action": nodes[0] if nodes else {},
        "narrative_mode": candidate["narrative_mode"],
    }
    if reader_quality_version == 1:
        from application.reader_entry import public_reader_entry
        context["core_premise"] = brief.get("core_premise")
        context["reader_entry"] = public_reader_entry(brief.get("reader_entry"))
        context["entry_requirements"] = (
            "先写眼前的日常需求。前500字说清人物身份、眼前关系和目标；"
            "前800字展示阻碍和独特吸引点。允许直接叙述，不能用术语和重复微动作替代故事。")
    return context


async def _select_or_repair(work, chosen, candidates, state):
    scores = [await _candidate_score(work, candidate) for candidate in chosen]
    try:
        selected = select_candidate(scores)
    except CreativePause:
        if await work.latest("decision", "inception_repair"):
            raise CreativePause("inception_failed", "立项修复后仍无合格方案，已保留全部产物")
        best = max(scores, key=lambda item: (sum(item["scores"].values()), -item["index"]))
        previous = candidates[best["index"] - 1]
        await work.save("decision", "inception_repair", {
            "candidate": best["index"], "input_version": previous["version"],
        }, source="system")
        await _candidate(work, best["index"], candidates, state, previous=previous)
        return _again("inception_repair")
    candidate = candidates[selected["index"] - 1]
    selection = await work.save("selection", "accepted", {
        **selected, "brief": candidate["payload"]["brief"],
        "narrative_mode": candidate["payload"]["narrative_mode"],
        "engine": candidate["payload"]["engine"], "future_roles": candidate["payload"]["future_roles"],
        "market_evidence_status": "unknown", "real_reader_validation": "not_performed",
    }, status="accepted", source="system")
    await work.repository.advance(work.tenant_id, work.novel_id, "planning")
    return _selected_command(selection, state)


async def _resume_inception_repair(work, candidates, state):
    repair = await work.latest("decision", "inception_repair")
    if not repair:
        return False
    index = repair["payload"]["candidate"]
    previous = candidates[index - 1]
    if previous["version"] > repair["payload"]["input_version"]:
        return False
    await _candidate(work, index, candidates, state, previous=previous)
    return True


def _selected_command(selection, state):
    payload = selection["payload"]
    brief = {**payload["brief"], "autonomous_contract": {
        "narrative_mode": payload["narrative_mode"], "engine": payload["engine"],
        "future_roles": payload["future_roles"], "hard_constraints": state.get("author_config", {}).get("hard_constraints", []),
    }}
    material = (state.get("creative_brief") or {}).get("research_material")
    if material:
        brief["research_material"] = material
    emit_workflow_event("creative", {"kind": "selection", "status": "accepted", "record_id": selection["id"]}, "creative_development_node")
    return Command(goto="genre_strategy_node", update={
        "creative_brief": brief, "creative_stage": "planning",
        "creative_selection_id": selection["id"], "creative_narrative_mode": payload["narrative_mode"],
    })
