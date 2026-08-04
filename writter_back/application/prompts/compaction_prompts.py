"""Prompts for bounded, optional chapter compaction."""

import json

from application.continuity import compact_text
from application.prompts.template_loader import render_prompt


def build_compaction_prompt(
    content: str,
    chapter_outline: dict,
    target_words: int,
    reasons: list[str],
    ending_anchor: str,
) -> str:
    """Build a loss-averse compaction request for an overlong draft."""
    contract = json.dumps(chapter_outline, ensure_ascii=False, indent=2)
    reason_text = "\n".join(f"- {reason}" for reason in reasons)
    return render_prompt(
        "compaction/chapter.txt",
        reasons=reason_text,
        target_words=target_words,
        ending_anchor=ending_anchor,
        chapter_contract=compact_text(contract, 5000),
        content=content,
    )
