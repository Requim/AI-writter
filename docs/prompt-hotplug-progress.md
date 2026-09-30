# 小说类型扩展与提示词热插拔实施记录

## 目标与决策
- 扩展为主类型、子类型、读者体验、节奏和风格轴。
- 提示词支持外部 UTF-8 文件热加载，外部文件优先、内置模板兜底。
- 新任务绑定当前提示词 manifest；运行中及恢复任务保持原版本。
- 保留 `novel_type`、旧小说和旧 checkpoint 兼容性。
- 本阶段不做在线编辑器、数据库提示词管理或自动部署。

## 状态
- 当前阶段：验证中
- 已完成：代码调查、方案确认、实施记录初始化、`PROMPT_ROOT`/`GENRE_PROFILE_ROOT` 配置入口、外部模板优先加载、最后有效模板回退、模板 manifest/hash API、新工作流入口绑定 manifest、类型 taxonomy 外部 JSON 覆盖
- 未完成：前端类型契约测试、真实部署验证
- 最后更新时间：2026-09-08

## 修改与验证记录
| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 类型配置化 | 已完成 | `GENRE_PROFILE_ROOT` 支持目录或 `genres.json` 外部 UTF-8 配置，内置 profile 兜底 |
| 提示词热加载 | 已完成 | `writter_back/application/prompts/template_loader.py` 已支持外部 UTF-8 文件、路径校验、非法更新回退和 hash |
| manifest 与恢复绑定 | 进行中 | 仅保存版本标识；尚无不可变模板快照读取，旧任务仍可能读到更新后的文件 |
| 全流程接入 | 进行中 | AI 策略审核与既有题材块传播已补充，整书规划与恢复仍待验证 |
| 测试与文档 | 进行中 | 后端提示词与质量管线测试已通过，前端契约和部署尚未验证 |

## 配置约定
- `PROMPT_ROOT`：外部提示词目录；为空时使用内置模板。
- 外部模板必须为 UTF-8、`.txt`，路径只能位于配置目录内。
- 加载失败时保留上一份有效模板，首次失败回退内置模板。

## 验证记录
- `python -m compileall -q application config.py`：通过。
- `python -m compileall -q application service api config.py`：通过。
- `python -c "from application.prompts.template_loader import prompt_manifest; ..."`：通过，生成带模板 hash 的 manifest。
- `python -m pytest -q tests/test_prompt_templates.py tests/test_prompt_quality_pipeline.py`：阻塞；当前环境缺少 `argon2`，在加载 `tests/conftest.py` 时失败。
- 使用项目 `.venv` 重跑上述测试：通过，29 passed，1 warning。
- `python -m compileall -q application service api config.py`：通过。

## 未验证风险
- 更正此前完成描述：保存版本号不等于冻结模板内容；本能力尚未完成。
- AI 题材策略本轮验证：后端 41 passed；前端审核相关 22 passed；TypeScript 通过。详情见根目录 IMPLEMENTATION_STATUS.md。
- 尚未完成旧 checkpoint 的真实恢复测试。
- 当前未执行模型效果验证、部署或提交。
