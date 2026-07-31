"""Prompts and validation for the macro novel outline."""

from typing import Any


OUTLINE_SCHEMA: dict[str, str] = {
    "story_background": "string",
    "main_characters": "array",
    "main_plot": "object",
    "writing_style": "string",
    "total_chapters": "integer",
    "volumes": "array",
}

# Kept as an alias for callers that still refer to the old two-phase contract.
MACRO_ONLY_SCHEMA = OUTLINE_SCHEMA


def build_outline_prompt(
    novel_type: str,
    title: str,
    summary: str,
    target_total_chapters: int | None = None,
    requested_writing_style: str | None = None,
) -> str:
    """Build a bounded macro-outline prompt without per-chapter output."""
    chapter_requirement = (
        f"固定为用户计划的 {target_total_chapters} 章，不得擅自增加或减少。"
        if target_total_chapters
        else "根据题材选择 120-200 章，不要固定为某一个数字。"
    )
    style_requirement = (
        f"以用户指定的“{requested_writing_style}”为强制基调，并扩展为叙事视角、节奏、语言、对话和氛围规范。"
        if requested_writing_style
        else "明确叙事视角、节奏、语言基调、对话风格和氛围。"
    )
    return f"""请根据以下信息生成小说的宏观总纲。这里只规划全书结构，不生成逐章列表；
每一章的详细细纲会在后续工作流中按章生成。

【基础信息】
类型：{novel_type}
书名：{title}
简介：{summary}

【用户设定优先级】
- 书名和简介是用户确认的正史事实，不是供改写的灵感素材。
- 必须保留简介中出现的全部人名、人物关系、时代背景和核心故事方向。
- 简介较短时只能围绕已有事实扩展，不得替换主角、关系、题材或另起故事。
- 后续的世界设定、人物表、主线和分卷必须能够直接追溯到这份简介。

【总纲要求】
1. story_background（600-1000字）：世界规则、核心限制或力量代价、主要势力、
   社会矛盾和故事导火索。所有后续剧情必须服从这些约束。
2. main_characters：6-10名核心角色。每人包含“姓名、性格、目标、冲突对象、
   关系标签”，并与至少两名角色形成明确关系。
3. main_plot：使用“起、承、转、合”描述全书主线、关键反转和最终收束。
4. writing_style（150-300字）：{style_requirement}
5. total_chapters：{chapter_requirement}
6. volumes：规划 4-6 卷，必须连续覆盖第1章到 total_chapters。每卷包含：
   volume_name、volume_number、start_chapter、end_chapter、core_conflict、
   main_character_arc、climax_event，以及 next_volume_hook（卷尾衔接钩子）。

【重要边界】
- 禁止输出 chapters 字段或逐章事件列表。
- 总纲只负责全局约束和分卷方向，当前章节细纲由后续节点结合前文记忆生成。
- 输出必须是一个完整、可解析的 JSON 对象，不要使用 Markdown 代码块。

【JSON格式】
{{
  "story_background": "...",
  "main_characters": [
    {{"姓名": "", "性格": "", "目标": "", "冲突对象": "", "关系标签": ""}}
  ],
  "main_plot": {{"起": "", "承": "", "转": "", "合": ""}},
  "writing_style": "...",
  "total_chapters": 150,
  "volumes": [
    {{
      "volume_name": "第一卷 ...",
      "volume_number": 1,
      "start_chapter": 1,
      "end_chapter": 30,
      "core_conflict": "...",
      "main_character_arc": "...",
      "climax_event": "...",
      "next_volume_hook": "..."
    }}
  ]
}}"""


def volume_for_chapter(outline: dict[str, Any], chapter_number: int) -> dict[str, Any]:
    """Return the macro volume containing a one-based chapter number."""
    for volume in outline.get("volumes", []):
        try:
            start = int(volume.get("start_chapter", 0))
            end = int(volume.get("end_chapter", 0))
        except (TypeError, ValueError):
            continue
        if start <= chapter_number <= end:
            return volume
    return {}


def validate_outline(outline: dict[str, Any]) -> dict[str, Any]:
    """Validate only the macro contract; chapter plans are intentionally absent."""
    issues: list[str] = []
    fatal: list[str] = []

    if not str(outline.get("story_background", "")).strip():
        fatal.append("story_background 为空")
    if not isinstance(outline.get("main_plot"), dict) or not outline.get("main_plot"):
        fatal.append("main_plot 为空")
    if not str(outline.get("writing_style", "")).strip():
        fatal.append("writing_style 为空")

    characters = outline.get("main_characters", [])
    if not isinstance(characters, list) or len(characters) < 3:
        fatal.append("main_characters 不足 3 人")
    elif len(characters) < 6:
        issues.append(f"核心角色少于 6 人（当前 {len(characters)} 人）")

    try:
        total = int(outline.get("total_chapters", 0))
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        fatal.append("total_chapters 无效")
    elif not 30 <= total <= 300:
        issues.append(f"total_chapters={total} 超出建议范围 30-300")

    volumes = outline.get("volumes", [])
    if not isinstance(volumes, list) or not volumes:
        fatal.append("volumes 为空")
    elif total > 0:
        first_start = volumes[0].get("start_chapter")
        last_end = volumes[-1].get("end_chapter")
        if first_start != 1 or last_end != total:
            issues.append("volumes 未完整覆盖第1章到 total_chapters")

    if "chapters" in outline:
        issues.append("已忽略总纲中多余的 chapters 字段")

    return {
        "valid": not fatal,
        "issues": [*fatal, *issues],
        "fatal_issues": fatal,
    }
