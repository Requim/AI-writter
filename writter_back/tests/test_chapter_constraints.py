"""章节快照契约及确定性摘要边界。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.story_fact import StoryEntity
from tests.test_story_facts import version


def snapshot(**changes):
    hall = StoryEntity(entity_key="hall", kind="place", name="辛家祖祠")
    family = StoryEntity(entity_key="xin", kind="family", name="辛家")
    values = dict(tenant_id=uuid4(), novel_id=uuid4(), chapter_number=2,
                  entities=(hall, family), fact_heads=(version(hall.id, family.id),))
    return ChapterConstraintSet(**(values | changes))


def test_snapshot_json_roundtrip_and_order_independent_digest():
    original = snapshot()
    restored = ChapterConstraintSet.model_validate_json(original.model_dump_json())
    reordered = original.model_copy(update={"entities": tuple(reversed(original.entities))})
    assert restored == original
    assert reordered.digest == restored.digest == original.digest
    assert len(original.digest) == 64


@pytest.mark.parametrize("field", ["tenant_id", "novel_id", "chapter_number", "entity", "evidence", "version", "status", "range"])
def test_digest_binds_scope_entities_evidence_and_all_versions(field):
    original = snapshot()
    if field in {"tenant_id", "novel_id", "chapter_number"}:
        updated = original.model_copy(update={field: 3 if field == "chapter_number" else uuid4()})
    elif field == "entity":
        updated = original.model_copy(update={"entities": (original.entities[0].model_copy(update={"aliases": ("祖祠",)}), original.entities[1])})
    else:
        changes = {"version": 2} if field == "version" else {"status": "retracted"} if field == "status" else {"valid_from_chapter": 3}
        if field == "evidence":
            changes = {"evidence": original.fact_heads[0].evidence.model_copy(update={"source_version": 2})}
        updated = original.model_copy(update={"fact_heads": (original.fact_heads[0].model_copy(update=changes),)})
    assert updated.digest != original.digest


@pytest.mark.parametrize("changes", [{"status": "retracted"}, {"valid_from_chapter": 3}, {"valid_to_chapter": 1}])
def test_inactive_heads_are_retained_but_not_injected(changes):
    original = snapshot()
    inactive = original.fact_heads[0].model_copy(update=changes)
    updated = original.model_copy(update={"fact_heads": (inactive,)})
    assert updated.active_facts == ()
    assert updated.fact_heads == (inactive,)
    assert updated.digest != original.digest


@pytest.mark.parametrize("chapter", [0, -1, True, "2", 2.5])
def test_chapter_requires_positive_integer(chapter):
    with pytest.raises(ValidationError):
        snapshot(chapter_number=chapter)


@pytest.mark.parametrize("case", ["duplicate_entity", "duplicate_key", "duplicate_fact", "missing_subject", "missing_object"])
def test_malformed_snapshot_is_rejected(case):
    original = snapshot()
    values = original.model_dump(mode="json")
    if case == "duplicate_entity":
        values["entities"].append(values["entities"][0])
    elif case == "duplicate_key":
        values["entities"][1]["entity_key"] = values["entities"][0]["entity_key"]
    elif case == "duplicate_fact":
        values["fact_heads"].append(values["fact_heads"][0])
    else:
        values["fact_heads"][0]["subject_id" if case == "missing_subject" else "object_entity_id"] = uuid4()
    with pytest.raises(ValidationError):
        ChapterConstraintSet.model_validate(values)


def test_empty_snapshot_has_no_implied_validation_success():
    value = snapshot(entities=(), fact_heads=())
    assert value.active_facts == ()
    assert "status" not in value.model_dump()
