"""章节内容填充节点 - 根据细纲生成3000-6000字内容"""
from langgraph.types import Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.chapter_writer_prompts import (
    build_chapter_writer_prompt,
    build_chapter_continue_prompt,
    build_chapter_system_prompt,
    CHAPTER_WRITER_TEMPERATURE,
)


async def chapter_writer_node(state: NovelAgentState, config) -> Command[Literal["reflection_node"]]:
    """
    章节内容填充节点 - 根据细纲生成3000-6000字内容
    禁止注水，确保内容质量
    """
    chapter_outline = state.get("chapter_outlines", [{}])[-1]
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    memory_context = state.get("memory_context", "")
    chapter_num = chapter_outline.get('chapter_number', '?')
    has_llm = bool(config["configurable"].get("llm_config", {}).get('llm_instance'))
    llm_status = '✅ 已加载' if has_llm else '❌ 不可用'
    print(f"{'='*60}", flush=True)
    print(f"【章节写作节点】进入 | 书名={title}, 第 {chapter_num} 章, LLM={llm_status}", flush=True)
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【章节写作节点】LLM不可用，跳过 -> 反思节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="reflection_node")

    prompt = build_chapter_writer_prompt(chapter_outline, novel_type, title, memory_context)

    content = await llm.generate(
        prompt=prompt,
        system_prompt=build_chapter_system_prompt(novel_type),
        temperature=CHAPTER_WRITER_TEMPERATURE
    )
    
    # 检查字数
    word_count = len(content)
    if word_count < 3000:
        print(f"【章节写作节点】字数不足 ({word_count}字)，正在扩展内容...", flush=True)
        continue_prompt = build_chapter_continue_prompt(word_count, content)
        additional_content = await llm.generate(
            continue_prompt,
            temperature=CHAPTER_WRITER_TEMPERATURE
        )
        content += "\n\n" + additional_content
        print(f"【章节写作节点】扩展后字数: {len(content)}字", flush=True)
    elif word_count > 6500:
        # 字数过多，截断（保留前6000字左右）
        print(f"【章节写作节点】字数过多 ({word_count}字)，截断至6000字", flush=True)
        content = content[:6000] + "\n\n[内容已截断，原稿过长]"
    else:
        print(f"【章节写作节点】字数合格: {word_count}字", flush=True)
    
    print(f"【章节写作节点】完成 -> 反思节点 | 最终字数: {len(content)}字", flush=True)
    print(f"{'='*60}", flush=True)
    return Command(
        goto="reflection_node",
        update={"current_chapter_content": content}
    )
