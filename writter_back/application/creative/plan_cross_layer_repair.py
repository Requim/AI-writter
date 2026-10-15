"""Evidence-bound initial candidate edits, never an alternative acceptance gate."""

import re
from copy import deepcopy

from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativeConflict, CreativePause
from application.creative.evidence import content_hash
from application.creative.plan_consistency import _audit_context, _valid_report
from application.fact_evidence import literal_leaf_catalog
from application.prompts.template_loader import render_prompt
from service.value_objects.novel_plan import NovelPlan, NovelPlanValidationError

INDEX = r"(0|[1-9][0-9]*)"
EVENT = re.compile(r"/plan/chapter_slots/" + INDEX + r"/must_happen/" + INDEX)
DELTA = re.compile(r"/plan/chapter_slots/" + INDEX + r"/planned_state_delta")
ARC = re.compile(r"/plan/arcs/" + INDEX + r"/escalation_points/" + INDEX + r"/change")
ENDING = re.compile(r"/plan/volumes/" + INDEX + r"/ending_state")
SCHEMA = {"changes": [{"path": "string", "before": "string", "after": "string"}]}


def initial_cross_layer_intent(request):
    return (request.get("repair_mode") == "cross_layer"
            and request.get("expected_version") == 0 and request.get("scope") == "future"
            and bool(request.get("repair_proposal_id")))


def initial_cross_layer_base(state, request):
    proposal, generation = state.get("pending_proposal") or {}, state.get("plan_generation") or {}
    return (initial_cross_layer_intent(request) and state.get("author_mode") == "autonomous_v1"
            and not state.get("novel_plan") and int(state.get("current_chapter_index") or 0) == 0
            and proposal.get("kind") == "novel_plan"
            and proposal.get("proposal_id") == request["repair_proposal_id"]
            and generation.get("mode") == "initial" and generation.get("expected_version") == 0)


def _field_location(plan, path):
    match = EVENT.fullmatch(path)
    if match:
        slot, event = map(int, match.groups())
        return ("chapter_slots", slot, "must_happen", event), plan["chapter_slots"][slot]["chapter_number"]
    match = DELTA.fullmatch(path)
    if match:
        slot = int(match[1])
        return ("chapter_slots", slot, "planned_state_delta"), plan["chapter_slots"][slot]["chapter_number"]
    match = ARC.fullmatch(path)
    if match:
        arc, point = map(int, match.groups())
        return ("arcs", arc, "escalation_points", point, "change"), (
            plan["arcs"][arc]["escalation_points"][point]["chapter_number"]
        )
    match = ENDING.fullmatch(path)
    if match:
        volume = int(match[1])
        return ("volumes", volume, "ending_state"), plan["volumes"][volume]["end_chapter"]
    raise CreativePause("plan_cross_layer_repair", "复审包含不支持受限修复的证据字段")


def _issue_fields(plan, issue, locked):
    if issue["code"] != "cross_layer":
        raise CreativePause("plan_cross_layer_repair", "受限跨层修复不支持其他问题类型")
    cited = {proof["path"]: _field_location(plan, proof["path"]) for proof in issue["evidence"]}
    chapters = {chapter for _, chapter in cited.values()}
    if len(chapters) < 2:
        raise CreativePause("plan_cross_layer_repair", "跨层修复缺少不同事件章节的精确证据")
    earliest = min(chapters)
    allowed = {path: route for path, (route, chapter) in cited.items()
               if chapter > max(earliest, locked)}
    for path in tuple(allowed):
        match = DELTA.fullmatch(path)
        if match:
            slot = int(match[1])
            for index in range(len(plan["chapter_slots"][slot]["must_happen"])):
                allowed[f"/plan/chapter_slots/{slot}/must_happen/{index}"] = (
                    "chapter_slots", slot, "must_happen", index,
                )
    if not allowed:
        raise CreativePause("plan_cross_layer_repair", "没有可改写的后续未锁定事件")
    return allowed


def _allowed_fields(plan, report, locked):
    if (report.get("cross_layer_pass") is not False or any(
            report.get(field) is not True
            for field in ("timeline_pass", "single_use_pass", "ending_causality_pass"))):
        raise CreativePause("plan_cross_layer_repair", "跨层修复要求其他完整复审判据已通过")
    groups = [_issue_fields(plan, issue, locked) for issue in report["issues"]]
    return {path: route for group in groups for path, route in group.items()}, groups


def _apply_fields(plan, result, allowed, groups, catalog):
    changes = result.get("changes") if isinstance(result, dict) else None
    if not isinstance(changes, list) or not changes or set(result) != {"changes"}:
        raise CreativePause("plan_cross_layer_protocol", "跨层修复必须返回非空受限变更")
    revised, seen = deepcopy(plan), set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "before", "after"}:
            raise CreativePause("plan_cross_layer_protocol", "跨层修复字段无效")
        path, after = change["path"], change["after"]
        if not isinstance(path, str) or path not in allowed or path in seen:
            raise CreativePause("plan_cross_layer_protocol", "跨层修复包含未授权或重复字段")
        if (change["before"] != catalog[path] or not isinstance(after, str)
                or not after.strip() or after == change["before"]):
            raise CreativePause("plan_cross_layer_protocol", "跨层修复缺少一致原文或实际变更")
        route, target = allowed[path], revised
        for part in route[:-1]:
            target = target[part]
        target[route[-1]] = after
        seen.add(path)
    if any(not seen.intersection(group) for group in groups):
        raise CreativePause("plan_cross_layer_protocol", "跨层修复遗漏复审问题")
    return revised


def _validated_candidate(revised):
    try:
        plan = NovelPlan.from_dict(revised)
        plan.assert_valid()
    except (NovelPlanValidationError, ValueError, TypeError, KeyError) as exc:
        raise CreativePause("plan_cross_layer_protocol", "跨层修复未通过整书结构校验") from exc
    return plan


async def _saved_patch(work, request, context, review, allowed):
    inputs = {**review["input_versions"], "review_version": review["version"],
              "instruction_hash": content_hash(request["instruction"]),
              "allowed_hash": content_hash(json_text(sorted(allowed)))}
    key = "plan_cross_layer_repair:" + request["repair_proposal_id"]
    saved = await work.latest("decision", key)
    if saved is None:
        prompt = render_prompt(
            "creative/plan_cross_layer_repair_v1.txt", include_active_rules=False,
            context=context, report=json_text(review["payload"]), allowed=json_text(list(allowed)),
            instruction=request["instruction"], schema=json_text(SCHEMA),
        )
        result = await work.generate(prompt, SCHEMA, temperature=.1, max_attempts=1)
        saved = await work.save("decision", key, result, inputs=inputs)
    if saved["input_versions"] != inputs:
        raise CreativeConflict("跨层修复输入已变化，不能复用旧修复")
    return saved["payload"]


async def repair_initial_cross_layer(state, config):
    request = state["plan_replan_request"]
    if not initial_cross_layer_base(state, request):
        raise CreativeConflict("初始跨层修复提案、版本或已完成范围已变化")
    plan = NovelPlan.from_dict(state["pending_proposal"]["payload"]["plan"])
    plan.assert_valid()
    if plan.version != 0 or plan.scale.to_dict() != state.get("scale_contract"):
        raise CreativeConflict("初始跨层修复不能改变规模或引用已接受版本")
    work = await workspace(config)
    context = await _audit_context(work, state, plan, config)
    review = await work.latest("decision", "plan_consistency:" + request["repair_proposal_id"])
    if not review or review["input_versions"] != {"context_hash": content_hash(context)}:
        raise CreativeConflict("跨层修复的完整复审输入已变化或缺失")
    if not _valid_report(review["payload"], context):
        raise CreativePause("plan_cross_layer_repair", "跨层修复缺少完整有效的原文证据")
    allowed, groups = _allowed_fields(plan.to_dict(), review["payload"], plan.scale.lock_window)
    result = await _saved_patch(work, request, context, review, allowed)
    revised = _apply_fields(plan.to_dict(), result, allowed, groups, literal_leaf_catalog(context))
    return _validated_candidate(revised)
