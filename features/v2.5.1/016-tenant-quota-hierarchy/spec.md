# Feature: F016-tenant-quota-hierarchy (配额沿树取严 + MVP 手工调整)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §6
**优先级**: P1
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团 IT**，
我希望 **每个 Tenant（Root 或 Child）独立设置配额，检查时叶子 + Root 双层取最严，且 Root 用量 = 自身 + 所有 Child 累计；全局超管在管理页直接手工调整配额**，
以便 **集团 Root 可设硬上限作为集团总量天花板，子公司 Child 在其分配内自治**。

> 2026-04-18 PRD Review 决策（P1-E）：**MVP 仅基础 CRUD**；转移/计费/分摊全推 v2.6+（附录 G.1）。
>
> 2026-04-20 收窄修订：MVP 锁 2 层 → "沿祖先取严"简化为"叶子 + Root 双层取严"；明确 Root 用量聚合算法 = Root 自身 + Σ 所有 Child 累计（INV-T9）。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 用户 | 创建资源（知识库等） | 检查叶子 Tenant 配额 + Root 配额（若叶子是 Child）；任一超限则拒绝 |
| AC-02 | 用户 | 创建 Root 共享资源（Child 不计用量） | 仅计入 Root 自身；Child quota_config.knowledge_space 不受影响（INV-T6） |
| AC-03 | 全局超管 | PUT /tenants/{id}/quota | 直接写 quota_config JSON；无转移语义 |
| AC-04 | 用户 | 存储达 100% | 上传新文件 HTTP 413；前端提示扩容 |
| AC-05 | 用户 | 删除文件释放存储 | 配额恢复；可继续上传 |
| AC-06 | 集团 IT | 查询本 Root 与各 Child 用量 | 返回树形结构每节点的 used/limit/utilization |
| AC-07 | 系统 | Root 用量聚合（INV-T9） | Root 用量 = Root 自身 strict 计数 + Σ 所有 Child strict 计数；场景：Child A=30G、Child B=50G、Root 自身=20G → Root 总用量=100G |
| AC-08 | 系统 | Root 配额触发 Child 阻断 | Root 用量达 Root 配额时，所有 Child 的创建类操作也被阻断（HTTP 413 + 提示 "集团总量已耗尽"） |
| AC-09 | 开发 | `get_tenant_resource_count` 调用 | 必须用 `with strict_tenant_filter():` 包裹（PRD §4.1）；避免 IN 列表叠加把 Root 共享资源算进 Child 用量 |
| AC-10 | 用户 | Child 用户读 Root 共享资源衍生数据（对话/token） | 衍生数据归属 Child 叶子 Tenant，计入 Child `model_tokens_monthly` 配额（INV-T13）。**具体写入层实现依赖 F017 §5.4（ChatMessageService / LLMTokenTracker 用 `get_current_tenant_id()` 赋值 tenant_id）**；本 feature 仅负责 `strict_tenant_filter()` 配额计数 |

---

## 3. 边界情况

- **并发创建**：允许轻微超额（不加分布式锁）
- **配额 = -1**：表示无限制
- **Tenant 禁用期间**：配额不计数
- **不支持**：
  - 配额转移（v2.6+ 附录 G.1）
  - 计费系统对接（v2.6+）
  - 多级告警阈值（80%/90%）（v2.6+）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | 取严算法 | A: 运行时遍历 / B: 物化视图 | A（2 层下检查链路 = [leaf, Root] 固定 2 步，O(1) 无性能问题）|
| AD-02 | 共享资源计数 | A: 计入 Root+Child / B: 仅 Root | B（PRD §6.3 / INV-T6） |
| AD-03 | Root 用量聚合 | A: 仅 Root 自身 / B: Root 自身 + Σ Child / C: max(Root, any Child) | B（INV-T9 / PRD §6.3）；Root 配额作为集团硬盖，Child 之间在配额内竞争 |
| AD-04 | 计数过滤上下文 | A: 默认 IN 列表 / B: strict_tenant_filter 精确匹配 | B（避免 IN 列表把 Root 共享资源叠加算进 Child；PRD §4.1）|

---

## 5. 配额检查逻辑

```python
class QuotaChecker:
    @classmethod
    async def check(cls, user_id: int, resource_type: str) -> bool:
        ut = await UserTenantDao.aget_active(user_id)
        leaf_tenant = await TenantDao.aget(ut.tenant_id)

        # 2 层下检查链固定为 [leaf] 或 [leaf, Root]
        tenants_to_check = [leaf_tenant]
        if leaf_tenant.parent_tenant_id is not None:
            root = await TenantDao.aget(leaf_tenant.parent_tenant_id)  # MVP 下永远 = id 1
            tenants_to_check.append(root)

        for t in tenants_to_check:
            limit = (t.quota_config or {}).get(resource_type, -1)
            if limit == -1:
                continue
            # 用量计算：
            #   - Child 用量：strict_tenant_filter 精确匹配（避免 IN 列表把 Root 共享叠加进来）
            #   - Root 用量：自身 + Σ 所有 Child 累计（INV-T9）
            if t.parent_tenant_id is None:  # Root
                used = await cls._aggregate_root_usage(t.id, resource_type)
            else:  # Child
                used = await cls._count_usage_strict(t.id, resource_type)
            if used >= limit:
                raise QuotaExceeded(tenant_id=t.id, resource_type=resource_type, used=used, limit=limit)

        # 角色级配额
        role_quota = await RoleQuotaService.get(user_id, resource_type)
        if role_quota > 0 and await cls._count_user_resources(user_id, resource_type) >= role_quota:
            raise RoleQuotaExceeded(user_id, resource_type, role_quota)

        return True

    @classmethod
    async def _count_usage_strict(cls, tenant_id: int, resource_type: str) -> int:
        """单 Tenant 严格匹配计数（用 strict_tenant_filter 避免 IN 列表叠加）"""
        with strict_tenant_filter():  # PRD §4.1 ContextVar
            return await ResourceDao.acount(tenant_id=tenant_id, resource_type=resource_type)

    @classmethod
    async def _aggregate_root_usage(cls, root_id: int, resource_type: str) -> int:
        """Root 用量 = Root 自身 + Σ 所有 active Child 累计（INV-T9）

        注意：仅 `status='active'` 的 Child 计入；`disabled / archived / orphaned` 状态的
        Child 用量不计（避免"归档后仍占 Root 配额"的歧义）。该行为与 F011 Tenant 生命周期
        对齐：禁用/归档/孤儿 Tenant 禁止创建新资源，配额语义上视为"已退出统计"。
        """
        root_self = await cls._count_usage_strict(root_id, resource_type)
        child_ids = await TenantDao.aget_children_ids_active(root_id)  # 依赖 F011 新增方法
        child_total = sum([await cls._count_usage_strict(cid, resource_type) for cid in child_ids])
        return root_self + child_total
```

---

## 6. 依赖

- F011-tenant-tree-model（Tenant 树字段；新增 `TenantDao.aget_children_ids_active(root_id)` 方法用于 Root 聚合）
- F012-tenant-resolver（`strict_tenant_filter()` context manager 实现；本 feature 所有配额计数调用必须 `with strict_tenant_filter():` 包裹以避免 IN 列表把 Root 共享资源叠加进 Child 用量）
- F013-tenant-fga-tree（tenant#shared_to 语义）
- F017-tenant-shared-storage（§5.4 衍生数据写入层：`ChatMessageService` / `LLMTokenTracker` 用 `get_current_tenant_id()` 赋值 tenant_id，使本 feature 的 Child `model_tokens_monthly` 计数天然命中 Child 叶子；本 feature 仅负责读取统计）
- v2.5.0/F005-role-menu-quota（role.quota_config）

---

## 7. 手工 QA 清单

- [ ] 单 Tenant 内配额 100% 阻断
- [ ] Root 硬限 < Child 配额时，Root 限触发
- [ ] 共享资源仅计入 Root（Child 用量不被叠加）
- [ ] **Root 用量聚合**：Child A=30G + Child B=50G + Root 自身=20G → Root 用量=100G
- [ ] **Root 满触发 Child 阻断**：Root 配额=100G，已用 100G 时，Child 创建新文件返回 413
- [ ] **strict_tenant_filter 验证**：Root 创建共享资源后，Child 用量 SQL 不包含此资源（IN 列表场景下也不算）
- [ ] **衍生数据归属**：Child 用户调 Root 共享 LLM 模型，token 计入 Child `model_tokens_monthly`，不算 Root
- [ ] 全局超管手工调整 quota_config 立即生效
- [ ] 删除资源释放配额
- [ ] -1 配额无限制

---

## 8. 错误码

- **MMM=194** (tenant_quota)
- 19401: Tenant 配额超限
- 19402: 角色配额超限
- 19403: 存储超限
