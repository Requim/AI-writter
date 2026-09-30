"""执行实际新节点的重放与故障边界；所有模型调用均为测试替身。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.creative.artifacts import workspace
from application.creative.development import _resume_inception_repair, creative_development_node
from application.creative.postprocess import creative_postprocess_node
from application.creative.runtime import PROSE_NODES, creative_node_scope, run_creative_node
from application.creative.patches import invalidate_patch
from tests.creative_fakes import CreativeRepositoryFake, creative_config


@pytest.mark.asyncio
async def test_inception_repair_resumes_missing_candidate_only(monkeypatch):
    repo = CreativeRepositoryFake()
    config = creative_config(repo, SimpleNamespace())
    work = await workspace(config)
    candidate = await work.save("candidate", "1", {"brief": {}})
    await work.save("decision", "inception_repair", {"candidate": 1, "input_version": 1})
    generate = AsyncMock()
    monkeypatch.setattr("application.creative.development._candidate", generate)
    assert await _resume_inception_repair(work, [candidate, None, None], {})
    generate.assert_awaited_once()
    repaired = await work.save("candidate", "1", {"brief": {"title": "改进"}}, previous=candidate)
    assert not await _resume_inception_repair(work, [repaired, None, None], {})
    assert generate.await_count == 1


@pytest.mark.asyncio
async def test_accepted_selection_never_regenerates_pilot():
    repo = CreativeRepositoryFake()
    llm = SimpleNamespace(structured_generate=AsyncMock(), generate=AsyncMock())
    config = creative_config(repo, llm)
    work = await workspace(config)
    await work.save("selection", "accepted", {
        "brief": {"tone": "克制"}, "narrative_mode": "stable", "engine": {}, "future_roles": [],
    }, status="accepted")
    result = await creative_development_node({}, config)
    assert result.goto == "genre_strategy_node"
    llm.generate.assert_not_awaited()
    llm.structured_generate.assert_not_awaited()
    assert not repo.archived


@pytest.mark.asyncio
async def test_persisted_body_redirects_before_any_generation():
    repo = CreativeRepositoryFake()
    repo.session["stage"] = "postprocess:6"
    config = creative_config(repo, SimpleNamespace())
    node = AsyncMock()
    state = {"author_mode": "autonomous_v1", "creative_session_id": repo.session["id"], "current_chapter_index": 5}
    result = await run_creative_node("persist_node", node, True, state, config)
    assert result.goto == "creative_postprocess_node"
    assert result.update["current_chapter_index"] == 6
    assert not result.update["is_completed"]
    node.assert_not_awaited()
    assert not repo.calls


@pytest.mark.asyncio
async def test_postprocess_receipt_skips_all_llm_calls():
    repo = CreativeRepositoryFake()
    repo.archived = [{"id": str(uuid4()), "version": 1, "chapter_index": 0, "content": "正文", "status": "completed"}]
    config = creative_config(repo, SimpleNamespace(structured_generate=AsyncMock()))
    work = await workspace(config)
    await work.save("postprocess", f"{repo.archived[0]['id']}:v1", {"chapter_number": 1}, status="completed")
    result = await creative_postprocess_node({"current_chapter_index": 1, "target_total_chapters": 6}, config)
    assert result.goto == "plan_reconciliation_node"
    assert result.update["creative_postprocessed_through"] == 1
    config["configurable"]["llm_config"]["llm_instance"].structured_generate.assert_not_awaited()
    assert repo.archived[0]["content"] == "正文"


@pytest.mark.asyncio
async def test_partial_postprocessing_retains_reader_result(monkeypatch):
    repo = CreativeRepositoryFake()
    repo.archived = [{"id": str(uuid4()), "version": 1, "chapter_index": 0, "content": "门开了。", "status": "completed"}]
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={"known": ["门开了"], "evidence": [{"start": 0, "quote": "门开了"}]}))
    config = creative_config(repo, llm)
    monkeypatch.setattr("application.creative.postprocess.initialize_cast", AsyncMock())
    monkeypatch.setattr("application.creative.postprocess._character_updates", AsyncMock())
    threads = AsyncMock(side_effect=[RuntimeError("断线"), None])
    monkeypatch.setattr("application.creative.postprocess.update_narrative_threads", threads)
    state = {"current_chapter_index": 1, "target_total_chapters": 6}
    with pytest.raises(RuntimeError, match="断线"):
        await creative_postprocess_node(state, config)
    await creative_postprocess_node(state, config)
    assert llm.structured_generate.await_count == 1
    assert len(await repo.records("", "", "reader_state")) == 1
    assert len(await repo.records("", "", "postprocess")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("node", sorted(PROSE_NODES))
async def test_all_prose_entrypoints_drop_author_truth(node):
    repo = CreativeRepositoryFake()
    config = creative_config(repo, SimpleNamespace())
    state = {
        "author_mode": "autonomous_v1", "creative_session_id": repo.session["id"],
        "character_design": {"secret": "绝密未来结局"}, "novel_plan": {"ending": "绝密未来结局"},
        "total_outline": {"main_characters": [{"character_id": "a", "name": "甲", "profile": {"secret": "绝密未来结局"}}]},
        "chapter_outlines": [{"scenes": [{"character_ids": ["a"], "allowed_information": ["门开了"], "secret": "绝密未来结局"}]}],
    }
    async with creative_node_scope(node, state, config) as (projected, _):
        assert "绝密未来结局" not in str(projected)
        assert projected["total_outline"]["main_characters"][0]["character_id"] == "a"
    assert state["novel_plan"]["ending"] == "绝密未来结局"


@pytest.mark.asyncio
async def test_invalid_patch_is_versioned_for_regeneration_not_treated_as_canon():
    repo = CreativeRepositoryFake()
    work = await workspace(creative_config(repo, SimpleNamespace()))
    patch = await work.save("decision", "character_patch:1:v1", {"updates": []})
    await invalidate_patch(work, patch, ValueError("错误原文位置"))
    latest = await work.latest("decision", patch["key"])
    assert latest["status"] == "invalid"
    assert latest["version"] == 2
    assert len(await work.records("decision")) == 2
    assert not await work.records("character")
