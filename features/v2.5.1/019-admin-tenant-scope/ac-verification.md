# F019-admin-tenant-scope AC 对照表

**生成时间**: 2026-04-21
**分支**: `feat/v2.5.1/019-admin-tenant-scope`（base=`2.5.0-PM`，commit `81e597690`）
**Worktree**: `/Users/lilu/Projects/bisheng-worktrees/019-admin-tenant-scope`
**F019 测试套件（新增）**: 5 个文件，~33 个用例
  - `test_admin_tenant_scope_service.py` — 10 用例（Service 单测）
  - `test_admin_tenant_scope_api.py` — 9 用例（HTTP 集成）
  - `test_admin_scope_middleware.py` — 8 用例（Middleware）
  - `test_logout_scope_clear.py` — 2 用例（AC-10 钩子）
  - `test_sync_user_scope_clear.py` — 3 用例（AC-11 钩子）
  - `test_admin_scope_cleanup_task.py` — 4 用例（Celery 巡检）
**回归目标**: F011/F012/F013/F016/F017 原有测试无破坏；v2.5.0 基线维持。

---

## AC → 测试映射（全部 16 条）

| AC | 描述 | 自动化测试 | 手工 QA |
|----|------|-----------|---------|
| **AC-01** | 全局超管 POST `{tenant_id: 5}` → 200 + `scope_tenant_id=5` + Redis TTL≈14400 | `test_admin_tenant_scope_service.py::test_set_scope_first_time` + `test_set_scope_override_existing` + `test_admin_tenant_scope_api.py::TestSetTenantScope::test_super_admin_success` | 114 手工验证清单 §1 |
| **AC-02** | 超管 GET → `{scope_tenant_id, expires_at}`（ISO 格式 + 剩余 TTL） | `test_get_scope_empty` + `test_get_scope_with_value` + `TestGetTenantScope::test_super_admin_returns_current` + `test_super_admin_empty_scope_returns_nulls` | §2 |
| **AC-03** | POST `{tenant_id: null}` → 200 + Redis DEL + 后续 GET 返 null | `test_set_scope_clear_with_none` + `TestSetTenantScope::test_clear_scope_via_null` | §3 |
| **AC-04** | Child Admin POST → HTTP 403 + body.status_code=19701 | `TestSetTenantScope::test_child_admin_forbidden_19701` + `TestGetTenantScope::test_child_admin_get_forbidden_19701` | §4 |
| **AC-05** | 普通用户 POST → HTTP 403 + 19701 | `TestSetTenantScope::test_normal_user_forbidden_19701` | §5 |
| **AC-06** | 超管已设 scope=5 调管理类 API → ContextVar=5（查询按 IN(5,1) 过滤由 F020 消费） | `test_admin_scope_middleware.py::TestScopeInjection::test_super_admin_with_scope_key_injects_and_refreshes_ttl` | §6（需 F020 联调） |
| **AC-07** | 超管已设 scope=5 调业务 API（`/chat`）→ 不受影响，ContextVar=None | `TestManagementApiDetection::test_non_mgmt_path_marks_is_management_false` | §7 |
| **AC-08** | 每次管理类 API 命中刷新 Redis TTL（滑动） | `test_set_scope_ttl_applied` + `TestScopeInjection::test_super_admin_with_scope_key_injects_and_refreshes_ttl`（assert `expire_calls`） | §8 |
| **AC-09** | 超过 TTL 未调用 → Redis 过期 → 再调回退"看全树" | `TestScopeInjection::test_super_admin_without_scope_key_leaves_context_none`（Redis 无值 = TTL 过期语义等价） | §9 |
| **AC-10** | logout → Redis DEL `admin_scope:{user_id}` | `test_clear_on_logout_deletes_key` + `test_clear_hooks_all_delegate_to_same_del` + `test_logout_scope_clear.py::test_logout_clears_scope_for_authenticated_user` | §10 |
| **AC-11** | `user.token_version +1`（主部门变更）→ Redis DEL | `test_sync_user_scope_clear.py::test_cross_tenant_relocation_clears_scope` + `test_scope_clear_failure_does_not_break_relocation` | §11 |
| **AC-12** | 超管角色撤销 → Redis DEL | `test_clear_hooks_all_delegate_to_same_del`（方法本体）；**T10 方案 2**：挂接点当前无公开 API，文档化 TODO（见 `role-revoke-hook.md`），中间件 `_check_is_global_super` 每次再校验兜底 AC-12 可观察行为 | §12（不适用，通过中间件验证） |
| **AC-13** | Celery 10min 巡检，清理指向非 active Tenant 的 key | `test_admin_scope_cleanup_task.py::test_cleanup_removes_non_active_scopes` + `test_cleanup_noop_when_no_keys` + `test_cleanup_noop_when_all_active` + `test_cleanup_removes_corrupt_value` | §13 |
| **AC-14** | 每次 POST 写 `audit_log`，action=`admin.scope_switch`，含 `from_scope/to_scope/ip/user_agent/operator_id` | `test_set_scope_audit_uses_root_operator_tenant_id`（assert all fields） + `test_set_scope_first_time`（from_scope=None） + `test_set_scope_override_existing`（from_scope=3→5） | §14 |
| **AC-15** | POST 指向不存在 Tenant → HTTP 400 + 19702 | `test_set_scope_tenant_not_found_raises_19702` + `TestSetTenantScope::test_invalid_tenant_id_returns_19702` | §15 |
| **AC-16** | POST `{tenant_id: 1}`（Root）允许；等价"锁定看 Root 视图" | `TestSetTenantScope::test_root_as_scope_accepted` | §16 |

---

## 架构决策（§4 AD-01~07）落地证据

| AD | 决策 | 落地证据 |
|----|------|---------|
| AD-01 | 存储介质：Redis（非 JWT/非 MySQL）| `admin/domain/services/tenant_scope.py` 只写 `admin_scope:{user_id}` Redis key；JWT 未改 |
| AD-02 | 滑动 TTL | `common/middleware/admin_scope.py` 每次 mgmt API 命中调 `aexpire_key` |
| AD-03 | TTL=4h | `core/config/multi_tenant.py::admin_scope_ttl_seconds=14400` |
| AD-04 | 仅管理类 API | `common/middleware/admin_scope.py::MANAGEMENT_API_PREFIXES = ('/llm', '/roles', '/audit_log', '/admin')` |
| AD-05 | 仅全局超管 | Endpoint 层 `_check_is_global_super` 守卫 + Middleware 层 fail-closed 再校验 |
| AD-06 | 非超管 403 | `AdminScopeForbiddenError(Code=19701)` → HTTP 403 via `_errcode_to_response` |
| AD-07 | Child 禁用后 Celery 巡检（非实时钩子）| `worker/admin_scope/tasks.py` + beat `*/10 * * * *` |

---

## §5 代码骨架落地清单

| spec §5 节 | 文件 | 状态 |
|-----|------|------|
| §5.1 API 端点 | `admin/api/endpoints/tenant_scope.py` | ✅ POST + GET + errcode→HTTP 映射 |
| §5.2 Service | `admin/domain/services/tenant_scope.py` | ✅ `set_scope/get_scope/clear_on_logout/clear_on_token_version_bump/clear_on_role_revoke` |
| §5.3 中间件 | `common/middleware/admin_scope.py` | ✅ 白名单 + 超管 fail-closed + 滑动刷新 |
| §5.4 Celery | `worker/admin_scope/tasks.py` | ✅ `bypass_tenant_filter` 包裹 + beat `*/10 * * * *` |

---

## §8 关键文件落地清单

| 类别 | 文件 | 改动 |
|------|------|------|
| 新建 | `bisheng/common/errcode/admin_scope.py` | 19701/19702 |
| 新建 | `bisheng/admin/__init__.py` + `api/`, `api/endpoints/`, `domain/`, `domain/services/` | 模块骨架 |
| 新建 | `bisheng/admin/domain/services/tenant_scope.py` | `TenantScopeService` |
| 新建 | `bisheng/admin/api/endpoints/tenant_scope.py` | POST/GET endpoints |
| 新建 | `bisheng/admin/api/router.py` | admin router |
| 新建 | `bisheng/common/middleware/__init__.py` + `admin_scope.py` | `AdminScopeMiddleware` |
| 新建 | `bisheng/worker/admin_scope/__init__.py` + `tasks.py` | Celery `admin_scope_cleanup` |
| 新建 | `src/frontend/platform/src/controllers/API/admin.ts` | axios `setTenantScope` / `getTenantScope` |
| 修改 | `bisheng/core/config/multi_tenant.py` | `admin_scope_ttl_seconds=14400` |
| 修改 | `bisheng/core/config/settings.py` | beat schedule + task_routers |
| 修改 | `bisheng/core/cache/redis_conn.py` | 加 `attl(key)` helper |
| 修改 | `bisheng/tenant/domain/constants.py` | `TenantAuditAction.ADMIN_SCOPE_SWITCH` |
| 修改 | `bisheng/main.py` | 注册 `AdminScopeMiddleware`（在 `CustomMiddleware` **之前** 添加，使其入站顺序在 Custom 之后） |
| 修改 | `bisheng/api/router.py` | `include_router(admin_router)` |
| 修改 | `bisheng/user/api/user.py` | `logout` 调 `clear_on_logout` |
| 修改 | `bisheng/tenant/domain/services/user_tenant_sync_service.py` | `sync_user` 成功路径调 `clear_on_token_version_bump` |
| 文档 | `features/v2.5.1/019-admin-tenant-scope/role-revoke-hook.md` | T10 方案 2 调研笔记 |

---

## 错误码（spec §5）

| 错误码 | 类 | HTTP 状态 | 使用位置 |
|--------|-----|----------|---------|
| 19701 | `AdminScopeForbiddenError` | 403 | Endpoint `_check_is_global_super` 失败 |
| 19702 | `AdminScopeTenantNotFoundError` | 400 | Service `set_scope` 校验 tenant_id 不存在时抛 |

---

## 手工 QA（114 环境）

> 执行时机：T13 本地回归通过后。前置要求：已有全局超管账号（user_id=1）+ ≥1 个 Child Tenant。

### §1 AC-01 happy path
```bash
# 以 admin 登录取 Cookie
curl -b jar -c jar -X POST http://192.168.106.114:7860/api/v1/user/login \
  -H 'Content-Type: application/json' \
  -d '{"user_name": "admin", "password": "Bisheng@top1"}'

# POST scope=5
curl -b jar -X POST http://192.168.106.114:7860/api/v1/admin/tenant-scope \
  -H 'Content-Type: application/json' -d '{"tenant_id": 5}'
# 期望：200，body.data.scope_tenant_id=5，body.data.expires_at≠null
```

### §2 AC-02 GET
```bash
curl -b jar http://192.168.106.114:7860/api/v1/admin/tenant-scope
# 期望：200，body.data.scope_tenant_id=5
```

### §3 AC-03 clear
```bash
curl -b jar -X POST http://192.168.106.114:7860/api/v1/admin/tenant-scope \
  -H 'Content-Type: application/json' -d '{"tenant_id": null}'
curl -b jar http://192.168.106.114:7860/api/v1/admin/tenant-scope
# 期望：后续 GET 返 {scope_tenant_id: null, expires_at: null}
```

### §4 AC-04 Child Admin
```bash
# 以 Child Admin 账号登录
# POST → HTTP 403 + body.status_code=19701
```

### §5 AC-05 普通用户
```bash
# 以普通用户登录
# POST → HTTP 403 + 19701
```

### §6 AC-06（需 F020 联调）
```bash
# 超管 scope=5 后 GET /api/v1/llm → 只见 Child 5 本地 + Root 共享
```

### §7 AC-07 业务 API 不受影响
```bash
# 超管 scope=5 后 POST /api/v1/chat/... → 按 JWT leaf 执行，不过滤
```

### §8 AC-08 滑动 TTL
```bash
# 超管 scope=5 → 等 3 分钟 → GET /api/v1/llm（命中中间件）
# → Redis TTL 应刷新回 ~14400
# redis-cli TTL admin_scope:1 → 预期 > 14000
```

### §9 AC-09 自然过期
```bash
# 方式 1（慢）：scope=5 后 4h+ 不操作，再调 → 回退
# 方式 2（快）：redis-cli DEL admin_scope:1 → GET → 应回退（ContextVar=None）
```

### §10 AC-10 logout
```bash
curl -b jar -X POST http://192.168.106.114:7860/api/v1/admin/tenant-scope \
  -H 'Content-Type: application/json' -d '{"tenant_id": 5}'
curl -b jar -X POST http://192.168.106.114:7860/api/v1/user/logout
# redis-cli EXISTS admin_scope:1 → 期望 0
```

### §11 AC-11 token_version+1
```bash
# 手工调 POST /api/v1/departments/... 变更超管主部门（跨 Tenant）
# → UserTenantSyncService.sync_user 执行
# redis-cli EXISTS admin_scope:1 → 期望 0
```

### §12 AC-12（通过中间件 fail-closed 兜底）
```bash
# 当前无 API 可撤销 super_admin（见 role-revoke-hook.md）
# 验证中间件兜底：redis-cli SET admin_scope:999 5  # 模拟一个非超管的 stale key
# 以 user_id=999 普通用户登录，调 GET /api/v1/llm
# 中间件 _check_is_global_super 返 False → 不注入 scope
```

### §13 AC-13 Celery 巡检
```bash
# 1. scope=5 后 禁用 Child 5：PUT /api/v1/tenants/5/status {status: 'disabled'}
# 2. 等 10 分钟（或 celery beat 手动触发 admin_scope_cleanup）
# 3. redis-cli EXISTS admin_scope:1 → 期望 0
```

### §14 AC-14 audit_log
```bash
# scope=5 后：
# mysql> SELECT id, tenant_id, operator_id, operator_tenant_id, action, audit_metadata
#        FROM audit_log
#        WHERE action='admin.scope_switch'
#        ORDER BY id DESC LIMIT 5;
# → 最新一行 metadata 含 from_scope / to_scope / ip / user_agent
```

### §15 AC-15 不存在的 Tenant
```bash
curl -b jar -X POST http://192.168.106.114:7860/api/v1/admin/tenant-scope \
  -H 'Content-Type: application/json' -d '{"tenant_id": 99999}'
# 期望：HTTP 400 + body.status_code=19702
```

### §16 AC-16 Root 作为 scope
```bash
curl -b jar -X POST http://192.168.106.114:7860/api/v1/admin/tenant-scope \
  -H 'Content-Type: application/json' -d '{"tenant_id": 1}'
# 期望：200 + scope_tenant_id=1
# ContextVar 注入后，管理类 API 见集合 = {1}（Root 视图，无 Child 可见）
```

---

## 自动化回归命令

```bash
# 单独 F019 专项
ssh root@192.168.106.114 "cd /opt/bisheng/src/backend && \
  /root/.local/bin/uv run pytest \
    test/test_admin_tenant_scope_service.py \
    test/test_admin_tenant_scope_api.py \
    test/test_admin_scope_middleware.py \
    test/test_logout_scope_clear.py \
    test/test_sync_user_scope_clear.py \
    test/test_admin_scope_cleanup_task.py -v"

# 全量（F011/F012/F013/F016/F017 回归）
ssh root@192.168.106.114 "cd /opt/bisheng/src/backend && \
  /root/.local/bin/uv run pytest -q"
```

---

## 开发实际偏差（待 114 回归后补录）

_待在 114 跑完 pytest 后回填本节。_

---

## 遗留事项

- **AC-12 挂接点**：当前版本无公开 API 撤销 super_admin。`TenantScopeService.clear_on_role_revoke` 方法已就位，等未来 RoleService 落地时 3 行接入（详见 `role-revoke-hook.md`）。
- **F019 → F020 依赖**：`useAdminScope` hook + `AdminScopeSelector` 组件归 F020 拥有；本 Feature 仅提供 axios 封装。
- **AC-06 端到端**：真正的 "GET /api/v1/llm 结果按 IN(5,1) 过滤" 需 F020 `LLMDao` tenant 感知改造到位后联调。
