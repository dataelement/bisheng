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
| AC-03 | 全局超管 | `PUT /api/v1/tenants/{id}/quota` | 直接写 `quota_config` JSON；无转移语义；响应 `UnifiedResponseModel`（HTTP 200 + `status_code=0`）；详见 §9 |
| AC-04 | 用户 | 存储达 100% | 上传新文件阻断，HTTP 200 + `status_code=19403`（`TenantStorageQuotaExceededError`）；前端识别该业务码展示扩容提示（与项目 `UnifiedResponseModel` 规范一致，非 HTTP 413） |
| AC-05 | 用户 | 删除文件释放存储 | 配额恢复；可继续上传 |
| AC-06 | 集团 IT | `GET /api/v1/tenants/quota/tree` | 返回 `TenantQuotaTreeResponse`（`{root: TenantQuotaTreeNode, children: TenantQuotaTreeNode[]}`），每节点 `usage` 列所有配额键的 `used/limit/utilization`；详见 §9 |
| AC-07 | 系统 | Root 用量聚合（INV-T9） | Root 用量 = Root 自身 strict 计数 + Σ 所有 Child strict 计数；场景：Child A=30G、Child B=50G、Root 自身=20G → Root 总用量=100G |
| AC-08 | 系统 | Root 配额触发 Child 阻断 | Root 用量达 Root 配额时，所有 Child 的创建类操作被阻断：HTTP 200 + `status_code=19401` + `status_message` 含 "集团总量已耗尽"（`TenantQuotaExceededError` 在聚合节点是 Root 时的 msg 变体） |
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

> **实现映射**：下列 `QuotaChecker` 为算法示意；实际落地合并入已有的 `QuotaService`（`src/backend/bisheng/role/domain/services/quota_service.py`），通过重写 `_apply_tenant_cap → _apply_tenant_chain_cap` 并新增 `_count_usage_strict` / `_aggregate_root_usage` 两个 classmethod 实现同等效果，保持 `@require_quota` 装饰器与 `check_quota` 签名不变。

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

## 7. 自测清单（对应 AC）

> 开发者在完成实现后必须自行运行以下测试；不依赖用户/产品人肉点击。

| Test | AC | 类型 | 备注 |
|------|----|------|------|
| `test_single_tenant_quota_blocks_at_100pct` | AC-01 | pytest 集成测试 | 单 Tenant 内配额 100% 阻断 |
| `test_root_hard_limit_triggers_before_child_quota` | AC-08 | pytest 集成测试 | Root 硬限先于 Child 自身配额触发 |
| `test_shared_resource_only_counts_to_root` | AC-02, AC-09 | pytest 集成测试 | 共享资源仅计 Root；Child 用量不叠加（依赖 `strict_tenant_filter`） |
| `test_root_usage_aggregates_all_children` | AC-07 | pytest 集成测试 | Child A=30G + Child B=50G + Root 自身=20G → Root 用量=100G |
| `test_child_blocked_when_root_quota_exhausted` | AC-08 | pytest 集成测试 | Root 满时 Child 创建返回 19401，msg 含"集团总量已耗尽" |
| `test_strict_tenant_filter_excludes_shared_from_child_in_list` | AC-09 | pytest 单元测试 | IN 列表场景下共享资源不算进 Child |
| `test_derived_token_attributed_to_child_leaf` | AC-10 | pytest 集成测试 | Child 用户调 Root 共享 LLM，token 计入 Child `model_tokens_monthly`；依赖 F017 §5.4 |
| `test_super_admin_quota_update_takes_effect_immediately` | AC-03 | pytest 集成测试 | `PUT /tenants/{id}/quota` 无缓存延迟 |
| `test_storage_quota_exceeded_returns_19403` | AC-04 | pytest 集成测试 | HTTP 200 + status_code=19403（TenantStorageQuotaExceededError） |
| `test_resource_deletion_releases_quota` | AC-05 | pytest 单元测试 | 删除后配额恢复，可继续创建 |
| `test_quota_tree_api_returns_root_and_children` | AC-06 | pytest 集成测试 | `GET /tenants/quota/tree` 返回结构正确 |
| `test_neg_one_means_unlimited` | AC-01 | pytest 单元测试 | quota=-1 跳过阻断 |

---

## 8. 错误码

**MMM=194** (tenant_quota)，所有类继承 `BaseErrorCode`，沿项目规范走 `UnifiedResponseModel`（HTTP 200 + `status_code=19xxx`）。

| Code | 类名 | 含义 | 关联 AC |
|------|------|------|---------|
| 19401 | `TenantQuotaExceededError` | 叶子 Tenant 或 Root 硬盖触发的 Tenant 级配额超限 | AC-01, AC-07, AC-08 |
| 19402 | `TenantRoleQuotaExceededError` | 角色级配额超限（在 Tenant 检查通过后） | AC-01 |
| 19403 | `TenantStorageQuotaExceededError` | 存储配额（`storage_gb` / `knowledge_space_file`）超限 | AC-04 |

**兼容说明**：v2.5.0 `QuotaExceededError(24001)` 作为旧基类保留不删，继承链不断；新增 5 个资源创建端点的报错行为通过 `QuotaService.check_quota` 内部切换到 194xx 子类。

---

## 9. API 契约

所有端点走 `UnifiedResponseModel`（HTTP 200 + 业务码）。

### 9.1 `PUT /api/v1/tenants/{id}/quota`（AC-03）

**权限**：`UserPayload.get_admin_user`（仅全局超管）

**现状**：v2.5.1 F010 已实现此端点（`src/backend/bisheng/tenant/api/endpoints/tenant_crud.py:141`）；F016 **不改路径/签名**，仅扩展 `QuotaService.validate_quota_config` 校验的合法 key 集合（新增 `storage_gb / user_count / model_tokens_monthly`）。

请求体（`TenantQuotaUpdate`）：
```json
{
  "quota_config": {
    "knowledge_space": 50,
    "storage_gb": 100,
    "model_tokens_monthly": 10000000,
    "workflow": -1
  }
}
```

响应（`UnifiedResponseModel[TenantDetailResponse]`）：
```json
{
  "status_code": 0,
  "status_message": "success",
  "data": {
    "id": 5,
    "tenant_name": "...",
    "quota_config": { ... }
  }
}
```

错误：`QuotaConfigInvalidError(24005)`（非法 key / 非整数 / 小于 -1）；`TenantNotFoundError`；Root 修改保护由 F011 承接。

### 9.2 `GET /api/v1/tenants/quota/tree`（AC-06，F016 新增）

**权限**：`UserPayload.get_admin_user`（仅全局超管）

**路径**：`GET /api/v1/tenants/quota/tree`（无 `{id}`，语义为"本实例整棵 Tenant 树"；MVP 锁 2 层，`children` 至多几十项）

请求参数：无

响应（`UnifiedResponseModel[TenantQuotaTreeResponse]`）：
```json
{
  "status_code": 0,
  "status_message": "success",
  "data": {
    "root": {
      "tenant_id": 1,
      "tenant_name": "集团总部",
      "parent_tenant_id": null,
      "quota_config": {"knowledge_space": 100, "storage_gb": 500, ...},
      "usage": [
        {"resource_type": "knowledge_space", "used": 100, "limit": 100, "utilization": 1.0},
        {"resource_type": "storage_gb", "used": 320, "limit": 500, "utilization": 0.64}
      ]
    },
    "children": [
      {
        "tenant_id": 5,
        "tenant_name": "子公司 A",
        "parent_tenant_id": 1,
        "quota_config": {"knowledge_space": 30, ...},
        "usage": [ ... ]
      }
    ]
  }
}
```

**语义约定**：
- `root.usage[*].used` = `QuotaService._aggregate_root_usage`（Root 自身 + Σ active Child 累计，INV-T9）
- `children[*].usage[*].used` = `QuotaService._count_usage_strict`（`with strict_tenant_filter():` 精确匹配，避免 IN 列表把 Root 共享叠加进 Child）
- `utilization = used / limit`，当 `limit = -1` 时 `utilization = 0.0` 且前端显示"无限制"
- Child Admin 仍读自己 Child 用 `GET /api/v1/tenants/{id}/quota`（现有端点，F010）；本端点**不对 Child Admin 开放**，避免 Child 看见兄弟 Child 用量

### 9.3 DTO 定义（新增于 `tenant/domain/schemas/tenant_schema.py`）

```python
class TenantQuotaUsageItem(BaseModel):
    resource_type: str
    used: int
    limit: int  # -1 = 无限制
    utilization: float  # 0.0 ~ 1.0+（可超 1.0 表示已超额）

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
