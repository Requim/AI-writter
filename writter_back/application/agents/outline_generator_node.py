"""总纲领生成节点

策略：单次生成为主，截断时自动降级为两阶段
  Phase 1 (primary): 单次调用生成完整大纲（含章节）
                     → 若 total_chapters == len(chapters) 则直接使用
  Phase 2 (fallback): 若截断（章节数不匹配），
                     先重出宏观总纲（无章节），再单独生成 chapters
"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt, Command
from typing import Literal, Dict, Any
from application.schemas.agent_state import NovelAgentState
from application.prompts.outline_prompts import (
    build_outline_prompt,
    build_chapters_only_prompt,
    OUTLINE_SCHEMA,
    MACRO_ONLY_SCHEMA,
    CHAPTERS_ONLY_SCHEMA,
    validate_outline,
    detect_truncation,
)


async def outline_generator_node(state: NovelAgentState, config) -> Command[Literal["persist_node"]]:
    """
    总纲领节点 - 用户输入优先，否则 AI 生成。
    单次生成 → 检测截断 → 降级两阶段 → 校验 → 中断审阅。
    """
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    summary = state.get("summary", "")
    has_outline = 'total_outline' in state and isinstance(state.get('total_outline'), dict)
    logger.info(f"{'='*60}")
    logger.info(f"【总大纲生成节点】进入 | 书名={title}, 已有大纲={'是' if has_outline else '否'}")

    # 用户已提供总纲领，直接使用
    if isinstance(state.get("total_outline"), dict):
        logger.info(f"【总大纲生成节点】跳过 | 使用已有大纲")
        logger.info(f"{'='*60}")
        return Command(goto="persist_node", update={"__next_node__": "progress_check_node"})

    # 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if not llm:
        logger.info(f"【总大纲生成节点】LLM不可用，跳过")
        logger.info(f"{'='*60}")
        return Command(goto="persist_node", update={"__next_node__": "progress_check_node"})

    # ==================== Phase 1: 单次生成完整大纲 ====================
    logger.info(f"【总大纲生成节点】Phase 1: 单次生成完整大纲...")
    prompt = build_outline_prompt(novel_type, title, summary)
    ai_outline = await llm.structured_generate(prompt=prompt, schema=OUTLINE_SCHEMA, temperature=0.85, top_p=0.92)

    if not ai_outline:
        logger.info(f"【总大纲生成节点】Phase 1 返回空，使用空大纲兜底")
        ai_outline = _empty_outline()

    # 检测截断
    truncation_issues = detect_truncation(ai_outline)
    chapters = ai_outline.get("chapters", [])
    total = ai_outline.get("total_chapters", 0)
    is_truncated = total > 0 and len(chapters) < total

    logger.info(f"【总大纲生成节点】Phase 1 完成 | "
                f"角色={len(ai_outline.get('main_characters', []))}个, "
                f"卷={len(ai_outline.get('volumes', []))}卷, "
                f"章节={len(chapters)}/{total}章, "
                f"截断={'⚠️ 是' if is_truncated else '否'}")

    # ==================== Phase 2 (fallback): 截断降级 ====================
    if is_truncated:
        logger.info(f"【总大纲生成节点】检测到截断，降级到两阶段生成...")

        # 从 Phase 1 结果中提取宏观字段
        macro_outline = _extract_macro(ai_outline)

        # 如果宏观信息不足，重新生成
        if not macro_outline.get("story_background") or len(macro_outline.get("main_characters", [])) < 3:
            logger.info(f"【总大纲生成节点】宏观信息不足，重新生成宏观总纲...")
            macro_outline = await llm.structured_generate(
                prompt=build_outline_prompt(novel_type, title, summary),
                schema=MACRO_ONLY_SCHEMA,
                temperature=0.85, top_p=0.92,
            )
            if not macro_outline:
                macro_outline = _empty_macro()

        # 用宏观总纲生成完整章节
        logger.info(f"【总大纲生成节点】Phase 2: 基于宏观总纲生成章节...")
        chapters_prompt = build_chapters_only_prompt(novel_type, title, summary, macro_outline)
        chapters_result = await llm.structured_generate(
            prompt=chapters_prompt,
            schema=CHAPTERS_ONLY_SCHEMA,
            temperature=0.85, top_p=0.92,
        )

        fallback_chapters = chapters_result.get("chapters", []) if chapters_result else []
        logger.info(f"【总大纲生成节点】Phase 2 完成 | 生成 {len(fallback_chapters)} 章")

        # 合并：macro_outline + chapters
        ai_outline = dict(macro_outline)
        ai_outline["chapters"] = fallback_chapters
        ai_outline["total_chapters"] = macro_outline.get("total_chapters", len(fallback_chapters))

    # ==================== 校验与修复 ====================
    validation = validate_outline(ai_outline)
    if not validation["valid"]:
        logger.info(f"【总大纲生成节点】校验发现 {len(validation['issues'])} 个问题:")
        for issue in validation["issues"]:
            logger.info(f"  ⚠ {issue}")
        ai_outline = _repair_outline(ai_outline)

    logger.info(f"【总大纲生成节点】最终大纲: "
                f"角色={len(ai_outline.get('main_characters', []))}个, "
                f"卷={len(ai_outline.get('volumes', []))}卷, "
                f"章节={len(ai_outline.get('chapters', []))}/{ai_outline.get('total_chapters', 0)}章")
    logger.info(f"{'='*60}")

    # 自动模式：直接接受
    auto_mode = config["configurable"].get("auto_mode", False)
    if auto_mode:
        logger.info(f"【总大纲生成节点】自动模式 | 接受AI生成")
        logger.info(f"{'='*60}")
        return Command(
            goto="persist_node",
            update={"total_outline": ai_outline, "__next_node__": "progress_check_node"}
        )

    # ==================== 中断：用户审阅 ====================
    user_decision = interrupt({
        "action": "review_or_modify_outline",
        "message": "AI已生成总纲领，请审阅并可选择修改",
        "ai_generated_outline": ai_outline,
        "validation": {
            "valid": validation["valid"],
            "issues": validation["issues"],
        },
        "note": "您可以：1) 直接使用（回复'accept'）2) 修改后提供新的总纲领 3) 要求AI重新生成（回复'regenerate'）"
    })

    if user_decision == "accept":
        logger.info(f"【总大纲生成节点】用户接受了AI生成的大纲")
        logger.info(f"{'='*60}")
        return Command(
            goto="persist_node",
            update={"total_outline": ai_outline, "__next_node__": "progress_check_node"}
        )
    elif user_decision == "regenerate":
        logger.info(f"【总大纲生成节点】用户要求重新生成，循环回本节点")
        return Command(goto="outline_generator_node")
    else:
        logger.info(f"【总大纲生成节点】用户提供了自定义大纲")
        logger.info(f"{'='*60}")
        return Command(
            goto="persist_node",
            update={"total_outline": user_decision, "__next_node__": "progress_check_node"}
        )


# ==================== 辅助函数 ====================

def _extract_macro(outline: Dict[str, Any]) -> Dict[str, Any]:
    """从完整大纲中提取宏观字段（去掉 chapters）"""
    macro_fields = ["story_background", "main_characters", "main_plot",
                    "writing_style", "total_chapters", "volumes"]
    return {k: outline.get(k, _default_for(k)) for k in macro_fields}


def _default_for(field: str) -> Any:
    defaults = {
        "story_background": "",
        "main_characters": [],
        "main_plot": {},
        "writing_style": "",
        "total_chapters": 0,
        "volumes": [],
    }
    return defaults.get(field, "")


def _empty_outline() -> Dict[str, Any]:
    return {
        "story_background": "",
        "main_characters": [],
        "main_plot": {},
        "chapters": [],
        "writing_style": "",
        "total_chapters": 0,
        "volumes": [],
    }


def _empty_macro() -> Dict[str, Any]:
    return {
        "story_background": "",
        "main_characters": [],
        "main_plot": {},
        "writing_style": "",
        "total_chapters": 0,
        "volumes": [],
    }


def _repair_outline(outline: Dict[str, Any]) -> Dict[str, Any]:
    """修复大纲中的可自动修复问题"""
    # 修复角色数量
    chars = outline.get("main_characters", [])
    if len(chars) < 9:
        needed = 9 - len(chars)
        for _ in range(needed):
            chars.append({
                "姓名": f"待定角色{len(chars)+1}",
                "性格": "待补充",
                "目标": "待补充",
                "冲突对象": "待补充",
                "关系标签": "待补充",
            })
        outline["main_characters"] = chars

    # 修复角色字段
    required_fields = ["姓名", "性格", "目标", "冲突对象", "关系标签"]
    for c in chars:
        for f in required_fields:
            if f not in c:
                c[f] = "待补充"

    # 修复章节数量一致性
    chapters = outline.get("chapters", [])
    total = outline.get("total_chapters", 0)
    if len(chapters) < total:
        volumes = outline.get("volumes", [])
        last_vol_name = volumes[-1].get("volume_name", "末卷") if volumes else "末卷"
        for i in range(len(chapters), total):
            chapters.append({
                "chapter_number": i + 1,
                "theme": "待生成的内容",
                "key_events": ["具体事件待补充"],
                "volume_name": last_vol_name,
            })
        outline["chapters"] = chapters
    elif len(chapters) > total:
        outline["total_chapters"] = len(chapters)

    return outline
