"""总纲领生成节点 - 用户输入优先，否则AI生成"""
from langgraph.types import interrupt, Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.prompts.outline_prompts import build_outline_prompt, OUTLINE_SCHEMA


async def outline_generator_node(state: NovelAgentState, config) -> Command[Literal["progress_check_node"]]:
    """
    总纲领节点 - 用户输入优先，否则AI生成
    总纲领包含：故事背景、主要人物、主线剧情、章节规划
    """
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    summary = state.get("summary", "")
    has_outline = 'total_outline' in state and isinstance(state.get('total_outline'), dict)
    print(f"{'='*60}", flush=True)
    print(f"【总大纲生成节点】进入 | 书名={title}, 已有大纲={'是' if has_outline else '否'}", flush=True)
    
    # 用户已提供总纲领，直接使用（仅当为字典时）
    if isinstance(state.get("total_outline"), dict):
        print(f"【总大纲生成节点】跳过 -> 进度检查节点 | 使用已有大纲", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="progress_check_node")
    
    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")
    
    if not llm:
        print(f"【总大纲生成节点】LLM不可用，跳过 -> 进度检查节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(goto="progress_check_node")
    
    # AI 生成总纲领
    prompt = build_outline_prompt(novel_type, title, summary)

    ai_outline = await llm.structured_generate(
        prompt=prompt,
        schema=OUTLINE_SCHEMA
    )
    
    # 暂停，让用户审阅/修改
    user_decision = interrupt({
        "action": "review_or_modify_outline",
        "message": "AI已生成总纲领，请审阅并可选择修改",
        "ai_generated_outline": ai_outline,
        "note": "您可以：1) 直接使用（回复'accept'）2) 修改后提供新的总纲领 3) 要求AI重新生成（回复'regenerate'）"
    })
    
    if user_decision == "accept":
        print(f"【总大纲生成节点】用户接受了AI生成的大纲 -> 进度检查节点", flush=True)

        # 将书名、简介、大纲持久化到数据库
        repository = config["configurable"].get("novel_repository")
        novel_id = config["configurable"].get("thread_id", "")
        title_to_save = state.get("title")
        summary_to_save = state.get("summary")
        print(f"【总大纲生成节点】诊断: novel_id={novel_id}, title='{title_to_save}', summary_len={len(summary_to_save or '')}", flush=True)
        if repository and novel_id:
            try:
                novel = await repository.find_by_id(novel_id)
                if novel:
                    novel.title = state.get("title")
                    novel.summary = state.get("summary")
                    from service.value_objects.outline import Outline
                    # 过滤只保留 Outline 需要的字段，防止 LLM 返回额外字段导致构造失败
                    outline_fields = {'story_background', 'main_characters', 'main_plot', 'chapters', 'writing_style', 'total_chapters'}
                    filtered = {k: v for k, v in ai_outline.items() if k in outline_fields} if isinstance(ai_outline, dict) else {}
                    novel.total_outline = Outline(**filtered) if filtered else ai_outline
                    await repository.update(novel)
                    print(f"【总大纲生成节点】书名={novel.title} 已保存到数据库", flush=True)
                else:
                    print(f"【总大纲生成节点】找不到小说 {novel_id}，跳过DB保存", flush=True)
            except Exception as e:
                print(f"【总大纲生成节点】保存失败(降级): {e}", flush=True)

        print(f"{'='*60}", flush=True)
        return Command(
            goto="progress_check_node",
            update={"total_outline": ai_outline}
        )
    elif user_decision == "regenerate":
        print(f"【总大纲生成节点】用户要求重新生成，循环回本节点", flush=True)
        return Command(goto="outline_generator_node")
    else:
        print(f"【总大纲生成节点】用户提供了自定义大纲 -> 进度检查节点", flush=True)
        print(f"{'='*60}", flush=True)
        return Command(
            goto="progress_check_node",
            update={"total_outline": user_decision}
        )
