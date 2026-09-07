"""实体事实规则：显式归属冲突、访问他族祠堂、未知来源及版本边界。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.story_facts import compile_character_surnames, compile_confirmed_fact, source_digest, validate_assertions
from service.value_objects.story_fact import CanonicalFact, FactEvidence, StoryFactAssertion, StoryFactVersion


def evidence(content="辛家祖祠归辛家所有", kind="human_confirmation"):
    return FactEvidence(source_kind=kind, source_ref="source-1", source_version=1,
                        quote=content, source_hash=source_digest(content))


def version(subject, owner, **changes):
    return StoryFactVersion(id=uuid4(), subject_id=subject, predicate="ancestral_hall_owner",
        object_entity_id=owner, evidence=evidence(), version=changes.pop("version", 1),
        created_at=datetime.now(timezone.utc), **changes)


def assertion(subject, owner, draft="辛家的祖祠归陆家所有", **changes):
    return StoryFactAssertion(subject_id=subject, predicate="ancestral_hall_owner", object_entity_id=owner,
        evidence=evidence(draft, "chapter_draft"), chapter_number=changes.pop("chapter_number", 2), **changes)


def test_explicit_hall_ownership_conflict_keeps_both_evidence_sources():
    hall, xin, lu = uuid4(), uuid4(), uuid4()
    canonical = version(hall, xin)
    claim = assertion(hall, lu)
    result = validate_assertions([claim], [canonical], draft=claim.evidence.quote)
    assert result.status == "blocked"
    assert result.findings[0].fact_version == 1
    assert result.findings[0].expected_evidence == canonical.evidence
    assert result.findings[0].actual_evidence == claim.evidence


def test_visiting_lu_hall_does_not_imply_xin_owns_it():
    hall, lu = uuid4(), uuid4()
    draft = "辛远受邀走进陆氏祠堂，这座祠堂归陆家所有。"
    claim = assertion(hall, lu, draft)
    assert validate_assertions([claim], [version(hall, lu)], draft=draft).status == "pass"
    assert validate_assertions([], [version(hall, lu)], draft="辛远走进陆氏祠堂").status == "unknown"


@pytest.mark.parametrize("case", ["missing", "retracted", "future", "expired", "duplicate", "stale_draft"])
def test_uncertain_evidence_never_passes(case):
    hall, xin = uuid4(), uuid4()
    claim = assertion(hall, xin)
    facts = [version(hall, xin)]
    draft = claim.evidence.quote
    if case == "missing":
        facts = []
    if case == "retracted":
        facts = [version(hall, xin, status="retracted")]
    if case == "future":
        facts = [version(hall, xin, valid_from_chapter=3)]
    if case == "expired":
        facts = [version(hall, xin, valid_to_chapter=1)]
    if case == "duplicate":
        facts *= 2
    if case == "stale_draft":
        draft += "修订后的新内容"
    assert validate_assertions([claim], facts, draft=draft).status == "unknown"


def test_latest_correction_supersedes_old_fact_without_erasing_history():
    hall, xin, lu = uuid4(), uuid4(), uuid4()
    facts = [version(hall, xin), version(hall, lu, version=2)]
    claim = assertion(hall, lu)
    assert validate_assertions([claim], facts, draft=claim.evidence.quote).status == "pass"
    assert facts[0].object_entity_id == xin


def test_adopted_character_can_keep_xin_surname_and_belong_to_lu_family():
    person, lu = uuid4(), uuid4()
    draft = "辛远被陆家收养，仍然姓辛。"
    fact = StoryFactVersion(id=uuid4(), subject_id=person, predicate="family", object_entity_id=lu,
        evidence=evidence(draft), version=1, created_at=datetime.now(timezone.utc))
    claim = StoryFactAssertion(subject_id=person, predicate="family", object_entity_id=lu,
        evidence=evidence(draft, "chapter_draft"), chapter_number=2)
    assert validate_assertions([claim], [fact], draft=draft).status == "pass"


def test_character_compilation_uses_explicit_surname_and_stable_identity():
    novel = uuid4()
    design = {"characters": [{"character_id": "hero", "name": "欧阳辛", "surname": "欧阳"},
        {"character_id": "other", "name": "陆甲"},
        {"character_id": "legacy", "name": "辛乙", "surname": "辛", "origin_type": "legacy_import"}]}
    entities, facts = compile_character_surnames(novel, design, source_ref="design-1", source_version=3, confirmed=True)
    again = compile_character_surnames(novel, design, source_ref="design-1", source_version=3, confirmed=True)
    assert len(entities) == len(facts) == 1
    assert facts[0].value_text == "欧阳" and facts[0].evidence.source_version == 3
    assert entities == again[0]
    assert facts[0].predicate == "surname"


def test_unconfirmed_source_and_invented_quote_are_rejected():
    with pytest.raises(ValueError):
        compile_character_surnames(uuid4(), {}, source_ref="design", source_version=1, confirmed=False)
    with pytest.raises(ValueError):
        compile_confirmed_fact({}, source_kind="novel_plan", source_ref="plan", source_version=1,
            source_content="辛家旧案", quote="陆家祖祠", confirmed=True)


@pytest.mark.parametrize("changes", [
    {"value_text": "辛", "object_entity_id": uuid4()}, {"value_text": None},
    {"valid_from_chapter": True}, {"valid_from_chapter": 5, "valid_to_chapter": 2},
    {"evidence": evidence("未经确认的正文", "chapter_draft")},
])
def test_invalid_canonical_contract_is_rejected(changes):
    payload = {"subject_id": uuid4(), "predicate": "surname", "value_text": "辛", "evidence": evidence()}
    with pytest.raises(ValidationError):
        CanonicalFact.model_validate({**payload, **changes})
