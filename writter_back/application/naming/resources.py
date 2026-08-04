"""UTF-8 package-resource loaders for naming data."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from application.naming.models import SourceEntry, SurnameEntry


def _load_json(filename: str) -> list[dict[str, Any]]:
    resource = files("application.naming.data").joinpath(filename)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"命名资源 {filename} 的顶层必须是数组")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"命名资源 {filename} 只能包含对象")
    return payload


def _ensure_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"命名资源存在重复 {field_name}")


@lru_cache(maxsize=1)
def load_source_entries() -> tuple[SourceEntry, ...]:
    """加载并校验全部古典文本取名词条。"""
    entries = tuple(
        SourceEntry.from_mapping(item) for item in _load_json("classical_sources.json")
    )
    _ensure_unique(tuple(item.source_id for item in entries), "source_id")
    if not entries:
        raise ValueError("古典文本取名词库不能为空")
    return entries


@lru_cache(maxsize=1)
def load_surnames() -> tuple[SurnameEntry, ...]:
    """加载并校验全部真实姓氏词条。"""
    entries = tuple(
        SurnameEntry.from_mapping(item) for item in _load_json("surnames.json")
    )
    _ensure_unique(tuple(item.surname for item in entries), "surname")
    if not entries or any(item.weight <= 0 for item in entries):
        raise ValueError("姓氏词库不能为空且权重必须为正数")
    return entries
