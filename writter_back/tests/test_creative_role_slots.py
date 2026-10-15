"""Role windows are validated before selection and written atomically on recovery."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.creative.artifacts import workspace
from application.creative.development import _candidate
from application.creative.errors import CreativePause
from application.creative.narrative import _initialize_slots
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_creative_inception_contract import candidate_payload


def slot(start=1, end=3):
    return {"slot_id": "witness", "function": "提供缺失记录",
        "arc_ids": ["debt"], "entrance_start": start, "entrance_end": end}


@pytest.mark.asyncio
async def test_saved_selection_chapter_references_recover_without_rewriting_author_sources():
    repo = CreativeRepositoryFake(chapters=3)
    work = await workspace(creative_config(repo, None))
    selection = {"engine": {"conflict_nodes": []}, "future_roles": [slot("ch1", "ch3")]}
    original = deepcopy(selection)
    await _initialize_slots(work, selection)
    record = await work.latest("role_slot", "witness")
    saved = record["payload"]
    assert (saved["entrance_start"], saved["entrance_end"]) == (1, 3)
    assert selection == original
    assert record["status"] == "planned"
    assert saved["function"] == "提供缺失记录"


@pytest.mark.asyncio
async def test_candidate_normalizes_unambiguous_chapter_references_before_persistence():
    repo = CreativeRepositoryFake(chapters=3)
    result = {**candidate_payload(), "future_roles": [slot("ch1", "ch3")]}
    work = await workspace(creative_config(repo, SimpleNamespace(
        structured_generate=AsyncMock(return_value=result))))
    await _candidate(work, 1, [None] * 3, {"target_total_chapters": 3})
    roles = (await work.latest("candidate", "1"))["payload"]["future_roles"]
    assert (roles[0]["entrance_start"], roles[0]["entrance_end"]) == (1, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("roles", [
    [slot("ch1-ch3", 3)], [slot("maybe ch1", 3)], [slot(0, 3)],
    [slot(1, 4)], [slot(3, 1)], [slot(True, 3)], [slot(), slot()],
])
async def test_invalid_candidate_role_windows_never_enter_the_candidate_pool(roles):
    repo = CreativeRepositoryFake(chapters=3)
    work = await workspace(creative_config(repo, SimpleNamespace(structured_generate=AsyncMock(
        return_value={**candidate_payload(), "future_roles": roles}))))
    with pytest.raises(CreativePause):
        await _candidate(work, 1, [None] * 3, {"target_total_chapters": 3})
    assert not await work.records("candidate")


@pytest.mark.asyncio
async def test_invalid_saved_role_window_is_rejected_before_any_initialization_write():
    repo = CreativeRepositoryFake(chapters=3)
    work = await workspace(creative_config(repo, None))
    with pytest.raises(CreativePause):
        await _initialize_slots(work, {"engine": {}, "future_roles": [slot(1, 4)]})
    assert not repo.rows
