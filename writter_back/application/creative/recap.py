"""每五章以归档正文复查故事发动机，结束时不强行追加问题。"""

from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.creative.postprocess import _proofs

REVIEW_SCHEMA = {
    "issues": "array", "needs_replan": "boolean", "instruction": "string",
    "closed_reasonably": "boolean", "changes_ending": "boolean",
}


async def creative_recap_node(state: dict, config: RunnableConfig) -> Command[Literal["creative_experiment_node", "novel_plan_initialize_node"]]:
    """模型必须提供原文证据；合理收束不能为了续写制造新冲突。"""
    work = await workspace(config)
    completed = int(state.get("current_chapter_index") or 0)
    key = str(completed)
    review = await work.latest("engine_review", key)
    if not review:
        chapters = await work.repository.chapters(work.tenant_id, work.novel_id, completed)
        engine = await work.latest("engine", "main")
        result = await work.generate(
            "复查最近实际正文中的重复解法、无代价升级、临时追加设定、支线失控、读者承诺拖延。"
            "每条issues包含chapter_number/start/quote和problem，不得编造铺垫。"
            "无问题或已经合理收束时needs_replan=false；不得为了维持冲突强行续写。"
            "如需调整只给未来局部修改假设，不改硬设定、规模、归档正文和锁定窗口。"
            "\n发动机：" + json_text(engine["payload"] if engine else {})
            + "\n正文：" + json_text(chapters[-5:]) + "\n返回：" + json_text(REVIEW_SCHEMA), REVIEW_SCHEMA,
        )
        proofs = []
        by_number = {c["chapter_index"] + 1: c for c in chapters[-5:]}
        for issue in result["issues"]:
            chapter = by_number.get(issue.get("chapter_number"))
            if not chapter:
                raise CreativePause("review_evidence", "复盘问题没有对应的归档章节")
            proofs.extend(_proofs([issue], chapter))
        if result["needs_replan"] and (not proofs or not result["instruction"]):
            raise CreativePause("review_evidence", "改纲建议必须包含正文证据和具体修改理由")
        review = await work.save("engine_review", key, result, evidence=proofs, status="reviewed")
    result = review["payload"]
    if result["needs_replan"] and not result["closed_reasonably"] and not await work.latest("decision", f"recap_replan:{key}"):
        await work.save("decision", f"recap_replan:{key}", {"review_id": review["id"]}, source="system")
        return Command(goto="novel_plan_initialize_node", update={
            "plan_replan_request": {
                "expected_version": state["novel_plan"]["version"], "scope": "future",
                "trigger": "autonomous_recap", "instruction": result["instruction"],
            }, "plan_generation": None, "tactical_window": None, "pending_proposal": None,
        })
    return Command(goto="creative_experiment_node")
