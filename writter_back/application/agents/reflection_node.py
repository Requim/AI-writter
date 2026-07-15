"""反思检查节点 - 检查逻辑问题，报告给用户，由用户决策"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from application.prompts.reflection_prompts import (
    build_reflection_prompt,
    build_chunk_reflection_prompt,
    build_aggregation_prompt,
    split_into_chunks,
    REFLECTION_SCHEMA,
    CHUNK_REFLECTION_SCHEMA,
    AGGREGATION_SCHEMA,
)


async def reflection_node(state: NovelAgentState, config) -> Command[Literal["persist_node", "revision_node"]]:
    """
    反思检查节点 - 检查逻辑问题，报告给用户，由用户决策如何修正
    """
    current_chapter_content = state.get("current_chapter_content", "")
    chapter_outline = state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
    total_outline_raw = state.get("total_outline", {})
    if isinstance(total_outline_raw, str):
        import json
        try:
            total_outline_raw = json.loads(total_outline_raw)
        except Exception:
            total_outline_raw = {}
    total_outline = total_outline_raw if isinstance(total_outline_raw, dict) else {}
    memory_context = state.get("memory_context", "")

    chapter_title = chapter_outline.get('title', '未知')
    content_len = len(current_chapter_content)
    logger.info(f"{'='*60}")
    logger.info(f"【反思检查节点】进入 | 章节标题={chapter_title}, 内容长度={content_len}字")

    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if not llm:
        logger.info("【反思检查节点】LLM不可用，跳过检查 -> 持久化节点")
        logger.info(f"{'='*60}")
        return Command(goto="persist_node")

    # AI 进行反思检查（分块 + 聚合）
    content_len = len(current_chapter_content)
    main_chars = total_outline.get('main_characters', [])

    if content_len > 2500:
        # ----- 分块检查 -----
        chunks = split_into_chunks(current_chapter_content)
        logger.info(f"【反思检查节点】分块检查 | {len(chunks)}块, 每块{2000}字, 重叠{200}字")

        chunk_results = []
        for chunk in chunks:
            chunk_prompt = build_chunk_reflection_prompt(
                chunk_text=chunk["text"],
                chunk_index=chunk["chunk_index"],
                total_chunks=len(chunks),
                chunk_start=chunk["start"],
                chunk_end=chunk["end"],
                chapter_outline=chapter_outline,
                main_characters=main_chars,
                memory_context=memory_context,
            )
            chunk_result = await llm.structured_generate(
                prompt=chunk_prompt,
                schema=CHUNK_REFLECTION_SCHEMA,
                temperature=0.1,
            )
            chunk_issues = chunk_result.get("issues", []) if chunk_result else []
            # 标记每个 issue 出自哪一块
            for iss in chunk_issues:
                iss["_chunk"] = chunk["chunk_index"]
                iss["_chunk_range"] = f"{chunk['start']}-{chunk['end']}"
            chunk_results.append({
                "start": chunk["start"],
                "end": chunk["end"],
                "chunk_index": chunk["chunk_index"],
                "issues": chunk_issues,
            })
            logger.info(f"【反思检查节点】块{chunk['chunk_index']+1}/{len(chunks)} 检查完成 | 发现{len(chunk_issues)}个问题")

        # ----- 聚合检查 -----
        agg_prompt = build_aggregation_prompt(
            chunk_results=chunk_results,
            chapter_outline=chapter_outline,
            main_characters=main_chars,
            memory_context=memory_context,
            content_length=content_len,
        )
        reflection_result = await llm.structured_generate(
            prompt=agg_prompt,
            schema=AGGREGATION_SCHEMA,
            temperature=0.1,
        )

        # 合并：聚合结果中的 issues + 所有分块中的 issues
        all_issues = reflection_result.get("issues", []) if reflection_result else []
        seen_locations = set()
        for iss in all_issues:
            loc = iss.get("location", "")
            if loc:
                seen_locations.add(loc)
        for cr in chunk_results:
            for iss in cr.get("issues", []):
                loc = iss.get("location", "")
                if loc not in seen_locations:
                    all_issues.append(iss)
                    seen_locations.add(loc)
        reflection_result["issues"] = all_issues
        logger.info(f"【反思检查节点】聚合完成 | 总计{len(all_issues)}个问题")
    else:
        # 短章节：单次检查即可
        reflection_prompt = build_reflection_prompt(
            chapter_content=current_chapter_content,
            chapter_outline=chapter_outline,
            main_characters=main_chars,
            memory_context=memory_context,
            content_length=content_len,
        )
        reflection_result = await llm.structured_generate(
            prompt=reflection_prompt,
            schema=REFLECTION_SCHEMA,
            temperature=0.1,
        )

    # 解析结构化输出
    quality_score = reflection_result.get("overall_quality_score", 0)
    word_analysis = reflection_result.get("word_count_analysis", {})
    effective_density = word_analysis.get("effective_density", 100)
    is_valid_words = word_analysis.get("is_valid_word_count", True)
    logic_chain_status = reflection_result.get("logic_chain_status", "")
    foreshadowing_check = reflection_result.get("foreshadowing_check", "")

    # 检查通过条件：passed + 质量分>=0.8 + 字数合规 + 有效密度>=70%
    passed = reflection_result.get("passed", False)
    density_ok = effective_density >= 70
    quality_ok = quality_score >= 0.8
    emit_workflow_event(
        "quality",
        {
            "score": quality_score,
            "issues": reflection_result.get("issues", []),
            "attempt": state.get("revision_attempts", 0),
            "max_attempts": config["configurable"].get("max_reflection_loops", 5),
        },
        "reflection_node",
    )

    if passed and quality_ok and is_valid_words and density_ok:
        logger.info(f"【反思检查节点】检查通过! 质量评分={quality_score}, "
                    f"有效密度={effective_density}%, 字数合格={is_valid_words} -> 持久化节点")
        logger.info(f"{'='*60}")
        return Command(goto="persist_node")

    # 检查未通过，向用户报告问题
    issues = reflection_result.get("issues", [])
    # 确保每个 issue 有 priority_action 和 issue_resolved 字段
    for issue in issues:
        if "priority_action" not in issue:
            sev = issue.get("severity", "low")
            issue["priority_action"] = {"high": "must_fix", "medium": "optional", "low": "can_ignore"}.get(sev, "optional")
        if "issue_resolved" not in issue:
            issue["issue_resolved"] = False
    fail_reasons = []
    if not quality_ok:
        fail_reasons.append(f"质量评分不足({quality_score}<0.8)")
    if not density_ok:
        fail_reasons.append(f"有效密度不足({effective_density}%<70%)")
    if not is_valid_words:
        fail_reasons.append("字数不合规")
    if not passed:
        fail_reasons.append("LLM判定未通过")
    logger.info(f"【反思检查节点】检查未通过! {'; '.join(fail_reasons)}, "
                f"问题数={len(issues)} -> 修正节点")

    # 自动模式：发现问题时自动走 AI 修正（动态收敛循环）
    auto_mode = config["configurable"].get("auto_mode", False)
    if auto_mode:
        attempts = state.get("revision_attempts", 0)
        MAX_REVISION_ATTEMPTS = 5  # 上限放大到 5 次

        # 提前收敛条件：高优问题全部解决且质量分 > 0.85
        has_high_unresolved = any(
            issue.get("priority_action") == "must_fix" and not issue.get("issue_resolved", False)
            for issue in issues
        )
        if not has_high_unresolved and quality_score > 0.85:
            logger.info(f"【反思检查节点】自动模式 | 高优问题已全部解决且质量分>{quality_score}>0.85，提前通过 -> 持久化节点")
            return Command(goto="persist_node")

        if attempts >= MAX_REVISION_ATTEMPTS:
            logger.info(f"【反思检查节点】自动模式 | 已修正{attempts}次仍未通过，降级放行 -> 持久化节点")
            return Command(goto="persist_node")
        logger.info(f"【反思检查节点】自动模式 | 走AI自动修正 (第{attempts + 1}次, 上限{MAX_REVISION_ATTEMPTS}次)")
        return Command(
            goto="revision_node",
            update={
                "reflection_issues": issues,
                "user_decision": {
                    "action": "revise",
                    "instructions": None  # AI 根据问题列表自动修正
                }
            }
        )

    user_decision = interrupt({
        "action": "review_reflection_issues",
        "message": "章节内容检查发现问题，请审阅并决定修正方式",
        "chapter_number": state.get("current_chapter_index", 0) + 1,
        "quality_score": quality_score,
        "word_count_analysis": word_analysis,
        "issues": issues,
        "chapter_content_preview": current_chapter_content[:500] + "...",
        "logic_chain_status": logic_chain_status,
        "foreshadowing_check": foreshadowing_check,
        "note": "请选择处理方式：\n"
               "1) 'accept' - 忽略问题，直接使用\n"
               "2) 'revise' - 根据问题列表自动修正\n"
               "3) 提供具体修正指令（字符串）- 按您的指示修正\n"
               "4) 'regenerate' - 重新生成本章内容"
    })

    logger.info("【反思检查节点】准备前往 -> 修正节点 (等待用户决策)")

    # 解析用户决策
    if user_decision == "accept":
        decision_action = "accept"
        decision_instructions = None
    elif user_decision == "regenerate":
        decision_action = "regenerate"
        decision_instructions = None
    elif user_decision == "revise":
        decision_action = "revise"
        decision_instructions = None  # AI 根据问题列表自动修正
    elif isinstance(user_decision, str) and user_decision.strip():
        decision_action = "revise"
        decision_instructions = user_decision  # 用户提供的自定义修正指令
    else:
        decision_action = "revise"
        decision_instructions = None

    return Command(
        goto="revision_node",
        update={
            "reflection_issues": issues,
            "user_decision": {
                "action": decision_action,
                "instructions": decision_instructions
            }
        }
    )
