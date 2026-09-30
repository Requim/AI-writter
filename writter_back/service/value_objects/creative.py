"""自主创作的独立版本契约，不改变旧工作流状态版本。"""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AUTHOR_MODE = "autonomous_v1"
CREATIVE_SCHEMA_VERSION = 1
SceneFunction = Literal["conflict", "setup", "aftermath", "relationship", "discovery"]
NarrativeMode = Literal["stable", "ensemble_relay"]
RecordKind = Literal[
    "source", "candidate", "engine", "pilot", "evaluation", "selection",
    "character", "role_slot", "relationship", "secret", "foreshadow",
    "decision", "reader_state", "engine_review", "postprocess",
    "feedback", "hypothesis", "experiment", "adoption", "style_application",
    "replan", "name_batch", "control",
]


class CreativeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetLimits(CreativeContract):
    preparation: int = Field(default=60, ge=1, le=60)
    chapter: int = Field(default=32, ge=1, le=32)
    review: int | None = Field(default=None, ge=0)
    search: int = Field(default=12, ge=0, le=12)
    preparation_search: int = Field(default=6, ge=0, le=6)

    def resolved(self, chapters: int, tenant_limit: int = 10000) -> dict[str, int]:
        """解析调用上限；拒绝超出全书或租户上限的配置。"""
        review = 20 + 8 * chapters if self.review is None else self.review
        if review > 20 + 8 * chapters:
            raise ValueError("复盘预算超出规模上限")
        if self.preparation_search > self.search:
            raise ValueError("立项检索预算不能超过全书检索预算")
        total = self.preparation + self.chapter * chapters + review
        if total > tenant_limit:
            raise ValueError("模型请求预算超出租户上限")
        return {**self.model_dump(exclude={"review"}), "review": review, "total": total, "chapters": chapters}


class ResearchSource(CreativeContract):
    title: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=50000)
    category: Literal["traceable_fact", "market_observation", "model_hypothesis"]
    origin: Literal["user_text", "user_file", "tavily"] = "user_text"
    source_url: str | None = Field(default=None, max_length=2000)
    observed_at: datetime
    applicable_scope: str = Field(min_length=1, max_length=1000)
    published_at: datetime | None = None

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("资料日期必须包含时区")
        if self.origin == "tavily" and not self.source_url:
            raise ValueError("检索资料必须保存原始来源")
        if self.source_url and not self.source_url.startswith(("https://", "http://")):
            raise ValueError("来源地址必须为 HTTP(S)")
        return self


class AuthorConfiguration(CreativeContract):
    author_mode: Literal["autonomous_v1"] = AUTHOR_MODE
    creative_schema_version: Literal[1] = CREATIVE_SCHEMA_VERSION
    narrative_mode: Literal["auto", "stable", "ensemble_relay"] = "auto"
    hard_constraints: list[str] = Field(default_factory=list, max_length=40)
    target_readers: str = Field(default="", max_length=2000)
    author_question: str = Field(default="", max_length=2000)
    desired_experience: str = Field(default="", max_length=2000)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=20)
    budget: BudgetLimits = Field(default_factory=BudgetLimits)
    author_profile_id: UUID | None = None
    author_profile_version: int | None = Field(default=None, ge=1)
    research_queries: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_profile_and_queries(self):
        if (self.author_profile_id is None) != (self.author_profile_version is None):
            raise ValueError("作者档案标识与版本必须同时指定")
        if any(not query.strip() or len(query) > 120 for query in self.research_queries):
            raise ValueError("检索词不能为空且不得超过120字，不得包含私人样章或秘密档案")
        if any(not item.strip() or len(item) > 1000 for item in self.hard_constraints):
            raise ValueError("硬设定不能为空且每项最多1000字")
        return self


class TextEvidence(CreativeContract):
    chapter_id: UUID
    chapter_version: int = Field(ge=1)
    chapter_number: int = Field(ge=1, le=200)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("证据位置与引用长度不一致")
        return self


class ArcDuty(CreativeContract):
    arc_id: str = Field(min_length=1, max_length=120)
    function: Literal["drive", "oppose", "witness", "inherit"]
    status: Literal["planned", "active", "fulfilled", "transferred"] = "planned"
    successor_id: str | None = None


class CharacterNarrative(CreativeContract):
    character_id: str = Field(min_length=1, max_length=120)
    story_entity_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    role: Literal["core", "supporting", "minor", "anonymous"] = "supporting"
    narrative_center: bool = False
    goal: str = ""
    lack: str = ""
    belief: str = ""
    red_line: str = ""
    abilities: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    voice: str = ""
    knowledge: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    narrative_status: Literal["planned", "active", "latent", "offstage", "exited"] = "planned"
    life_status: Literal["unknown", "alive", "dead"] = "unknown"
    perceived_life_status: Literal["unknown", "alive", "dead"] = "unknown"
    allegiance: str = ""
    arc_duties: list[ArcDuty] = Field(default_factory=list)
    secret_ids: list[str] = Field(default_factory=list)
    evidence: list[TextEvidence] = Field(default_factory=list)


class RoleSlot(CreativeContract):
    slot_id: str
    function: str = Field(min_length=1)
    arc_ids: list[str] = Field(min_length=1)
    entrance_start: int = Field(ge=1)
    entrance_end: int = Field(ge=1)
    character_id: str | None = None
    existing_character_decision: str = ""

    @model_validator(mode="after")
    def validate_window(self):
        if self.entrance_end < self.entrance_start:
            raise ValueError("角色登场窗口顺序错误")
        if self.character_id and not self.existing_character_decision.strip():
            raise ValueError("具体化角色前必须记录复用既有角色的判断")
        return self


class Secret(CreativeContract):
    secret_id: str
    truth: str
    character_ids: list[str] = Field(default_factory=list)
    known_by: list[str] = Field(default_factory=list)
    reveal_conditions: list[str] = Field(min_length=1)
    reader_revealed: bool = False
    evidence: list[TextEvidence] = Field(default_factory=list)


class Foreshadow(CreativeContract):
    foreshadow_id: str
    origin: Literal["planned", "retrospective"]
    conceived_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["planned", "seeded", "reinforced", "partial", "completed"] = "planned"
    core: bool = False
    description: str
    arc_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    due_chapter: int | None = Field(default=None, ge=1, le=200)
    resolution: str = ""
    evidence: list[TextEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence(self):
        if (self.origin == "retrospective" or self.status != "planned") and not self.evidence:
            raise ValueError("实际埋设或后续接续必须有归档正文证据")
        if self.status == "completed" and not self.resolution:
            raise ValueError("伏笔完成必须说明兑现或合理解释")
        return self


class CreativeRecord(CreativeContract):
    kind: RecordKind
    key: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any]
    status: str = Field(default="candidate", min_length=1, max_length=40)
    input_versions: dict[str, int | str] = Field(default_factory=dict)
    evidence: list[TextEvidence] = Field(default_factory=list)
    source: Literal["model", "human_reader", "author", "system", "research"]
