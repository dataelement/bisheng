# 验证记录 Verification: 知识空间内容统计索引重设计

## 验证结论

- 结论：实现与自动化定向验收通过；破坏性重建和部署后 SLO 人工计时尚未执行。
- 日期：`2026-08-03`
- 覆盖范围：双粒度索引契约、覆盖写、预览日累计、Redis 租约队列、owner lock、当前状态投影、生命周期触发、四项看板指标、scope filter、重建门禁与只读预检。
- 安全边界：本次没有执行 `--apply`，没有删除或写入真实 Elasticsearch/Redis/MySQL。

## 验收覆盖

| 需求 | 结论 | 主要证据 |
|---|---|---|
| REQ-001 文件快照覆盖写 | 通过 | 文件 `_id=str(file_id)`、当前状态重读、失效快照删除和 stale cleanup 单测 |
| REQ-002 预览日汇总 | 通过 | UTC+8 日 ID、原子脚本递增、维度冻结、无 refresh、失败不重试单测 |
| REQ-003 四项指标 | 通过 | `value_count(file_id)`、`cardinality(uploader_user_id)`、`sum(preview_count)` 数据集测试 |
| REQ-004 无租户字段和 scope | 通过 | 模型/mapping 无 `tenant_id` 和重复 `user_*`；知识空间 scope 无 tenant filter 单测 |
| REQ-005 受保护重建 | 自动化通过，真实执行待确认 | 默认 dry-run、错误确认拒绝、精确删除模拟、结果报告和失败退出码测试 |
| REQ-006 并发协调 | 通过 | 同 slot claim/ack/reclaim、再入队不丢信号、owner 校验、续租与恢复单测 |
| REQ-007 生命周期触发 | 通过 | 文件夹后代、标签、删除/回收冲突、主版本切换和版本删除触发测试 |
| REQ-008 准实时与可观察性 | 代码级通过，人工 SLO 待部署 | `refresh_interval=1s` 设置、60 秒恢复任务、队列/延迟/degraded 字段测试 |

## 自动化证据

### 定向测试

命令：

```bash
cd src/backend
uv run pytest \
  test/test_rebuild_knowledge_space_content_stat.py \
  test/test_knowledge_space_content_telemetry.py \
  test/test_knowledge_space_content_realtime.py \
  test/test_realtime_dashboard.py \
  test/knowledge/test_knowledge_space_content_projection_events.py \
  test/knowledge/test_knowledge_recycle_bin.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_version_service_delete.py -q
```

结果：`73 passed, 36 warnings`，退出码 `0`。警告来自 SWIG、Jieba 和现有 SQLModel Repository 弃用提示。

### 静态与架构检查

以下新增或核心重写文件执行 `ruff check`：

```bash
uv run ruff check \
  bisheng/telemetry/domain/mid_table/base.py \
  bisheng/telemetry/domain/mid_table/knowledge_space_content.py \
  scripts/rebuild_knowledge_space_content_stat.py \
  test/test_knowledge_space_content_realtime.py \
  test/test_rebuild_knowledge_space_content_stat.py \
  test/knowledge/test_knowledge_space_content_projection_events.py
```

结果：`All checks passed!`，退出码 `0`。

- `bash scripts/arch-guard.sh`：退出码 `0`。
- `git diff --check`：退出码 `0`。

遗留大文件全量 `ruff check` 仍会报告既有 lint 债务，未在本功能中批量修复，以避免扩大修改范围。

## 真实环境只读 dry-run

命令：

```bash
cd src/backend
PYTHONPATH=./ uv run python scripts/rebuild_knowledge_space_content_stat.py
```

结果：退出码 `0`，`mode=dry-run`，未带 `--apply`。预检观测值：

- MySQL 当前有效源文件：`562`
- ES 总文档：`5121`
- ES `record_type=file`：`563`
- ES `record_type=preview_daily`：`0`
- ES 当前显式 `refresh_interval`：未设置（返回 `null`）
- 新 pending/processing/lock/scheduled：均为 `0`
- 旧 file/preview/space pending、lock、scheduled：均为 `0`

解释：总文档中仍包含大量旧结构记录；源文件与旧文件快照相差 1 条。正式重建会清空旧结构并从 MySQL 重建，执行后必须复核最终文件快照数；本次只读预检不尝试修正差异。

## 相关模块回归边界

尝试运行知识空间服务的较宽 `-k` 回归批次，结果为 `10 passed, 19 failed, 211 deselected`。失败主要来自现有用例没有模拟当前服务已新增的数据库、收藏快照、回收站配置或路径元数据依赖，测试环境因此尝试使用无效数据库配置；例如移动文件用例进入路径元数据 DB 查询，旧删除用例进入回收站配置查询。这些失败发生在本次投影入队逻辑之前。

本次没有借机重构整套旧测试；投影相关行为由上述 73 项定向测试覆盖。较宽模块回归仍作为已知测试债务保留，不声称该批次通过。

## 待执行人工/运维验证

1. 部署全部新 API/Celery/beat 进程并确认没有旧版本进程。
2. 审核本次 dry-run 差异，在维护窗口获得单独最终确认后才可运行精确 `--apply --confirm-index mid_knowledge_space_content_stat`。
3. 重建后确认文件快照数与当时 MySQL 有效文件数一致、预览日汇总为 0、`refresh_interval=1s`、pending 最终清空。
4. 新建或更新一个文件，人工计时验证 30 秒内看板可见。
5. 预览一个已存在文件快照的文件，人工计时验证 5 秒内当日 `preview_count` 增加。

## 已知风险

- 真实重建会永久清空历史预览数据，无法从 MySQL 恢复；只有文件快照可重新全量生成。
- 重建期间看板允许短暂为空或只显示部分数据，30 秒/5 秒 SLO 不适用。
- 文件入队失败只记录 degraded 日志，不回滚已提交业务；每日全量任务负责最终校准。预览累计失败按已确认策略不重试。
