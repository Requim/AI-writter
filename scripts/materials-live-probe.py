"""以真实素材服务验证旧作品绑定路径，不调用模型、不修改作品。"""

import asyncio
import json

from langgraph.types import Command

from application.research.materials import material_prompt_block, with_research_material
from config import settings
from infrastructure.research.library_client import ResearchLibraryClient


async def writer_probe(state, config):
    """仅检查进入生成节点的上下文，返回原路由而不生成或保存正文。"""
    material = state["creative_brief"]["research_material"]
    assert material["status"] == "applied"
    assert state["total_outline"]["creative_brief"]["research_material"] == material
    assert material["knowledge_version_id"] in material_prompt_block(
        state["creative_brief"], "chapter_writer",
    )
    return Command(goto="reflection_node", update={"probe_passed": True})


async def main():
    """用线上内部鉴权读取已审核版本，输出非敏感验收摘要。"""
    assert settings.RESEARCH_LIBRARY_ENABLED
    client = ResearchLibraryClient(
        settings.RESEARCH_LIBRARY_BASE_URL, settings.RESEARCH_LIBRARY_TOKEN,
        settings.RESEARCH_LIBRARY_TIMEOUT_SECONDS,
    )
    try:
        state = {"novel_type": "仙侠", "total_outline": {
            "story_background": "只读探针", "creative_brief": {"core_premise": "已有故事"},
        }}
        result = await with_research_material(writer_probe)(state, {
            "configurable": {"research_library": client},
        })
        material = result.update["creative_brief"]["research_material"]
        assert result.goto == "reflection_node"
        assert result.update["total_outline"]["story_background"] == "只读探针"
        assert "research_material" not in state["total_outline"]["creative_brief"]
        print(json.dumps({
            "read_only": True, "passed": result.update["probe_passed"],
            "knowledge_version_id": material["knowledge_version_id"],
            "sample_count": material["sample_count"], "digest": material["digest"],
        }, ensure_ascii=False))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
