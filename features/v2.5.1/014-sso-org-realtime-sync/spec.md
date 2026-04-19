# Feature: F014-sso-org-realtime-sync (SSO 登录同步部门树)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §5.6.2, §9.2
**优先级**: P1
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团 IT / Gateway 管理员**，
我希望 **Gateway 在用户 SSO 登录时同步部门结构 + 用户属性到 bisheng，并触发叶子 Tenant 派生**，
以便 **bisheng 中的部门树与 HR 系统保持实时一致，无需管理员手工维护**。

核心能力：
- 新增内部接口 `POST /api/v1/internal/sso/login-sync`（HMAC 鉴权；用户登录时触发）
- 新增内部接口 `POST /api/v1/departments/sync`（HMAC 鉴权；Gateway 主动批量推送部门变更；PRD §9.3）
- 处理流程：Upsert 用户 → Upsert 部门树 → 绑定 user_department → 触发 UserTenantSyncService
- 可选 tenant_mapping payload：首次遇到未挂载部门自动 mount（PRD §5.2.3）
- 部门删除后统一调 F011 `DepartmentDeletionHandler.on_deleted(dept_id, 'sso_realtime')` 处理孤儿 Tenant

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | Gateway | POST /internal/sso/login-sync 含新用户 | Upsert user / user_department；派生叶子 Tenant |
| AC-02 | Gateway | 同步已有用户的主部门变更 | user_department.is_primary 更新；触发 UserTenantSyncService.sync_user |
| AC-03 | Gateway | payload 含 tenant_mapping | 首次 mount 目标部门；幂等：同一部门已 mount 则忽略 |
| AC-04 | Gateway | 通过 `POST /api/v1/departments/sync` 提交部门删除 | `Department.is_deleted=1` 后**调用** `DepartmentDeletionHandler.on_deleted(dept_id, 'sso_realtime')`（F011 §5.4.1）统一处理孤儿 Tenant |
| AC-05 | 集团超管 | orphaned Tenant 产生（由 F011 handler 触发） | audit_log（action=`tenant.orphaned`）+ 站内消息 + 邮件；本 feature 仅触发 handler 调用，具体写入逻辑在 F011 |
| AC-06 | 开发 | HMAC 鉴权失败 | 返回 401；记录告警日志 |
| AC-07 | 性能 | 10 万人登录峰值并发 | P99 < 500ms（包含 SSO 同步 + 派生 + JWT 签发） |
| AC-08 | 开发 | payload 含 `ts` 字段 | 必填；写入 `org_sync_log.last_sync_ts` 供 F015 冲突处理消费（INV-T12） |
| AC-09 | 开发 | payload `ts` < `external_id` 已记录的 `last_sync_ts` | 跳过该消息 + 写 org_sync_log warn（按 ts 最大为准；INV-T12） |
| AC-10 | Gateway | `POST /api/v1/departments/sync` 批量 upsert | 按 `external_id` 增量 upsert 部门；HMAC 鉴权失败返回 401；每条变更独立走 §5.5 ts 冲突守卫；写 org_sync_log |
| AC-11 | Gateway | `POST /api/v1/departments/sync` 批量 remove | 每个 remove 先校验 ts 冲突（INV-T12）→ 通过则 `Department.is_deleted=1` → 调用 `DepartmentDeletionHandler.on_deleted(dept_id, 'sso_realtime')`；逐项处理，单项失败不影响其他 |

---

## 3. 边界情况

- **SSO 端 external_id 稳定**：本 Feature 假定 external_id 稳定；换型迁移见 F015
- **部门批量变更**：单次同步单个用户；批量部门变更由 `/departments/sync` API 承接
- **Tenant 禁用状态下登录**：阻断登录并返回提示
- **并发同步**：同一 user_id 使用 Redis 分布式锁 SETNX 去重

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | SSO 同步时机 | A: 登录时 / B: 事件驱动 | A（简单可靠） |
| AD-02 | tenant_mapping 幂等 | A: 以 SSO 为准 / B: 以 bisheng 为准 | B（PRD §5.2.3）|

---

## 5. API 设计

### 5.1 SSO 登录同步（实时，用户登录时触发）

```
POST /api/v1/internal/sso/login-sync
Header: X-Signature (HMAC)
Body: {
  "external_user_id": "...",
  "primary_dept_external_id": "...",
  "secondary_dept_external_ids": [...],
  "user_attrs": {"name": "...", "email": "..."},
  "root_tenant_id": 1,
  "tenant_mapping": [                             # 可选
    {"dept_external_id": "...", "tenant_code": "...", "tenant_name": "...", "initial_quota": {...}, "initial_admin_external_ids": [...]}
  ],
  "ts": 1713400000
}
Returns: {"user_id": 7, "leaf_tenant_id": 15, "token": "..."}
```

### 5.2 批量部门同步（Gateway 主动推送，新增 / 2026-04-21 承接 PRD §9.3）

```
POST /api/v1/departments/sync
Header: X-Signature (HMAC)
Body: {
  "upsert": [
    {"external_id": "D001", "name": "研发部", "parent_external_id": "D000", "sort": 1, "ts": 1713400000},
    {"external_id": "D002", "name": "市场部", "parent_external_id": "D000", "sort": 2, "ts": 1713400001}
  ],
  "remove": ["D099", "D100"],
  "source_ts": 1713400100                         # 批次 ts；当条目无 ts 时回退使用
}
Returns: {"applied_upsert": N, "applied_remove": M, "skipped_ts_conflict": K, "orphan_triggered": [tenant_id, ...]}
```

**处理流程**：

1. HMAC 鉴权（由 `HmacAuthMiddleware` 实施）：
   - 算法：HMAC-SHA256
   - 密钥来源：`config.sso_sync.gateway_hmac_secret`（YAML 或环境变量 `BS_SSO_SYNC__GATEWAY_HMAC_SECRET`）
   - 签名 Header：`X-Signature`（十六进制小写）
   - 签名原文：`HTTP Method + "\n" + Path + "\n" + raw body`（body 参与；避免重放参考 5 分钟时间窗口可选 `X-Timestamp`，MVP 不强制）
   - 失败返 **401 + 19301**
   - 密钥轮换：grace period 由客户流程承接（MVP 不实现 dual-key）
2. 逐条 upsert：调用 `OrgSyncTsGuard._check_ts_conflict(external_id, ts)` → 通过则 upsert Department，更新 last_sync_ts
3. 逐条 remove：同 ts 守卫 → `Department.is_deleted=1` → 调用 **F011 `DepartmentDeletionHandler.on_deleted(dept_id, 'sso_realtime')`**（本 feature 仅触发 handler 调用，不实现孤儿处理逻辑）
4. 批次结束后返回汇总统计

**与 F015 Celery 校对的关系**：F015 校对使用的 ts 冲突规则（§5.5.2）与本端点共享 `OrgSyncTsGuard` 服务；两者通过同一 `last_sync_ts` 字段协调，确保不同路径应用同一规则（INV-T12）。

---

## 6. 依赖

- F011-tenant-tree-model（`DepartmentDeletionHandler` 孤儿处理入口；**本 feature 仅在 remove 流程调用 `on_deleted(dept_id, 'sso_realtime')`，不实现孤儿处理逻辑**——audit_log / Tenant.orphaned 切换 / 站内消息告警均由 F011 §5.4.1 承载）
- F012-tenant-resolver（UserTenantSyncService）
- v2.5.0/F009-org-sync（OrgSyncProvider 抽象 + HMAC 中间件；若已有 `/departments/sync` 端点，本 feature 扩展其 payload 支持 ts + tenant_mapping 字段）
- v2.5.0/F002-department-tree（Department upsert）

---

## 7. 手工 QA 清单

- [ ] 新用户首次登录成功 + 叶子 Tenant 正确派生
- [ ] 主部门变更触发 sync_user
- [ ] tenant_mapping 首次生效、二次忽略
- [ ] 部门删除后 Tenant 进入 orphaned + 告警
- [ ] HMAC 鉴权失败拦截
- [ ] 10 万人并发压测 P99 < 500ms

---

## 8. 错误码

- **MMM=193** (tenant_sync)
- 19301: HMAC 签名无效
- 19302: 部门挂载冲突
- 19303: 用户 Tenant 禁用
