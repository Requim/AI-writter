# Novel Writer Backend

AI 自动创作小说系统 - 后端服务

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web框架 | FastAPI 0.110+ | 异步高性能 API 服务 |
| Agent编排 | LangGraph 0.2+ | 状态机工作流，支持 interrupt/resume |
| 数据库 | PostgreSQL 16 + pgvector | 小说/章节存储 + 向量记忆 |
| ORM | SQLAlchemy 2.0 | 异步 ORM，支持 asyncio |
| LLM适配 | OpenAI / Anthropic / DeepSeek | 多模型支持，统一接口 |
| 依赖管理 | uv | 快速 Python 包管理 |
| 配置管理 | pydantic-settings | 从 .env 自动加载配置 |

---

## 项目结构

```
writter_back/
├── api/                        # API 层（路由、控制器）
│   ├── main.py                 # FastAPI 应用入口 + 生命周期管理
│   ├── routers/
│   │   ├── novel_router.py    # 小说 CRUD + 进度查询（已接入仓储）
│   │   └── workflow_router.py # 工作流 invoke/stream（已接入 Orchestrator）
│   └── __init__.py
├── application/                 # 应用层（用例、工作流）
│   ├── orchestrator.py         # NovelOrchestrator（持有依赖，驱动工作流）
│   ├── workflow_builder.py     # LangGraph 工作流构建器（11节点+边）
│   ├── schemas/
│   │   └── agent_state.py     # NovelAgentState TypedDict（17个字段）
│   └── agents/                # LangGraph 节点（11个）
│       ├── type_confirmation_node.py   # 强制用户选择小说类型
│       ├── title_generator_node.py     # 书名生成 + 用户确认
│       ├── summary_generator_node.py   # 简介生成 + 用户确认
│       ├── outline_generator_node.py   # 总纲领生成（结构化 JSON）
│       ├── progress_check_node.py     # 进度检查（完结判断）
│       ├── memory_retrieval_node.py   # 长期记忆检索（已接入 MemoryService）
│       ├── chapter_outline_node.py    # 章节细纲生成（含字数约束）
│       ├── chapter_writer_node.py     # 章节内容填充（3000-6000字）
│       ├── reflection_node.py         # 反思检查（7点清单 + 质量评分）
│       ├── revision_node.py          # 修正节点（4种用户决策）
│       └── persist_node.py           # 持久化（已接入 Repository + MemoryService）
├── service/                     # 服务层（领域模型、接口定义）
│   ├── entities/
│   │   ├── novel.py            # Novel 聚合根（id, type, chapters, progress）
│   │   └── chapter.py         # Chapter 实体（content, word_count, issues）
│   ├── value_objects/
│   │   ├── novel_type.py      # NovelType 枚举（10种类型）
│   │   ├── outline.py        # Outline（story_background, characters, plot）
│   │   ├── progress.py       # Progress（current_chapter, percentage, status）
│   │   └── chapter_outline.py # ChapterOutline（scenes, word_count）
│   └── ports/
│       ├── novel_repository.py # NovelRepository 接口（5个方法）
│       ├── llm_service.py     # LLMService 接口（generate, structured_generate, chat）
│       ├── memory_service.py  # MemoryService 接口（store, retrieve, get_context）
│       └── agent_service.py  # AgentOrchestrator 接口（invoke, resume, stream）
├── infrastructure/              # 基础设施层（实现）
│   ├── database/
│   │   ├── models.py         # SQLAlchemy 模型（Novel, Chapter, Memory）
│   │   └── repository.py    # PostgresNovelRepository（完整 CRUD）
│   ├── llm/
│   │   ├── base.py          # BaseLLMAdapter 抽象类
│   │   ├── openai_adapter.py    # OpenAI 适配（AsyncOpenAI）
│   │   ├── deepseek_adapter.py  # DeepSeek 适配（OpenAI 兼容接口）
│   │   └── anthropic_adapter.py # Anthropic 适配（AsyncAnthropic）
│   └── memory/
│       └── postgres_memory.py   # PostgresMemoryAdapter（pgvector 就绪）
├── config.py                    # 集中化配置（pydantic-settings）
├── pyproject.toml              # uv 项目配置
├── .python-version             # Python 3.11
└── .env                        # 环境变量（不提交到版本库）
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

本项目采用 **LangGraph Config 注入** + **FastAPI Depends** 双轨制：

#### 1. LangGraph Config 注入（给 Agent 节点用）
```python
# orchestrator.py - 构造 config
def _make_config(self, thread_id: str) -> Dict[str, Any]:
    return {
        "configurable": {
            "thread_id": thread_id,
            "memory_service": self.memory_service,
            "novel_repository": self.repository,
            "llm_config": self.llm_config,
        }
    }

# agent 节点通过第二个参数接收
async def memory_retrieval_node(state: NovelAgentState, config):
    memory_service = config["configurable"]["memory_service"]
    # ...
```

#### 2. FastAPI Depends 注入（给 API 路由用）
```python
# novel_router.py
def get_repository() -> PostgresNovelRepository:
    return PostgresNovelRepository(settings.DATABASE_URL)

@router.post("")
async def create_novel(repo: PostgresNovelRepository = Depends(get_repository)):
    # repo 已注入，可直接使用
```

---

## 进度追踪

- [x] Phase 0: 项目初始化 (uv + pyproject.toml)
- [x] Phase 1: 服务层 (Novel, Chapter, NovelType, Outline, Progress, Ports)
- [x] Phase 2: 基础设施层 (PostgreSQL仓储、LLM适配器、长期记忆)
- [x] Phase 3: 应用层 (11个Agent节点 + workflow_builder)
  - [x] type_confirmation_node（强制用户输入，无AI fallback）
  - [x] title_generator_node（AI生成 + interrupt确认）
  - [x] summary_generator_node（AI生成 + interrupt确认）
  - [x] outline_generator_node（结构化JSON + interrupt审阅）
  - [x] progress_check_node（完结条件判断）
  - [x] memory_retrieval_node（接入 MemoryService，降级内存兜底）
  - [x] chapter_outline_node（含字数约束 3000-6000）
  - [x] chapter_writer_node（场景填充 + 字数强制）
  - [x] reflection_node（7点检查 + 质量评分 >= 0.8）
  - [x] revision_node（4种修正策略）
  - [x] persist_node（接入 Repository + MemoryService）
- [x] Phase 4: API层 (FastAPI路由、interrupt/resume接口) **【已修复存根】**
  - [x] novel_router.py：接入 PostgresNovelRepository，实现 CRUD
  - [x] workflow_router.py：接入 NovelOrchestrator，实现 invoke/stream
  - [x] orchestrator.py：新建，持有所有依赖驱动工作流
- [x] Phase 5: 配置集中化 (config.py + .env)
- [ ] Phase 6: 集成测试 ← **进行中**
- [ ] Phase 7: Docker Compose 部署配置

---

## 开发环境设置

### 1. 环境变量配置

创建 `.env` 文件（参考 `.env.example` 或直接使用）：

```env
# ========= 数据库配置 =========
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/novel_writer

# ========= LLM 配置（至少配置一个） =========
DEFAULT_LLM_PROVIDER=deepseek
DEFAULT_MODEL_NAME=deepseek-chat

DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek-chat

OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_MODEL=gpt-4o

ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# ========= Agent 约束 =========
MIN_CHAPTER_WORDS=3000
MAX_CHAPTER_WORDS=6000
MAX_REFLECTION_LOOPS=3
REFLECTION_THRESHOLD=0.8

# ========= LangGraph =========
LANGGRAPH_CHECKPOINTER_URI=postgresql://user:password@localhost:5432/novel_writer
```

### 2. 数据库准备

```bash
# 创建数据库
createdb novel_writer

# 启用 pgvector 扩展（用于长期记忆向量检索）
psql novel_writer -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. 安装依赖并启动

```bash
cd writter_back
uv sync
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

后端启动后监听 `http://localhost:8000`。

---

## API 接口详细说明

### 小说管理

#### POST `/api/v1/novels` — 创建小说
```bash
curl -X POST http://localhost:8000/api/v1/novels \
  -H "Content-Type: application/json" \
  -d '{
    "novel_type": "suspense",
    "title": "午夜谜案",
    "summary": "一个关于...的悬疑故事"
  }'
```
**响应**：
```json
{
  "novel_id": "550e8400-e29b-41d4-a716-446655440000",
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "created"
}
```

#### GET `/api/v1/novels` — 列出用户所有小说
```bash
curl http://localhost:8000/api/v1/novels
```
**响应**：`NovelResponse[]`

#### GET `/api/v1/novels/{id}` — 获取小说详情
**响应**：`NovelResponse`

#### GET `/api/v1/novels/{id}/progress` — 获取进度
**响应**：
```json
{
  "current_chapter": 3,
  "total_chapters": 20,
  "percentage": 15.0,
  "status": "writing"
}
```

#### GET `/api/v1/novels/{id}/chapters` — 获取所有章节
**响应**：`ChapterResponse[]`

---

### 工作流控制（支持 interrupt/resume）

#### POST `/api/v1/workflows/{thread_id}/invoke` — 启动/恢复工作流

**首次调用（启动）**：
```bash
curl -X POST http://localhost:8000/api/v1/workflows/{thread_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "novel_id": "550e8400-...",
      "novel_type": "suspense"
    }
  }'
```

**恢复调用（响应 interrupt）**：
```bash
curl -X POST http://localhost:8000/api/v1/workflows/{thread_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "command": {"resume": "suspense"}
  }'
```

**Interrupt 响应格式**：
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

#### GET `/api/v1/workflows/{thread_id}/stream` — SSE 流式获取
```bash
curl http://localhost:8000/api/v1/workflows/{thread_id}/stream
```
**SSE 输出格式**：
```
data: {"type": "node_start", "node": "title_node"}
data: {"type": "node_end", "node": "title_node", "result": {...}}
data: [DONE]
```

---

## LangGraph 工作流详解

### Agent 节点列表（11个）

| # | 节点 | 职责 | 用户交互 | LLM调用 |
|---|------|------|----------|---------|
| 1 | `type_confirmation` | 强制用户输入小说类型 | `interrupt()` 暂停，10种类型 | 无 |
| 2 | `title_node` | 书名生成 | `interrupt()` 确认/重生成/自定义 | `generate()` temp=0.9 |
| 3 | `summary_node` | 简介生成 | `interrupt()` 确认/重生成/自定义 | `generate()` temp=0.8 |
| 4 | `outline_node` | 总纲领生成 | `interrupt()` 审阅/重生成 | `structured_generate()` JSON |
| 5 | `progress_check_node` | 进度检查 | 自动（完结判断） | 无 |
| 6 | `memory_retrieval_node` | 长期记忆检索 | 自动（从 MemoryService 获取） | 无 |
| 7 | `chapter_outline_node` | 章节细纲生成 | `interrupt()` 确认/重生成 | `structured_generate()` JSON |
| 8 | `chapter_writer_node` | 章节内容填充 | 自动（场景队列生成） | `generate()` 场景填充 |
| 9 | `reflection_node` | 反思检查 | 自动/中断报告问题 | `structured_generate()` 7点检查 |
| 10 | `revision_node` | 修正节点 | 自动/中断4种决策 | `generate()` 修正 |
| 11 | `persist_node` | 持久化 | 自动（写DB + 三层记忆） | 无 |
| 12 | `router_agent` | LLM 路由决策 | 自动 | `structured_generate()` |

### 工作流图结构

```
START → type_confirmation → title_node → summary_node → outline_node
                                                        ↓
progress_check ────────────────────────────────→ (is_completed?)
   ├─ 是 → END
   └─ 否 → memory_retrieval_node → router_agent → chapter_outline_node
                                                    ↓
                                              router_agent → chapter_writer_node
                                                              ↓
                                                        router_agent → reflection_node
                                                            ├─ 通过 → persist_node → progress_check
                                                            └─ 有问 → revision_node → reflection_node（循环最多3次）
                                                                                          ↓
                                                                                    降级放行 persist_node
```

### State 传递机制

1. **初始状态**：`ainvoke(input_data, config)` 的 `input_data` 作为初始 NovelAgentState
2. **节点更新**：每个节点通过 `Command(update={...})` 声明变更（非完整 state）
3. **LangGraph 合并**：自动合并变更到当前 state，传给下一节点
4. **特殊字段**：`Annotated[..., add]` 标注的字段（如 `completed_chapters`）会被追加而非覆盖

---

## 优化方案

完整的优化点清单见根目录 `README.md` 的[优化点清单](../README.md#优化点清单)章节。

### 当前已解决的问题

| 问题 | 解决方案 | 状态 |
|------|----------|------|
| 章节内容字数过多被截断 | 取消 `_semantic_truncate`，保留自动扩展 | ✅ 已修复 |
| 章节间故事衔接断层 | `chapter_writer_node` 自动注入上一章末尾 1000 字 | ✅ 已修复 |
| 循环修正死循环 | `revision_attempts` 计数器，最多 3 次后降级放行 | ✅ 已修复 |
| 中断后卡在等待状态 | 自动模式链式 resume，中断后自动发起下一个 | ✅ 已修复 |
| 后端有空状态但无中断 | 改为直接 resume 继续创作，不再轮询等待 | ✅ 已修复 |

---

## 许可证

内部项目，仅供学习交流使用。
