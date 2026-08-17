# Tasks: 应用广场接入与治理面（RT-02 广场 + GOV-01 授权交互 + GOV-04 审计登记）

**关联规格**: [spec.md](./spec.md)（45 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D11 / K1–K11 / 坑 1–21 / §4.2 契约）
**版本**: v3.0.0
**纵切**: [mvp-114-path.md](../mvp-114-path.md) **§6 MVP-核心 F056 行**是本轮裁剪基准——Wave 1–2 全部为 `[MVP-核心]`（广场接入 + 两入口授权与「仅 owner 可见」提示 + 三类审计事件可查），Wave 3–4 为顺延项（release 仍必做，只列标题 / 文件 / 覆盖 AC，不展开）
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe` HEAD `11e1b211d`，2026-08-17 核实）。路径以 `src/backend/bisheng/` 为根；前端另注 `client/` = `src/frontend/client/src/`、`platform/` = `src/frontend/platform/src/`。**行号会漂、符号名不会**——落地前一律以符号名重定位（F054 Wave 3 落地后 platform 前端行号必漂）。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 初稿 + 同日独立审查修订（45 AC、11 决议，跨 Feature 归属规则全文改写） |
| design.md | ✅ 已评审 | 2026-08-17 初版 + 同日 `/sdd-review design` 14 条修订（D1–D11 / K1–K11 / 坑 21 条）；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-08-17） | 本文（33 任务 / 4 Wave / 21 条 `[MVP-核心]`）；2026-08-17 初稿 + 同日 `/sdd-review tasks` 15 条修订（审计租户字段口径、client i18n、`objectTypeEnum.app` 新增认领、T009/T011 实现手段写死、夹具与追溯口径） |
| 实现 | 🟡 进行中（2026-08-18） | **19 / 33 完成**；`[MVP-核心]` 21 条中完成 19（T001–T015 / T017–T020），未完成 2：**T016**（集成测试需 MySQL / Redis / OpenFGA，本地无中间件，CI 跑）、**T021**（114 部署与人工验收）。Wave 3–4 顺延 12 条未启。偏差见文末「实际偏差记录」 |

---

## 开发模式

**按 Wave 组织任务**：
- **Wave 1（`[MVP-核心]` 后端）**：审计 action 四处 lockstep 中的后端两处与前端两处（登记先行，否则事件写了查不到）→ 广场动作集两层裁剪 → DAO 状态豁免参数 → 广场载荷补 `slug` / `app_state` 与两入口状态收窄 → 应用中心路径排除 → 可见范围变更审计回调。
- **Wave 2（`[MVP-核心]` 前端 + 114）**：Client 广场卡片与跳转；Platform 可见范围区与授权弹窗第二触发点；114 手动验证清单（**必须用非管理员账号**）。
- **Wave 3–4（顺延）**：审计查询面「对象应用」筛选 / 导出 / 超管租户筛选；GOV-07 界面通道验收；⚙️ 裁剪与标签接入回归；§3.0.3 事件触达。按 `mvp-114-path.md` §6 排在 MVP-核心之后，**属本 Feature 范围、不得被裁掉**。

每个任务标 `依赖:`，无依赖的可并行。

**后端 Test-First**：测试任务先于其配对实现任务，`覆盖 AC` 逐条列举（禁 `AC-01~AC-05` 范围写法）。基础设施任务（审计常量登记、上游协调）无测试配对、排最前。单测放 `src/backend/test/workflow/`（既有目录，`test/` 根不放新文件），`asyncio_mode=auto`；集成测试连 test 中间件（MySQL / Redis / OpenFGA）在 CI 跑。

**验收账号红线（贯穿全部测试与手动验证）**：
- 广场 / 权限相关一律用**非管理员、非 owner 的普通账号**——`_identity_shortcut`（`permission/domain/services/permission_action_service.py:372-384`）对 `SUPER_ADMIN` / `TENANT_ADMIN` 与 action 无关地放行，且发生在动作合法性校验**之前**（design K2）：管理员账号**必然通过**，拿它当证据等于没测。
- 审计查询一律用 `is_admin()` 或持「日志菜单」权限的账号——`ainsert_v2` 从不填 `group_ids`，而 `api/services/audit_log.py:78-101` 会对其余账号强加 `json_array_contains(group_ids, …)` 过滤 → 这类账号**查不到任何 v2 结构化事件**（design K9 / 坑 15），会误判成「事件没写」。

**前端**：Platform / Client 分区严格分节，任务附「手动验证」步骤（Playwright 未落地）。**两条被 lint 冻结的路**（design 坑 17）：client 的 recoil（`client/eslint.config.mjs:47`）→ 新读取走 react-query v4；platform 的 react-query v3（`platform/eslint.config.mjs:45,51`）→ 新组件用 `useState + useEffect` / `useTable`。新增 i18n key 三语（zh-Hans / en-US / ja）同 PR。

**Worker**：本 Feature **无 Worker / Celery 任务**（授权变更与广场列表都在 API 进程内同步完成；审计回调的注册点也只挂 API 进程的 `lifespan`，design D6「进程边界」）。故无 `tenant_id` → ContextVar 传递问题。

**自包含任务**：每个任务内联文件、逻辑、AC 覆盖；设计论证指向 design §X 不复制。

**编号 ≠ 执行顺序**：T001–T003 是基础设施，可与 T004 起的测试并行；T012–T014（审计回调）与 T004–T011（广场）互不依赖，可两路并行。

**跨 Feature 前置（`[MVP-核心]` 全部依赖 F054 已落地的批 1 / 批 3）**：

| 本 Feature 消费 | 上游任务 | 缺失时的现象（全部无报错） |
|---|---|---|
| `FlowType.HOSTED_APP=35` + `_build_apps_subquery` 第三支（含手工租户条款、`status` 投影 2/1、`user_id` ← `owner_user_id`） | **F054 T059** | 广场查不到任何托管应用；第三支漏租户条款 = 四条路径一起跨租户泄漏（design 坑 4） |
| `SUPPORTED_APP_TYPES` / `_FLOW_TYPE_TO_RESOURCE_TYPE` 加 35 + **tag 预过滤 4 处**（含 `workflow.py:517-528`）+ `ResourceTypeEnum.HOSTED_APP` | **F054 T060** | 不放行 = 广场空列表；第 4 处漏补 = 有标签 tab 下托管应用整类消失（`tagged_ids` 空 → `return []`） |
| 卡片 ⚙️「管理权限」接线（`BuildPage/apps.tsx` `typeMap` 补 `35:'app'`、`useResourceActions` 第三桶、`canManage`） | **F054 T063** | AC-11 入口 A 直接失效（弹窗对着 `workflow` 类型查，registry 报类型不符） |
| 应用详情页 · 发布 tab 的 slot / children | **F054 T067** | 可见范围区无处挂载（AC-12） |
| `useAppRuntimeEnabled` hook + `/api/v1/env.app_runtime_enabled` | **F054 T071 / AC-62** | 未部署形态下广场出现托管应用相关文案（AC-10 不成立）。**别引成 T090 / AC-61**——T090 是审批期预览入口 |
| `app` 资源类型注册（catalog / FGA / 前端三处 `ResourceType` union） | **F054 批 1** | 授权弹窗与 `batch_check_business_actions` 全线不可用 |
| `/apps/{slug}` 入口（app-proxy + nginx `location /apps/`） | **F054 批 2** | 卡片点击落 platform SPA `/404` |
| `app.release.*` 事件的四处 lockstep 自登记 | **F055** | AC-27 的缺陷会记在本 Feature 头上（故 T015 有断言测试兜底） |

**跨 Feature 副作用登记**（`release-contract.md` 检查项 17；本 Feature **不新增领域对象、不新增不变量、零 DDL、零新错误码**，design C2 / K11）：

| 任务 | 改动的共享物 | 影响面与保护措施 |
|---|---|---|
| T001 | `app_runtime/domain/constants.py` 的 `AppAuditAction`（**F054 领域对象**，正被并发编辑，坑 19）+ `database/models/audit_log.py` 的 `_UI_VISIBLE_V2_ACTIONS`（全平台共享白名单） | 只**加成员**不改既有；改前与 F054 owner 协调（T003）；合并冲突时 rebase 不覆盖 |
| T002 | `platform/controllers/API/log.ts` 的 `actions` 数组 + 三语 `bs.json`（审计页共享常量与文案） | 只加一条 app 段成员；模块下拉与 `getActionsByModuleApi` 的 `case 'app'` **F054 已落，不动** |
| T005 / T009 / T011 | `api/services/workflow.py`（广场 + 构建页 + 工作台 + 应用中心共用的 application service，`_application_action_map` 有 **7 个调用方**；T011 另改 `filter_apps_by_action`，**3 个生产调用方**：`workflow.py:949` / `workstation/apps.py:41` / `:119`） | 每个任务只改自己那一个函数；`_application_action_map` / `filter_apps_by_action` 新增参数均缺省（`None` / `frozenset()`）= 其余调用方逐字节不变（design D3 爆炸半径表），单测逐条断言。⚠️ `test/workstation/` 有 4 个文件 patch 了 `filter_apps_by_action`（见 T011） |
| T007 | `database/models/flow.py` 的 `aget_all_apps` / `_build_apps_subquery`（**4 个调用方**，且 F054 T059 正在同文件并发编辑） | 只增可选参数、缺省不改行为；**落地前先与 F054 owner 对一次**：若 T059/T060 已加等价参数则复用其命名并回写 design D9；合并时 rebase 不覆盖 |
| T009 | `database/models/app.py` 的 `AppDao`（**F054 领域模型**，可能并发编辑） | 只**新增一个只读**批量方法 `alist_slug_state_by_ids`（不改既有方法、不加列、无 DDL）；`AppDao` 刻意不暴露通用 UPDATE（`app.py:101-107` docstring），本任务不破这条戒律 |
| T013 | `permission/application/resource_api.py`（**F048 领域**的 application 门面，类名 `F048ResourcePermissionApi:99`，构造 `__init__:102-111`）+ `api/services/f048_permission_runtime.py:236` 的构造处（多传一个可选依赖） | 只加「按资源类型注册的回调」扩展点，本期只注册 `app` 一个类型；**其余资源类型行为逐字节不变**（知识库 / 工作流的授权今天完全不写审计，不顺手加）；注册表照既有 `ResourceAuthorizationRegistry`（`permission/application/resource_authorization.py:37-53`）形态**实例化 + 组合根注入**，不用模块级全局 dict |
| T014 | `api/services/f048_permission_runtime.py`（`initialize_f048_api_runtime:214` 内 `F048ResourcePermissionApi(...)` 的构造处 `:236-240`，与既有 `registry.register("app", hosted_app):210` 同一处组合根；该文件已 import `app_runtime`，`:17`） | 只加一次显式注入；**不得依赖模块 import 副作用**；**不动 `main.py`**（见 T014 正文「注册落点」——放这里正好与 `mutate_grants` 同生共死，openfga 关闭时二者一起不存在，不构成静默失败） |
| T018 | `client/src/pages/apps/components/AgentCard.tsx`（**广场与「应用中心」共用组件**，`explore.tsx` + `index.tsx` 两个页面）+ `client/src/locales/{zh-Hans,en,ja}/translation.json`（三语视为一组） | 只加「已停用」角标（由数据字段 `app_state` 驱动）；分享按钮**不加类型判断**（靠后端 `can_share=false` 数据闸，零改组件达成 AC-07）；新增文案只加 key 不改既有 key |
| T011 | `api/services/workflow.py` 的 `filter_apps_by_action:663`（3 个生产调用方）+ `workstation/api/endpoints/apps.py`（工作台推荐位 `:41` / 常用列表 `:119` 两处调用处） | 只在「应用中心 / 最近使用」路径显式排除 `flow_type=35`（design 坑 10）；新参数有默认值 → 不传即行为不变；不改另两类行为、**不动 `FlowDao`** |

**上游勘误（本 Feature 不代改，见 T003）**：① F054 design `:339` 访问记录 TTL 300s → **1800s**（design D7 / spec 决议-2）；② F054 T060 文件清单补 tag 预过滤第 4 处 `workflow.py:517-528`；③ `flow.py` 两个内部参数的命名与 F054 T059 对齐。

---

## Tasks

### Wave 1 · `[MVP-核心]` 基础设施（无测试配对，排最前）

- [x] **T001**: `[MVP-核心]` 审计 action 后端两处 lockstep 登记
  **文件**: `src/backend/bisheng/app_runtime/domain/constants.py`（`AppAuditAction` 枚举加成员）, `src/backend/bisheng/database/models/audit_log.py`（`_UI_VISIBLE_V2_ACTIONS:193` 加同一字符串）
  **逻辑**: 加 `VISIBILITY_CHANGE = "app.visibility_change"`（本 Feature 唯一自写的事件类型，design D6）。`_UI_VISIBLE_V2_ACTIONS` 是 `_ui_visible_predicate:272-282` 的 `OR(system_id IS NOT NULL, action IN (...))` 白名单，被 `get_audit_logs:329` 与 `get_all_operators:408` 应用——**不在白名单 = 写库但审计页查不到，且无任何报错**（design K3，AC-27 的实现锚点）。命名空间前缀 `_V2_NAMESPACE_TO_ACTION_PREFIX:261` 的 `"app": "app."` 与模块下拉 **F054 已落，本任务不动**。
  **⚠️ 并发**: `constants.py` 正被 F054 实现 agent 编辑（design 坑 19）——改前先 `git pull` / 与 owner 对一次；若不便共改，可在 `app_runtime` 自己的常量位置定义该 action，但 `_UI_VISIBLE_V2_ACTIONS` 白名单**仍必须加**。
  **回滚**: 纯常量增补，无 DDL；回滚 = 删两处成员（历史事件行仍在库，只是页面查不到）。
  **覆盖 AC**: AC-22, AC-27
  **依赖**: 无

- [x] **T002**: `[MVP-核心]` Platform · 审计 action 前端两处 lockstep 登记
  **文件**: `src/frontend/platform/src/controllers/API/log.ts`（`actions` 数组 app 段 `:136-144`）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（三语视为一组，**两处各加一条**：`log.eventTypeEnum` + `log.objectTypeEnum`）
  **逻辑**: 事件类型下拉里加 `app.visibility_change`。**i18n key 由代码推导、不能自己起名**（design 坑 20）：`actionToI18nKey`（`platform/src/pages/LogPage/systemLog/index.tsx:43-47`）按 `action.split(/[._]/)` 首段小写 + 其余首字母大写 → key **只能是 `appVisibilityChange`**（起成 `appVisibility` / `app_visibility_change` 则事件类型列显示英文原串，有 defaultValue 兜底不炸、三语文件那三条永远用不上）。
  **⚠️ `log.objectTypeEnum.app` 是本任务要「新增」的，不是「确认存在」**（2026-08-17 实测三语 `bs.json` 的 `log.objectTypeEnum` 键集 = `approval_exception / approval_flow / approval_instance / approval_scenario / approval_task / assistant / channel / dashboard / file / flow / knowledge / knowledge_space / llm_server / none / role_conf / tenant / tool / user_conf / user_group_conf / work_flow / workstation`，**没有 `app`**）。缺这条时 `renderObjectType`（`systemLog/index.tsx:68-72`）回落显示原始串 `app`，与 AC-27「三语文案」正面冲突且**不报错**。文案初值：zh-Hans「应用」/ en-US `Application` / ja「アプリ」，以产品词表为准。机器化护栏见 T015 断言 ④。
  **模块下拉与 `getActionsByModuleApi` 的 `case 'app'`（`log.ts:49` / `:166`）F054 已落，不动**。
  **手动验证**: 见 T021 **步 9**（管理员账号在系统操作日志页看到「可见范围变更」中文选项、对象列显示「应用」而非 `app`，切 en/ja 文案不为空、不显示原始串）。
  **覆盖 AC**: AC-22, AC-27
  **依赖**: T001

- [x] **T003**: `[MVP-核心]` 上游勘误提交与同文件并发协调（无代码产出）
  **文件**: 无（勘误内容以书面 / SendMessage 形式交 F054 owner，**本 Feature 不代改 F054 任何文档**）
  **逻辑**: 三条勘误逐条落地确认：① F054 design `:339` 的访问记录合并窗口 TTL **300s → 1800s**（值由 F056 D7 / spec 决议-2 定义，不回写 = F054 按 300s 落地且无任何报错）；② F054 T060 的文件清单补 tag 预过滤**第 4 处** `api/services/workflow.py:517-528`（F054 `tasks.md:47` 批次边界注已认账 4 处，仅清单行漏写；不补 = 有标签 tab 下托管应用整类消失且不报错）；③ `database/models/flow.py` 的 `status_exempt_flow_types` / `app_state_in` 两个内部参数命名与 F054 T059 对齐——若 T059/T060 已加等价参数则 T007 复用其命名并回写 design D9，否则由 T007 新增。**任一条未获回复即视为未决，T007 落地前必须完成 ③**。
  **回滚**: 不适用（纯协调）。
  **依赖**: 无

### Wave 1 · `[MVP-核心]` 后端 · 广场动作集裁剪（Test-First 配对）

- [x] **T004**: `[MVP-核心]` `_application_action_map` 第一层（合法性过滤）单元测试
  **文件**: `src/backend/test/workflow/test_workflow_action_map.py`（新）
  **逻辑**: 对 `WorkFlowService._application_action_map`（`api/services/workflow.py:146-178`）断言按资源类型的请求集裁剪，判据 = `permission/domain/services/catalog_policy.py:60-75` 的 `ACTION_RESOURCE_SCOPES`（与真正抛错的 `_prepare_action_target` 读同一张表）。用例：
  - `test_app_bucket_drops_share` → 含 `flow_type=35` 的 data + 请求 `("use","edit","share")` → app 桶实际请求集**不含 `share`**（`catalog_policy.py:71` 的 `share` 范围集不含 `app`）；
  - `test_other_buckets_unchanged` → `workflow` / `assistant` 桶请求集与改动前**逐元素相同**（防回归）；
  - `test_visible_never_filtered` → `"visible"` 在任何桶都不被滤掉（它不在 `ACTION_RESOURCE_SCOPES` 里——`_normalize_action:366-370` 把它排除在 `REGISTERED_ACTION_CODES` 外、走 `batch_check_visible` 另一条路；滤掉 = **广场空列表**）；
  - `test_enrich_can_share_no_error` → 对 `aenrich_apps_can_share`（`:129-143`，无条件请求 `("share",)`）传含 `flow_type=35` 的 data → **不抛 `InvalidCatalogActionError`**（现象是 HTTP 200 + 业务码 **25001**，不是 500，design 坑 1）、`can_share` 为 `False`。这条覆盖坑 1 的另外 4 个调用方（`workstation/api/endpoints/apps.py:53` / `:150`、`api/v1/chat.py:83`、`workflow.py:962`），**只测广场是测不到的**。
  **基础设施**: `test/workflow/` 已有 conftest 基线（`test_flow_dao_tenant_isolation.py` 同目录）；本任务只 mock `batch_check_business_actions` 观察入参，不需中间件。
  **覆盖 AC**: AC-04, AC-07
  **依赖**: 无（跨 Feature 前置：F054 T059 / T060）

- [x] **T005**: `[MVP-核心]` `_application_action_map` 第一层实现 + 按桶覆盖扩展点
  **文件**: `src/backend/bisheng/api/services/workflow.py`（只改 `_application_action_map:146-178` 一个函数）
  **逻辑**: 分桶（`grouped:152-155`，F054 T060 已加第三桶 `35: "app"`）之后、发 `batch_check_business_actions` 之前，**每个桶只请求对该 `resource_type` 合法的 action**（判据 `catalog_policy.ACTION_RESOURCE_SCOPES`），并**显式豁免 `visible`**。同时加可选参数 `actions_by_type: dict[str, tuple[str, ...]] | None = None` 做按桶覆盖，缺省 `None` = 全桶用 `actions` —— **另 6 个调用方一行不改**（design D3 爆炸半径表）。请求集为空的桶不发起 check（→ `can_share` 落回 `False`，`_apply_page_can_share:485` 与 `aenrich_apps_can_share:139` 都是「命中才 true」，AC-07 后半句零改组件达成）。
  **⚠️ 不要顺手给 `app` 加 `share`**：托管应用没有 share-token 免登录通道（spec 决议-6），加 `share` 就是造一个不存在的能力（design K6）。
  **⚠️ 第一层把「抛 25001」换成了「静默滤掉」**——这恰好是坑 10 想要的效果，但**坑 10 的显式排除（T011）仍要做，不得依赖这个副作用**（`use` 对 app 合法，应用中心传的正是 `use`）。
  **测试**: T004 全部通过。
  **覆盖 AC**: AC-04, AC-07
  **依赖**: T003, T004

### Wave 1 · `[MVP-核心]` 后端 · 广场状态收窄与载荷（Test-First 配对）

- [x] **T006**: `[MVP-核心]` `FlowDao` 广场两参数单元测试
  **文件**: `src/backend/test/workflow/test_flow_dao_square_params.py`（新）
  **逻辑**: 对 `FlowDao.aget_all_apps`（`database/models/flow.py:508`）新增的两个**内部**参数断言：
  - `test_status_exempt_flow_types` → 传 `status=2` + `status_exempt_flow_types={35}` 时，外层 status 条件（`flow.py:582 sub_query.c.status == status`）对第三支**不生效**、对另两支照旧（可对拼出的 SQL 文本断言或用 DAO 层构造断言）；
  - `test_app_state_in_narrows_third_branch` → 传 `app_state_in={"online","stopped"}` 时第三支子查询带 `App.state IN (...)` 条件，草稿 / 待上线 / 已删除**被挡在 SQL 层**；
  - `test_defaults_unchanged` → 两参数都不传（构建页与另 3 个调用方的形态）时，拼出的 SQL 与改动前**逐字节相同**（`aget_all_apps` 有 4 个调用方：`get_all_apps:420` / `aget_all_apps:508` / `get_all_app_by_time_range_sync:810` / `get_first_app:849`）。
  **覆盖 AC**: AC-02, AC-03
  **依赖**: 无（跨 Feature 前置：F054 T059 第三支）

- [x] **T007**: `[MVP-核心]` `FlowDao.aget_all_apps` / `_build_apps_subquery` 两个内部参数实现
  **文件**: `src/backend/bisheng/database/models/flow.py`（`aget_all_apps:508` + `_build_apps_subquery:660-702`）
  **逻辑**: 加 `status_exempt_flow_types: set[int] | None = None`（外层 status 条件由 `sub_query.c.status == status` 改为「`status == :status` **或** `flow_type ∈ 豁免集合`」）与 `app_state_in: set[str] | None = None`（第三支子查询侧的 `App.state` 收窄）。**两个参数缺省 `None` = 行为逐字节不变**，构建页与另 3 个调用方不传（design D9）。
  **⚠️ 为什么不改 F054 的 status 投影**：把「已停运」也投成 2 会**打坏构建页**（`platform/controllers/API/flow.ts:204` 按 `status ∈ {1,2}` 筛「已上线 / 已下线」），且是修改 F054 已定稿的契约（design D9 备选 A 已否）。
  **⚠️ 同文件并发**: `flow.py` 正被 F054 T059 编辑——落地前先完成 T003 ③；**合并时 rebase 而非覆盖**；第三支的手工 `build_tenant_filter_clause`（`:695` / `:698` 形态，docstring `:661-671` 明写「`.subquery()` 一包租户自动过滤即失效」）**归 F054 T059**，本任务不得删改（漏写 = 四条路径一起跨租户泄漏，design K1 / 坑 4）。
  **回滚**: 纯可选参数增补，无 DDL；回滚 = 删两参数与其条件分支。
  **测试**: T006 全部通过；另跑既有 `src/backend/test/workflow/test_flow_dao_tenant_isolation.py` 回归（K1 的四方法覆盖）。
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T003, T006

- [x] **T008**: `[MVP-核心]` 广场扫描页口径切换 + 载荷补字段单元测试（两个入口各断言一次）
  **文件**: `src/backend/test/workflow/test_square_scan_page.py`（新）
  **逻辑**: 对 `WorkFlowService._scan_visible_apps_page`（`workflow.py:401-478`）与其两个入口断言：
  - `test_app_bucket_requests_use_edit` → app 桶请求 `("use","edit")`、另两类保持 `(action,"edit","share")`（`share` 由第一层裁，**此处不重复裁**）；
  - `test_kept_filter_per_row_type` → `kept` 筛选（`:450-455`）不再用外部传入的 `action` 一刀切，改为**按行的 `flow_type` 取该桶实际请求的可见性 action**（`app` 行看 `use`，其余行看 `action`）——这是 AC-06 同源的机器化护栏（入口用 `check_business_action("app", id, actor, "use")`，广场默认传 `visible`，二者在 FGA 里是两条不同关系，design K7 / 坑 2）；
  - `test_slug_and_app_state_batched` → 出口对 `flow_type==35` 的行**批量一次**回查补 `slug` / `app_state`，另两类为 `None`，且**不额外发起 N 次查询**；
  - `test_both_entries_carry_slug`（**坑 21 / 坑 8 的护栏**）→ `get_online_flows_page:500` 与 `get_uncategorized_flows:977` 的返回体里托管应用行**都带** `slug` / `app_state`——后者从不调 `add_extra_field`（`:1012-1016` 只补 `logo` 后直接 `_apply_page_can_share` 返回），补在 `add_extra_field` 里就只对标签 tab 生效，而未分类 tab 正是 §7 指定的唯一验收面；
  - `test_square_state_narrowing_hardcoded` → 两个入口函数在调用处**写死** `status_exempt_flow_types={35}` + `app_state_in={"online","stopped"}`，**不从 HTTP 层接收**（广场不新增任何 query 参数）；
  - `test_can_share_false_for_app` → `_apply_page_can_share:485` 对 `flow_type=35` 恒 `False`。
  **覆盖 AC**: AC-01, AC-03, AC-06, AC-07
  **依赖**: T005, T007

- [x] **T009**: `[MVP-核心]` `_scan_visible_apps_page` 与广场两入口实现
  **文件**: `src/backend/bisheng/api/services/workflow.py`（`_scan_visible_apps_page:401-478` + 两个入口函数 `get_online_flows_page:500` / `get_uncategorized_flows:977` 的调用处）
  **逻辑**: 三件事一次改完（同一函数 + 其两个调用处，避免与 T005 重复修改同一段）：
  1. **口径切换**：`requested_actions:425` 由「一个全局元组」改为「按桶取值」，经 T005 的 `actions_by_type` 传 `{"app": ("use","edit")}`；`kept:450-455` 按行 `flow_type` 取该桶的可见性 action。
  2. **载荷补字段**：返回整页之前，对 `flow_type==35` 的行批量一次回查 `app.slug` / `app.state` 补成 `slug` / `app_state` 两个载荷字段（**不能放 `add_extra_field:87-127`**——未分类 tab 不经过它，现象是点击落 `/apps/undefined`、没有「已停用」角标且不报错，坑 21）。
  3. **状态收窄**：两个入口函数在调用 `aget_all_apps` 时**写死** `status_exempt_flow_types={35}` + `app_state_in={"online","stopped"}`（`api/v1/chat.py:63` 硬传 `FlowStatus.ONLINE(2)` 保持不变，草稿 / 待上线 / 已删除靠 `app_state_in` 挡在 SQL 层，**不必额外写权限收窄**，AC-03 的「不因用户是 owner 或管理员而例外」由此成立）。
  **⚠️ 不在广场前端做任何数据过滤**：`hasMore = pageData.length >= pageSize`（`client/pages/apps/explore.tsx:74`），后端不返回 total——扫描外层再加过滤会造成「返回不足一页 → 前端判定没有更多 → 后面的应用永远刷不出来」（坑 9）。
  **测试**: T008 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07
  **依赖**: T008

- [x] **T010**: `[MVP-核心]` 应用中心 / 最近使用排除托管应用 单元测试
  **文件**: `src/backend/test/workflow/test_app_center_excludes_hosted.py`（新）
  **逻辑**: 断言 `WorkFlowService.get_frequently_used_flows`（`workflow.py:924-965`，内部走 `filter_apps_by_action:663` + `action="visible"`）与工作台推荐位 / 常用列表（`workstation/api/endpoints/apps.py:41` / `:119`）的返回集中**不含 `flow_type=35`**。理由（坑 10）：这两条路径的点击落 `/app/{chatId}/{id}/{flow_type}` 对话页（`client/pages/apps/hooks/useAppCenter.ts:74`），托管应用没有会话语义，用户点它会白屏或报错——**而这条路径不在任何 AC 里，没人会去测**。用例含「另两类数量与顺序不变」的回归断言。
  **覆盖 AC**: AC-01, AC-07
  **依赖**: T005

- [x] **T011**: `[MVP-核心]` 应用中心 / 最近使用路径显式排除 `flow_type=35`
  **文件**: `src/backend/bisheng/api/services/workflow.py`（`get_frequently_used_flows:924-965` 一处过滤）, `src/backend/bisheng/workstation/api/endpoints/apps.py`（推荐位 `:41` / 常用 `:119` 两处调用的类型入参）
  **逻辑**: 在这两条「进对话页」的路径上显式排除托管应用（**不要依赖 T005 第一层的静默滤除副作用**——`use` 对 app 合法，托管应用照样会流进去）。排除位置取「类型闸」而非前端，保证工作台 / 应用中心两个消费者一次到位。
  **测试**: T010 全部通过。
  **覆盖 AC**: AC-01, AC-07
  **依赖**: T010

### Wave 1 · `[MVP-核心]` 后端 · 可见范围变更审计（Test-First 配对）

- [x] **T012**: `[MVP-核心]` 可见范围变更审计回调 单元 / 集成测试
  **文件**: `src/backend/test/app_runtime/test_visibility_change_audit.py`（新，`test/app_runtime/` 已存在）
  **逻辑**: 对 `ResourcePermissionApi.mutate_grants`（`permission/application/resource_api.py:290`）新增的回调链断言：
  - `test_callback_registered_for_app` → 起最小 app 上下文后注册表里有 `app` 项（**未注册是静默失败、无任何报错**，design D6）；
  - `test_audit_written_once_on_grant` → ADD 一个用户组后审计表恰好 **1 条** `app.visibility_change`，字段 = `target_type='app'` / `target_id=app.id` / `object_name=app.name` / `metadata={app_slug, added[], removed[], model_keys[]}` / `operator_*` = **变更人本人**；
  - `test_idempotent_replay_writes_nothing` → 重放同一 `idempotency_key` **不新增记录**（`ProjectionOutcome.idempotent`，`permission/domain/services/projection_plan.py:58-64`；不判这个标志 = 审计页出现「同一秒改了三次可见范围」的假记录，坑 12）；
  - `test_removed_carries_subject_identity`（**坑 11 的机器化断言**）→ ADD 一个用户组 → REMOVE 它 → `metadata.removed[0]` 是 `{type:"group", id:…}` 而**不是** `{assignee_id:…}`；
  - `test_pure_add_does_not_preread_roster` → 没有 REMOVE / MOVE 的纯 ADD 请求**不触发**名册预读（调用计数 / mock 断言，防止把成本加在最常见的路径上）；
  - `test_tenant_admin_operator_is_self` → 租户管理员代 owner 调整时变更人记该管理员本人（AC-14）；
  - `test_non_owner_denied` → 非 owner 非管理员调 mutate → 被 `_target(..., "manage_permission")` 拒（AC-15 的**后端**闸，前端闸只是体验不是安全边界）；
  - `test_audit_failure_does_not_rollback_grant` → 审计写入抛错时授权动作照常成功（`ainsert_v2` 自带独立 session + commit 且写失败会抛，坑 14）。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-22
  **依赖**: T001

- [x] **T013**: `[MVP-核心]` 授权变更回调注册表 + 名册预读（permission 侧扩展点）
  **文件**: `src/backend/bisheng/permission/application/resource_api.py`（`ResourcePermissionApi.mutate_grants:290-372`）
  **逻辑**: 加模块级注册表 `{resource_type: async callback}`，`mutate_grants` 成功返回前按 `resource_type` 查表并调用（有则调、无则跳过），回调入参 `actor / target / changes / result`。**前置的名册预读**（坑 11）：仅当 ① 该 `resource_type` 注册了回调、且 ② 本次 `changes` 里存在 `REMOVE` / `MOVE` 时，在 `self._runtime.mutate_grants(...):337` **之前**用既有读法 `list_permission_sources_page(actor, target, after_id=0, limit=…)`（`:190` 同款）取一页名册，建 `source_id → (subject_type, subject_id)` 索引供回调反查；名册 `has_more` 为真时对超出部分只写 `{assignee_id}` 并在 `metadata` 打 `roster_truncated: true`，**宁可标注不完整也不做多页扫描**。
  **⚠️ 为什么必须预读**：`remove_source` 把被撤销的 source **整行丢弃**（`permission/domain/services/grant_source_service.py:279` / `:305-311` 的 `remaining` + `replace(...)`），不是标 `active=False` 保留 → `GrantMutationResult.grants`（`grant_service.py:232`）里**查无此人**；而请求体侧 `REMOVE` / `MOVE` 只带 `assignee_id` + 版本（`domain/schemas/f048.py:242-262 validate_operation_shape`）。两头都拿不到主体身份，「从结果快照反解」已被证伪（design D6 审查修订）。
  **⚠️ 依赖方向**: 本文件**不认识 `app.*` 命名空间**——写入器由 `app_runtime` 侧提供（T014）。不得在此按 `resource_type == "app"` 直接写审计（那会让权限模块知道应用工场的命名空间，且将来变成一串 if/elif，design D6 备选 B 已否，C1）。
  **⚠️ 本期只注册 `app` 一个类型**：知识库 / 工作流的授权今天完全不写审计，**不顺手给它们加**（那是范围外的行为变更）。
  **测试**: T012 的注册表 / 预读 / removed 主体身份三组用例通过。
  **覆盖 AC**: AC-13, AC-15, AC-22
  **依赖**: T012

- [x] **T014**: `[MVP-核心]` `app_runtime` 审计写入器 + 组合根显式注册
  **文件**: `src/backend/bisheng/app_runtime/domain/services/visibility_audit.py`（新）, `src/backend/bisheng/main.py`（`lifespan:82-84` 加一次显式注册调用，照 `_register_permission_runtime_contexts:55-77` 先例）
  **逻辑**: 写入器组装并调 `AuditLogDao.ainsert_v2`（`database/models/audit_log.py:428`）写 `action='app.visibility_change'`，字段口径见 T012。三条硬规：① `if outcome.idempotent: return`（坑 12）；② **不要再包事务**——`ainsert_v2` 自带 `bypass_tenant_filter()` + 独立 async session + commit（`:494-500`）；③ 整个写入用 try/except 包住、失败只打 **warning**（照 `approval/domain/services/approval_outbox_service.py:105-121` 的「审计失败不影响主流程」包法），日志字段 `resource_type / resource_id / operator_id / reason`——**这条 warning 是「审计静默丢失」的唯一信号**。
  **⚠️ 注册落点 = 组合根显式注册，不得依赖模块 import 副作用**（否则注册与否取决于 router 加载顺序，一次 import 图重排就静默失效）。注册成功打一条 info（`registered visibility-change audit hook for resource_type=app`）——114 查不到事件时**先 grep 这条启动日志**，再怀疑写入逻辑。
  **⚠️ 进程边界**: `mutate_grants` 的唯一触发源是 `permission/api/endpoints/grant.py:113`，只跑在 **API 进程**，注册挂 API `lifespan` 即充分；celery / linsight worker 内不注册**不是缺陷**（无触发源）。将来若有 worker 内调用方改授权，注册必须跟着搬。
  **测试**: T012 全部通过（含审计失败不回滚、幂等不重复写）。
  **覆盖 AC**: AC-13, AC-14, AC-22
  **依赖**: T013

### Wave 1 · `[MVP-核心]` 后端 · 跨 Feature 兜底与端到端

- [x] **T015**: `[MVP-核心]` 审计事件登记断言测试（AC-27 的跨 Feature 兜底）
  **文件**: `src/backend/test/app_runtime/test_audit_action_registry_lockstep.py`（新）
  **逻辑**: 参数化读取**全部已注册**的 `app.*` / `app.release.*` action 常量（`app_runtime/domain/constants.py` 的 `AppAuditAction` + F055 的 release action 枚举），逐条断言四处 lockstep 齐备：① 在 `_UI_VISIBLE_V2_ACTIONS`（`database/models/audit_log.py:193`）里；② 在 `platform/src/controllers/API/log.ts` 的 `actions` 数组里（读文件做文本匹配）；③④ 三语 `platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 的 `log.eventTypeEnum` 里都有对应 `actionToI18nKey(action)`（`split(/[._]/)` + 驼峰化）的 key。
  **为什么这条价值最高**：它一存在，F054 / F055 / F049 将来漏登记会在 **CI 上立即失败**，而不是等到有人在审计页里找不到事件——AC-27「不存在已写入但页面查不到的事件类型」的判定归本 Feature，故必须机器化。本轮它同时把 F054 已写的 `app.publish` / `app.stop` / `app.resume` 等九条与 F055 的 `app.release.*` 一并纳入断言（= MVP-核心承诺的「发布 / 上线 / 可见范围变更三类事件可查」）。
  **覆盖 AC**: AC-19, AC-20, AC-27
  **依赖**: T002

- [ ] **T016**: `[MVP-核心]` 广场端到端集成测试（**非管理员账号**）
  **文件**: `src/backend/test/workflow/test_square_hosted_app_e2e.py`（新，pytest + httpx，连 test 中间件 MySQL / Redis / OpenFGA，CI 跑）
  **逻辑**: 用**非管理员、非 owner 的普通用户**跑 `GET /api/v1/chat/online` 与 `GET /api/v1/workstation/app/uncategorized`：
  - `test_grant_then_revoke_visibility` → 授权前 0 条托管应用、授权后 1 条、撤销后 0 条，且生效发生在**下一次请求**（无需重新登录、不依赖任何缓存到期，AC-05）；
  - `test_square_and_entry_same_source` → 同一普通用户对同一应用调 F054 入口判定 `check_business_action("app", app_id, actor, "use")` → 与广场结果**同真同假**（AC-06 的机器化断言，禁止「广场看得见、点进去无权限」稳态）；
  - `test_state_filter` → 已停运应用**仍出现**且 `app_state='stopped'`；草稿 / 待上线 / 已删除**不出现**，且不因用户是 owner 或管理员而例外（AC-02 / AC-03）；
  - `test_payload_shape` → 托管应用行带 `slug`、`user_name`（owner 显示名，决议-3）、`can_share=False`，另两类载荷形状不变（新字段为 null / 既有值）；
  - `test_tenant_isolation` → A 租户用户查不到 B 租户的托管应用（坑 4 回归；**测试若只用超管跑永远发现不了**）；
  - `test_manage_dialog_denied_for_grantee` → 仅被授予可见范围的用户调 `GET/POST /api/v1/permissions/resources/app/{id}/grants*` → 403（AC-15：被授予可见范围只获得广场可见与入口访问，不获得任何管理入口）。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-15
  **依赖**: T009, T011, T014

### Wave 2 · `[MVP-核心]` 前端 Client（手动验证）

- [x] **T017**: `[MVP-核心]` Client · 托管应用图标与列表项类型
  **文件**: `src/frontend/client/src/components/Avator/index.tsx`（`flowConfig:30-43` 加第三支）, `src/frontend/client/src/@types/app.ts`（列表项类型加 `slug?: string` / `app_state?: 'online' | 'stopped'`，`flow_type` 注释补 35）
  **逻辑**: `flowConfig` 今天只有 `1 / 5 / 10` 且 `flowConfig[flowType] || flowConfig[5]` **默认回落助手图标**（`:45`）——不加 35 则广场里托管应用**显示成助手图标，且没有任何报错**（坑 6）。
  **⚠️ 这是 client 侧那份图标 map**，与 F054 T063 改的 `platform/src/components/bs-comp/cardComponent/avatar.tsx` **不是同一文件**——「F054 说图标已经加了」是误判来源。
  **手动验证**: 见 T021 步 3（普通账号广场里托管应用卡片图标不是助手图标）。
  **覆盖 AC**: AC-01
  **依赖**: 无（跨 Feature 前置：F054 T059 的 `FlowType.HOSTED_APP=35`）

- [x] **T018**: `[MVP-核心]` Client · 广场卡片跳转分流 + 「已停用」角标 + 未部署形态文案闸
  **文件**: `src/frontend/client/src/pages/apps/explore.tsx`（`handleCardClick:132-146` 分流 + 未部署 guard）, `src/frontend/client/src/pages/apps/components/AgentCard.tsx`（`app_state==='stopped'` 时渲染「已停用」标识）
  **逻辑**:
  1. **跳转分流**：`flow_type===35` 时走 `window.location.assign('/apps/' + agent.slug)`（整页跳、**当前窗口**、**不带 base**），且**不写** `sessionStorage` 的 `appFlowOriginKey` / `appLastOriginKey`（那是对话页返回用的，托管应用离开 SPA 后不回来）；其余类型走原有 `navigate('/app/...')` 一行不改。
  **⚠️ 三个必错写法**：`navigate('/apps/…')` 会自动前置 basename → `/workspace/apps/{slug}` **404**（client vite `base = /workspace`，`client/vite.config.ts:127`）；拼 `__APP_ENV__.BASE_URL` 同样 404；**同目录的 `appUtils.ts:67-71 getAppShareUrl` 恰恰是反例**（它主动拼 `BASE_URL`），照抄它就会把 `/workspace` 加回去，且因为「抄的是仓内既有写法」而更难被质疑（坑 3）。
  2. **「已停用」角标**：由数据字段 `app_state` 驱动（AC-03 / 决议-5：保留卡片并标注，隐藏会让用户误判为被移出可见范围）。`AgentCard` 是**广场与「应用中心」共用组件**，改它要同时想两个页面；**分享按钮不加类型判断**（靠后端 `can_share=false` 数据闸，零改组件达成 AC-07，坑 7）。
  3. **未部署形态**：消费 F054 T071 的 `useAppRuntimeEnabled`（react-query v4 hook；**不得 `useRecoilValue`**——client 的 recoil 已被 lint 冻结，`client/eslint.config.mjs:47`，坑 17）仅用于隐藏与托管应用相关的**文案 / 空态提示**；**前端不做任何数据过滤**（开关关时后端天然无 `app` 行，双保险的数据侧；前端过滤会撞上「不足一页 → 判定没有更多」的无限滚动缺陷，坑 9）。
  **手动验证**（用**非管理员、非 owner 普通账号**，见 T021 步 3–4）:
  - client 广场「未分类」tab 看到该托管应用卡片 → 点击 → 浏览器地址栏变成 `http://<host>/apps/<slug>`（**没有 `/workspace`**）→ 应用页面正常渲染；
  - 卡片上**没有分享按钮**；
  - owner 停运后刷新广场 → 卡片**仍在**且带「已停用」标识，点击落 F054 的「已停用」页；重新启用后标识消失；
  - `app_runtime_enabled=false` 的环境（或临时改 `/api/v1/env` 返回）下广场无任何托管应用卡片与相关文案，**广场其余行为零变化**。
  **覆盖 AC**: AC-01, AC-03, AC-07, AC-10
  **依赖**: T009, T017

### Wave 2 · `[MVP-核心]` 前端 Platform（手动验证 + 纯逻辑单测）

- [x] **T019**: `[MVP-核心]` Platform · 「仅 owner 可见」判据纯函数 + 单测
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/visibilityScope.ts`（新，纯函数 `isOwnerOnly(appState, grants)` / `summarizeGrants(grants, hasMore)`）, `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/visibilityScope.test.ts`（新）
  **逻辑**: 判据 = `appState === 'online' && grants.filter(a => !a.protected).length === 0`。
  **⚠️ 不能用 `grants.length === 0`**：F048 在应用创建时给 owner 投一条 **protected** 授权（`app_runtime/domain/services/f048_app_permission.py:168-186`，`mode="CUSTOM", protected=True`），刚上线的应用 grants **恰好有一条** → 提示条**永远不出现且无任何报错**，owner 于是漏掉「设可见范围」这一步、同事在广场什么也看不到——正是 PRD 要用这条提示解决的问题（坑 13）。
  **⚠️ `app_state === 'online'` 前置不能省**：AC-12 原文是「WHILE 应用**已上线**且可见范围仍为『仅 owner 可见』」；不加前置，草稿 / 待上线态详情页也会常驻「同事无法在广场看到」——那句话在未上线时本来就成立且无从解决，是纯噪音。
  **摘要口径**: 只判/只取 grants **首页**（`page_size` 默认 50，`has_more`）——首页 50 条里若一条非 protected 都没有，后面更不会有（protected 行数是个位数）；摘要文案取 `has_more ? 'N+' : N`。
  **测试**: `test_owner_only_when_single_protected_row`（1 条 protected → true）/ `test_not_owner_only_with_grant`（1 protected + 1 普通 → false）/ `test_draft_never_shows_banner`（`app_state='draft'` + 0 非 protected → false）/ `test_summary_plus_when_has_more`。
  **覆盖 AC**: AC-12
  **依赖**: 无（跨 Feature 前置：F054 T067 的发布 tab slot）

- [x] **T020**: `[MVP-核心]` Platform · 可见范围区组件（授权弹窗第二触发点）
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/VisibilityScopeSection.tsx`（新，填 F054 T067 交付的发布 tab slot）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（三语视为一组：可见范围区标题 / 提示条 / 摘要 / 设置按钮文案）
  **逻辑**: 区块只做四件事：① 读状态 `getResourcePermissionGrantsApi('app', app.id)`（`platform/src/controllers/API/permission.ts:313-327`）；② 用 T019 的纯函数渲染**「仅 owner 可见」常驻提示条**（文案必须含「仅 owner 可见」与「同事无法在广场看到」两个要素，**不是一次性 toast**）或已授主体摘要——可见范围区本身**常驻**，未上线时只是不出提示条；③ 提示条内与区块内各有一个设置按钮，点击 `setOpen(true)` 拉起 `<PermissionDialog resourceType="app" resourceId={app.id} resourceName={app.name} />`（`platform/src/components/bs-comp/permission/PermissionDialog.tsx:26-32`，**组件零改动、无 per-type 分支**）；④ 弹窗关闭后**重新拉一次 grants** 刷新摘要（不做乐观更新——授权是低频动作，一次往返换准确性）。
  **⚠️ 不碰 `PublishTab.tsx` 本体**：F054 T067 / F055 已三方约定发布 tab 用 slot / children 留位，直接改本体等于毁约且并发期必冲突（design D4 备选 A 已否）。
  **⚠️ 前端权限闸的正确写法**：`can_manage_permission`（`GET .../context`）为 false 时**根本不发起 grants 请求**——platform 拦截器对 GET 的 403/404 会**整页跳** `/403` / `/404`（`platform/src/controllers/request.ts:160-166`），用户会被甩出整个详情页而不是看到区块内提示（坑 16）。前端闸只是体验，**安全边界是后端 403**（AC-15）。
  **⚠️ 状态管理**: platform 的 react-query v3 已被 lint 冻结（`platform/eslint.config.mjs:45,51`）→ 用 `useState + useEffect` / `useTable`，**不得照抄同目录的 `useQuery`**（坑 17）。
  **手动验证**（owner 账号，见 T021 步 1–2）:
  - 构建 → 应用 → 托管应用卡片 ⚙️ →「管理权限」→ 弹窗出现（`resourceType=app`），选人框里**不出现服务账号**（INV-29，由 `permission/domain/services/grant_subject_service.py:95` 的 `user_type == USER_TYPE_HUMAN` 数据层过滤保证，回归验证不是新工作）；
  - 应用详情页 · 发布 tab → 首发上线后未设可见范围时**顶部常驻提示条**；点提示条内设置按钮 → 拉起**同一个**弹窗；授予后提示条消失、改为摘要呈现；把授权全部撤销后刷新 → 提示条**重新出现**（AC-12 双向验证）；
  - 两个入口保存后的可见范围结果一致（AC-11）；
  - 换非 owner 非管理员账号打开详情页 → 无管理入口、直接调 grants 接口得 403 且**不被甩去 `/403` 整页**（AC-15）。
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-15
  **依赖**: T019

### Wave 2 · `[MVP-核心]` 114 部署与手动验证

- [ ] **T021**: `[MVP-核心]` 114 部署与 MVP-核心闭环手动验证清单（演示剧本步 5–6）
  **文件**: 无代码产出（验证记录回填本任务表格；`/apps/` location 由 F054 交付于 `/etc/nginx/conf.d/bisheng-lilu.conf`）
  **前置**: `curl -s http://127.0.0.1:7860/api/v1/env | jq .app_runtime_enabled` → `true`；`curl -I http://127.0.0.1:4101/apps/<slug>` 非 404 的 SPA 页；后端启动日志里有 `registered visibility-change audit hook for resource_type=app`（T014，**查不到审计事件时先 grep 这条**）。⚠️ 外网 13000 是静态 build 快照，需手动重建。
  **验证清单**:

  | # | 账号 / 位置 | 步骤 | 期望 | AC |
  |---|---|---|---|---|
  | 1 | **owner** · platform 构建 → 应用 → 卡片 ⚙️ | 「管理权限」→ 授予「全员用户组 / 根部门」→ 保存 | 弹窗为平台通用授权弹窗（`resourceType=app`），选人不出现服务账号；保存成功 | AC-11 |
  | 2 | owner · 应用详情页 · 发布 tab | 看可见范围区；再把授权全部撤销后刷新 | 授权后显示**摘要**；撤销后「仅 owner 可见」提示条**重新出现**（含「同事无法在广场看到」） | AC-12 |
  | 3 | **⚠️ 非管理员、非 owner 普通账号** · client 应用广场 | 进**「未分类」tab**（AC-08 的正确验收面——广场默认 tab 是首个首页标签、不是未分类，`AgentNavigation.tsx:59`；无标签的卡片会显示硬编码的「精选」标签，坑 8） | 看到该应用卡片；图标**不是助手图标**；卡片上**没有分享按钮**；按**名称**搜索能搜到（描述搜索本轮不做，design D10 已知偏差） | AC-01, AC-04, AC-07, AC-08 |
  | 4 | 同上 | 点击卡片 | 地址栏变成 `http://<host>/apps/<slug>`（**没有 `/workspace`**）→ 应用页面正常渲染，当前窗口、不新开标签 | AC-07 |
  | 5 | owner 改一次应用名称 / 描述（CLI deploy 或 F054 元信息更新）→ 普通账号**刷新广场** | 观察卡片 | 即见新值，不需重登、不需清缓存（**零代码**，广场直读表行、无缓存层） | AC-09 |
  | 6 | owner 停运 → 普通账号刷新广场；再重新启用 | 观察卡片 | 停运后卡片**仍在**且带「已停用」标识，点击落「已停用」页；重新启用后标识消失 | AC-03 |
  | 7 | owner 撤销该普通账号的可见范围 | 普通账号刷新广场 | **下一次请求**即看不到，无需重新登录 | AC-05 |
  | 8 | 普通账号 | 直接调 `GET /api/v1/permissions/resources/app/{id}/grants` | 403；界面上无任何管理入口 | AC-15 |
  | 9 | **管理员账号**（`is_admin()` 或持日志菜单权限——否则查不到任何 v2 事件，坑 15）· platform 系统操作日志 | 模块选「应用工场」→ 事件类型选「可见范围变更」 | 查到步 1 / 步 7 两条记录：操作人 = 变更人本人、对象 = 应用名；三语切换文案不为空、不显示 `app.visibility_change` 原始串 | AC-14, AC-22, AC-27 |
  | 10 | 同上 | 同一筛选面下查「上线」「停运」事件（F054 / F055 写入） | 能查到（MVP-核心承诺的三类事件可查；机器化护栏见 T015） | AC-19, AC-20, AC-27 |
  | 11 | **租户管理员**（非超管）· platform 构建 → 应用 → 某他人 owner 的托管应用卡片 ⚙️ | 「管理权限」→ 调整可见范围 | 可查看并调整（既有身份短路，非本 Feature 新增）；审计中变更人 = 该管理员本人 | AC-14 |

  > 记录（部署时填）：部署时间 = ；commit = ；逐条结果 = 。
  **覆盖 AC**: AC-03, AC-05, AC-08, AC-09, AC-10, AC-11, AC-12, AC-14, AC-15, AC-19, AC-20, AC-22, AC-27
  **依赖**: T016, T018, T020

---

### Wave 3 · 顺延 · 审计查询面与导出（GOV-04 界面；只列标题 / 文件 / 覆盖 AC，实施前再展开）

> 顺延依据 `mvp-114-path.md` §6 F056 行「审计查询面扩展、导出、超管租户筛选」；**属本 Feature 范围、不得被裁掉**。做的顺序是「对象应用筛选 → 租户筛选 → 导出」——没有第一件，「按应用追溯」这句产品语言不成立（design §8）。落点方向：`api/v1/audit.py:13-27` 与 `AuditLogDao.get_audit_logs`（`database/models/audit_log.py:288-374`）**今天完全没有 `target_type` / `target_id` 维度**，是从零新增而非改配置。

- [ ] **T022**: 审计查询「对象应用」筛选（后端查询参数 + DAO 过滤 + 已删除应用的名称快照）
  **文件**: `src/backend/bisheng/api/v1/audit.py`, `src/backend/bisheng/database/models/audit_log.py`, `src/backend/bisheng/api/services/audit_log.py`
  **覆盖 AC**: AC-21, AC-28

- [ ] **T023**: 按应用名 / 标识检索的选择器端点 + Platform 审计页筛选控件（含已删除应用可选中）
  **文件**: `src/backend/bisheng/api/v1/audit.py`, `src/frontend/platform/src/pages/LogPage/systemLog/index.tsx`, `src/frontend/platform/src/controllers/API/log.ts`
  **覆盖 AC**: AC-28

- [ ] **T024**: 审计列表列扩展（对象列显示应用名 + 标识 / 名称快照；操作人列对服务账号显示账号名 + 密钥掩码并附 owner）
  **文件**: `src/frontend/platform/src/pages/LogPage/systemLog/index.tsx`, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **覆盖 AC**: AC-17, AC-29

- [ ] **T025**: 系统操作审计导出端点 + Platform 导出按钮（导出当前筛选条件下的全部记录，受与查询完全相同的租户与角色边界；内容不含密钥明文）
  **文件**: `src/backend/bisheng/api/v1/audit.py`, `src/frontend/platform/src/controllers/API/log.ts`, `src/frontend/platform/src/pages/LogPage/systemLog/index.tsx`
  **覆盖 AC**: AC-26, AC-32

- [ ] **T026**: 平台超管租户筛选与租户列 + 租户管理员边界拒绝（「对象应用」筛选不得穿透到其它租户）
  **文件**: `src/backend/bisheng/database/models/audit_log.py`（`_visible_for_tenant`）, `src/backend/bisheng/api/services/audit_log.py`（`_get_audit_tenant_scope`）, `src/frontend/platform/src/pages/LogPage/systemLog/index.tsx`
  **覆盖 AC**: AC-30, AC-31

- [ ] **T027**: 审计查询面角色边界与「单一查询入口」回归（仅租户管理员及以上；owner / 普通用户调查询与导出接口被拒；高频三类事件与低频事件同面经事件类型筛选可达）
  **文件**: `src/backend/test/audit/test_audit_scope_and_roles.py`（新）, `src/backend/bisheng/api/services/audit_log.py`
  **覆盖 AC**: AC-33, AC-34

- [ ] **T028**: 各写入方事件的可查性验收（CLI 首发导入 / 发布类含审批单四终态 / 停运 · 重新启用 / 删除后仍可查 / 元信息修改 / 访问记录 / 密钥事件 / 运行期凭据与能力声明 / 生产数据行编辑 / 模型调用逐条；并验证记录与响应不含密钥明文）
  **文件**: `src/backend/test/audit/test_hosted_app_event_queryability.py`（新）
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-21, AC-23, AC-24, AC-25, AC-26

### Wave 4 · 顺延 · GOV-07 验收 / 标签接入 / 事件触达（只列标题 / 文件 / 覆盖 AC）

- [ ] **T029**: ⚙️ 菜单按类型裁剪的回归验证（工作流与助手四项与既有行为完全一致；托管应用两项 + 已上线态删除置灰——**实现归 F054 T063 / AC-42 / AC-53**，本任务只验收）
  **文件**: 无代码产出（手动验证清单，落本任务表格）
  **覆盖 AC**: AC-16

- [ ] **T030**: 标签体系接入验收（托管应用出现在其已有标签的 tab 下；未设标签仍在默认分类可见；本版无打标入口）
  **文件**: 无代码产出（手动验证；标签预过滤 4 处的实现归 F054 T060）
  **覆盖 AC**: AC-08

- [ ] **T031**: GOV-07 界面通道零新增权限点验收（无 `create_app` 者看不到新建入口、其既有托管应用的运行 / 访问 / 迭代发布 / 详情页管理入口不受影响；升级前后角色配置面菜单项与权限点数量不变、新建角色默认值不变；三个承载面分别寄居既有页面、不新增一级菜单）
  **文件**: 无代码产出（回归验收，本 Feature 零改动）
  **覆盖 AC**: AC-35, AC-36, AC-37, AC-38

- [ ] **T032**: 事件触达接线——租户管理员（或超管代行）停运 / 重新启用 → owner 站内消息（owner 本人执行时不发；挂 F054 `AppStateService.stop/resume` 后置钩子，复用平台既有消息通知能力；**发送失败只记日志、不回滚业务动作**）
  **文件**: `src/backend/bisheng/app_runtime/domain/services/`（新增触达钩子）, `src/backend/test/app_runtime/test_state_change_notify.py`（新）
  **覆盖 AC**: AC-43, AC-45
  **跨 Feature**: 挂在 F054 交付的状态动作上；审批类 / 待上线 / 因删除取消的触达归 F055 AC-31 / AC-35 / AC-64，**不得重复接线**（会产生双份消息）

- [ ] **T033**: §3.0.3 事件触达全表验收（审批单生成 / 通过 / 驳回 / owner 撤回 / 因删除取消 / 待上线含成因由 F055 触达；站内消息在 client 工作台「消息提醒」铃铛接收、管理后台不设消息面；明示「无主动提示」的四类事件确实不发；发送失败不影响业务动作完成）
  **文件**: 无代码产出（跨 Feature 验收清单）
  **覆盖 AC**: AC-39, AC-40, AC-41, AC-42, AC-44, AC-45

---

## AC 追溯表（45 / 45 覆盖）

| AC | 覆盖任务 | 波次 |
|---|---|---|
| AC-01 | T008, T009, T010, T011, T016, T017, T018 | 1 / 2 |
| AC-02 | T006, T007, T009, T016 | 1 |
| AC-03 | T006, T007, T008, T009, T016, T018, T021 | 1 / 2 |
| AC-04 | T004, T005, T016, T021 | 1 / 2 |
| AC-05 | T016, T021 | 1 / 2 |
| AC-06 | T008, T009, T016 | 1 |
| AC-07 | T004, T005, T008, T009, T010, T011, T016, T018, T021 | 1 / 2 |
| AC-08 | T021, T030 | 2 / 4 |
| AC-09 | T021 | 2 |
| AC-10 | T018, T021 | 2 |
| AC-11 | T020, T021 | 2 |
| AC-12 | T019, T020, T021 | 2 |
| AC-13 | T012, T013, T014, T020 | 1 / 2 |
| AC-14 | T012, T014, T021 | 1 / 2 |
| AC-15 | T012, T013, T016, T020, T021 | 1 / 2 |
| AC-16 | T029 | 4 |
| AC-17 | T024 | 3 |
| AC-18 | T028 | 3 |
| AC-19 | T015, T021, T028 | 1 / 2 / 3 |
| AC-20 | T015, T021, T028 | 1 / 2 / 3 |
| AC-21 | T022, T028 | 3 |
| AC-22 | T001, T002, T012, T013, T014, T021 | 1 / 2 |
| AC-23 | T028 | 3 |
| AC-24 | T028 | 3 |
| AC-25 | T028 | 3 |
| AC-26 | T025, T028 | 3 |
| AC-27 | T001, T002, T015, T021 | 1 / 2 |
| AC-28 | T022, T023 | 3 |
| AC-29 | T024 | 3 |
| AC-30 | T026 | 3 |
| AC-31 | T026 | 3 |
| AC-32 | T025 | 3 |
| AC-33 | T027 | 3 |
| AC-34 | T027 | 3 |
| AC-35 | T031 | 4 |
| AC-36 | T031 | 4 |
| AC-37 | T031 | 4 |
| AC-38 | T031 | 4 |
| AC-39 | T033 | 4 |
| AC-40 | T033 | 4 |
| AC-41 | T033 | 4 |
| AC-42 | T033 | 4 |
| AC-43 | T032 | 4 |
| AC-44 | T033 | 4 |
| AC-45 | T032, T033 | 4 |

**统计**：33 任务 / 4 Wave / `[MVP-核心]` 21 条（T001–T021）/ 未覆盖 AC **0** 条。
**任务类别分布**：基础设施 3（T001–T003）· 后端 Domain 与 Service 13（T004–T016）· 前端 Client 2（T017–T018）· 前端 Platform 2（T019–T020）· 部署与验收 1（T021）· 顺延 12（T022–T033，含后端 6 / 前端 3 / 纯验收 3）· Worker **0**。

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

| 任务 | 偏差 | 回写到 design | 原因（一句话） |
|---|---|---|---|
| T008 | 测试落 `test/app_runtime/test_square_scan_page.py`，不是 tasks 写的 `test/workflow/` | §7 单测目录 | 三表 + 同库 sync/async 双 session 的 `build_list_env` 夹具是 `test/app_runtime/conftest.py` 的，pytest 夹具不跨包；为凑路径复制 200 行夹具更糟 |
| T009 | `app_state` 无需回查——F054 第三支已投第 10 列并由 `_app_row_to_dict` 只给托管行落键；本 Feature 只补 `slug` | D2 / §4.2「广场列表项 `app_state`」标注为 F056 新增 | F054 已交付，重复补入会造第二处真相 |
| T007 | `status` 豁免抽成 `FlowDao._build_status_clause`；`app_state_in` 下推进 `_build_apps_subquery`（新增可选参数） | D9「具体形状」 | 下推让草稿在行集层就不存在（AC-03「不因 owner 或管理员而例外」无需二次判权），且外层条件可单测 |
| T014 | 注册落 `api/services/f048_permission_runtime.py` 的 `initialize_f048_api_runtime`，**不动 `main.py`** | D6「注册落点」 | 与 tasks 跨 Feature 副作用表 T014 行一致；该处正是 `mutate_grants` 的构造处，二者同生共死，且避开并发编辑 `main.py` |
| T014 | `metadata` 增 `moved`（MOVE 的主体身份 + 目标 model_key） | §4.2 审计 metadata 形状 | MOVE 的主体身份与 REMOVE 一样事后不可还原；只记 added/removed 会让「某人从 viewer 升为 editor」在审计里彻底消失 |
| T015 | 拆成两个参数化用例：`AppAuditAction` 硬断言 + `app.release.*` 走 `xfail(strict=True)` | §7 登记断言测试 | F055 尚未补 `log.ts` / 三语 `bs.json`，直接断言会让本 Feature 的新测试为别的 Feature 挂红；`strict=True` 保证 F055 落地当天该用例 XPASS 报错、强制删除待办项 |
| T011 | 连带修 `test/workstation/test_workstation_apps_rebac.py`（2 处断言）与 `test_f040_workbench_cursor.py`（1 处 mock 签名） | 无（tasks 跨 Feature 副作用表已认账该文件） | `filter_apps_by_action` 增参数是有意的签名变更，桩与断言须同步 |
| T018 | 第 3 件「未部署形态文案闸」未实现 | D8 / §6.2 F054 T071 行 | 上游 `client/src/hooks/useAppRuntimeEnabled.ts`（F054 T071）尚未落地；且广场今天**没有**任何托管应用专属文案可隐藏（唯一的托管 UI 是按行数据驱动的「已停用」角标），开关关时后端天然无 `app` 行 → AC-10 由数据侧独立成立 |
| T003 | 勘误 ② 已由 F054 落实（`get_online_flows_page` 的 tag 预过滤第 4 处已含 `ResourceTypeEnum.HOSTED_APP`）；③ 经核查 F054 未加等价参数，故由 T007 新增并沿用本文命名；① TTL 300s→1800s **仍未回写**（F054 访问记录尚未实现，`app_access` 全仓仅一处 TODO 注释） | 无 | 三条勘误逐条落地确认，①待上游 |
| 测试基建 | `test/app_runtime/conftest.py` 增两个 session patch 目标（`bisheng.api.services.workflow`、`bisheng.app_runtime.domain.services.visibility_audit`） | 无 | 二者各自按名字绑定 `get_async_db_session`；不加则测试打到真 MySQL |

## 2026-08-18 · 主 agent 裁决与顺带修复

1. **`metadata.moved` 保留**（实施方问是否要删）。§4.2 只列了 `added / removed / model_keys`，但 **MOVE 恰恰是最该留痕的那种变更**——「某人从 viewer 升为 editor」只记 added/removed 会在审计里彻底消失，而它的权限影响不比新增小。主体身份事后不可还原这一点与 REMOVE 同理。代价是三行。design §4.2 应随之补记该键。
2. **`app.release.*` 的前端半边已补齐（16 条 × log.ts × 三语），T015 的 `xfail(strict=True)` 哨兵已摘除、转为正常断言（30 passed）。** 实施方测出的这个缺口是真的：后端白名单 17 条、前端 0 条——**发布事件写进了库却在审计页一条都筛不出来**，正是 F054 坑 24 记载的同一种失效，AC-27 判的就是筛得出来而不是写得进去。哨兵的设计在这里完全奏效：补齐当天 16 条全部 XPASS(strict) 报错，强制把待办项删掉而不是让它静静地活过它所描述的缺口。
3. **越出「只改」清单的四个文件属正当**：`api/services/workflow.py` / `permission/application/resource_api.py` / `api/services/f048_permission_runtime.py` / `database/models/app.py` 都是 tasks.md 的 T005/T009/T011/T013/T014 直接点名的，不改则 F056 什么也做不成；我给的清单是并发边界（避开另两路的战场），不是任务范围，实施方按 tasks.md 执行且严格避开了四个「不碰」目录，判断正确。
4. **T003 勘误①（访问记录合并窗口 300s → 1800s）登记为待办**：`app_access` 全仓只有 `tenant_filter.py:117` 一句 TODO，功能未实现，无处可回写——等该功能落地时随它一起定，不在本轮制造一个指向空处的引用。
5. **T016 / T021 未做属正确取舍**：前者要真 FGA + MySQL 才有意义（AC-05 授权→撤销、AC-06 与入口判定同真同假、AC-15 被授予者调 grants 得 403），本地无中间件；**没写一个跑不起来的空壳是对的**——空壳会让人以为覆盖到了。后者要 114 环境与非管理员账号实操。两条都随 114 联调一起做。

