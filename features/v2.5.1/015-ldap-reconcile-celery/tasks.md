# Tasks: F015-ldap-reconcile-celery (部门定时校对 + SSO 换型 relink)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/015-ldap-reconcile-celery`（base=`2.5.0-PM`）
**Worktree**: `/Users/lilu/Projects/bisheng-worktrees/015-ldap-reconcile`
**前置**: F011/F012/F014 已合入 `2.5.0-PM`
- `OrgSyncTsGuard`（F014 T04）/ `DeptUpsertService`（F014 T07）/ `_OrgSyncLogBuffer+flush_log`（F014 T12）/ `verify_hmac`（F014 T05）
- `DepartmentDeletionHandler.on_deleted(dept_id, deletion_source)`（F011）
- `UserTenantSyncService.sync_user(user_id, trigger)`（F012）
- `DepartmentDao.aget_by_source_external_id / aupsert_by_external_id / aarchive_by_external_id`（F014 T03）
- `AuditLogDao.ainsert_v2`（F011）
- `DeletionSource.CELERY_RECONCILE` / `UserTenantSyncTrigger.CELERY_RECONCILE` 常量（F011 constants）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-21 Round 2 Review |
| tasks.md | ✅ 已拆解 | 15 任务（Test-Alongside） |
| 实现 | 🔲 进行中 | 依次 T01 → T15 |

---

## 开发模式

**后端 Test-Alongside（对齐 F014）**：
- 单任务 = 实现代码 + 单测/集成测共 2-4 文件
- Celery 任务用直接调 `.apply()` 同步触发或 mock `apply_async`
- Redis SETNX/ZSET/Hash 用 `mock_redis` fixture
- Provider `fetch_departments` 用 `MagicMock()` 返回 DTO 列表
- 迁移通过 MySQL 手工 `alembic upgrade head` / `downgrade -1` 往返 + SQLite `table_definitions.py` 同步
- 冲突告警复用 F011 `send_inbox_notice` + `list_global_super_admin_ids`

**决策锁定**（plan 阶段确认）：
- D1: Service 放 `bisheng/org_sync/domain/services/`；API endpoint 放 `bisheng/org_sync/api/endpoints/relink.py`（F009 扩展）
- D2: 6h Beat 独立 `reconcile_all_organizations`，不复用 F009 `check_org_sync_schedules`（后者响应用户 cron；F015 是系统强制）
- D3: `org_sync_log` 表加 4 列 + 复合索引（不拆事件表，摘要行 `event_type=''`，事件行非空）
- D4: relink 多候选冲突存 Redis Hash `relink_conflict:{dept_id}`，TTL 7 天
- D5: 前端 UI 不纳入；归 F019 admin-scope console
- D6: 细粒度 15 任务（对齐 F014）
- D7: 独立 worktree `/Users/lilu/Projects/bisheng-worktrees/015-ldap-reconcile`
- D8: 错误码 19314-19318 继续写入 `errcode/sso_sync.py`（MMM=193 与 F014 共享）

---

## 依赖图

```
T01 (errcode + ReconcileConf)
  │
  ├─→ T02 (Alembic 迁移 + table_definitions)
  │    │
  │    ├─→ T03 (OrgSyncLog ORM + DAO 扩展)
  │    │    │
  │    │    ├─→ T10 (TsConflictReporter)
  │    │    │    │
  │    │    │    └─→ T13 (Celery weekly/daily beats)
  │    │    │
  │    │    └─→ T11 (event 持久化集成测)
  │    │
  │    └─→ T04 (OrgSyncConfigDao.aget_all_active)
  │         │
  │         └─→ T09 (Celery reconcile_all + single_config)
  │
  ├─→ T05 (RemoteDeptDiffer 纯函数)
  │    │
  │    └─→ T06 (OrgReconcileService 主编排)
  │         │
  │         ├─→ T09
  │         ├─→ T11
  │         └─→ T14 (SETNX 并发幂等测)
  │
  └─→ T07 (Relink schemas + service)
       │
       ├─→ T08 (Relink API endpoints)
       │
       └─→ T12 (RelinkConflictStore)

T01-T14 ──→ T15 (AC 对照 + /e2e-test + 压测占位)
```

**并行建议**：T01 后三路并行 — (T02→T03→T04→T06) / (T05→T07→T08→T12) / (T10)；T09/T11/T13/T14 收尾；T15 统一验收。

---

## Tasks

### 基础：配置 + 错误码

- [ ] **T01**: 错误码 `sso_sync.py` 追加 + `ReconcileConf` + Settings 注册

  **文件（修改）**:
  - `src/backend/bisheng/common/errcode/sso_sync.py` — 追加 5 个 `BaseErrorCode` 子类
  - `src/backend/bisheng/core/config/settings.py` — 注册 `reconcile: ReconcileConf`

  **文件（新建）**:
  - `src/backend/bisheng/core/config/reconcile.py` — `ReconcileConf`

  **错误码清单**（19310-19313 已被 F014 占用）:
  ```python
  SsoReconcileLockBusyError          Code=19314  # 6h 校对 Redis 锁冲突
  SsoRelinkStrategyUnsupportedError  Code=19315  # relink matching_strategy 未识别
  SsoRelinkConflictUnresolvedError   Code=19316  # relink 冲突选择不在候选内 / 未确认
  SsoSameTsRemoveAppliedWarnError    Code=19317  # 同 ts upsert/remove 冲突已按 remove 为准（告警）
  SsoReconcileReservedError          Code=19318  # 预留
  ```

  **`ReconcileConf` 字段**:
  ```python
  class ReconcileConf(BaseModel):
      beat_cron_reconcile: str = '0 */6 * * *'
      beat_cron_weekly_report: str = '0 9 * * MON'
      beat_cron_daily_escalation: str = '0 9 * * *'
      redis_lock_ttl_seconds: int = 1800
      relink_conflict_ttl_seconds: int = 604800  # 7d
      weekly_conflict_threshold: int = 3
      daily_escalation_days: int = 5
      task_time_limit: int = 1800
      task_soft_time_limit: int = 1500
  ```

  **Settings 注册** (`core/config/settings.py`):
  ```python
  from bisheng.core.config.reconcile import ReconcileConf
  class Settings(BaseSettings):
      reconcile: ReconcileConf = Field(default_factory=ReconcileConf)
  ```

  **测试**: 无（纯常量 + Pydantic schema）
  **覆盖 AC**: AC-12（阈值配置）、§5 配置项
  **依赖**: 无

---

### 数据层：Alembic 迁移

- [ ] **T02**: Alembic 迁移 + SQLite `table_definitions.py` 同步

  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f015_reconcile_log_fields.py`

  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — `TABLE_ORG_SYNC_LOG` 追加 4 列 + 索引

  **逻辑**（复用 F014 `_column_exists` / `_index_exists` 幂等 helper）:
  - `revision='f015_reconcile_log_fields', down_revision='<F014 head>'`（实施前跑 `alembic heads` 确认）
  - `upgrade()`:
    ```python
    if not _column_exists('org_sync_log', 'event_type'):
        op.add_column('org_sync_log', sa.Column('event_type', sa.String(32),
                      nullable=False, server_default=''))
    if not _column_exists('org_sync_log', 'level'):
        op.add_column('org_sync_log', sa.Column('level', sa.String(16),
                      nullable=False, server_default='info'))
    if not _column_exists('org_sync_log', 'external_id'):
        op.add_column('org_sync_log', sa.Column('external_id', sa.String(128), nullable=True))
    if not _column_exists('org_sync_log', 'source_ts'):
        op.add_column('org_sync_log', sa.Column('source_ts', sa.BigInteger, nullable=True))
    if not _index_exists('org_sync_log', 'idx_conflict_lookup'):
        op.create_index('idx_conflict_lookup', 'org_sync_log',
                        ['level', 'event_type', 'external_id', 'create_time'])
    ```
  - `downgrade()`: drop 索引 + drop 4 列

  **测试**: SQLite T03 测试绿灯即为 table_definitions 同步佐证；MySQL 手工 upgrade/downgrade -1 往返
  **覆盖 AC**: AC-09 / AC-11 / AC-12（事件行可持久化）
  **依赖**: T01

---

### 数据层：OrgSyncLog ORM + DAO 扩展

- [ ] **T03**: `OrgSyncLog` 加字段 + `OrgSyncLogDao` 扩展 3 方法 + DAO 测试

  **文件（修改）**:
  - `src/backend/bisheng/org_sync/domain/models/org_sync.py` — `OrgSyncLog` ORM 追加 4 列；`OrgSyncLogDao` 追加 3 classmethods

  **文件（新建）**:
  - `src/backend/test/test_org_sync_log_dao_f015.py`

  **`OrgSyncLog` 追加字段**:
  ```python
  event_type: str = Field(
      default='',
      sa_column=Column(String(32), nullable=False, server_default=text("''"),
                       comment='Event type: '' (batch summary) | ts_conflict | stale_ts | conflict_weekly_sent | conflict_daily_escalation_sent'),
  )
  level: str = Field(
      default='info',
      sa_column=Column(String(16), nullable=False, server_default=text("'info'"),
                       comment='Log level: info / warn / error'),
  )
  external_id: Optional[str] = Field(
      default=None,
      sa_column=Column(String(128), nullable=True,
                       comment='Department external_id for event-scoped rows'),
  )
  source_ts: Optional[int] = Field(
      default=None,
      sa_column=Column(BigInteger, nullable=True,
                       comment='INV-T12 incoming ts captured for audit'),
  )
  ```

  **DAO 新增方法** (`OrgSyncLogDao`):
  - `acreate_event(event_type, level, external_id, source_ts, config_id, error_details=None, tenant_id=1)` — event 行快捷构造；摘要计数器全 0
  - `acount_recent_conflicts(external_id: str, days: int = 7) -> int` — 利用 `idx_conflict_lookup` 查 `level='warn' AND event_type='ts_conflict' AND external_id=? AND create_time > now-days`
  - `aget_conflicts_since(since: datetime, event_type: str = 'ts_conflict', level: str = 'warn') -> list[OrgSyncLog]` — 聚合输入，Service 层按 external_id group

  **测试**（6 条）:
  - `test_acreate_event_persists_row_with_event_fields`
  - `test_acreate_event_keeps_summary_counters_zero`
  - `test_acount_recent_conflicts_filters_by_external_id_and_window`
  - `test_acount_recent_conflicts_returns_zero_when_older_than_window`
  - `test_aget_conflicts_since_returns_rows_ordered`
  - `test_summary_log_coexists_with_event_log`（`event_type=''` 与 `'ts_conflict'` 两行共存可分别查出）

  **覆盖 AC**: AC-09 / AC-11 / AC-12（事件持久化 + 查询）
  **依赖**: T02

---

- [ ] **T04**: `OrgSyncConfigDao.aget_all_active` + 测试

  **文件（修改）**:
  - `src/backend/bisheng/org_sync/domain/models/org_sync.py` — `OrgSyncConfigDao` 追加 `aget_all_active`
  - `src/backend/test/test_org_sync_log_dao_f015.py` — 复用文件追加 3 条用例

  **逻辑**:
  ```python
  @classmethod
  async def aget_all_active(cls) -> List[OrgSyncConfig]:
      """Scan all tenants for active configs (F015 6h forced reconcile).

      Does NOT filter schedule_type (unlike F009 aget_active_cron_configs).
      Caller should filter provider=='sso_realtime' (F014 seed id=9999).
      """
      async with get_async_db_session() as session:
          statement = select(OrgSyncConfig).where(
              OrgSyncConfig.status == 'active',
          )
          result = await session.exec(statement)
          return result.all()
  ```

  **测试**（3 条）:
  - `test_aget_all_active_returns_manual_and_cron_configs`
  - `test_aget_all_active_excludes_disabled_configs`
  - `test_aget_all_active_returns_empty_when_no_active`

  **覆盖 AC**: AC-01（6h fan-out 入口）
  **依赖**: T02

---

### 核心 Reconcile：Diff 引擎

- [ ] **T05**: `RemoteDeptDiffer` 纯函数 diff + 单测

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/services/remote_dept_differ.py`
  - `src/backend/test/test_remote_dept_differ.py`

  **输出 DTO**:
  ```python
  @dataclass
  class UpsertOp:
      external_id: str
      name: str
      parent_external_id: Optional[str]
      sort_order: int
      incoming_ts: int
      is_new: bool

  @dataclass
  class ArchiveOp:
      external_id: str
      dept_id: int
      mounted_tenant_id: Optional[int]
      incoming_ts: int

  @dataclass
  class MoveOp:
      external_id: str
      dept_id: int
      new_parent_external_id: Optional[str]
      crosses_tenant: bool
      incoming_ts: int

  @dataclass
  class ReconcileDiff:
      upserts: list[UpsertOp]
      archives: list[ArchiveOp]
      moves: list[MoveOp]
  ```

  **逻辑**:
  - 复用 F009 `reconciler` 的拓扑排序（若存在 `reconciler.topological_sort`）或独立实现
  - `diff(remote, local, source, ts) -> ReconcileDiff`
  - `crosses_tenant` 计算：沿 local + new_parent 链各自找最近 mount 点派生 leaf tenant id，对比是否不同

  **测试**（6 条）:
  - `test_diff_new_dept_generates_upsert_op_with_ts`
  - `test_diff_deleted_dept_generates_archive_op`
  - `test_diff_rename_generates_upsert_op_preserves_mount_flag`（生成 upsert 但不动 is_tenant_root）
  - `test_diff_move_across_tenant_marks_crosses_tenant_true`
  - `test_diff_move_within_same_leaf_tenant_crosses_tenant_false`
  - `test_diff_topo_sort_parent_before_child`

  **覆盖 AC**: AC-02 / AC-03 / AC-04（diff 输入）
  **依赖**: T01（纯函数，可早启）

---

### 核心 Reconcile：主编排服务

- [ ] **T06**: `OrgReconcileService.reconcile_config` + 集成测试

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/services/reconcile_service.py`
  - `src/backend/test/test_org_reconcile_service.py`

  **主流程（11 步）**:
  ```python
  class OrgReconcileService:
      @classmethod
      async def reconcile_config(cls, config_id: int) -> ReconcileResult:
          # 1) load config, skip sso_realtime seed
          config = await OrgSyncConfigDao.aget_by_id(config_id)
          if config is None or config.provider == 'sso_realtime':
              return ReconcileResult(skipped=True)

          # 2) Redis SETNX lock `org_reconcile:{config_id}` TTL=1800s
          async with cls._acquire_lock(config_id):
              # 3) Provider.authenticate + fetch_departments
              provider = cls._build_provider(config)
              await provider.authenticate()
              remote = await provider.fetch_departments(
                  (config.sync_scope or {}).get('root_dept_ids') or None)

              # 4) local = DepartmentDao.aget_active_by_tenant(config.tenant_id)
              local = await DepartmentDao.aget_active_by_tenant(config.tenant_id)

              # 5) diff
              now_ts = int(time.time())
              diff = RemoteDeptDiffer.diff(remote, local,
                                            source=config.provider, ts=now_ts)

              buffer = _OrgSyncLogBuffer()
              event_rows: list[dict] = []

              # 6) Upserts (+ same-ts conflict detection)
              applied_upsert_ext_ids: set[str] = set()
              for op in diff.upserts:
                  existing = await DepartmentDao.aget_by_source_external_id(
                      source=config.provider, external_id=op.external_id)
                  decision = await OrgSyncTsGuard.check_and_update(
                      existing, op.incoming_ts, 'upsert')
                  if decision == GuardDecision.SKIP_TS:
                      event_rows.append(dict(
                          event_type='stale_ts', level='warn',
                          external_id=op.external_id, source_ts=op.incoming_ts,
                          error_details={'action': 'upsert', 'last_sync_ts': getattr(existing, 'last_sync_ts', 0)}))
                      buffer.warn('stale_ts', op.external_id)
                      continue
                  await DeptUpsertService.upsert_from_sync_payload(
                      existing=existing, item=op, source=config.provider,
                      last_sync_ts=op.incoming_ts)
                  buffer.dept_upserted(op.external_id, is_new=op.is_new)
                  applied_upsert_ext_ids.add(op.external_id)

              # 7) Archives (+ same-ts remove-wins over upsert)
              for op in diff.archives:
                  existing = await DepartmentDao.aget_by_source_external_id(
                      source=config.provider, external_id=op.external_id)
                  if existing is None:
                      continue
                  decision = await OrgSyncTsGuard.check_and_update(
                      existing, op.incoming_ts, 'remove')
                  if decision == GuardDecision.SKIP_TS:
                      event_rows.append(dict(
                          event_type='stale_ts', level='warn',
                          external_id=op.external_id, source_ts=op.incoming_ts,
                          error_details={'action': 'remove'}))
                      buffer.warn('stale_ts', op.external_id)
                      continue

                  # Same-ts conflict: upsert already applied this run → rollback + archive
                  if op.external_id in applied_upsert_ext_ids:
                      # INV-T12 AC-11: remove wins; audit + warn
                      event_rows.append(dict(
                          event_type='ts_conflict', level='warn',
                          external_id=op.external_id, source_ts=op.incoming_ts,
                          error_details={'resolution': 'remove_wins',
                                         'via': 'celery_reconcile'}))
                      await AuditLogDao.ainsert_v2(
                          tenant_id=config.tenant_id, operator_id=0,
                          operator_tenant_id=config.tenant_id,
                          action='dept.sync_conflict',
                          target_type='department', target_id=str(existing.id),
                          metadata={'external_id': op.external_id,
                                    'source_ts': op.incoming_ts,
                                    'resolution': 'remove_wins',
                                    'via': 'celery_reconcile'},
                          ip_address='internal')
                      # rollback previous upsert is a no-op because archive below will overwrite

                  await DepartmentDao.aarchive_by_external_id(
                      source=config.provider, external_id=op.external_id,
                      last_sync_ts=op.incoming_ts)
                  await DepartmentDeletionHandler.on_deleted(
                      existing.id, deletion_source=DeletionSource.CELERY_RECONCILE)
                  buffer.dept_archived_event(op.external_id)

              # 8) Cross-tenant moves → UserTenantSyncService per active user
              for mv in diff.moves:
                  if not mv.crosses_tenant:
                      continue
                  user_ids = await UserDepartmentDao.aget_user_ids_by_department(
                      mv.dept_id, is_primary=True)
                  for uid in user_ids:
                      try:
                          await UserTenantSyncService.sync_user(
                              uid, trigger=UserTenantSyncTrigger.CELERY_RECONCILE)
                      except Exception as e:
                          logger.exception(f'sync_user {uid} failed: {e}')
                          buffer.error('sync_user', str(uid), str(e))

              # 9) flush summary log
              await flush_log(buffer, trigger_type='reconcile', config_id=config.id)

              # 10) persist event rows
              for ev in event_rows:
                  await OrgSyncLogDao.acreate_event(
                      event_type=ev['event_type'], level=ev['level'],
                      external_id=ev['external_id'], source_ts=ev['source_ts'],
                      config_id=config.id, tenant_id=config.tenant_id,
                      error_details=ev.get('error_details'))

              # 11) return result
              return ReconcileResult(
                  applied_upsert=len(applied_upsert_ext_ids),
                  applied_archive=buffer.dept_archived,
                  skipped_ts=len([e for e in event_rows if e['event_type'] == 'stale_ts']),
                  conflicts=len([e for e in event_rows if e['event_type'] == 'ts_conflict']),
              )

      @classmethod
      @asynccontextmanager
      async def _acquire_lock(cls, config_id: int):
          redis = await get_redis_client()
          key = f'org_reconcile:{config_id}'
          ok = await redis.async_connection.set(
              key, b'1', nx=True,
              ex=settings.reconcile.redis_lock_ttl_seconds)
          if not ok:
              raise SsoReconcileLockBusyError.http_exception()
          try:
              yield
          finally:
              try:
                  await redis.async_connection.delete(key)
              except Exception:
                  pass
  ```

  **测试**（8 条集成）:
  - `test_reconcile_new_dept_upserts_preserves_mount` — 预置本地 dept 带 `is_tenant_root=1`；remote 返同 external_id 但改名；断言名改 + mount 不变。**AC-02**
  - `test_reconcile_removed_dept_triggers_department_deletion_handler` — mock handler 断言调用 `(dept_id, DeletionSource.CELERY_RECONCILE)`。**AC-03**
  - `test_reconcile_primary_dept_change_triggers_user_tenant_sync` — mock `UserTenantSyncService.sync_user` 断言 `trigger=UserTenantSyncTrigger.CELERY_RECONCILE`。**AC-04**
  - `test_reconcile_stale_ts_skipped_writes_warn_event` — 预置 `last_sync_ts=100`；remote ts=50；断言 skip + `event_type='stale_ts', level='warn'` 行写入。**AC-09**
  - `test_reconcile_newer_ts_applies_and_updates_last_sync_ts` — 预置 ts=100；remote ts=200；断言 apply + `last_sync_ts=200`。**AC-10**
  - `test_reconcile_same_ts_upsert_then_remove_prefers_remove` — 构造 diff 同时含 upsert + archive 同 external_id 同 ts；断言最终 dept `is_deleted=1` + audit `dept.sync_conflict` + `event_type='ts_conflict'` 行。**AC-11**
  - `test_reconcile_redis_lock_busy_raises_19314` — 两协程并发 `reconcile_config(same_id)`；一成一 19314。
  - `test_reconcile_skips_sso_realtime_seed_config` — `config.provider='sso_realtime'` 直接 return `skipped=True`，Provider 不被调。

  **覆盖 AC**: AC-02 / AC-03 / AC-04 / AC-09 / AC-10 / AC-11
  **依赖**: T02, T03, T04, T05；复用 F014 `OrgSyncTsGuard / DeptUpsertService / _OrgSyncLogBuffer / flush_log`、F011 `DepartmentDeletionHandler / AuditLogDao.ainsert_v2`、F012 `UserTenantSyncService`

---

### Relink 子系统

- [ ] **T07**: Pydantic Relink schemas + `DepartmentRelinkService` + 单测

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/schemas/relink.py`
  - `src/backend/bisheng/org_sync/domain/services/relink_service.py`
  - `src/backend/test/test_department_relink_service.py`

  **Schemas**:
  ```python
  class RelinkRequest(BaseModel):
      old_external_ids: list[str]
      matching_strategy: Literal['external_id_map', 'path_plus_name']
      external_id_map: Optional[dict[str, str]] = None
      source: str = 'sso'
      dry_run: bool = False

  class RelinkAppliedItem(BaseModel):
      dept_id: int
      old_external_id: str
      new_external_id: str

  class RelinkCandidate(BaseModel):
      new_external_id: str
      path: str
      name: str
      score: float = 1.0

  class RelinkConflictItem(BaseModel):
      dept_id: int
      old_external_id: str
      candidates: list[RelinkCandidate]

  class RelinkResponse(BaseModel):
      applied: list[RelinkAppliedItem] = []
      would_apply: list[RelinkAppliedItem] = []  # dry_run
      conflicts: list[RelinkConflictItem] = []

  class ResolveConflictRequest(BaseModel):
      dept_id: int
      chosen_new_external_id: str
  ```

  **Service**:
  - `relink(req)`:
    - 策略 `external_id_map`：遍历 `old_external_ids`；每个查 dept（by source+old_ext），若 map 有 new_ext → 写入 `external_id=new_ext`（dry_run 仅收集 would_apply，不写）
    - 策略 `path_plus_name`：对每个 old_ext 查本地 dept；在同 source 下未被占用（`external_id` 不等于任何已存在 dept 的 external_id）的 dept 中，按 `(path, name)` 精确匹配（path 完全相等 + name 完全相等）找候选；单候选 auto apply；多候选调 `RelinkConflictStore.save` 并加入 `conflicts`
    - 策略不识别 → raise `SsoRelinkStrategyUnsupportedError(19315)`
    - apply 时写 `audit_log.action='dept.relink_applied'`，metadata 含 `{old_ext, new_ext, strategy}`
  - `resolve_conflict(dept_id, chosen_new_external_id)`:
    - `candidates = await RelinkConflictStore.get(dept_id)`
    - 若 `chosen not in {c['new_external_id'] for c in candidates}` → raise `SsoRelinkConflictUnresolvedError(19316)`
    - UPDATE department SET external_id=? + `audit_log.action='dept.relink_resolved'` + `RelinkConflictStore.delete(dept_id)`

  **测试**（7 条）:
  - `test_relink_external_id_map_strategy_applies` **AC-05**
  - `test_relink_path_plus_name_single_candidate_auto_apply` **AC-06**
  - `test_relink_path_plus_name_multi_candidate_returns_conflicts` **AC-06**（含 store.save 被调）
  - `test_relink_dry_run_returns_would_apply_no_db_write` **AC-07**
  - `test_relink_unknown_strategy_raises_19315`
  - `test_resolve_conflict_applies_chosen_candidate`
  - `test_resolve_conflict_raises_19316_when_not_in_candidates`

  **覆盖 AC**: AC-05 / AC-06 / AC-07
  **依赖**: T01；T12 的 `RelinkConflictStore` 接口提前约定（实现在 T12，T07 用 mock）

---

- [ ] **T08**: Relink API endpoints + router 挂载 + `TENANT_CHECK_EXEMPT_PATHS`

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/api/endpoints/relink.py`
  - `src/backend/test/test_relink_api_integration.py`

  **文件（修改）**:
  - `src/backend/bisheng/org_sync/api/router.py` — `router.include_router(relink_router)`
  - `src/backend/bisheng/utils/http_middleware.py` — `TENANT_CHECK_EXEMPT_PATHS` 追加:
    - `/api/v1/internal/departments/relink`
    - `/api/v1/internal/departments/relink/resolve-conflict`

  **端点骨架**:
  ```python
  relink_router = APIRouter(prefix='/internal/departments', tags=['internal.relink'])

  @relink_router.post('/relink', response_model=UnifiedResponseModel[RelinkResponse])
  async def relink(
      payload: RelinkRequest,
      request: Request,
      _: None = Depends(verify_hmac),
  ):
      result = await DepartmentRelinkService.relink(payload)
      return resp_200(result)

  @relink_router.post('/relink/resolve-conflict',
                      response_model=UnifiedResponseModel[RelinkAppliedItem])
  async def resolve_conflict(
      payload: ResolveConflictRequest,
      request: Request,
      _: None = Depends(verify_hmac),
  ):
      result = await DepartmentRelinkService.resolve_conflict(
          payload.dept_id, payload.chosen_new_external_id)
      return resp_200(result)
  ```

  **测试**（4 条，FastAPI TestClient）:
  - `test_relink_route_responds_200_with_valid_hmac`
  - `test_relink_dry_run_via_http_returns_would_apply` **AC-07**
  - `test_relink_route_returns_401_without_hmac`
  - `test_resolve_conflict_route_happy_path`

  **覆盖 AC**: AC-05 / AC-06 / AC-07（HTTP 端到端）
  **依赖**: T07；复用 F014 T05 `verify_hmac`

---

### Celery 任务：6h reconcile fan-out

- [ ] **T09**: Celery `reconcile_all_organizations` + `reconcile_single_config` + beat 注册

  **文件（新建）**:
  - `src/backend/bisheng/worker/org_sync/reconcile_tasks.py`
  - `src/backend/test/test_reconcile_celery_tasks.py`

  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — `CeleryConf.validate` 追加 `reconcile_all_organizations` beat 注册

  **逻辑**:
  ```python
  import asyncio
  from loguru import logger
  from bisheng.worker.main import bisheng_celery
  from bisheng.common.errcode.sso_sync import SsoReconcileLockBusyError

  @bisheng_celery.task(acks_late=True)
  def reconcile_all_organizations():
      """6h Beat entry: fan out reconcile per active OrgSyncConfig."""
      loop = asyncio.new_event_loop()
      try:
          loop.run_until_complete(_fan_out_all())
      finally:
          loop.close()

  async def _fan_out_all() -> None:
      from bisheng.org_sync.domain.models.org_sync import OrgSyncConfigDao
      configs = await OrgSyncConfigDao.aget_all_active()
      for c in configs:
          if c.provider == 'sso_realtime':
              continue
          reconcile_single_config.apply_async(args=[c.id], queue='knowledge_celery')

  @bisheng_celery.task(acks_late=True, time_limit=1800, soft_time_limit=1500)
  def reconcile_single_config(config_id: int):
      """Execute one reconcile run; swallow lock-busy without retry."""
      loop = asyncio.new_event_loop()
      try:
          from bisheng.org_sync.domain.services.reconcile_service import OrgReconcileService
          loop.run_until_complete(OrgReconcileService.reconcile_config(config_id))
      except SsoReconcileLockBusyError:
          logger.warning(f'reconcile_single_config {config_id} skipped: lock busy')
      except Exception:
          logger.exception(f'reconcile_single_config {config_id} failed')
      finally:
          loop.close()
  ```

  **beat 注册**（settings.py 在 F012 `reconcile_user_tenant_assignments` 后追加）:
  ```python
  if 'reconcile_all_organizations' not in self.beat_schedule:
      self.beat_schedule['reconcile_all_organizations'] = {
          'task': 'bisheng.worker.org_sync.reconcile_tasks.reconcile_all_organizations',
          'schedule': crontab.from_string('0 */6 * * *'),  # every 6h
      }
  ```

  **测试**（4 条）:
  - `test_beat_schedule_registers_reconcile_all_every_6h` **AC-01**（导入 settings → assert `beat_schedule['reconcile_all_organizations']['schedule']` 为 `crontab(minute=0, hour='*/6')`）
  - `test_reconcile_all_dispatches_single_config_per_active_config`（mock `reconcile_single_config.apply_async` 断言调用次数）
  - `test_reconcile_all_skips_sso_realtime_seed`
  - `test_reconcile_single_swallows_lock_busy_logs_warning`（mock `OrgReconcileService.reconcile_config` 抛 19314 → no re-raise）

  **覆盖 AC**: AC-01
  **依赖**: T04, T06

---

### 告警子系统：周报 + 每日升级

- [ ] **T10**: `TsConflictReporter` + 单测

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/services/ts_conflict_reporter.py`
  - `src/backend/test/test_ts_conflict_reporter.py`

  **逻辑**:
  ```python
  class TsConflictReporter:

      @classmethod
      async def weekly_report(cls) -> dict:
          """Aggregate last-7d conflicts; notify super admins when >= threshold."""
          since = datetime.utcnow() - timedelta(days=7)
          rows = await OrgSyncLogDao.aget_conflicts_since(
              since=since, event_type='ts_conflict', level='warn')
          counts: dict[str, int] = {}
          for r in rows:
              if r.external_id:
                  counts[r.external_id] = counts.get(r.external_id, 0) + 1
          threshold = settings.reconcile.weekly_conflict_threshold
          flagged = {ext: cnt for ext, cnt in counts.items() if cnt >= threshold}
          if not flagged:
              return {'flagged_count': 0}

          payload = {
              'window_days': 7, 'total_conflicts': sum(counts.values()),
              'flagged_externals': [
                  {'external_id': ext, 'count': cnt,
                   'suggested_action': 'run /api/v1/internal/departments/relink'}
                  for ext, cnt in flagged.items()
              ],
          }
          admins = await list_global_super_admin_ids()
          for uid in admins:
              await send_inbox_notice(
                  user_id=uid, title='Org sync ts_conflict weekly report',
                  body=json.dumps(payload, ensure_ascii=False))

          # Marker row for daily escalation trigger
          await OrgSyncLogDao.acreate_event(
              event_type='conflict_weekly_sent', level='info',
              external_id=None, source_ts=None,
              config_id=0, error_details={'payload': payload})
          return {'flagged_count': len(flagged), 'notified': len(admins)}

      @classmethod
      async def daily_escalation_report(cls) -> dict:
          """Escalate to daily notice when last weekly report is >= 5 days old AND conflicts still active."""
          last_marker = await OrgSyncLogDao.aget_latest_event(
              event_type='conflict_weekly_sent')
          if not last_marker:
              return {'escalated': False, 'reason': 'no_weekly_marker'}
          age = datetime.utcnow() - last_marker.create_time
          if age < timedelta(days=settings.reconcile.daily_escalation_days):
              return {'escalated': False, 'reason': 'within_grace'}

          since = datetime.utcnow() - timedelta(days=settings.reconcile.daily_escalation_days)
          rows = await OrgSyncLogDao.aget_conflicts_since(
              since=since, event_type='ts_conflict', level='warn')
          if not rows:
              return {'escalated': False, 'reason': 'resolved'}

          counts: dict[str, int] = {}
          for r in rows:
              if r.external_id:
                  counts[r.external_id] = counts.get(r.external_id, 0) + 1
          admins = await list_global_super_admin_ids()
          for uid in admins:
              await send_inbox_notice(
                  user_id=uid,
                  title='Org sync ts_conflict daily ESCALATION',
                  body=json.dumps(counts, ensure_ascii=False))
          await OrgSyncLogDao.acreate_event(
              event_type='conflict_daily_escalation_sent', level='warn',
              external_id=None, source_ts=None, config_id=0,
              error_details={'unresolved_externals': counts})
          return {'escalated': True, 'notified': len(admins)}
  ```

  **注**: T03 需要追加 `OrgSyncLogDao.aget_latest_event(event_type)` 辅助方法。

  **测试**（6 条）:
  - `test_weekly_report_aggregates_conflicts_above_threshold` **AC-12**
  - `test_weekly_report_skips_below_threshold`
  - `test_weekly_report_sends_inbox_to_all_global_super_admins`
  - `test_weekly_report_writes_conflict_weekly_sent_marker`
  - `test_daily_escalation_triggers_after_5_days_unresolved` **AC-12**
  - `test_daily_escalation_no_trigger_when_within_5_days`

  **覆盖 AC**: AC-12
  **依赖**: T03；复用 F011 `send_inbox_notice` / `list_global_super_admin_ids`

---

### event 行持久化专项

- [ ] **T11**: reconcile 服务的 event 行持久化集成测

  **文件（修改）**:
  - `src/backend/test/test_org_reconcile_service.py` — 追加 4 条专项用例

  **测试**（4 条）:
  - `test_stale_ts_event_written_with_level_warn_and_event_type_stale_ts` **AC-09**
  - `test_same_ts_conflict_event_written_with_external_id_and_source_ts` **AC-11**
  - `test_conflict_event_distinct_from_batch_summary_row`（同 run 两种行可分别查）
  - `test_event_rows_written_even_after_partial_failure`（reconcile 中抛异常 → 已缓存 event 行仍写入；可通过 try/finally 在 T06 中保证）

  **覆盖 AC**: AC-09 / AC-11（持久化维度）
  **依赖**: T03, T06

---

### Relink 多候选存储

- [ ] **T12**: `RelinkConflictStore` Redis Hash + 集成测

  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/services/relink_conflict_store.py`
  - `src/backend/test/test_relink_conflict_store.py`

  **逻辑**:
  ```python
  class RelinkConflictStore:
      """Redis-backed multi-candidate conflict registry, TTL 7d."""
      KEY_PREFIX = 'relink_conflict:'

      @classmethod
      async def save(cls, dept_id: int, candidates: list[dict]) -> None:
          key = f'{cls.KEY_PREFIX}{dept_id}'
          redis = await get_redis_client()
          # Serialize: one hash field per candidate new_external_id
          mapping = {c['new_external_id']: json.dumps(c, ensure_ascii=False)
                     for c in candidates}
          await redis.async_connection.hset(key, mapping=mapping)
          await redis.async_connection.expire(
              key, settings.reconcile.relink_conflict_ttl_seconds)

      @classmethod
      async def get(cls, dept_id: int) -> list[dict]:
          key = f'{cls.KEY_PREFIX}{dept_id}'
          redis = await get_redis_client()
          raw = await redis.async_connection.hgetall(key)
          if not raw:
              return []
          return [json.loads(v) for v in raw.values()]

      @classmethod
      async def delete(cls, dept_id: int) -> None:
          key = f'{cls.KEY_PREFIX}{dept_id}'
          redis = await get_redis_client()
          await redis.async_connection.delete(key)
  ```

  **测试**（5 条）:
  - `test_save_and_get_returns_candidates_list`
  - `test_save_sets_ttl_7_days`（mock_redis 断言 `expire` 调用 ex=604800）
  - `test_get_returns_empty_after_delete`
  - `test_resolve_conflict_with_valid_choice_persists_and_deletes_store`（走 T07 service 端到端）
  - `test_resolve_conflict_with_invalid_choice_raises_19316_and_preserves_store`

  **覆盖 AC**: AC-06
  **依赖**: T07

---

### Celery 任务：冲突周报 + 升级

- [ ] **T13**: Celery `report_ts_conflicts_weekly` + `report_ts_conflicts_daily_escalation` + 注册

  **文件（修改）**:
  - `src/backend/bisheng/worker/org_sync/reconcile_tasks.py` — 追加两 task
  - `src/backend/bisheng/core/config/settings.py` — 两条 beat 注册
  - `src/backend/test/test_reconcile_celery_tasks.py` — 追加 3 条测试

  **逻辑**:
  ```python
  @bisheng_celery.task(acks_late=True)
  def report_ts_conflicts_weekly():
      loop = asyncio.new_event_loop()
      try:
          from bisheng.org_sync.domain.services.ts_conflict_reporter import TsConflictReporter
          loop.run_until_complete(TsConflictReporter.weekly_report())
      except Exception:
          logger.exception('report_ts_conflicts_weekly failed')
      finally:
          loop.close()

  @bisheng_celery.task(acks_late=True)
  def report_ts_conflicts_daily_escalation():
      loop = asyncio.new_event_loop()
      try:
          from bisheng.org_sync.domain.services.ts_conflict_reporter import TsConflictReporter
          loop.run_until_complete(TsConflictReporter.daily_escalation_report())
      except Exception:
          logger.exception('report_ts_conflicts_daily_escalation failed')
      finally:
          loop.close()
  ```

  **beat 注册**:
  ```python
  if 'report_ts_conflicts_weekly' not in self.beat_schedule:
      self.beat_schedule['report_ts_conflicts_weekly'] = {
          'task': 'bisheng.worker.org_sync.reconcile_tasks.report_ts_conflicts_weekly',
          'schedule': crontab.from_string('0 9 * * MON'),
      }
  if 'report_ts_conflicts_daily_escalation' not in self.beat_schedule:
      self.beat_schedule['report_ts_conflicts_daily_escalation'] = {
          'task': 'bisheng.worker.org_sync.reconcile_tasks.report_ts_conflicts_daily_escalation',
          'schedule': crontab.from_string('0 9 * * *'),
      }
  ```

  **测试**（3 条）:
  - `test_beat_registers_weekly_conflict_report_monday_09`
  - `test_beat_registers_daily_escalation_09`
  - `test_weekly_celery_task_invokes_reporter_weekly`（mock `TsConflictReporter.weekly_report` 断言被 await）

  **覆盖 AC**: AC-12
  **依赖**: T09, T10

---

### 并发与幂等专项

- [ ] **T14**: Redis SETNX 并发幂等集成测

  **文件（修改）**:
  - `src/backend/test/test_org_reconcile_service.py` — 追加 4 条并发用例

  **测试**（4 条）:
  - `test_concurrent_same_ts_same_config_deduped_by_setnx` **AC-13**（两协程同时调 `reconcile_config(same_id)` → 一成一 19314）
  - `test_different_config_ids_lock_independently`（并发不同 config 不互相阻塞）
  - `test_lock_released_even_on_exception`（service 内抛异常后 Redis key 被 delete）
  - `test_lock_ttl_30min_prevents_stuck_lock`（mock_redis 断言 SETNX 调用 ex=1800）

  **覆盖 AC**: AC-13 + INV-T12（原子性）
  **依赖**: T06

---

### 验收与专项

- [ ] **T15**: AC 对照矩阵 + `/task-review` 逐任务 + `/e2e-test` + 性能专项占位

  **文件（新建）**:
  - `features/v2.5.1/015-ldap-reconcile-celery/ac-verification.md` — AC 对照 + 手工 QA 指引
  - `scripts/performance/locust_ldap_reconcile_100k.py` — 占位；发版前 2 周跑 AC-08

  **内容**:
  - 每任务完成后执行 `/task-review features/v2.5.1/015-ldap-reconcile-celery <Txx>`
  - 全部完成后执行 `/e2e-test features/v2.5.1/015-ldap-reconcile-celery`
  - 性能专项 AC-08：fake provider 生成 10 万部门 DTO，`OrgReconcileService.reconcile_config` wall time < 30 min，MySQL/Redis 压力基线写 `ac-verification.md §10`
  - 更新 spec.md §7 自测清单（勾选）
  - 汇总 AC-01~AC-13 覆盖表写入 `ac-verification.md`
  - 跑 F011/F012/F014/F015 回归：`.venv/bin/pytest test/ -k "org_sync or tenant or sso or reconcile or relink" -v`

  **覆盖 AC**: 全部
  **依赖**: T01-T14

---

## AC 对照矩阵

| AC | 任务 | 关键测试 |
|----|------|---------|
| AC-01 | T04, T09 | `test_beat_schedule_registers_reconcile_all_every_6h` + `test_reconcile_all_dispatches_single_config_per_active_config` |
| AC-02 | T05, T06 | `test_reconcile_new_dept_upserts_preserves_mount` |
| AC-03 | T06 | `test_reconcile_removed_dept_triggers_department_deletion_handler`（deletion_source='celery_reconcile'）|
| AC-04 | T05, T06 | `test_diff_move_across_tenant_marks_crosses_tenant_true` + `test_reconcile_primary_dept_change_triggers_user_tenant_sync`（trigger='celery_reconcile'）|
| AC-05 | T07, T08 | `test_relink_external_id_map_strategy_applies` |
| AC-06 | T07, T08, T12 | `test_relink_path_plus_name_*_candidate_*` + `test_resolve_conflict_*` |
| AC-07 | T07, T08 | `test_relink_dry_run_returns_would_apply_no_db_write` + HTTP dry_run |
| AC-08 | T15（专项，不在 CI）| locust 10 万部门 < 30 min |
| AC-09 | T06, T11 | `test_reconcile_stale_ts_skipped_writes_warn_event` + `test_stale_ts_event_written_*` |
| AC-10 | T06 | `test_reconcile_newer_ts_applies_and_updates_last_sync_ts` |
| AC-11 | T06, T11 | `test_reconcile_same_ts_upsert_then_remove_prefers_remove` + audit `dept.sync_conflict` + 19317 |
| AC-12 | T03, T10, T13 | `test_weekly_report_aggregates_conflicts_above_threshold` + `test_daily_escalation_triggers_after_5_days_unresolved` |
| AC-13 | T14 | `test_concurrent_same_ts_same_config_deduped_by_setnx` |

---

## 不变量映射

- **INV-T12**（ts 最大为准 + 同 ts remove 优先）：T05 diff 给每 op `incoming_ts` → T06 每 op 调 `OrgSyncTsGuard.check_and_update` → 同 ts upsert+remove 冲突走 AC-11 路径（remove wins + audit `dept.sync_conflict`）；T11 持久化；T14 并发兜底
- **INV-T8**（孤儿 Tenant）：T06 在 archive mount 部门后调 `DepartmentDeletionHandler.on_deleted(dept_id, DeletionSource.CELERY_RECONCILE)` → F011 handler 将 `Tenant.status='orphaned'` 并告警
- **INV-T7**（挂载/解绑强制 audit）：T07 `resolve_conflict` 写 `action='dept.relink_resolved'`；T06 同 ts 冲突写 `action='dept.sync_conflict'`
- **INV-T2**（用户唯一叶子）：T06 `crosses_tenant=True` 主动 `UserTenantSyncService.sync_user(user_id, CELERY_RECONCILE)` → token_version +1

---

## 开发命令

```bash
# 进入 worktree
cd /Users/lilu/Projects/bisheng-worktrees/015-ldap-reconcile/src/backend

# 单任务跑测
.venv/bin/pytest test/test_org_reconcile_service.py -v
.venv/bin/pytest test/test_reconcile_celery_tasks.py -v
.venv/bin/pytest test/test_ts_conflict_reporter.py -v
.venv/bin/pytest test/test_department_relink_service.py -v
.venv/bin/pytest test/test_relink_conflict_store.py -v
.venv/bin/pytest test/test_remote_dept_differ.py -v
.venv/bin/pytest test/test_org_sync_log_dao_f015.py -v

# 迁移往返（T02）
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head

# 全 feature 回归
.venv/bin/pytest test/ -k "org_sync or tenant or sso or reconcile or relink" -v

# Worker + Beat 手工 QA
.venv/bin/celery -A bisheng.worker.main:bisheng_celery worker -Q knowledge_celery -l info &
.venv/bin/celery -A bisheng.worker.main:bisheng_celery beat -l info &

# 手动触发 6h 校对
.venv/bin/python -c "from bisheng.worker.org_sync.reconcile_tasks import reconcile_all_organizations; reconcile_all_organizations.delay()"

# relink HTTP 调用（HMAC 签名）
# python -c "import hmac,hashlib; print(hmac.new(b'<secret>', b'POST\n/api/v1/internal/departments/relink\n<body>', hashlib.sha256).hexdigest())"
curl -X POST http://localhost:7860/api/v1/internal/departments/relink \
  -H "X-Signature: <sha256>" -H "Content-Type: application/json" \
  -d '{"old_external_ids":["abc"], "matching_strategy":"path_plus_name", "dry_run":true}'

# SDD 审查
/task-review features/v2.5.1/015-ldap-reconcile-celery T06
/e2e-test features/v2.5.1/015-ldap-reconcile-celery
/code-review --base 2.5.0-PM
```
