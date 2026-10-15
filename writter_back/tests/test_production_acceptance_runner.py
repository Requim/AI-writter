"""Acceptance retries use distinct books, never renewed exhausted counters."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind,chapters,words,suffix", [
    ("smoke-r3", 3, 12600, "·冒烟R3"),
    ("smoke-r4", 3, 12600, "·冒烟R4"),
    ("long", 80, 336000, "·长篇"),
    ("long-r2", 80, 336000, "·长篇R2"),
    ("long-r3", 80, 336000, "·长篇R3"),
])
def test_runner_creates_the_requested_bounded_book(monkeypatch, tmp_path, kind, chapters, words, suffix):
    path = Path(__file__).resolve().parents[2] / "scripts" / "production_acceptance.py"
    spec = importlib.util.spec_from_file_location("acceptance_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private = tmp_path / "private.json"
    private.write_text(json.dumps({"accounts": [{}], "books": {}}))
    monkeypatch.setattr(module, "PRIVATE", private)
    monkeypatch.setattr(module, "refreshed", lambda _: {})
    captured = []

    def api(method, path, session=None, payload=None, key=None, **_kwargs):
        if method == "GET":
            return {"enabled": True}
        captured.append((payload, key))
        return {"novel_id": "new-marked-book"}

    monkeypatch.setattr(module, "request", api)
    module.create_book(kind)
    payload, key = captured[0]
    assert payload["planning"]["target_chapters"] == chapters
    assert payload["planning"]["target_total_words"] == words
    assert payload["title"].endswith(suffix)
    assert payload["author_config"]["budget"] == {
        "preparation": 60, "chapter": 32, "search": 0, "preparation_search": 0}
    assert key == f"qa-20261001-create-{kind}"
    assert json.loads(private.read_text())["books"][kind] == {
        "id": "new-marked-book", "chapters": chapters, "words": words}


def test_known_copyediting_failure_cannot_be_marked_full_book_passed(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts" / "production_acceptance.py"
    spec = importlib.util.spec_from_file_location("acceptance_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private = tmp_path / "private.json"
    text = "她写：已查阅，一致性待复核。\n\n六个字。"
    private.write_text(json.dumps({
        "accounts": [{}, {}], "books": {"long": {"id": "book", "chapters": 1, "words": len(text)}},
    }))
    monkeypatch.setattr(module, "PRIVATE", private)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "refreshed", lambda _: {})

    def api(method, path, session=None, **_kwargs):
        if path.endswith("/progress"):
            return {"status": "completed", "current_chapter": 1}
        if path.endswith("/chapters"):
            return [{"id": "chapter", "chapter_index": 0}]
        if "/chapters/" in path:
            return {"content": text, "word_count": len(text), "status": "completed",
                    "review_status": "passed"}
        if path.endswith("/export"):
            return 404, b""
        pytest.fail("Export must not run after a known literary failure")

    monkeypatch.setattr(module, "request", api)
    with pytest.raises(AssertionError, match="copyediting"):
        module.verify_book("long")
