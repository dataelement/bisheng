# Feature: F015-ldap-reconcile-celery (部门定时校对 + SSO 换型 relink)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §9.4, §9.6
**优先级**: P1
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团 IT**，
我希望 **系统每 6 小时自动校对 SSO 端部门树与 bisheng 内部结构，发现漂移时自动修复；SSO 换 HR 系统时提供 relink 接口重建映射**，
以便 **部门归属长期保持一致，换型不丢失用户归属**。

核心能力：
- Celery Beat 定时任务：每 6h 全量校对 LDAP/OAuth 部门树 vs bisheng
- 漂移处理策略：新增/命名变更自动同步；删除进入 orphaned；移动触发 UserTenantSyncService
- **Gateway 实时 vs Celery 校对冲突处理**（INV-T12，PRD §9.5）：每 external_id 维护 `last_sync_ts`，按 ts 最大为准；同 ts 下 upsert+remove 冲突以 remove 为准
- 新增 `POST /api/v1/internal/departments/relink`：SSO 换型时 path+name 回落匹配
- 冲突列表需管理员 UI 逐项确认

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 系统 | Celery Beat 定时触发 | 每 6h 执行一次 SSO 全量校对 |
| AC-02 | 系统 | 发现 SSO 新部门 | 自动 upsert，mount 状态保留（不动标记） |
| AC-03 | 系统 | 发现 SSO 删除部门 | bisheng 标记 is_deleted；挂载点进入 orphaned |
| AC-04 | 系统 | 发现主部门跨 Tenant 变更 | 触发 UserTenantSyncService |
| AC-05 | 运维 | POST /internal/departments/relink（策略 external_id_map） | 显式映射应用成功 |
| AC-06 | 运维 | POST /internal/departments/relink（策略 path_plus_name） | 单候选自动 apply；多候选返回 conflicts 列表 |
| AC-07 | 运维 | relink dry_run=true | 返回 would_apply 清单但不写入 |
| AC-08 | 性能 | 10 万部门全量校对 | 执行时间 < 30 min；MySQL/Redis 压力可控（TBD 基线） |
| AC-09 | 系统 | Gateway 实时同步 ts=T1 后 Celery 校对推送 ts=T0 (T0 < T1) | 跳过该 Celery 消息 + 写 `org_sync_log` level=warn；不覆盖 bisheng 当前状态 |
| AC-10 | 系统 | Celery 校对推送 ts=T2 (T2 > T1) | 应用变更；更新 `last_sync_ts=T2` |
| AC-11 | 系统 | 同 ts 下 upsert（Gateway）和 remove（Celery）冲突 | 以 remove 为准（从严，避免幽灵部门）；写 audit_log + 站内消息；remove 应用后调用 **F011 `DepartmentDeletionHandler.on_deleted(dept_id, 'celery_reconcile')`** 统一处理孤儿 Tenant |
| AC-12 | 系统 | 单 external_id 一周内出现 ≥3 次冲突 | Celery Beat `report_ts_conflicts_weekly` 每周一 09:00 聚合过去 7 天 `audit_log.action='dept.sync_conflict'` + `org_sync_log.event_type='ts_conflict'`；对同 external_id 冲突 ≥3 次的条目发送全局超管（站内消息 + 邮件）；payload 含冲突详情 + `是否需要 relink` 建议 + 本周总冲突数；连续 5 天未解决则升级至每日一次（由 Celery daily beat 独立任务 `report_ts_conflicts_daily_escalation` 检测周报发送后的"未解决"信号） |
| AC-13 | 系统 | 并发同 external_id 同 ts 的两条同方向消息 | 通过 Redis SETNX 去重；幂等返回 |

---

## 3. 边界情况

- **校对期间部门变更**：使用 Redis 锁避免并发同步
- **relink 冲突长期未解决**：5 天告警升级
- **SSO 端暂时不可用**：校对跳过本轮，下次重试

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | 校对频率 | A: 6h / B: 1h / C: 24h | A（PRD §9.4） |
| AD-02 | relink 冲突处理 | A: 自动最近匹配 / B: 人工确认 | B（避免误操作） |
| AD-03 | 实时 vs 校对冲突 | A: 实时优先 / B: 最新 ts 优先 / C: 校对优先 | B（PRD §9.5 / INV-T12）：以源系统 ts 最大为准，与同步发起方无关 |
| AD-04 | 同 ts upsert+remove 冲突 | A: 以 upsert 为准 / B: 以 remove 为准 | B（从严处理，避免保留 SSO 已删除的幽灵部门）|

---

## 5. API 设计

```
POST /api/v1/internal/departments/relink
Body: {
  "old_external_ids": [...],
  "matching_strategy": "external_id_map" | "path_plus_name",
  "external_id_map": {...},
  "dry_run": false
}
Returns: {"applied": [...], "conflicts": [...]}

POST /api/v1/internal/departments/relink/resolve-conflict
Body: {"dept_id": ..., "chosen_new_external_id": "..."}
```

## 5.5 Gateway 实时 vs Celery 校对冲突处理（INV-T12，PRD §9.5）

### 5.5.1 last_sync_ts 字段维护

每条同步消息（无论来自 Gateway 实时还是 Celery 校对）携带 `ts` 字段（源系统时间戳，单位秒）。

bisheng 为每个 `Department.external_id` 维护：

```sql
-- 已存在的 org_sync_log 表新增 last_sync_ts 索引视图
SELECT external_id, MAX(source_ts) AS last_sync_ts
FROM org_sync_log
WHERE level IN ('info', 'warn')
GROUP BY external_id;
```

或在 `Department` 表加 `last_sync_ts BIGINT DEFAULT 0` 列（性能更好）。

### 5.5.2 冲突处理决策表

| incoming ts vs last_sync_ts | 动作 |
|----------------------------|------|
| incoming.ts > last_sync_ts | 应用变更 + 更新 last_sync_ts |
| incoming.ts == last_sync_ts，同 source 同方向 | 幂等跳过（已应用） |
| incoming.ts == last_sync_ts，upsert + remove 双向 | **以 remove 为准**（从严，避免幽灵部门；INV-T12）：① `Department.is_deleted=1` → ② 调用 **F011 `DepartmentDeletionHandler.on_deleted(dept_id, 'celery_reconcile')`** → ③ 写 `audit_log.action='dept.sync_conflict'` + 站内消息告警全局超管；不可回滚 |
| incoming.ts < last_sync_ts | **跳过**该消息；写 org_sync_log level=warn（"陈旧消息丢弃"） |

### 5.5.3 冲突告警

- 单 external_id 一周内 ≥3 次冲突 → 周报告汇总站内消息给全局超管
- 数据库写入失败（FK 冲突等）单独走错误码 19302 路径
- 所有冲突跳过事件留痕 30 天

**冲突计数实现**（2026-04-21 明确）：

```sql
-- 统计单 external_id 过去 7 天的冲突次数（决定是否发周报告警）
SELECT COUNT(*)
FROM org_sync_log
WHERE level = 'warn'
  AND event_type = 'ts_conflict'
  AND external_id = :external_id
  AND create_time > NOW() - INTERVAL 7 DAY;
```

**索引要求**：

- `org_sync_log` 表需存在复合索引 `idx_conflict_lookup (level, event_type, external_id, create_time)`
- 若 v2.5.0/F009 创建的 `org_sync_log` 表无此索引，本 feature 的 DDL 补丁文件需加：
  ```sql
  ALTER TABLE org_sync_log
      ADD INDEX idx_conflict_lookup (level, event_type, external_id, create_time);
  ```
- 若 `event_type` 字段不存在，本 feature 补：
  ```sql
  ALTER TABLE org_sync_log
      ADD COLUMN event_type VARCHAR(32) NOT NULL DEFAULT '' COMMENT '事件类型：ts_conflict / upsert / remove 等';
  ```

**周报任务**：新增 Celery Beat 任务 `report_ts_conflicts_weekly`（每周一 09:00 执行），聚合上周所有冲突按 external_id / count 排序，发送全局超管站内消息。

### 5.5.4 实现位置

- Celery 任务 `sync_organization_from_ldap` 入口处加 `_check_ts_conflict()` 守卫
- Gateway 实时端点 `POST /internal/sso/login-sync` 同样调用此守卫
- 共享 `OrgSyncTsGuard` service

---

## 6. 依赖

- F014-sso-org-realtime-sync（SSO 同步框架）
- F012-tenant-resolver（UserTenantSyncService）

---

## 7. 自测清单（对应 AC）

> 开发者在完成实现后必须自行运行以下测试；不依赖用户/产品人肉点击。不可自动化项明确标 `[发版前专项]`。

| Test | AC | 类型 | 备注 |
|------|----|------|------|
| `test_celery_beat_scheduled_every_6h` | AC-01 | Celery 单元测试 | 校验 beat schedule 注册 + 周期 |
| `test_reconcile_upsert_new_dept_preserves_mount` | AC-02 | pytest 集成测试 | 新部门 upsert 不动挂载标记 |
| `test_reconcile_removes_dept_triggers_handler` | AC-03 | pytest 集成测试 | 触发 F011 `DepartmentDeletionHandler` |
| `test_reconcile_primary_dept_change_triggers_sync_user` | AC-04 | pytest 集成测试 | UserTenantSyncService 被调用；token_version +1 |
| `test_relink_external_id_map_strategy` | AC-05 | pytest 集成测试 | 显式 external_id 映射应用 |
| `test_relink_path_plus_name_single_candidate_auto_apply` | AC-06 | pytest 集成测试 | 单候选自动 apply |
| `test_relink_path_plus_name_multi_candidate_conflict` | AC-06 | pytest 集成测试 | 多候选返回 conflicts 列表 |
| `test_relink_dry_run_no_write` | AC-07 | pytest 单元测试 | dry_run 返回 would_apply，无 DB 写入 |
| `test_ts_guard_skips_stale_celery_push` | AC-09 | pytest 单元测试 | T0 < T1 跳过 + warn 日志 |
| `test_ts_guard_applies_newer_celery_push` | AC-10 | pytest 单元测试 | T2 > T1 应用变更 + 更新 last_sync_ts |
| `test_same_ts_upsert_vs_remove_prefers_remove` | AC-11 | pytest 集成测试 | 同 ts 冲突以 remove 为准 + audit_log |
| `test_report_ts_conflicts_weekly_notifies_super_admin` | AC-12 | Celery 单元测试 | 周报聚合 ≥3 次冲突 + 站内消息/邮件 |
| `test_report_ts_conflicts_daily_escalation` | AC-12 | Celery 单元测试 | 周报后 5 天未解决升级至每日 |
| `test_concurrent_same_ts_deduped_by_redis_setnx` | AC-13 | pytest 集成测试 | Redis SETNX 幂等 |

**发版前专项**（不在 CI/自测范围）：
- AC-08：10 万部门全量校对压测 < 30 min（发版前 2 周专项，MySQL/Redis 压力基线 TBD）

---

## 8. 错误码

- **MMM=193** (tenant_sync 复用)
- 19310: 校对锁冲突
- 19311: relink 策略不支持
- 19312: relink 冲突未解决
- 19313: 同步消息 ts 陈旧已跳过（INV-T12，PRD §9.5）
- 19314: 同 ts 下 upsert/remove 冲突（已按 remove 为准应用 + 告警）
