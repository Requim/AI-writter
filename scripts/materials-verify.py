"""在服务器用生产依赖验证候选覆盖文件。"""

from pathlib import Path
import subprocess

ROOT = Path("/opt/novel-writer/releases/materials-20260922")


def main():
    """挂载当前候选文件到隔离测试容器，保留线上运行容器不变。"""
    args = ["docker", "run", "--rm"]
    for path in (ROOT / "research_service").rglob("*.py"):
        relative = path.relative_to(ROOT)
        args.extend(["-v", f"{path}:/app/{relative}:ro"])
    args += ["novel-writer-research:materials-tests", "python", "-m", "pytest",
             "/app/research_service/tests", "--ignore=/app/research_service/tests/test_biquge.py", "-q"]
    subprocess.run(args, check=True)
    for kind in ("backend", "research"):
        subprocess.run([
            "docker", "build", "-f", str(ROOT / f"source/scripts/Dockerfile.materials-{kind}"),
            "--target", "production", "-t", f"novel-writer-{kind}:materials-20260922", str(ROOT),
        ], check=True)


if __name__ == "__main__":
    main()
