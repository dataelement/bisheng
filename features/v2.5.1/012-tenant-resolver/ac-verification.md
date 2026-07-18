# F012-tenant-resolver AC 对照表

**生成时间**: 2026-04-19
**分支**: `feat/v2.5.1/012-tenant-resolver`（base=`2.5.0-PM`）
**F012 测试套件**: 77 tests passed / 9 files
**F011 回归**: 85 tests passed（无回归）
**v2.5.0 回归**: 553 passed（与 F011 完成时的基线一致；其余 16 failed + 38 errors 皆为 v2.5.0 先前存在的不稳定测试：mineru/paddleocr 文件依赖、e2e HTTP 调用、docx 文件依赖、test_role_service 等与 F012 无关的模块）

---

## AC → 测试映射

| AC | 描述 | 自动化测试 | 手工 QA |
|----|------|---------|---------|
| **AC-01** | SSO 首次登录沿主部门 path 反向派生叶子 Tenant | `test_tenant_resolver.py::TestResolveUserLeafTenant::test_happy_path_active_mount` + `test_disabled_mount_falls_back_to_parent_mount` + `test_nested_returns_nearest` + `test_no_primary_dept_returns_root` | 手工挂载 Child Tenant 后重登 → JWT `tenant_id=新Child.id` |
| **AC-02** | `user` 表含 `token_version INT NOT NULL DEFAULT 0` | `test_user_token_version_dao.py::TestTokenVersionField::test_token_version_default_zero` + `test_token_version_column_not_nullable` + Alembic `v2_5_1_f012_user_token_version.py` | 本地 MySQL 执行 `alembic upgrade head` 后 `DESC user \| grep token_version` |
| **AC-03** | 无主部门 → `tenant_id=1` + audit `user.tenant_relocated reason=no_primary_department` | `test_user_tenant_sync_service.py::TestFirstTimeSync::test_first_time_sync_root_writes_no_audit_reason_set` + `TestResolveUserLeafTenant::test_no_primary_dept_returns_root` | — |
| **AC-04** | 主部门跨 Tenant 变更 → user_tenant 切换 + token_version+1 + Redis 缓存失效 | `test_user_tenant_sync_service.py::TestRelocateHappy::test_swap_flow_calls_all_collaborators` + `test_fga_rewrite_revokes_old_and_writes_new` + `TestHappyPath::test_promote_new_primary_triggers_sync` | 手工修改 user_department.is_primary → 检查 user_tenant 切换 + Redis key 清空 |
| **AC-05** | 名下资源 > 0 时 audit + 站内消息告警 | `test_user_tenant_sync_service.py::TestRelocateHappy::test_warns_but_proceeds_when_owned_resources_exist` | — |
| **AC-06** | `enforce_transfer_before_relocate=true` 时返 409 `19101` 阻断 | `test_user_tenant_sync_service.py::TestBlocked::test_blocked_when_owned_and_enforce_true` + `test_user_department_service.py::TestBlockedPropagation::test_sync_blocked_raises` | 设置 config 后调 change_primary_department → 抛 19101 |
| **AC-07** | 兼职部门增加不触发 UserTenantSync | `test_user_department_service.py::TestNoOp::test_same_primary_skips_writes_and_sync`（同主部门无 sync） + 设计契约（`UserDepartmentService` 仅负责 primary-dept change；`UserDepartmentDao.aadd_member`/`aremove_member` 入口不调用 sync_user） | 手工 `aadd_member` 添加兼职 → user_tenant 不变 |
| **AC-08** | JWT payload 含 `tenant_id` + `token_version`（不含 tenant_path） | `test_auth_jwt_token_version.py::TestJWTPayload::test_token_version_embedded_in_subject` + `TestCreateAccessTokenClassmethod::test_reads_token_version_from_user` | 使用 jwt.io 解码 Cookie |
| **AC-09** | 旧 JWT `token_version` 不匹配 → 401 | `test_middleware_token_version.py::TestValidateTokenVersion::test_mismatch_returns_false` + `TestApplyTokenVersionAndVisible::test_mismatch_returns_401` | 变更主部门后用旧 Cookie 请求 → 401 `19103` |
| **AC-10** | `GET /api/v1/user/current-tenant` 返回 4 字段 | `test_current_tenant_api.py::TestCurrentTenantHandler::test_root_user_is_child_false` + `test_child_user_reports_mounted_dept` | `curl -b access_token_cookie=... http://localhost:7860/api/v1/user/current-tenant` |
| **AC-11** | `POST /api/v1/user/switch-tenant` 返 410 Gone | `test_current_tenant_api.py::TestSwitchTenantDeprecated::test_switch_tenant_returns_410`（F011 T07 handler 已落地，F012 复用） | `curl -X POST ...switch-tenant` → 410 |

---

## spec §5.4 ContextVar 扩展 契约

| 契约 | 测试 |
|------|------|
| `visible_tenant_ids` ContextVar 存在、默认 None、可 set/reset | `test_tenant_context_vars.py::TestDefaults::test_visible_tenant_ids_default_none` + `TestVisibleTenantIds` |
| `_strict_tenant_filter` + `strict_tenant_filter()` context manager | `TestStrictFilterCM` (enter/exit、嵌套、异常安全) |
| `_admin_scope_tenant_id` 优先级高于 `current_tenant_id` | `TestGetCurrentPriority::test_admin_scope_overrides_current` |
| `_is_management_api` 默认 False、可设置 | `TestDefaults::test_is_management_api_default_false` + `TestIsManagementApi` |
| v2.5.0 签名保留不变 | `TestV25Signatures`（`set_current_tenant_id`, `bypass_tenant_filter`, `get_current_tenant_id` 三者未破坏） |

---

## spec §5.5 Middleware 计算语义

| 语义 | 测试 |
|------|------|
| Root 用户 `visible_tenant_ids = {1}` | `test_middleware_token_version.py::TestComputeVisibleTenantIds::test_root_user_returns_root_only` |
| Child 用户 `visible_tenant_ids = {leaf, 1}` | `test_child_user_returns_leaf_and_root` |
| 全局超管 `visible_tenant_ids = None`（不注入过滤） | `test_super_admin_returns_none` |
| pending 选择 tenant (tenant_id=0) → `frozenset()` | `test_pending_tenant_returns_empty_set` |
| `token_version` 匹配放行 + 设置 visible | `TestApplyTokenVersionAndVisible::test_match_sets_visible_for_child_user` + `test_match_sets_visible_none_for_super` |
| Undecodable 旧 token → 不拦截（交给后续路由 401） | `TestApplyTokenVersionAndVisible::test_undecodable_token_noops` |

---

## Celery 6h reconcile 契约（spec §8.4）

| 契约 | 测试 |
|------|------|
| 分页扫全量 user 表（单批/多批） | `test_tenant_reconcile_task.py::TestReconcileAsync::test_scans_all_users_one_batch` + `test_scans_multiple_batches` |
| 每次调用 sync_user trigger 为 `celery_reconcile` | `TestReconcileAsync`（assert trigger == UserTenantSyncTrigger.CELERY_RECONCILE） |
| `TenantRelocateBlockedError` 被吞掉，不中断其他用户 | `test_blocked_errors_swallowed` |
| 其他未知异常日志 + 继续 | `test_generic_errors_swallowed_with_logging` |
| 空表无副作用 | `test_empty_user_table_noop` |
| Beat schedule 注册 | `src/backend/bisheng/core/config/settings.py::CeleryConf.validate` 追加 `reconcile_user_tenant_assignments`（cron `0 */6 * * *`）+ `task_routers` 加 `bisheng.worker.tenant_reconcile.*` → `knowledge_celery` |

---

## 错误码（spec §9）

| 错误码 | 类 | 使用位置 |
|--------|-----|---------|
| 19101 | `TenantRelocateBlockedError` | `UserTenantSyncService._audit_blocked` 前后抛出 |
| 19102 | `TenantResolveFailedError` | 保留（未来无 Root 时用） |
| 19103 | `TokenVersionMismatchError` | `_apply_token_version_and_visible` 返 401 body |
| 19104 | `TenantCycleDetectedError` | `TenantResolver._walk_from_dept` 检测循环路径 |

---

## 手工 QA（spec §8，待在本地 114 环境执行）

### 8.1 派生逻辑
- [ ] SSO 登录时自动派生正确叶子 Tenant
- [ ] 无主部门用户默认 tenant_id=1
- [ ] 部门树多层挂载（集团→事业部→子公司挂载点）返回最近挂载点
- [ ] Tenant disabled 时派生跳过

### 8.2 主部门变更
- [ ] 跨 Tenant 调岗：user_tenant 旧 inactive、新 active
- [ ] 同 Tenant 调部门：不触发 UserTenantSync
- [ ] 兼职部门增减：无 sync
- [ ] 名下有资源时触发告警，站内消息 + 邮件
- [ ] `enforce_transfer_before_relocate=true` 时阻断主部门变更

### 8.3 JWT
- [ ] 新登录 token 含 `tenant_id` + `token_version`（不含 tenant_path）
- [ ] 主部门变更后 `user.token_version` 自增
- [ ] 旧 token 被拒绝（401）：中间件比对 payload.token_version vs user.token_version
- [ ] IN 列表过滤直接从 tenant_id 推导（leaf + Root=1），无需读 payload 其他字段

### 8.4 Celery 兜底
- [ ] 每 6h 定时任务批量校对所有 active 用户的归属
- [ ] 不一致时自动 sync 并写 audit_log

---

## 开发实际偏差

| 偏差 | 原因 |
|------|-----|
| **T02 DAO-method 测试精简**：spec/tasks.md 原计划 4 个 async DAO 测试（含 Redis mock），实际因 conftest 的 `premock_import_chain` 对 `bisheng.user.domain.models.user` 的预 Mock 与 SQLModel metadata 重注册冲突，改为 6 个 SQL 级行为测试（ORM 默认值、NOT NULL 约束、原子 UPDATE 语义、幂等性）；DAO 方法的 Redis 缓存路径由 T06 `UserTenantSyncService` 集成调用链间接验证 | 避免与 F000 conftest 的预 Mock 结构冲突；实际覆盖仍包含 DAO 读写路径的核心 SQL 语义 |
| **T10 current-tenant 实现位置**：原计划直接在 `user/api/user.py` 添加；实际抽到 `user/api/current_tenant.py` 作为独立 handler 再由 user.py 薄包装 | `user.py` 导入链过重（`bisheng.api.services.assistant` → `bisheng.common.services.base`）导致单测无法 import；抽出后单测可直接调 handler |
| **T11 Celery 任务单测 import 路径**：原计划直接 `from bisheng.worker.tenant_reconcile import tasks`；实际通过 `importlib.util.spec_from_file_location` 旁路加载 | `bisheng.worker/__init__.py` 会引入大量生产级 Celery 任务及 celery.signals 等，测试无法走常规 import |
| **T08 Middleware 改造方式**：原计划提取为独立 `TenantContextMiddleware`；实际在现有 `CustomMiddleware` 中原地增强 | 与 plan §3 Q2 锁定一致——避免破坏 v2.5.0 的 middleware 注册顺序 |

---

## 产物清单

**新建 11 个文件**：
- `src/backend/bisheng/common/errcode/tenant_resolver.py`
- `src/backend/bisheng/core/config/user_tenant_sync.py`
- `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f012_user_token_version.py`
- `src/backend/bisheng/tenant/domain/services/tenant_resolver.py`
- `src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py`
- `src/backend/bisheng/user/domain/services/user_department_service.py`
- `src/backend/bisheng/user/api/current_tenant.py`
- `src/backend/bisheng/worker/tenant_reconcile/__init__.py`
- `src/backend/bisheng/worker/tenant_reconcile/tasks.py`
- `features/v2.5.1/012-tenant-resolver/tasks.md`（本文件所在目录同级）
- `features/v2.5.1/012-tenant-resolver/ac-verification.md`（本文件）

**修改 9 个文件**：
- `src/backend/bisheng/user/domain/models/user.py`（+token_version 字段 + `aget_token_version` / `aincrement_token_version` / `alist_users_paginated` 3 个 classmethod）
- `src/backend/bisheng/core/context/tenant.py`（+4 ContextVar、+3 context manager/setter、`get_current_tenant_id` 优先级规则）
- `src/backend/bisheng/utils/http_middleware.py`（+`_validate_token_version`、`_check_is_global_super`、`_compute_visible_tenant_ids`、`_apply_token_version_and_visible`；`CustomMiddleware.dispatch` 集成）
- `src/backend/bisheng/user/domain/services/auth.py`（`LoginUser.token_version` 字段、`create_access_token` classmethod + `init_login_user(_sync)` + `get_login_user(_from_ws)` 全部 token_version 传递）
- `src/backend/bisheng/user/domain/services/user.py`（login 流程集成 `UserTenantSyncService.sync_user` + `UserDao.aget_token_version` 获取最新版本）
- `src/backend/bisheng/user/api/user.py`（追加 `GET /user/current-tenant` 路由）
- `src/backend/bisheng/tenant/domain/constants.py`（+2 audit action 枚举值 + 新 `UserTenantSyncTrigger` 枚举）
- `src/backend/bisheng/core/config/settings.py`（注册 `UserTenantSyncConf` 字段 + `CeleryConf.validate` 追加 reconcile 任务）
- `src/backend/test/fixtures/table_definitions.py`（TABLE_USER 补 source/external_id/token_version 字段）

**新建 9 个测试文件（77 tests passed）**：
- `test/test_user_token_version_dao.py`（6）
- `test/test_tenant_context_vars.py`（16）
- `test/test_tenant_resolver.py`（12）
- `test/test_user_tenant_sync_service.py`（10）
- `test/test_auth_jwt_token_version.py`（7）
- `test/test_middleware_token_version.py`（13）
- `test/test_user_department_service.py`（5）
- `test/test_current_tenant_api.py`（3）
- `test/test_tenant_reconcile_task.py`（5）

---

## 下游 Feature 解锁

- **F013-tenant-fga-tree**：读 `visible_tenant_ids` 做 IN-list FGA check（`bisheng.core.context.tenant.get_visible_tenant_ids`）
- **F016-tenant-quota-hierarchy**：用 `strict_tenant_filter()` 做精确配额计数
- **F019-admin-tenant-scope**：写 `_admin_scope_tenant_id` + `_is_management_api`；`get_current_tenant_id()` 优先级已就位
- **F020-llm-tenant-isolation**：LLMDao 查询读 `visible_tenant_ids`
- **F014-sso-org-realtime-sync**：直接调 `UserTenantSyncService.sync_user(user_id, trigger='dept_change')` 完成 SSO 主部门变更联动

---

## 回归命令

```bash
# F012 专项（期望 77 passed）
cd src/backend
.venv/bin/python -m pytest \
    test/test_user_token_version_dao.py \
    test/test_tenant_context_vars.py \
    test/test_tenant_resolver.py \
    test/test_user_tenant_sync_service.py \
    test/test_auth_jwt_token_version.py \
    test/test_middleware_token_version.py \
    test/test_user_department_service.py \
    test/test_current_tenant_api.py \
    test/test_tenant_reconcile_task.py -v

# F011 回归（期望 85 passed 维持）
.venv/bin/python -m pytest \
    test/test_tenant_tree_dao.py \
    test/test_user_tenant_leaf.py \
    test/test_department_dao.py \
    test/test_audit_log_v2.py \
    test/test_tenant_service_root_protect.py \
    test/test_tenant_mount_service.py \
    test/test_department_deletion_handler.py \
    test/test_tenant_mount_api.py -v

# v2.5.0 全量回归（排除 e2e/环境依赖）
.venv/bin/python -m pytest test/ \
    --ignore=test/test_api.py \
    --ignore=test/test_celery_tenant.py \
    --ignore=test/test_docx.py \
    --ignore=test/test_es.py \
    --ignore=test/test_filelib.py \
    --ignore=test/test_gpts.py \
    --ignore=test/test_node.py \
    --ignore=test/e2e \
    --ignore=test/test_infrastructure_smoke.py \
    --ignore=test/test_llm.py \
    --ignore=test/test_ws.py
# 期望与 F011 落地时基线一致：约 553 passed + 16 pre-existing failed（role_service、permission_enrichment、mineru/paddleocr/docx 文件依赖）
```
