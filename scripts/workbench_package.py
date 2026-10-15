"""Package and upload an immutable current-workspace release using verified SSH."""

import argparse
import base64
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".release/workbench-production-20261014"
REMOTE = "/opt/novel-writer/releases/workbench-production-20261014"
SSH = ["-i", str(Path.home() / ".ssh/id_ed25519_tencent_leetionm"),
       "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def remote(code):
    encoded = base64.b64encode(code.encode()).decode()
    subprocess.run(["ssh", *SSH, "ubuntu@124.220.67.163",
                    f"echo {encoded} | base64 -d | sudo -n python3 -"], check=True)


def package():
    spec = importlib.util.spec_from_file_location("packager", ROOT / "scripts/production_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTPUT = OUTPUT
    sys.argv = [sys.argv[0]]
    module.main()
    archive = OUTPUT / "current-source.tar.gz"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    temporary = f"/tmp/workbench-{digest}.tar.gz"
    subprocess.run(["scp", *SSH, str(archive), "ubuntu@124.220.67.163:" + temporary], check=True)
    remote(f"""import hashlib, json, tarfile
from pathlib import Path
root=Path({REMOTE!r})
assert root.parent==Path('/opt/novel-writer/releases') and not root.is_symlink()
root.mkdir(mode=0o700,exist_ok=True)
(root/'evidence').mkdir(mode=0o700,exist_ok=True)
archive=Path({temporary!r})
assert hashlib.sha256(archive.read_bytes()).hexdigest()=={digest!r}
source=root/('source-'+{digest!r})
source.mkdir(mode=0o700,exist_ok=True)
with tarfile.open(archive) as bundle:
 for member in bundle.getmembers():
  assert member.isfile() and (source/member.name).resolve().is_relative_to(source.resolve())
 bundle.extractall(source)
manifest=json.loads((source/'source-manifest.json').read_text())
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in manifest.items())
assert not (root/'qa-images.json').exists(),'Do not replace a qualified release source'
(root/'source-path.txt').write_text(str(source))
(root/'source-sha256.txt').write_text({digest!r})
previous=Path('/opt/novel-writer/releases/reader-first-20261013/source-path.txt').read_text().strip()
prior=json.loads((Path(previous)/'source-manifest.json').read_text())
changed=[name for name in manifest if name.startswith(('writter_back/','writter_front/')) and '/dist/' not in name and manifest[name]!=prior.get(name)]
removed=[name for name in prior if name.startswith(('writter_back/','writter_front/')) and '/dist/' not in name and name not in manifest]
comparison={{'changed_runtime_files':changed,'removed_runtime_files':removed,'source_sha256':{digest!r}}}
(root/'evidence/source-comparison.json').write_text(json.dumps(comparison,indent=2))
print(json.dumps({{'files':len(manifest),'source_sha256':{digest!r},**comparison}}))
""")


def action(name):
    remote(f"""import subprocess
from pathlib import Path
root=Path({REMOTE!r})
source=Path((root/'source-path.txt').read_text().strip())
assert source.resolve().is_relative_to(root.resolve())
subprocess.run(['python3',str(source/'scripts/workbench_release.py'),{name!r}],check=True)
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["package", "qa", "regression", "prepare", "backup",
                                           "rehearse", "deploy", "verify", "rollback", "smoke",
                                           "observe", "audit"])
    name = parser.parse_args().action
    if name == "package":
        package()
    else:
        action(name)
