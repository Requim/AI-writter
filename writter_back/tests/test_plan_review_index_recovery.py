"""Repair only unambiguous adjacent event indices, never semantic verdicts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.novel_plan_node import novel_plan_review_node
from application.creative.artifacts import json_text, workspace
from application.creative.errors import CreativePause
from application.creative.evidence import content_hash
from application.proposals import proposal_update
from tests.test_plan_consistency_audit import _conflict, _fixture


async def _saved_bad_index(case=None):
    repo, llm, cfg, plan, state = _fixture()
    report = _conflict(plan)
    plan.chapter_slots[27].must_happen.append("七日鉴定完成")
    quote = "最终期限当天重新启动七日鉴定。"
    plan.chapter_slots[62].must_happen = [quote, "摘要提到旧年度表决。"]
    report["issues"][0]["evidence"][1] = {
        "path": "/plan/chapter_slots/62/must_happen/1", "quote": quote,
    }
    if case in {"unique_substring", "duplicate_elsewhere", "same_event_repeat"}:
        plan.chapter_slots[62].must_happen[0] = "她找到当事人，" + quote
    if case == "duplicate_elsewhere":
        plan.chapter_slots[30].must_happen = ["现场复述：" + quote]
    if case == "same_event_repeat":
        plan.chapter_slots[62].must_happen[0] += quote
    if case == "duplicate":
        plan.chapter_slots[62].must_happen.append(quote)
    if case == "nonadjacent":
        plan.chapter_slots[62].must_happen.append("核对旧档。")
        report["issues"][0]["evidence"][1]["path"] = "/plan/chapter_slots/62/must_happen/2"
    if case == "ambiguous_fragment":
        report["issues"][0]["evidence"][1]["quote"] = "七日鉴定"
    if case == "other_chapter":
        plan.chapter_slots[61].must_happen = ["档案比对。", "继续核对旧表决。"]
        report["issues"][0]["evidence"][1]["path"] = "/plan/chapter_slots/61/must_happen/1"
    if case == "noncanonical_index":
        report["issues"][0]["evidence"][1]["path"] = "/plan/chapter_slots/62/must_happen/01"
    if case == "object":
        report["issues"][0]["evidence"][1]["path"] = "/plan/chapter_slots/62"
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    work = await workspace(cfg)
    context = json_text({
        "plan": plan.to_dict(), "previous_plan": {}, "completed_chapters": 0,
        "author_constraints": {key: value for key, value in work.session["config"].items()
                               if key not in {"budget", "research_queries", "sources"}},
        "characters": [], "story_engine": {},
    })
    await work.save("decision", "plan_consistency:" + state["pending_proposal"]["proposal_id"],
                    report, status="reviewed", inputs={"context_hash": content_hash(context)})
    repo.session["counters"] = {"preparation": 28}
    accept = AsyncMock()
    cfg["configurable"]["novel_repository"] = SimpleNamespace(accept_plan=accept)
    return repo, llm, cfg, state, report, accept


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [None, "unique_substring"])
async def test_cached_wrong_event_index_routes_real_plan_repair_without_rerunning_review(case):
    repo, llm, cfg, state, report, accept = await _saved_bad_index(case)
    before = deepcopy(state)
    command = await novel_plan_review_node(state, cfg)
    assert command.goto == "novel_plan_initialize_node"
    assert command.update["plan_generation"] is None
    assert command.update["pending_proposal"] is None
    assert "重新启动七日鉴定" in command.update["plan_feedback"]
    reviews = [row for row in repo.rows if row["key"].startswith("plan_consistency:")]
    assert len(reviews) == 2
    assert reviews[0]["payload"] == report and reviews[0]["source"] == "model"
    located = reviews[1]
    assert located["source"] == "system" and located["version"] == 2
    assert located["input_versions"] == reviews[0]["input_versions"]
    expected = deepcopy(report)
    expected["issues"][0]["evidence"][1]["path"] = "/plan/chapter_slots/62/must_happen/0"
    assert {key: located["payload"][key] for key in report} == expected
    assert located["payload"]["timeline_pass"] is False
    assert state == before and repo.session["counters"] == {"preparation": 28}
    replay = await novel_plan_review_node(state, cfg)
    assert replay.update == command.update and len(repo.rows) == 3
    llm.structured_generate.assert_not_awaited()
    accept.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "duplicate", "nonadjacent", "ambiguous_fragment", "other_chapter",
    "noncanonical_index", "object", "duplicate_elsewhere", "same_event_repeat",
])
async def test_event_index_recovery_cannot_guess_or_relax_review_evidence(case):
    repo, llm, cfg, state, report, accept = await _saved_bad_index(case)
    before = deepcopy(state)
    with pytest.raises(CreativePause, match="精确"):
        await novel_plan_review_node(state, cfg)
    assert len(repo.rows) == 1 and repo.rows[0]["payload"] == report
    assert state == before and repo.session["counters"] == {"preparation": 28}
    llm.structured_generate.assert_not_awaited()
    accept.assert_not_awaited()
