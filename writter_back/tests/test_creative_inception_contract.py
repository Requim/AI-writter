"""The inception model boundary preserves author intent and actual book scale."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.creative.artifacts import workspace
from application.creative.development import _candidate, _pilot_or_evaluation
from tests.creative_fakes import CreativeRepositoryFake, creative_config


def candidate_payload():
    return {
        "brief": {
            "tone": "克制",
            "setting_context": {"city": "江城"},
            "protagonist_drive": {"goal": "查清水债", "cost": "父亲名誉"},
            "reader_promise": {"experience": "线索可回溯"},
            "core_conflict": "救回街坊用水权",
        },
        "engine": {"conflict_nodes": [{"problem": "旧账即将销毁"}]},
        "narrative_mode": "stable",
        "future_roles": [],
    }


@pytest.mark.asyncio
async def test_candidate_receives_user_story_seed_not_just_empty_creative_brief():
    repo = CreativeRepositoryFake(chapters=3)
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=candidate_payload()))
    work = await workspace(creative_config(repo, llm))
    await _candidate(work, 1, [None, None, None], {
        "title": "潮汐账本", "summary": "档案员查清水债并救回街坊用水权",
        "novel_type": "suspense", "target_total_chapters": 3,
    })
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    assert "档案员查清水债并救回街坊用水权" in prompt
    assert "潮汐账本" in prompt
    assert (await work.latest("candidate", "1"))["payload"]["brief"]["core_conflict"] == "救回街坊用水权"


@pytest.mark.asyncio
async def test_independent_plan_uses_book_scale_without_request_budget():
    repo = CreativeRepositoryFake(chapters=3)
    repo.session["config"]["budget"]["chapter"] = 32
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "sustainability": 80, "repetition_risk": 20, "complexity": 50,
        "hard_constraints_pass": True, "issues": [],
    }))
    work = await workspace(creative_config(repo, llm))
    candidate = await work.save("candidate", "1", candidate_payload())
    await work.save("pilot", "1:v1", {"text": "正文" * 2000}, status="isolated")
    await work.save("evaluation", "blind:1:v1", {"quality_pass": True}, status="simulated")
    await _pilot_or_evaluation(work, [candidate], {
        "target_total_chapters": 3, "target_total_words": 12600,
    })
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    context = json.loads(prompt.split("评估输入JSON：\n", 1)[1])
    assert context["scale"] == {"target_chapters": 3, "target_total_words": 12600}
    assert "budget" not in context["author_constraints"]
    assert (await work.latest("evaluation", "plan:1:v1"))["payload"]["hard_constraints_pass"]


@pytest.mark.asyncio
async def test_isolated_pilot_has_motivation_and_reader_promise_without_future_truth():
    repo = CreativeRepositoryFake(chapters=3)
    llm = SimpleNamespace(generate=AsyncMock(return_value="门开了。" * 1000))
    work = await workspace(creative_config(repo, llm))
    payload = candidate_payload()
    payload["brief"]["secret_ending"] = "不得泄露的结局"
    candidate = await work.save("candidate", "1", payload)
    await _pilot_or_evaluation(work, [candidate], {"target_total_chapters": 3})
    prompt = llm.generate.call_args.args[0]
    assert "查清水债" in prompt and "父亲名誉" in prompt and "线索可回溯" in prompt
    assert "不得泄露的结局" not in prompt
    assert (await work.latest("pilot", "1:v1"))["status"] == "isolated"
    assert not repo.archived


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "quote", "model_pass", "reasons"), [
    ("门开了。" * 1000, "门……开了。", True, ["invalid_pilot_evidence"]),
    ("门开了。" * 1800, "门开了。", True, ["pilot_length_out_of_range"]),
    ("门开了。" * 1000, "门开了。", False, ["model_quality_rejected"]),
    ("门开了。" * 1000, "门开了。", True, []),
], ids=["paraphrased-evidence", "oversized-pilot", "model-rejection", "valid-review"])
async def test_blind_review_keeps_model_and_deterministic_rejection_reasons(
    text, quote, model_pass, reasons,
):
    repo = CreativeRepositoryFake(chapters=3)
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "continue_reading": 88, "clarity": 82, "payoff": 85,
        "quality_pass": model_pass, "evidence": [{"quote": quote}], "issues": [],
    }))
    work = await workspace(creative_config(repo, llm))
    candidate = await work.save("candidate", "1", candidate_payload())
    await work.save("pilot", "1:v1", {"text": text}, status="isolated")
    await _pilot_or_evaluation(work, [candidate], {"target_total_chapters": 3})
    result = (await work.latest("evaluation", "blind:1:v1"))["payload"]
    assert result["model_quality_pass"] is model_pass
    assert result["validation_issues"] == reasons
    assert result["quality_pass"] is (not reasons)
    assert not repo.archived


@pytest.mark.asyncio
async def test_new_pilot_incomprehension_cannot_be_outvoted_by_high_scores():
    from tests.test_reader_comprehension import OPAQUE_BODY, report
    text = OPAQUE_BODY + "杯子放在桌上。" * 500
    reader = report()
    for check in reader["checks"]:
        check.update(status="unclear", answer="不清楚人物要做什么",
                     evidence=[{"source": "current", "quote": "林先芸把四份打印件对齐"}])
    repo = CreativeRepositoryFake(chapters=3)
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "continue_reading": 99, "clarity": 99, "payoff": 99, "quality_pass": True,
        "evidence": [{"quote": "林先芸把四份打印件对齐"}], "issues": [],
        "reader_report": reader,
    }))
    work = await workspace(creative_config(repo, llm))
    candidate = await work.save("candidate", "1", candidate_payload())
    await work.save("pilot", "1:v1", {"text": text}, status="isolated")
    await _pilot_or_evaluation(work, [candidate], {"reader_quality_version": 1, "novel_type": "romance"})
    result = (await work.latest("evaluation", "blind:1:v1"))["payload"]
    assert result["quality_pass"] is False
    assert "reader_comprehension_failed" in result["validation_issues"]
    assert result["reader_comprehension_receipt"]["report"]["checks"][0]["status"] == "unclear"
    assert not repo.archived


@pytest.mark.asyncio
async def test_blind_format_correction_cannot_change_original_quality_rejection():
    from copy import deepcopy
    from application.creative.development import _blind_pilot
    from application.creative.errors import CreativePause
    from tests.test_reader_comprehension import BODY, report
    raw = {"continue_reading": 60, "clarity": 60, "payoff": 60, "quality_pass": False,
           "evidence": [{"quote": "陈宁是外卖员"}], "issues": [], "reader_report": report()}
    corrected = deepcopy(raw)
    raw["reader_report"]["checks"][0]["evidence"][0]["quote"] = "不存在的原文"
    corrected["quality_pass"] = True
    repo = CreativeRepositoryFake(chapters=3)
    work = await workspace(creative_config(repo, SimpleNamespace(
        structured_generate=AsyncMock(side_effect=[raw, corrected]))))
    with pytest.raises(CreativePause, match="报告格式"):
        await _blind_pilot(work, {"reader_quality_version": 1}, BODY)
    invalid = [row for row in await work.records("evaluation") if row["status"] == "invalid"]
    assert len(invalid) == 1 and len(invalid[0]["payload"]["attempts"]) == 2


@pytest.mark.asyncio
async def test_pilot_uses_server_outer_template_and_binds_complete_review_contract(monkeypatch):
    from application.creative.development import _blind_pilot
    from application import reader_comprehension as reader
    from application.prompts.template_loader import set_prompt_snapshot, reset_prompt_snapshot
    from tests.test_reader_comprehension import BODY, report
    raw = {"continue_reading": 88, "clarity": 88, "payoff": 88, "quality_pass": True,
           "evidence": [{"quote": "陈宁是外卖员"}], "issues": [], "reader_report": report()}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=raw))
    work = await workspace(creative_config(CreativeRepositoryFake(chapters=3), llm))
    current = {"reader_quality_version": 1, "current_chapter_index": 0, "reader_history": []}
    token = set_prompt_snapshot({"creative/blind_review.txt": "CLIENT_HIDDEN_TRUTH $text"})
    try:
        result = await _blind_pilot(work, current, BODY)
    finally:
        reset_prompt_snapshot(token)
    assert "CLIENT_HIDDEN_TRUTH" not in llm.structured_generate.call_args.kwargs["prompt"]
    receipt = result["reader_comprehension_receipt"]
    assert reader.reader_receipt_valid(receipt, current, BODY, scope="pilot")
    assert not reader.reader_receipt_valid(receipt, current, BODY)
    original = reader._server_template
    monkeypatch.setattr(reader, "_server_template", lambda name=reader.TEMPLATE:
                        original(name) + ("changed" if name == "creative/blind_review.txt" else ""))
    assert not reader.reader_receipt_valid(receipt, current, BODY, scope="pilot")
