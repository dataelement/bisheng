# 任务清单：平台管理员（运营岗）

| 文档 | 状态 |
|---|---|
| `design.md` | 已确认 |
| `acceptance-test-cases.md` | 已确认 |
| `tasks.md` | 已拆解 |

- Feature: `056-platform-operator-role`
- 关联：`specs/056-platform-operator-role/design.md`、`acceptance-test-cases.md`
- 无 `spec.md`：验收标准以 AT-xx 为准（等同 AC）
- 仓：毕昇 `feat-2.5.0-sg-issue-3` + 门户 `dev-issue-3`
- 无 DDL；无 Client 改动；无 Worker/Celery 新任务
- 后端 Test-First：测试任务不得混入实现。写库 P0 必须 171 MySQL 流转（接口 + SELECT + 再打一枪）
- 禁止把「平台管理员」并入门户 `ADMIN_ROLES` / `isPortalAdmin`；禁止把 `can_platform_operate` 写进 `is_admin()` / `get_admin_user`

常量（两仓同一字面量）：`PLATFORM_OPERATOR_ROLE_NAME = "平台管理员"`

---

## Phase 0 — 基础设施 / 身份 helper（毕昇）

- [x] T001 毕昇：写运营身份 helper 单测
  - Done when: 新测试文件在 helper 尚不存在或未实现时失败；覆盖精确匹配与反例。
  - 覆盖 AC: AT-03
  - 验证: `cd src/backend && uv run pytest test/user/test_platform_operator_identity.py -k helper --coverage=false`（或项目既有 pytest 命令）
  - 边界: 仅 `src/backend/test/user/test_platform_operator_identity.py`
  - 逻辑: `has_platform_operator_role`：`平台管理员` true；trim 后全等 true；`管理员` / `系统管理员` / `admin` / `xx平台管理员` false。`can_platform_operate`：超管 true、运营岗 true、普通用户 false。`is_admin()` 不因运营岗变 true。

- [x] T002 毕昇：实现运营身份 helper
  - Done when: T001 绿；`is_admin()` 未改语义。
  - 覆盖 AC: AT-03
  - Depends: T001
  - 边界: 仅新建 `src/backend/bisheng/user/domain/services/platform_operator.py`（中文 docstring）。`common/` 不引用 domain。
  - 产出: `PLATFORM_OPERATOR_ROLE_NAME`、`has_platform_operator_role(user)`（读 `role_names`）、`can_platform_operate(user)` = `is_admin()` 或 `is_global_super` 或前者。

---

## Phase 1 — 身份下发与保留名（毕昇）

- [x] T003 毕昇：写 `/user/info` 与 `get_admin_user` 测试
  - Done when: 夹具 U-ops 在实现前失败（`role` 仍是 id 列表或 `get_admin_user` 误放行）。
  - 覆盖 AC: AT-10, AT-11, AT-81
  - Depends: T002
  - 边界: 扩 `test/user/test_platform_operator_identity.py`（或同目录新测，不超过该文件）。171 若需真实登录则走现网 user fixture。
  - 逻辑: U-ops：`role=平台管理员`，`role_names` 含该名，非 `admin`。U-ops Cookie `PUT /api/v1/shougang-portal/config` 改 domains → 403，`config` 行不变，再读导航不变。同时绑 AdminRole+运营岗 → `role=admin` 且 `is_admin()` true。

- [x] T004 毕昇：下发 `role` / `role_names`
  - Done when: T003 绿。
  - 覆盖 AC: AT-10, AT-11, AT-81
  - Depends: T003
  - 边界: `src/backend/bisheng/user/api/user.py`（`_user_info_role_label`）、`src/backend/bisheng/user/domain/models/user.py`（`UserRead.role_names`）。不改 `get_admin_user`。
  - 逻辑: 优先级 AdminRole→`admin`；否则 `role_names` 含保留名→`平台管理员`；否则原门户整页名。响应增加 `role_names`。

- [x] T005 毕昇：写保留名与 WEB_MENU 剥离测试
  - Done when: 实现前失败。
  - 覆盖 AC: AT-01, AT-02, AT-04, AT-90
  - Depends: T002
  - 边界: 仅新文件 `src/backend/test/role/test_platform_operator_reserved_name.py`。171 MySQL。
  - 逻辑: 超管创建「平台管理员」落 `role`；同租户任意 department 再创建 → 24002，行数仍 1；可与「管理员」并存；改名/删除 → 24004，`role_name` 不变；保存 WEB_MENU 含 `board`/`sys` 后 `roleaccess` 无这些 `third_id`。

- [x] T006 毕昇：RoleService 保留名 + 剥离管理端菜单
  - Done when: T005 绿。
  - 覆盖 AC: AT-01, AT-02, AT-04, AT-90
  - Depends: T005
  - 边界: `src/backend/bisheng/role/domain/services/role_service.py`（创建/更新/删除/存菜单）。不改 `role` 表结构。
  - 逻辑: 租户内保留名跨 scope 唯一；该名角色禁止改名/删除；保存 WEB_MENU 丢掉 design 所列管理端 key，只留工作台。

---

## Phase 2 — 毕昇写闸门（Test-First，171 流转）

- [x] T007 毕昇：写积分运营流转测试
  - Done when: U-ops 调账在实现前 18201。
  - 覆盖 AC: AT-21, AT-48, AT-80
  - Depends: T002
  - 边界: 仅新文件 `src/backend/test/points/test_platform_operator_points_admin.py`。禁止追加巨石。171 MySQL。
  - 逻辑: U-ops `POST /api/v1/points/admin/adjust` → 200，`user_point_log.delta` 与余额一致；再 GET detail 与表一致。U-user 同一接口 18201，log 行数不变。解绑 `userrole` 后再 adjust → 18201，无新 log。断言 `is_platform_super_admin(U-ops)` 仍 false。若存在专家问答超管删除/扣分接口，U-ops 调用须 403 或 18201 且问答/积分表无脏行（AT-48）。

- [x] T008 毕昇：积分管理改认 `can_platform_operate`
  - Done when: T007 绿；专家问答超管判定仍用 `is_platform_super_admin`。
  - 覆盖 AC: AT-21, AT-48, AT-80
  - Depends: T007
  - 边界: `src/backend/bisheng/points/domain/services/points_auth.py`。`require_platform_admin` 改为 `can_platform_operate`；**不要**把运营岗并入 `is_platform_super_admin`。
  - 影响: 所有调用 `require_platform_admin` 的积分 admin 写/读；`test_department_org_level.py` 夹具若只 mock `is_admin` 需能过（可在本任务补 import/夹具，不改产品语义）。

- [x] T009 毕昇：写迁移全库流转测试
  - Done when: U-ops 建批在实现前 403。
  - 覆盖 AC: AT-22, AT-23
  - Depends: T002
  - 边界: 新文件 `src/backend/test/knowledge/test_platform_operator_migration.py`。不把新逻辑追加进巨石 knowledge 测试。171 MySQL。
  - 逻辑: U-ops `GET /api/v1/knowledge/migrations/spaces` 含非本人库（与超管同一口径）；`POST /batches` 落 `knowledge_migration_batch`，操作者 U-ops；再 GET batch_no 仍在。U-user 建批 403，表无新行。

- [x] T010 毕昇：迁移闸门扩运营岗
  - Done when: T009 绿；账号名/`管理员` 旁路仍 403。
  - 覆盖 AC: AT-22, AT-23
  - Depends: T009
  - 边界: `src/backend/bisheng/knowledge/domain/services/knowledge_migration_service.py` 的 `require_system_admin`。同步改 `src/backend/test/knowledge/test_knowledge_migration_auth.py`：运营岗（`role_names`）通过；`account=admin` 且 `is_admin` false 仍拒。

- [x] T011 毕昇：写字典流转测试
  - Done when: U-ops 创建字典在实现前 19102。
  - 覆盖 AC: AT-29
  - Depends: T002
  - 边界: 新文件 `src/backend/test/dictionary/test_platform_operator_dictionary.py`。171 MySQL。
  - 逻辑: U-ops `POST /api/v1/dictoption/create` → `system_dictionary` 新行；再按 type GET 见该行。U-user 19102，无新行。

- [x] T012 毕昇：字典 `_ensure_admin` 改认运营岗
  - Done when: T011 绿。
  - 覆盖 AC: AT-29
  - Depends: T011
  - 边界: `src/backend/bisheng/dictionary/domain/services/dictionary_service.py`

- [x] T013 毕昇：写看板 / 标签 / 敏感词 / 审批未扩测试
  - Done when: 实现前 U-ops 看板列表窄于超管或敏感词 19801。
  - 覆盖 AC: AT-30, AT-47
  - Depends: T002
  - 边界: 新文件 `src/backend/test/workstation/test_platform_operator_tag_and_sensitive.py`（敏感词+tag）；看板断言可同文件或 `test/telemetry_search/` 下新小文件（合计本任务 ≤2 文件）。171 能连则查 `sensitive_word_policy`。
  - 逻辑: U-ops 看板列表范围等同超管；敏感词 GET/PUT 200，PUT 后表一致再 GET。tag-console 管理接口一成功。U-user 未授权。抽一条现网审批/系统超管 API，U-ops 仍 403。

- [x] T014 毕昇：看板列表/写按 `can_platform_operate`
  - Done when: T013 中看板断言绿。
  - 覆盖 AC: AT-30
  - Depends: T013
  - 边界: `src/backend/bisheng/telemetry_search/domain/services/dashboard.py`（现 `is_admin()` 列表与实时写）。只扩运营资格，不改分享/部门管理员其它分支语义。

- [x] T015 毕昇：tag console + 敏感词策略认运营岗
  - Done when: T013 中标签/敏感词绿；`get_tenant_admin_user` 全局语义不变。
  - 覆盖 AC: AT-30, AT-47
  - Depends: T013
  - 边界: `src/backend/bisheng/workstation/domain/services/tag_console_service.py` 的 `_ensure_can_manage_tags`；`src/backend/bisheng/sensitive_word/api/endpoints/policies.py` 改为 `get_login_user` + `can_platform_operate`（**不要**扩大 `get_tenant_admin_user`）。

---

## Phase 3 — 门户 BFF ACL（门户仓）

- [x] T016 门户：写身份会话 + 模块 ACL 流转测试
  - Done when: U-ops 在实现前进不了 `/admin` 配置或误拿到全量密钥。
  - 覆盖 AC: AT-12, AT-24, AT-25, AT-26, AT-27, AT-28, AT-40, AT-41, AT-42, AT-43, AT-44, AT-45, AT-46, AT-91
  - Depends: T004
  - 边界: 新文件 `backend/tests/test_platform_operator_admin_acl.py`（门户仓）。不要把断言塞进巨石后整文件跑。落库查毕昇 `config` / 课程表 / 回收。171。
  - 逻辑:
    - 会话 `role` 或 `role_names` 为运营岗；`is_portal_admin_role('平台管理员')` false。
    - 允许：POST `/api/v1/admin/config/qa`（含 templates）、`/agent-config`、`/document-types`、`/watermark` → 200，对应 JSON 块变、`domains` 不变；再 GET 一致。
    - 禁止：POST domains / recommendation / search / banners / display、课程写、自动发布、科室绑定、回收站写、GET/POST site / bisheng / integrations / unified-auth / rest-auth、**GET 全量 `/admin/config`** → 403，body 无密码/token，目标块/表不变，再打一枪仍不变。

- [x] T017 门户：会话透传 `role_names` + 运营岗判定
  - Done when: AT-12 会话断言绿；`ADMIN_ROLES` 仍为三元。
  - 覆盖 AC: AT-12, AT-91
  - Depends: T016
  - 边界: `backend/app/schemas/auth.py`、`backend/app/services/portal_auth_service.py`、`backend/app/api/dependencies.py`。不把保留名加入 `ADMIN_ROLES`。
  - 产出: `is_platform_operator`；`can_enter_admin_shell`；`require_ops_module_session` / 按 path 的依赖（地图可放 `dependencies.py`）。

- [x] T018 门户：`admin_config` 与课程/回收站/上传分路
  - Done when: T016 绿。
  - 覆盖 AC: AT-24, AT-25, AT-26, AT-27, AT-28, AT-40, AT-41, AT-42, AT-43, AT-44, AT-45, AT-46
  - Depends: T017
  - 边界: `backend/app/api/routes/admin_config.py`（去掉 router 整组 `require_admin_session`，按 path 挂依赖）；课程/回收站文件保持仅整页管理员；`admin_upload.py` 允许 `can_enter_admin_shell`。
  - 逻辑: 全量 GET/POST `""` 仅整页管理员。允许名单 path 见 design §4.3。BFF 仍用服务账号写毕昇 `config`，用户 Cookie 不能靠本任务放开 `get_admin_user`。

---

## Phase 4 — 门户前端

- [x] T019 门户：写 adminAccess / Header / 迁移路由单测
  - Done when: 实现前 `isPortalAdmin('平台管理员')` 仍 false 且 `/admin` 壳进不去或迁移入口仍关。
  - 覆盖 AC: AT-50, AT-52, AT-53, AT-54, AT-48, AT-71
  - 边界: 扩 `frontend/tests/adminAccess.test.ts`、`frontend/tests/knowledgeMigrationAccess.test.ts`（门户仓，2 文件）。
  - 逻辑: `isPortalAdmin` 不含该名；`canEnterAdminShell` 含该名。`canViewMigrations` 含运营岗与系统管理员。`isPlatformSuperAdmin` / 专家问答违规删 **不含** 运营岗。「管理员」整页资格回归仍 true。U-user / U-anon 行为保持。

- [x] T020 门户：adminAccess + Header + 迁移路由
  - Done when: T019 绿。
  - 覆盖 AC: AT-50, AT-52, AT-48
  - Depends: T017, T019
  - 边界: `frontend/src/utils/adminAccess.ts`、`frontend/src/components/Header.tsx`、`frontend/src/App.tsx`（KnowledgeMigrationsRoute / AdminRoute）。
  - 逻辑: Header「知识管理后台」用壳资格；迁移用 `canViewMigrations`；回收站/毕昇外链仍 `isPortalAdmin`。`/admin` 壳允许运营岗。映射 `PortalUser.roleNames`。

- [x] T021 门户：AdminPage 11 项菜单、直链、loadConfig
  - Done when: 运营岗只渲染 11 项中 1–10；禁止 section 无权限；不请求 `/bisheng`、`/rest-auth`、全量 config。
  - 覆盖 AC: AT-20, AT-51, AT-45
  - Depends: T020
  - 边界: `frontend/src/pages/AdminPage.tsx`（只动导航过滤、section 守卫、`loadConfig`；不重构整页）。
  - 逻辑: 允许名单 key 见 design 11 项。`?section=site|domains|...` 无权限页且不发禁止 API。外链「毕昇管理后台」对运营岗不展示。

---

## Phase 5 — 毕昇 Platform standalone

- [x] T022 Platform：写 standalone 白名单单测
  - Done when: 实现前无管理端 WEB_MENU 的用户在 standalone 三页仍会被踢（用纯函数测路径判定，不测真浏览器亦可）。
  - 覆盖 AC: AT-60, AT-62
  - 边界: `src/frontend/platform/src/test/` 下新小文件（路径白名单函数）。若必须改 `userContext.tsx` 才能抽函数，本任务只写失败测试 + 约定导出名 `isPlatformOperatorStandalonePath`。
  - 逻辑: `/standalone/dashboard`、`/knowledge-tag-library`、`/content-security`（含子路径 dashboard/:id）为白名单；`/standalone/approval`、`/sys`、`/log`、有壳 `/dashboard` 否。

- [x] T023 Platform：`userContext` 对白名单跳过踢走
  - Done when: T022 绿；非白名单 standalone 与有壳管理页仍踢 workspace 或 403。
  - 覆盖 AC: AT-60, AT-62, AT-63
  - Depends: T004, T022
  - 边界: `src/frontend/platform/src/contexts/userContext.tsx`；路径判断放 `src/frontend/platform/src/routes/standalone.ts`（已有 `isStandalonePath`，可加白名单集合）。
  - 逻辑: 白名单且已登录 → 不因 `canAccessPlatform=false` 而 `location.replace(workspace)`。不给运营岗管理端 WEB_MENU。

---

## Phase 6 — 回归与手测

- [x] T024 跑 P0 自动化（171）
  - Done when: 上列新测 + 被改调用方测绿；超管积分/迁移/POST domains 回归仍绿（AT-70）。
  - 覆盖 AC: AT-70
  - Depends: T008, T010, T012, T014, T015, T018, T021, T023
  - 边界: 只跑本特性相关 pytest/npm test，不跑全仓无关套件。记录命令与结果（可写本目录 `verification.md`）。
  - 调用方: `test/points/test_department_org_level.py`、`test/knowledge/test_knowledge_migration_auth.py`、门户 `adminAccess.test.ts`。

- [ ] T025 UI 手测清单（无稳定 iframe E2E，测试降级）
  - Done when: 书面记录 U-ops 实点结果；未跑的不勾完成。
  - 覆盖 AC: AT-20, AT-51, AT-60, AT-62, AT-63, AT-71
  - Depends: T021, T023
  - 降级理由: 三 iframe 依赖门户+Platform Cookie 同源与登录态，仓库无现成 Playwright 覆盖 standalone。
  - 手测: `/admin` 仅 11 项菜单；直链 site 无权限；三条 standalone 能开且接口可用；改 URL 进 approval/sys 失败；超管/整页管理员菜单全开。

---

## AT 覆盖表（防漏）

| AT | 测试任务 |
|---|---|
| AT-01, AT-02, AT-04, AT-90 | T005 |
| AT-03 | T001 |
| AT-10, AT-11, AT-81 | T003 |
| AT-12, AT-24～AT-28, AT-40～AT-46, AT-91 | T016 |
| AT-20, AT-51, AT-45（前端） | T021, T025 |
| AT-21, AT-48, AT-80 | T007, T019 |
| AT-22, AT-23 | T009 |
| AT-29 | T011 |
| AT-30, AT-47 | T013 |
| AT-48, AT-50, AT-52, AT-53, AT-54, AT-71 | T019 |
| AT-60, AT-62 | T022, T025 |
| AT-63 | T023, T025 |
| AT-70 | T024 |

---

## 实际偏差记录

- T003：`UserRead` / `LoginUser.get_admin_user` 受 conftest premock 影响，不能在测试里直接实例化 `UserRead` 或原样 `raise UnAuthorizedError.http_exception()`；改为测 `collect_user_info_role_names` + 源码字段，以及 patch `http_exception` 后断言 403。`PUT /shougang-portal/config` 的 171 流转放到后续闸门任务，本任务覆盖身份下发与 `get_admin_user` 仍只认 `is_admin()`。
- T008：`require_platform_admin` 扩运营岗后，专家问答 `moderate_delete` 若继续调用它会误放行。按 AT-48 / design，该接口改为 `is_platform_super_admin`（`qa_expert/domain/moderate_delete_service.py`），不把运营岗并入超管判定。
- T009：pytest premock 了 `user.domain.models.user.User`，真实 `list_spaces` 的 User join 跑不起来。GET 全库口径用 mock 返回「本人库 + 非本人库」；POST 建批 mock `_normalize_create` 与 Celery dispatcher，真实 Repository 写 171 `knowledge_migration_batch`，再 SELECT / GET batch_no。
- T011：生产挂载是 `/api/v1/dictionaries/dictoption/create`；AT 写的是 `/api/v1/dictoption/create`。流转测按 endpoint 自身 prefix（AT 路径）挂载，闸门与落库表相同。
- T015：敏感词 endpoint 改为 `get_login_user` + `can_platform_operate`，错误码仍 19801（`LLMModelSharedReadonlyError`）。不改 `get_tenant_admin_user`。看板 `is_admin()` 全部改为 `_can_operate_dashboards()`，运营岗列表/实时写与超管同口径。
- T016：门户配置 ACL 走 `PortalConfigService` 内存/文件 store（与 `test_admin_config_api` 同口径），不拿用户 Cookie PUT 毕昇全量 `config`。课程/回收站禁止路径断言 403，不打现网毕昇表。
- T018：`require_admin_config_session` 与 `require_admin_session` 同一函数对象，按 path 分路（整页管理员全放行，运营岗仅 design §4.3 允许名单）。课程/回收站仍挂 `require_admin_session`（path 不在名单 → 运营岗 403）。`admin_upload` 改挂 `require_admin_shell_session`（`can_enter_admin_shell`）。未给 80 个路由逐个 Depends。
- T020：Header「知识管理后台」改为 `navigate('/admin')`，不再 `window.open(bisheng_admin_entry_url)`；回收站仍 `isPortalAdmin`。`canViewMigrations` = 系统管理员 ∪ 运营岗，「管理员」角色仍不能进迁移（与改前一致）。
- T021：运营岗 `loadConfig` 只 GET `/qa` `/agent-config` `/document-types` `/watermark`；不请求全量 config / `/bisheng` / `/rest-auth`。`?section=` 无权限时主区「无权限访问该模块」，左侧外链「BiSheng 管理后台」对运营岗隐藏。
- T023：无管理端 WEB_MENU 时已登录走 `resolveNoAdminConsoleAction`（白名单 fall through，其它 standalone 进 `/403`，有壳管理页仍踢 workspace）；未登录（无 `user_id`）仍踢走，不把无 session 留在 iframe。
- T024：命令与结果见同目录 `verification.md`。AT-70 用调用方测 + 门户 `test_post_admin_domains_updates_persisted_config` / `test_post_admin_bisheng_config_updates_runtime_without_echoing_secret`，未跑全仓。
- T025：2026-08-28 本地栈未起（7860/8010/4001/3001/5173 down），手测未实点，不勾完成。清单写在 `verification.md`。

