"""打包白名单源码与前端产物，不包含凭证和开发预览。"""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".release" / "20260910"


def sources():
    backend = ROOT / "writter_back"
    for directory in ("alembic", "api", "application", "infrastructure", "service"):
        for path in sorted((backend / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path, "backend/" + path.relative_to(backend).as_posix()
    for name in ("__init__.py", "config.py", "alembic.ini", "pyproject.toml", "uv.lock", "docker-entrypoint.sh"):
        yield backend / name, "backend/" + name
    frontend = ROOT / "writter_front"
    for path in sorted((frontend / "dist").rglob("*")):
        if path.is_file():
            yield path, "frontend/dist/" + path.relative_to(frontend / "dist").as_posix()
    yield frontend / "nginx.conf", "frontend/nginx.conf"


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o755 if name.endswith(".sh") else 0o644
    archive.addfile(info, io.BytesIO(data))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    target = OUTPUT / "release.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        for path, name in sources():
            data = path.read_bytes()
            if path.suffix in (".py", ".sh", ".toml", ".lock", ".ini", ".txt", ".conf"):
                data = data.replace(b"\r\n", b"\n")
            manifest[name] = hashlib.sha256(data).hexdigest()
            add_bytes(archive, name, data)
        add_bytes(archive, "manifest.json", json.dumps(manifest, indent=2).encode())
    print(json.dumps({"archive": str(target), "files": len(manifest),
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
