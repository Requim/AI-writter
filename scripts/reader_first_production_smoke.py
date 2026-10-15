"""One explicitly marked, budget-bounded production book through normal APIs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

ROOT = Path("/opt/novel-writer/releases/reader-first-production-20261013")
PRIVATE = ROOT / "smoke-private.json"
BASE = "http://127.0.0.1:5173/api"
TITLE = "[生产测试]退租那天20261013"


def save(data):
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(data, output, ensure_ascii=False)


def request(method, path, session=None, payload=None, key=None):
    headers = {"Content-Type": "application/json"}
    if session:
        headers["Authorization"] = "Bearer " + session["access_token"]
        headers["X-Tenant-ID"] = session["tenants"][0]["id"]
    if key:
        headers["Idempotency-Key"] = key
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    with urlopen(Request(BASE + path, data=body, headers=headers, method=method), timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None


def login(data):
    return request("POST", "/v1/auth/login", payload={
        "email": data["email"], "password": data["password"],
    })


def create():
    assert not PRIVATE.exists(), "Keep and reuse the existing production smoke book"
    original = json.loads((ROOT.parent / "production-20261001/acceptance-private.json").read_text())
    account = original["accounts"][0]
    assert account["email"].startswith("production-qa-20261001-")
    data = {"email": account["email"], "password": account["password"], "marked_test": True}
    session = login(data)
    options = request("GET", "/v1/novels/creative-options", session)
    assert options["enabled"], "Existing marked QA tenant lacks autonomous access"
    book = request("POST", "/v1/novels", session, {
        "novel_type": "romance", "title": TITLE,
        "summary": "【生产发布链路测试，非正式作品，不代替九章验收】"
                   "普通打工人女主今天搬离与前男友共同租住的房子，"
                   "必须拿回她那一半押金才能交新房的租金。前男友也来还钥匙。"
                   "房东已经把共同押金全额打给前男友，她担心他故意不还，"
                   "而他正在等她把收款方式发来。两个人带着分手后的别扭一起"
                   "收拾行李、算清押金并还钥匙，用直接交谈解开眼前误会。"
                   "以日常行动和一次有代价的关系选择结束这个单章短篇，"
                   "不写企业项目、专业办案或法律术语，不引入未来的新谜团。",
        "planning": {"preset": "custom", "target_chapters": 1, "target_total_words": 4200},
        "author_config": {
            "author_mode": "autonomous_v1", "narrative_mode": "stable",
            "target_readers": "希望一开场就能看懂人物关系和眼前行动的普通网文读者",
            "desired_experience": "从搬家拿押金进入冲突，人物交流和实际选择推动关系变化",
            "hard_constraints": ["人物均为虚构", "不得声称真实读者或市场认可",
                                 "这是明确标记的生产测试作品"],
            "budget": {"preparation": 60, "chapter": 32, "search": 0, "preparation_search": 0},
        },
    }, key="reader-first-production-smoke-create-20261013")
    data["novel_id"] = book["novel_id"]
    save(data)
    saved = request("GET", f"/v1/novels/{data['novel_id']}", session)
    assert saved["total_outline"]["reader_quality_version"] == 1
    assert saved["title"] == TITLE
    evidence = {"novel_id": data["novel_id"], "title": saved["title"],
                "reader_quality_version": 1, "marked_test": True,
                "target_chapters": 1, "nine_chapter_acceptance": "not_replaced"}
    (ROOT / "evidence/smoke-created.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False), flush=True)


def start():
    data = json.loads(PRIVATE.read_text())
    assert not data.get("started"), "No automatic repeated paid smoke runs"
    session = login(data)
    headers = {"Authorization": "Bearer " + session["access_token"],
               "X-Tenant-ID": session["tenants"][0]["id"],
               "Content-Type": "application/json",
               "Idempotency-Key": "reader-first-production-smoke-start-20261013"}
    request_stream = Request(BASE + f"/v1/workflows/{data['novel_id']}/stream", method="POST",
                             headers=headers, data=b'{"input":{"_auto_mode":true}}')
    with urlopen(request_stream, timeout=60) as response:
        assert response.status == 200
        for line in response:
            if line.startswith(b"data:"):
                event = json.loads(line.removeprefix(b"data:").strip())
                break
        else:
            raise RuntimeError("Stream ended before its first data event")
    data["started"] = True
    save(data)
    (ROOT / "evidence/smoke-first-event.json").write_text(json.dumps(event, ensure_ascii=False, indent=2))
    print(json.dumps({"novel_id": data["novel_id"], "sse_first_event": True,
                      "disconnected_reader": True, "event_type": event.get("type")}), flush=True)


def observe():
    data = json.loads(PRIVATE.read_text())
    session = login(data)
    novel = data["novel_id"]
    state = request("GET", f"/v1/workflows/{novel}/state", session)
    creative = request("GET", f"/v1/novels/{novel}/creative", session)
    progress = request("GET", f"/v1/novels/{novel}/progress", session)
    rows = request("GET", f"/v1/novels/{novel}/chapters", session)
    artifact_rows = request("GET", f"/v1/novels/{novel}/creative/artifacts", session)
    evidence = ROOT / "evidence"
    for name, value in (("state", state), ("creative", creative), ("progress", progress),
                        ("artifacts", artifact_rows)):
        (evidence / f"smoke-{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
    archived = []
    for row in rows:
        chapter = request("GET", f"/v1/novels/{novel}/chapters/{row['id']}", session)
        number = chapter["chapter_index"] + 1
        (evidence / f"smoke-chapter-{number}.json").write_text(json.dumps(chapter, ensure_ascii=False, indent=2))
        (evidence / f"smoke-chapter-{number}.txt").write_text(chapter["content"])
        archived.append({"chapter": number, "words": chapter["word_count"],
                         "review_status": chapter["review_status"],
                         "reader_status": (chapter.get("reader_comprehension") or {}).get("status"),
                         "body_sha256": hashlib.sha256(chapter["content"].encode()).hexdigest()})
    result = {"novel_id": novel, "status": state.get("status"),
              "execution": state.get("execution"), "next_nodes": state.get("next_nodes"),
              "interrupts": state.get("interrupts"), "progress": progress,
              "creative_stage": creative["session"]["stage"],
              "counters": creative["session"]["counters"],
              "archived": archived, "real_reader_validation": "not_performed"}
    (evidence / "smoke-status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"interrupts", "progress", "execution"}}, ensure_ascii=False), flush=True)
    return result


def ledger():
    data = json.loads(PRIVATE.read_text())
    session = login(data)
    tenant = session["tenants"][0]["id"]
    code = f"""import asyncio,json
from uuid import UUID
from sqlalchemy import select
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.creative_models import CreativeRequestModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
async def main():
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.async_session() as db:
        rows=await db.scalars(select(CreativeRequestModel).where(
            CreativeRequestModel.tenant_id==UUID({tenant!r}),
            CreativeRequestModel.novel_id==UUID({data["novel_id"]!r})).order_by(CreativeRequestModel.created_at))
        calls=[{{'id':str(row.id),'bucket':row.bucket,'stage':row.stage,'status':row.status,'usage':row.usage}} for row in rows]
    checkpoints=[]
    uri=settings.LANGGRAPH_CHECKPOINTER_URI or settings.DATABASE_URL.replace('+asyncpg','')
    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        async for item in saver.alist({{'configurable':{{'thread_id':{tenant + ':' + data["novel_id"]!r}}}}}):
            values=item.checkpoint.get('channel_values',{{}})
            body=values.get('current_chapter_content')
            receipt=values.get('reader_comprehension_receipt')
            if body or receipt:
                checkpoints.append({{'body':body,'reader_receipt':receipt,'revision_history':values.get('revision_history')}})
    await repo.aclose()
    print(json.dumps({{'calls':calls,'checkpoints':checkpoints}},ensure_ascii=False,default=str))
asyncio.run(main())
"""
    exported = json.loads(subprocess.check_output(
        ["docker", "exec", "-i", "novel-writer-backend", "/app/.venv/bin/python", "-"],
        input=code.encode(),
    ))
    (ROOT / "evidence/smoke-ledger.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2))
    calls = exported["calls"]
    usage = {"requests": len(calls), "unknown": sum(row["status"] == "unknown" for row in calls),
             "prompt_tokens": sum((row["usage"] or {}).get("prompt_tokens", 0) for row in calls),
             "completion_tokens": sum((row["usage"] or {}).get("completion_tokens", 0) for row in calls)}
    (ROOT / "evidence/smoke-usage.json").write_text(json.dumps(usage, indent=2))
    print(json.dumps(usage), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "start", "observe", "ledger"])
    globals()[parser.parse_args().action]()
