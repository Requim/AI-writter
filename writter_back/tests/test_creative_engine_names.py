"""Engine views retain original sources but use admitted character identities."""

from copy import deepcopy
import json

import pytest

from application.creative.artifacts import workspace
from application.creative.narrative import initialize_cast
from application.creative.recap import creative_recap_node
from tests.creative_fakes import CreativeRepositoryFake, creative_config


def state():
    roles = [{"character_id": "father", "name": "贺兰亭", "role_type": "core",
        "profile": {}, "source_name_binding": {"name": "陆守潮", "quote": "父亲陆守潮承担责任。"}}]
    return {"character_design": {"characters": roles},
        "total_outline": {"main_characters": deepcopy(roles)},
        "current_chapter_index": 5}


def engine():
    return {"conflict_mechanism": "陆守潮承担责任。", "sources": [{"text": "父亲陆守潮承担责任。"}]}


class RecapLLM:
    def __init__(self):
        self.engine_view = None

    async def structured_generate(self, prompt, schema, **kwargs):
        self.engine_view = json.loads(prompt.split("\n发动机：", 1)[1].split("\n正文：", 1)[0])
        return {"issues": [], "needs_replan": False, "instruction": "",
            "closed_reasonably": False, "changes_ending": False}


@pytest.mark.asyncio
async def test_initial_engine_uses_adopted_names_without_rewriting_accepted_selection():
    repo = CreativeRepositoryFake()
    work = await workspace(creative_config(repo, RecapLLM()))
    selection = await work.save("selection", "accepted", {"engine": engine(), "future_roles": []},
        status="accepted")
    await initialize_cast(work, state())
    saved = await work.latest("engine", "main")
    assert saved["payload"]["conflict_mechanism"] == "贺兰亭承担责任。"
    assert saved["payload"]["sources"] == [{"text": "父亲陆守潮承担责任。"}]
    assert await work.latest("selection", "accepted") == selection


@pytest.mark.asyncio
@pytest.mark.parametrize("current_name", [None, "秦明"])
async def test_recap_projects_legacy_engine_to_current_identity_without_mutating_history(current_name):
    repo, llm = CreativeRepositoryFake(), RecapLLM()
    config = creative_config(repo, llm)
    work = await workspace(config)
    original = await work.save("engine", "main", engine(), status="accepted")
    if current_name:
        await work.save("character", "father", {"name": current_name}, status="active")
    source = state()
    before = deepcopy(source)
    result = await creative_recap_node(source, config)
    assert result.goto == "creative_experiment_node"
    assert llm.engine_view["conflict_mechanism"] == f"{current_name or '贺兰亭'}承担责任。"
    assert llm.engine_view["sources"] == [{"text": "父亲陆守潮承担责任。"}]
    assert await work.latest("engine", "main") == original
    assert source == before


@pytest.mark.asyncio
async def test_engine_name_projection_cannot_rename_identity_fields():
    repo = CreativeRepositoryFake()
    work = await workspace(creative_config(repo, RecapLLM()))
    source = state()
    source["character_design"]["characters"][0]["character_id"] = "陆守潮"
    source["total_outline"]["main_characters"][0]["character_id"] = "陆守潮"
    payload = {**engine(), "character_ids": ["陆守潮"]}
    await work.save("selection", "accepted", {"engine": payload, "future_roles": []},
        status="accepted")
    await initialize_cast(work, source)
    saved = await work.latest("engine", "main")
    assert saved["payload"]["conflict_mechanism"] == "贺兰亭承担责任。"
    assert saved["payload"]["character_ids"] == ["陆守潮"]
    assert (await work.records("character"))[0]["key"] == "陆守潮"
