"""Entity mention evidence cannot invent canonical properties or bypass archive checks."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.fact_archive_guard import archive_fact_guard, verify_fact_receipt
from application.fact_evaluation import evaluate_facts
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot
from application.creative.runtime import active_creative_rules
from service.value_objects.fact_gate import FactGateBlockedError, FactGateReport
from service.value_objects.story_fact import StoryEntity, StoryFactVersion
from tests.test_fact_gate import config, setup_gate
from tests.test_story_facts import evidence


def person_snapshot():
    person = StoryEntity(entity_key="hero", kind="character", name="辛远")
    fact = StoryFactVersion(id=uuid4(), subject_id=person.id, predicate="surname", value_text="辛",
        version=1, created_at=datetime.now(timezone.utc), evidence=evidence("辛远姓辛"))
    return setup_gate().model_copy(update={"entities": (person,), "fact_heads": (fact,)})


def mention_judge(snapshot, quote="辛远推开门。", path=None, **changes):
    raw = {"coverage": "complete", "claims": [], "unresolved": [],
           "mentions": [{"entity_id": str(snapshot.entities[0].id), "quote": quote, "quote_path": path}]}
    return SimpleNamespace(structured_generate=AsyncMock(return_value={**raw, **changes}))


@pytest.mark.asyncio
async def test_grounded_mention_passes_without_creating_a_property_assertion():
    snapshot, content = person_snapshot(), "辛远推开门。"
    report = await evaluate_facts(snapshot, content, "body", mention_judge(snapshot))
    assert report.status == "pass"
    assert report.assertions == ()
    assert len(report.mentions) == 1
    assert report.mentions[0].entity_id == snapshot.entities[0].id
    verify_fact_receipt(snapshot, report, content)
    assert len(snapshot.fact_heads) == 1


@pytest.mark.asyncio
async def test_mention_receipt_revalidates_inside_archive_transaction():
    snapshot, content = person_snapshot(), "辛远推开门。"
    report = await evaluate_facts(snapshot, content, "body", mention_judge(snapshot))
    assert report.status == "pass"
    store = config(snapshot)["configurable"]["story_fact_repository"]
    guard = archive_fact_guard(store, str(snapshot.tenant_id), str(snapshot.novel_id), snapshot, report, None)
    session = object()
    await guard(session, SimpleNamespace(chapter_index=0, content=content))
    assert store.assert_constraints_current.call_args.args[0] is session
    with pytest.raises(FactGateBlockedError):
        await guard(session, SimpleNamespace(chapter_index=0, content=content + "新增"))


@pytest.mark.asyncio
async def test_outline_mention_uses_exact_leaf_and_binds_unselected_context():
    snapshot, quote = person_snapshot(), "辛远推开门。"
    content = json.dumps({"summary": quote, "scenes": [{"result": quote}]}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline",
        mention_judge(snapshot, quote, "/scenes/0/result"))
    assert report.status == "pass"
    verify_fact_receipt(snapshot, report, content)
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, report, content.replace('"summary"', '"changed"'))


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unknown_entity", "no_name", "duplicate", "invalid_path",
    "body_path", "partial", "unresolved", "schema_keyword", "no_baseline", "empty"])
async def test_invalid_or_incomplete_mentions_never_pass(mutation):
    snapshot, content = person_snapshot(), "辛远推开门。他走了。"
    llm = mention_judge(snapshot)
    raw = llm.structured_generate.return_value
    if mutation == "unknown_entity":
        raw["mentions"][0]["entity_id"] = str(uuid4())
    if mutation == "no_name":
        raw["mentions"][0]["quote"] = "他走了。"
    if mutation == "duplicate":
        content += "辛远推开门。"
    if mutation in {"invalid_path", "body_path"}:
        raw["mentions"][0]["quote_path"] = "/missing"
    if mutation == "partial":
        raw["coverage"] = "partial"
    if mutation == "unresolved":
        raw["unresolved"] = ["实际姓氏断言无法核对"]
    if mutation == "schema_keyword":
        raw["type"] = "object"
    if mutation == "no_baseline":
        snapshot = snapshot.model_copy(update={"fact_heads": ()})
    if mutation == "empty":
        raw["mentions"] = []
    report = await evaluate_facts(snapshot, content, "body", llm)
    assert report.status == "unknown"
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, report, content)


@pytest.mark.asyncio
@pytest.mark.parametrize("content,hard", [("辛远姓陆。", True), ("辛远已经去世。", False)])
async def test_mentions_do_not_hide_conflicting_or_unconfirmed_properties(content, hard):
    snapshot = person_snapshot()
    llm = mention_judge(snapshot, content)
    llm.structured_generate.return_value["claims"] = [{
        "subject_id": str(snapshot.entities[0].id),
        "predicate": "surname" if hard else "life_status",
        "value_text": "陆" if hard else "dead", "quote": content,
    }]
    report = await evaluate_facts(snapshot, content, "body", llm)
    assert report.status == ("blocked" if hard else "unknown")
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, report, content)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["entity", "quote", "hash", "path", "snapshot"])
async def test_forged_mention_receipts_cannot_archive(mutation):
    snapshot, content = person_snapshot(), "辛远推开门。"
    report = await evaluate_facts(snapshot, content, "body", mention_judge(snapshot))
    assert report.status == "pass"
    raw = report.model_dump(mode="json")
    if mutation == "entity":
        raw["mentions"][0]["entity_id"] = str(uuid4())
    if mutation == "quote":
        raw["mentions"][0]["evidence"]["quote"] = "他推开门。"
    if mutation == "hash":
        raw["mentions"][0]["evidence"]["source_hash"] = "0" * 64
    if mutation == "path":
        raw["mentions"][0]["quote_path"] = "/missing"
    if mutation == "snapshot":
        snapshot = snapshot.model_copy(update={"entities": (
            snapshot.entities[0].model_copy(update={"name": "辛宁"}),)})
    with pytest.raises(FactGateBlockedError):
        verify_fact_receipt(snapshot, FactGateReport.model_validate(raw), content)


@pytest.mark.asyncio
async def test_independent_fact_extractor_does_not_inherit_creative_output_rules():
    snapshot = person_snapshot()
    llm = mention_judge(snapshot)
    rules_token = active_creative_rules.set("CREATIVE_ONLY_OUTPUT_MARKER")
    prompt_token = set_prompt_snapshot({"fact_judge_v2.txt": "原不可变快照 $constraints $kind $content",
        "fact_extraction_contract.txt": "LEGACY_EXTRACTION_V3_MARKER"})
    try:
        report = await evaluate_facts(snapshot, "辛远推开门。", "body", llm)
    finally:
        reset_prompt_snapshot(prompt_token)
        active_creative_rules.reset(rules_token)
    prompt = llm.structured_generate.call_args.kwargs["prompt"]
    assert "CREATIVE_ONLY_OUTPUT_MARKER" not in prompt
    assert "原不可变快照" in prompt
    assert "LEGACY_EXTRACTION_V3_MARKER" not in prompt
    assert report.status == "pass"


@pytest.mark.parametrize("version", ["fact-extraction-v1", "fact-extraction-v2", "fact-extraction-v3"])
def test_old_receipt_digests_do_not_change_with_optional_mention_support(version):
    import hashlib
    from application.fact_evaluation import _base
    raw = {**_base(person_snapshot(), "原稿", "body"), "extraction_version": version,
           "status": "unknown", "coverage": "unknown", "assertions": [], "findings": [],
           "reasons": [], "rule_version": "fact-gate-v1"}
    legacy = dict(raw)
    if version == "fact-extraction-v1":
        legacy.pop("extraction_version")
    expected = hashlib.sha256(json.dumps(legacy, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    assert FactGateReport.model_validate(raw).digest == expected
