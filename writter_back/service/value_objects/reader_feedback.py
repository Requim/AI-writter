"""反馈与隔离实验的来源、版本及验证契约。"""

from typing import Literal

from pydantic import Field, model_validator

from service.value_objects.creative import CreativeContract, TextEvidence


class ReaderFeedback(CreativeContract):
    source: Literal["human_reader", "author_instruction", "simulated_reader"]
    reader_id: str = Field(min_length=1, max_length=120)
    issue_key: str = Field(min_length=1, max_length=120)
    category: Literal["style", "pace", "character", "understanding", "fact", "plot"]
    comment: str = Field(min_length=1, max_length=4000)
    evidence: list[TextEvidence] = Field(min_length=1, max_length=10)


class BlindJudgment(CreativeContract):
    evaluator_id: str = Field(min_length=1, max_length=120)
    source: Literal["model", "human"]
    order: Literal["AB", "BA"]
    winner: Literal["A", "B", "tie"]
    reason: str = Field(min_length=1, max_length=2000)
    valid: bool = True


class FeedbackExperiment(CreativeContract):
    issue_key: str
    factor: str = Field(min_length=1, max_length=500)
    scene_id: str = Field(min_length=1, max_length=120)
    hypothesis_ids: list[str] = Field(min_length=1)
    created_after_chapter: int = Field(ge=0, le=200)
    variant_a: str = Field(min_length=1, max_length=1500)
    variant_b: str = Field(min_length=1, max_length=1500)
    quality_pass: bool = False
    judgments: list[BlindJudgment] = Field(default_factory=list, max_length=100)
    status: Literal["candidate", "model_supported_trial", "human_supported", "revoked"] = "candidate"
    trial_start: int | None = Field(default=None, ge=1)
    trial_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_variants(self):
        if self.variant_a == self.variant_b:
            raise ValueError("实验版本必须存在单一因素差异")
        if self.trial_start and self.trial_end != self.trial_start + 4:
            raise ValueError("临时采用窗口必须为后续五章")
        return self
