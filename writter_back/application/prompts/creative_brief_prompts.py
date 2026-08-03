"""Creative-brief prompt and deterministic compatibility helpers."""

import json
from typing import Any

from application.prompts.version import PROMPT_VERSION


CREATIVE_BRIEF_SCHEMA = {
    "core_premise": "string",
    "protagonist_drive": "string",
    "core_conflict": "string",
    "theme_question": "string",
    "reader_promise": "string",
    "tone": "string",
    "originality_anchor": "string",
    "content_boundaries": "array",
}

_REQUIRED_TEXT_FIELDS = tuple(
    field for field, field_type in CREATIVE_BRIEF_SCHEMA.items() if field_type == "string"
)


def normalize_creative_brief(value: Any) -> dict[str, Any]:
    """Normalize model or user input into the stable creative-brief contract."""
    raw = value if isinstance(value, dict) else {}
    brief = {field: str(raw.get(field, "") or "").strip() for field in _REQUIRED_TEXT_FIELDS}
    boundaries = raw.get("content_boundaries", [])
    if isinstance(boundaries, str):
        boundaries = [item.strip() for item in boundaries.split("；") if item.strip()]
    if not isinstance(boundaries, list):
        boundaries = []
    brief["content_boundaries"] = [str(item).strip() for item in boundaries if str(item).strip()]
    return brief


def validate_creative_brief(brief: dict[str, Any]) -> list[str]:
    """Return missing creative-contract fields."""
    return [field for field in _REQUIRED_TEXT_FIELDS if not str(brief.get(field, "")).strip()]


def build_legacy_creative_brief(
    novel_type: str,
    title: str,
    summary: str,
    outline: dict[str, Any],
) -> dict[str, Any]:
    """Create a no-LLM compatibility brief for an already planned legacy novel."""
    main_plot = outline.get("main_plot", {})
    plot_text = json.dumps(main_plot, ensure_ascii=False) if main_plot else summary
    background = str(outline.get("story_background", "") or "")
    style = str(outline.get("writing_style", "") or "")
    premise = summary or f"《{title}》围绕既定主线展开"
    return normalize_creative_brief(
        {
            "core_premise": premise,
            "protagonist_drive": premise,
            "core_conflict": plot_text or premise,
            "theme_question": "人物为达成目标愿意付出什么代价",
            "reader_promise": f"持续兑现{novel_type}类型的冲突、变化与情绪回报",
            "tone": style or "遵循既有正文风格",
            "originality_anchor": background[:240] or premise,
            "content_boundaries": [],
        }
    )


def build_creative_brief_prompt(
    novel_type: str,
    title: str = "",
    summary: str = "",
    seed: dict[str, Any] | None = None,
    feedback: str = "",
) -> str:
    """Build the premise-first contract used by all downstream prompts."""
    seed_json = json.dumps(seed or {}, ensure_ascii=False, indent=2)
    feedback_block = f"\n【本次修改要求】\n{feedback}" if feedback else ""
    return f"""[PROMPT_VERSION:{PROMPT_VERSION}]
你是一名小说总策划。请先建立可供整条创作链复用的“创作简报”，不要写书名、简介或正文。

【已有输入】
类型：{novel_type}
暂定书名：{title or "未提供"}
用户简介：{summary or "未提供"}
用户创作意图：
{seed_json}{feedback_block}

【约束】
1. 用户已提供的书名、简介和创作意图是正史约束，只能补全，不能替换。
2. core_premise 用一句话表达“谁因什么异常处境，不得不做什么，否则失去什么”。
3. protagonist_drive 写清外在欲望、内在缺口和不能退出的理由。
4. core_conflict 必须是双方目标无法同时成立的冲突，不得只写氛围或题材。
5. theme_question 只提出贯穿全书的价值问题，不提前给答案。
6. reader_promise 写明读者将持续获得的类型快感、情绪体验和升级方式。
7. originality_anchor 给出一个可反复参与剧情的独特机制或关系，不用空泛标签。
8. tone 描述叙事视角、距离、节奏、句式、意象和对话潜台词倾向。
9. content_boundaries 列出用户要求避开的内容；没有则为空数组。

只输出与给定 schema 对应的 JSON 对象，不要 Markdown、解释或备选方案。"""
