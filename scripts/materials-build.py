"""准备隔离候选镜像，保留线上镜像以便回退。"""

from pathlib import Path
import shutil
import subprocess

ROOT = Path("/opt/novel-writer/releases/materials-20260922")
SOURCE = ROOT / "source"


def prepare():
    """只覆盖清单文件，三个存在无关差异的文件使用已审核线上补丁。"""
    for name in (SOURCE / "scripts/materials-release-manifest.txt").read_text().splitlines():
        if name.startswith("writter_front/"):
            continue
        target = ROOT / name.replace("writter_back/", "backend/", 1)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / name, target)
    for name in ("api/main.py", "application/orchestrator.py", "application/prompts/genre_strategy.py"):
        shutil.copy2(SOURCE / "overlay" / name, ROOT / "backend" / name)
    shutil.copytree(SOURCE / "writter_back/tests", ROOT / "backend/tests", dirs_exist_ok=True)
    shutil.copytree(SOURCE / "research_service/tests", ROOT / "research_service/tests", dirs_exist_ok=True)


if __name__ == "__main__":
    prepare()
