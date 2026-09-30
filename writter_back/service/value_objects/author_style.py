"""原创样例、明确偏好及固定作者档案版本。"""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from service.value_objects.creative import CreativeContract


class AuthorSample(CreativeContract):
    original_confirmed: Literal[True]
    original: str = Field(min_length=1, max_length=50000)
    revision: str = Field(default="", max_length=50000)
    judgment: Literal["accepted", "rejected", "reference"]
    reason: str = Field(min_length=1, max_length=4000)
    category: Literal["style", "fact_correction", "plot_change"] = "style"
    scope: Literal["book", "genre", "global"] = "book"
    novel_id: UUID | None = None
    genre: str | None = None
    explicit_scope: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope != "book" and not self.explicit_scope:
            raise ValueError("跨书样例范围必须由作者明确指定")
        if self.scope == "book" and self.novel_id is None:
            raise ValueError("未指定范围的样例只作用于当前书，必须绑定作品")
        if self.scope == "genre" and not self.genre:
            raise ValueError("题材样例必须指定题材")
        return self


class StylePreference(CreativeContract):
    preference_id: str = Field(min_length=1, max_length=120)
    aspect: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)
    strength: Literal["hard", "soft"] = "soft"
    scope: Literal["instruction", "scene", "book", "genre", "global"] = "book"
    novel_id: UUID | None = None
    genre: str | None = None
    scene_function: str | None = None
    tasks: list[Literal["topic", "character", "prose", "revision"]] = Field(min_length=1)
    sample_ids: list[UUID] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=2000)
    explicit_scope: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope in {"global", "genre"} and not self.explicit_scope:
            raise ValueError("一次接受修改不能自动变为跨书偏好")
        if self.scope in {"book", "scene", "instruction"} and self.novel_id is None:
            raise ValueError("本书或当前任务偏好必须绑定作品")
        if self.scope == "genre" and not self.genre:
            raise ValueError("题材偏好必须明确题材范围")
        if self.scope == "scene" and self.scene_function not in {"conflict", "setup", "aftermath", "relationship", "discovery"}:
            raise ValueError("场景偏好必须明确适用功能")
        return self


class AuthorProfile(CreativeContract):
    name: str = Field(min_length=1, max_length=120)
    preferences: list[StylePreference] = Field(default_factory=list, max_length=100)
