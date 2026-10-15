"""Bounded real API acceptance on marked books; never accept rejected manuscripts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "writter_back"))
from application.editorial_facts import literal_count_issues

ROOT = Path("/opt/novel-writer/releases/production-20261001")
PRIVATE = ROOT / "acceptance-private.json"
BASE = "http://127.0.0.1:5173/api"
TITLE = "生产验收20261001·潮汐账本"
SMOKE_KINDS = {"smoke", "smoke-r2", "smoke-r3", "smoke-r4"}
BOOK_KINDS = SMOKE_KINDS | {"long", "long-r2", "long-r3"}


def request(method, path, session=None, payload=None, key=None, raw=False):
    headers = {"Content-Type": "application/json"}
    if session:
        headers["Authorization"] = "Bearer " + session["access_token"]
        headers["X-Tenant-ID"] = session.get("tenant_id", session["tenants"][0]["id"])
    if key:
        headers["Idempotency-Key"] = key
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=45) as response:
            body = response.read()
            return (response.status, body) if raw else (json.loads(body) if body else None)
    except HTTPError as error:
        if raw:
            return error.code, error.read()
        raise RuntimeError(f"API {method} {path} returned {error.code}: "
                           + error.read().decode()[:700]) from None


def save_private(data):
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as content:
        json.dump(data, content, ensure_ascii=False)


def refreshed(account):
    session = request("POST", "/v1/auth/login", payload={
        "email": account["email"], "password": account["password"]})
    account["session"] = session
    return session


def grant_test_policy(account):
    session = account["session"]
    tenant_id, user_id = session["tenants"][0]["id"], session["user"]["id"]
    assert account["email"].startswith("production-qa-20261001-")
    assert account["email"].endswith("@example.invalid")
    code = f"""import asyncio, json
from uuid import UUID
from sqlalchemy import select
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.models import TenantModel, TenantMembershipModel, UserModel
async def main():
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    try:
        async with repo.async_session() as session, session.begin():
            user=await session.get(UserModel,UUID({user_id!r}))
            tenant=await session.scalar(select(TenantModel).where(
                TenantModel.id==UUID({tenant_id!r})).with_for_update())
            member=await session.get(TenantMembershipModel,(tenant.id,user.id))
            assert user.email=={account["email"]!r} and member.role=="owner"
            assert tenant.name=="生产验收20261001-1" and tenant.status=="active"
            tenant.novel_planning_v1_enabled=True
            tenant.autonomous_author_enabled=True
            tenant.autonomous_request_limit=4000
            tenant.monthly_generation_limit=100
        print(json.dumps({{"policy_scope":"new-marked-qa-tenant-only","tenant":str(tenant.id)}}))
    finally:
        await repo.aclose()
asyncio.run(main())
"""
    subprocess.run(["docker", "exec", "-i", "novel-writer-backend", "/app/.venv/bin/python", "-"],
                   input=code.encode(), check=True)


def setup():
    if PRIVATE.exists():
        data = json.loads(PRIVATE.read_text())
        assert not data.get("configured"), "Reuse existing configured acceptance identity"
        accounts = data["accounts"]
    else:
        data, accounts = {"books": {}}, []
    for number in range(len(accounts), 2):
        email = f"production-qa-20261001-{secrets.token_hex(5)}@example.invalid"
        password = secrets.token_urlsafe(30)
        session = request("POST", "/v1/auth/register", payload={
            "email": email, "password": password,
            "tenant_name": f"生产验收20261001-{number + 1}"})
        accounts.append({"email": email, "password": password, "session": session})
        data["accounts"] = accounts
        save_private(data)
    grant_test_policy(accounts[0])
    data["configured"] = True
    save_private(data)
    print(json.dumps({"test_accounts": len(accounts),
                      "test_tenant": accounts[0]["session"]["tenants"][0]["id"]}))


def create_book(kind):
    data = json.loads(PRIVATE.read_text())
    if kind in data["books"]:
        raise RuntimeError("Marked acceptance book already exists; reuse it")
    session = refreshed(data["accounts"][0])
    chapters, words = (3, 12600) if kind in SMOKE_KINDS else (80, 336000)
    assert request("GET", "/v1/novels/creative-options", session)["enabled"]
    payload = {
        "novel_type": "suspense", "title": TITLE + (
            "·冒烟" + kind.removeprefix("smoke-").upper()
            if kind.startswith("smoke-") else "·冒烟" if kind == "smoke"
            else "·长篇" + kind.removeprefix("long-").upper()
            if kind.startswith("long-") else "·长篇"),
        "summary": "架空江城，年轻水务档案员发现一笔被抹去的旧水债。"
                   "她需要在城市改造最后期限前查清账本背后的责任链，"
                   "在保全父亲名誉与救回街坊用水权之间做出有代价的选择。"
                   "结局关闭水债主线，人物选择改变实际处境，不以新谜团替代收束。",
        "planning": {"preset": "short" if kind in SMOKE_KINDS else "long",
                     "target_chapters": chapters, "target_total_words": words},
        "author_config": {
            "author_mode": "autonomous_v1", "narrative_mode": "stable",
            "target_readers": "喜欢人物驱动、线索可回溯的悬疑网文的成年读者",
            "desired_experience": "开篇尽快进入困境，信息差与人物选择推动转折，结尾兑现主线",
            "hard_constraints": ["城市、机构及主要人物均为虚构，不引用真实公共人物",
                                 "所有核心谜底均在本书内给出可回溯解释",
                                 "不得把模型市场推测表述为真实读者反馈"],
            "budget": {"preparation": 60, "chapter": 32, "search": 0, "preparation_search": 0},
        },
    }
    book = request("POST", "/v1/novels", session, payload, key=f"qa-20261001-create-{kind}")
    data["books"][kind] = {"id": book["novel_id"], "chapters": chapters, "words": words}
    save_private(data)
    print(json.dumps({"created": kind, **data["books"][kind]}))


def start_book(kind, retry=False):
    data = json.loads(PRIVATE.read_text())
    session = refreshed(data["accounts"][0])
    novel = data["books"][kind]["id"]
    headers = {"Authorization": "Bearer " + session["access_token"],
               "X-Tenant-ID": session["tenants"][0]["id"], "Content-Type": "application/json",
               "Idempotency-Key": ("qa-20261001-retry-" + secrets.token_hex(6)
                                   if retry else "qa-20261001-start-" + kind)}
    req = Request(BASE + "/v1/workflows/" + novel + "/stream", method="POST",
                  headers=headers, data=(b'{"command":{"retry":true,"_auto_mode":true}}'
                                        if retry else b'{"input":{"_auto_mode":true}}'))
    with urlopen(req, timeout=45) as response:
        assert response.status == 200
        while True:
            line = response.readline()
            if not line:
                raise RuntimeError("Writing stream ended before any data event")
            if line.startswith(b"data:"):
                break
    save_private(data)
    print(json.dumps({"started": kind, "novel": novel, "reader_disconnected": True, "retry": retry}))


def inspect_book(kind):
    data = json.loads(PRIVATE.read_text())
    session = refreshed(data["accounts"][0])
    book = data["books"][kind]
    novel = book["id"]
    progress = request("GET", f"/v1/novels/{novel}/progress", session)
    run = request("GET", f"/v1/workflows/{novel}/run", session)
    state = request("GET", f"/v1/workflows/{novel}/state", session)
    creative = request("GET", f"/v1/novels/{novel}/creative", session)
    report = {"novel": novel, "progress": progress, "run": run,
              "next_nodes": state.get("next_nodes"), "interrupts": state.get("interrupts"),
              "creative_status": creative["session"]["status"],
              "creative_stage": creative["session"]["stage"],
              "creative_counters": creative["session"]["counters"],
              "reader_validation": creative["real_reader_validation"]}
    (ROOT / f"evidence/{kind}-status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save_private(data)
    print(json.dumps(report, ensure_ascii=False))
    return report


def verify_book(kind):
    data = json.loads(PRIVATE.read_text())
    session = refreshed(data["accounts"][0])
    outsider = refreshed(data["accounts"][1])
    book, novel = data["books"][kind], data["books"][kind]["id"]
    progress = request("GET", f"/v1/novels/{novel}/progress", session)
    assert progress["status"] == "completed" and progress["current_chapter"] == book["chapters"]
    rows = request("GET", f"/v1/novels/{novel}/chapters", session)
    assert [row["chapter_index"] for row in rows] == list(range(book["chapters"]))
    status, _ = request("GET", f"/v1/novels/{novel}/export", outsider, raw=True)
    assert status == 404, "Tenant isolation failed"
    texts, counts, reviews = [], [], []
    for chapter in rows:
        saved = request("GET", f"/v1/novels/{novel}/chapters/{chapter['id']}", session)
        text = saved["content"]
        assert saved["word_count"] == len(text) and saved["status"] == "completed"
        assert not text.lstrip().startswith(("{", "[", "```json"))
        assert saved["review_status"] == "passed", "Acceptance requires independently reviewed chapters"
        assert not literal_count_issues(text), "Known copyediting failure in archived chapter"
        texts.append(text)
        counts.append(len(text))
        reviews.append(saved["review_status"])
    assert abs(sum(counts) - book["words"]) <= book["words"] * 0.1
    for format in ("txt", "md"):
        status, content = request("GET", f"/v1/novels/{novel}/export?format={format}", session, raw=True)
        assert status == 200
        exported = content.decode("utf-8-sig")
        assert all(text in exported for text in texts), "Export altered archived prose"
        (ROOT / f"evidence/{kind}-manuscript.{format}").write_bytes(content)
    result = {"novel": novel, "chapters": len(rows), "actual_words": sum(counts),
              "chapter_words": counts, "reviews": reviews, "tenant_isolation": True,
              "export_unchanged": True, "human_review": "not_performed",
              "content_sha256": hashlib.sha256("\n".join(texts).encode()).hexdigest()}
    (ROOT / f"evidence/{kind}-verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "create", "start", "retry", "inspect", "verify"])
    parser.add_argument("--kind", choices=sorted(BOOK_KINDS), default="smoke")
    arguments = parser.parse_args()
    if arguments.action == "setup":
        setup()
    elif arguments.action == "retry":
        start_book(arguments.kind, retry=True)
    else:
        {"create": create_book, "start": start_book, "inspect": inspect_book,
         "verify": verify_book}[arguments.action](arguments.kind)
