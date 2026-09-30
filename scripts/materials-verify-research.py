"""只验证素材候选覆盖文件，不构建或重启生产服务。"""

from pathlib import Path
import subprocess


def main():
    """逐文件挂载补丁，保留基线镜像中未变更的模块。"""
    root = Path("/opt/novel-writer/releases/materials-20260922")
    args = ["docker", "run", "--rm"]
    for path in (root / "research_service").rglob("*.py"):
        args += ["-v", f"{path}:/app/{path.relative_to(root)}:ro"]
    args += ["novel-writer-research:materials-tests", "python", "-m", "pytest",
             "/app/research_service/tests",
             "--ignore=/app/research_service/tests/test_biquge.py", "-q"]
    subprocess.run(args, check=True)


if __name__ == "__main__":
    main()
