"""Chapter rewrite state-machine tests."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langgraph.types import Command

from api.routers.novel_router import (
    _generate_rewritten_chapter,
    _rewrite_config,
    _rewrite_state,
)
from application.errors import QualityGateReviewRequired
from service.entities.chapter import Chapter
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.value_objects.progress import Progress


def _patch_rewrite_nodes(
    monkeypatch, writer, reflection, revision, persist, reconcile=None
):
    modules = {
        "application.agents.chapter_writer_node": ("chapter_writer_node", writer),
        "application.agents.reflection_node": ("reflection_node", reflection),
        "application.agents.revision_node": ("revision_node", revision),
        "application.agents.persist_node": ("persist_node", persist),
    }
    if reconcile is not None:
        modules["application.agents.novel_plan_node"] = (
            "plan_reconciliation_node",
            reconcile,
        )
    for module_name, (attribute, replacement) in modules.items():
        monkeypatch.setattr(
            importlib.import_module(module_name), attribute, replacement
        )


@pytest.mark.asyncio
async def test_rewrite_rechecks_revision_before_persist(monkeypatch):
    calls: list[str] = []

    async def writer(state, config):
        calls.append("writer")
        return Command(goto="router_agent", update={"current_chapter_content": "初稿"})

    async def reflection(state, config):
        calls.append("reflection")
        if calls.count("reflection") == 1:
            return Command(goto="revision_node", update={"reflection_issues": []})
        return Command(goto="persist_node")

    async def revision(state, config):
        calls.append("revision")
        return Command(
            goto="reflection_node",
            update={"current_chapter_content": "修订稿", "revision_attempts": 1},
        )

    async def persist(state, config):
        calls.append("persist")
        return Command(goto="progress_check_node", update={"saved": True})

    _patch_rewrite_nodes(monkeypatch, writer, reflection, revision, persist)

    state = await _generate_rewritten_chapter({}, {})

    assert calls == ["writer", "reflection", "revision", "reflection", "persist"]
    assert state["current_chapter_content"] == "修订稿"
    assert state["saved"] is True


@pytest.mark.asyncio
async def test_rewrite_rejects_non_converging_node_loop(monkeypatch):
    writer = AsyncMock(
        return_value=Command(
            goto="router_agent", update={"current_chapter_content": "初稿"}
        )
    )
    reflection = AsyncMock(return_value=Command(goto="revision_node"))
    revision = AsyncMock(return_value=Command(goto="reflection_node"))
    persist = AsyncMock(return_value=Command(goto="progress_check_node"))
    _patch_rewrite_nodes(monkeypatch, writer, reflection, revision, persist)

    with pytest.raises(HTTPException, match="超过最大修订次数"):
        await _generate_rewritten_chapter({}, {})

    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_returns_quality_gate_error_instead_of_interrupt_failure(monkeypatch):
    writer = AsyncMock(
        return_value=Command(
            goto="router_agent", update={"current_chapter_content": "初稿"}
        )
    )
    reflection = AsyncMock(side_effect=QualityGateReviewRequired("仍未通过质量门禁"))
    revision = AsyncMock()
    persist = AsyncMock()
    _patch_rewrite_nodes(monkeypatch, writer, reflection, revision, persist)

    with pytest.raises(HTTPException) as exc_info:
        await _generate_rewritten_chapter({}, {})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "quality_gate_not_met"


@pytest.mark.asyncio
async def test_rewrite_with_plan_reconciles_after_persist(monkeypatch):
    calls: list[str] = []

    async def writer(state, config):
        calls.append("writer")
        return Command(goto="router_agent", update={"current_chapter_content": "重写稿"})

    async def reflection(state, config):
        calls.append("reflection")
        return Command(goto="persist_node")

    async def persist(state, config):
        calls.append("persist")
        return Command(goto="plan_reconciliation_node", update={"saved": True})

    async def reconcile(state, config):
        calls.append("reconcile")
        return Command(goto="progress_check_node", update={"reconciled": True})

    _patch_rewrite_nodes(
        monkeypatch,
        writer,
        reflection,
        AsyncMock(),
        persist,
        reconcile,
    )
    repository = SimpleNamespace(
        mark_continuity_reconciliation_needed=AsyncMock()
    )
    config = {"configurable": {
        "novel_repository": repository,
        "tenant_id": "tenant-1",
        "novel_id": "novel-1",
    }}

    state = await _generate_rewritten_chapter(
        {"novel_plan": {"version": 1}}, config
    )

    assert calls == ["writer", "reflection", "persist", "reconcile"]
    assert state["saved"] is True
    assert state["reconciled"] is True
    repository.mark_continuity_reconciliation_needed.assert_awaited_once_with(
        "tenant-1", "novel-1"
    )


def test_rewrite_preserves_chapter_identity_and_following_chapters() -> None:
    chapter = Chapter(chapter_index=2, version=7, outline={"title": "旧章"})
    novel = Novel(novel_type="suspense", progress=Progress(current_chapter=6))

    state = _rewrite_state(novel, chapter, "run-1", "memory")
    context = TenantContext(
        tenant_id=chapter.id,
        tenant_name="测试租户",
        user_id=chapter.id,
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )
    orchestrator = type("Orchestrator", (), {
        "tenant_planning_loader": None,
        "_get_llm_instance": lambda self: object(),
    })()
    request = type("Request", (), {
        "app": type("App", (), {
            "state": type("State", (), {"memory_service": object()})()
        })()
    })()
    config = _rewrite_config(
        request, context, "novel-1", object(), object(), orchestrator
    )

    assert state["rewrite_chapter_id"] == str(chapter.id)
    assert state["rewrite_chapter_version"] == 7
    assert state["rewrite_chapter_created_at"] == chapter.created_at
    assert config["configurable"]["discard_following_chapters"] is False
