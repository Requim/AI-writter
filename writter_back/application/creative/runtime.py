"""节点范围的创作配置、预算和上下文投影，不改变共享模型实例。"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
import inspect

from langgraph.types import Command, interrupt

from application.creative.artifacts import json_text
from application.creative.errors import CreativePause
from application.creative.projection import project_context
from application.creative.goal_recovery import restore_goal_brief
from application.creative.scoped_goal_repair import applicable_goal_repair, goal_repair_command
from application.creative.progress_repair import editorial_legacy_replay, progress_review_replay
from application.goal_contract import active_goal_source, current_goal_contract, prose_goal_contract
from service.ports.model_meter import CreativeRequestMeter, active_model_meter
from service.value_objects.creative_budget import ProgressRepairPolicy, budget_capacity

active_creative_rules: ContextVar[str] = ContextVar("creative_rules", default="")
active_style_evidence: ContextVar[dict] = ContextVar("style_evidence", default={})
PROSE_NODES = {"chapter_writer_node", "revision_node", "chapter_compaction_node"}
REVIEW_NODES = {"creative_recap_node", "creative_experiment_node"}
PREPARATION_NODES = {
    "type_confirmation", "creative_development_node", "genre_strategy_node", "genre_strategy_review_node",
    "creative_brief_node", "creative_brief_review_node", "character_design_node", "character_design_review_node",
    "title_node", "title_review_node", "summary_node", "summary_review_node", "outline_node", "outline_review_node",
    "metadata_persist_node",
}
QUIET_RULES = (
    "\n【自主模式场景规则】以chapter_intent及scene.function验收。"
    "conflict仅在存在主动对手时要求反制和策略变化；setup/aftermath/relationship/discovery"
    "按认知、关系、情绪或后续作用验收。允许余韵和安静，不强求即时反转与额外危机。"
    "发现人物没有合理路线时报告no_feasible_route。不得扩写未提供的未来秘密。"
)


def budget_bucket(name: str, state: dict) -> str:
    if name in REVIEW_NODES or state.get("plan_replan_request") or (
        name == "novel_plan_review_node" and state.get("novel_plan")
    ):
        return "review"
    if name in PREPARATION_NODES or (
        name.startswith("novel_plan_") and not state.get("novel_plan")
    ):
        return "preparation"
    chapter = int(state.get("current_chapter_index") or 0)
    return f"chapter:{max(1, chapter) if name == 'creative_postprocess_node' else chapter + 1}"


def _meter_bucket(name, state, policy):
    if policy and name in {"reflection_node", "reflection_review_node", "persist_node", "creative_postprocess_node"}:
        return "review"
    return budget_bucket(name, state)


@asynccontextmanager
async def creative_node_scope(name: str, state: dict, config: dict):
    """预算绑定仅信任数据库会话；运行中关闭功能则保留现场并中断。"""
    if state.get("author_mode") != "autonomous_v1":
        yield state, config
        return
    repository = config.get("configurable", {}).get("creative_repository")
    if repository is None:
        raise CreativePause("session_missing", "自主作家模式缺少持久化仓储")
    values = config["configurable"]
    session = await repository.get_session(values["tenant_id"], values["novel_id"])
    if not session or session["id"] != state.get("creative_session_id"):
        raise CreativePause("session_mismatch", "创作会话引用不匹配")
    await repository.require_enabled(values["tenant_id"])
    policy = session["config"].get("repair_policy")
    policy = ProgressRepairPolicy.model_validate(policy).model_dump() if policy else None
    bucket = _meter_bucket(name, state, policy)
    meter = CreativeRequestMeter(repository, values["tenant_id"], values["novel_id"], bucket, name)
    meter_token = active_model_meter.set(meter)
    rules_token = active_creative_rules.set("")
    style_token = active_style_evidence.set({})
    goal_token = active_goal_source.set(None)
    try:
        active_creative_rules.set(await _task_rules(name, state, values, session))
        current = dict(state)
        current["author_config"] = {k: v for k, v in session["config"].items() if k != "sources"}
        if state.get("total_outline"):
            current["total_outline"] = {**state["total_outline"], "author_config": {
                "author_mode": "autonomous_v1", "creative_schema_version": 1,
            }}
        current["_creative_persisted_stage"] = session["stage"]
        current, restored = await restore_goal_brief(current, values)
        approved = session["config"].get("goal_repair")
        goal_repair = approved if name in {"reflection_node", "revision_node"} and applicable_goal_repair(current, approved) else None
        held_round = await _begin_budget_round(name, current, values, session) or {}
        if name in PROSE_NODES:
            current_goal_contract(current)
            active_goal_source.set(current)
        current = await _project_prose_state(current, values) if name in PROSE_NODES else current
        options = _runtime_options(name, state, session, held_round, policy)
        yield current, {**config, "configurable": {**values, **options, "auto_mode": True,
            "_goal_source_repair": restored, "_scoped_goal_repair": goal_repair}}
    finally:
        active_model_meter.reset(meter_token)
        active_creative_rules.reset(rules_token)
        active_style_evidence.reset(style_token)
        active_goal_source.reset(goal_token)


def _runtime_options(name, state, session, held_round, policy):
    return {
        "_local_only_repair": name == "revision_node" and held_round.get("purpose") in {"repair_local", "repair_progress"},
        "_elastic_budget": "policy" in session["limits"],
        "_repair_progress_policy": policy,
        "_repair_progress_capacity": budget_capacity(
            session["limits"], session["counters"], budget_bucket(name, state), include_round=False) if policy else 0,
        "_repair_progress_review": session["config"].get("repair_policy_review") if policy else None,
    }


async def _begin_budget_round(name, state, values, session):
    if "policy" not in session["limits"] or name not in {"revision_node", "reflection_node"}:
        return
    body = state.get("current_chapter_content") or ""
    if not body or (name == "revision_node" and (state.get("pending_proposal") or {}).get("kind") == "revision"):
        return
    policy = session["config"].get("repair_policy")
    if name == "reflection_node" and policy and progress_review_replay(
        state, session["config"].get("repair_policy_review"), policy,
        budget_capacity(session["limits"], session["counters"], budget_bucket(name, state), include_round=False),
    ):
        return
    from application.goal_contract import fingerprint
    approved = session["config"].get("goal_repair")
    goal_local = (name == "revision_node" and applicable_goal_repair(state, approved)
        and (state.get("quality_gate") or {}).get("scoped_goal_repair") == approved["id"])
    purpose = "repair_local" if name == "revision_node" and (goal_local or _local_repair_eligible(state, body)) else (
        "repair" if name == "revision_node" else "review")
    proof = (state.get("quality_gate") or {}).get("repair_progress") or {}
    if (name == "revision_node" and session["config"].get("repair_policy")
        and proof.get("body_hash") == fingerprint(body) and _local_repair_eligible(state, body)):
        purpose = "repair_progress"
    return await values["creative_repository"].begin_budget_round(
        values["tenant_id"], values["novel_id"], _meter_bucket(name, state, policy),
        fingerprint(body), purpose,
    )


def _local_repair_eligible(state, body):
    from application.goal_contract import fingerprint

    gate = state.get("quality_gate") or {}
    report = gate.get("goal_acceptance") or {}
    outlines = state.get("chapter_outlines") or [{}]
    contract = outlines[-1].get("goal_contract") or {}
    blocking = [issue for issue in state.get("reflection_issues") or []
        if issue.get("priority_action") == "must_fix" and not issue.get("issue_resolved")
        and issue.get("evidence_valid") is True and isinstance(issue.get("evidence"), str)
        and issue["evidence"] in body]
    return (len(body) <= 6000 and gate.get("decision") == "patch" and bool(blocking)
        and not (state.get("user_decision") or {}).get("instructions")
        and bool(contract.get("id")) and report.get("contract_id") == contract["id"]
        and report.get("content_hash") == fingerprint(body) and report.get("status") == "passed")


async def _task_rules(name, state, values, session):
    rules = QUIET_RULES
    if name in PROSE_NODES:
        from application.creative.adoption import trial_rules
        from application.creative.direct_feedback import author_instruction_rules
        rules += await trial_rules(values["creative_repository"], values["tenant_id"], values["novel_id"],
                                   int(state.get("current_chapter_index") or 0) + 1)
        rules += await author_instruction_rules(values["creative_repository"], values["tenant_id"], values["novel_id"])
    if name not in PROSE_NODES:
        rules += "\n【不可变创作约定】" + json_text({
            "hard_constraints": session["config"].get("hard_constraints", []),
            "narrative_mode": state.get("creative_narrative_mode"),
            "target_chapters": state.get("target_total_chapters"),
        })
    style_service = values.get("creative_style_service")
    if style_service and (name in PROSE_NODES or name in PREPARATION_NODES or name.startswith("novel_plan") or name in {"chapter_outline_node", "tactical_plan_node"}):
        task = "prose" if name in PROSE_NODES else "character" if name.startswith("character") else "topic"
        if name == "revision_node":
            task = "revision"
        compiled = await style_service.compile_for_task(values["tenant_id"], values["novel_id"], session, task, state)
        if compiled.get("learned"):
            active_style_evidence.set({"profile_id": session["config"]["author_profile_id"],
                                       "profile_version": session["config"]["author_profile_version"],
                                       "preference_ids": compiled["applied_ids"]})
            rules += "\n【本次有效作者审美】" + json_text(compiled)
    return rules


async def _project_prose_state(state, values):
    result = _prose_runtime_state(state)
    repository = values["creative_repository"]
    chapters = await repository.chapters(values["tenant_id"], values["novel_id"], state.get("current_chapter_index", 0))
    total = state.get("total_outline") or {}
    current = (state.get("chapter_outlines") or [{}])[-1]
    ids = tuple({cid for scene in current.get("scenes", []) for cid in scene.get("character_ids", [])})
    cards = await _current_public_cards(repository, values, total)
    allowed = tuple(info for scene in current.get("scenes", []) for info in scene.get("allowed_information", []))
    projected = project_context("scene", {
        "chapters": chapters[-3:], "characters": cards,
        "chapter_intent": current.get("chapter_intent"),
    }, character_ids=ids, allowed_information=allowed)
    brief = total.get("creative_brief") or {}
    result["total_outline"] = {
        "author_config": {"author_mode": "autonomous_v1"}, "main_characters": projected["characters"],
        "reader_quality_version": state.get("reader_quality_version", 0),
        "story_background": json_text({"allowed_information": projected["allowed_information"]}),
        "writing_style": total.get("writing_style", ""),
        "creative_brief": {k: deepcopy(brief[k]) for k in (
            "tone", "style_fingerprint", "genre_context", "research_material") if k in brief},
        "total_chapters": total.get("total_chapters", 0),
    }
    result["memory_context"] = json_text(project_context("reader", {"chapters": chapters[-3:]}))
    result["chapter_outlines"] = [_prose_outline(current)]
    result["creative_brief"] = result["total_outline"]["creative_brief"]
    result["novel_plan"] = None
    result["tactical_window"] = None
    result["author_config"] = {}
    return result


def _prose_runtime_state(state):
    fields = {
        "author_mode", "creative_session_id", "creative_schema_version", "_creative_persisted_stage",
        "novel_type", "title", "current_chapter_index", "workflow_schema_version", "workflow_run_id",
        "current_chapter_content", "chapter_quota_reserved_for_chapter", "scene_ledger",
        "scene_queue", "scene_cursor", "scene_attempts", "revision_history", "revision_attempts",
        "reflection_issues", "quality_gate", "user_decision", "target_total_chapters",
        "chapter_word_count", "compact_attempts", "chapter_compaction_attempts",
        "completed_chapters",
        "automatic_recovery",
        "reader_quality_version", "reader_comprehension_receipt",
    }
    return {key: deepcopy(value) for key, value in state.items() if key in fields}


def _public_card(character):
    profile = character.get("profile") or {}
    return {
        "character_id": character.get("character_id"),
        "name": character.get("name", ""),
        "voice": profile.get("speech_fingerprint", profile.get("speech_style", profile.get("speech_pattern", ""))),
    }


async def _current_public_cards(repository, values, total):
    planned = {c["character_id"]: _public_card(c) for c in total.get("main_characters", []) if c.get("character_id")}
    latest = {r["key"]: r["payload"] for r in await repository.records(values["tenant_id"], values["novel_id"], "character")}
    for key, character in latest.items():
        planned[key] = {"character_id": key, "name": character["name"], "voice": character.get("voice", "")}
    return list(planned.values())


def _prose_outline(outline):
    fields = {
        "chapter_number", "title", "chapter_goal", "chapter_intent", "reader_contract", "pov_character",
        "entry_state", "state_delta", "ending_mode", "estimated_word_count",
        "scenes", "chapter_execution_contract", "creative_contract_version",
        "reader_quality_version",
    }
    result = {k: deepcopy(v) for k, v in outline.items() if k in fields}
    if outline.get("goal_contract"):
        result["goal_contract"] = prose_goal_contract(outline["goal_contract"])
    if outline.get("reader_entry"):
        from application.reader_entry import public_reader_entry
        result["reader_entry"] = public_reader_entry(outline["reader_entry"])
    scene_fields = {
        "scene_index", "location", "characters", "character_ids", "function", "purpose",
        "state_change", "scene_goal", "active_opposition", "counteraction", "tactics",
        "cost", "allowed_information", "action_requirements", "events",
        "dialogue_targets", "sensory_anchors",
        "reader_quality_version",
    }
    result["scenes"] = [{k: v for k, v in scene.items() if k in scene_fields} for scene in outline.get("scenes", [])]
    return result


async def run_creative_node(name, node, accepts_config, state, config):
    """节点暂停后恢复时重新检查预算及硬约束，不跳过仍存在的错误。"""
    async with creative_node_scope(name, state, config) as (projected, scoped):
        pending = str(projected.get("_creative_persisted_stage") or "")
        if pending.startswith("postprocess:") and name != "creative_postprocess_node":
            return Command(goto="creative_postprocess_node", update={
                "current_chapter_index": int(pending.split(":")[1]),
                "current_chapter_content": "", "is_completed": False,
            })
        recovery = _review_recovery(name, projected, scoped["configurable"])
        result = recovery or (node(projected, config=scoped) if accepts_config else node(projected))
        result = await result if inspect.isawaitable(result) else result
        if name == "creative_postprocess_node" and scoped["configurable"].get("_elastic_budget"):
            await scoped["configurable"]["creative_repository"].release_budget_round(
                scoped["configurable"]["tenant_id"], scoped["configurable"]["novel_id"], budget_bucket(name, state))
            if scoped["configurable"].get("_repair_progress_policy"):
                await scoped["configurable"]["creative_repository"].release_budget_round(
                    scoped["configurable"]["tenant_id"], scoped["configurable"]["novel_id"], "review")
        restored = scoped["configurable"].get("_goal_source_repair") or {}
        if restored:
            from dataclasses import replace
            result = replace(result, update={**restored, **(result.update or {})}) if isinstance(result, Command) else {
                **restored, **result}
        if name == "progress_check_node" and isinstance(result, dict) and result.get("__route__") == "end" and state.get("author_mode") == "autonomous_v1":
            values = scoped["configurable"]
            await values["creative_repository"].advance(values["tenant_id"], values["novel_id"], "completed", "completed")
        return result


def _review_recovery(name, state, values):
    if name == "reflection_review_node":
        return editorial_legacy_replay(state, values.get("_repair_progress_policy"))
    if name != "reflection_node":
        return None
    recovery = goal_repair_command(state, values.get("_scoped_goal_repair"))
    return recovery or progress_review_replay(state, values.get("_repair_progress_review"),
        values.get("_repair_progress_policy"), values.get("_repair_progress_capacity", 0))


def pause_creative(error: CreativePause, node_name: str) -> Command:
    interrupt({"action": "creative_paused", "reason": error.reason, "message": str(error),
               "retryable": error.reason != "budget_exhausted"})
    return Command(goto=node_name)
