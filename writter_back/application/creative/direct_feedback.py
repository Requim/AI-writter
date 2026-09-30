"""明确作者指令进入原改纲入口，事实反馈进入既有两步纠错流程。"""

from langgraph.types import Command

from application.creative.artifacts import json_text
from application.creative.errors import CreativePause
from application.creative.evidence import content_hash


async def dispatch_author_feedback(work, state):
    """不等待读者投票；指令仍受原计划CAS及自主改纲边界约束。"""
    feedback = [r for r in await work.records("feedback") if r["source"] == "author" and r["status"] != "stale_unverified"]
    for item in feedback:
        if item["payload"]["category"] not in {"plot", "character"}:
            continue
        key = f"author_feedback:{item['id']}"
        previous = await work.latest("decision", key)
        version = state["novel_plan"]["version"]
        if previous and previous["input_versions"]["plan"] < version:
            continue
        if previous is None:
            await work.save("decision", key, {"feedback_id": item["id"]}, source="author",
                            inputs={"plan": version}, status="requested")
        return Command(goto="novel_plan_initialize_node", update={
            "plan_replan_request": {"expected_version": version, "scope": "future", "trigger": "author_feedback",
                                   "instruction": item["payload"]["comment"]},
            "plan_generation": None, "pending_proposal": None, "tactical_window": None,
        })
    return None


async def author_instruction_rules(repository, tenant_id, novel_id):
    """当前书的明确表达指令不学习为作者全局偏好。"""
    records = await repository.records(tenant_id, novel_id, "feedback")
    instructions = [r for r in records if r["source"] == "author" and r["status"] != "stale_unverified"
                    and r["payload"]["category"] in {"style", "pace", "understanding"}]
    if not instructions:
        return ""
    text = json_text([{"id": r["id"], "instruction": r["payload"]["comment"]} for r in instructions[-10:]])
    if len(text) > 4000:
        raise CreativePause("author_instruction_size", "当前明确指令超过上下文上限，请合并取舍后继续")
    return "\n【当前书的作者明确指令】" + text + "\n优先于非硬审美偏好；不修改事实或历史正文，不学习为跨书文风。"


async def file_fact_feedback(work):
    """事实评论是待核实线索，不以投票或模型预测直接更改规范事实。"""
    for item in await work.records("feedback"):
        if item["payload"]["category"] != "fact" or item["status"] == "stale_unverified":
            continue
        key = "fact_feedback:" + content_hash(item["id"])[:32]
        if not await work.latest("hypothesis", key):
            await work.save("hypothesis", key, {
                "feedback_id": item["id"], "route": "existing_fact_correction",
                "proposal_endpoint": f"/api/v1/novels/{work.novel_id}/facts/proposals",
                "confirmation_required": True, "comment": item["payload"]["comment"],
            }, source="system", status="fact_review_required", evidence=item["evidence"])
