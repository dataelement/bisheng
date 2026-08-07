# 验证记录 Verification: 知识文件解析三级优先级与排队位置可视化

## 验证结论

- 结论：代码实现与本地自动化定向验证通过；真实 Redis/Celery、MySQL upgrade/downgrade、DM8 Linux CI 和浏览器端到端验证尚未执行，因此规格仍为 `in-progress`，不声明全部验收完成。
- 日期：`2026-08-06`
- 已完成任务：`T001`、`T002`、`T003`、`T005`、`T006`、`T007`、`T008`。
- 待完成门禁：`T004`、`T009`、`T010`、`T011`、`T012`。这些任务的主要代码已落地，但其 Done when 包含当前环境无法替代的真实数据库、Redis/Worker、完整安全集成或发布证据。
- 安全边界：未连接或修改生产数据库、Redis、Celery broker；未清空 broker、未修改全局 `visibility_timeout`、未执行 Alembic upgrade/downgrade。

## 已实现范围

| 范围 | 结果 | 主要证据 |
|---|---|---|
| 角色三级配置 | 通过 | 角色专用 validator、旧角色中优默认、多角色最高、超管高优、异常低优降级及 Platform 角色表单测试 |
| 文件不可变快照 | 代码级通过 | nullable migration、条件更新首次写入、SQLite 双 session 竞争、重复写不覆盖、异常 rollback 测试 |
| 统一解析投递 | 通过 | 标题/正式解析/重试统一 `apply_async` 契约，生产代码无三个任务的直接 `.delay()` 绕过，broker/索引失败路径测试 |
| 单队列优先消费配置 | 代码级通过 | `priority_steps=[0,3,6,9]`、业务映射 `0/3/9`、`round_robin`、两套 Worker 入口 `prefetch=1`，并发与路由白名单保持 |
| 排队位置索引 | 模拟 Redis 通过 | Cluster hash tag、三级排名、同文件多 ticket、同 ticket 多 attempt、fencing、续租防误删、失败降级测试 |
| 安全查询与前端展示 | 代码级通过 | 1～100 参数归一化、候选文件省略、文件可见性/部门审批 fail-closed、queued/processing/unavailable 展示和 Platform build |
| 首钢门户上传记录排队展示 | 定向通过 | 当前页按知识库分组、queued 简化等待数、processing/unavailable 降级、终态停止、已有数据静默字段刷新和 Client build；当前工作树完整门户回归仍有范围外失败 |

## 自动化证据

### 后端定向与受影响回归

命令：

```bash
cd src/backend
./.venv/bin/pytest \
  test/role \
  test/knowledge/test_knowledge_parse_priority_dispatch.py \
  test/knowledge/test_knowledge_parse_priority_migration.py \
  test/knowledge/test_knowledge_parse_priority_snapshot.py \
  test/knowledge/test_knowledge_parse_processing_lease.py \
  test/knowledge/test_knowledge_parse_queue_api.py \
  test/knowledge/test_knowledge_parse_queue_redis.py \
  test/knowledge/test_file_title_worker.py \
  test/celery/test_celery_redis_config.py \
  test/celery/test_knowledge_parse_queue_routing.py \
  test/knowledge/test_enqueue_reparse_knowledge_space_files_script.py \
  test/open_endpoints/test_filelib_sync.py \
  test/open_endpoints/test_filelib_sync_folder_target.py \
  test/open_endpoints/test_filelib_sync_version_link.py \
  test/knowledge/test_knowledge_retry_file_category.py \
  -q --tb=short
```

结果：`145 passed, 16 warnings in 13.89s`，退出码 `0`。其后仅格式化标题 Worker 测试文件，并重新运行该文件：`4 passed in 1.34s`。警告来自 SWIG/Jieba 和现有 SQLModel `session.execute()` 弃用提示。

租户自动过滤机制的定向证据：

```bash
cd src/backend
./.venv/bin/pytest test/test_tenant_filter.py::TestSelectAutoFilter -q --tb=short
```

结果：`3 passed in 1.44s`，退出码 `0`。

### 前端组件与构建

```bash
cd src/frontend/platform
npm test -- --run src/test/roleParsePriorityField.test.tsx src/test/parseQueuePosition.test.tsx
npm run build
```

结果：组件测试 `2` 个文件、`6` 个用例全部通过；Vite build 成功，`built in 13.44s`。构建保留项目既有的 Browserslist、第三方 `eval` 和大 chunk 警告。

首钢门户 Client 扩展：

```bash
cd src/frontend/client
npx jest --runInBand --coverage=false src/api/knowledge.test.ts -t "getKnowledgeParseQueuePositionsApi"
npx jest --runInBand --coverage=false src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx
npm run build
```

结果：Client 排队 API 契约用例 `1 passed`；完整 `PortalKnowledgeWorkbench` 测试文件退出码 `0`，其中新增 3 个用例覆盖跨知识库分组、失败降级和终态停止；Vite production build 退出码 `0`。测试保留既有 `stroke-width` React 警告，构建保留既有 Browserslist、字体、第三方 `eval`、大 chunk 和 PWA 图标 glob 警告。

2026-08-06 首钢门户文案与刷新策略调整后的新鲜证据：

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-CLIENT-004 | 当前工作树，简化门户排队文案并提取刷新 Hook 后 | `npx jest --runInBand --coverage=false src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx -t "compact queue positions\|merges refreshed fields in place\|keeps the original upload status when queue positions are unavailable\|does not query queue positions for terminal upload records"` | `PASS`，`4 passed`，退出码 `0` | `AC-REQ-007-13` 的简化 queued 文案、已有表格静默刷新、unavailable 降级和终态停止 |
| E-CLIENT-005 | 同上 | `npm run build -- --logLevel error` | `PASS`，`BUILD_EXIT:0` | Client production build |
| E-CLIENT-006 | 同上 | `npm run check-imports`、三个受影响组件的 `scripts/arch-guard.sh`、`git diff --check` | 全部退出码 `0` | import 大小写、架构规则和 diff 静态检查 |

当前工作树也执行了完整 `PortalKnowledgeWorkbench.test.tsx`，结果为 `91 passed, 46 failed`，不作为通过证据。首个失败已显示测试仍断言 `order_by=update_time`，而当前范围外代码实际使用 `sort_weight`；其余包含多个页面初始化和上传流程级联超时。另一个上传记录相关子集为 `10 passed, 3 failed`，失败包含“上传成功后打开记录”和两个受前序一次性 mock 响应残留影响的编码用例。上述失败未由本次两条目标用例复现，本次没有越界修改排序、上传主流程或测试全局 mock 基线。

额外执行 `npx tsc --noEmit --pretty false`，退出码 `2`。该命令当前被约 988 行既有类型错误阻塞，涉及聊天、审批、文件预览等多个未改模块；本次新增 `PortalUploadQueueStatus.tsx` 未出现在报错列表，因此不把该命令记录为通过证据，也未在本功能范围内清理全库类型债务。

### 静态、迁移头与架构检查

- 对本功能 `25` 个新增 Python 文件，以及标题 Worker 回归和快照 Repository 执行 `ruff check`：`All checks passed!`。
- 对同一范围执行 `ruff format --check`：通过；标题 Worker 测试经一次格式化后复验通过。
- 对全部变更/新增的 backend 生产 Python 文件执行 `python -m py_compile`：退出码 `0`。
- `cd src/backend && ./.venv/bin/alembic heads`：`f078_knowledge_parse_priority (head)`。
- migration 自动化在 SQLite 执行 upgrade/downgrade，并编译 MySQL/DM-compatible DDL：包含 nullable `VARCHAR(16)` 且历史行保持 `NULL`。
- `git diff --check`：退出码 `0`。
- Client 新增 `PortalUploadQueueStatus.tsx`、`PortalUploadFolderTree.tsx` 与 `usePortalUploadedFiles.ts` 通过 `scripts/arch-guard.sh`；`PortalUploadedFilesDrawer.tsx` 当前为 `562` 行，满足单文件规模门禁。
- 对全部变更和新增文件逐个执行 `scripts/arch-guard.sh`：无新增 violation；现有超长 `knowledge.py` 报告一条 RULE-3 warning，原因是该文件在本功能前已直接导入 `database.models`，本次端点没有新增该类导入。

## 较宽回归诊断

实现中曾运行一个包含大量既有知识空间用例的较宽后端批次，结果为 `379 passed, 104 failed`。该批次未作为通过证据：失败集中在现有大型 `knowledge_space_service` fixture/Mock 与当前服务依赖不一致、既有源码字符串断言，以及本次接口由同步 Mock 变为异步后的直接受影响用例。

本次已修复并重新验证直接受影响的文件同步、重试和标题后继用例，相关定向批次全部通过；未在本功能中重写其余既有大型测试基础设施，也不声称全量 backend suite 通过。

## 尚未执行的验收门禁

1. 当前本机 `127.0.0.1:6379` 与 `:36379` 均返回 `ConnectionError`，且没有 `redis-cli`，因此未执行真实 Redis/Kombu 高→中→低与同级 FIFO smoke。
2. 未启动独立 knowledge Worker，尚未验证 publishing→processing 竞态、Worker 强退后 90 秒 lease 收敛、visibility timeout 导致同 task ID 重叠 delivery 及两种结束顺序。
3. 未连接真实 MySQL/DM8；未对目标数据库执行 Alembic upgrade/downgrade。DM8 必须由 Linux CI 使用真实驱动验证，当前 macOS 的兼容 DDL 编译不能替代该门禁。
4. 排队 Repository 测试使用真实 `redis-py` API 与 `fakeredis` 执行 Lua/ZSET 行为，但不等同于真实 Redis Cluster/Sentinel 集成。
5. API 安全行为目前由 domain/service 定向测试覆盖，尚未用真实登录会话执行未登录、跨租户、跨知识库和完整部门审批矩阵的 HTTP 集成测试。
6. 前端已通过组件测试与构建，但尚未连接真实 API/Celery 做浏览器端动态排队位置 smoke。

## 发布前人工/CI清单

1. 在非生产 Redis 启动 `knowledge_celery` Worker，固定 `-c 1 --prefetch-multiplier=1`，交错发布低/中/高任务并记录高→中→低和同级 FIFO。
2. 验证同文件多 ticket、标题换票、重叠 delivery、Worker 强退租约收敛、Redis 索引断开时业务任务不受影响。
3. 在 MySQL 执行 `upgrade f078`、历史行检查与 `downgrade f077`；在 Linux DM8 CI 执行同等门禁。
4. 使用真实权限数据调用批量位置 API，确认不可见、跨租户、跨知识库与不存在 ID 均静默省略。
5. 在 Platform 上传进度区观察阶段、约数、运行数、终态停止和 Redis 故障降级；在首钢门户“上传记录”确认 queued 状态仅显示“排队中，前方约 N 个等待任务”，并确认自动/手动刷新期间表格不消失、字段原位更新。
6. 发布顺序为 migration → backend/Worker → frontend；回滚时先回滚前端和应用，确认无新消息依赖后再考虑删除 nullable 列。禁止 broker purge、broker key 删除或消息迁移。
