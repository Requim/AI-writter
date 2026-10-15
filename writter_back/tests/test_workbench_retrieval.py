"""Catch lost middle paragraphs, draft leakage and unbounded RAG context."""

import importlib

import pytest


def retrieval():
    try:
        return importlib.import_module("application.workbench.retrieval")
    except ModuleNotFoundError:
        pytest.fail("The workbench retrieval capability has not been implemented")


def test_chunks_preserve_exact_offsets_and_middle_paragraph():
    text = "开场。\n\n" + "日常。" * 400 + "\n\n师父答应归还青玉剑。\n\n结尾。"
    chunks = retrieval().chunk_text(text)
    assert any("归还青玉剑" in item["text"] for item in chunks)
    assert all(text[item["start"]:item["end"]] == item["text"] for item in chunks)
    assert max(len(item["text"]) for item in chunks) <= 1600


def test_related_old_chapter_beats_recent_unrelated_chapter():
    hits = [
        {"source_id": "old", "title": "师父的承诺", "text": "师父答应归还青玉剑。", "version": 1},
        {"source_id": "new", "title": "集市", "text": "街边卖鱼，众人散去。", "version": 2},
    ]
    ranked = retrieval().rank_sources("师父归还青玉剑", hits)
    assert [item["source_id"] for item in ranked] == ["old"]


def test_context_keeps_hard_settings_when_retrieval_budget_is_full():
    value = retrieval().assemble_context(
        ["主角失明，不可突然恢复视力。"],
        [{"text": "回忆" * 6000, "source_id": "one"}],
        explicit=["用户要求参考的草稿"],
    )
    assert "不可突然恢复视力" in value
    assert "用户要求参考的草稿" in value
    assert len(value) < 9000
