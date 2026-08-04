"""Premise-grounded title generation prompts."""

import json
from typing import Any

from application.prompts.template_loader import render_prompt


TITLE_CANDIDATES_SCHEMA = {"candidates": "array"}


def build_title_prompt(
    novel_type: str,
    creative_brief: dict[str, Any] | None = None,
    main_characters: list[dict[str, Any]] | None = None,
) -> str:
    """Generate scored title candidates that preserve the creative promise."""
    return render_prompt(
        "title/candidates.txt",
        novel_type=novel_type,
        creative_brief=json.dumps(creative_brief or {}, ensure_ascii=False, indent=2),
        main_characters=json.dumps(main_characters or [], ensure_ascii=False, indent=2),
    )


TITLE_TEMPERATURE = 0.85
TITLE_TOP_P = 0.92
