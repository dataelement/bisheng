# Design: 应用广场接入与治理面（RT-02 广场 + GOV-01 授权交互 + GOV-04 审计登记）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（45 条 AC、边界、11 条决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；但每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 按分支 `3.0-vibe` **HEAD `11e1b211d`**（*F054 Wave 2「托管应用统一入口」*；2026-08-17 复核基线。探查笔记原写的 `084c1e134` **不在本分支历史上**（`git merge-base --is-ancestor` 为假），已作废——**F054 Wave 1 已落地**：`FlowType`/领域模型/`app` 资源类型注册/`app.*` 审计九条已在库；Wave 2 runtime-manager 已落地；**F054 前端 Wave 3 未落地**）于 2026-08-17 由探查笔记 `e1-square-authz-audit.md` 逐条核实并由本文作者复核。路径以 `src/backend/bisheng/` 为根，前端另注 `client/` = `src/frontend/client/src/`、`platform/` = `src/frontend/platform/src/`。**行号会漂、符号名不会**——落地前一律以符号名重定位；F054 Wave 3 落地后 platform 前端行号必漂。
>
> **本文是"要建成的样子"**：F056 尚未开工。凡标「F054 交付」的锚点在写作时可能还不存在（如 `hostedApp/tabs/PublishTab.tsx` 的 slot），本 Feature 的落地顺序依赖 F054 Wave 3。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待写）· [release-contract.md](../release-contract.md)（表 3 F056 行；错误码 **163** 段）· [mvp-114-path.md](../mvp-114-path.md)（**§6 MVP-核心是本轮裁剪基准**、§3 114 环境事实）· 上游 [F054 design](../054-app-domain-runtime/design.md)（D8 后端 6 组硬闸 / D13 详情页壳与 slot / §4.2 契约 / 坑 8·25）· [F055 spec](../055-app-publish-pipeline/spec.md)（发布 tab 其余区块、`app.release.*`）· [F049 design](../049-openapi-auth-baseline/design.md) **D11**（审计四处 lockstep 的既有做法，commit `43e73bfc5` 已落地一次，本文照其形状）
**版本**: v3.0.0
**最后更新**: 2026-08-17（初版 + 审查修订 14 条）

---

## 1. 目标与非目标

- **目标**：把 F054 立起来的「托管应用」接到**用户看得见的两个面**上——① client 应用广场把已上线 / 已下线的托管应用与工作流 / 助手**并列**成同构卡片、按可见范围过滤、点击整页跳 `/apps/{slug}`；② 用平台既有的 `PermissionDialog` 在**两个入口**（构建页卡片 ⚙️「管理权限」、应用详情页 · 发布「可见范围区」）设可见范围，并把「可见范围变更」这一类事件写进审计。一句话：**让同事能找到它、让 owner 能放行它、让管理员能查到谁放行了它**。

- **非目标**（防后人误扩范围；按 `mvp-114-path.md` §6 MVP-核心裁剪，**顺延项属本 Feature 范围、不得被裁掉**，落点方向逐项给出）：
  - **审计查询面扩展与导出**（AC-28 / AC-29 / AC-32 新增「对象应用」筛选 + 导出按钮）——顺延。落点方向：后端 `GET /api/v1/audit`（`api/v1/audit.py:13-27`）与 `AuditLogDao.get_audit_logs`（`database/models/audit_log.py:288-374`）今天**完全没有 target_type / target_id 维度**，要新增两个查询参数 + 一个按名称检索应用的选择器端点；导出照会话数据面既有形态（`platform/controllers/API/log.ts:287-314 exportCsvApi` → `/api/v1/audit/session/export*`）另加一个系统操作面的导出端点。**这是从零新增，不是改配置**。
  - **平台超管租户筛选与租户列**（AC-30 / AC-31）——顺延。落点方向：审计租户边界今天在 `AuditLogDao._visible_for_tenant` + `AuditLogService._get_audit_tenant_scope`，超管跨租户是加一个 `tenant_id` 查询参数 + 列表增列，不动写入侧。
  - **§3.0.3 事件触达全表接线**（AC-39–AC-45，含本 Feature 唯一自有的「租户管理员下线 / 重新上线 → owner」AC-43）——顺延。落点方向：挂在 F054 `AppStateService.stop/resume` 的后置钩子上，复用平台既有站内消息能力（与审批中心同一通道），**发送失败只记日志不回滚**。
  - **GOV-07 界面通道验收**（AC-35–AC-38）——顺延。它是**零改动的回归验收**（`create_app` 权限点与菜单模型平台既有），本轮不产出代码。
  - **标签接入验收**（AC-08 的标签体系部分）与 **⚙️ 菜单裁剪回归验证**（AC-16）——顺延，实现分别归 F054 T060 / T064 / T065。
  - **`app` 资源类型注册本身**（后端 catalog / FGA 模型 / 前端三处 `ResourceType` union / 存量环境生效脚本）——**F054 已落地**，本 Feature 只消费、不重写。
  - **除「可见范围变更」外的任何审计事件写入**——归各动作 owner（F054 状态动作 / F055 管线 / F049 密钥 / F051 模型调用）。本 Feature 只做**登记**与**可查性**。
  - **入口后的一切行为**（登录回跳 / 四类兜底页 / 身份注入 / 反代）——F054；广场只负责把浏览器送到 `/apps/{slug}`。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md) **C1–C7**，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| **K1** | **广场列表的租户隔离是手工的，自动过滤在这里失效**：广场走 `FlowDao.aget_all_apps`（`database/models/flow.py:508`）→ `_build_apps_subquery`（`:660-702`）。该函数 docstring（`:661-671`）明写：租户自动过滤监听器只看外层查询的 `column_descriptions`，`.subquery()` 一包就失效，**每一支 UNION 都必须自己 `build_tenant_filter_clause(...)`**（`flow_clause` `:695` / `assistant_clause` `:698`）。第三支（`App`）由 F054 T059 落，但它有 **4 个调用方**（`get_all_apps:420` / `aget_all_apps:508` / `get_all_app_by_time_range_sync:810` / `get_first_app:849`）——漏写就是四条路径一起跨租户泄漏。**F056 不写这支，但广场是它最直接的消费者，回归责任在本 Feature**（`test/workflow/test_flow_dao_tenant_isolation.py` 已覆盖这四个方法） | C3；memory `reference_tenant_filter_in_list_trap`；F054 design K5 ③ |
| **K2** | **管理员身份短路发生在动作合法性校验之前**：`permission_action_service.py:372-384 _identity_shortcut` 三条判定（`SUPER_ADMIN` → allow / `TENANT_MISMATCH` → deny / `TENANT_ADMIN` → allow）**与 action 无关**，且在批量路径里发生在 `_prepare_action_target`（`:244`）**之前**。含义有二：① 租户管理员天然看到本租户全部托管应用——决议-4「不额外收窄」在实现上是**零工作量**；② 任何"某 action 对 `app` 类型非法"的错误**只炸普通用户**，管理员账号永远测不出来（见坑 1、§7 验收红线） | `permission/domain/services/permission_action_service.py:372-384`；memory `reference_remote_dev`「health 200 会骗人」 |
| **K3** | **审计事件的"写了必须查得到"靠四处 lockstep，缺一即静默失效**：① 后端 `_UI_VISIBLE_V2_ACTIONS`（`database/models/audit_log.py:193`，作用点 `_ui_visible_predicate:272-282` = `OR(system_id IS NOT NULL, action IN (...))`，被 `get_audit_logs:329` 与 `get_all_operators:408` 应用）；② 动作枚举 `AppAuditAction`（`app_runtime/domain/constants.py:82`，其 docstring `:9-13` 已把 lockstep 写死）；③ 前端 `platform/controllers/API/log.ts` 的 `actions` 数组 app 段（`:136-144`）；④ 三语 `platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 的 `log.eventTypeEnum`。命名空间前缀 `_V2_NAMESPACE_TO_ACTION_PREFIX`（`:261`，`"app": "app."`）与模块下拉（`log.ts:49`）、`getActionsByModuleApi` 的 `case 'app'`（`:166`）**F054 已落，无需再动**。**不在白名单 = 写库但页面查不到**，这是 AC-27 的实现锚点 | F049 design **D11**（同形态四处 lockstep，`open_api.*` 已落地一次）；F054 T007 |
| **K4** | **两个 SPA 不可混用，且各自有一条被 lint 冻结的路**：client（Vite 6 / **Recoil 已冻结**，`client/eslint.config.mjs:47` / react-query **v4** `@tanstack` / shadcn / alias `~/` 与 `@/` 并存 / base `/workspace`）与 platform（Vite 5 / Zustand / **react-query v3 已冻结**，`platform/eslint.config.mjs:45,51` / bs-ui / alias `@/`）。**广场在 client、授权与审计在 platform**——同一件事（可见范围）的两个面分属两个应用，任何"抽个共享组件"的念头在这里都不成立（两套 UI 库、两套状态管理） | 根 `CLAUDE.md` §4；`client/AGENTS.md`；`platform/AGENTS.md` |
| **K5** | **广场卡片跳的地址不在 client 的路由空间里**：`/apps/{slug}` 由 nginx `location /apps/` 直达 app-proxy（F054 交付），**不是** client SPA 路由；而 client 的 vite `base` = `/workspace`（`client/vite.config.ts:127`），react-router 的 `navigate()` 会自动前置 basename。**任何用 `navigate()` 或拼 `__APP_ENV__.BASE_URL` 的写法都会得到 `/workspace/apps/{slug}` → 404** | `mvp-114-path.md` §3；F054 design D5 |
| **K6** | **`share` 动作对 `app` 类型不存在**：`permission/domain/services/catalog_policy.py:71` 的 `"share": frozenset({"knowledge_space","knowledge_file","workflow","assistant"})` **不含 `app`**；而请求 `share` 的地方有 **5 处**：广场列表无条件请求 `("visible"/"use", "edit", "share")` 三个动作（`api/services/workflow.py:425`），以及 `aenrich_apps_can_share:133` 的 `("share",)` 及其 **4 个调用方**（`workstation/apps.py:53` / `:150` / `chat.py:83` / `workflow.py:962`）。这不是"可以顺手加个 share"——托管应用没有 share-token 免登录通道（决议-6），**加 share 就是造一个不存在的能力** | `catalog_policy.py:60-75`；spec 决议-6 |
| **K7** | **广场的可见性判定必须与入口判定同源**：F054 入口用 `check_business_action("app", app_id, actor, "use")`（F054 design `:239` 明写「不用 `runtime.check_visible`——后者对『授了 editor 但没 use』的自定义模型更宽」），而广场今天默认传 `action='visible'`（`client/src/api/apps.ts:429` 前端默认值 + `explore.tsx:62` 不传该参数 → 落到默认 `'visible'`；未分类 tab 更是 `workflow.py:1010` 硬编码 `"visible"`）。`visible` 与 `can_use` 在 FGA 模型里是**两条不同关系**（`permission_action_service.py:272-322 batch_check_visible` vs `:223-270 batch_check_actions`；`_normalize_action:366-370` 明确把 `"visible"` 排除在 `REGISTERED_ACTION_CODES` 外）。不统一 = AC-06 明令禁止的「广场看得见、点进去无权限」稳态 | spec AC-06；F054 design D8 动作集合 |
| **K8** | **应用态五值与列表 `status` 两值是两套语义**：`getAppsApi` 只放行 `status ∈ {1,2}`（`platform/controllers/API/flow.ts:204`）、后端 `flow.py:582 sub_query.c.status == status`；F054 第三支把「已上线」投 `2`、其余四态投 `1`，五值另走**独立的应用态条件**（F054 给构建页开了 `app_state` 查询参数；广场不复用它，见 D9）。而广场硬传 `FlowStatus.ONLINE.value`（`api/v1/chat.py:63`）→ **已下线应用天然进不了广场**，与 AC-03 / 决议-5 正面冲突。这是本 Feature 必须解的口径问题（D9） | `api/v1/chat.py:63`；F054 design D8 |
| **K9** | **审计写入自带事务与租户旁路，且非全局管理员可能永远查不到**：`AuditLogDao.ainsert_v2`（`database/models/audit_log.py:428`）自带 `bypass_tenant_filter()` + 独立 async session + commit（`:494-500`），调用方**不要再包事务**；同时 `ainsert_v2` **从不填 `group_ids`**，而 `api/services/audit_log.py:78-101 get_audit_log` 对非 `is_admin()` 且无「日志菜单」权限的用户会把 `groups` 填成其管理的用户组，DAO 随即施加 `json_array_contains(AuditLog.group_ids, ...)`（`audit_log.py:337-342`）→ **这类用户查不到任何 v2 结构化事件**（`app.*` 与 `open_api.*` 同病）。114 验收账号必须是 `is_admin()` 或持日志菜单权限者，否则会误判成"事件没写" | `database/models/audit_log.py`；`api/services/audit_log.py:78-101` |
| **K10** | **MVP-核心边界与 114 形态**：本轮只做「广场接入 + 两入口授权 + 可见范围变更审计三类事件可查」（`mvp-114-path.md` §6 F056 行）。114 上 `/apps/` location 在 `/etc/nginx/conf.d/bisheng-lilu.conf`（F054 加，外网另有 `bisheng-external-13000.conf` 静态快照需手动重建）；广场验证必须用**非管理员账号**（K2） | `mvp-114-path.md` §3 / §6 |
| **K11** | **错误码段 163**（`app_factory` · F056 段，`release-contract.md:100`）。**本轮 MVP-核心不落任何新错误码**——广场列表复用既有响应、授权走 F048 既有错误码（`permission_error_response`）、审计写失败被吞。顺延的审计查询面若需要（如「对象应用不存在」）再从 `16301` 起，落码时须在同一次改动内回写 `docs/constitution.md` C5 登记表 + `packages/locales/src/api_errors/{zh-Hans,en,ja}.json` 三语（生成物勿手改，CI `pnpm check-i18n` 校验） | C5；release-contract 错误码表 |

**Constitution Check（自查）**：

- **C1（DDD 分层）**：本 Feature 后端改动集中在 `api/services/workflow.py`（既有 application service）与 `permission/application/resource_api.py`（既有 application 层）；**不新建后端模块**。审计写入不由 `permission` 模块直接发 `app.*`——那会让权限模块知道应用工场的命名空间；改用**回调注册表**由 `app_runtime` 侧注册写入器（D6），依赖方向仍是 `app_runtime → permission`，反向为零。
- **C2（双 DB）**：**零 DDL**。广场列表新增的 `slug` / `app_state` 两个载荷字段来自 F054 已建的 `app` 表显式列（F054 K4 已保证它们不是 JSON 字段、可 SQL 筛）；审计复用既有 `audit_log` 表的 `action` / `target_type` / `target_id` / `metadata` 结构化字段（`database/models/audit_log.py:117-158`），不加表不加列。
- **C3（多租户）**：见 K1。广场只列当前租户（UNION 三支各自的手工租户条款 + `_identity_shortcut` 的 `TENANT_MISMATCH` 兜底）；审计租户边界沿用 `AuditLogDao._visible_for_tenant`。本 Feature **不新增任何绕过租户过滤的读路径**；唯一的 `bypass_tenant_filter` 出现在 `ainsert_v2` 内部（既有）。
- **C4（权限）**：广场过滤只经 `permission/application/business_authorization.py:64 batch_check_business_actions`（既有唯一入口），**不新建判定路径、不直连 OpenFGA**；授权读写全部走 F048 既有端点 `GET/POST /api/v1/permissions/resources/{type}/{id}/grants*`（`permission/api/endpoints/grant.py`）。「非 owner 非管理员打不开弹窗」（AC-15）的前端闸是 `can_manage_permission`（`GET .../context`），**后端 403 由端点自身兜**——前端闸只是体验，不是安全边界。
- **C5（错误码）**：见 K11。
- **C6（无硬编码密钥）**：不涉及。
- **C7（前端 store 不直连 HTTP）**：client 广场的新读取（`app_runtime_enabled`）走 react-query v4 hook + 既有 `~/api` 封装（**不 import axios、不进 recoil store**，K4）；platform 可见范围区走 `controllers/API/permission.ts` 既有封装。

---

## 3. 方案对比与选定

> 每条 3 段：备选 / 选定 / 原因 + **何时该重新考虑**。本节是"想当然会走但被否决"的路的登记处。

### D1：广场第三类型接入 = 扩既有 UNION + 既有批量扫描范式（不并列查询后合并）

- **备选**：
  - A. **并列查询后在应用层合并**（工作流 / 助手走既有 UNION，托管应用另起一条 `SELECT app`，Python 侧归并排序分页）— 优点：完全不碰既有 SQL，回归面看似最小；缺点：**分页与排序必然撕裂**——广场的分页是「keyset 游标 + 批量鉴权后按整页长度判 `hasMore`」的扫描式分页（`workflow.py:401 _scan_visible_apps_page` + `explore.tsx:74 hasMore = pageData.length >= pageSize`，后端**不返回 total**），两条流各自扫、各自被权限过滤后再归并，同一页会出现"跳号 / 重复 / 提前判无更多"；排序字段（`update_time`、置顶 `ranking_user_id`）也要在 Python 里重排整个候选集，等于把数据库分页搬进内存
  - B. **扩既有 `_build_apps_subquery` 第三支**（选定）— 一条 SQL、一套分页、一套排序、一套权限过滤范式
  - C. **先用 FGA `ListObjects` 预取可见 id 集，再用 `id_list` 收窄 SQL**（`permission/application/runtime.py:177-189 list_action_objects`）— 优点：大租户下省掉"扫一批查一批"的往返；缺点：与工作流 / 助手的分页范式**不同源**，同一个列表里两类走两条判定路径，AC-06「同源一致」反而更难保；且 F054 入口未用它
- **选定**：**B**。第三支由 **F054 T059 落**（`database/models/flow.py:660-702`），F056 **不重复实现**，只做三件事：① 消费；② **验收**（非实现）tag 预过滤第 4 处 `workflow.py:517-528`——归属仍是 F054 T060，见 §4.3；③ 承接回归责任（K1）。
- **原因**：广场今天这套「UNION 子查询 → `filter_supported_apps`（`workflow.py:83`，`SUPPORTED_APP_TYPES:76` 是唯一硬闸）→ `_application_action_map:146` 分桶 → `batch_check_business_actions` 切片 100 条（`business_authorization.py:24 _MAX_BATCH_CHECKS`）→ 按 action 命中筛 `kept:450-455`」的范式**已经内置了**超管整批短路（`business_authorization.py:78-83`）、租户短路、缺失资源跳过（`:97-112` 捕获 `InvalidCatalogActionError` / `PermissionInvalidResourceError` 并跳过该条）、keyset 续扫。第三类型只要"长得像另外两类"就白拿这一切。F054 design `:615` 已把这条写成对 F056 的契约：「`get_online_flows_page`（`workflow.py:514`）走同一道 `SUPPORTED_APP_TYPES` 闸，F056 直接受益，**不要重复改**」。
- **何时该重新考虑**：单租户托管应用数量进入千级、扫描式分页的往返成本可测量地拖慢广场首屏时（那时按 C 对**全部三类**统一改造，而不是只给 `app` 开小灶——小灶就是 AC-06 的裂缝）。

### D2：卡片跳转 = `window.location.assign('/apps/{slug}')` 整页跳、当前窗口、不带 base；`slug` 随列表载荷下发

- **备选**：
  - A. `navigate('/apps/{slug}')`（react-router）— **必错**：自动前置 basename `/workspace`（K5），得到 `/workspace/apps/{slug}` → client SPA 内无此路由 → 404
  - B. `window.open(..., '_blank')` 新窗口 — 缺点：与工作流 / 助手卡片"当前窗口进入"不一致；且 F054 四类兜底页都带「返回广场」按钮，**新窗口下这个按钮语义不成立**（决议-6）
  - C. **`window.location.assign('/apps/{slug}')`**（选定）
  - D. 后端返回完整 `entry_url` 由前端直接跳 — 优点：不用前端拼路径；缺点：广场列表是 UNION 出来的通用载荷，为一种类型塞一个完整 URL 字段会让另两类的载荷形状变得不对称；且 F054 详情页已有 `entry_url`（`GET /api/v1/apps/{id}`），广场再要一份是重复真相
- **选定**：**C**，跳转前不写 `sessionStorage` 的 `app-flow-origin` / `app-last-origin`（`explore.tsx:18-19,136-137` 是对话页返回用的，托管应用离开 SPA 后不回来）。`slug` 由 **F056 补进广场列表载荷**——`_build_apps_subquery` 的列集是固定九列 `(id, name, description, flow_type, logo, user_id, status, create_time, update_time)`，**没有 `slug`**，所以要么加进 UNION 列集（三支都得投一列，另两支投 NULL），要么在 `add_extra_field`（`workflow.py:87-127`）里按 `flow_type==35` 的 id 批量回查 `app.slug` 补上。**选后者**：UNION 列集是 4 个调用方共享的，为广场一个消费者加列会波及构建页与商业版增量同步（`scripts/sync_increment_table.py:53`）；而按 id 批量回查一次 `app` 表与既有做法同构（`add_extra_field` 本来就在批量拉 `UserDao.get_user_by_ids:103` 与 `FlowVersionDao.get_list_by_flow_ids:107`）。
  - **⚠️ 补入点不是 `add_extra_field`，是 `_scan_visible_apps_page`（`workflow.py:401-478`）**：广场两个入口只有后者是共同下游。`get_online_flows_page` 末尾确实调 `add_extra_field`（`:548`），但**未分类 tab 的 `get_uncategorized_flows` 从不调它**——它只做 `one["logo"] = get_logo_share_link(...)` 后直接 `_apply_page_can_share` 返回（`:1012-1016`）。把补入写进 `add_extra_field`，未分类 tab 的托管应用卡片就**没有 `slug`（点击落 `/apps/undefined`）、也没有 `app_state`（AC-03「已下线」角标不出现），且不报错**——而 §7 恰恰把未分类 tab 指定为唯一正确的验收面（坑 8）。故：在 `_scan_visible_apps_page` 返回整页之前，对 `flow_type==35` 的行**批量一次**回查补字段（`WorkFlowService._attach_hosted_app_entry_fields` → `AppDao.alist_slug_state_by_ids`）；`get_uncategorized_flows` 与 `get_online_flows_page` 都经过它，两个入口一次到位。**落地订正（2026-08-18）**：实际只需补 `slug` —— F054 第三支已把 `App.state` 投成 UNION 第 10 列、并由 `FlowDao._app_row_to_dict` 只对托管行落 `app_state` 键，所以 `app_state` 是白拿的；回查里仍带上 `state`，但只在该键缺失时兜底填入（投影若改，这里不至于静默变空）。
- **原因**：C 是唯一同时满足「同窗口（决议-6）+ 跨出 client base + 不改另两类载荷形状」的写法。**现成反例必须点名**：`client/src/pages/apps/appUtils.ts:67-71 getAppShareUrl` 用的是 `window.location.origin + __APP_ENV__.BASE_URL + '/share/...'`——照抄它就会把 `/workspace` 加回去，**托管应用恰恰不能加 `BASE_URL`**。
- **何时该重新考虑**：产品要求广场卡片支持"新标签打开"（那时是 A/B 之外的第三态：按住 Ctrl 的原生行为——那需要卡片改成真 `<a href>`，是一次组件改造，不是一行 navigate）。

### D3：动作集裁剪**分两层**——合法性过滤落 `_application_action_map`（惠及全部 7 个调用方），`visible`→`use` 的口径切换只落 `_scan_visible_apps_page`（广场两入口）

- **备选**：
  - A. **广场整体改传 `action='use'`**（`client/src/api/apps.ts:429` 默认值 + `workflow.py:1010` 硬编码一起改）— 优点：一处改完、三类型口径统一；缺点：**改变了工作流 / 助手的既有可见集**（`visible` 比 `can_use` 宽），回归面覆盖广场全部存量行为，MVP-核心期不可控
  - B. **只改 `_scan_visible_apps_page` 的 `requested_actions`**（把 `app` 桶换成 `("use","edit")`）— **不够**：非法的 `share` 请求**不止广场这一处**（见下表 `aenrich_apps_can_share` 的四条路径），只裁剪广场，坑 1 在工作台推荐位 / 常用列表 / `sort_by=update_time` 分支照样触发
  - C. **两层分开：合法性过滤下沉到分桶函数、可见性口径切换留在广场**（选定）
  - D. 保持全部 `visible`，改 F054 入口也用 `visible` — **反向违约**：F054 design `:239` 已论证 `visible` 对"授了 editor 但没 use"的自定义权限模型更宽，会让可见范围口径与 `PermissionDialog` 授的档位语义不一致
- **选定**：**C**。两层的职责必须写死，否则实现者会把两件事塞进同一个函数，连带改掉应用中心与构建页的既有语义：

  **第一层 · 合法性过滤（落 `WorkFlowService._application_action_map`，`workflow.py:146-178`；影响全部 7 个调用方）**
  分桶（`grouped:152-155`，F054 T060 加第三桶 `35: "app"`）之后、发 `batch_check_business_actions` 之前，**每个桶只请求对该 `resource_type` 合法的 action**，判据 = `catalog_policy.ACTION_RESOURCE_SCOPES`（`permission/domain/services/catalog_policy.py:60-75`——与真正抛错的 `_prepare_action_target` 读的是同一张表，`permission_action_service.py:387-398`）。
  - **`visible` 必须显式豁免**：它不是注册动作——`_normalize_action`（`permission_action_service.py:366-370`）把 `"visible"` 排除在 `REGISTERED_ACTION_CODES` 外、走 `batch_check_visible` 另一条路，`ACTION_RESOURCE_SCOPES` 里根本查不到它。不豁免 = 把另两类的可见性动作一并滤掉 = **广场空列表**。
  - 今天的效果：`workflow` / `assistant` 桶请求集**逐元素不变**（`use`/`edit`/`share` 对二者全合法）；`app` 桶唯一被滤掉的是 `share`（K6）。
  - 这一层才是坑 1 的**真正解**：`aenrich_apps_can_share`（`workflow.py:129-143`）无条件请求 `("share",)`，四个调用方全会踩——`workstation/api/endpoints/apps.py:53`（工作台推荐应用）、`:150`（常用 / 最近使用）、`api/v1/chat.py:83`（`/chat/online` 的 `sort_by=update_time` 分支）、`workflow.py:962`（`get_frequently_used_flows`）。裁剪后 `app` 桶请求集为空 → 该桶不发起 check → `can_share` 落回 false（`aenrich_apps_can_share:139` 与 `_apply_page_can_share:493` 都是"命中才 true"）→ **AC-07 后半句零改组件达成**。

  **第二层 · 可见性口径切换（只落 `_scan_visible_apps_page`，`workflow.py:401-478`；只影响广场两入口）**
  - `requested_actions`（`:425`）由「一个全局元组」改为「按桶取值」：`workflow`/`assistant` → 原样 `(action, "edit", "share")`（`share` 交第一层裁，**此处不动，保持第一层是唯一裁剪处**）；`app` → `("use", "edit")`。
  - `kept` 筛选（`:450-455`）不能再用外部传入的 `action` 一刀切，改为**按行的 `flow_type` 取该桶实际请求的可见性 action**（`app` 行看 `use`，其余行看 `action`）。
  - 实现形状：给 `_application_action_map` 加一个可选参数（如 `actions_by_type: dict[str, tuple[str, ...]] | None = None`）做按桶覆盖，缺省 `None` = 全桶用 `actions` —— **另 6 个调用方一行不改**。

  **爆炸半径（7 个调用点逐条认账）**

  | 调用点 | 传入 actions | 第一层影响 | 第二层影响 |
  |---|---|---|---|
  | `aenrich_apps_can_share:133` | `("share",)` | **app 桶请求集变空 → 不再抛 25001**，`can_share=false`；另两类不变 | 不涉及 |
  | `get_all_flows:246`（构建页 / `sort_by=update_time`） | `(required_action, "edit")` | 不变（`use`/`edit`/`visible` 对 app 均可请求） | **不涉及**——构建页仍按外部传入的 action 判定 |
  | `_scan_visible_flows_cursor:356`（游标版构建页） | 同上 | 不变 | 不涉及 |
  | `_scan_visible_apps_page:445`（**广场两入口**） | `(action, "edit", "share")` | app 桶去掉 `share` | **唯一改口径处**：app 桶可见性 = `use` |
  | `filter_apps_by_action:671`（应用中心 `get_frequently_used_flows:941` / `workstation/apps.py:41`） | 单 action | 若该 action 对 app 非法 → 请求集空 → **该类型被静默滤掉**（不抛错） | 不涉及 |
  | `aget_writeable_app_ids:692` | `("edit",)` | 不变 | 不涉及 |

  最后一格要留意：第一层把「抛 25001」换成了「静默滤掉」。这**恰好**是坑 10 想要的效果，但它是静默的、且只在 action 非法时才发生（`use` 对 app 合法，应用中心传的正是 `use`，托管应用照样会流进去）——**坑 10 的显式排除仍要做，不得依赖这个副作用**。
- **原因**：① AC-06 要求广场与入口同源，而入口是 `use`（F054 已定），所以要动的是广场侧；② A 的回归面在 MVP-核心期不可接受——广场是全体用户每天进的页面，"工作流突然少了几个"比"托管应用暂时不完美"严重得多；③ 把合法性过滤下沉一层，是因为**非法动作的触发点由"谁在请求"决定、不由"哪个页面"决定**——`aenrich_apps_can_share` 的四个调用方没有一个属于广场，却全都会踩。
- **何时该重新考虑**：F048 权限模型把 `visible` 与 `can_use` 合并成同一条关系（那时三类型可统一为一个 action，第二层可删）；或 `ACTION_RESOURCE_SCOPES` 变成运行时可配（那时第一层的常量对齐要改成读同一份配置，并加对账断言）。

### D4：授权弹窗第二触发点 = 新建 `VisibilityScopeSection` 填 F054 的 slot，内部复用同一个 `PermissionDialog`

- **备选**：
  - A. 直接改 `PublishTab.tsx` 本体插入区块 — 缺点：F054 T067 / F055 design `:356,:363,:627` 已三方约定「发布 tab 用 slot / children 给 F055 与 F056 留位，**避免三个 Feature 改同一文件冲突**」；直接改本体等于毁约，且并发期必冲突
  - B. **新建 `hostedApp/publish/VisibilityScopeSection.tsx` 填 slot**（选定）
  - C. 为托管应用做一个专用的授权面板（不用 `PermissionDialog`）— **直接违反 AC-11**（两个入口必须是同一个弹窗），且会造出第二套授权语义
- **选定**：**B**。区块内部只做三件事：读状态（`GET /api/v1/permissions/resources/app/{id}/grants` → `getResourcePermissionGrantsApi`，`platform/controllers/API/permission.ts:313-327`）、渲染「仅 owner 可见」提示条或已授主体摘要、点按钮 `setOpen(true)` 拉起 `<PermissionDialog resourceType="app" resourceId={app.id} resourceName={app.name} />`（`platform/src/components/bs-comp/permission/PermissionDialog.tsx`，props `:26-32`）。弹窗关闭后**重新拉一次 grants** 刷新摘要（不做乐观更新——授权是低频动作，一次往返换准确性）。
  - 另一个入口（卡片 ⚙️「管理权限」）**F054 T063 已接线**：`platform/src/pages/BuildPage/apps.tsx:215-218 handleOpenPermission` 的 `typeMap` 补 `35: 'app'`、`:139-140 useResourceActions` 加第三桶、`:150 canManage` 判 `manage_permission`、`:415-423` 弹窗挂载均为既有结构。F056 **只做回归验证**（AC-16）。
  - `PermissionDialog` 组件本身**无 per-type 分支**（F054 design `:250` 原话），三处 `ResourceType` union 已含 `app`（`platform/controllers/API/permission.ts:19`、`platform/components/bs-comp/permission/types.ts:16`、`client/src/api/permission.ts:15`），**本 Feature 对弹窗零改动**。
- **原因**：slot 是三方书面约定，B 是唯一不制造合并冲突的落法；复用弹窗是 AC-11 的字面要求，也天然满足 INV-29（选人不出现服务账号——`permission/domain/services/grant_subject_service.py:95` 的 `User.user_type == USER_TYPE_HUMAN` 过滤在数据层，**AC-11 的这半句是回归验证不是新工作**）。
- **何时该重新考虑**：F055 交付发布 tab 后 slot 机制被改成别的（如 tab 内路由）——那时本区块跟着换挂载点，内容不变。

### D5：「仅 owner 可见」的判据 = grants 首页里**非 protected** 的授权行数为 0，不是"列表为空"

- **备选**：
  - A. `grants.length === 0` — **必错**：F048 在应用创建时给 owner 投一条 **protected** 授权（`app_runtime/domain/services/f048_app_permission.py:168-186 authorize_created`，`mode="CUSTOM", protected=True`），所以刚上线的应用 grants **恰好有一条**，A 的提示条永远不出现——AC-12 的"首发必经提醒"直接失效，且**没有任何报错**
  - B. **`data.filter(a => !a.protected).length === 0`**（选定）
  - C. 后端加一个 `visibility_summary` 端点专门回答这个问题 — 优点：前端最省事；缺点：为一句提示新开端点，而 grants 端点本来就要拉（要渲染摘要）
- **⚠️ 提示条还有一半前置：`app_state === 'online'`**（AC-12 原文是「WHILE 应用**已上线**且可见范围仍为『仅 owner 可见』」）。只用 `非 protected 行数 === 0` 判定，草稿 / 待上线态的详情页也会常驻「同事无法在广场看到」——那句话在未上线时**本来就成立且无从解决**，是纯噪音。故完整判据 = `app_state === 'online' && grants.filter(a => !a.protected).length === 0`；未上线时**区块照常渲染**（AC-12 要求可见范围区常驻）、只是不出提示条。
- **选定**：**B**。`PermissionGrantAssignee`（`platform/controllers/API/permission.ts:152-163`）带 `protected: boolean` / `editable: boolean` / `scope: "LOCAL"|"INHERITED"`；grants 是游标分页（`page_size` 默认 50、`has_more`），但**只需判首页**——首页 50 条里若一条非 protected 都没有，后面更不会有（protected 行数是个位数）。摘要文案同样从首页取（"已授予 N 个主体"取 `has_more ? 'N+' : N`）。
- **原因**：这是一条**只能靠读代码才知道**的判据（坑 13）。选 B 还有一个副作用红利：`protected` 行在 UI 上本来就 `editable: false`，摘要里把它渲染成 "owner（默认）" 与提示条逻辑天然一致。
- **何时该重新考虑**：F048 改变 owner 授权的投影方式（不再用 protected 行，而是隐式 owner 关系）——那时判据要跟着改，且**没有编译期报错会提醒你**，所以本条必须留在 design 里。

### D6：可见范围变更审计 = 在 F048 通用 `mutate_grants` 上挂**按资源类型注册的回调**，由 `app_runtime` 侧写 `app.visibility_change`

- **备选**：
  - A. **为托管应用另开一个专用授权端点**，在里面写审计 — **违反 AC-11**：弹窗是共用的，专用端点等于第二套授权界面（弹窗内部要按 resourceType 走不同 URL，`PermissionDialog` 就有了 per-type 分支）
  - B. **在 `permission` 的 application 层直接按 `resource_type == "app"` 白名单写 `app.visibility_change`** — 优点：一处改完；缺点：**权限模块从此知道应用工场的命名空间**，将来知识库 / 工作流也要审计授权时这里会变成一串 if/elif；依赖方向也别扭（`permission` 是被所有业务模块依赖的下游）
  - C. **回调注册表**（选定）：`permission/application/resource_api.py` 里加一个模块级注册表 `{resource_type: async callback}`，`ResourcePermissionApi.mutate_grants` 在成功返回前按 `resource_type` 查表并调用（有则调、无则跳过）；`app_runtime` 侧提供写入器，**在组合根显式注册**（形态同 F054 的 `lifecycle_hooks` 钩子注册表，注册动作放组合根而非模块 import 副作用，见下）
- **选定**：**C**。写入形状（对齐 AC-22 / 决议-7）：
  `action='app.visibility_change'`、`target_type='app'`、`target_id=app.id`、`object_name=app.name`、`metadata={'app_slug':…, 'added':[{type,id}], 'removed':[{type,id}], 'model_keys':[…]}`、`operator_*` = **变更人本人**（租户管理员 / 超管代行也记本人，AC-14）。**落地增补（2026-08-18）**：另有 `moved:[{type,id,model_key}]`（仅在本次含 MOVE 时出现）——MOVE 的主体身份与 REMOVE 一样事后不可还原，只记 added/removed 会让「某人从 viewer 升到 editor」在审计里彻底消失。
- **⚠️ `removed` 的数据来源：必须在 mutate 之前读一次名册快照（审查发现，原方案已证伪）**
  - 原写法"从 `result.grants` 反解被移除的行"**行不通**：`GrantSourceService.remove_source` 算出 `remaining = tuple(row for row in grant.sources if row.active and row.source_id != source_id)` 后 `replace(grant, active=bool(remaining), sources=remaining)`（`grant_source_service.py:279` / `:305-311`）——被移除的 source 是**整行丢弃**，不是标 `active=False` 留下；`GrantService.mutate` 的 `final_grants`（`grant_service.py:232`）由这些 grant 组成，所以 `result.grants` 里**根本不存在被撤销的主体**。`resource_api.py:344-372` 渲染时那句 `if source.active` 只是防御，不证明存在 inactive 行。
  - 而请求体侧：`ADD` 带 `subject`（`type`/`id`），**`REMOVE` / `MOVE` 只有 `assignee_id` + 版本**（`domain/schemas/f048.py:242-262 validate_operation_shape`：「REMOVE only accepts the assignee identity and version」）。两头都拿不到 → 按原方案实现只能写出 `removed:[{assignee_id: 123}]`，正是坑 11 要避免的无取证价值记录。
  - **唯一可行解 = mutate 之前多读一次名册**：`ResourcePermissionApi.mutate_grants` 里在 `self._runtime.mutate_grants(...)`（`resource_api.py:337`）之前，用**既有读法** `self._runtime.list_permission_sources_page(actor=actor, target=target, after_id=0, limit=…)`（`resource_api.py:190` 就是这么读的）取一页名册，建 `source_id → (subject_type, subject_id)` 索引，供回调反查 `REMOVE`/`MOVE` 的 `assignee_row_id`。
  - **成本认账**（不再假装零成本）：① 多一次 SQL 名册页读；② 该读法内部还会 `_require_manage_permission`（`runtime.py:937`）——即多一次权限判定，虽然 `_target(..., "manage_permission")` 刚判过。**降本三条门槛**：仅当 ① 该 `resource_type` 注册了回调、且 ② 本次 `changes` 里存在 `REMOVE` / `MOVE`、且 ③ 名册在首页放得下（`has_more` 为真时对超出部分的 `removed` 只写 `{assignee_id}` 并在 `metadata` 打 `roster_truncated: true` 标记，**宁可标注不完整也不做多页扫描**）时才读。
  - `added` 不受影响：直接取请求体 `changes` 里 ADD 的 `subject`，零额外读。
- **⚠️ 注册时机与执行进程（必须写死，否则失败模式是"静默不写审计、无任何报错"，与 K3 同级）**
  - **注册落点 = 组合根显式注册**。**落地形态（2026-08-18）**：落在 `api/services/f048_permission_runtime.py` 的 `initialize_f048_api_runtime`，与 `F048ResourcePermissionApi(...)` 的构造处同一行上下文——那里正是本 API 进程唯一装配 `mutate_grants` 的地方，二者同生共死（没有 API runtime 就没有可观测的变更），比挂 `main.py` 的 `lifespan` 少一处可脱节的接线，也避开并发编辑 `main.py`。**不得依赖"模块被 import 时的副作用"**——`app_runtime` 的写入器模块若只被 endpoints/services 间接 import，注册与否就取决于 router 加载顺序，一次 import 图重排就静默失效。
  - **进程边界**：`mutate_grants` 的唯一触发源是 `permission/api/endpoints/grant.py:113`，只跑在 **API 进程**，所以注册挂 API 的 `lifespan` 是充分的；celery / linsight worker 进程内不注册**不是缺陷**（那里没有触发源）。若将来有内部调用方在 worker 里改授权，注册必须跟着搬——本条即是那时的提醒。
  - **可观测**：回调未注册时 `mutate_grants` 走"无则跳过"分支，**没有任何日志**。故实现时在注册函数里打一条 info（`registered visibility-change audit hook for resource_type=app`），114 验收查不到事件时**先 grep 这条启动日志**，再怀疑写入逻辑。
- **原因**：① C 让权限模块只知道"有人订阅了资源类型 X 的授权变更"，不知道 `app.*` 是什么，依赖方向仍是 `app_runtime → permission`（C1）；② 本期只注册 `app` 一个类型，**其余资源类型行为逐字节不变**（知识库 / 工作流的授权今天完全不写审计，不能顺手给它们加——那是范围外的行为变更）；③ 落点选 application 层而非端点层，是因为同一个 `api.mutate_grants` 被端点与将来可能的内部调用共用，端点层挂钩会漏。
- **本 Feature 只写这一类事件**：其余 `app.*` 九条（`app.publish` / `publish_pending` / `manual_publish` / `stop` / `resume` / `delete` / `delete_hook_failed` / `meta_update` / `data_row_edit`）**F054 T007 已登记并由 F054 写入**；`app.release.*` 归 F055 自行登记（F055 design §4.2 ⑥）。F056 的 lockstep 义务只有**一条 action 的四处**（K3），其中 `AppAuditAction` 枚举文件正被并发编辑，**改前须协调**（坑 19）。
- **模式切换（`mode-drafts` / `apply`，`grant.py:136-176`）算不算「可见范围变更」**：算——INHERIT↔CUSTOM 切换会整体改变谁可见。但**本期不接线**（MVP-核心只要求"变更即时生效 + 计审计"的主路径），且托管应用今天恒为 `CUSTOM` 模式（`f048_app_permission.py:168-186` 创建即 CUSTOM），模式切换在托管应用上没有触发源。登记为 §8 后续。
- **何时该重新考虑**：第二种资源类型也要审计授权变更时（那时注册表证明了自己）；或审计要求记录**变更前后的完整主体快照**而非增删差异——那时"mutate 前读一页"要升级成"读全量名册"（多页扫描 + `roster_truncated` 兜底作废），成本随主体数线性上涨，需产品确认。

### D7：访问记录（谁在用）本期只保证"可查"，写入归 F054；MVP-核心期两侧都顺延

- **备选**：
  - A. F056 在广场跳转时前端埋点上报 — **错在语义**：广场点击 ≠ 成功进入（可能被四类兜底页拦下），AC-24 明确"被兜底页拦下的访问不计入"；且前端埋点可被绕过
  - B. **写入归 F054 的内部授权端点**（判定通过时顺带，F054 design D14 已选 `llm_call_log` 式独立业务日志表 + fire-and-forget + Redis `SETNX app_access:{app_id}:{user_id}` 去重），F056 只保证查询面可查（选定）
- **选定**：**B**。合并窗口取部署配置项、**默认 30 分钟 = 1800 秒**（spec 决议-2）。
- **⚠️ 必须回写上游，否则这条定义传不到实现者手里**：F054 design `:339` 原文是「Redis `SETNX app_access:{app_id}:{user_id}` TTL = 合并窗口（**默认 300s**，窗口值由 F056 定）」——F054 的实现者读自己的 design 会照 300 落地，本文写在这里他不会看到。故本条**同时是一个待办**：F056 design 定稿后，向 F054 提交勘误，把 F054 design `:339` 与对应 tasks 的 TTL 默认值改为 **1800s** 并注明"值由 F056 D7 定义"。已登记为 §6.1 的一条 Outgoing 契约（合并窗口 = 1800s）。
- **原因**：留痕点在统一入口（F054 的组件里），写入归动作 owner 是本版全局的归属规则；30 分钟对齐常见会话粒度，避免用户刷新一次就多一条。
- **何时该重新考虑**：安全侧要求拒绝类访问也留痕（那是另一个事件类型，写入仍归 F054）；或访问量级让审计页低频查询变慢（那时访问记录进独立表 / 分区，查询面按事件类型路由到不同存储——AC-34 承诺的是"同一查询面可达"，不是"同一张表"）。

### D8：未部署工场运行时层时的隐藏方式 = 消费 F054 的 `/api/v1/env.app_runtime_enabled`，前端隐藏 + 后端天然为空的双保险

- **备选**：
  - A. **只靠后端**：开关关时后端不返回托管应用（列表天然为空）— 优点：零前端改动；缺点：AC-10 还要求"与之相关的**文案 / 筛选项**也不出现"，纯后端做不到
  - B. **只靠前端**：读开关后过滤掉 `flow_type===35` 的卡片 — 缺点：数据已经过网了，等于把"未部署"当成 UI 隐藏；且开关是部署级真相，前端过滤是最弱的一道
  - C. **双保险**（选定）：后端在 `SUPPORTED_APP_TYPES` 之外**不额外加闸**（开关关 = 根本没有 `app` 行，列表天然为空，A 的效果自动成立），前端读开关只用来隐藏"与托管应用相关的文案 / 空态提示 / 未来的类型筛选项"
- **选定**：**C**。client 侧读取件由 **F054 T071 交付**（`client/src/hooks/useAppRuntimeEnabled.ts` + `@types/chat.ts:102` 的 `BishengConfig.app_runtime_enabled`，覆盖 **AC-62**「开关取值可被两个前端读取」，依赖 F054 T005）——**不是 T090**（那是审批期临时预览入口 `/apps/preview/{session}`，与开关无关）。既有的 `/api/v1/env` 全量落进 `bishengConfState` 在 `client/src/layouts/MainLayout.tsx:388-394`（**目录是复数 `layouts/`**），但 **client 的 recoil 已被 lint 冻结**（`client/eslint.config.mjs:47`）→ 新读取必须走 T071 那个 **react-query v4 hook**，不得 `useRecoilValue`（K4）。
- **原因**：把"有没有这类应用"交给数据、把"有没有这类文案"交给开关，是唯一不制造第二处真相的分法。给后端再加一道 `if not enabled: exclude 35` 的闸看似更保险，实际是同一事实的第二处判断——开关与数据一旦不一致（比如关开关但库里有历史应用），两处会给出不同答案，而**正确答案应该是"数据说了算"**（历史应用的卡片消失比它带着一个点不开的入口更糟？不——F054 的 `/apps/{slug}` 在未部署时会渲染引导页，卡片留着反而能解释"这台机器没装"）。
- **何时该重新考虑**：产品要求"关开关即对用户完全隐身（含历史应用）"——那时后端加闸，且要同步 F054 的入口页行为，两处一起改。

### D9：已下线应用进广场 = 广场请求对第三类型**豁免 `status` 条件**并按应用态收窄（服务端写死 `{online, stopped}`），不改 F054 的 status 投影

- **背景（K8）**：`api/v1/chat.py:63` 硬传 `FlowStatus.ONLINE.value`（2），F054 第三支把「已上线」投 2、其余四态投 1 → **已下线托管应用不会出现在广场**，与 AC-03 / 决议-5 冲突（决议-5 要求"保留卡片 + 标『已下线』"，因为隐藏会让用户误判为被移出可见范围）。
- **备选**：
  - A. **改 F054 第三支投影**：「已上线 ∪ 已下线」都投 2 — 优点：广场一行不改；缺点：**打坏构建页**——构建页按 `status ∈ {1,2}` 筛"已上线 / 已下线"（`platform/controllers/API/flow.ts:204`），已下线投 2 后就再也筛不出来了；而且这是修改 F054 已定稿的契约
  - B. **广场按类型分支状态条件**（外层 SQL 写成 `(flow_type = 35) OR (status = :status)` 之类）（选定）
  - C. **两条查询分别取再合并** — 同 D1-A 的分页撕裂问题
  - D. 广场对托管应用干脆不过滤状态，让草稿 / 待上线也进来再由前端滤 — **违反 AC-03**，且草稿进广场是产品明令禁区
- **选定**：**B**。具体形状 = **两个参数、都是内部参数，广场不向前端开放任何新 query 参数**：
  - `FlowDao.aget_all_apps` 增 `status_exempt_flow_types: set[int] | None`，外层 status 条件抽成 `FlowDao._build_status_clause`（「`status == :status` **或** `flow_type ∈ 豁免集合`」，缺省仍是纯等值，可单测拼串）；
  - `FlowDao.aget_all_apps` 增 `app_state_in: set[str] | None`，**下推给 `_build_apps_subquery(app_state_in=…)` 加到第三支的 `App.state IN (...)`**（不是外层过滤——外层要额外容忍另两支投的 typed NULL，下推还让草稿在行集层就不存在），广场路径**恒传** `{online, stopped}` —— 草稿 / 待上线 / 已删除被挡在 SQL 层，这正是 AC-03「不因用户是 owner 或管理员而例外」的实现依托，**不必额外写权限收窄**。
  - 构建页与另两个调用方两个参数都不传 → 行为逐字节不变。
- **⚠️ 参数串联的落点归属（审查发现，必须写死）**：广场链路上 `app_state` **没有现成的落点**——`api/v1/chat.py:17-57`（无该 Query）→ `get_online_flows_page:544`（签名无该参数）→ `_scan_visible_apps_page:401`（签名无该参数）→ `aget_all_apps:508`；未分类链路 `workstation/api/endpoints/apps.py:86` → `get_uncategorized_flows:977` 同理。而 F054 T060 交付的 `app_state` 是**构建页的用户可传查询参数**（`api/services/workflow.py` 的构建页函数 + platform `controllers/API/flow.ts:177 getAppsApi`），与广场不是同一条链。结论：
  - **广场侧的串联归 F056**：`_scan_visible_apps_page` 增内部参数（默认 `None` = 既有行为）并透传到 `aget_all_apps`；两个入口函数（`get_online_flows_page` / `get_uncategorized_flows`）在调用处**写死** `status_exempt_flow_types={35}` + `app_state_in={"online","stopped"}`，**不从 HTTP 层接收**（广场没有让用户筛应用态的产品需求，开成 query 参数等于把 AC-03 的 SQL 闸交给调用方）。
  - **DAO 两个参数归谁写**：`flow.py` 的 `aget_all_apps` / `_build_apps_subquery` 正被 F054 T059 并发编辑。**F056 落地前先与 F054 owner 对一次**：若 T059/T060 已顺手加了等价参数则复用其命名、本文同步改；否则由 F056 加（只增可选参数、缺省不改行为），并在 tasks 里标注"同文件并发，最后合并者负责 rebase 而非覆盖"。
- **原因**：B 是唯一"单条 SQL、单套分页、既有语义零改"的解；A 打坏上游、C 撕裂分页、D 违反 AC。把状态收窄写死在服务端而不是接成 HTTP 参数，是因为 AC-03 的两个方向（已下线必须出现、草稿必须不出现）都是**产品硬规则**，不是用户可选项。
- **何时该重新考虑**：产品要在广场提供"按应用态筛选"的控件（那时 `app_state_in` 才升级为 HTTP query 参数，且要同步想清楚它与 `status` 两值的叠加语义）；或 F054 把 `App.state` 的取值集合改了（`{online, stopped}` 这个白名单要跟着改，且**没有编译期报错会提醒你**）。

### D10：广场搜索按名称，不为托管应用单独打开 `search_description`

- **备选**：
  - A. 广场请求补传 `search_description=true` — 优点：直接满足 AC-08 字面（"可按名称 / 描述被搜索到"）；缺点：该参数在后端是**全类型生效**的（`api/v1/chat.py:24` 默认 `False`，一路透到 DAO），打开就同时改变了工作流 / 助手的既有搜索结果集——广场搜索行为的变更对全体用户可见，属高回归面改动
  - B. **保持既有行为（只按名称搜），把 AC-08 的"描述"部分记为已知偏差**（选定）
  - C. 后端把 `search_description` 做成"只对 `flow_type=35` 生效" — 缺点：同一个搜索框对不同类型用不同匹配规则，用户搜不到时无法解释；且这是为一个 AC 字面量在 SQL 里造特例
- **选定**：**B**。托管应用在广场**可按名称搜索**（与工作流 / 助手完全一致），描述搜索留待产品统一决定是否为全类型打开。
- **原因**：AC-08 的实质诉求是"未设标签的应用不会因为没标签而找不到"（这条 B 完全满足：未分类 tab + 名称搜索），"按描述搜"是搭车条款；为它改变全平台搜索语义不划算。**本条需要 spec 侧确认口径**——若产品坚持描述搜索，正确做法是 A（全类型打开）并把它当作一次独立的广场行为变更来回归，而不是 C。
- **何时该重新考虑**：产品决定为全部类型打开描述搜索（那时是一次广场级变更，与本 Feature 无关）。

### D11：MVP-核心边界 = 只做"看得到 + 管得住 + 查得到"，查询面与触达整体顺延

- **备选**：
  - A. 按 spec 45 条 AC 全做 — 预算不允许（`mvp-114-path.md` §6 用户定调）
  - B. **只做 `mvp-114-path.md` §6 F056 行的三项**（广场接入 / 两入口授权 + 「仅 owner 可见」提示 / 三类审计事件可查）（选定）
  - C. 折中：把「对象应用」筛选也做进来（不做导出与租户筛选）— 缺点：「对象应用」筛选是**后端查询参数 + DAO 过滤 + 前端筛选控件 + 应用检索选择器**四件套从零新增（`api/v1/audit.py:13-27` 今天连 `target_type` 参数都没有），不是半天的活；且没有它，`app.*` 事件仍可按"事件类型 = 可见范围变更"筛出（AC-22 的验收路径成立）
- **选定**：**B**。本轮交付边界（对应 AC）：AC-01–AC-07 / **AC-09** / AC-10（广场）、AC-11–AC-15（授权交互，AC-16 回归验证顺延）、AC-22 + AC-27 的**三类事件**（发布 / 上线由 F054 F055 写、可见范围变更由本 Feature 写，三者在审计页事件类型下拉可选且可查）。其余顺延，落点方向见 §1 非目标。
  - **AC-09（元信息更新后广场卡片自下一次加载呈现新值）= 零代码**，但**必须显式认领**（此前两个清单都没有它，属落点空白）：广场列表直读 `app.name` / `description` / `logo`（UNION 第三支的投影列，无缓存层），元信息由 F054 `AppMetaService` / F055 deploy 就地更新表行 → 下一次拉列表即新值。本 Feature 的义务是**验收**（§7 步 3 的补充断言），不产出代码；其审计事件由 F054 AC-06 / F055 AC-05 写入，本 Feature 只保证可查（AC-23，属顺延的查询面）。
- **原因**：这三项构成 114 演示剧本步 5–6 的全部（管理员授权 → 非管理员从广场打开），是纵切闭环的最后一段；审计查询面的增强对"闭环能不能跑通"零贡献。
- **何时该重新考虑**：预算恢复，或客户在 POC 中明确要求审计导出（那时按 §8 的顺序做，第一件是「对象应用」筛选，因为没有它"按应用追溯"这句话不成立）。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**① 广场列表（有标签 tab）**

```
client 广场页 pages/apps/explore.tsx:60-62
  → getChatOnlineApi(page, keyword, tagId, 20)        client/src/api/apps.ts:429   ← 第 5 参 action 未传，落默认 'visible'（D3 要改）
  → GET /api/v1/chat/online                          api/v1/chat.py:17-57         ← status 硬传 FlowStatus.ONLINE(2)（D9 要改）
  → WorkFlowService.get_online_flows_page             api/services/workflow.py:500
       ├ tag 预过滤 :517-528                          ← 只列 WORK_FLOW / ASSISTANT 两类，F054 T060 未覆盖此处（§4.3）
       └ _scan_visible_apps_page :401
            ├ FlowDao.aget_all_apps :508  → _build_apps_subquery（flow.py:660-702，UNION 二支 → 三支由 F054 T059 落）
            ├ filter_supported_apps :83   ← SUPPORTED_APP_TYPES:76 唯一硬闸（F054 T060 加 35）
            ├ _application_action_map :146 → 按资源类型分桶 → batch_check_business_actions
            │      requested_actions :425  ← 今天恒为 (action,'edit','share')，D3 改为按桶取值
            └ 按命中筛 kept :450-455
  → add_extra_field :87-127（user_name / version_list / tags）  ← **未分类 tab 不走这里**；slug / app_state 在上一步的 _scan_visible_apps_page 出口补
  → _apply_page_can_share :485（app 恒 false → 卡片分享按钮消失）
  → client 归一化 explore.tsx:66-71（flow_type ?? type）→ AgentCard 渲染
```

**② 广场列表（未分类 tab）**：`getUncategorized`（`client/src/api/apps.ts:403`）→ `GET /api/v1/workstation/app/uncategorized`（`workstation/api/endpoints/apps.py:86-93`）→ `WorkFlowService.get_uncategorized_flows`（`workflow.py:977-1016`，**`action="visible"` 硬编码于 `:1010`**）→ 汇入同一条 `_scan_visible_apps_page`（`:1003`）。**两个入口都要改，漏一个就是"标签 tab 里能看到、未分类里看不到"**。
  **两条链的关键不对称**：`get_online_flows_page` 末尾调 `add_extra_field`（`:548`）+ `_apply_page_can_share`；`get_uncategorized_flows` **只做 `one["logo"] = get_logo_share_link(...)` 后直接 `_apply_page_can_share` 返回（`:1012-1016`），从不调 `add_extra_field`**。所以任何"给列表补字段"的改动（`slug` / `app_state`）**必须落在两条链的共同下游 `_scan_visible_apps_page` 里**，落在 `add_extra_field` 就只对标签 tab 生效——而 §7 指定的验收面恰恰是未分类 tab（坑 8），现象是"点击落 `/apps/undefined`、没有已下线角标"且不报错。

**③ 卡片点击**：`AgentCard onClick`（`:76`）→ `explore.tsx handleCardClick:132-146` → **托管应用分支**：`window.location.assign('/apps/' + agent.slug)`（D2）→ 离开 SPA → nginx `location /apps/` → app-proxy（F054）。其余类型走原有 `navigate('/app/...')` 不变。

**④ 授权变更 → 生效**

```
入口 A：platform 构建页卡片 ⚙️「管理权限」  BuildPage/apps.tsx:215-218 / :415-423   （F054 T063 接线）
入口 B：应用详情页 · 发布 tab「可见范围区」 hostedApp/publish/VisibilityScopeSection.tsx（F056 新建，填 F054 slot）
  两者拉起同一个 PermissionDialog（resourceType="app"）
  → POST /api/v1/permissions/resources/app/{id}/grants:mutate   permission/api/endpoints/grant.py:113-131
  → ResourcePermissionApi.mutate_grants                          permission/application/resource_api.py:290
       ├ _target(..., "manage_permission")  ← 非 owner 非管理员在此 403（AC-15 的后端闸）
       ├ **F056 新增（前置）**：有回调 且 changes 含 REMOVE/MOVE → list_permission_sources_page 读一页名册
       │                        建 source_id → (subject_type, subject_id) 索引（坑 11：事后反解不到）
       ├ runtime.mutate_grants → GrantService.mutate（projection prepare/execute/finalize）
       └ **F056 新增（后置）**：按 resource_type 查回调注册表（注册在 main.py lifespan 的组合根，D6）
                              → app_runtime 写入器 → AuditLogDao.ainsert_v2('app.visibility_change')
                              （outcome.idempotent 直接 return，坑 12；写失败只 warning，坑 14）
  → 授权即时生效：被授权用户**下一次请求**的 batch_check 就命中（无缓存到期依赖）→ 广场出现 / 消失（AC-05）
```

**⑤ 审计可查**：`AuditLogDao.ainsert_v2` 写行 → `_ui_visible_predicate`（`:272-282`）判 `action ∈ _UI_VISIBLE_V2_ACTIONS` → `GET /api/v1/audit` → platform 系统操作日志页（`platform/src/pages/LogPage/systemLog/index.tsx`）按 `模块=应用工场` / `事件类型=可见范围变更` 筛出。

### 4.2 对外契约与字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 广场列表项 `flow_type` | `number`，托管应用 = **35** | F054 `FlowType.HOSTED_APP`；client `@types/app.ts:2-15` 注释与 `components/Avator/index.tsx:30-43` 图标 map 需同步加第三支（**client 侧，与 F054 改的 platform `avatar.tsx` 不是同一文件**） | client 广场卡片 / 图标 |
| 广场列表项 `slug` | `string`，仅 `flow_type=35` 非空 | **F056 新增**，在 `_scan_visible_apps_page` 出口批量回查 `app.slug` 补入（D2；**不能放 `add_extra_field`——未分类 tab 不经过它**）；跳转地址 = `/apps/{slug}`（**不带 `/workspace`**） | client 广场卡片点击 |
| 广场列表项 `app_state` | `string`，取值 `online` / `stopped`（本期广场只可能出现这两值） | **F054 交付**（UNION 第三支第 10 列 → `_app_row_to_dict` 只对托管行落键）；F056 只在缺失时兜底。卡片据此渲染「已下线」角标（AC-03 / 决议-5） | client 广场卡片 |
| 广场列表项 `can_share` | `boolean`，托管应用**恒 `false`** | 由 `_apply_page_can_share`（`workflow.py:485`）产出；`AgentCard.tsx:44-55/127-136` 的分享按钮闸门，置 false 即零改组件隐藏（AC-07） | client 广场卡片 |
| 广场列表项 `user_name` | `string` | owner 显示名，与工作流 / 助手同取值（`add_extra_field:103 UserDao.get_user_by_ids`）；第三支把 `owner_user_id` 投成 `user_id` 后天然可用（决议-3） | client 广场卡片 |
| `GET /api/v1/chat/online` 查询参数 | 既有 `page/keyword/tag_id/flow_type/limit/sort_by/search_description/action`，**F056 不新增任何 query 参数** | `action` 参数保留（另两类仍用），托管应用桶在服务端强制走 `use`（D3）；`status` 对 `flow_type=35` 豁免、应用态收窄为 `{online,stopped}` 均在服务端写死（D9） | client 广场 |
| 授权弹窗入参 | `{open, onOpenChange, resourceType: "app", resourceId: app.id, resourceName: app.name}` | `PermissionDialog.tsx:26-32`，**组件零改动**；`resourceType` union 三处已含 `app` | platform 卡片 ⚙️ / 可见范围区 |
| 「仅 owner 可见」**提示条**判据 | `app_state === 'online' && grants.filter(a => !a.protected).length === 0`（状态前置来自 AC-12「WHILE 应用已上线」；未上线只是不出提示条，区块照常渲染） | `PermissionGrantAssignee.protected`（`platform/controllers/API/permission.ts:152-163`）；owner 的 protected 行由 `f048_app_permission.py:168-186` 创建时投下（D5） | 可见范围区提示条 |
| 审计 action（**本 Feature 唯一自写**） | `app.visibility_change` | `target_type='app'` / `target_id=app.id` / `object_name=app.name` / `metadata={app_slug, added[], removed[], model_keys[]}` / `operator_*` = 变更人本人 | 系统操作日志页 |
| 审计 i18n key 推导规则 | `action.split(/[._]/)` → 首段小写 + 其余首字母大写 | `platform/src/pages/LogPage/systemLog/index.tsx:43-47 actionToI18nKey` → `app.visibility_change` ⇒ **`appVisibilityChange`**（三语 `bs.json` 的 `log.eventTypeEnum` 各加一条） | 审计页事件类型列 |
| 审计对象类型文案 | `log.objectTypeEnum.app` | `systemLog/index.tsx:68-72 renderObjectType` 取 `log.object_type \|\| log.target_type` 并回落 `log.objectTypeEnum.<target_type>`；不补则对象列显示原始串 `app`（有 defaultValue 兜底，不炸但难看） | 审计页对象列 |
| **事件类型登记契约**（对 F054 / F055 / F049 / F051 的要求） | 新增任一 `app.*` / `app.release.*` 事件时，**同一 PR 内**改四处：`_UI_VISIBLE_V2_ACTIONS` + 自己的 action 枚举 + `log.ts` actions 数组 + 三语 `bs.json` | K3；漏任一处 = 写入成功但审计页查不到（AC-27 判定为本 Feature 缺陷，故本 Feature 把契约写在此处并在 §7 加断言测试） | 全部写入方 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `client/src/pages/apps/explore.tsx`（281 行，`ExplorePlaza`） | 广场页：tab 分流两个列表接口、无限滚动、卡片点击分流（托管应用整页跳） | **不是**「应用中心」（那是同目录 `index.tsx` 的 `AppCenter`，走 `getFrequently`，点击进对话页——坑 10）；不做权限判断（后端已过滤） |
| `client/src/pages/apps/components/AgentCard.tsx`（244 行） | 卡片渲染：图标 / 名称 / 描述 3 行定高 / 标签行 / 分享按钮 / 置顶 | **广场与应用中心共用**——改它要同时想两个页面；分享按钮不加类型判断（靠 `can_share` 数据闸） |
| `client/src/components/Avator/index.tsx` | client 侧应用图标 map（`flowConfig` `:30-43`，今天只有 1/5/10，`:45` 回落助手图标） | 与 platform 的 `bs-comp/cardComponent/avatar.tsx`**不是同一文件**，F054 改的是后者 |
| `api/services/workflow.py`（`WorkFlowService`） | 广场与构建页共用的列表编排：类型闸、批量鉴权分桶、扫描分页、载荷加工 | 不直接判权（交 `business_authorization`）；不认识 UI |
| `permission/application/resource_api.py`（`ResourcePermissionApi`） | 资源侧授权读写的 application 门面；**F056 在此挂审计回调注册表** | 不认识 `app.*` 命名空间（回调由 `app_runtime` 注册，D6）；不改任何既有资源类型的行为 |
| `platform/src/pages/BuildPage/hostedApp/publish/VisibilityScopeSection.tsx`（**F056 新建**） | 可见范围区：状态摘要 / 「仅 owner 可见」常驻提示条 / 设置按钮 / 拉起 `PermissionDialog` / 关闭后刷新 | 不碰 `PublishTab.tsx` 本体（填 slot，D4）；不自建授权 UI；不做 react-query（platform v3 已冻结，用 `useState + useEffect` 或 `useTable`） |
| `platform/src/components/bs-comp/permission/PermissionDialog.tsx` | 通用授权弹窗（用户 / 部门 / 用户组三 tab） | **本 Feature 零改动**；无 per-type 分支 |
| `platform/src/controllers/API/log.ts` + `bs.json` 三语 | 审计页的模块下拉 / 事件类型清单 / i18n 文案 | 模块下拉与 `case 'app'` **F054 已落**，F056 只加一条 action |

**tag 预过滤第 4 处：归属是 F054，不是 F056（审查订正）**。tag 预过滤共 4 处（`workflow.py:203` / `:598` / `:998-999` / **`:517-528`**），其中 `:517-528` 正是广场标签 tab 那一处。**F054 tasks 的批次边界注（`tasks.md:47`）已明写 T059/T060 的范围含「标签 4 处」——F054 自己认账 4 处，只是 T060 的文件清单行（`tasks.md:461`）漏写了这一处**；而它改的正是 T059/T060 同批在改的同一个函数（`get_online_flows_page`），F056 自行接管 = 并发期同文件撞车。故本 Feature 的动作是：**向 F054 提一条勘误（把 `:517-528` 补进 T060 的文件清单），由 T060 落实现**，F056 只承担**验收**（§7 步 3 的有标签 tab 用例）。若 F054 在 F056 开工时仍未补，才走书面交接（F056 tasks 单列一条并注明「代 F054 T060 补，合并时以 F054 分支为准 rebase」），**不得默默改掉**。不补的现象是：有标签 tab 下托管应用**整类消失**，且**没有任何报错**（`tagged_ids` 为空即 `return []`）——极易被误判为"权限没配好"。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **`share` 动作对 `app` 类型不存在，而请求它的地方有 5 处**（`catalog_policy.py:71` 的 `share` 范围集不含 `app`）：`_scan_visible_apps_page:425` 的 `requested_actions`（广场两入口），外加 `aenrich_apps_can_share:133` 无条件请求的 `("share",)`——后者有 4 个调用方：`workstation/api/endpoints/apps.py:53`（工作台推荐应用）、`:150`（常用 / 最近使用）、`api/v1/chat.py:83`（`sort_by=update_time` 分支）、`workflow.py:962`（应用中心）。链路：`business_authorization.py:113-127` → `runtime.batch_check_actions` → `permission_action_service.py:244 _prepare_action_target` → `is_action_effective("app","share")` = False → 抛 `InvalidCatalogActionError`；`business_authorization.py:97-112` 的 `except` **只捕 resolve 阶段**，batch 阶段不捕 → 冒泡 | **不是 500，是 HTTP 200 + 业务码 25001**：`InvalidCatalogActionError` 继承 `BaseErrorCode`（`common/errcode/permission.py:52`），`_EXCEPTION_HANDLERS`（`main.py:46-51`）把它交给 `handle_http_exception`，该分支返回 `200 + {status_code: 25001, ...}`（只有非 `BaseErrorCode` 才落 500，`main.py:25-38`）。现象 = 前端 request 封装 reject → 列表 catch 后置空 → **"广场空白 / 打不开"，而后端日志里没有任何 5xx**（按"查 500"排查会一无所获，只能 `grep 25001`）。且超管（`business_authorization.py:78-83` 整批短路）与租户管理员（`_identity_shortcut` 在 `_prepare_action_target` **之前**）**都不触发** → 自测全绿、上线即炸 | D3 **第一层**：合法性过滤下沉到 `_application_action_map`，一次覆盖全部 5 个请求点（只裁广场那一处**解不掉**另 4 条）；`can_share` 随之恒 false，`_apply_page_can_share` 零改 |
| 2 | **广场默认走 `visible`、入口走 `use`**（`client/src/api/apps.ts:429` 默认值 + `workflow.py:1010` 硬编码 vs F054 design `:239`）；二者在 FGA 里是两条不同关系 | 造出 AC-06 明令禁止的稳态：**广场看得见、点进去无权限**（自定义权限模型下"授了 editor 没授 use"即复现）；反向也可能"入口能进但广场不见" | D3：`app` 桶换 `use`，另两类保持 `visible` |
| 3 | **`navigate()` 会自动加 client 的 basename `/workspace`**；且 `appUtils.ts:67-71 getAppShareUrl` 这个"现成范例"恰恰是**反例**（它主动拼 `__APP_ENV__.BASE_URL`） | 卡片点击落 `/workspace/apps/{slug}` → 404；照抄 `getAppShareUrl` 会得到同样结果，且因为"抄的是仓内既有写法"而更难被质疑 | D2：`window.location.assign('/apps/'+slug)`，不拼 base |
| 4 | **UNION 子查询里租户自动过滤失效**，每支必须手工 `build_tenant_filter_clause`（`flow.py:661-671` docstring + `:695` / `:698`），且该子查询有 **4 个调用方** | 第三支漏写租户条款 = 广场、构建页、时间范围查询、商业版增量同步**四条路径一起跨租户泄漏**，而且测试若只用超管跑（超管本就跨租户）永远发现不了 | K1；F054 T059 落实现，F056 跑 `test/workflow/test_flow_dao_tenant_isolation.py` 回归 |
| 5 | **tag 预过滤有 4 处，F054 T060 的文件清单行只列了 3 处**（漏 `workflow.py:517-528` = 广场标签 tab），但 F054 tasks 的批次边界注（`tasks.md:47`）**已认账 4 处**——是清单漏写，不是范围外 | 有标签 tab 下**托管应用整类消失且不报错**（`tagged_ids` 空 → `return []`），排查方向会跑到权限上去；而 F056 若"顺手补"就与 F054 T060 改同一函数撞车 | §4.3：**向 F054 提勘误、由 T060 补**，F056 只验收（无交接才书面代补） |
| 6 | **client 与 platform 的应用图标 map 是两份文件**：F054 T063 改的是 `platform/components/bs-comp/cardComponent/avatar.tsx`，广场用的是 `client/src/components/Avator/index.tsx:30-45`（`flowConfig[flowType] \|\| flowConfig[5]`，**默认回落助手图标**） | 广场里托管应用**显示成助手图标**，没有任何报错，且因为"F054 说图标已经加了"而被判为已完成 | §4.2；F056 改 client 侧那份 |
| 7 | **`AgentCard` 是广场与「应用中心」共用组件**（`explore.tsx:235-241` / `index.tsx:202-211`），且分享按钮的闸门是数据字段 `can_share === true` 而非类型判断 | 想隐藏分享按钮时去改组件 → 连带影响应用中心；实际上后端把 `can_share` 置 false 即**零改组件**达成 | D3 尾段（`_apply_page_can_share`） |
| 8 | **无标签的应用在卡片上会显示硬编码的「精选」标签**（`AgentCard.tsx:198-205` 无标签时回落 `{name:'精选'}`）；而广场默认 tab 是**首个首页标签**、不是「未分类」（`AgentNavigation.tsx:59`） | AC-08 的"默认分类可见"若按"默认 tab 可见"验收会判失败——正确验收面是**「未分类」tab**（这是工作流 / 助手的既有行为，不是缺陷）；卡片上莫名其妙的"精选"也会被当成 bug 上报 | D10 / spec AC-08；验收口径写进 §7 |
| 9 | **广场无限滚动没有 total**：`hasMore = pageData.length >= pageSize`（`explore.tsx:74`），后端按整页长度判断；而权限过滤发生在扫描之后（`_scan_visible_apps_page` 内部有续扫补齐逻辑） | 若在扫描外层再加一层过滤（比如前端按 `app_state` 滤卡片），会出现"返回不足一页 → 前端判定没有更多 → 后面的应用永远刷不出来" | D8：前端**不做数据过滤**，只做文案隐藏；任何过滤必须发生在 `_scan_visible_apps_page` 之内 |
| 10 | **「应用中心 / 最近使用」也走同一道类型闸**（`get_frequently_used_flows`，`workflow.py:924-965`，同样 `filter_supported_apps` + `visible`），而它的点击落 `/app/{chatId}/{id}/{flow_type}` 对话页（`useAppCenter.ts:74`） | 托管应用一旦被记入最近使用，用户点它会进**对话页**（一个不存在的会话语义），表现为白屏或报错——而这条路径不在 F056 的任何 AC 里，没人会去测 | §4.3；F056 在该路径显式排除 35（或让其 `onStartChat` 也分流），tasks 单列一条 |
| 11 | **两头都拿不到"移除了谁"**：① `mutate_grants` 的 REMOVE / MOVE 只带 `assignee_id` + 版本，不带主体身份（`domain/schemas/f048.py:242-262 validate_operation_shape`）；② `GrantMutationResult.grants` 里**也没有**被移除的行——`remove_source` 把它**整行丢弃**（`grant_source_service.py:279` / `:305-311` 的 `remaining` + `replace(...)`），不是标 `active=False` 保留，`final_grants`（`grant_service.py:232`）自然查无此人（`resource_api.py:344-372` 那句 `if source.active` 只是防御） | 想当然"从结果快照反解"会写出 `removed: [{assignee_id: 123}]` 这种对取证毫无用处的记录，**而且测试用例里 ADD 场景全绿**（ADD 带 subject），只有撤销场景才暴露 | D6「`removed` 的数据来源」：**mutate 之前**读一页名册快照（`list_permission_sources_page`，`resource_api.py:190` 既有读法）建 `source_id → subject` 索引；带三条门槛降本 + `roster_truncated` 标记 |
| 12 | **`mutate_grants` 是幂等的**：`ProjectionOutcome.idempotent: bool`（`permission/domain/services/projection_plan.py:58-64`），同一 `idempotency_key` 重放会返回相同结果但**不产生实际变更** | 审计钩子不判这个标志 → 前端重试 / 网络重放各写一条 `app.visibility_change`，审计页出现"同一秒改了三次可见范围"的假记录 | D6：回调内 `if outcome.idempotent: return` |
| 13 | **「仅 owner 可见」不能用"grants 为空"判据**——F048 创建时给 owner 投一条 **protected** 授权（`f048_app_permission.py:168-186`），刚上线的应用 grants **恰好有一条** | AC-12 的首发提示条**永远不出现**，且没有任何报错；owner 于是漏掉"设可见范围"这一步，同事在广场里什么也看不到——正是 PRD 要用这条提示解决的问题 | D5：判据 = 非 protected 行数为 0 |
| 14 | **`AuditLogDao.ainsert_v2` 自带 `bypass_tenant_filter` + 独立 session + commit**（`audit_log.py:494-500`），且写失败会抛 | 在外层事务里调它 → 事务语义错乱；不 try/except 包 → **审计写失败连累授权动作回滚**（授权明明成功了却报错） | D6：照 `approval/domain/services/approval_outbox_service.py:105-121` 的"审计失败不影响主流程"包法 |
| 15 | **`ainsert_v2` 从不填 `group_ids`（NULL）**，而 `api/services/audit_log.py:78-101` 对非 `is_admin()` 且无日志菜单权限的用户会强加 `json_array_contains(group_ids, ...)` 过滤（`audit_log.py:337-342`） | 这类账号**查不到任何 v2 结构化事件**（`app.*` / `open_api.*` 同病）→ 114 验收时会得出"事件根本没写"的错误结论，然后去改一个没坏的写入路径 | K9；§7 明确验收账号；顺延的查询面改造应一并修这条 |
| 16 | **platform 拦截器对 GET 的 403/404 会整页跳 `/403` / `/404`**（`controllers/request.ts:160-166`） | 可见范围区的 grants 读接口若对非 owner 返回 403，用户**被甩出整个详情页**，而不是看到"你没有权限管理"的区块内提示 | D4：读接口用业务码或 `silent: true`；`can_manage_permission`（`GET .../context`）为 false 时**根本不发起 grants 请求** |
| 17 | **两个前端各有一条被 lint 冻结的路**：client 的 recoil（`client/eslint.config.mjs:47`）与 platform 的 react-query v3（`platform/eslint.config.mjs:45,51`） | 照抄同目录既有写法（client 里到处是 recoil、platform 里到处是 useQuery）会**直接被 CI 拦下**，而这两个仓的既有代码全是反例 | K4；client 新读取走 react-query v4，platform 新组件走 `useState + useEffect` / `useTable` |
| 18 | **`add_extra_field` 会给每行拉版本列表**（`workflow.py:107 FlowVersionDao.get_list_by_flow_ids`），而托管应用在 `flow_version` 表里**没有行** | `version_list` 恒空——不是 bug，别去"修"它（托管应用的版本在 `app_version` 表，归 F054 / F055 的详情页版本 tab） | §4.1；F054 design 坑 13 已记 |
| 19 | **`AppAuditAction` 枚举文件（`app_runtime/domain/constants.py:82`）正被另一 agent 并发编辑** | 直接改会撞掉对方的改动，或造出重复成员 | D6：改前协调；若不便共改，F056 可在自己的常量位置定义该 action，但 **`_UI_VISIBLE_V2_ACTIONS` 白名单仍必须加**（否则写了查不到） |
| 20 | **审计事件的 i18n key 由代码推导、不能自己起名**：`actionToI18nKey`（`systemLog/index.tsx:43-47`）按 `split(/[._]/)` + 驼峰化 → `app.visibility_change` 只能是 `appVisibilityChange` | key 起成 `appVisibility` 或 `app_visibility_change` → 审计页事件类型列显示英文原串（有 defaultValue 兜底不炸），三语文件里那三条永远用不上 | §4.2 契约表 |
| 21 | **广场两个入口的后处理不对称**：`get_online_flows_page` 调 `add_extra_field`（`workflow.py:548`），**`get_uncategorized_flows` 不调**（`:1012-1016` 只补 `logo` 就返回） | 把 `slug` / `app_state` 补在 `add_extra_field` 里 → 未分类 tab 的托管应用**点击落 `/apps/undefined`、没有「已下线」角标**，且不报错；而未分类 tab 正是 §7 指定的验收面（坑 8），两个坑叠加会让人以为是 F054 的 slug 没生成 | D2 / §4.1 ②：补字段落在两条链的共同下游 `_scan_visible_apps_page`；§7 对两个入口各断言一次 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 广场列表载荷新增 `slug` / `app_state`（仅 `flow_type=35` 非空），`can_share` 对 app 恒 false | HTTP 响应字段（`GET /api/v1/chat/online`、`GET /api/v1/workstation/app/uncategorized`） | client 广场卡片；**另两类的载荷形状不变**（新字段对它们为 null / 既有值） |
| `_application_action_map` 的**按资源类型请求不同动作**的能力 | 内部 Python 行为（`api/services/workflow.py:146`） | 将来的第四种应用类型（若其动作集与前三类不同，直接加桶即可） |
| `FlowDao.aget_all_apps` 的 `status` **类型豁免**参数 | 内部 Python API（`database/models/flow.py:508`） | 广场路径；构建页与另两个调用方不传 = 行为不变 |
| 授权变更**回调注册表**（`resource_type → async callback`，在 `ResourcePermissionApi.mutate_grants` 成功后触发，带 `actor / target / changes / result`） | 内部 Python 扩展点（`permission/application/resource_api.py`） | 本期只注册 `app`；将来知识库 / 工作流若要审计授权变更，注册即可，**不用再改 permission 代码** |
| 审计事件 `app.visibility_change`（+ 四处 lockstep 登记） | 审计事件 | 审计查询面；租户管理员取证 |
| **访问记录合并窗口 = 1800 秒（30 分钟）**（D7 的定义处；F054 design `:339` 现写 300s，**需回写勘误**） | 数值契约 | **F054**（`SETNX app_access:{app_id}:{user_id}` 的 TTL 取此值）。不回写 = F054 按 300s 落地，与 spec 决议-2 不符且没有任何报错 |
| **事件类型登记契约**（§4.2 末行）：任何写 `app.*` / `app.release.*` 的 Feature 必须在同一 PR 内改四处 | 文档契约 + §7 的断言测试 | **F054 / F055 / F049 / F051**——AC-27「不存在已写入但页面查不到的事件类型」由本 Feature 兜底验收 |
| 「可见范围区」区块（填 F054 发布 tab 的 slot） | React 组件 | platform 应用详情页；F055 的其余区块与它并列、互不引用 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| **F054 T059**：`FlowType.HOSTED_APP=35` + `_build_apps_subquery` 第三支（含手工租户条款、`status` 投影 2/1、`user_id` ← `owner_user_id`） | SQL / 枚举 | 第三支漏租户条款 = 四路径跨租户泄漏（坑 4）；投影列类型与另两支不一致（`id` 必须是 str）会让 UNION 直接报错 |
| **F054 T060**：`SUPPORTED_APP_TYPES` / `_FLOW_TYPE_TO_RESOURCE_TYPE` 加 35 + tag 预过滤 **4 处**（`tasks.md:47` 认账 4 处，T060 清单行漏写 `:517-528`）+ `ResourceTypeEnum.HOSTED_APP` | 常量 | 不放行 = 广场空列表**且不报错**；第 4 处漏补 = 有标签 tab 整类消失。**F056 只提勘误 + 验收，不接管实现**（同文件并发） |
| **F054 T060**：构建页的 `app_state` 查询参数（`api/services/workflow.py` 构建页函数 + platform `flow.ts:177 getAppsApi`） | HTTP 参数 | **广场不消费它**——广场链路的状态收窄由 F056 自己的内部参数 `app_state_in` 完成（D9）。此处只登记"同名概念存在两处"，防止实现者以为广场能白拿 |
| **F054 T059**：`App.state` 的取值集合（`online` / `stopped` / 草稿 / 待上线 / 已删除五值的字面量） | 领域枚举 | D9 的广场白名单 `{online, stopped}` 是**字面量对齐**，枚举改名不会有编译期报错，只会让广场悄悄空掉 |
| **F054 T063**：`typeMap` 补 `35:'app'`（`BuildPage/apps.tsx:215-218`，默认回落 `'workflow'`） | 前端常量 | 不补 = 弹窗开了但对着 `workflow` 类型查，registry 报类型不符（F054 坑 7）；**AC-11 入口 A 直接失效** |
| **F054 T067**：发布 tab 的 slot / children | React 组件契约 | slot 不存在或签名变 → 可见范围区无处挂载；三方并发改同一文件会冲突 |
| **F054 T071 / AC-62**：`useAppRuntimeEnabled` hook（读 `GET /api/v1/env.app_runtime_enabled`） | react-query v4 hook + HTTP 字段 | 字段或 hook 缺失 → 未部署形态下广场出现相关文案（AC-10 不成立）。**别引成 T090 / AC-61**：T090 是审批期预览入口、AC-61 是"两开关任意组合可启动" |
| **F054 AC-38**：访问记录写入（合并窗口 = **1800s**，本文 D7 定义，**待回写 F054 design `:339` 的 300s**） | 业务日志 | 勘误未回写 = F054 按 300s 落地；写入方若改口径（记请求级明细）→ 审计页高频事件量级爆炸 |
| **F048（既有）**：`PermissionDialog` / `getResourcePermissionGrantsApi` / `getResourcePermissionContextApi` / `mutateResourceGrantsApi` / `batch_check_business_actions` / `_identity_shortcut` / `catalog_policy.ACTION_RESOURCE_SCOPES` | 前端组件 + HTTP + Python | `ACTION_RESOURCE_SCOPES` 里 `app` 的动作集若变（比如有人"顺手"加了 `share`），D3 的裁剪就成了多余甚至错误；`PermissionGrantAssignee.protected` 语义变 → D5 判据静默失效（坑 13） |
| **F048（既有）**：`grant_subject_service.py:95` 的 `user_type == USER_TYPE_HUMAN` 过滤 | SQL | INV-29「选人不出现服务账号」靠它；改了会让服务账号出现在授权弹窗里 |
| **审计基建**：`AuditLogDao.ainsert_v2` / `_UI_VISIBLE_V2_ACTIONS` / `_V2_NAMESPACE_TO_ACTION_PREFIX` / `log.ts` / 三语 `bs.json` | Python + 前端常量 + i18n | 签名或白名单机制变 → 事件写了查不到（K3） |
| **F055**：`app.release.*` 白名单登记 | 审计登记 | F055 自登记；F056 只验收"可查"，若 F055 漏登记，AC-27 会记在本 Feature 头上（故 §7 有断言测试） |
| **114 部署**：nginx `location /apps/`（`/etc/nginx/conf.d/bisheng-lilu.conf`，F054 交付） | 运维配置 | 没这条 location，卡片点击落 platform SPA → `/404`；外网 13000 快照需手动重建 |

---

## 7. 测试与可观测

**分层策略**（不重复 tasks.md 的清单）：

- **后端单元测试**（`src/backend/test/workflow/`，`asyncio_mode=auto`）：
  - **第一层（合法性过滤）**：断言 `app` 桶请求集**不含 `share`**；`workflow`/`assistant` 桶请求集与改动前**逐元素相同**（防回归）；`visible` 在任何桶都不被滤掉（它不在 `ACTION_RESOURCE_SCOPES` 里，滤掉即广场空列表）。**并对 `aenrich_apps_can_share` 单独跑一次**：传 `("share",)` + 含 `flow_type=35` 的 data → **不抛 25001**、`can_share` 为 false（这条覆盖坑 1 的另外 4 个调用方，只测广场是测不到的）。
  - **第二层（口径切换）**：`_scan_visible_apps_page` 的 app 桶请求 `("use","edit")`、`kept` 按行类型取可见性 action；另 6 个 `_application_action_map` 调用方的入参与结果**逐元素不变**。
  - `_apply_page_can_share` 对 `flow_type=35` 恒 false。
  - `status` 类型豁免：传 `status=2` + 豁免集合 `{35}` 时，SQL 条件对第三支不生效（可用 DAO 层构造断言或对拼出的 SQL 文本断言）。
  - `_scan_visible_apps_page` 出口补 `slug` / `app_state`：托管应用有值、另两类为 None，且**不额外发起 N 次查询**（批量一次）。
  - **两个入口各断言一次**：`get_online_flows_page` 与 `get_uncategorized_flows` 的返回体里托管应用行都带 `slug` / `app_state`——后者**不调 `add_extra_field`**（`:1012-1016`），这条断言是坑 8 验收面的护栏。
- **后端集成测试**（pytest + httpx，连 test 中间件 MySQL / Redis / OpenFGA）：
  - **必须用非管理员用户**跑 `GET /api/v1/chat/online`：授权前 0 条托管应用、授权后 1 条、撤销后 0 条（AC-04 / AC-05 的"下一次请求生效"）。
  - 同一非管理员对同一应用调 F054 入口判定（`check_business_action("app", id, actor, "use")`）→ 与广场结果**同真同假**（AC-06 的机器化断言）。
  - 已下线应用在广场**仍出现**且 `app_state='stopped'`；草稿 / 待上线 / 已删除**不出现**（AC-03）。
  - 授权变更后审计表恰好 1 条 `app.visibility_change`；**重放同一 `idempotency_key` 不新增记录**（坑 12）。
  - **撤销场景的 `removed` 必须含主体身份**（坑 11 的机器化断言）：ADD 一个用户组 → REMOVE 它 → 断言 `metadata.removed[0]` 是 `{type: "group", id: ...}` 而**不是** `{assignee_id: ...}`；再断言"没有 REMOVE/MOVE 的纯 ADD 请求**不触发**名册预读"（用调用计数或 mock 断言，防止把成本加在最常见的路径上）。
  - **回调注册**：起一个最小 app 上下文调 `mutate_grants`，断言注册表里有 `app` 项（防"没注册 = 静默不写、无报错"，D6）。
  - **多租户**：A 租户用户查不到 B 租户的托管应用（坑 4 的回归，复用 `test/workflow/test_flow_dao_tenant_isolation.py`）。
- **审计登记断言测试**（本 Feature 对 AC-27 的兜底，**跨 Feature 价值最高的一条**）：一个参数化测试读取全部已注册的 `app.*` / `app.release.*` action 常量，逐条断言 ① 在 `_UI_VISIBLE_V2_ACTIONS` 里；② 在 `platform/controllers/API/log.ts` 的 actions 数组里（用文本匹配读文件）；③ 三语 `bs.json` 的 `log.eventTypeEnum` 里都有对应 `actionToI18nKey(action)` 的 key。**这条测试一旦存在，F054 / F055 / F049 将来漏登记会在 CI 上立即失败**，而不是等到有人在审计页里找不到事件。
- **前端**：client 广场无自动化（既有页面无测试基线）；platform 可见范围区的「仅 owner 可见」判据（非 protected 计数）可用纯逻辑单测覆盖（与 DOM 无关的纯函数抽出来测）。
- **不测**：`PermissionDialog` 内部（F048 既有覆盖）、F054 交付的入口与兜底页。

**114 手动验证（MVP-核心闭环的步 5–6）**：

0. 前置：`curl -s http://127.0.0.1:7860/api/v1/env | jq .app_runtime_enabled` → `true`；`/apps/{slug}` location 已生效（`curl -I http://127.0.0.1:4101/apps/<slug>` 非 404 的 SPA 页）。
1. **owner 账号** · platform 构建 → 应用 → 该托管应用卡片 ⚙️ →「管理权限」→ 弹窗出现（`resourceType=app`）→ 授予"全员用户组 / 根部门" → 保存。
2. 同一 owner · 应用详情页 · 发布 tab → 「可见范围区」显示**摘要**（不再是「仅 owner 可见」提示条）；把授权全部撤销后刷新 → 提示条**重新出现**（AC-12 双向验证）。
3. **⚠️ 关键：换成非管理员、非 owner 的普通账号**（memory `reference_remote_dev`「health 200 会骗人」；K2 的两条短路会让管理员账号**必然通过**，拿它当证据等于没测）——登录 client → 应用广场 →
   - 在**「未分类」tab** 里能看到该应用卡片（AC-08 的正确验收面，见坑 8），图标不是助手图标（坑 6），卡片上**没有分享按钮**（AC-07）；
   - 按名称搜索能搜到（描述搜索不在本轮，D10）；
   - **AC-09 抽验**：owner 侧改一次应用名称 / 描述（CLI deploy 或 F054 的元信息更新），普通账号**刷新广场**即见新值（不需要重登、不需要清缓存）；
   - 点击 → 浏览器地址栏变成 `http://<host>/apps/<slug>`（**没有 `/workspace`**，坑 3）→ 应用页面正常渲染。
4. owner 下线该应用 → 普通账号刷新广场 → 卡片**仍在**且带「已下线」标识（AC-03 / 决议-5），点击落 F054 的「已下线」页；重新上线后标识消失。
5. owner 撤销该普通账号的可见范围 → 普通账号**下一次请求**（刷新广场）即看不到，无需重新登录（AC-05）。
6. **管理员账号**（`is_admin()` 或持日志菜单权限——否则查不到任何 v2 事件，坑 15）→ platform 系统操作日志 → 模块选「应用工场」→ 事件类型选「可见范围变更」→ 能查到步 1 / 步 5 两条记录，操作人 = 变更人本人、对象 = 应用名；同一筛选下也能查到 F054 / F055 写的上线 / 下线事件（AC-27 的人工抽验）。

**关键日志 / 指标**：广场侧无新增指标（复用既有 `flow_fetch_start` 耗时打点，`api/v1/chat.py:58-70`）；审计回调失败只打 warning（不影响授权），日志字段建议 `resource_type / resource_id / operator_id / reason`——**这条 warning 是"审计静默丢失"的唯一信号**，114 验收若查不到事件，先 `grep app.visibility_change` 后端日志再怀疑写入逻辑。

---

## 8. 后续改进 / 不打算做的事

- **审计查询面「对象应用」筛选 + 导出 + 超管租户筛选**（AC-28–AC-32）：顺延。做的顺序是「对象应用筛选 → 租户筛选 → 导出」——没有第一件，"按应用追溯"这句产品语言不成立；导出必须复用查询的同一套过滤（决议-8：导出范围 ≠ 查询范围就是旁路）。同时**顺手修坑 15**（`group_ids` 恒 NULL 让部分管理员查不到 v2 事件）。
- **事件触达接线**（AC-43「租户管理员下线 / 重新上线 → owner」）：顺延。挂 F054 `AppStateService.stop/resume` 后置钩子，owner 本人执行时不发；失败只记日志（AC-45）。
- **模式切换（INHERIT↔CUSTOM）计入可见范围变更审计**：本期不接（托管应用恒 CUSTOM，无触发源）；将来若 F048 给 app 开放继承模式，`mode-drafts/apply`（`grant.py:159-176`）要接同一个回调注册表。
- **广场"上新推送"**：PRD-1 §3.0.3 明示本版不做，owner 自行转发入口链接。**不要因为"消息通道现成"就顺手加**——它会给全租户用户发广播。
- **广场按描述搜索**：D10 记为已知偏差；若要做，正确形态是为**全部类型**打开 `search_description`（一次广场级行为变更），不是给 `app` 开小灶。
- **不打算做**：为托管应用单独建一个广场 tab / 页面（AC-01 明令并列同构）；为授权做第二套面板（AC-11）；在广场前端做数据过滤（坑 9）。
- **重写触发条件**：若托管应用数量让"扫描式分页 + 批量鉴权"成为广场首屏瓶颈，按 D1「何时该重新考虑」对**三类统一**改造成 ListObjects 预过滤——单独给 `app` 改就是 AC-06 的裂缝。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-18 | **实现期同步（Wave 1–2 落地）**：① D2 / §4.2 订正——`app_state` 由 F054 第三支的第 10 列直接投出，F056 只补 `slug`（回查里仍带 `state`，仅缺失时兜底）；② D6 订正注册落点为 `api/services/f048_permission_runtime.py` 的 `initialize_f048_api_runtime`（与 `mutate_grants` 的构造同处，不动 `main.py`），并增补 `metadata.moved`；③ D9 订正实现形状——`status` 豁免抽成 `FlowDao._build_status_clause`、`app_state_in` **下推**到第三支子查询。其余偏差（测试落点、T015 xfail、T018 第 3 件未做）见 tasks.md 偏差记录 | Wave 1–2 实现落地 |
| 2026-08-17 | **审查修订：处理 14 条**（3 high / 4 medium / 7 low）。**high**：① **D6 的 `removed` 数据来源被证伪并重写**——`remove_source` 把被撤销的 source **整行丢弃**（`grant_source_service.py:279/305-311`），`result.grants`（`grant_service.py:232`）里查无此人，原"从结果快照反解"不成立；改为 **mutate 前读一页名册快照**（`list_permission_sources_page`）建索引，并认账成本与三条降本门槛 + `roster_truncated` 兜底（坑 11 重写）；② **`slug`/`app_state` 的补入点从 `add_extra_field` 改到 `_scan_visible_apps_page`**——未分类 tab 的 `get_uncategorized_flows` 从不调 `add_extra_field`（`workflow.py:1012-1016`），而它正是 §7 的唯一验收面（新增坑 21，§4.1 ② 补不对称说明）；③ **D3 重写为两层**——坑 1 的触发点不止广场，`aenrich_apps_can_share:133` 的 4 个调用方（`workstation/apps.py:53`/`:150`、`chat.py:83`、`workflow.py:962`）同样非法请求 `share`，故合法性过滤下沉到 `_application_action_map`（覆盖全部 7 个调用方），`visible→use` 的口径切换只留在 `_scan_visible_apps_page`。**medium**：④ D3 补「7 个调用点爆炸半径」表，写死规则放在哪一层；⑤ **D9 补 `app_state` 的落点归属**——广场链路无该参数落点，改为 F056 自建**内部参数** `status_exempt_flow_types` / `app_state_in` 并在服务端写死 `{online,stopped}`，不开 HTTP query；同时登记 `flow.py` 与 F054 T059 并发同文件的协调义务；⑥ **上游任务号订正**：开关读取件是 **F054 T071 / AC-62**（`useAppRuntimeEnabled.ts`），不是 T090 / AC-61（T090 是审批期预览入口）；⑦ **tag 预过滤第 4 处归属订正**——F054 `tasks.md:47` 已认账 4 处（T060 清单行漏写），改为 F056 提勘误 + 验收，**不接管实现**（同文件并发）。**low**：⑧ 坑 1 后果订正为 **HTTP 200 + 业务码 25001**（`BaseErrorCode` → `handle_http_exception`，`main.py:25-51`）而非 500，排查手法改为 `grep 25001`；⑨ **代码事实基线订正为 HEAD `11e1b211d`**（`084c1e134` 不在 3.0-vibe 历史上），并修漂移行号（`kept:450-455`、`flow.py:582`、docstring `:661-671`、`f048.py:242-262`、tag 预过滤 `:517-528`、`add_extra_field` 调用 `:548`）；⑩ `client/src/layouts/MainLayout.tsx`（**layouts 复数**）路径修正；⑪ **AC-09 显式认领**为本轮交付（零代码 + §7 抽验），此前两个清单都没有它；⑫ D5 判据补 **`app_state === 'online'`** 前置（AC-12 的「WHILE 应用已上线」，否则草稿态也常驻噪音提示条）；⑬ D7 的 1800s 补**回写 F054 design `:339`（现写 300s）**的待办 + §6.1 Outgoing 契约行；⑭ D6 补**注册时机与执行进程**（组合根显式注册，照 `main.py:55-77` 先例；worker 无触发源；注册成功打 info 日志，因未注册是静默失败）。坑表 20 → 21 条 | `/sdd-review` 独立审查 14 条发现 |
| 2026-08-17 | 初版（11 决策 / 20 坑）。按 spec 45 AC + `mvp-114-path.md` §6 MVP-核心裁剪编写；代码事实取探查笔记 `e1-square-authz-audit.md` 并由作者复核（`workflow.py:425/519-528/146-178/485`、`catalog_policy.py:71`、`chat.py:26-31/63`、`explore.tsx:62/132-146`、`Avator/index.tsx:30-45`、`permission_action_service.py:372-384`、`resource_api.py:290-372`、`grant_service.py:198-266`、`projection_plan.py:58-64`、`audit_log.py:193/261/272-282`、`log.ts:49/136-144/166` 逐条 grep 核实） | F056 design 首次编写 |

<!-- self-check
按 .claude/skills/sdd-review/references/design-checklist.md 24 项自检（2026-08-17，写手自检）：

已满足：
1 目标 1 句话 + 一句话总结 ✅
2 非目标逐项给出「顺延 + 落点方向」 ✅
3 §2 只写本 Feature 特有约束（K1–K11），无全局铁律重抄 ✅
4 全局铁律以「遵循 C1–C7」带过 + Constitution Check 逐条自查 ✅
5 决策 11 条（≥1–3） ✅
6 每条含备选（至少 1 个被否）/ 选定 / 原因 ✅
7 每条含「何时该重新考虑」 ✅（D11 的触发条件写在选定段末，形式为「预算恢复 / POC 要求」）
8 原因引具体证据（文件:行号、FGA 关系差异、protected 行、幂等标志） ✅
9 §4.1 四条数据流（广场两入口 / 跳转 / 授权→审计→生效） ✅
10 §4.2 对外字段含类型与取值 ✅
11 §4.3 模块表「职责 + 不做什么」两列齐 ✅
12 与 spec §5 指针表逐行对应（决策/约束/数据流/坑/契约/tasks） ✅
13 §5 共 21 条反直觉事实 ✅
14 每条带「如果不知道会怎样」 ✅
15 每条带「在哪处理」（决策号或文件） ✅
16 §6.1 含 HTTP 响应字段 + 内部 Python 扩展点 + 审计事件 + 前端组件 ✅
17 §6.2 含上游 Feature 契约 + F048 既有基建 + 运维配置 ✅
18 §6.2 每行有风险点列 ✅
19 §7 分层策略（单测/集成/登记断言/前端/不测） ✅
20 §7 给出 114 可操作剧本（含 curl、账号类型、逐步预期） ✅
21 §8 短板 + 不打算做的理由 + 重写触发条件 ✅
22 修订历史已记初版 ✅
23 与 spec 不矛盾 ✅（唯一需 spec 侧确认的一处：D10 对 AC-08「按描述搜索」取「本轮不做、记为已知偏差」——已在 D10 显式标注需 spec 口径确认）

未满足 / 待补：
24 「反映 tasks.md 偏差记录」——tasks.md 尚未编写，本项暂不适用；tasks 落盘后若出现改变系统认知的偏差，须回写本文并在修订历史加行。
另：D9 的 DAO 两个内部参数（`status_exempt_flow_types` / `app_state_in`）与 D2 的第三支 UNION 都落在 `database/models/flow.py` —— 属并发编辑的上游文件，本文只声明消费与协调义务，**未在本文修改 F054 任何文档**；若 F054 最终形状变更，D2 / D9 需同步修订。
**本文对上游 F054 留下三条待回写勘误**（均未由本文代改）：① design `:339` 的访问记录 TTL 300s → **1800s**（D7）；② tasks T060 文件清单补 tag 预过滤第 4 处 `workflow.py:517-528`（§4.3）；③ 若 T059/T060 未加 `status_exempt_flow_types` / `app_state_in`，由 F056 加并在 F054 侧登记（D9）。
-->
