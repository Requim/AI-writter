"""目标契约发布白名单与服务端发布入口，不包含凭证。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import production_release as release
from package_production import add_bytes, sources

TAG = "goals-20260910-v1"
BACKEND = (
    "application/goal_contract.py",
    "application/agents/chapter_outline_node.py",
    "application/agents/chapter_writer_node.py",
    "application/agents/reflection_node.py",
    "application/agents/revision_node.py",
    "application/agents/persist_node.py",
    "application/prompts/reflection_prompts.py",
    "application/prompts/chapter_writer_prompts.py",
    "application/scene_queue.py",
)


def package():
    """仅打包已验证的目标契约源码、前端产物和逐文件校验清单。"""
    root = Path(__file__).resolve().parents[1]
    target = root / ".release" / "20260910" / f"{TAG}.tar.gz"
    manifest = {}
    with tarfile.open(target, "x:gz") as archive:
        for path, name in sources():
            if not name.startswith("frontend/") and name not in {"backend/" + p for p in BACKEND}:
                continue
            data = path.read_bytes()
            if name.endswith((".py", ".conf")):
                data = data.replace(b"\r\n", b"\n")
            manifest[name] = hashlib.sha256(data).hexdigest()
            add_bytes(archive, name, data)
        add_bytes(archive, "manifest.json", json.dumps(manifest, indent=2).encode())
    print(json.dumps({"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "backend_files": len(BACKEND), "files": len(manifest)}))


def baseline():
    """保存实际运行镜像与配置链，回滚不依赖 Git 工作区。"""
    files, services, runtime = [], {}, {}
    for name in ("backend", "frontend"):
        container = release.inspect(f"novel-writer-{name}")
        chain = container["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
        files.extend(path for path in chain if path not in files)
        services[name] = {"image": container["Config"]["Image"]}
        runtime[name] = {"mounts": container["Mounts"], "ports": container["NetworkSettings"]["Ports"]}
    override = release.RELEASE / "compose.baseline.json"
    override.write_text(json.dumps({"services": services}))
    files.append(str(override))
    (release.RELEASE / "baseline.json").write_text(json.dumps({"files": files, "services": services, "runtime": runtime}, indent=2))
    return files, services


def prepare():
    """校验包与依赖，备份后构建，不切换运行服务。"""
    if release.active_leases():
        raise RuntimeError("Active leases; preparation stopped")
    if (release.RELEASE / "baseline.json").exists():
        raise RuntimeError("Release already prepared; use a new release tag")
    manifest = json.loads((release.RELEASE / "manifest.json").read_text())
    for path, digest in manifest.items():
        if hashlib.sha256((release.RELEASE / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Manifest mismatch: {path}")
    _, services = baseline()
    release.backup()
    for name in ("backend", "frontend"):
        body = "".join(f"COPY backend/{path} /app/{path}\n" for path in BACKEND) if name == "backend" else (
            "COPY frontend/dist/ /usr/share/nginx/html/\nCOPY frontend/nginx.conf /etc/nginx/conf.d/default.conf\n")
        dockerfile = release.RELEASE / f"Dockerfile.{name}"
        dockerfile.write_text(f"FROM {services[name]['image']}\n" + body)
        subprocess.run(["docker", "build", "-f", str(dockerfile), "-t",
                        f"novel-writer-{name}:{TAG}", str(release.RELEASE)], check=True)
    print("prepared", TAG, flush=True)


def deploy():
    """切换前再次检查租约，失败恢复原镜像，不回退数据库。"""
    if release.active_leases():
        raise RuntimeError("Active leases; deployment stopped")
    files = json.loads((release.RELEASE / "baseline.json").read_text())["files"]
    override = release.RELEASE / "compose.goals.json"
    override.write_text(json.dumps({"services": {name: {"image": f"novel-writer-{name}:{TAG}"}
                                                for name in ("backend", "frontend")}}))
    try:
        subprocess.run(release.compose(files + [str(override)]) + [
            "up", "-d", "--no-deps", "--no-build", "backend", "frontend"], check=True)
        for _ in range(36):
            if release.healthy():
                print("goals_release_healthy", flush=True)
                return
            time.sleep(5)
        raise RuntimeError("Health timeout")
    except Exception:
        subprocess.run(release.compose(files) + ["up", "-d", "--no-deps", "--no-build",
                                                "backend", "frontend"], check=True)
        print("rolled_back_to_baseline", flush=True)
        raise


if __name__ == "__main__":
    if sys.argv[1] == "package":
        package()
    else:
        release.RELEASE = Path(__file__).resolve().parent
        release.BACKUP = release.BASE / "backups" / f"{TAG}.dump"
        {"prepare": prepare, "deploy": deploy}[sys.argv[1]]()
