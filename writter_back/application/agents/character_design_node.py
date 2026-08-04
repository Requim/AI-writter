"""生成、审核并规范化小说角色设计。"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.character_design import (
    backfill_character_design,
    build_character_design_proposal,
    resolve_character_design,
)
from application.errors import RetryableWorkflowError
from application.naming import NamingValidationError, build_candidate_pool
from application.prompts.character_design_prompts import (
    CHARACTER_DESIGN_SCHEMA,
    build_character_design_prompt,
)
from application.prompts.version import PROMPT_VERSION
from application.proposals import (
    proposal_matches,
    proposal_update,
    request_decision,
    require_proposal,
    unpack_decision,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event


def _return_target(state: NovelAgentState) -> str:
    target = state.get("character_design_return_to")
    return target if target in {"title_node", "outline_node"} else "title_node"


def _existing_design(state: NovelAgentState) -> dict[str, Any] | None:
    design = state.get("character_design")
    if isinstance(design, Mapping):
        restored = backfill_character_design(
            design.get("characters"), design.get("naming_policy"), design.get("relationships"),
        )
        if restored:
            return restored
    outline = state.get("total_outline")
    if not isinstance(outline, Mapping):
        return None
    brief_value = outline.get("creative_brief")
    brief = brief_value if isinstance(brief_value, Mapping) else {}
    return backfill_character_design(outline.get("main_characters"), brief.get("naming_policy"))


def _accept_design(state: NovelAgentState, design: dict[str, Any]) -> Command:
    return Command(
        goto=_return_target(state),
        update={
            "character_design": design, "pending_proposal": None,
            "pending_proposal_decision": None, "character_design_return_to": None,
            "prompt_version": PROMPT_VERSION,
        },
    )


def _character_name(value: Any) -> str:
    raw = value if isinstance(value, Mapping) else {}
    return str(raw.get("name") or raw.get("姓名") or "").strip()


def _outline_characters(novel: Any) -> list[Any]:
    outline = getattr(novel, "total_outline", None)
    if isinstance(outline, Mapping):
        value = outline.get("main_characters")
    else:
        value = getattr(outline, "main_characters", None)
    return value if isinstance(value, list) else []


async def _recent_character_names(config: RunnableConfig) -> tuple[str, ...]:
    configurable = config.get("configurable", {})
    repository = configurable.get("novel_repository")
    tenant_id = str(configurable.get("tenant_id") or "")
    if repository is None or not tenant_id or not hasattr(repository, "find_all"):
        return ()
    novels = await repository.find_all(tenant_id)
    current_id = str(configurable.get("novel_id") or "")
    recent = [item for item in novels if str(getattr(item, "id", "")) != current_id][:20]
    names = [_character_name(item) for novel in recent for item in _outline_characters(novel)]
    return tuple(name for name in names if name)


def _proposal_version(state: NovelAgentState) -> int:
    versions = state.get("proposal_versions") or {}
    return int(versions.get("character_design", 0) or 0) + 1


def _seed_identity(config: RunnableConfig) -> tuple[str, str]:
    value = config.get("configurable", {})
    tenant_id = str(value.get("tenant_id") or "local-tenant")
    novel_id = str(value.get("novel_id") or "local-novel")
    return tenant_id, novel_id


def _prompt_pool(pool: Any) -> list[dict[str, Any]]:
    return [item.to_dict() for item in pool]


async def _generate_valid_proposal(
    state: NovelAgentState,
    llm: Any,
    pool: Any,
    version: int,
) -> dict[str, Any]:
    feedback = str(state.get("character_design_feedback") or "")
    brief = state.get("creative_brief") or {}
    for _attempt in range(3):
        prompt = build_character_design_prompt(
            state.get("novel_type", ""), brief, _prompt_pool(pool),
            brief.get("naming_preference") if isinstance(brief, Mapping) else None,
            feedback,
        )
        generated = await llm.structured_generate(
            prompt, CHARACTER_DESIGN_SCHEMA, temperature=0.55, top_p=0.85,
        )
        try:
            return build_character_design_proposal(
                generated, pool, proposal_version=version, prompt_version=PROMPT_VERSION,
            )
        except NamingValidationError as exc:
            feedback = str(exc)
    raise RetryableWorkflowError(f"角色设计生成失败：{feedback or '模型输出无效'}")


async def character_design_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["character_design_review_node", "title_node", "outline_node"]]:
    """生成角色设计提案；姓名与典故全部由服务端候选池约束。"""
    if proposal_matches(state, "character_design"):
        return Command(goto="character_design_review_node")
    existing = _existing_design(state)
    if existing:
        return _accept_design(state, existing)
    llm = config.get("configurable", {}).get("llm_config", {}).get("llm_instance")
    if llm is None:
        raise RetryableWorkflowError("角色设计生成失败：LLM 不可用")
    recent_names = await _recent_character_names(config)
    version = _proposal_version(state)
    tenant_id, novel_id = _seed_identity(config)
    pool = build_candidate_pool(
        tenant_id=tenant_id, novel_id=novel_id, proposal_version=version,
        prompt_version=PROMPT_VERSION, count=52, recent_names=recent_names,
        genre_tag=state.get("novel_type"),
    )
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成角色设计与典故姓名候选"},
        "character_design_node",
    )
    proposal = await _generate_valid_proposal(state, llm, pool, version)
    if config.get("configurable", {}).get("auto_mode", False):
        return _accept_design(state, resolve_character_design(proposal, {}, recent_names=recent_names))
    return Command(
        goto="character_design_review_node",
        update=proposal_update(state, "character_design", proposal),
    )


async def character_design_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["character_design_node", "title_node", "outline_node"]]:
    """审核当前版本角色提案，并拒绝跨版本候选选择。"""
    proposal = require_proposal(state, "character_design")
    raw_decision = request_decision(
        state, proposal, action="review_or_modify_character_design",
        message="AI 已生成角色设计，请逐一确认核心角色姓名",
        ai_generated_character_design=proposal["payload"],
    )
    decision = unpack_decision(raw_decision, proposal)
    if decision == "regenerate":
        feedback = raw_decision.get("feedback", "") if isinstance(raw_decision, Mapping) else ""
        return _regenerate_design(feedback)
    selection = {} if decision == "accept" else decision
    if not isinstance(selection, Mapping):
        return _regenerate_design(str(selection or "请生成不同角色方案"))
    recent_names = await _recent_character_names(config)
    design = resolve_character_design(proposal["payload"], selection, recent_names=recent_names)
    return _accept_design(state, design)


def _regenerate_design(feedback: str) -> Command:
    return Command(
        goto="character_design_node",
        update={
            "pending_proposal": None, "pending_proposal_decision": None,
            "character_design_feedback": feedback or "请生成不同角色方案",
        },
    )
