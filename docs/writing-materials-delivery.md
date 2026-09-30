# 写作素材端到端交付

日期：2026-09-22

## 验收契约

- AC-1：入口改为“写作素材库”；采集分类与检索题材共享服务端映射。
- AC-2：草稿可检索、可选择审核；生成只使用已审核版本，不自动放宽授权。
- AC-3：主副题材均可汇总，历史样本可重建；跨题材引用不改变样本主归属。
- AC-4：生成使用真实素材版本和证据 ID；素材传递到策略、简报、大纲、正文及审读。
- AC-5：生产浏览器模拟手工操作，核对持久状态和实际章节。无素材、服务错误不得宣称使用成功。
- AC-6：只借鉴结构和机制，不复制原文、专名或独特设定组合；保留人工审核和事实硬门。

## 发布前基线

- 工作区大量已有变更，保留，不整体提交或整体覆盖线上。
- 发布前研究镜像 research-e2e-20260921-r4，前端 research-e2e-20260921-r3，后端 research-auth-2cc0a31。
- 发现：副题材未进入汇总；页面只能查已审核版本，草稿无可达入口；生成未使用 research_library。

## 状态

- 已完成：映射、草稿检索与审核入口、中文关键词、生成前版本绑定、各阶段素材提示词。
- 已完成：历史样本重建。玄幻 v18 / 17 个样本，仙侠 v1 / 17 个样本，武侠 v5 / 4 个样本。
- 已完成：服务器定向回归，后端及整图 72 项、素材服务 22 项、前端 7 项。
- 已完成：生产浏览器检索“仙侠 + 开局”，审核仙侠 v1，创建一章 3000 字的验收作品《水低两指》。
- 已确认：创作简报与总纲保存同一素材版本及 17 个证据 ID；正文初稿采用日常转入事件和任务压力结构。
- 已完成：正文经过 4 次自动修订，最终 3239 字；质量审读 `pass`，目标兑现 `passed`，一章已归档，作品与章节均为 `completed`。初稿因字数和情节兑现未达标被拦截，没有放宽 2700–3300 字范围或绕过硬门。
- 已完成：无活动写作后切换续写兼容补丁；真实素材服务只读探针通过，保留已有故事和原路由，不调用模型、不修改旧作品。
- 已完成：最后切换后重新读取数据库和生产页面，已归档素材版本、摘要及 17 个证据 ID 一致，正文可读，浏览器未记录错误。

## 验收结论

| 条件 | 结果 | 证据 |
| --- | --- | --- |
| AC-1 | 通过 | 生产写作素材库、服务端映射与桌面/手机截图 |
| AC-2 | 通过 | 浏览器找到仙侠草稿、选择并受限审核，生成绑定该已审核版本 |
| AC-3 | 通过 | 真实 PostgreSQL 历史重建，玄幻样本通过副题材进入仙侠 v1 |
| AC-4 | 通过 | 同一版本进入简报/总纲并归档；提示词与整图测试、真实策略及正文核对 |
| AC-5 | 通过 | 页面完成检索、审核、创建，真实模型生成并修订，归档一章 3239 字 |
| AC-6 | 通过 | 保留低置信度限制，未开启未授权正文采集，未跳过事实/目标硬门 |

本轮验证的是已采集素材到 AIGC 成稿的实际链路，不是新采集批次的再次验收，也不是素材提升文学质量的对照实验。当前只能充分使用已存在的目录级观察；更丰富的正文机制需要合法授权后的真实采集与审核，不能用编造的卡片补齐。

## 最终线上版本

- 北京时间 2026-09-22 22:59 完成最后后端切换并确认健康。
- 后端：`novel-writer-backend:materials-20260922-r2`。
- 前端：`novel-writer-frontend:materials-20260922-r2`。
- 素材 API / worker：`novel-writer-research:materials-20260922`。
- 后端、前端、素材 API 健康；worker 运行中。发布前两个数据库备份保存在服务器 `releases/materials-20260922/`，未清理现有镜像。

## 验收对象

- 小说 ID：`a01988ae-12b0-4198-9983-bf0e910dab94`。
- 素材版本：`knowledge-xianxia-8b6d802698e245faa3dd21d2c6bde1dd`，v1。
- 绑定摘要：`27e8c78ddf017a51bdaad0dafa438d989d5e1baec627d0e6a0dc4a255b7b9eef`。
- 来源：17 个已采集玄幻样本，通过副题材归属生成仙侠素材包。
- 限制：当前样本来自目录元数据，开局模式为低置信度候选，不代表已验证正文或市场因果。
- 人工模拟动作：查看素材及限制、选择版本、填写审核人和受限用途备注、审核通过、选择同题材创建作品。
- 实际正文：日常煎药照料师父，试炼规则引入外部任务，替代方案逐一受阻，违约与代价在当章兑现；与素材中的“日常转入事件”等候选机制相容，不据此作因果提升声明。
- 已保存桌面、手机、完稿截图和最终 checkpoint / 归档证据，位于 `docs/verification/writing-materials/`。

## 实现与证据位置

- `research_service/contracts.py`：服务端统一题材标签及采集来源映射；生成端默认只读已审核包。
- `research_service/repository.py`、`service.py`、`aggregate.py`：主副题材汇总，保留样本证据、限制及已有结构化卡片信息。
- `writter_front/src/pages/ResearchConsole.tsx`：写作素材库、草稿检索、映射展示及可达的审核入口。
- `writter_back/application/research/materials.py`：绑定已审核版本与摘要；无素材明确标记，服务故障不静默伪装成功。
- `writter_back/application/prompts/genre_strategy.py`：同一素材快照进入简报、大纲、章纲、正文与审读提示词。
- `writter_back/application/workflow_builder.py`：新作品接入素材节点；已上线补丁兼容未绑定素材的旧作品继续生成。
- `docs/verification/writing-materials/backend-tests.txt`：服务器 72 项通过。
- `docs/verification/writing-materials/research-tests.txt`：服务器 22 项通过。
- `docs/verification/writing-materials/frontend-tests.txt`：服务器 7 项通过。
- `docs/verification/writing-materials/generation-progress.json`：实际验收作品的 checkpoint、素材快照、审读与归档证据。
- `docs/verification/writing-materials/legacy-live-probe.json`：最后上线代码对真实素材服务的只读续写绑定验证。
- `docs/verification/writing-materials/novel-completed-desktop.png`：刷新后已完稿、一章 3239 字与实际正文。
- `docs/verification/writing-materials/production-health.txt`：最终生产镜像与运行状态。

## 未覆盖与基线差异

- 不把定向回归称为全套测试通过。素材全套测试中两项旧 HTTP 520 重试测试与原线上实现不一致，本轮未改采集重试策略。
- 本地完整提示词测试包含尚未部署的 `reader_contract` 依赖，不能直接用于线上基线镜像的全量验收。
- 前端测试存在已有的 jsdom `height: NaN` 警告；本轮素材库生产浏览器检查未发现控制台错误，手机页面未发生横向溢出。
- 本次完稿瞬间目录/字数摘要曾保留旧值，手动刷新后与数据库一致；未在本轮扩展修改已有的完稿事件刷新逻辑。
- 未提交或推送代码；工作区其他已有修改没有回退。后端发布对有差异的三个文件使用线上基线上的窄补丁。
