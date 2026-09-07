"""真实 PostgreSQL 验证租户归属、幂等、历史和并发修正。"""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.story_facts import validate_assertions
from infrastructure.database.models import StoryEntityModel, StoryFactAssertionModel, StoryFactVersionModel
from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.story_fact import CanonicalFact, StoryEntity, StoryFactAssertion
from tests.test_story_facts import evidence


@pytest_asyncio.fixture
async def ledger(repository, tenant_context, sample_novel):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    return PostgresStoryFactRepository(repository.async_session), str(tenant_context.tenant_id), str(sample_novel.id)


async def _person(ledger):
    store, tenant, novel = ledger
    return await store.ensure_entity(tenant, novel, StoryEntity(entity_key="hero", kind="character", name="辛远"))


def _surname(person, value="辛", **changes):
    return CanonicalFact(subject_id=person.id, predicate="surname", value_text=value, evidence=evidence(), **changes)


@pytest.mark.asyncio
async def test_entity_idempotency_and_content_conflict(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    repeated = await _person(ledger)
    assert person == repeated
    with pytest.raises(FactVersionConflictError):
        await store.ensure_entity(tenant, novel, person.model_copy(update={"name": "陆远"}))
    assert await store.list_entities(tenant, novel) == [person]


@pytest.mark.asyncio
async def test_version_history_retry_and_retraction(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    fact = _surname(person)
    first = await store.append_fact(tenant, novel, fact, expected_version=0, idempotency_key="first")
    assert await store.append_fact(tenant, novel, fact, expected_version=0, idempotency_key="first") == first
    second = await store.append_fact(tenant, novel, _surname(person, "陆"), expected_version=1, idempotency_key="second")
    with pytest.raises(FactVersionConflictError):
        await store.append_fact(tenant, novel, fact, expected_version=0, idempotency_key="stale")
    with pytest.raises(FactVersionConflictError):
        await store.append_fact(tenant, novel, _surname(person, "陆"), expected_version=0, idempotency_key="first")
    history = await store.list_history(tenant, novel, person.id, "surname")
    assert [item.value_text for item in history] == ["辛", "陆"]
    assert await store.list_current(tenant, novel) == [second]
    withdrawn = await store.append_fact(tenant, novel, _surname(person, "陆", status="retracted"),
        expected_version=2, idempotency_key="withdraw")
    assert (await store.list_current(tenant, novel))[0] == withdrawn


@pytest.mark.asyncio
async def test_concurrent_expected_version_allows_only_one_winner(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    results = await asyncio.gather(
        store.append_fact(tenant, novel, _surname(person), expected_version=0, idempotency_key="a"),
        store.append_fact(tenant, novel, _surname(person, "陆"), expected_version=0, idempotency_key="b"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, FactVersionConflictError) for item in results) == 1
    assert len(await store.list_history(tenant, novel, person.id, "surname")) == 1


@pytest.mark.asyncio
async def test_cross_tenant_read_and_write_are_rejected(ledger, other_tenant_context):
    store, _tenant, novel = ledger
    person = await _person(ledger)
    foreign = str(other_tenant_context.tenant_id)
    with pytest.raises(ValueError, match="不可访问"):
        await store.list_current(foreign, novel)
    with pytest.raises(ValueError, match="不可访问"):
        await store.ensure_entity(foreign, novel, person)
    with pytest.raises(ValueError, match="不可访问"):
        await store.append_fact(foreign, novel, _surname(person), expected_version=0, idempotency_key="foreign")


@pytest.mark.asyncio
async def test_unknown_entity_and_wrong_relation_kind_are_rejected(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    with pytest.raises(ValueError, match="不可访问"):
        await store.append_fact(tenant, novel, _surname(person).model_copy(update={"subject_id": uuid4()}),
            expected_version=0, idempotency_key="missing")
    invalid = CanonicalFact(subject_id=person.id, predicate="ancestral_hall_owner", object_entity_id=person.id, evidence=evidence())
    with pytest.raises(ValueError, match="类型不匹配"):
        await store.append_fact(tenant, novel, invalid, expected_version=0, idempotency_key="wrong-kind")


@pytest.mark.asyncio
async def test_assertions_do_not_become_canonical_and_retry_is_safe(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    claim = StoryFactAssertion(subject_id=person.id, predicate="surname", value_text="陆", chapter_number=1,
        evidence=evidence("陆远走了进来", "chapter_draft"))
    await store.record_assertion(tenant, novel, claim)
    await store.record_assertion(tenant, novel, claim)
    assert await store.list_assertions(tenant, novel, 1) == [claim]
    assert await store.list_current(tenant, novel) == []
    with pytest.raises(FactVersionConflictError):
        await store.record_assertion(tenant, novel, claim.model_copy(update={"value_text": "辛"}))


@pytest.mark.asyncio
async def test_database_rejects_cross_tenant_entity_reference(ledger, repository, other_tenant_context):
    store, tenant, novel = ledger
    person = await _person(ledger)
    await store.append_fact(tenant, novel, _surname(person), expected_version=0, idempotency_key="valid")
    async with repository.async_session() as session:
        row = await session.scalar(select(StoryFactVersionModel))
        row.tenant_id = other_tenant_context.tenant_id
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_same_tenant_other_novel_entity_cannot_be_referenced(ledger, repository, sample_novel):
    store, tenant, novel = ledger
    person = await _person(ledger)
    other = replace(sample_novel, id=uuid4())
    await repository.save(tenant, other)
    family = await store.ensure_entity(tenant, str(other.id), StoryEntity(entity_key="family", kind="family", name="陆家"))
    fact = CanonicalFact(subject_id=person.id, predicate="family", object_entity_id=family.id, evidence=evidence())
    with pytest.raises(ValueError, match="不可访问"):
        await store.append_fact(tenant, novel, fact, expected_version=0, idempotency_key="other-novel")


@pytest.mark.asyncio
async def test_persisted_hall_conflict_and_versioned_correction_round_trip(ledger, repository):
    store, tenant, novel = ledger
    xin = await store.ensure_entity(tenant, novel, StoryEntity(entity_key="xin", kind="family", name="辛家"))
    lu = await store.ensure_entity(tenant, novel, StoryEntity(entity_key="lu", kind="family", name="陆家"))
    hall = await store.ensure_entity(tenant, novel, StoryEntity(entity_key="hall", kind="place", name="旧祠堂"))
    fact = CanonicalFact(subject_id=hall.id, predicate="ancestral_hall_owner", object_entity_id=xin.id, evidence=evidence())
    await store.append_fact(tenant, novel, fact, expected_version=0, idempotency_key="ownership-v1")
    draft = "旧祠堂归陆家所有。"
    claim = StoryFactAssertion(subject_id=hall.id, predicate="ancestral_hall_owner", object_entity_id=lu.id,
        chapter_number=1, evidence=evidence(draft, "chapter_draft"))
    await store.record_assertion(tenant, novel, claim)
    claims = await store.list_assertions(tenant, novel, 1)
    report = validate_assertions(claims, await store.list_current(tenant, novel), draft=draft)
    assert report.status == "blocked"
    corrected = fact.model_copy(update={"object_entity_id": lu.id, "evidence": evidence("已确认祠堂实际属于陆家")})
    await store.append_fact(tenant, novel, corrected, expected_version=1, idempotency_key="ownership-v2")
    report = validate_assertions(claims, await store.list_current(tenant, novel), draft=draft)
    assert report.status == "pass"
    assert len(await store.list_history(tenant, novel, hall.id, "ancestral_hall_owner")) == 2
    await repository.delete(tenant, novel)
    async with repository.async_session() as session:
        for model in (StoryEntityModel, StoryFactVersionModel, StoryFactAssertionModel):
            assert await session.scalar(select(model.id).limit(1)) is None
