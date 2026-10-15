"""Host-side workbench release with isolated tests and image-only rollback."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path("/opt/novel-writer")
ROOT = BASE / "releases/workbench-production-20261014"
PREFIX = "novel-writer-workbench-qa-20261014"
DB = PREFIX + "-db"
TOOLS = PREFIX + "-tools"
TEST_DATABASE = "workbench_regression_test"
RESTORE_DATABASE = "workbench_restore_20261014"
SERVICES = ("backend", "frontend", "database", "redis", "research-api", "research-worker")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def capture(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def inspect(name):
    return json.loads(capture("docker", "inspect", name))[0]


def exists(name):
    return subprocess.run(["docker", "inspect", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def save(name, value):
    path = ROOT / name
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)


def load(name):
    return json.loads((ROOT / name).read_text())


def source():
    path = Path((ROOT / "source-path.txt").read_text().strip())
    assert path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink()
    return path


def source_sha():
    return (ROOT / "source-sha256.txt").read_text().strip()


def image_tag(name):
    return f"novel-writer-{name}:workbench-production-20261014"


def previous_release():
    spec = importlib.util.spec_from_file_location(
        "previous_release", source() / "scripts/reader_first_deploy.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    module.RESTORE = DB
    module.RESTORE_DATABASE = RESTORE_DATABASE
    module.SOURCE = source_sha()
    return module


def qa():
    assert not (ROOT / "qa-images.json").exists(), "Reuse the qualified image pins"
    if not exists(PREFIX):
        run("docker", "network", "create", PREFIX)
    if not exists(DB):
        run("docker", "run", "-d", "--name", DB, "--network", PREFIX,
            "-e", "POSTGRES_USER=qa", "-e", "POSTGRES_PASSWORD=isolated-workbench-qa",
            "-e", "POSTGRES_DB=workbench_qa", "pgvector/pgvector:pg16")
    for _ in range(30):
        ready = subprocess.run(["docker", "exec", DB, "pg_isready", "-U", "qa"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Isolated PostgreSQL failed to become ready")
    images = {}
    for name in ("backend", "frontend"):
        baseline = inspect("novel-writer-" + name)
        base_image = baseline["Config"]["Image"]
        assert inspect(base_image)["Id"] == baseline["Image"], "Production base tag changed"
        run("docker", "build", "-f", str(source() / f"scripts/release/{name}.Dockerfile"),
            "--build-arg", "BASE_IMAGE=" + base_image,
            "--build-arg", "SOURCE_SHA256=" + source_sha(),
            "-t", image_tag(name), str(source()))
        images[name] = inspect(image_tag(name))["Id"]
        assert inspect(images[name])["Config"]["Labels"]["novel-writer.source-sha256"] == source_sha()
    save("qa-images.json", images)
    if not exists(TOOLS):
        run("docker", "run", "-d", "--name", TOOLS, "--network", PREFIX,
            "--entrypoint", "sleep", "-v", str(ROOT) + ":/qa",
            "novel-writer-backend:materials-tests", "infinity")
    print(json.dumps({"images": images, "production_changed": False}), flush=True)


def regression():
    assert exists(TOOLS) and exists(DB)
    present = capture("docker", "exec", DB, "psql", "-U", "qa", "-d", "workbench_qa",
                      "-Atc", f"SELECT 1 FROM pg_database WHERE datname='{TEST_DATABASE}'")
    if not present.strip():
        run("docker", "exec", DB, "createdb", "-U", "qa", TEST_DATABASE)
    command = ["docker", "exec", "-w", "/qa/" + source().name + "/writter_back",
               "-e", f"TEST_DATABASE_URL=postgresql+asyncpg://qa:isolated-workbench-qa@{DB}:5432/{TEST_DATABASE}",
               "-e", "REQUIRE_DATABASE_TESTS=true", "-e", "ENVIRONMENT=test",
               TOOLS, "/app/.venv/bin/python", "-m", "pytest", "-q", "--tb=short"]
    path = ROOT / "evidence/linux-regression.txt"
    with path.open("w") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
    tail = path.read_text()[-5000:]
    save("evidence/linux-regression.json", {"exit_code": result.returncode, "tail": tail,
                                          "source_sha256": source_sha()})
    print(tail, flush=True)
    raise SystemExit(result.returncode)


def prepare():
    module = previous_release()
    module.idle()
    assert not (ROOT / "baseline.json").exists(), "Keep the existing release baseline"
    assert load("evidence/linux-regression.json")["exit_code"] == 0
    images = load("qa-images.json")
    files, services = [], {}
    for name in SERVICES:
        row = inspect("novel-writer-" + name)
        assert row["Config"]["Labels"]["com.docker.compose.project"] == "novel-writer"
        services[name] = {"container_id": row["Id"], "image_id": row["Image"],
                          "runtime": module.runtime(row)}
        if name in images:
            for path in row["Config"]["Labels"]["com.docker.compose.project.config_files"].split(","):
                assert Path(path).is_file()
                if path not in files:
                    files.append(path)
            module.tag_exact(row["Image"], f"novel-writer-{name}:workbench-rollback-20261014")
    save("baseline.json", {"files": files, "services": services, "source_sha256": source_sha(),
                          "captured_at": datetime.now(timezone.utc).isoformat(),
                          "authorization": "User explicitly requested production deployment on 2026-10-14"})
    save("compose.release.json", {"services": {name: {"image": image_tag(name)} for name in images}})
    save("compose.rollback.json", {"services": {
        name: {"image": f"novel-writer-{name}:workbench-rollback-20261014"} for name in images
    }})
    resolved = json.loads(capture(*module.compose("compose.release.json"), "config", "--format", "json"))
    original = json.loads(capture(*module.compose("compose.rollback.json"), "config", "--format", "json"))
    for name in images:
        desired, prior = dict(resolved["services"][name]), dict(original["services"][name])
        desired.pop("image")
        prior.pop("image")
        assert desired == prior, f"Unexpected runtime configuration change: {name}"
        current_env = dict(item.split("=", 1) for item in inspect("novel-writer-" + name)["Config"]["Env"])
        assert all(current_env.get(key) == str(value) for key, value in desired.get("environment", {}).items())
    save("evidence/data-before.json", module.data_baseline())
    print(json.dumps({"prepared": True, "compose_files": len(files), "active_writing_leases": 0}), flush=True)


def backup():
    previous_release().backup()


def rehearse():
    """Apply the exact candidate migration to a restored production backup."""
    assert load("evidence/backup-restore.json")["restore_database"] == RESTORE_DATABASE
    run("docker", "run", "--rm", "--network", PREFIX, "--entrypoint", "/app/.venv/bin/python",
        "-e", f"DATABASE_URL=postgresql+asyncpg://qa:isolated-workbench-qa@{DB}:5432/{RESTORE_DATABASE}",
        "-e", "ENVIRONMENT=test", "-e", "JWT_SECRET=isolated-workbench-migration-test-secret",
        load("qa-images.json")["backend"], "-m", "alembic", "upgrade", "head")
    revision = capture("docker", "exec", DB, "psql", "-U", "qa", "-d", RESTORE_DATABASE,
                       "-Atc", "SELECT version_num FROM alembic_version").decode().strip()
    assert revision == "0011_conversation_workbench"
    before = load("evidence/data-before.json")
    for table in before:
        name = table["table"]
        if name == "alembic_version":
            continue
        sql = f"""SELECT json_build_object('table','{name}','rows',count(*),
        'hash',md5(coalesce(string_agg(md5(row_to_json(t)::text),''
        ORDER BY md5(row_to_json(t)::text)),''))) FROM public."{name}" t;"""
        restored = json.loads(capture("docker", "exec", DB, "psql", "-U", "qa",
                                     "-d", RESTORE_DATABASE, "-Atc", sql))
        assert restored == table, f"Migration changed existing data: {name}"
    save("evidence/migration-rehearsal.json", {
        "revision": revision, "restored_existing_data_unchanged": True,
        "source_sha256": source_sha(),
    })
    print(json.dumps(load("evidence/migration-rehearsal.json")), flush=True)


def verify(rollback=False):
    module, baseline = previous_release(), load("baseline.json")
    images = load("qa-images.json")
    for name in SERVICES:
        row, prior = inspect("novel-writer-" + name), baseline["services"][name]
        expected = prior["image_id"] if rollback or name not in images else images[name]
        assert row["Image"] == expected and module.runtime(row) == prior["runtime"], name
        if name not in images:
            assert row["Id"] == prior["container_id"], f"Unrelated service restarted: {name}"
    assert module.healthy(), "Production applications are not healthy"
    ready = json.loads(capture("docker", "exec", "novel-writer-backend", "/app/.venv/bin/python", "-c",
        "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("
        "'http://127.0.0.1:8000/health/ready',timeout=15))))"))
    revision = module.database_sql("SELECT version_num FROM alembic_version;").decode().strip()
    assert revision == "0011_conversation_workbench"
    current = module.data_baseline()
    saved = load("evidence/data-before-rollback.json" if rollback else "evidence/data-before.json")
    assert [row for row in current if row["table"] != "alembic_version"] == [
        row for row in saved if row["table"] != "alembic_version"
    ], "Existing production business data changed"
    save("evidence/data-after.json", current)
    result = {"deployment": "rollback" if rollback else "updated", "healthy": True,
              "readiness": ready, "source_sha256": source_sha(), "revision": revision,
              "images": images, "existing_data_unchanged": True,
              "unrelated_services_not_restarted": True,
              "verified_at": datetime.now(timezone.utc).isoformat()}
    save("evidence/deployment.json", result)
    print(json.dumps(result), flush=True)


def deploy(rollback=False):
    module, baseline = previous_release(), load("baseline.json")
    module.idle()
    if rollback:
        save("evidence/data-before-rollback.json", module.data_baseline())
    else:
        assert load("evidence/migration-rehearsal.json")["restored_existing_data_unchanged"]
        assert module.data_baseline() == load("evidence/data-before.json"), "Production changed since backup"
        for name in ("backend", "frontend"):
            assert inspect("novel-writer-" + name)["Image"] == baseline["services"][name]["image_id"]
    override = "compose.rollback.json" if rollback else "compose.release.json"
    try:
        run(*module.compose(override), "up", "-d", "--no-deps", "--no-build", "backend", "frontend", cwd=BASE)
        for _ in range(48):
            if module.healthy():
                verify(rollback)
                return
            time.sleep(5)
        raise RuntimeError("Production application health deadline exceeded")
    except BaseException:
        if not rollback:
            run(*module.compose("compose.rollback.json"), "up", "-d", "--no-deps",
                "--no-build", "backend", "frontend", cwd=BASE)
            save("evidence/automatic-rollback.json", {"images_restored": True, "database_retained": True})
            print("Restored previous application images; kept current data.", flush=True)
        raise


def smoke_session():
    from urllib.request import Request, urlopen
    original = load("smoke-private.json")
    with urlopen(Request("http://127.0.0.1:5173/api/v1/auth/login",
                         data=json.dumps({"email": original["email"], "password": original["password"]}).encode(),
                         headers={"Content-Type": "application/json"}, method="POST"), timeout=60) as response:
        return json.load(response)


def smoke_request(method, path, session, data=None, key=None):
    from urllib.request import Request, urlopen
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + session["access_token"],
               "X-Tenant-ID": session["tenants"][0]["id"]}
    if key:
        headers["Idempotency-Key"] = key
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    with urlopen(Request("http://127.0.0.1:5173/api/v1" + path, data=body,
                         headers=headers, method=method), timeout=60) as response:
        return json.load(response)


def smoke():
    """Create one marked test book and allow exactly one paid generation attempt."""
    assert not (ROOT / "smoke-private.json").exists(), "Do not repeat paid smoke requests"
    original = json.loads((BASE / "releases/production-20261001/acceptance-private.json").read_text())
    account = original["accounts"][0]
    assert account["email"].startswith("production-qa-20261001-")
    private = {"email": account["email"], "password": account["password"], "marked_test": True}
    save("smoke-private.json", private)
    session = smoke_session()
    novel = smoke_request("POST", "/novels", session, {
        "title": "[生产测试]对话资产检索20261014", "novel_type": "suspense",
        "summary": "仅用于部署验收。失明的师父回到旧车站，青玉剑始终完好。",
        "planning": {"preset": "custom", "target_chapters": 1, "target_total_words": 4200},
    }, "workbench-production-smoke-create-20261014")
    novel_id = novel["novel_id"]
    root = f"/novels/{novel_id}/workbench"
    world = smoke_request("POST", root + "/assets", session, {
        "title": "青玉剑规则", "kind": "world", "content": "青玉剑不可损毁。师父始终失明。",
    })
    conversation = smoke_request("POST", root + "/conversations", session, {"title": "部署验收"})
    private.update(novel_id=novel_id, conversation_id=conversation["id"], asset_id=world["id"],
                   tenant_id=session["tenants"][0]["id"], started=True)
    save("smoke-private.json", private)
    job = smoke_request("POST", root + f"/conversations/{conversation['id']}/messages", session, {
        "text": "这是部署测试。请依据青玉剑规则写一段50字以内的虚构小说开场，不解释。",
        "intent": "discuss", "reference_ids": [world["id"]],
    }, "workbench-production-smoke-generate-20261014")
    private["job_id"] = job["id"]
    save("smoke-private.json", private)
    save("evidence/smoke-created.json", {
        "novel_id": novel_id, "conversation_id": conversation["id"], "job_id": job["id"],
        "marked_test": True, "max_paid_generation_attempts": 1,
    })
    print(json.dumps(load("evidence/smoke-created.json")), flush=True)


def observe():
    private, session = load("smoke-private.json"), smoke_session()
    root = f"/novels/{private['novel_id']}/workbench"
    job = smoke_request("GET", root + "/jobs/" + private["job_id"], session)
    overview = smoke_request("GET", root + "/overview", session)
    hits = smoke_request("GET", root + "/search?q=%E9%9D%92%E7%8E%89%E5%89%91", session)
    assert any(row["source_id"] == private["asset_id"] for row in hits["hits"])
    assert overview["chapters"] == []
    source = next(row for row in job["sources"] if row["source_id"] == private["asset_id"])
    assert source["version"] == 1 and source["text"] == "青玉剑不可损毁。师父始终失明。"
    save("evidence/smoke-job.json", job)
    result = {"novel_id": private["novel_id"], "status": job["status"],
              "reply_chars": len(job["content"]), "error": job["error"],
              "retrieval_available": job["retrieval_available"],
              "source_version_verified": True, "official_chapters": 0,
              "paid_attempts": 1}
    save("evidence/smoke-status.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def audit():
    """Compare original business rows with the restored pre-deployment backup."""
    from uuid import UUID
    module, private = previous_release(), load("smoke-private.json")
    novel, tenant = str(UUID(private["novel_id"])), str(UUID(private["tenant_id"]))
    tables = []
    for table in load("evidence/data-before.json"):
        name = table["table"]
        if name == "alembic_version":
            continue
        columns = module.database_sql(
            f"SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='{name}';"
        ).decode().splitlines()
        where = ""
        if name == "novels":
            where = f" WHERE id <> '{novel}'::uuid"
        elif "novel_id" in columns:
            where = f" WHERE novel_id IS DISTINCT FROM '{novel}'::uuid"
        elif name == "tenants":
            where = f" WHERE id <> '{tenant}'::uuid"
        elif name == "quota_reservations":
            where = f" WHERE tenant_id <> '{tenant}'::uuid"
        sql = f"""SELECT json_build_object('rows',count(*),'hash',
        md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')))
        FROM (SELECT * FROM public."{name}"{where}) t;"""
        current = json.loads(module.database_sql(sql))
        restored = json.loads(capture("docker", "exec", DB, "psql", "-U", "qa",
                                     "-d", RESTORE_DATABASE, "-Atc", sql))
        assert current == restored, f"Original data changed: {name}"
        tables.append({"table": name, **current})
    baseline, images = load("baseline.json"), load("qa-images.json")
    for name in SERVICES:
        row, prior = inspect("novel-writer-" + name), baseline["services"][name]
        assert module.runtime(row) == prior["runtime"]
        assert row["Image"] == images.get(name, prior["image_id"])
        assert name in images or row["Id"] == prior["container_id"]
    assert module.healthy()
    result = {"existing_business_data_unchanged": True, "excluded_marked_qa_novel": novel,
              "allowed_qa_tenant_quota_usage": True, "healthy": True,
              "active_writing_leases": module.idle(), "tables": tables}
    save("evidence/final-audit.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "tables"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["qa", "regression", "prepare", "backup", "rehearse",
                                           "deploy", "verify", "rollback", "smoke", "observe", "audit"])
    action = parser.parse_args().action
    if action == "rollback":
        deploy(True)
    else:
        globals()[action]()
