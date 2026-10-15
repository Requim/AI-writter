"""Keep editorial advice separate from the user's binding acceptance contract."""

import json

from application.prompts.template_loader import render_prompt


def review_contract_rules(schema: dict) -> str:
    """只澄清验收口径，不改变服务端事实、目标或规模门禁。"""
    if "goal_checks" not in schema:
        return ""
    return "\n" + render_prompt(
        "reflection/contract_rules.txt", include_active_rules=False,
    ).rstrip("\n")


def unmet_review_findings(gate: dict) -> str:
    """把非 issue 字段中的真实阻塞也传给修订器，避免盲目全文润色。"""
    goals = gate.get("goal_acceptance") or {}
    findings = {
        "word_count_analysis": gate.get("word_count_analysis"),
        "plan_fulfillment": gate.get("plan_fulfillment"),
        "tactical_fulfillment": gate.get("tactical_fulfillment"),
        "failed_goals": [row for row in goals.get("checks", [])
                         if row.get("status") != "passed"],
    }
    return (
        "\n【本轮未通过项及验收依据】\n" + json.dumps(findings, ensure_ascii=False)
        + "\n仅修正实际未满足的项，保留已通过的情节、证据、人物与动作；"
        "不得将建议当作新目标，也不得把验收报告写入小说正文。"
        + _scale_revision_budget(goals.get("checks", []))
    )


def _scale_revision_budget(checks: list[dict]) -> str:
    """将整书实数约束换算成当前正文预算，不依赖模型自行从总数推算。"""
    scale = next((row for row in checks if row.get("id") == "scale"
                  and row.get("status") == "failed"), {})
    words, total = scale.get("actual_chapter_words"), scale.get("actual_total_words")
    bounds = scale.get("range")
    if not (type(words) is int and type(total) is int and total >= words >= 0
            and isinstance(bounds, list) and len(bounds) == 2
            and all(type(value) is int for value in bounds)):
        return ""
    prior = total - words
    minimum, maximum = max(0, bounds[0] - prior), bounds[1] - prior
    if maximum <= 0:
        return "\n整书已归档字数已耗尽上限，不能靠新增正文满足规模；不得放宽用户上限。"
    return "\n" + render_prompt(
        "revision/scale_budget.txt", include_active_rules=False,
        prior=prior, words=words, minimum=minimum, maximum=maximum,
        suggested=max(minimum, int(maximum * 0.95)),
    ).rstrip("\n")
