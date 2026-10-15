"""Package current source changes without credentials or installed dependencies."""

import hashlib
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".release" / "production-20261001"
TEXT = {".py", ".txt", ".toml", ".sh", ".ini", ".conf", ".ts", ".tsx", ".json", ".yml", ".yaml"}


def main():
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", "writter_back", "writter_front", "research_service", "scripts",
         "docker-compose.yml", "docker-compose.prod.yml", "docker-compose.research.yml"],
        cwd=ROOT,
    ).decode().split("\0")
    names.extend(path.relative_to(ROOT).as_posix() for path in (ROOT / "writter_front/dist").rglob("*")
                 if path.is_file())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "current-source.tar.gz"
    manifest = {}
    with tarfile.open(target, "w:gz") as archive:
        for name in sorted(set(names) - {""}):
            path = ROOT / name
            if not path.is_file() or path.is_symlink() or path.name.startswith(".env"):
                continue
            content = path.read_bytes()
            if path.suffix in TEXT:
                content = content.replace(b"\r\n", b"\n")
            manifest[name] = hashlib.sha256(content).hexdigest()
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = int(time.time())
            info.mode = 0o755 if path.suffix == ".sh" else 0o644
            archive.addfile(info, io.BytesIO(content))
        content = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("source-manifest.json")
        info.size = len(content)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(content))
    print(json.dumps({"path": str(target), "files": len(manifest),
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}))
    immutable = OUTPUT / f"source-{hashlib.sha256(target.read_bytes()).hexdigest()}.tar.gz"
    if not immutable.exists():
        shutil.copyfile(target, immutable)
    if "--upload" in sys.argv:
        upload(target)


def upload(target):
    key = str(Path.home() / ".ssh/id_ed25519_tencent_leetionm")
    options = ["-i", key, "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    root = "/opt/novel-writer/releases/production-20261001"
    subprocess.run(["scp", *options, str(target),
                    "ubuntu@124.220.67.163:" + root + "/current-source.tar.gz"], check=True)
    payload = f"""import hashlib, json, tarfile, shutil
from pathlib import Path
root = Path({root!r})
archive = root / 'current-source.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == {hashlib.sha256(target.read_bytes()).hexdigest()!r}
immutable = root / ('source-' + {hashlib.sha256(target.read_bytes()).hexdigest()!r} + '.tar.gz')
if not immutable.exists():
    shutil.copyfile(archive, immutable)
with tarfile.open(archive) as source:
    for item in source.getmembers():
        assert item.isfile() and (root/'source'/item.name).resolve().is_relative_to((root/'source').resolve())
    source.extractall(root/'source')
manifest=json.loads((root/'source/source-manifest.json').read_text())
for name, digest in manifest.items():
    assert hashlib.sha256((root/'source'/name).read_bytes()).hexdigest() == digest, name
print('verified_source_files', len(manifest))
"""
    encoded = base64.b64encode(payload.encode()).decode()
    subprocess.run(["ssh", *options, "ubuntu@124.220.67.163",
                    f"echo {encoded} | base64 -d | sudo -n python3 -"], check=True)


if __name__ == "__main__":
    main()
