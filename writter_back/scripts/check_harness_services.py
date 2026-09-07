"""CI服务预检：只连接显式测试库并PING Redis，连接失败立即退出。"""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url
from redis.asyncio import Redis

async def main():
    url = os.environ['TEST_DATABASE_URL']
    if not (make_url(url).database or '').endswith('_test'):
        raise RuntimeError('只允许显式隔离测试数据库')
    engine = create_async_engine(url, connect_args={'timeout': 5})
    redis = Redis.from_url(os.environ['TEST_REDIS_URL'], socket_connect_timeout=5, socket_timeout=5)
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SELECT 1'))
        assert await redis.ping()
    finally:
        await engine.dispose()
        await redis.aclose()
    print('postgresql=ready redis=ready')
asyncio.run(asyncio.wait_for(main(), timeout=15))
