"""
一次性数据修复脚本：从 LangGraph checkpoint 恢复工作流 state，
提取 title/summary 回写数据库 novels 表。

用法：
  uv run python scripts/backfill_novel_metadata.py
"""
import logging
logger = logging.getLogger("uvicorn")
import asyncio
import sys
import json

if sys.platform == "win32":
    import asyncio as _asyncio
    try:
        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update, text as sql_text
from infrastructure.database.models import NovelModel
from config import settings


async def main():
    logger.info("=" * 60)
    logger.info("Start backfill novel metadata...")

    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession)

    async with async_session() as session:
        # 找所有 total_chapters 为 0 或 progress 为 null 的小说
        from sqlalchemy import or_
        stmt = select(NovelModel).where(
            or_(
                NovelModel.progress.is_(None),
                sql_text("(progress->>'total_chapters')::int = 0"),
            )
        )
        result = await session.execute(stmt)
        novels = result.scalars().all()
        logger.info(f"Found {len(novels)} novels with missing total_chapters")

        if not novels:
            logger.info("Nothing to fix")
            return

        fixed_count = 0

        for novel in novels:
            thread_id = novel.thread_id or str(novel.id)
            logger.info(f"\nProcessing: novel_id={novel.id}, thread_id={thread_id}")

            try:
                # 从 checkpoint_blobs 表获取 total_outline（checkpoints 表 channel_values 里没有）
                blob = await session.execute(
                    sql_text("""
                        SELECT blob
                        FROM checkpoint_blobs
                        WHERE thread_id = :tid
                          AND channel = 'total_outline'
                        ORDER BY version DESC
                        LIMIT 1
                    """),
                    {"tid": thread_id}
                )
                blob_row = blob.scalar_one_or_none()

                state_title = None
                state_summary = None
                state_total_outline = None

                # 从 checkpoints 表拿 title/summary
                cp_raw = await session.execute(
                    sql_text("""
                        SELECT checkpoint
                        FROM checkpoints
                        WHERE thread_id = :tid
                        ORDER BY checkpoint_id DESC
                        LIMIT 1
                    """),
                    {"tid": thread_id}
                )
                cp_row = cp_raw.scalar_one_or_none()
                if cp_row:
                    if isinstance(cp_row, str):
                        cp = json.loads(cp_row)
                    elif isinstance(cp_row, dict):
                        cp = cp_row
                    else:
                        cp = {}
                    cv = cp.get("channel_values", {})
                    state_title = cv.get("title")
                    state_summary = cv.get("summary")

                # 反序列化 total_outline blob（msgpack 格式，十六进制编码）
                if blob_row:
                    import struct
                    try:
                        raw_bytes = bytes(blob_row)
                        # msgpack 解码
                        import msgpack
                        state_total_outline = msgpack.unpackb(raw_bytes)
                        if isinstance(state_total_outline, dict):
                            logger.info(f"  total_outline loaded: keys={list(state_total_outline.keys())}")
                        else:
                            logger.info(f"  total_outline unpacked but not dict: {type(state_total_outline)}")
                            state_total_outline = None
                    except Exception as e:
                        logger.info(f"  Failed to decode blob: {e}")
                        # 尝试字符串解码
                        try:
                            txt = str(blob_row)
                            if txt.startswith("\\x"):
                                txt = txt[2:]
                            state_total_outline = {"_raw": txt[:200]}
                        except:
                            pass

                updates = {}
                if state_title and not novel.title:
                    updates["title"] = state_title
                if state_summary and not novel.summary:
                    updates["summary"] = state_summary

                # 从 total_outline 更新 progress.total_chapters
                if state_total_outline and isinstance(state_total_outline, dict):
                    total_ch = state_total_outline.get("total_chapters", 0)
                    if total_ch:
                        progress_dict = dict(novel.progress) if novel.progress else {"current_chapter": 0, "total_chapters": 0, "percentage": 0.0, "status": "draft"}
                        old_total = progress_dict.get("total_chapters", 0)
                        if not old_total:
                            progress_dict["total_chapters"] = total_ch
                            progress_dict["percentage"] = round((progress_dict["current_chapter"] / total_ch * 100), 2) if total_ch > 0 else 0.0
                            updates["progress"] = progress_dict
                            logger.info(f"  Will update progress: current={progress_dict['current_chapter']}, total={total_ch}")

                if updates:
                    stmt_update = (
                        update(NovelModel)
                        .where(NovelModel.id == novel.id)
                        .values(**updates)
                    )
                    await session.execute(stmt_update)
                    await session.commit()
                    fixed_count += 1
                    logger.info(f"  UPDATED: {updates}")
                else:
                    logger.info(f"  Nothing to update")

            except Exception as e:
                logger.info(f"  Error: {type(e).__name__}: {e}")
                await session.rollback()

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Done: {fixed_count} novels fixed")
        logger.info(f"{'=' * 60}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
