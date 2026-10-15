"""Real report validation and workflow boundaries; only the provider is doubled."""

from copy import deepcopy
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.persist_node import persist_node
from application.agents.reflection_node import _finish_review
from application.errors import StructuredOutputInvalidError

BODY = (
    "陈宁是外卖员，林雨是他分手三年的前女友。今晚她搬家，他来拿还寄存在她家的电动车钥匙。\n"
    "她把钥匙递给他：楼下的车已经卖了，欠的房租今天必须还。陈宁口袋里只有二百块。\n"
    "手机亮起：你可以改掉过去的一次选择，只剩七次。代价是她会忘掉你们的一段共同记忆。\n"
    "他想到那晚没接的电话，手指停在确认上。再改一次，她也许就不记得他了。"
)
OPAQUE_BODY = (
    "林先芸把四份打印件对齐，又检查了一遍投影线。张乔木将纸杯放在桌边。\n"
    "她点开待办事项，删掉了一行，又重新打上。空调吹得纸角翘起来。\n"
    "他看了一眼手机，把屏幕扣在桌上。她把笔推过去。他没有接。"
)


def api():
    return import_module("application.reader_comprehension")


def state(body=BODY, chapter=1):
    return {"reader_quality_version": 1, "novel_type": "romance",
            "current_chapter_index": chapter - 1, "current_chapter_content": body,
            "completed_chapters": [], "chapter_outlines": [{}], "total_outline": {},
            "revision_attempts": 0}


def report(body=BODY):
    quotes = [
        "陈宁是外卖员", "林雨是他分手三年的前女友",
        "他来拿还寄存在她家的电动车钥匙", "欠的房租今天必须还",
        "代价是她会忘掉你们的一段共同记忆",
    ]
    answers = ["陈宁，外卖员", "陈宁与林雨是前任", "拿回车钥匙", "车被卖了且房租到期",
               "改掉过去选择能解决眼前困境，却会失去共同记忆"]
    return {"checks": [{"key": key, "status": "clear", "answer": answer,
                       "evidence": [{"source": "current", "quote": quote}]}
                      for key, answer, quote in zip(
                          ("who", "relationship", "goal", "obstacle", "hook"), answers, quotes)],
            "issues": []}


def literary_report(body):
    return {"overall_quality_score": .99,
            "word_count_analysis": {"total_count": len(body), "effective_density": 95,
                                    "is_valid_word_count": True}, "issues": []}


@pytest.mark.asyncio
async def test_current_prose_passes_without_outline_leaking_into_blind_input():
    current = state()
    current["title"] = "不能泄露的书名"
    current["total_outline"] = {"story_background": "不能泄露的幕后真相"}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    receipt = await api().review_reader(llm, current, BODY)
    assert api().reader_archive_ready({**current, "reader_comprehension_receipt": receipt}, BODY)
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    assert BODY in prompt
    assert "不能泄露" not in prompt


@pytest.mark.asyncio
async def test_opaque_opening_blocks_high_literary_score():
    raw = {"checks": [
        {"key": key, "status": "unclear", "answer": "正文没有交代",
         "evidence": [{"source": "current", "quote": "林先芸把四份打印件对齐"}]}
        for key in ("who", "relationship", "goal", "obstacle", "hook")], "issues": []}
    current = state(OPAQUE_BODY)
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=raw))
    current["reader_comprehension_receipt"] = await api().review_reader(llm, current, OPAQUE_BODY)
    command = _finish_review(current, {"configurable": {"auto_mode": True}},
                             literary_report(OPAQUE_BODY), OPAQUE_BODY, 1)
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["score"] == .99
    assert command.update["quality_gate"]["reader_review_required"] is True
    assert command.update["reflection_issues"]
    assert not api().reader_archive_ready(current, OPAQUE_BODY)


@pytest.mark.asyncio
async def test_actual_legacy_opening_cannot_archive_with_incomprehension_and_high_score():
    body = (Path(__file__).parent / "fixtures/reader_first/legacy-opening.txt").read_text(
        encoding="utf-8").rstrip("\n")
    assert len(body) == 800
    quotes = ("通知上甲方对接人那一栏，宋体，三个字：章乔木。",
              "今天需要听她把时序讲清楚的那个人",
              "按议程顺序压平：签到、项目范围、节点、停运窗口、验收。",
              "她拔了线，换接口，再插。屏幕还是灰的。",
              "然后把纸杯往自己那边推了半寸，视线回到屏幕上。")
    raw = {"checks": [
        {"key": key, "status": "unclear" if key in ("obstacle", "hook") else "clear",
         "answer": "尚未呈现具体人的损失或吸引点" if key in ("obstacle", "hook") else "会议双方正在准备讲方案",
         "evidence": [{"source": "current", "quote": quote}]}
        for key, quote in zip(api().CHECKS, quotes)], "issues": []}
    current = state(body)
    current["reader_comprehension_receipt"] = await api().review_reader(
        SimpleNamespace(structured_generate=AsyncMock(return_value=raw)), current, body)
    command = _finish_review(current, {"configurable": {"auto_mode": True}},
                             literary_report(body), body, 1)
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["score"] == .99
    assert not api().reader_archive_ready(current, body)


@pytest.mark.asyncio
async def test_archive_checks_reader_receipt_before_fact_or_database_work(monkeypatch):
    current = state()
    facts = AsyncMock(side_effect=AssertionError("reader failure must stop archive"))
    monkeypatch.setattr(import_module("application.agents.persist_node"), "check_fact_artifact", facts)
    command = await persist_node(current, {"configurable": {}})
    assert command.goto == "reflection_node"


@pytest.mark.asyncio
async def test_cached_receipt_expires_on_body_prior_prose_or_report_change():
    current = state(chapter=2)
    current["completed_chapters"] = [{"chapter_index": 0, "content": BODY, "status": "completed"}]
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    receipt = await api().review_reader(llm, current, BODY)
    assert api().reader_receipt_valid(receipt, current, BODY)
    assert not api().reader_receipt_valid(receipt, current, BODY + "她走了。")
    changed = deepcopy(current)
    changed["completed_chapters"][0]["content"] += "他的工作变了。"
    assert not api().reader_receipt_valid(receipt, changed, BODY)
    receipt["report"]["checks"][0]["answer"] = "伪造结果"
    assert not api().reader_receipt_valid(receipt, current, BODY)


@pytest.mark.asyncio
async def test_invalid_evidence_is_corrected_once_and_then_stops():
    raw = report()
    raw["checks"][0]["evidence"][0]["quote"] = "书中不存在的人物介绍"
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=raw))
    with pytest.raises(StructuredOutputInvalidError):
        await api().review_reader(llm, state(), BODY)
    assert len(llm.structured_generate.call_args_list) == 2


@pytest.mark.asyncio
async def test_format_correction_cannot_turn_genuine_confusion_into_a_pass():
    invalid = report()
    invalid["checks"][0]["status"] = "unclear"
    invalid["checks"][0]["evidence"][0]["quote"] = "不存在的原文"
    llm = SimpleNamespace(structured_generate=AsyncMock(side_effect=[invalid, report()]))
    with pytest.raises(StructuredOutputInvalidError, match="不清楚"):
        await api().review_reader(llm, state(), BODY)
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_checks", [False, True])
async def test_format_correction_cannot_drop_a_blocking_reader_problem(missing_checks):
    invalid = report()
    invalid["issues"] = [{"kind": "clarity", "blocking": True, "reason": "当前目标不清楚",
                          "suggestion": "补清当前目标", "quote": "不存在的引文"}]
    if missing_checks:
        invalid.pop("checks")
    llm = SimpleNamespace(structured_generate=AsyncMock(side_effect=[invalid, report()]))
    with pytest.raises(StructuredOutputInvalidError, match="阻断"):
        await api().review_reader(llm, state(), BODY)
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_end_explanation_cannot_satisfy_first_500_character_identity():
    body = "纸杯放在桌边，纸角被空调吹起来。" * 45 + BODY
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    receipt = await api().review_reader(llm, state(body), body)
    assert not api().reader_archive_ready(
        {**state(body), "reader_comprehension_receipt": receipt}, body)


@pytest.mark.asyncio
async def test_later_chapter_checks_current_goal_without_inventing_an_800_character_deadline():
    body = "他们一路走到旧房门口。" * 90 + BODY
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    current = state(body, chapter=2)
    receipt = await api().review_reader(llm, current, body)
    assert api().reader_archive_ready({**current, "reader_comprehension_receipt": receipt}, body)


def test_legacy_and_later_chapters_do_not_require_new_receipt():
    assert api().reader_archive_ready({"reader_quality_version": 0}, BODY)
    assert api().reader_archive_ready(state(chapter=4), BODY)


def test_reader_uses_server_prompt_instead_of_client_or_old_writer_snapshot():
    from application.prompts.template_loader import set_prompt_snapshot, reset_prompt_snapshot
    token = set_prompt_snapshot({api().TEMPLATE: "CLIENT_ALWAYS_PASS_SENTINEL"})
    try:
        prompt = api().reader_prompt(state(), BODY)
        assert "CLIENT_ALWAYS_PASS_SENTINEL" not in prompt
        assert "当前正文" in prompt
    finally:
        reset_prompt_snapshot(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["status", "kind"])
async def test_malformed_nested_values_get_only_one_format_correction(field):
    raw = report()
    if field == "status":
        raw["checks"][0]["status"] = []
    else:
        raw["issues"] = [{"kind": [], "reason": "理由", "suggestion": "建议",
                          "blocking": True, "quote": "陈宁是外卖员"}]
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=raw))
    with pytest.raises(StructuredOutputInvalidError):
        await api().review_reader(llm, state(), BODY)
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_unchanged_checkpoint_reuses_paid_reader_receipt():
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    current = state()
    receipt = await api().review_reader(llm, current, BODY)
    current["reader_comprehension_receipt"] = receipt
    assert await api().review_reader(llm, current, BODY) == receipt
    assert llm.structured_generate.await_count == 1
    await api().review_reader(llm, current, BODY + "她走了。")
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_clear_answer_with_late_quote_gets_one_evidence_correction():
    body = BODY + "他们一起走下楼梯。" * 120 + "最后她彻底忘掉了这段感情。"
    raw = report()
    raw["checks"][4]["evidence"] = [{"source": "current", "quote": "最后她彻底忘掉了这段感情。"}]
    llm = SimpleNamespace(structured_generate=AsyncMock(side_effect=[raw, report()]))
    current = state(body)
    receipt = await api().review_reader(llm, current, body)
    assert api().reader_archive_ready({**current, "reader_comprehension_receipt": receipt}, body)
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_an_opening_name_quote_cannot_launder_a_late_identity_quote():
    body = BODY.replace("陈宁是外卖员", "陈宁走进门") + "纸杯放在桌边。" * 100 + "陈宁是外卖员"
    raw = report()
    raw["checks"][0]["evidence"].insert(0, {"source": "current", "quote": "陈宁走进门"})
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=raw))
    receipt = await api().review_reader(llm, state(body), body)
    assert not api().reader_archive_ready({**state(body), "reader_comprehension_receipt": receipt}, body)


@pytest.mark.asyncio
async def test_public_prior_prose_evidence_expires_after_previous_chapter_edit():
    from api.routers.novel_router import _chapter_review_fields
    prior = [{"chapter_index": 0, "content": BODY, "status": "completed"}]
    current = {**state(chapter=2), "reader_history": prior}
    raw = report()
    raw["checks"][0]["evidence"][0]["source"] = "chapter:1"
    receipt = await api().review_reader(SimpleNamespace(structured_generate=AsyncMock(return_value=raw)), current, BODY)
    chapter = SimpleNamespace(chapter_index=1, content=BODY, user_decision={
        "review_status": "passed", "quality_score": .9, "reader_comprehension": receipt})
    assert _chapter_review_fields(chapter, reader_history=prior)["reader_comprehension"]
    assert _chapter_review_fields(chapter)["reader_comprehension"] is None
    prior[0]["content"] = prior[0]["content"].replace("外卖员", "出租车司机")
    assert _chapter_review_fields(chapter, reader_history=prior)["reader_comprehension"] is None


def test_direct_rewrite_keeps_the_server_reader_version():
    from api.routers.novel_router import _rewrite_state
    from service.value_objects.outline import Outline
    novel = SimpleNamespace(total_outline=Outline(reader_quality_version=1),
                            novel_type="romance", title="书名", summary="简介")
    chapter = SimpleNamespace(chapter_index=0, outline={}, id="chapter", version=1, created_at=None)
    assert _rewrite_state(novel, chapter, "run", "")["reader_quality_version"] == 1


@pytest.mark.asyncio
async def test_archived_chapter_exposes_reader_evidence_but_edit_invalidates_it():
    from api.routers.novel_router import _chapter_review_fields
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report()))
    receipt = await api().review_reader(llm, state(), BODY)
    chapter = SimpleNamespace(content=BODY, user_decision={
        "review_status": "passed", "quality_score": .9, "reader_comprehension": receipt})
    assert _chapter_review_fields(chapter)["reader_comprehension"]["report"] == report()
    chapter.content += "她走了。"
    assert _chapter_review_fields(chapter)["reader_comprehension"] is None
