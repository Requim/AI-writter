"""Check database state for novel_memories and chapters"""
import asyncio
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from sqlalchemy import text

async def check_db():
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.engine.begin() as conn:
        from sqlalchemy import inspect
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        print('Tables:', tables)
        
        result = await conn.execute(text('SELECT COUNT(*) as cnt FROM novel_memories'))
        print('Memory rows:', result.fetchone()[0])
        
        result = await conn.execute(text('SELECT COUNT(*) as cnt FROM chapters'))
        print('Chapter rows:', result.fetchone()[0])
        
        result = await conn.execute(text("""
            SELECT id, title, status, progress::text as progress_str
            FROM novels
            ORDER BY created_at DESC
            LIMIT 5
        """))
        for row in result:
            print(f'Novel: id={str(row[0])[:16]}..., title={row[1]}, status={row[2]}, progress_preview={str(row[3])[:200] if row[3] else "None"}')
        
        # Check if there's a novel with thread_id matching
        thread_id = "0ead5e1c-e50c-46ac-b065-23e080b5dcfa"
        result = await conn.execute(text(
            "SELECT id, title, thread_id FROM novels WHERE thread_id = :tid"
        ), {"tid": thread_id})
        novel = result.fetchone()
        if novel:
            print(f'\nFound novel: id={str(novel[0])}, thread_id={novel[2]}')
        else:
            print(f'\nNovel with thread_id={thread_id} NOT found')
            # List all threads
            result = await conn.execute(text("SELECT thread_id, title FROM novels WHERE thread_id IS NOT NULL"))
            for r in result:
                print(f'  thread_id={r[0]}, title={r[1]}')

asyncio.run(check_db())
