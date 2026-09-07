"""可追溯事实契约；规范事实与正文断言分开，不根据名字猜测亲属归属。"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

TextValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Predicate = Literal["surname", "family", "ancestral_hall_owner", "location", "life_status"]


class FactContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryEntity(FactContract):
    id: UUID = Field(default_factory=uuid4)
    entity_key: Key
    kind: Literal["character", "family", "place", "item"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    aliases: tuple[TextValue, ...] = ()


class FactEvidence(FactContract):
    source_kind: Literal["character_design", "novel_plan", "human_confirmation", "chapter_draft"]
    source_ref: Key
    source_version: Annotated[StrictInt, Field(ge=1)]
    quote: TextValue
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class FactStatement(FactContract):
    subject_id: UUID
    predicate: Predicate
    object_entity_id: UUID | None = None
    value_text: TextValue | None = None
    evidence: FactEvidence

    @model_validator(mode="after")
    def valid_value(self) -> Self:
        if (self.object_entity_id is None) == (self.value_text is None):
            raise ValueError("事实值必须为一个实体引用或一段文本")
        relation = self.predicate in {"family", "ancestral_hall_owner", "location"}
        if relation != (self.object_entity_id is not None):
            raise ValueError("关系事实必须引用规范实体，标量事实必须使用文本")
        return self


class CanonicalFact(FactStatement):
    valid_from_chapter: Annotated[StrictInt, Field(ge=1)] = 1
    valid_to_chapter: Annotated[StrictInt, Field(ge=1)] | None = None
    status: Literal["confirmed", "retracted"] = "confirmed"

    @model_validator(mode="after")
    def valid_authority(self) -> Self:
        if self.evidence.source_kind == "chapter_draft":
            raise ValueError("正文草稿不能直接成为规范事实")
        if self.valid_to_chapter is not None and self.valid_to_chapter < self.valid_from_chapter:
            raise ValueError("事实生效区间不合法")
        return self


class StoryFactVersion(CanonicalFact):
    id: UUID
    version: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime


class StoryFactAssertion(FactStatement):
    id: UUID = Field(default_factory=uuid4)
    chapter_number: Annotated[StrictInt, Field(ge=1)]

    @model_validator(mode="after")
    def draft_evidence(self) -> Self:
        if self.evidence.source_kind != "chapter_draft":
            raise ValueError("正文断言必须引用草稿证据")
        return self


class ValidationFinding(FactContract):
    code: str
    severity: Literal["hard_conflict", "unknown"]
    assertion_id: UUID
    fact_id: UUID | None = None
    fact_version: int | None = None
    message: str
    expected_evidence: FactEvidence | None = None
    actual_evidence: FactEvidence


class ValidationReport(FactContract):
    status: Literal["pass", "blocked", "unknown"]
    findings: tuple[ValidationFinding, ...]
    checked_assertions: int
