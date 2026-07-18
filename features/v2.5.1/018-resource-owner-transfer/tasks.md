# Tasks: F018-resource-owner-transfer (资源所有者交接 API)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/018-resource-owner-transfer`（base=`2.5.0-PM`，F011 已合入）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-21 Round 2 修订 |
| tasks.md | 🔲 本文件 | 2026-04-21 起草 |
| 实现 | 🔲 未开始 | — |

---

## 开发模式

**后端 Test-Alongside**（务实版，与 F011 一致）：
- 错误码 + Registry 先行（T01, T02）
- Service 层 + 单元测试合并（T03）
- API endpoints + 集成测试合并（T04）
- AC 对照 + 手工 QA 收口（T05）

**前端**：N/A — spec §2 AC-09/10 UI 本期不落地，等用户侧 feature 对齐后实现。

**决策锁定**（来自 plan 阶段）：
- **资源类型收窄为 7 类**（spec §5 原含 `dashboard`，但项目无 Dashboard ORM）；spec 做小改同步
- **`to_user_id_leaf` 内联派生**（F012 `TenantResolver` 未实施）：`UserTenantDao.aget_active_user_tenant(user_id).tenant_id`，无记录回退 `ROOT_TENANT_ID=1`
- **`is_global_super` 沿用 F011 `_require_super` 模式**：`getattr(operator, 'is_global_super', None)`；F011 `tenant_mount_service.py:60-64`
- **`aupdate_resource_user_ids` 写在 F018 Service 内**（不扩展 F011 `TenantDao`）——F011 DAO helper 职责是 tenant_id，user_id 是 F018 语义；避免跨 Feature 耦合
- **OpenFGA owner 翻转** 通过 `PermissionService.batch_write_tuples(ops, crash_safe=True)` —— F004 既有能力，自动 FailedTuple 补偿
- **Audit action 名** 需要先在 F011 `TenantAuditAction` enum 追加 `RESOURCE_TRANSFER_OWNER = 'resource.transfer_owner'`（F011 spec §5.4.2 已登记 `resource.transfer_owner` action，但 enum 尚未追加）

---

## 依赖图

```
T01 (errcode + CLAUDE.md + TenantAuditAction 扩展 + spec 微调)
  │
  v
T02 (ResourceTypeRegistry — 7 类资源元数据)
  │
  v
T03 (ResourceOwnershipService + Service 单测)
  │  [transfer_owner / list_pending_transfer]
  │
  v
T04 (API endpoints + DTO + 路由注册 + 集成测)
  │
  v
T05 (ac-verification.md + 手工 QA + 本地/远程回归)
```

---

## Tasks

### T01 — 错误码 + CLAUDE.md + Enum 扩展 + spec 微调

**文件（新建）**:
- `src/backend/bisheng/common/errcode/resource_owner_transfer.py` — 6 个错误码 `19601-19606`

**文件（修改）**:
- `src/backend/bisheng/tenant/domain/constants.py` — `TenantAuditAction` enum 追加 `RESOURCE_TRANSFER_OWNER = 'resource.transfer_owner'`
- `CLAUDE.md` — "错误码模块编码"清单在 `195=tenant_sharing` 后插入 `196=resource_owner_transfer`（已占位于 release-contract 表 3，但 CLAUDE.md 全局清单未同步）
- `features/v2.5.1/018-resource-owner-transfer/spec.md` — §5 `SUPPORTED_TYPES` 去掉 `dashboard`；文末补脚注说明延后原因；§1-§8 中所有 `dashboard` 引用改为脚注形式

**错误码定义**（模板对齐 F011 `tenant_tree.py` 风格）:
```python
# src/backend/bisheng/common/errcode/resource_owner_transfer.py
from .base import BaseErrorCode

# F018 resource owner transfer module, code: 196 (v2.5.1, spec §9)

class ResourceTransferPermissionError(BaseErrorCode):
    Code: int = 19601
    Msg: str = 'Only the resource owner or a tenant admin may transfer ownership'

class ResourceTransferBatchLimitError(BaseErrorCode):
    Code: int = 19602
    Msg: str = 'Transfer batch exceeds 500 items; split into smaller requests'

class ResourceTransferReceiverOutOfTenantError(BaseErrorCode):
    Code: int = 19603
    Msg: str = 'to_user leaf tenant must lie within the resource tenant visible set'

class ResourceTransferUnsupportedTypeError(BaseErrorCode):
    Code: int = 19604
    Msg: str = 'Unsupported resource type for transfer'

class ResourceTransferTxFailedError(BaseErrorCode):
    Code: int = 19605
    Msg: str = 'MySQL/OpenFGA transaction failed; all changes rolled back'

class ResourceTransferSelfError(BaseErrorCode):
    Code: int = 19606
    Msg: str = 'from_user_id and to_user_id must be different'
```

**测试**: 无（纯常量类；被下游任务隐式覆盖）
**覆盖 AC**: AC-03 / AC-07 / AC-08 / §9 错误码表
**依赖**: 无

---

### T02 — ResourceTypeRegistry（7 类资源元数据注册表）

**文件（新建）**:
- `src/backend/bisheng/tenant/domain/services/resource_type_registry.py`
- `src/backend/test/test_resource_type_registry.py`

**逻辑**:
```python
# resource_type_registry.py（示意结构）
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass(frozen=True)
class ResourceTypeMeta:
    resource_type: str          # 业务名 / FGA type
    table: str                  # MySQL 表名
    id_type: type               # int | str（Flow/Assistant/Channel 是 UUID str）
    type_filter_sql: Optional[str]  # e.g. "type = 3" | "file_type = 0" | "flow_type = 10" | None

REGISTRY: dict[str, ResourceTypeMeta] = {
    'knowledge_space': ResourceTypeMeta('knowledge_space', 'knowledge', int, 'type = 3'),
    'folder':          ResourceTypeMeta('folder',          'knowledgefile', int, 'file_type = 0'),
    'knowledge_file':  ResourceTypeMeta('knowledge_file',  'knowledgefile', int, 'file_type = 1'),
    'workflow':        ResourceTypeMeta('workflow',        'flow', str, 'flow_type = 10'),
    'assistant':       ResourceTypeMeta('assistant',       'assistant', str, None),
    'tool':            ResourceTypeMeta('tool',            't_gpts_tools', int, 'is_delete = 0'),
    'channel':         ResourceTypeMeta('channel',         'channel', str, None),
}

SUPPORTED_TYPES = tuple(REGISTRY.keys())  # 7 个

def get_meta(resource_type: str) -> ResourceTypeMeta: ...
```

**测试**（`test_resource_type_registry.py`）:
- `test_supported_types_exactly_7` — 长度 == 7，不含 dashboard
- `test_get_meta_known_type` — `get_meta('workflow').table == 'flow'`
- `test_get_meta_unknown_raises` — 抛 `ResourceTransferUnsupportedTypeError(19604)`
- `test_id_types_match_orm` — workflow/assistant/channel 为 str；其余 int
- `test_type_filters_present` — knowledge_space/folder/knowledge_file/workflow/tool 有 type_filter，assistant/channel 为 None

**覆盖 AC**: AC-03 分支（unsupported type → 19604）；spec §5 SUPPORTED_TYPES
**依赖**: T01

---

### T03 — ResourceOwnershipService + Service 单元测试

**文件（新建）**:
- `src/backend/bisheng/tenant/domain/services/resource_ownership_service.py`
- `src/backend/test/test_resource_ownership_service.py`

**逻辑**:
```python
# resource_ownership_service.py（核心 API）

class ResourceOwnershipService:
    MAX_BATCH = 500

    @classmethod
    async def transfer_owner(
        cls, tenant_id: int, from_user_id: int, to_user_id: int,
        resource_types: List[str], resource_ids: Optional[List[int | str]] = None,
        reason: str = '', operator=None,
    ) -> dict:
        # 1. 基础校验
        if from_user_id == to_user_id:
            raise ResourceTransferSelfError()
        for rt in resource_types:
            get_meta(rt)  # 校验 type；未知抛 19604

        # 2. 可见集合校验（叶子 ∈ {tenant_id, Root})
        await cls._check_receiver_visible(to_user_id, tenant_id)  # AC-08/08b/08c/08d

        # 3. 资源解析
        resources = await cls._resolve_resources(tenant_id, from_user_id, resource_types, resource_ids)
        if len(resources) > cls.MAX_BATCH:
            raise ResourceTransferBatchLimitError()  # AC-07
        if not resources:
            return {'transferred_count': 0, 'transfer_log_id': None}

        # 4. operator 权限检查（owner 本人 / tenant admin / 全局超管）
        cls._check_operator(operator, from_user_id)  # AC-03

        # 5. 事务：MySQL UPDATE → OpenFGA batch_write crash_safe → audit_log
        transfer_log_id = f'txn_{datetime.utcnow():%Y%m%d}_{uuid4().hex[:8]}'
        try:
            # 5a. MySQL：分表 UPDATE user_id（bypass_tenant_filter，显式 tenant_id 条件）
            for rt, rows in _group_by_type(resources):
                await cls._bulk_update_user_id(rt, [r.id for r in rows], to_user_id)

            # 5b. OpenFGA：翻转 owner 元组
            ops = []
            for r in resources:
                meta = get_meta(r.type)
                ops.append(TupleOperation('delete', f'user:{from_user_id}', 'owner',
                                          f'{meta.resource_type}:{r.id}'))
                ops.append(TupleOperation('write',  f'user:{to_user_id}',   'owner',
                                          f'{meta.resource_type}:{r.id}'))
            await PermissionService.batch_write_tuples(ops, crash_safe=True)

            # 5c. audit_log
            await _safe_audit(
                tenant_id=tenant_id,
                operator_id=getattr(operator, 'user_id', 0),
                operator_tenant_id=cls._resolve_operator_tenant(operator, tenant_id),
                action=TenantAuditAction.RESOURCE_TRANSFER_OWNER.value,
                target_type='resource_batch',
                target_id=transfer_log_id,
                reason=reason,
                metadata={
                    'from': from_user_id, 'to': to_user_id,
                    'count': len(resources),
                    'resource_types': list({r.type for r in resources}),
                    'resource_ids_by_type': _group_ids_by_type(resources),
                },
            )
        except Exception as exc:
            logger.error('transfer_owner transaction failed: %s', exc)
            raise ResourceTransferTxFailedError() from exc

        return {'transferred_count': len(resources), 'transfer_log_id': transfer_log_id}

    # ---------- helpers ----------

    @classmethod
    async def _resolve_leaf_tenant(cls, user_id: int) -> int:
        """F012 降级实现 — 从 UserTenant(is_active=1) 派生叶子 Tenant ID."""
        rec = await UserTenantDao.aget_active_user_tenant(user_id)
        return rec.tenant_id if rec else ROOT_TENANT_ID

    @classmethod
    async def _check_receiver_visible(cls, to_user_id: int, tenant_id: int) -> None:
        """AC-08 / INV-T10: to_user 叶子 ∈ {tenant_id, Root}."""
        leaf = await cls._resolve_leaf_tenant(to_user_id)
        allowed = {tenant_id, ROOT_TENANT_ID}
        if leaf not in allowed:
            raise ResourceTransferReceiverOutOfTenantError()

    @classmethod
    def _check_operator(cls, operator, from_user_id: int) -> None:
        """AC-03: owner 本人 / tenant admin / 全局超管 三选一."""
        if operator is None:
            raise ResourceTransferPermissionError()
        if getattr(operator, 'user_id', None) == from_user_id:
            return  # owner 本人
        is_super = getattr(operator, 'is_global_super', None)
        if callable(is_super) and is_super():
            return  # 全局超管
        if getattr(operator, 'is_admin', lambda: False)():
            return  # tenant admin（v2.5.0 既有 is_admin；F013 会细化为 is_tenant_admin）
        raise ResourceTransferPermissionError()

    @classmethod
    async def _resolve_resources(cls, tenant_id, from_user_id, resource_types, resource_ids):
        """按 type dispatch SELECT，返回 [ResourceRow(type, id, user_id, tenant_id)]."""
        results = []
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for rt in resource_types:
                    meta = get_meta(rt)
                    sql = f'SELECT id, user_id, tenant_id FROM {meta.table} WHERE user_id = :uid AND tenant_id = :tid'
                    params = {'uid': from_user_id, 'tid': tenant_id}
                    if meta.type_filter_sql:
                        sql += f' AND {meta.type_filter_sql}'
                    if resource_ids:
                        sql += ' AND id IN :ids'
                        stmt = text(sql).bindparams(bindparam('ids', expanding=True))
                        params['ids'] = [_coerce_id(meta.id_type, rid) for rid in resource_ids]
                    else:
                        stmt = text(sql)
                    rows = (await session.execute(stmt, params)).all()
                    for row in rows:
                        results.append(ResourceRow(type=rt, id=row[0], user_id=row[1], tenant_id=row[2]))
        return results

    @classmethod
    async def _bulk_update_user_id(cls, resource_type, ids, new_user_id):
        meta = get_meta(resource_type)
        if not ids:
            return
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = text(
                    f'UPDATE {meta.table} SET user_id = :uid WHERE id IN :ids'
                ).bindparams(bindparam('ids', expanding=True))
                await session.execute(stmt, {'uid': new_user_id, 'ids': ids})
                await session.commit()

    @classmethod
    def _resolve_operator_tenant(cls, operator, tenant_id):
        """AC 注脚：超管跨 Child 操作时 operator_tenant_id 与 tenant_id 不同。
        F019 admin_scope_tenant_id 未实施时回退 Root（1）。"""
        scope = getattr(operator, 'admin_scope_tenant_id', None)
        if scope:
            return scope
        is_super = getattr(operator, 'is_global_super', None)
        if callable(is_super) and is_super():
            return ROOT_TENANT_ID
        return getattr(operator, 'tenant_id', tenant_id)

    @classmethod
    async def list_pending_transfer(cls, tenant_id: int) -> list:
        """AC-10 MVP 实现：聚合 7 张表 user_id → 再与 UserTenant 当前 leaf 对比。
        返回 current_leaf != tenant_id（或 user 已无 active UserTenant 记录）的用户清单。
        """
        counts_by_user: dict[int, int] = {}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for meta in REGISTRY.values():
                    sql = (
                        f'SELECT user_id, COUNT(*) FROM {meta.table} '
                        f'WHERE tenant_id = :tid AND user_id IS NOT NULL '
                    )
                    if meta.type_filter_sql:
                        sql += f'AND {meta.type_filter_sql} '
                    sql += 'GROUP BY user_id'
                    rows = (await session.execute(text(sql), {'tid': tenant_id})).all()
                    for uid, n in rows:
                        if uid is None:
                            continue
                        counts_by_user[uid] = counts_by_user.get(uid, 0) + int(n)

        pending = []
        for uid, count in counts_by_user.items():
            leaf = await cls._resolve_leaf_tenant(uid)
            if leaf != tenant_id:  # 主部门已经切走 / 无 active 记录 → 待交接
                pending.append({'user_id': uid, 'resource_count': count, 'current_leaf_tenant_id': leaf})
        return pending
```

**测试**（`test_resource_ownership_service.py`）——每项一行用例名：
- `test_transfer_self_rejected_19606` — from==to → 19606
- `test_transfer_unsupported_type_19604` — resource_types 含 'dashboard' → 19604
- `test_transfer_batch_over_500_19602` — mock _resolve_resources 返 501 条 → 19602
- `test_transfer_receiver_out_of_tenant_19603_cross_child` — AC-08c：tenant_id=A, to_user leaf=B
- `test_transfer_receiver_root_to_child_19603` — AC-08d：tenant_id=Root, to_user leaf=Child
- `test_transfer_child_to_root_allowed` — AC-08b：tenant_id=Child, to_user leaf=Root → 不抛
- `test_transfer_owner_self_allowed` — owner 本人 → 通过 _check_operator
- `test_transfer_non_owner_non_admin_19601` — 普通用户转他人资源 → 19601
- `test_transfer_happy_path_mysql_fga_audit` — mock FGA，2 条资源 → MySQL user_id 更新；FGA 写 2 delete + 2 write；audit_log ainsert_v2 调用 1 次；transferred_count=2
- `test_transfer_resource_ids_null_returns_all` — AC-04：resource_ids=None 返回 from_user 全部
- `test_transfer_resource_ids_list_filtered` — AC-05：指定 id 仅交接命中项
- `test_transfer_fga_failure_rolls_back` — AC-06：mock FGA 抛异常 → 19605；audit_log 不写入（try 外 catch）
- `test_transfer_mixed_types` — 2 个 workflow + 1 个 knowledge_space → 3 条总计；分表 UPDATE 调 2 次
- `test_list_pending_transfer_filters_active_leaf` — 用户 A 在 tenant=2 下有 3 条资源，其 active leaf=3 → 返回 {user_id: A, count: 3, leaf: 3}
- `test_list_pending_transfer_excludes_current_leaf` — 用户 B 在 tenant=2，其 active leaf=2 → 不返回

**测试基础设施**:
- 使用 `db_session` / `async_db_session` fixture（F000 提供）+ `test/fixtures/factories.py` 建测试数据
- `operator` 用 `MagicMock(user_id=X, is_admin=lambda: True/False, is_global_super=lambda: True/False)`
- `PermissionService.batch_write_tuples` 用 `monkeypatch.setattr` 替换为 AsyncMock
- `AuditLogDao.ainsert_v2` 同上

**覆盖 AC**: AC-01/03/04/05/06/07/08/08b/08c/08d/10；AD-02/AD-03
**依赖**: T01, T02

---

### T04 — API endpoints + DTO + 路由注册 + 集成测试

**文件（新建）**:
- `src/backend/bisheng/tenant/api/schemas/transfer_schema.py`
- `src/backend/bisheng/tenant/api/endpoints/resource_owner_transfer.py`
- `src/backend/test/test_resource_owner_transfer_api.py`

**文件（修改）**:
- `src/backend/bisheng/tenant/api/router.py` — 在 `include_router(tenant_mount.router)` 后追加 `include_router(resource_owner_transfer.router)`

**DTO**:
```python
# transfer_schema.py
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field

ResourceType = Literal['knowledge_space', 'folder', 'knowledge_file',
                       'workflow', 'assistant', 'tool', 'channel']

class TransferOwnerRequest(BaseModel):
    from_user_id: int = Field(..., gt=0)
    to_user_id: int = Field(..., gt=0)
    resource_types: List[ResourceType] = Field(..., min_length=1)
    resource_ids: Optional[List[Union[int, str]]] = None  # int 或 UUID str
    reason: str = Field(default='', max_length=1000)

class TransferOwnerResponse(BaseModel):
    transferred_count: int
    transfer_log_id: Optional[str] = None

class PendingTransferItem(BaseModel):
    user_id: int
    resource_count: int
    current_leaf_tenant_id: int
```

**端点**:
```python
# endpoints/resource_owner_transfer.py
router = APIRouter(prefix='/tenants', tags=['F018 Resource Owner Transfer'])

@router.post('/{tenant_id}/resources/transfer-owner',
             response_model=UnifiedResponseModel[TransferOwnerResponse])
async def transfer_owner(
    tenant_id: int,
    body: TransferOwnerRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    result = await ResourceOwnershipService.transfer_owner(
        tenant_id=tenant_id,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        resource_types=body.resource_types,
        resource_ids=body.resource_ids,
        reason=body.reason,
        operator=user,
    )
    return resp_200(data=TransferOwnerResponse(**result))

@router.get('/{tenant_id}/resources/pending-transfer',
            response_model=UnifiedResponseModel[List[PendingTransferItem]])
async def list_pending_transfer(
    tenant_id: int,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    # 仅超管 / tenant admin 可见
    is_super = getattr(user, 'is_global_super', lambda: False)()
    is_admin = getattr(user, 'is_admin', lambda: False)()
    if not (is_super or is_admin):
        raise ResourceTransferPermissionError()
    items = await ResourceOwnershipService.list_pending_transfer(tenant_id)
    return resp_200(data=[PendingTransferItem(**it) for it in items])
```

**集成测试**（`test_resource_owner_transfer_api.py`，参照 F011 `test_tenant_mount_api.py` 结构）:
- `test_transfer_owner_happy_path_returns_200` — AC-01
- `test_transfer_owner_child_admin_ok` — AC-02：operator.is_admin() 且 user_id != from
- `test_transfer_owner_non_owner_returns_19601` — AC-03
- `test_transfer_owner_resource_ids_null_returns_count_N` — AC-04
- `test_transfer_owner_specific_ids_only_returns_K` — AC-05
- `test_transfer_owner_over_500_returns_19602` — AC-07
- `test_transfer_owner_to_user_cross_child_returns_19603` — AC-08c
- `test_transfer_owner_root_to_child_returns_19603_with_hint` — AC-08d，响应 msg 含 "migrate-from-root"
- `test_transfer_owner_child_to_root_allowed` — AC-08b
- `test_pending_transfer_lists_relocated_users` — AC-10
- `test_pending_transfer_forbidden_for_normal_user` — 普通用户 → 19601

**覆盖 AC**: AC-01/02/03/04/05/07/08b/08c/08d/10（HTTP 层）；AC-06 在 T03 内走 unit test
**依赖**: T03

---

### T05 — ac-verification.md + 手工 QA + 回归

**文件（新建）**:
- `features/v2.5.1/018-resource-owner-transfer/ac-verification.md` — mimic F011 格式

**逻辑**:
- AC 映射表（AC-01 ~ AC-10 + AC-08b/c/d）→ 对应测试文件/函数名 / curl 命令 / 状态
- 手工 QA 清单（spec §8）逐条勾选
- 跑全量回归：
  ```bash
  # 远程 114 服务器 via rsync → ssh
  ssh root@192.168.106.114 "cd /opt/bisheng/src/backend && \
    .venv/bin/pytest test/test_resource_type_registry.py \
                     test/test_resource_ownership_service.py \
                     test/test_resource_owner_transfer_api.py -v"
  # 全量回归
  ssh root@192.168.106.114 "cd /opt/bisheng/src/backend && .venv/bin/pytest test/ -q"
  ```

**覆盖 AC**: 全部 13 条（AC-01~10 + AC-08b/c/d）
**依赖**: T01-T04

---

## 工时预估

| Task | 预估 | 说明 |
|------|------|------|
| T01 | 0.5h | 纯常量 + 文档 |
| T02 | 1h | Registry + 5 条用例 |
| T03 | 4h | Service 核心（6 个 helper + transfer_owner + list_pending）+ 15 条单测 |
| T04 | 2.5h | DTO + 2 endpoint + 11 条集成测 |
| T05 | 1h | AC 表 + 回归 |
| **合计** | **~9h** | 1-2 人日 |

---

## 实际偏差记录

> 完成后在此记录与 spec.md 的偏差。

- 待填写
