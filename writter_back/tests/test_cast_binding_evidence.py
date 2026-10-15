"""A rejected cast assignment stays inspectable without changing character cards."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.creative.artifacts import workspace
from application.creative.cast import align_cast_to_plan
from application.creative.errors import CreativePause
from service.value_objects.creative import CharacterNarrative
from tests.creative_fakes import CreativeRepositoryFake, creative_config


@pytest.mark.asyncio
async def test_rejected_binding_is_retained_without_applying_partial_duties():
    repo = CreativeRepositoryFake()
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "characters": [{"character_id": "wrong", "arc_duties": []}], "slots": [],
    }))
    work = await workspace(creative_config(repo, llm))
    card = CharacterNarrative(character_id="admitted", name="Reader", role="core")
    await work.save("character", "admitted", card.model_dump(mode="json"), source="system")
    original = deepcopy(repo.rows[0])
    with pytest.raises(CreativePause, match="逐一覆盖"):
        await align_cast_to_plan(work, {"novel_plan": {"version": 1, "arcs": [{"arc_id": "main"}]}})
    failures = [r for r in repo.rows if r["key"].startswith("cast_plan_failed:")]
    assert len(failures) == 1 and failures[0]["payload"] == llm.structured_generate.return_value
    assert failures[0]["status"] == "rejected" and failures[0]["source"] == "model"
    assert failures[0]["input_versions"] == {"plan": 1, "characters": '["admitted"]', "slots": "[]"}
    assert repo.rows[0] == original and len([r for r in repo.rows if r["kind"] == "character"]) == 1
    assert not [r for r in repo.rows if r["key"].startswith("cast_plan:")]
    assert repo.session["counters"] == {}


@pytest.mark.asyncio
async def test_binding_assignment_exposes_story_ids_without_competing_archive_ids():
    repo = CreativeRepositoryFake()
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "characters": [{"character_id": "wrong", "arc_duties": []}], "slots": [],
    }))
    work = await workspace(creative_config(repo, llm))
    card = CharacterNarrative(character_id="admitted", name="Reader", role="core")
    record = await work.save("character", "admitted", card.model_dump(mode="json"), source="system")
    with pytest.raises(CreativePause):
        await align_cast_to_plan(work, {"reader_quality_version": 1,
                                      "novel_plan": {"version": 1, "arcs": [{"arc_id": "main"}]}})
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    assert '"character_id":"admitted"' in prompt
    assert record["id"] not in prompt
