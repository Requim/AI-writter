"""Check duplicate chapter 2 details"""
import asyncio
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from sqlalchemy import text

thread_id = "0ead5e1c-e50c-46ac-b065-23e080b5dcfa"

async def check():
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT id, chapter_index, title, word_count, 
                   LEFT(content, 200) as preview, 
                   created_at, status
            FROM chapters
            WHERE novel_id = :nid
            ORDER BY chapter_index, created_at
        """), {"nid": thread_id})
        for r in result.fetchall():
            print(f"id={str(r[0])[:12]}... | idx={r[1]} | title={r[2]} | words={r[3]} | status={r[6]} | created={r[5]}")
            print(f"  preview: {r[4][:100]}")
            print()

asyncio.run(check())
