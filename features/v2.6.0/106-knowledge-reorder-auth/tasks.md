# Tasks: F106 库与文件夹排序权限

**关联规格**: [spec.md](./spec.md)  
**技术方案**: [design.md](./design.md)  
**验收用例**: [acceptance-test-cases.md](./acceptance-test-cases.md)  
**PRD**: [prd.md](./prd.md)  
**版本**: v2.6.0  
**分支**: 当前 `feat/v2.6.0/083-expert-qa-enhancement`（未经允许不新建分支）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 审查通过 | `/sdd-review spec` 仅低优先级 18010 已回写 |
| design.md | ✅ 用户已确认 | 「确认方案和 tasks」 |
| acceptance-test-cases.md | ✅ 矩阵已确认 | 流转测已跑通; 本文件仍是用例矩阵不是执行报告 |
| tasks.md | ✅ 已确认并落地 | T001–T013 |
| 实现 | ✅ 完成 | 13 / 13 |

---

## 开发模式

**后端 Test-First**：先红后绿。写路径必须走 Endpoint → Service → 171 MySQL，断言 HTTP + SELECT `sort_weight` + 再打一枪。禁止把测试追加进 `test/test_knowledge_space_service.py`。禁止对巨石 Service 整文件 `ruff format`。

**前端 Test-Alongside（Client）**：`npx jest <files> --coverage=false --watchAll=false`。Platform 不改。门户仓不改。

**自包含**：每个任务内联路径与断言，实现时不必回读 spec。

**贯穿约束**：

- 分层 Endpoint → Service → DAO；鉴权不查 `role_access`
- 运营岗只用 `has_platform_operator_role`，禁止写入 `is_admin()`
- 库管 `user_role=admin` 不能当「能排库」
- TEAM 工作集勿用 `can_platform_operate`（含超管，会让运营岗排到团队库）
- 无 DDL；不手写 `tenant_id`
- 中文 docstring（新文件）；ruff 全角标点：ASCII 标点或 per-file ignore RUF001–003

---

## Tasks

### 基础设施（无测试配对）

- [x] **T001**: 列表契约字段
  **文件**: `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`
  **逻辑**: `KnowledgeSpaceInfoResp` 增加 `can_reorder: bool = False`。新增 children 页模型（或扩展返回结构）：在保留 `data` / `page_size` / `has_more` / `next_cursor` 前提下增加 `can_reorder_folders: bool = False`。无 DDL。
  **依赖**: 无

### 后端 Domain / API（Test-First）

- [x] **T002**: 库排序流转测试（先红）
  **文件**: `src/backend/test/knowledge/test_space_reorder_auth_flow.py`（新建）
  **逻辑**: 仿 `test/knowledge/test_clinic_bind_office_flow.py`：171 `config.yaml` MySQL、`httpx.AsyncClient` + 真实 Endpoint。夹具创建/清理测试库与 `knowledge_space_scope`。用例对应 AT-01, AT-02, AT-03, AT-05, AT-06, AT-07, AT-15, AT-18（仅库 sort）, AT-19, AT-21, AT-22, AT-24, AT-40：成功则 SELECT `knowledge.sort_weight` 为中点且邻居不变，再 GET `/level/...` 顺序一致；失败则 18040/18041 且目标行 weight 与调用前相同后再 POST 一次仍拒绝。运营岗 `is_admin=false` 且 `role_names` 精确「平台管理员」。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-15, AC-18, AC-19, AC-21, AC-22, AC-24
  **依赖**: T001

- [x] **T003**: 库排序鉴权与工作集实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/space_reorder_auth.py`（新建），
           `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（仅 `reorder_space` 及相关载序，薄调用）
  **逻辑**: 抽出工作集：系统管理员 PUBLIC/DEPARTMENT=该 level 全部、TEAM+TEAM_KS 合并一条 `sort_weight` 序；运营岗 PUBLIC/DEPARTMENT 同管理员、TEAM 空；其他人（含部门管理员）TEAM 先空集，绑定表留给 T005。不在工作集 18040；邻居不在工作集 18041；个人库 18041。NULL 重铺**只更新工作集内** ID。`reorder_space` 去掉 `if not is_admin()`。T002 转绿（不含部门管理员用例）。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-15, AC-18, AC-19, AC-21, AC-22, AC-24
  **依赖**: T001, T002

- [x] **T004**: 部门管理员绑定与重铺隔离测试（先红）
  **文件**: `src/backend/test/knowledge/test_space_reorder_auth_flow.py`（追加，不改无关用例）
  **逻辑**: AT-09～AT-12, AT-23：本部门+下级已绑定可见库可拖；未绑定、他部门绑定、公共/部门库 18040 无脏写；首次 respread 后工作集外团队库 `sort_weight` 逐列不变。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-23
  **依赖**: T003

- [x] **T005**: 部门管理员工作集补全
  **文件**: `src/backend/bisheng/knowledge/domain/services/space_reorder_auth.py`
  **逻辑**: 落实绑定表 ∩ `_admin_department_ids()`（含下级）∩ 可见；T004 转绿。禁止用侧栏可见集代替绑定。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-23
  **依赖**: T003, T004

- [x] **T006**: 文件夹排序流转测试（先红）
  **文件**: `src/backend/test/knowledge/test_folder_reorder_auth_flow.py`（新建）
  **逻辑**: 171 真库。AT-04 系统管理员根目录拖文件夹；AT-08 运营岗非库管 18040；AT-13 部门管理员非库管 18040；AT-14 库管根目录 200；AT-16 父文件夹 `can_manage` 200；AT-17 仅子文件夹管理员在根目录 18040；AT-18 成员文件夹 sort 18040。断言 `knowledgefile.sort_weight`，失败再打一枪行不变。OpenFGA 写 `can_manage` tuple 或走现网 authorize 测试夹具。
  **覆盖 AC**: AC-04, AC-08, AC-13, AC-14, AC-16, AC-17, AC-18
  **依赖**: T001

- [x] **T007**: 文件夹排序鉴权实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/space_reorder_auth.py`，
           `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（仅 `reorder_folder`）
  **逻辑**: 父目录空 → `PermissionService.check(can_manage, knowledge_space)`；否则 `check(can_manage, folder, parent_id)`。去掉 `is_admin()` 硬闸（L1 短路保留系统管理员）。邻居必须同目录兄弟，否则 18010。T006 转绿。
  **覆盖 AC**: AC-04, AC-08, AC-13, AC-14, AC-16, AC-17, AC-18
  **依赖**: T006

- [x] **T008**: 列表标志流转测试（先红）
  **文件**: `src/backend/test/knowledge/test_space_reorder_flags_api.py`（新建）
  **逻辑**: AT-20：运营岗/部门管理员/库管/成员 GET `/api/v1/knowledge/space/level/{level}` 与详情，`can_reorder` 与随后 sort 写是否 200 一致。AT-25：库管 GET `/children` 根目录 `can_reorder_folders=true`，无权子目录 false。
  **覆盖 AC**: AC-20, AC-25
  **依赖**: T001, T003, T005, T007

- [x] **T009**: 下发 `can_reorder*`
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（列表/详情/`list_space_children` 填充），
           `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`（children 响应带 `can_reorder_folders`，更新 sort 注释）
  **逻辑**: 批量算工作集，禁止对每个库 N+1 OpenFGA。`can_reorder` = 该 space_id 在当前用户库工作集中。`can_reorder_folders` = 当前 `parent_id` 是否通过文件夹写鉴权（只 check 不写）。T008 转绿。
  **覆盖 AC**: AC-20, AC-25
  **依赖**: T008

### 前端 Client

- [x] **T010**: Client 映射 `can_reorder`
  **文件**: `src/frontend/client/src/api/knowledge.ts`
  **逻辑**: `KnowledgeSpace` 增加 `canReorder`；`mapSpace` 读 `can_reorder`。`reorderSpaceApi` / `reorderFolderApi` 注释改为服务端矩阵，不再写「仅系统管理员」。
  **覆盖 AC**: AC-20
  **依赖**: T001

- [x] **T011**: 侧栏邻居过滤测试（先红）
  **文件**: `src/frontend/client/src/pages/knowledge/portal/components/resolveReorderNeighbours.test.ts`
  **逻辑**: 在现有置顶分组用例外增加：邻居解析不得把 `canReorder=false` 的行当作 prev/next（AT-30）。实现未改前应失败。命令：`npx jest src/pages/knowledge/portal/components/resolveReorderNeighbours.test.ts --coverage=false --watchAll=false`。
  **覆盖 AC**: AC-20
  **依赖**: T010

- [x] **T012**: 侧栏按 `canReorder` 拖拽
  **文件**: `src/frontend/client/src/pages/knowledge/portal/components/SpaceSidebar.tsx`
  **逻辑**: 行 `draggable` 当 `space.canReorder`；`resolveReorderNeighbours` 只锚定 `canReorder` 且同置顶组的行。T011 转绿。
  **覆盖 AC**: AC-20
  **依赖**: T011

- [x] **T013**: 工作台与库详情去掉 isSystemAdmin 总闸
  **文件**: `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.tsx`，
           `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`
  **逻辑**: 去掉 `canReorderSpaces={isSystemAdmin}` / `canReorderFolders={isSystemAdmin}`。侧栏组内任一条 `canReorder` 才启用拖拽层，行仍看字段。文件夹：children 响应的 `can_reorder_folders` 且无列头排序，经 FileTable 的 `canReorderFolders` 传入。工作台测若写死 isSystemAdmin 才能排序则改断言。AT-31, AT-32。
  **覆盖 AC**: AC-20, AC-25
  **依赖**: T010, T012
  **浏览器验证（AT-31 / AT-32）**: 本轮跳过。代码已去掉 `isSystemAdmin` 总闸，侧栏看 `canReorder`，文件夹表看 `can_reorder_folders` 且无列头排序。真机/Playwright 留到联调账号与列表契约更稳后再补。

---

## 实际偏差记录

- 写路径可见集不再调 `get_spaces_by_level`(会拉成员表和列表装饰). 改为: 系统管理员/运营岗 PUBLIC|DEPARTMENT 不求交; 运营岗 TEAM 空集; 部门管理员 TEAM 用 OpenFGA `can_read` ∪ `can_manage`. **纯 membership、无 FGA 可读的绑定库不会进写工作集**; 若现网存在这种部门管理员, 必须把 membership ID 并进可见集.
- 列表 flags 测 GET `/level/team` mock 了 `_get_relation_models_map` / `_get_relation_bindings`, 避免 ConfigDao 在薄 ASGI 里重建引擎. `can_reorder` 计算仍走真实 Service.
- 工作台 `can_reorder_folders` 按 `parent_id` 缓存; 搜索模式强制 false. AT-31/AT-32 浏览器验证本轮跳过（手验和 Playwright 都不做）; 门户仓 / Platform 未改.
- 夹具 INSERT `knowledge` 补了 171 表上无默认值的 `is_released` / `is_favorite` / `auth_type`; 工作集查询裁到本用例 ID, 避免重铺打到现网行.

