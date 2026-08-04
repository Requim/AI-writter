"""Generate the bounded macro outline before the per-chapter loop."""

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.character_design import backfill_character_design
from application.prompts.outline_prompts import (
    OUTLINE_SCHEMA,
    build_outline_prompt,
    validate_outline,
)
from application.prompts.review_feedback import append_review_feedback
from application.prompts.version import PROMPT_VERSION
from application.proposals import (
    decide_proposal,
    proposal_update,
    proposal_matches,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event

logger = logging.getLogger("uvicorn")


def apply_creation_constraints(
    outline: dict[str, Any],
    target_total_chapters: Any = None,
    requested_writing_style: Any = None,
) -> dict[str, Any]:
    """Apply trusted user planning constraints to a generated macro outline."""
    constrained = dict(outline)

    target = 0
    if not isinstance(target_total_chapters, bool):
        try:
            target = int(target_total_chapters) if target_total_chapters is not None else 0
        except (TypeError, ValueError):
            target = 0
    if 1 <= target <= 200:
        constrained["total_chapters"] = target
        volumes = constrained.get("volumes")
        if isinstance(volumes, list) and volumes:
            volume_count = min(len(volumes), target)
            normalized_volumes: list[dict[str, Any]] = []
            for index, raw_volume in enumerate(volumes[:volume_count]):
                volume = dict(raw_volume) if isinstance(raw_volume, dict) else {}
                volume["volume_number"] = index + 1
                volume["start_chapter"] = index * target // volume_count + 1
                volume["end_chapter"] = (index + 1) * target // volume_count
                normalized_volumes.append(volume)
            constrained["volumes"] = normalized_volumes

    requested_style = str(requested_writing_style or "").strip()
    if requested_style:
        generated_style = str(constrained.get("writing_style") or "").strip()
        if requested_style not in generated_style:
            constrained["writing_style"] = (
                f"用户指定风格：{requested_style}。{generated_style}"
            )

    return constrained


def _prepare_outline(state: NovelAgentState, generated: dict[str, Any]) -> dict[str, Any]:
    """应用可信输入约束并验证宏观总纲。"""
    outline = dict(generated)
    outline.pop("chapters", None)
    outline = apply_creation_constraints(
        outline,
        state.get("target_total_chapters"),
        state.get("requested_writing_style"),
    )
    if state.get("title"):
        outline["source_title"] = state["title"]
    planning_summary = state.get("editorial_summary") or state.get("summary", "")
    if planning_summary:
        outline["source_summary"] = planning_summary
    design = state.get("character_design") if isinstance(state.get("character_design"), dict) else {}
    characters = design.get("characters") if isinstance(design.get("characters"), list) else []
    if characters:
        outline["main_characters"] = characters
    brief = dict(state.get("creative_brief") or {})
    if isinstance(design.get("naming_policy"), dict):
        brief["naming_policy"] = design["naming_policy"]
    outline["creative_brief"] = brief
    outline["prompt_version"] = PROMPT_VERSION
    try:
        outline["total_chapters"] = int(outline.get("total_chapters", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("宏观总纲生成失败：total_chapters 无效") from exc
    validation = validate_outline(outline)
    if not validation["valid"]:
        details = "；".join(validation["fatal_issues"][:3])
        raise RuntimeError(f"宏观总纲生成失败：{details}")
    return outline


def _reuse_existing_outline(
    state: NovelAgentState,
) -> Command[Literal["persist_node"]] | None:
    existing = state.get("total_outline")
    if not isinstance(existing, dict):
        return None
    if not existing.get("story_background") or not existing.get("total_chapters"):
        return None
    enriched = dict(existing)
    enriched["creative_brief"] = state.get("creative_brief") or enriched.get(
        "creative_brief", {}
    )
    enriched["prompt_version"] = PROMPT_VERSION
    design = backfill_character_design(
        enriched.get("main_characters"),
        enriched.get("creative_brief", {}).get("naming_policy", {}),
    )
    return Command(
        goto="persist_node",
        update={
            "total_outline": enriched, "character_design": design,
            "__next_node__": "progress_check_node",
        },
    )


def _needs_character_design(state: NovelAgentState) -> bool:
    design = state.get("character_design")
    return not isinstance(design, dict) or not design.get("characters")


async def _generate_outline_proposal(
    state: NovelAgentState, config: RunnableConfig, title: str,
) -> dict[str, Any]:
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("宏观总纲生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成宏观总纲提案"},
        "outline_node",
    )
    design = state.get("character_design") or {}
    planning_summary = state.get("editorial_summary") or state.get("summary", "")
    prompt = build_outline_prompt(
            state.get("novel_type", ""), title, planning_summary,
            target_total_chapters=state.get("target_total_chapters"),
            requested_writing_style=state.get("requested_writing_style"),
            creative_brief=state.get("creative_brief"),
            main_characters=design.get("characters", []),
        )
    generated = await llm.structured_generate(
        prompt=append_review_feedback(prompt, state.get("outline_feedback")),
        schema=OUTLINE_SCHEMA, temperature=0.75, top_p=0.9,
    )
    if not generated:
        raise RuntimeError("宏观总纲生成失败：模型未返回有效 JSON")
    return generated


async def outline_generator_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["character_design_node", "persist_node", "outline_review_node"]]:
    """生成宏观总纲并保存提案，不执行人工审核。"""
    title = state.get("title", "")
    if proposal_matches(state, "outline"):
        return Command(goto="outline_review_node")
    existing_command = _reuse_existing_outline(state)
    if existing_command:
        logger.info("【宏观总纲节点】跳过 | 使用已有总纲并补齐创作简报")
        return existing_command
    if _needs_character_design(state):
        return Command(
            goto="character_design_node",
            update={"character_design_return_to": "outline_node"},
        )
    generated = await _generate_outline_proposal(state, config, title)
    ai_outline = _prepare_outline(state, generated)
    return Command(
        goto="outline_review_node",
        update={**proposal_update(state, "outline", ai_outline), "outline_feedback": None},
    )


async def outline_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["persist_node", "outline_node"]]:
    """审核已保存的宏观总纲，本节点不得调用 LLM。"""
    proposal = require_proposal(state, "outline")
    validation = validate_outline(proposal["payload"])
    decision = decide_proposal(
        state,
        proposal,
        config,
        action="review_or_modify_outline",
        message="AI 已生成宏观总纲，请审阅后进入逐章创作",
        ai_generated_outline=proposal["payload"],
        validation=validation,
    )
    if decision.action in {"regenerate", "revise"}:
        feedback = (
            decision.instruction
            if decision.action == "revise"
            else decision.feedback
        )
        return _regenerate_outline(feedback)
    selected = proposal["payload"] if decision.action == "accept" else decision.value
    if not isinstance(selected, dict):
        raise RuntimeError("宏观总纲生成失败：用户提交的总纲格式无效")
    selected = _prepare_outline(state, selected)
    return Command(
        goto="persist_node",
        update={
            "total_outline": selected,
            "outline_feedback": None,
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "__next_node__": "progress_check_node",
        },
    )


def _regenerate_outline(feedback: str) -> Command:
    return Command(
        goto="outline_node",
        update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "outline_feedback": feedback or None,
        },
    )
