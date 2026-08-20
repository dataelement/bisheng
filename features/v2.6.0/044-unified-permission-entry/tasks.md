# Tasks: F044-unified-permission-entry（知识空间与频道统一权限设置入口）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)（接手第一入口）
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户确认范围、细粒度能力显隐与转私密语义 |
| design.md | ✅ 已评审 | `/sdd-review design` 通过；候选查询下沉 Service，创建接口携带初始授权 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 复审通过；45 项任务、6 个 Wave |
| 实现 | ✅ 已完成 | 45 / 45 完成；真实 E2E 环境不可用，验证结论明确记录为阻塞而非通过 |
| 契约登记 | ✅ 已完成 | `release-contract.md` 表 1 / 表 3 / 变更历史已登记 F044 |

---

## 开发模式

- **后端 Test-First**：测试任务先红，再完成紧随其后的实现任务；测试放 `src/backend/test/{permission,knowledge,channel}/`。
- **前端仅 Client**：只修改 `src/frontend/client/`，本 Feature 不涉及 platform；服务器状态用 react-query v4，本地草稿用 `useState`/hook，不新增 Recoil。
- **无基础设施变更**：不新增 ORM、迁移、配置、错误码、Celery/Worker；因此无数据库回滚和 Worker tenant header 任务。
- **共享文件防护**：`resource_permission.py`、`ChannelAuthorizationService` 的候选结果必须与改造前保持一致；Service 下沉只改变分层，不改变范围、排序、分页或 F038 懒加载形状。
- **自包含**：每项内联文件、逻辑、AC、依赖；设计理由只引用 design，不复制。
- **E2E 必做**：完成实现后调用 `/e2e-test features/v2.6.0/044-unified-permission-entry`，生成 API E2E 与页面手动清单。

---

## Tasks

### Wave 1 — grant-subject 查询下沉（后端，可独立完成）

- [x] **T001**: `GrantSubjectQueryService` 单元测试
  **文件**: `src/backend/test/permission/test_grant_subject_query_service.py`
  **逻辑**: 以 mock repository 固化用户分页、用户组关键词、部门 children/search/path-tree、tenant scope、prospective-owner 无管理能力拒绝；固化创建前批量验证对跨 tenant 对象、非法 owner 的拒绝；断言不接受客户端 tenant_id。
  **测试**: `test_user_candidates_tenant_scoped`、`test_department_lazy_operations`、`test_creator_without_manage_permission_denied`、`test_validate_creation_grants_rejects_cross_tenant`、`test_group_owner_rejected`
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: 无

- [x] **T002**: 候选查询 Repository + Service
  **文件**: `src/backend/bisheng/permission/domain/repositories/grant_subject_query_repository.py`, `src/backend/bisheng/permission/domain/services/grant_subject_query_service.py`
  **逻辑**: 将 endpoint 内 `_list_knowledge_space_grant_users`、`_grant_departments_*`、`_list_knowledge_space_grant_user_groups` 的取数下沉；Service 暴露资源/创建阶段查询与 `validate_creation_grants`，负责能力/tenant/scope/非用户 owner 编排，Repository 承担 ORM 和按 subject IDs 批量存在性查询；保持 F038 lazy shape 和 F033 可选 bound-department scope。
  **测试**: T001 全部通过
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: T001

- [x] **T003**: 资源权限候选 API 回归测试
  **文件**: `src/backend/test/permission/test_resource_grant_subject_api.py`
  **逻辑**: 对真实 resource_id 固化 knowledge_space 的 users/departments/user-groups 响应与拒绝路径；增加 creation query 的 resource_type/subject_type/operation 参数、prospective-owner 管理能力和跨 tenant 断言；固化 `relation-models/grantable?creation=true` 无 object_id 的过滤与旧调用兼容。
  **测试**: 只写 HTTP/API 断言，不包含 Service 实现。
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: T002

- [x] **T004**: Permission API 改调 Service + 创建候选端点
  **文件**: `src/backend/bisheng/permission/api/endpoints/resource_permission.py`
  **逻辑**: 删除 endpoint 内候选 ORM/helper 实现，现有 resource-id 候选端点改调 T002；新增 `GET /permissions/creation-grant-subjects`；扩展现有 `relation-models/grantable` 支持 `creation=true`、省略 object_id 并按 prospective owner permission IDs 过滤，默认编辑模式不变；authorize 路径本任务不改。
  **测试**: T003 全部通过
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: T002, T003

- [x] **T005**: 频道候选委托回归测试
  **文件**: `src/backend/test/channel/test_channel_grant_subject_delegation.py`
  **逻辑**: mock `GrantSubjectQueryService`，逐项断言 channel users/departments children/search/path-tree/user-groups 使用 channel tenant 和现有权限门禁；禁止 import permission API endpoint。
  **测试**: 只验证委托、参数和拒绝传播。
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: T002

- [x] **T006**: `ChannelAuthorizationService` 改调候选 Service
  **文件**: `src/backend/bisheng/channel/domain/services/channel_authorization_service.py`
  **逻辑**: 移除对 `permission.api.endpoints.resource_permission` 的五处反向 import；`list_grant_*` 统一委托 T002，保留 `_require_manage_access`、channel tenant 解析与返回形状。
  **测试**: T005 全部通过
  **覆盖 AC**: AC-06, AC-09, AC-22, AC-25
  **依赖**: T002, T005

- [x] **T007**: 通用资源授权 Service 回归测试
  **文件**: `src/backend/test/permission/test_resource_authorization_service.py`
  **逻辑**: 从现有 authorize endpoint 行为固化 grant-tier/管理 permission 校验、F033 scope、禁止部门/用户组 owner、自身权限与最后 owner 防护、tuple 写入、relation-model binding、通知、现有错误码；频道 resource_type 仍拒绝走通用 Service。
  **测试**: 只写 Service 行为测试，mock OpenFGA/Config/通知，不修改 endpoint。
  **覆盖 AC**: AC-09, AC-10, AC-12, AC-13, AC-16, AC-22, AC-25
  **依赖**: 无

- [x] **T008**: `ResourceAuthorizationService` 下沉 + endpoint 委托
  **文件**: `src/backend/bisheng/permission/domain/services/resource_authorization_service.py`, `src/backend/bisheng/permission/api/endpoints/resource_permission.py`
  **逻辑**: 将现有 `authorize_resource` 的模型/能力/scope 校验、PermissionService tuple 写、binding 保存、通知编排下沉为 `authorize(...)`；成功返回 `None`，业务失败抛现有 `BaseErrorCode`，tuple 写失败归一为 `PermissionTupleWriteError`；endpoint 只做 DTO/response 转换。保留 relation-model/binding store 的兼容 wrapper，channel 继续拒绝并走 F026。
  **测试**: T007 与 T003 全部通过
  **覆盖 AC**: AC-09, AC-10, AC-12, AC-13, AC-16, AC-22, AC-25
  **依赖**: T004, T007

### Wave 2 — 创建请求携带初始授权（后端，知识空间与频道可并行）

- [x] **T009**: 知识空间创建编排 Service 单元测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_creation_application_service.py`
  **逻辑**: mock `KnowledgeSpaceService`、T002 `GrantSubjectQueryService` 与 T008 `ResourceAuthorizationService`，断言无 grants 完全保持旧行为；有 grants 时先校验再只调一次原 create、批量授权，不重复写 owner/成员/审计；授权 `BaseErrorCode` 保留 resource id、返回 failed + 现有 error code，不删除/重建资源；非法 owner/跨 tenant 在写资源前拒绝。
  **测试**: `test_create_without_initial_permissions_compatible`、`test_create_then_grant`、`test_grant_failure_keeps_resource`、`test_invalid_grant_rejected_before_create`
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-22, AC-23, AC-25
  **依赖**: T002, T008

- [x] **T010**: 知识空间初始授权 Schema + Application Service
  **文件**: `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_creation_application_service.py`
  **逻辑**: `KnowledgeSpaceCreateReq` 增加可选 `initial_permissions.grants`，复用 `AuthorizeGrantItem` 且无 revokes；application service 先调 T002 批量校验，再只调一次原 create，最后调 T008；原 create 继续独占 owner best-effort、成员、审计等副作用。输出原资源字段 + 可选 `initial_permission_result(status,error_code)`，不得直接调底层 `PermissionService.authorize()`。
  **测试**: T009 全部通过
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-22, AC-23, AC-25
  **依赖**: T002, T008, T009

- [x] **T011**: 知识空间创建端点 API 测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_create_initial_permissions_api.py`
  **逻辑**: TestClient 覆盖旧请求响应兼容、新字段解析、成功结果、资源已创建但授权失败结果、用户组/部门 owner 拒绝；断言 endpoint 不直接写权限。
  **测试**: 只写 API 合约与依赖 mock。
  **覆盖 AC**: AC-01, AC-09, AC-12, AC-13, AC-22, AC-23
  **依赖**: T010

- [x] **T012**: 知识空间创建 Endpoint 接入编排 Service
  **文件**: `src/backend/bisheng/knowledge/api/dependencies.py`, `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  **逻辑**: 注入 T010 application service；`POST /knowledge/space` 从直接调用原 service 改为委托编排服务，保持 quota decorator、认证、响应 envelope 和旧字段兼容。
  **测试**: T011 全部通过
  **覆盖 AC**: AC-01, AC-09, AC-12, AC-13, AC-22, AC-23
  **依赖**: T010, T011

- [x] **T013**: 频道创建编排 Service 单元测试
  **文件**: `src/backend/test/channel/test_channel_creation_application_service.py`
  **逻辑**: mock `ChannelService.create_channel`、T002 `GrantSubjectQueryService` 与 F026 `authorize_channel`，断言无 grants 旧行为、有 grants 先校验再创建后授权、授权失败不重放情报源订阅/知识同步、返回 resource id + failed、非法对象创建前拒绝。
  **测试**: `test_create_channel_without_grants_compatible`、`test_create_then_authorize_channel`、`test_authorize_failure_does_not_recreate_channel`、`test_invalid_subject_rejected`
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-22, AC-24, AC-25
  **依赖**: T002, T006

- [x] **T014**: 频道初始授权 Schema + Application Service
  **文件**: `src/backend/bisheng/channel/domain/schemas/channel_manager_schema.py`, `src/backend/bisheng/channel/domain/services/channel_creation_application_service.py`
  **逻辑**: `CreateChannelRequest` 增加可选 `initial_permissions.grants`，grant item 复用 F026 schema 且无 revokes；application service 先调 T002 批量校验、再只调一次原 create，最后调 `ChannelAuthorizationService.authorize_channel`；原 create 独占 owner/成员/订阅/知识同步副作用，授权失败不重放。
  **测试**: T013 全部通过
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-22, AC-24, AC-25
  **依赖**: T002, T006, T013

- [x] **T015**: 频道创建端点 API 测试
  **文件**: `src/backend/test/channel/test_channel_create_initial_permissions_api.py`
  **逻辑**: TestClient 覆盖 `POST /channel/manager/create` 旧请求兼容、initial grants 成功/失败、string channel id、非法 owner 与跨 tenant 拒绝；断言失败恢复不再次调用 create。
  **测试**: 只写 API 合约与依赖 mock。
  **覆盖 AC**: AC-02, AC-09, AC-12, AC-13, AC-22, AC-24
  **依赖**: T014

- [x] **T016**: 频道创建 Endpoint 接入编排 Service
  **文件**: `src/backend/bisheng/channel/api/dependencies.py`, `src/backend/bisheng/channel/api/endpoints/channel_manager.py`
  **逻辑**: 注入 T014 application service；现有 create endpoint 改为委托编排，保持认证、响应 envelope、审计与原 `ChannelService.create_channel` 副作用顺序。
  **测试**: T015 全部通过
  **覆盖 AC**: AC-02, AC-09, AC-12, AC-13, AC-22, AC-24
  **依赖**: T014, T015

- [x] **T017**: 编辑权限、并发与转私密回归测试
  **文件**: `src/backend/test/permission/test_unified_settings_permission_regression.py`
  **逻辑**: 固化知识空间/频道提交时失权拒绝、非管理者不得读授权、touched grant/revoke 不覆盖未触碰并发授权、分享转私密只留创建者、再转分享不恢复、现有角色/permission ID 语义不变。
  **测试**: 仅补回归测试；本任务不修改生产实现，失败时先判断是基线缺陷还是本 Feature 引入。
  **覆盖 AC**: AC-09, AC-10, AC-15, AC-16, AC-17, AC-20, AC-21, AC-22, AC-25
  **依赖**: T012, T016

### Wave 3 — Client 共享权限草稿与 API Adapter

- [x] **T018**: Client API 合约测试
  **文件**: `src/frontend/client/src/api/unifiedPermissionEntry.test.ts`
  **逻辑**: mock request wrapper，断言创建候选、`relation-models/grantable?creation=true`、两类 initial grants 请求；固化 camelCase `InitialPermissionResult {status,errorCode}` 和资源 id 均不被 adapter 丢失；编辑继续调现有 resource-id authorize。
  **覆盖 AC**: AC-09, AC-11, AC-12, AC-13, AC-22
  **依赖**: T004, T012, T016

- [x] **T019**: 创建候选与权限 API Adapter
  **文件**: `src/frontend/client/src/api/permission.ts`
  **逻辑**: 增加 `getCreationGrantSubjects`、`getCreationGrantableRelationModels` 及 query/响应类型；后者复用现有 grantable 路径并传 `creation=true`；保留编辑态现有候选/authorize API；使用 wrapped request + `skip403Redirect` 现有约定，不增加业务 403 分支。
  **测试**: T018 中候选/权限断言通过
  **覆盖 AC**: AC-06, AC-09, AC-11, AC-22
  **依赖**: T004, T018

- [x] **T020**: 两类资源创建 API Adapter
  **文件**: `src/frontend/client/src/api/knowledge.ts`, `src/frontend/client/src/api/channels.ts`
  **逻辑**: create payload 增加可选 `initialPermissions.grants` 的 snake_case 映射；两类 adapter 统一导出 camelCase `InitialPermissionResult {status: "success"|"failed", errorCode: number|null}` 并在返回结果中保留资源 id，不得被现有 mapping 丢失；频道只用真实 `/channel/manager/create` adapter，更新/授权路径不变。
  **测试**: T018 中两类 create 断言通过
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-23, AC-24
  **依赖**: T012, T016, T018

- [x] **T021**: `PermissionDraft` reducer/hook 单元测试
  **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.test.ts`
  **逻辑**: 覆盖 add/change/remove、创建者锁定、稳定 key 包含 relation/model/includeChildren、只生成 touched diff、baseline 并发新增不被撤销、reset/cancel 无写副作用。
  **覆盖 AC**: AC-11, AC-14, AC-16, AC-22, AC-25
  **依赖**: 无

- [x] **T022**: 权限草稿 Hook + 受控编辑器
  **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.ts`, `src/frontend/client/src/components/permission/PermissionDraftEditor.tsx`
  **逻辑**: 实现 design §4.3 草稿和 diff；编辑器只接收 value/onChange/capabilities，不发 HTTP；创建者行不可编辑/删除，部门和用户组不提供 owner；复用 `RelationSelect` 与现有 permission UI。
  **测试**: T021 全部通过
  **覆盖 AC**: AC-06, AC-07, AC-11, AC-14, AC-16, AC-22, AC-25
  **依赖**: T021

- [x] **T023**: 用户/用户组选择器支持创建阶段数据源
  **文件**: `src/frontend/client/src/components/permission/SubjectSearchUser.tsx`, `src/frontend/client/src/components/permission/SubjectSearchUserGroup.tsx`
  **逻辑**: 增加显式 `mode=create|resource`/query adapter props；create 调 T019，edit 保持 resource-id API；候选去重仍由受控草稿负责，不放宽搜索范围。
  **覆盖 AC**: AC-11, AC-22, AC-25
  **手动验证**: 普通创建者可搜索 tenant 内允许的用户/组；跨 tenant 与不可见私有组不出现。
  **依赖**: T019, T022

- [x] **T024**: 部门选择器支持创建阶段懒加载
  **文件**: `src/frontend/client/src/components/permission/SubjectSearchDepartment.tsx`, `src/frontend/client/src/components/permission/useGrantDepartmentTree.ts`
  **逻辑**: create 模式将 children/search/path-tree 映射到 T019 的单端点 operation；edit 模式不变；保持 F038 逐层展开、搜索裁剪树和 includeChildren scope。
  **覆盖 AC**: AC-11, AC-22, AC-25
  **手动验证**: 首屏只取根层，展开只取直接子层，搜索不加载整树；包含子部门选择保持现状。
  **依赖**: T019, T022

### Wave 4 — 知识空间统一页面与入口

- [x] **T025**: 知识空间 Settings 表单 Hook + Page
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts`, `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx`
  **逻辑**: named export 完整页面；create/edit 共用表单，加载服务端详情/permission IDs；管理能力决定访问与分享区，纯编辑者只见可编辑字段；private 隐藏授权，切 share 默认 approval；create 携 initial grants，失败提供仅重试授权/进入资源；edit 用 touched diff，转 private 后不再 authorize。
  **覆盖 AC**: AC-01, AC-03, AC-06, AC-07, AC-10, AC-11, AC-13, AC-14, AC-15, AC-17, AC-18, AC-19, AC-20, AC-21, AC-23, AC-25
  **手动验证**: A/B/C 三类账号分别验证 create/settings 显隐；权限失败不重复创建；private→share 不恢复成员。
  **依赖**: T019, T020, T022, T023, T024

- [x] **T026**: 知识空间列表 Action 合并为单一设置入口
  **文件**: `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`, `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceCardItem.tsx`
  **逻辑**: 删除独立“成员管理”菜单；当 `canEditSpace || canManageMembers` 时只展示一个“空间设置”并调用统一 settings callback；置顶、退出、删除规则不变。
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-06, AC-07, AC-08
  **手动验证**: 仅编辑者、仅权限管理者都看到一个设置入口；只读者看不到；其他 action 不变。
  **依赖**: T025

- [x] **T027**: 知识空间侧边栏与列表容器接入 Settings 路由
  **文件**: `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`, `src/frontend/client/src/pages/knowledge/index.tsx`
  **逻辑**: 移除 `onManageMembers` 独立传递链，新建与统一设置回调分别 navigate 到 create/settings；保留现有细粒度能力计算，仅合并入口不改权限语义。
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-06, AC-07, AC-08, AC-25
  **手动验证**: 行列表、卡片列表和新建按钮均进入对应统一页面。
  **依赖**: T025, T026

- [x] **T028**: 知识空间详情移除独立权限入口
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`
  **逻辑**: 详情页编辑/原管理成员入口统一 navigate 到 settings；删除空间级 `KnowledgeSpaceShareDialog` state/render，保留文件/文件夹通用 `PermissionDialog`。
  **覆盖 AC**: AC-03, AC-05, AC-06, AC-07, AC-08
  **手动验证**: 详情页只进入统一设置页；文件与文件夹权限弹窗仍正常。
  **依赖**: T025

- [x] **T029**: 移除知识空间旧创建抽屉
  **文件**: `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx`
  **逻辑**: 在 T027 无调用方且 `rg` 验证后删除；不得删除仍供文件/文件夹使用的通用权限 dialog。
  **覆盖 AC**: AC-01, AC-05
  **依赖**: T027

### Wave 5 — 频道统一页面、入口与旧组件清理

- [x] **T030**: 频道 Settings 表单 Hook + Page
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/useChannelSettingsForm.ts`, `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.tsx`
  **逻辑**: named export 完整页面；复用 CreateChannel 下现有信息源、筛选、子频道、知识同步组件；桌面双栏/移动单栏；有效 permission IDs 控制权限区；private/share(review/public)、默认 review、initial grants、失败仅重试权限、edit touched diff 与 private 后禁 authorize。
  **覆盖 AC**: AC-02, AC-04, AC-06, AC-07, AC-10, AC-11, AC-13, AC-14, AC-15, AC-17, AC-18, AC-19, AC-20, AC-21, AC-24, AC-25
  **手动验证**: 创建保留全部频道业务字段；权限失败后不重复频道/情报源订阅；桌面双栏、窄屏单栏。
  **依赖**: T019, T020, T022, T023, T024

- [x] **T031**: 频道文章区 Action 合并为单一设置入口
  **文件**: `src/frontend/client/src/pages/Subscription/ArticleList/ChannelActionsMenu.tsx`, `src/frontend/client/src/pages/Subscription/ArticleList/ArticleList.tsx`
  **逻辑**: 删除独立“管理成员”菜单；当 `canEditChannelSettings || canManageChannelPermissions` 时展示一个“频道设置”，回调统一传 channel；置顶、退出、删除/解散规则不变。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-07, AC-08
  **手动验证**: 仅编辑者、仅权限管理者都看到一个设置入口；只读者看不到；其他 action 不变。
  **依赖**: T030

- [x] **T032**: 频道侧栏 Action 合并为单一设置入口
  **文件**: `src/frontend/client/src/pages/Subscription/Sidebar/ChannelItem.tsx`, `src/frontend/client/src/pages/Subscription/Sidebar/ChannelSidebar.tsx`
  **逻辑**: 与 T031 同口径移除侧栏独立管理成员入口；UI 只消费既有 helper 输出的有效 permission IDs，不新增 legacy role fallback 或角色名判断。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-07, AC-08, AC-25
  **手动验证**: 两种列表形态的菜单项、显隐和跳转一致。
  **依赖**: T030

- [x] **T033**: 频道容器接入 Settings 路由
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelLayout.tsx`, `src/frontend/client/src/pages/Subscription/index.tsx`
  **逻辑**: 新建/编辑/原管理成员回调统一 navigate create/settings；删除 permission dialog 和 create drawer state/render；向 ArticleList/Sidebar 仅传统一 settings callback；频道数据刷新在路由返回后读取服务端状态。
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-06, AC-08, AC-14, AC-15
  **手动验证**: 新建、文章区、侧栏和详情入口均进入相同页面；返回后列表显示服务端最新值。
  **依赖**: T030, T031, T032

- [x] **T034**: 注册四个 client 页面路由
  **文件**: `src/frontend/client/src/routes/index.tsx`
  **逻辑**: lazy import named page并注册 `knowledge/create`、`knowledge/space/:spaceId/settings`、`channel/create`、`channel/:channelId/settings`（最终 URL 含 `/workspace` base）；沿用 knowledge/subscription plugin gate 与登录保护。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-08
  **手动验证**: 四个 URL 刷新、前进/后退和无菜单权限访问行为正确。
  **依赖**: T025, T030, T033

- [x] **T035**: 移除频道独立权限弹窗
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelPermissionDialog.tsx`, `src/frontend/client/src/pages/Subscription/ChannelShareDialog.tsx`
  **逻辑**: T033 后 `rg` 确认无调用方再删除；不得影响知识文件/文件夹的通用权限 dialog。
  **覆盖 AC**: AC-05
  **依赖**: T033

- [x] **T036**: 迁移频道表单类型并移除旧创建抽屉
  **文件**: `src/frontend/client/src/pages/Subscription/channelUtils.ts`, `src/frontend/client/src/pages/Subscription/CreateChannel/CreateChannelDrawer.tsx`
  **逻辑**: 将 `CreateChannelFormData` 移到并由 `channelUtils.ts` 导出，保持 payload builder 与 T030 settings hook 共用稳定类型；T030/T033 复用完子组件后删除无调用方 Drawer，保留 AddSource、Filter、SubChannel、KnowledgeSync 等组件。
  **覆盖 AC**: AC-02, AC-05, AC-24
  **依赖**: T030, T033

- [x] **T037**: 移除频道旧创建成功页
  **文件**: `src/frontend/client/src/pages/Subscription/CreateChannel/CreateChannelSuccess.tsx`
  **逻辑**: T036 删除 Drawer 后使用 `rg` 确认无调用方再删除；统一页创建成功或初始授权失败的恢复动作均由 ChannelSettingsPage 承载。
  **覆盖 AC**: AC-02, AC-05, AC-13
  **依赖**: T036

- [x] **T038**: 统一页面 i18n（中英）
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`, `src/frontend/client/src/locales/en/translation.json`
  **逻辑**: 使用 `/i18n-localizer` 增加访问与分享、创建/保存、资源已创建但权限未完全设置、仅重试权限、进入资源等嵌套 key；复用已有基础设置/角色/私密/分享 key，禁止硬编码中文。
  **覆盖 AC**: AC-01, AC-02, AC-13, AC-17, AC-18, AC-19
  **依赖**: T025, T030

- [x] **T039**: 统一页面 i18n（日文）
  **文件**: `src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 与 T038 key 集完全一致并生成自然日语；运行 locale key 对齐检查，缺 key 视为任务失败。
  **覆盖 AC**: AC-01, AC-02, AC-13, AC-17, AC-18, AC-19
  **依赖**: T038

### Wave 6 — 自动化、E2E 与交付门禁

- [x] **T040**: 知识空间统一页面组件测试
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.test.tsx`
  **逻辑**: mock API 覆盖 A/B/C 能力显隐、create/edit 服务端初始化、private 隐藏、share 默认 approval、initial auth failed 恢复、touched diff、转 private 不调用 authorize、既有字段保留。
  **覆盖 AC**: AC-01, AC-03, AC-06, AC-07, AC-08, AC-11, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-23, AC-25
  **依赖**: T025, T026, T027, T028, T029, T034, T038, T039

- [x] **T041**: 频道统一页面组件测试
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.test.tsx`
  **逻辑**: mock API 覆盖能力显隐、业务字段、private/review/public、initial auth failed 不重建、touched diff、转 private 不 authorize、桌面/移动布局关键 class/区域。
  **覆盖 AC**: AC-02, AC-04, AC-06, AC-07, AC-08, AC-11, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-24, AC-25
  **依赖**: T030, T031, T032, T033, T034, T038, T039

- [x] **T042**: 统一入口回归测试
  **文件**: `src/frontend/client/src/pages/unifiedPermissionEntryRoutes.test.tsx`
  **逻辑**: 用 route/action mocks 断言知识空间与频道不再渲染独立权限入口，新建/设置指向四个路由；置顶、退出、删除/解散以及文件权限 dialog 仍存在。
  **覆盖 AC**: AC-05, AC-06, AC-07, AC-08, AC-25
  **依赖**: T026, T027, T028, T029, T031, T032, T033, T034, T035, T036, T037

- [x] **T043**: API E2E 测试
  **文件**: `src/backend/test/e2e/test_e2e_f044_unified_permission_entry.py`
  **逻辑**: 调用 `/e2e-test` 生成并运行：两类 creation candidates、create+initial grants、授权失败资源保留、编辑失权、分享转私密清理、再分享不恢复、跨租户拒绝；所有资源名使用唯一 `f044-e2e-*` 前缀，`finally` 清理空间/频道/测试用户并记录清理失败证据；使用真实认证和服务端查询验证结果。
  **覆盖 AC**: AC-06, AC-09, AC-10, AC-11, AC-12, AC-13, AC-16, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T017

- [x] **T044**: 页面 E2E 手动验证清单
  **文件**: `features/v2.6.0/044-unified-permission-entry/e2e-checklist.md`
  **逻辑**: 由 `/e2e-test` 生成 A/B/C 账号矩阵、Figma 桌面/移动布局、创建/编辑/失败恢复、独立入口消失、文件权限不受影响、频道副作用不重放的逐步清单；不写账号凭据。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T040, T041, T042, T043

- [x] **T045**: 最终构建、架构与差异验证
  **文件**: 无（只执行验证，不改生产文件）
  **逻辑**: 运行后端聚焦 pytest、client `test:ci/typecheck/build`、`scripts/arch-guard.sh`、`git diff --check`；`rg` 确认 domain 不 import permission endpoint、空间/频道独立 permission dialog 无调用、文件/文件夹 permission dialog 仍在；区分基线失败与本 Feature 引入失败并记录证据。
  **覆盖 AC**: AC-05, AC-09, AC-12, AC-13, AC-20, AC-21, AC-25
  **依赖**: T040, T041, T042, T043, T044

### Wave 7 — 中粮集团/部门空间固定分享

- [x] **T046**: 集团/部门空间 private 后端最终门禁
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/test/department/test_department_space_private_forbidden.py`
  **逻辑**: 保留管理后台批量创建的 super-admin 门禁及 public/approval 选择；创建和更新显式 private 均在清理或资源写入前返回 18075，历史 private 的无 auth_type 维护不受影响。
  **覆盖 AC**: AC-26, AC-28
  **依赖**: F033

- [x] **T047**: 前台私密禁选且保留审核与成员权限
  **文件**: `src/frontend/client/src/components/permission/UnifiedPermissionControls.tsx`, `src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts`, `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx`, `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.test.tsx`
  **逻辑**: `space_kind=department` 时展示但单独禁用 private，shared 下 public/approval 与权限草稿保持可用；历史 private 在页面初始化为 approval 并在下次保存修正。
  **覆盖 AC**: AC-27, AC-28
  **依赖**: T025, T040, T046

---

## 验证记录（2026-08-07）

- **后端变更集**：F044 新增/关联的 10 个测试文件 `96 passed`；计划指定的聚合命令 `12 passed, 1440 deselected`；新增文件与关键私密清理路径 Ruff 通过。
- **前端变更集**：统一入口 5 个 Jest suite `30 passed`；变更文件 ESLint、大小写 import 检查通过；三语 `com_unified_permission` 均为 21 个 key。
- **架构与差异**：`scripts/arch-guard.sh`、`git diff --check` 通过；domain 未反向 import permission endpoint；空间/频道旧独立权限组件无生产调用，文件/文件夹权限弹窗仍在。
- **真实 E2E（未通过）**：4 个用例因本机 API/中间件不可达而明确 `skipped`，均报告 `All connection attempts failed`；已生成独立 fixture、唯一资源名前缀、`finally` 清理和残留证据，等待可用环境复跑。
- **仓库基线阻塞**：client `typecheck` 与 Vite build 均停在既有 `packages/ui/ErrorPage.tsx` 缺少 `qrcode.react`；全量 Jest 在注入本机 canvas 兼容层后为 `190 passed`、4 个既有 suite 失败（`filenamify`/`sse.js` ESM、历史结构断言与通知断言）；未将这些结果标记为本 Feature 通过。

## 验证补充（2026-08-11）

- **中粮固定分享规则**：部门服务与 private 最终门禁聚焦测试 `20 passed`；知识空间设置页 Jest `10 passed`，覆盖私密禁选、加入审核切换、成员权限区域保留和历史 private 归一化。
- **静态与架构检查**：变更文件 Ruff、ESLint、`scripts/arch-guard.sh`、`git diff --check` 通过。
- **仓库基线阻塞**：client `typecheck` 仍有 6 个既有错误（聊天图标/配置类型、文件与文件夹上传可选值、该测试文件既有 matcher 类型声明）；本次新增 matcher 类型错误已清零。

---

## 实际偏差记录

> 只留一行指针；论证回写 design.md。推翻已确认决策时先停下重新确认。

- 暂无。
