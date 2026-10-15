from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetKind = Literal["idea", "world", "character", "outline", "chapter", "reference"]
Intent = Literal["discuss", "setting", "outline", "write", "continue", "rewrite", "review"]


class WorkbenchConflict(Exception):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetInput(Contract):
    title: str = Field(min_length=1, max_length=240)
    kind: AssetKind
    content: str = Field(min_length=1, max_length=100000)
    source_message_id: UUID | None = None

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value


class AssetEdit(AssetInput):
    expected_version: int = Field(ge=1)


class MessageInput(Contract):
    text: str = Field(min_length=1, max_length=20000)
    intent: Intent = "discuss"
    reference_ids: list[UUID] = Field(default_factory=list, max_length=20)
    chapter_index: int | None = Field(default=None, ge=0, le=199)
    target_chapter_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请求不能为空")
        return value


class AdoptInput(Contract):
    expected_version: int = Field(ge=1)
    acceptance: Literal["reviewed", "with_issues", "unreviewed"] = "reviewed"
    chapter_index: int | None = Field(default=None, ge=0, le=199)
    target_chapter_id: UUID | None = None
    expected_chapter_version: int | None = Field(default=None, ge=1)
