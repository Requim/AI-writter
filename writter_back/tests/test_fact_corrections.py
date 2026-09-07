"""纠错令牌不可越权、篡改、过期或改变预览后的事实。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.fact_corrections import FactCorrectionInput, make_proposal, sign_proposal, verify_proposal, validate_entity_kinds
from service.value_objects.story_fact import StoryEntity


def values():
    context = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    novel = uuid4()
    person = StoryEntity(entity_key="hero", kind="character", name="辛远")
    change = FactCorrectionInput(subject_id=person.id, predicate="surname", value_text="辛", expected_version=1,
        valid_from_chapter=2, status="confirmed", reason="作者确认族谱记载")
    return context, novel, person, change


def test_signed_proposal_roundtrip_retains_author_evidence_and_scope():
    context, novel, _, change = values()
    proposal = make_proposal(context, novel, change)
    token = sign_proposal(proposal, "secret")
    assert verify_proposal(token, "secret", context, novel) == proposal
    assert str(context.user_id) in proposal.fact.evidence.source_ref
    assert proposal.fact.evidence.source_kind == "human_confirmation"


@pytest.mark.parametrize("case", ["tamper", "secret", "tenant", "reviewer", "novel", "expired"])
def test_invalid_confirmation_is_rejected(case):
    context, novel, _, change = values()
    proposal = make_proposal(context, novel, change)
    if case == "expired":
        proposal = proposal.model_copy(update={"expires_at": 1})
    token = sign_proposal(proposal, "secret")
    if case == "tamper":
        token += "x"
    if case == "tenant":
        context.tenant_id = uuid4()
    if case == "reviewer":
        context.user_id = uuid4()
    with pytest.raises(ValueError):
        verify_proposal(token, "different" if case == "secret" else "secret", context, uuid4() if case == "novel" else novel)


def test_entity_kind_confusion_and_invalid_versions_are_rejected():
    _, _, person, change = values()
    validate_entity_kinds(change, [person])
    with pytest.raises(ValueError):
        validate_entity_kinds(change, [person.model_copy(update={"kind": "family"})])
    with pytest.raises(ValidationError):
        FactCorrectionInput(**{**change.model_dump(), "expected_version": True})
