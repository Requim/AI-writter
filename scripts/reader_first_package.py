"""Create an immutable isolated QA bundle while preserving prior release files."""

import base64
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/opt/novel-writer/releases/reader-first-20261013"
SSH = ["-i", str(Path.home() / ".ssh/id_ed25519_tencent_leetionm"),
       "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def remote_python(code):
    encoded = base64.b64encode(code.encode()).decode()
    subprocess.run(["ssh", *SSH, "ubuntu@124.220.67.163",
                    f"echo {encoded} | base64 -d | sudo -n python3 -"], check=True)


def main():
    spec = importlib.util.spec_from_file_location("packager", ROOT / "scripts/production_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTPUT = ROOT / ".release/reader-first-20261013"
    sys.argv = [sys.argv[0]]
    module.main()
    archive = module.OUTPUT / "current-source.tar.gz"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    temporary = f"/tmp/reader-first-{digest}.tar.gz"
    subprocess.run(["scp", *SSH, str(archive), "ubuntu@124.220.67.163:" + temporary], check=True)
    remote_python(f"""import hashlib, json, tarfile
from pathlib import Path
root = Path({REMOTE!r})
assert root.parent == Path('/opt/novel-writer/releases') and not root.is_symlink()
root.mkdir(exist_ok=True)
(root/'evidence').mkdir(exist_ok=True)
archive=Path({temporary!r})
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={digest!r}
source=root/('source-'+{digest!r})
source.mkdir(exist_ok=True)
with tarfile.open(archive) as bundle:
    for member in bundle.getmembers():
        assert member.isfile() and (source/member.name).resolve().is_relative_to(source.resolve())
    bundle.extractall(source)
manifest=json.loads((source/'source-manifest.json').read_text())
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in manifest.items())
(root/'source-path.txt').write_text(str(source))
(root/'source-sha256.txt').write_text({digest!r})
print(json.dumps({{'source':str(source),'files':len(manifest),'sha256':{digest!r}}}))
""")


if __name__ == "__main__":
    main()
