# Feature: F106-knowledge-reorder-auth（库与文件夹排序权限）

> **前置**：Spec Discovery 已确认（2026-09-01）。

**关联 PRD**: [`prd.md`](./prd.md)  
**技术方案（权威）**: [`design.md`](./design.md)  
**优先级**: P0  
**所属版本**: v2.6.0  
**模块编码**: **180**（复用 `common/errcode/knowledge_space.py`，不新开模块号）  
**依赖**: 现有 `knowledge.sort_weight` / `knowledgefile.sort_weight` midpoint 算法；F013 ReBAC；部门绑定 `department_knowledge_space`；运营岗 `has_platform_operator_role`

> **范围边界**
> - **纳入**：排序写接口鉴权矩阵；列表下发 `can_reorder` / `can_reorder_folders`；团队+科室同一工作集；部门管理员按绑定表。
> - **明确排除**：门户自建鉴权；未绑定团队库的组织推断；置顶语义；个人库排序；运营岗文件夹拖拽；DDL。
> - **端侧**：知识门户 Client（毕昇 iframe）；写模型 → 毕昇 `knowledge`。

---

## 1. 概述与用户故事

作为 **系统管理员**，我希望 **现有拖拽排序全部保留**，以便 **继续治理全站库序和目录序**。

作为 **运营岗（平台管理员角色）**，我希望 **调整公共库、部门库顺序**，以便 **做门户运营而不升格为系统管理员**。

作为 **部门管理员**，我希望 **调整本部门（含下级）已绑定的团队/科室库顺序**，以便 **整理自己管辖范围内的库列表**。

作为 **库 / 文件夹的所有者或管理员**，我希望 **调整当前目录下的文件夹顺序**，以便 **组织自己有权管理的目录树**。

---

## 2. 验收标准

角色代码对照见 [`design.md`](./design.md) §4。失败默认：HTTP 业务体 `status_code=18040`（`SpacePermissionDeniedError`），目标行 `sort_weight` 与调用前一致。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 系统管理员 | 拖公共库到同组新位置 | 200；该库 `knowledge.sort_weight` 变为邻居中点 |
| AC-02 | 系统管理员 | 拖部门库 | 同 AC-01 |
| AC-03 | 系统管理员 | 将团队库拖到科室库旁边（同侧栏组） | 200；允许跨 `TEAM`/`TEAM_KS` 互为邻居 |
| AC-04 | 系统管理员 | 拖任意目录下的文件夹 | 200；该文件夹 `knowledgefile.sort_weight` 更新 |
| AC-05 | 运营岗 | 拖公共库 | 同 AC-01 |
| AC-06 | 运营岗 | 拖部门库 | 同 AC-01 |
| AC-07 | 运营岗 | 拖团队库或科室库 | 18040；该库及邻居 `sort_weight` 不变 |
| AC-08 | 运营岗（非该库/文件夹管理员） | 拖文件夹 | 18040；文件夹 `sort_weight` 不变 |
| AC-09 | 部门管理员 | 拖「管辖部门含下级 ∩ 已绑定」且当前可见的团队/科室库 | 200；只改被拖动库的 `sort_weight` |
| AC-10 | 部门管理员 | 拖未绑定部门的团队库 | 18040；无脏写 |
| AC-11 | 部门管理员 | 拖绑定在其他部门上的团队/科室库 | 18040；无脏写 |
| AC-12 | 部门管理员 | 拖公共库或部门库 | 18040；无脏写 |
| AC-13 | 部门管理员（非该库/文件夹管理员） | 拖文件夹 | 18040；无脏写 |
| AC-14 | 库所有者或库管理员 | 在库根目录拖文件夹 | 200 |
| AC-15 | 库所有者或库管理员（非系统管理员/运营岗/合格部门管理员） | 拖该库在侧栏中的位置 | 18040；库 `sort_weight` 不变 |
| AC-16 | 文件夹所有者或管理员 | 在该文件夹内拖子文件夹 | 200 |
| AC-17 | 仅某子文件夹管理员 | 在库根或其他文件夹内拖文件夹 | 18040 |
| AC-18 | 普通成员 / 只读 | 调两个 sort 写接口 | 18040；无脏写 |
| AC-19 | 任意登录用户 | 拖个人库 | `SpaceInvalidLevelError` 18041；与现网一致 |
| AC-20 | 有/无权限用户 | 打开侧栏或目录 | 列表 `can_reorder` / `can_reorder_folders` 与写接口一致；为 false 时不显示拖拽 |
| AC-21 | 任意 | 把公共库的邻居设为部门库（或跨组） | 拒绝；不写 `sort_weight` |
| AC-22 | 系统管理员或合格部门管理员 | 团队库与科室库互为 `prev`/`next` | 允许（工作集含两个 level） |
| AC-23 | 部门管理员 | 首次拖动触发权重重铺 | **不得**改写授权工作集之外的库的 `sort_weight` |
| AC-24 | 两人连续拖同一库 | 后一次成功覆盖前一次权重 | 无半更新脏行；单行 midpoint |
| AC-25 | 库管进入有权文件夹 vs 无权目录 | 拉 `/children` | 当前目录 `can_reorder_folders` 分别为 true / false |

---

## 3. 边界情况

- 侧栏看得见 ≠ 可排序。分享进来的未绑定团队库可以出现在列表，但 `can_reorder=false`。
- 置顶仍是每人一份；拖拽邻居只在同一置顶分组内解析（现网前端行为，不改）。
- 工作集里只有 1 个库：写接口 no-op 成功，权重可不变。
- 列头排序模式下文件夹拖拽仍关闭（现网）。
- 未登录：既有登录墙，不新开口。
- **不支持**：未绑定团队库的组织归属推断；运营岗排团队库/文件夹；个人库排序。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 资格真相源 | A: 前端用 `role===admin` 猜 / B: 服务端下发 `can_reorder*` 且写接口再鉴权 | 选 B | 运营岗、部门绑定无法从 Client `role` 推出 |
| AD-02 | 部门管理员工作集 | A: 侧栏可见团队库 / B: 管辖部门绑定表 ∩ 可见 | 选 B | Discovery「按绑定走」 |
| AD-03 | 团队+科室 | A: 按存储 level 分两条序 / B: 同一工作集 | 选 B | 与侧栏一组一致；修现网拖到科室旁失败 |
| AD-04 | 文件夹鉴权点 | A: 被拖文件夹自身 / B: 当前父目录 | 选 B | 与需求「文件夹内的文件夹顺序」一致 |
| AD-05 | 重铺权重范围 | A: 整 level 全量 / B: 仅本次授权工作集 | 选 B | AC-23；避免部门管理员改别人的序 |

细则与否决项见 [`design.md`](./design.md) §1。

---

## 5. 数据库 & Domain 模型

无新表、无新列、无迁移。读写列见 [`design.md`](./design.md) §2。

列表 Schema 增量（无 DDL）：

- `KnowledgeSpaceInfoResp.can_reorder: bool`（默认 false）
- 子目录列表响应增加 `can_reorder_folders: bool`

---

## 6. API 契约

契约源：FastAPI `/docs`（OpenAPI）。不改路径，改鉴权与列表字段。

| Method | Path | 变更 | 认证 |
|--------|------|------|------|
| POST | `/api/v1/knowledge/space/{space_id}/sort` | 鉴权矩阵替换 `is_admin()` | 登录 |
| POST | `/api/v1/knowledge/space/{space_id}/folders/{folder_id}/sort` | 鉴权改为当前目录 `can_manage`（系统管理员短路保留） | 登录 |
| GET | `/api/v1/knowledge/space/level/{space_level}` | 每条 `can_reorder` | 登录 |
| GET | `/api/v1/knowledge/space/{space_id}` | `can_reorder` | 登录 |
| GET | `/api/v1/knowledge/space/{space_id}/children` | 增加 `can_reorder_folders` | 登录 |

**写成功**: `{ "status_code": 200, "status_message": "SUCCESS", "data": true }`

**无权**: `{ "status_code": 18040, "status_message": "...", "data": null }`（`SpacePermissionDeniedError`）

**个人库 / 跨组邻居**: `18041` `SpaceInvalidLevelError`

| HTTP 包装 | MMMEE | Error Class | 场景 | AC |
|-----------|-------|-------------|------|-----|
| 200 body | 18040 | SpacePermissionDeniedError | 角色不配、未绑定、跨部门、无权目录 | AC-07..18, AC-21 中的鉴权拒绝 |
| 200 body | 18041 | SpaceInvalidLevelError | 个人库；邻居不在同一工作集 | AC-19, AC-21 |
| 200 body | 18000 | SpaceNotFoundError | 库不存在 | 沿用现网 |
| 200 body | 18010 | SpaceFolderNotFoundError | 文件夹不存在或非同级邻居 | 沿用现网 |

前端：`PortalKnowledgeWorkbench` 侧栏按 `space.canReorder` 拖；`SpaceDetail` / 门户文件表按 `can_reorder_folders` 拖。禁止再用单一 `isSystemAdmin` 作为唯一开关。

---

## 7. Service 层逻辑

调用链：`knowledge/api/endpoints/knowledge_space.py` → `KnowledgeSpaceService.reorder_*` → **新小模块**鉴权 helper → 现有 midpoint 写 DAO。

禁止 Endpoint 直连 `database.models`。禁止为鉴权查 `role_access`。运营岗用已有 `has_platform_operator_role`；库/文件夹管理员用 `PermissionService.check(..., relation="can_manage")`（系统管理员 L1 短路保持）。

巨石 `knowledge_space_service.py` 只留调用点；新鉴权与工作集计算放独立小文件。

---

## 8. 前端设计

仅 **Client** `src/frontend/client/`（知识门户 iframe）。Platform 不改。门户仓不改。

- 侧栏：`can_reorder===true` 的行可拖；投放目标限于同组、同置顶态、且同样 `can_reorder` 的行。
- 文件夹：当前目录 `can_reorder_folders===true` 且默认排序模式才可拖。
- 不在 Client 用 `role_names` / `is_department_admin` 自行推导排序权。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/knowledge/domain/services/space_reorder_auth.py` | 工作集与写鉴权（中文 docstring） |
| `src/backend/test/knowledge/test_space_reorder_auth_flow.py` | 真库流转：身份 → HTTP → SELECT → 再打一枪 |

### 修改

| 文件 | 变更 |
|------|------|
| `knowledge/domain/services/knowledge_space_service.py` | `reorder_space` / `reorder_folder` 换鉴权；列表填充 `can_reorder*` |
| `knowledge/domain/schemas/knowledge_space_schema.py` | `can_reorder` |
| `knowledge/api/endpoints/knowledge_space.py` | children 响应带 `can_reorder_folders`；注释 |
| Client `api/knowledge.ts`、侧栏、SpaceDetail、PortalKnowledgeWorkbench | 按服务端标志拖拽 |

---

## 10. 非功能要求

- **性能**: 列表 `can_reorder` 批量计算，禁止对每个库 N+1 次 OpenFGA（部门管理员走绑定 ID 集合 + `is_admin` / 运营岗短路）。
- **安全**: 写路径必须再鉴权；列表标志可藏按钮，不能当唯一门禁。
- **兼容**: 旧 Client 忽略新字段则只是按钮仍可能显示，写接口会 18040；本版 Client 同步改。
- **规格位置**: `features/` 默认 gitignore，仅本地。
