"""逐章细纲的生成节点与人工审核节点。"""

import json
import logging
from dataclasses import asdict
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.continuity import normalize_chapter_contract, validate_chapter_contract
from application.errors import InvalidReviewDecisionError, RetryableWorkflowError
from application.feature_policy import require_planning_v1
from application.planning import select_plan_context
from application.tactical_planning import (
    execution_contract_requirements,
    hydrate_tactical_window,
    validate_chapter_execution_contract,
)
from application.agents.tactical_plan_node import tactical_window_diff
from application.reserved_names import (
    consume_reserved_introductions,
    hydrate_reserved_introductions,
)
from application.prompts.chapter_outline_prompts import (
    CHAPTER_OUTLINE_SCHEMA,
    build_chapter_outline_prompt,
)
from application.prompts.review_feedback import append_review_feedback
from application.proposals import (
    decide_proposal,
    proposal_update,
    proposal_matches,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from service.value_objects.novel_plan import NovelPlan
from service.value_objects.tactical_plan import (
    ChapterExecutionContract,
    TacticalWindow,
)

logger = logging.getLogger("uvicorn")


def _total_outline(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validated_outline(
    generated: Any,
    chapter_number: int,
    total_outline: dict[str, Any] | None = None,
    *,
    plan: NovelPlan | None = None,
    window: TacticalWindow | None = None,
) -> dict[str, Any]:
    if not isinstance(generated, dict) or not generated:
        raise RuntimeError("章节细纲生成失败：模型未返回有效 JSON")
    outline = normalize_chapter_contract(generated, chapter_number)
    outline = hydrate_reserved_introductions(outline, total_outline or {})
    if plan is not None and window is not None:
        outline = _attach_execution_contract(outline, plan, window, chapter_number)
    issues = validate_chapter_contract(outline, chapter_number)
    if issues:
        raise RuntimeError(f"第 {chapter_number} 章细纲生成失败：" + "；".join(issues))
    word_count = outline.get("estimated_word_count", 5000)
    outline["estimated_word_count"] = max(3000, min(7000, int(word_count)))
    return outline


def _number_scenes(outline: dict[str, Any]) -> list[int]:
    raw = outline.get("scenes")
    scenes = raw if isinstance(raw, list) else []
    normalized: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        item = dict(scene) if isinstance(scene, dict) else {}
        item["scene_index"] = index
        normalized.append(item)
    outline["scenes"] = normalized
    return list(range(1, len(normalized) + 1))


def _rolling_plan(window: TacticalWindow, plan: NovelPlan) -> list[dict[str, Any]]:
    slots = {slot.chapter_number: slot for slot in plan.chapter_slots}
    return [
        {
            "chapter_number": beat.chapter_number,
            "goal": beat.tactical_goal,
            "required_event": "；".join(slots[beat.chapter_number].must_happen),
            "state_delta": slots[beat.chapter_number].planned_state_delta,
            "callback_ids": [
                *slots[beat.chapter_number].setup_ids,
                *slots[beat.chapter_number].payoff_ids,
            ],
            "exit_hook": beat.exit_hook,
        }
        for beat in window.beats
    ]


def _attach_execution_contract(
    outline: dict[str, Any],
    plan: NovelPlan,
    window: TacticalWindow,
    chapter_number: int,
) -> dict[str, Any]:
    result = dict(outline)
    scene_indices = _number_scenes(result)
    raw = result.get("chapter_execution_contract")
    payload = dict(raw) if isinstance(raw, dict) else {}
    payload.update({
        "plan_version": plan.version,
        "tactical_version": window.version,
        "chapter_number": chapter_number,
    })
    contract = ChapterExecutionContract.from_dict(payload)
    errors = validate_chapter_execution_contract(
        contract, plan, window, scene_indices
    )
    if errors:
        raise RuntimeError("执行契约未覆盖全部硬约束：" + "；".join(errors))
    result["chapter_execution_contract"] = contract.to_dict()
    result["rolling_plan"] = _rolling_plan(window, plan)
    return result


async def _generate_outline(
    state: NovelAgentState, config: RunnableConfig, chapter_number: int
) -> dict[str, Any]:
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("章节细纲生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": f"正在生成第{chapter_number}章细纲"},
        "chapter_outline_node",
    )
    plan = _novel_plan(state) if _schema5(state) else None
    window = _tactical_window(state) if plan else None
    plan_context = _plan_context(state, chapter_number)
    tactical_context = hydrate_tactical_window(window, plan) if window and plan else {}
    requirements = _execution_requirements(plan, chapter_number) if plan else {}
    errors: list[str] = []
    attempts = 3 if plan and window else 1
    for _attempt in range(attempts):
        prompt = build_chapter_outline_prompt(
            chapter_index=chapter_number,
            novel_type=state.get("novel_type", ""),
            title=str(state.get("title") or ""),
            total_outline=_total_outline(state.get("total_outline")),
            memory_context=str(state.get("memory_context") or ""),
            plan_context=plan_context,
            tactical_context=tactical_context,
            execution_requirements=requirements,
            validation_issues=errors,
            schema_version=int(state.get("workflow_schema_version") or 2),
        )
        generated = await llm.structured_generate(
            prompt=append_review_feedback(prompt, state.get("chapter_outline_feedback")),
            schema=CHAPTER_OUTLINE_SCHEMA,
            temperature=0.45,
        )
        try:
            outline = _validated_outline(
                generated,
                chapter_number,
                _total_outline(state.get("total_outline")),
                plan=plan,
                window=window,
            )
            return _attach_plan_contract(
                outline, plan_context, tactical_context=tactical_context
            )
        except RuntimeError as exc:
            errors = [str(exc)]
    raise RetryableWorkflowError("章节细纲执行契约校验失败：" + "；".join(errors))


def _schema5(state: NovelAgentState) -> bool:
    return int(state.get("workflow_schema_version") or 2) >= 5


def _novel_plan(state: NovelAgentState) -> NovelPlan:
    raw = state.get("novel_plan")
    if not isinstance(raw, dict) or not raw:
        raise RetryableWorkflowError("章节细纲生成失败：缺少整书计划")
    return NovelPlan.from_dict(raw)


def _tactical_window(state: NovelAgentState) -> TacticalWindow:
    raw = state.get("tactical_window")
    if not isinstance(raw, dict) or not raw:
        raise RetryableWorkflowError("章节细纲生成失败：缺少近期战术窗口")
    return TacticalWindow.from_dict(raw)


def _execution_requirements(
    plan: NovelPlan, chapter_number: int
) -> dict[str, list[str]]:
    slot = next(
        item for item in plan.chapter_slots if item.chapter_number == chapter_number
    )
    values = execution_contract_requirements(slot)
    return {key: sorted(items) for key, items in values.items()}


def _plan_context(
    state: NovelAgentState, chapter_number: int
) -> dict[str, Any]:
    raw = state.get("novel_plan")
    if not isinstance(raw, dict) or not raw:
        return {}
    return select_plan_context(NovelPlan.from_dict(raw), chapter_number)


def _attach_plan_contract(
    outline: dict[str, Any],
    context: dict[str, Any],
    *,
    tactical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not context:
        return outline
    slot = context.get("current_slot") or {}
    outline["estimated_word_count"] = int(slot.get("target_words", 0) or 5000)
    outline["plan_context"] = context
    if tactical_context:
        outline["tactical_context"] = tactical_context
    return outline


def _accept_outline_update(
    state: NovelAgentState, outline: dict[str, Any], *, clear_proposal: bool = False,
) -> dict[str, Any]:
    total = _total_outline(state.get("total_outline"))
    update: dict[str, Any] = {
        "chapter_outlines": [outline],
        "total_outline": consume_reserved_introductions(total, outline),
    }
    if clear_proposal:
        update.update({"pending_proposal": None, "pending_proposal_decision": None})
    return update


async def chapter_outline_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal[
    "router_agent", "chapter_outline_review_node", "chapter_plan_review_node"
]]:
    """生成当前章节细纲并保存提案，不执行人工审核。"""
    if _schema5(state):
        await require_planning_v1(config)
    chapter_number = int(state.get("current_chapter_index", 0) or 0) + 1
    proposal_kind = "chapter_plan" if _schema5(state) else "chapter_outline"
    if proposal_matches(state, proposal_kind, chapter_number):
        if proposal_kind == "chapter_plan":
            return Command(goto="chapter_plan_review_node")
        return Command(goto="chapter_outline_review_node")
    if state.get("chapter_outlines_input"):
        plan = _novel_plan(state) if _schema5(state) else None
        window = _tactical_window(state) if plan else None
        outline = _validated_outline(
            state["chapter_outlines_input"], chapter_number,
            _total_outline(state.get("total_outline")),
            plan=plan, window=window,
        )
        outline = _attach_plan_contract(
            outline,
            _plan_context(state, chapter_number),
            tactical_context=(
                hydrate_tactical_window(window, plan) if window and plan else None
            ),
        )
        if not _schema5(state):
            return Command(goto="router_agent", update={
                **_accept_outline_update(state, outline),
                "chapter_outlines_input": None,
            })
        return _chapter_plan_proposal(state, outline, chapter_number)
    outline = await _generate_outline(state, config, chapter_number)
    if _schema5(state):
        return _chapter_plan_proposal(state, outline, chapter_number)
    return Command(
        goto="chapter_outline_review_node",
        update={
            **proposal_update(state, "chapter_outline", outline, chapter_number),
            "chapter_outline_feedback": None,
        },
    )


def _assembled_slots(
    plan: NovelPlan, window: TacticalWindow
) -> list[dict[str, Any]]:
    return list(hydrate_tactical_window(window, plan).get("beats") or [])


def _chapter_plan_payload(
    state: NovelAgentState, outline: dict[str, Any]
) -> dict[str, Any]:
    plan = _novel_plan(state)
    window = _tactical_window(state)
    previous = None
    raw_previous = state.get("tactical_previous_window")
    if isinstance(raw_previous, dict) and raw_previous:
        previous = TacticalWindow.from_dict(raw_previous)
    slot = next(
        asdict(item) for item in plan.chapter_slots
        if item.chapter_number == window.start_chapter
    )
    return {
        "tactical_window": window.to_dict(),
        "assembled_slots": _assembled_slots(plan, window),
        "current_slot": slot,
        "chapter_outline": outline,
        "execution_contract": outline.get("chapter_execution_contract", {}),
        "previous_window_diff": tactical_window_diff(previous, window),
    }


def _chapter_plan_proposal(
    state: NovelAgentState, outline: dict[str, Any], chapter_number: int
) -> Command:
    payload = _chapter_plan_payload(state, outline)
    return Command(
        goto="chapter_plan_review_node",
        update={
            **proposal_update(state, "chapter_plan", payload, chapter_number),
            "chapter_outline_feedback": None,
            "chapter_outlines_input": None,
        },
    )


async def _accept_tactical_window(
    state: NovelAgentState,
    window: TacticalWindow,
    idempotency_key: str,
    config: RunnableConfig,
) -> TacticalWindow:
    values = config["configurable"]
    repository = values.get("novel_repository")
    accept = getattr(repository, "accept_tactical_plan", None)
    if not callable(accept):
        return window
    context = values.get("tenant_context")
    user_id = getattr(context, "user_id", None)
    return await accept(
        values.get("tenant_id", ""),
        values.get("novel_id", ""),
        window,
        int(state.get("tactical_window_expected_version", 0) or 0),
        idempotency_key=idempotency_key,
        created_by_user_id=str(user_id) if user_id else None,
    )


def _accepted_outline(
    state: NovelAgentState,
    payload: dict[str, Any],
    accepted: TacticalWindow,
    chapter_number: int,
) -> dict[str, Any]:
    raw = payload.get("chapter_outline")
    plan = _novel_plan(state)
    outline = _validated_outline(
        raw,
        chapter_number,
        _total_outline(state.get("total_outline")),
        plan=plan,
        window=accepted,
    )
    return _attach_plan_contract(
        outline,
        _plan_context(state, chapter_number),
        tactical_context=hydrate_tactical_window(accepted, plan),
    )


def _regenerate_chapter_plan(scope: str, instruction: str) -> Command:
    if scope == "chapter_outline":
        return Command(goto="chapter_outline_node", update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "chapter_outline_feedback": instruction or None,
            "chapter_plan_revision_scope": scope,
        })
    return Command(goto="tactical_plan_node", update={
        "pending_proposal": None,
        "pending_proposal_decision": None,
        "tactical_window": None,
        "tactical_window_persisted": False,
        "tactical_plan_feedback": instruction or None,
        "chapter_outline_feedback": instruction if scope == "both" else None,
        "chapter_plan_revision_scope": scope,
    })


async def chapter_plan_review_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["router_agent", "chapter_outline_node", "tactical_plan_node"]]:
    """Review and atomically bind a tactical version to the chapter outline."""
    await require_planning_v1(config)
    chapter_number = int(state.get("current_chapter_index", 0) or 0) + 1
    proposal = require_proposal(state, "chapter_plan", chapter_number)
    payload = proposal["payload"] if isinstance(proposal["payload"], dict) else {}
    decision = decide_proposal(
        state,
        proposal,
        config,
        action="review_or_modify_chapter_plan",
        message=f"第{chapter_number}章近期战术与执行细纲已生成，请统一审核",
        chapter_plan=payload,
        tactical_window=payload.get("tactical_window"),
        ai_generated_outline=payload.get("chapter_outline"),
        execution_contract=payload.get("execution_contract"),
    )
    if decision.action == "replace":
        raise InvalidReviewDecisionError("联合章节计划不支持直接替换原始 JSON")
    if decision.action in {"regenerate", "revise"}:
        instruction = (
            decision.instruction if decision.action == "revise" else decision.feedback
        )
        return _regenerate_chapter_plan(decision.scope or "both", instruction)
    window_raw = payload.get("tactical_window")
    if not isinstance(window_raw, dict):
        raise RetryableWorkflowError("联合章节计划缺少战术窗口")
    accepted = await _accept_tactical_window(
        state,
        TacticalWindow.from_dict(window_raw),
        proposal["proposal_id"],
        config,
    )
    outline = _accepted_outline(state, payload, accepted, chapter_number)
    return Command(goto="router_agent", update={
        **_accept_outline_update(state, outline, clear_proposal=True),
        "tactical_window": accepted.to_dict(),
        "tactical_window_expected_version": accepted.version,
        "tactical_window_persisted": True,
        "tactical_plan_feedback": None,
        "chapter_outline_feedback": None,
        "chapter_plan_revision_scope": None,
    })


async def chapter_outline_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["router_agent", "chapter_outline_node"]]:
    """审核已保存的章节细纲，本节点不得调用 LLM。"""
    chapter_number = int(state.get("current_chapter_index", 0) or 0) + 1
    proposal = require_proposal(state, "chapter_outline", chapter_number)
    decision = decide_proposal(
        state,
        proposal,
        config,
        action="review_or_provide_chapter_outline",
        message=f"第{chapter_number}章细纲已生成，请审阅或修改",
        ai_generated_outline=proposal["payload"],
    )
    if decision.action in {"regenerate", "revise"}:
        feedback = (
            decision.instruction
            if decision.action == "revise"
            else decision.feedback
        )
        return _regenerate_chapter_outline(feedback)
    selected = proposal["payload"] if decision.action == "accept" else decision.value
    outline = _validated_outline(
        selected, chapter_number, _total_outline(state.get("total_outline")),
    )
    return Command(
        goto="router_agent",
        update={
            **_accept_outline_update(state, outline, clear_proposal=True),
            "chapter_outline_feedback": None,
        },
    )


def _regenerate_chapter_outline(feedback: str) -> Command:
    return Command(
        goto="chapter_outline_node",
        update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "chapter_outline_feedback": feedback or None,
        },
    )
