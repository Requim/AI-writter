"""稿件事实审校回执，绑定作用域、完整稿件、快照和规则版本。"""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt

from service.value_objects.story_fact import FactContract, StoryFactAssertion, ValidationFinding

FACT_GATE_VERSION = "fact-gate-v1"


class FactGateReport(FactContract):
    rule_version: Literal["fact-gate-v1"] = "fact-gate-v1"
    tenant_id: UUID
    novel_id: UUID
    chapter_number: StrictInt = Field(ge=1)
    artifact_kind: Literal["outline", "body"]
    artifact_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["pass", "blocked", "unknown"]
    coverage: Literal["complete", "partial", "unknown"]
    assertions: tuple[StoryFactAssertion, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        """人工确认只对本份回执生效，内容或版本变化后必须重新审核。"""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FactGateBlockedError(ValueError):
    """已确认硬冲突或缺少有效审核回执时禁止归档。"""
