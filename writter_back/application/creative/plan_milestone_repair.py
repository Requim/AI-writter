"""Correct only evidence-cited arc milestones, then require independent review."""

import json
import re
from copy import deepcopy

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativeConflict, CreativePause
from application.creative.evidence import content_hash
from application.creative.plan_consistency import _audit_context, _valid_report
from application.fact_evidence import outline_leaf
from application.prompts.template_loader import render_prompt
from service.value_objects.novel_plan import NovelPlan, NovelPlanValidationError, validate_plan_transition

SCHEMA = {"changes": [{
    "path": "string", "before": "string", "after": "string", "chapter_number": "integer",
}]}
MILESTONE_PATH = re.compile(r"/plan/arcs/([0-9]+)/escalation_points/([0-9]+)/change")


def _allowed_milestones(report):
    if (report.get("cross_layer_pass") is not False or
            any(report.get(field) is not True for field in
                ("timeline_pass", "single_use_pass", "ending_causality_pass"))):
        raise CreativePause("plan_milestone_repair", "受限修复仅支持其他判据已通过的剧情弧节点错位")
    allowed = {}
    for issue in report["issues"]:
        points = {proof["path"]: MILESTONE_PATH.fullmatch(proof["path"])
                  for proof in issue["evidence"]}
        matches = {path: tuple(map(int, match.groups()))
                   for path, match in points.items() if match}
        if issue["code"] != "cross_layer" or not matches:
            raise CreativePause("plan_milestone_repair", "问题没有可安全局部修复的剧情弧节点证据")
        allowed.update(matches)
    return allowed


def _future_milestones(plan, allowed, locked):
    for arc, point in allowed.values():
        if int(plan.arcs[arc].escalation_points[point]["chapter_number"]) <= locked:
            raise CreativePause("plan_milestone_repair", "已完成或锁定的剧情弧节点不能受限重写")


def _apply_milestones(plan, result, allowed, context, locked):
    changes = result.get("changes") if isinstance(result, dict) else None
    if not isinstance(changes, list) or not changes or set(result) != {"changes"}:
        raise CreativePause("plan_milestone_protocol", "节点修复必须返回非空受限变更")
    revised, seen = deepcopy(plan), set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "before", "after", "chapter_number"}:
            raise CreativePause("plan_milestone_protocol", "节点修复字段无效")
        path, after, chapter = change["path"], change["after"], change["chapter_number"]
        if not isinstance(path, str) or path not in allowed or allowed[path] in seen:
            raise CreativePause("plan_milestone_protocol", "节点修复包含未引用或重复的修改")
        before = json.loads('"' + outline_leaf(context, path) + '"')
        if change["before"] != before or not isinstance(after, str) or not after.strip() or type(chapter) is not int:
            raise CreativePause("plan_milestone_protocol", "节点修复缺少一致的原文或有效章号")
        if chapter <= locked:
            raise CreativePause("plan_milestone_protocol", "剧情弧节点不能移入已完成或锁定范围")
        arc, point = allowed[path]
        revised["arcs"][arc]["escalation_points"][point].update(chapter_number=chapter, change=after)
        seen.add(allowed[path])
    if revised == plan:
        raise CreativePause("plan_milestone_protocol", "节点修复没有实际变更")
    return revised


def _validate_transition(state, revised):
    try:
        candidate = NovelPlan.from_dict(revised)
        candidate.assert_valid()
        errors = validate_plan_transition(
            NovelPlan.from_dict(state["novel_plan"]), candidate,
            int(state.get("current_chapter_index") or 0),
        )
        if errors:
            raise NovelPlanValidationError(errors)
    except (NovelPlanValidationError, ValueError, TypeError, KeyError) as exc:
        raise CreativePause("plan_milestone_protocol", "节点修复未通过计划及锁定范围校验") from exc
    return candidate


async def repair_plan_milestones(state, config):
    request = state["plan_replan_request"]
    proposal = state.get("pending_proposal") or {}
    source_id = request["repair_proposal_id"]
    previous = state.get("novel_plan") or {}
    if (state.get("author_mode") != "autonomous_v1" or proposal.get("kind") != "novel_plan"
            or proposal.get("proposal_id") != source_id
            or request.get("scope") != "future"
            or (state.get("plan_generation") or {}).get("expected_version") != request["expected_version"]
            or previous.get("version") != request["expected_version"]):
        raise CreativeConflict("节点修复提案或接受版本已变化")
    work = await workspace(config)
    plan = NovelPlan.from_dict(proposal["payload"]["plan"])
    if plan.scale != NovelPlan.from_dict(previous).scale:
        raise CreativeConflict("受限节点修复不能改变已接受规模")
    context = await _audit_context(work, state, plan, config)
    review = await work.latest("decision", "plan_consistency:" + source_id)
    if not review or review["input_versions"] != {"context_hash": content_hash(context)}:
        raise CreativeConflict("节点修复的完整复审输入已变化或缺失")
    if not _valid_report(review["payload"], context):
        raise CreativePause("plan_milestone_repair", "节点修复不能使用缺少精确原文证据的复审")
    allowed = _allowed_milestones(review["payload"])
    locked = int(state.get("current_chapter_index") or 0) + plan.scale.lock_window
    _future_milestones(plan, allowed, locked)
    inputs = {**review["input_versions"], "review_version": review["version"],
              "instruction_hash": content_hash(request["instruction"])}
    key = "plan_milestone_repair:" + source_id
    saved = await work.latest("decision", key)
    if saved is None:
        prompt = render_prompt(
            "creative/plan_milestone_repair_v1.txt", include_active_rules=False,
            context=context, report=json_text(review["payload"]), allowed=json_text(list(allowed)),
            instruction=request["instruction"], schema=json_text(SCHEMA), locked=locked,
        )
        result = await work.generate(prompt, SCHEMA, temperature=.1, max_attempts=1)
        saved = await work.save("decision", key, result, inputs=inputs)
    if saved["input_versions"] != inputs:
        raise CreativeConflict("节点修复输入已变化，不能复用旧修复")
    revised = _apply_milestones(plan.to_dict(), saved["payload"], allowed, context, locked)
    return _validate_transition(state, revised)
