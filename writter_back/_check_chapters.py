"""Check chapters and memories for the specific novel"""
import asyncio
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from sqlalchemy import text

thread_id = "0ead5e1c-e50c-46ac-b065-23e080b5dcfa"

async def check():
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.engine.begin() as conn:
        # Check chapters
        result = await conn.execute(text("""
            SELECT chapter_index, title, word_count, left(content, 100) as preview
            FROM chapters
            WHERE novel_id = :nid
            ORDER BY chapter_index
        """), {"nid": thread_id})
        rows = result.fetchall()
        print(f"Chapters for novel: {len(rows)}")
        for r in rows:
            print(f"  Ch {r[0]}: {r[1]}, {r[2]} words")
        
        # Check memories
        result = await conn.execute(text("""
            SELECT left(content, 200) as preview, metadata::text, created_at
            FROM novel_memories
            WHERE novel_id = :nid
            ORDER BY created_at
        """), {"nid": thread_id})
        rows = result.fetchall()
        print(f"\nMemories for novel: {len(rows)}")
        for i, r in enumerate(rows):
            print(f"  Memory {i}: {r[0][:80]}... | created_at={r[2]}")
        
        # Check checkpoint state
        result = await conn.execute(text("""
            SELECT thread_id, checkpoint,
                   checkpoint ->> 'channel_values' as channel_values
            FROM checkpoints
            WHERE thread_id = :tid
            ORDER BY checkpoint ->> 'ts' DESC
            LIMIT 3
        """), {"tid": thread_id})
        rows = result.fetchall()
        print(f"\nCheckpoints for thread: {len(rows)}")
        for r in rows:
            cv = r[2]
            has_completed = 'completed_chapters' in cv if cv and isinstance(cv, str) else False
            has_memory = 'memory_context' in cv if cv and isinstance(cv, str) else False
            print(f"  thread_id={str(r[0])[:16]}..., has_completed_chapters={has_completed}, has_memory_context={has_memory}")
            if cv and len(cv) > 100:
                print(f"    channel_values preview: {cv[:300]}")

asyncio.run(check())
