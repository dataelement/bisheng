# AC Verification — F015-ldap-reconcile-celery

**Feature**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**分支**: `feat/v2.5.1/015-ldap-reconcile-celery` (worktree `/Users/lilu/Projects/bisheng-worktrees/015-ldap-reconcile`)
**最后更新**: 2026-04-20

本文件记录 14 条 AC（AC-01 ~ AC-13 + 边界情况）的自动化 + 手工验证矩阵，供 `/task-review` / `/e2e-test` / `/code-review` 核对。

---

## 1. 自动化覆盖矩阵

| AC | 关键任务 | 测试文件 | 关键用例 |
|----|---------|---------|---------|
| AC-01 Celery Beat 每 6h | T04, T09 | `test_reconcile_celery_tasks.py` | `TestBeatSchedule::test_beat_schedule_registers_reconcile_all_every_6h`<br>`TestFanOut::test_fan_out_dispatches_single_config_per_active_config` |
| AC-02 新 dept 保留 mount | T05, T06 | `test_remote_dept_differ.py`<br>`test_org_reconcile_service.py` | `TestUpserts::test_diff_rename_generates_upsert_op_preserves_existing_id`<br>`TestReconcileHappyBranches::test_reconcile_new_dept_upserts_preserves_mount` |
| AC-03 删除触发 handler | T06 | `test_org_reconcile_service.py` | `TestReconcileHappyBranches::test_reconcile_removed_dept_triggers_department_deletion_handler`（断言 `deletion_source=CELERY_RECONCILE`） |
| AC-04 主部门跨 Tenant | T05, T06 | `test_remote_dept_differ.py`<br>`test_org_reconcile_service.py` | `TestMoveCrossTenant::test_diff_move_across_tenant_marks_crosses_tenant_true`<br>`TestReconcileHappyBranches::test_reconcile_primary_dept_change_triggers_user_tenant_sync`（断言 `trigger=CELERY_RECONCILE`） |
| AC-05 relink external_id_map | T07, T08 | `test_department_relink_service.py`<br>`test_relink_api_integration.py` | `TestExternalIdMapStrategy::test_external_id_map_strategy_applies`<br>`TestRelinkRoute::test_relink_route_responds_200_with_valid_hmac` |
| AC-06 path+name 单/多候选 | T07, T08, T12 | `test_department_relink_service.py`<br>`test_relink_conflict_store.py` | `TestPathPlusNameStrategy::test_path_plus_name_single_candidate_auto_apply`<br>`TestPathPlusNameStrategy::test_path_plus_name_multi_candidate_returns_conflicts`<br>`TestResolveConflict::test_resolve_conflict_applies_chosen_candidate`<br>`TestRelinkConflictStore::test_save_and_get_returns_candidates_list` |
| AC-07 dry_run | T07, T08 | `test_department_relink_service.py`<br>`test_relink_api_integration.py` | `TestDryRun::test_dry_run_returns_would_apply_no_db_write`<br>`TestRelinkRoute::test_relink_dry_run_via_http_returns_would_apply` |
| AC-08 10 万 < 30min | T15 | scripts/performance/locust_ldap_reconcile_100k.py（占位） | **发版前专项**，不在 CI |
| AC-09 stale ts 跳过 | T06, T11 | `test_org_reconcile_service.py` | `TestTsGuardBranches::test_reconcile_stale_ts_skipped_writes_warn_event`<br>`TestEventRowPersistence::test_stale_ts_event_written_with_level_warn_and_event_type_stale_ts` |
| AC-10 新 ts 应用 | T06 | `test_org_reconcile_service.py` | `TestTsGuardBranches::test_reconcile_newer_ts_applies_and_updates_last_sync_ts` |
| AC-11 同 ts remove 优先 | T06, T11 | `test_org_reconcile_service.py` | `TestSameTsRemoveWins::test_reconcile_same_ts_upsert_then_remove_prefers_remove`（断言 audit `dept.sync_conflict` + ts_conflict event 行 + 19317 warn log）<br>`TestEventRowPersistence::test_same_ts_conflict_event_written_with_external_id_and_source_ts` |
| AC-12 周报/升级 | T03, T10, T13 | `test_ts_conflict_reporter.py`<br>`test_reconcile_celery_tasks.py` | `TestWeeklyReport::test_weekly_report_aggregates_conflicts_above_threshold`<br>`TestDailyEscalation::test_daily_escalation_triggers_after_5_days_unresolved`<br>`TestBeatSchedule::test_beat_registers_weekly_conflict_report_monday_09`<br>`TestBeatSchedule::test_beat_registers_daily_escalation_09` |
| AC-13 SETNX 幂等 | T14 | `test_org_reconcile_service.py` | `TestLockSemantics::test_concurrent_same_ts_same_config_deduped_by_setnx`<br>`TestLockSemantics::test_different_config_ids_lock_independently`<br>`TestLockSemantics::test_lock_released_even_on_exception`<br>`TestLockSemantics::test_lock_ttl_30min_prevents_stuck_lock` |

**测试用例统计**：
- test_org_sync_log_dao_f015.py：9 条（T03 + T04）
- test_remote_dept_differ.py：6 条（T05）
- test_org_reconcile_service.py：16 条（T06 + T11 + T14）
- test_department_relink_service.py：7 条（T07）
- test_relink_api_integration.py：4 条（T08）
- test_reconcile_celery_tasks.py：7 条（T09 + T13）
- test_ts_conflict_reporter.py：6 条（T10）
- test_relink_conflict_store.py：5 条（T12）
- **合计**：60 条

---

## 2. 手工 QA 指引（在 114 远程或本地 conda env 运行）

### 2.1 环境准备

```bash
# 在 worktree 中
cd /Users/lilu/Projects/bisheng-worktrees/015-ldap-reconcile/src/backend

# 本地如有 BiShengVENV conda env
conda activate BiShengVENV
uv sync --frozen --python $(which python)

# 数据库迁移（F014 → F015）
.venv/bin/alembic upgrade head

# 验证 org_sync_log 新字段
.venv/bin/python -c "
from sqlalchemy import inspect
from bisheng.core.database import engine
print(sorted(c['name'] for c in inspect(engine).get_columns('org_sync_log')))
"
# 期待输出含 event_type / level / external_id / source_ts
```

### 2.2 自测命令速查

```bash
# 单文件
.venv/bin/pytest test/test_org_reconcile_service.py -v
.venv/bin/pytest test/test_department_relink_service.py -v
.venv/bin/pytest test/test_ts_conflict_reporter.py -v
.venv/bin/pytest test/test_reconcile_celery_tasks.py -v
.venv/bin/pytest test/test_relink_api_integration.py -v
.venv/bin/pytest test/test_relink_conflict_store.py -v
.venv/bin/pytest test/test_remote_dept_differ.py -v
.venv/bin/pytest test/test_org_sync_log_dao_f015.py -v

# 全 F015 + 回归
.venv/bin/pytest test/ -k "reconcile or relink or org_sync" -v

# 迁移往返
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

### 2.3 端到端手工验证脚本

**(A) AC-01 手工触发 6h 校对**

```bash
# 启动 worker + beat
.venv/bin/celery -A bisheng.worker.main:bisheng_celery worker -Q knowledge_celery -l info &
.venv/bin/celery -A bisheng.worker.main:bisheng_celery beat -l info &

# 手动派发一次（不用等 6h）
.venv/bin/python -c "
from bisheng.worker.org_sync.reconcile_tasks import reconcile_all_organizations
reconcile_all_organizations.delay()
"

# 检查 org_sync_log
.venv/bin/python -c "
import asyncio
from bisheng.org_sync.domain.models.org_sync import OrgSyncLogDao
async def run():
    rows = await OrgSyncLogDao.aget_conflicts_since(__import__('datetime').datetime.utcnow()-__import__('datetime').timedelta(hours=1))
    print(f'recent events: {len(rows)}')
asyncio.run(run())
"
```

**(B) AC-05/06/07 relink HTTP**

```bash
# HMAC 签名 helper
python3 << 'PY'
import hmac, hashlib
secret = b'test-hmac-secret-ABC123'  # 同 sso_sync.gateway_hmac_secret
method, path = 'POST', '/api/v1/internal/departments/relink'
body = b'{"old_external_ids":["DEPT-OLD"], "matching_strategy":"path_plus_name", "dry_run":true}'
print(hmac.new(secret, f'{method}\n{path}\n'.encode() + body, hashlib.sha256).hexdigest())
PY

# 用上面输出的签名
curl -X POST http://localhost:7860/api/v1/internal/departments/relink \
  -H "X-Signature: <sig>" -H "Content-Type: application/json" \
  -d '{"old_external_ids":["DEPT-OLD"], "matching_strategy":"path_plus_name", "dry_run":true}'
```

**(C) AC-11 手工构造同 ts 冲突**

```sql
-- 预置 dept：Gateway 已写入 E1@ts=7000
UPDATE department SET last_sync_ts=7000, is_deleted=0
 WHERE source='feishu' AND external_id='E1';

-- 让 Celery reconcile 在 ts=7000 时 diff 出 archive（移除 remote 中 E1 即可）
-- 然后触发
.venv/bin/python -c "from bisheng.worker.org_sync.reconcile_tasks import reconcile_single_config; reconcile_single_config.delay(<config_id>)"

-- 检查 audit_log 是否写入
SELECT action, target_id, metadata FROM audit_log
 WHERE action='dept.sync_conflict' ORDER BY create_time DESC LIMIT 5;

-- 检查 org_sync_log 事件行
SELECT event_type, level, external_id, source_ts, create_time
 FROM org_sync_log
 WHERE event_type='ts_conflict' AND external_id='E1'
 ORDER BY create_time DESC LIMIT 5;
```

**(D) AC-12 手工触发周报告**

```bash
.venv/bin/python -c "
import asyncio
from bisheng.org_sync.domain.services.ts_conflict_reporter import TsConflictReporter
summary = asyncio.run(TsConflictReporter.weekly_report())
print(summary)
"

# 然后检查全局超管的站内消息（message 表）
```

---

## 3. 发版前专项

### AC-08 10 万部门全量校对 < 30 min

**脚本**: `scripts/performance/locust_ldap_reconcile_100k.py`（占位，发版前 2 周落地）

**计划**:
1. fake provider 生成 10 万 RemoteDepartmentDTO（2 层树：100 个一级 × 1000 个二级）
2. 在本地 MySQL + Redis 跑 `OrgReconcileService.reconcile_config`，度量：
   - wall time（目标 < 30min）
   - MySQL CPU / 连接数峰值
   - Redis 命令吞吐峰值
   - Worker 内存峰值
3. 基线写入本节 §4。

---

## 4. 压测基线（发版前填写）

| 指标 | 目标 | 实测 |
|------|------|------|
| 10 万部门 reconcile wall time | < 30 min | _TBD_ |
| MySQL 峰值 CPU | < 70% | _TBD_ |
| MySQL 峰值连接数 | < 100 | _TBD_ |
| Redis 命令峰值 QPS | < 5k | _TBD_ |
| Worker 峰值内存 | < 1 GB | _TBD_ |

---

## 5. /e2e-test 执行记录

| 日期 | 执行人 | 通过/失败 | 说明 |
|------|--------|----------|------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## 6. 回归验证（合并前最后一次）

```bash
# 在 worktree 运行
.venv/bin/pytest test/ -k "permission or tenant or fga or sso or org_sync or relink or reconcile" -v

# 期待：F002/F011/F012/F013/F014 全部通过
```
