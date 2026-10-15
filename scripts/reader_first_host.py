"""Host-side isolated QA. Production containers and data are read only."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path("/opt/novel-writer/releases/reader-first-20261013")
PREFIX = "novel-writer-reader-qa-20261013"
NETWORK = PREFIX
DB = PREFIX + "-db"
REDIS = PREFIX + "-redis"
BACKEND = PREFIX + "-backend"
FRONTEND = PREFIX + "-frontend"
TOOLS = PREFIX + "-tools"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def inspect(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name]))[0]


def exists(name):
    return subprocess.run(["docker", "inspect", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def source():
    path = Path((ROOT / "source-path.txt").read_text())
    assert path.resolve().is_relative_to(ROOT.resolve()) and not path.is_symlink()
    return path


def require_idle():
    if not exists(BACKEND):
        return
    code = """import asyncio
from sqlalchemy import select,func
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.runtime_models import WorkflowLeaseModel
async def main():
    assert 'reader_acceptance' in settings.DATABASE_URL
    repo=PostgresNovelRepository(settings.DATABASE_URL)
    async with repo.async_session() as session:
        active=await session.scalar(select(func.count()).select_from(WorkflowLeaseModel).where(WorkflowLeaseModel.expires_at>func.clock_timestamp()))
        assert active==0,'Isolated writing is still active; do not interrupt paid requests'
    await repo.aclose()
asyncio.run(main())
"""
    run("docker", "exec", "-i", BACKEND, "/app/.venv/bin/python", "-", input=code.encode())


def setup():
    require_idle()
    if subprocess.run(["docker", "network", "inspect", NETWORK], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        run("docker", "network", "create", NETWORK)
    if not exists(DB):
        run("docker", "run", "-d", "--name", DB, "--network", NETWORK,
            "-e", "POSTGRES_USER=qa", "-e", "POSTGRES_PASSWORD=isolated-qa",
            "-e", "POSTGRES_DB=reader_acceptance", "pgvector/pgvector:pg16")
    if not exists(REDIS):
        run("docker", "run", "-d", "--name", REDIS, "--network", NETWORK, "redis:7.4-alpine")
    image = "novel-writer-backend:reader-first-20261013"
    baseline = inspect("novel-writer-backend")
    base = baseline["Config"]["Image"]
    assert inspect(base)["Id"] == baseline["Image"], "Production baseline tag changed"
    run("docker", "build", "-f", str(source() / "scripts/release/backend.Dockerfile"),
        "--build-arg", "BASE_IMAGE=" + base,
        "--build-arg", "SOURCE_SHA256=" + (ROOT / "source-sha256.txt").read_text(),
        "-t", image, str(source()))
    if not exists(TOOLS):
        run("docker", "run", "-d", "--name", TOOLS, "--network", NETWORK,
            "--entrypoint", "sleep", "-v", str(ROOT) + ":/qa",
            "novel-writer-backend:materials-tests", "infinity")
    env = dict(item.split("=", 1) for item in inspect("novel-writer-backend")["Config"]["Env"])
    env.update(DATABASE_URL=f"postgresql+asyncpg://qa:isolated-qa@{DB}:5432/reader_acceptance",
               REDIS_URL=f"redis://{REDIS}:6379/0", JWT_SECRET=secrets.token_urlsafe(48),
               LANGGRAPH_CHECKPOINTER_URI="",
               ENVIRONMENT="test", NOVEL_PLANNING_V1_ENABLED="true", AUTONOMOUS_AUTHOR_ENABLED="true",
               RESEARCH_LIBRARY_ENABLED="false", PLATFORM_ADMIN_EMAIL="", PLATFORM_ADMIN_PASSWORD="")
    env_file = ROOT / "qa-private.env"
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("\n".join(f"{key}={value}" for key, value in env.items() if "\n" not in value))
    if exists(BACKEND):
        assert inspect(BACKEND)["Name"] == "/" + BACKEND
        run("docker", "stop", BACKEND)
        run("docker", "rm", BACKEND)
    run("docker", "run", "-d", "--name", BACKEND, "--network", NETWORK,
        "--network-alias", "backend",
        "--env-file", str(env_file), "-p", "127.0.0.1:5183:8000", image)
    print(json.dumps({"qa_backend": BACKEND, "source": str(source()), "production_changed": False}))


def frontend():
    baseline = inspect("novel-writer-frontend")
    base = baseline["Config"]["Image"]
    assert inspect(base)["Id"] == baseline["Image"]
    image = "novel-writer-frontend:reader-first-20261013"
    run("docker", "build", "-f", str(source() / "scripts/release/frontend.Dockerfile"),
        "--build-arg", "BASE_IMAGE=" + base,
        "--build-arg", "SOURCE_SHA256=" + (ROOT / "source-sha256.txt").read_text(),
        "-t", image, str(source()))
    if exists(FRONTEND):
        assert inspect(FRONTEND)["Name"] == "/" + FRONTEND
        run("docker", "stop", FRONTEND)
        run("docker", "rm", FRONTEND)
    run("docker", "run", "-d", "--name", FRONTEND, "--network", NETWORK,
        "-p", "127.0.0.1:5184:80", image)
    print(json.dumps({"qa_frontend": FRONTEND, "production_changed": False}))


def regression():
    present = subprocess.check_output(["docker", "exec", DB, "psql", "-U", "qa",
        "-d", "reader_acceptance", "-Atc", "SELECT 1 FROM pg_database WHERE datname='reader_regression_test'"])
    if present.strip() != b"1":
        run("docker", "exec", DB, "createdb", "-U", "qa", "reader_regression_test")
    target = "/qa/" + source().name + "/writter_back"
    command = ["docker", "exec", "-w", target,
               "-e", f"TEST_DATABASE_URL=postgresql+asyncpg://qa:isolated-qa@{DB}:5432/reader_regression_test",
               "-e", f"REDIS_URL=redis://{REDIS}:6379/1", "-e", "REQUIRE_DATABASE_TESTS=true",
               TOOLS, "/app/.venv/bin/python", "-m", "pytest", "-q", "--tb=short"]
    with (ROOT / "evidence/linux-regression.txt").open("w") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
    print(json.dumps({"linux_regression_returncode": result.returncode}))
    if result.returncode:
        print((ROOT / "evidence/linux-regression.txt").read_text()[-14000:])
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "frontend", "regression"])
    globals()[parser.parse_args().action]()
