"""Generate the premise-first creative brief before naming the novel."""

import logging
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.prompts.creative_brief_prompts import (
    CREATIVE_BRIEF_SCHEMA,
    build_creative_brief_prompt,
    build_legacy_creative_brief,
    normalize_creative_brief,
    validate_creative_brief,
)
from application.prompts.version import PROMPT_VERSION
from application.proposals import (
    proposal_update,
    proposal_matches,
    require_proposal,
    request_decision,
    unpack_decision,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event

logger = logging.getLogger("uvicorn")


def _legacy_brief(state: NovelAgentState) -> dict | None:
    outline = state.get("total_outline")
    if not isinstance(outline, dict) or not outline.get("story_background"):
        return None
    return build_legacy_creative_brief(
        state.get("novel_type", ""),
        state.get("title", ""),
        state.get("summary", ""),
        outline,
    )


def _merge_seed(generated: dict, seed: dict) -> dict:
    merged = dict(generated)
    for key, value in seed.items():
        if value not in (None, "", []):
            merged[key] = value
    return normalize_creative_brief(merged)


async def creative_brief_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["title_node", "creative_brief_review_node"]]:
    """生成创作简报并先写入 checkpoint，不执行人工审核。"""
    if proposal_matches(state, "creative_brief"):
        return Command(goto="creative_brief_review_node")
    seed = normalize_creative_brief(state.get("creative_brief"))
    if not validate_creative_brief(seed):
        return Command(goto="title_node", update={"prompt_version": PROMPT_VERSION})
    legacy = _legacy_brief(state)
    if legacy:
        legacy = _merge_seed(legacy, seed)
        return Command(
            goto="title_node",
            update={"creative_brief": legacy, "prompt_version": PROMPT_VERSION},
        )
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("创作简报生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成创作简报提案"},
        "creative_brief_node",
    )
    generated = await llm.structured_generate(
        prompt=build_creative_brief_prompt(
            state.get("novel_type", ""),
            state.get("title", ""),
            state.get("summary", ""),
            seed,
            state.get("creative_brief_feedback", ""),
        ),
        schema=CREATIVE_BRIEF_SCHEMA,
        temperature=0.65,
        top_p=0.9,
    )
    brief = _merge_seed(normalize_creative_brief(generated), seed)
    missing = validate_creative_brief(brief)
    if missing:
        raise RuntimeError(f"创作简报生成失败：缺少 {', '.join(missing)}")
    if config["configurable"].get("auto_mode", False):
        return Command(
            goto="title_node",
            update={"creative_brief": brief, "prompt_version": PROMPT_VERSION},
        )
    return Command(
        goto="creative_brief_review_node",
        update=proposal_update(state, "creative_brief", brief),
    )


async def creative_brief_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["title_node", "creative_brief_node"]]:
    """审核已保存的创作简报，本节点不得调用 LLM。"""
    del config
    proposal = require_proposal(state, "creative_brief")
    raw_decision = request_decision(
        state,
        proposal,
        action="review_or_modify_creative_brief",
        message="AI 已形成创作简报，请确认故事承诺与核心冲突",
        ai_generated_creative_brief=proposal["payload"],
    )
    decision = unpack_decision(raw_decision, proposal)
    if decision == "accept":
        return _accept_brief(proposal["payload"])
    if decision == "regenerate":
        feedback = raw_decision.get("feedback", "") if isinstance(raw_decision, dict) else ""
        return _regenerate_brief(feedback or "请生成不同方案")
    if isinstance(decision, dict):
        selected = _merge_seed(proposal["payload"], decision)
        if not validate_creative_brief(selected):
            return _accept_brief(selected)
    return _regenerate_brief(str(decision or ""))


def _accept_brief(brief: dict) -> Command:
    return Command(
        goto="title_node",
        update={
            "creative_brief": brief,
            "pending_proposal": None,
            "pending_proposal_decision": None,
        },
    )


def _regenerate_brief(feedback: str) -> Command:
    return Command(
        goto="creative_brief_node",
        update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "creative_brief_feedback": feedback,
        },
    )
