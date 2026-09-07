"""线上只读/合成事实门禁验收，不调用 Provider，不写生产数据库。"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from application.fact_evaluation import evaluate_facts
from application.fact_archive_guard import verify_fact_receipt
from application.story_facts import source_digest
from config import settings
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.fact_gate import FactGateBlockedError
from service.value_objects.story_fact import StoryEntity, StoryFactVersion, FactEvidence


def snapshot():
    person = StoryEntity(entity_key="hero", kind="character", name="辛远")
    evidence = FactEvidence(source_kind="human_confirmation", source_ref="synthetic-qa",
        source_version=1, quote="辛远姓辛", source_hash=source_digest("辛远姓辛"))
    fact = StoryFactVersion(id=uuid4(), subject_id=person.id, predicate="surname", value_text="辛",
        evidence=evidence, version=1, created_at=datetime.now(timezone.utc))
    return ChapterConstraintSet(tenant_id=uuid4(), novel_id=uuid4(), chapter_number=1,
        entities=(person,), fact_heads=(fact,))


async def check_gate():
    value = snapshot()
    blocked = await evaluate_facts(value, "辛远姓陆。", "body", None)
    assert blocked.status == "blocked" and blocked.findings[0].expected_evidence is not None
    try:
        verify_fact_receipt(value, blocked, "辛远姓陆。")
    except FactGateBlockedError:
        pass
    else:
        raise AssertionError("hard conflict accepted")
    unknown = await evaluate_facts(value, "他走进陆氏祠堂。", "body", None)
    assert unknown.status == "unknown" and not unknown.assertions
    ack = {"report_digest": unknown.digest, "reviewed_by": "synthetic", "proposal_id": "synthetic"}
    verify_fact_receipt(value, unknown, "他走进陆氏祠堂。", ack)
    async def judge(**kwargs):
        assert kwargs["temperature"] == 0.0 and kwargs["max_attempts"] == 1
        return {"coverage": "complete", "unresolved": [], "claims": [{"subject_id": str(value.entities[0].id),
            "predicate": "surname", "value_text": "辛", "quote": "辛远姓辛"}]}
    passed = await evaluate_facts(value, "辛远姓辛。", "body", SimpleNamespace(structured_generate=judge))
    assert passed.status == "pass"
    verify_fact_receipt(value, passed, "辛远姓辛。")
    print("fact_gate=pass hard_block=pass unknown_review=pass provider_calls=0")


async def main():
    await check_gate()
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            isolation = await connection.scalar(text("SHOW transaction_isolation"))
            assert revision == "0007_story_facts" and isolation == "read committed"
            print("database_revision=" + revision + " production_writes=0")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
