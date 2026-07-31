"""Chapter rewrite state-machine tests."""

import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langgraph.types import Command

from api.routers.novel_router import _generate_rewritten_chapter


def _patch_rewrite_nodes(monkeypatch, writer, reflection, revision, persist):
    modules = {
        "application.agents.chapter_writer_node": ("chapter_writer_node", writer),
        "application.agents.reflection_node": ("reflection_node", reflection),
        "application.agents.revision_node": ("revision_node", revision),
        "application.agents.persist_node": ("persist_node", persist),
    }
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
