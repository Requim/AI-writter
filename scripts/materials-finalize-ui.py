"""仅更新素材汇总和进度文案，不重启正在生成作品的写作后端。"""

import runpy
import subprocess


def main():
    """确认没有采集任务后发布已测试的素材服务与前端。"""
    count = subprocess.check_output([
        "docker", "exec", "novel-writer-database", "psql", "-U", "novel_writer",
        "-d", "novel_research", "-At", "-c",
        "SELECT count(*) FROM research_jobs WHERE status IN ('queued','running')",
    ], text=True).strip()
    if count != "0":
        raise RuntimeError("active collection prevents research restart")
    deploy = runpy.run_path("/tmp/materials-deploy.py")["deploy_group"]
    deploy("research-api", ["research-api", "research-worker"],
           "novel-writer-research:materials-20260922", True)
    deploy("frontend", ["frontend"], "novel-writer-frontend:materials-20260922-r2")


if __name__ == "__main__":
    main()
