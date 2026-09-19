"""Keep editorial advice separate from the user's binding acceptance contract."""

import json


def review_contract_rules(schema: dict) -> str:
    """只澄清验收口径，不改变服务端事实、目标或规模门禁。"""
    if "goal_checks" not in schema:
        return ""
    return (
        "\n【验收口径澄清】\n"
        "goal_contract 是验收依据，estimated_word_count 是分章写作参考，不是分章硬上限。"
        "整书 tolerance_ratio 只用于整书总字数，不得擅自套用到每章平均字数。"
        "不得仅因本章超过细纲估字或平均值就把 is_valid_word_count 判为 false；"
        "该字段依据有效正文和用户明确规定的本章硬限制判断。整书规模由服务端另行按实数验收。"
        "实际冗余仍须按证据报告；低密度、核心场景遗漏与明确硬限制违规不得忽略。"
        "plan_fulfillment.deferred_items 只填写本章应兑现却未兑现的事项，"
        "原本安排在后续章节的事件不是本章延期。不得把尚未发生写成已经发生，"
        "本章 state_delta 必须发生而实际未发生时，应报告缺失，不得用方向一致代替兑现。"
        "只检查当前版本正文；上一轮引文若已不存在，必须重找证据或标为已解决。"
        "轻微风格偏好使用 optional，不得为了修改而制造新的 must_fix。"
    )


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
    return (
        f"\n【整书规模修订的明确预算】已归档正文共 {prior} 字，不修改前文。"
        f"当前章现有 {words} 字，修订后的当前章必须在 {minimum} 至 {maximum} 字之间，"
        "按实际字符数计算（包含标点与空白）。"
        f"建议靠近 {max(minimum, int(maximum * 0.95))} 字，留出计数余量。"
        "若超出预算，压缩重复描写和重复解释；不得删去必达事件、证据链、人物选择和结局，"
        "不得以截断正文、修改目标字数或输出验收说明代替修订。"
    )
