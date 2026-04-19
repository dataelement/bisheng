# Tasks: F016-tenant-quota-hierarchy (配额沿树取严 + MVP 手工调整)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/016-tenant-quota-hierarchy`（base=`2.5.0-PM`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-19 `/sdd-review spec` 修复 3 项 medium + 2 项 low；新增 §9 API 契约 |
| tasks.md | ✅ 已拆解 | 2026-04-19 `/sdd-review tasks` 第 2 轮通过；修复 T05 4 文件超标（集成测并入 T07）；Test-Alongside 模式沿用 F013 |
| 实现 | 🔲 未开始 | 9 任务待启动 |

---

## 开发模式

**后端 Test-Alongside**（F011/F013 同款，plan 阶段已确认）：
- F016 扩展 v2.5.0 F005 `QuotaService`（非新建模块），不引入新 DDD 目录
- 单测与实现合并在同一任务（每个 Domain 任务包含 `test_quota_service_*.py` 单测文件）
- E2E 测试（T07）独立任务，覆盖 spec §7 九条手工 QA 中可自动化的 7 条
- AC-05（删除资源释放配额）与 AC-10（衍生数据归属）走**测试降级**：
  - AC-05 无独立实现代码，靠现有资源删除路径的 count SQL 自然生效，T09 手工验证
  - AC-10 依赖 F017 §5.4 `ChatMessageService` / `LLMTokenTracker` 写入层，F017 未合并时无法 E2E；F016 仅提供 SQL 模板 stub（缺表返 0），T07 覆盖"缺表降级"，T09 联调

**前端**：N/A — F016 仅新增 1 个后端 API `GET /tenants/quota/tree`；前端管理页集成归后续 Feature 或 T08 附带验证 MVP 呈现。

**决策锁定**（来自 plan 阶段用户确认，见 `.claude/plans/2-5-2-5-immutable-cupcake.md`）：
- **D1** 代码归属：扩展 v2.5.0 `QuotaService`，不新建 `QuotaChecker` 独立类
- **D2** 错误码策略：新增 194xx 子类；v2.5.0 `QuotaExceededError(24001)` 保留不删，内部切到 194xx
- **D3** tenant 链路获取在 `get_effective_quota._apply_tenant_cap` 内改写为 `_apply_tenant_chain_cap`
- **D4** Root 聚合用 `asyncio.gather` 避免 N+1
- **D5** `strict_tenant_filter()` 包裹所有 Tenant 级计数（包括叶子自身，防御性）
- **D6** `storage_gb / user_count / model_tokens_monthly` 加入 `VALID_QUOTA_KEYS` + SQL 模板，但**不进** `DEFAULT_ROLE_QUOTA`（3 类是租户级非角色级）
- **D7** 树形 API 新端点 `GET /tenants/quota/tree`（仅全局超管），不扩展 `GET /tenants/{id}/quota`
- **D8** Admin 直通保留（`login_user.is_admin() → -1` 短路不变）
- **AC-04 HTTP 码决策**：业务码 19403 走 HTTP 200 + `UnifiedResponseModel`（而非 HTTP 413，保持项目统一）

---

## 依赖图

```
T01 (errcode 194xx) ─────────────────────────────┐
                                                 │
T02 (VALID_QUOTA_KEYS + SQL 模板扩展)  ← T01 ────┤
   │                                             │
   ↓                                             │
T03 (_count_usage_strict + _aggregate_root_usage + 单测)  ← T02
   │
   ↓
T04 (_apply_tenant_chain_cap + check_quota 异常切换 + 单测)  ← T03
   │
   ├────→ T05 (TenantQuotaTree DTO + Service + API + 集成测)
   │
   └────→ T06 (v2.5.0 旧测试兼容回归)
                │
                ↓
T07 (E2E test_e2e_tenant_quota_hierarchy.py)  ← T04, T05, T06
   │
   ↓
T08 (文档同步 + README 状态)  ← T01-T07
   │
   ↓
T09 (手工 QA + ac-verification.md)  ← T08
```

---

## Tasks

### 基础设施

- [x] **T01**: 错误码注册（194xx）+ release-contract / CLAUDE.md 校验

  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/tenant_quota.py` — 3 个错误码类

  **文件（修改）**: 无（release-contract.md 表 3 "194 = tenant_quota F016" 已声明，CLAUDE.md 错误码模块表已同步 —— **仅校验不修改**）

  **逻辑**:
  ```python
  # src/backend/bisheng/common/errcode/tenant_quota.py
  """Tenant quota module error codes, module code: 194 (F016).

  Declared in CLAUDE.md + release-contract.md; this file is the authoritative registry.
  Inherits BaseErrorCode → HTTP 200 + UnifiedResponseModel.status_code (per project convention).
  """
  from .base import BaseErrorCode


  class TenantQuotaExceededError(BaseErrorCode):
      """Leaf Tenant or Root hard-cap quota exceeded (AC-01, AC-07, AC-08).

      When raised because Root usage reached Root limit (Child creation blocked by
      group-wide cap), the ``Msg`` variant should contain '集团总量已耗尽' for AC-08.
      """
      Code: int = 19401
      Msg: str = 'Tenant quota exceeded'


  class TenantRoleQuotaExceededError(BaseErrorCode):
      """Role-level quota exceeded after Tenant chain check passed (AC-01)."""
      Code: int = 19402
      Msg: str = 'Role quota exceeded'


  class TenantStorageQuotaExceededError(BaseErrorCode):
      """Storage quota (storage_gb / knowledge_space_file) exceeded (AC-04)."""
      Code: int = 19403
      Msg: str = 'Storage quota exceeded'
  ```

  **依赖**: —

  **验收**: `python -c "from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError; e=TenantQuotaExceededError(); print(e.return_resp_instance().model_dump())"` 返回 `{status_code: 19401, status_message: 'Tenant quota exceeded', data: None}`

- [x] **T02**: `VALID_QUOTA_KEYS` 扩展 + `_RESOURCE_COUNT_TEMPLATES` 新增 3 个 SQL 模板

  **文件（修改）**:
  - `src/backend/bisheng/role/domain/services/quota_service.py`

  **修改位置**:
  - L36 `VALID_QUOTA_KEYS`：
    ```python
    VALID_QUOTA_KEYS = set(DEFAULT_ROLE_QUOTA.keys()) | {
        'storage_gb', 'user_count', 'model_tokens_monthly',
    }
    ```
  - L40-49 `_RESOURCE_COUNT_TEMPLATES.update({...})`：
    ```python
    _RESOURCE_COUNT_TEMPLATES.update({
        # storage_gb: 所有知识文件字节数 SUM → 后续在 _count_resource 中 //GB
        'storage_gb': (
            "SELECT COALESCE(SUM(file_size), 0) FROM knowledgefile "
            "WHERE {col}=:{param} AND status IN (1,2)"
        ),
        # user_count: 租户下活跃用户数（通过 user_tenant 关联）
        # Note: 'user_id' 列在 user 表、'tenant_id' 列在 user_tenant 表；
        #       当 {col}='tenant_id' 时此模板有效；{col}='user_id' 时返 0（无语义）
        'user_count': (
            "SELECT COUNT(DISTINCT ut.user_id) FROM user_tenant ut "
            "INNER JOIN user u ON u.user_id = ut.user_id "
            "WHERE ut.{col}=:{param} AND ut.is_active=1 AND u.delete=0"
        ),
        # model_tokens_monthly: 本月 LLM token 消耗累加（F017 合入 llm_token_log 表后生效；
        # 当前表不存在 → _count_resource 的 try/except 返 0，stub-safe）
        'model_tokens_monthly': (
            "SELECT COALESCE(SUM(total_tokens), 0) FROM llm_token_log "
            "WHERE {col}=:{param} AND created_at >= DATE_FORMAT(NOW(), '%Y-%m-01')"
        ),
    })
    ```
  - L248-249 GB 转换分支扩展：
    ```python
    if resource_type in ('knowledge_space_file', 'storage_gb'):
        count = count // (1024 * 1024 * 1024)
    ```
  - L52-61 `QuotaResourceType` 增量：
    ```python
    class QuotaResourceType:
        # ... existing 8 常量
        STORAGE_GB = 'storage_gb'
        USER_COUNT = 'user_count'
        MODEL_TOKENS_MONTHLY = 'model_tokens_monthly'
    ```

  **不改 `DEFAULT_ROLE_QUOTA`**（3 新键是租户级非角色级；`_compute_role_quotas` 只遍历 `DEFAULT_ROLE_QUOTA`，新键对它透明）

  **依赖**: T01

  **验收**:
  - `QuotaService.validate_quota_config({'storage_gb': 100})` 不抛异常
  - `QuotaService.validate_quota_config({'xxx': 1})` 抛 `QuotaConfigInvalidError(24005)`
  - `QuotaService.get_tenant_resource_count(1, 'model_tokens_monthly')` 在表缺失时返 `0` 不 crash
  - 覆盖 AC: AC-04（`storage_gb` 前置依赖）, AC-10（`model_tokens_monthly` 前置依赖）

### 后端 Domain

- [x] **T03**: `_count_usage_strict` + `_aggregate_root_usage` + 单测

  **文件（修改）**:
  - `src/backend/bisheng/role/domain/services/quota_service.py` — 新增 2 个 `@classmethod`

  **文件（新建）**:
  - `src/backend/test/test_quota_service_tenant_tree.py` — 单测文件

  **新增方法**:
  ```python
  # 放在 get_user_resource_count (L261-263) 之后
  @classmethod
  async def _count_usage_strict(cls, tenant_id: int, resource_type: str) -> int:
      """Strict-equality count; wraps with strict_tenant_filter to prevent IN-list
      inflating Child usage with Root shared resources (INV-T6, AC-02, AC-09).

      Note: `_count_resource` uses raw text SQL with explicit WHERE tenant_id=:id,
      so strict_tenant_filter() is defensive — ORM event listener does not touch
      raw text statements, but semantic clarity for future refactors is worth it.
      """
      from bisheng.core.context.tenant import strict_tenant_filter
      with strict_tenant_filter():
          return await cls.get_tenant_resource_count(tenant_id, resource_type)

  @classmethod
  async def _aggregate_root_usage(cls, root_id: int, resource_type: str) -> int:
      """Root usage = Root self + Σ active Child (INV-T9, AC-07).

      Only ``status='active'`` Children count; disabled/archived/orphaned are
      excluded per spec §5. Uses asyncio.gather to avoid N+1.
      """
      from bisheng.database.models.tenant import TenantDao
      root_self = await cls._count_usage_strict(root_id, resource_type)
      child_ids = await TenantDao.aget_children_ids_active(root_id)
      if not child_ids:
          return root_self
      child_counts = await asyncio.gather(
          *[cls._count_usage_strict(cid, resource_type) for cid in child_ids]
      )
      return root_self + sum(child_counts)
  ```

  **单测** (`test_quota_service_tenant_tree.py`)：
  ```python
  # 覆盖 AC: AC-02, AC-07, AC-09
  async def test_count_usage_strict_excludes_sibling_tenants(db_session, factories):
      """Child A has 3 knowledge_space rows; Child B has 5; Root has 2.
      _count_usage_strict(Child A) == 3 (不含 B 或 Root)."""
      root = factories.make_tenant(id=1, parent_tenant_id=None)
      child_a = factories.make_tenant(id=5, parent_tenant_id=1)
      child_b = factories.make_tenant(id=6, parent_tenant_id=1)
      factories.make_knowledge_spaces(tenant_id=5, count=3)
      factories.make_knowledge_spaces(tenant_id=6, count=5)
      factories.make_knowledge_spaces(tenant_id=1, count=2)
      assert await QuotaService._count_usage_strict(5, 'knowledge_space') == 3

  async def test_aggregate_root_usage_sums_self_plus_active_children(db_session, factories):
      """AC-07 场景：Child A=30, Child B=50, Root 自身=20 → Root total=100"""
      # setup: Root=1 (active), Child A=5 (active), Child B=6 (active), Child C=7 (archived)
      factories.make_tenant(id=1, parent_tenant_id=None, status='active')
      factories.make_tenant(id=5, parent_tenant_id=1, status='active')
      factories.make_tenant(id=6, parent_tenant_id=1, status='active')
      factories.make_tenant(id=7, parent_tenant_id=1, status='archived')  # 不计
      factories.make_knowledge_spaces(tenant_id=1, count=20)
      factories.make_knowledge_spaces(tenant_id=5, count=30)
      factories.make_knowledge_spaces(tenant_id=6, count=50)
      factories.make_knowledge_spaces(tenant_id=7, count=99)  # archived 不计
      assert await QuotaService._aggregate_root_usage(1, 'knowledge_space') == 100

  async def test_aggregate_root_usage_no_children(db_session, factories):
      """Root with no active children: just return root_self count."""
      factories.make_tenant(id=1, parent_tenant_id=None, status='active')
      factories.make_knowledge_spaces(tenant_id=1, count=7)
      assert await QuotaService._aggregate_root_usage(1, 'knowledge_space') == 7
  ```

  **依赖**: T02

  **验收**:
  - `pytest test/test_quota_service_tenant_tree.py` 全绿
  - 覆盖 AC: AC-02（strict 避免叠加）, AC-07（Root 聚合算法）, AC-09（strict_tenant_filter 包裹）

- [x] **T04**: `_apply_tenant_chain_cap` 重写 + `check_quota` 异常切换 + 单测

  **文件（修改）**:
  - `src/backend/bisheng/role/domain/services/quota_service.py` — 重写 L96-134

  **文件（新建）**:
  - `src/backend/test/test_quota_service_check_chain.py` — 单测文件

  **重写 L96-110 `_apply_tenant_cap` → `_apply_tenant_chain_cap`**:
  ```python
  @classmethod
  async def _apply_tenant_chain_cap(
      cls, role_quota: int, tenant_id: int, resource_type: str,
  ) -> tuple[int, Optional[tuple[int, str]]]:
      """Apply Tenant-chain hard limit (leaf + Root if Child).

      Returns (effective_remaining, blocker):
      - effective_remaining: min of all chain remaining + role_quota (-1 if all unlimited)
      - blocker: (tenant_id, reason) when some node already at 100%, else None.
                 reason in {'tenant_limit', 'root_hardcap'} for AC-08 Msg variant.
      """
      tenant = await TenantDao.aget_by_id(tenant_id)
      if not tenant:
          return role_quota, None

      # Build chain: [leaf] or [leaf, Root] per INV-T1 (MVP 2-layer).
      chain: list[Tenant] = [tenant]
      if tenant.parent_tenant_id is not None:
          root = await TenantDao.aget_by_id(tenant.parent_tenant_id)
          if root:
              chain.append(root)

      tenant_remaining = -1
      for t in chain:
          limit = (t.quota_config or {}).get(resource_type, -1)
          if limit == -1:
              continue
          is_root = t.parent_tenant_id is None
          used = (
              await cls._aggregate_root_usage(t.id, resource_type) if is_root
              else await cls._count_usage_strict(t.id, resource_type)
          )
          remaining = max(limit - used, 0)
          if remaining == 0:
              reason = 'root_hardcap' if is_root else 'tenant_limit'
              return 0, (t.id, reason)
          tenant_remaining = remaining if tenant_remaining == -1 else min(tenant_remaining, remaining)

      if role_quota == -1:
          return tenant_remaining, None
      if tenant_remaining == -1:
          return role_quota, None
      return min(tenant_remaining, role_quota), None
  ```

  **`get_effective_quota` (L67-94) 适配**：
  ```python
  @classmethod
  async def get_effective_quota(
      cls, user_id: int, resource_type: str, tenant_id: int, login_user=None,
  ) -> int:
      if login_user and login_user.is_admin():
          return -1  # AC: admin 直通保留
      # ... 角色 quota 计算保持 ...
      effective, _blocker = await cls._apply_tenant_chain_cap(role_quota, tenant_id, resource_type)
      return effective
  ```

  **`check_quota` (L112-134) 切换异常类型**：
  ```python
  from bisheng.common.errcode.tenant_quota import (
      TenantQuotaExceededError, TenantRoleQuotaExceededError, TenantStorageQuotaExceededError,
  )

  @classmethod
  async def check_quota(
      cls, user_id: int, resource_type: str, tenant_id: int, login_user=None,
  ) -> bool:
      if login_user and login_user.is_admin():
          return True

      # ... compute role_quota ...

      effective, blocker = await cls._apply_tenant_chain_cap(role_quota, tenant_id, resource_type)
      if blocker is not None:
          blocker_tid, reason = blocker
          # AC-04: storage_gb 特殊化
          if resource_type in ('storage_gb', 'knowledge_space_file'):
              raise TenantStorageQuotaExceededError(
                  msg=f'Storage quota exceeded at tenant {blocker_tid} ({reason})',
              )
          # AC-08: Root 硬盖触发 Child 阻断 msg 变体
          if reason == 'root_hardcap':
              raise TenantQuotaExceededError(
                  msg=f'集团总量已耗尽（Root tenant {blocker_tid} quota for {resource_type} reached）',
              )
          raise TenantQuotaExceededError(
              msg=f'Tenant {blocker_tid} quota exceeded for {resource_type}',
          )
      if effective == -1:
          return True

      user_used = await cls.get_user_resource_count(user_id, resource_type)
      if user_used >= effective:
          raise TenantRoleQuotaExceededError(
              msg=f'Role quota exceeded for {resource_type} (used={user_used}, effective={effective})',
          )
      return True
  ```

  **单测** (`test_quota_service_check_chain.py`)：
  ```python
  # 覆盖 AC: AC-01, AC-04, AC-08

  async def test_check_quota_leaf_exceeded(factories, login_user_child):
      """AC-01: Child quota_config.knowledge_space=2，已建 2 个 → 第 3 个抛 19401."""
      factories.make_tenant(id=5, parent_tenant_id=1, quota_config={'knowledge_space': 2})
      factories.make_knowledge_spaces(tenant_id=5, count=2)
      with pytest.raises(TenantQuotaExceededError) as exc:
          await QuotaService.check_quota(
              user_id=login_user_child.user_id, resource_type='knowledge_space',
              tenant_id=5, login_user=login_user_child,
          )
      assert exc.value.Code == 19401

  async def test_check_quota_root_hardcap_blocks_child(factories, login_user_child):
      """AC-08: Root=5 / Child=10, Root 已用 5 (Root自身 2 + Child 3) → Child 再创抛 19401 + msg 含'集团总量已耗尽'."""
      factories.make_tenant(id=1, parent_tenant_id=None, quota_config={'knowledge_space': 5})
      factories.make_tenant(id=5, parent_tenant_id=1, quota_config={'knowledge_space': 10})
      factories.make_knowledge_spaces(tenant_id=1, count=2)
      factories.make_knowledge_spaces(tenant_id=5, count=3)  # Child 用量 3 <10, 单 Child 不触
      with pytest.raises(TenantQuotaExceededError) as exc:
          await QuotaService.check_quota(
              user_id=login_user_child.user_id, resource_type='knowledge_space',
              tenant_id=5, login_user=login_user_child,
          )
      assert '集团总量已耗尽' in exc.value.Msg

  async def test_check_quota_storage_raises_19403(factories, login_user_child):
      """AC-04: storage_gb 超限抛 TenantStorageQuotaExceededError(19403)."""
      factories.make_tenant(id=5, parent_tenant_id=1, quota_config={'storage_gb': 1})
      # 填 2 GB 文件 (2 * 1024**3 bytes)
      factories.make_knowledgefile(tenant_id=5, file_size=2 * (1024**3))
      with pytest.raises(TenantStorageQuotaExceededError) as exc:
          await QuotaService.check_quota(
              user_id=login_user_child.user_id, resource_type='storage_gb',
              tenant_id=5, login_user=login_user_child,
          )
      assert exc.value.Code == 19403

  async def test_check_quota_admin_bypass(factories, login_user_admin):
      """Admin 直通 — 即使叶子已 100% 也放行."""
      factories.make_tenant(id=5, parent_tenant_id=1, quota_config={'knowledge_space': 0})
      assert await QuotaService.check_quota(
          user_id=login_user_admin.user_id, resource_type='knowledge_space',
          tenant_id=5, login_user=login_user_admin,
      ) is True

  async def test_check_quota_unlimited_neg1(factories, login_user_child):
      """quota=-1 无限制."""
      factories.make_tenant(id=5, parent_tenant_id=1, quota_config={'workflow': -1})
      for _ in range(10):
          factories.make_workflow(tenant_id=5)
      assert await QuotaService.check_quota(
          user_id=login_user_child.user_id, resource_type='workflow',
          tenant_id=5, login_user=login_user_child,
      ) is True
  ```

  **依赖**: T03

  **验收**:
  - `pytest test/test_quota_service_check_chain.py` 全绿（5 条测试）
  - 覆盖 AC: AC-01（单 Tenant 阻断）, AC-04（storage 19403）, AC-08（Root 硬盖 msg 变体）

### 后端 API

- [x] **T05**: TenantQuotaTree DTO + `TenantService.aget_quota_tree` + `GET /tenants/quota/tree`

  **文件（修改，3 个）**:
  - `src/backend/bisheng/tenant/domain/schemas/tenant_schema.py` — 新增 3 个 DTO
  - `src/backend/bisheng/tenant/domain/services/tenant_service.py` — 新增 `aget_quota_tree`
  - `src/backend/bisheng/tenant/api/endpoints/tenant_crud.py` — 新增 `GET /quota/tree` 端点

  **文件（新建）**: 无 —— API 集成测（`test_quota_tree_returns_root_and_active_children` / `test_quota_tree_forbidden_for_non_super_admin` / `test_put_quota_accepts_storage_gb_key`）合并至 **T07 E2E 测试**（T05 保持 ≤3 文件粒度）

  **schema 新增**（见 spec §9.3）：
  ```python
  class TenantQuotaUsageItem(BaseModel):
      resource_type: str
      used: int
      limit: int
      utilization: float

  class TenantQuotaTreeNode(BaseModel):
      tenant_id: int
      tenant_name: str
      parent_tenant_id: Optional[int]
      quota_config: dict
      usage: list[TenantQuotaUsageItem]

  class TenantQuotaTreeResponse(BaseModel):
      root: TenantQuotaTreeNode
      children: list[TenantQuotaTreeNode]
  ```

  **service 新增**：
  ```python
  # tenant_service.py
  @classmethod
  async def aget_quota_tree(cls, login_user: UserPayload) -> TenantQuotaTreeResponse:
      """Build the full quota tree (Root + all active Children) for global super admin."""
      from bisheng.role.domain.services.quota_service import QuotaService, VALID_QUOTA_KEYS
      root = await TenantDao.aget_by_id(ROOT_TENANT_ID)
      child_ids = await TenantDao.aget_children_ids_active(ROOT_TENANT_ID)
      children = [await TenantDao.aget_by_id(cid) for cid in child_ids]

      async def _build_node(t: Tenant, is_root: bool) -> TenantQuotaTreeNode:
          usage_items: list[TenantQuotaUsageItem] = []
          for rt in sorted(VALID_QUOTA_KEYS):
              limit = (t.quota_config or {}).get(rt, -1)
              used = (
                  await QuotaService._aggregate_root_usage(t.id, rt) if is_root
                  else await QuotaService._count_usage_strict(t.id, rt)
              )
              utilization = 0.0 if limit == -1 else (used / limit if limit > 0 else 1.0)
              usage_items.append(TenantQuotaUsageItem(
                  resource_type=rt, used=used, limit=limit, utilization=utilization,
              ))
          return TenantQuotaTreeNode(
              tenant_id=t.id, tenant_name=t.tenant_name,
              parent_tenant_id=t.parent_tenant_id,
              quota_config=t.quota_config or {},
              usage=usage_items,
          )

      return TenantQuotaTreeResponse(
          root=await _build_node(root, is_root=True),
          children=[await _build_node(c, is_root=False) for c in children if c],
      )
  ```

  **endpoint**（tenant_crud.py L151 后）：
  ```python
  @router.get('/quota/tree')
  async def get_quota_tree(
      login_user: UserPayload = Depends(UserPayload.get_admin_user),
  ):
      try:
          result = await TenantService.aget_quota_tree(login_user)
          return resp_200(result)
      except BaseErrorCode as e:
          return e.return_resp_instance()
  ```

  **API 集成测**：见 T07（已合并）

  **依赖**: T04

  **验收**:
  - `python -c "from bisheng.tenant.domain.services.tenant_service import TenantService; print(TenantService.aget_quota_tree.__doc__)"` 无 ImportError
  - 路由注册可见：`curl http://localhost:7860/openapi.json | jq '.paths | keys[] | select(contains("quota/tree"))'`
  - 完整 AC 验证由 T07 承接（覆盖 AC: AC-03, AC-06）

### 测试

- [x] **T06**: v2.5.0 F005/F008 旧测试回归兼容

  **文件（修改）**:
  - `src/backend/test/test_require_quota_decorator.py` — 断言 `QuotaExceededError(24001)` 的地方切换或保持（取决于旧测试是否断言 `isinstance(e, QuotaExceededError)`）
  - `src/backend/test/test_e2e_role_menu_quota.py` — 同上

  **验证原则**：
  - 仅 Tenant 链触发的超限：旧测试断言点若通过 `QuotaExceededError` 基类断言则保持（194xx 继承 BaseErrorCode，与 24001 兄弟关系而非继承关系 → 旧断言会 fail）
  - 若旧测试 `assert isinstance(e, QuotaExceededError)` 必 fail → 改为 `assert isinstance(e, (QuotaExceededError, TenantQuotaExceededError, TenantRoleQuotaExceededError))`
  - 旧测试如果断言 `e.Code == 24001`，改为 `e.Code in (24001, 19402)`（兼容两阶段）

  **替代方案（如旧测试过多）**：在 `QuotaService.check_quota` 抛 194xx 前，先单独保持旧代码路径 —— 不推荐，增加维护复杂度。

  **依赖**: T04

  **验收**:
  - `pytest test/test_require_quota_decorator.py test/test_e2e_role_menu_quota.py` 全绿
  - 覆盖 AC: AC-01（回归）

- [ ] **T07**: E2E 测试 `test_e2e_tenant_quota_hierarchy.py`

  **文件（新建）**:
  - `src/backend/test/e2e/test_e2e_tenant_quota_hierarchy.py` — 端到端测试

  **覆盖 spec §7 九条手工 QA 中 7 条可自动化 + T05 API 集成测（合并自修复后的 tasks review）**：

  ```python
  # 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-06, AC-07, AC-08, AC-09, AC-10（stub 层面）

  # --- 核心配额链路 ---
  async def test_single_tenant_100pct_blocks():
      """§7-1 / AC-01: 单 Tenant 内配额 100% 阻断 → 19401"""

  async def test_root_hardcap_less_than_child_triggers_first():
      """§7-2 / AC-01 AC-08: Root=5 < Child=10, Root 已满 → Child 创建抛 19401 msg 含 '集团总量'"""

  async def test_shared_resource_counts_only_root():
      """§7-3 / AC-02: Root 创建共享知识库 + FGA shared_to → Child 用量 SQL 不含此资源"""

  async def test_root_aggregate_usage_30_50_20():
      """§7-4 / AC-07: Child A=30, Child B=50, Root=20 → _aggregate_root_usage(1) == 100"""

  async def test_root_saturated_blocks_all_children():
      """§7-5 / AC-08: Root quota=100, 已用 100 → 任一 Child 创建抛 19401"""

  async def test_strict_filter_no_inlist_leak():
      """§7-6 / AC-09: Root 创建共享资源（IN-list 场景下）→ _count_usage_strict(child) 仍不含"""

  async def test_minus_one_unlimited():
      """§7-9: quota=-1 无限制，重复创建不阻断"""

  async def test_model_tokens_monthly_table_missing_returns_zero():
      """AC-10 stub-safe: llm_token_log 表缺失时 _count_resource 返 0 不 crash"""

  # --- T05 API 集成测（AC-03 / AC-06）---
  async def test_quota_tree_returns_root_and_active_children(client, factories, admin_cookie):
      """AC-06: Root + 2 active Children + 1 archived Child → tree 不含 archived."""
      factories.make_tenant(id=1, parent_tenant_id=None, quota_config={'knowledge_space': 100})
      factories.make_tenant(id=5, parent_tenant_id=1, status='active', quota_config={'knowledge_space': 30})
      factories.make_tenant(id=6, parent_tenant_id=1, status='active')
      factories.make_tenant(id=7, parent_tenant_id=1, status='archived')
      resp = await client.get('/api/v1/tenants/quota/tree', cookies=admin_cookie)
      assert resp.status_code == 200
      data = resp.json()['data']
      assert data['root']['tenant_id'] == 1
      assert {c['tenant_id'] for c in data['children']} == {5, 6}

  async def test_quota_tree_forbidden_for_non_super_admin(client, child_admin_cookie):
      """AC-06: Only global super admin can access /quota/tree."""
      resp = await client.get('/api/v1/tenants/quota/tree', cookies=child_admin_cookie)
      assert resp.status_code == 403

  async def test_put_quota_accepts_storage_gb_key(client, factories, admin_cookie):
      """AC-03: PUT /tenants/{id}/quota 接受 storage_gb 键（T02 扩展 VALID_QUOTA_KEYS 的端到端验证）."""
      factories.make_tenant(id=5, parent_tenant_id=1)
      resp = await client.put(
          '/api/v1/tenants/5/quota',
          json={'quota_config': {'storage_gb': 100, 'knowledge_space': 30}},
          cookies=admin_cookie,
      )
      assert resp.status_code == 200
      assert resp.json()['data']['quota_config']['storage_gb'] == 100
  ```

  **测试降级（不覆盖）**：
  - §7-7「衍生数据归属」：依赖 F017 §5.4 写入层；F017 未合并前无写入路径，F016 仅能测"读 SUM 返 0"；完整 E2E 在 T09 手工联调
  - §7-8「全局超管手工调整 quota_config 立即生效」：T05 `test_put_quota_accepts_storage_gb_key` 已覆盖
  - §7-?「删除资源释放配额」：AC-05，无代码变更，T09 手工验证

  **依赖**: T04, T05, T06

  **验收**:
  - `pytest test/e2e/test_e2e_tenant_quota_hierarchy.py -v` 全绿（11 条测试）
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-06, AC-07, AC-08, AC-09, AC-10（stub 层面）

### 文档

- [ ] **T08**: 文档同步 + README / release-contract / CLAUDE.md 校验

  **文件（修改）**:
  - `features/v2.5.1/README.md` — F016 状态 `🔲 未开始` → `✅ 已完成`
  - `features/v2.5.1/016-tenant-quota-hierarchy/tasks.md` — 状态表 "实现" 行改 `✅ 已完成`

  **文件（校验不修改，若不一致则改）**：
  - `features/v2.5.1/release-contract.md` — 表 3 中 `194 | tenant_quota | F016` 已存在 → 校验
  - `CLAUDE.md` — 错误码模块表中 `194=tenant_quota (F016)` 已存在 → 校验

  **文件（新建）**：
  - `features/v2.5.1/016-tenant-quota-hierarchy/ac-verification.md` — 从 F013 复制模板并填 AC-01~AC-10 验证记录（T09 填内容）

  **依赖**: T01-T07

  **验收**: `/sdd-review tasks` 通过；文档 grep 一致性校验。

- [ ] **T09**: 手工 QA 执行 + ac-verification.md 填表

  **文件（修改）**:
  - `features/v2.5.1/016-tenant-quota-hierarchy/ac-verification.md` — 填入 spec §7 九条 QA 实际运行结果（Pass/Fail + 截图或日志）

  **手工 QA 清单**（spec §7 全部 9 条）：
  1. 单 Tenant 内配额 100% 阻断 — T04/T07 已自动化，仅校验
  2. Root 硬限 < Child 配额时 Root 限触发 — T04/T07 已自动化
  3. 共享资源仅计入 Root — T07 已自动化
  4. **Root 用量聚合** 30+50+20=100 — T03/T07 已自动化
  5. **Root 满触发 Child 阻断** — T04/T07 已自动化
  6. **strict_tenant_filter 验证** — T07 已自动化
  7. **衍生数据归属**（F017 依赖）— **仅此项需手工**：F017 合并后，Child 用户调 Root 共享 LLM，检查 `llm_token_log.tenant_id == child_id` 且 `get_all_effective_quotas(child).model_tokens_monthly.used` 递增
  8. 全局超管手工调整 quota_config 立即生效 — T05 已自动化
  9. 删除资源释放配额 — **仅此项需手工**：通过 UI 删除一个知识库，再创建一个新的观察是否放行

  **依赖**: T08

  **验收**:
  - ac-verification.md 9 项全部 Pass 记录
  - 如 §7-7 因 F017 未合并无法验证 → 记录为"Blocked by F017，合并后补测"

---

## 跨 Feature 副作用自检

- **修改共享文件 `quota_service.py`（F005 Owner）**：F005 Owner 延续到 v2.5.1，F016 为"同 Owner 内部扩展"，不跨 Feature；对 `require_quota` 装饰器签名零改动，5 个调用端点无感知。
- **修改 `tenant_service.py` / `tenant_crud.py`（F010/F011 Owner）**：仅新增 `aget_quota_tree` / `GET /quota/tree`，不改既有方法。
- **`release-contract.md` + `CLAUDE.md`**：194 已预分配，T08 仅校验不写入。

## 数据库回滚

F016 **无 DDL 变更** — 仅读 `tenant.quota_config`（F011 已建）+ 新增 Python 代码；无回滚风险。

## 实际偏差记录

（开发过程中产生的与 spec / tasks 不一致需在此登记）
