# 中粮 923 频道文章同步移植

## 范围与来源

目标分支：`feat/cofco-923-3.0.0-beta1`，开发起点 `def3912f87cd9de7374b3b3ee176e5df71112d9c`。

源分支：2026-10-14 获取的 `origin/feat/3.0.0`，提交 `e058f58eb8`。移植该提交中的文章同步实现，涉及 `15a19694dc` 的上游就绪/文章更新时间判断和 `0b22f59aa3` 的首次同步协议。F060 设计在源分支的 `features/v3.0.0-beta1/060-information-source-subscription-reconciliation/`，本次没有移植整套 F060。

这是既有实现的定向移植。目标分支保留 F031 订阅对账、租户上下文、原有 Celery 任务名/周期、知识空间投递及中粮配置；不引入主线 F060 的平台订阅并集和独立知识投递任务。

## 验收条件

| ID | 条件 | 本地验证 |
|---|---|---|
| AC-C1 | 上游 `last_sync_at` 不是当前业务日时不拉文章、不标记处理完成；同日后续轮询在上游完成后继续同步。 | `test_worker_retries_late_remote_sync_then_bootstraps_and_polls_incrementally` |
| AC-C2 | 首次请求 `/information/articles/{id}/bootstrap?limit=36`，写入上游按发布时间选出的最新文章；保存 `snapshot_max_create_time`，后续包含式增量分页使用该游标和固定快照上限。 | 同上；`test_information_article_sync_pagination.py` |
| AC-C3 | 全部文章写入成功且仍持有来源锁后才提交游标；部分失败、响应不完整、丢锁或状态冲突均不提前推进。 | `test_failed_bootstrap_keeps_null_cursor_and_retries`；`test_information_article_sync_commit.py`；状态 CAS 测试 |
| AC-C4 | 原有 `sync_information_article` 入口仍遍历活跃租户，调用新文章服务；只把 ES 中原先不存在且写入成功的 ID 交给目标分支知识投递链路。 | `test_sync_information_article_tenant.py`；Worker 接线测试 |
| AC-C5 | 原有来源表新增三个可空 BIGINT 字段，保留旧记录；迁移图保持单 head，重复升级不重复添加列。 | `test_existing_source_table_upgrade_adds_nullable_progress_and_is_idempotent`；`test_alembic_single_head.py` |

## 目标分支适配

- 状态保存在 `channel_info_source`：`article_cursor_create_time`、`processed_remote_sync_at`、`processed_article_list_updated_at`。采用主线的行锁/CAS 提交，沿用目标分支租户自动过滤。
- 不再把本地 `update_time` 或 ES 最大文章时间当作同步完成/游标依据。升级后旧行的新增字段为空，会执行一次 bootstrap；已经存在的 ES ID 不重复进入知识投递。
- 文章同步服务、状态 Repository、Redis 来源锁和 ES 逐项写入能力来自主线；原 Worker 收集服务返回的新 ID，继续调用原有知识空间同步钩子。频道展示时间按每个成功写入的来源分别更新。
- 客户端 GET 的 `return_information` 编码为字符串 `false/true`，兼容 aiohttp；订阅列表请求使用 `page_size`，响应仍读取 `PageSize`。
- 仅增加 `information_initial_article_limit: 36` 和 `information_business_timezone: Asia/Shanghai` 两个 `information_conf` 子配置。既有 DB 配置通过缺省项补齐机制获得默认值，运维已有值保持优先。
- DDL revision 为 `cofco_923_information_cursor`，父节点使用目标分支实际 head `f062_merge_cofco_923_f068_heads`；没有复制主线不属于此分支的迁移依赖，也没有数据迁移。

## 发布与联调

应用升级需要先执行现有部署流程中的 `alembic upgrade head`，然后让后台 Worker 使用新代码。情报订阅服务必须提供订阅项的 `last_sync_at` / `article_list_updated_at`、bootstrap 接口及增量文章响应的 `snapshot_max_create_time`。

依照仓库 `e2e-test` skill，本次没有新增毕昇 HTTP API/页面，不生成只覆盖 mock 的伪 API E2E。真实联调尚未执行，需在指定测试环境验证：

- [ ] 上游仍未完成当天同步时触发旧 Celery 入口，确认 `not_ready`，三个进度字段不变；上游完成后再次触发，确认文章被拉取。
- [ ] 新增一个文章数超过 36、发布时间与入库时间排序不同的信息源，确认首次仅取最新发布的 36 篇，保存上游完整快照游标。
- [ ] 上游新增文章后再次触发，确认新文章进入频道，重复执行不重复投递到知识空间。
- [ ] 两个租户分别同步各自来源，确认上下文隔离和原有知识空间权限/子频道筛选正常。
- [ ] 在 MySQL/DM8 测试环境验证升级 DDL、行锁和 CAS；SQLite 本地测试不代表 DM8 联调结果。

## 本地验证结果（2026-10-14）

- `pytest -q test/channel test/cofco test/database/test_alembic_single_head.py`：179 passed。
- 所有变更 Python 文件的 Ruff 检查和格式检查通过，`git diff --check` 通过。
- `alembic heads`：仅 `cofco_923_information_cursor`。
- 架构守卫无新增违规；`settings.py` 的敏感字段警告在修改前后均为同一条既有匹配。
- 核心文章 Service、状态 Repository、ES Service、来源模型和 Redis 锁与源分支内容一致；差异集中在客户端请求编码、目标 Worker 适配、配置和迁移父节点。
- 本次本地验证不代表真实环境部署或联调完成；主工作区原有未提交文件未被改动。
