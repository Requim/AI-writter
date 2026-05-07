"""章节细纲生成节点 - 用户输入优先，否则AI生成"""
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt, CHAPTER_OUTLINE_SCHEMA


async def chapter_outline_node(state: NovelAgentState, config) -> Command[Literal["chapter_writer_node"]]:
    """
    章节细纲生成节点 - 用户可提供，否则AI生成
    总纲通过 total_outline 传递，包含章节规划
    """
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    total_outline = state.get("total_outline", {})
    current_index = state.get("current_chapter_index", 0)
    memory_context = state.get("memory_context", "")
    has_user_outline = 'chapter_outlines_input' in state and bool(state.get('chapter_outlines_input'))
    mem_status = '✅ 有' if memory_context else '❌ 无'
    print(f"{'='*60}", flush=True)
    print(f"【章节细纲节点】进入 | 书名={title}, 第 {current_index+1} 章, 用户已提供细纲={'是' if has_user_outline else '否'}, 前文记忆={mem_status}", flush=True)
    
    if state.get("chapter_outlines_input"):
        print(f"【章节细纲节点】使用用户提供的细纲 -> 章节写作节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="chapter_writer_node")
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【章节细纲节点】LLM不可用，跳过 -> 章节写作节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="chapter_writer_node")
    
    # 从总纲领获取当前章节规划
    chapters = total_outline.get("chapters", [])
    chapter_plan = chapters[current_index] if current_index < len(chapters) else {"theme": "未指定", "key_events": []}
    
    # AI 生成详细章节细纲
    prompt = build_chapter_outline_prompt(
        chapter_index=current_index + 1,
        novel_type=novel_type,
        title=title,
        chapter_theme=chapter_plan.get('theme', '未指定'),
        key_events=chapter_plan.get('key_events', []),
        memory_context=memory_context,
    )

    ai_outline = await llm.structured_generate(
        prompt=prompt,
        schema=CHAPTER_OUTLINE_SCHEMA
    )
    
    # 验证字数规划
    word_count = ai_outline.get("estimated_word_count", 4500)
    if word_count < 3000 or word_count > 6000:
        ai_outline["estimated_word_count"] = max(3000, min(6000, word_count))
    
    # 暂停，让用户审阅/修改
    user_decision = interrupt({
        "action": "review_or_provide_chapter_outline",
        "message": f"第{current_index + 1}章细纲已生成，请审阅或修改",
        "chapter_number": current_index + 1,
        "ai_generated_outline": ai_outline,
        "note": "您可以：1) 直接使用（回复'accept'）2) 提供自定义细纲 3) 要求重新生成（回复'regenerate'）"
    })
    
    if user_decision == "accept":
        print(f"【章节细纲节点】用户接受AI细纲 -> 章节写作节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(
            goto="chapter_writer_node",
            update={"chapter_outlines": [ai_outline]}
        )
    elif user_decision == "regenerate":
        print(f"【章节细纲节点】用户要求重新生成，循环回本节点", flush=True)
        return Command(goto="chapter_outline_node")
    else:
        print(f"【章节细纲节点】用户提供了自定义细纲 -> 章节写作节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(
            goto="chapter_writer_node",
            update={"chapter_outlines": [user_decision]}
        )
