"""Immutable value objects used by the naming service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """表示一条由服务端维护并核验的古典文本取名词条。"""

    source_id: str
    work: str
    chapter: str
    quote: str
    token: str
    meaning: str
    pinyin: str
    gender_tendency: str
    genre_tags: tuple[str, ...]
    era_tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceEntry":
        """从 JSON 映射构造不可变词条。"""
        return cls(
            source_id=str(value["source_id"]),
            work=str(value["work"]),
            chapter=str(value["chapter"]),
            quote=str(value["quote"]),
            token=str(value["token"]),
            meaning=str(value["meaning"]),
            pinyin=str(value["pinyin"]),
            gender_tendency=str(value["gender_tendency"]),
            genre_tags=tuple(str(item) for item in value["genre_tags"]),
            era_tags=tuple(str(item) for item in value["era_tags"]),
        )

    def attribution(self) -> dict[str, Any]:
        """返回只能由服务端词库生成的出处信息。"""
        return {
            "source_id": self.source_id,
            "work": self.work,
            "chapter": self.chapter,
            "quote": self.quote,
            "token": self.token,
            "meaning": self.meaning,
            "pinyin": self.pinyin,
            "gender_tendency": self.gender_tendency,
            "genre_tags": list(self.genre_tags),
            "era_tags": list(self.era_tags),
        }


@dataclass(frozen=True, slots=True)
class SurnameEntry:
    """表示一个可抽样的真实姓氏及其封顶前基础权重。"""

    surname: str
    pinyin: str
    weight: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SurnameEntry":
        """从 JSON 映射构造姓氏词条。"""
        return cls(
            surname=str(value["surname"]),
            pinyin=str(value["pinyin"]),
            weight=float(value["weight"]),
        )


@dataclass(frozen=True, slots=True)
class NameCandidate:
    """表示一个已由服务端补齐出处的姓名候选。"""

    candidate_id: str
    name: str
    surname: str
    source: SourceEntry

    def to_dict(self) -> dict[str, Any]:
        """转换为可直接持久化或返回前端的字典。"""
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "surname": self.surname,
            "source_id": self.source.source_id,
            "source": self.source.attribution(),
        }


@dataclass(frozen=True, slots=True)
class NameSelection:
    """表示通过校验后可写入角色表的最终姓名。"""

    character_id: str
    name: str
    surname: str
    origin_type: str
    source: SourceEntry | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为兼容 JSON 的最终姓名结构。"""
        result: dict[str, Any] = {
            "character_id": self.character_id,
            "name": self.name,
            "surname": self.surname,
            "origin_type": self.origin_type,
        }
        if self.source is not None:
            result["source_id"] = self.source.source_id
            result["source"] = self.source.attribution()
        return result


class NamingValidationError(ValueError):
    """命名数据或选中方案不满足服务端约束。"""

    def __init__(self, issues: list[str] | tuple[str, ...]) -> None:
        self.issues = tuple(issues)
        super().__init__("；".join(self.issues))
