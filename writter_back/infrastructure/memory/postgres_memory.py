"""PostgreSQL + pgvector 长期记忆实现"""

import json
import logging
import uuid
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text

from service.ports.memory_service import MemoryService

logger = logging.getLogger(__name__)


async def _latest_layer(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    memory_type: str,
    current_index: int,
) -> str | None:
    result = await session.execute(
        text(
            "SELECT content FROM novel_memories "
            "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
            "AND metadata @> CAST(:meta_filter AS jsonb) "
            "AND (metadata->>'chapter_index' IS NULL "
            "OR (metadata->>'chapter_index')::int < :current_index) "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {
            "tenant_id": tenant_id,
            "novel_id": novel_id,
            "meta_filter": json.dumps({"type": memory_type}),
            "current_index": current_index,
        },
    )
    row = result.fetchone()
    return str(row[0]) if row else None


async def _recent_chapters(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    current_index: int,
    count: int,
) -> list[str]:
    result = await session.execute(
        text(
            "SELECT content FROM novel_memories "
            "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
            "AND metadata @> CAST(:type_filter AS jsonb) "
            "AND (metadata->>'chapter_index')::int >= :min_index "
            "AND (metadata->>'chapter_index')::int < :current_index "
            "ORDER BY (metadata->>'chapter_index')::int ASC"
        ),
        {
            "tenant_id": tenant_id,
            "novel_id": novel_id,
            "type_filter": json.dumps({"type": "chapter"}),
            "min_index": current_index - count,
            "current_index": current_index,
        },
    )
    return [str(row[0]) for row in result.fetchall()]


async def _historical_summaries(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    max_index: int,
) -> list[str]:
    result = await session.execute(
        text(
            "SELECT content, metadata FROM novel_memories "
            "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
            "AND metadata @> CAST(:type_filter AS jsonb) "
            "AND (metadata->>'chapter_index')::int < :max_index "
            "ORDER BY (metadata->>'chapter_index')::int ASC"
        ),
        {
            "tenant_id": tenant_id,
            "novel_id": novel_id,
            "type_filter": json.dumps({"type": "chapter_summary"}),
            "max_index": max_index,
        },
    )
    summaries = []
    for content, metadata in result.fetchall():
        parsed = (
            metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
        )
        summaries.append(f"第{parsed.get('chapter_index', 0) + 1}章摘要：{content}")
    return summaries


def _format_hierarchical_context(
    story_state: str | None,
    rolling_plan: str | None,
    recent_chapters: list[str],
    historical_summaries: list[str],
) -> str:
    parts = []
    if story_state:
        parts.append(f"<S层故事状态>\n{story_state}")
    if rolling_plan:
        parts.append(f"<P层滚动规划>\n{rolling_plan}")
    if recent_chapters:
        parts.append("<M层近期章节>\n" + "\n\n".join(recent_chapters))
    if historical_summaries:
        parts.append("<L层历史章节摘录>\n" + "\n".join(historical_summaries))
    return "\n\n".join(parts)


class PostgresMemoryAdapter(MemoryService):
    """PostgreSQL长期记忆适配器"""

    def __init__(self, database_url: str, async_session: async_sessionmaker):
        self.database_url = database_url
        self.async_session = async_session

    @staticmethod
    def build_chapter_memory(chapter: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        full_content = chapter.get("content", "")
        head = full_content[:800]
        tail = (
            f"\n...（上文结尾）...\n{full_content[-500:]}"
            if len(full_content) > 1300
            else ""
        )
        content = (
            f"第{chapter.get('chapter_index', 0) + 1}章：{chapter.get('title', '')}"
            f"\n\n{head}{tail}"
        )
        metadata = {
            "type": "chapter",
            "chapter_index": chapter.get("chapter_index"),
            "title": chapter.get("title"),
            "word_count": chapter.get("word_count", 0),
        }
        return content, metadata

    async def store(
        self, tenant_id: str, novel_id: str, content: str, metadata: Dict[str, Any]
    ) -> str:
        """存储记忆"""
        memory_id = str(uuid.uuid4())
        async with self.async_session() as session:
            # 简化版：不存储向量，仅存储文本
            # 完整版需要pgvector扩展和向量化
            stmt = text("""
                INSERT INTO novel_memories (id, tenant_id, novel_id, content, metadata, created_at)
                VALUES (:id, :tenant_id, :novel_id, :content, :metadata, NOW())
                RETURNING id
            """)
            await session.execute(
                stmt,
                {
                    "id": uuid.UUID(memory_id),
                    "tenant_id": uuid.UUID(tenant_id),
                    "novel_id": uuid.UUID(novel_id),
                    "content": content,
                    "metadata": json.dumps(metadata),
                },
            )
            await session.commit()
            return memory_id

    async def retrieve(
        self, tenant_id: str, novel_id: str, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """检索相关记忆 - 简化版：基于关键词匹配"""
        async with self.async_session() as session:
            stmt = text("""
                SELECT id, content, metadata
                FROM novel_memories
                WHERE tenant_id = :tenant_id AND novel_id = :novel_id
                ORDER BY created_at DESC
                LIMIT :top_k
            """)
            result = await session.execute(
                stmt,
                {
                    "tenant_id": uuid.UUID(tenant_id),
                    "novel_id": uuid.UUID(novel_id),
                    "top_k": top_k,
                },
            )
            rows = result.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2]
                    if isinstance(row[2], dict)
                    else (json.loads(row[2]) if row[2] else {}),
                }
                for row in rows
            ]

    async def get_novel_context(self, tenant_id: str, novel_id: str) -> str:
        """获取小说完整上下文"""
        memories = await self.retrieve(tenant_id, novel_id, "", top_k=100)
        context_parts = []
        for m in memories:
            context_parts.append(m["content"])
        return "\n\n".join(context_parts)

    async def store_chapter_memory(
        self, tenant_id: str, novel_id: str, chapter: Dict[str, Any]
    ) -> str:
        """存储章节到长期记忆（包含开头和结尾，确保无缝衔接）"""
        content, metadata = self.build_chapter_memory(chapter)
        return await self.store(tenant_id, novel_id, content, metadata)

    async def delete_chapter_memory(
        self, tenant_id: str, novel_id: str, chapter_index: int
    ) -> None:
        """删除指定章节索引的旧记忆"""
        async with self.async_session() as session:
            stmt = text("""
                DELETE FROM novel_memories
                WHERE tenant_id = :tenant_id AND novel_id = :novel_id
                  AND metadata @> CAST(:meta_filter AS jsonb)
            """)
            await session.execute(
                stmt,
                {
                    "tenant_id": uuid.UUID(tenant_id),
                    "novel_id": uuid.UUID(novel_id),
                    "meta_filter": json.dumps(
                        {"type": "chapter", "chapter_index": chapter_index}
                    ),
                },
            )
            await session.commit()

    async def search_similar(
        self, tenant_id: str, novel_id: str, embedding: List[float], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """基于向量相似度检索记忆（需要pgvector扩展）

        完整版实现需要pgvector扩展支持:
        SELECT id, content, metadata, 1 - (embedding <=> :query_embedding) AS similarity
        FROM novel_memories
        WHERE novel_id = :novel_id
        ORDER BY similarity DESC
        LIMIT :top_k
        """
        # 简化版：回退到基于时间的检索
        return await self.retrieve(tenant_id, novel_id, "", top_k=top_k)

    async def store_chapter_summary(
        self,
        tenant_id: str,
        novel_id: str,
        chapter_index: int,
        summary_content: str,
    ) -> str:
        """Store L-layer chapter summary"""
        logger.info(
            "Storing chapter summary for novel %s, chapter %d", novel_id, chapter_index
        )
        metadata = {"type": "chapter_summary", "chapter_index": chapter_index}
        return await self.store(tenant_id, novel_id, summary_content, metadata)

    async def update_story_state(
        self, tenant_id: str, novel_id: str, state_content: str
    ) -> None:
        """Upsert S-layer story state (delete old type='story_state', insert new)"""
        logger.info("Updating story state for novel %s", novel_id)
        async with self.async_session() as session:
            # Delete existing story_state
            stmt = text("""
                DELETE FROM novel_memories
                WHERE tenant_id = :tenant_id AND novel_id = :novel_id
                  AND metadata @> CAST(:meta_filter AS jsonb)
            """)
            await session.execute(
                stmt,
                {
                    "tenant_id": uuid.UUID(tenant_id),
                    "novel_id": uuid.UUID(novel_id),
                    "meta_filter": json.dumps({"type": "story_state"}),
                },
            )

            # Insert new story state
            new_id = str(uuid.uuid4())
            stmt = text("""
                INSERT INTO novel_memories (id, tenant_id, novel_id, content, metadata, created_at)
                VALUES (:id, :tenant_id, :novel_id, :content, :metadata, NOW())
            """)
            await session.execute(
                stmt,
                {
                    "id": uuid.UUID(new_id),
                    "tenant_id": uuid.UUID(tenant_id),
                    "novel_id": uuid.UUID(novel_id),
                    "content": state_content,
                    "metadata": json.dumps({"type": "story_state"}),
                },
            )
            await session.commit()

    async def get_hierarchical_context(
        self,
        tenant_id: str,
        novel_id: str,
        current_index: int,
        m_count: int = 3,
    ) -> str:
        """Get S+P+M+L hierarchical context as a formatted string."""
        logger.info(
            "Building hierarchical context for novel %s, current_index=%d, m_count=%d",
            novel_id,
            current_index,
            m_count,
        )
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session:
            tenant_uuid = uuid.UUID(tenant_id)
            story_state = await _latest_layer(
                session, tenant_uuid, novel_uuid, "story_state", current_index
            )
            rolling_plan = await _latest_layer(
                session, tenant_uuid, novel_uuid, "rolling_plan", current_index
            )
            recent = await _recent_chapters(
                session, tenant_uuid, novel_uuid, current_index, m_count
            )
            historical = await _historical_summaries(
                session, tenant_uuid, novel_uuid, current_index - m_count
            )
        return _format_hierarchical_context(
            story_state, rolling_plan, recent, historical
        )
