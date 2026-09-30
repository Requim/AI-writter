"""采集修复的窄范围发布；保留线上配置与回滚镜像，不重启写作后端。"""

import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path("/opt/novel-writer/releases/collection-fix-20260924")
BASE = Path("/opt/novel-writer")
SERVICES = ("research-api", "research-worker", "frontend")
TAG = "collection-fix-20260924"


def inspect(service):
    return json.loads(subprocess.check_output([
        "docker", "inspect", f"novel-writer-{service}",
    ]))[0]


def idle():
    count = subprocess.check_output([
        "docker", "exec", "novel-writer-database", "psql", "-U", "novel_writer",
        "-d", "novel_research", "-At", "-c",
        "SELECT count(*) FROM research_jobs WHERE status IN ('running','queued')",
    ], text=True).strip()
    if count != "0":
        raise RuntimeError(f"Active research jobs: {count}")


def snapshot():
    """只记录回滚所需配置，不保存或输出容器环境中的凭据。"""
    path = ROOT / "baseline.json"
    if path.exists():
        raise RuntimeError("Baseline already exists; do not overwrite")
    idle()
    baseline = {}
    for service in SERVICES:
        row = inspect(service)
        baseline[service] = {
            "image": row["Config"]["Image"], "image_id": row["Image"],
            "labels": row["Config"]["Labels"], "mounts": row["Mounts"],
            "ports": row["NetworkSettings"]["Ports"],
            "networks": list(row["NetworkSettings"]["Networks"]),
        }
    path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print("Baseline saved; no active research jobs")


def compose(service, baseline, rollback=False):
    row = baseline[service]
    labels = row["labels"]
    files = labels["com.docker.compose.project.config_files"].split(",")
    args = ["docker", "compose", "--project-name", labels["com.docker.compose.project"],
            "--project-directory", labels["com.docker.compose.project.working_dir"],
            "--env-file", str(BASE / ".env")]
    if service.startswith("research"):
        args += ["--env-file", str(BASE / ".env.research")]
    group = ["research-api", "research-worker"] if service == "research-api" else [service]
    overrides = {
        item: {"image": baseline[item]["image"] if rollback else
               f"novel-writer-{'research' if item.startswith('research') else item}:{TAG}"}
        for item in group
    }
    override = ROOT / f"compose.{service}.{'rollback' if rollback else 'release'}.json"
    override.write_text(json.dumps({"services": overrides}), encoding="utf-8")
    for file in [*files, str(override)]:
        args += ["-f", file]
    subprocess.run(args + ["config", "--services"], check=True)
    subprocess.run(args + ["up", "-d", "--no-build", "--no-deps", *group], check=True)
    return group


def healthy(services):
    for _ in range(36):
        states = [inspect(service)["State"] for service in services]
        if all(state["Running"] and state.get("Health", {}).get("Status", "healthy")
               == "healthy" for state in states):
            return
        time.sleep(5)
    raise RuntimeError(f"Health check failed: {services}")


def deploy():
    """发现基线漂移或活动任务时拒绝切换；失败只回滚已触及的服务。"""
    baseline = json.loads((ROOT / "baseline.json").read_text())
    idle()
    for service in SERVICES:
        if inspect(service)["Image"] != baseline[service]["image_id"]:
            raise RuntimeError(f"Live image changed: {service}")
    touched = []
    try:
        for service in (item for item in SERVICES if item != "research-worker"):
            touched.append(service)
            healthy(compose(service, baseline))
    except Exception:
        for service in reversed(touched):
            healthy(compose(service, baseline, rollback=True))
        raise
    print(f"Release healthy: {SERVICES}; backend unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("snapshot", "deploy"))
    parser.add_argument("--tag", choices=(TAG, f"{TAG}-r2"), default=TAG)
    parser.add_argument("--research-only", action="store_true")
    options = parser.parse_args()
    TAG = options.tag
    ROOT = BASE / "releases" / TAG
    if options.research_only:
        SERVICES = ("research-api", "research-worker")
    {"snapshot": snapshot, "deploy": deploy}[options.operation]()
