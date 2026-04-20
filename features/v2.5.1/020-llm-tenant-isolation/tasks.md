# Tasks: F020-llm-tenant-isolation (LLM 服务多租户隔离)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/020-llm-tenant-isolation`（base=`2.5.0-PM`，commit `ee6d24e61`）
**Worktree**: `/Users/lilu/Projects/bisheng-worktrees/020-llm-tenant-isolation`
**前置**: F011 / F012 / F013 / F017 / F019 已合入 `2.5.0-PM`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-19 PRD 精化后定稿；24 AC + 8 AD + 完整 §5 代码骨架；经 `/sdd-review spec` 通过 |
| tasks.md | ✅ 已拆解 | 2026-04-21 `/sdd-review tasks` 第 2 轮通过（第 1 轮修复：T02/T11/T15 三个跨文件/跨前后端任务拆分 + AC-18/19 E2E 测试补齐 + D10/D11 决策锁定） |
| 实现 | 🟡 进行中 | 9 / 19 完成（T01~T08 ✓） |

---

## 决策锁定（plan 阶段 + 实施前调研 + Review 第 1 轮）

| ID | 决策 | 结论 |
|----|------|------|
| D1 | 模块编码 | **198**（release-contract 已登记）；错误码 `19801` `llm_model_shared_readonly` / `19802` `llm_model_not_accessible` / `19803` `llm_system_config_forbidden` / `19804` `llm_endpoint_not_whitelisted` |
| D2 | FGA 元组机制 | **复用 F017 `ResourceShareService`，不自行 `FGAClient.write_tuple`**。原因：OpenFGA DSL 已升级到 v2.0.1（`core/openfga/authorization_model.py` L30-33），用 `{resource}#shared_with → tenant:{child}` 显式 per-Child 展开替代 spec §5.1 中 `tenant#shared_to#member` 旧写法；F017 已封装此逻辑。**T02b 需将 `llm_server` 加入 `SUPPORTED_SHAREABLE_TYPES`**（当前含 `knowledge_space/workflow/assistant/channel/tool`）|
| D3 | 查询合并策略 | **Service 层双查询合并**，不改 `tenant_filter.py` event。原因：v2.5.1 event 仍是 `tenant_id == tid` 严格过滤（`core/database/tenant_filter.py:L87`），`visible_tenant_ids` ContextVar 虽已定义但 event 未消费；**F020 不承担 event 改造**（避免扩散风险，保持 F013/F016/F017 既有行为）。LLMService `get_all_llm` 分两步：① `aget_all_server()` 自动获取 leaf；② `aget_shared_server_ids_for_leaf(leaf_id)` 通过 FGA `list_objects(user=tenant:{leaf}, relation=shared_with, type=llm_server)` 拿 Root 共享 id 列表；③ `bypass_tenant_filter` 内 `aget_server_by_ids` 取 Root 共享记录；④ 合并去重返回 |
| D4 | 依赖函数归属 | `get_tenant_admin_user` 作为 **`UserPayload.get_tenant_admin_user` classmethod**（沿 `get_admin_user` / `get_login_user` 既有 style，非独立函数），spec §5.2 中独立函数写法仅供参考 |
| D5 | audit_log action | 沿 F019 T02 在 `tenant/domain/constants.py` `TenantAuditAction` enum 追加 6 行：`LLM_SERVER_CREATE / LLM_SERVER_UPDATE / LLM_SERVER_DELETE / LLM_SERVER_TOGGLE_SHARE / LLM_MODEL_UPDATE_ONLINE / LLM_MODEL_UPDATE_STATUS`；写入用 `AuditLogDao.ainsert_v2`；payload `api_key_hash = sha256(api_key)[:16]`，明文不入 audit |
| D6 | endpoint 白名单 | 读 `settings.llm.endpoint_whitelist`（默认空列表 = 不限制）；全局超管不受限；非 Root + 非空 whitelist 场景校验 `server.config.openai_api_base`（或 `endpoint`，以 v2.4 LLMServer.config JSON key 为准 —— T05 实施前确认 key 名）前缀匹配 |
| D7 | UNIQUE 迁移 | Alembic upgrade 先 `SELECT tenant_id, name, COUNT(*) GROUP BY ... HAVING COUNT>1`；有冲突则抛 `RuntimeError` 附清单中止；需 DBA 手工去重再重跑；**不自动重命名**（避免误删） |
| D8 | 前端组件归属 | **`AdminScopeSelector.tsx` 归本 Feature owning**（F019 §9 out-of-scope 明确剥离）；`useAdminScope` hook 归本 Feature；后端 axios 封装（`controllers/API/admin.ts`）F019 已提供；**MountDialog UI 不新建**，F020 仅提供 `GET /llm?only_shared=true` 预览数据端点（AC-17~19 的 UI 集成挂至 F011 后续 PR 或外部 UI Feature） |
| D9 | 系统级端点保留 | `POST /llm/workbench` / `POST /llm/knowledge` / `POST /llm/assistant` / `POST /llm/evaluation` 保持 `UserPayload.get_admin_user`（仅全局超管，AD-07 + AC-11 落地） |
| D10 | `/user/info` 响应扩展归属 | **F020 T15a pure-additive 扩展** `/user/info` 响应体 4 个字段（`is_global_super / is_child_admin / leaf_tenant_id / leaf_tenant_name`）。release-contract 视角：F012 拥有 `UserTenantSyncService` 与 JWT payload，但 `/user/info` 响应 DTO 扩展属向前兼容的增量字段，不修改既有行为；与 F019 T13 前端封装风格对齐 |
| D11 | AC-11 在"超管 + scope=Child"下的语义 | **工作台等系统级配置不受 admin-scope 影响**：超管即使切到 Child 5 scope，`POST /llm/workbench` 等 D9 清单仍可操作（全局默认模型是集团级决策，`get_admin_user` 保留）；前端 SystemModelConfig 对"超管（任意 scope）"可见，仅对"Child Admin（非全局超管）"隐藏 |

---

## 依赖图

```
T01 (errcode 19801~04) ──┐
T02a (LLMConf + Settings 注册) ──┤
T02b (TenantAuditAction + SUPPORTED_SHAREABLE_TYPES + CLAUDE.md) ──┤
T03 (UserPayload.get_tenant_admin_user)                            ├──→ T05 (LLMDao 写方法改造)
T04 (Alembic 迁移 + ORM 补 tenant_id)                              ──┤     │
                                                                    │     ├──→ T06 (LLMDao aget_shared_server_ids_for_leaf)
                                                                    │     │         │
                                                                    │     └─────────┼──→ T07 (LLMService 改造 + get_model_for_call + 查询合并)
                                                                    │               │             │
                                                                    │               │             ├──→ T08 (Router 权限降级)
                                                                    │               │             │         │
                                                                    │               │             │         ├──→ T09 (Router audit_log)
                                                                    │               │             │         └──→ T10 (GET /llm only_shared 预览端点)
                                                                    │               │             │
                                                                    │               │             ├──→ T11a (knowledge PUT 校验 + retrieval 调用链)
                                                                    │               │             └──→ T11b (workflow 节点 + assistant 调用链)
                                                                    │
                                                                    ├──→ T15a (后端 /user/info 响应扩展)
                                                                    │         │
                                                                    └──→ T12~T14 (前端 API/hook/组件) ──→ T15b (前端 ModelPage + userContext) ──→ T16 (AC 对照)
```

---

## 开发模式

- **后端 Test-Alongside**：基础（errcode/config/enum/依赖）无测试配对；DAO / Service / Router 每个任务内联集成测试（沿 F019 模式）；外部 LLM 调用用 mock client
- **前端 Platform 手动验证**：仓库无 Vitest，每个前端任务附手动验证步骤
- **自包含任务**：每个任务内联文件路径、关键代码位置、测试用例；实现阶段无需回读 spec.md
- **迁移演练**：T04 的 Alembic 在 114 远程服务器克隆 v2.4 MySQL 快照上走一遍，确认 GROUP BY 查重路径

---

## Tasks

### 基础设施（无测试配对）

- [x] **T01**: 错误码 `llm_tenant.py`
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/llm_tenant.py`
  **逻辑**（参照 `common/errcode/admin_scope.py` 模式）:
  ```python
  from bisheng.common.errcode.base import BaseErrorCode

  class LLMModelSharedReadonlyError(BaseErrorCode):
      Code: int = 19801
      Msg: str = 'Root 共享模型对 Child Admin 只读'

  class LLMModelNotAccessibleError(BaseErrorCode):
      Code: int = 19802
      Msg: str = '目标模型不在当前可见集合'

  class LLMSystemConfigForbiddenError(BaseErrorCode):
      Code: int = 19803
      Msg: str = '系统级模型配置仅全局超管可修改'

  class LLMEndpointNotWhitelistedError(BaseErrorCode):
      Code: int = 19804
      Msg: str = 'LLM endpoint 不在配置的白名单前缀中'
  ```
  **测试**: 无（错误码返回行为由 T05/T07/T08 的 pytest 集成测试覆盖）
  **覆盖 AC**: — （基础任务）
  **依赖**: 无

---

- [x] **T02a**: `LLMConf` 新建 + `Settings` 注册
  **文件（新建 + 修改）**:
  - 新建 `src/backend/bisheng/core/config/llm.py`:
    ```python
    from pydantic import BaseModel, Field

    class LLMConf(BaseModel):
        endpoint_whitelist: list[str] = Field(
            default_factory=list,
            description='F020: Child Admin 注册 LLM Server 时 endpoint 前缀白名单；空=不限制',
        )
    ```
  - 修改 `src/backend/bisheng/core/config/settings.py` —— 导入 `LLMConf` 并在 `Settings` 注册 `llm: LLMConf = LLMConf()`
  **测试**: 无（Pydantic 字段扩展；在 T05/T09 集成测试中验证 `settings.llm.endpoint_whitelist` 可达）
  **覆盖 AC**: — （基础任务；边界 "endpoint 白名单" 由 T05 `test_endpoint_whitelist_enforced_for_child_admin` 覆盖）
  **依赖**: 无

---

- [x] **T02b**: `TenantAuditAction` 扩展 + `SUPPORTED_SHAREABLE_TYPES` 加 `llm_server` + CLAUDE.md 模块编码核对
  **文件（修改）**:
  - `src/backend/bisheng/tenant/domain/constants.py` `TenantAuditAction` enum 追加 6 行（放在 ADMIN_SCOPE_SWITCH 之后，沿 F019 T02 pure-additive 扩展模式）:
    ```python
    # v2.5.1 F020 — LLM server/model lifecycle (Child-scoped CRUD).
    LLM_SERVER_CREATE = 'llm.server.create'
    LLM_SERVER_UPDATE = 'llm.server.update'
    LLM_SERVER_DELETE = 'llm.server.delete'
    LLM_SERVER_TOGGLE_SHARE = 'llm.server.toggle_share'
    LLM_MODEL_UPDATE_ONLINE = 'llm.model.update_online'
    LLM_MODEL_UPDATE_STATUS = 'llm.model.update_status'
    ```
  - `src/backend/bisheng/tenant/domain/services/resource_share_service.py` `SUPPORTED_SHAREABLE_TYPES` 集合增加 `'llm_server'`（`llm_model` 随 Server 共享，不单独列）
  - `CLAUDE.md` —— 验证「模块编码」表含 `198=llm_tenant (F020)`；若缺则补
  **跨 Feature 说明**：`TenantAuditAction` 归 F011 owner，F017 `ResourceShareService` 归 F017 owner；两处改动均为 **F020 pure-additive 扩展**，不修改既有 action 值/既有类型语义，沿 F019 T02 前例
  **测试**: 无（枚举 + 常量集合扩展；行为由 T05 FGA 元组写入、T09 audit_log 写入集成测试覆盖）
  **覆盖 AC**: AC-12（action 落地）、AC-17, AC-18, AC-19（llm_server 可共享的 DSL 前置条件）
  **依赖**: 无

---

- [x] **T03**: `UserPayload.get_tenant_admin_user` classmethod 新增
  **文件（修改）**:
  - `src/backend/bisheng/common/dependencies/user_deps.py` —— 在 `UserPayload` 类末尾追加（风格参照 `get_admin_user` / `get_login_user`）:
    ```python
    @classmethod
    async def get_tenant_admin_user(cls, request: Request = ...) -> 'UserPayload':
        """F020 AD-03: 全局超管 或 当前 tenant_id 的 Child Admin 放行，否则 403+19801。"""
        user: UserPayload = await cls.get_login_user(request)  # 复用既有 JWT 解析链路
        if await user.is_global_super():
            return user
        from bisheng.core.context.tenant import get_current_tenant_id
        tid = get_current_tenant_id()
        if tid is not None and tid != 1 and await user.has_tenant_admin(tid):
            return user
        from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
        raise LLMModelSharedReadonlyError.http_exception()
    ```
  **注意**:
  - `get_login_user` 的具体签名先读 `LoginUser.get_login_user`（`user/domain/services/auth.py`），若非 classmethod 需要参照实际委托路径调整；T03 实施首行即确认签名
  - `is_global_super()` / `has_tenant_admin(tenant_id)` 已在 F013 `UserPayload` 存在（L53-77）
  - 当前 tenant_id 取用的是 `get_current_tenant_id()`（F019 已含 admin-scope override），因此超管切到 Child 5 视图时 `tid=5`，走 Child Admin 分支等价；超管无 scope 则 `is_global_super()` 分支直接放行
  **测试**: 无独立测试，行为由 T08 Router 层集成测试覆盖（AC-05/06/07 + AC-14）
  **覆盖 AC**: AC-05, AC-06, AC-07, AC-11, AC-14（Child Admin 可写本 Child；超管 + scope 等价 Child Admin）
  **依赖**: T01

---

### 数据库迁移 + ORM 模型

- [x] **T04**: Alembic 迁移 `UNIQUE(name) → UNIQUE(tenant_id, name)` + ORM 模型 `__table_args__` 修正
  **文件（新建 + 修改）**:
  - 新建 `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f020_llm_tenant.py`（基于最近的 revision）
    - `upgrade()`:
      1. 前置校验 `SELECT tenant_id, name, COUNT(*) FROM llm_server GROUP BY tenant_id, name HAVING COUNT(*)>1`，有结果即抛 `RuntimeError(f'llm_server (tenant_id,name) 重复: {conflicts}')` 中止
      2. `op.drop_index('name', table_name='llm_server')`（v2.4 的 UNIQUE name 索引）
      3. `op.create_index('uk_llm_server_tenant_name', 'llm_server', ['tenant_id', 'name'], unique=True)`
    - `downgrade()`: 反向（drop uk_llm_server_tenant_name + create UNIQUE(name)）
  - 修改 `src/backend/bisheng/llm/domain/models/llm_server.py`:
    - `LLMServerBase.name`: 去掉 `unique=True`（仅保留 `index=True`）
    - `LLMServer.__table_args__ = (UniqueConstraint('tenant_id', 'name', name='uk_llm_server_tenant_name'),)`
    - **注意**：`LLMServerBase` 当前**没有 `tenant_id` 字段**。v2.5.0/F001 通过 Alembic 加了数据库列（默认 1），但 ORM 模型缺失。T04 顺便补齐：
      ```python
      tenant_id: int = Field(default=1, index=True, nullable=False, description='F001: Tenant isolation')
      ```
      `LLMModelBase` 同样补齐
  **迁移演练**:
  - 本地：`cd src/backend && .venv/bin/alembic upgrade head` → 验证 `SHOW CREATE TABLE llm_server\G`
  - 远程 114：克隆 v2.4 快照后执行，验证无冲突
  **测试**:
  - `src/backend/test/test_f020_migration.py`（纯 Alembic 测试）:
    - `test_upgrade_rejects_duplicate_tenant_name_pairs` — mock `op.get_bind().execute` 返回 ≥1 条冲突记录 → 断言抛 RuntimeError
    - `test_upgrade_creates_composite_unique_index` — 成功路径，断言 `create_index` 被调
  **覆盖 AC**: AC-16（存量 tenant_id=1）、边界"同名冲突"、spec §5.5
  **依赖**: 无（与 T01~T03 并行）

---

### DAO 层改造

- [x] **T05**: `LLMDao` 写方法改造（ainsert / aupdate_server_with_models / adelete_server_by_id + aupdate_server_share 新方法）
  **文件（修改）**:
  - `src/backend/bisheng/llm/domain/models/llm_server.py` `LLMDao` 类
  **逻辑**:

  **`ainsert_server_with_models`**（L90-100）改造：
  ```python
  @classmethod
  async def ainsert_server_with_models(cls, server, models, *, share_to_children: bool = True, operator=None):
      from bisheng.core.context.tenant import get_current_tenant_id
      from bisheng.database.models.tenant import TenantDao
      from bisheng.common.services.config_service import settings
      from bisheng.common.errcode.llm_tenant import LLMEndpointNotWhitelistedError

      tid = get_current_tenant_id() or 1
      server.tenant_id = tid
      for m in models:
          m.tenant_id = tid

      # D6: endpoint 白名单（全局超管不校验；whitelist 空=不限制）
      whitelist = settings.llm.endpoint_whitelist
      if whitelist and operator is not None and not await operator.is_global_super():
          endpoint = (server.config or {}).get('openai_api_base') \
                     or (server.config or {}).get('endpoint', '')
          if not any(endpoint.startswith(p) for p in whitelist):
              raise LLMEndpointNotWhitelistedError.http_exception()

      async with get_async_db_session() as session:
          session.add(server)
          await session.flush()
          for m in models:
              m.server_id = server.id
          session.add_all(models)
          await session.commit()
          await session.refresh(server)

      # D2: 复用 F017 ResourceShareService（自动处理 v2.0.1 DSL + Children fanout）
      tenant = await TenantDao.aget(tid)
      if (tenant is not None and tenant.parent_tenant_id is None
              and tenant.share_default_to_children and share_to_children):
          from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
          await ResourceShareService.enable_sharing('llm_server', str(server.id))
      return server
  ```

  **新增 `aupdate_server_share(server_id, share_to_children, operator)`**：
  ```python
  from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
  from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError

  @classmethod
  async def aupdate_server_share(cls, server_id: int, share_to_children: bool, operator):
      server = await cls.aget_server_by_id(server_id)
      if not server or server.tenant_id != 1:  # Root only
          raise LLMModelNotAccessibleError.http_exception()
      if not await operator.is_global_super():
          raise LLMModelSharedReadonlyError.http_exception()
      if share_to_children:
          await ResourceShareService.enable_sharing('llm_server', str(server_id))
      else:
          await ResourceShareService.disable_sharing('llm_server', str(server_id))
  ```

  **`aupdate_server_with_models`**（L103-133）改造：
  - 前置：`server = await cls.aget_server_by_id(server.id)` — 被 event 自动过滤，拿不到即不可见
  - 若 `server.tenant_id == 1` 且 `not await operator.is_global_super()` → 抛 `LLMModelSharedReadonlyError`
  - 正常更新流程不变

  **`adelete_server_by_id`**（L297-302）改造：
  - 前置：`server = await cls.aget_server_by_id(server_id)`；不存在抛 19802
  - Root 模型 + 非超管 → 抛 19801
  - 级联：`await ResourceShareService.disable_sharing('llm_server', str(server_id))`（不管是否 Root，幂等）
  - 然后执行既有 DELETE 逻辑

  **测试（集成）** `src/backend/test/test_llm_tenant_isolation_dao.py`:
  - `test_root_llm_default_shared_writes_viewer_tuple` → AC-01
  - `test_root_llm_share_off_skips_viewer_tuple` → AC-02
  - `test_child_admin_creates_own_llm_not_shared` → AC-05
  - `test_child_admin_cannot_delete_root_shared_llm` → AC-09
  - `test_toggle_root_llm_share_updates_fga_tuples` → AC-04
  - `test_endpoint_whitelist_enforced_for_child_admin` → 19804（边界）
  - `test_mount_child_default_distributes_shared_llm` → AC-18（调 F011 `TenantMountService.mount_child(..., auto_distribute=True)` 后断言 Child 可见 Root 共享 LLM，依赖 F017 `distribute_to_child` 已写 `shared_to` 元组 + 本 Feature `llm_server` 已在 SUPPORTED_SHAREABLE_TYPES）
  - `test_mount_child_skip_distribute` → AC-19（`auto_distribute=False` 挂载后 Child 初始不可见任何 Root 共享 LLM）
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-09, AC-18, AC-19, AC-21, AC-23（间接）
  **依赖**: T01, T02a, T02b, T03, T04

---

- [x] **T06**: `LLMDao.aget_shared_server_ids_for_leaf(leaf_id)` 新方法（Root→Child 共享 id 查询）
  **文件（修改）**:
  - `src/backend/bisheng/llm/domain/models/llm_server.py` LLMDao 类末尾新增:
  ```python
  @classmethod
  async def aget_shared_server_ids_for_leaf(cls, leaf_id: int) -> list[int]:
      """F020: Return Root llm_server ids shared to the given leaf tenant via F017.

      Reads ``{llm_server}#shared_with → tenant:{leaf}`` tuples. Returns []
      when OpenFGA disabled or leaf is Root (no shares point to Root itself).
      """
      from bisheng.database.models.tenant import ROOT_TENANT_ID
      if leaf_id == ROOT_TENANT_ID:
          return []
      from bisheng.core.openfga.manager import aget_fga_client
      fga = await aget_fga_client()
      if fga is None:
          return []
      objects = await fga.list_objects(
          user=f'tenant:{leaf_id}', relation='shared_with', type='llm_server',
      )  # returns ['llm_server:123', 'llm_server:456', ...]
      return [int(o.split(':')[-1]) for o in objects]
  ```
  **注意**: `FGAClient.list_objects` 签名先读 `core/openfga/client.py` 确认（F017 enable_sharing 反向已用 `list_tuples`，但 `list_objects` 更直接）；若无 list_objects，降级为 `list_tuples(user='tenant:{leaf}', relation='shared_with', object_type='llm_server')` 后提取 object
  **测试**:
  - `test_aget_shared_server_ids_for_leaf_returns_root_shared` → 单测，mock FGA 返回 2 个 object → 断言 `[123, 456]`
  - `test_aget_shared_server_ids_for_leaf_root_returns_empty` → leaf=1 → `[]`
  - `test_aget_shared_server_ids_for_leaf_fga_disabled_returns_empty`
  **覆盖 AC**: AC-03（查询合并的数据源）
  **依赖**: T02b, T05

---

### Service 层 + 调用链

- [x] **T07**: `LLMService` 改造（add / update / delete / get_model_for_call + 查询合并 + share_to_children 分发）
  **文件（修改）**:
  - `src/backend/bisheng/llm/domain/services/llm.py`
  - `src/backend/bisheng/llm/domain/schemas.py`（DTO 扩展）
  **逻辑**:
  - **`get_all_llm()`**（L35-）改为双查询合并：
    ```python
    leaf_servers = await LLMDao.aget_all_server()           # event 自动过滤 leaf
    leaf_id = get_current_tenant_id() or 1
    shared_ids = await LLMDao.aget_shared_server_ids_for_leaf(leaf_id)
    if shared_ids:
        from bisheng.core.context.tenant import bypass_tenant_filter
        with bypass_tenant_filter():
            shared_servers = await LLMDao.aget_server_by_ids(shared_ids)
        # 去重（leaf_id == 1 时 leaf_servers 已含 Root 模型）
        existing = {s.id for s in leaf_servers}
        leaf_servers += [s for s in shared_servers if s.id not in existing]
    # 标注只读：为每个 server 附加 is_root_shared_readonly 属性（DTO 层处理）供前端渲染 Badge
    return cls._to_server_info_list(leaf_servers)
    ```
  - **`add_llm_server()`**（L67-）改为：
    - 去掉「`aget_server_by_name` 全局查重」，让复合 UNIQUE 约束承担（或改为 tenant_id 内查重）
    - 调 `LLMDao.ainsert_server_with_models(server, models, share_to_children=server.share_to_children, operator=login_user)`
    - 写 audit（T09）
  - **`update_llm_server()`**（L254-）分发：
    - 若 body 含 `share_to_children` 字段变化 → 调 `LLMDao.aupdate_server_share(server_id, share_to_children, operator=login_user)`
    - 其他字段变化 → 走 `LLMDao.aupdate_server_with_models(...)`
  - **`delete_llm_server()`** 保持 DAO 委托；权限校验在 DAO 层
  - **新增 `get_model_for_call(model_id)`**：
    ```python
    @classmethod
    async def get_model_for_call(cls, model_id: int):
        """F020 §5.4: 跨模块调用 LLM 统一入口。
        拿不到（不可见 / 已删 / 跨 Child）即抛 19802。"""
        model = await LLMDao.aget_model_by_id(model_id)  # event 自动 tenant 过滤
        if model is None:
            # bypass 再查一次确认是"跨 Tenant 不可见"而非"ID 无效"（日志区分）
            from bisheng.core.context.tenant import bypass_tenant_filter
            with bypass_tenant_filter():
                raw = await LLMDao.aget_model_by_id(model_id)
            if raw is not None:
                # 模型存在但不在可见集合 → 验证是否为 Root 共享给当前 leaf
                if raw.server_id:
                    shared_ids = await LLMDao.aget_shared_server_ids_for_leaf(get_current_tenant_id() or 1)
                    if raw.server_id in shared_ids:
                        return raw
            from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
            raise LLMModelNotAccessibleError.http_exception()
        return model
    ```
  - **Schemas**（`llm/domain/schemas.py`）: `LLMServerCreateReq` 加字段 `share_to_children: bool = True`；`LLMServerInfo` 返回含 `is_root_shared_readonly: bool`
  **测试（集成）** `src/backend/test/test_llm_tenant_isolation_service.py`:
  - `test_child_user_llm_list_merges_root_shared` → AC-03
  - `test_super_admin_without_scope_sees_all_root` → AC-15
  - `test_super_admin_with_scope_acts_as_child` → AC-13, AC-14
  - `test_get_model_for_call_cross_child_raises_19802` → AC-22, AC-23
  - `test_get_model_for_call_root_shared_accessible_for_child` → AC-20
  **覆盖 AC**: AC-03, AC-13, AC-14, AC-15, AC-20, AC-22, AC-23
  **依赖**: T05, T06

---

### API 路由

- [x] **T08**: Router 权限降级（CRUD → `get_tenant_admin_user`；workbench 等保留 `get_admin_user`）
  **文件（修改）**:
  - `src/backend/bisheng/llm/api/router.py`
  **改动清单**（逐行替换 `UserPayload.get_admin_user` → `UserPayload.get_tenant_admin_user`）:
  - L19 `add_llm_server` ✅ 改
  - L26 `delete_llm_server` ✅ 改
  - L33 `update_llm_server` ✅ 改
  - L40 `get_one_llm` ✅ 改
  - L47 `update_model_online` ✅ 改
  - L64 `update_workbench_llm` ❌ 保留 `get_admin_user`（AC-11 / D9）
  - L94 `update_knowledge_llm` ❌ 保留（D9）
  - L109 `update_assistant_llm` ❌ 保留（D9）
  - `update_evaluation_llm` ❌ 保留（D9）
  **PUT `/llm` body 扩展**：
  - 既有 `PUT /llm` body 接受 `share_to_children: bool`，由 Service 内分发到 DAO `aupdate_server_share` 或 `aupdate_server_with_models`
  - 不新增独立 `/llm/share` 端点（保持 API 表面简洁；AC-04 body 侧命中）
  **测试（集成）** `src/backend/test/test_llm_tenant_isolation_api.py`:
  - `test_child_admin_can_create_llm` → AC-05
  - `test_child_admin_cannot_edit_root_shared_llm` → AC-08
  - `test_child_admin_cannot_delete_root_shared_llm` → AC-09
  - `test_child_admin_cross_child_access_denied` → AC-10
  - `test_child_admin_system_config_forbidden` → AC-11
  - `test_normal_user_forbidden_on_crud`
  **覆盖 AC**: AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11
  **依赖**: T03, T07

---

- [ ] **T09**: Router / Service 审计日志写入（`llm.server.{create,update,delete,toggle_share}` + sha256 api_key）
  **文件（修改）**:
  - `src/backend/bisheng/llm/domain/services/llm.py` —— add/update/delete/aupdate_server_share 后统一写 audit:
  ```python
  import hashlib
  from bisheng.database.models.audit_log import AuditLogDao
  from bisheng.database.models.tenant import ROOT_TENANT_ID
  from bisheng.tenant.domain.constants import TenantAuditAction

  def _hash_api_key(config: dict) -> str | None:
      key = (config or {}).get('openai_api_key') or (config or {}).get('api_key')
      if not key:
          return None
      return hashlib.sha256(key.encode()).hexdigest()[:16]

  await AuditLogDao.ainsert_v2(
      tenant_id=server.tenant_id,
      operator_id=login_user.user_id,
      operator_tenant_id=get_current_tenant_id() or ROOT_TENANT_ID,
      action=TenantAuditAction.LLM_SERVER_CREATE.value,
      target_type='llm_server',
      target_id=str(server.id),
      metadata={
          'server_name': server.name,
          'endpoint': (server.config or {}).get('openai_api_base'),
          'api_key_hash': _hash_api_key(server.config),
          'share_to_children': share_to_children,
      },
  )
  ```
  **注意**:
  - `AuditLogDao.ainsert_v2` 的参数名以 `audit_log.py` 实际为准（F011/F019 已有样式）
  - 明文 API Key 绝不写 audit（AC-12 红线）
  **测试**: `test_llm_crud_writes_audit_log_with_hashed_key` → AC-12
  **覆盖 AC**: AC-12
  **依赖**: T07

---

- [ ] **T10**: `GET /llm` 支持 `?only_shared=true` 过滤（挂载弹窗预览 - AC-17 数据侧）
  **文件（修改）**:
  - `src/backend/bisheng/llm/api/router.py` L12-15：
    ```python
    @router.get('')
    async def get_all_llm(
        request: Request,
        only_shared: bool = Query(False, description='仅返回 Root 默认共享的 Server（挂载弹窗预览）'),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
    ):
        ret = await LLMService.get_all_llm(only_shared=only_shared, operator=login_user)
        return resp_200(data=ret)
    ```
  - `LLMService.get_all_llm(only_shared=False, operator=None)` 里：
    - `only_shared=True` 且 caller 非全局超管 → 抛 `LLMSystemConfigForbiddenError`（19803，复用 D9 系统级配置禁止语义：挂载预览属于集团级管理动作）
    - `only_shared=True` 且 caller 是超管 → `bypass_tenant_filter` 查询 `tenant_id=1` 的 server + 对每个调 `ResourceShareService.list_sharing_children(...)` 判断是否有 Child（即"已默认共享"判定）→ 仅返回有共享的
  **测试**:
  - `test_mount_child_preview_shared_llm_list` → AC-17（超管路径返回共享列表）
  - `test_mount_child_preview_forbidden_for_non_super_admin` → 19803（边界）
  **覆盖 AC**: AC-17
  **依赖**: T07

---

- [ ] **T11a**: 知识库调用链统一走 `get_model_for_call` + PUT 选型校验
  **文件（修改）**:
  - `src/backend/bisheng/knowledge/api/` 下 PUT 知识库 endpoint（具体文件实施首行 grep `PUT.*knowledge` 定位；spec §8 指向 `/knowledge/{id}` 配置入口）—— 接收 `model_id` 处加校验:
    ```python
    model = await LLMService.get_model_for_call(body.model_id)
    # 抛 19802 时前端 toast "该知识库引用的模型不可用"
    ```
  - `src/backend/bisheng/knowledge/` 下检索/RAG 调用 `get_bisheng_llm` / `get_bisheng_llm_sync` 的位置前置 `get_model_for_call` 校验（集中点约 1~2 处）
  **测试（集成）** `src/backend/test/test_llm_cross_ref_knowledge.py`:
  - `test_knowledge_using_root_model_works_for_child` → AC-20
  - `test_knowledge_model_inaccessible_raises_19802` → AC-21, AC-23
  - `test_knowledge_own_model_reference_works` → AC-22
  - `test_knowledge_model_select_validates_visibility` → AC-24
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24
  **依赖**: T07

---

- [ ] **T11b**: Workflow 节点 + Assistant 调用链接入 `get_model_for_call`
  **文件（修改）** —— 每文件薄改动（≤ 2 行前置校验）:
  - `src/backend/bisheng/workflow/nodes/llm/llm.py` —— `get_bisheng_llm_sync(model_id)` 调用前先 `await LLMService.get_model_for_call(model_id)`
  - `src/backend/bisheng/workflow/nodes/agent/agent.py` —— 同上
  - `src/backend/bisheng/workflow/nodes/rag/rag.py` —— 同上
  - `src/backend/bisheng/assistant/` 下 `llm_list[].model_id` 引用处同上（实施首行 grep `assistant.*model_id` 定位集中点）
  - 可选重构：若 3 个 workflow 节点改动一致，改 `LLMService.get_bisheng_llm_sync / get_bisheng_llm` 内部统一加校验，消除 3 处重复；此为加分项，首个实施策略以"不改 get_bisheng_llm 签名、仅在节点调用前校验"为准
  **测试（集成）** `src/backend/test/test_llm_cross_ref_workflow.py`:
  - `test_workflow_llm_node_blocked_on_cross_tenant_model` → 沿 AC-22/23 语义（workflow 节点执行时引用不可见模型报 19802）
  - `test_workflow_llm_node_uses_root_shared_model_in_child_context` → 沿 AC-20 语义
  **覆盖 AC**: AC-20, AC-21, AC-23（workflow / assistant 侧增强）
  **依赖**: T07

---

### 前端 Platform（手动验证）

- [ ] **T12**: 前端 API 层 `controllers/API/llm.ts` 扩展
  **文件（修改）**:
  - `src/frontend/platform/src/controllers/API/llm.ts`（若不存在则创建；参考 `admin.ts` 风格）
  **改动**:
  - 既有 `createLLM / updateLLM / deleteLLM` DTO 加 `share_to_children: boolean`
  - 新增 `fetchSharedLLMPreview(): Promise<LLMServerInfo[]>` → `axios.get('/api/v1/llm?only_shared=true')`
  - LLMServerInfo 类型加 `is_root_shared_readonly: boolean`
  **手动验证**: 打开浏览器 DevTools 观察 `PUT /api/v1/llm` 请求含 `share_to_children` 字段
  **覆盖 AC**: AC-04（前端侧）、AC-17（数据）
  **依赖**: T10

---

- [ ] **T13**: 前端 `hooks/useAdminScope.ts` 新建
  **文件（新建）**:
  - `src/frontend/platform/src/hooks/useAdminScope.ts`
  ```typescript
  import { useState, useEffect, useCallback } from 'react';
  import { getTenantScope, setTenantScope } from '@/controllers/API/admin';

  export interface AdminScope { scope_tenant_id: number | null; expires_at: string | null }

  export function useAdminScope() {
      const [scope, setScope] = useState<AdminScope>({ scope_tenant_id: null, expires_at: null });
      const [loading, setLoading] = useState(false);
      const refresh = useCallback(async () => {
          setLoading(true);
          try { setScope(await getTenantScope()); } finally { setLoading(false); }
      }, []);
      useEffect(() => { refresh(); }, [refresh]);
      const update = useCallback(async (tenantId: number | null) => {
          setLoading(true);
          try { setScope(await setTenantScope(tenantId)); } finally { setLoading(false); }
      }, []);
      return { scope, setScope: update, loading, refresh };
  }
  ```
  **手动验证**: 超管登录 → 在 ModelPage 切换 scope → 观察 `admin_scope:{user_id}` Redis key 写入 + 4h TTL
  **覆盖 AC**: AC-13, AC-14（前端侧）
  **依赖**: F019 已合入（`controllers/API/admin.ts` 就绪）

---

- [ ] **T14**: 前端 `components/AdminScopeSelector.tsx` 新建（全局复用组件）
  **文件（新建）**:
  - `src/frontend/platform/src/components/AdminScopeSelector.tsx`
  ```tsx
  import { Tabs, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';

  export interface TenantOption { value: number | 'global'; label: string }
  export interface AdminScopeSelectorProps {
      value: number | 'global';
      tenants: TenantOption[];  // [{value:'global',label:'全部'}, {value:1,label:'Root'}, ...childTenants]
      onChange: (v: number | 'global') => void;
      disabled?: boolean;
  }

  export function AdminScopeSelector({ value, tenants, onChange, disabled }: AdminScopeSelectorProps) {
      return (
          <Tabs value={String(value)} onValueChange={v => onChange(v === 'global' ? 'global' : Number(v))}>
              <TabsList>
                  {tenants.map(t => (
                      <TabsTrigger key={String(t.value)} value={String(t.value)} disabled={disabled}>
                          {t.label}
                      </TabsTrigger>
                  ))}
              </TabsList>
          </Tabs>
      );
  }
  ```
  **手动验证**: 超管 ModelPage 顶部看到 Tabs；Child Admin 看不到
  **覆盖 AC**: AC-13
  **依赖**: T13

---

- [ ] **T15a**: 后端 `/user/info` 响应扩展（4 个字段 pure-additive）
  **文件（修改）**:
  - `src/backend/bisheng/user/api/user.py`（具体 endpoint 位置实施首行 grep `/user/info` 或 `/user/me` 定位；沿 F012 既有响应 DTO 扩展）—— 响应体内补 4 字段:
    ```python
    from bisheng.database.models.tenant import TenantDao

    leaf_id = (await user.get_visible_tenants())[0] if login_user else 1
    is_super = await login_user.is_global_super()
    is_child_admin = (leaf_id != 1 and not is_super
                      and await login_user.has_tenant_admin(leaf_id))
    leaf_tenant = await TenantDao.aget(leaf_id)
    resp_data = {
        ...existing_fields,
        'is_global_super': is_super,
        'is_child_admin': is_child_admin,
        'leaf_tenant_id': leaf_id,
        'leaf_tenant_name': leaf_tenant.name if leaf_tenant else '',
    }
    ```
  **跨 Feature 说明**：F012 拥有 `UserTenantSyncService` 与 JWT payload，但 `/user/info` 响应 DTO 扩展属 **F020 pure-additive 扩展**（D10），不改既有字段/既有行为；沿 F019 T12（`controllers/API/admin.ts` 独立封装）前例
  **测试（集成）** `src/backend/test/test_user_info_tenant_fields.py`:
  - `test_user_info_returns_super_admin_flags` — 超管登录 → `is_global_super=True`, `is_child_admin=False`, `leaf_tenant_id=1`
  - `test_user_info_returns_child_admin_flags` — mock 用户 has `tenant:5#admin` 元组 → `is_child_admin=True`, `leaf_tenant_id=5`
  - `test_user_info_returns_normal_user_flags` — 普通用户 → 两个 bool 均 False
  **覆盖 AC**: AC-13, AC-15（前端 UI 正确渲染的数据基础）
  **依赖**: T03

---

- [ ] **T15b**: 前端 ModelPage 改造 + userContext 扩展 + SystemModelConfig 条件渲染
  **文件（修改）**:
  - `src/frontend/platform/src/contexts/userContext.tsx`：`User` interface 扩展 `is_global_super?: boolean`、`is_child_admin?: boolean`、`leaf_tenant_id?: number`、`leaf_tenant_name?: string`（与 T15a 后端响应对齐）
  - `src/frontend/platform/src/pages/ModelPage/manage/index.tsx`：顶部挂 `<AdminScopeSelector>`（仅 `user.is_global_super`）；Child Admin 渲染 `管理 {leaf_tenant_name} 的模型`；模型卡片 Root 共享加 `Badge`；Child Admin 编辑按钮 disabled
  - `src/frontend/platform/src/pages/ModelPage/manage/SystemModelConfig.tsx`（或 workbench 配置组件）：`{user.is_child_admin && !user.is_global_super ? null : <组件原有内容/>}` —— **按 D11，超管（任意 scope）均可见；仅 Child Admin 隐藏**
  **手动验证清单**（114 环境）:
  1. 超管登录 `admin / admin` → 访问 `http://192.168.106.114:3001/model/manage` → 看到 AdminScopeSelector；切换到 Child 5 → 列表变为 Child 5 + Root 共享；新增模型验证落 Child 5；SystemModelConfig 仍可见（D11）
  2. Child Admin 登录（先用 F019 后端 API 授予 `tenant:5#admin` 元组）→ 不见 Selector；列表为本 Child + Root 共享；Root 共享行显示 `Root 共享（只读）` Badge；编辑按钮 disabled
  3. Child Admin 访问 `/model/manage` → SystemModelConfig 组件整段不渲染
  4. 普通 Child 用户访问 → 503 或无权限提示（现有 RBAC 菜单权限 WEB_MENU 负责，不属本 Feature）
  **覆盖 AC**: AC-08（UI 层 disabled）、AC-11（UI 层隐藏）、AC-13, AC-15
  **依赖**: T12, T13, T14, T15a

---

### 回归 + AC 对照

- [ ] **T16**: 本地回归 + AC 对照表 + 114 pytest + UI 手动验证
  **执行**:
  - 本地 `cd /Users/lilu/Projects/bisheng-worktrees/020-llm-tenant-isolation/src/backend && .venv/bin/pytest test/test_llm_tenant_isolation_*.py test/test_llm_cross_ref_*.py test/test_user_info_tenant_fields.py test/test_f020_migration.py -v`
  - F012/F013/F017/F019 回归（防止 F020 改 DAO/Service 造成破坏）:
    `.venv/bin/pytest test/test_tenant_context_vars.py test/test_user_payload_tenant.py test/test_admin_tenant_scope_api.py test/test_resource_share_service.py -v`
  - 114 远程 worktree 同步 + Alembic 演练（参考 F019 T13 的 deploy.sh 调用方式；注意 memory `feedback_114_dual_role` 避免 `--delete`）
  - 前端 `cd src/frontend/platform && npm run build` 确认无 TS 错误
  - 按 T15b 的"手动验证清单" + spec §8.5 的 24 条 pytest 用例 + AC 对照
  **产物**:
  - `features/v2.5.1/020-llm-tenant-isolation/ac-verification.md`（沿 F019 模板）
  - pytest 全绿截图或日志摘要
  - 若实际偏离 spec 记入本文件「实际偏差记录」
  **覆盖 AC**: 全部 24 条
  **依赖**: T01~T15b

---

## 实际偏差记录

> 完成后，记录实现与 spec.md 的偏差，供 `/code-review` 与后续 Feature 参考。

（暂无）

---

## 本地命令速查

```bash
WT=/Users/lilu/Projects/bisheng-worktrees/020-llm-tenant-isolation

# 单项 pytest
cd $WT/src/backend && .venv/bin/pytest test/test_llm_tenant_isolation_api.py::test_child_admin_cannot_edit_root_shared_llm -v

# Alembic 演练
cd $WT/src/backend && .venv/bin/alembic history --verbose | head -20
cd $WT/src/backend && .venv/bin/alembic upgrade head

# black + ruff
cd $WT/src/backend && .venv/bin/black . && .venv/bin/ruff check --fix bisheng/llm/ bisheng/common/errcode/llm_tenant.py bisheng/core/config/llm.py

# 前端 TS 检查
cd $WT/src/frontend/platform && npm run build
```
