"""无活动写作时切换续写兼容补丁，失败回退到切换前镜像。"""

import json
import runpy
import subprocess


def main():
    """只发布后端，保留当前素材服务与前端以及原有 Compose 配置。"""
    count = subprocess.check_output([
        "docker", "exec", "novel-writer-database", "psql", "-U", "novel_writer",
        "-d", "novel_writer", "-At", "-c",
        "SELECT count(*) FROM workflow_leases WHERE expires_at > now()",
    ], text=True).strip()
    if count != "0":
        raise RuntimeError("active writing prevents backend restart")
    current = json.loads(subprocess.check_output([
        "docker", "inspect", "novel-writer-backend",
    ]))[0]["Config"]["Image"]
    deploy = runpy.run_path("/tmp/materials-deploy.py")["deploy_group"]
    try:
        deploy("backend", ["backend"], "novel-writer-backend:materials-20260922-r2")
    except Exception:
        deploy("backend", ["backend"], current)
        raise
    print("backend_materials_r2_healthy")


if __name__ == "__main__":
    main()
