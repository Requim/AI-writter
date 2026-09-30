"""只读发布预检和数据库备份，不输出凭据。"""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path("/opt/novel-writer/releases/materials-20260922")


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def sql(database, statement):
    return output("docker", "exec", "novel-writer-database", "psql",
                  "-U", "novel_writer", "-d", database, "-At", "-c", statement)


def main():
    """记录容器与数据库安全基线并创建只读逻辑备份。"""
    names = ("backend", "frontend", "research-api", "research-worker")
    records = {}
    for name in names:
        row = json.loads(output("docker", "inspect", f"novel-writer-{name}"))[0]
        records[name] = {key: row[key] for key in ("Id", "Mounts", "NetworkSettings")}
        records[name]["image"] = row["Config"]["Image"]
        records[name]["labels"] = row["Config"]["Labels"]
    (ROOT / "deployment-baseline.json").write_text(json.dumps(records, indent=2))
    print("leases", sql("novel_writer",
          "SELECT count(*) FROM workflow_leases WHERE expires_at > now()"))
    print("jobs", sql("novel_research",
          "SELECT status,count(*) FROM research_jobs GROUP BY status"))
    print("materials", sql("novel_research",
          "SELECT project_genre,status,max(version),max((package_json->>'sample_count')::int) "
          "FROM genre_knowledge_versions GROUP BY project_genre,status"))
    for database in ("novel_writer", "novel_research"):
        path = ROOT / f"{database}-before.dump"
        if not path.exists():
            with path.open("wb") as stream:
                subprocess.run(["docker", "exec", "novel-writer-database", "pg_dump",
                                "-U", "novel_writer", "-Fc", database], stdout=stream, check=True)
        print("backup", database, path.stat().st_size,
              hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
