from unittest.mock import AsyncMock

import pytest

from application.prompts.creative_brief_prompts import normalize_creative_brief
from application.prompts.genre_strategy import genre_strategy_block
from application.research.materials import research_material_node, with_research_material
from langgraph.types import Command


def package(status="approved", genre="fantasy"):
    return {
        "status": status, "project_genre": genre, "version": 3,
        "knowledge_version_id": "knowledge-material-test", "sample_count": 2,
        "evidence_sample_ids": ["sample-a", "sample-b"],
        "writing_guidance": ["把资源限制落实为有代价的行动"],
        "mechanism_counts": {"resource_rivalry": 2},
        "opening_pattern_counts": {"immediate_crisis": 2},
        "originality_rules": ["不复制专名或独特设定组合"], "limitations": ["低置信度"],
        "clusters": [], "source_categories": ["玄幻"],
    }


@pytest.mark.asyncio
async def test_material_is_pinned_and_reaches_all_prompt_stages():
    client = AsyncMock()
    client.search.return_value = {"items": [{"content": package()}]}
    state = {"novel_type": "奇幻", "genre_strategy_enabled": True}
    config = {"configurable": {"research_library": client}}
    command = await research_material_node(state, config)
    brief = normalize_creative_brief(command.update["creative_brief"])
    assert command.goto == "genre_strategy_node"
    assert brief["research_material"]["evidence_sample_ids"] == ["sample-a", "sample-b"]
    for stage in ("creative_brief", "outline", "chapter_outline", "chapter_writer", "reflection"):
        prompt = genre_strategy_block("fantasy", brief, stage)
        assert "knowledge-material-test" in prompt
        assert "resource_rivalry" in prompt
        assert "低置信度" in prompt
    await research_material_node({**state, "creative_brief": brief}, config)
    client.search.assert_awaited_once_with(project_genre="fantasy", limit=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,genre", [("draft", "fantasy"), ("approved", "romance")])
async def test_material_rejects_unapproved_or_wrong_genre(status, genre):
    client = AsyncMock()
    client.search.return_value = {"items": [{"content": package(status, genre)}]}
    with pytest.raises(ValueError):
        await research_material_node({"novel_type": "fantasy"}, {
            "configurable": {"research_library": client},
        })


@pytest.mark.asyncio
async def test_absent_material_is_not_reported_as_applied():
    client = AsyncMock()
    client.search.return_value = {"items": []}
    command = await research_material_node({"novel_type": "urban"}, {
        "configurable": {"research_library": client},
    })
    assert command.update["creative_brief"]["research_material"]["status"] == "no_approved_material"


@pytest.mark.asyncio
async def test_material_outage_is_not_silent_success():
    client = AsyncMock()
    client.search.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        await research_material_node({"novel_type": "fantasy"}, {
            "configurable": {"research_library": client},
        })


@pytest.mark.asyncio
async def test_legacy_continuation_receives_material_before_generation():
    client = AsyncMock()
    client.search.return_value = {"items": [{"content": package()}]}
    state = {"novel_type": "fantasy", "total_outline": {
        "story_background": "已有世界", "creative_brief": {"core_premise": "已有故事"},
    }}

    async def writer(value, config):
        assert value["total_outline"]["creative_brief"]["research_material"]["status"] == "applied"
        return Command(goto="reflection_node", update={"current_chapter_content": "新章节"})

    command = await with_research_material(writer)(state, {
        "configurable": {"research_library": client},
    })
    assert command.goto == "reflection_node"
    assert command.update["total_outline"]["story_background"] == "已有世界"
    assert command.update["creative_brief"]["core_premise"] == "已有故事"
    assert "research_material" not in state["total_outline"]["creative_brief"]
    assert command.update["current_chapter_content"] == "新章节"


@pytest.mark.asyncio
async def test_existing_material_is_not_replaced_during_continuation():
    client = AsyncMock()
    state = {"creative_brief": {"research_material": {"status": "applied", "version": 2}}}
    result = Command(goto="reflection_node", update={"current_chapter_content": "续写"})

    async def writer(value, config):
        assert value["creative_brief"]["research_material"]["version"] == 2
        return result

    assert await with_research_material(writer)(state, {
        "configurable": {"research_library": client},
    }) is result
    client.search.assert_not_called()
