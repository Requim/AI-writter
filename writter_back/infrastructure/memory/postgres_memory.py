"""PostgreSQL + pgvector 长期记忆实现"""
import json
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, text

from service.ports.memory_service import MemoryService


class PostgresMemoryAdapter(MemoryService):
    """PostgreSQL长期记忆适配器"""

    def __init__(self, database_url: str, async_session: async_sessionmaker):
        self.database_url = database_url
        self.async_session = async_session

    async def store(self, novel_id: str, content: str, metadata: Dict[str, Any]) -> str:
        """存储记忆"""
        memory_id = str(uuid.uuid4())
        async with self.async_session() as session:
            # 简化版：不存储向量，仅存储文本
            # 完整版需要pgvector扩展和向量化
            stmt = text("""
                INSERT INTO novel_memories (id, novel_id, content, metadata, created_at)
                VALUES (:id, :novel_id, :content, :metadata, NOW())
                RETURNING id
            """)
            await session.execute(stmt, {
                "id": uuid.UUID(memory_id),
                "novel_id": uuid.UUID(novel_id),
                "content": content,
                "metadata": json.dumps(metadata)
            })
            await session.commit()
            return memory_id

    async def retrieve(self, novel_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索相关记忆 - 简化版：基于关键词匹配"""
        async with self.async_session() as session:
            stmt = text("""
                SELECT id, content, metadata
                FROM novel_memories
                WHERE novel_id = :novel_id
                ORDER BY created_at DESC
                LIMIT :top_k
            """)
            result = await session.execute(stmt, {
                "novel_id": uuid.UUID(novel_id),
                "top_k": top_k
            })
            rows = result.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2] if isinstance(row[2], dict) else (json.loads(row[2]) if row[2] else {})
                }
                for row in rows
            ]

    async def get_novel_context(self, novel_id: str) -> str:
        """获取小说完整上下文"""
        memories = await self.retrieve(novel_id, "", top_k=100)
        context_parts = []
        for m in memories:
            context_parts.append(m["content"])
        return "\n\n".join(context_parts)

    async def store_chapter_memory(self, novel_id: str, chapter: Dict[str, Any]) -> str:
        """存储章节到长期记忆（包含开头和结尾，确保无缝衔接）"""
        full_content = chapter.get('content', '')
        # 取前800字 + 后500字，确保下一章开篇能无缝衔接
        head = full_content[:800]
        tail = f"\n...（上文结尾）...\n{full_content[-500:]}" if len(full_content) > 1300 else ""
        content = f"第{chapter.get('chapter_index', 0)+1}章：{chapter.get('title', '')}\n\n{head}{tail}"

        metadata = {
            "type": "chapter",
            "chapter_index": chapter.get('chapter_index'),
            "title": chapter.get('title'),
            "word_count": chapter.get('word_count', 0)
        }

        return await self.store(novel_id, content, metadata)

    async def search_similar(self, novel_id: str, embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """基于向量相似度检索记忆（需要pgvector扩展）

        完整版实现需要pgvector扩展支持:
        SELECT id, content, metadata, 1 - (embedding <=> :query_embedding) AS similarity
        FROM novel_memories
        WHERE novel_id = :novel_id
        ORDER BY similarity DESC
        LIMIT :top_k
        """
        # 简化版：回退到基于时间的检索
        return await self.retrieve(novel_id, "", top_k=top_k)
