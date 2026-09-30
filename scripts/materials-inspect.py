"""读取生产素材摘要和工作流验收证据，不访问用户凭据。"""

import json
import subprocess


def sql(database, statement):
    result = subprocess.check_output([
        "docker", "exec", "novel-writer-database", "psql", "-U", "novel_writer",
        "-d", database, "-At", "-c", statement,
    ], text=True)
    print(result.strip())


if __name__ == "__main__":
    sql("novel_research", "SELECT package_json FROM genre_knowledge_versions "
        "WHERE project_genre='fantasy' ORDER BY version DESC LIMIT 1")
    sql("novel_research", "SELECT sample_json->'card'->'limitations',"
        "sample_json->'secondary_project_genres' FROM research_samples LIMIT 3")
