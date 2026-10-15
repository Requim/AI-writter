"""Outline extraction uses actual source locators, never guessed JSON paths."""

import json

import pytest

from application.fact_archive_guard import verify_fact_receipt
from application.fact_evaluation import evaluate_facts
from tests.test_fact_entity_mentions import mention_judge, person_snapshot


MARKER = "本稿实体引用定位JSON：\n"


class CatalogJudge:
    async def structured_generate(self, *, prompt, **_kwargs):
        self.catalog = json.loads(prompt.split(MARKER, 1)[1].splitlines()[0])
        return {"coverage": "complete", "claims": [], "unresolved": [],
            "mentions": self.catalog[:1]}


@pytest.mark.asyncio
async def test_outline_catalog_provides_a_real_escaped_pointer_and_full_artifact_receipt():
    snapshot = person_snapshot()
    content = json.dumps({"结构/~": ["辛远推开门。"],
        "plan_context": {"future": "辛远推开门。"}}, ensure_ascii=False)
    llm = CatalogJudge()
    report = await evaluate_facts(snapshot, content, "outline", llm)
    assert report.status == "pass"
    assert llm.catalog == [{"entity_id": str(snapshot.entities[0].id),
        "quote": "辛远", "quote_path": "/结构~1~0/0"}]
    verify_fact_receipt(snapshot, report, content)


@pytest.mark.asyncio
async def test_repeated_names_in_one_leaf_do_not_create_ambiguous_locator_hints():
    snapshot = person_snapshot()
    content = json.dumps({"repeated": "辛远回答辛远的问题。", "actual": "辛远"}, ensure_ascii=False)
    llm = CatalogJudge()
    report = await evaluate_facts(snapshot, content, "outline", llm)
    assert report.status == "pass"
    assert llm.catalog[0]["quote_path"] == "/actual"


@pytest.mark.asyncio
async def test_future_context_alone_cannot_supply_a_current_chapter_mention():
    snapshot = person_snapshot()
    llm = CatalogJudge()
    report = await evaluate_facts(snapshot,
        json.dumps({"plan_context": {"next": "辛远"}}, ensure_ascii=False), "outline", llm)
    assert llm.catalog == []
    assert report.status == "unknown"
    assert not report.mentions


@pytest.mark.asyncio
async def test_catalog_does_not_repair_a_model_supplied_invalid_path():
    snapshot = person_snapshot()
    content = json.dumps({"actual": "辛远推开门。"}, ensure_ascii=False)
    report = await evaluate_facts(snapshot, content, "outline",
        mention_judge(snapshot, path="/invented"))
    assert report.status == "unknown"
    assert not report.mentions
