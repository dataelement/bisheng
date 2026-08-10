# 验证记录 Verification: 知识文件解析三级优先级与排队位置可视化

## 验证结论

- 结论：2026-08-09 已完成“一次文件尝试单 delivery/单 ticket”的代码实施与本地自动化复验。新生产入口只发布初次解析/重试生命周期消息，旧标题/正式解析/重试消息保留滚动兼容；Platform 与首钢门户均已去除内部阶段展示。发布级结论仍为条件通过，真实 Redis/Celery 顺序、Worker 强退租约、MySQL/DM8 migration 尚待非生产环境和 CI 门禁。
- 日期：`2026-08-09`
- 已完成任务：`T001`～`T008`、`T010`～`T013`。
- 待完成门禁：`T009`。T006/T007 的阶段消息部分仅保留为历史基线，最终生命周期以 T013 为准。
- 安全边界：未连接或修改生产数据库、Redis、Celery broker；未清空 broker、未修改全局 `visibility_timeout`、未执行 Alembic upgrade/downgrade。

## 2026-08-09 规格修订影响

| 新验收范围 | 当前状态 | 旧证据是否可复用 | 新证据要求 |
|---|---|---|---|
| 初次解析单 delivery：领取即 PROCESSING→标题→正式解析 | AUTOMATED_PASS | 否；已用新 lifecycle worker 用例替换旧后继消息证据 | 处理时点、标题失败继续、无后继发布和新/旧正式解析分流已覆盖 |
| 重试单 delivery：领取即 PROCESSING→清理→正式解析，不执行标题 | AUTOMATED_PASS | 终态基线可复用，步骤边界使用新证据 | 清理顺序、无标题、清理失败置 FAILED 且跳过正式解析已覆盖 |
| 一次正常文件尝试单 ticket | AUTOMATED_PASS | 否；已改为 attempt-kind 单消息契约 | dispatcher、Redis ticket/attempt 和 source guard 定向测试通过；真实 Worker smoke 待 T009 |
| Platform/门户统一无阶段排队文案 | PASS | 门户旧证据可复用，Platform 已更新 | 两端定向组件/API 测试和 production build 通过 |
| 单并发三个同优文件完整生命周期 FIFO | NOT_RUN | 否；旧 smoke 只计划验证消息 priority/FIFO | 真实 Redis/Celery `-c 1 --prefetch-multiplier=1` 事件序列 |
| 旧标题/正式解析/重试消息滚动兼容 | AUTOMATED_PASS | 否 | 旧标题直跑完整生命周期且不重排队、旧正式解析 formal-only、旧重试兼容路径已自动化覆盖；真实滚动发布待 T009 |

## 已实现范围

| 范围 | 结果 | 主要证据 |
|---|---|---|
| 角色三级配置 | 通过 | 角色专用 validator、旧角色中优默认、多角色最高、超管高优、异常低优降级及 Platform 角色表单测试 |
| 文件不可变快照 | 代码级通过 | nullable migration、条件更新首次写入、SQLite 双 session 竞争、重复写不覆盖、异常 rollback 测试 |
| 统一解析投递 | 通过 | 所有新生产入口统一投递 `attempt_kind=initial|retry`；标题 task 仅保留为旧消息兼容消费者，生产源码无标题后继发布 |
| 单队列优先消费配置 | 通过 | `priority_steps=[0,3,6,9]`、业务映射 `0/3/9`、`round_robin`、两套 Worker 入口 `prefetch=1` 已验证；新生产白名单仅正式解析/重试，旧标题单列兼容路由 |
| 排队位置索引 | 模拟 Redis 通过 | Cluster hash tag、三级排名、同文件多 ticket、同 ticket 多 attempt、fencing、续租防误删、失败降级测试 |
| 安全查询与前端展示 | 通过 | 1～100 参数归一化、候选文件省略、文件可见性/部门审批 fail-closed 通过；Platform/Client 都不读取或展示 `stage` |
| 首钢门户上传记录排队展示 | 定向通过 | 当前页按知识库分组、queued 简化等待数、processing/unavailable 降级、终态停止、已有数据静默字段刷新和 Client build；当前工作树完整门户回归仍有范围外失败 |

## 自动化证据

以下命令与结果均来自 2026-08-06 的旧阶段消息代码状态。除上表明确允许复用的角色、快照、Redis priority、权限和门户刷新证据外，任何涉及标题后继、ticket stage 或 Platform 阶段文案的结果在 T013 后都必须重新执行。

### 2026-08-09 单生命周期实施后的新鲜证据

后端功能批次：

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
  test/knowledge/test_knowledge_file_parse_lifecycle.py \
  test/celery/test_celery_redis_config.py \
  test/celery/test_knowledge_parse_queue_routing.py \
  test/knowledge/test_enqueue_reparse_knowledge_space_files_script.py \
  test/open_endpoints/test_filelib_sync.py \
  test/open_endpoints/test_filelib_sync_folder_target.py \
  test/open_endpoints/test_filelib_sync_version_link.py \
  test/knowledge/test_knowledge_retry_file_category.py \
  -q --tb=short
```

结果：`156 passed, 16 warnings in 14.30s`，退出码 `0`。覆盖角色等级、文件快照、初次/重试单消息 dispatch、PROCESSING→标题/清理→正式解析顺序、标题失败继续、清理失败终态、旧消息兼容、单 ticket/多 attempt、三级位置公式、路由白名单、prefetch 和重解析脚本。

PDF 后置任务边界：

```bash
./.venv/bin/pytest test/knowledge/pdf/test_pdf_artifact_integration_contracts.py \
  -q --tb=short \
  -k "sync_and_celery_parse_completion_hooks_enqueue_existing_generation or batch_retry_invalidates_before_dispatch"
```

结果：`2 passed, 7 deselected`，退出码 `0`；证明 PDF Artifact 仍由 formal parse 完成钩子独立调度，批量重试先失效旧产物再发布生命周期消息。

前端新鲜证据：

| Evidence | Command | Result | Scope |
|---|---|---|---|
| E-PLATFORM-007 | `npm test -- --run src/test/parseQueuePosition.test.tsx` | `3 passed`，退出码 `0` | 通用排队数字、无阶段/无运行数、processing/unavailable 通用降级、终态停止 |
| E-CLIENT-007 | `npm run test:ci -- --runInBand src/api/knowledge.test.ts -t getKnowledgeParseQueuePositionsApi` | `1 passed`，退出码 `0` | Client 不读取兼容 `stage`，映射稳定位置字段 |
| E-CLIENT-008 | Portal workbench 定向 `-t`：compact queue positions | `1 passed`，退出码 `0` | 首钢门户按知识库分组、无阶段 queued 文案、processing 原状态 |
| E-CLIENT-009 | Portal workbench 定向 `-t`：原位刷新、unavailable、终态 | `3 passed`，退出码 `0` | 已有表格按 ID 合并字段、失败不清空、终态不查询 |
| E-BUILD-007 | Platform 与 Client `npm run build -- --logLevel error` | 两端退出码 `0` | 两个生产构建均成功，仅保留既有 Browserslist/eval/chunk/Tailwind 警告 |

Client `knowledge.test.ts` 全文件执行时，本次目标用例通过，但另有 3 个既有业务错误 mock 用例失败（`renameFolderApi`、`deleteFolderApi`、`batchDownloadApi`）；随后用 `-t getKnowledgeParseQueuePositionsApi` 隔离复验通过。本次未越界修改这些目录/批量下载错误处理。

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
- `cd src/backend && ./.venv/bin/alembic heads`：`f079_tag_review_audit_fields (head)`；`alembic history -r f077_knowledge_folder_sort_weight:heads` 证明当前线性链为 `f077 -> f078_knowledge_parse_priority -> f049_automotive_sheet_intro_sync_run_log -> f079_tag_review_audit_fields`。
- migration 自动化在 SQLite 执行 upgrade/downgrade，并编译 MySQL/DM-compatible DDL：包含 nullable `VARCHAR(16)` 且历史行保持 `NULL`。
- `git diff --check`：退出码 `0`。
- Client 新增 `PortalUploadQueueStatus.tsx`、`PortalUploadFolderTree.tsx` 与 `usePortalUploadedFiles.ts` 通过 `scripts/arch-guard.sh`；`PortalUploadedFilesDrawer.tsx` 当前为 `562` 行，满足单文件规模门禁。
- 对全部变更和新增文件逐个执行 `scripts/arch-guard.sh`：无新增 violation；现有超长 `knowledge.py` 报告一条 RULE-3 warning，原因是该文件在本功能前已直接导入 `database.models`，本次端点没有新增该类导入。

## 较宽回归诊断

实现中曾运行一个包含大量既有知识空间用例的较宽后端批次，结果为 `379 passed, 104 failed`。该批次未作为通过证据：失败集中在现有大型 `knowledge_space_service` fixture/Mock 与当前服务依赖不一致、既有源码字符串断言，以及本次接口由同步 Mock 变为异步后的直接受影响用例。

本次已修复并重新验证直接受影响的文件同步、重试和标题后继用例，相关定向批次全部通过；未在本功能中重写其余既有大型测试基础设施，也不声称全量 backend suite 通过。

## 2026-08-09 T014 门户上传完成队列名次 Toast

实现结果：

- 后端位置响应增加 nullable `waiting_count`，由 Redis Repository 汇总 high/medium/low 三个 waiting ZSET；publishing 和 processing 不进入该总数，Redis 查询失败时返回 `null` 并沿用原 unavailable 降级。
- Client 对旧后端未返回 `waiting_count` 的响应映射为 `null`；上传成功后只查询可靠的非重复注册文件 ID，超过 100 个 ID 分批请求，使用本批最小 `ahead_waiting_count + 1` 作为 X、对应快照的 `waiting_count` 作为 Y。
- 只有 `ahead_waiting_count > 0` 且 `Y >= X` 时，以一条 success Toast 替换原提示；无排队、响应缺字段、无效 X/Y 或查询失败时继续显示“上传成功”，查询错误不阻断上传。

| Evidence | Command | Result | Scope |
|---|---|---|---|
| E-T014-BACKEND | `./.venv/bin/pytest test/knowledge/test_knowledge_parse_queue_redis.py test/knowledge/test_knowledge_parse_queue_api.py test/knowledge/test_knowledge_parse_priority_dispatch.py test/knowledge/test_knowledge_parse_processing_lease.py test/knowledge/test_knowledge_file_parse_lifecycle.py -q --tb=short` | `31 passed`，退出码 `0` | 三级 waiting 总数、publishing/processing 排除、位置 API、优先级派发、租约与单文件生命周期回归 |
| E-T014-CLIENT-API | `npx jest --runInBand --coverage=false src/api/knowledge.test.ts -t getKnowledgeParseQueuePositionsApi` | `2 passed`，退出码 `0` | `waiting_count` 映射及旧后端缺字段时降级为 `null` |
| E-T014-CLIENT-HOOK | `npx jest --runInBand --coverage=false src/pages/knowledge/portal/hooks/usePortalUploadDialog.test.ts -t "aggregate queue position toast\|keeps the original success toast\|separates duplicate files"` | `4 passed`，退出码 `0` | 多文件聚合、无前方任务、查询失败和重复文件流程不触发额外 success Toast |
| E-T014-CLIENT-BATCH | `npx jest --runInBand --coverage=false src/pages/knowledge/portal/portalUploadQueueToast.test.ts` | `1 passed`，退出码 `0` | 101 个文件按 100/1 分批并聚合最前名次 |
| E-T014-BUILD | `npm run build -- --logLevel error` | 退出码 `0` | Client production build；仅保留既有 Browserslist、Tailwind 和 PWA 图标 glob 警告 |
| E-T014-STATIC | 后端受影响文件 `ruff check`、`ruff format --check`，根目录 `bash scripts/arch-guard.sh` | 全部退出码 `0` | Python lint/format 与架构边界 |

补充诊断：完整 `usePortalUploadDialog.test.ts` 执行为 `16 passed, 1 failed`；失败是既有“accepts audio and video files in portal upload selections”用例中 mp3 未进入上传列表，与 T014 的位置查询及 Toast 分支无关。本次未扩大范围修改音视频格式过滤；上表已用目标路径定向用例覆盖本次行为。

## 尚未执行的验收门禁

1. 当前本机 `127.0.0.1:6379` 与 `:36379` 均返回 `ConnectionError`，且没有 `redis-cli`，因此未执行真实 Redis/Kombu 高→中→低与同级 FIFO smoke。
2. 尚未以真实 Worker `-c 1 --prefetch-multiplier=1` 验证三个同优文件按“文件1完整生命周期→文件2完整生命周期→文件3完整生命周期”执行；单消息/单 ticket 已有自动化契约证据，但不替代 broker runtime 证据。
3. 自动化已覆盖 publishing→processing 快路径、同 ticket 多 attempt 与两种结束顺序；尚未用真实 Worker 进程强退验证 90 秒 lease 收敛，也未制造真实 visibility timeout 重叠 delivery。
4. 未连接真实 MySQL/DM8；未对目标数据库执行 Alembic upgrade/downgrade。当前数据库还曾报告存量版本号 `f078_points_system` 不在本代码 migration 图中，必须先按实际部署分支核对/修复版本图，禁止直接 stamp 猜测。DM8 必须由 Linux CI 使用真实驱动验证。
5. 排队 Repository 测试使用真实 `redis-py` API 与 `fakeredis` 执行 Lua/ZSET 行为，但不等同于真实 Redis Cluster/Sentinel 集成。
6. API 安全行为目前由 domain/service 定向测试覆盖，尚未用真实登录会话执行未登录、跨租户、跨知识库和完整部门审批矩阵的 HTTP 集成测试。
7. Platform/Client 无阶段文案、构建、门户原位刷新和上传完成名次 Toast 已经自动化通过；尚未连接真实 API/Celery 做浏览器端动态排队位置及名次 Toast smoke。

## 发布前人工/CI清单

1. 在非生产 Redis 启动 `knowledge_celery` Worker，固定 `-c 1 --prefetch-multiplier=1`，交错发布低/中/高任务并记录高→中→低和同级 FIFO。
2. 发布三个同优初次解析文件，确认每个文件从领取即 PROCESSING 到正式解析终态连续占用同一 delivery；标题失败仍进入正式解析；重试执行清理但不执行标题；正常尝试内部不换 ticket。
3. 验证同文件异常多 ticket、重叠 delivery、Worker 强退租约收敛、Redis 索引断开时业务任务不受影响。
4. 验证新 Worker 可自然消费旧标题/正式解析/重试消息；旧标题消息不得再次发布正式解析后继。按 Worker→producer→frontend 顺序滚动发布，禁止 purge。
5. 在 MySQL 执行 `upgrade f078`、历史行检查与 `downgrade f077`；在 Linux DM8 CI 执行同等门禁。
6. 使用真实权限数据调用批量位置 API，确认不可见、跨租户、跨知识库与不存在 ID 均静默省略。
7. 在 Platform 与首钢门户确认 queued 状态都只显示“排队中，前方约 N 个等待任务”，不展示标题/正式解析/重试阶段；同时确认终态停止、Redis 故障降级、门户自动/手动刷新期间表格不消失且字段原位更新，以及上传成功时有前方任务显示一条“最前第 X/Y 名”Toast、无可靠位置时退回“上传成功”。
8. 回滚时先回滚前端和 producer，确认没有新生命周期消息依赖旧 Worker 后再回滚 Worker；nullable 列可保留。禁止 broker purge、broker key 删除或消息迁移。
