"""进度检查节点 - 通过总纲进度条控制小说完结，每章完成后暂停等用户触发下一章"""
from langgraph.graph import END
from langgraph.types import interrupt
from application.schemas.agent_state import NovelAgentState


def progress_check_node(state: NovelAgentState) -> dict:
    """
    进度检查节点 - 检查是否完结
    通过总纲进度条控制小说完结
    每完成一章后暂停，等待用户点击"生成下一章"
    返回路由决策，由 workflow_builder 的 conditional_edges 处理
    """
    is_completed = state.get("is_completed", False)
    current_index = state.get("current_chapter_index", 0)
    total_outline = state.get("total_outline") or {}
    total_chapters = total_outline.get("total_chapters", 0)

    print(f"{'='*60}", flush=True)
    print(f"【进度检查节点】进入 | 当前章节={current_index}, 总章节={total_chapters}, 是否完成={is_completed}", flush=True)

    # 检查是否已完成所有章节
    if is_completed or current_index >= total_chapters:
        print(f"【进度检查节点】小说已完成! 进入 -> 结束", flush=True)
        print(f"{'='*60}", flush=True)
        return {"__route__": "end"}

    # 章节数为 0 表示刚从大纲确认过来，直接进入创作循环（不暂停）
    if current_index == 0:
        print(f"【进度检查节点】首章创作 -> 记忆检索节点", flush=True)
        print(f"{'='*60}", flush=True)
        return {"__route__": "continue"}

    # ====== 已完成至少一章，暂停等待用户点击"生成下一章" ======
    user_choice = interrupt({
        "action": "ready_for_next_chapter",
        "message": f"第{current_index}章已完成，共{total_chapters}章",
        "current_chapter": current_index,
        "total_chapters": total_chapters,
        "progress_percentage": round(current_index / total_chapters * 100, 1) if total_chapters > 0 else 0,
        "note": "点击「生成下一章」继续创作，或去书架查看已有章节",
    })

    # 用户选择继续 → 进入下一章的创作循环
    print(f"【进度检查节点】用户选择继续 -> 记忆检索节点 | 准备创作第 {current_index + 1} 章", flush=True)
    print(f"{'='*60}", flush=True)
    return {"__route__": "continue"}
