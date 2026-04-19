# Tasks: F013-tenant-fga-tree (OpenFGA 升级 + 权限链路)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/013-tenant-fga-tree`（base=`2.5.0-PM`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-18/20/21 三轮 Review 定稿；Round 3 DSL 收窄确定 |
| tasks.md | ✅ 已拆解 | 2026-04-19 /sdd-review tasks 通过；10 任务（3 项低中严重度 issue 已修复） |
| 实现 | 🔲 未开始 | 0 / 10 完成 |

---

## 开发模式

**后端 Test-Alongside（F011 同款）**：
- F000 已搭建 pytest 基础设施（`test/conftest.py` + SQLite `db_session` fixture + `test/fixtures/factories.py`）
- DSL / Service / Client 单测合并在同一任务（与 F011 T02 风格一致）
- OpenFGA 端到端测试（T09）依赖本地或远程 OpenFGA store，可跳过且记录在「实际偏差记录」

**前端**：N/A — F013 不涉及前端。Tenant Admin 管理 UI 归后续 Feature（F011 `/tenants/{id}/admins` API 已就绪，UI 侧待排期）

**决策锁定**（来自 plan 阶段用户确认，见 `.claude/plans/2-5-2-5-frolicking-quasar.md`）：
- **D1** F013 内 stub `get_visible_tenants` —— 基于 `user_tenant(is_active=1)` 反查，F012 落地后切到 JWT claim；代码中统一加 `# TODO(F012): replace with JWT claim` 锚点
- **D2** 沿用 `authorization_model.py`（Python 单一来源）；spec §5 的 `.yaml` 仅作叙述性表达
- **D4** 双 model 灰度：`openfga.dual_model_mode` + `openfga.legacy_model_id`；写入双写、check 走新 model
- **D5** `PermissionService.check` 增量插入 L2/L3（不重写现有 L1-L5）
- **错误码**：`192xx`（已在 CLAUDE.md + release-contract.md 声明，无冲突）

---

## 依赖图

```
T01 (错误码 19201-19204)  ─────────┐
                                   │
T02 (DSL 升级)  ─┐                 │
                 │                 │
T03 (配置扩展)  ─┤                 │
                 │                 │
                 ↓                 ↓
T04 (Manager 双 model bootstrap)   │
   │                               │
   ↓                               │
T05 (Client 双写旁路)  ─────────────┤
                                   │
T06 (UserPayload stub)  ← T01 ─────┤
                                   │
T07 (TenantAdminService)  ← T01, T05
   │
   ↓   (T06 独立)
T08 (PermissionService.check L2/L3)  ← T06, T07
   │
   ↓
T09 (集成测试 FGA 端到端 + AC 映射)  ← T02, T05, T06, T07, T08
   │
   ↓
T10 (手工 QA + ac-verification.md)  ← T01-T09
```

---

## Tasks

### 基础：错误码与文档对齐

- [x] **T01**: 错误码注册（192xx）+ release-contract / CLAUDE.md 同步校验
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/tenant_fga.py` — 4 个错误码类
  **文件（修改）**:
  - `features/v2.5.1/013-tenant-fga-tree/tasks.md` — 本文件状态表同步
  - （release-contract.md 表 3 "192 = tenant_fga F013" 已声明，CLAUDE.md 同步已存在 —— **仅校验不修改**）
  **逻辑**:
  ```python
  # src/backend/bisheng/common/errcode/tenant_fga.py
  from .base import BaseErrorCode

  # Tenant FGA tree module error codes, module code: 192
  # (Declared in CLAUDE.md + release-contract.md; this file is the authoritative registry)

  class OpenFGAConnectionError(BaseErrorCode):
      Code: int = 19201
      Msg: str = 'OpenFGA service unreachable'

  class OpenFGAModelNotFoundError(BaseErrorCode):
      Code: int = 19202
      Msg: str = 'OpenFGA authorization model not found for given model_id'

  class OpenFGATupleCompensationFailedError(BaseErrorCode):
      Code: int = 19203
      Msg: str = 'Failed to compensate FGA tuple write after max retries'

  class RootTenantAdminNotAllowedError(BaseErrorCode):
      Code: int = 19204
      Msg: str = 'Root tenant admin granting is forbidden; use system:global#super_admin instead'
  ```
  **测试**: 无（纯常量类定义；被下游 Task 引用时隐式覆盖）
  **覆盖 AC**: AC-13（19204 拦截）、spec §10 错误码清单
  **依赖**: 无

---

### DSL 层：OpenFGA 授权模型升级

- [x] **T02**: OpenFGA authorization_model 升级（tenant.shared_to + 资源 viewer 补丁 + llm_server/llm_model 新增）
  **文件（修改）**:
  - `src/backend/bisheng/core/openfga/authorization_model.py` —
    - `MODEL_VERSION` 提升到 `v2.0.0`
    - `tenant` 类型新增 `shared_to` 关系（`directly_related_user_types: [{type: tenant}]`）
    - `_standard_resource_type()` 签名新增 `viewer_includes_tenant_shared: bool = True` 形参（默认 True，仅 viewer 追加 `tenant#shared_to#member`，**manager/editor 不加**）
    - 新增两个顶层资源类型：`llm_server` / `llm_model`（无 parent，复用 `_standard_resource_type`；F020 预置依赖）
  **文件（修改）**:
  - `src/backend/test/test_openfga_authorization_model.py`（如不存在则新建） — DSL 结构断言
  **逻辑**:
  - **`tenant` 类型元数据扩展**（在现有 `admin` / `member` 之后追加）:
    ```python
    # === tenant: admin + member + shared_to ===
    {
        'type': 'tenant',
        'relations': {
            'admin': {'this': {}},
            'member': {'this': {}},
            'shared_to': {'this': {}},
        },
        'metadata': {
            'relations': {
                'admin': {'directly_related_user_types': [{'type': 'user'}]},
                'member': {'directly_related_user_types': [{'type': 'user'}]},
                'shared_to': {'directly_related_user_types': [{'type': 'tenant'}]},
            },
        },
    },
    ```
    **不加** `tenant#parent` 关系（2026-04-20 Round 2 收窄，spec AD-05）。
  - **`_standard_resource_type()` 签名扩展**：
    ```python
    def _standard_resource_type(type_name: str, *, has_parent: bool = False,
                                parent_types: list = None,
                                viewer_includes_tenant_shared: bool = True) -> dict:
        # ... 既有逻辑保持
        # viewer metadata：在原 _user_types() 列表末尾追加 tenant#shared_to#member
        viewer_user_types = _user_types()
        if viewer_includes_tenant_shared:
            viewer_user_types.append({'type': 'tenant', 'relation': 'shared_to#member'})
        metadata['viewer'] = {'directly_related_user_types': viewer_user_types}
        # ❌ manager / editor 的 metadata **不变**（保持 _user_types() 三源）—— Round 3 收窄
    ```
    注：OpenFGA protobuf encoding 使用 `relation: 'shared_to#member'`；运行时元组写入格式 `tenant:{root_id}#shared_to#member`。
  - **新增 llm_server / llm_model**（在 `dashboard` 之后追加）：
    ```python
    _standard_resource_type('llm_server'),
    _standard_resource_type('llm_model'),
    ```
    注：F020 LLM 多租户在 T07 TenantAdminService 之后会消费；此处仅预置 DSL，F020 Feature 负责业务落地。
  **测试**（`test_openfga_authorization_model.py`）:
  - `test_tenant_has_shared_to_relation` — `model['type_definitions']` 中 tenant 类型含 `shared_to` 且指向 `{'type': 'tenant'}`
  - `test_tenant_has_no_parent_relation` — tenant 类型 relations 不含 `parent`（AD-05 回归）
  - `test_knowledge_space_viewer_includes_tenant_shared` — viewer metadata 含 `{'type': 'tenant', 'relation': 'shared_to#member'}`
  - `test_knowledge_space_manager_excludes_tenant_shared` — manager metadata **不**含 tenant 类型条目（Round 3 收窄）
  - `test_knowledge_space_editor_excludes_tenant_shared` — editor metadata **不**含 tenant 类型条目
  - `test_llm_server_type_exists` — 类型列表含 `llm_server`
  - `test_llm_model_type_exists` — 类型列表含 `llm_model`
  - `test_llm_server_viewer_includes_tenant_shared` — llm_server viewer 含 `tenant#shared_to#member`
  - `test_model_version_bumped_to_v2` — `MODEL_VERSION == 'v2.0.0'`
  **覆盖 AC**: AC-01（新 model 部署）、AC-07（shared_to 分发 ReBAC）、AD-01 / AD-05（DSL 结构收窄）、spec §5 DSL
  **依赖**: 无（纯 DSL 数据结构改造）

---

### 配置与启动层：双 model 灰度支持

- [x] **T03**: `OpenFGAConf` 扩展（dual_model_mode / legacy_model_id）
  **文件（修改）**:
  - `src/backend/bisheng/core/config/openfga.py` — `OpenFGAConf` 新增 2 字段
  **文件（修改）**:
  - `src/backend/bisheng/config.yaml` —
    `openfga` 配置块新增默认值（dual_model_mode=false；legacy_model_id=null）
    （**需 grep 确认配置 key**：`grep -n 'openfga:' src/backend/bisheng/config.yaml`）
  **逻辑**:
  ```python
  # src/backend/bisheng/core/config/openfga.py
  class OpenFGAConf(BaseModel):
      """OpenFGA connection and behavior configuration."""
      enabled: bool = Field(default=True, ...)
      api_url: str = Field(default='http://localhost:8080', ...)
      store_name: str = Field(default='bisheng', ...)
      store_id: Optional[str] = Field(default=None, ...)
      model_id: Optional[str] = Field(default=None, ...)
      timeout: int = Field(default=5, ...)

      # ── v2.5.1 F013 新增：双 model 灰度 ──
      dual_model_mode: bool = Field(
          default=False,
          description='Enable dual-model gray release: writes go to both model_id and legacy_model_id; '
                      'check still runs against model_id only',
      )
      legacy_model_id: Optional[str] = Field(
          default=None,
          description='Previous authorization model id, used during 2-week gray period. '
                      'Only effective when dual_model_mode=true',
      )
  ```
  **测试**（合入 `test_openfga_config.py`，如不存在则新建）:
  - `test_dual_model_mode_default_false` — 默认 `dual_model_mode=False`
  - `test_legacy_model_id_default_none` — 默认 `legacy_model_id=None`
  - `test_openfga_conf_accepts_dual_mode_true` — 实例化 `OpenFGAConf(dual_model_mode=True, legacy_model_id='xxx')` 不抛异常
  **覆盖 AC**: AC-09（灰度期旧 model 读写）、AD-04（灰度策略）
  **依赖**: 无

---

- [x] **T04**: `FGAManager` 双 model bootstrap
  **文件（修改）**:
  - `src/backend/bisheng/core/openfga/manager.py` — `_async_initialize` 在写新 model 时，若 `dual_model_mode=True` 且 `legacy_model_id` 已配置，保留旧 id 在 client 上
  **文件（修改）**:
  - `src/backend/bisheng/core/openfga/client.py` — `FGAClient.__init__` 新增 `legacy_model_id: Optional[str] = None` 形参（**为 T05 铺路，此 Task 仅加字段不改逻辑**）
  **逻辑**:
  - **`FGAClient.__init__` 签名变化**:
    ```python
    def __init__(self, api_url: str, store_id: str, model_id: str,
                 timeout: int = 5, legacy_model_id: Optional[str] = None):
        # ... 既有逻辑
        self._legacy_model_id = legacy_model_id

    @property
    def legacy_model_id(self) -> Optional[str]:
        return self._legacy_model_id
    ```
  - **`FGAManager._async_initialize` 调用处**：
    ```python
    client = FGAClient(
        api_url=api_url,
        store_id=store_id,
        model_id=model_id,
        timeout=config.timeout,
        legacy_model_id=config.legacy_model_id if config.dual_model_mode else None,
    )
    ```
  - **version 日志增强**：`logger.info('FGAClient initialized: store=%s model=%s legacy=%s dual=%s', ...)`
  **测试**（扩展 `test_openfga_manager.py`，如不存在则新建）:
  - `test_manager_passes_legacy_model_id_when_dual_mode` — mock config `dual_model_mode=True, legacy_model_id='xxx'`，断言 client 构造参数含 `legacy_model_id='xxx'`
  - `test_manager_ignores_legacy_when_dual_mode_false` — `dual_model_mode=False` 时 client 的 `legacy_model_id=None`（即使配置文件有值）
  - `test_fga_client_legacy_model_id_default_none` — `FGAClient(...)` 不传该参时 `client.legacy_model_id is None`
  **覆盖 AC**: AC-09（灰度期 client 持有双 model）
  **依赖**: T02, T03

---

- [x] **T05**: `FGAClient` 双写旁路（write_tuples 灰度期双写，check 仅走新 model）
  **文件（修改）**:
  - `src/backend/bisheng/core/openfga/client.py` — `write_tuples` 方法灰度期向 legacy model 二次写入
  **逻辑**:
  - **修改 `write_tuples` 方法**：新 model 写成功后，若 `legacy_model_id` 非空，再向旧 model 发一次 write（**旧 model 失败仅记 warning，不抛异常** —— 灰度期弃用中，不阻塞业务）
    ```python
    async def write_tuples(self, writes: list[dict] = None,
                           deletes: list[dict] = None) -> None:
        body = self._build_write_body(writes, deletes)
        if not body:
            return
        # Primary write (new model)
        try:
            await self._post(f'/stores/{self._store_id}/write', body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e
        # Shadow write (legacy model during gray period)
        if self._legacy_model_id:
            try:
                shadow_body = {**body, 'authorization_model_id': self._legacy_model_id}
                await self._post(f'/stores/{self._store_id}/write', shadow_body)
            except Exception as e:  # noqa: BLE001 — gray period tolerance
                logger.warning(
                    'Shadow write to legacy model %s failed (ignored during gray): %s',
                    self._legacy_model_id, e,
                )
    ```
    抽取辅助方法 `_build_write_body` 保持主流程可读。
  - **`check` 方法不变**：`authorization_model_id` 仍取 `self._model_id`（AD-04：仅主 model 参与运行时 check）
  - **`read_tuples` 不变**：读走默认 model；如需审计旧 model，后续单独接口
  **测试**（`test_fga_client_dual_write.py` 新建；使用 httpx_mock 或自制 fake transport）:
  - `test_write_tuples_single_write_when_no_legacy` — `legacy_model_id=None` 时仅一次 POST `/write`
  - `test_write_tuples_double_write_when_legacy_set` — `legacy_model_id='old'` 时两次 POST，第二次 body 含 `authorization_model_id='old'`
  - `test_write_tuples_legacy_failure_does_not_raise` — legacy POST 抛 500，主调用仍 success return（验证容错）
  - `test_write_tuples_primary_failure_raises` — 主 POST 抛 500，`FGAWriteError` 抛出（验证优先级）
  - `test_check_ignores_legacy_model` — 设 legacy 后 `check()` 调用 body `authorization_model_id == self._model_id`
  **覆盖 AC**: AC-09（双 model 灰度）、AD-04
  **依赖**: T04

---

### 领域层：用户可见租户派生

- [x] **T06**: `UserPayload` 扩展 stub —— `get_visible_tenants` / `has_tenant_admin`
  **文件（修改）**:
  - `src/backend/bisheng/common/dependencies/user_deps.py` — `UserPayload` 新增两个 async 方法
  **文件（新建）**:
  - `src/backend/test/test_user_payload_tenant.py` — stub 行为单测
  **逻辑**:
  ```python
  # src/backend/bisheng/common/dependencies/user_deps.py
  from __future__ import annotations

  from typing import List

  from bisheng.user.domain.services.auth import LoginUser

  # ROOT_TENANT_ID: Private-deployment MVP fixes root tenant id to 1.
  # Do NOT read from config — spec §1.5 locks this as a hardcoded invariant.
  ROOT_TENANT_ID = 1


  class UserPayload(LoginUser):
      async def get_visible_tenants(self) -> List[int]:
          """Return the user's visible tenant IDs: [leaf_tenant_id, ROOT_TENANT_ID].

          MVP 2-layer rule: visible set = {leaf} ∪ {root}. Deduplicated if leaf == root.

          TODO(F012): replace with JWT claim `tenant_id` + ROOT_TENANT_ID.
          Currently falls back to UserTenantDao live lookup (is_active=1 record).
          """
          from bisheng.database.models.tenant import UserTenantDao

          leaf_tenant = await UserTenantDao.aget_active_user_tenant(self.user_id)
          leaf_id = leaf_tenant.tenant_id if leaf_tenant else ROOT_TENANT_ID
          if leaf_id == ROOT_TENANT_ID:
              return [ROOT_TENANT_ID]
          return [leaf_id, ROOT_TENANT_ID]

      async def has_tenant_admin(self, tenant_id: int) -> bool:
          """Check if the user is Child Admin of the given tenant via FGA direct tuple.

          Non-inheriting (AD-01). Returns False for Root tenant (Root has no tenant#admin tuple
          — INV-T3); global super_admin should be checked separately via self.is_admin().

          TODO(F012): optionally cache via JWT-embedded admin tenants list.
          """
          if tenant_id == ROOT_TENANT_ID:
              return False
          from bisheng.core.openfga.manager import aget_fga_client
          fga = await aget_fga_client()
          if fga is None:
              return False
          return await fga.check(
              user=f'user:{self.user_id}',
              relation='admin',
              object=f'tenant:{tenant_id}',
          )
  ```
  **测试**（`test_user_payload_tenant.py`，使用 monkeypatch + AsyncMock）:
  - `test_get_visible_tenants_leaf_equals_root_dedupes` — 用户 `UserTenant(tenant_id=1, is_active=1)`，返回 `[1]`
  - `test_get_visible_tenants_child_leaf_returns_leaf_plus_root` — 用户 `UserTenant(tenant_id=5, is_active=1)`，返回 `[5, 1]`
  - `test_get_visible_tenants_no_active_falls_back_to_root` — 无 active 记录，返回 `[1]`
  - `test_has_tenant_admin_false_for_root` — `has_tenant_admin(1)` 直接返回 False（不调 FGA）
  - `test_has_tenant_admin_delegates_to_fga_for_child` — `has_tenant_admin(5)` 调用 fga.check(user, admin, tenant:5)
  - `test_has_tenant_admin_returns_false_when_fga_none` — FGA 未初始化时返回 False（降级安全）
  **覆盖 AC**: AC-02 / AC-03 / AC-05 / AC-06（管理员短路基础）、AD-02（IN 列表）
  **依赖**: T01（错误码供内部异常使用，虽本任务未 raise）

---

### 服务层：Tenant Admin 管理

- [x] **T07**: `TenantAdminService` 新增（Child admin CRUD + Root 守卫）
  **文件（新建）**:
  - `src/backend/bisheng/permission/domain/services/tenant_admin_service.py` — 服务类
  - `src/backend/test/test_tenant_admin_service.py` — 单测
  **文件（修改）**:
  - `src/backend/bisheng/database/models/failed_tuple.py` — **无改动**（已在 F011 落地时就绪，复用 `FailedTupleDao.acreate_batch`）
  **逻辑**:
  ```python
  # src/backend/bisheng/permission/domain/services/tenant_admin_service.py
  from __future__ import annotations

  import logging
  from typing import List, Optional

  from bisheng.common.errcode.tenant_fga import RootTenantAdminNotAllowedError
  from bisheng.common.exceptions.domain import BusinessError
  from bisheng.core.openfga.exceptions import FGAConnectionError
  from bisheng.core.openfga.manager import aget_fga_client
  from bisheng.database.models.tenant import TenantDao

  logger = logging.getLogger(__name__)

  ROOT_TENANT_ID = 1


  class TenantAdminService:
      """Manages tenant-level admin grants (Child Tenants only)."""

      @classmethod
      async def grant_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
          """Grant user the Child Admin role on given tenant.

          Raises RootTenantAdminNotAllowedError (19204) if tenant is Root (id=1 or
          parent_tenant_id IS NULL). Root admin is granted via system:global#super_admin only.
          """
          await cls._guard_not_root(tenant_id)
          fga = await aget_fga_client()
          if fga is None:
              raise BusinessError(code=19201, msg='OpenFGA service unreachable')
          await fga.write_tuples(writes=[{
              'user': f'user:{user_id}',
              'relation': 'admin',
              'object': f'tenant:{tenant_id}',
          }])
          logger.info('Granted Child Admin: user=%s tenant=%s', user_id, tenant_id)

      @classmethod
      async def revoke_tenant_admin(cls, tenant_id: int, user_id: int) -> None:
          await cls._guard_not_root(tenant_id)
          fga = await aget_fga_client()
          if fga is None:
              raise BusinessError(code=19201, msg='OpenFGA service unreachable')
          await fga.write_tuples(deletes=[{
              'user': f'user:{user_id}',
              'relation': 'admin',
              'object': f'tenant:{tenant_id}',
          }])
          logger.info('Revoked Child Admin: user=%s tenant=%s', user_id, tenant_id)

      @classmethod
      async def list_tenant_admins(cls, tenant_id: int) -> List[int]:
          """List all user IDs who are Child Admin of the given tenant.

          For Root tenant returns [] (Root has no tenant#admin tuples by design).
          """
          if tenant_id == ROOT_TENANT_ID:
              return []
          fga = await aget_fga_client()
          if fga is None:
              return []
          tuples = await fga.read_tuples(
              relation='admin',
              object=f'tenant:{tenant_id}',
          )
          user_ids = []
          for t in tuples:
              user = t.get('user', '')
              if user.startswith('user:'):
                  try:
                      user_ids.append(int(user.split(':', 1)[1]))
                  except ValueError:
                      continue
          return user_ids

      @classmethod
      async def _guard_not_root(cls, tenant_id: int) -> None:
          """Reject Root tenant admin operations at service entry (INV-T3, AC-13)."""
          if tenant_id == ROOT_TENANT_ID:
              raise BusinessError(
                  code=RootTenantAdminNotAllowedError.Code,
                  msg=RootTenantAdminNotAllowedError.Msg,
              )
          tenant = await TenantDao.aget_one(tenant_id)  # may return None
          if tenant is None or tenant.parent_tenant_id is None:
              # Defense-in-depth: parent_tenant_id IS NULL means Root
              raise BusinessError(
                  code=RootTenantAdminNotAllowedError.Code,
                  msg=RootTenantAdminNotAllowedError.Msg,
              )
  ```
  **测试**（`test_tenant_admin_service.py`，用 `db_session` + AsyncMock fga）:
  - `test_grant_rejects_root_by_id` — `grant_tenant_admin(1, 10)` 抛 `BusinessError(19204)`，fga 未被调用
  - `test_grant_rejects_root_by_null_parent` — 插入 tenant(id=2, parent_tenant_id=NULL)，`grant_tenant_admin(2, 10)` 抛 19204
  - `test_grant_success_for_child` — 插入 tenant(id=5, parent_tenant_id=1)，调用 grant，mock fga 收到 `(user:10, admin, tenant:5)` write
  - `test_revoke_rejects_root` — `revoke_tenant_admin(1, 10)` 抛 19204
  - `test_revoke_success_for_child` — 调用 revoke 后 fga 收到 deletes
  - `test_list_admins_returns_empty_for_root` — `list_tenant_admins(1) == []` 且 fga 未被调用
  - `test_list_admins_parses_user_ids` — mock fga.read_tuples 返回含 `user:7`/`user:9`，返回 `[7, 9]`
  - `test_list_admins_ignores_non_user_tuples` — fga 返回 `user:foo`（非数字），被过滤
  - `test_grant_raises_19201_when_fga_unavailable` — fga 返回 None，抛 `BusinessError(19201)`
  **覆盖 AC**: AC-11（挂载 Child 时仅写 tenant:{child}#admin，不写 Root）、AC-13（19204 Root 守卫）、INV-T3
  **依赖**: T01, T05

---

### 核心链路：PermissionService 五级短路扩展

- [ ] **T08**: `PermissionService.check` 插入 L2/L3 + `_is_shared_to` 辅助
  **文件（修改）**:
  - `src/backend/bisheng/permission/domain/services/permission_service.py` — `check` 方法 L1 后插入 L2/L3；新增 `_is_shared_to` 辅助
  **文件（修改）**:
  - `src/backend/test/test_permission_service.py` — 追加 F013 场景
  **逻辑**:
  - **`check` 方法签名不变**，在 L1（超管）后插入两级，原 L2-L5 顺位下移（D5 增量策略）：
    ```python
    @classmethod
    async def check(cls, user_id, relation, object_type, object_id, login_user=None) -> bool:
        # L1: Super admin shortcircuit
        if login_user and login_user.is_admin():
            return True

        # ── F013 新增：L2 Tenant 归属 IN 列表 ──
        # 仅在 login_user 非空且资源可定位 tenant 时触发；无法定位则跳过（回退旧链路）
        resource_tenant_id = await cls._resolve_resource_tenant(object_type, object_id)
        if login_user and resource_tenant_id is not None:
            visible = await login_user.get_visible_tenants()
            if resource_tenant_id not in visible:
                # 非归属 + 非显式共享 → 拒绝
                if not await cls._is_shared_to(user_id, resource_tenant_id):
                    return False

        # ── F013 新增：L3 Child tenant admin ──
        if login_user and resource_tenant_id is not None and resource_tenant_id != 1:
            # Root (id=1 or parent_tenant_id IS NULL) 不触发 tenant.admin check（Root 无此元组）
            from bisheng.database.models.tenant import TenantDao
            tenant = await TenantDao.aget_one(resource_tenant_id)
            if tenant is not None and tenant.parent_tenant_id is not None:
                if await login_user.has_tenant_admin(resource_tenant_id):
                    return True

        # ── 原 L2 Cache（顺位下移为 L4）── 以下保持不变
        if relation not in UNCACHEABLE_RELATIONS:
            # ...（既有代码）
    ```
  - **新增辅助 `_resolve_resource_tenant`**：基于 `object_type` 查 DAO 层取 `tenant_id`；无法解析返回 None（降级到原链路）
    ```python
    @classmethod
    async def _resolve_resource_tenant(cls, object_type: str, object_id: str) -> Optional[int]:
        """Resolve the tenant_id of a resource. Returns None if unavailable or type unsupported.

        Defensive implementation: any exception → None → falls back to original L3+ chain.
        """
        try:
            if object_type == 'workflow':
                from bisheng.database.models.flow import FlowDao
                obj = await FlowDao.aget_one(object_id)
                return obj.tenant_id if obj else None
            if object_type == 'knowledge_space':
                from bisheng.database.models.knowledge import KnowledgeDao
                obj = await KnowledgeDao.aget_one(object_id)
                return obj.tenant_id if obj else None
            if object_type == 'assistant':
                from bisheng.database.models.assistant import AssistantDao
                obj = await AssistantDao.aget_one(object_id)
                return obj.tenant_id if obj else None
            # Other types: return None (skip L2/L3, fall through to existing ReBAC)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning('_resolve_resource_tenant failed for %s:%s: %s',
                           object_type, object_id, e)
            return None
    ```
    注：MVP 仅覆盖 workflow/knowledge_space/assistant 三类主资源；folder/knowledge_file 等派生资源继承父资源 tenant_id（由 FGA parent 链处理，L2/L3 跳过返回 None 即可）；llm_server/llm_model/tool/channel/dashboard 的 tenant 过滤待 F016/F020 按需扩展。
  - **新增辅助 `_is_shared_to`**：
    ```python
    @classmethod
    async def _is_shared_to(cls, user_id: int, target_tenant_id: int) -> bool:
        """Check if user is under target_tenant#shared_to#member (Root → Child share)."""
        fga = cls._get_fga()
        if fga is None:
            return False
        try:
            return await fga.check(
                user=f'user:{user_id}',
                relation='member',
                object=f'tenant:{target_tenant_id}#shared_to',
            )
        except FGAConnectionError:
            return False
    ```
  - **docstring 更新**：`check` 方法顶部的 L1-L5 注释扩为 L1-L7（L1 超管 / L2 IN 列表 / L3 Child admin / L4 缓存 / L5 FGA check / L6 DB creator / L7 fail-closed）
  **测试**（扩展 `test_permission_service.py`，仅加新 case 不改既有）:
  - `test_check_l2_rejects_when_tenant_not_visible` — user leaf=5, resource tenant=10，非 shared_to → False
  - `test_check_l2_allows_when_resource_tenant_in_visible` — user leaf=5, resource tenant=5，L2 通过（继续走 L4+）
  - `test_check_l2_allows_root_resource_for_child_user` — user leaf=5, resource tenant=1（Root），L2 通过（visible 含 Root）
  - `test_check_l2_shared_to_bypasses_visibility` — user leaf=5, resource tenant=10（非 visible），但 fga 返回 shared_to=True → 继续走后续链（不在 L2 直接 False）
  - `test_check_l3_child_admin_returns_true` — user=10 是 tenant:5 的 Child admin，check 返回 True（不走 ReBAC）
  - `test_check_l3_skips_for_root_resource` — resource tenant=1，L3 跳过（不调 fga.check on tenant:1#admin）；说明：此场景下 L2 先命中通过（Root 在 visible 中），L3 跳过，继续 L4+（现有链路）
  - `test_check_l3_skips_when_parent_tenant_id_null` — 插入 tenant(id=99, parent_tenant_id=NULL)，L3 跳过
  - `test_check_resolver_failure_falls_back_to_existing_chain` — mock `_resolve_resource_tenant` 抛异常，返回 None，L2/L3 跳过，走原 L4+（回归保护）
  - `test_check_super_admin_shortcircuit_still_works` — L1 仍优先（既有断言不破坏）
  - `test_is_shared_to_true_when_fga_allows` — fga.check 返回 True，`_is_shared_to` 返回 True
  - `test_is_shared_to_false_when_fga_none` — fga=None，返回 False
  **覆盖 AC**: AC-02 / AC-03 / AC-04 / AC-05 / AC-06 / AC-07 / AC-08 / AC-12、INV-T3、INV-T5、spec §6 伪代码
  **依赖**: T06（stub 方法）、T07（TenantAdminService 虽独立，但测试场景可借其写入元组）

---

### 集成层：OpenFGA 端到端 + AC 映射

- [ ] **T09**: 集成测试 `test_f013_tenant_fga_tree.py`（FGA 端到端，AC-01/02/03/04/05/06/07/08/10/11/12/13 映射）
  **文件（新建）**:
  - `src/backend/test/test_f013_tenant_fga_tree.py` — 集成测试套件
  **测试降级标注**：
  - **降级范围**：本任务自动化覆盖使用 `AsyncMock(FGAClient)` 直接 mock FGA check/write/read 响应，**不接真实 OpenFGA store**
  - **降级理由**：
    1. CI 环境不部署 OpenFGA docker（与 Milvus/ES 同类外部依赖，项目约定不纳入 CI 自动化）
    2. 真实 FGA store DSL 部署、元组预置、并发 QPS 压测需要有状态服务，pytest 难以稳定复现
    3. 本地开发人员已有 `docker compose -p bisheng up -d openfga`，手动跑通可替代自动化
  - **补偿措施**：真实 FGA 端到端验证 + AC-10 性能压测 100% 推到 T10 手工 QA（spec §9.4），用真实 Docker OpenFGA + 10w 元组数据集执行
  **逻辑**:
  - **前置 fixture**：从 `test/conftest.py` 获取 `db_session`；FGA 侧统一使用 `AsyncMock` 替身（不启动 httpx、不连接 OpenFGA）
  - **关键测试场景**（每个 AC 一个 test_fn，命名 `test_ac_NN_<summary>`）：
    - `test_ac_01_authorization_model_accepted` — 部署新 model 到 fake store，`MODEL_VERSION='v2.0.0'`，类型数=15
    - `test_ac_02_super_admin_shortcircuit` — 全局超管 user 请求 Child 资源，无需 FGA 元组，返回 True
    - `test_ac_03_child_admin_access_own_child` — grant `user:10` admin on tenant:5；check(user:10, read, workflow:xxx) 在 workflow.tenant_id=5 时命中 L3 → True
    - `test_ac_04_child_admin_denied_cross_child` — user:10 是 tenant:5 admin，请求 workflow(tenant_id=7) → L2 拒绝
    - `test_ac_05_normal_user_no_tenant_admin` — FGA `check(user:20, admin, tenant:1)` = False
    - `test_ac_06_super_admin_no_tenant_admin_on_root` — 即使 user:1 是 super_admin，`check(user:1, admin, tenant:1)` = False（Root 不写 tenant#admin 元组）
    - `test_ac_07_shared_resource_reachable` — 写 `tenant:1#shared_to → tenant:5`；写 `knowledge_space:xyz#viewer → tenant:1#shared_to#member`；user(leaf=5) 读 ks:xyz → True
    - `test_ac_08_root_non_shared_resource_via_in_list` — user(leaf=5) 访问 Root 资源（tenant_id=1）且资源属于该用户（owner）→ L2 通过（Root ∈ visible）→ L5 ReBAC owner → True
    - `test_ac_11_mount_child_writes_minimal_tuples` — 调用 TenantAdminService.grant_tenant_admin(tenant:5, user:10) 仅写 1 条元组；显式断言 `fga.read_tuples(relation='admin', object='tenant:1')` 返回空
    - `test_ac_12_member_no_default_resource_access` — user(leaf=5) 访问 tenant_id=5 的他人创建资源（无 owner/dept/group grant）→ False（验证 manager/editor 不含 tenant#member 的收窄）
    - `test_ac_13_direct_root_admin_write_rejected` — 调用 `TenantAdminService.grant_tenant_admin(1, 10)` 抛 `BusinessError(19204)`
  - **性能 smoke（可选，AC-10）**：
    - `test_ac_10_perf_cached_check_under_10ms` — 10 次 check（缓存命中）P99 < 10ms（非严格基准，仅冒烟）
  **覆盖 AC**: AC-01 / AC-02 / AC-03 / AC-04 / AC-05 / AC-06 / AC-07 / AC-08 / AC-10 / AC-11 / AC-12 / AC-13 全集成覆盖
  **依赖**: T02, T05, T06, T07, T08

---

### 验收：手工 QA + 文档归档

- [ ] **T10**: 手工 QA 清单执行 + `ac-verification.md` 归档
  **文件（新建）**:
  - `features/v2.5.1/013-tenant-fga-tree/ac-verification.md` — AC 对照 + 手工验证记录（参考 F011 同名文件）
  **逻辑**:
  - 按 spec §9 五大类清单逐项在本地 + 测试服务器 114 执行；每项记录：执行时间、执行人、结果、截图/日志路径
  - 五大类：
    1. **DSL 升级**（§9.1）：`fga model get` CLI 验证；旧 model 仍可读
    2. **两层管理员行为**（§9.2）：全局超管/Child Admin/跨 Child/普通用户四种访问路径
    3. **归属 IN 列表**（§9.3）：Child 可见 Root 共享资源 / 不可见未共享 / 跨 Child 严格隔离
    4. **性能**（§9.4）：10w 元组 P99 < 10ms、1000 QPS 无超时（真实 OpenFGA store 压测）
    5. **灰度**（§9.5）：双 model 切换 + 回滚 + 双写元组验证
  - **ac-verification.md 结构**：
    ```markdown
    # F013 AC Verification Record

    ## 执行环境
    - 本地：Darwin 25.3.0 / OpenFGA docker 1.5.3
    - 测试服务器：192.168.106.114 / OpenFGA ...

    ## AC 对照
    | AC | 覆盖位置 | 状态 | 备注 |
    |----|---------|------|------|
    | AC-01 | T09/test_ac_01 + §9.1 CLI | ✅ | model_id=xxx 部署成功 |
    | AC-02 | T08 test_check_super_admin_shortcircuit_still_works | ✅ | |
    | ... | ... | ... | ... |

    ## 手工 QA 清单（spec §9）
    - [x] §9.1 DSL 升级
      - 执行时间: 2026-04-XX
      - 结果: 通过
      - 日志: ...
    ...
    ```
  - **关键补充**：若某项无法在当前环境完成（如无真实 OpenFGA cluster 做性能压测），记录在 `ac-verification.md` 末尾「未完成项」并附原因 + 建议后续窗口
  **测试**: 无（手工验证）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13（spec §9 全类对照签收）
  **依赖**: T01-T09 全部完成

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- (待实现过程中补充)
