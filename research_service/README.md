# Novel Research Service

独立的笔趣阁结构化采集、按项目题材累积知识包和关键词检索服务。

## 运行

```powershell
$env:PYTHONPATH = (Get-Location).Path
writter_back\.venv\Scripts\python.exe -m uvicorn research_service.api:app --port 8010
```

Worker 使用同一项目环境启动：

```powershell
writter_back\.venv\Scripts\python.exe -m research_service.worker
```

没有配置 `RESEARCH_DATABASE_URL` 时，API 使用内存仓储，只适合测试。生产环境必须配置独立的 `novel_research` 数据库，并先执行 Alembic 迁移。

迁移命令示例：

```powershell
$env:RESEARCH_DATABASE_URL = "postgresql+asyncpg://novel_writer:<password>@localhost:5432/novel_research"
writter_back\.venv\Scripts\alembic.exe -c research_service\alembic.ini upgrade head
```

## 边界

- 主知识对象是按 `project_genre` 聚合的类型知识包，不是单本小说卡片。
- 单本样本只用于去重、统计和证据追溯。
- v1 只使用关键词检索和 `pg_trgm`，不启用向量或 embedding。
- 详情简介在模型处理后不进入研究样本；完整首章只在明确授权时临时驻留内存。
