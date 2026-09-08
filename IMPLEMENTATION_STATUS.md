# 创作流程优化实施记录

## 目标与范围

- 任务可靠性优先：超时、重试、停止、恢复、SSE 状态一致性。
- P1：完整创作流程与作品级 Markdown/TXT/DOCX 导出。
- P2：观测、书架状态、窄屏体验与操作引导。
- 不记录密码、令牌、完整用户稿件或其他敏感数据。

## 当前状态

- 状态：P0 进行中；已完成取消安全和节点级超时第一版，真实生产任务诊断仍待验证。
- 代码修改：复用既有事件协议，撤回上一轮无后端生产者的新事件名；不把类型声明当成端到端实现。
- 测试：项目 `.venv` 后端 96/96、静态约束 4/4 通过；前端相关测试 77/77、构建通过。
- 环境更正：上一轮使用系统 Python 才导致 `argon2` 缺失，项目虚拟环境依赖完整，没有安装新依赖。
- 部署：未执行；未声明线上生效。

## 阶段清单

| 阶段 | 状态 | 验收证据 |
|---|---|---|
| 实施记录与接续入口 | 已完成 | 本文件 |
| P0 状态协议与展示 | 进行中 | 已撤回无生产者的新事件名；修复取消/未知快照归一化，未完成持久终态统一 |
| P0 停止与恢复安全 | 本地子项完成 | 后端取消后清理未结束时保留锁；前端等待快照确认并持续轮询 |
| P0 节点超时/重试/生产诊断 | 进行中 | 节点包装层已增加 240 秒可配置截止时间和 `workflow_node_timeout`；生产耗时分布未验证 |
| P1 完整创作流程 | 待开始 | 未覆盖 |
| P1 作品级导出 | 待开始 | 未覆盖 |
| P2 观测与易用性 | 部分完成 | 60 秒阶段耗时提示及正文分状态空页；未进行本地浏览器视觉验收 |

## 已知问题与决策

- 浏览器实测：测试作品 `189c6fc2-69f5-421b-add1-67c1119f7c46` 的角色设计阶段等待超过七分钟未返回；停止和再次启动有响应，最后已停止，正文为零章。
- 待验证根因：不能仅凭页面等待判断模型调用卡死，需结合服务端日志、节点耗时和模型请求记录确认。
- 已确认决策：复用现有工作流、命令幂等、checkpoint 和 SSE，不建立平行任务系统。
- 取消请求最多等待现有 5 秒；若后台任务尚未退出，不释放本地锁、不返回停止成功。重复取消不再次打断任务清理，结束回调负责释放锁。
- 前端取消接口返回不等于停止完成；以服务端快照为准，`unknown` 或同步失败保留当前执行状态，不伪装空闲。
- 阶段超过 60 秒仅作耗时提示，不声称模型卡死、不触发额外重试、不以传输心跳代替模型进展。
- 节点超时默认 240 秒，仍需结合模型调用和结构化重试耗时校准；未修改生产环境变量。
- 节点超时只负责中止当前节点并抛出可重试错误，不自动追加第二套重试逻辑；自动模式是否重试仍由现有 provider 错误策略决定。
- 既有作品未修改；测试作品仅用于验收。

## 变更与验证

- 后端：`writter_back/application/orchestrator.py`、`writter_back/application/runtime_observability.py`、`writter_back/application/errors.py`、`writter_back/config.py`、`writter_back/api/routers/workflow_router.py`；新增 `writter_back/tests/test_cancellation_safety.py`、`writter_back/tests/test_runtime_observability.py`。
- 前端：`workflowState.ts`、`useWorkflowStream.ts`、`types/novel.ts`、`WorkflowOverview.tsx`、`NovelStudioView.tsx`、`useNovelStudioController.ts` 及相邻回归测试。
- 接口：复用 `/cancel` 和 `/state`；前端补齐既有 `execution.cancel_requested` 类型，无数据库迁移。
- 在 `writter_back` 执行：`.\.venv\Scripts\python.exe -m pytest tests/test_cancellation_safety.py tests/test_streaming_contracts.py tests/test_workflow_command_idempotency.py tests/test_workflow_flow.py -q`：96 passed。
- 在 `writter_back` 执行：`.\.venv\Scripts\python.exe -m pytest tests/test_static_quality_constraints.py -q`：4 passed。
- 在 `writter_front` 执行：`npm test -- --run src/hooks/useWorkflowStream.test.ts src/hooks/useWorkflowCommand.test.ts src/components/WorkflowPanel.test.tsx src/components/workflow/WorkflowPresentation.test.tsx src/pages/novel-studio/NovelStudioView.test.tsx`：77 passed。
- 在 `writter_front` 执行：`npm run build`：成功；有现有大包体积警告。测试环境有 jsdom 伪元素提示，后端有 LangChain 弃用预告。
- Ruff 针对后端本轮文件通过，`git diff --check` 通过（仅 Windows 换行提示）。
- 在 `writter_back` 执行：超时、流式、幂等、工作流、静态门禁共 100 passed；Ruff 通过。
- ESLint 针对本轮前端文件通过；拆分超出行数上限的测试分组后，最终复验仍为 77 passed，构建成功。
- 未覆盖：真实模型完整生成、编辑保存、完稿和三种格式导出。

## 接续入口

- 分支：`codex/harness-usability-reliability`。
- 当前 HEAD：`bc113142ca99a10c7dbeb863bcb954fccdb64104`，未创建提交。
- 开始前已有修改：`workflow_router.py`、`template_loader.py`、`config.py`、`genre_profile.py`、`test_prompt_templates.py`、未跟踪的 `docs/prompt-hotplug-progress.md`；本轮未覆盖这些改动。
- 下一步：先读本文件并核对工作区；沿测试作品及原命令 `9cbd7ef0-51c6-4eb1-84cc-b9b53d4c0a26` 核对生产日志/部署版本，明确人物设计长等待原因。
- 后续顺序：分节点超时策略与租约失效回归 → 持久终态与书架状态统一 → 完整两章生成/编辑验收 → 三种格式导出。不得把当前取消安全修复标为 P0 全部完成。
- 阻塞条件：真实模型供应商不可用、生产配置未确认或测试任务无法稳定复现。
- 回滚：仅回滚本轮新增修改，不处理开始前已有脏改动。

## 更新日志

- 2026-09-08（北京时间）：创建实施记录，完成 P0 事件契约与前端状态展示的首轮修改。
- 2026-09-08（北京时间）：前端相关测试 44/44 通过；后端测试被环境依赖 `argon2` 阻塞。
- 2026-09-08 13:36–13:45（北京时间）：改用项目虚拟环境解除误报阻塞；完成取消安全、未知快照和长等待展示修复；撤回无生产者的事件类型。后端 96/96、静态 4/4、前端 77/77、构建通过；未提交、未部署、未修改线上作品。
- 2026-09-08 13:45（北京时间）：最终 ESLint、前端测试和构建复验通过；UTF-8 独立回读确认七个固定章节完整，无替换字符。
- 2026-09-08（北京时间）：在现有节点观测包装层加入可配置节点截止时间，超时错误包含节点名、错误码和可重试标记；后端相关测试累计 100 passed，未提交、未部署。
