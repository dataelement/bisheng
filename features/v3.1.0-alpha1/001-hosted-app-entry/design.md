# Design: 托管应用入口理顺与桌面专用通道下线

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：
> - 实现变化 → **覆盖更新本文档**，只留"今天的状态"、不留旧快照；但每个决策保留"为什么 + 被否方案"和坑（护栏，见 §3/§5）
> - **偏差分级**：推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design，不必停
> - `tasks.md`「实际偏差记录」只留一行指针，论证在本文档，不重复

**代码依据**：`feat/3.1.0-alpha1@837c8a8fde`；配套客户端 bisheng-desktop `V1.3.1@ac6a3e7a4d` 与已发版 `v1.3.0`。
**状态**：2026-11-23 用户确认（★）；服务端与两个网页端已实现，真实环境未验证（§7）；AC-03 的实现口径待用户确认（文末）。

---

## 1. 目标与非目标

**目标**：托管应用只留既有发布管线一条发布路；员工端在「应用」「发现广场」按类型区分和分类；管理后台不再出现跳员工端的入口、「应用模板」页先看说明；拆掉 v3.0.0 F130 给桌面单独造的接入、鉴权、发布、取源码和 Agent 规范，同时给已发版的 1.3.0 客户端留出可理解的失败。

**非目标**：不改托管应用平台本身（运行时、发布管线、审批、详情页、命令行、技能包、教程页）；不改名；不改表结构；不做员工自助密钥；桌面客户端自身的界面在 bisheng-desktop 配套交付，本文只写它依赖的服务端行为（§6.2）。

---

## 2. 关键约束

| 约束 | 本特性怎么遵守 |
| --- | --- |
| C1 分层 | 只动既有 endpoint 与 domain service；不新增跨层调用。改完跑 `scripts/arch-guard.sh` |
| C2 双库 | **不改表、不加迁移**。`v3_0_0_f130_cloud_workbenches.py` 保留（只把两个计数列放宽为 BIGINT，后续迁移以它为 down_revision） |
| C3 多租户 | 列表查询保持在原有租户上下文里（`strict_tenant_filter` / `principal_scope`），不新增手写租户条件 |
| C4 权限 | 所有判断仍走 `business_authorization`（`check_business_action` / `filter_apps_by_action`）；不新增权限动作 |
| C5 错误码 | 新增 1 个：`16149`，落在 161 段「16140–16159 入口与身份注入」子段，三语文案同步 `packages/locales/src/api_errors/` |
| C7 前端 store | 新增的类型参数经 `~/api/apps.ts` 传给接口，store 不直接发 HTTP |
| 兼容 | 1.3.0 客户端已发版（带 F130 云端标签和 Agent 云端工具），服务端变化必须让它「列表照常、其余明确报错」 |
| 可选部署 | 运行时层可整层不装：`settings.app_runtime.enabled` / `WorkFlowService.enabled_app_types()` 决定托管应用类型是否出现 |
| 前端 | 两个 SPA 不混用；三语文案；`client` 的 `shared.gen.json` 由 `packages/locales` 生成，只改源文件后重新生成 |

---

## 3. 方案对比与选定

### 决策 1：桌面打开托管应用用什么身份

- **备选**：A. 保留一次性票据 + Redis 桌面会话 + app-proxy 换票（现状）；B. 桌面用 Chat 已登录的网页会话打开 `/apps/{slug}/`；C. 一律交给系统浏览器。
- **选定**：B（桌面实现，见 §6.2）。服务端拆掉 A 的全部代码。
- **原因**：B 让网页和桌面用同一个身份、同一条入口鉴权（JWT Cookie → `authorize_entry`），去掉一套并行鉴权：A 牵出了 Redis 票据与会话、app-proxy 换票路由和专用 Cookie、入口鉴权里的 `desktop_actor` 分支、运行时身份里的 `dsh_session` 类型，共四处额外代码。C 要员工在浏览器里再登录一次，体验最差。
- **何时推翻**：若实测 app-proxy 不认 Chat 会话分区里的网页 Cookie（作用域 / SameSite / 过期续期），退回 C，并回到本节重新确认，不要恢复 A。

### 决策 2：桌面 Chat 里点托管应用卡片

- **备选**：A. 网页识别桌面环境后同窗口跳转（原云端工作台页的做法）；B. 网页调用新增的桌面桥接方法；C. 网页不改，仍然 `window.open`，桌面在 Chat 视图的 `setWindowOpenHandler` 里把同域名 `/apps/` 地址留在客户端打开。
- **选定**：C（桌面实现）。网页两处打开代码（`useAppCenter.ts`、`explore.tsx`）不改。
- **原因**：A **不可行**：桌面 Chat 视图只要文档离开 `/workspace` 就进入出错恢复（bisheng-desktop `src/main/enterprise/chat-view.ts` 的 `noteDocumentLeftWorkspace`），托管应用不会被正常显示（§5 坑 1）。B 要改网页、扩桥接白名单（`clientEnvironment/types.ts` + `presentation.ts` + `docs/dsh-adaptation.md`），形成两仓库新契约。C 只改桌面一处，浏览器与桌面共用同一套网页代码，「云端工作台」标签和 Chat 内打开用同一个应用窗口。
- **何时推翻**：桌面无法区分同域 `/apps/` 与其他外链时（例如私有化部署把托管入口放在独立域名），改用 B。

### 决策 3：桌面列表接口

- **备选**：A. 删除，桌面改调网页的 `/chat/online`；B. 保留 `GET /api/v1/dsh/apps`，路径、参数、游标、返回字段不变，去掉 `managed`，增加 `runtime_enabled`；C. 新开接口。
- **选定**：B。
- **原因**：1.3.0 校验游标格式和返回字段（`id()` 校验游标，launch 校验 slug / entry_path），换形状就会坏；桌面主进程只持桌面会话凭据，不能直接调网页 Cookie 鉴权的接口。列表规则不变：同租户、`state == online`、`check_action(..., "use")`；`use` 是 `visible` 的旧别名（§5 坑 2），与发现广场用的是同一个权限判断。
- **`managed=true`**：只有被拆掉的 Agent 开发流程用它列「可编辑的应用」，改为返回 16149（决策 4）。
- **何时推翻**：1.3.0 退场后，可以让桌面改用与发现广场同一个查询服务、换游标格式（§8）。
- **范围**：发现广场显示「已上线」和「已下线」（已下线卡片标「已下线」、不能打开，F056 既定规则，`SQUARE_APP_STATES`），桌面列表只列「已上线」。spec AC-22 已按此口径确认（2026-11-23）。

### 决策 4：已下线的桌面能力怎么回应 1.3.0

- **备选**：A. 直接删路由，返回 404；B. 保留路由壳，统一返回新错误码 16149，HTTP 400，`status_message` 提示升级到 1.3.1 或以上。
- **选定**：B，覆盖 `POST /{app_id}/launch`、`GET /deploy-limits`、`POST /deploy`、`GET /{app_id}/deployments/{id}`、`GET /{app_id}/versions/{id}/source`、`GET ?managed=true`。
- **原因**：1.3.0 的 `json()` 遇到非 200 时把 `status_message` 当错误信息抛出，B 能让员工看到原因；A 只会显示通用错误，列表路由 404 还会被 1.3.0 当成「服务器没有云端工作台接口」。错误必须是**不带 `ClientCode` 的普通 `BaseErrorCode`**：带 `ClientCode` 的 Dsh 错误走 `DshRoute.error` 格式，没有 `status_message`（§5 坑 3）。
- **认证**：路由壳只声明 `desktop_principal` 依赖、不声明请求体，所以 `/deploy` 不再读上传包，未认证时照常先返回桌面鉴权错误；原 PR 为 `/deploy` 加的「解析请求体前先认证」路由类逻辑随之去掉。
- **文案是中英双语一句话**（`Msg` = 「请将毕昇桌面端升级到 1.3.1 或以上后使用此功能 / Upgrade BISHENG Desktop to 1.3.1 or later to use this feature」）：1.3.0 原样显示 `status_message`，不查前端 `api_errors` 文案，也不带语言协商，只能在服务端一句话里同时照顾中英文用户。网页端照常按 `api_errors:16149` 显示三语文案。
- **何时推翻**：1.3.0 装机量清零后，可以把这些路由壳连同错误码一起删掉（§8）。

### 决策 5：类型分类在服务端过滤

- **备选**：A. 前端对已拉到的列表过滤；B. 接口加 `flow_type` 参数。
- **选定**：B。`/api/v1/chat/online` 已有 `flow_type`（含 35），前端直接传；`/api/v1/workstation/app/uncategorized`、`/api/v1/workstation/app/used` 各加可选 `flow_type`，不传时行为不变。
- **原因**：发现广场和「未分类」是游标翻页，最近使用是服务端分页，前端过滤会出现「某页过滤后为空但还有下一页」和计数不对。
- **类型选项是否出现「托管应用」**：网页用现有的 `hooks/useAppRuntimeEnabled.ts`，与服务端 `enabled_app_types()` 口径一致；服务端对未开通的类型直接返回空页。已选「托管应用」后开关变为关闭时，分类自动回到「全部类型」。
- **控件**：类型分类用 `@bisheng/ui` 的 `Segmented`（规范：2–5 个互斥选项），两个页面共用 `pages/apps/components/AppTypeSegmented.tsx`；类型与 `flow_type`、标签文案的对应只在 `pages/apps/appTypes.ts` 一处。
- **卡片类型标签用默认灰色 `Tag`，不按类型上色**：`packages/ui/docs` 的 Tag 规范要求普通分类词用默认中性色，颜色只表达状态或强调。需求文档原型里给三种类型分别上了色，实现以组件规范为准（AC-01 只要求标签文字，不涉及颜色）。标签放在卡片右上角、置顶 / 更多按钮之前，同在一个不收缩的容器里，不遮挡按钮。
- **与标签分类、搜索词的组合（AC-03 待确认，见文末）**：类型分类与「标签分类」组合，也与「搜索词」组合；但发现广场里「标签分类」和「搜索词」沿用现有规则互斥——输入搜索词时在全部标签里搜，选标签会清掉搜索词（`explore.tsx` 注释里写明的既定行为）。所以实际不存在「标签 + 类型 + 搜索词」三者同时生效的状态。
- **何时推翻**：若以后列表改为一次性全量返回（不分页），可以退回前端过滤。

### 决策 6：原 PR 里哪些是通用改动、保留

| 改动 | 处理 | 原因 |
| --- | --- | --- |
| app-proxy `sse.py`：SSE 流定期重新鉴权，撤权后断开 | **保留** | 对所有经入口的 SSE 生效，网页用户同样受保护；平台对 WebSocket 早有同类机制 |
| `admission.py` 发布准入锁（`SELECT … FOR UPDATE` 应用行） | **保留**，去掉其中只给桌面用的 `base_version_id` / `check_base_version` | 命令行与构建页发布同样受益，防并发提交互相覆盖 |
| `dsh/access_runtime.py` 抽出 `build_runtime()` | **保留** | 同事的头像功能测试已依赖（`test/dsh/test_profile_avatar.py`、`test_avatar_cold_runtime.py`） |
| SDK 0.1.1 / 0.1.2 历史版本下载（`artifact_service` 的 `sdk_history`、`distribution.py`） | **保留** | spec AC-24 |
| app-proxy `headers.py` 不向应用转发 `bisheng_app_session_*` Cookie | **保留**（一行） | 1.3.0 留下的旧 Cookie 不应转发给应用代码 |
| `app_query_service` 版本列表的 `deployment_status` 与 `AppDeploymentDao.astatuses_by_version` | **去掉** | 两个前端都没用，只有被拆的桌面流程用 |
| `failure.py`、`app_secret_repository.py` 的格式化改动 | 不动 | 纯格式或无行为差异 |

### 决策 7：「应用模板」页托管应用说明

- **选定**：说明是前端静态内容（三语文案，`flow.json` 的 `hostedAppGuide.*`），不新增接口，组件为 `components/bs-comp/sheets/HostedAppGuide.tsx`；托管应用卡片变成和「工作流」「助手」并列的可选中项（`role="button"` + `aria-pressed`，支持键盘），选中时右侧不请求模板、显示说明，搜索框禁用，关闭抽屉时复位；运行时开关复用构建页已有的 `appConfig.appRuntimeEnabled`（`contexts/locationContext.tsx`，来自环境接口的 `app_runtime_enabled`），关闭时在说明顶部用现有文案 `bs.json` 的 `hostedApp.guide.descDisabled`。「看部署教程」用 `window.open("/tutorial/hosted-app.html", "_blank", "noopener")`。
- **被否**：从服务端下发说明内容——内容随版本发布即可，不需要运行时可配。
- **何时推翻**：若产品要按租户定制说明或教程地址，再改为服务端下发。

### 决策 8：旧地址与旧文档

- 网页路由 `/apps/cloud-workbenches` 保留为 `<Navigate to="/apps" replace />`，避免收藏的链接 404。
- `features/v3.0.0/130-cloud-workbenches/` 不删（追溯用），在 spec / design 顶部加一行「桌面专用部分已由 v3.1.0-alpha1 F001 撤销」。

---

## 4. 系统现状（改完以后）

### 4.1 数据流

**员工打开托管应用**

```
网页「应用」/「发现广场」卡片 ──window.open("/apps/{slug}")──▶ app-proxy ──内部 authorize（网页 JWT Cookie）──▶ 放行 / 兜底页
桌面「工作台 → 云端工作台」 ──主进程 GET /api/v1/dsh/apps（桌面会话）──▶ 列表
        └─打开：用 Chat 会话分区开 /apps/{slug}/ ──▶ 同上的 app-proxy 入口鉴权
桌面 Chat 里的网页点卡片 ──window.open──▶ 桌面拦截同域 /apps/ ──▶ 同一个应用窗口
```

**发布**（不变）：命令行 `bisheng deploy`（平台密钥）或构建页详情页 → `PublishPipelineService.accept`（准入锁）→ 扫描 / 构建 / 启动检查 → 审批单 → 上线。

### 4.2 对外可见的契约

| 接口 | 改完以后 |
| --- | --- |
| `GET /api/v1/dsh/apps`（桌面会话） | 不变：`{items: [{id, name, slug, description, state, version_id, entry_path}], next_cursor}`；**新增** `runtime_enabled: bool`；运行时关闭时 `items` 为空；`managed=true` → 16149 |
| `POST /api/v1/dsh/apps/{app_id}/launch` 等 5 个桌面能力 | HTTP 400，`{"status_code": 16149, "status_message": "请将毕昇桌面端升级到 1.3.1 或以上后使用此功能 / Upgrade BISHENG Desktop to 1.3.1 or later to use this feature", "data": …}`；未认证仍先返回桌面鉴权错误 |
| `GET /api/v1/chat/online` | 不变（已有 `flow_type`） |
| `GET /api/v1/workstation/app/uncategorized` | **新增**可选 `flow_type`（5 / 10 / 35） |
| `GET /api/v1/workstation/app/used` | **新增**可选 `flow_type`（5 / 10 / 35）；不传时行为不变 |
| 删除 | `GET /api/v1/apps/workbenches`；`GET /api/v1/dev-toolkit/workbench-guide*.md`；内部 `POST /api/v1/internal/app-proxy/desktop-session`；app-proxy `POST /apps/{slug}/_desktop`；入口鉴权不再认 `bs-view-` 会话和 `bisheng_app_session_*` Cookie |

### 4.3 关键模块职责（改动清单）

**后端 `src/backend/bisheng/`**
- `dsh/api/endpoints/apps.py`：只保留列表（加 `runtime_enabled`、`managed` → 16149）和 5 个返回 16149 的路由壳；去掉对 `desktop_publish_service`、`source_export`、`desktop_app_sessions` 的依赖。
- `app_runtime/domain/services/desktop_apps_service.py`：保留 `actor()`、`page()`、`workbench_page()`；删 `require()`、`launch()`。
- 删除：`app_runtime/domain/repositories/desktop_app_sessions.py`、`app_runtime/domain/services/desktop_entry_service.py`、`dsh/application/runtime_identity.py`、`app_publish/domain/services/desktop_publish_service.py`、`app_publish/domain/services/source_export.py`。
- 还原接入点：`app_runtime/api/endpoints/internal_app_proxy.py`（去 `bs-view-` 分支和 desktop-session 路由）、`app_runtime/domain/services/entry_authz_service.py`（去 `desktop_actor`）、`app_runtime/domain/services/runtime_authorization_service.py`（去 `dsh_session`）、`utils/http_middleware.py`（去豁免路径）、`app_publish/domain/services/publish_pipeline_service.py`（去 `base_version_id` / `check_base_version`，保留准入锁）、`app_runtime/domain/services/app_query_service.py` + `app_publish/domain/models/app_deployment.py`（去 `deployment_status`）。
- `app_runtime/api/endpoints/apps.py`：删 `/workbenches`。
- `workstation/api/endpoints/apps.py` + `api/services/workflow.py`：`uncategorized`、`used` 加 `flow_type`。
- `dev_toolkit`：删 workbench-guide 路由、`read_workbench_guide`、`guides/workbench-guide.*.md`、`skills/platform-wiring/workbench-realtime/`、`SKILL.md` 末尾「工作台部署与记录协作补充（F113）」一节；SDK 历史版本保留。
- `common/errcode/app_factory.py`：新增 16149。

**app-proxy `src/app-proxy/app_proxy/`**：删 `desktop.py` 与 `main.py` 里的 `_desktop` 路由、`clients.py` 的 `redeem_desktop`、`authz.py` 里读桌面 Cookie 的分支；`sse.py`、`proxy.py` 的 SSE 接入与 `headers.py` 的 Cookie 过滤保留。

**网页 `src/frontend/client/`**：删 `pages/apps/CloudWorkbenches.tsx`、`api/cloudWorkbenches.ts`；`routes/index.tsx` 旧路由改为跳转；新增 `pages/apps/appTypes.ts`（类型 ↔ `flow_type` ↔ 标签文案）和 `pages/apps/components/AppTypeSegmented.tsx`（类型分类控件）；`pages/apps/index.tsx` 去链接、在提示语下方加类型分类；`explore.tsx` 在右侧筛选区、搜索框前加类型分类并传 `flow_type`（`AgentNavigation.tsx` 不改）；`hooks/useAppCenter.ts` 持有类型状态并传 `flow_type`；`api/apps.ts` 三个列表请求加可选 `flowType`；`AgentCard.tsx` 右上角类型标签、去 `openLabel`；`locales/*/translation.json` 加 `com_app.type_*`。

**管理后台 `src/frontend/platform/`**：`pages/BuildPage/apps.tsx` 去「云端工作台」链接；`components/bs-comp/sheets/AppTempSheet.tsx` 托管应用可选中、右侧说明、搜索禁用；新增 `components/bs-comp/sheets/HostedAppGuide.tsx`（说明面板与运行时提示）；`flow.json` 三语文案。

**文案 `src/frontend/packages/locales/`**：`shared` 删 `cloudWorkbenches.*`；`api_errors` 加 16149；改完用 `node scripts/build.mjs` 重新生成两个应用的 `shared` / `api_errors` 生成文件。

**接口清单**：`packages/api-client/src/requestScopeRoutes.json` 重新生成（少了 `GET /api/v1/apps/workbenches` 和内部 `POST /api/v1/internal/app-proxy/desktop-session`），须与后端 `route_inventory(app.routes)` 一致。

**测试**：删 `test/cloud_workbench/`、`test/app_publish/test_desktop_publish.py`、`test/dev_toolkit/test_workbench_guide.py`、app-proxy `tests/test_desktop_launch.py`、前端 `CloudWorkbenches.test.tsx`、`cloudWorkbenches.test.ts`；新增见 §7。

---

## 5. 已知坑 / 反直觉事实

1. **桌面 Chat 视图离开 `/workspace` 就进入出错恢复**（bisheng-desktop `chat-view.ts` 的 `noteDocumentLeftWorkspace`）。所以「网页在桌面里同窗口跳到 `/apps/{slug}/`」并不能把托管应用嵌进 Chat 显示。不知道的话会照着原云端工作台页的写法做，桌面里只看到出错页（决策 2）。
2. **`use` 是 `visible` 的旧别名**：`permission_action_service.normalize_legacy_action` 把 `use` / `use_kb` 换成 `visible`。桌面列表的 `check_action("use")` 和发现广场的 `visible` 是同一个判断；不知道的话会以为两边权限不同而去「统一」。
3. **带 `ClientCode` 的 Dsh 错误没有 `status_message`**：`DesktopAppsRoute` 对它们走 `DshRoute.error`，1.3.0 只能显示「Cloud workbench request failed.」。要让旧客户端看到「请升级」，必须用普通 `BaseErrorCode`（决策 4）。
4. **发现广场的托管应用包含「已下线」**（`SQUARE_APP_STATES = {online, stopped}`，草稿永不出现），桌面列表只含「已上线」（决策 3）。
5. **`workbench_page` 不按租户过滤 SQL**：按 `App.id` 每 100 条全表扫描后在内存里过滤租户和状态，可能返回空页但 `next_cursor` 不为空。1.3.0 会继续翻页，所以能用；本次为了保持 1.3.0 的游标格式不改扫描方式（§8）。
6. **`sse.py` 是通用能力**：文件名和原 PR 都挂在云端工作台名下，但它对所有 SSE 流做撤权断连，误删会让网页用户的权限收回不再即时生效。
7. **运行时关闭时托管应用类型不存在**：`enabled_app_types()` 会直接返回空页，前端类型分类也要同步隐藏「托管应用」，否则选了它永远是空列表。
8. **`client` 的 `shared.gen.json` 是生成物**：改 `packages/locales/src/shared/*.json` 后要重新生成，不能只改生成文件。
9. **删路由要同步 `requestScopeRoutes.json`**：前端请求作用域清单必须与后端 `route_inventory(app.routes)` 一致，只删后端路由不重新生成清单，对应的一致性测试会失败。

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 消费方 | 契约 | 改了会破坏谁 |
| --- | --- | --- |
| bisheng-desktop 1.3.0（已发版） | `GET /api/v1/dsh/apps` 形状、游标；其余 5 个路由返回 16149 | 改列表形状或游标会让 1.3.0 的云端标签整体报错 |
| bisheng-desktop 1.3.1（配套） | 同上，并读 `runtime_enabled` 决定「制作我的工作台」里云端是否可点、标签显示什么 | 去掉 `runtime_enabled` 会让 1.3.1 无法判断是否开通 |
| 网页 / 管理后台 | `flow_type` 参数（三个列表接口） | — |
| 已经用 SDK `realtime` 的托管应用 | SDK 0.1.2 继续可下载 | 删 SDK 会让它们构建失败 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 用途 | 风险点 |
| --- | --- | --- |
| v3.0.0 F054 app-proxy 入口鉴权（网页 JWT Cookie → `authorize_entry`、`extract_access_token`） | 网页和桌面打开托管应用的唯一身份路径 | 入口改为只认 Bearer、或 Cookie 改为非 `path=/`，桌面共用 Chat 会话的打开方式会失效（决策 1 退回 C） |
| v3.0.0 F055 发布管线、F056 发现广场查询（`get_online_flows_cursor`、`SQUARE_APP_STATES`、`filter_apps_by_action`） | 发布、员工端列表 | 广场改状态集合或权限动作时，桌面列表规则要同步（INV-2） |
| `settings.app_runtime.enabled`、环境接口 `app_runtime_enabled` | 托管应用类型是否出现 | 两处口径不一致会出现「分类有、列表空」 |
| bisheng-desktop `V1.3.1`（配套 PR） | 「制作我的工作台」先选云端 / 本地；「云端工作台」标签用 Chat 会话打开；Chat 内 `/apps/` 新窗口留在客户端打开；去掉 Agent 云端工具、确认弹窗、票据窗口 | 服务端先合、客户端没跟上时，1.3.1 开发版的云端标签打开会拿到 16149；两边要一起发 |
| bisheng-desktop `v1.3.0`（已发版） | 只消费，不改 | 见 §6.1 |

---

## 7. 测试与可观测

- **后端（pytest）**：
  - `test/dsh/test_hosted_app_catalog.py`：桌面列表的租户 / 状态 / 权限过滤，形状不变 + `runtime_enabled`；运行时关闭返回空；`managed=true` 与 5 个路由返回 16149、`status_message` 含「1.3.1」；`/deploy` 不读上传包；未认证仍先返回鉴权错误。
  - `test/app_runtime/test_entry_authz_service.py`：入口鉴权不认 `bs-view-` 会话。
  - `test/workstation/test_used_app_pin.py`、`test_f040_app_square_cursor.py`：`used` / `uncategorized` 的 `flow_type` 过滤、未开通类型返回空、选托管应用时不查会话记录；不传 `flow_type` 的行为由这两个文件里原有的测试覆盖。
- **app-proxy（pytest）**：`tests/test_authz_and_fallback.py::TestRetiredDesktopAccess`——`/apps/{slug}/_desktop` 不再存在；只带 `bisheng_app_session_*` Cookie 时按未登录处理；`tests/test_sse_revocation.py` 改用网页登录 Cookie 后保留。
- **网页（jest，客户端测试用 jest 不是 vitest）**：`explore.test.tsx`「ExplorePlaza kind filter (F001)」、`useAppCenter.test.tsx` 类型分类传 `flow_type`、未开通时隐藏、切换后回到第一页。
- **管理后台（vitest）**：`src/test/appTempSheetHostedGuide.test.tsx`——选中托管应用显示说明、不打开新标签、搜索禁用、切回模板类型复位、运行时关闭时有提示、「看部署教程」打开教程页。
- **回归基线**：在干净的 `feat/3.1.0-alpha1` 上跑同样的测试集，逐文件对比失败列表，只接受新增 0。
- **静态检查**：ruff、`scripts/arch-guard.sh`、前端 lint / typecheck / `check-i18n`。
- **真实环境（待确认环境）**：装了运行时的测试环境上照教程走一遍发布 → 审批 → 授权 → 网页打开；1.3.0 安装包上点打开，确认能看到「请升级」（spec Q1）。
- **手动验证命令**（`$BS` 为平台地址，`$DSH` 为桌面会话访问令牌，测试账号用时向需求方要，不写进文档）：

  ```bash
  curl -s "$BS/api/v1/dsh/apps" -H "Authorization: Bearer $DSH" | jq '.data | {runtime_enabled, n: (.items|length), next_cursor}'
  curl -s -X POST "$BS/api/v1/dsh/apps/<app_id>/launch" -H "Authorization: Bearer $DSH" | jq '{status_code, status_message}'   # 期望 16149
  curl -s -o /dev/null -w "%{http_code}\n" "$BS/api/v1/dev-toolkit/workbench-guide.md"                                            # 期望 404
  curl -s "$BS/api/v1/workstation/app/used?flow_type=35" -b "access_token_cookie=<网页登录 Cookie>" | jq '[.data.list[].flow_type] | unique'
  ```

---

## 8. 后续改进 / 不打算做的事

- 1.3.0 装机量清零后，删掉 5 个路由壳与 16149。
- `workbench_page` 改为按租户、状态在 SQL 里过滤（需要同时换游标格式，等 1.3.0 退场再做）。
- 桌面列表是否也显示「已下线」——本期不做。
- 员工自助申请平台密钥、名称统一——不在本期。

---

## 待用户确认

1. **spec AC-03 与现有发现广场规则不一致**（决策 5）：AC-03 写的是「标签分类 + 类型分类 + 搜索词」三者同时生效，但发现广场里标签和搜索词本来就互斥（输入搜索词时在全部标签里搜）。实现保留了这个既有规则，类型分类分别与标签、与搜索词组合。建议把 AC-03 改为：「WHEN 员工在『发现广场』选择了类型分类, THE SYSTEM SHALL 在当前标签分类或当前搜索结果中只展示该类型的应用；标签分类与搜索词的关系沿用现有规则（输入搜索词时在全部标签里搜）」。确认后回写 spec；若要求三者同时生效，需要另改发现广场的搜索规则。

## 修订历史

| 日期 | 变更 |
| --- | --- |
| 2026-11-23 | 初稿；用户确认设计与 AC-22 措辞修正 |
| 2026-11-23 | 实现后按现状更新：16149 双语文案与路由壳认证方式（决策 4）、类型分类控件 / 灰色类型标签 / 与标签和搜索词的组合（决策 5）、说明面板组件（决策 7）、改动清单与测试清单（§4.3、§7）、坑 9；新增 AC-03 待确认项 |
