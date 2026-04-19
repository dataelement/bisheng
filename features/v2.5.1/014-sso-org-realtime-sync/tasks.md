# Tasks: F014-sso-org-realtime-sync (SSO 登录 + 部门批量同步)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/014-sso-org-realtime-sync`（base=`2.5.0-PM`）
**前置**: F011/F012 已合入 `2.5.0-PM`（`DepartmentDeletionHandler` / `UserTenantSyncService` / `AuditLogDao.ainsert_v2` / `User.token_version` / `bypass_tenant_filter` 均可直接调用）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-21 Round 2 Review |
| tasks.md | ✅ 已拆解 | 15 任务（Test-Alongside） |
| 实现 | ✅ 已完成 | 15 / 15；87 tests passed；F002/F011/F012 回归 112 passed（1 pre-existing failure 无关 F014）|

---

## 开发模式

**后端 Test-Alongside（对齐 F012）**：
- Pydantic schemas + 单元测试合并为一个任务
- DAO 扩展 + 测试合并同一任务
- Service 编排 + 集成测试合并
- 迁移通过 MySQL 手工 `alembic upgrade head` / `downgrade -1` 往返校验 + SQLite `table_definitions` 同步
- HMAC 签名生成用 `test/fixtures/sso_sync.py` 的 `hmac_signer` fixture 统一管理
- Redis SETNX 锁用 `mock_redis` fixture 隔离

**决策锁定**（plan 阶段确认）：
- 错误码模块 MMM=193（spec §8 已声明，与 F015 共享）
- 新建顶级模块 `sso_sync/`（HMAC 信任模型独立于 org_sync/ 的 Provider 拉模式）
- `OrgSyncTsGuard` 放 `org_sync/domain/services/`（F015 也要复用）
- **不建新表**：同步日志复用 F009 的 `org_sync_log`，通过迁移脚本插入 `id=9999` 的 `OrgSyncConfig(provider='sso_realtime')` seed
- HMAC 用 FastAPI **Dependency**（不 Middleware），读 raw body 后用 `request._receive = ...` 重放给下游 Pydantic 解析
- `tenant_mapping` 首次挂载直接绕过 `TenantMountService._require_super`，DAO 层写入，audit `metadata.via='sso_realtime'`
- Cross-source 用户优先复用：`source≠'sso'` 时 UPDATE source + audit，不建重复账号
- 父链缺失 → 返 19312（严格模式，不容忍树不一致）
- 两端点 bypass 全局 JWT 上下文（加入 `TENANT_CHECK_EXEMPT_PATHS`）；内部用 `set_current_tenant_id(ROOT_TENANT_ID)` + `bypass_tenant_filter()`

---

## 依赖图

```
T01 (SSOSyncConf + errcode)
  │
  ├─→ T02 (Alembic 迁移 + seed)
  │    │
  │    └─→ T03 (Department ORM + DAO 扩展)
  │         │
  │         ├─→ T04 (OrgSyncTsGuard)
  │         │
  │         └─→ T07 (DeptUpsertService)
  │              │
  │              ├─→ T08 (LoginSyncService)
  │              │    │
  │              │    ├─→ T09 (Cross-source 复用)
  │              │    ├─→ T10 (tenant_mapping 分支)
  │              │    ├─→ T12 (org_sync_log 封装)
  │              │    └─→ T14 (禁用/主部门缺失阻断)
  │              │
  │              └─→ T11 (DepartmentsSyncService)
  │
  ├─→ T05 (HMAC Dependency)
  │
  └─→ T06 (Pydantic Schemas)
       │
       └─→ T13 (Router 挂载 + exempt paths)
            │
            └─→ T15 (AC 对照 + /e2e-test)
```

---

## Tasks

### 基础：配置 + 错误码

- [x] **T01**: 错误码 `sso_sync.py` + `SSOSyncConf` + Settings 注册 + CLAUDE.md 同步
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/sso_sync.py` — 8 个 `BaseErrorCode` 子类（19301-19313）
  - `src/backend/bisheng/core/config/sso_sync.py` — `SSOSyncConf`
  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — 注册 `sso_sync: SSOSyncConf`
  - `CLAUDE.md` — 错误码表 `193=tenant_sync (F014/F015)` 已存在；验证即可
  **错误码清单**:
  ```python
  SsoHmacInvalidError              Code=19301  # HMAC 签名无效（AC-06）
  SsoDeptMountConflictError        Code=19302  # tenant_mapping 挂载冲突（父链已挂载）
  SsoTenantDisabledError           Code=19303  # 叶子 Tenant 非 active 阻断登录
  SsoCrossSourceUserError          Code=19304  # Cross-source 用户冲突（仅极端场景）
  SsoTsConflictSkippedError        Code=19310  # ts 冲突被跳过（内部告警用，不返前端）
  SsoUserLockBusyError             Code=19311  # Redis SETNX 失败，同 user 并发登录
  SsoDeptParentMissingError        Code=19312  # 父链部门未 upsert（AC 边界）
  SsoPrimaryDeptMissingError       Code=19313  # payload 未提供 primary_dept_external_id
  ```
  **`SSOSyncConf` 字段**:
  ```python
  class SSOSyncConf(BaseModel):
      gateway_hmac_secret: str = ''
      signature_header: str = 'X-Signature'
      user_lock_ttl_seconds: int = 30
      orphan_config_id: int = 9999  # OrgSyncConfig seed id
  ```
  **测试**: 无（纯常量 + Pydantic）
  **覆盖 AC**: AC-06（19301）、§5 配置项
  **依赖**: 无

---

### 数据层：Alembic 迁移 + seed

- [x] **T02**: Alembic 迁移 + SQLite table_definitions 同步 + OrgSyncConfig seed
  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f014_sso_sync_fields.py`
  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — `TABLE_DEPARTMENT` 追加两列
  **逻辑**:
  - **revision**: `revision='f014_sso_sync_fields', down_revision=<当前最新>`（实施时 `alembic heads` 确认）
  - **upgrade()**（沿用 F011/F012 的 `_column_exists` / `_index_exists` 幂等 helper）:
    ```python
    if not _column_exists('department', 'is_deleted'):
        op.add_column('department', sa.Column('is_deleted', sa.SmallInteger, nullable=False, server_default='0',
                                              comment='F014 soft delete flag'))
    if not _column_exists('department', 'last_sync_ts'):
        op.add_column('department', sa.Column('last_sync_ts', sa.BigInteger, nullable=False, server_default='0',
                                              comment='F014/F015 INV-T12 ts guard'))
    if not _index_exists('department', 'idx_department_last_sync_ts'):
        op.create_index('idx_department_last_sync_ts', 'department', ['last_sync_ts'])

    # Seed: OrgSyncConfig for SSO realtime (id=9999，避免与用户创建的配置 id 漂移)
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM org_sync_config WHERE id = 9999"
    )).scalar()
    if not exists:
        conn.execute(sa.text("""
            INSERT INTO org_sync_config (id, tenant_id, provider, config_name, auth_type, auth_config,
                                          sync_scope, schedule_type, sync_status, status, create_time, update_time)
            VALUES (9999, 1, 'sso_realtime', 'SSO Gateway (internal)', 'hmac', '{}',
                    '{}', 'manual', 'disabled', 1, NOW(), NOW())
        """))
    ```
  - **downgrade()**: drop column + drop index + `DELETE FROM org_sync_config WHERE id = 9999`
  **测试**: SQLite 测试（T03）绿灯即为 table_definitions 同步佐证；MySQL 手工 `alembic upgrade head` / `downgrade -1` 往返
  **覆盖 AC**: AC-08/AC-09/AC-10（last_sync_ts 字段可用）；org_sync_log 写入（T12）
  **依赖**: T01

---

### 数据层：Department ORM + DAO

- [x] **T03**: `Department` 模型加字段 + `DepartmentDao` 扩展 3 方法 + DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/database/models/department.py` — `Department` 加字段 + `DepartmentDao` 加方法
  **文件（新建）**:
  - `src/backend/test/test_department_sso_dao.py`
  **逻辑**:
  - **`Department` 字段**（追加在 `mounted_tenant_id` 附近）:
    ```python
    is_deleted: int = Field(
        default=0,
        sa_column=Column('is_deleted', SmallInteger, nullable=False, server_default=text('0'),
                         comment='F014 soft delete flag'),
    )
    last_sync_ts: int = Field(
        default=0,
        sa_column=Column('last_sync_ts', BigInteger, nullable=False, server_default=text('0'),
                         index=True,
                         comment='F014/F015 INV-T12 ts guard'),
    )
    ```
  - **`DepartmentDao` 新增 classmethods**:
    - `aget_by_source_external_id(source: str, external_id: str) -> Optional[Department]` — SELECT … WHERE source=? AND external_id=? LIMIT 1（不加 is_deleted 过滤，guard 需要读 is_deleted=1 的行）
    - `aupsert_by_external_id(source, external_id, name, parent_id, sort_order, last_sync_ts) -> Department` — 若 existing 则 UPDATE name/parent_id/sort_order/path/last_sync_ts/status='active'/is_deleted=0，**不触碰 is_tenant_root/mounted_tenant_id**；不存在则 INSERT（先构造新对象再 parent→path 换算）
    - `aarchive_by_external_id(source, external_id, last_sync_ts) -> Optional[Department]` — UPDATE status='archived', is_deleted=1, last_sync_ts=? WHERE source=? AND external_id=? RETURNING row
  **测试**（7 条）:
  - `test_aget_by_source_external_id_found` / `_not_found`
  - `test_aupsert_creates_when_missing` — 新建返回含 id
  - `test_aupsert_updates_name_but_preserves_mount_fields` — 预置 is_tenant_root=1 + mounted_tenant_id=5，upsert 后两字段不变
  - `test_aupsert_resurrect_archived` — existing.is_deleted=1 且 incoming_ts>last_sync_ts → 重置 status='active', is_deleted=0
  - `test_aarchive_sets_flags_and_ts`
  - `test_aarchive_returns_none_when_missing`
  **覆盖 AC**: AC-04/AC-10/AC-11（upsert + archive）
  **依赖**: T02

---

### 基础设施：OrgSyncTsGuard（F014/F015 共用）

- [x] **T04**: `OrgSyncTsGuard` 服务 + 决策矩阵测试
  **文件（新建）**:
  - `src/backend/bisheng/org_sync/domain/services/ts_guard.py`
  - `src/backend/test/test_org_sync_ts_guard.py`
  **逻辑**:
  ```python
  from enum import Enum

  class GuardDecision(str, Enum):
      APPLY = 'apply'
      SKIP_TS = 'skip_ts'

  class OrgSyncTsGuard:
      @classmethod
      async def check_and_update(
          cls,
          existing: Optional[Department],
          incoming_ts: int,
          action: Literal['upsert', 'remove'],
      ) -> GuardDecision:
          if existing is None:
              return GuardDecision.APPLY if action == 'upsert' else GuardDecision.SKIP_TS
          last = existing.last_sync_ts or 0
          if incoming_ts < last:
              return GuardDecision.SKIP_TS
          if incoming_ts == last and action == 'upsert' and existing.is_deleted == 1:
              return GuardDecision.SKIP_TS  # INV-T12 同 ts remove 优先
          return GuardDecision.APPLY
  ```
  纯判断函数；调用方负责成功 upsert/archive 后同步写 `last_sync_ts`。
  **测试**（8 条决策矩阵）:
  - `test_new_existing_upsert_applies`
  - `test_new_existing_remove_skipped`
  - `test_stale_upsert_skipped`
  - `test_stale_remove_skipped`
  - `test_same_ts_upsert_on_active_applies`
  - `test_same_ts_upsert_on_deleted_skipped`  # INV-T12 关键
  - `test_same_ts_remove_applies`
  - `test_newer_ts_upsert_resurrect_applies`
  **覆盖 AC**: AC-08/AC-09/AC-11（INV-T12 核心）
  **依赖**: T03

---

### 基础设施：HMAC 鉴权

- [x] **T05**: `verify_hmac` FastAPI Dependency + body replay + 测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/__init__.py`
  - `src/backend/bisheng/sso_sync/domain/__init__.py`
  - `src/backend/bisheng/sso_sync/domain/services/__init__.py`
  - `src/backend/bisheng/sso_sync/domain/services/hmac_auth.py`
  - `src/backend/test/test_sso_hmac_auth.py`
  - `src/backend/test/fixtures/sso_sync.py` — 复用 fixture（`hmac_signer` / `hmac_secret_configured`）
  **逻辑**:
  ```python
  import hmac, hashlib
  from fastapi import Request
  from bisheng.common.services.config_service import settings
  from bisheng.common.errcode.sso_sync import SsoHmacInvalidError

  def compute_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
      msg = f'{method.upper()}\n{path}\n'.encode() + raw_body
      return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()

  async def verify_hmac(request: Request) -> None:
      secret = settings.sso_sync.gateway_hmac_secret
      if not secret:
          raise SsoHmacInvalidError.http_exception('hmac secret not configured')
      provided = (request.headers.get(settings.sso_sync.signature_header, '') or '').lower().strip()
      if not provided:
          raise SsoHmacInvalidError.http_exception('missing signature header')
      raw = await request.body()
      # body replay：让下游 Pydantic 解析器可再次读取
      async def _receive():
          return {'type': 'http.request', 'body': raw, 'more_body': False}
      request._receive = _receive
      expected = compute_signature(request.method, request.url.path, raw, secret)
      if not hmac.compare_digest(expected, provided):
          raise SsoHmacInvalidError.http_exception('invalid signature')
  ```
  **测试**（5 条）:
  - `test_valid_signature_passes` — 用 `hmac_signer` fixture 签名 → dep 不抛
  - `test_missing_signature_header_returns_401`
  - `test_invalid_signature_returns_401`
  - `test_empty_secret_returns_401` — 未配置密钥，所有请求拒绝
  - `test_body_replay_enables_downstream_read` — 调 dep 后手动 `await request.body()` 第二次返回一致
  **覆盖 AC**: AC-06
  **依赖**: T01

---

### 数据结构：Pydantic Schemas

- [x] **T06**: Payload Schemas + validation 测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/schemas/__init__.py`
  - `src/backend/bisheng/sso_sync/domain/schemas/payloads.py`
  - `src/backend/test/test_sso_payload_schemas.py`
  **Schema 清单**（对齐 spec §5.1 + §5.2）:
  ```python
  class UserAttrsDTO(BaseModel):
      name: Optional[str] = None
      email: Optional[str] = None
      phone: Optional[str] = None

  class TenantMappingItem(BaseModel):
      dept_external_id: str
      tenant_code: str
      tenant_name: str
      initial_quota: Optional[dict] = None
      initial_admin_external_ids: Optional[list[str]] = None

  class LoginSyncRequest(BaseModel):
      external_user_id: str
      primary_dept_external_id: Optional[str] = None  # 无主部门容错 → 降级 Root
      secondary_dept_external_ids: Optional[list[str]] = Field(default_factory=list)
      user_attrs: UserAttrsDTO = Field(default_factory=UserAttrsDTO)
      root_tenant_id: int = 1
      tenant_mapping: Optional[list[TenantMappingItem]] = None
      ts: int  # 必填（INV-T12）

  class LoginSyncResponse(BaseModel):
      user_id: int
      leaf_tenant_id: int
      token: str

  class DepartmentUpsertItem(BaseModel):
      external_id: str
      name: str
      parent_external_id: Optional[str] = None  # None = 顶级（Root 下）
      sort: int = 0
      ts: Optional[int] = None

  class DepartmentsSyncRequest(BaseModel):
      upsert: list[DepartmentUpsertItem] = Field(default_factory=list)
      remove: list[str] = Field(default_factory=list)
      source_ts: Optional[int] = None  # 批次 ts，单条无 ts 时回退

  class BatchResult(BaseModel):
      applied_upsert: int = 0
      applied_remove: int = 0
      skipped_ts_conflict: int = 0
      orphan_triggered: list[int] = Field(default_factory=list)
      errors: list[dict] = Field(default_factory=list)
  ```
  **测试**（5 条）:
  - `test_login_sync_request_requires_external_user_id`
  - `test_login_sync_request_requires_ts`
  - `test_tenant_mapping_item_requires_dept_and_tenant_code`
  - `test_departments_sync_allows_empty_lists`
  - `test_upsert_item_missing_parent_is_valid` — 顶级部门
  **覆盖 AC**: AC-01/AC-10（payload 契约）
  **依赖**: T01

---

### 服务层：DeptUpsertService

- [x] **T07**: `DeptUpsertService` 幂等树构建 + 测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/services/dept_upsert_service.py`
  - `src/backend/test/test_dept_upsert_service.py`
  **接口**（spec §5.2 + INV-T12）:
  ```python
  class DeptUpsertService:
      @classmethod
      async def assert_parent_chain_exists(cls, external_ids: Iterable[str]) -> dict[str, Department]:
          """对每个 external_id 确保存在（不创建），miss → raise SsoDeptParentMissingError。返回 ext→Department 映射。"""

      @classmethod
      async def upsert_from_sync_payload(
          cls,
          existing: Optional[Department],
          item: DepartmentUpsertItem,
          source: str,
          last_sync_ts: int,
      ) -> Department:
          """
          单条 upsert；调用方已完成 OrgSyncTsGuard 决策。
          不触碰 is_tenant_root / mounted_tenant_id（PRD §5.2.5）。
          parent_external_id 必须已存在（否则 raise 19312）。
          """
  ```
  **测试**（7 条）:
  - `test_assert_parent_chain_raises_when_missing` — 19312
  - `test_upsert_creates_new_department`
  - `test_upsert_updates_name_only_preserves_mount_fields`
  - `test_upsert_resets_is_deleted_on_resurrect`
  - `test_upsert_raises_when_parent_missing`
  - `test_upsert_top_level_dept_no_parent`
  - `test_upsert_path_recomputed_when_parent_changes`
  **覆盖 AC**: AC-01（父链）、AC-04（不覆盖 mount）
  **依赖**: T03

---

### 服务层：LoginSyncService 核心

- [x] **T08**: `LoginSyncService.execute` 11 步编排 + 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`
  - `src/backend/test/test_sso_login_sync_service.py`
  **逻辑**（plan §4 步骤 1-11）:
  ```python
  class LoginSyncService:
      SOURCE = 'sso'

      @classmethod
      async def execute(cls, payload: LoginSyncRequest, request_ip: str) -> LoginSyncResponse:
          # ① HMAC 已通过 Depends 验证（上层保障）
          # ② Redis 并发锁
          lock_key = f'user:sso_lock:{payload.external_user_id}'
          async with cls._acquire_user_lock(lock_key):
              with bypass_tenant_filter():
                  tok = set_current_tenant_id(ROOT_TENANT_ID)
                  try:
                      # ③ 主部门缺失容错 or 19313
                      if not payload.primary_dept_external_id:
                          # Spec §3 允许回退 Root；仅为无主部门用户登录
                          primary_dept = None
                          secondary_depts = []
                      else:
                          # ④ 父链校验（严格）
                          all_exts = [payload.primary_dept_external_id,
                                      *(payload.secondary_dept_external_ids or [])]
                          ext_to_dept = await DeptUpsertService.assert_parent_chain_exists(all_exts)
                          primary_dept = ext_to_dept[payload.primary_dept_external_id]
                          secondary_depts = [ext_to_dept[e] for e in (payload.secondary_dept_external_ids or [])
                                             if e in ext_to_dept]

                      # ⑤ tenant_mapping 幂等处理（见 T10）
                      await TenantMappingHandler.process(
                          payload.tenant_mapping or [], request_ip=request_ip)

                      # ⑥ Upsert User（见 T09 的 cross-source 复用分支）
                      user = await cls._upsert_user(payload, request_ip)

                      # ⑦ Upsert UserDepartment
                      if primary_dept is not None:
                          await cls._ensure_primary(user.user_id, primary_dept.id)
                          await cls._ensure_secondaries(user.user_id, [d.id for d in secondary_depts])

                      # ⑧ sync_user
                      leaf_tenant = await UserTenantSyncService.sync_user(
                          user.user_id, trigger=UserTenantSyncTrigger.LOGIN,
                      )

                      # ⑨ 禁用阻断（见 T14）
                      if leaf_tenant.status != 'active':
                          raise SsoTenantDisabledError.http_exception(
                              f'tenant {leaf_tenant.id} status={leaf_tenant.status}')

                      # ⑩ JWT 签发
                      auth_jwt = AuthJwt()
                      token_version = await UserDao.aget_token_version(user.user_id)
                      token = LoginUser.create_access_token(
                          user, auth_jwt,
                          tenant_id=leaf_tenant.id, token_version=token_version,
                      )
                      return LoginSyncResponse(user_id=user.user_id,
                                               leaf_tenant_id=leaf_tenant.id,
                                               token=token)
                  finally:
                      current_tenant_id.reset(tok)
          # ⑪ org_sync_log 写入：异步/非事务，失败 warn 不阻塞（见 T12）
  ```
  **测试**（6 条集成，用 sqlite + mock_redis）:
  - `test_new_user_happy_path` **AC-01** — 新用户全链路：user/user_department/user_tenant 建立；JWT 含 tenant_id
  - `test_existing_user_primary_change_triggers_sync` **AC-02** — 先 sync 到 dept A，再换 dept B（不同 mount），token_version +1
  - `test_primary_dept_missing_falls_back_to_root` — payload.primary 为空 → 回 Root
  - `test_parent_chain_missing_raises_19312` — Gateway 未推父 → 拒登
  - `test_user_lock_busy_returns_19311` — 同 user_id 并发 2 次 → 一个成功一个 19311
  - `test_disabled_user_returns_UserForbidden` — `user.delete=1`
  **覆盖 AC**: AC-01 / AC-02 / AC-07（骨架；性能在 T15）
  **依赖**: T03, T04, T05, T06, T07

---

### 服务层：Cross-source 用户复用

- [x] **T09**: `_upsert_user` cross-source 分支 + 测试
  **文件（修改）**:
  - `src/backend/bisheng/sso_sync/domain/services/login_sync_service.py` — 添加 `_upsert_user` helper
  - `src/backend/test/test_sso_login_sync_service.py` — 追加测试
  **逻辑**:
  ```python
  @classmethod
  async def _upsert_user(cls, payload, request_ip) -> User:
      ext = payload.external_user_id
      user = await UserDao.aget_by_source_external_id(cls.SOURCE, ext)
      if user is None:
          # 全局查：其他 source（如 feishu）命中 → 转移 source
          legacy = await UserDao.aget_by_external_id(ext)
          if legacy is not None:
              old_source = legacy.source
              legacy.source = cls.SOURCE
              await UserDao.aupdate_user(legacy)
              await AuditLogDao.ainsert_v2(
                  tenant_id=ROOT_TENANT_ID, operator_id=0,
                  operator_tenant_id=ROOT_TENANT_ID,
                  action='user.source_migrated',
                  target_type='user', target_id=str(legacy.user_id),
                  metadata={'old_source': old_source, 'new_source': cls.SOURCE,
                            'external_id': ext, 'via': 'sso_realtime'},
                  ip_address=request_ip,
              )
              user = legacy
          else:
              new_user = User(
                  user_name=payload.user_attrs.name or ext,
                  email=payload.user_attrs.email,
                  phone_number=payload.user_attrs.phone,
                  external_id=ext,
                  source=cls.SOURCE,
                  password='',
              )
              user = await UserDao.add_user_and_default_role(new_user)
      else:
          dirty = False
          if payload.user_attrs.name and user.user_name != payload.user_attrs.name:
              user.user_name, dirty = payload.user_attrs.name, True
          if payload.user_attrs.email and user.email != payload.user_attrs.email:
              user.email, dirty = payload.user_attrs.email, True
          if dirty:
              await UserDao.aupdate_user(user)
      if user.delete == 1:
          raise UserForbiddenError.http_exception()
      return user
  ```
  **测试**（3 条）:
  - `test_cross_source_feishu_user_reused_and_migrated` — 预置 source='feishu' 用户 → 转移为 'sso' + audit 写入
  - `test_new_sso_user_created_with_default_role`
  - `test_existing_sso_user_name_email_updated`
  **覆盖 AC**: 边界"Cross-source 复用"（Phase 3 决策 2）
  **依赖**: T08

---

### 服务层：tenant_mapping 幂等挂载

- [x] **T10**: `TenantMappingHandler` + 测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/services/tenant_mapping_handler.py`
  - `src/backend/test/test_sso_tenant_mapping.py`
  **逻辑**（Phase 3 决策 3：允许绕过 super_admin）:
  ```python
  class TenantMappingHandler:
      @classmethod
      async def process(cls, mappings: list[TenantMappingItem], request_ip: str) -> None:
          for item in mappings:
              dept = await DepartmentDao.aget_by_source_external_id('sso', item.dept_external_id)
              if dept is None:
                  logger.warning('tenant_mapping dept not found: %s', item.dept_external_id)
                  continue
              if dept.is_tenant_root == 1:
                  continue  # 已挂载，幂等忽略
              # 父链上已有挂载点 → INV-T1 2 层锁
              ancestor_mount = await DepartmentDao.aget_ancestors_with_mount(dept.id)
              if ancestor_mount is not None:
                  raise SsoDeptMountConflictError.http_exception(
                      f'dept {dept.id} parent chain already mounted to tenant {ancestor_mount.mounted_tenant_id}')
              # 创建 Child Tenant + 挂载（绕过 TenantMountService._require_super）
              tenant = await TenantDao.acreate_tenant(Tenant(
                  tenant_code=item.tenant_code,
                  tenant_name=item.tenant_name,
                  parent_tenant_id=ROOT_TENANT_ID,
                  status='active',
              ))
              await DepartmentDao.aset_mount(dept.id, tenant.id)
              await AuditLogDao.ainsert_v2(
                  tenant_id=tenant.id, operator_id=0,
                  operator_tenant_id=ROOT_TENANT_ID,
                  action='tenant.mount',
                  target_type='tenant', target_id=str(tenant.id),
                  metadata={'dept_id': dept.id, 'tenant_code': item.tenant_code,
                            'via': 'sso_realtime'},
                  ip_address=request_ip,
              )
  ```
  **测试**（4 条）:
  - `test_new_mount_creates_tenant_and_audit` **AC-03**
  - `test_already_mounted_dept_is_idempotent_skip` **AC-03** — 同 payload 两次 → 仅 1 个 tenant
  - `test_parent_already_mounted_raises_19302`
  - `test_missing_dept_is_warned_not_raised` — Gateway 还没推送该 dept，不挂载不报错
  **覆盖 AC**: AC-03
  **依赖**: T03

---

### 服务层：DepartmentsSyncService 批量

- [x] **T11**: `DepartmentsSyncService.execute` 批量编排 + 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/services/departments_sync_service.py`
  - `src/backend/test/test_sso_departments_sync_service.py`
  **逻辑**（plan §5 流程）:
  ```python
  class DepartmentsSyncService:
      @classmethod
      async def execute(cls, payload: DepartmentsSyncRequest, request_ip: str) -> BatchResult:
          result = BatchResult()
          with bypass_tenant_filter():
              tok = set_current_tenant_id(ROOT_TENANT_ID)
              try:
                  # Upsert 轮
                  for item in payload.upsert:
                      try:
                          existing = await DepartmentDao.aget_by_source_external_id('sso', item.external_id)
                          incoming_ts = item.ts or payload.source_ts or 0
                          decision = await OrgSyncTsGuard.check_and_update(existing, incoming_ts, 'upsert')
                          if decision == GuardDecision.SKIP_TS:
                              result.skipped_ts_conflict += 1
                              continue
                          await DeptUpsertService.upsert_from_sync_payload(
                              existing=existing, item=item, source='sso', last_sync_ts=incoming_ts)
                          result.applied_upsert += 1
                      except SsoDeptParentMissingError as e:
                          result.errors.append({'type': 'parent_missing', 'external_id': item.external_id,
                                                'error': str(e)})
                      except Exception as e:
                          result.errors.append({'type': 'upsert_error', 'external_id': item.external_id,
                                                'error': str(e)})

                  # Remove 轮
                  for ext_id in payload.remove:
                      try:
                          dept = await DepartmentDao.aget_by_source_external_id('sso', ext_id)
                          if dept is None:
                              continue
                          incoming_ts = payload.source_ts or 0
                          decision = await OrgSyncTsGuard.check_and_update(dept, incoming_ts, 'remove')
                          if decision == GuardDecision.SKIP_TS:
                              result.skipped_ts_conflict += 1
                              continue
                          mounted_before = dept.mounted_tenant_id
                          await DepartmentDao.aarchive_by_external_id('sso', ext_id, last_sync_ts=incoming_ts)
                          await DepartmentDeletionHandler.on_deleted(
                              dept.id, deletion_source=DeletionSource.SSO_REALTIME)
                          if mounted_before:
                              result.orphan_triggered.append(mounted_before)
                          result.applied_remove += 1
                      except Exception as e:
                          result.errors.append({'type': 'remove_error', 'external_id': ext_id,
                                                'error': str(e)})
              finally:
                  current_tenant_id.reset(tok)
          # org_sync_log 在 T12 中 flush
          return result
  ```
  **测试**（6 条）:
  - `test_upsert_batch_happy_path` **AC-10**
  - `test_remove_mounted_triggers_on_deleted` **AC-04** — `DepartmentDeletionHandler` 被 mock 断言调用
  - `test_remove_unmounted_no_orphan_trigger`
  - `test_ts_conflict_skips_and_counts` **AC-09**
  - `test_single_item_failure_does_not_abort_batch` **AC-11**
  - `test_same_ts_upsert_after_remove_skipped` **INV-T12**
  **覆盖 AC**: AC-04 / AC-09 / AC-10 / AC-11
  **依赖**: T03, T04, T07

---

### 基础设施：org_sync_log 写入

- [x] **T12**: `_OrgSyncLogBuffer` 工具 + 测试
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/domain/services/org_sync_log_writer.py`
  - `src/backend/test/test_sso_org_sync_log_writer.py`
  **逻辑**:
  ```python
  class _OrgSyncLogBuffer:
      """单次 SSO 调用累积的日志，结尾 flush 到 org_sync_log 表。"""
      def __init__(self):
          self.dept_created = 0
          self.dept_updated = 0
          self.dept_archived = 0
          self.member_created = 0
          self.member_updated = 0
          self.errors: list[dict] = []
          self.warnings: list[dict] = []

      def dept_upserted(self, external_id, is_new: bool): ...
      def dept_archived_event(self, external_id): ...
      def member_upserted(self, user_id, is_new: bool): ...
      def warn(self, event_type, external_id, **kwargs): ...
      def error(self, event_type, external_id, err: str): ...

  async def flush_log(buffer: _OrgSyncLogBuffer, *, trigger_type: str,
                      config_id: int | None = None, status: str = 'success') -> None:
      config_id = config_id or settings.sso_sync.orphan_config_id  # 默认 9999
      await OrgSyncLogDao.acreate(OrgSyncLog(
          config_id=config_id, tenant_id=ROOT_TENANT_ID,
          trigger_type=trigger_type, status=status,
          dept_created=buffer.dept_created, dept_updated=buffer.dept_updated,
          dept_archived=buffer.dept_archived,
          member_created=buffer.member_created, member_updated=buffer.member_updated,
          error_details={'errors': buffer.errors, 'warnings': buffer.warnings},
          start_time=..., end_time=...,
      ))
  ```
  **集成到 T08/T11**: T08 `LoginSyncService.execute` 和 T11 `DepartmentsSyncService.execute` 在 return 前调 `flush_log`。
  **测试**（3 条）:
  - `test_flush_writes_row_with_stats`
  - `test_flush_uses_seed_config_id`
  - `test_error_details_json_serializable`
  **覆盖 AC**: AC-09/AC-10（告警 trace）
  **依赖**: T02, T08, T11

---

### 端点：Router + Exempt Paths

- [x] **T13**: API endpoints + Router 挂载 + TENANT_CHECK_EXEMPT_PATHS
  **文件（新建）**:
  - `src/backend/bisheng/sso_sync/api/__init__.py`
  - `src/backend/bisheng/sso_sync/api/router.py`
  - `src/backend/bisheng/sso_sync/api/endpoints/__init__.py`
  - `src/backend/bisheng/sso_sync/api/endpoints/login_sync.py`
  - `src/backend/bisheng/sso_sync/api/endpoints/departments_sync.py`
  - `src/backend/test/test_sso_api_integration.py`
  **文件（修改）**:
  - `src/backend/bisheng/api/router.py` — import `sso_sync_router` 并 `router.include_router(sso_sync_router)`
  - `src/backend/bisheng/utils/http_middleware.py` — `TENANT_CHECK_EXEMPT_PATHS` 加入 `/api/v1/internal/sso/login-sync` / `/api/v1/departments/sync`
  **端点骨架**:
  ```python
  # login_sync.py
  @router.post('/internal/sso/login-sync', response_model=UnifiedResponseModel[LoginSyncResponse])
  async def login_sync(
      payload: LoginSyncRequest,
      request: Request,
      _: None = Depends(verify_hmac),
  ):
      result = await LoginSyncService.execute(payload, request_ip=get_request_ip(request))
      return resp_200(result)

  # departments_sync.py
  @router.post('/departments/sync', response_model=UnifiedResponseModel[BatchResult])
  async def departments_sync(
      payload: DepartmentsSyncRequest,
      request: Request,
      _: None = Depends(verify_hmac),
  ):
      result = await DepartmentsSyncService.execute(payload, request_ip=get_request_ip(request))
      return resp_200(result)
  ```
  **测试**（3 条，FastAPI TestClient 端到端）:
  - `test_login_sync_route_responds_200_with_valid_hmac`
  - `test_departments_sync_route_responds_200_with_valid_hmac`
  - `test_routes_return_401_without_hmac`
  **覆盖 AC**: AC-01/AC-10/AC-06
  **依赖**: T05, T06, T08, T11

---

### 阻断分支：Tenant 禁用 + 主部门缺失

- [x] **T14**: 禁用 Tenant 阻断 + `primary_dept_external_id` None 分支
  **文件（修改）**:
  - `src/backend/bisheng/sso_sync/domain/services/login_sync_service.py` — 已在 T08 骨架写入 ⑨ 步；本任务仅补齐测试与容错
  - `src/backend/test/test_sso_login_sync_service.py`
  **测试**（3 条）:
  - `test_disabled_leaf_tenant_returns_19303` — 预置 Tenant.status='disabled'，登录 → 403+19303
  - `test_archived_leaf_tenant_returns_19303`
  - `test_orphaned_leaf_tenant_returns_19303`
  **覆盖 AC**: AC-04 + §3 边界"Tenant 禁用状态下登录"
  **依赖**: T08

---

### 验证：AC 对照 + 手工 QA

- [x] **T15**: AC 对照矩阵 + /task-review + /e2e-test + 性能专项
  **内容**:
  - 每任务完成后执行 `/task-review features/v2.5.1/014-sso-org-realtime-sync <Txx>`
  - 全部完成后执行 `/e2e-test features/v2.5.1/014-sso-org-realtime-sync`
  - 性能专项：独立 `locust_sso_sync.py`，10k 并发 P99 < 500ms（AC-07）；不在 CI
  - 更新 spec §7 手工 QA 清单为 `[x]`
  - 汇总 AC-01 ~ AC-11 覆盖表
  **覆盖 AC**: 全部
  **依赖**: T01-T14

---

## AC 对照矩阵

| AC | 任务 | 测试 |
|----|------|------|
| AC-01 | T06, T07, T08 | `test_new_user_happy_path` + endpoint integration |
| AC-02 | T08 | `test_existing_user_primary_change_triggers_sync` |
| AC-03 | T10 | `test_new_mount_creates_tenant_and_audit` + `test_already_mounted_dept_is_idempotent_skip` |
| AC-04 | T11, T14 | `test_remove_mounted_triggers_on_deleted` + 禁用阻断 3 条 |
| AC-05 | — | F011 `DepartmentDeletionHandler` 负责；本 feature 仅触发 |
| AC-06 | T05 | `test_*_signature_*` + `test_routes_return_401_without_hmac` |
| AC-07 | T15 | 性能专项 locust 脚本 |
| AC-08 | T03, T04 | `test_aupsert_*` + ts 决策矩阵 |
| AC-09 | T04, T11 | `test_ts_conflict_skips_and_counts` + `test_stale_upsert_skipped` |
| AC-10 | T11 | `test_upsert_batch_happy_path` |
| AC-11 | T11 | `test_single_item_failure_does_not_abort_batch` |

---

## 不变量映射

- **INV-T12**（ts 最大为准 + 同 ts remove 优先）：T04 决策矩阵 + T11 remove 轮实现
- **INV-T7**（管理类操作强制 audit）：T09 `user.source_migrated` + T10 `tenant.mount`
- **INV-T1**（2 层嵌套锁）：T10 `ancestor_mount` 检查返 19302

---

## 开发命令

```bash
# 启动分支
git checkout 2.5.0-PM
git pull
git checkout -b feat/v2.5.1/014-sso-org-realtime-sync

# 单任务跑测
cd src/backend
.venv/bin/pytest test/test_sso_<task>.py -v

# 迁移往返（T02）
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1

# 启动后手工 QA（T15）
export BS_SSO_SYNC__GATEWAY_HMAC_SECRET=test-secret-12345
.venv/bin/uvicorn bisheng.main:app --port 7860
# 用 httpx/curl 发签名请求到 /api/v1/internal/sso/login-sync + /api/v1/departments/sync
```
