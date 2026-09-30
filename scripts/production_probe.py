"""只读发布基线检查；输出配置白名单，不输出凭证或正文。"""

import hashlib
import json
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True)


def query(sql):
    return run("docker", "exec", "novel-writer-database", "psql",
               "-U", "novel_writer", "-d", "novel_writer", "-Atc", sql).strip()


def main():
    containers = json.loads(run("docker", "inspect", "novel-writer-backend",
                               "novel-writer-frontend"))
    keys = {"DEFAULT_LLM_PROVIDER", "DEFAULT_MODEL_NAME", "LLM_TIMEOUT_SECONDS",
            "WORKFLOW_NODE_TIMEOUT_SECONDS", "NOVEL_PLANNING_V1_ENABLED",
            "AUTONOMOUS_AUTHOR_ENABLED", "WORKFLOW_REVIEW_V3_ENABLED",
            "WORKFLOW_IDEMPOTENCY_REQUIRED", "WORKFLOW_AUTO_RETRY_ENABLED"}
    for item in containers:
        env = dict(value.split("=", 1) for value in item["Config"]["Env"] if "=" in value)
        print(json.dumps({"container": item["Name"], "image": item["Config"]["Image"],
                          "config": {k: v for k, v in env.items() if k in keys},
                          "providers_configured": [k for k in env if k.endswith("API_KEY") and env[k]]}))
        print("health", item["Name"], item["State"].get("Health", {}).get("Status"))
    for name in ("uv.lock", "pyproject.toml"):
        text = run("docker", "exec", "novel-writer-backend", "cat", f"/app/{name}")
        print(name, hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest())
    tables = query("select tablename from pg_tables where schemaname='public' "
                   "and tablename like 'workflow%'")
    print("workflow_tables", tables)
    print("novels_by_status", query("select status,count(*) from novels group by status"))
    print("tenant_count", query("select count(*) from tenants"))
    print("migration", query("select version_num from alembic_version"))
    print("active_leases", query("select count(*) from workflow_leases "
                                "where expires_at > now()"))
    print("run_status_counts", query("select status,count(*) from workflow_runs group by status"))
    print("qa_runs", query("select status,finished_at from workflow_runs where "
                          "novel_id='44dbea4c-982b-445b-b527-cb598441f75a' "
                          "order by created_at desc limit 2"))
    print("qa_chapters", query("select chapter_index,status,word_count,version from chapters "
                              "where novel_id='44dbea4c-982b-445b-b527-cb598441f75a'"))


if __name__ == "__main__":
    main()
