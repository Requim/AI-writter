"""Read the old manuscript unchanged and blind-review it with the isolated model."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path("/opt/novel-writer/releases/reader-first-20261013")


def main(*, read_only=False):
    read = """import asyncio,json,hashlib
from uuid import UUID
from sqlalchemy import select
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.models import ChapterModel
async def main():
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    tenant='130cc1a6-14e5-4c3c-b69e-af0e802c9570'
    novel='3cf0d8da-20d4-4a2b-b0c0-48d44d3d0f71'
    book=await repo.find_by_id(tenant,novel)
    assert book is not None and book.title=='你那份我没动'
    async with repo.async_session() as db:
        chapter=await db.scalar(select(ChapterModel).where(ChapterModel.novel_id==UUID(novel),ChapterModel.chapter_index==0))
        print(json.dumps({'novel_id':novel,'title':book.title,'chapter_title':chapter.title,'content':chapter.content,'content_sha256':hashlib.sha256(chapter.content.encode()).hexdigest(),'reader_quality_version':book.total_outline.reader_quality_version if hasattr(book.total_outline,'reader_quality_version') else 0},ensure_ascii=False))
    await repo.aclose()
asyncio.run(main())
"""
    sample = json.loads(subprocess.check_output(["docker", "exec", "-i", "novel-writer-backend",
        "/app/.venv/bin/python", "-"], input=read.encode()))
    (ROOT / "evidence/legacy-negative.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2))
    if read_only:
        print(json.dumps({"production_book_unchanged": True, "title": sample["title"],
                          "body_sha256": sample["content_sha256"],
                          "reader_quality_version": sample["reader_quality_version"]}, ensure_ascii=False))
        return
    account = json.loads((ROOT / "acceptance-private.json").read_text())
    novel = account["books"]["romance"]["id"]
    code = f"""import asyncio,json
from sqlalchemy import select
from uuid import UUID
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.models import NovelModel
from infrastructure.database.creative_repository import PostgresCreativeRepository
from infrastructure.llm.openai_adapter import OpenAIAdapter
from service.ports.model_meter import active_model_meter,CreativeRequestMeter
from application.reader_comprehension import review_reader,reader_archive_ready
from application.errors import StructuredOutputInvalidError
async def main():
    assert 'reader_acceptance' in settings.DATABASE_URL and settings.DEFAULT_LLM_PROVIDER=='openai'
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.async_session() as db:
        book=await db.scalar(select(NovelModel).where(NovelModel.id==UUID({novel!r})))
    meter=CreativeRequestMeter(PostgresCreativeRepository(repo.async_session),str(book.tenant_id),str(book.id),'review','legacy_reader_regression')
    token=active_model_meter.set(meter)
    llm=OpenAIAdapter(settings.OPENAI_API_KEY or '',settings.DEFAULT_MODEL_NAME,settings.LLM_TIMEOUT_SECONDS,base_url=settings.OPENAI_BASE_URL,max_retries=0)
    state={{'reader_quality_version':1,'current_chapter_index':0,'novel_type':'romance','reader_history':[]}}
    content={sample["content"]!r}
    attempts=[]
    original=llm.structured_generate
    async def recorded(**kwargs):
        result=await original(**kwargs)
        attempts.append(result)
        return result
    llm.structured_generate=recorded
    try:
        try:
            receipt=await review_reader(llm,state,content)
            passed=reader_archive_ready({{**state,'reader_comprehension_receipt':receipt}},content)
            outcome={{'passes_new_gate':passed,'receipt':receipt}}
        except StructuredOutputInvalidError as error:
            passed=False
            outcome={{'passes_new_gate':False,'status':'report_invalid','error':str(error)}}
        print(json.dumps({{**outcome,'source':'real_model_simulated_reader','attempts':attempts}},ensure_ascii=False))
        assert not passed,'The existing opaque opening incorrectly passed the new gate'
    finally:
        active_model_meter.reset(token)
        await repo.aclose()
asyncio.run(main())
"""
    result = subprocess.run(["docker", "exec", "-i", "novel-writer-reader-qa-20261013-backend",
        "/app/.venv/bin/python", "-"], input=code.encode(), stdout=subprocess.PIPE)
    if result.stdout:
        latest = ROOT / "evidence/legacy-negative-review.json"
        if latest.exists():
            previous = latest.read_bytes()
            (ROOT / ("evidence/legacy-negative-review-" + hashlib.sha256(previous).hexdigest()[:12] + ".json")).write_bytes(previous)
        (ROOT / ("evidence/legacy-negative-review-" + hashlib.sha256(result.stdout).hexdigest()[:12] + ".json")).write_bytes(result.stdout)
        latest.write_bytes(result.stdout)
        value = json.loads(result.stdout)
        print(json.dumps({"legacy_sample_passes": value["passes_new_gate"],
                          "original_body_sha256": sample["content_sha256"],
                          "production_book_unchanged": True}))
    result.check_returncode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true")
    main(read_only=parser.parse_args().read_only)
