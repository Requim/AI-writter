"""Generate the bounded macro outline before the per-chapter loop."""

import logging
from typing import Literal

from langgraph.types import Command, interrupt

from application.prompts.outline_prompts import (
    OUTLINE_SCHEMA,
    build_outline_prompt,
    validate_outline,
)
from application.schemas.agent_state import NovelAgentState

logger = logging.getLogger("uvicorn")


async def outline_generator_node(
    state: NovelAgentState,
    config,
) -> Command[Literal["persist_node"]]:
    """Generate global constraints and volumes, never all chapter plans at once."""
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    summary = state.get("summary", "")
    existing = state.get("total_outline")

    logger.info("%s", "=" * 60)
    logger.info(
        "【宏观总纲节点】进入 | 书名=%s, 已有总纲=%s",
        title,
        "是" if isinstance(existing, dict) and existing else "否",
    )
    if isinstance(existing, dict) and existing:
        logger.info("【宏观总纲节点】跳过 | 使用已有总纲")
        return Command(goto="persist_node", update={"__next_node__": "progress_check_node"})

    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("宏观总纲生成失败：LLM 不可用")

    ai_outline = await llm.structured_generate(
        prompt=build_outline_prompt(novel_type, title, summary),
        schema=OUTLINE_SCHEMA,
        temperature=0.75,
        top_p=0.9,
    )
    if not ai_outline:
        raise RuntimeError("宏观总纲生成失败：模型未返回有效 JSON")

    # Enforce the contract even when a compatible provider adds extra fields.
    ai_outline.pop("chapters", None)
    try:
        ai_outline["total_chapters"] = int(ai_outline.get("total_chapters", 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("宏观总纲生成失败：total_chapters 无效") from exc

    validation = validate_outline(ai_outline)
    if not validation["valid"]:
        details = "；".join(validation["fatal_issues"][:3])
        raise RuntimeError(f"宏观总纲生成失败：{details}")

    logger.info(
        "【宏观总纲节点】完成 | 角色=%s, 卷=%s, 总章节=%s, 提示=%s",
        len(ai_outline.get("main_characters", [])),
        len(ai_outline.get("volumes", [])),
        ai_outline.get("total_chapters"),
        len(validation["issues"]),
    )

    if config["configurable"].get("auto_mode", False):
        return Command(
            goto="persist_node",
            update={"total_outline": ai_outline, "__next_node__": "progress_check_node"},
        )

    user_decision = interrupt(
        {
            "action": "review_or_modify_outline",
            "message": "AI已生成宏观总纲，请审阅后进入逐章创作",
            "ai_generated_outline": ai_outline,
            "validation": validation,
            "note": "回复 accept 使用，回复 regenerate 重做，或提交自定义宏观总纲。",
        }
    )
    if user_decision == "regenerate":
        return Command(goto="outline_node")
    selected = ai_outline if user_decision == "accept" else user_decision
    if not isinstance(selected, dict):
        raise RuntimeError("宏观总纲生成失败：用户提交的总纲格式无效")
    selected.pop("chapters", None)
    return Command(
        goto="persist_node",
        update={"total_outline": selected, "__next_node__": "progress_check_node"},
    )
