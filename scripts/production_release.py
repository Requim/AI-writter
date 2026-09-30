"""服务器端受限发布：备份、保留 Compose 覆盖层、健康失败回滚镜像。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

BASE = Path("/opt/novel-writer")
RELEASE = BASE / "releases" / "workbench-20260910"
BACKUP = BASE / "backups" / "workbench-20260910.dump"
TAG = "workbench-20260910"


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def inspect(name):
    return json.loads(run("docker", "inspect", name))[0]


def active_leases():
    return int(run("docker", "exec", "novel-writer-database", "psql", "-U",
                   "novel_writer", "-d", "novel_writer", "-Atc",
                   "select count(*) from workflow_leases where expires_at > now()"))


def compose(files):
    args = ["docker", "compose", "--project-name", "novel-writer",
            "--project-directory", str(BASE), "--env-file", str(BASE / ".env")]
    for name in files:
        args.extend(["-f", name])
    return args


def backup():
    BACKUP.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with BACKUP.open("xb") as target:
        subprocess.run(["docker", "exec", "novel-writer-database", "pg_dump",
                        "-U", "novel_writer", "-d", "novel_writer", "-Fc"],
                       stdout=target, check=True)
    BACKUP.chmod(0o600)
    with BACKUP.open("rb") as source:
        listing = subprocess.check_output(
            ["docker", "exec", "-i", "novel-writer-database", "pg_restore", "--list"],
            stdin=source)
    if b"TABLE DATA" not in listing:
        raise RuntimeError("Backup has no table data")
    digest = hashlib.sha256(BACKUP.read_bytes()).hexdigest()
    (RELEASE / "backup.sha256").write_text(f"{digest}  {BACKUP}\n")
    print("backup_verified", digest, flush=True)


def prepare():
    if active_leases():
        raise RuntimeError("Active workflow leases; do not deploy")
    previous = inspect("novel-writer-backend")
    files = previous["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
    baseline = {"files": files, "backend": previous["Config"]["Image"],
                "frontend": inspect("novel-writer-frontend")["Config"]["Image"]}
    (RELEASE / "baseline.json").write_text(json.dumps(baseline, indent=2))
    backup()
    for service in ("backend", "frontend"):
        parent = baseline[service]
        copy = ("COPY backend/ /app/\nRUN chmod +x /app/docker-entrypoint.sh\n"
                if service == "backend" else
                "COPY frontend/dist/ /usr/share/nginx/html/\n"
                "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf\n")
        dockerfile = RELEASE / f"Dockerfile.{service}"
        dockerfile.write_text(f"FROM {parent}\n{copy}")
        subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                        f"novel-writer-{service}:{TAG}", str(RELEASE)], check=True)
    override = {"services": {
        "backend": {"image": f"novel-writer-backend:{TAG}",
                    "environment": {"AUTONOMOUS_AUTHOR_ENABLED": "false"}},
        "frontend": {"image": f"novel-writer-frontend:{TAG}"}}}
    (RELEASE / "compose.release.json").write_text(json.dumps(override, indent=2))
    print("prepared", TAG, flush=True)


def healthy():
    for name in ("novel-writer-backend", "novel-writer-frontend"):
        state = inspect(name)["State"]
        if not state["Running"] or state.get("Health", {}).get("Status") != "healthy":
            return False
    return True


def deploy():
    if active_leases():
        raise RuntimeError("Active workflow leases; do not deploy")
    baseline = json.loads((RELEASE / "baseline.json").read_text())
    files = baseline["files"] + [str(RELEASE / "compose.release.json")]
    try:
        subprocess.run(compose(files) + ["up", "-d", "--no-deps", "--no-build",
                                         "backend", "frontend"], check=True)
        for _ in range(36):
            if healthy():
                print("release_healthy", TAG, flush=True)
                return
            time.sleep(5)
        raise RuntimeError("Release health timeout")
    except Exception:
        subprocess.run(compose(baseline["files"]) + ["up", "-d", "--no-deps",
                       "--no-build", "backend", "frontend"], check=True)
        print("images_rolled_back; database_not_downgraded", flush=True)
        raise


def frontend_cache():
    """只替换前端缓存配置，不重启正在写作的后端。"""
    dockerfile = RELEASE / "Dockerfile.frontend-cache"
    dockerfile.write_text(f"FROM novel-writer-frontend:{TAG}\n"
                         "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf\n"
                         "RUN touch /usr/share/nginx/html/index.html\n")
    image = f"novel-writer-frontend:{TAG}-cache"
    subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                    image, str(RELEASE)], check=True)
    subprocess.run(["docker", "run", "--rm", "--network", "novel-writer_default",
                    image, "nginx", "-t"], check=True)
    current = inspect("novel-writer-frontend")
    files = current["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
    override = RELEASE / "compose.cache.json"
    override.write_text(json.dumps({"services": {"frontend": {"image": image}}}))
    subprocess.run(compose(files + [str(override)]) + [
        "up", "-d", "--no-deps", "--no-build", "frontend"], check=True)
    print("frontend_cache_updated", flush=True)


def strategy_fix():
    """在审阅边界更新策略输入，健康失败时还原原 Compose 链。"""
    if active_leases():
        raise RuntimeError("Active workflow leases; do not deploy")
    dockerfile = RELEASE / "Dockerfile.strategy"
    paths = ("application/agents/genre_strategy_node.py",
             "application/prompts/genre_strategy_prompts.py",
             "application/prompts/templates/genre_strategy/generate.txt")
    dockerfile.write_text(f"FROM novel-writer-backend:{TAG}\n" + "".join(
        f"COPY backend/{path} /app/{path}\n" for path in paths))
    image = f"novel-writer-backend:{TAG}-strategy"
    subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                    image, str(RELEASE)], check=True)
    current = inspect("novel-writer-frontend")
    files = current["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
    override = RELEASE / "compose.strategy.json"
    override.write_text(json.dumps({"services": {"backend": {"image": image}}}))
    subprocess.run(compose(files + [str(override)]) + [
        "up", "-d", "--no-deps", "--no-build", "backend"], check=True)
    for _ in range(36):
        if healthy():
            print("strategy_fix_healthy", flush=True)
            return
        time.sleep(5)
    subprocess.run(compose(files) + ["up", "-d", "--no-deps",
                   "--no-build", "backend"], check=True)
    raise RuntimeError("Strategy fix rolled back")


def frontend_layout(suffix="layout"):
    """发布经浏览器复测的空状态布局，保留后端热修复覆盖层。"""
    dockerfile = RELEASE / "Dockerfile.layout"
    parent = inspect("novel-writer-frontend")["Config"]["Image"]
    dockerfile.write_text(f"FROM {parent}\n"
                         "COPY frontend/dist/ /usr/share/nginx/html/\n"
                         "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf\n")
    image = f"novel-writer-frontend:{TAG}-{suffix}"
    subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                    image, str(RELEASE)], check=True)
    files = []
    for service in ("novel-writer-backend", "novel-writer-frontend"):
        current = inspect(service)
        chain = current["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
        files.extend(name for name in chain if name not in files)
    override = RELEASE / f"compose.{suffix}.json"
    override.write_text(json.dumps({"services": {"frontend": {"image": image}}}))
    subprocess.run(compose(files + [str(override)]) + [
        "up", "-d", "--no-deps", "--no-build", "frontend"], check=True)
    for _ in range(24):
        if healthy():
            print("frontend_updated", suffix, flush=True)
            return
        time.sleep(5)
    subprocess.run(compose(files) + ["up", "-d", "--no-deps",
                   "--no-build", "frontend"], check=True)
    raise RuntimeError("Frontend update rolled back")


def qa_cleanup():
    """只删除本次明确标记、没有生产数据的临时数据库容器及其匿名卷。"""
    name = "novel-writer-qa-db-20260910"
    container = inspect(name)
    if container["Config"]["Labels"].get("purpose") != "novel-writer-release-qa":
        raise RuntimeError("QA label mismatch")
    subprocess.run(["docker", "rm", "-fv", name], check=True)


def plan_fix(suffix="plan-fix", paths=(
    "application/agents/novel_plan_node.py", "application/orchestrator.py",
    "service/value_objects/novel_plan.py",
)):
    """在无活动租约时发布规划校验修复，保留当前前端及全部覆盖层。"""
    if active_leases():
        raise RuntimeError("Active workflow leases; do not deploy")
    parent = inspect("novel-writer-backend")["Config"]["Image"]
    dockerfile = RELEASE / f"Dockerfile.{suffix}"
    dockerfile.write_text(f"FROM {parent}\n" + "".join(
        f"COPY backend/{path} /app/{path}\n" for path in paths))
    image = f"novel-writer-backend:{TAG}-{suffix}"
    subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                    image, str(RELEASE)], check=True)
    files = inspect("novel-writer-backend")["Config"]["Labels"][
        "com.docker.compose.project.config_files"].split(",")
    override = RELEASE / f"compose.{suffix}.json"
    override.write_text(json.dumps({"services": {"backend": {"image": image}}}))
    subprocess.run(compose(files + [str(override)]) + [
        "up", "-d", "--no-deps", "--no-build", "backend"], check=True)
    for _ in range(36):
        if healthy():
            print("backend_fix_healthy", suffix, flush=True)
            return
        time.sleep(5)
    subprocess.run(compose(files) + ["up", "-d", "--no-deps",
                   "--no-build", "backend"], check=True)
    raise RuntimeError("Plan fix rolled back")


if __name__ == "__main__":
    {"prepare": prepare, "deploy": deploy, "frontend-cache": frontend_cache,
     "strategy-fix": strategy_fix, "frontend-layout": frontend_layout,
     "frontend-reliability": lambda: frontend_layout("reliability"),
     "frontend-draft": lambda: frontend_layout("draft-recovery"),
     "qa-cleanup": qa_cleanup, "plan-fix": plan_fix,
     "fact-baseline": lambda: plan_fix("fact-baseline", ("application/fact_evaluation.py",))}[sys.argv[1]]()
