"""Generate the premise-first creative brief before naming the novel."""

import logging
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from application.prompts.creative_brief_prompts import (
    CREATIVE_BRIEF_SCHEMA,
    build_creative_brief_prompt,
    build_legacy_creative_brief,
    normalize_creative_brief,
    validate_creative_brief,
)
from application.prompts.version import PROMPT_VERSION
from application.schemas.agent_state import NovelAgentState

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
) -> Command[Literal["title_node", "creative_brief_node"]]:
    """生成并确认创作简报，作为后续提示词的共同事实源。"""
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
        return Command(goto="title_node", update={"creative_brief": brief, "prompt_version": PROMPT_VERSION})

    decision = interrupt(
        {
            "action": "review_or_modify_creative_brief",
            "message": "AI 已形成创作简报，请确认故事承诺与核心冲突",
            "ai_generated_creative_brief": brief,
        }
    )
    if decision == "accept":
        return Command(goto="title_node", update={"creative_brief": brief, "prompt_version": PROMPT_VERSION})
    if isinstance(decision, dict):
        selected = normalize_creative_brief({**brief, **decision})
        if not validate_creative_brief(selected):
            return Command(goto="title_node", update={"creative_brief": selected, "prompt_version": PROMPT_VERSION})
    feedback = "请生成不同方案" if decision == "regenerate" else str(decision or "")
    return Command(goto="creative_brief_node", update={"creative_brief_feedback": feedback})
