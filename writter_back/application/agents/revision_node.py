"""修正节点 - 根据用户决策或AI自动修正"""

import logging

logger = logging.getLogger("uvicorn")
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.continuity import build_story_bible
from application.streaming import collect_streamed_text, emit_workflow_event
from application.prompts.revision_prompts import (
    build_user_instruction_revision_prompt,
    build_patch_revision_prompt,
    build_refactor_revision_prompt,
    build_expansion_prompt,
    format_issues_for_prompt,
    classify_revision_mode,
    build_revision_system_prompt,
    PATCH_TEMPERATURE,
    REFACTOR_TEMPERATURE,
)


async def revision_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[
    Literal[
        "chapter_writer_node",
        "persist_node",
        "reflection_node",
        "revision_node",
    ]
]:
    """
    修正节点 - 根据用户决策或AI自动修正
    用户决策优先，否则AI根据问题列表自动修正
    """
    current_content = state.get("current_chapter_content", "")
    chapter_outline = (
        state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
    )
    user_decision = state.get("user_decision", {})
    action = user_decision.get("action", "revise")
    instructions = user_decision.get("instructions")
    issues = state.get("reflection_issues", [])
    memory_context = state.get("memory_context", "")
    total_outline_raw = state.get("total_outline", {})
    total_outline = total_outline_raw if isinstance(total_outline_raw, dict) else {}
    story_bible = build_story_bible(total_outline)

    action_label = {
        "accept": "接受(忽略问题)",
        "regenerate": "重新生成",
        "revise": "修正",
    }.get(action, action)
    logger.info(f"{'=' * 60}")
    logger.info(f"【修正节点】进入 | 决策={action_label}, 问题数={len(issues)}")

    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if action == "accept":
        logger.info("【修正节点】用户选择忽略问题 -> 持久化节点")
        logger.info(f"{'=' * 60}")
        return Command(goto="persist_node")

    elif action == "regenerate":
        logger.info("【修正节点】用户要求重新生成 -> 章节写作节点")
        logger.info(f"{'=' * 60}")
        return Command(goto="chapter_writer_node")

    else:
        # 有修正指令（用户决策优先）或AI自动修正
        # 注意：两个 prompt 现在都接收完整的 chapter_outline 字典
        if instructions:
            revision_prompt = build_user_instruction_revision_prompt(
                instructions=instructions,
                current_content=current_content,
                chapter_outline=chapter_outline,
                continuity_context=memory_context,
                story_bible=story_bible,
            )
            temperature = 0.5
            mode = "user_instruction"
        else:
            # 构建修正历史文本（供 prompt 参考）
            revision_history = state.get("revision_history", [])
            history_text = ""
            if revision_history:
                history_parts = []
                for h_entry in revision_history:
                    att = h_entry.get("attempt", 0)
                    iss = h_entry.get("issues_before", [])
                    iss_summary = "; ".join(
                        [
                            f"{i.get('type', '?')}({i.get('priority_action', '?')})"
                            for i in iss[:5]
                        ]
                    )
                    history_parts.append(f"第{att}次修正处理: {iss_summary}")
                history_text = "\n".join(history_parts)

            # 根据问题类型判断修正模式
            mode = classify_revision_mode(issues)
            if mode == "patch":
                revision_prompt = build_patch_revision_prompt(
                    issues_text=format_issues_for_prompt(issues),
                    current_content=current_content,
                    chapter_outline=chapter_outline,
                    revision_history=history_text,
                    continuity_context=memory_context,
                    story_bible=story_bible,
                )
                temperature = PATCH_TEMPERATURE
            else:
                revision_prompt = build_refactor_revision_prompt(
                    issues_text=format_issues_for_prompt(issues),
                    current_content=current_content,
                    chapter_outline=chapter_outline,
                    revision_history=history_text,
                    continuity_context=memory_context,
                    story_bible=story_bible,
                )
                temperature = REFACTOR_TEMPERATURE

        if llm:
            mode_label = {
                "patch": "Patch局部修正",
                "refactor": "Refactor全文重构",
                "user_instruction": "用户指令修正",
            }.get(mode, mode)
            logger.info(
                f"【修正节点】正在{'按用户指令' if instructions else 'AI自动'}修正内容... 模式={mode_label}, temperature={temperature}"
            )
            chapter_index = state.get("current_chapter_index", 0)
            emit_workflow_event(
                "content_delta",
                {"chapter_index": chapter_index, "operation": "reset", "text": ""},
                "revision_node",
            )
            revised_content = await collect_streamed_text(
                llm,
                revision_prompt,
                node="revision_node",
                chapter_index=chapter_index,
                system_prompt=build_revision_system_prompt(),
                temperature=temperature,
            )
            if not revised_content.strip():
                raise RuntimeError("章节修订失败：模型未返回正文")
            original_len = len(current_content)
            revised_len = len(revised_content)
            logger.info(
                f"【修正节点】修正完成 | 原长度={original_len}字, 修正后={revised_len}字"
            )

            # 字数缩减超过 20% 时，自动触发扩写
            if revised_len < original_len * 0.8:
                logger.info(
                    f"【修正节点】⚠️ 字数缩减超过20% ({original_len}→{revised_len})，正在自动扩充细节..."
                )
                target = min(original_len, 7000)
                expansion_prompt = build_expansion_prompt(
                    current_content=revised_content,
                    chapter_outline=chapter_outline,
                    target_words=target,
                    continuity_context=memory_context,
                    story_bible=story_bible,
                )
                emit_workflow_event(
                    "content_delta",
                    {"chapter_index": chapter_index, "operation": "reset", "text": ""},
                    "revision_node",
                )
                revised_content = await collect_streamed_text(
                    llm,
                    expansion_prompt,
                    node="revision_node",
                    chapter_index=chapter_index,
                    system_prompt=build_revision_system_prompt(),
                    temperature=REFACTOR_TEMPERATURE + 0.1,
                )
                if not revised_content.strip():
                    raise RuntimeError("章节修订扩写失败：模型未返回正文")
                logger.info(f"【修正节点】扩充后字数: {len(revised_content)}字")
        else:
            logger.info("【修正节点】LLM不可用，保留原内容")
            revised_content = current_content

        # 自动模式：修正后走回 reflection_node 再次检查（循环修正）
        auto_mode = config["configurable"].get("auto_mode", False)
        if auto_mode:
            attempts = state.get("revision_attempts", 0)
            # 记录本轮修正历史
            revision_history = state.get("revision_history", [])
            revision_history = revision_history + [
                {
                    "attempt": attempts + 1,
                    "issues_before": issues,
                }
            ]
            logger.info(
                f"【修正节点】自动模式 | 修正完成 -> 反思节点复查 (第{attempts + 1}次修正)"
            )
            logger.info(f"{'=' * 60}")
            return Command(
                goto="reflection_node",
                update={
                    "current_chapter_content": revised_content,
                    "revision_attempts": attempts + 1,
                    "revision_history": revision_history,
                },
            )

        # 修正后再次暂停，让用户确认修正结果
        user_confirmation = interrupt(
            {
                "action": "confirm_revision",
                "message": "内容已修正，请确认是否满意",
                "chapter_number": state.get("current_chapter_index", 0) + 1,
                "revised_content_preview": revised_content[:500] + "...",
                "note": "您可以：1) 接受修正（回复'accept'）2) 继续修改（提供新的修正指令）3) 重新生成（回复'regenerate'）",
            }
        )

        if user_confirmation == "accept":
            logger.info("【修正节点】用户确认修正结果 -> 持久化节点")
            logger.info(f"{'=' * 60}")
            return Command(
                goto="persist_node", update={"current_chapter_content": revised_content}
            )
        elif user_confirmation == "regenerate":
            logger.info("【修正节点】用户要求重新生成 -> 章节写作节点")
            logger.info(f"{'=' * 60}")
            return Command(goto="chapter_writer_node")
        else:
            logger.info("【修正节点】用户提供了新的修正指令，继续修正")
            return Command(
                goto="revision_node",
                update={
                    "user_decision": {
                        "action": "revise",
                        "instructions": user_confirmation,
                    }
                },
            )
