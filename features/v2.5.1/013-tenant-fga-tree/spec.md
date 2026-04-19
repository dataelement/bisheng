# Feature: F013-tenant-fga-tree (OpenFGA 升级 + 权限链路)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §3
**优先级**: P0
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团 IT / 全局超管**，
我希望 **OpenFGA authorization model 原生支持 Tenant 树的两层管理员模型与集团共享资源**，
以便 **权限检查链路在树形拓扑下仍保持 <10ms 延迟**。

核心变更：
- OpenFGA DSL 新增 `type tenant`（`admin` / `member` / `shared_to` 关系；2026-04-20 简化：**不保留 `parent` 关系**——FGA 中冗余，父子完全依赖 MySQL `parent_tenant_id` 字段）
- **`tenant.admin` 不沿 parent 继承**（两层管理员模型，PRD Review P2-G）
- **Root Tenant 不写 `tenant#admin` 元组**（Root 管理由 `system:global#super_admin` 承担）
- 所有资源类型的 `viewer` 关系仅补 `tenant#shared_to#member`（显式共享分发）；manager/editor 不补 `tenant#` 任何关系（2026-04-21 收窄：资源授权回归 owner + user + department#member + user_group#member 四源；Tenant 不参与资源级授权）
- `PermissionService.check()` 五级短路更新：② IN 列表归属、③ 仅 Child admin（不继承）

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 开发 | 部署新 authorization model | OpenFGA store 接受新 DSL；model_id 版本号递增 |
| AC-02 | 全局超管 | 请求 Child Tenant 内资源 | ① 全局超管短路 → True；不走 tenant.admin FGA check |
| AC-03 | Child Admin | 请求本 Child Tenant 资源 | ③ Child tenant admin 命中 → True |
| AC-04 | Child Admin | 请求其他 Child Tenant 资源 | ② IN 列表拒绝（归属校验失败） |
| AC-05 | 开发 | 验证 FGA check(user, admin, tenant:root_id) for normal user | 结果 False（不继承） |
| AC-06 | 开发 | 验证 FGA check(user, admin, tenant:1) for 全局超管 | 结果 False（**Root 不写 tenant#admin 元组**；全局超管仅通过 `system:global#super_admin` 授权） |
| AC-11 | 开发 | 启用本 feature 后，挂载 Child 流程 | 仅写 `tenant:{child}#admin → user:{initial_admin}` + `tenant:{child}#member`；不写 Root 的 tenant#admin |
| AC-07 | 业务用户 | 访问 Root 共享资源 | ④ ReBAC 通过 `tenant#shared_to#member` 分发 → True |
| AC-08 | 业务用户 | 访问 Root 非共享资源 | ② IN 列表命中 Root（用户祖先含 Root）→ ④ ReBAC 判断 |
| AC-09 | 开发 | 升级灰度期旧 authorization model 读写 | 旧 `tenant:{id}#admin` 元组可读作审计；不参与运行时 check |
| AC-10 | 性能 | 单次 PermissionService.check 延迟 | P99 < 10ms（缓存命中）/ P99 < 50ms（未命中） |
| AC-12 | 普通 Tenant 成员 | 请求本 Tenant **他人创建**的资源（无 owner/显式 department/user_group 授权） | ReBAC 检查拒绝返回 False；**SQL IN 列表仅过滤元数据可见性，不代表可读资源内容**；2026-04-21 DSL 收窄后 `tenant#member` 不再出现在资源 viewer 中 |
| AC-13 | 开发 | 后端 `POST /tenants/1/admins` 请求 或 代码路径直接调 `fga.write_tuple(user=..., relation='admin', object='tenant:1')` | 拒绝：前者 HTTP 403 + 错误码 19204；后者由 `TenantAdminService` 入口守卫抛出 `RootTenantAdminNotAllowed` 异常（错误码 19204）。Root 管理权由 `system:global#super_admin` 授予 |

---

## 3. 边界情况

- **旧 model 兼容期**：发版后 2 周内同时部署新旧 model；`PermissionService` 默认走新 model，配置 `openfga.model_id` 可切换回滚
- **OpenFGA 连接失败**：熔断 5s 内直接放行（可配置） OR 返回 503；二选一由 SRE 决定
- **升级期双写**：新旧 model 各自维护 tenant 元组，避免升级中途请求失败
- **不支持**：
  - 多层 Tenant 树（>2 层，MVP 限制）
  - 跨 Root 共享（仅私有化单 Root，2026-04-20 收窄）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | tenant.admin 继承 | A: `or admin from parent` / B: 仅 direct | **选 B** | 两层管理员模型；全局超管用 ① 短路（PRD Review P2-G）；2026-04-21 补充：同时在 DSL 资源 manager/editor/viewer 中移除 `tenant#member`——避免"同一 Tenant 成员默认可编辑/读所有资源"的隐式越权；资源授权回归 4 源（owner + user + department#member + user_group#member），Tenant 仅作配额/存储/归属边界 |
| AD-02 | 归属校验方式 | A: 严格相等 / B: IN 列表（leaf + Root + shared_to） | 选 B | 覆盖叶子 + Root + shared_to |
| AD-03 | 全局超管授权位置 | A: `tenant:1#admin` / B: `system:global#super_admin` 单点 | 选 B | 仅私有化单实例，全局超管在 system 层授予即可，无需 tenant 层（Root 不写 tenant#admin） |
| AD-04 | DSL 升级灰度 | A: 一次切换 / B: 新旧并行 2 周 | 选 B | 避免权限中断（业务热路径）|
| AD-05 | tenant#parent 关系 | A: 保留 / B: 删除 | 选 B | FGA 中冗余（admin 不继承、member 不继承、shared_to 直接写元组）；父子完全依赖 MySQL `parent_tenant_id` 字段（2026-04-20 收窄） |

---

## 5. OpenFGA DSL 完整定义

```yaml
model
  schema 1.1

type user

type system
  relations
    define super_admin: [user]

type tenant
  relations
    define admin: [user]              # 仅 Child Tenant 写元组；不沿 parent 继承；Root 不写
    define member: [user]
    define shared_to: [tenant]
    # 2026-04-20 简化：删除 `parent: [tenant]` 关系（FGA 中冗余，依赖 MySQL parent_tenant_id 字段）

type department
  relations
    define parent: [department]
    define admin: [user] or admin from parent       # 部门 admin 仍向下传递
    define member: [user]

type user_group
  relations
    define admin: [user]
    define member: [user]

type knowledge_space
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor:  [user, department#member, user_group#member] or manager
    define viewer:  [user, department#member, user_group#member, tenant#shared_to#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer

# (folder / knowledge_file / channel / workflow / assistant / tool / dashboard 同 knowledge_space 模式)

type llm_server
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor:  [user, department#member, user_group#member] or manager
    define viewer:  [user, department#member, user_group#member, tenant#shared_to#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer

type llm_model
  relations
    define owner: [user]
    define manager: [user, department#member, user_group#member] or owner
    define editor:  [user, department#member, user_group#member] or manager
    define viewer:  [user, department#member, user_group#member, tenant#shared_to#member] or editor
    define can_manage: manager
    define can_edit: editor
    define can_read: viewer

# 【2026-04-21 Review 收窄】资源 manager/editor/viewer 移除 `tenant#member`；viewer 仅保留 `tenant#shared_to#member`（显式共享）。
# 原则：Tenant 不进资源授权，回归 owner + user + department#member + user_group#member 四源。
# Tenant 在 FGA 中的 3 个用途：① admin（Child Admin 短路，② 级）/ ② member（归属反查，不进资源授权）/ ③ shared_to（Root 显式共享给 Child）。
# 【2026-04-19 补 llm_server / llm_model 类型】F020 LLM 多租户依赖此 DSL 类型写入 `{llm_server:id}#viewer → tenant:{root}#shared_to#member`
# 元组实现 Root 共享；若类型缺失则 F020 FGA 写 tuple 返回 "unknown object type" 错误。
# 注：Child Admin 对 Root 共享 llm_server 的 **写保护**（19801）由 F020 应用层检查承担，不进 DSL
# （FGA editor 关系允许 editor 链路在极端场景被间接触发，但 F020 DAO 层的显式 is_global_super 校验会率先拒绝）。
```

---

## 6. PermissionService.check 五级短路

```python
async def check(self, user_id, resource_tenant_id, resource_type, resource_id, action):
    # ① 全局超管
    if await self._is_super_admin(user_id):
        return True

    # ② Tenant 归属 IN 列表
    visible = self.get_visible_tenants(user_id)  # 含叶子 + 祖先
    if resource_tenant_id not in visible:
        if not await self._is_shared_to(user_id, resource_tenant_id):
            return False

    # ③ Child tenant admin（不继承；2026-04-20：用 parent_tenant_id 判定 Child）
    tenant = await TenantDao.aget(resource_tenant_id)
    if tenant.parent_tenant_id is not None:  # 仅 Child 级触发；Root 跳过（Root 资源依赖 ① 全局超管短路）
        if await fga.check(f"user:{user_id}", "admin", f"tenant:{resource_tenant_id}"):
            return True

    # ④ ReBAC
    return await fga.check(f"user:{user_id}", action, f"{resource_type}:{resource_id}")
    # ⑤ RBAC 菜单/配额 — 由 API 层调用方处理


async def _is_shared_to(self, user_id: int, target_tenant_id: int) -> bool:
    """检查 user 是否位于 target_tenant#shared_to#member 下（Root→Child 显式共享场景）。

    仅当 ② 阶段资源 tenant_id 不在用户可见集合时调用；用于判断"Root 共享给本 Child 的资源"
    是否对当前用户可达。依赖 F017 在挂载 Child 时写入的 `tenant:{root}#shared_to → tenant:{child}`
    元组，以及资源创建时写入的 `{resource}#viewer → tenant:{root}#shared_to#member` 元组。
    """
    return await fga.check(
        f"user:{user_id}",
        "member",
        f"tenant:{target_tenant_id}#shared_to",
    )
```

---

## 7. 依赖

### 7.1 前置依赖

| 依赖 | 原因 |
|------|------|
| F011-tenant-tree-model | Tenant 表字段 + 挂载关系 |
| F012-tenant-resolver | 叶子 Tenant 派生（叶子 + Root 即 IN 列表） |
| v2.5.0/F004-rebac-core | OpenFGA 客户端 + PermissionService 基础 |

### 7.2 本 Feature 阻塞

- F016-tenant-quota-hierarchy（共享资源计数规则）
- F017-tenant-shared-storage（`shared_to` 关系使用）

---

## 8. 改造文件清单

| 文件 | 改造点 |
|------|--------|
| `src/backend/bisheng/core/openfga/authorization_model.yaml` | 新增 tenant 类型（admin / member / shared_to 三关系）；资源类型 viewer 补 `tenant#shared_to#member`（manager/editor 不补 tenant# 任何关系；2026-04-21 收窄） |
| `src/backend/bisheng/core/openfga/client.py` | 升级 SDK 到 v1.8+；支持 model_id 显式指定 |
| `src/backend/bisheng/permission/domain/services/permission_service.py` | check 方法重写五级短路 ② ③ |
| `src/backend/bisheng/permission/domain/services/tenant_admin_service.py` | 新增：Child admin 管理（增删改查） |
| `src/backend/bisheng/common/dependencies/user_deps.py` | UserPayload 新增 `get_visible_tenants()` / `has_tenant_admin()` |
| `src/backend/bisheng/core/config/settings.py` | 新增 `openfga.model_id` / `openfga.dual_model_mode` |

---

## 9. 手工 QA 清单

### 9.1 DSL 升级

- [ ] 部署新 model 到 OpenFGA store
- [ ] 用 CLI 验证 authorization model：`fga model get --store-id=... --model-id=...`
- [ ] 旧 model 仍可读（灰度期兼容）

### 9.2 两层管理员行为

- [ ] 全局超管访问 Child 资源：① 短路 True
- [ ] Child Admin 访问本 Child：③ True
- [ ] Child Admin 访问其他 Child：② 拒绝
- [ ] 普通用户不通过 tenant.admin FGA 意外命中（不继承）

### 9.3 归属 IN 列表

- [ ] Child 用户可见 Root 共享资源
- [ ] Child 用户不可见 Root 未共享资源
- [ ] Child A 用户不可见 Child B 资源（仅私有化单 Root 内 Child 间隔离；跨 Child 严格不可见，除非通过 Root shared_to 分发）

### 9.4 性能

- [ ] 10 万元组量级下单次 check P99 < 10ms
- [ ] 并发 1000 QPS 下无超时

### 9.5 灰度

- [ ] 双 model 模式下切到新 model
- [ ] 回滚到旧 model 无数据丢失
- [ ] 灰度期间新 tenant 元组同时写入两 model

---

## 10. 错误码

- **MMM=192** (tenant_fga)
- 19201: OpenFGA 连接失败
- 19202: authorization model 不存在
- 19203: 元组写入补偿失败
- 19204: Tenant admin 授权冲突（授予对象非 Child Tenant）

---

## 11. 不在本 Feature 范围

- tenant 表数据模型 → F011
- JWT / 叶子派生 → F012
- 配额检查 → F016
- shared_to 元组写入时机 → F017
- 所有者交接 → F018
