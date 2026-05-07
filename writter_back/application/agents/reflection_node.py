"""反思检查节点 - 检查逻辑问题，报告给用户，由用户决策"""
from langgraph.types import interrupt, Command
from typing import Literal
import json
from application.schemas.agent_state import NovelAgentState
from application.prompts.reflection_prompts import build_reflection_prompt, REFLECTION_SCHEMA


async def reflection_node(state: NovelAgentState, config) -> Command[Literal["persist_node", "revision_node"]]:
    """
    反思检查节点 - 检查逻辑问题，报告给用户，由用户决策如何修正
    """
    current_chapter_content = state.get("current_chapter_content", "")
    chapter_outline = state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
    total_outline = state.get("total_outline", {})
    memory_context = state.get("memory_context", "")
    
    chapter_title = chapter_outline.get('title', '未知')
    content_len = len(current_chapter_content)
    print(f"{'='*60}", flush=True)
    print(f"【反思检查节点】进入 | 章节标题={chapter_title}, 内容长度={content_len}字", flush=True)
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【反思检查节点】LLM不可用，跳过检查 -> 持久化节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="persist_node")
    
    # AI 进行反思检查
    reflection_prompt = build_reflection_prompt(
        chapter_content=current_chapter_content,
        chapter_outline=chapter_outline,
        main_characters=total_outline.get('main_characters', []),
        memory_context=memory_context,
        content_length=len(current_chapter_content),
    )

    reflection_result = await llm.structured_generate(
        prompt=reflection_prompt,
        schema=REFLECTION_SCHEMA
    )
    
    # 检查通过（质量分数>=0.8 且 字数合格）
    quality_score = reflection_result.get("overall_quality_score", 0)
    is_valid_words = reflection_result.get("is_valid_word_count", True)
    
    if reflection_result.get("passed") and quality_score >= 0.8 and is_valid_words:
        print(f"【反思检查节点】检查通过! 质量评分={quality_score}, 字数合格={is_valid_words} -> 持久化节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="persist_node")
    
    # 检查未通过，向用户报告问题
    issues = reflection_result.get("issues", [])
    print(f"【反思检查节点】检查未通过! 质量评分={quality_score}, 问题数={len(issues)} -> 修正节点 (等待用户决策)", flush=True)
    
    user_decision = interrupt({
        "action": "review_reflection_issues",
        "message": f"章节内容检查发现问题，请审阅并决定修正方式",
        "chapter_number": state.get("current_chapter_index", 0) + 1,
        "quality_score": quality_score,
        "word_count": reflection_result.get("word_count", 0),
        "issues": issues,
        "chapter_content_preview": current_chapter_content[:500] + "...",
        "note": "请选择处理方式：\n"
               "1) 'accept' - 忽略问题，直接使用\n"
               "2) 'revise' - 根据问题列表自动修正\n"
               "3) 提供具体修正指令（字符串）- 按您的指示修正\n"
               "4) 'regenerate' - 重新生成本章内容"
    })
    
    print(f"【反思检查节点】准备前往 -> 修正节点 (等待用户决策)", flush=True)
    
    return Command(
        goto="revision_node",
        update={
            "reflection_issues": issues,
            "user_decision": {
                "action": user_decision if isinstance(user_decision, str) else "revise",
                "instructions": user_decision if isinstance(user_decision, str) else None
            }
        }
    )
