"""修正节点 - 根据用户决策或AI自动修正"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.revision_prompts import (
    build_user_instruction_revision_prompt,
    build_auto_fix_revision_prompt,
    build_expansion_prompt,
    format_issues_for_prompt,
    build_revision_system_prompt,
    REVISION_TEMPERATURE,
)


async def revision_node(state: NovelAgentState, config) -> Command[Literal["chapter_writer_node", "persist_node"]]:
    """
    修正节点 - 根据用户决策或AI自动修正
    用户决策优先，否则AI根据问题列表自动修正
    """
    current_content = state.get("current_chapter_content", "")
    chapter_outline = (
        state.get("chapter_outlines", [{}])[-1]
        if state.get("chapter_outlines") else {}
    )
    user_decision = state.get("user_decision", {})
    action = user_decision.get("action", "revise")
    instructions = user_decision.get("instructions")
    issues = state.get("reflection_issues", [])

    action_label = {'accept': '接受(忽略问题)', 'regenerate': '重新生成', 'revise': '修正'}.get(action, action)
    logger.info(f"{'='*60}")
    logger.info(f"【修正节点】进入 | 决策={action_label}, 问题数={len(issues)}")

    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if action == "accept":
        logger.info(f"【修正节点】用户选择忽略问题 -> 持久化节点")
        logger.info(f"{'='*60}")
        return Command(goto="persist_node")

    elif action == "regenerate":
        logger.info(f"【修正节点】用户要求重新生成 -> 章节写作节点")
        logger.info(f"{'='*60}")
        return Command(goto="chapter_writer_node")

    else:
        # 有修正指令（用户决策优先）或AI自动修正
        # 注意：两个 prompt 现在都接收完整的 chapter_outline 字典
        if instructions:
            revision_prompt = build_user_instruction_revision_prompt(
                instructions=instructions,
                current_content=current_content,
                chapter_outline=chapter_outline,
            )
        else:
            revision_prompt = build_auto_fix_revision_prompt(
                issues_text=format_issues_for_prompt(issues),
                current_content=current_content,
                chapter_outline=chapter_outline,
            )

        if llm:
            logger.info(f"【修正节点】正在{'按用户指令' if instructions else 'AI自动'}修正内容...")
            revised_content = await llm.generate(
                revision_prompt,
                system_prompt=build_revision_system_prompt(),
                temperature=REVISION_TEMPERATURE
            )
            original_len = len(current_content)
            revised_len = len(revised_content)
            logger.info(f"【修正节点】修正完成 | 原长度={original_len}字, 修正后={revised_len}字")

            # 字数缩减超过 20% 时，自动触发扩写
            if revised_len < original_len * 0.8:
                logger.info(f"【修正节点】⚠️ 字数缩减超过20% ({original_len}→{revised_len})，正在自动扩充细节...")
                target = min(original_len, 7000)
                expansion_prompt = build_expansion_prompt(
                    current_content=revised_content,
                    chapter_outline=chapter_outline,
                    target_words=target,
                )
                revised_content = await llm.generate(
                    expansion_prompt,
                    system_prompt=build_revision_system_prompt(),
                    temperature=REVISION_TEMPERATURE + 0.1
                )
                logger.info(f"【修正节点】扩充后字数: {len(revised_content)}字")
        else:
            logger.info(f"【修正节点】LLM不可用，保留原内容")
            revised_content = current_content

        # 修正后再次暂停，让用户确认修正结果
        user_confirmation = interrupt({
            "action": "confirm_revision",
            "message": "内容已修正，请确认是否满意",
            "chapter_number": state.get("current_chapter_index", 0) + 1,
            "revised_content_preview": revised_content[:500] + "...",
            "note": "您可以：1) 接受修正（回复'accept'）2) 继续修改（提供新的修正指令）3) 重新生成（回复'regenerate'）"
        })

        if user_confirmation == "accept":
            logger.info(f"【修正节点】用户确认修正结果 -> 持久化节点")
            logger.info(f"{'='*60}")
            return Command(
                goto="persist_node",
                update={"current_chapter_content": revised_content}
            )
        elif user_confirmation == "regenerate":
            logger.info(f"【修正节点】用户要求重新生成 -> 章节写作节点")
            logger.info(f"{'='*60}")
            return Command(goto="chapter_writer_node")
        else:
            logger.info(f"【修正节点】用户提供了新的修正指令，继续修正")
            return Command(
                goto="revision_node",
                update={
                    "user_decision": {"action": "revise", "instructions": user_confirmation}
                }
            )
