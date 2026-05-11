"""Count all checkpoints and check latest state"""
import asyncio
import json
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from sqlalchemy import text

thread_id = "0ead5e1c-e50c-46ac-b065-23e080b5dcfa"

async def check():
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM checkpoints WHERE thread_id = :tid
        """), {"tid": thread_id})
        print(f"Total checkpoints: {result.fetchone()[0]}")

        result = await conn.execute(text("""
            SELECT thread_id, checkpoint,
                   checkpoint ->> 'ts' as ts
            FROM checkpoints
            WHERE thread_id = :tid
            ORDER BY checkpoint ->> 'ts' DESC
            LIMIT 1
        """), {"tid": thread_id})
        r = result.fetchone()
        cv_str = r[2] if len(r) > 2 else ""
        print(f"Latest checkpoint ts: {r[1]}")

        # Check all checkpoint channel_values for completed_chapters
        result = await conn.execute(text("""
            SELECT checkpoint ->> 'ts' as ts,
                   checkpoint -> 'channel_values' as cv
            FROM checkpoints
            WHERE thread_id = :tid
            ORDER BY checkpoint ->> 'ts' DESC
        """), {"tid": thread_id})
        total_with_cc = 0
        for r in result.fetchall():
            cv_raw = r[1]
            ts = r[0]
            if cv_raw:
                try:
                    cv = json.loads(cv_raw) if isinstance(cv_raw, str) else {}
                    if 'completed_chapters' in cv:
                        total_with_cc += 1
                        print(f"  ts={ts}: HAS completed_chapters, len={len(cv['completed_chapters'])}")
                except:
                    pass
        print(f"Total checkpoints WITH completed_chapters: {total_with_cc}")

asyncio.run(check())
