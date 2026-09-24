# 统计任务运行与恢复

## 改动范围

人员当天同步/历史补算、问答补漏、内容全量对账、文件增量、行为事件增量、租约恢复，保留现有 Celery 名称。不同事件类型的五个每日明细任务未合并；本次通过复用查询、合并批次和差异写入减少实际 I/O。

## 默认调度

按用户确认降低定时兜底频率并错开启动时间（按 Beat 配置的时区执行）：

| 任务 | 时间 |
|---|---|
| 人员当天对账 | 每小时 0、30 分 |
| 问答补漏 | 每小时 15、45 分 |
| 内容全量对账 | 每天 01:10 |
| 人员历史补算 | 每天 00:40，回补两天 |
| 租约恢复 | 每分钟 |

实时事件入口和失败重试策略保持不变；漏写的定时兜底等待可能延长至约 30 分钟，排队和执行耗时另计。错开启动不能保证长任务完全不重叠，需观察实际耗时。部署后需重新加载 Beat 配置；已有同名自定义 `beat_schedule` 优先于默认值，需要同步核对。回退调度可恢复三个默认表达式并重新加载 Beat，无需删除调度文件或 Redis 数据。

## 失败处理

- 每条内容工作项：首次领取加最多 5 次重试，共 6 次；正常批次最多 500 条，失败批次拆成单条重试，成功后清除次数。其他受保护任务按连续失败链限制 6 次执行。
- 重试间隔 30、60、120、240、480 秒。队列项还受分钟级恢复器调度影响；实际执行可能更晚。锁竞争不计失败，不进行零延迟自旋。
- 崩溃、部分 bulk 失败、重新调度和 Beat 都不重置预算；第 6 次失败进入 dead。队列 payload、失败原因留在 Redis，无自动过期；普通入队和全量文件对账不会复活 dead 文件。
- 固定失败任务的调用参数和日期窗口，重放不会因跨天跳过原数据。恢复器可补偿重试消息投递失败；重复补偿发布有 5 分钟去重窗口。
- 任务级 dead 会停止该类任务的业务执行，需要人工检查和恢复；工作项级 dead 只隔离对应条目。恢复器自身连续失败达到上限同样需要人工恢复。
- Redis 不可用时停止业务执行；不以无状态重试替代持久预算。Redis 必须保留持久数据，清空 Redis 会失去预算和待处理记录。

## 查看与重放

以下命令在 `src/backend` 目录、正常应用配置环境中由运维执行。本次开发没有执行这些线上操作。

只读查看任务状态：

```bash
.venv/bin/python scripts/telemetry_retry_control.py --job sync_mid_realtime_qa_question_fact
```

只读查看终止工作项，输出 `cursor` 非零时用 `--cursor` 继续：

```bash
.venv/bin/python scripts/telemetry_retry_control.py --queue files
.venv/bin/python scripts/telemetry_retry_control.py --queue events
.venv/bin/python scripts/telemetry_retry_control.py --queue files --member file:123
```

修复依赖或数据原因后，显式重置指定预算并调度（恢复执行会写入统计数据，应先保存只读输出）：

```bash
.venv/bin/python scripts/telemetry_retry_control.py --job sync_mid_realtime_qa_question_fact --apply
.venv/bin/python scripts/telemetry_retry_control.py --queue files --member file:123 --apply
```

不支持清空全部失败记录；运行中任务不允许重置。队列条目重放后若返回 `job_state.status=dead`，还需检查并恢复相应消费者任务。发布失败时状态仍在 Redis，分钟恢复器会再次发现；重复人工操作前先查看状态。

## 观察日志

- `participation.reconcile.progress`：已检查、写入、未变数量。
- `qa.reconcile.progress`：来源及批次对账数量。
- `content_stat.reconcile.progress`：全量总数、百分比、差异和实际写入量。
- `content_stat.events.progress`：领取、合并分组、成功、失败数量。
- `telemetry.task.failed/skipped`：任务预算、错误原因、下次执行时间或 dead。
- `content_stat.reconcile.dead_items_skipped`：全量扫描遇到等待人工恢复的文件。

## 发布与回退边界

仅完成本地代码与离线回归。真实 ES、Redis Cluster、MySQL/DM8、Celery broker 的集成尚待验证；不会把本地通过等同于生产可用。发布时应统一更新统计 Worker，避免旧 Worker 不识别新的退避和终止状态；回退须先停止新旧统计消费者，保留 Redis 状态备查，旧代码不能可靠遵守新预算。不要通过删除 Redis 键回退。

人员历史补算仍以当前人员/部门补齐历史，统计口径不变；全量任务仍与内容增量共用原有锁。差异对账增加目标 ES 读取，减少的是重复写入，实际性能需部署后按日志和服务指标确认。
