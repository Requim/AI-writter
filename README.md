# AI 小说自动创作系统 (NovelWriter)

> 基于 LangGraph + PostgreSQL + FastAPI + Vue 3 构建的具备**长期记忆**、**大纲规划**和**反思修正**能力的 AI Agent 小说创作系统。

---

## 目录

- [系统架构](#系统架构)
- [核心设计](#核心设计)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [输出逻辑链路](#输出逻辑链路)
- [API 接口](#api-接口)
- [LangGraph 工作流](#langgraph-工作流)
- [进度追踪](#进度追踪)
- [集成测试](#集成测试)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端层 (Frontend)                       │
│  writter_front/  (Vue 3 + TypeScript + Element Plus)       │
│  - 小说配置界面    - 进度可视化    - 中断处理UI          │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API / SSE Stream
┌──────────────────────────▼──────────────────────────────────┐
│                   API层 (API Layer)                        │
│  writter_back/api/  (FastAPI + Uvicorn)                   │
│  - Depends注入   - 请求校验   - 路由分发                  │
│  - novel_router (CRUD + 进度)                            │
│  - workflow_router (invoke/stream + SSE)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│               应用层 (Application Layer)                     │
│  writter_back/application/                                │
│  - NovelOrchestrator (持有依赖，驱动工作流)                │
│  - AgentWorkflow (LangGraph 11节点)                       │
│  - NovelAgentState (17字段 TypedDict)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                服务层 (Service Layer)                        │
│  writter_back/service/                                     │
│  - Novel (小说聚合根)  - Chapter (章节实体)                │
│  - ports/ (LLMService, MemoryService, NovelRepository 接口) │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            基础设施层 (Infrastructure Layer)                 │
│  writter_back/infrastructure/                              │
│  - PostgreSQL (NovelRepository, Chapter 仓储实现)          │
│  - LangGraph (PostgresSaver Checkpointer)                  │
│  - LLM Adapters (OpenAI/Anthropic/DeepSeek)              │
│  - VectorStore (pgvector, 长期记忆检索)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 核心设计

### SOLID 原则

| 原则 | 实现方式 |
|------|----------|
| **S** 单一职责 | 每个模块只负责一个功能（类型确认、书名生成、反思检查各为独立节点） |
| **O** 开闭原则 | LangGraph 节点可插拔，新增节点不影响现有流程 |
| **L** 里氏替换 | 所有 LLM 适配器实现同一服务接口，可无缝替换 |
| **I** 接口隔离 | 端口接口粒度精细（LLMService、MemoryService、NovelRepository） |
| **D** 依赖倒置 | 服务层定义接口，基础设施层实现；应用层依赖抽象而非实现 |

### 依赖注入机制

本项目采用 **双轨制依赖注入**：

#### 1. LangGraph Config 注入（Agent 节点用）
```python
# orchestrator.py
def _make_config(self, thread_id):
    return {
        "configurable": {
            "thread_id": thread_id,
            "memory_service": self.memory_service,
            "novel_repository": self.repository,
            "llm_config": self.llm_config,
        }
    }

# agent 节点通过第二个参数接收
async def memory_retrieval_node(state, config):
    memory_service = config["configurable"]["memory_service"]
```

#### 2. FastAPI Depends 注入（API 路由用）
```python
# novel_router.py
def get_repository() -> PostgresNovelRepository:
    return PostgresNovelRepository(settings.DATABASE_URL)

@router.post("")
async def create_novel(repo=Depends(get_repository)):
    ...
```

---

## 输出逻辑链路

```
小说类型（必选，用户输入）
    ↓
书名（用户输入 → AI生成 → 用户确认）
    ↓
简介（用户输入 → AI生成 → 用户确认）
    ↓
总纲领（用户输入 → AI生成 → 用户审阅/修改）
    ↓
┌─────────────── 循环开始 ───────────────┐
│                                            │
│  进度检查：已完成？──是──→ 完结退出      │
│      │ 否                               │
│      ▼                                    │
│  长期记忆检索（MemoryService 查询前文）    │
│      ↓                                    │
│  单章节细纲（用户输入 → AI生成 → 确认） │
│      ↓                                    │
│  章节内容填充（3000-6000字，禁止注水）   │
│      ↓                                    │
│  反思检查（AI自查 → 报告问题给用户）    │
│      │                                    │
│  有问题？──是──► 用户决策修正方式        │
│      │              │                     │
│      │              ├─ 接受（忽略问题）  │
│      │              ├─ AI自动修正        │
│      │              ├─ 按用户指令修正    │
│      │              └─ 重新生成          │
│      ▼                                    │
│  持久化（写DB + 存MemoryService）        │
│      │                                    │
│  更新进度（repository.update）            │
│      │                                    │
└──────┴────────────────────────────────────┘
```

---

## 项目结构

```
NovelWritter/
├── README.md                  # 本文件 - 总架构文档
├── writter_back/             # 后端（FastAPI + LangGraph）
│   ├── pyproject.toml      # uv 项目配置
│   ├── .python-version     # Python 3.11
│   ├── README.md           # 后端详细文档（含API、工作流说明）
│   ├── config.py           # 集中化配置（pydantic-settings）
│   ├── service/           # 服务层
│   │   ├── entities/      # Novel, Chapter 实体
│   │   ├── value_objects/ # NovelType, Outline, Progress
│   │   └── ports/        # LLMService, MemoryService 等接口
│   ├── infrastructure/     # 基础设施层
│   │   ├── database/     # SQLAlchemy 模型 + 仓储实现
│   │   ├── llm/          # OpenAI, DeepSeek, Anthropic 适配器
│   │   └── memory/       # PostgreSQL 长期记忆实现
│   ├── application/        # 应用层
│   │   ├── orchestrator.py # NovelOrchestrator（驱动工作流）
│   │   ├── agents/       # LangGraph 节点（11个节点）
│   │   ├── schemas/      # NovelAgentState 状态定义
│   │   └── workflow_builder.py  # 工作流构建器
│   └── api/              # API层
│       ├── main.py        # FastAPI 入口 + 生命周期
│       └── routers/       # FastAPI 路由（novel, workflow）
└── writter_front/            # 前端（Vue 3 + Vite）
    ├── package.json        # 依赖配置
    ├── vite.config.ts      # Vite 配置（代理 /api）
    ├── tsconfig.json       # TypeScript 配置
    ├── README.md           # 前端详细文档
    └── src/
        ├── api/           # Axios 客户端（novel.ts, client.ts）
        ├── views/         # 页面组件
        │   ├── NovelConfig.vue    # 小说配置（5步向导 + interrupt）
        │   └── NovelProgress.vue  # 进度查看（进度条 + 章节列表）
        ├── router/        # Vue Router
        └── main.ts        # 入口文件
```

---

## 快速开始

### 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.11 | 后端运行环境 |
| Node.js | >= 18 | 前端运行环境 |
| PostgreSQL | >= 16 | 需安装 pgvector 扩展 |
| Redis | >= 6 | 可选，用于 LangGraph Platform |

### 1. 数据库准备

```bash
# 创建数据库
createdb novel_writer

# 启用 pgvector 扩展
psql novel_writer -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. 后端启动

```bash
cd writter_back

# 配置环境变量（创建 .env 文件）
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/novel_writer
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek-chat
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_MODEL=gpt-4o
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
ANTHROPIC_MODEL=claude-sonnet-4-20250514
MIN_CHAPTER_WORDS=3000
MAX_CHAPTER_WORDS=6000
EOF

# 安装依赖并启动
uv sync
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

后端监听 `http://localhost:8000`。

### 3. 前端启动

```bash
cd writter_front
npm install
npm run dev
```

前端监听 `http://localhost:5173`，API 请求通过 Vite 代理转发到后端。

---

## API 接口

### 小说管理

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| POST | `/api/v1/novels` | 创建小说（启动创作流程） | ✅ 已实现 + 测试通过 |
| GET | `/api/v1/novels` | 查询用户所有小说 | ✅ 已实现 + 测试通过 |
| GET | `/api/v1/novels/{id}` | 获取小说详情 | ✅ 已实现 + 测试通过 |
| DELETE | `/api/v1/novels/{id}` | 删除小说 | ⚠️ 路由已定义，待测试 |
| GET | `/api/v1/novels/{id}/progress` | 获取进度 | ✅ 已实现 + 测试通过 |
| GET | `/api/v1/novels/{id}/chapters` | 获取所有章节 | ✅ 已实现 + 测试通过 |
| POST | `/api/v1/novels/{id}/chapters` | 触发下一章生成 | ⚠️ 待测试 |
| GET | `/api/v1/novels/{id}/chapters/{cid}` | 获取章节详情 | ⚠️ 待测试 |
| PUT | `/api/v1/novels/{id}/chapters/{cid}` | 更新章节内容 | ⚠️ 待测试 |

### 工作流控制（支持 interrupt/resume）

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| POST | `/api/v1/workflows/{thread_id}/invoke` | 启动/恢复工作流 | ✅ 已实现 |
| GET | `/api/v1/workflows/{thread_id}/stream` | SSE 流式获取 | ✅ 已实现 |

### Interrupt 响应格式

工作流中断时，API 返回包含 `__interrupt__` 的响应：

```json
{
  "__interrupt__": [
    {
      "value": {
        "action": "require_novel_type",
        "message": "请选择小说类型（必选）",
        "available_types": {"suspense": "悬疑", "sci_fi": "科幻"}
      }
    }
  ]
}
```

恢复工作流：

```bash
POST /api/v1/workflows/{thread_id}/invoke
{
  "command": {"resume": "sci_fi"}
}
```

---

## LangGraph 工作流

### Agent 节点列表（11个）

| 节点 | 职责 | 用户交互 | LLM调用 | 状态 |
|------|------|----------|---------|------|
| `type_confirmation` | 强制用户输入小说类型 | interrupt() 暂停 | 无 | ✅ 完整 |
| `title_node` | 书名生成 | interrupt() 确认 | `generate()` temp=0.9 | ✅ 完整 |
| `summary_node` | 简介生成 | interrupt() 确认 | `generate()` temp=0.8 | ✅ 完整 |
| `outline_node` | 总纲领生成 | interrupt() 审阅 | `structured_generate()` | ✅ 完整 |
| `progress_check_node` | 进度检查 | 自动（完结判断） | 无 | ✅ 完整 |
| `memory_retrieval_node` | 长期记忆检索 | 自动（MemoryService） | 无 | ✅ 已接入 |
| `chapter_outline_node` | 章节细纲生成 | interrupt() 确认 | `structured_generate()` | ✅ 完整 |
| `chapter_writer_node` | 章节内容填充 | 自动（3000-6000字） | `generate()` | ✅ 完整 |
| `reflection_node` | 反思检查 | interrupt() 报告问题 | `structured_generate()` | ✅ 完整 |
| `revision_node` | 修正节点 | interrupt() 4种决策 | `generate()` | ✅ 完整 |
| `persist_node` | 持久化 | 自动（写DB+记忆） | 无 | ✅ 已接入 |

### 字数约束

- **章节细纲**：`estimated_word_count` 必须在 3000-6000 之间
- **章节内容**：`chapter_writer_node` 检查字数，不足则追加，过多则截断
- **反思检查**：`reflection_node` 验证质量评分 >= 0.8

---

## 进度追踪

### 后端进度

- [x] Phase 0: 项目初始化 (uv + pyproject.toml)
- [x] Phase 1: 服务层 (Novel, Chapter, NovelType, Outline, Progress, Ports)
- [x] Phase 2: 基础设施层 (PostgreSQL仓储、LLM适配器、长期记忆)
- [x] Phase 3: 应用层 (11个Agent节点 + workflow_builder)
- [x] Phase 4: API层 (FastAPI路由、interrupt/resume接口) **【已修复存根】**
  - [x] novel_router.py：接入 PostgresNovelRepository
  - [x] workflow_router.py：接入 NovelOrchestrator
  - [x] orchestrator.py：新建，持有所有依赖
- [x] Phase 5: 配置集中化 (config.py + .env)
- [x] Phase 6: 集成测试 **【已完成】**
  - [x] 测试数据库隔离 (novel_writer_test)
  - [x] tests/conftest.py：测试配置 + fixtures
  - [x] tests/test_novel_crud.py：8个测试全部通过
    - [x] test_create_novel
    - [x] test_create_novel_invalid_type
    - [x] test_get_novel
    - [x] test_get_novel_not_found
    - [x] test_list_novels
    - [x] test_get_progress
    - [x] test_list_chapters_empty
    - [x] test_create_novel_with_outline
  - [ ] tests/test_workflow_e2e.py — 待实现（需 mock LLM）
  - [ ] tests/test_agents.py — 待实现
- [ ] Phase 7: Docker Compose 部署配置

### 前端进度

- [x] 基础脚手架 (Vue 3 + TypeScript + Vite)
- [x] API客户端封装 (Axios + TypeScript 类型)
- [x] 小说配置页面 (NovelConfig.vue - 5步向导 + interrupt)
- [x] 进度查看页面 (NovelProgress.vue - 进度条 + 章节列表)
- [x] 工作流中断处理UI (4种 interrupt action 响应)
- [ ] 章节编辑器 (富文本编辑 + 实时预览)
- [ ] 章节查看功能 (NovelProgress.vue viewChapter)
- [ ] 用户认证模块 (JWT + 登录/注册)

---

## 集成测试

### 测试目标

验证以下核心流程端到端可用：

1. **小说创建** → `POST /api/v1/novels` 返回 novel_id + thread_id ✅
2. **工作流启动** → `POST /api/v1/workflows/{thread_id}/invoke` 正确触发 interrupt ⚠️ 待 E2E 测试
3. **Interrupt 恢复** → 依次提供 type → title → summary → outline，工作流推进 ⚠️ 待 E2E 测试
4. **章节生成** → 工作流自动完成记忆检索 → 细纲 → 内容 → 反思 → 持久化 ⚠️ 待 E2E 测试
5. **进度查询** → `GET /api/v1/novels/{id}/progress` 返回正确进度 ✅
6. **章节列表** → `GET /api/v1/novels/{id}/chapters` 返回已生成章节 ✅

### 自动化测试（已完成 ✅）

```
tests/
├── conftest.py          # 测试配置，数据库隔离
├── test_novel_crud.py  # 8个测试全部通过 ✅
│   ├── test_create_novel           ✅
│   ├── test_create_novel_invalid_type ✅
│   ├── test_get_novel              ✅
│   ├── test_get_novel_not_found    ✅
│   ├── test_list_novels            ✅
│   ├── test_get_progress           ✅
│   ├── test_list_chapters_empty    ✅
│   └── test_create_novel_with_outline ✅
└── test_workflow_e2e.py # ⚠️ 尚未实现（需 mock LLM 或真实 API Key）
```

**测试覆盖：**
- ✅ 小说 CRUD（创建/查询/列表/进度/章节列表）
- ⚠️ 工作流 E2E（未实现：需 mock LLMService 或配置真实 API Key）

**测试数据库**：`novel_writer_test`（与生产库 `novel_writer` 隔离）

**运行测试**：
```bash
cd writter_back
$env:DATABASE_URL="postgresql+asyncpg://postgres:mima12138@localhost:5432/novel_writer_test"
uv run pytest tests/ -v
```

### 手动测试步骤

```bash
# 1. 创建小说
curl -X POST http://localhost:8000/api/v1/novels \
  -H "Content-Type: application/json" \
  -d '{"novel_type": "suspense", "title": "测试小说"}'
# 记录返回的 novel_id / thread_id

# 2. 启动工作流（预期：返回 require_novel_type interrupt）
curl -X POST http://localhost:8000/api/v1/workflows/{thread_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": {"novel_id": "{thread_id}", "novel_type": "suspense"}}'

# 3. 恢复工作流（提供书名）
curl -X POST http://localhost:8000/api/v1/workflows/{thread_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{"command": {"resume": "我的悬疑小说"}}'

# 4. 继续恢复（提供简介、大纲...）
# ...

# 5. 查询进度
curl http://localhost:8000/api/v1/novels/{novel_id}/progress

# 6. 查询章节列表
curl http://localhost:8000/api/v1/novels/{novel_id}/chapters
```

### 自动化测试（待实现）

- [ ] `tests/test_novel_crud.py` — 小说 CRUD 测试
- [ ] `tests/test_workflow_e2e.py` — 工作流端到端测试
- [ ] `tests/test_agents.py` — Agent 节点单元测试

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18, TypeScript, Vite, Ant Design, Zustand, Axios |
| API | FastAPI, Uvicorn, Pydantic |
| Agent | LangGraph 0.2+, LangChain Core |
| LLM | OpenAI GPT-4o, Anthropic Claude, DeepSeek |
| 数据库 | PostgreSQL 16, pgvector, SQLAlchemy 2.0 |
| 依赖管理 | uv (Python), npm (Node.js) |

---

## 许可证

内部项目，仅供学习交流使用。
