"""章节约束快照：保留完整版本头，适用事实与失效检测分开。"""

import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from service.value_objects.story_fact import FactContract, StoryEntity, StoryFactVersion


class ChapterConstraintSet(FactContract):
    """内部可信仓储生成的章节输入，不接受客户端自报为已验证事实。"""

    schema_version: Literal["chapter-constraints-v1"] = "chapter-constraints-v1"
    tenant_id: UUID
    novel_id: UUID
    chapter_number: Annotated[StrictInt, Field(ge=1)]
    entities: tuple[StoryEntity, ...]
    fact_heads: tuple[StoryFactVersion, ...]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """拒绝重复实体、重复版本头及快照之外的关系引用。"""
        ids = {item.id for item in self.entities}
        keys = {item.entity_key for item in self.entities}
        heads = {(item.subject_id, item.predicate) for item in self.fact_heads}
        if len(ids) != len(self.entities) or len(keys) != len(self.entities):
            raise ValueError("章节快照包含重复实体")
        if len(heads) != len(self.fact_heads):
            raise ValueError("章节快照包含重复事实版本头")
        for fact in self.fact_heads:
            if fact.subject_id not in ids or (fact.object_entity_id and fact.object_entity_id not in ids):
                raise ValueError("章节快照包含未知实体引用")
        return self

    @property
    def active_facts(self) -> tuple[StoryFactVersion, ...]:
        """只返回当前章节生效的最新事实，不回退至已被替代的旧版本。"""
        return tuple(fact for fact in self.fact_heads if fact.status == "confirmed"
            and fact.valid_from_chapter <= self.chapter_number
            and (fact.valid_to_chapter is None or self.chapter_number <= fact.valid_to_chapter))

    @property
    def digest(self) -> str:
        """摘要绑定归属、章节、全部实体和版本头；新增或撤回事实也使快照失效。"""
        payload = self.model_dump(mode="json")
        payload["entities"] = sorted(payload["entities"], key=lambda item: item["id"])
        payload["fact_heads"] = sorted(payload["fact_heads"], key=lambda item: (item["subject_id"], item["predicate"]))
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
