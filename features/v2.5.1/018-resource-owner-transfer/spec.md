# Feature: F018-resource-owner-transfer (所有者交接 API)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §5.6.4.1
**优先级**: P0
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **离职员工 / 调岗员工 / 管理员**，
我希望 **将某用户在本 Tenant 下的资源所有权批量转交给其他成员**，
以便 **调岗/离职时不留孤儿资源，保障集团核心知识库的连续性**。

**背景**：PRD Review P0-C 决策"用户归属跟主部门切，数据留原处不动"。此设计下需配套所有者交接能力。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 资源原 owner | POST /tenants/{tid}/resources/transfer-owner 自己转交 | 成功；transferred_count 返回；audit_log 记录 |
| AC-02 | Child Admin | 代替下属 owner 转交 | 成功（tenant admin 权限放行） |
| AC-03 | 非 owner 非 admin | 尝试转交他人资源 | HTTP 403 错误码 `19601` |
| AC-04 | 调用者 | 指定 resource_ids=null | 自动转交 from_user 在 tenant_id 下所有可转移资源 |
| AC-05 | 调用者 | 指定 resource_ids 列表 | 仅转交列表中的资源 |
| AC-06 | 开发 | MySQL 写成功但 OpenFGA 失败 | 事务回滚；写入 failed_tuples 队列重试 |
| AC-07 | 调用者 | 单次请求 > 500 条 | HTTP 400 错误码 `19602` 提示分批 |
| AC-08 | to_user 叶子 Tenant 不在 tenant_id 可见集合内 | 拒绝 | HTTP 400 错误码 `19603`；可见集合 = `{tenant_id, tenant_id 的 Root}`（INV-T10 / PRD §5.6.3.1）|
| AC-08b | from 在 Child A、to 在 Root（同 Root 子树） | 允许 | 典型"交回总部"场景；FGA owner 元组直接转移 |
| AC-08c | from 在 Child A、to 在 Child B（同 Root 但不同 Child） | 拒绝 | to_user 叶子=Child B ∉ {Child A, Root}；返回 19603 |
| AC-08d | from 在 Root、to 在 Child（资源下沉场景） | 拒绝 | 资源 tenant_id=Root 时可见集合 = {Root}；to_user 叶子=Child ∉ 集合；返回 19603；响应体提示"Root 资源下沉 Child 请走 F011 `/tenants/{child_id}/resources/migrate-from-root` 迁移 tenant_id，再于 Child 内交接"（2026-04-21 修正：原 §3 声称支持此场景与 AC-08 规则矛盾） |
| AC-09 | 用户个人中心 | 访问 "我的资源" → "转交给..." UI | 可批量选择资源 + 接收人 |
| AC-10 | 全局超管 | 访问"待交接资源"列表 | 展示离职/超期未交接的资源清单 |

---

## 3. 边界情况

- **transfer_types 不含的资源**：忽略（比如 session / message 不支持 owner）
- **to_user 已是 owner**：幂等 skip
- **部分资源无 owner 元组**：跳过并记录（可能是 v2.4 遗留未迁移资源，记入告警）
- **不支持**：
  - 跨 Root 子树交接（即不支持把资源从一个集团转给另一个集团；本实例只有一个 Root，物理上不存在此场景）
  - 同 Root 内 Child A → Child B 直接交接（应先 Child A → Root 交回总部，再通过 F011 `/tenants/{B_id}/resources/migrate-from-root` 迁移 tenant_id 两步走；避免出现"飞地"资源）
  - **Root → Child（资源下沉）**：本 API 的 `tenant_id` 参数 = 资源所在 Tenant = Root；其可见集合 = `{Root}`，不含 Child，to_user 在 Child 会被 AC-08 规则拒绝。资源下沉场景请走 F011 `POST /api/v1/tenants/{child_id}/resources/migrate-from-root` 接口（改资源 tenant_id），再于 Child 内交接 owner（2026-04-21 修正）
  - 交接后撤回（需二次交接回去）
  - 自动调岗时转交（用户须主动发起或 Admin 代发）

**支持的交接路径**（INV-T10 / PRD §5.6.3.1）：
- 同 Tenant 内：from_user 与 to_user 都在 tenant_id（典型"同事接手"场景）✓
- Child → Root：from_user 在 Child，to_user 在 Root（典型"交回总部"场景）✓
- ~~Root → Child：资源下沉场景~~ ❌ 2026-04-21 移除；走 F011 迁移 API，不走本接口

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | 交接操作权限 | A: 仅 owner 本人 / B: 本人 + Admin 代发 | B（支持离职场景）|
| AD-02 | 批量上限 | A: 无限制 / B: 500 条 / C: 100 条 | B（权衡 FGA Write 性能） |
| AD-03 | 失败策略 | A: 整批回滚 / B: 局部成功 + 补偿 | A（避免部分交接导致的不一致）|

---

## 5. 核心服务

```python
class ResourceOwnershipService:
    SUPPORTED_TYPES = ["knowledge_space", "folder", "knowledge_file",
                       "workflow", "assistant", "tool", "channel", "dashboard"]
    MAX_BATCH = 500

    @classmethod
    async def transfer_owner(cls, tenant_id, from_user_id, to_user_id,
                              resource_types, resource_ids=None, reason="", operator=None):
        # 校验
        cls._validate_types(resource_types)
        resources = await cls._resolve_resources(tenant_id, from_user_id, resource_types, resource_ids)
        if len(resources) > cls.MAX_BATCH:
            raise BatchLimitExceeded()
        if not resources:
            return TransferResult(transferred_count=0)
        await cls._check_receiver_in_visible_set(to_user_id, tenant_id)  # 叶子 ∈ {tenant_id, tenant_id 的 Root}
        await cls._check_operator_permission(operator, from_user_id, tenant_id)

        # 事务
        async with db.atomic():
            # 1. MySQL 更新 resource.user_id
            for r in resources:
                await r.__class__.aupdate(id=r.id, user_id=to_user_id)

            # 2. OpenFGA 批量 owner 交接
            writes = [(f"user:{to_user_id}", "owner", f"{r.type}:{r.id}") for r in resources]
            deletes = [(f"user:{from_user_id}", "owner", f"{r.type}:{r.id}") for r in resources]
            try:
                await fga.batch_write(writes=writes, deletes=deletes)
            except OpenFGAError as e:
                await FailedTupleDao.abulk_create([...])
                raise

            # 3. audit_log（2026-04-21 补 operator_tenant_id；对齐 release-contract 表 1 AuditLog 字段约束）
            await AuditLogDao.acreate(
                tenant_id=tenant_id,
                operator_id=operator.user_id,
                operator_tenant_id=operator.leaf_tenant_id,  # 操作者所属叶子 Tenant；全局超管跨 Child 操作时与 tenant_id 不同
                action="resource.transfer_owner",
                target_type="resource_batch",
                target_id=str(uuid4()),
                metadata={"from": from_user_id, "to": to_user_id, "count": len(resources), "reason": reason},
            )

        return TransferResult(transferred_count=len(resources), transfer_log_id=str(uuid4()))
```

---

## 6. API 设计

```
POST /api/v1/tenants/{tenant_id}/resources/transfer-owner
Auth: 资源 owner 本人 OR tenant admin
Body: {
  "from_user_id": 123,
  "to_user_id": 456,
  "resource_types": ["knowledge_space", "workflow", ...],
  "resource_ids": null,  # 或指定列表
  "reason": "张三调岗到子公司 X"
}
Returns: {"transferred_count": 18, "transfer_log_id": "txn_..."}

GET /api/v1/tenants/{tenant_id}/resources/pending-transfer
Auth: 全局超管 / Child admin
Returns: {"list": [{"user_id": 123, "user_name": "...", "resource_count": 8, "relocated_at": "..."}]}
```

---

## 7. 依赖

- F011-tenant-tree-model（Tenant 模型 + **`POST /api/v1/tenants/{child_id}/resources/migrate-from-root`** 资源下沉端点，INV-T10）；本 feature **不**实现 Root→Child 下沉逻辑，AC-08d 命中场景需引导调用方走 F011 迁移 API
- F013-tenant-fga-tree（FGA batch_write 能力）
- v2.5.0/F004-rebac-core（FailedTuple 补偿）

---

## 8. 手工 QA 清单

- [ ] owner 本人发起交接成功
- [ ] Admin 代发交接成功
- [ ] 无权限调用拒绝 403
- [ ] 批量 501 条请求拒绝
- [ ] to_user 非 Tenant 成员拒绝
- [ ] MySQL 成功 OpenFGA 失败时整批回滚 + failed_tuples 记录
- [ ] audit_log 完整
- [ ] 个人中心 UI "我的资源 → 转交给..." 可用
- [ ] 超管"待交接"清单展示调岗 > N 天未交接用户
- [ ] **`user_tenant_sync.enforce_transfer_before_relocate=true` 开关验证**：开启后用户名下有资源时主部门变更被 F012 阻断（返 409+19101）；关闭时允许变更但发告警 + audit_log `user.tenant_relocated`；触发本 feature 交接 API 清空资源后再尝试变更应通过

---

## 9. 错误码

- **MMM=196** (resource_owner_transfer)
- 19601: 无权限转交（非 owner 且非 admin）
- 19602: 超过批量上限（500 条）
- 19603: 接收人叶子 Tenant 不在资源 tenant_id 的可见集合内（即 ∉ {tenant_id, tenant_id 的 Root}；INV-T10）
- 19604: 资源类型不支持交接
- 19605: MySQL/OpenFGA 事务失败已回滚
- 19606: from_user_id 等于 to_user_id
