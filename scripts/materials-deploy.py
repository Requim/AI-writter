"""使用已备份的 Compose 链发布本轮候选，健康失败自动回退。"""

import json
from pathlib import Path
import subprocess
import time

BASE = Path("/opt/novel-writer")
ROOT = BASE / "releases/materials-20260922"


def inspect(name):
    return json.loads(subprocess.check_output(["docker", "inspect", f"novel-writer-{name}"]))[0]


def command(files, research=False):
    args = ["docker", "compose", "--project-name", "novel-writer",
            "--project-directory", str(BASE), "--env-file", str(BASE / ".env")]
    if research:
        args += ["--env-file", str(BASE / ".env.research")]
    for path in files:
        args += ["-f", path]
    return args


def healthy(name):
    for _ in range(36):
        state = inspect(name)["State"]
        if state["Running"] and state.get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(5)
    raise RuntimeError(f"health timeout: {name}")


def deploy_group(name, services, image, research=False):
    baseline = json.loads((ROOT / "deployment-baseline.json").read_text())
    files = baseline[name]["labels"]["com.docker.compose.project.config_files"].split(",")
    override = ROOT / f"compose.{name}.json"
    override.write_text(json.dumps({"services": {service: {"image": image} for service in services}}))
    args = command(files + [str(override)], research)
    subprocess.run(args + ["config", "--services"], check=True)
    subprocess.run(args + ["up", "-d", "--no-build", "--no-deps", *services], check=True)
    healthy(name)


def rollback():
    baseline = json.loads((ROOT / "deployment-baseline.json").read_text())
    for name, services in (("research-api", ["research-api", "research-worker"]),
                           ("backend", ["backend"]), ("frontend", ["frontend"])):
        files = baseline[name]["labels"]["com.docker.compose.project.config_files"].split(",")
        subprocess.run(command(files, name == "research-api") + [
            "up", "-d", "--no-build", "--no-deps", *services,
        ], check=True)


def main():
    """发布前再次确认无活动写作和采集任务，不中断用户正在进行的任务。"""
    for database, query in (
        ("novel_writer", "SELECT count(*) FROM workflow_leases WHERE expires_at > now()"),
        ("novel_research", "SELECT count(*) FROM research_jobs WHERE status IN ('running','queued')"),
    ):
        value = subprocess.check_output([
            "docker", "exec", "novel-writer-database", "psql", "-U", "novel_writer",
            "-d", database, "-At", "-c", query,
        ], text=True).strip()
        if value != "0":
            raise RuntimeError(f"active work in {database}: {value}")
    try:
        deploy_group("research-api", ["research-api", "research-worker"],
                     "novel-writer-research:materials-20260922", True)
        deploy_group("backend", ["backend"], "novel-writer-backend:materials-20260922")
        deploy_group("frontend", ["frontend"], "novel-writer-frontend:materials-20260922")
    except Exception:
        rollback()
        raise
    print("materials_release_healthy")


if __name__ == "__main__":
    main()
