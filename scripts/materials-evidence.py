"""读取指定验收作品的素材版本、阶段和章节证据。"""

import asyncio
import json
import sys
from uuid import UUID

import asyncpg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config import settings


async def archive_evidence(conn, novel_id):
    novel = await conn.fetchrow(
        "SELECT title,status,progress,total_outline->'creative_brief'->'research_material' "
        "AS material FROM novels WHERE id=$1", UUID(novel_id),
    )
    chapters = await conn.fetch(
        "SELECT chapter_index,title,word_count,status,content,revision_count "
        "FROM chapters WHERE novel_id=$1 ORDER BY chapter_index", UUID(novel_id),
    )
    return {"novel": dict(novel) if novel else None,
            "chapters": [dict(row) for row in chapters]}


async def main():
    """只读验收作品 checkpoint，不导出鉴权和模型密钥。"""
    novel_id = str(UUID(sys.argv[1]))
    dsn = str(settings.DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        thread = await conn.fetchval(
            "SELECT thread_id FROM checkpoints WHERE thread_id LIKE $1 LIMIT 1",
            f"%{novel_id}%",
        )
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            checkpoint = await saver.aget_tuple({"configurable": {"thread_id": thread}})
        state = checkpoint.checkpoint["channel_values"]
        brief = state.get("creative_brief") or {}
        total = state.get("total_outline") or {}
        result = {
            "novel_id": novel_id, "checkpoint": checkpoint.config,
            "material": brief.get("research_material"),
            "outline_material": (total.get("creative_brief") or {}).get("research_material"),
            "strategy": state.get("genre_strategy"), "brief": brief.get("core_premise"),
            "current_chapter_index": state.get("current_chapter_index"),
            "is_completed": state.get("is_completed"),
            "proposal_kind": (state.get("pending_proposal") or {}).get("kind"),
            "chapter_outlines": state.get("chapter_outlines"),
            "chapter_content": state.get("current_chapter_content"),
            "completed_chapters": state.get("completed_chapters"),
            "quality_gate": state.get("quality_gate"),
            "reflection_issues": state.get("reflection_issues"),
            "revision_attempts": state.get("revision_attempts"),
            "errors": state.get("errors"),
            "archive": await archive_evidence(conn, novel_id),
        }
        print(json.dumps(result, ensure_ascii=False, default=str))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
