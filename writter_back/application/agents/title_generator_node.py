"""书名生成节点 - 用户输入优先，否则AI生成"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.title_prompts import build_title_prompt, TITLE_TEMPERATURE


def _parse_title_suggestions(text: str) -> list:
    """解析 LLM 输出的 '书名 | 卖点说明' 格式，返回 [{title, hint}, ...]"""
    suggestions = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        title = hint = ""
        # 尝试按 | 分割
        if "|" in line:
            parts = line.split("|", 1)
            title = parts[0].strip()
            hint = parts[1].strip() if len(parts) > 1 else ""
        else:
            title = line.strip()
        # 清理编号前缀（如 "1. "、"1、")
        if title and (title[0].isdigit() and len(title) > 2 and title[1] in ".、）)"):
            title = title[2:].strip()
        if title and len(title) >= 4:
            suggestions.append({"title": title, "hint": hint})
    return suggestions[:10]


async def title_generator_node(state: NovelAgentState, config) -> Command[Literal["summary_node"]]:
    """
    书名节点 - 用户输入优先，否则AI生成
    如果用户未提供书名，AI自动生成后询问用户确认
    """
    novel_type = state.get("novel_type", "")
    has_title = 'title' in state and bool(state.get('title'))
    logger.info(f"{'='*60}")
    logger.info(f"【书名生成节点】进入 | 小说类型={novel_type}, 已有书名={'是' if has_title else '否'}")

    # 用户已提供书名，直接使用
    if state.get("title"):
        logger.info(f"【书名生成节点】跳过 -> persist | 使用已有书名: {state['title']}")
        logger.info(f"{'='*60}")
        return Command(goto="summary_node")

    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if not llm:
        logger.info(f"【书名生成节点】LLM不可用，跳过 -> persist")
        logger.info(f"{'='*60}")
        return Command(goto="summary_node")

    # AI 生成书名候选
    prompt = build_title_prompt(novel_type)
    ai_titles_text = await llm.generate(prompt, temperature=TITLE_TEMPERATURE)
    ai_titles = _parse_title_suggestions(ai_titles_text)
    logger.info(f"【书名生成节点】AI生成了 {len(ai_titles)} 个书名候选: {ai_titles}")

    ai_suggestions_list = ai_titles  # [{title, hint}, ...]

    if not ai_suggestions_list:
        logger.info(f"【书名生成节点】未解析到有效书名，使用默认")
        ai_suggestions_list = [{"title": "未命名小说", "hint": ""}]

    # 自动模式：取第一个候选
    auto_mode = config["configurable"].get("auto_mode", False)
    if auto_mode:
        chosen_title = ai_suggestions_list[0]["title"]
        chosen_hint = ai_suggestions_list[0].get("hint", "")
        logger.info(f"【书名生成节点】自动模式 | 选择: {chosen_title}")
        logger.info(f"{'='*60}")
        return Command(
            goto="summary_node",
            update={
                "title": chosen_title,
                "title_story_hint": chosen_hint,
            }
        )

    # 暂停，让用户选择或自定义
    user_choice = interrupt({
        "action": "confirm_or_provide_title",
        "message": "AI已生成书名候选，请选择或输入自定义书名",
        "ai_suggestions": ai_suggestions_list,
        "note": "您可以直接使用AI推荐的书名，也可以输入自定义书名"
    })

    # user_choice 可以是字符串（自定义书名）或对象（选择了某个候选）
    chosen_title = ai_suggestions_list[0]["title"] if ai_suggestions_list else "未命名小说"
    chosen_hint = ""

    if isinstance(user_choice, str):
        chosen_title = user_choice
        logger.info(f"【书名生成节点】用户自定义书名: {chosen_title}")
    elif isinstance(user_choice, dict):
        chosen_title = user_choice.get("title", chosen_title)
        chosen_hint = user_choice.get("hint", "")
        logger.info(f"【书名生成节点】用户选择了候选: {chosen_title}")
    elif isinstance(user_choice, int) and 0 <= user_choice < len(ai_suggestions_list):
        chosen_title = ai_suggestions_list[user_choice]["title"]
        chosen_hint = ai_suggestions_list[user_choice].get("hint", "")
        logger.info(f"【书名生成节点】用户选择了第 {user_choice+1} 个候选: {chosen_title}")
    else:
        logger.info(f"【书名生成节点】默认使用第一个候选: {chosen_title}")

    logger.info(f"{'='*60}")
    return Command(
        goto="summary_node",
        update={
            "title": chosen_title,
            "title_story_hint": chosen_hint,
        }
    )
