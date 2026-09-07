# Harness运行与发布验收

## 安全策略

- 新稿默认执行事实保护。明确硬冲突阻断，证据缺失或审校失败进入unknown，不能当作通过。
- WORKFLOW_GENERATION_PAUSED默认false。设置true并重新部署后，新的生成、继续、重试和直接重写返回generation_paused；阅读、事实台账、人工编辑、取消接口保留。
- 暂停不会撤销已发出的Provider请求。已有任务先调用作品取消接口，再等待共享租约和任务结束；不得通过删除检查点或清空租约强行处理。
- FACT_REVIEW_MODE默认standard；human_only使非硬冲突稿件进入人工事实审核，不调用语义Judge，不沿用旧的自动通过回执。硬冲突规则不会关闭。
- 开关变更使用独立Compose环境覆盖层，不覆盖服务器.env、不输出凭据；变更前检查活动租约，保留上一个镜像和配置。

## 运行指标

已登录用户通过GET /api/v1/workflows/{novel_id}/metrics查看有权访问作品的指标。

- runs_by_status覆盖所有持久运行尝试；applied表示命令完成，不表示小说内容完全正确。
- counts统计最近5000条公开执行事件中的自动重试、人工审核请求、硬事实冲突、未知事实和错误。truncated=true时不得将样本计数当成全量。
- node_duration_seconds来自节点执行计时，包含该次节点内部等待，不包含作者在两次运行之间的审核等待；无样本时不虚构零耗时。
- P5以前没有持久事件的历史运行不能反推指标。旧章节未验证标记继续保留。
- 指标接口不返回正文、Prompt、API密钥或纠错签名令牌。

## 恢复与告警

- 当前执行状态：GET /api/v1/workflows/{novel_id}/run。
- 断线恢复：GET /api/v1/workflows/{novel_id}/events，使用Last-Event-ID；不得通过再次POST生成请求恢复流。
- 数据库租约60秒，每20秒续期，受总截止时间约束。过期执行者不能提交章节、连续性记忆或检查点；其他进程可以接管。
- checkpoint_sync恢复失败指数退避，五次后保留dead_letter并输出checkpoint_recovery_dead_letter错误日志。运维日志告警系统应订阅该错误；本项目没有擅自新增外部通知渠道。
- 排除数据库或检查点故障后，作者可POST /api/v1/workflows/{novel_id}/recovery/retry解除退避，随后同步创作现场；此接口不调用模型、不修改稿件。
- 不在生产运行数据库downgrade、不删除workflow事件表。应用回滚前先停止旧执行进程，并确认没有活动租约。

## 评估边界

- evals/fact_cases.json固定13个案例，包含1个用户反馈的脱敏关系抽象案例和12个合成案例；没有收集或输出生产原稿。
- 运行python scripts/harness_eval.py生成JSON报告。案例通过表示系统输出符合预期，其中包括正确阻断和正确返回unknown，不代表稿件全部事实正确。
- 另有姓氏替换、无关前缀等变形测试，签名和版本属性测试，Provider异常契约，数据库租约接管与检查点写入故障场景，以及浏览器断流重放测试。
- 所有离线评估使用可控Provider替身，provider_calls=0；不能替代真实供应商可用性、长篇质量或作者人工验收。

## CI与发布

- CI强制连接隔离PostgreSQL/Redis，连接失败即失败；先从空库执行Alembic升级，再运行静态检查、单测和固定案例评估。
- 前端执行lint、组件/状态测试和构建；docs/qa保留375/768/1280像素事实台账、两步确认和断流恢复脚本。
- 阶段提交采用中文Conventional Commits，发布只使用已提交源码；每次记录代码SHA、镜像摘要、迁移版本、健康结果和回滚层。
- 生产与隔离验收证据、当前恢复点统一写入HARNESS_IMPLEMENTATION_PROGRESS.md。
