"""Deep check checkpoint state for completed_chapters"""
import asyncio
import json
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from sqlalchemy import text

thread_id = "0ead5e1c-e50c-46ac-b065-23e080b5dcfa"

async def check():
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.engine.begin() as conn:
        # Query checkpoints
        result = await conn.execute(text("""
            SELECT thread_id, checkpoint, checkpoint_ns, 
                   checkpoint ->> 'ts' as ts,
                   checkpoint ->> 'channel_values' as channel_values
            FROM checkpoints
            WHERE thread_id = :tid
            ORDER BY checkpoint ->> 'ts' DESC
            LIMIT 5
        """), {"tid": thread_id})
        rows = result.fetchall()
        print(f"Checkpoints: {len(rows)}")
        for i, r in enumerate(rows):
            cv_str = r[4]
            if cv_str:
                try:
                    cv = json.loads(cv_str) if isinstance(cv_str, str) else {}
                    keys = list(cv.keys())
                    has_cc = 'completed_chapters' in keys
                    has_mc = 'memory_context' in keys
                    has_ci = 'current_chapter_index' in keys
                    memory_val = cv.get('memory_context', '')
                    memory_preview = f"len={len(memory_val)}, preview={str(memory_val)[:80]}" if memory_val else "EMPTY/''"
                    print(f"\n  Checkpoint {i}: ts={r[3]}")
                    print(f"    Keys: {keys}")
                    print(f"    has_completed_chapters={has_cc}, has_memory_context={has_mc}, has_current_chapter_index={has_ci}")
                    print(f"    memory_context: {memory_preview}")
                    if has_ci:
                        print(f"    current_chapter_index: {cv.get('current_chapter_index')}")
                except json.JSONDecodeError as e:
                    print(f"  JSON parse error: {e}")
            else:
                print(f"\n  Checkpoint {i}: NO channel_values")

        # Check checkpoint_blobs
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM checkpoint_blobs
            WHERE thread_id = :tid
        """), {"tid": thread_id})
        print(f"\nCheckpoint blobs for thread: {result.fetchone()[0]}")

        # Check checkpoint_writes (pending writes)
        result = await conn.execute(text("""
            SELECT task_id, channel, type, value FROM checkpoint_writes
            WHERE thread_id = :tid
            LIMIT 10
        """), {"tid": thread_id})
        for r in result.fetchall():
            print(f"  Write: task_id={str(r[0])[:20]}..., channel={r[1]}, type={r[2]}")

asyncio.run(check())
