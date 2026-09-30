# Feature: 知识库置顶偏好统一

**Feature ID**: `053-knowledge-space-pin-unification`  
**Status**: Implemented（环境验证待完成）  
**Mode**: Spec Then Implement  
**Created**: 2026-07-14  
**Updated**: 2026-07-14  
**关联 PRD**: 首钢门户知识库列表置顶需求  
**优先级**: P1  
**所属版本**: v2.6.0

---

## 1. 概述与用户故事

作为 **门户知识库用户**，
我希望 **可以分别置顶公共、部门、团队知识库，并在所有知识库列表中得到一致结果**，
以便 **快速访问常用知识库，且置顶偏好不再依赖是否订阅或是否存在成员关系**。

作为 **个人知识库用户**，
我希望 **个人知识库不提供置顶操作**，
以便 **个人知识库继续按照“我的收藏优先、默认个人库随后”的固定顺序展示，避免产生无意义的个人排序状态**。

### 1.1 当前问题

- 知识库置顶当前写入 `space_channel_member.is_pinned`，只有存在 ACTIVE SPACE 成员关系时才能真正更新。
- 公共知识库列表没有输出当前用户的置顶状态，未订阅公共库无法置顶。
- 门户内嵌工作台和普通知识库侧边栏都向个人知识库展示置顶操作。
- 前端仅在当前分组内校验“最多置顶 5 个”，后端没有权威限制。
- grouped 列表缓存完整的 `is_pinned` 响应，置顶结果可能在 15 秒 TTL 内陈旧。

### 1.2 目标

- 将所有**支持置顶的知识库类型**统一使用 `user_link` 作为唯一事实源。
- 公共、部门、团队知识库支持按用户置顶，每个分类最多 5 个。
- 个人知识库不支持置顶，前端不显示操作，后端拒绝直接调用。
- 所有知识库列表以相同方式输出 `is_pinned` 并稳定地将置顶项排在前面。
- 保持频道置顶、知识库订阅、权限关系和现有 API 地址兼容。

### 1.3 非目标

- 不提供置顶项拖拽排序或自定义 `sort_order`。
- 不改变知识库订阅、成员角色、审批或 OpenFGA 授权语义。
- 不把置顶操作视为授权；置顶不得扩大资源可见范围。
- 不将频道置顶迁移到 `user_link`。
- 不新增或改造知识库级别切换能力；当前产品没有级别切换入口。
- 不修改首钢门户 iframe 宿主页面；用户可见改动位于被嵌入的 BiSheng Client 页面。

---

## 2. 需求 Requirements

| ID | 需求 |
|----|------|
| REQ-001 | 公共、部门、团队知识库的用户置顶偏好必须统一存储为 `user_link(type='knowledge_space_pin', type_detail=str(space_id))`。 |
| REQ-002 | 个人知识库不支持置顶：列表始终返回 `is_pinned=false`，前端不展示置顶操作，后端拒绝置顶请求。 |
| REQ-003 | 每个用户在公共、部门、团队三个分类中，当前可见置顶分别不得超过 5 个，后端为权威校验方。 |
| REQ-004 | 列表必须先完成权限过滤和基础排序，再叠加用户置顶状态；置顶项排在非置顶项前，组内保持调用方请求的原始排序。 |
| REQ-005 | 历史有效知识库置顶记录必须迁移到 `user_link`，迁移后知识库不再读写 `business_type=SPACE` 的 `space_channel_member.is_pinned`。 |
| REQ-006 | `space_channel_member.is_pinned` 必须保留给频道置顶使用，频道现有行为不得变化。 |
| REQ-007 | 知识库删除时必须清理对应的 `knowledge_space_pin`；普通权限暂时丢失时保留偏好但不展示，个人库残留记录始终忽略。 |
| REQ-008 | 现有 `POST /api/v1/knowledge/space/{space_id}/set-pin` 地址和请求字段 `is_pined` 必须保持兼容。 |
| REQ-009 | `user_link` 置顶写入必须幂等，并保证同一 `(user_id, type, type_detail)` 最多一条记录。 |

---

## 3. 验收标准 Acceptance Criteria

| ID | 关联需求 | 场景 | 预期结果 | Verification Method |
|----|----------|------|----------|---------------------|
| AC-01 | REQ-001, REQ-004 | 用户置顶一个当前可见但未订阅的公共知识库 | API 成功；重新获取公共库列表时该库 `is_pinned=true` 且位于非置顶项之前 | 后端 Service/API 自动化测试 + Client 列表测试 |
| AC-02 | REQ-001, REQ-004 | 用户分别置顶部门和团队知识库 | 两类列表均从 `user_link` 返回正确置顶状态和顺序，不依赖成员记录中的 `is_pinned` | 后端单元测试 |
| AC-03 | REQ-003, REQ-009 | 用户在同一分类已有 5 个有效置顶后再次置顶 | 后端拒绝新增并返回明确业务错误；已有 5 条记录不变 | 后端并发/顺序写入测试 + API 测试 |
| AC-04 | REQ-002 | 用户打开门户内嵌工作台或普通知识库侧边栏中的个人知识库菜单 | 普通个人库和“我的收藏”均不展示“置顶空间/取消置顶” | 两个 React 组件测试 |
| AC-05 | REQ-002, REQ-008 | 客户端直接请求置顶个人知识库 | 后端返回 `SpacePersonalPinForbiddenError`，个人列表仍为 `is_pinned=false` | 后端 Service/API 测试 |
| AC-06 | REQ-003, REQ-007 | 用户失去部门或团队知识库查看权限 | 该库不出现在列表中且不计入当前可见分类上限；恢复权限后原置顶偏好恢复 | 后端 Service 测试 |
| AC-07 | REQ-005, REQ-009 | 数据库中存在历史 SPACE 成员置顶及重复 `user_link` | 迁移保留每组三元组的最新记录，回填非个人历史置顶，并成功建立唯一约束 | MySQL 迁移测试 + DM8 CI 验证 |
| AC-08 | REQ-006 | 用户置顶或取消置顶频道 | 频道仍通过 `space_channel_member.is_pinned` 工作，列表排序和 API 行为不变 | 频道回归测试 |
| AC-09 | REQ-007 | 删除知识库 | 对应 `knowledge_space_pin` 全部清理；其他类型 `user_link` 不受影响；个人库残留记录不进入响应 | 后端 Service 测试 |
| AC-10 | REQ-004 | grouped 列表已命中 Redis 缓存后，用户置顶或取消置顶 | 下一次列表响应立即反映最新置顶状态，不等待 15 秒 TTL | 缓存单元测试 |
| AC-11 | REQ-008 | 旧版前端继续提交 `{ "is_pined": true }` | API 契约保持可用，无需同步升级门户宿主项目 | API 集成测试 |
| AC-12 | REQ-009 | 对同一知识库重复置顶或重复取消置顶 | 请求幂等，不产生重复记录，也不返回内部错误 | Repository/Service 自动化测试 |

---

## 4. 边界情况与业务规则

### 4.1 支持矩阵

| 知识库级别 | 是否支持置顶 | 上限 | 数据来源 |
|------------|--------------|------|----------|
| `PUBLIC` | 是 | 每用户 5 个 | `user_link` |
| `DEPARTMENT` | 是 | 每用户 5 个 | `user_link` |
| `TEAM` | 是 | 每用户 5 个 | `user_link` |
| `PERSONAL` | 否 | 0 | 固定 `is_pinned=false` |

### 4.2 可见性与生命周期

- 公共知识库按公共库列表的可见规则判断；不要求用户先订阅。
- 部门、团队知识库必须通过现有权限/成员关系校验，置顶不能授予查看权限。
- 用户暂时失去权限时，`user_link` 记录保留，但列表与上限统计只考虑当前可见知识库；恢复权限后偏好自动恢复。
- 当前功能不提供知识库级别切换入口；若数据库中出现个人库残留置顶，列表必须忽略且 `is_pinned` 仍为 `false`。
- 知识库被删除时，删除所有用户对该知识库的 `knowledge_space_pin`。
- `type_detail` 不是外键；列表必须与当前租户、当前用户可见知识库 ID 求交集，不能直接返回孤儿记录。

### 4.3 幂等与并发

- 重复置顶已有记录返回成功，不重复计数。
- 重复取消不存在的记录返回成功。
- 同一用户的“计数 + 写入”必须串行化或在等效事务边界内完成，防止并发请求突破每分类 5 个的上限。
- 唯一约束只解决重复记录，不能单独替代上限并发控制。

---

## 5. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 知识库置顶事实源 | A: `space_channel_member` / B: `user_link` / C: 新表 | 选 B | 置顶是用户对资源的偏好，不应依赖订阅或成员关系；项目已有 `used_app_pin` 先例 |
| AD-02 | `user_link.type` 设计 | A: 每级别一个 type / B: 统一 `knowledge_space_pin` | 选 B | 分类已经由 `knowledge_space_scope.level` 表达，避免级别变更时搬迁偏好记录 |
| AD-03 | 个人知识库处理 | A: 也使用 `user_link` / B: 禁止置顶 | 选 B | 个人区只有固定系统空间，已有“我的收藏优先”的确定排序，置顶没有业务价值 |
| AD-04 | 数据访问方式 | A: Service 调用旧 `UserLinkDao` / B: 专用 Repository | 选 B | 遵守 `Endpoint → Service → Repository → DB`，避免在 Service 增加 ORM/DAO 依赖 |
| AD-05 | 列表整合方式 | A: 各列表独立查询 / B: 统一批量装饰器 | 选 B | 防止公共、部门、团队、grouped 等入口出现语义漂移和 N+1 查询 |
| AD-06 | 缓存策略 | A: 缓存完整置顶响应并主动失效 / B: 缓存基础可见列表，响应时叠加置顶 | 选 B | 避免多排序缓存键失效问题，同时保证置顶立即可见 |
| AD-07 | API 契约 | A: 改为新端点和 `is_pinned` / B: 保留现有契约 | 选 B | 兼容现有 Client 和门户部署，不要求跨仓库同步发布 |
| AD-08 | `space_channel_member.is_pinned` | A: 删除字段 / B: 保留但 SPACE 不再使用 | 选 B | 频道仍以该字段作为用户置顶事实源 |
| AD-09 | 上限控制 | A: 仅前端 / B: 前后端双层、后端权威 | 选 B | 防止旧客户端、直接 API 和并发请求绕过限制 |

---

## 6. 数据库与 Domain 模型

### 6.1 `user_link` 语义

不新增业务表，复用现有 `user_link`：

```text
type = "knowledge_space_pin"
type_detail = str(space_id)
记录存在 = 当前用户已置顶
记录不存在 = 当前用户未置顶
```

新增复合唯一约束：

```text
UNIQUE (user_id, type, type_detail)
```

`user_link` 继续不增加 `tenant_id`。这是对现有全局用户偏好表的复用，不改变其多租户模型；知识库置顶查询必须通过当前租户下的 `knowledge_space_scope` 和最终可见 ID 集合收敛结果。

### 6.2 数据迁移

计划迁移文件：

```text
src/backend/bisheng/core/database/alembic/versions/
v2_6_0_f057_knowledge_space_user_link_pin.py
```

升级顺序：

1. 按 `(user_id, type, type_detail)` 查找重复 `user_link`，保留 `create_time` 最新、`id` 最大的记录。
2. 创建复合唯一约束。
3. 读取 `space_channel_member` 中 `business_type=SPACE`、`status=ACTIVE`、`is_pinned=true` 的记录。
4. 关联 `knowledge_space_scope`，排除 `PERSONAL`，幂等写入 `knowledge_space_pin`。
5. 不修改或清空原 `space_channel_member.is_pinned` 数据，频道字段及旧数据保留。

迁移只使用 SQLAlchemy/Alembic 可移植能力，禁止依赖 MySQL 专用 JSON、`information_schema` 或方言专用 upsert；真实 DM8 验证在 Linux CI 执行。

降级时不删除 `knowledge_space_pin` 数据，因为无法区分迁移回填和上线后用户新产生的数据。应用回滚到旧代码时，未订阅公共库的新置顶以及迁移后变更不会被旧版成员表识别，需要配套反向回填脚本；这是已知回滚限制。

### 6.3 Repository 边界

新增知识库领域专用 Repository：

```text
knowledge/domain/repositories/interfaces/knowledge_space_pin_repository.py
knowledge/domain/repositories/implementations/knowledge_space_pin_repository_impl.py
```

Repository 负责：

- 按用户批量读取 `knowledge_space_pin`。
- 在事务中幂等新增或删除单条偏好。
- 按 `space_id` 清理所有用户的知识库置顶。
- 提供同一用户写入串行化所需的事务能力。

Service 不直接导入 `bisheng.database.models.user_link`，不新增旧 DAO 入口。

---

## 7. API 契约

### 7.1 端点

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| POST | `/api/v1/knowledge/space/{space_id}/set-pin` | 置顶或取消置顶知识库 | 是 |

保持请求字段拼写兼容：

```json
{
  "is_pined": true
}
```

成功响应保持现有包装：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

### 7.2 错误码

沿用知识空间模块编码 `180`：

| HTTP Status | Code | Error Class | 场景 | 关联 AC |
|-------------|------|-------------|------|---------|
| 200（业务错误包装） | 18000 | `SpaceNotFoundError` | 知识库不存在 | AC-05 |
| 200（业务错误包装） | 18040 | `SpacePermissionDeniedError` | 用户无权查看目标知识库 | AC-06 |
| 200（业务错误包装） | 18078 | `SpacePersonalPinForbiddenError` | 尝试置顶个人知识库 | AC-05 |
| 200（业务错误包装） | 18079 | `SpacePinLimitError` | 当前分类有效置顶已经达到 5 个 | AC-03 |

---

## 8. Service 层设计

### 8.1 `KnowledgeSpacePinService`

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `get_pinned_space_ids` | `user_id`, `visible_space_ids` | `set[int]` | 批量读取偏好并与当前可见 ID 求交集 |
| `set_pin` | `space_id`, `is_pinned`, `login_user` | `bool` | 校验级别、可见性、上限并幂等写入 |
| `apply_pins` | 已完成基础排序的空间列表 | 装饰并稳定分组后的列表 | 设置 `is_pinned`，置顶优先且保持组内原顺序 |
| `delete_space_pins` | `space_id` | 删除数量 | 知识库删除时清理偏好 |

### 8.2 置顶写入流程

```text
读取知识库和 scope
→ 不存在则 SpaceNotFoundError
→ PERSONAL 则 SpacePersonalPinForbiddenError
→ 按列表同口径校验当前用户可见性
→ 取消置顶：幂等删除并返回
→ 置顶：进入同用户串行化事务
→ 重新读取该分类当前可见置顶并校验上限
→ 幂等新增 user_link
```

公共库可见性以公共库列表口径为准，不要求存在成员关系；部门和团队库复用现有有效权限/成员关系判断。

### 8.3 列表流程

以下入口必须统一接入置顶装饰：

- `_format_accessible_spaces`
- `_format_member_spaces`
- `get_public_spaces`
- `get_grouped_spaces`
- `get_spaces_by_level`
- 我的创建、管理、关注列表所复用的上述格式化路径

统一顺序：

```text
收集候选空间
→ 权限过滤
→ 调用方指定的基础排序
→ 缓存基础可见列表（如适用）
→ 批量读取 user_link
→ PERSONAL 强制 false，其余列表设置 is_pinned
→ 稳定拼接 pinned + normal
```

禁止逐知识库查询 `user_link`。

---

## 9. 前端设计

### 9.1 门户内嵌知识库工作台

修改 `SpaceSidebar`：

- 只有 `group.level !== SpaceLevel.PERSONAL` 时渲染置顶菜单项。
- “我的收藏”和普通个人知识库都不显示置顶或取消置顶。
- `PortalKnowledgeWorkbench.handlePinSpace` 对 `PERSONAL` 增加防御性返回。
- 公共、部门、团队继续保留前端每组最多 5 个的即时提示；后端错误仍通过统一 Toast 展示。

### 9.2 普通知识库侧边栏

修改 `KnowledgeSpaceItem`、`KnowledgeSpaceSidebar` 和 `useSpaceActions`：

- 按 `space.spaceLevel`/分组 `type` 判断个人知识库，隐藏置顶菜单。
- handler 对 `PERSONAL` 增加防御性返回。
- 不影响设置、成员管理、删除、退出等现有权限门控。

### 9.3 门户宿主项目

`shougang-group-knowledge-portal` 仅通过 iframe 打开 `/workspace/knowledge-portal`，本特性不修改其生产代码。

---

## 10. 文件结构计划

### 10.1 新建

| 文件 | 职责 |
|------|------|
| `features/v2.6.0/053-knowledge-space-pin-unification/spec.md` | 本规格 |
| `features/v2.6.0/053-knowledge-space-pin-unification/tasks.md` | 用户确认规格后拆分的实现任务 |
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f057_knowledge_space_user_link_pin.py` | 去重、唯一约束、历史置顶回填 |
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_space_pin_repository.py` | Repository 接口 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/knowledge_space_pin_repository_impl.py` | `user_link` 持久化实现 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_pin_service.py` | 置顶规则、装饰和清理逻辑 |
| `src/backend/test/knowledge/test_knowledge_space_pin_service.py` | Service 与列表回归测试 |

### 10.2 修改

| 文件 | 变更内容 |
|------|----------|
| `src/backend/bisheng/database/models/user_link.py` | 声明三元组唯一约束，与迁移一致 |
| `src/backend/bisheng/common/errcode/knowledge_space.py` | 增加 18078、18079 错误码 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 替换 SPACE 成员置顶读写，接入 Pin Service 和生命周期清理 |
| `src/backend/bisheng/knowledge/domain/services/space_list_cache.py` | 缓存基础列表或确保命中后重新叠加置顶 |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` | 保持契约并委托新服务，修正知识库语义命名 |
| `src/backend/test/knowledge/test_public_space_level_list.py` | 增加公共库置顶输出与排序覆盖 |
| `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.tsx` | 个人分组隐藏置顶菜单 |
| `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.tsx` | handler 防御与错误提示 |
| `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx` | 普通侧边栏个人库隐藏置顶 |
| `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx` | 向列表项传递级别和置顶操作 |
| `src/frontend/client/src/pages/knowledge/hooks/useSpaceActions.ts` | 普通侧边栏 handler 的个人库防御 |
| `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.test.tsx` | 反转个人库置顶断言，补非个人回归 |
| `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.test.tsx` | 反转个人库置顶断言，补非个人回归 |
| `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx` | 每组上限、API 刷新和个人防御测试 |

---

## 11. 测试与验证策略

### 11.1 后端

- Repository：读取、幂等新增、幂等删除、唯一约束冲突、按空间清理。
- Service：四类级别、公共未订阅、权限拒绝、每级别上限、并发上限、权限丢失恢复、删除清理。
- 列表：公共、部门、团队、grouped、缓存命中后的置顶立即生效、个人始终 false。
- API：保留 `is_pined`，覆盖成功、个人禁止、上限、无权限、不存在。
- 迁移：重复数据去重、历史 SPACE 置顶回填、个人排除、重复执行安全性。
- 回归：频道 `is_pinned` 行为不变。

### 11.2 前端

- `SpaceSidebar`：两个个人空间不显示置顶；公共、部门、团队显示置顶。
- `KnowledgeSpaceItem`：个人级别隐藏置顶；非个人级别保留置顶和取消置顶。
- Workbench/Sidebar handler：个人请求不调用 API；非个人请求正常刷新查询缓存。
- 每组 5 个前端提示保持不变。

### 11.3 验证命令

```bash
cd src/backend
uv run pytest test/knowledge/test_knowledge_space_pin_service.py
uv run pytest test/knowledge/test_public_space_level_list.py
uv run pytest test/ -k "channel and pin"
uv run ruff format <changed-backend-files>
uv run ruff check <changed-backend-files>
uv run alembic upgrade head

cd src/frontend/client
npm test -- --runInBand SpaceSidebar KnowledgeSpaceItem PortalKnowledgeWorkbench
npm run build
```

DM8 迁移和行为验证在 Linux CI 中执行；macOS 本地不声明 DM8 已验证。

---

## 12. 非功能要求

- **性能**：单次列表最多增加一次批量 `user_link` 查询，不允许 N+1；缓存命中时不得重新执行权限 fan-out。
- **一致性**：`user_link` 是知识库置顶唯一事实源；成员表旧值不得参与知识库响应计算。
- **并发**：同一用户并发置顶不能突破单分类上限；写入必须幂等。
- **安全**：置顶前校验知识库存在、级别和当前用户可见性；置顶不产生 OpenFGA 元组或成员关系。
- **多租户**：禁止手写 `tenant_id` 条件；通过当前租户范围内的知识库 scope/可见集合过滤全局 `user_link`。
- **兼容性**：MySQL 和 DM8 双兼容；保留现有 API 路径与 `is_pined` 请求字段；频道行为不变。
- **可观测性**：置顶失败、迁移去重数量、历史回填数量记录结构化日志，不记录敏感信息。

---

## 13. 发布与回滚

### 13.1 发布前检查

- 只读检查生产 `user_link` 实际 DDL、已有索引和三元组重复数量。
- 统计历史 SPACE 置顶数、个人库置顶数和预期回填数。
- 确认迁移在与生产同版本 MySQL 演练通过，并由 CI 验证 DM8。

### 13.2 发布顺序

1. 备份或记录待去重、待回填数据统计。
2. 执行 Alembic 迁移。
3. 发布后端 Repository/Service/API。
4. 发布 BiSheng Client 前端。
5. 验证四类列表、上限、权限和频道回归。

### 13.3 回滚边界

- 前端可独立回滚，不影响偏好数据。
- 后端回滚到旧代码后只能识别旧成员表置顶，无法表达未订阅公共库的置顶。
- Alembic downgrade 不删除 `knowledge_space_pin` 数据；如必须恢复旧版知识库置顶显示，需要将仍有 ACTIVE SPACE 成员关系的 `user_link` 反向回填到成员表。
- 未订阅公共库置顶在旧模型中无等价表示，回滚期间只能暂时不展示，但数据仍保留，可在重新升级后恢复。

---

## 14. 追踪矩阵 Traceability

| Requirement | Architecture / Design | Acceptance Criteria |
|-------------|-----------------------|---------------------|
| REQ-001 | AD-01, AD-02, §6, §8 | AC-01, AC-02 |
| REQ-002 | AD-03, §4.1, §9 | AC-04, AC-05 |
| REQ-003 | AD-09, §4.3, §8.2 | AC-03, AC-06 |
| REQ-004 | AD-05, AD-06, §8.3 | AC-01, AC-02, AC-10 |
| REQ-005 | AD-01, §6.2 | AC-07 |
| REQ-006 | AD-08, §6.2 | AC-08 |
| REQ-007 | §4.2, §8.1 | AC-06, AC-09 |
| REQ-008 | AD-07, §7 | AC-05, AC-11 |
| REQ-009 | §4.3, §6.1, §6.3 | AC-03, AC-07, AC-12 |

---

## 15. Clarifications

- 2026-07-14：用户确认公共、部门、团队知识库统一使用 `user_link` 表达置顶偏好。
- 2026-07-14：用户明确个人知识库不需要置顶功能，前端页面不得显示置顶操作。
- 2026-07-14：用户确认进入规划中的 SDD 规格阶段；生产代码、迁移和数据操作需在规格评审确认后执行。
- 2026-07-14：用户确认 `spec.md`；任务拆解前按代码检索校正普通侧边栏 handler 路径，并明确当前不新增知识库级别切换能力。

---

## 相关文档

- [v2.6.0 release contract](../release-contract.md)
- [SDD README](../../README.md)
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
- `src/backend/bisheng/database/models/user_link.py`
- `src/backend/bisheng/common/models/space_channel_member.py`
- `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.tsx`
