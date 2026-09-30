"""可选反馈实验：隔离样稿、交换顺序模型盲评、有限采用与到期撤销。"""

from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.creative.feedback import evaluate_experiment, feedback_hypotheses
from application.streaming import emit_workflow_event
from service.value_objects.reader_feedback import BlindJudgment, FeedbackExperiment, ReaderFeedback


async def creative_experiment_node(state: dict, config: RunnableConfig) -> Command[Literal["creative_experiment_node", "plan_reconciliation_node"]]:
    """预算不足跳过可选实验；正式正文始终不被实验覆盖。"""
    work = await workspace(config)
    completed = int(state.get("current_chapter_index") or 0)
    await refresh_trials(work, completed)
    total = int(state.get("target_total_chapters") or (state.get("total_outline") or {}).get("total_chapters") or 0)
    if completed >= total or completed % 5:
        return Command(goto="plan_reconciliation_node")
    try:
        if await _experiment_step(work, completed):
            return Command(goto="creative_experiment_node")
    except CreativePause as error:
        if error.reason != "budget_exhausted":
            raise
        emit_workflow_event("creative", {"kind": "experiment", "status": "skipped", "reason": "budget_exhausted"}, "creative_experiment_node")
    return Command(goto="plan_reconciliation_node")


async def refresh_trials(work, completed):
    latest = {r["key"]: r for r in await work.records("experiment")}
    for key, record in latest.items():
        experiment = FeedbackExperiment.model_validate(record["payload"])
        updated = evaluate_experiment(experiment, completed)
        if updated != experiment:
            await work.save("experiment", key, updated.model_dump(mode="json"), previous=record,
                            status=updated.status, source="system")
            emit_workflow_event("creative", {"kind": "experiment", "status": updated.status, "record_key": key}, "creative_experiment_node")


async def _eligible_hypothesis(work):
    records = await work.records("feedback")
    chapters = {str(c["id"]): c["version"] for c in await work.repository.chapters(work.tenant_id, work.novel_id)}
    feedback = [ReaderFeedback.model_validate(r["payload"]) for r in records]
    current = [f for f in feedback if all(chapters.get(str(e.chapter_id)) == e.chapter_version for e in f.evidence)]
    hypotheses = feedback_hypotheses(current)
    for hypothesis in hypotheses:
        key = hypothesis["issue_key"]
        previous = await work.latest("hypothesis", key)
        if not previous or previous["payload"] != hypothesis:
            await work.save("hypothesis", key, hypothesis, previous=previous, source="system")
    return next((h for h in hypotheses if h["auto_experiment_eligible"]), None)


async def _experiment_step(work, completed):
    key = f"window:{completed // 5}"
    record = await work.latest("experiment", key)
    if record and record["status"] != "candidate":
        return False
    if not record:
        if _remaining_budget(work) < 6:
            return False
        hypothesis = await _eligible_hypothesis(work)
        if not hypothesis:
            return False
        return await _create_experiment(work, key, hypothesis, completed)
    experiment = FeedbackExperiment.model_validate(record["payload"])
    for order in ("AB", "BA"):
        if not await work.latest("evaluation", f"experiment:{key}:{order}"):
            if _remaining_budget(work) < 3:
                return False
            await _blind_judgment(work, key, experiment, order)
            return True
    judgments = [(await work.latest("evaluation", f"experiment:{key}:{order}"))["payload"] for order in ("AB", "BA")]
    experiment = experiment.model_copy(update={
        "judgments": [BlindJudgment.model_validate(j["judgment"]) for j in judgments],
        "quality_pass": all(j["quality_pass"] for j in judgments),
    })
    evaluated = evaluate_experiment(experiment, completed)
    if evaluated.status == "candidate":
        evaluated = evaluated.model_copy(update={"status": "revoked"})
    await work.save("experiment", key, evaluated.model_dump(mode="json"), previous=record, status=evaluated.status, source="system")
    emit_workflow_event("creative", {"kind": "experiment", "status": evaluated.status, "record_key": key}, "creative_experiment_node")
    return False


async def _create_experiment(work, key, hypothesis, completed):
    chapter, paragraphs = await _feedback_excerpts(work, hypothesis, completed)
    if not paragraphs:
        return False
    raw = await work.generate(
        "只改变一个因素生成隔离A/B样稿。A必须逐字使用下方一个自然段；B不超过1500字，"
        "不得改变事实、人物知识、关键剧情结果或硬设定，不得跨场景。返回factor、variant_a、variant_b。\n"
        "修改假设：" + json_text(hypothesis) + "\n可选原文：" + json_text(paragraphs[:8]),
        {"factor": "string", "variant_a": "string", "variant_b": "string"},
    )
    if raw["variant_a"] not in paragraphs:
        raise CreativePause("experiment_source", "实验A稿不是归档正文的单场景片段")
    experiment = FeedbackExperiment(
        **raw, issue_key=hypothesis["issue_key"], hypothesis_ids=[hypothesis["issue_key"]],
        scene_id=f"{chapter['id']}:paragraph:{paragraphs.index(raw['variant_a'])}", created_after_chapter=completed,
    )
    await work.save("experiment", key, experiment.model_dump(mode="json"), status="candidate",
                    inputs={"chapter": chapter["version"]})
    return True


async def _feedback_excerpts(work, hypothesis, completed):
    chapters = {c["id"]: c for c in await work.repository.chapters(work.tenant_id, work.novel_id, completed)}
    feedback = [r for r in await work.records("feedback") if r["source"] == "human_reader"
                and r["status"] != "stale_unverified" and r["payload"]["issue_key"] == hypothesis["issue_key"]]
    for record in feedback:
        for proof in record["payload"]["evidence"]:
            chapter = chapters.get(proof["chapter_id"])
            if not chapter or chapter["version"] != proof["chapter_version"]:
                continue
            paragraphs = [p for p in chapter["content"].split("\n\n") if proof["quote"] in p and 100 <= len(p) <= 1500]
            if paragraphs:
                return chapter, paragraphs
    return {}, []


def _remaining_budget(work):
    return work.session["limits"]["review"] - work.session["counters"].get("review", 0)


async def _blind_judgment(work, key, experiment, order):
    variants = {"A": experiment.variant_a, "B": experiment.variant_b}
    result = await work.generate(
        "盲评以下两份同场景文本，仅返回winner(first/second/tie)、reason和quality_pass。"
        "检查人物可信度、事实、因果、文风；若不是同一场景单因素变化，quality_pass=false。\n"
        + json_text({"first": variants[order[0]], "second": variants[order[1]]}),
        {"winner": "string", "reason": "string", "quality_pass": "boolean"},
    )
    if result["winner"] not in {"first", "second", "tie"}:
        raise CreativePause("invalid_blind_judgment", "模型盲评没有有效选择")
    winner = "tie" if result["winner"] == "tie" else order[0 if result["winner"] == "first" else 1]
    judgment = BlindJudgment(evaluator_id="simulated", source="model", order=order, winner=winner, reason=result["reason"])
    await work.save("evaluation", f"experiment:{key}:{order}", {
        "judgment": judgment.model_dump(mode="json"), "quality_pass": result["quality_pass"],
    }, status="simulated")
