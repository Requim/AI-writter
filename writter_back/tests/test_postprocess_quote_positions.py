"""Archived state uses exact quotes, not model-estimated character counts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.creative.artifacts import workspace
from application.creative.evidence import verify_evidence
from application.creative.postprocess import _proofs, _reader_state
from tests.creative_fakes import CreativeRepositoryFake, creative_config


def chapter(content="索引页。\n原件在桌上。\n门关了。"):
    return {"id": str(uuid4()), "version": 2, "chapter_index": 0,
        "content": content, "status": "completed"}


def test_unique_exact_quote_overrides_model_estimated_offset():
    saved = chapter()
    proofs = _proofs([{"quote": "原件在桌上。", "start": 1500}], saved)
    assert (proofs[0].start, proofs[0].end, proofs[0].quote) == (5, 11, "原件在桌上。")
    verify_evidence(proofs[0], saved)


def test_ambiguous_quote_requires_correct_model_offset():
    saved = chapter("门开了。门开了。")
    with pytest.raises(ValueError):
        _proofs([{"quote": "门开了。", "start": 3}], saved)
    proof = _proofs([{"quote": "门开了。", "start": 4}], saved)[0]
    assert (proof.start, proof.end) == (4, 8)


def test_overlapping_quote_occurrences_retain_the_valid_disambiguating_offset():
    proof = _proofs([{"quote": "哈哈", "start": 1}], chapter("哈哈哈"))[0]
    assert (proof.start, proof.end) == (1, 3)


def test_overlapping_quote_occurrences_cannot_resolve_an_invalid_offset():
    with pytest.raises(ValueError):
        _proofs([{"quote": "哈哈", "start": 9}], chapter("哈哈哈"))


def test_quote_not_in_archived_body_never_becomes_evidence():
    with pytest.raises(ValueError):
        _proofs([{"quote": "原件已经烧毁。", "start": 5}], chapter())


def test_unique_quote_does_not_bypass_archive_or_version_validation():
    saved = chapter()
    proof = _proofs([{"quote": "原件在桌上。", "start": 1500}], saved)[0]
    with pytest.raises(ValueError):
        verify_evidence(proof, {**saved, "version": 3})
    with pytest.raises(ValueError):
        _proofs([{"quote": "原件在桌上。", "start": 1500}], {**saved, "status": "draft"})


@pytest.mark.asyncio
async def test_invalid_reader_response_remains_a_diagnostic_not_reader_truth():
    repo = CreativeRepositoryFake()
    raw = {"known": ["原件烧毁"], "evidence": [{"quote": "原件烧毁。", "start": 0}]}
    work = await workspace(creative_config(repo, SimpleNamespace(
        structured_generate=AsyncMock(return_value=deepcopy(raw)))))
    with pytest.raises(ValueError):
        await _reader_state(work, chapter(), 1)
    patch = await work.latest("decision", "reader_patch:1:v2")
    assert patch["status"] == "invalid"
    assert patch["payload"]["evidence"] == raw["evidence"]
    assert "validation_error" in patch["payload"]
    assert not await work.records("reader_state")


@pytest.mark.asyncio
async def test_reader_recovery_reuses_generated_response_after_storage_failure(monkeypatch):
    repo = CreativeRepositoryFake()
    raw = {"known": ["原件在桌上"], "evidence": [{"quote": "原件在桌上。", "start": 5}]}
    work = await workspace(creative_config(repo, SimpleNamespace(
        structured_generate=AsyncMock(return_value=deepcopy(raw)))))
    put = repo.put
    failed = False

    async def fail_reader_once(tenant, novel, record, **kwargs):
        nonlocal failed
        if record.kind == "reader_state" and not failed:
            failed = True
            raise RuntimeError("storage unavailable")
        return await put(tenant, novel, record, **kwargs)

    monkeypatch.setattr(repo, "put", fail_reader_once)
    saved = chapter()
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await _reader_state(work, saved, 1)
    assert await work.latest("decision", "reader_patch:1:v2")
    await _reader_state(work, saved, 1)
    assert len(await work.records("reader_state")) == 1
    assert work.llm.structured_generate.await_count == 1
    assert (await work.latest("decision", "reader_patch:1:v2"))["payload"] == raw
