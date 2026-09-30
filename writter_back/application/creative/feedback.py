"""模型支持试用与真人复测分别判定，不修改归档正文。"""

from collections import defaultdict

from service.value_objects.reader_feedback import FeedbackExperiment, ReaderFeedback


def feedback_hypotheses(feedback: list[ReaderFeedback]) -> list[dict]:
    """至少三个独立读者、两处精确片段才自动进入实验候选。"""
    groups = defaultdict(list)
    for item in feedback:
        groups[(item.issue_key, item.category)].append(item)
    return [_hypothesis(key, category, items) for (key, category), items in sorted(groups.items())]


def _hypothesis(key, category, items):
    human = [f for f in items if f.source == "human_reader"]
    readers = {f.reader_id for f in human}
    excerpts = {(str(e.chapter_id), e.chapter_version, e.start, e.end) for f in human for e in f.evidence}
    direct = any(f.source == "author_instruction" for f in items)
    return {
        "issue_key": key, "category": category,
        "independent_readers": len(readers), "located_excerpts": len(excerpts),
        "route": "author_instruction" if direct else "fact_review" if category == "fact" else "experiment",
        "auto_experiment_eligible": not direct and category != "fact" and len(readers) >= 3 and len(excerpts) >= 2,
        "status": "candidate",
    }


def evaluate_experiment(experiment: FeedbackExperiment, completed_chapter: int) -> FeedbackExperiment:
    """仅确定性证据可推进采用状态；样本不足或模型分歧不采用。"""
    model = [j for j in experiment.judgments if j.valid and j.source == "model"]
    orders = {j.order for j in model if j.winner == "B"}
    model_supported = experiment.quality_pass and len(model) == 2 and orders == {"AB", "BA"}
    humans = {}
    for judgment in experiment.judgments:
        if judgment.valid and judgment.source == "human":
            humans[judgment.evaluator_id] = judgment
    support = sum(j.winner == "B" for j in humans.values())
    opposed = sum(j.winner == "A" for j in humans.values())
    human_supported = len(humans) >= 3 and support > len(humans) / 2
    contradicted = len(humans) >= 3 and opposed >= len(humans) / 2
    expired = experiment.trial_end is not None and completed_chapter >= experiment.trial_end
    if experiment.status == "revoked":
        return experiment
    if not experiment.quality_pass or contradicted or (expired and not human_supported):
        status = "revoked" if experiment.status != "candidate" else "candidate"
    elif model_supported and human_supported:
        status = "human_supported"
    elif model_supported:
        status = "model_supported_trial"
    else:
        status = "candidate"
    updates = {"status": status}
    if status in {"model_supported_trial", "human_supported"} and experiment.trial_start is None:
        updates.update(trial_start=completed_chapter + 1, trial_end=completed_chapter + 5)
    return FeedbackExperiment.model_validate({**experiment.model_dump(), **updates})
