"""Evidence-based chapter reflection prompts."""

import json

from application.continuity import (
    build_budgeted_context,
    compact_story_bible,
    compact_text,
)
from application.prompts.template_loader import render_prompt


CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


def split_into_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """将文本按固定大小分块，并保留重叠区域。"""
    if len(text) <= chunk_size:
        return [{"start": 0, "end": len(text), "text": text, "chunk_index": 0}]
    chunks: list[dict] = []
    position = 0
    while position < len(text):
        end = min(position + chunk_size, len(text))
        chunks.append(
            {
                "start": position,
                "end": end,
                "text": text[position:end],
                "chunk_index": len(chunks),
            }
        )
        position += chunk_size - overlap
    return chunks


def _editorial_checks() -> str:
    return render_prompt("reflection/editorial_checks.txt")


def build_score_contract() -> str:
    """加载服务端评分量纲契约。"""
    return render_prompt("reflection/score_contract.txt")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_chunk_reflection_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    story_bible: str = "",
) -> str:
    """生成只审核当前文本块的提示词。"""
    return render_prompt(
        "reflection/chunk.txt",
        chunk_number=chunk_index + 1,
        total_chunks=total_chunks,
        chunk_start=chunk_start,
        chunk_end=chunk_end,
        editorial_checks=_editorial_checks(),
        chunk_text=chunk_text,
        chapter_outline=_json(chapter_outline),
        main_characters=_json(main_characters),
        memory_context=build_budgeted_context(memory_context, max_chars=1800),
        story_bible=compact_story_bible(story_bible, 1400) if story_bible else "无",
    )


def _format_chunk_results(chunk_results: list[dict]) -> str:
    lines: list[str] = []
    for index, result in enumerate(chunk_results):
        issues = result.get("issues", [])
        if not issues:
            lines.append(f"第{index + 1}块：无问题")
            continue
        start, end = result.get("start", 0), result.get("end", 0)
        lines.append(f"第{index + 1}块（{start}-{end}字符）发现 {len(issues)} 个问题：")
        for issue in issues:
            issue_type = issue.get("type", "?")
            severity = issue.get("severity", "?")
            lines.append(f"  - [{issue_type}]({severity}) {issue.get('description', '')}")
    return "\n".join(lines)


def build_aggregation_prompt(
    chunk_results: list[dict],
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
    story_bible: str = "",
    previous_issues: list[dict] | None = None,
) -> str:
    """聚合局部结论，并基于完整正文完成全局审核。"""
    return render_prompt(
        "reflection/aggregation.txt",
        chunks_summary=_format_chunk_results(chunk_results),
        editorial_checks=_editorial_checks(),
        chapter_content=compact_text(chapter_content, 9000, tail_ratio=0.45),
        chapter_outline=_json(chapter_outline),
        main_characters=_json(main_characters),
        memory_context=build_budgeted_context(memory_context, max_chars=2600),
        story_bible=compact_story_bible(story_bible, 2200) if story_bible else "无",
        previous_issues=_json(previous_issues or []),
        content_length=content_length,
    )


def build_reflection_prompt(
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
    story_bible: str = "",
    previous_issues: list[dict] | None = None,
) -> str:
    """生成有评分锚点和原文证据约束的整章审核提示词。"""
    return render_prompt(
        "reflection/full.txt",
        editorial_checks=_editorial_checks(),
        chapter_content=compact_text(chapter_content, 9000, tail_ratio=0.45),
        chapter_outline=_json(chapter_outline),
        main_characters=_json(main_characters),
        memory_context=build_budgeted_context(memory_context, max_chars=2600),
        story_bible=compact_story_bible(story_bible, 2200) if story_bible else "无",
        previous_issues=_json(previous_issues or []),
        content_length=content_length,
    )


CHUNK_REFLECTION_SCHEMA = {
    "issues": {
        "type": "string",
        "severity": "string",
        "priority_action": "string",
        "issue_resolved": "boolean",
        "location": "string",
        "description": "string",
        "evidence": "string",
        "suggestion": "string",
    },
}

RUBRIC_SCHEMA = {
    "causality": "number",
    "continuity": "number",
    "character": "number",
    "scene_function": "number",
    "voice": "number",
    "prose_specificity": "number",
    "ending_effect": "number",
}

AGGREGATION_SCHEMA = {
    "score_scale": "integer",
    "rubric_scores": RUBRIC_SCHEMA,
    "hard_failures": "array",
    "word_count_analysis": {
        "total_count": "integer",
        "effective_density": "number",
        "is_valid_word_count": "boolean",
    },
    "issues": "array",
    "logic_chain_status": "string",
    "foreshadowing_check": "string",
}

REFLECTION_SCHEMA = AGGREGATION_SCHEMA
