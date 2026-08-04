"""Prompt resource, rendering and content-contract regression tests."""

import ast
from pathlib import Path
from string import Template

import pytest

from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.prompts.chapter_writer_prompts import (
    build_chapter_continue_prompt,
    build_chapter_writer_prompt,
    build_first_scene_prompt,
    build_next_scene_prompt,
    build_scene_continue_prompt,
)
from application.prompts.character_design_prompts import (
    CHARACTER_DESIGN_SCHEMA,
    build_character_design_prompt,
)
from application.prompts.creative_brief_prompts import CREATIVE_BRIEF_SCHEMA
from application.prompts.outline_prompts import build_outline_prompt
from application.prompts.reflection_prompts import build_reflection_prompt
from application.prompts.revision_prompts import build_patch_revision_prompt
from application.prompts.template_loader import render_prompt
from application.prompts.version import PROMPT_VERSION


PROMPT_ROOT = Path(__file__).parents[1] / "application" / "prompts"
TEMPLATE_ROOT = PROMPT_ROOT / "templates"


def _scene() -> dict:
    return {
        "location": "雨夜车站",
        "characters": ["许澄"],
        "events": {"entry": "抵达", "struggle": "被拦", "result": "改道"},
        "sensory_anchors": [
            {"sense": "auditory", "detail": "失真广播", "dramatic_function": "误导判断"}
        ],
    }


def _outline() -> dict:
    return {
        "chapter_number": 1,
        "title": "错站",
        "ending_mode": "decision",
        "scenes": [_scene()],
        "logic_hooks": {},
        "estimated_word_count": 4200,
    }


def _long_prompt_literals(path: Path) -> list[ast.Constant]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) > 300
    ]


def test_all_prompt_templates_are_valid_utf8_string_templates() -> None:
    paths = sorted(TEMPLATE_ROOT.rglob("*.txt"))
    assert paths
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "\ufffd" not in content
        assert Template(content).is_valid(), path


def test_renderer_is_versioned_strict_and_preserves_dollar_in_values() -> None:
    prompt = render_prompt(
        "title/candidates.txt",
        novel_type="悬疑$类型",
        creative_brief="{}",
        main_characters="[]",
    )
    assert f"PROMPT_VERSION:{PROMPT_VERSION}" in prompt
    assert "悬疑$类型" in prompt
    with pytest.raises(ValueError, match="缺少变量"):
        render_prompt("title/candidates.txt", novel_type="悬疑")
    with pytest.raises(ValueError, match="非法提示词模板路径"):
        render_prompt("../version.txt")
    with pytest.raises(ValueError, match="非法提示词模板路径"):
        render_prompt(r"..\version.txt")


def test_prompt_python_modules_do_not_embed_long_prompt_literals() -> None:
    violations = [
        f"{path.name}:{node.lineno}"
        for path in PROMPT_ROOT.glob("*.py")
        for node in _long_prompt_literals(path)
    ]
    assert violations == []


def test_character_design_prompt_only_allows_server_pool_references() -> None:
    pool = [{"surname": "许", "source_id": "shijing-001", "name": "许清扬"}]
    prompt = build_character_design_prompt("悬疑", {}, pool)
    assert CHARACTER_DESIGN_SCHEMA == {
        "core_roles": "array",
        "supporting_characters": "array",
        "relationships": "array",
    }
    assert "恰好 3 个" in prompt
    assert "只能包含" in prompt and "surname、source_id" in prompt
    assert "不得返回姓名、原句、释义" in prompt


def test_outline_keeps_accepted_cast_and_adds_macro_pressure_curves() -> None:
    characters = [{"character_id": "lead", "name": "许清扬"}]
    prompt = build_outline_prompt("悬疑", "雨站", "旧案重启", main_characters=characters)
    assert "许清扬" in prompt
    assert "不得换名、删人" in prompt
    assert "antagonist_plan" in prompt
    assert "truth_reveal_ladder" in prompt
    assert "cost_curve" in prompt and "relationship_turns" in prompt


def test_creative_brief_and_chapter_contract_expose_new_fields() -> None:
    assert {"setting_context", "naming_preference", "style_fingerprint", "trope_contract"} <= set(
        CREATIVE_BRIEF_SCHEMA
    )
    prompt = build_chapter_outline_prompt(
        2,
        "悬疑",
        "雨站",
        {"total_chapters": 12, "volumes": []},
        'recent_narrative_patterns: [{"ending_mode":"revelation"}]',
    )
    assert "recent_narrative_patterns" in prompt
    assert "sensory_anchors" in prompt
    assert "不得无理由连续重复" in prompt


def test_every_prose_path_uses_shared_principles_and_ending_mode() -> None:
    outline = _outline()
    common = {
        "scene": _scene(), "chapter_outline": outline, "novel_type": "悬疑",
        "title": "雨站", "chapter_num": 1, "ch_title": "错站",
    }
    prompts = [
        build_first_scene_prompt(
            **common, memory_context="", target_words=1000, total_scenes=2,
            logic_hooks={}, internal_monologue="",
        ),
        build_next_scene_prompt(
            **common, scene_index=2, total_scenes=2, prev_scene_digest="改道",
            prev_word_count=900, correction_note="", target_words=1000,
            logic_hooks={}, internal_monologue="", memory_context="",
        ),
        build_scene_continue_prompt(500, 1000, "已有正文"),
        build_chapter_writer_prompt(outline, "悬疑", "雨站", ""),
        build_chapter_continue_prompt(2500, "已有正文"),
    ]
    assert all("POV 知识边界" in prompt for prompt in prompts)
    assert all("ending_mode" in prompt for prompt in prompts)
    assert "必须翻到下一页" not in prompts[3]


def test_reflection_prompt_contains_score_anchors_and_ai_cliche_checks() -> None:
    prompt = build_reflection_prompt("正文", {}, [], "", 2)
    assert "1/3/5 分锚点" in prompt
    assert "去掉人物姓名后" in prompt
    assert "眸色一沉" in prompt
    assert '"score_scale": 5' in prompt


def test_prompt_compaction_preserves_complete_character_sections() -> None:
    active = "ACTIVE_CARD_MUST_SURVIVE" * 80
    index = "OTHER_CHARACTER_INDEX_MUST_SURVIVE" * 40
    bible = f"<全局规则>\n{'G' * 6000}\n\n<当前场景角色卡>\n{active}\n\n<其他角色索引>\n{index}"
    prompts = [
        build_chapter_writer_prompt(_outline(), "悬疑", "雨站", "", story_bible=bible),
        build_reflection_prompt("正文", {}, [], "", 2, story_bible=bible),
        build_patch_revision_prompt("问题", "正文", {}, story_bible=bible),
    ]
    assert all(active in prompt for prompt in prompts)
    assert all(index in prompt for prompt in prompts)
