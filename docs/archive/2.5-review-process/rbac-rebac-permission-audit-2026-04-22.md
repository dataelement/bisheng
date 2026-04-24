# RBAC / ReBAC / 资源管理权限问题盘点

日期：2026-04-22

## 目的

本文件用于整理本轮对 BiSheng v2.5 权限体系的代码审计结果。

重点不是说明“理论设计”，而是记录：

1. 当前仓库里权限实际是如何生效的
2. 哪些地方已经接了 ReBAC / OpenFGA
3. 哪些地方仍在走旧 RBAC / membership / group_resource 逻辑
4. 哪些资源管理操作存在权限失效、越权、列表不一致、新旧逻辑覆盖的问题

本文件只记录当前代码现状和已确认问题，不包含修复实现。

## 审计范围

本轮重点检查了以下部分：

- `permission/`：`PermissionService`、`OwnerService`、`TenantAdminService`、缓存、权限 API
- `core/openfga/`：授权模型、FGA client/manager
- `user/domain/services/auth.py`、`common/dependencies/user_deps.py`
- `common/middleware/admin_scope.py`、`utils/http_middleware.py`
- 资源模块：
  - `knowledge/domain/services/knowledge_space_service.py`
  - `knowledge/domain/services/knowledge_service.py`
  - `knowledge/domain/knowledge_rag.py`
  - `channel/domain/services/channel_service.py`
  - `api/services/flow.py`
  - `api/services/assistant.py`
  - `tool/domain/services/tool.py`
  - `workstation/api/endpoints/apps.py`
- 遗留结构：
  - `database/models/role_access.py`
  - `database/models/group_resource.py`
  - `common/models/space_channel_member.py`
  - `api/services/role_group_service.py`
  - `user/api/user.py`

## 当前真实权限层次

当前代码里实际同时存在 4 套权限来源：

### 1. ReBAC / OpenFGA

- 资源关系：`owner / manager / editor / viewer`
- 运行时关系：`can_manage / can_edit / can_read / can_delete`
- 主要入口：`PermissionService.check()`、`list_accessible_ids()`、`get_permission_level()`

### 2. Legacy RBAC

- `role_access`
- 通过 `AccessType -> relation/object_type` 的映射，部分场景转发到 ReBAC
- 但仍有大量老路径直接查询 `RoleAccessDao`

### 3. Membership Overlay

- `space_channel_member`
- 在 `knowledge_space` / `channel` 里大量承担“创建者 / 管理员 / 成员”判断
- 这套逻辑和 ReBAC 并没有完全统一

### 4. Legacy Group Resource

- `group_resource`
- 用户组资源页、部分资源管理页仍直接依赖它
- 与 ReBAC 的资源授权是并行存在的，不是只读归档态

## 总结结论

本轮审计确认：当前问题不是“某一个权限判断写错了”，而是以下四类问题同时存在：

1. 核心权限引擎内部语义不一致
2. 资源模块接入 ReBAC 的程度不一致
3. 旧 RBAC / membership / group_resource 逻辑仍在真实运行
4. 某些接口没有鉴权，或鉴权档位用错，或详情和列表不是一套规则

下面按问题编号展开。

---

## A. 核心引擎与一致性问题

### PA-001 `check / list_accessible_ids / get_permission_level` 不是同一套语义

**现象**

- `PermissionService.check()` 有 visible tenant gate、`shared_to` 判断、child tenant admin shortcut
- `PermissionService.list_accessible_ids()` 没有这些逻辑，直接走 `fga.list_objects()`
- `PermissionService.get_permission_level()` 也没有这些逻辑，直接 `batch_check()`

**证据**

- `src/backend/bisheng/permission/domain/services/permission_service.py:51`
- `src/backend/bisheng/permission/domain/services/permission_service.py:141`
- `src/backend/bisheng/permission/domain/services/permission_service.py:560`

**影响**

- 同一个用户对同一资源，`check=true`、列表不出现、授权 UI 里权限档位又算不出来，这三种结果可能同时出现
- `resource_permission` 相关接口依赖 `get_permission_level()`，因此其授权级别判断不一定和真实访问判断一致

### PA-002 资源创建者 fallback 查询错误且覆盖不完整

**现象**

- `_get_resource_creator()` 把 `assistant` 错误地走到了 `FlowDao`
- 同时直接把 `tool / channel / dashboard / folder` 视为“无 creator 字段”
- 但这些模型里实际上存在 `user_id`

**证据**

- `src/backend/bisheng/permission/domain/services/permission_service.py:783`
- `src/backend/bisheng/database/models/assistant.py:37`
- `src/backend/bisheng/channel/domain/models/channel.py:74`
- `src/backend/bisheng/tool/domain/models/gpts_tools.py:52`
- `src/backend/bisheng/knowledge/domain/models/knowledge_file.py:55`

**影响**

- FGA 未及时写入、FGA 不可用、或 fallback 生效时，会错误拒绝本该放行的 owner
- assistant 的 owner fallback 直接失真
- tool/channel 等资源在 fallback 模式下会比设计更“严格”

### PA-003 权限缓存失效策略不完整

**现象**

- `PermissionService.authorize()` 只对直接 `subject_type == user` 的主体做 cache invalidate
- 部门授权、用户组授权不会清理任何用户权限缓存
- 大量真正写 FGA 的路径直接走 `batch_write_tuples()`，完全没有做 cache invalidate
- `PermissionCache.invalidate_user()` 只按当前 tenant scope 删键

**证据**

- `src/backend/bisheng/permission/domain/services/permission_service.py:209`
- `src/backend/bisheng/permission/domain/services/permission_service.py:252`
- `src/backend/bisheng/permission/domain/services/permission_service.py:262`
- `src/backend/bisheng/permission/domain/services/permission_cache.py:112`
- `src/backend/bisheng/department/domain/services/department_change_handler.py:156`
- `src/backend/bisheng/user_group/domain/services/group_change_handler.py:105`

**影响**

- 变更了部门/用户组授权后，用户一段时间内仍可能看到旧结果
- 组织变更、用户组成员变更、部门管理员变更后，权限缓存与 FGA 状态容易漂移

### PA-004 `department include_children` 使用的是“授权时展开”，组织树变化后会漂移

**现象**

- `authorize()` 对 `department + include_children` 会把当前整棵子树展开成多条 `department:{id}#member`
- 后续部门新增、移动、摘出时，没有看到资源授权重算机制

**证据**

- `src/backend/bisheng/permission/domain/services/permission_service.py:747`
- `src/backend/bisheng/department/domain/services/department_change_handler.py:31`

**影响**

- 对“部门及子部门”授权后，后续组织树变化不会自动反映到既有资源授权
- 新增下级部门可能拿不到继承授权
- 被迁出的部门可能继续保留旧授权

### PA-005 `get_permission_level()` 未覆盖 child tenant admin shortcut

**现象**

- `check()` 中明确实现了 child tenant admin shortcut
- `get_permission_level()` 没有这一层，只做 FGA `batch_check()` + creator fallback

**证据**

- `src/backend/bisheng/permission/domain/services/permission_service.py:74`
- `src/backend/bisheng/permission/domain/services/permission_service.py:560`

**影响**

- 资源授权弹窗、grantable relation models、资源权限 API 里对调用方“最高权限档位”的判断，可能低于 `check()` 的真实结果
- child tenant admin 在“能访问”与“能授权/能管理”的接口上可能出现不一致

---

## B. Sync/Async 混用导致的权限失效

### PA-006 同步包装器在 async 场景下会超时或误判

**现象**

- `LoginUser.access_check()`
- `LoginUser.get_user_access_resource_ids()`
- `LoginUser.get_merged_rebac_app_resource_ids()`

这些同步方法内部通过 `_run_async_safe` / `run_async_safe` 调 ReBAC。

而 `run_async_safe()` 在“当前线程已经在事件循环里”时会：

- `run_coroutine_threadsafe(..., loop).result(timeout=10)`

我做了最小复现，结果是直接 `TimeoutError`。

**证据**

- `src/backend/bisheng/user/domain/services/auth.py:191`
- `src/backend/bisheng/user/domain/services/auth.py:297`
- `src/backend/bisheng/user/domain/services/auth.py:331`
- `src/backend/bisheng/utils/async_utils.py:20`

**影响**

- 在 async 业务函数里如果误调同步权限包装器，会出现超时、假阴性、列表缺项
- 这不是局部 bug，而是一整类调用方式错误

### PA-007 受 PA-006 影响的已确认调用点

**已确认调用点**

- `api/services/workflow.py` 的 async `get_all_flows()` 最后调用 sync `add_extra_field()`，而 `add_extra_field()` 内部又调用 sync `user.access_check()`
- `workstation/api/endpoints/apps.py` 的 async `get_used_apps()` 调用 sync `get_merged_rebac_app_resource_ids()`
- `knowledge/domain/services/knowledge_service.py` 中多处 async 方法直接调用 sync `access_check()`

**证据**

- `src/backend/bisheng/api/services/workflow.py:42`
- `src/backend/bisheng/api/services/workflow.py:82`
- `src/backend/bisheng/workstation/api/endpoints/apps.py:95`
- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:740`
- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:1426`

**影响**

- 这些页面/接口会出现“明明有权限但被判没有”的问题
- 对部门管理员、间接授权用户影响尤其大，因为他们更依赖 ReBAC 实时计算

---

## C. Workflow / Assistant / Tool / App 资源问题

### PA-008 workflow 版本读取接口缺少权限校验

**现象**

- `get_version_list_by_flow()` 没校验调用方是否能读该 workflow
- `get_version_info()` 也没校验

**证据**

- `src/backend/bisheng/api/services/flow.py:33`
- `src/backend/bisheng/api/services/flow.py:46`
- `src/backend/bisheng/api/v1/workflow.py:203`
- `src/backend/bisheng/api/v1/workflow.py:243`

**影响**

- 已登录用户只要知道 `flow_id` / `version_id` 就能读取版本列表和版本详情
- 这是直接越权读口子

### PA-009 workflow 删除后不会清理 OpenFGA 元组

**现象**

- workflow 创建时会写 owner tuple
- 删除时 `delete_flow_hook()` 没有清理 FGA tuples

**证据**

- `src/backend/bisheng/api/services/flow.py:286`
- `src/backend/bisheng/api/services/flow.py:308`
- `src/backend/bisheng/api/v1/flows.py:28`

**影响**

- FGA 中遗留脏 `owner/editor/viewer/shared_with` 元组
- 后续若资源 ID 被复用、审计查询、权限核对，都会出现脏数据

### PA-010 assistant 列表 `write` 标记没有按 ReBAC 写权限算

**现象**

- assistant 列表里 `write` 只按“自己创建”或“系统管理员”来算
- 没有使用 `ASSISTANT_WRITE` / `can_edit`

**证据**

- `src/backend/bisheng/api/services/assistant.py:73`

**影响**

- 被显式授予 assistant 编辑权限的用户，列表 UI 仍会显示不可编辑
- 详情接口可能能进，列表按钮却灰掉

### PA-011 `FlowDao.get_user_access_online_flows()` 仍完全走旧 `role_access`

**现象**

- 这个函数没有接 ReBAC，仍直接查 `RoleAccessDao.get_role_access(...)`

**证据**

- `src/backend/bisheng/database/models/flow.py:314`

**影响**

- assistant 自动选 workflow 的能力仍基于旧 RBAC 可见性
- 新 ReBAC 授权出去的 workflow 可能在这类场景里完全不可见

### PA-012 `workstation` 推荐应用接口存在双重问题

**现象**

- 用了不存在的 `AccessType.FLOW`
- 即便去掉 `FLOW`，`get_user_access_resource_ids([a, b, c])` 也只会取第一个已映射类型，不会做多类型并集

**证据**

- `src/backend/bisheng/workstation/api/endpoints/apps.py:41`
- `src/backend/bisheng/user/domain/services/auth.py:303`

**影响**

- 推荐应用接口的权限过滤本身就是错的
- workflow / assistant 混合列表会天然漏资源

### PA-013 workflow 创建已接入 `share_on_create`，但删除未对称清理共享元组

**现象**

- workflow 创建时已经接了 `share_on_create_sync`
- 但删除仅删 DB 和 version，不删 FGA / shared_with

**证据**

- `src/backend/bisheng/api/v1/workflow.py:185`
- `src/backend/bisheng/api/v1/workflow.py:191`
- `src/backend/bisheng/api/services/flow.py:308`

**影响**

- 同一个资源的“创建路径”和“删除路径”不对称
- shared resource 相关的 tenant 共享状态更容易残留脏数据

---

## D. Knowledge / Knowledge Space 资源问题

### PA-014 知识空间成员角色变更只改 membership，不同步 FGA

**现象**

- `update_member_role()` 只更新 `space_channel_member.user_role`
- 没像 channel 那样执行“撤销旧 relation + 授予新 relation”

**证据**

- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1106`
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1156`

**影响**

- 成员升为管理员后，FGA 里可能仍是 `viewer`
- 管理员降回成员后，FGA 里可能还残留 `manager`
- 列表显示角色和实际鉴权结果会漂移

### PA-015 知识空间“我的创建 / 我的管理 / 我的关注”列表主要走 membership，不走 ReBAC 结果

**现象**

- `get_my_created_spaces()`
- `get_my_managed_spaces()`
- `get_my_followed_spaces()`

都直接基于 `SpaceChannelMemberDao`

**证据**

- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:950`

**影响**

- 通过资源权限 API 直接授予给用户 / 部门 / 用户组的知识空间，详情可能能打开，但“我的列表”里不会出现
- 新 ReBAC 与旧 membership overlay 会出现双轨结果

### PA-016 QA 知识库的“写权限 helper”实际只检查了读权限

**现象**

- `judge_qa_knowledge_write()` 名字叫 write
- 实际检查的是 `AccessType.KNOWLEDGE`，不是 `KNOWLEDGE_WRITE`

**证据**

- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:1409`
- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:1416`

**受影响接口**

- `GET /qa/list/{qa_knowledge_id}`
- `GET /qa/export/{qa_knowledge_id}`
- `POST /qa/import/{qa_knowledge_id}`

**证据**

- `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:390`
- `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:637`
- `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:745`

**影响**

- 只读用户可能进入本该要求写权限的 QA 管理接口

### PA-017 组织知识库检索路径仍走旧 RBAC

**现象**

- `KnowledgeRag.get_multi_knowledge_vectorstore()` 对 organization knowledge 仍调用 `KnowledgeDao.ajudge_knowledge_permission()`
- 后者本质还是：
  - owner
  - `role_access`
  - 不是真正的 ReBAC / OpenFGA

**证据**

- `src/backend/bisheng/knowledge/domain/knowledge_rag.py:180`
- `src/backend/bisheng/knowledge/domain/models/knowledge.py:380`

**影响**

- 工作台知识检索、组织知识引用场景中，组织知识的权限结果仍会受旧 RBAC 影响
- 新授予的 department/user_group ReBAC 关系在这条检索链上可能失效

### PA-018 知识服务中仍有多处 async 方法直接调用 sync `access_check()`

**现象**

- 本轮已确认一些 async 方法仍直接走 sync `access_check()`

**已确认调用点**

- `rebuild_knowledge_file()`
- `batch_download_files()`

**证据**

- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:740`
- `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:1426`

**影响**

- 会继承 PA-006 的 timeout / 误判问题
- 表现为知识文件重建、批量下载等管理操作偶发性“没权限”

### PA-019 `KnowledgeDao.judge_knowledge_permission()` 仍是对外真实运行逻辑，不只是遗留代码

**现象**

- 该函数仍被 `KnowledgeRag` 真实调用
- 逻辑只认 owner + `role_access`

**证据**

- `src/backend/bisheng/knowledge/domain/models/knowledge.py:341`
- `src/backend/bisheng/knowledge/domain/knowledge_rag.py:158`

**影响**

- 这意味着知识库权限当前并没有完成“全链路切到 ReBAC”
- 至少检索链仍然会被旧表覆盖

---

## E. Channel 资源问题

### PA-020 channel 详情 / 管理 / 成员接口仍主要按 membership 和 visibility 判断，不走 ReBAC

**现象**

以下接口/服务逻辑主要看 `space_channel_member` 和 `channel.visibility`：

- `list_channel_members()`
- `update_member_role()`
- `remove_member()`
- `update_channel()`
- `dismiss_channel()`
- `get_channel_detail()`

**证据**

- `src/backend/bisheng/channel/domain/services/channel_service.py:390`
- `src/backend/bisheng/channel/domain/services/channel_service.py:459`
- `src/backend/bisheng/channel/domain/services/channel_service.py:595`
- `src/backend/bisheng/channel/domain/services/channel_service.py:886`
- `src/backend/bisheng/channel/domain/services/channel_service.py:1035`
- `src/backend/bisheng/channel/domain/services/channel_service.py:1248`

**影响**

- channel 虽然已经进入 `VALID_RESOURCE_TYPES`
- 也能通过资源权限 API 授 `owner/manager/editor/viewer`
- 但大量 channel 实际接口根本不认这些关系

### PA-021 direct ReBAC grants 在 channel 上基本不会产生完整业务效果

**现象**

- 如果通过资源权限 API 给某用户 / 部门 / 用户组直接授 `channel.viewer` 或 `channel.manager`
- 该用户未必有 `space_channel_member`
- channel 详情和成员管理服务仍按 membership/visibility 判

**证据**

- `src/backend/bisheng/channel/domain/services/channel_service.py:1046`
- `src/backend/bisheng/channel/domain/services/channel_service.py:468`
- `src/backend/bisheng/channel/domain/services/channel_service.py:604`

**影响**

- 会出现“FGA 中有权限，但业务服务不承认”的现象
- channel 是当前最明显的“接了 ReBAC schema，但业务层没真正接”的模块

### PA-022 `get_my_channels()` 只从 membership 找数据，不从 ReBAC 找数据

**现象**

- `get_my_channels()` 先查 `find_channel_memberships()`
- 然后再按 `query_type` 和 visibility 过滤
- 完全不使用 `PermissionService.list_accessible_ids()`

**证据**

- `src/backend/bisheng/channel/domain/services/channel_service.py:224`

**影响**

- 通过 direct grant / department / user_group 拿到 channel 权限的用户，“我的频道”列表中可能完全看不到该资源

### PA-023 `channel detail` 对 private channel 的判断仍是“是不是 member”，不是“有没有 can_read”

**现象**

- 若当前用户不是 active membership
- private channel 直接拒绝
- 没有再检查 `PermissionService.check(can_read)`

**证据**

- `src/backend/bisheng/channel/domain/services/channel_service.py:1046`

**影响**

- 直接 ReBAC 授权给用户的 private channel，在 detail 接口上仍不可见

---

## F. 旧 RBAC / Group Resource 仍在真实运行

### PA-024 `role_access` 仍有对外可写接口

**现象**

- 仍存在 `/role_access/refresh`
- 仍存在 `/role_access/list`

**证据**

- `src/backend/bisheng/user/api/user.py:659`
- `src/backend/bisheng/user/api/user.py:679`

**影响**

- 旧 RBAC 表并不是“纯历史归档”
- 后台仍可继续修改旧权限数据
- 会持续制造“新旧逻辑同时在变”的混乱状态

### PA-025 `role_access/list` 的 `type` 过滤参数实际上失效

**现象**

- 入参 `access_type` 在函数内部被直接重置为 `None`

**证据**

- `src/backend/bisheng/user/api/user.py:680`
- `src/backend/bisheng/user/api/user.py:689`

**影响**

- 旧权限排查接口本身返回值就不可信
- 会进一步放大排障成本

### PA-026 `group_resource` 不是遗留摆设，而是在真实驱动资源管理页

**现象**

- 用户组资源页仍直接按 `GroupResourceDao` 查资源
- group 删除/迁移时也仍在搬运 `group_resource`

**证据**

- `src/backend/bisheng/api/v1/usergroup.py:128`
- `src/backend/bisheng/api/services/role_group_service.py:283`
- `src/backend/bisheng/api/services/role_group_service.py:123`

**影响**

- 用户组资源管理仍是旧授权模型
- 与 ReBAC 的资源授权是并行、重叠、可互相覆盖的

### PA-027 `FlowDao.get_user_access_online_flows()` 与 `KnowledgeDao.judge_knowledge_permission()` 仍在真实业务中读取旧 RBAC

**现象**

- `workflow` 的老可见性函数仍读 `RoleAccessDao`
- `knowledge` 的老可见性函数仍读 `RoleAccessDao`

**证据**

- `src/backend/bisheng/database/models/flow.py:314`
- `src/backend/bisheng/knowledge/domain/models/knowledge.py:341`

**影响**

- 不是“只剩管理页没迁完”
- 而是运行时业务流里仍有真实旧 RBAC 决策

---

## G. 新旧逻辑覆盖的典型表现

下面这些现象在当前代码结构下是高概率发生的：

1. 详情接口能进，列表没有
2. FGA 已授 `manager`，但页面按钮仍灰
3. membership 已降级，FGA 里仍保留旧高权限
4. old RBAC 表改了，某些老路径立刻生效；但新路径完全无感知
5. department / user_group 授权改了，缓存还保留旧值
6. child tenant admin 在“能访问”和“能授权”两个接口上结果不一致
7. channel / knowledge space / workflow / assistant / tool 的权限行为不在同一抽象层

---

## H. 高风险空白与待补审点

以下内容本轮已经看到风险，但还没有完全展开到每个 endpoint / service：

### GAP-001 dashboard 接入面可疑

当前可以确认：

- OpenFGA model 已包含 `dashboard`
- `AccessType -> ReBAC` 映射里也有 `dashboard`

但本轮在已审代码中没有找到与 `dashboard` 对应的完整资源服务接入链路。

**结论**

- `dashboard` 很可能存在“schema 先建了，但业务层还没真正接完整”的问题
- 需要单独补审 `telemetry_search/domain/services/dashboard.py` 及其 API

### GAP-002 channel / knowledge_space 的 direct grant 与 membership overlay 的边界未统一

本轮已经确认：

- detail / manage / list 很多地方仍看 membership
- 资源权限 API 可以直接写 FGA relations

但“产品上是否要求 direct grant 自动投影到 membership overlay”这件事，在当前实现中没有统一答案。

**结论**

- 这不是单个 bug，而是权限语义层未收口

### GAP-003 `permissions[]` 细粒度动作与资源运行时仍非全链路统一

知识空间已经开始把 relation model 的 `permissions[]` 纳入部分运行时动作判断。

但从全仓库看：

- 并不是所有资源模块都进入了这一层
- relation level 与 `permissions[]` 的关系在不同模块并不一致

**结论**

- 需要后续单独做一次“relation model / permission template / runtime action check”的全链路审计

---

## 本文件结论

本轮审计确认的核心事实是：

1. 当前仓库不是“已经切到统一 ReBAC 权限模型”
2. 而是“ReBAC、legacy RBAC、membership overlay、group_resource”四套结构并存
3. 不同资源模块接入程度不同：
   - `knowledge_space` 部分接入较深
   - `assistant / workflow / tool` 基础接入已有，但列表与管理层不完整
   - `channel` 仍明显以 membership/visibility 逻辑为主
4. 部分接口存在直接越权口子
5. 部分接口存在读写档位判断错误
6. 列表、详情、授权弹窗、成员管理，并不保证来自同一套真实权限判断

如果后续要进入集中修复阶段，这份文档可以直接作为问题拆解底稿使用。
