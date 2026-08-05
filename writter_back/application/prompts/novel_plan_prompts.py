"""整书规划提示词构建器。"""

import json
from typing import Any

from application.prompts.template_loader import render_prompt


BLUEPRINT_SCHEMA = {
    "scale": "object",
    "ending_contract": "object",
    "volumes": "array",
    "arcs": "array",
}

VOLUME_SLOTS_SCHEMA = {"chapter_slots": "array"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_blueprint_prompt(
    *, scale: dict[str, Any], outline: dict[str, Any], existing_plan: dict[str, Any] | None,
    instruction: str, legacy_chapters: list[dict[str, Any]], errors: list[str],
) -> str:
    return render_prompt(
        "outline/plan_blueprint.txt",
        scale=_json(scale),
        outline=_json(outline),
        existing_plan=_json(existing_plan or {}),
        instruction=instruction or "无",
        legacy_chapters=_json(legacy_chapters),
        validation_errors=_json(errors),
    )


def build_volume_slots_prompt(
    *, scale: dict[str, Any], ending_contract: dict[str, Any], volume: dict[str, Any],
    arcs: list[dict[str, Any]], context: dict[str, Any], existing_slots: list[dict[str, Any]],
    detail_level: str, locked_through: int, errors: list[str], instruction: str = "",
) -> str:
    return render_prompt(
        "outline/plan_volume_slots.txt",
        scale=_json(scale),
        ending_contract=_json(ending_contract),
        volume=_json(volume),
        arcs=_json(arcs),
        generation_context=_json(context),
        existing_slots=_json(existing_slots),
        detail_level=detail_level,
        locked_through=locked_through,
        validation_errors=_json(errors),
        instruction=instruction or "无",
    )
