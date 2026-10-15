"""Canonicalize explicit chapter references at the model boundary, not in goals."""

import re

from pydantic import ValidationError

from application.creative.errors import CreativePause
from service.value_objects.creative import RoleSlot


def planned_role_slots(value, chapters: int) -> list[RoleSlot]:
    if not isinstance(value, list):
        raise CreativePause("role_slots_shape", "未来人物槽必须为列表")
    result, seen = [], set()
    for raw in value:
        slot = _role_slot(raw)
        if slot.slot_id in seen or slot.entrance_end > chapters:
            raise CreativePause("role_slot_scope", "未来人物槽重复或登场窗口超出本书规模")
        seen.add(slot.slot_id)
        result.append(slot)
    return result


def _role_slot(raw) -> RoleSlot:
    if not isinstance(raw, dict):
        raise CreativePause("role_slot_shape", "未来人物槽必须为对象")
    canonical = dict(raw)
    for key in ("entrance_start", "entrance_end"):
        value = canonical.get(key)
        if isinstance(value, bool):
            raise CreativePause("role_slot_chapter", "角色登场章号不能为布尔值")
        if isinstance(value, str) and (match := re.fullmatch(r"ch([1-9][0-9]*)", value)):
            canonical[key] = int(match[1])
    try:
        return RoleSlot.model_validate(canonical)
    except ValidationError as exc:
        raise CreativePause("invalid_role_slot", "未来人物槽字段或登场窗口无效") from exc
