# AI 题材策略生成实施记录

## 当前状态
- 阶段：核心功能已实现；等待真实恢复、部署和生产验证
- 日期：2026-09-08
- 范围：用户选择题材后，由 AI 生成结构化作品专属题材策略；普通模式可审核，自动模式自动接受。

## 已确认决策
- 策略独立保存为 `genre_strategy`，不替换固定 Prompt。
- 输入为题材选择、已有题材上下文和用户补充要求。
- 普通模式审核，自动模式自动接受。
- 旧 checkpoint 静态兼容策略属于待实现事项；新任务模型输出非法时明确失败，不静默回退。

## 阶段进度
| 阶段 | 状态 |
| --- | --- |
| 策略 Schema 与校验 | 已完成 |
| 策略生成 Prompt | 已完成 |
| LangGraph 生成/审核节点 | 已完成 |
| Proposal 与 checkpoint 接入 | 已完成 |
| 前端中断类型、阶段映射与结构化审核 | 已完成 |
| 下游 Prompt 全面注入 | 进行中 |
| 测试与恢复验证 | 进行中 |

## 已修改文件
- `writter_back/application/prompts/genre_strategy_prompts.py`
- `writter_back/application/prompts/templates/genre_strategy/generate.txt`
- `writter_back/application/agents/genre_strategy_node.py`
- `writter_back/application/workflow_builder.py`
- `writter_back/application/proposals.py`
- `writter_back/application/schemas/agent_state.py`
- `writter_back/application/agents/type_confirmation_node.py`
- `writter_front/src/types/novel.ts`
- `writter_front/src/components/workflow/presentation.ts`

## 验证命令与结果
- 后端 `compileall`：通过。
- 前端 `npm run build`：通过；存在既有 chunk size warning。

### 2026-09-08 本轮验证
- 项目 `.venv`：`pytest -q tests/test_genre_strategy.py tests/test_prompt_templates.py tests/test_prompt_quality_pipeline.py`：41 passed，1 warning。
- `npx vitest run src/components/workflow/GenreStrategyReview.test.tsx src/components/WorkflowPanel.test.tsx`：22 passed。
- `npx tsc -b`：通过。
- 创作简报归一化保留策略快照；既有创作简报、总纲、细纲、正文、审读题材块会读取快照。
- 修订节点把当前策略加入送往模型的细纲副本，不修改存储的细纲。
- 新增字段类型与长度校验；无效模型结果禁止静默回退。
- 保持既有 workflow schema 5 约定，不再用 schema 6 区分功能；API 新任务设置 `genre_strategy_enabled`，没有该字段的旧图入口维持原流程。
- `genre_strategy_version` 在策略接受时递增。
- 新任务保存完整 `prompt_snapshot`；节点执行期间从异步上下文读取绑定模板内容。
- 相关 pytest：通过，29 passed，1 warning。
- 当前题材策略、Prompt 快照和质量管线测试：43 passed，1 warning。
- 前端 `npm run build`：通过；存在既有 chunk size warning。

## 阻塞与风险
- 更正：当前静态兼容判断仍使用 `< 6`，带初始创作简报的新 API 任务可能误走静态策略，待修正；不能将现阶段标为完全实施。
- 尚未完成真实 checkpoint 恢复测试。
- `prompt_snapshot` 已覆盖运行中节点的模板读取；跨进程 checkpoint 恢复仍需真实环境验证。
- 独立 `genre_strategy` 为工作流状态；兼容提示词通过创作简报中的策略快照读取，整书规划和独立重写恢复覆盖仍待验证。
- 策略来源/hash 和初始用户补充要求输入尚未闭环。
- 尚未执行模型效果、部署或生产验证。

## 下一步
1. 修正新任务和旧任务的策略分支，并验证快照内容与 manifest hash 一致性及恢复绑定。
2. 补齐策略来源/hash 及初始用户补充要求。
3. 验证整书规划、独立重写及数据库恢复的数据传播。
4. 执行更广工作流回归、浏览器视觉检查和真实恢复测试。

## 最后更新时间
2026-09-08

## 完整回归验证（2026-09-08）
- 后端：`writter_back/.venv/Scripts/python.exe -m pytest -q`：476 passed，60 skipped，1 warning。跳过项不代表通过。
- 前端：`npx vitest run`：23 个文件、139 项测试通过；有 jsdom getComputedStyle 伪元素能力警告。
- 修复旧工作流错误进入新题材阶段、schema 版本影响规划权限门禁及函数长度超限问题。
- 新题材工作流测试显式开启 `genre_strategy_enabled`，旧流程测试保持原行为。
- 尚未执行跨进程恢复、浏览器视觉检查、模型效果验证、提交或部署。
