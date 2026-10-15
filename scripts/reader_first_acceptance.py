"""Normal API real-model acceptance on explicitly marked isolated QA books."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path("/opt/novel-writer/releases/reader-first-20261013")
PRIVATE = ROOT / "acceptance-private.json"
BASE = "http://127.0.0.1:5183/api"
BACKEND = "novel-writer-reader-qa-20261013-backend"
SEEDS = {
    "romance": "都市言情。女主是普通打工人，分手后今天要搬离旧出租屋，取回属于自己的押金。"
               "前男友也来退租，两人因房东把共同押金全部打给一个人而必须一起核对旧账。"
               "他们当初分手有具体且可以通过交流澄清的误会。押金和搬家是眼前行动，"
               "旧情与是否再次信任对方是阅读吸引点。故事从收拾行李、还钥匙和拿钱开始。"
               "三章完成退租和一个有代价的关系选择，不写企业项目、法律办案或专业流程。",
    "suspense": "都市悬疑。普通便利店夜班店员收到一部顾客落下的手机，想把手机还给失主。"
                "手机突然收到一条消息：别把手机交给门口穿雨衣的人。那个人已来到店外。"
                "已出场人物身份和还手机的目标从开头就让人明白，悬念在于消息可信与否。"
                "风险和线索来自便利店日常的监控、收据和交谈，不要求懂警方或技术业务。"
                "三章查清手机归属和威胁来源，用前文已有证据完成主线。",
    "fantasy": "玄幻。贫穷少年在宗门灶房帮工，今天必须领到工钱给生病的妹妹买药。"
               "管事说名册没有他的名字，要把他赶下山。他意外发现自己能听见一件"
               "旧物最后一次被主人使用时的声音，依靠被丢弃的记账木牌找回工钱证据。"
               "能力只能从亲手触到的旧物听见一次既有声音，不能创造事实、读心或万能解题。"
               "修炼世界从吃饭、打工、买药这些日常需要进入，不先讲功法等级。"
               "三章解决欠薪与买药，少年承担具体代价后获得留山学习的机会。",
}


def request(method, path, session=None, payload=None, key=None):
    headers = {"Content-Type": "application/json"}
    if session:
        headers.update(Authorization="Bearer " + session["access_token"],
                       **{"X-Tenant-ID": session["tenants"][0]["id"]})
    if key:
        headers["Idempotency-Key"] = key
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    try:
        with urlopen(Request(BASE + path, data=data, headers=headers, method=method), timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None
    except HTTPError as error:
        raise RuntimeError(f"API {method} {path}: {error.code} " + error.read().decode()[:800]) from None


def save(data):
    fd = os.open(PRIVATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(data, output, ensure_ascii=False)


def login(data):
    return request("POST", "/v1/auth/login", payload={
        "email": data["email"], "password": data["password"]})


def setup():
    if PRIVATE.exists():
        raise RuntimeError("Reuse the existing marked acceptance identity")
    email = f"reader-qa-20261013-{secrets.token_hex(5)}@example.invalid"
    password = secrets.token_urlsafe(30)
    session = request("POST", "/v1/auth/register", payload={
        "email": email, "password": password, "tenant_name": "读者理解隔离验收20261013"})
    data = {"email": email, "password": password, "books": {}}
    save(data)
    code = f"""import asyncio
from uuid import UUID
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.models import TenantModel,UserModel,TenantMembershipModel
async def main():
    assert 'reader_acceptance' in settings.DATABASE_URL
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.async_session() as db,db.begin():
        tenant=await db.get(TenantModel,UUID({session["tenants"][0]["id"]!r}))
        user=await db.get(UserModel,UUID({session["user"]["id"]!r}))
        member=await db.get(TenantMembershipModel,(tenant.id,user.id))
        assert user.email=={email!r} and tenant.name=='读者理解隔离验收20261013' and member.role=='owner'
        tenant.novel_planning_v1_enabled=True
        tenant.autonomous_author_enabled=True
        tenant.autonomous_request_limit=4000
        tenant.monthly_generation_limit=100
    await repo.aclose()
asyncio.run(main())
"""
    run = subprocess.run(["docker", "exec", "-i", BACKEND, "/app/.venv/bin/python", "-"],
                         input=code.encode(), check=True)
    assert run.returncode == 0
    print(json.dumps({"setup": "new-isolated-test-tenant", "production_changed": False}))


def create(kind):
    data = json.loads(PRIVATE.read_text())
    assert kind not in data["books"], "Keep existing failure samples; do not replace the book"
    book = request("POST", "/v1/novels", login(data), {
        "novel_type": kind, "summary": SEEDS[kind],
        "planning": {"preset": "short", "target_chapters": 3, "target_total_words": 12600},
        "author_config": {
            "author_mode": "autonomous_v1", "narrative_mode": "stable",
            "target_readers": "希望开篇就明白人物正在做什么的普通网文读者",
            "desired_experience": "人物有具体需求，阻碍和代价能理解，读者能辨认本题材的核心吸引点",
            "hard_constraints": ["所有人物和机构均为虚构", "不声称获得真人读者或市场验证",
                                 "三章关闭眼前主线，允许人物未来继续发展"],
            "budget": {"preparation": 60, "chapter": 32, "search": 0, "preparation_search": 0},
        },
    }, key="reader-qa-20261013-create-" + kind)
    data["books"][kind] = {"id": book["novel_id"], "marked_test": True}
    save(data)
    print(json.dumps({"created": kind, "novel_id": book["novel_id"]}))


def start(kind, retry=False):
    data = json.loads(PRIVATE.read_text())
    session = login(data)
    novel = data["books"][kind]["id"]
    headers = {"Authorization": "Bearer " + session["access_token"],
               "X-Tenant-ID": session["tenants"][0]["id"], "Content-Type": "application/json",
               "Idempotency-Key": "reader-qa-" + kind + ("-retry-" + secrets.token_hex(5) if retry else "-start")}
    payload = {"command": {"retry": True, "_auto_mode": True}} if retry else {"input": {"_auto_mode": True}}
    with urlopen(Request(BASE + f"/v1/workflows/{novel}/stream",
                         data=json.dumps(payload).encode(), headers=headers, method="POST"), timeout=60) as response:
        for line in response:
            if line.startswith(b"data:"):
                break
    print(json.dumps({"started": kind, "novel": novel, "retry": retry}))


def inspect_book(kind):
    data = json.loads(PRIVATE.read_text())
    session = login(data)
    novel = data["books"][kind]["id"]
    state = request("GET", f"/v1/workflows/{novel}/state", session)
    creative = request("GET", f"/v1/novels/{novel}/creative", session)
    progress = request("GET", f"/v1/novels/{novel}/progress", session)
    report = {"kind": kind, "novel_id": novel, "progress": progress,
              "status": state.get("status"), "node": state.get("execution", {}).get("active_node"),
              "interrupts": state.get("interrupts"), "blocker": state.get("blocker"),
              "counters": creative["session"]["counters"], "stage": creative["session"]["stage"]}
    path = ROOT / "evidence" / kind
    path.mkdir(exist_ok=True)
    (path / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (path / "creative.json").write_text(json.dumps(creative, ensure_ascii=False, indent=2))
    artifacts = request("GET", f"/v1/novels/{novel}/creative/artifacts", session)
    (path / "artifacts.json").write_text(json.dumps(artifacts, ensure_ascii=False, indent=2))
    for artifact in artifacts:
        if artifact["kind"] == "pilot":
            payload = artifact["payload"]
            digest = hashlib.sha256(payload["text"].encode()).hexdigest()[:12]
            (path / f"isolated-pilot-{digest}.txt").write_text(payload["text"])
    (path / "snapshot.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    rows = request("GET", f"/v1/novels/{novel}/chapters", session)
    for row in rows:
        chapter = request("GET", f"/v1/novels/{novel}/chapters/{row['id']}", session)
        number = chapter["chapter_index"] + 1
        (path / f"chapter-{number}.json").write_text(json.dumps(chapter, ensure_ascii=False, indent=2))
        (path / f"chapter-{number}.txt").write_text(chapter["content"])
    print(json.dumps(report, ensure_ascii=False))
    return rows


def export(kind):
    inspect_book(kind)
    data = json.loads(PRIVATE.read_text())
    session = login(data)
    tenant, novel = session["tenants"][0]["id"], data["books"][kind]["id"]
    code = f"""import asyncio,json
from uuid import UUID
from sqlalchemy import select
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.creative_models import CreativeRequestModel
from infrastructure.database.models import ChapterModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
async def main():
    assert 'reader_acceptance' in settings.DATABASE_URL
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.async_session() as db:
        requests=await db.scalars(select(CreativeRequestModel).where(CreativeRequestModel.tenant_id==UUID({tenant!r}),CreativeRequestModel.novel_id==UUID({novel!r})).order_by(CreativeRequestModel.created_at))
        ledger=[{{'id':str(row.id),'bucket':row.bucket,'stage':row.stage,'status':row.status,'usage':row.usage,'created_at':row.created_at.isoformat()}} for row in requests]
        chapters=await db.scalars(select(ChapterModel).where(ChapterModel.novel_id==UUID({novel!r})).order_by(ChapterModel.chapter_index))
        reviews=[{{'chapter':row.chapter_index+1,'user_decision':row.user_decision,'reflection_issues':row.reflection_issues,'revision_history':row.revision_history,'revision_count':row.revision_count}} for row in chapters]
    checkpoints=[]
    drafts={{}}
    uri=settings.LANGGRAPH_CHECKPOINTER_URI or settings.DATABASE_URL.replace('+asyncpg','')
    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        async for item in saver.alist({{'configurable':{{'thread_id':{tenant + ':' + novel!r}}}}}):
            values=item.checkpoint.get('channel_values',{{}})
            body=values.get('current_chapter_content')
            if isinstance(body,str) and body:
                import hashlib
                digest=hashlib.sha256(body.encode()).hexdigest()
                drafts.setdefault(digest,{{'body_sha256':digest,'chapter_number':int(values.get('current_chapter_index') or 0)+1,'text':body}})
            proposal=values.get('pending_proposal') or {{}}
            if proposal.get('kind')=='title':
                checkpoints.append({{'kind':'title','proposal':proposal}})
            if values.get('reader_comprehension_receipt'):
                checkpoints.append({{'kind':'reader','receipt':values['reader_comprehension_receipt'],'chapter_index':values.get('current_chapter_index')}})
            if not checkpoints or not any(row.get('kind')=='latest' for row in checkpoints):
                checkpoints.append({{'kind':'latest','chapter_index':values.get('current_chapter_index'),'draft':values.get('current_chapter_content'),'revision_history':values.get('revision_history'),'quality_gate':values.get('quality_gate')}})
    await repo.aclose()
    print(json.dumps({{'ledger':ledger,'reviews':reviews,'checkpoints':checkpoints,
        'drafts':list(drafts.values()),'runtime':{{'model':settings.DEFAULT_MODEL_NAME,
        'provider':settings.DEFAULT_LLM_PROVIDER,'prompt_version':__import__('application.prompts.version',fromlist=['PROMPT_VERSION']).PROMPT_VERSION}}}},ensure_ascii=False,default=str))
asyncio.run(main())
"""
    raw = subprocess.check_output(["docker", "exec", "-i", BACKEND, "/app/.venv/bin/python", "-"],
                                  input=code.encode())
    exported = json.loads(raw)
    path = ROOT / "evidence" / kind
    for name, payload in exported.items():
        (path / (name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    for draft in exported["drafts"]:
        (path / f"unarchived-draft-{draft['chapter_number']}-{draft['body_sha256'][:12]}.txt").write_text(draft["text"])
    titles = [item["proposal"] for item in exported["checkpoints"] if item["kind"] == "title"]
    (path / "title-candidates.json").write_text(json.dumps(titles, ensure_ascii=False, indent=2))
    ledger = exported["ledger"]
    usage = {"requests": len(ledger), "completed": sum(row["status"] == "completed" for row in ledger),
             "unknown": sum(row["status"] == "unknown" for row in ledger),
             "prompt_tokens": sum(row["usage"].get("prompt_tokens", 0) for row in ledger),
             "completion_tokens": sum(row["usage"].get("completion_tokens", 0) for row in ledger),
             "monetary_charge": "not_reported_by_provider"}
    (path / "usage.json").write_text(json.dumps(usage, indent=2))
    print(json.dumps({"exported": kind, "usage": usage}))


def verify(kind):
    rows = inspect_book(kind)
    assert len(rows) == 3, "Nine-chapter acceptance is incomplete"
    path = ROOT / "evidence" / kind
    verified = []
    for number in range(1, 4):
        chapter = json.loads((path / f"chapter-{number}.json").read_text())
        receipt = chapter.get("reader_comprehension")
        assert chapter["status"] == "completed" and chapter["review_status"] == "passed"
        assert receipt and receipt["body_sha256"] == hashlib.sha256(chapter["content"].encode()).hexdigest()
        verified.append({"chapter": number, "words": len(chapter["content"]),
                         "receipt": receipt, "content_sha256": receipt["body_sha256"]})
    (path / "verification.json").write_text(json.dumps({
        "source": "real_model_simulated_reader", "real_reader_validation": "not_performed",
        "chapters": verified}, ensure_ascii=False, indent=2))
    print(json.dumps({"verified": kind, "chapters": 3}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "create", "start", "retry", "inspect", "verify", "export"])
    parser.add_argument("--kind", choices=list(SEEDS), default="romance")
    args = parser.parse_args()
    if args.action == "setup":
        setup()
    elif args.action == "retry":
        start(args.kind, retry=True)
    else:
        {"create": create, "start": start, "inspect": inspect_book, "verify": verify, "export": export}[args.action](args.kind)
