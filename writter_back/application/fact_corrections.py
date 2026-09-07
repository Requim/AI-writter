"""签名纠错提案绑定作者、作用域、目标事实及期望版本，确认后仅追加历史。"""
import base64
import hashlib
import hmac
import json
import time
from uuid import UUID, uuid4
from collections.abc import Sequence

from pydantic import Field, StrictInt

from application.story_facts import source_digest
from service.value_objects.story_fact import CanonicalFact, FactContract, FactEvidence, Predicate, StoryEntity
from service.entities.identity import TenantContext


class FactCorrectionInput(FactContract):
    subject_id: UUID
    predicate: Predicate
    object_entity_id: UUID | None = None
    value_text: str | None = None
    expected_version: StrictInt = Field(ge=0)
    valid_from_chapter: StrictInt = Field(ge=1)
    valid_to_chapter: StrictInt | None = Field(default=None, ge=1)
    status: str = Field(pattern="^(confirmed|retracted)$")
    reason: str = Field(min_length=1, max_length=2000)


class FactCorrectionProposal(FactContract):
    id: UUID
    tenant_id: UUID
    novel_id: UUID
    reviewer_id: UUID
    expires_at: int
    expected_version: StrictInt = Field(ge=0)
    fact: CanonicalFact


def make_proposal(context: TenantContext, novel_id: UUID, change: FactCorrectionInput) -> FactCorrectionProposal:
    identifier = uuid4()
    payload = change.model_dump(mode="json", exclude={"expected_version", "reason"})
    evidence = FactEvidence(source_kind="human_confirmation", source_ref=f"correction:{context.user_id}:{identifier}"[:128],
        source_version=change.expected_version + 1, quote=change.reason.strip(),
        source_hash=source_digest(json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    fact = CanonicalFact(**payload, evidence=evidence)
    return FactCorrectionProposal(id=identifier, tenant_id=context.tenant_id, novel_id=novel_id,
        reviewer_id=context.user_id, expires_at=int(time.time()) + 900, expected_version=change.expected_version, fact=fact)


def validate_entity_kinds(change: FactCorrectionInput, entities: Sequence[StoryEntity]) -> None:
    kinds = {entity.id: entity.kind for entity in entities}
    subject_kind = {"surname": "character", "life_status": "character", "family": "character", "ancestral_hall_owner": "place"}.get(change.predicate)
    target_kind = {"family": "family", "ancestral_hall_owner": "family", "location": "place"}.get(change.predicate)
    if change.subject_id not in kinds or (subject_kind and kinds[change.subject_id] != subject_kind):
        raise ValueError("事实主体类型与属性不匹配")
    if target_kind and (change.object_entity_id is None or kinds.get(change.object_entity_id) != target_kind):
        raise ValueError("关系对象类型不匹配，请选择家族或地点")


def sign_proposal(proposal: FactCorrectionProposal, secret: str) -> str:
    raw = base64.urlsafe_b64encode(proposal.model_dump_json().encode()).decode()
    signature = hmac.new(secret.encode(), ("fact-correction-v1:" + raw).encode(), hashlib.sha256).hexdigest()
    return raw + "." + signature


def verify_proposal(token: str, secret: str, context: TenantContext, novel_id: UUID) -> FactCorrectionProposal:
    if len(token) > 20000:
        raise ValueError("纠错提案过大")
    try:
        raw, signature = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), ("fact-correction-v1:" + raw).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("纠错提案签名无效")
        proposal = FactCorrectionProposal.model_validate_json(base64.urlsafe_b64decode(raw))
    except (ValueError, TypeError) as exc:
        raise ValueError("纠错提案无效，请重新预览") from exc
    if (proposal.tenant_id, proposal.novel_id, proposal.reviewer_id) != (context.tenant_id, novel_id, context.user_id):
        raise ValueError("纠错提案归属不匹配")
    if proposal.expires_at <= int(time.time()):
        raise ValueError("纠错提案已过期，请重新预览")
    return proposal
