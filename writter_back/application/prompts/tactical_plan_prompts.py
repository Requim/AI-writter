"""Bounded prompts for the rolling tactical planning layer."""

from __future__ import annotations

import json
from typing import Any

from application.continuity import build_budgeted_context, build_story_bible
from application.prompts.template_loader import render_prompt


TACTICAL_WINDOW_SCHEMA = {
    "window_objective": "string",
    "beats": [{
        "chapter_number": "integer",
        "slot_ref": "string",
        "tactical_goal": "string",
        "approach": "string",
        "bridge_from_previous": "string",
        "pressure_escalation": "string",
        "exit_hook": "string",
        "pacing": "string",
    }],
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_tactical_window_prompt(
    *,
    total_outline: dict[str, Any],
    volume: dict[str, Any],
    arcs: list[dict[str, Any]],
    slot_contracts: list[dict[str, Any]],
    story_state: str,
    start_chapter: int,
    end_chapter: int,
    validation_errors: list[str] | None = None,
    instruction: str = "",
) -> str:
    """Render a tactical prompt containing at most the selected seven slots."""
    retry = list(validation_errors or [])
    if instruction.strip():
        retry.insert(0, f"审核修改要求：{instruction.strip()}")
    retry_block = ""
    if retry:
        retry_block = "\n【必须修正】\n- " + "\n- ".join(retry)
    return render_prompt(
        "chapter/tactical_window.txt",
        story_bible=build_story_bible(total_outline, max_chars=2600),
        volume_json=_json(volume),
        arcs_json=_json(arcs),
        story_state=build_budgeted_context(story_state, max_chars=3200),
        slot_contracts_json=_json(slot_contracts),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        retry_block=retry_block,
    )
