"""Postprocess metadata cites server-indexed prose and repairs bounded proposals."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest

from application.creative.artifacts import workspace
from application.creative.errors import CreativePause
from application.creative.postprocess import _proofs, _character_updates
from application.creative.threads import update_narrative_threads
from service.value_objects.creative import CharacterNarrative, Foreshadow
from tests.creative_fakes import CreativeRepositoryFake, creative_config


def chapter(content="门开了。\r\n\r\n门开了。"):
    return {"id": str(uuid4()), "version": 1, "chapter_index": 0,
        "content": content, "status": "completed"}


def test_paragraph_reference_disambiguates_repeated_text_without_model_offsets():
    proof = _proofs([{"evidence_start": "p2", "evidence_end": "p2"}], chapter())[0]
    assert (proof.start, proof.end, proof.quote) == (8, 12, "门开了。")


def test_paragraph_reference_can_resolve_an_exact_fragment_within_its_scope():
    proof = _proofs([{"evidence_start": "p2", "evidence_end": "p2",
        "quote": "开了", "start": 999}], chapter())[0]
    assert (proof.start, proof.end, proof.quote) == (9, 11, "开了")


@pytest.mark.parametrize("reference", [
    {"evidence_start": "p9", "evidence_end": "p9"},
    {"evidence_start": "p2", "evidence_end": "p1"},
    {"evidence_start": "p1", "evidence_end": None},
    {"evidence_start": "p1", "evidence_end": "p1", "quote": "窗开了。"},
])
def test_invalid_reference_cannot_fall_back_to_an_unrelated_valid_quote(reference):
    with pytest.raises(ValueError):
        _proofs([reference], chapter())


class MetadataLLM:
    def __init__(self, responses):
        self.responses = responses
        self.prompts = []
        self.kwargs = []

    async def structured_generate(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        self.kwargs.append(kwargs)
        return deepcopy(self.responses[min(len(self.prompts) - 1, len(self.responses) - 1)])


async def thread_workspace(responses):
    repo = CreativeRepositoryFake()
    llm = MetadataLLM(responses)
    work = await workspace(creative_config(repo, llm))
    await work.save("foreshadow", "f1", Foreshadow(foreshadow_id="f1",
        description="门后的线索", origin="planned").model_dump(mode="json"), status="planned")
    return work


def thread_change(evidence, status="seeded"):
    return {"updates": [{"kind": "foreshadow", "key": "f1",
        "changes": {"status": status}, "evidence": evidence}]}


@pytest.mark.asyncio
async def test_thread_metadata_repairs_once_and_keeps_the_rejected_proposal():
    bad = thread_change([{"quote": "门开了。", "start": 999}])
    good = thread_change([{"evidence_start": "p2", "evidence_end": "p2"}])
    work = await thread_workspace([bad, good])
    saved = chapter()
    await update_narrative_threads(work, saved, 1, _proofs)
    record = await work.latest("foreshadow", "f1")
    assert record["status"] == "seeded"
    assert record["evidence"][0]["start"] == 8
    rejected = [row for row in await work.records("decision") if row["status"] == "invalid"]
    assert len(rejected) == 1 and rejected[0]["payload"]["updates"] == bad["updates"]
    assert len(work.llm.prompts) == 2
    assert all(kwargs.get("max_attempts") == 1 for kwargs in work.llm.kwargs)
    assert saved["content"] == "门开了。\r\n\r\n门开了。"


@pytest.mark.asyncio
async def test_invalid_metadata_stops_after_two_attempts_without_canon_writes():
    work = await thread_workspace([thread_change([{"quote": "门开了。", "start": 999}])])
    with pytest.raises(ValueError):
        await update_narrative_threads(work, chapter(), 1, _proofs)
    assert (await work.latest("foreshadow", "f1"))["status"] == "planned"
    assert len(work.llm.prompts) == 2
    assert len([r for r in await work.records("decision") if r["status"] == "invalid"]) == 2


@pytest.mark.asyncio
async def test_invalid_foreshadow_enum_is_regenerated_not_silently_normalized():
    evidence = [{"quote": "线索出现了。", "start": 0}]
    work = await thread_workspace([
        thread_change(evidence, "planted"), thread_change(evidence, "seeded")])
    await update_narrative_threads(work, chapter("线索出现了。"), 1, _proofs)
    assert (await work.latest("foreshadow", "f1"))["status"] == "seeded"
    assert any(r["status"] == "invalid" and r["payload"]["updates"][0]["changes"]["status"] == "planted"
        for r in await work.records("decision"))
    values = json.loads(work.llm.prompts[0].split("FORESHADOW_STATUS_VALUES:\n", 1)[1].split("\n\n", 1)[0])
    assert values == ["planned", "seeded", "reinforced", "partial", "completed"]
    catalog = json.loads(work.llm.prompts[0].split("SOURCE_PARAGRAPHS:\n", 1)[1])
    assert catalog == [{"id": "p1", "text": "线索出现了。"}]


@pytest.mark.asyncio
async def test_foreshadow_unknown_character_is_rejected_before_metadata_repair():
    evidence = [{"quote": "线索出现了。", "start": 0}]
    bad = thread_change(evidence)
    bad["updates"][0]["changes"]["character_ids"] = ["not-admitted"]
    good = thread_change(evidence)
    good["updates"][0]["changes"]["character_ids"] = []
    work = await thread_workspace([bad, good])
    await update_narrative_threads(work, chapter("线索出现了。"), 1, _proofs)
    saved = await work.latest("foreshadow", "f1")
    assert saved["payload"]["character_ids"] == []
    assert len(work.llm.prompts) == 2
    assert any(r["status"] == "invalid" for r in await work.records("decision"))


@pytest.mark.asyncio
async def test_lifecycle_conflict_is_not_retried_or_overridden_by_metadata_repair():
    repo = CreativeRepositoryFake()
    llm = MetadataLLM([{"updates": [{"character_id": "dead", "changes": {"life_status": "alive"},
        "evidence": [{"quote": "她回来了。", "start": 0}]}]}])
    work = await workspace(creative_config(repo, llm))
    original = await work.save("character", "dead",
        CharacterNarrative(character_id="dead", name="甲", life_status="dead",
            narrative_center=True).model_dump(mode="json"))
    with pytest.raises(CreativePause, match="死亡"):
        await _character_updates(work, chapter("她回来了。"), 1)
    assert await work.latest("character", "dead") == original
    assert len(llm.prompts) == 1
