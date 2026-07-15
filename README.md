# 墨间 Novel Writer

支持公开注册和租户数据隔离的 AI 小说创作工作台。系统使用 React + FastAPI + LangGraph，把选题、总纲、章节生成、质量审读、修订和长期记忆组织为一个可恢复工作流。

## 主要能力

- 编辑部式书架、创建向导和统一三栏创作工作台
- DeepSeek、OpenAI、Anthropic 三种模型适配器
- 正文与修订内容通过 SSE 实时输出，包含路由理由、质量评分和进度
- 手动审阅与自动创作两种模式，支持取消和 checkpoint 恢复
- PostgreSQL 章节、进度与记忆一致性存储
- Alembic 非破坏基线、Docker Compose 一键启动
- 邮箱密码登录、多租户切换、成员角色和平台管理
- 每租户按月计量的大纲与章节生成额度

## Docker 启动

1. 从根目录的 `.env.example` 创建 `.env`。
2. 修改 `POSTGRES_PASSWORD` 和 `JWT_SECRET`，并填写所选模型对应的 API Key。
3. 启动服务：

```powershell
docker compose up --build
```

访问 `http://localhost:5173`。后端接口文档位于 `http://localhost:8000/docs`。

Compose 固定一个后端 worker。同一租户内的同一本小说同一时间只允许一个生成任务。

首次部署可临时设置 `PLATFORM_ADMIN_EMAIL` 和 `PLATFORM_ADMIN_PASSWORD`，迁移后执行：

```bash
docker compose exec backend uv run --no-sync python -m scripts.bootstrap_admin
```

引导完成后应从 `.env` 清除平台管理员明文密码并重建后端容器。

生产服务器使用 `docker-compose.prod.yml` 覆盖端口并接入现有反向代理网络：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

## 本地开发

后端：

```powershell
cd writter_back
Copy-Item .env.example .env
uv sync --frozen --all-groups
uv run alembic upgrade head
uv run uvicorn api.main:app --reload
```

前端：

```powershell
cd writter_front
npm ci
npm run dev
```

前端开发服务器会把 `/api` 代理到 `http://localhost:8000`。

## 验证

```powershell
cd writter_front
npm run lint
npm run test
npm run build

cd ../writter_back
uv run ruff check .
uv run mypy
uv run pytest tests/test_streaming_contracts.py -q
```

数据库集成测试需要通过 `TEST_DATABASE_URL` 指向独立测试数据库，测试会清理其中的全部测试表。

## 认证与租户上下文

注册入口为 `POST /api/v1/auth/register`。除注册、登录、刷新和邀请接受外，业务 API 必须携带：

```http
Authorization: Bearer <access-token>
X-Tenant-ID: <tenant-uuid>
```

服务端根据成员关系验证租户身份；前端传入的小说或工作流 UUID 不能跨租户访问。Access Token 有效期 15 分钟，Refresh Token 有效期 30 天并在刷新时轮换。

## SSE 事件协议

统一入口为 `POST /api/v1/workflows/{thread_id}/stream`。事件包结构为：

```json
{
  "id": 12,
  "type": "content_delta",
  "thread_id": "...",
  "node": "chapter_writer_node",
  "data": {
    "chapter_index": 0,
    "operation": "append",
    "text": "正文片段"
  },
  "timestamp": "2026-07-15T00:00:00Z"
}
```

事件类型包括 `status`、`reasoning`、`content_delta`、`quality`、`interrupt`、`progress`、`completed`、`heartbeat` 和 `error`。服务端不会在节点切换时重复发送完整正文或记忆上下文。

## 安全说明

- 仓库不包含数据库口令或模型 API Key，所有凭据只从 `.env` 读取。
- 曾经提交到仓库的 Key 应视为已泄漏，必须在供应商控制台撤销并重新生成。
- JWT Secret 不提供生产默认值，Refresh Token 在数据库中只保存 SHA-256 哈希。
- 密码使用 Argon2id；邀请链接一次性使用并在 7 天后过期。
- 不建议将后端端口直接暴露到公网。
