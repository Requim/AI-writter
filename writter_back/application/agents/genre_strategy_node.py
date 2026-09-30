"""Generate and review the work-specific genre strategy."""

from typing import Literal
import hashlib
import json

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.prompts.genre_strategy_prompts import (
    GENRE_STRATEGY_SCHEMA,
    build_genre_strategy_prompt,
    normalize_genre_strategy,
    static_genre_strategy,
    validate_genre_strategy,
)
from application.proposals import (
    decide_proposal,
    proposal_matches,
    proposal_update,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.prompts.version import PROMPT_VERSION
from application.research.materials import material_prompt_block


def _strategy_update(state: NovelAgentState, strategy: dict) -> dict:
    brief = dict(state.get("creative_brief") or {})
    brief["genre_strategy"] = strategy
    version = int(state.get("genre_strategy_version") or 0) + 1
    brief["genre_strategy_meta"] = {
        "version": version, "prompt_version": state.get("prompt_version") or PROMPT_VERSION,
        "digest": hashlib.sha256(json.dumps(strategy, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    return {
        "genre_strategy": strategy,
        "genre_strategy_version": version,
        "creative_brief": brief,
        "genre_strategy_feedback": None,
        "pending_proposal": None,
        "pending_proposal_decision": None,
    }


def _work_context(state: NovelAgentState) -> dict:
    """仅向策略阶段提供用户创作输入，不带入历史正文或作者秘密。"""
    brief = state.get("creative_brief") or {}
    result = {key: state.get(key) for key in (
        "title", "summary", "target_total_chapters", "target_total_words",
        "scale_contract", "requested_writing_style",
    ) if state.get(key) is not None}
    result["brief"] = {key: brief[key] for key in (
        "core_premise", "reader_promise", "setting_context",
        "naming_preference", "content_boundaries", "style_fingerprint",
    ) if key in brief}
    return result


async def genre_strategy_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["genre_strategy_review_node", "creative_brief_node"]]:
    """Generate a validated strategy proposal, or reuse an existing one."""
    if not validate_genre_strategy(state.get("genre_strategy")) and not state.get("genre_strategy_feedback"):
        return Command(goto="creative_brief_node")
    if (
        not state.get("genre_strategy_enabled", False)
        and isinstance(state.get("creative_brief"), dict)
        and state.get("creative_brief")
    ):
        strategy = static_genre_strategy(state.get("novel_type", ""))
        return Command(
            goto="creative_brief_node",
            update=_strategy_update(state, strategy),
        )
    if proposal_matches(state, "genre_strategy"):
        return Command(goto="genre_strategy_review_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("题材策略生成失败：LLM 不可用")
    context = state.get("creative_brief") or {}
    generated = await llm.structured_generate(
        prompt=build_genre_strategy_prompt(
            state.get("novel_type", ""),
            context.get("genre_context") if isinstance(context, dict) else {},
            state.get("genre_strategy_feedback", ""),
            work_context=_work_context(state),
        ) + material_prompt_block(context, "genre_strategy"),
        schema=GENRE_STRATEGY_SCHEMA,
        temperature=0.45,
        top_p=0.85,
    )
    missing = validate_genre_strategy(generated)
    if missing:
        raise RuntimeError(f"题材策略生成失败：无效字段 {', '.join(missing)}")
    strategy = normalize_genre_strategy(generated)
    return Command(
        goto="genre_strategy_review_node",
        update={
            **proposal_update(state, "genre_strategy", strategy),
            "genre_strategy_feedback": None,
            "prompt_version": state.get("prompt_version") or PROMPT_VERSION,
        },
    )


async def genre_strategy_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["creative_brief_node", "genre_strategy_node"]]:
    """Accept or revise the strategy proposal without calling the model."""
    proposal = require_proposal(state, "genre_strategy")
    decision = decide_proposal(
        state,
        proposal,
        config,
        action="review_or_modify_genre_strategy",
        ai_generated_genre_strategy=proposal["payload"],
        message="AI 已生成本作品的题材策略，请确认后继续",
    )
    if decision.action == "accept":
        if validate_genre_strategy(proposal["payload"]):
            raise ValueError("题材策略提案无效，不能接受")
        return Command(
            goto="creative_brief_node",
            update={
                **_strategy_update(state, normalize_genre_strategy(proposal["payload"])),
            },
        )
    if decision.action == "regenerate":
        feedback = decision.feedback or "请生成不同的题材策略"
    elif decision.action == "revise":
        feedback = decision.instruction or "请按审核意见修改题材策略"
    else:
        selected = decision.value
        if not validate_genre_strategy(selected):
            return Command(
                goto="creative_brief_node",
                update={
                    **_strategy_update(state, selected),
                },
            )
        feedback = "请生成满足题材策略契约的结果"
    return Command(
        goto="genre_strategy_node",
        update={
            "genre_strategy_feedback": feedback,
            "pending_proposal": None,
            "pending_proposal_decision": None,
        },
    )
