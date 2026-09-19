from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.archive_metrics import refresh_archived_word_counts


@pytest.mark.asyncio
async def test_rewritten_archive_replaces_stale_size_without_mutating_checkpoint():
    reader = AsyncMock(return_value=[{"chapter_index": 4, "word_count": 4346}])
    state = {"completed_chapters": [{"chapter_index": 4, "word_count": 6880, "title": "retained"}]}
    config = {"configurable": {"tenant_id": "tenant", "novel_id": "novel",
                              "novel_repository": SimpleNamespace(completed_chapter_word_counts=reader)}}
    result = await refresh_archived_word_counts(state, config)
    assert result["completed_chapters"] == [{"chapter_index": 4, "word_count": 4346, "title": "retained"}]
    assert state["completed_chapters"][0]["word_count"] == 6880
    reader.assert_awaited_once_with("tenant", "novel")


@pytest.mark.asyncio
async def test_missing_archives_cannot_be_counted_from_old_checkpoint():
    reader = AsyncMock(return_value=[])
    config = {"configurable": {"tenant_id": "tenant", "novel_id": "novel",
                              "novel_repository": SimpleNamespace(completed_chapter_word_counts=reader)}}
    result = await refresh_archived_word_counts({"completed_chapters": [{"chapter_index": 0, "word_count": 5000}]}, config)
    assert result["completed_chapters"] == []


@pytest.mark.asyncio
async def test_archive_read_failure_does_not_silently_use_stale_counts():
    reader = AsyncMock(side_effect=RuntimeError("database unavailable"))
    config = {"configurable": {"tenant_id": "tenant", "novel_id": "novel",
                              "novel_repository": SimpleNamespace(completed_chapter_word_counts=reader)}}
    with pytest.raises(RuntimeError, match="database unavailable"):
        await refresh_archived_word_counts({}, config)


@pytest.mark.asyncio
async def test_isolated_workflows_without_archive_repository_keep_state():
    state = {"completed_chapters": []}
    assert await refresh_archived_word_counts(state, {}) is state
