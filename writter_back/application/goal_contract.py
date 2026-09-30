"""将已接受目标固定为可追踪契约，避免以生成结果重定义验收。"""

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from application.errors import QualityGateReviewRequired


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    """计算正文或结构化目标的稳定指纹，不依赖模型输出。"""
    text = value if isinstance(value, str) else _json(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(state: dict) -> dict:
    plan = state.get("novel_plan") or {}
    chapter = int(state.get("current_chapter_index", 0)) + 1
    slot = next((s for s in plan.get("chapter_slots", []) if s["chapter_number"] == chapter), None)
    if not slot:
        return {}
    total = state.get("total_outline") or {}
    brief = state.get("creative_brief") or total.get("creative_brief") or {}
    author = state.get("author_config") or total.get("author_config") or {}
    return deepcopy({
        "chapter": chapter, "plan_version": plan["version"], "slot": slot,
        "scale": state.get("scale_contract") or plan["scale"],
        "ending": plan.get("ending_contract", {}) if chapter == plan["scale"]["target_chapters"] else {},
        "brief": {k: brief[k] for k in ("core_premise", "reader_promise", "setting_boundaries",
                                      "content_boundaries") if brief.get(k)},
        "hard_constraints": author.get("hard_constraints", []),
        "user_summary": state.get("summary") or "",
    })


def _requirements(source: dict) -> list[dict]:
    chapter, slot = source["chapter"], source["slot"]
    items = [{"id": f"ch{chapter}:must:{i}", "expected": text, "source": "accepted_plan"}
             for i, text in enumerate(slot.get("must_happen", []), 1)]
    if slot.get("planned_state_delta"):
        items.append({"id": "state_delta", "expected": slot["planned_state_delta"], "source": "accepted_plan"})
    for key, value in source["brief"].items():
        items.append({"id": f"brief:{key}", "expected": value, "source": "creative_brief"})
    for index, text in enumerate(source["hard_constraints"], 1):
        items.append({"id": f"author:hard:{index}", "expected": text, "source": "author_config"})
    if source["user_summary"]:
        items.append({"id": "user:summary", "expected": source["user_summary"], "source": "user_input"})
    if chapter == source["scale"]["target_chapters"]:
        items.append({"id": "ending", "expected": source["ending"], "source": "accepted_plan"})
    return items


def compile_goal_contract(state: dict) -> dict | None:
    """仅从服务端已接受的来源编译，模型细纲不能覆盖上游目标。"""
    source = _source(state)
    if not source:
        return None
    data = {"version": 1, "source": source, "requirements": _requirements(source)}
    if len(_json(data)) > 18000:
        raise QualityGateReviewRequired("目标契约超过上下文预算，请先明确本章适用范围；不能静默截断硬约束")
    return {**data, "id": fingerprint(data)}


def current_goal_contract(state: dict) -> dict | None:
    """校验已绑定来源，禁止同章修订时重新生成或悄悄放宽目标。"""
    outlines = state.get("chapter_outlines") or []
    contract = outlines[-1].get("goal_contract") if outlines else None
    if contract is None:
        return None
    expected = compile_goal_contract(state)
    if not expected or contract != expected:
        raise QualityGateReviewRequired("本章目标来源已变化，请重新确认章节计划，不能沿用旧验收")
    return contract


def goal_prompt(contract: dict | None) -> str:
    """把当前目标和证据规则附加到现有调用，不增加模型请求。"""
    if not contract:
        return ""
    projection = {k: contract[k] for k in ("id", "requirements")}
    projection["scale"] = contract["source"]["scale"]
    return (
        "\n【固定目标契约，不是待修改建议】\n" + _json(projection)
        + "\n逐项核对原始目标，不得因正文写得流畅或评分较高放宽标准。"
        "审读时额外返回 goal_checks 数组，每项包含 id、status(passed/failed/unknown)、"
        "evidence(当前完整正文的逐字引用)、reason(如何满足预期，含因果和范围)。"
        "每个目标必须恰好一项；缺少证据或无法确定时用 unknown。"
        "本书总体前提与阅读承诺检查本章是否兼容，不要求每章重复解释或提前兑现全书目标。"
        "禁止只凭覆盖ID或提到关键词判定完成。终章不得把欠缺转移到不存在的下一章。"
        "修改时保持这些目标和已完成修正，修订意见冲突时报告不能完成，不能改写目标。"
    )


def _semantic_checks(contract: dict, raw: Any, content: str) -> list[dict]:
    rows = raw if isinstance(raw, list) else []
    checks = []
    for goal in contract["requirements"]:
        matched = [r for r in rows if isinstance(r, dict) and r.get("id") == goal["id"]]
        row = matched[0] if len(matched) == 1 else {}
        quote = row.get("evidence")
        valid = isinstance(quote, str) and bool(quote.strip()) and quote in content
        status = row.get("status") if row.get("status") in {"passed", "failed", "unknown"} else "unknown"
        if status == "passed" and (not valid or not isinstance(row.get("reason"), str) or not row["reason"].strip()):
            status = "unknown"
        checks.append({"id": goal["id"], "expected": goal["expected"], "status": status,
                       "evidence": quote if valid else "", "reason": row.get("reason", ""),
                       "evidence_valid": valid})
    return checks


def _scale_check(contract: dict, state: dict, content: str) -> dict:
    source, words = contract["source"], len(content)
    scale, chapter = source["scale"], source["chapter"]
    prior = {c["chapter_index"]: c for c in state.get("completed_chapters", [])
             if isinstance(c, dict) and isinstance(c.get("chapter_index"), int)
             and 0 <= c["chapter_index"] < chapter - 1}
    final = chapter == scale["target_chapters"]
    known = len(prior) == chapter - 1 and all(type(c.get("word_count")) is int and c["word_count"] >= 0 for c in prior.values())
    accumulated = words + sum(c["word_count"] for c in prior.values()) if known else words
    target, tolerance = scale["target_total_words"], scale.get("tolerance_ratio", 0.1)
    lower, upper = math.ceil(target * (1 - tolerance)), math.floor(target * (1 + tolerance))
    status = "unknown" if final and not known else "passed"
    if words > upper or (known and (accumulated > upper or (final and accumulated < lower))):
        status = "failed"
    return {"id": "scale", "status": status, "actual_chapter_words": words,
            "actual_total_words": accumulated if known else None, "range": [lower, upper],
            "reason": "按实际字符数检查整书规模；分章目标仅作参考，不由模型放宽整书容差"}


def evaluate_goals(state: dict, result: dict, content: str) -> dict | None:
    """独立于质量分数逐项验收，缺项、无证据和规模违约均不算通过。"""
    contract = current_goal_contract(state)
    if not contract:
        return None
    checks = _semantic_checks(contract, result.get("goal_checks"), content)
    checks.append(_scale_check(contract, state, content))
    final = contract["source"]["chapter"] == contract["source"]["scale"]["target_chapters"]
    plan = result.get("plan_fulfillment") or {}
    breaches = ("volume_boundary_breached", "core_arc_breached", "ending_contract_breached", "scale_change_required")
    for field in breaches:
        if plan.get(field) is True:
            checks.append({"id": field, "status": "failed", "reason": "兑现报告已报告违约，不能用另一项评分覆盖"})
    if plan.get("missing_required_events"):
        checks.append({"id": "missing_events", "status": "failed", "reason": "必达事件仍有缺失"})
    if final and plan.get("deferred_items"):
        checks.append({"id": "no_final_deferral", "status": "failed", "reason": "终章没有后续章节可承接延期事项"})
    passed = bool(checks) and all(c["status"] == "passed" for c in checks)
    return {"contract_id": contract["id"], "content_hash": fingerprint(content),
            "status": "passed" if passed else "blocked", "checks": checks}


def require_goal_acceptance(state: dict, content: str) -> bool:
    """归档前校验目标及正文版本；人工质量接受不能替代目标验收。"""
    contract = current_goal_contract(state)
    if not contract:
        return True
    report = (state.get("quality_gate") or {}).get("goal_acceptance") or {}
    checks = report.get("checks") or []
    expected_ids = {g["id"] for g in contract["requirements"]} | {"scale"}
    actual_ids = {c.get("id") for c in checks if isinstance(c, dict)}
    return (report.get("contract_id") == contract["id"]
            and report.get("content_hash") == fingerprint(content)
            and report.get("status") == "passed" and expected_ids <= actual_ids
            and all(isinstance(c, dict) and c.get("status") == "passed" for c in checks))
