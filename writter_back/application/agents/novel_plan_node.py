"""整书规划生成、审核、版本接受与章节执行对账节点。"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.errors import InvalidReviewDecisionError, RetryableWorkflowError
from application.planning import (
    build_plan,
    classify_drift,
    generation_context,
    plan_diff,
    reschedule_minor_drift,
    scale_from_state,
    validate_blueprint,
    validate_volume_slots,
)
from application.prompts.novel_plan_prompts import (
    BLUEPRINT_SCHEMA,
    VOLUME_SLOTS_SCHEMA,
    build_blueprint_prompt,
    build_volume_slots_prompt,
)
from application.proposals import (
    decide_proposal,
    proposal_matches,
    proposal_update,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from service.value_objects.novel_plan import (
    NovelPlan,
    NovelPlanValidationError,
    PlanExecution,
    ScaleContract,
    StoryArc,
    VolumePlan,
)

logger = logging.getLogger("uvicorn")


def _plan(value: Any) -> NovelPlan | None:
    if isinstance(value, NovelPlan):
        return value
    if isinstance(value, dict) and value:
        return NovelPlan.from_dict(value)
    return None


def _mode(state: NovelAgentState, previous: NovelPlan | None) -> str:
    request = state.get("plan_replan_request")
    if isinstance(request, dict) and request:
        return "replan"
    if previous is not None:
        return "volume_detail"
    return "legacy_upgrade" if int(state.get("current_chapter_index", 0) or 0) else "initial"


def _target_volume(previous: NovelPlan, chapter_number: int) -> str:
    for volume in previous.volumes:
        if volume.start_chapter <= chapter_number <= volume.end_chapter:
            return volume.volume_id
    raise NovelPlanValidationError([f"第 {chapter_number} 章不在任何分卷内"])


async def _legacy_facts(
    state: NovelAgentState, values: dict[str, Any]
) -> list[dict[str, Any]]:
    if int(state.get("current_chapter_index", 0) or 0) < 1:
        return []
    repository = values.get("novel_repository")
    finder = getattr(repository, "find_by_id_with_chapters", None)
    if not callable(finder):
        return []
    novel = await finder(values.get("tenant_id", ""), values.get("novel_id", ""))
    if novel is None:
        return []
    facts = [
        {
            "chapter_number": chapter.chapter_index + 1,
            "title": chapter.title,
            "word_count": chapter.word_count,
            "outline": _legacy_outline_fact(chapter.outline),
        }
        for chapter in novel.chapters
    ]
    for fact, chapter in zip(facts[-5:], novel.chapters[-5:], strict=True):
        fact["content_excerpt"] = _legacy_content_excerpt(chapter)
    memory = values.get("memory_service")
    context_loader = getattr(memory, "get_hierarchical_context", None)
    if facts and callable(context_loader):
        context = await context_loader(
            values.get("tenant_id", ""),
            values.get("novel_id", ""),
            int(state.get("current_chapter_index", 0) or 0),
            m_count=5,
        )
        facts[-1]["continuity_context"] = context
    return facts


def _legacy_content_excerpt(chapter: Any) -> str:
    content = str(getattr(chapter, "content", "") or "")
    if len(content) <= 480:
        return content
    return content[:240] + "\n...\n" + content[-240:]


def _legacy_outline_fact(value: Any) -> dict[str, Any]:
    outline = value if isinstance(value, dict) else {}
    return {
        key: outline[key]
        for key in ("chapter_goal", "key_events", "state_delta", "logic_hooks")
        if key in outline
    }


def _instruction(state: NovelAgentState) -> str:
    request = state.get("plan_replan_request")
    if isinstance(request, dict):
        return str(request.get("instruction") or "")
    return str(state.get("plan_feedback") or "")


def _scale_for_request(
    state: NovelAgentState, previous: NovelPlan | None
) -> ScaleContract:
    request = state.get("plan_replan_request")
    scope = request.get("scope") if isinstance(request, dict) else None
    if previous is not None and scope != "scale":
        return previous.scale
    return scale_from_state(state)


async def _generate_blueprint(
    state: NovelAgentState,
    config: RunnableConfig,
    scale: ScaleContract,
    previous: NovelPlan | None,
    legacy: list[dict[str, Any]],
) -> tuple[dict[str, Any], ScaleContract]:
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if llm is None:
        raise RetryableWorkflowError("整书规划失败：LLM 不可用")
    errors: list[str] = []
    for _attempt in range(3):
        prompt = build_blueprint_prompt(
            scale=scale.to_dict(),
            outline=dict(state.get("total_outline") or {}),
            existing_plan=previous.to_dict() if previous else None,
            instruction=_instruction(state),
            legacy_chapters=legacy,
            errors=errors,
        )
        raw = await llm.structured_generate(
            prompt, BLUEPRINT_SCHEMA, temperature=0.35, max_attempts=1
        )
        candidate_scale, scale_errors = _candidate_scale(
            state, raw, scale, previous
        )
        blueprint, errors = validate_blueprint(raw, candidate_scale)
        errors = [*scale_errors, *errors]
        if not errors:
            return blueprint, candidate_scale
    raise RetryableWorkflowError("整书规划蓝图未通过校验：" + "；".join(errors))


def _candidate_scale(
    state: NovelAgentState,
    raw: Any,
    default: ScaleContract,
    previous: NovelPlan | None,
) -> tuple[ScaleContract, list[str]]:
    request = state.get("plan_replan_request")
    if not isinstance(request, dict) or request.get("scope") != "scale":
        return default, []
    supplied = raw.get("scale") if isinstance(raw, dict) else None
    if not isinstance(supplied, dict):
        return default, ["规模重规划必须返回新的 scale 契约"]
    payload = {**default.to_dict(), **supplied, "preset": "custom"}
    payload["lock_window"] = default.lock_window
    try:
        candidate = ScaleContract.from_dict(payload)
    except NovelPlanValidationError as exc:
        return default, exc.errors
    locked = int(state.get("current_chapter_index", 0) or 0)
    locked += previous.scale.lock_window if previous else default.lock_window
    if candidate.target_chapters < locked:
        return candidate, ["缩减后的总章节数不得低于锁定边界"]
    return candidate, []


def _existing_blueprint(previous: NovelPlan) -> dict[str, Any]:
    return {
        "ending_contract": dict(previous.ending_contract),
        "volumes": [asdict(volume) for volume in previous.volumes],
        "arcs": [asdict(arc) for arc in previous.arcs],
    }


def _serializable_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "ending_contract": dict(blueprint["ending_contract"]),
        "volumes": [asdict(item) if isinstance(item, VolumePlan) else dict(item) for item in blueprint["volumes"]],
        "arcs": [asdict(item) if isinstance(item, StoryArc) else dict(item) for item in blueprint["arcs"]],
    }


def _volume_scope(mode: str, state: NovelAgentState) -> bool:
    request = state.get("plan_replan_request")
    return mode == "volume_detail" or (
        isinstance(request, dict) and request.get("scope") == "volume"
    )


def _base_slots(
    previous: NovelPlan | None, generation_order: list[str]
) -> list[dict[str, Any]]:
    if previous is None:
        return []
    generated_volumes = set(generation_order)
    return [
        {**asdict(slot), "intensity_weight": slot.target_words}
        for slot in previous.chapter_slots
        if slot.volume_id not in generated_volumes
    ]


async def _new_generation(
    state: NovelAgentState, config: RunnableConfig
) -> dict[str, Any]:
    previous = _plan(state.get("novel_plan"))
    mode = _mode(state, previous)
    scale = _scale_for_request(state, previous)
    legacy = await _legacy_facts(state, config["configurable"])
    if previous is not None and _volume_scope(mode, state):
        blueprint = _existing_blueprint(previous)
    else:
        blueprint, scale = await _generate_blueprint(
            state, config, scale, previous, legacy
        )
    current = int(state.get("current_chapter_index", 0) or 0) + 1
    order = [
        volume.volume_id if isinstance(volume, VolumePlan) else str(volume["volume_id"])
        for volume in blueprint["volumes"]
    ]
    if previous is not None and _volume_scope(mode, state):
        order = [_target_volume(previous, current)]
    request = state.get("plan_replan_request")
    force = mode == "legacy_upgrade" or isinstance(request, dict)
    return {
        "mode": mode,
        "source": _source(mode, request),
        "scale": scale.to_dict(),
        "blueprint": _serializable_blueprint(blueprint),
        "chapter_slots": _base_slots(previous, order),
        "generation_order": order,
        "next_volume_index": 0,
        "previous_plan": previous.to_dict() if previous else None,
        "legacy_chapters": legacy,
        "expected_version": previous.version if previous else 0,
        "review_force_human": force,
        "instruction": _instruction(state),
        "final_validation_attempts": 0,
        "preserve_all_word_targets": previous is not None and _volume_scope(mode, state),
    }


def _source(mode: str, request: Any) -> str:
    if mode == "legacy_upgrade":
        return "legacy_upgrade"
    if mode == "volume_detail":
        return "volume_detail"
    if isinstance(request, dict) and request.get("trigger") == "drift":
        return "drift_replan"
    return "user_replan" if mode == "replan" else "initial"


async def novel_plan_initialize_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["novel_plan_volume_node", "novel_plan_review_node"]]:
    """初始化可断点恢复的规划批次。"""
    if proposal_matches(state, "novel_plan"):
        return Command(goto="novel_plan_review_node")
    generation = state.get("plan_generation")
    if not isinstance(generation, dict) or not generation:
        emit_workflow_event(
            "status", {"status": "started", "message": "正在建立整书规模与分卷蓝图"},
            "novel_plan_initialize_node",
        )
        generation = await _new_generation(state, config)
    return Command(
        goto="novel_plan_volume_node",
        update={"plan_generation": generation, "plan_feedback": None},
    )


def _volume_for_generation(generation: dict[str, Any]):
    index = int(generation.get("next_volume_index", 0) or 0)
    volume_id = generation["generation_order"][index]
    raw = next(
        item for item in generation["blueprint"]["volumes"]
        if item.get("volume_id") == volume_id
    )
    return VolumePlan.from_dict(raw)


def _existing_volume_slots(
    generation: dict[str, Any], volume_id: str
) -> list[dict[str, Any]]:
    previous = generation.get("previous_plan")
    if not isinstance(previous, dict):
        return []
    return [asdict(slot) for slot in NovelPlan.from_dict(previous).chapter_slots if slot.volume_id == volume_id]


async def _generate_volume_slots(
    state: NovelAgentState,
    config: RunnableConfig,
    generation: dict[str, Any],
) -> list[dict[str, Any]]:
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if llm is None:
        raise RetryableWorkflowError("整书章节骨架生成失败：LLM 不可用")
    volume = _volume_for_generation(generation)
    detail = _detail_for_state(state, volume)
    errors: list[str] = []
    for _attempt in range(3):
        prompt = _volume_prompt(state, generation, volume, detail, errors)
        raw = await llm.structured_generate(
            prompt, VOLUME_SLOTS_SCHEMA, temperature=0.3, max_attempts=1
        )
        slots, errors = validate_volume_slots(
            raw, volume, _blueprint_arcs(generation), detail
        )
        if not errors:
            return slots
    raise RetryableWorkflowError(f"分卷 {volume.title} 未通过校验：" + "；".join(errors))


def _blueprint_arcs(generation: dict[str, Any]) -> list[StoryArc]:
    return [StoryArc.from_dict(item) for item in generation["blueprint"]["arcs"]]


def _detail_for_state(state: NovelAgentState, volume: Any) -> str:
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    return "detailed" if volume.start_chapter <= chapter <= volume.end_chapter else "skeleton"


def _volume_prompt(
    state: NovelAgentState,
    generation: dict[str, Any],
    volume: Any,
    detail: str,
    errors: list[str],
) -> str:
    completed = int(state.get("current_chapter_index", 0) or 0)
    previous = _plan(generation.get("previous_plan"))
    locked = completed + (previous.scale.lock_window if previous else 0)
    return build_volume_slots_prompt(
        scale=generation["scale"],
        ending_contract=generation["blueprint"]["ending_contract"],
        volume=asdict(volume),
        arcs=[asdict(arc) for arc in _blueprint_arcs(generation)],
        context=generation_context(generation["chapter_slots"]),
        existing_slots=_existing_volume_slots(generation, volume.volume_id),
        detail_level=detail,
        locked_through=locked,
        errors=errors,
        instruction=str(generation.get("instruction") or ""),
    )


def _merge_slots(
    generation: dict[str, Any], generated: list[dict[str, Any]], volume_id: str
) -> list[dict[str, Any]]:
    retained = [slot for slot in generation["chapter_slots"] if slot.get("volume_id") != volume_id]
    return sorted([*retained, *generated], key=lambda item: int(item["chapter_number"]))


async def novel_plan_volume_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["novel_plan_volume_node", "novel_plan_finalize_node"]]:
    """每次只生成一卷槽位，使成功批次进入 checkpoint。"""
    generation = dict(state.get("plan_generation") or {})
    volume = _volume_for_generation(generation)
    emit_workflow_event(
        "status", {"status": "started", "message": f"正在生成《{volume.title}》章节骨架"},
        "novel_plan_volume_node",
    )
    slots = await _generate_volume_slots(state, config, generation)
    generation["chapter_slots"] = _merge_slots(generation, slots, volume.volume_id)
    generation["next_volume_index"] = int(generation["next_volume_index"]) + 1
    finished = generation["next_volume_index"] >= len(generation["generation_order"])
    return Command(
        goto="novel_plan_finalize_node" if finished else "novel_plan_volume_node",
        update={"plan_generation": generation},
    )


def _restart_after_final_error(
    generation: dict[str, Any], error: NovelPlanValidationError
) -> dict[str, Any]:
    attempts = int(generation.get("final_validation_attempts", 0) or 0) + 1
    if attempts >= 3:
        raise RetryableWorkflowError("整书计划未通过全量校验：" + "；".join(error.errors))
    generation["chapter_slots"] = _base_slots(
        _plan(generation.get("previous_plan")), generation["generation_order"]
    )
    generation["next_volume_index"] = 0
    generation["final_validation_attempts"] = attempts
    generation["instruction"] = (
        str(generation.get("instruction") or "")
        + "\n必须修复全量校验错误："
        + "；".join(error.errors)
    ).strip()
    return generation


async def novel_plan_finalize_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["novel_plan_volume_node", "novel_plan_review_node"]]:
    """精确分配字数、全量校验并形成唯一计划提案。"""
    del config
    generation = dict(state.get("plan_generation") or {})
    completed = int(state.get("current_chapter_index", 0) or 0)
    generation["completed_chapters"] = completed
    try:
        plan = build_plan(generation, completed)
    except NovelPlanValidationError as exc:
        restarted = _restart_after_final_error(generation, exc)
        return Command(goto="novel_plan_volume_node", update={"plan_generation": restarted})
    previous = _plan(generation.get("previous_plan"))
    payload = {"plan": plan.to_dict(), "diff": plan_diff(previous, plan)}
    return Command(
        goto="novel_plan_review_node",
        update={**proposal_update(state, "novel_plan", payload), "plan_generation": generation},
    )


def _proposal_plan(payload: Any) -> NovelPlan:
    if not isinstance(payload, dict):
        raise RuntimeError("整书计划提案格式无效")
    raw = payload.get("plan") or payload.get("novel_plan") or payload
    if not isinstance(raw, dict):
        raise RuntimeError("整书计划提案缺少计划内容")
    plan = NovelPlan.from_dict(raw)
    plan.assert_valid()
    return plan


async def _accept_plan(
    plan: NovelPlan, generation: dict[str, Any], config: RunnableConfig
) -> NovelPlan:
    values = config["configurable"]
    repository = values.get("novel_repository")
    expected = int(generation.get("expected_version", 0) or 0)
    if repository is None or not hasattr(repository, "accept_plan"):
        plan.version = expected + 1
        return plan
    context = values.get("tenant_context")
    user_id = getattr(context, "user_id", None)
    return await repository.accept_plan(
        values.get("tenant_id", ""),
        values.get("novel_id", ""),
        plan,
        expected,
        created_by_user_id=str(user_id) if user_id else None,
        trigger_chapter=int(generation.get("completed_chapters", 0) or 0) or None,
        change_summary=str(generation.get("instruction") or generation.get("source") or ""),
    )


def _review_return(generation: dict[str, Any]) -> str:
    return "persist_node" if generation.get("mode") == "initial" else "progress_check_node"


def _mirrored_outline(state: NovelAgentState, plan: NovelPlan) -> dict[str, Any]:
    outline = dict(state.get("total_outline") or {})
    outline.update(
        total_chapters=plan.scale.target_chapters,
        scale=plan.scale.to_dict(),
        volumes=[asdict(volume) for volume in plan.volumes],
    )
    outline.pop("chapters", None)
    return outline


async def novel_plan_review_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["novel_plan_initialize_node", "persist_node", "progress_check_node"]]:
    """审核计划提案；旧书升级、用户重规划与重大漂移强制人工确认。"""
    proposal = require_proposal(state, "novel_plan")
    generation = dict(state.get("plan_generation") or {})
    decision = decide_proposal(
        state,
        proposal,
        config,
        force_human=bool(generation.get("review_force_human")),
        action="review_novel_plan",
        message="整书规划已完成，请审核规模、分卷、剧情弧和章节骨架",
        novel_plan=proposal["payload"],
    )
    if decision.action == "replace":
        raise InvalidReviewDecisionError("整书计划不支持直接替换原始 JSON")
    if decision.action in {"regenerate", "revise"}:
        feedback = decision.instruction if decision.action == "revise" else decision.feedback
        return Command(
            goto="novel_plan_initialize_node",
            update={
                "plan_generation": None,
                "plan_feedback": feedback or None,
                "pending_proposal": None,
                "pending_proposal_decision": None,
            },
        )
    accepted = await _accept_plan(_proposal_plan(proposal["payload"]), generation, config)
    return Command(
        goto=_review_return(generation),
        update={
            "novel_plan": accepted.to_dict(),
            "scale_contract": accepted.scale.to_dict(),
            "total_outline": _mirrored_outline(state, accepted),
            "plan_generation": None,
            "plan_replan_request": None,
            "pending_proposal": None,
            "pending_proposal_decision": None,
        },
    )


def _fulfillment(state: NovelAgentState) -> dict[str, Any]:
    gate = state.get("quality_gate")
    if isinstance(gate, dict) and isinstance(gate.get("plan_fulfillment"), dict):
        return dict(gate["plan_fulfillment"])
    value = state.get("plan_fulfillment")
    return dict(value) if isinstance(value, dict) else {}


async def _save_execution(
    execution: PlanExecution, config: RunnableConfig
) -> None:
    values = config["configurable"]
    repository = values.get("novel_repository")
    if repository is None or not hasattr(repository, "upsert_plan_execution"):
        return
    await repository.upsert_plan_execution(
        values.get("tenant_id", ""), values.get("novel_id", ""), execution
    )


def _execution(
    state: NovelAgentState, plan: NovelPlan, fulfillment: dict[str, Any]
) -> PlanExecution:
    chapter = int(state.get("current_chapter_index", 0) or 0)
    completed = state.get("last_persisted_chapter") or {}
    slot = next(item for item in plan.chapter_slots if item.chapter_number == chapter)
    actual = int(completed.get("word_count", 0) or 0)
    severity = classify_drift(fulfillment, actual, slot.target_words)
    status = {"none": "fulfilled", "minor": "deferred", "major": "breached"}[severity]
    return PlanExecution(chapter, plan.version, status, actual, fulfillment, severity)


async def _accept_drift_candidate(
    candidate: NovelPlan, plan: NovelPlan, chapter: int, config: RunnableConfig
) -> NovelPlan:
    values = config["configurable"]
    repository = values.get("novel_repository")
    if repository is None or not hasattr(repository, "accept_plan"):
        candidate.version = plan.version + 1
        return candidate
    context = values.get("tenant_context")
    user_id = getattr(context, "user_id", None)
    return await repository.accept_plan(
        values.get("tenant_id", ""), values.get("novel_id", ""), candidate,
        plan.version, created_by_user_id=str(user_id) if user_id else None,
        trigger_chapter=chapter, change_summary="章节轻微漂移自动顺延",
    )


def _drift_replan_request(plan: NovelPlan, execution: PlanExecution) -> dict[str, Any]:
    return {
        "expected_version": plan.version,
        "scope": "future",
        "instruction": "根据本章重大结构偏差重排未来计划：" + str(execution.fulfillment),
        "trigger": "drift",
    }


async def plan_reconciliation_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["progress_check_node", "novel_plan_initialize_node", "novel_plan_review_node"]]:
    """正文持久化后记录兑现情况，并按漂移等级进入既有提案流程。"""
    plan = _plan(state.get("novel_plan"))
    if plan is None:
        return Command(goto="novel_plan_initialize_node")
    fulfillment = _fulfillment(state)
    execution = _execution(state, plan, fulfillment)
    await _save_execution(execution, config)
    emit_workflow_event(
        "plan_reconciled", execution.to_dict(), "plan_reconciliation_node"
    )
    base_update = {
        "plan_fulfillment": fulfillment,
        "plan_drift_severity": execution.drift_severity,
    }
    if execution.drift_severity == "major":
        return Command(
            goto="novel_plan_initialize_node",
            update={**base_update, "plan_replan_request": _drift_replan_request(plan, execution)},
        )
    candidate = reschedule_minor_drift(plan, execution.chapter_number, fulfillment)
    if execution.drift_severity != "minor" or candidate is None:
        return Command(goto="progress_check_node", update=base_update)
    if config["configurable"].get("auto_mode", False):
        accepted = await _accept_drift_candidate(
            candidate, plan, execution.chapter_number, config
        )
        return Command(
            goto="progress_check_node",
            update={**base_update, "novel_plan": accepted.to_dict()},
        )
    payload = {"plan": candidate.to_dict(), "diff": plan_diff(plan, candidate)}
    generation = {
        "mode": "replan",
        "source": "manual_drift",
        "expected_version": plan.version,
        "completed_chapters": execution.chapter_number,
        "review_force_human": True,
        "instruction": "章节轻微漂移顺延",
    }
    return Command(
        goto="novel_plan_review_node",
        update={**base_update, "plan_generation": generation, **proposal_update(state, "novel_plan", payload)},
    )
