"""2026-10-01 host-side release; retain the existing Compose environment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path("/opt/novel-writer")
RELEASE = ROOT / "releases/production-20261001"
BACKEND = "novel-writer-backend:production-20261001"
FRONTEND = "novel-writer-frontend:production-20261001"
RESTORE_DB = "novel-writer-qa-restore-20261001"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def inspect(*names):
    return json.loads(subprocess.check_output(["docker", "inspect", *names]))


def baseline():
    target = RELEASE / "baseline.json"
    if target.exists():
        return json.loads(target.read_text())
    containers = inspect("novel-writer-backend", "novel-writer-frontend",
                         "novel-writer-research-api", "novel-writer-research-worker")
    files = []
    services = {}
    for item in containers:
        labels = item["Config"]["Labels"]
        service = labels["com.docker.compose.service"]
        services[service] = {"image": item["Config"]["Image"], "image_id": item["Image"]}
        if service in {"backend", "frontend"}:
            for name in labels["com.docker.compose.project.config_files"].split(","):
                if name not in files:
                    assert Path(name).is_file(), name
                    files.append(name)
    saved = {"project": "novel-writer", "files": files, "services": services,
             "source_sha256": hashlib.sha256((RELEASE / "current-source.tar.gz").read_bytes()).hexdigest()}
    target.write_text(json.dumps(saved, indent=2))
    os.chmod(target, 0o600)
    override = {"services": {name: {"image": values["image"]}
                            for name, values in services.items()}}
    (RELEASE / "compose.rollback.json").write_text(json.dumps(override, indent=2))
    print(json.dumps({"captured_services": list(services), "compose_files": len(files)}))
    return saved


def compose(extra):
    args = ["docker", "compose", "--project-directory", str(ROOT), "-p", "novel-writer",
            "--env-file", str(ROOT / ".env")]
    for path in baseline()["files"] + [str(extra)]:
        args += ["-f", path]
    return args


def backup():
    baseline()
    target = RELEASE / "production-before.dump"
    if target.exists():
        raise RuntimeError("Existing backup will not be overwritten")
    with target.open("wb") as output:
        run("docker", "exec", "novel-writer-database", "sh", "-c",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
            stdout=output)
    os.chmod(target, 0o600)
    with target.open("rb") as content:
        listing = subprocess.check_output(["docker", "exec", "-i", RESTORE_DB,
                                          "pg_restore", "--list"], stdin=content)
    (RELEASE / "evidence/backup-catalog.txt").write_bytes(listing)
    run("docker", "exec", RESTORE_DB, "createdb", "-U", "qa", "production_restore_test")
    with target.open("rb") as content:
        run("docker", "exec", "-i", RESTORE_DB, "pg_restore",
            "-U", "qa", "-d", "production_restore_test", "--no-owner", "--no-acl",
            "--exit-on-error", stdin=content)
    count = subprocess.check_output(["docker", "exec", RESTORE_DB, "psql",
        "-U", "qa", "-d", "production_restore_test", "-Atc",
        "SELECT 'novels='||count(*) FROM novels UNION ALL SELECT 'chapters='||count(*) FROM chapters"])
    record = {"sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "restore": count.decode().splitlines(), "size": target.stat().st_size}
    (RELEASE / "evidence/backup-restore.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record))


def build():
    saved = baseline()
    current = hashlib.sha256((RELEASE / "current-source.tar.gz").read_bytes()).hexdigest()
    source = RELEASE / "source"
    for service, image in (("backend", BACKEND), ("frontend", FRONTEND)):
        base = saved["services"][service]
        assert inspect(base["image"])[0]["Id"] == base["image_id"], "Baseline image changed"
        run("docker", "build", "-f", str(source / f"scripts/release/{service}.Dockerfile"),
            "--build-arg", f"BASE_IMAGE={base['image']}",
            "--build-arg", f"SOURCE_SHA256={current}", "-t", image, str(source))
    images = inspect(BACKEND, FRONTEND)
    (RELEASE / "evidence/images.json").write_text(json.dumps(
        [{"id": row["Id"], "tags": row["RepoTags"], "labels": row["Config"]["Labels"]} for row in images], indent=2))
    release = {"services": {"backend": {"image": BACKEND, "stop_grace_period": "45s",
                                       "environment": {"AUTONOMOUS_AUTHOR_ENABLED": "true"}},
                            "frontend": {"image": FRONTEND}}}
    (RELEASE / "compose.release.json").write_text(json.dumps(release, indent=2))


def healthy():
    rows = inspect("novel-writer-backend", "novel-writer-frontend")
    return all(row["State"].get("Health", {}).get("Status") == "healthy" for row in rows)


def verify_configuration(path):
    resolved = json.loads(subprocess.check_output([*compose(path), "config", "--format", "json"], cwd=ROOT))
    for row in inspect("novel-writer-backend", "novel-writer-frontend"):
        service = row["Config"]["Labels"]["com.docker.compose.service"]
        current = dict(value.split("=", 1) for value in row["Config"]["Env"])
        desired = resolved["services"][service].get("environment", {})
        changed = [key for key, value in desired.items() if current.get(key) != str(value)]
        if service == "backend" and changed == ["AUTONOMOUS_AUTHOR_ENABLED"]:
            assert str(desired["AUTONOMOUS_AUTHOR_ENABLED"]).lower() == "true"
            changed = []
        assert not changed, f"Unexpected {service} environment changes: {changed}"
    print(json.dumps({"configuration": "preserved-except-authorized-autonomous-availability",
                      "tenant_flags": "unchanged"}))


def deploy(rollback=False):
    baseline()
    if not rollback:
        assert (RELEASE / "evidence/backup-restore.json").is_file()
        active = subprocess.check_output(["docker", "exec", "novel-writer-database", "sh", "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc '
            '"SELECT count(*) FROM workflow_leases WHERE token IS NOT NULL AND expires_at > clock_timestamp()"'])
        assert active.strip() == b"0", "Active user writing leases; release not switched"
    path = RELEASE / ("compose.rollback.json" if rollback else "compose.release.json")
    if not rollback:
        verify_configuration(path)
    try:
        run(*compose(path), "up", "-d", "--no-deps", "--no-build", "backend", "frontend", cwd=ROOT)
        for _ in range(36):
            if healthy():
                print(json.dumps({"deployment": "rollback" if rollback else "updated", "healthy": True}))
                return
            time.sleep(5)
        raise RuntimeError("Application health deadline exceeded")
    except BaseException:
        if not rollback:
            run(*compose(RELEASE / "compose.rollback.json"), "up", "-d", "--no-deps",
                "--no-build", "backend", "frontend", cwd=ROOT)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["baseline", "backup", "build", "deploy", "rollback"])
    action = parser.parse_args().action
    if action == "rollback":
        deploy(rollback=True)
    else:
        globals()[action]()
