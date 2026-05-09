# NovelWriter 前端

> 基于 **React 19 + TypeScript + Vite + Ant Design + Zustand** 构建的 AI 小说创作系统前端。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 框架 | **React 19** | `react@^19.2.5`，最新并发特性 |
| 语言 | **TypeScript 5.8+** | 严格模式，`verbatimModuleSyntax` |
| 构建 | **Vite 8** | `@vitejs/plugin-react`（Oxc 编译器），HMR |
| UI | **Ant Design 6** | `antd@^6.3.7`，中文语言包 |
| 图标 | **@ant-design/icons 6** | 与 Ant Design 6 配套 |
| 路由 | **React Router 7** | `react-router-dom@^7.15.0` |
| 状态管理 | **Zustand 5** | 轻量级状态管理 |
| HTTP | **Axios** | 请求/响应拦截器，超时 600s |
| 流式通信 | **Fetch API / EventSource** | SSE 实时工作流状态 |
| 代码规范 | **ESLint 10** | Flat config，TypeScript ESLint |

---

## 项目结构

```
writter_front/
├── index.html                 # Vite 入口 HTML
├── package.json               # 依赖与脚本
├── vite.config.ts             # Vite 配置（@ 别名、/api 代理、React 插件）
├── tsconfig.json              # TypeScript 项目引用
├── tsconfig.app.json          # 应用 TS 配置（ES2023 target，JSX react-jsx）
├── tsconfig.node.json         # Node 端 TS 配置
├── eslint.config.js           # ESLint 扁平化配置
├── public/                    # 静态资源
├── dist/                      # 构建产物
└── src/
    ├── main.tsx               # 入口：createRoot + StrictMode
    ├── App.tsx                # 根组件：ConfigProvider（中文）+ BrowserRouter + 路由
    ├── App.css                # 全局样式
    ├── index.css              # 重置样式
    ├── api/                   # API 层
    │   ├── client.ts          # Axios 实例（JWT 注入、错误处理、401 跳转）
    │   └── novel.ts           # 全部 API 函数 + TypeScript 类型定义
    ├── stores/
    │   └── novelStore.ts      # Zustand store（currentNovelId, novel, progress, chapters）
    ├── pages/                 # 页面组件
    │   ├── BookShelf.tsx      # 书架：卡片网格、进度条、批量删除
    │   ├── NovelConfig.tsx    # 创作配置：多步骤向导 + 工作流中断处理
    │   ├── NovelProgress.tsx  # 进度查看：章节目录、章节查看/编辑、批量删除
    │   └── Login.tsx          # 登录页
    ├── components/            # 公共组件（待开发）
    └── types/                 # 公共类型（待开发）
```

---

## 架构设计

### 1. 路由设计 (App.tsx)

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | BookShelf | 书架首页，展示所有小说 |
| `/novel/:novelId` | NovelConfig | 创作配置/恢复，`/novel/new` 新建 |
| `/progress/:novelId` | NovelProgress | 进度查看 + 章节编辑 |
| `/login` | Login | 用户登录 |

使用 `antd/locale/zh_CN` 全局提供中文 UI。

### 2. API 层 (api/)

**client.ts** — Axios 实例配置：
- `baseURL: '/api'`，通过 Vite proxy 转发到 `http://localhost:8000`
- 请求拦截器：自动注入 `localStorage` 中的 JWT token
- 响应拦截器：自动解包 `response.data`；401 → 清除 token 并跳转 `/login`

**novel.ts** — 分层 API 模块：
- `novelApi`：小说 CRUD（createNovel, getNovels, getNovel, getProgress, getChapters, etc.）
- `workflowApi`：工作流控制（invokeWorkflow, getWorkflowState, streamWorkflow via fetch, streamWorkflowGet via EventSource）

### 3. 状态管理 (stores/novelStore.ts)

Zustand store，单文件管理：
- `currentNovelId`：当前选中的小说 ID
- `novel`：小说详情
- `progress`：创作进度（当前章节/总章节/百分比）
- `chapters`：章节列表
- 三个 `fetch*` action 分别加载小说、进度、章节

### 4. 页面功能

#### BookShelf — 书架
- 标题渐变 Banner + 创建按钮
- 小说卡片网格（封面渐变、类型标签、进度条）
- 单本删除（Popconfirm 确认）
- 批量删除模式（全选/反选、勾选框、选中蒙层）
- 空状态引导

#### NovelConfig — 创作配置向导
核心功能：与后端 LangGraph 工作流通过 **interrupt/resume** 模式交互。

**6 个中断步骤：**
| 步骤 | 中断 Action | 用户操作 |
|------|-------------|----------|
| 0. 选择类型 | `require_novel_type` | 选择小说类型 |
| 1. 书名确认 | `confirm_or_provide_title` | 接受 AI 推荐/手动输入 |
| 2. 简介确认 | `confirm_or_provide_summary` | 接受 AI 生成/手动编辑 |
| 3. 大纲确认 | `review_or_modify_outline` | 编辑故事背景、角色、主线、章节数 |
| 4. 章节细纲 | `review_or_provide_chapter_outline` | 编辑场景安排、心理轨迹、伏笔 |
| 5. 质量检查 | `review_reflection_issues` | 4 种处理：接受/AI修正/指令修正/重生成 |

**流式通信：**
- 使用 `fetch()` 建立 SSE 流，`ReadableStream` 逐行读取 `data:` 事件
- 实时显示已完成的节点标签（title_node, chapter_writer_node 等）
- 流式处理期间覆盖占位遮罩，完成后自动更新 UI

**恢复模式：**
- 从书架进入已有小说时，调用 `getWorkflowState` 获取中断状态
- `ready_for_next_chapter` 中断自动 resume 进入下一章
- 无中断时构造注入已有数据跳过设定阶段

#### NovelProgress — 进度查看
- 顶部小说信息卡片（渐变图标、类型标签、进度条）
- 章节目录列表（章节编号、标题、状态标签、字数）
- 章节详情弹窗（富文本编辑区，支持保存修改）
- 批量删除章节模式

#### Login — 登录
- 用户名密码表单
- JWT token 存储（待对接后端）

---

## 开发命令

```bash
# 安装依赖
npm install

# 开发模式（HMR）
npm run dev
# → http://localhost:5173

# 构建
npm run build

# 预览构建产物
npm run preview

# 代码检查
npm run lint
```

---

## Vite 配置说明 (vite.config.ts)

```typescript
// React 插件（Oxc 编译器）
plugins: [react()]

// @ 路径别名 → src/
resolve.alias: { '@': path.resolve(__dirname, './src') }

// 开发服务器代理
server.proxy: {
  '/api': { target: 'http://localhost:8000', changeOrigin: true }
}
```

---

## 工作流集成

前端通过 **SSE（Server-Sent Events）** 与后端 LangGraph 工作流通信：

```
启动/恢复: POST /api/v1/workflows/{thread_id}/invoke
     ↓
后端实时推送  data: { node_name: { ... } }
     ↓
中断到达:  data: { __interrupt__: [{ value: { action, message, data } }] }
     ↓
用户确认 → POST { command: { resume: value } }
     ↓
工作流继续执行...
```

节点名中文映射（`nodeLabels`）：

| 节点 | 显示名 |
|------|--------|
| title_node | 生成书名 |
| summary_node | 生成简介 |
| outline_node | 生成总纲领 |
| progress_check_node | 进度检查 |
| memory_retrieval_node | 检索前文记忆 |
| chapter_outline_node | 生成章节细纲 |
| chapter_writer_node | 撰写章节内容 |
| reflection_node | 质量检查 |
| revision_node | 修正内容 |
| persist_node | 保存章节 |

---

## 进度

- [x] 基础脚手架（React 19 + TypeScript + Vite）
- [x] API 客户端封装（Axios + 拦截器）
- [x] Zustand 状态管理
- [x] 书架页面（卡片网格 + 批量删除）
- [x] 创作配置页面（6 步中断向导 + SSE 流式通信）
- [x] 进度查看页面（章节目录 + 章节编辑弹窗）
- [x] 登录页面
- [ ] 公共组件库（components/）
- [ ] 全局类型定义（types/）
- [ ] 用户认证模块完整对接
- [ ] 单元测试
