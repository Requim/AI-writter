"""书名生成节点 - 用户输入优先，否则AI生成"""
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.title_prompts import build_title_prompt, TITLE_TEMPERATURE
from datetime import datetime


async def title_generator_node(state: NovelAgentState, config) -> Command[Literal["summary_node"]]:
    """
    书名节点 - 用户输入优先，否则AI生成
    如果用户未提供书名，AI自动生成后询问用户确认
    """
    novel_type = state.get("novel_type", "")
    has_title = 'title' in state and bool(state.get('title'))
    print(f"{'='*60}", flush=True)
    print(f"【书名生成节点】进入 | 小说类型={novel_type}, 已有书名={'是' if has_title else '否'}", flush=True)
    
    # 用户已提供书名，直接使用并回写数据库
    if state.get("title"):
        print(f"【书名生成节点】跳过 -> 简介节点 | 使用已有书名: {state['title']}", flush=True)
        _repo = config["configurable"].get("novel_repository")
        if _repo:
            try:
                novel_id = state.get("novel_id", "")
                if novel_id:
                    novel = await _repo.find_by_id(novel_id)
                    if novel:
                        novel.title = state["title"]
                        novel.updated_at = datetime.now()
                        await _repo.update(novel)
                        print(f"【书名生成节点】书名已回写数据库", flush=True)
            except Exception as e:
                print(f"【书名生成节点】回写书名失败(降级): {e}", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="summary_node")
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【书名生成节点】LLM不可用，跳过 -> 简介节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="summary_node")
    
    # AI 生成书名候选
    prompt = build_title_prompt(novel_type)
    ai_titles_text = await llm.generate(prompt, temperature=TITLE_TEMPERATURE)
    ai_titles = [t.strip() for t in ai_titles_text.split("\n") if t.strip()][:5]
    print(f"【书名生成节点】AI生成了 {len(ai_titles)} 个书名候选: {ai_titles}", flush=True)
    
    # 暂停，让用户选择或自定义
    user_choice = interrupt({
        "action": "confirm_or_provide_title",
        "message": "AI已生成书名候选，请选择或输入自定义书名",
        "ai_suggestions": ai_titles,
        "note": "您可以直接使用AI推荐的书名，也可以输入自定义书名"
    })
    
    # user_choice 可以是字符串（自定义书名）或数字（选择AI推荐的某个）
    if isinstance(user_choice, str):
        chosen_title = user_choice
        print(f"【书名生成节点】用户自定义书名: {chosen_title}", flush=True)
    elif isinstance(user_choice, int) and 0 <= user_choice < len(ai_titles):
        chosen_title = ai_titles[user_choice]
        print(f"【书名生成节点】用户选择了第 {user_choice+1} 个候选: {chosen_title}", flush=True)
    else:
        # 默认使用AI第一个推荐
        chosen_title = ai_titles[0] if ai_titles else "未命名小说"
        print(f"【书名生成节点】默认使用第一个候选: {chosen_title}", flush=True)

    # 回写书名到数据库
    _repo = config["configurable"].get("novel_repository")
    if _repo:
        try:
            novel_id = state.get("novel_id", "")
            if novel_id:
                novel = await _repo.find_by_id(novel_id)
                if novel:
                    novel.title = chosen_title
                    novel.updated_at = datetime.now()
                    await _repo.update(novel)
                    print(f"【书名生成节点】书名已回写数据库", flush=True)
        except Exception as e:
            print(f"【书名生成节点】回写书名失败(降级): {e}", flush=True)

    print(f"{'='*60}", flush=True)
    return Command(
        goto="summary_node",
        update={"title": chosen_title}
    )
