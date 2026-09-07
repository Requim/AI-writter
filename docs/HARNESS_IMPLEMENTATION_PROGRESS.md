# AI-writter Harness 实施进展与中断恢复记录

> 本文件是可用性、可靠性与内容一致性改造的唯一恢复入口。
> 恢复工作时先阅读本文件，再核对 `git status`、当前提交和实际测试结果；工作区事实优先于本文档。

## 当前恢复点

- 状态：实施中
- 当前阶段：P3.1 已提交、已部署腾讯云并验收；P3 总阶段尚未完成，下一步 P3.2
- 当前分支：`codex/harness-usability-reliability`
- 基准提交：`b310aee`
- 最后更新时间：2026-09-07
- 最后确认代码提交：后端 `8bce179fef6a6284bb5c20e1c271dc3fdc5e496c`（P3.1），前端保持 `7b7b7ea`（P1）；均已部署，Git 未推送
- 下一唯一动作：开始 P3.2，从真正已确认的设定入账并将章节快照接入章纲、正文与修订输入；参考 CP-006 的确认入口边界
- 当前阻塞：无；P3.1 后端全量434项通过、零跳过，Ruff和mypy通过
- 回滚点：P3.1 应用可回退 `harness-61d65b6`，使用 CP-007 的回滚配置；保留0007事实表，不执行数据库降级

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
- 部署策略：每个阶段验收通过并提交后，部署到腾讯云；部署和上线验证是阶段完成的必要条件，不以本地提交或容器启动代替上线成功。
- 安全策略：只记录脱敏路径、哈希、命令和错误类别，不记录密钥、完整 Prompt、隐私或完整 Provider 响应

## 每阶段提交与部署规范

用户于 2026-09-07 补充要求，适用于当前阶段及所有后续阶段。

1. 完成阶段实现和验收：运行相关单测、静态检查、构建及必要集成测试。存在未通过的必需验收时标记待验收，不宣称阶段完成，也不绕过门禁发布。
2. 检查差异并按阶段精确暂存，不覆盖无关改动。提交格式为 `<type>(<scope>): <中文摘要>`，例如 `fix(harness): 阻断缺失事实报告的章节归档`、`feat(workflow): 展示可恢复的创作进度`；破坏性变更注明 BREAKING CHANGE。已有规范提交不改写历史。
3. 提交正文记录阶段编号、主要改动、验证命令及结果、兼容性和迁移影响。阶段较大可拆分多个原子提交，发布时明确完整提交范围和最终代码 SHA。
4. 部署前只读核对腾讯云现行部署目录、Compose 项目、镜像、容器、挂载、监听端口和服务健康；确认发布范围仅为本项目。记录旧代码 SHA 或旧镜像 ID、回滚方法及必要备份，不输出环境变量或密钥。
5. 部署来源必须可追溯到已提交代码。记录代码 SHA 和发布制品或镜像摘要，沿用项目实际部署流程；不上传本地未提交文件，不删除数据卷，不覆盖服务器独有配置。涉及数据库变更先完成隔离库迁移测试、备份与恢复方案。
6. 部署到腾讯云后检查容器健康、后端健康接口、前端页面及该阶段关键接口/流程，核对线上版本与发布提交一致。真实模型验收单独记录，不用 HTTP 200 或模拟接口代替。
7. 验证失败时停止继续发布，按已确认方案回滚应用；数据库不得盲目执行破坏性降级。记录失败原因、回滚版本和回滚后健康状态。
8. 更新本文件：阶段、提交 SHA、部署时间、目标服务、旧/新镜像或制品摘要、验收结果、回滚点及下一动作。部署记录单独使用 docs 类型提交，不触发无意义的应用重部署。

阶段状态依次为：实现中 → 待验收 → 已提交待部署 → 已部署待验证 → 完成。阻塞时保留实际状态和原因。Git 推送与云部署分别记录，不将二者混同；若发布流程需要远端拉取，先确认目标分支并核对远端 SHA，禁止强推。

当前部署检查（2026-09-07）：P0/P1/P2 和 P3.1 已完成部署；当前后端P3.1、前端P1、数据库0007，详见 CP-007。

## 阶段看板

| 阶段 | 状态 | 目标 | 主要验收证据 |
| --- | --- | --- | --- |
| P0 | 完成（阶段上线验收通过） | 建立恢复文档，清理基线失败，修复 fail-open，统一错误分类 | 后端 pytest、Ruff、mypy；前端 test、lint、build |
| P1 | 完成（阶段上线验收通过） | 重构“创作进度”、中文术语、用户状态与技术状态 | 组件测试、状态矩阵、三视口截图 |
| P2 | 完成（阶段上线验收通过） | 建立规范化实体、事实版本和事实校验最小闭环 | Alembic、仓储集成测试、事实规则单测 |
| P3 | 实施中（P3.1 已上线，下一步 P3.2） | 在章纲、正文、修订和归档前接入确定性门禁 | 工作流测试、辛/陆祠堂回归用例 |
| P4 | 待开始 | 建立冲突中心、证据审阅和版本化纠错 | 前后端契约、审阅 E2E、版本冲突测试 |
| P5 | 待开始 | 持久运行事件、SSE 重放、共享租约和恢复机制 | Redis/PostgreSQL 集成、断线与重启测试 |
| P6 | 待开始 | 建立评估集、CI 门禁、可观测性和默认开启策略 | 指标报告、视觉回归、部署前检查 |

## P0 任务清单

- [x] 创建实施分支
- [x] 记录既有未提交文件和基准提交
- [x] 创建本进展与恢复文件
- [x] 拆分 `workflow_router._public_error_data`，满足函数长度限制
- [x] 清理 `orchestrator.py` 未使用导入
- [x] 将计划和战术兑现结果从缺失即通过改为显式 `unknown`
- [x] 验证已有结构化输出错误分类改动
- [x] 补充 P0 回归测试
- [x] 运行后端完整测试、Ruff 和 mypy
- [x] 运行前端测试、lint 和 build
- [x] 更新本文件并创建 P0 阶段提交

## P1 任务清单

- [x] 建立用户状态与技术状态映射
- [x] 将“执行记录”更名为“创作进度”
- [x] 面板按“当前任务、需要操作、最近完成、技术详情”分区
- [x] 技术节点、错误码、checkpoint 和请求信息默认折叠
- [x] 统一整书规划、近期推进方案、章节细纲和本章必须完成的中文术语
- [x] 清除 `Production Blueprint`、`Ending Contract`、`Window Objective`、`Near-term Tactics` 等用户可见英文
- [x] 处理 `plan_reconciled` 前端 reducer 和展示
- [x] 明确生成、质量、计划兑现三类状态
- [x] 为未知节点和机器错误码提供中文兜底
- [x] 补充组件、状态 reducer 和视觉回归测试

## P2-P4 事实一致性任务清单

### P3 分步交付

- P3.1（完成）：章节约束快照、一致性读取、事务内失效检查。独立测试、提交与部署，不宣称已接入工作流。
- P3.2：从真正已确认的设定入账，在章纲、正文和修订输入中绑定快照；旧 checkpoint 明确兼容，不采信模型自报确认。
- P3.3：正文断言证据、覆盖范围与报告绑定；确定性门禁和人工审核分流；同一归档事务内复验，不允许用户接受质量问题绕过硬事实冲突。
- P3.4：完整工作流与重写入口回归，验证事实修正期间的并发归档与恢复行为；完成后才将 P3 标为完成。

每个子阶段同样执行上述提交、部署和证据记录规范。P3.1 不新增迁移，不启用自动内容阻断。

### 跨阶段任务

- [x] 定义 `StoryEntity`、`StoryFactVersion`、`StoryFactAssertion`
- [ ] 定义 `ValidationFinding`、`ValidationReport`、`FactCorrectionProposal`
- [x] 新增事实相关数据库表和 Alembic 迁移
- [x] 实现事实仓储和租户隔离
- [ ] 从已确认人物设定和整书规划编译规范事实
- [ ] 实现姓氏、家族、祠堂、亲属、地点、时间、知识和状态规则
- [ ] 编译每章 `ChapterConstraintSet`
- [ ] 在章纲、正文、修订、持久化前执行门禁
- [ ] 缺失、异常或不可解析结果进入 `unknown`，禁止静默通过
- [ ] 新增“事实台账”和“冲突中心”接口
- [ ] 新增原文证据定位、修订复验和版本化事实修正
- [x] 新增“辛姓人物却出现陆氏祠堂”等回归样本

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
- [ ] 冻结0001/0002历史迁移元数据，增加空库到head的独立验收，避免新ORM字段反向污染早期迁移

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

### 2026-09-07 P0/P1 本轮验收

- 后端完整测试：351 passed、21 skipped、1 warning。跳过项为 PostgreSQL 集成测试，不代表通过。
- 后端 Ruff 通过；mypy 配置范围内 30 个源文件通过。
- 前端 20 个测试文件、115 个测试通过；lint 和生产构建通过。现有大于 500 KB chunk 警告仍在。
- 严格兑现报告校验：必填字段缺失、字符串布尔值、明确偏差均不能自动通过；schema >= 5 转人工审核，旧工作流维持兼容。人工接受保留 accepted_with_issues 语义。
- 测试库仅使用 TEST_DATABASE_URL，强制数据库名以 _test 结尾，避免复用业务 DATABASE_URL；显式配置或 CI 下连接失败直接失败。
- 新增 .github/workflows/harness-quality.yml，提供隔离 PostgreSQL/Redis 服务和前后端门禁。尚未在 GitHub 执行。
- Playwright 使用合成小说、假登录、拦截 API，未调用真实模型或业务写入。已截图 1280、768、375px；人工检查桌面和移动端正文/创作进度未发现明显遮挡。
- 截图：output/playwright/desktop.png、studio-768.png、studio-375.png、progress-375.png（忽略目录，仅本地证据，非已入库视觉回归基准）。
- 本地前端预览：http://127.0.0.1:5175；正常访问需后端和登录，模拟数据仅存在于 harness-qa 浏览器会话。

### 下一批待办与验收标准

1. P1（已完成，见 CP-003）：计划兑现从状态快照恢复，不只消费 SSE；刷新前后结果一致，缺失保持尚未确认。
2. P1（已完成，见 CP-003）：接受存在问题的章节前二次确认，提交中禁用重复操作；覆盖重复点击、失败恢复和同步失败。
3. P1（已完成，见 CP-003）：补齐整书规划和近期推进三视口交互验收，保存可复现脚本和自动断言，本轮截图不替代完整 E2E。
4. P2（已完成，见 CP-005）：实体/事实版本/断言、报告类型和隔离仓储已落地，迁移与并发验收通过；报告持久化及审批界面留给P3/P4。
5. P2-P3：家族与祠堂归属必须有规范事实和原文证据。辛姓人物走进陆氏祠堂并非必然矛盾；明确将其写为辛家自有祠堂且与已确认归属冲突才是硬冲突。收养、改姓、母族、拜访均须加入允许或待核对样本。
6. P3：细纲、正文、修订和最终持久化复验；事实版本变动不得复用过期报告；模型自报高分不能代替事实证据。
7. P5 前不声称历史可持久恢复；最近完成仅为本页事件记录，刷新后缺失记录明确提示。
8. P6 前不启用事实保护默认开关。本轮只加强兑现报告格式和失败语义，尚不能防止全部人物、时间、地点、亲属错误。

## 当前未解决风险

| 风险 | 影响 | 临时措施 | 解除条件 |
| --- | --- | --- | --- |
| 远端 Git 未同步 | 代码只在本地提交与云端发布制品保留 | 记录完整 SHA 和制品摘要；禁止声称已推送 | 授权目标分支推送并核对远端 SHA |
| 常规镜像构建依赖下载慢 | 后续发布可能停留在下载步骤 | 本次验证锁文件一致后复用旧后端依赖；前端使用已验收 dist | 固定依赖缓存和可复现构建流程 |
| 生成链路尚未引用事实台账 | 已建立数据层，但生成矛盾仍可能归档 | 保持人工审阅，不宣称自动事实保护已开启 | P3 约束快照及归档前门禁接入 |
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

### CP-001：P0/P1 首批交付

- 已完成：失败语义、严格兑现报告门禁、隔离测试库保护、CI 定义、创作进度分区与中文术语、状态兜底和回归测试。
- 提交：P0 d7ef9a7；P1 首批 1d28544。既有错误分类、事件契约和对应测试在审查及验证后随相关阶段保存，未丢弃原有改动。
- 未完成：数据库集成、P1 补验，以及 P2-P6 事实台账、确定性规则、冲突中心、持久事件和评估闭环。
- 下一动作：按“下一批待办与验收标准”顺序继续，首先处理状态快照恢复及高风险接受确认。
- 恢复检查：git status --short --branch；git log -4 --oneline；使用 writter_back/.venv 运行测试。不要因本轮单测通过而跳过数据库与真实模型验收。
- 提交边界：本轮仅本地保存，未推送、未部署。前端开发服务可随会话结束失效，恢复时先检查 5175 端口。

### CP-002：P1 收尾与部署准备

- 新增 last_plan_execution 检查点字段，恢复实际已兑现章节、计划版本和漂移状态；旧检查点无字段不伪造报告。自动重排后仍展示执行时版本。
- 问题章节及未审读章节须二次确认；请求期间同步互斥避免重复发送，审阅控件禁用；命令结束释放，允许后续操作。
- 后端 372 passed、0 skipped（286.06 秒）：独立 pgvector 测试容器、独立数据库、127.0.0.1 端口和 SSH 隧道；无生产数据接入。
- 三视口规划/近期推进及确认取消脚本：docs/qa/harness-studio-mock.js 和 harness-studio-check.js。先启动前端 5175 并用 playwright-cli 打开本地页，再 run-code --filename 依次执行 mock 和 check。截图写入 output/playwright（仅本地）。
- 腾讯云 Compose 位于 /opt/novel-writer，project 为 novel-writer；仅发布 backend/frontend，不改数据库/Redis/edge 网络和环境配置。
- 当前迁移 0006_tactical_planning；本轮无新增迁移。旧镜像 backend：sha256:4672321844797287baf9966730b6a13280e684f34cb0303d33ba5e67f01da7de；frontend：sha256:7143c0fc92db0651fd76fe81312e6dae76f9b8153a2786e7ccf963bfa0254809。
- 发布状态：待代码提交和镜像构建，尚未更换生产容器。真实模型生成验收未执行，不与合成接口验收混淆。

### CP-003：P0/P1 腾讯云阶段部署完成

- 验证时间：2026-09-07 17:47（Asia/Shanghai）。代码 SHA：7b7b7eab58f14bdbf513560b3d78d92d1fc99f07；Git 未推送，部署采用已提交源码制品，不依赖远端 Git 拉取。
- 阶段验收：后端隔离库全量 372 passed、零跳过；新增版本断言复验 20 passed；前端 118 passed；Ruff、mypy、lint、build 通过。三视口规划/近期推进、风险确认取消通过。仍有前端大 chunk 和 LangGraph 弃用提示。
- 常规 Docker 构建在依赖下载处等待后主动取消。后端 uv.lock 与 pyproject.toml 的 SHA-256 和旧镜像一致，因此从 rollback-pre-7b7b7ea 复用依赖并复制提交源码构建；前端本地重新 build 后使用现有 Dockerfile.runtime 打包。未修改项目源 Dockerfile。
- 后端镜像：novel-writer-backend:harness-7b7b7ea，sha256:a077a51256a417d6fc20ed6b84a279fe6c53efd60ae367325d7d9926967baf97。
- 前端镜像：novel-writer-frontend:harness-7b7b7ea，sha256:6f5f8ff42f4b4ed252dce39bd1d40b337c790224be196104fd62e7bdbd2d2686。两容器 revision 标签均为完整代码 SHA。
- 源码包 SHA-256：415f13f31ca55546ec1f30e33b1d3f4f95598a11a5c840bbc18a7cb5617e3e1c；dist 包：a34dcb940e240ca7110fde0b957af34d112016ad7f5d5b2ec9e23dd12f487ce4；传输前后摘要一致。
- 上线检查：前后端 healthy；后端 /health/ready 返回 ready；前端回环入口 HTTP 200；同源 /api/v1/auth/me 未登录返回 401；线上缺失兑现报告拒绝通过的运行时断言通过；last_plan_execution 类型字段存在。
- 前端 index.html 线上/本地摘要均为 48e5eea50e26dad01e1f32694c9ea405413d45a0507173ffb5e94afc11b2e44b。
- 仅更换 backend/frontend，database/redis 保持原容器、数据卷、内网端口；原 edge 网络保留。检查时活跃命令租约为 0；测试容器与 SSH 隧道已清理。
- 发布目录：/opt/novel-writer/releases/7b7b7ea；当前生效覆盖文件：compose.harness-release.yml。后续重启/发布必须核对并携带当前覆盖文件，不能仅用原两个 Compose 文件重建旧目录源码。
- 回滚文件：同发布目录 compose.harness-rollback.yml；对应旧镜像已打 rollback-pre-7b7b7ea 标签。按下方命令仅回滚应用，不清卷、不降级数据库。
- 验收边界：本轮未进行真实模型生成、生产账号登录后的全流程或公网域名浏览器验收；已完成本阶段隔离回归、模拟交互及线上服务/运行时检查，不代表小说事实一致性已解决。
- 下一阶段：P2 实体与事实版本、租户隔离和迁移测试；P3 才将事实冲突规则接入生成和归档门禁。

回滚命令（服务器执行，先核对当前发布和是否需要回滚）：

~~~bash
sudo docker compose --project-directory /opt/novel-writer -p novel-writer --env-file /opt/novel-writer/.env -f /opt/novel-writer/docker-compose.yml -f /opt/novel-writer/docker-compose.prod.yml -f /opt/novel-writer/releases/7b7b7ea/compose.harness-rollback.yml up -d --no-deps --no-build --wait --wait-timeout 120 backend frontend
~~~

### CP-004：P2 实现与迁移验收

- 新增 StoryEntity、CanonicalFact、StoryFactVersion、StoryFactAssertion、FactEvidence、ValidationFinding/Report；实体和事实保留明确来源及版本，草稿不能直接提升为规范事实。
- 新增 story_entities、story_fact_versions、story_fact_assertions；租户与小说复合外键、每属性版本唯一性和幂等请求唯一性。仓储复用现有会话工厂，锁小说行防止并发覆盖。
- 编译器支持已确认角色的显式姓氏及已确认来源的显式结构化陈述；不从首字猜姓、不推断祠堂归属、不自动处理历史章节。
- 最小规则区分明确归属冲突与拜访/收养，校验原文摘要、证据存在、版本唯一性及生效区间。尚未接入生成、修订和归档，也未新增 HTTP 接口；后续 P3/P4 接入。
- 后端全量 399 passed、零跳过（419.99 秒）；最后增加的持久化冲突/修正闭环和类型标注正在定向复验。Ruff 通过，默认 mypy 扩展为 34 个源文件通过。前端源码未改动，本轮不重建前端。
- 0006 → 0007 → 0006 → 0007 真实隔离 schema 测试已通过，原有小说保留。生产逻辑备份已恢复到临时隔离库，再执行真实 Alembic upgrade head 到 0007，小说和章节数量不变。
- 备份位于腾讯云 /opt/novel-writer/backups/p2-20260907-before-0007.dump，权限 600，SHA-256 为 ffd398f3acea58090625341f9a57ac457d20a1f602622a0e3c47156d75665f2b；未下载到本地。发布时仅应用回滚，不自动降级删除事实表。
- 本轮确认空库初始化仍存在历史迁移依赖实时 ORM 元数据的风险，列入后续发布工程整改；本次验收明确针对现有 0006 数据升级。
- 详细数据契约和边界：docs/STORY_FACT_CONTRACT.md。
- 当前状态：代码待提交；生产仍为 P1 版本，0007 仅在隔离测试/恢复库执行。

P2 提交前补验：最新事实/迁移/静态门禁 32 passed；另补充并通过 1 项持久化冲突、版本修正及删除小说级联清理复验；mypy 34 个源文件、Ruff 通过。全量 399 项结果与定向复验分别记录，不合并宣称一次全量结果。

### CP-005：P2 腾讯云部署完成

- 验证时间：2026-09-07 18:32（Asia/Shanghai）。后端 revision 为 61d65b673632dbda048bb4a62cc98f0bca641566，镜像 novel-writer-backend:harness-61d65b6，摘要 sha256:5a11a7586829fb3a64b52a177cdd9658cb55d0209bb71202098d5c0a083355d5。
- 发布包由 Git 提交导出，仅包含后端；传输前后 SHA-256 一致：af4de5a2ec0c04c1d5f0a5bbeb92da3ac0391d93a7e3074a5fac4417ed8eb08e。未推送 Git。
- 依赖复用 P1 镜像：项目/构建/依赖组结构化摘要 63d1a1d70d23fb125e68cdb2fda311fe41b138d9206c986547919af32b79d8a0、锁文件结构化摘要 44b804c278a57789f0649bac5cc229bf753bffc867af94e8439ec90a8aa660bf 均与线上一致；本轮 pyproject 只扩大 mypy 范围，没有新增依赖。
- 发布配置在 /opt/novel-writer/releases/61d65b6/compose.harness-p2.yml。必须叠加原基础/生产配置和 P1 compose.harness-release.yml，保留 P1 前端、网络和环境配置；只替换 backend，随后 nginx -t 和 nginx -s reload 更新代理解析。
- 生产只读验证：alembic_version 为 0007_story_facts，三张事实表存在；运行时显式冲突 blocked、无断言 unknown 断言通过；检查脚本没有生产写入。后端 ready，前端200，同源未登录鉴权401，四个服务 healthy。
- 生产数据库/Redis 容器、数据卷及端口未更换；本轮仅新增三表，没有历史正文回填。前端镜像仍为 harness-7b7b7ea，没有重新构建。
- 备份文件及摘要见 CP-004。隔离测试与生产备份恢复库所在的临时容器、tmpfs 数据及 SSH 隧道已清理；受限生产备份保留。
- 应用回滚配置为同目录 compose.harness-p2-rollback.yml，镜像指向 P1，并将 entrypoint 改为 /app/.venv/bin/uvicorn、直接运行 api.main:app。原因：旧镜像不认识0007迁移号，不能运行它的 Alembic 入口。已验证回滚配置解析和旧镜像 uvicorn 可执行；未实际切换回滚。
- 回滚时保留0007和事实表，不自动 downgrade。后续重新发布时确认已移除回滚入口覆盖，再恢复正常迁移入口。
- 下一阶段为 P3：规范来源实际落库、章节约束快照、断言抽取/证据校验、归档前重验及并发事实版本校验。复杂亲属/时间/知识规则、纠错审批与 UI 仍为后续工作。

P2 专用应用回滚命令（先确认需要回滚；不会降级数据库）：

~~~bash
sudo docker compose --project-directory /opt/novel-writer -p novel-writer --env-file /opt/novel-writer/.env -f /opt/novel-writer/docker-compose.yml -f /opt/novel-writer/docker-compose.prod.yml -f /opt/novel-writer/releases/7b7b7ea/compose.harness-release.yml -f /opt/novel-writer/releases/61d65b6/compose.harness-p2-rollback.yml up -d --no-deps --no-build --wait --wait-timeout 120 backend
sudo docker exec novel-writer-frontend nginx -s reload
~~~

### CP-006：P3.1 章节约束快照（验收通过）

- 新增 ChapterConstraintSet：作用域、章节、实体、全部事实版本头和稳定摘要；生效事实单独筛选，撤回/未来/过期记录继续参与版本检测。
- 事实仓储增加 capture_constraints 与 assert_constraints_current。前者在小说锁内一致读取，后者要求调用方写入事务且保持锁至提交，拒绝错租户、错小说、错章节、内容变化及不安全隔离级别。
- 初轮单元40项、数据库定向19项、静态约束4项通过；Ruff 和 mypy 35源文件通过。最终全量434 passed、零跳过（571.89秒），包含最后增加的 READ COMMITTED 限制与测试；1条既有 LangGraph 依赖未来默认值变更警告。
- 无数据库迁移、无依赖变更、无前端变更。没有接入真实生成和归档入口，空快照不会生成“通过”结论，P3 总阶段仍在实施中。
- 已只读核对线上后端 P2 镜像、前端 P1 镜像、后端无挂载、前端双网络及回环端口；依赖元数据与解析锁文件摘要与 CP-005 一致。
- 本轮隔离库：novel-writer-harness-p31-test，回环55441，tmpfs；SSH 隧道PID37884。已在验收后核对身份并清理容器和隧道，不清生产卷。
- 下一步来源接入须特别注意：character_design_review_node 在 decide_proposal 验证当前提案后才 resolve_character_design；_accept_design 同时被旧设定恢复路径调用，不能直接把所有 _accept_design 调用都当作新的人工确认。必须记录真正的确认来源版本、摘要与幂等键。
- 下一步归档接入须将快照复验放到 PostgresNovelRepository 的章节写入事务中，不能在 persist_node 单独开启事实仓储事务后再保存。章纲、正文、修订、直接重写和旧 checkpoint 路径都必须有明确覆盖策略。

### CP-007：P3.1 腾讯云部署完成

- 验证时间：2026-09-07 19:08（Asia/Shanghai）。代码提交 8bce179fef6a6284bb5c20e1c271dc3fdc5e496c，提交信息 feat(harness): 增加章节事实快照与事务内版本复验；Git 未推送。
- 后端镜像 novel-writer-backend:harness-8bce179，镜像摘要 sha256:a28410051b23dc3fb4e2c36f15c4365d7e921f381adc96d2b12d2e0fefdcf7d2；线上 revision 标签与提交一致。
- Git 归档发布包仅包含后端，传输前后 SHA-256 一致：078a6b01011bb53d38163d3559edbfb9238b6f35d27155cbd2727227d00f2b00。复用 P2 已验证依赖镜像，依赖元数据/锁解析摘要与 CP-005 一致；本次无迁移、无新增依赖。
- 发布目录 /opt/novel-writer/releases/8bce179；生效文件 compose.harness-p31.yml，叠加基础/生产/P1/P2 配置。Dockerfile.harness-p31 与只读运行时检查脚本同目录保留。
- 发布前 active_command_leases=0；Compose 配置解析通过。只重建 backend，随后 nginx -t 和 nginx -s reload 通过，保持前端 P1 和原双网络。
- 上线验收：后端 /health/ready 返回 ready；前端回环入口200，同源未登录鉴权401；四个生产服务 healthy。内存快照序列化、摘要变化、生效事实筛选和接口存在性检查通过。
- 数据库只读检查：0007_story_facts、READ COMMITTED；检查脚本 production_writes=0。数据库和 Redis 的容器 ID、挂载及数据卷与发布前一致。未回填正文，未执行真实模型或生产账号登录后的生成验收。
- 回滚镜像为 P2 的 harness-61d65b6，摘要 sha256:5a11a7586829fb3a64b52a177cdd9658cb55d0209bb71202098d5c0a083355d5。回滚覆盖文件 compose.harness-p31-rollback.yml 已通过 Compose 解析；因数据库版本未变化，可保持正常迁移入口。未实际切换回滚。
- 临时测试容器、tmpfs 数据和经身份核对的 SSH 隧道已清理。P2 的受限备份继续保留，本次没有数据库变更，不执行数据库降级。
- P3.1 仅完成约束基础设施，真实工作流门禁未启用。下一步 P3.2 的代码入口与风险见 CP-006；P3 总阶段不能标记为完成。

P3.1 应用回滚命令（仅在确认需要回滚后执行）：

~~~bash
sudo docker compose --project-directory /opt/novel-writer -p novel-writer --env-file /opt/novel-writer/.env -f /opt/novel-writer/docker-compose.yml -f /opt/novel-writer/docker-compose.prod.yml -f /opt/novel-writer/releases/7b7b7ea/compose.harness-release.yml -f /opt/novel-writer/releases/61d65b6/compose.harness-p2.yml -f /opt/novel-writer/releases/8bce179/compose.harness-p31-rollback.yml up -d --no-deps --no-build --wait --wait-timeout 120 backend
sudo docker exec novel-writer-frontend nginx -s reload
~~~

## 变更历史

- 2026-09-07：创建实施恢复记录，登记初始基线、锁定决策、阶段任务和风险。
- 2026-09-07：完成 P0 本地验证及 P1 首批改造，记录测试、截图、阶段提交和后续验收边界。
- 2026-09-07：按用户补充要求，将规范提交、腾讯云部署及上线验证纳入每阶段完成条件；完成腾讯云只读连通与后端健康检查，未执行部署。
