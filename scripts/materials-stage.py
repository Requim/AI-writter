"""在服务器提取线上基线并展示本次覆盖范围。"""

import difflib
from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/novel-writer/releases/materials-20260922")
SOURCE = ROOT / "source"


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def main():
    """只读取线上文件，在独立发布目录准备候选文件。"""
    baseline = ROOT / "baseline"
    baseline.mkdir(exist_ok=True)
    for folder in ("application", "api", "infrastructure", "service"):
        run("docker", "cp", f"novel-writer-backend:/app/{folder}", str(baseline / folder))
    frontend = ROOT / "frontend"
    if not frontend.exists():
        shutil.copytree("/opt/novel-writer/releases/research-e2e-20260921/frontend", frontend)
    diffs = []
    for name in (SOURCE / "scripts/materials-release-manifest.txt").read_text().splitlines():
        if name.startswith("writter_back/"):
            old = baseline / name.removeprefix("writter_back/")
        elif name.startswith("writter_front/"):
            old = frontend / name.removeprefix("writter_front/")
        else:
            old = ROOT / "research-baseline" / name
            old.parent.mkdir(parents=True, exist_ok=True)
            run("docker", "cp", f"novel-writer-research-api:/app/{name}", str(old))
        before = old.read_text() if old.exists() else ""
        after = (SOURCE / name).read_text()
        diff = list(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile=f"live/{name}", tofile=name))
        diffs.extend(diff)
        print(name, "changed_lines", sum(line[:1] in ("+", "-") for line in diff))
    (ROOT / "scope.diff").write_text("".join(diffs))


if __name__ == "__main__":
    main()
