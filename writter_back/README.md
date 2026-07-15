# Novel Writer Backend

FastAPI + LangGraph 后端。应用生命周期内复用数据库连接池、仓储、记忆服务和工作流编排器。

## 开发

```powershell
Copy-Item .env.example .env
uv sync --frozen --all-groups
uv run alembic upgrade head
uv run uvicorn api.main:app --reload
```

健康检查：`/health/live` 和 `/health/ready`。

## 测试

不依赖数据库的认证与流式契约测试：

```powershell
uv run pytest tests/test_streaming_contracts.py tests/test_auth_service.py -q
```

CRUD 集成测试需要设置 `TEST_DATABASE_URL`。该地址必须指向可清理的独立测试数据库。

## 配置

以 `.env.example` 为模板。生产环境必须提供至少 32 字符的 `JWT_SECRET`。`DEFAULT_LLM_PROVIDER` 可选 `deepseek`、`openai`、`anthropic`，并提供对应 Key。业务接口统一使用 Bearer Token 与 `X-Tenant-ID`，Repository 不提供无租户查询入口。
