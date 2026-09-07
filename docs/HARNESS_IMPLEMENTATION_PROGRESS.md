# AI-writter Harness 实施进展与中断恢复记录

> 本文件是可用性、可靠性与内容一致性改造的唯一恢复入口。
> 恢复工作时先阅读本文件，再核对 `git status`、当前提交和实际测试结果；工作区事实优先于本文档。

## 当前恢复点

- 状态：实施中
- 当前阶段：P0 基线、术语与失败语义
- 当前分支：`codex/harness-usability-reliability`
- 基准提交：`b310aee`
- 最后更新时间：2026-09-07
- 最后确认提交：尚未创建本轮阶段提交
- 下一唯一动作：修复当前后端静态质量失败和未使用导入，然后运行 P0 后端质量门禁
- 当前阻塞：PostgreSQL 测试库未配置，21 个数据库集成测试会跳过
- 回滚点：`b310aee`；不得回退下方列出的既有未提交改动

### 既有未提交改动

下列文件在本轮实施前已经修改。后续必须在其基础上继续，不得重置或覆盖：

- `writter_back/api/routers/workflow_router.py`
- `writter_back/application/agents/reflection_node.py`
- `writter_back/application/errors.py`
- `writter_back/application/events.py`
- `writter_back/application/orchestrator.py`
- `writter_back/tests/test_streaming_contracts.py`
- `writter_back/tests/test_workflow_flow.py`
- `writter_front/src/types/novel.ts`

## 已锁定决策

- 用户可见语言：中文为主；英文仅保留必要代码标识和可复制错误码
- 信息架构：按作者任务组织为作品设定、整书规划、近期推进、章节细纲、正文与修订、质量与事实、创作进度、版本历史
- 执行面板：将“执行记录”调整为“创作进度”，默认展示用户摘要，技术详情默认折叠
- 规划层级：保留整书规划、近期推进方案、章节细纲和正文四层，并明确输入、输出和影响范围
- 用户范围：优先服务单一创作者，不在本阶段增加复杂协作权限
- 可用性取舍：可理解性优先；允许增加必要确认，避免误操作和误信通过
- 可用性验收：自动化状态契约与多视口视觉验收，不安排本阶段人工访谈
- 内容门禁：高置信度硬冲突阻断归档；低置信度冲突进入人工审核
- 审校策略：确定性规则优先，独立低温度 Judge 处理语义不确定问题
- 事实修改：使用版本化修正提案，禁止直接覆盖高权威事实
- 历史章节：只保护新章节；旧章节标记为 `legacy_unverified`，不自动回填
- 上线策略：新章节默认开启事实保护，同时保留紧急暂停或转人工审核开关
- 进展维护：每个阶段完成后更新；每次中断前额外更新
- 提交策略：每个阶段单独提交，提交信息使用中文 Conventional Commits
- 安全策略：只记录脱敏路径、哈希、命令和错误类别，不记录密钥、完整 Prompt、隐私或完整 Provider 响应

## 阶段看板

| 阶段 | 状态 | 目标 | 主要验收证据 |
| --- | --- | --- | --- |
| P0 | 进行中 | 建立恢复文档，清理基线失败，修复 fail-open，统一错误分类 | 后端 pytest、Ruff、mypy；前端 test、lint、build |
| P1 | 待开始 | 重构“创作进度”、中文术语、用户状态与技术状态 | 组件测试、状态矩阵、三视口截图 |
| P2 | 待开始 | 建立规范化实体、事实版本和事实校验最小闭环 | Alembic、仓储集成测试、事实规则单测 |
| P3 | 待开始 | 在章纲、正文、修订和归档前接入确定性门禁 | 工作流测试、辛/陆祠堂回归用例 |
| P4 | 待开始 | 建立冲突中心、证据审阅和版本化纠错 | 前后端契约、审阅 E2E、版本冲突测试 |
| P5 | 待开始 | 持久运行事件、SSE 重放、共享租约和恢复机制 | Redis/PostgreSQL 集成、断线与重启测试 |
| P6 | 待开始 | 建立评估集、CI 门禁、可观测性和默认开启策略 | 指标报告、视觉回归、部署前检查 |

## P0 任务清单

- [x] 创建实施分支
- [x] 记录既有未提交文件和基准提交
- [x] 创建本进展与恢复文件
- [ ] 拆分 `workflow_router._public_error_data`，满足函数长度限制
- [ ] 清理 `orchestrator.py` 未使用导入
- [ ] 将计划和战术兑现结果从缺失即通过改为显式 `unknown`
- [ ] 验证已有结构化输出错误分类改动
- [ ] 补充 P0 回归测试
- [ ] 运行后端完整测试、Ruff 和 mypy
- [ ] 运行前端测试、lint 和 build
- [ ] 更新本文件并创建 P0 阶段提交

## P1 任务清单

- [ ] 建立用户状态与技术状态映射
- [ ] 将“执行记录”更名为“创作进度”
- [ ] 面板按“当前任务、需要操作、最近完成、技术详情”分区
- [ ] 技术节点、错误码、checkpoint 和请求信息默认折叠
- [ ] 统一整书规划、近期推进方案、章节细纲和本章必须完成的中文术语
- [ ] 清除 `Production Blueprint`、`Ending Contract`、`Window Objective`、`Near-term Tactics` 等用户可见英文
- [ ] 处理 `plan_reconciled` 前端 reducer 和展示
- [ ] 明确生成、质量、计划兑现三类状态
- [ ] 为未知节点和机器错误码提供中文兜底
- [ ] 补充组件、状态 reducer 和视觉回归测试

## P2-P4 事实一致性任务清单

- [ ] 定义 `StoryEntity`、`StoryFactVersion`、`StoryFactAssertion`
- [ ] 定义 `ValidationFinding`、`ValidationReport`、`FactCorrectionProposal`
- [ ] 新增事实相关数据库表和 Alembic 迁移
- [ ] 实现事实仓储和租户隔离
- [ ] 从已确认人物设定和整书规划编译规范事实
- [ ] 实现姓氏、家族、祠堂、亲属、地点、时间、知识和状态规则
- [ ] 编译每章 `ChapterConstraintSet`
- [ ] 在章纲、正文、修订、持久化前执行门禁
- [ ] 缺失、异常或不可解析结果进入 `unknown`，禁止静默通过
- [ ] 新增“事实台账”和“冲突中心”接口
- [ ] 新增原文证据定位、修订复验和版本化事实修正
- [ ] 新增“辛姓人物却出现陆氏祠堂”等回归样本

## P5-P6 运行与评估任务清单

- [ ] 建立持久 Run、Attempt、Checkpoint、Artifact、Event 记录
- [ ] 将同小说执行互斥迁移到 DB/Redis lease，并加入 fencing token
- [ ] 实现 SSE 单调序号、`Last-Event-ID` 重放、客户端去重和 gap 检测
- [ ] 为 checkpoint reconciliation 增加退避、死信和告警
- [ ] 服务启动时识别 orphan run
- [ ] 建立合成与脱敏真实稿评估集
- [ ] 增加 Provider contract、property、metamorphic、chaos 和浏览器 E2E
- [ ] PostgreSQL/Redis 集成测试在 CI 中 fail-fast
- [ ] 建立节点延迟、重试、冲突、人工审核和恢复指标
- [ ] 完成默认开启和紧急暂停验证

## 已验证证据

### 2026-09-07 初始基线

- CodeGraph：235 个文件、3830 个节点、4430 条边，索引可用
- 后端：`326 passed / 21 skipped / 1 failed`
- 后端唯一失败：`workflow_router.py:_public_error_data` 53 行，违反静态函数长度限制
- 后端跳过项：21 个 PostgreSQL 集成测试，原因是测试数据库不可用
- 后端 Ruff：`application/orchestrator.py` 存在未使用的 `RetryableWorkflowError`
- 后端 mypy：通过
- 前端：19 个测试文件、109 个测试通过
- 前端 lint：通过
- 前端 build：通过，存在大于 500 KB chunk 警告
- `git diff --check`：通过，仅有 LF/CRLF 提示

## 当前未解决风险

| 风险 | 影响 | 临时措施 | 解除条件 |
| --- | --- | --- | --- |
| 既有改动未提交 | 容易误提交或覆盖用户工作 | 精确暂存；不得 reset 或 checkout | 明确归属并通过阶段测试 |
| PostgreSQL 测试跳过 | 仓储、迁移和事务闭环未被当前环境验证 | 单独标记为未验证，不声称集成成功 | 启动隔离测试库并全部通过 |
| 内容事实仍是自由文本 | 姓氏、家族、地点等冲突可能归档 | P2 前保持人工审阅 | 事实账本和归档前门禁启用 |
| SSE 事件不持久 | 断线后历史和顺序可能丢失 | 通过状态同步恢复最终状态 | P5 事件 outbox 和重放完成 |
| 执行锁位于进程内 | 多 worker 或重启可能重复执行 | 生产保持单 worker | 共享 lease 与 fencing 完成 |

## 中断记录

### CP-000：实施启动

- 触发原因：建立跨会话恢复基线
- 已完成：只读审计、锁定产品决策、创建实施分支和进展文件
- 未完成：P0 代码和测试修复
- 下一动作：修复后端静态质量失败与未使用导入，补充 fail-closed 测试
- 恢复前必须验证：`git status --short --branch` 与既有未提交文件列表一致
- 相关提交：待创建

## 变更历史

- 2026-09-07：创建实施恢复记录，登记初始基线、锁定决策、阶段任务和风险。
