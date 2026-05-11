"""路由决策节点 - LLM 决定创作循环中下一步调用哪个工具"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import Command
from typing import Literal, Dict, Any
from application.schemas.agent_state import NovelAgentState

# ================ 工具注册表 ================
# 写作循环中每个节点对应一个"工具"，LLM 从中选择下一步

WRITING_TOOLS: Dict[str, Dict[str, str]] = {
    "memory_retrieval_node": {
        "description": "检索前文长期记忆。在新章节开始时调用，保证故事连贯性。",
        "when_to_call": "当需要开始创作新章节，需要回顾前文内容时",
    },
    "chapter_outline_node": {
        "description": "为当前章节生成详细细纲（场景、字数、伏笔、人物心理）。",
        "when_to_call": "当需要创作新章节但还没有细纲时",
    },
    "chapter_writer_node": {
        "description": "基于章节细纲撰写章节正文，3000-7000字。",
        "when_to_call": "当章节细纲已就绪，可以开始写正文时",
    },
    "reflection_node": {
        "description": "检查刚写完的章节质量（逻辑一致性、人物OOC、节奏等），评分低于0.8需修正。",
        "when_to_call": "当章节正文刚写完，需要质量检查时",
    },
    "revision_node": {
        "description": "根据检查发现的问题修正章节内容。",
        "when_to_call": "当质量检查发现问题需要修正时",
    },
    "persist_node": {
        "description": "将当前数据保存到数据库。",
        "when_to_call": "当有数据（章节、大纲等）需要持久化保存时",
    },
    "progress_check_node": {
        "description": "检查所有章节是否已完成，决定完结或进入下一章。",
        "when_to_call": "当数据保存完毕，需要判断是否继续创作时",
    },
}

ROUTER_SCHEMA = {
    "next_tool": "string",
    "reasoning": "string",
}


def _is_setup_phase(state: NovelAgentState) -> bool:
    """判断是否还在设定阶段（总大纲还没生成）"""
    raw = state.get("total_outline")
    if not raw:
        return True
    if isinstance(raw, str):
        return False  # 字符串说明有内容
    if isinstance(raw, dict):
        return not bool(raw)  # 空 dict = 还没生成
    return True


def _format_tools_for_prompt(tools: Dict[str, Dict[str, str]]) -> str:
    lines = []
    for name, meta in tools.items():
        lines.append(f"- {name}: {meta['description']}")
        lines.append(f"  适用场景: {meta['when_to_call']}")
    return "\n".join(lines)


async def router_agent(state: NovelAgentState, config) -> Command:
    """
    Agent 路由节点：
    - 设定阶段不会到达此节点（设定阶段走线性流程，由显式 `add_edge` 路由）
    - 写作阶段 LLM 根据当前 state 决策下一步
    """
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    current_index = state.get("current_chapter_index", 0)
    has_outline = bool(state.get("total_outline"))

    logger.info(f"{'='*60}")
    logger.info(f"【路由节点】进入 | 阶段={'设定' if not has_outline else '写作'}, "
                f"书名={title}, 当前章节={current_index + 1}")

    # ========== 安全兜底 ==========
    # 正常流程下 router_agent 只会在写作阶段被到达（has_outline=True）
    # 如果 state 异常导致无大纲就到达了这里，路由到 outline_node 修复
    if not has_outline:
        logger.info(f"【路由节点】⚠️ 异常状态：无总大纲但到达路由节点 -> outline_node")
        logger.info(f"{'='*60}")
        return Command(goto="outline_node")

    # ========== 写作阶段 ==========
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if not llm:
        # LLM 不可用时：走默认路径（persist → progress_check → continue 循环）
        logger.info(f"【路由节点】LLM不可用 -> progress_check_node")
        logger.info(f"{'='*60}")
        return Command(goto="progress_check_node", update={"phase": "writing", "graph_version": "v2"})

    # ========== 强制记忆检索守卫 ==========
    # 当已有前文（current_index > 0）但 memory_context 为空时，强制先检索记忆再进入细纲生成
    # 注意: 不依赖 completed_chapters（因其为 reducer channel，checkpoint 恢复后可能为空）
    if current_index > 0 and not state.get("memory_context"):
        logger.info(f"【路由节点】memory_context 为空，第 {current_index+1} 章需前文记忆，强制 -> memory_retrieval_node")
        logger.info(f"{'='*60}")
        return Command(
            goto="memory_retrieval_node",
            update={
                "phase": "writing",
                "graph_version": "v2",
                "next_tool": "memory_retrieval_node",
                "router_reasoning": f"第 {current_index+1} 章但 memory_context 为空，强制检索前文记忆",
            }
        )

    # 构建当前状态摘要
    # 注意: 使用 current_index 而非 completed_chapters 长度来计算完成数,
    # 因为 completed_chapters 是 Annotated[List, add] 累计的, 删除 DB 章节后
    # 该列表不会自动减少, 会导致章节计数偏差。
    has_content = bool(state.get("current_chapter_content"))
    has_issues = bool(state.get("reflection_issues"))
    has_chapter_outline = (
        len(state.get("chapter_outlines", [])) > current_index
    )
    chapter_count = current_index

    has_memory = bool(state.get("memory_context"))
    state_summary = (
        f"小说类型: {novel_type}\n"
        f"当前章节索引: {current_index + 1}\n"
        f"已完成章节数: {chapter_count}\n"
        f"已有章节细纲: {'是' if has_chapter_outline else '否'}\n"
        f"已有章节正文: {'是' if has_content else '否'}\n"
        f"有待处理问题: {'是' if has_issues else '否'}\n"
        f"已有前文记忆: {'是' if has_memory else '否'}\n"
    )

    decision = await llm.structured_generate(
        prompt=f"""你是一个小说创作工作流的智能路由决策者。你的任务是根据当前创作状态，
从可用工具中选择下一步最合理的工具。

当前创作状态：
{state_summary}

可用工具（每次选一个）：
{_format_tools_for_prompt(WRITING_TOOLS)}

选择规则：
0. 【强制】如果已完成章节 > 0 且 memory_context 为空 → 必须选择 memory_retrieval_node
1. 如果已有章节正文但未做质量检查 → 选择 reflection_node
2. 如果质量检查发现问题 → 选择 revision_node
3. 如果章节数据就绪需要保存 → 选择 persist_node
4. 如果数据已保存需要判断是否继续 → 选择 progress_check_node
5. 如果需要创作新章节但无细纲 → 选择 chapter_outline_node
6. 如果新章节细纲已就绪 → 选择 chapter_writer_node
7. 如果需要回顾前文记忆 → 选择 memory_retrieval_node

输出 JSON 格式：
{{"next_tool": "工具名", "reasoning": "选择此工具的简要原因"}}
""",
        schema=ROUTER_SCHEMA
    )

    next_tool = decision.get("next_tool", "progress_check_node")
    reasoning = decision.get("reasoning", "")

    logger.info(f"【路由节点】LLM 决策: {reasoning} -> {next_tool}")
    logger.info(f"{'='*60}")

    return Command(
        goto=next_tool,
        update={
            "phase": "writing",
            "graph_version": "v2",
            "next_tool": next_tool,
            "router_reasoning": reasoning,
        }
    )
