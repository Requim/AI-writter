"""Release the qualified reader-first images without rebuilding or changing data."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

BASE = Path("/opt/novel-writer")
ROOT = BASE / "releases/reader-first-production-20261013"
QA = BASE / "releases/reader-first-20261013"
SOURCE = "f8f8d2555ca4b07cb19c871c344476fcf322d99e5f750d2f72cb6888991d5bac"
TARGETS = {
    "backend": "sha256:405f99d26e01b7b90a001090e4d81d4a82ca43f7d5d570fe2c55f1594377ef8c",
    "frontend": "sha256:465c9b82330e26db5fba1906192480b3e4fec4683963a0ce58342aa3c7dce79c",
}
NAMES = ["backend", "frontend", "database", "redis", "research-api", "research-worker"]
RESTORE = "novel-writer-reader-qa-20261013-db"
RESTORE_DATABASE = "reader_production_restore_20261013"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def capture(*args):
    return subprocess.check_output(args)


def inspect(name):
    return json.loads(capture("docker", "inspect", name))[0]


def write(name, data):
    path = ROOT / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def database_sql(sql):
    return subprocess.check_output(
        ["docker", "exec", "-i", "novel-writer-database", "sh", "-c",
         'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],
        input=sql.encode(),
    )


def idle():
    active = int(database_sql(
        "SELECT count(*) FROM workflow_leases "
        "WHERE token IS NOT NULL AND expires_at > clock_timestamp();"
    ).strip())
    assert active == 0, "Active writing leases; no production switch is allowed"
    return active


def data_baseline():
    names = database_sql(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
    ).decode().splitlines()
    # Runtime recovery may update command/lease rows on process startup.
    prefixes = ("novel", "chapter", "character", "story_fact", "creative", "author_")
    protected = [name for name in names if name.startswith(prefixes) or name in {
        "tenants", "users", "tenant_memberships", "quota_reservations", "alembic_version",
    }]
    assert {"novels", "chapters", "tenants", "alembic_version"} <= set(protected)
    statements = ["BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;"]
    for name in protected:
        assert name.replace("_", "").isalnum()
        statements.append(
            f"""SELECT json_build_object('table','{name}','rows',count(*),
            'hash',md5(coalesce(string_agg(md5(row_to_json(t)::text),''
            ORDER BY md5(row_to_json(t)::text)),''))) FROM public."{name}" t;"""
        )
    statements.append("COMMIT;")
    rows = database_sql("\n".join(statements)).decode().splitlines()
    return [json.loads(row) for row in rows if row.startswith("{")]


def runtime(row):
    return {
        "environment_sha256": digest(sorted(row["Config"]["Env"])),
        "mounts_sha256": digest(row["Mounts"]),
        "ports": row["HostConfig"]["PortBindings"],
        "networks": sorted(row["NetworkSettings"]["Networks"]),
        "restart_policy": row["HostConfig"]["RestartPolicy"],
    }


def compose(override):
    args = ["docker", "compose", "--project-directory", str(BASE), "-p", "novel-writer",
            "--env-file", str(BASE / ".env")]
    for path in read("baseline.json")["files"] + [str(ROOT / override)]:
        args.extend(["-f", path])
    return args


def tag_exact(image_id, tag):
    result = subprocess.run(["docker", "image", "inspect", tag],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        assert json.loads(result.stdout)[0]["Id"] == image_id, f"Refusing to move tag {tag}"
    else:
        run("docker", "tag", image_id, tag)


def prepare():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    (ROOT / "evidence").mkdir(mode=0o700, exist_ok=True)
    assert not (ROOT / "baseline.json").exists(), "Existing release baseline must be reused"
    idle()
    services, files = {}, []
    for name in NAMES:
        row = inspect("novel-writer-" + name)
        labels = row["Config"]["Labels"]
        assert labels["com.docker.compose.project"] == "novel-writer"
        services[name] = {
            "container_id": row["Id"], "image_id": row["Image"],
            "image": row["Config"]["Image"], "runtime": runtime(row),
        }
        if name in TARGETS:
            for path in labels["com.docker.compose.project.config_files"].split(","):
                assert Path(path).is_file()
                if path not in files:
                    files.append(path)
    for name, image_id in TARGETS.items():
        image = inspect(image_id)
        assert image["Config"]["Labels"]["novel-writer.source-sha256"] == SOURCE
        assert inspect("novel-writer-reader-qa-20261013-" + name)["Image"] == image_id
        tag_exact(image_id, f"novel-writer-{name}:reader-first-production-20261013")
        tag_exact(services[name]["image_id"], f"novel-writer-{name}:reader-first-rollback-20261013")
    evidence = (QA / "evidence/linux-regression.txt").read_text()
    assert "1337 passed" in evidence and "failed" not in evidence.rsplit("\n", 5)[-1]
    write("baseline.json", {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "files": files, "services": services, "source_sha256": SOURCE,
        "authorization": "2026-10-13 user explicitly requested production deployment",
        "acceptance": "nine real chapters incomplete; not waived as a quality claim",
    })
    write("compose.release.json", {"services": {
        name: {"image": f"novel-writer-{name}:reader-first-production-20261013"}
        for name in TARGETS
    }})
    write("compose.rollback.json", {"services": {
        name: {"image": f"novel-writer-{name}:reader-first-rollback-20261013"}
        for name in TARGETS
    }})
    resolved = json.loads(capture(*compose("compose.release.json"), "config", "--format", "json"))
    original = json.loads(capture(*compose("compose.rollback.json"), "config", "--format", "json"))
    for name in TARGETS:
        desired = dict(resolved["services"][name])
        previous = dict(original["services"][name])
        desired.pop("image")
        previous.pop("image")
        assert desired == previous, f"Compose configuration changed beyond image: {name}"
        current_env = dict(value.split("=", 1) for value in inspect("novel-writer-" + name)["Config"]["Env"])
        for key, value in desired.get("environment", {}).items():
            assert current_env.get(key) == str(value), f"Environment mismatch: {name}/{key}"
    write("evidence/data-before.json", data_baseline())
    write("evidence/images.json", {name: {"image_id": image_id, "source_sha256": SOURCE}
                                  for name, image_id in TARGETS.items()})
    print(json.dumps({"prepared": True, "compose_files": len(files),
                      "active_writing_leases": 0, "source_sha256": SOURCE}), flush=True)


def backup():
    assert (ROOT / "baseline.json").exists()
    idle()
    path = ROOT / "production-before.dump"
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        run("docker", "exec", "novel-writer-database", "sh", "-c",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
            stdout=output)
    with path.open("rb") as content:
        listing = subprocess.check_output(["docker", "exec", "-i", RESTORE, "pg_restore", "--list"],
                                          stdin=content)
    assert b"TABLE DATA" in listing
    (ROOT / "evidence/backup-catalog.txt").write_bytes(listing)
    present = capture("docker", "exec", RESTORE, "psql", "-U", "qa", "-d", "reader_acceptance",
                      "-Atc", f"SELECT 1 FROM pg_database WHERE datname='{RESTORE_DATABASE}'")
    assert not present.strip(), "Existing restore-test database will not be replaced"
    run("docker", "exec", RESTORE, "createdb", "-U", "qa", RESTORE_DATABASE)
    with path.open("rb") as content:
        run("docker", "exec", "-i", RESTORE, "pg_restore", "-U", "qa", "-d", RESTORE_DATABASE,
            "--no-owner", "--no-acl", "--exit-on-error", stdin=content)
    counts = capture("docker", "exec", RESTORE, "psql", "-U", "qa", "-d", RESTORE_DATABASE,
                     "-Atc", "SELECT 'novels='||count(*) FROM novels UNION ALL "
                     "SELECT 'chapters='||count(*) FROM chapters").decode().splitlines()
    result = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "bytes": path.stat().st_size, "restore_database": RESTORE_DATABASE,
              "restored_counts": counts}
    write("evidence/backup-restore.json", result)
    print(json.dumps(result), flush=True)


def healthy():
    rows = [inspect("novel-writer-" + name) for name in TARGETS]
    return all(row["State"]["Running"] and row["State"].get("Health", {}).get("Status") == "healthy"
               for row in rows)


def verify(rollback=False):
    saved = read("baseline.json")
    for name in NAMES:
        current = inspect("novel-writer-" + name)
        prior = saved["services"][name]
        expected = prior["image_id"] if rollback or name not in TARGETS else TARGETS[name]
        assert current["Image"] == expected, f"Image mismatch: {name}"
        assert runtime(current) == prior["runtime"], f"Runtime configuration changed: {name}"
        if name not in TARGETS:
            assert current["Id"] == prior["container_id"], f"Unrelated service restarted: {name}"
    assert healthy(), "Application containers are not healthy"
    run("docker", "exec", "novel-writer-backend", "/app/.venv/bin/python", "-c",
        "import json,urllib.request; print(json.load(urllib.request.urlopen("
        "'http://127.0.0.1:8000/health/ready',timeout=15)))")
    for path in ("/healthz", "/api/v1/auth/me"):
        if path.endswith("/me"):
            from urllib.error import HTTPError
            try:
                urlopen("http://127.0.0.1:5173" + path, timeout=15)
            except HTTPError as error:
                assert error.code == 401, "Unauthenticated API route did not reject access"
            else:
                raise AssertionError("Unauthenticated API route accepted access")
        else:
            with urlopen("http://127.0.0.1:5173" + path, timeout=15) as response:
                assert response.status == 200
    current_data = data_baseline()
    write("evidence/data-after.json", current_data)
    expected_data = read("evidence/data-before-rollback.json" if rollback else "evidence/data-before.json")
    assert current_data == expected_data, "Protected production data changed"
    result = {"deployment": "rollback" if rollback else "updated", "healthy": True,
              "source_sha256": SOURCE if not rollback else "restored original image pins",
              "images": {name: inspect("novel-writer-" + name)["Image"] for name in TARGETS},
              "environment_and_protected_data": "unchanged", "unrelated_services": "not restarted",
              "verified_at": datetime.now(timezone.utc).isoformat()}
    write("evidence/deployment.json", result)
    print(json.dumps(result), flush=True)


def switch(rollback=False):
    saved = read("baseline.json")
    idle()
    if not rollback:
        assert (ROOT / "evidence/backup-restore.json").exists()
        for name in TARGETS:
            assert inspect("novel-writer-" + name)["Image"] == saved["services"][name]["image_id"]
        assert data_baseline() == read("evidence/data-before.json"), "Production changed since baseline"
    else:
        write("evidence/data-before-rollback.json", data_baseline())
    override = "compose.rollback.json" if rollback else "compose.release.json"
    try:
        run(*compose(override), "up", "-d", "--no-deps", "--no-build", "backend", "frontend", cwd=BASE)
        for _ in range(36):
            if healthy():
                verify(rollback)
                return
            time.sleep(5)
        raise RuntimeError("Application health deadline exceeded")
    except BaseException:
        if not rollback:
            run(*compose("compose.rollback.json"), "up", "-d", "--no-deps",
                "--no-build", "backend", "frontend", cwd=BASE)
            print("Rolled back application images; retained current database.", flush=True)
        raise


def audit():
    """Compare original rows with the restored backup after adding the marked test."""
    saved = read("baseline.json")
    smoke = read("smoke-private.json")
    with (ROOT / "evidence/smoke-created.json").open(encoding="utf-8") as content:
        assert json.load(content)["marked_test"] is True
    for name in NAMES:
        row = inspect("novel-writer-" + name)
        prior = saved["services"][name]
        assert runtime(row) == prior["runtime"]
        assert row["Image"] == (TARGETS[name] if name in TARGETS else prior["image_id"])
        if name not in TARGETS:
            assert row["Id"] == prior["container_id"]
    assert healthy()
    account = json.loads((BASE / "releases/production-20261001/acceptance-private.json").read_text())
    tenant = account["accounts"][0]["session"]["tenants"][0]["id"]
    from uuid import UUID
    novel, tenant = str(UUID(smoke["novel_id"])), str(UUID(tenant))
    summaries = []
    for table in read("evidence/data-before.json"):
        name = table["table"]
        columns = database_sql(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema='public' AND table_name='{name}';"
        ).decode().splitlines()
        where = ""
        if name == "novels":
            where = f" WHERE id <> '{novel}'::uuid"
        elif "novel_id" in columns:
            where = f" WHERE novel_id IS DISTINCT FROM '{novel}'::uuid"
        elif name == "tenants":
            where = f" WHERE id <> '{tenant}'::uuid"
        elif name == "quota_reservations" and "tenant_id" in columns:
            where = f" WHERE tenant_id <> '{tenant}'::uuid"
        sql = f"""SELECT json_build_object('rows',count(*),'hash',
        md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')))
        FROM (SELECT * FROM public."{name}"{where}) t;"""
        current = json.loads(database_sql(sql))
        restored = json.loads(capture(
            "docker", "exec", RESTORE, "psql", "-U", "qa", "-d", RESTORE_DATABASE, "-Atc", sql,
        ))
        assert current == restored, f"Original rows changed after smoke: {name}"
        summaries.append({"table": name, **current})
    result = {"original_data_unchanged": True, "excluded_new_test_novel": novel,
              "allowed_test_tenant_quota_usage": True, "tables": summaries,
              "healthy": True, "active_writing_leases": idle()}
    write("evidence/final-audit.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "tables"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "backup", "deploy", "verify", "rollback", "audit"])
    action = parser.parse_args().action
    if action in {"deploy", "rollback"}:
        switch(action == "rollback")
    else:
        globals()[action]()
