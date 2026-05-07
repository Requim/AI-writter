"""简介生成节点 - 用户输入优先，否则AI生成"""
from langgraph.types import interrupt, Command
from typing import Literal
from datetime import datetime
from application.schemas.agent_state import NovelAgentState
from application.prompts.summary_prompts import build_summary_prompt, SUMMARY_TEMPERATURE


async def summary_generator_node(state: NovelAgentState, config) -> Command[Literal["outline_node"]]:
    """
    简介节点 - 用户输入优先，否则AI生成
    """
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    has_summary = 'summary' in state and bool(state.get('summary'))
    print(f"{'='*60}", flush=True)
    print(f"【简介生成节点】进入 | 书名={title}, 已有简介={'是' if has_summary else '否'}", flush=True)
    
    # 用户已提供简介，直接使用并回写数据库
    if state.get("summary"):
        print(f"【简介生成节点】跳过 -> 大纲节点 | 使用已有简介 (长度={len(state['summary'])}字)", flush=True)
        _repo = config["configurable"].get("novel_repository")
        if _repo:
            try:
                novel_id = state.get("novel_id", "")
                if novel_id:
                    novel = await _repo.find_by_id(novel_id)
                    if novel:
                        novel.summary = state["summary"]
                        novel.updated_at = datetime.now()
                        await _repo.update(novel)
                        print(f"【简介生成节点】简介已回写数据库", flush=True)
            except Exception as e:
                print(f"【简介生成节点】回写简介失败(降级): {e}", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="outline_node")
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【简介生成节点】LLM不可用，跳过 -> 大纲节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="outline_node")
    
    # AI 生成简介
    prompt = build_summary_prompt(novel_type, title)
    ai_summary = await llm.generate(prompt, temperature=SUMMARY_TEMPERATURE)
    
    # 暂停，让用户确认或修改
    user_choice = interrupt({
        "action": "confirm_or_provide_summary",
        "message": "AI已生成小说简介，请确认或修改",
        "ai_generated_summary": ai_summary,
        "note": "您可以：1) 直接使用（回复'accept'）2) 输入自定义简介 3) 要求重新生成（回复'regenerate'）"
    })
    
    if user_choice == "accept":
        final_summary = ai_summary
        print(f"【简介生成节点】用户接受了AI生成的简介 -> 大纲节点", flush=True)
    elif user_choice == "regenerate":
        print(f"【简介生成节点】用户要求重新生成，循环回本节点", flush=True)
        return Command(goto="summary_generator_node")
    else:
        final_summary = user_choice
        print(f"【简介生成节点】用户提供了自定义简介 -> 大纲节点", flush=True)

    # 回写简介到数据库
    _repo = config["configurable"].get("novel_repository")
    if _repo:
        try:
            novel_id = state.get("novel_id", "")
            if novel_id:
                novel = await _repo.find_by_id(novel_id)
                if novel:
                    novel.summary = final_summary
                    novel.updated_at = datetime.now()
                    await _repo.update(novel)
                    print(f"【简介生成节点】简介已回写数据库", flush=True)
        except Exception as e:
            print(f"【简介生成节点】回写简介失败(降级): {e}", flush=True)

    print(f"{'='*60}", flush=True)
    return Command(
        goto="outline_node",
        update={"summary": final_summary}
    )
