"""Generate the bounded macro outline before the per-chapter loop."""

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from application.prompts.outline_prompts import (
    OUTLINE_SCHEMA,
    build_outline_prompt,
    validate_outline,
)
from application.schemas.agent_state import NovelAgentState

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


async def outline_generator_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["persist_node", "outline_node"]]:
    """Generate global constraints and volumes, never all chapter plans at once."""
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    summary = state.get("summary", "")
    target_total_chapters = state.get("target_total_chapters")
    requested_writing_style = state.get("requested_writing_style")
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
        prompt=build_outline_prompt(
            novel_type,
            title,
            summary,
            target_total_chapters=target_total_chapters,
            requested_writing_style=requested_writing_style,
        ),
        schema=OUTLINE_SCHEMA,
        temperature=0.75,
        top_p=0.9,
    )
    if not ai_outline:
        raise RuntimeError("宏观总纲生成失败：模型未返回有效 JSON")

    # Enforce the contract even when a compatible provider adds extra fields.
    ai_outline.pop("chapters", None)
    ai_outline = apply_creation_constraints(
        ai_outline,
        target_total_chapters=target_total_chapters,
        requested_writing_style=requested_writing_style,
    )
    if title:
        ai_outline["source_title"] = title
    if summary:
        ai_outline["source_summary"] = summary
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
