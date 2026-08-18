# Design: 发布管线、预置审批流、版本记录、资源档位与能力总线

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（65 条 AC、边界、9 条决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 按 `3.0-vibe`（含 F048、F049 Wave 1 **与 F054 首波落码**）于 2026-08-17 由两份探查笔记（E1 审批与管线后端 / E2 发布面与审批弹窗前端）核实并经评审复核，路径以 `src/backend/bisheng/` 为根（前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`；仓根路径显式写出）。行号会漂移、符号名不会——**落地前一律以符号名重定位，不要按行号跳**。
>
> ⚠️ **F054 已落码，下列原"待办"已是既成事实**：`common/errcode/app_factory.py`（161 段）存在；`audit_log.py` 的 `_V2_NAMESPACE_TO_ACTION_PREFIX` 已含 `"app": "app."`（`:266`）且 `app.*` 白名单已就位——F055 只**追加 action 值**，不新建命名空间。
>
> **本文是"要建成的样子"**：F055 尚未开工，`app_publish` 模块、`resource_tier` / `app_deployment` 两张表、密钥扫描规则集、`app_publish_request` 审批场景全是绿地；**唯三例外**是三项阻塞前置（`approver_resolver` / seed / `withdraw` 守卫）——它们是对**存量代码**的修改，且对既有审批场景有行为变更。实现后按现状覆盖本文。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待写）· [release-contract.md](../release-contract.md)（表 1 **ResourceTier** / **「应用发布」审批场景预置** / **AppManifest** 三项归本 Feature；INV-28 / INV-29 / INV-31 / INV-33 / INV-34 / INV-36）· [mvp-114-path.md](../mvp-114-path.md)（**§6 MVP-核心是本轮裁剪基准**、§3 114 环境事实、§1 演示剧本步 3–4）
**上游 / 姊妹**: [F054 design](../054-app-domain-runtime/design.md)（领域对象 D8 / 容量与档位 D11 / 状态动作与编排 RPC §4.2 / 删除钩子 §4.1-C）· [F049 design](../049-openapi-auth-baseline/design.md)（凭据底座 D2 / `open_api_subject` 工厂 / `OpenApiPrincipal.resource_owner_user_id`）· [F053 spec](../053-dev-cli-skills/spec.md)（CLI 侧 AC-31～AC-38）· [F056 spec](../056-app-square-governance/spec.md)（可见范围区 / 审计面）
**审批模块权威参考**: `.claude/skills/approval-module/SKILL.md`（**改审批中心代码必须同 PR 更新该 skill**，见 §8）
**版本**: v3.0.0
**最后更新**: 2026-08-17

---

## 1. 目标与非目标

- **目标**：把「一次 `bisheng deploy`」变成「一个已上线、可被找到、可被治理的应用」——交付发布管线的全部服务端（接收包 → 冻结快照 → 托管预检 → 密钥扫描 → 正式版本记录 → 审批单 → 上线终检 → 触达）、平台预置的「应用发布」审批流（部署即生效、含三项阻塞前置的存量修复）、只增不改的版本记录与终态标注、平台级资源档位实体，以及应用经能力声明取得平台能力的总线。它站在 F054 的领域模型与运行时之上，**只调 F054 的状态动作、不直写应用态**。
- **非目标**（防后人误扩范围）：
  - **F054 的地盘**：App / AppVersion / AppInstance 三张表与五个状态动作、runtime-manager 与 app-proxy、`app` 资源类型注册、构建页卡片与详情页四 tab 壳、预览入口路由——本 Feature **只调用与填充**，不碰壳、不直写应用态（spec 决议-8 / F054 §6.1）。
  - **F056 的地盘**：应用广场、授权交互（含发布面可见范围区的内容与行为，本 Feature 只留槽位）、审计查询面与「对象应用」筛选、GOV-07 界面通道。
  - **F053 的地盘**：CLI 命令本身（打包 / 上传 / 轮询 / 交互确认 / `logs` 输出）——本 Feature 只做服务端接收、状态接口与权限判定。
  - **本轮 MVP-核心之外一律后置**（`mvp-114-path.md` §6 F055 行；**属本 Feature 范围、不得被裁掉**，逐项落点方向见 **D13 / D14 / D15** 与 **§8**）：**能力总线注入与收回**（D13）· **应用运行期凭据**（D13）· **审读视图与审批期临时预览实例**（D14）· **结构演进（改删列确认与迁移前快照）**（D3 / §8）· **WB-15 版本差异**（D15 / §8）· **资源档位管理 tab**（D11）· **发布面提交入口**（spec 决议-2，随 PRD-2）。
  - **明确不做**（PRD-1 §5.2 已取消 / 顺延）：平台侧回滚、迭代审批单变更摘要、应用标签设置、租户级实例数配额、审批单催办 / 超时提醒 / 升级、任何免审配置项（INV-34）、应用运行期凭据的产品化（管理入口 / 强制吊销 tab / 会话 key）、发布期 CVE 扫描与 SBOM（v3.1）、密钥引用（Discovery N4，随 PRD-2）。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md) **C1–C7**，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| **K1** | **接入审批中心是「四件套」不是三件套**：① preset 目录（`approval/domain/services/approval_registry.py:16-44 with_default_presets`，只是管理后台下拉来源 + `approver_source_types` 白名单）② 业务侧本地 registry + Gate 组装（范式 `channel/domain/services/channel_service.py:1524-1530`，**没有全局单例注册表**，`ApprovalGate(registry=...)` 是构造参数 `approval_gate.py:79-90`）③ runtime handler 工厂分支（`approval_runtime_handler_factory.py:17-35`，outbox 执行 / 多节点 advance / reject / withdraw 钩子都从这里重建 handler，**漏加分支 = 审批通过后业务永不执行**）④ **seed**（`common/init_data.py:320-436`）。**缺 ④ 则 `ApprovalGate` 在 `approval_gate.py:109-111` 直接 `raise ApprovalScenarioDisabledError`**，第一次 deploy 就炸 | E1 §1.1；skill §4 |
| **K2** | **Gate 的两个"静默"语义必须由调用方兜**：① 重复提交命中 `find_duplicate_active_instance`（`approval_gate.py:93-103`，按 `(tenant_id, scenario_code, business_key, applicant_user_id)` 且 status ∈ `pending/exception/execute_failed`）**直接返回既有实例、不报错** → AC-03「在途则拒绝新提交」必须在**调 Gate 之前**自查并抛业务码；② 审批人解析为空**返回 `ApprovalGateResult(decision=EXCEPTION)` 而不是抛异常**（`:196-208` → `_create_exception_result(APPROVER_EMPTY)`）→ AC-18「不放行也不静默卡死」的落点在调用方的显式分支 | E1 §1.5 |
| **K3** | **outbox 判成败只看是否抛异常**（`worker/approval/tasks.py:111-120`；`approval_outbox_service.py:13-76`）：`on_approved` 正常返回 = 成功 → instance=`executed`；抛异常 = 失败 → instance=`execute_failed` + 建异常 + 通知管理员。**反例勿抄**：`knowledge_space_subscribe_scenario_handler.py:122-126` 的 `return {"status":"missing_membership"}` 是 skill §6 明令禁止的假成功。**但"待上线（资源不足 / 上线失败）"是产品定义的终态、不是失败**（AC-31），它必须**正常返回**——见坑 10 的边界判据 | skill §6；E1 §1.5 |
| **K4** | **三项阻塞前置是对存量代码的行为变更，不是新增**：`approver_resolver.py:63-74` 的 `tenant_admin` 分支今天解析的是**全站系统超管**（`UserRoleDao.aget_roles_user([AdminRole])`，注释自认 "pragmatic approximation"），改成真租户管理员后**对一切使用该来源的既有场景与人工配置立即生效**（AC-21）→ **release note 必须显著声明**；`TenantAdminService.list_tenant_admins` 对 Root 租户**恒返回 `[]` 是显式设计**（`tenant_admin_service.py:95-96`，注释 `:10-12` 说明是 INV-T3 的设计），114 单租户形态**必然**命中「回退平台超管」分支；`_init_default_approval_scenarios` 今天**六处硬编码 `DEFAULT_TENANT_ID`**（`init_data.py:365/374/384/402/414/425`）且新建租户有**两条**路径 | E1 §1.2–1.4；PRD-1 §3.3 锚点表 GOV-02 三行 |
| **K5** | **快照体一律走 MinIO 引用、库里只存对象键（C2 加强）**：代码包 tar、构建产物、生产数据快照**绝不入库**。反面教训 `FlowVersion.data` 全量 JSON 入库在 DM8 上撑爆 undo（memory `project_linsight_dm8_history_write_amplification`）。桶与键布局**已由 F054 design 定死、F055 沿用不另起**：独立桶 `bisheng-apps`（不挂 nginx location、不设匿名策略），代码快照 `apps/{app_id}/versions/{version_id}/code.tar.gz`。**真正的风险在 nginx 不在 MinIO 策略**：`src/frontend/nginx.conf:49` 的 `location ~ ^(/workspace/bisheng|bisheng|tmp-dir)/` 把公共桶任意 key 匿名转发出去 | F054 design **D10「per-app SQLite …… 快照走 `.backup` 后 tar 上独立 bucket」**（约 `:266-273`，桶与键布局在该决策末段；**不是 D8**，D8 是领域对象决策）；E1 §2.2 |
| **K6** | **多租户（C3）的两处非常规**：① `app_deployment` 带 `tenant_id`、登记进 `core/database/tenant_filter.py:39 _TENANT_AWARE_MODEL_MODULES` 走自动过滤；② **`resource_tier` 是平台级跨租户实体、无 `tenant_id` 列**（spec AC-44），模型定义落 `database/models/resource_tier.py`（**两模块共读，见 C1 的双向依赖说明**），登记进该元组**只为保证 metadata 被 import**，不代表受自动过滤——这与 F054 的 `app_version` 同形（F054 K5 ②）。另：租户过滤监听器**只拦 SELECT**（`tenant_filter.py:164-165`），管线里任何批量 UPDATE / DELETE 必须手写租户条件 | C3；memory `reference_tenant_filter_in_list_trap` |
| **K7** | **AppManifest（`bisheng-app.yaml` 对外形态）是本 Feature 拥有的对外契约**（release-contract 表 1）：F053 CLI 按它打包与本地必填校验、F054 运行时按它取 `runtime` / `port` / `tier` / `egress.domains`，**三方不各自定义**。权威 schema 只有一份（§4.2 ③）；**CLI 不复制 schema、也不复制密钥扫描规则集**（F053 决议-2：同一规则集分两处必漂移），CLI 侧只做"必填项存在"级快速失败 | release-contract 表 1；F053 spec §3 / 决议-2 |
| **K8** | **`deploy` / `logs` 的服务端权限判定复用 F049 底座、不自建**：新 router 每个端点挂 `Depends(open_api_subject("app:manage"))`（`open_api/api/dependencies.py:103-115`，docstring 逐字点名 F053 / F055）；owner 判定读 `OpenApiPrincipal.resource_owner_user_id`（`open_api/domain/context.py:39`）**不是** `subject_user_id`；`app:manage` 已注册（`open_api/domain/scopes.py:177-184`，`requires_open_platform=True`）；`delegate` 位在 F049 期**根本发不出来**（`scopes.py:186-195` 只留 `DELEGATE_SCOPE_CODE` 用于精确报错 26024）→ AC-04「持 delegate 一律拒」在本期天然成立，F055 只需对齐错误文案（INV-31） | E1 §2.4；F049 design §6.1 |
| **K9** | **错误码段 = 162**（`app_factory` 家族第二段），**分配已完成、不需要 F055 再去"落定"**：`release-contract.md` 的「已分配模块编码」表已写死 `162 = app_factory · F055 段`（F054 落码时一并写入），`docs/constitution.md` C5 的 `12x–18x` 行与 `161–164 = app_factory` 段落也已登记 **162 = F055 (publish pipeline)**。→ **落码时真正要做的只剩两件**：① 新建 `common/errcode/app_publish.py`（**勿写进 F054 的 `app_factory.py`**）② `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json` 三语各一条（生成物勿手改，CI `pnpm check-i18n`）。⚠️ **不要去"修正"上游那两张表**——它们已经是对的，改动只会制造 diff 噪声 | C5；release-contract「已分配模块编码」；E1 §3.4 |
| **K10** | **部署配置项一律挂进 F054 已开的 `settings.app_runtime` 块，不再开顶层键**：档位出厂规格默认值（`default_tiers`）、预览实例超时（决议-5，7 天，`preview_ttl_days`）、**包体与解包三闸**（`max_package_mb` / `max_unpacked_mb` / `max_package_entries`，**本期就做、不是"将来"**，见 D2 与 F053 AC-32）。⚠️ `load_settings_from_yaml`（`common/services/config_service.py:91-107`，`:105-107` 对未知顶层键直接 `raise KeyError`）→ **必须先发代码、再改 `config.yaml`、再重启**，顺序反了直接拒启 | F054 design K12；E1 §3.2 |
| **K11** | **前端三条硬约束**：① platform 的 react-query v3 被 eslint 冻结（`platform/eslint.config.mjs:45`）→ 发布面用 `platform/src/util/hook.ts:215 useTable` 或裸 `useState+useEffect`；② platform 拦截器对 `403/404` **整页跳转 `/403`**（`platform/src/controllers/request.ts:160-166`）→ 发布面只读接口对无权者**不能回 403/404**，用业务码或 `silent: true`；③ client 审批弹窗 `DialogContent` 宽度上限 **800px**（`ApprovalCenterDialog.tsx:392` `md:max-w-[800px] md:h-[80vh]`）→ 审读视图（左文件树 + 右只读代码 + 4 tab）塞不进去，是 D14 的尺寸级前提 | E2 §0-4 / §3.2 |
| **K12** | **114 是单租户形态 + 存量环境**：`ROOT_TENANT_ID` 场景下 `list_tenant_admins` 恒空 → 演示必然走「回退平台超管」；deploy.sh 一条命令部署（memory `reference_remote_dev`）；**审批 outbox 走默认 `celery` 队列**（`worker/config.py` 不为 `bisheng.worker.approval.*` 配路由），部署时必须有 worker 消费默认队列，否则审批通过后业务不执行（skill §6 的 ⚠️） | `mvp-114-path.md` §3；skill §6 |

**Constitution Check（自查）**：

- **C1（DDD 分层）**：新模块 `bisheng/app_publish/` 按 `api/ + domain/{services,schemas,models}` 分层；`api/endpoints/*` 一律经 domain service、不直接 import `database/models`（RULE-3）；不跨模块 import 其他模块的 `api/`（RULE-5）。
  - **`app_publish` → `app_runtime` 的服务调用是单向的**（F055 调 F054 的 `AppStateService` / `AppMetaService` / `orchestrator_client`），反向由 F054 的 `lifecycle_hooks` 回调解耦（F054 §4.1-C）。
  - ⚠️ **这个方向没有机器护栏，别以为 arch-guard 管**：`scripts/arch-guard.sh` 的 RULE-5 只匹配 `/api/endpoints/` 与 `/api/router.py`（`:71-82`），**对 domain 层的跨模块 import 一概不检查**；RULE-2/3/4 也都不管模块间方向。方向靠 §6.1 / §6.2 的契约表 + code review 维持，**不是靠 hook**。
  - ⚠️ **且方向本身不是纯单向**：`ResourceTier` 实体归 F055、F054 只读（release-contract 表 1；F054 design D11「表存在时以表为准」）→ 若把它放进 `app_publish/domain/models/`，`app_runtime` 就必须 import `app_publish` 的 domain，双向依赖当场成立。**故 `ResourceTier` 的模型定义落 `database/models/resource_tier.py`、由两个模块共读**（业务逻辑仍归 F055 的 `ResourceTierService`），D16 与 §4.3 已同步。
- **C2（双 DB）**：新表 `resource_tier` / `app_deployment` 须 MySQL + DM8 双方言可建；`manifest` / `failure` / `scan_result` 用 `JsonType`（`core/database/dialect_helpers.py:196`，DM8 落 CLOB），**禁 `JSON_EXTRACT` / `JSON_CONTAINS`**；凡需 SQL 筛选的（`stage` / `status` / `tier_code` / `enabled`）一律拆显式列。快照体见 K5。Alembic revision DDL-only、`down_revision` 取 `uv run alembic heads` 唯一头。
- **C3（多租户）**：见 K6。审批相关读写全部经审批模块既有服务（它们已在租户上下文内）；**Celery worker 里的租户上下文经 header 自动透传**（`worker/tenant_context.py:63-90`），`on_approved` 内**不需要**手动 `set_current_tenant_id`。
- **C4（权限）**：应用侧判权一律经 F054 已注册的 `app` 资源类型与 `permission/application/business_authorization.py` 三个函数；**`deploy` / `logs` / 撤回 / 手动上线的 owner-only 是业务规则前置拦截**（管理员在权限运行时被身份短路放行，`permission_action_service.py:372-385`），不能靠权限运行时——spec §3 已声明。开放面权限位判定经 F049 `Depends`，不自建。
- **C5（错误码）**：见 K9。
- **C6（无硬编码密钥）**：密钥扫描规则集里的 `bs-sak-` 模式**引用 `open_api/domain/models/api_credential.py:35-38` 的 `KEY_PREFIX` / `KEY_SECRET_LENGTH` 常量拼接**，不硬编码字面量；扫描结果**绝不含命中的密钥值本身**（AC-10）。
- **C7（前端 store 不直连 HTTP）**：platform 发布面经 `controllers/API/hostedApp.ts`（F054 已建）扩展，client 审批弹窗经 `client/src/api/approval.ts`；两边都不 import axios。

---

## 3. 方案对比与选定

> 每条 3 段：备选 / 选定 / 原因 + **何时该重新考虑**。这里是"想当然会走但被否决"的路的登记处。

### D1：管线编排形态 = 同步接收端点 + Celery 异步阶段机 + `app_deployment` 作为进度载体

- **备选**：
  - A. **同步端点内一条龙**（HTTP 请求里跑完解包 → 校验 → 构建 → 探活 → 扫描 → 审批单）— 优点：无异步状态、CLI 只等一次；缺点：构建是**分钟级**（`docker build` 装 pip 依赖），撞 nginx `proxy_read_timeout` 与网关超时；CLI 拿不到分阶段输出（F053 AC-31a 要求"按阶段依次输出"）；一个长请求占死一个 uvicorn worker
  - B. **纯 Celery**（接收也异步，端点只收包落盘就返回）— 缺点：包大小 / manifest 缺失这类**秒级可判**的错误也要走一圈队列才告诉 CLI，`deploy` 的第一手反馈从 200ms 退化到数秒；且失败时用户拿到的是"任务已提交"而非"你少写了 `runtime`"
  - C. **同步端点做秒级前段（鉴权 → 大小闸 → 落 MinIO → 解包安全闸 → manifest 校验 → 在途/待上线闸）+ Celery 做分钟级后段（扫描 → 构建 → 探活 → 版本记录 → 审批单）**（选定）
  - D. **状态机驱动 + Beat 轮询推进**（`app_deployment.stage` 由定时任务推进）— 缺点：仓内无先例、引入 Beat 依赖（114 上 Beat 曾因未起而让频道信息源永不同步，memory `project_channel_information_sync_tenant_fix`），且 stage 推进本就是线性的、不需要调度器
- **选定**：**C**。
  - **进度载体 = 新表 `app_deployment`（一次发布尝试）**，不复用 `app_version`：AC-02 / 决议-9 要求"预检或扫描失败的提交不进版本列表"，而 F054 已把 `app_version` 定死为**只 INSERT 不 UPDATE**（唯一例外是 `terminal_state` 单列，由 F055 写）——把失败尝试塞进版本表既违反前者、又要给 `terminal_state` 加"预检失败"这类过程值。
  - **CLI 轮询**：`GET /api/v2/apps/deployments/{deployment_id}`（同一把 `app:manage` 依赖），返回 `{stage, status, failure{stage,code,message,details,hints}, app_id, version_no, approval{...}, app_state}`。CLI 默认在"审批单生成"后返回（F053 AC-31b），`--wait` 继续轮到审批终态与上线结果。轮询间隔由 CLI 定（建议 2s，构建期退避到 5s），服务端不做长轮询（长轮询会把 uvicorn worker 又占回去）。
  - **队列**：**走默认 `celery` 队列**（与审批 outbox 同队列，114 已有 default worker 在跑），**不新建队列**——新队列意味着 114 与 compose 都要加 worker 单元，而 MVP 期并发发布量是个位数。任务 `bisheng.worker.app_publish.run_pipeline(deployment_id)`。
  - **阶段与状态**：`stage ∈ {received, secret_scan, precheck_manifest, precheck_build, precheck_probe, version_recorded, approval_created, approved, publishing, online, pending_online}`；`status ∈ {running, waiting_approval, succeeded, failed}`。每次阶段推进 = 一次 `app_deployment` 单行 UPDATE + 一条审计（`app.release.*`）。
- **原因**：C 是唯一同时满足「秒级错误秒级回」「分钟级阶段不占连接」「CLI 能分阶段输出」的落点，且不引入新队列 / 新调度器。A 被超时与 F053 AC-31a 证伪；B 把最常见的错误（manifest 少字段）反馈路径拉长；D 属为线性流程引调度器。
- **何时该重新考虑**：单机并发发布 > 2 或构建把默认队列的审批 outbox 饿死（表现：审批通过后业务执行延迟数分钟）→ 拆独立队列 `app_publish` 并在部署增量里加 worker 单元；或 F059 k8s 形态下构建下沉到集群 Job（那时后段变成"提交 Job + 观察"，阶段机不变）。

### D2：应用包接收与快照存储 = `/api/v2` 新 router + 首发即建草稿应用 + 键先于版本行

- **备选（端点位置）**：
  - A. 挂 `/api/v1` 并复用登录态 — **不成立**：CLI 持的是服务账号密钥（`Bearer bs-sak-…`），v1 走 cookie / JWT 登录态
  - B. 塞进既有 `/api/v2` 共享 router — 缺点：F049 `api/router.py:114-126` 的共享 router 依赖提升尚在 T040 之后，塞进去会与 F049 的接入节奏耦合
  - C. **F055 自建 router（`/api/v2/apps`），每个端点挂 `Depends(open_api_subject("app:manage"))`**（选定）
- **选定端点位置**：**C**——这正是 F049 `dependencies.py:103-115` 的 docstring 逐字预留的用法（*"For routers that F053 / F055 add outside the shared /api/v2 router"*）。
- **备选（首发时 App 行何时创建）**：
  - A. **预检通过后与版本记录同事务创建** — 优点：预检失败不留草稿应用；**致命缺点**：构建 RPC 入参是 `(app_id, version_id, runtime, code_object_key)`（F054 §4.2 ①）、MinIO 键前缀是 `apps/{app_id}/…`——预检期根本没有 app_id，只能造一个占位 id 污染编排器期望态与对象键
  - B. **接收成功（manifest 基本校验通过）后立即创建草稿应用**（选定）— 代价：连续预检失败会在构建页留下草稿应用
  - C. 用 `deployment_id` 当临时 app_id、通过后改名 — 缺点：MinIO 键要搬家、manager 的期望态与容器 label 要改写，纯属自找
- **选定**：**B**。理由：① 草稿态本就是"存在但没上过线"的态（F054 状态机第一格），首发被驳回也保持草稿态（AC-33）——预检失败留一个草稿应用与之同构；② CLI 会把 app_id 随项目保存（F053 AC-33），**重试 deploy 复用同一个 app_id**，不会每次新建；③ 构建 / 探活 / 对象键 / 审计对象全都要真 app_id。
  - **⚠️ 跨 Feature 缺口**：F054 design §4.2 ② 只列了五个状态动作 + `stage_version` + `update_meta`，**没有"创建草稿应用"的服务方法**，而 release-contract 已定「本册唯一创建路径 = CLI 首发」。→ 需 F054 补 `AppProvisionService.create_draft(name, slug, owner_user_id, tenant_id) -> app_id`（写 `app` 行 state=草稿 + 经 F048 `runtime.authorize_created` 授权 owner + 审计 `app.create` + `slug` 全局唯一冲突 → 16103）。**F055 调它、不直写 `app` 表**（spec 决议-8 的精神）。已登记进 §6.2 与坑 26。
- **对象键与版本 id**：接收时即由平台生成 `version_id`（uuid4），快照**直接写 `apps/{app_id}/versions/{version_id}/code.tar.gz`**（F054 定的键布局）；预检通过后 INSERT `app_version` 复用同一个 id。
  - **被否**：先写 `deployments/{id}/code.tar.gz`、通过后 server-side `copy_object` 到 version 键 — 否决理由：server-side copy 对大对象仍是 MinIO 内部一次完整读写，是**幻觉优化**（memory `project_linsight_skill_object_storage`）；而 version_id 由平台在接收时生成本就自由，没有任何理由推迟。
  - 预检失败留下的对象是**孤儿**（有键无 `app_version` 行）：按 `app_deployment` 的失败记录保留 **7 天**供排障（AC-02「快照临时保留供排障」），到期由清理任务删除。**清理任务不做定时调度**（避免又引 Beat）——挂在下一次同应用 deploy 的接收阶段顺手清（同 `app_id` 前缀下 `terminal_state IS NULL ∧ 无 deployment 引用 ∧ 超 7 天` 的键）。
- **大小与解包闸**（照 `linsight/domain/services/skill_store.py:34/40` 的双限额形态；**代码常量给默认值、部署配置可覆盖，不进 DB 热配置**）：
  - 默认值：`MAX_PACKAGE_MB = 50`（上传字节，超 → 16201）· `MAX_UNPACKED_MB = 200`（解包后总大小，tar bomb 闸）· `MAX_PACKAGE_ENTRIES = 20000`（条目数闸，防海量小文件）。
  - **三者均可被 `settings.app_runtime.{max_package_mb, max_unpacked_mb, max_package_entries}` 覆盖**（K10；**本期就做**）——理由不是"将来可能要调"，而是 **F053 AC-32 逐字要求 CLI 在上传前按「部署配置的上限」拒绝并提示当前体量**。上限若只是后端常量，CLI 只能硬编码 50 MiB，那正是 K7「同一契约分两处必漂移」自己反对的形态。
  - **给 CLI 的取值途径（新增 Outgoing 契约）**：`GET /api/v2/apps/deploy-limits`（同一把 `app:manage` 依赖）→ `{max_package_mb, max_unpacked_mb, max_package_entries}`。CLI 在 `deploy` 打包后、上传前取一次（可按 profile 缓存），**取不到时退化为直接上传、由服务端 16201 兜底**（不让一个可选的软校验挡死发布）。已登记 §4.2 ① / §6.1，并在 §8 登记「回写 F053 spec AC-32 的取值口径」。
  - `UploadFile` **落临时盘后用 `put_object(file=Path(...))`**（走 `fput_object` + `asyncio.to_thread`，`minio_storage.py:359-407`），**绝不 `await file.read()` 整包进内存**。
  - **解包安全闸**：照抄 `skill_store.py:171-176 _safe_rel_path`（拒绝绝对路径与 `..` 穿越），tar 额外拒 **符号链接 / 硬链接 / 设备文件 / FIFO**（`TarInfo.issym() / islnk() / isdev() / isfifo()`）——zip 先例只需防前两者，tar 多这四类（坑 15）。
- **何时该重新考虑**：包体上限被真实项目顶穿（表现：CLI 反复报 16201 且 `.gitignore` 已清干净）→ 调 `settings.app_runtime.max_package_mb`（K10 的先发代码后改 YAML 顺序），**这是运维动作不是改码**；或引入分片 / 断点续传（那时接收端点要改成两段式 init + parts，`deploy-limits` 要加 `chunk_size`）。

### D3：`bisheng-app.yaml` 形态与校验 = pydantic v2 `extra='forbid'` + `manifest_version` 兼容闸

- **备选（校验库）**：
  - A. **jsonschema**（新依赖）— 优点：schema 可直接发给 CLI 与技能包做本地校验；缺点：新依赖、错误信息对非技术使用者更差
  - B. **手写校验函数** — 缺点：必填 / 类型 / 枚举 / 嵌套四类校验全手写，错误结构不统一，AC-11 的"可机读 + 可读"要自己发明
  - C. **pydantic v2 模型 + `extra='forbid'`**（选定）
- **选定**：**C**。零新依赖（全仓栈）；`ValidationError.errors()` 天然产出 `{loc, msg, type}` 三元组 → **直接映射 AC-11 的双形态**：machine = `{stage:'precheck_manifest', code:16221, details:[{field:'runtime', reason:'missing'}]}`，human = 按 `loc` 拼的中文句子 + 改造指引 `hints`。
- **形态**（权威定义在 `app_publish/domain/schemas/app_manifest.py`，§4.2 ③ 是字段表）：
  - **必填**：`name`（1–64）· `runtime`（枚举，取值来自 runtime-manager `GET /v1/runtime/status.supported_runtimes`，MVP 期实际只有 `python3.11`）· `port`（1–65535）
  - **可选**：`description` · `icon`（包内相对路径）· `slug`（未声明由平台按名称生成，F054 AC-08）· `tier`（默认 `light`）· `capabilities{models[],knowledge_bases[]}` · `database.tables[]` · `egress.domains[]` · `manifest_version`（默认 `1`）
  - **`extra='forbid'`**：字段名拼错立刻被拒并给出"未知字段 X，你是不是想写 Y"（Levenshtein 近似建议）。向前兼容方向是"平台新增可选字段、老 CLI 不写"，`forbid` 不阻碍它；反方向（新 CLI 写了老平台不认的字段）由 `manifest_version` 闸给出明确的"请升级平台"而不是"未知字段"。
  - **YAML 解析用 `yaml.safe_load`**（禁 `full_load` / `unsafe_load`——`!!python/object` 是 RCE）；文件必须在包根 `bisheng-app.yaml`，缺失 → 16203。
- **F053 / F054 如何消费**：F054 只读 `runtime` / `port` / `tier` / `egress.domains`（F054 §4.2 ④）；F053 是**独立 CLI 包、不能 import backend**，故 CLI 只做"三个必填项存在 + YAML 可解析"级快速失败，**权威校验恒在服务端**（K7 / F053 决议-2 同源）。
- **结构演进（`database.tables[]`）本轮后置**：MVP 期该字段**允许声明但不建表、不做破坏性变更检测**——预检对非空 `database.tables[]` 给出 `hints`「本环境暂不由平台建表，请用 `BISHENG_APP_DB_URL` 自行建表」而**不拒绝**（应用自己在 SQLite 里 `CREATE TABLE IF NOT EXISTS` 完全可行，拒绝反而挡死剧本）。改 / 删列的显式确认（AC-09 / AC-42）与迁移前生产数据快照随后置波次，落点 = 预检新增 `precheck_schema` 阶段 + `POST /api/v2/apps/deploy` 的 `confirm_schema_change` 参数（端点参数**本期就留**，避免 CLI 侧改两次）。
- **何时该重新考虑**：出现第二个消费方需要机器可读的 schema（如技能包要内嵌 JSON Schema 供 agent 自校验）→ 用 `TypeAdapter.json_schema()` 从同一个 pydantic 模型导出，仍不引 jsonschema 运行时依赖；或 manifest 需要表达条件依赖（如 `runtime=node20` 时 `port` 默认值不同）→ 那时才值得上 discriminated union。

### D4：托管预检编排 = 线性 fail-fast 阶段机，失败原因恒为 `{stage, code, message, details, hints}` 五元组

- **备选**：
  - A. **全量校验后一次性报所有错** — 优点：一轮修完；缺点：构建 / 探活是分钟级且互相依赖（manifest 不合法就没法构建），"全量"物理上做不到，只能对 manifest 层做
  - B. **线性 fail-fast**（选定）：manifest 层内部一次性报全（pydantic 天然如此），跨阶段 fail-fast
  - C. 并行跑构建与扫描 — 缺点：扫描命中即阻断，并行等于白烧一次构建（见 D5）
- **选定**：**B**。阶段顺序与落点：

  | 序 | `stage` | 段 | 做什么 | 失败码 |
  |---|---|---|---|---|
  | 1 | `precheck_manifest` | **同步** | YAML 解析 + pydantic 校验（D3） | 16221 / 16203 |
  | 2 | `precheck_manifest` | **同步** | **本地可判的引用校验**：`runtime` ∈ **本地枚举常量**（`SUPPORTED_RUNTIMES`）· `tier` 存在且 `enabled`（查本地 `resource_tier` 表）· 能力声明格式 · 密钥引用出现即拒 | 16222 / 16223 / 16224 / 16230 |
  | 3 | `secret_scan` | 异步 | 密钥扫描（D5）——**排在构建之前**：扫描是秒级正则、构建是分钟级 + 一次容量闸，命中即终止的前提下先构建等于每次命中白烧一次构建 | 16241 |
  | 4 | `precheck_build` | 异步 | 起手先向 manager **复核 `runtime`**（`GET /v1/runtime/status.supported_runtimes`，本地枚举与 manager 支持集取交）→ `POST /v1/intents/build` → 轮询 `GET /v1/builds/{id}`（manager 侧阶段 `fetch_source/render_dockerfile/docker_build/probe`） | 16222 / 16226 / 16227（含 manager 回的 `stage/message/tail`） |
  | 5 | `precheck_probe` | 异步 | `POST /v1/intents/probe`（临时形态：`image_ref + env + port + health`，不占实例名额） | 16228 |

  - **⚠️ 第 2 步为什么不问 manager（对 D1 选 C 的兑现）**：`precheck_manifest` 整块在**同步端点内**（§4.1 ①，D1「秒级错误秒级回」）。若在这里发 `GET /v1/runtime/status`，manager 不可达就会把 `POST /deploy` 变成一个挂在 RPC 超时上的请求——秒级反馈当场失效。→ **同步段只做本地可判的校验**（枚举常量 + 本地表查询），`runtime` 与 manager 支持集的复核**下沉到异步段 `precheck_build` 起手**。代价：本地枚举与 manager 模板集漂移时，错的 `runtime` 要多等一次进队列才报 16222——可接受，且 F054 加模板时两处同批改（§6.2 已登记该风险）。
  - **AC-08（依赖托管契约外的中间件 / 白名单外外网）怎么落**：本轮**不做静态依赖分析**（读 `requirements.txt` 猜"是不是连了 MySQL"是幻觉级判据）——判据下沉为**启动探活失败**（应用连不上自带的 MySQL 就起不来 → 16228），错误 `hints` 里给出托管运行契约的改造指引（"平台不提供自带数据库 / 消息队列 / 缓存；数据请改接 `BISHENG_APP_DB_URL`"）。出站白名单的实际拦截随 F054 D12 后置，本期 `egress.domains` 只做格式校验。
  - **容量不足也是预检失败**：构建同样过容量闸（F054 D11 `purpose=build`），不足 → `stage=precheck_build`、`code=`**`16226`**（"运行环境容量不足"，**不点名 compose/k8s 形态**，ui-demo §3-6）。
    - ⚠️ **别写成 16225**：`16225` 是「审批场景未启用」（D6 的 Gate 抛异常落码），两者的 CLI 处置完全不同（等资源 vs 平台没 seed 审批场景）。错误码是 §6.1 登记的 Outgoing 契约（F053 按 `code` 分支、三语 `api_errors` 各一条文案），**同码双义 = C5 违规 + 必然写错一条文案**。
- **失败原因结构（AC-11 的唯一形态）**：`failure = {stage, code, message, details, hints[]}`。`code` + `stage` + `details` 是机读面（CLI 与本地 agent 据此自动修）、`message` + `hints` 是人读面。**同一结构同时出现在三处**：CLI 轮询返回、发布面审批状态区、`app_deployment.failure` 落库（JsonType）。
- **原因**：spec AC-07 的"依次校验"本就是线性语义；把 machine+human 收成一个五元组而不是两个字段，是因为 F053 AC-35 与 F055 AC-11 是同一份数据的两个视图——分成两套会立刻漂移。
- **何时该重新考虑**：预检阶段数超过 8 个或出现分支（如 `runtime=static` 跳过构建）→ 阶段表要升级为带前置条件的有向图；或本地 agent 反馈"`hints` 修不动"（表现：同一 `code` 反复失败 3 次以上）→ 那时把 `hints` 从静态文案升级为按 `details` 生成的定向指引。

### D5：密钥扫描规则集 = 常量规则表 + 输出永不含值（**扫描排在构建之前，2026-08-17 已拍板**）

- **备选（规则引擎）**：
  - A. 引入 `detect-secrets` / `gitleaks` — 缺点：全仓**零先例**（`grep -rn "detect-secrets|gitleaks|trufflehog"` 零命中）、新增二进制或 Python 依赖、规则集不可控且大量误报，与"与平台内发布同一规则集"（AC-10）的自持要求相冲突
  - B. 复用 `sensitive_word/domain/services/ac_automaton.py`（Aho-Corasick）— **不适用**：它是**字面词多模匹配**，不支持正则；但它的「规则集 → 命中项（含位置）上报」接口形状可参考
  - C. **模块常量规则表 + `re` 编译**（选定），形态同 `open_api/domain/scopes.py:66-185 OPEN_API_SCOPES`
- **选定**：**C**。`SECRET_SCAN_RULES: tuple[SecretRule, ...]`，`SecretRule(rule_id, name_i18n_key, pattern: re.Pattern, description_i18n_key)`，放 `app_publish/domain/services/secret_scanner.py`。首批规则：
  - `bs_sak`：**引 `api_credential.KEY_PREFIX` / `KEY_SECRET_LENGTH` 拼**（C6），即 `\bbs-sak-[A-Za-z0-9_-]{43}\b`——**不硬编码字面量**，F049 改前缀时这条自动跟随
  - `aws_akid`（`\bAKIA[0-9A-Z]{16}\b`）· `openai_sk`（`\bsk-[A-Za-z0-9]{20,}\b`）· `private_key_pem`（`-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----`）· `db_conn_string`（`(mysql|postgresql|postgres|mongodb(\+srv)?|redis)://[^\s:@/]+:[^\s@/]+@`，**用户名密码都在串里才算命中**——只有 host 的连接串是正常配置）· `generic_high_entropy`（`(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*["']([^"'\s]{20,})["']`，且值不匹配占位符白名单 `^(xxx+|your[_-]|<.*>|\$\{|change[_-]?me|example)`）
- **扫描范围与性能闸**：解包后逐文件；跳过 `.git/` · `node_modules/` · `venv/` · `__pycache__/` · `dist/` · `build/`；**二进制嗅探**（前 8KB 含 `\x00` 即跳过）；单文件 > **1 MiB** 跳过并在结果里标 `skipped`（不静默——大文件被跳过必须可见，否则等于假通过）。
- **输出（AC-10 硬承诺）**：`hits: [{rule_id, name_i18n_key, file, line}]`——**连脱敏后的值都不给**。理由：任何"前 4 后 4"式脱敏在低熵密钥上等于泄漏，而定位一个密钥有 `file:line` 已经足够。
- **✅ 扫描执行位置 = 构建之前（2026-08-17 拍板，此前挂 ★ 待确认）**：
  - **定案**：`PIPELINE_STAGES` 顺序为 `secret_scan → precheck_build → precheck_probe`，CLI 输出 `manifest → 扫描 → 构建 → 探活 → 审批单`。
  - **理由**：①扫描是纯正则、秒级，构建是分钟级 + 一次容量闸占用（114 上尤其贵）——命中即终止的前提下，先构建再扫描等于**每一次命中都白烧一次构建**；②扫描的输入是**解包后的源码根**（`run_pipeline` 在阶段循环之前就已 `_materialise_snapshot`），**不依赖任何构建产物**，所以这只是一次元组重排，没有技术代价；③PRD-1 DEV-04 列的四步是**逻辑分组**（说清"要过哪几道门"），AC 层真正约束的是「两道门都过、任一失败都不进审批」，顺序未被写成契约。
  - **代价（如实记）**：这与 F055 AC-01 与 F053 AC-31a 的**字面表述**相悖，两份 spec 已在同一次改动里同批订正——这是对 PRD 字面顺序的一处**自觉偏离**，按 SDD-Guide 偏离再确认规则登记在案（裁决记录见 `053-dev-cli-skills/spec.md` 决议-13 与 `mvp-114-path.md` §5）。
  - **同批已改的四处**：F055 spec AC-01 顺序措辞 · F053 spec AC-31a 阶段序 · 本文 D4 阶段表与 §4.1 数据流 · `publish_pipeline_service.PIPELINE_STAGES` 与其顺序断言单测。
  - **CLI 侧不跟着写死**：F053 的 `STAGE_LABELS` 是**无序 dict**、只按服务端到达顺序输出、未知 stage 原样打印。顺序既然改过一次就可能再改，把服务端的编排决策复制到客户端就是下一次返工的来源。
  - **何时该重新考虑**：若扫描对象从源码包改成**镜像层**（扫构建产物里的密钥），它就真的依赖构建了，顺序必须换回去。
- **测试即验收**：`test/app_publish/test_secret_rules.py` 遍历规则表，每条规则一个正样本（必须命中）+ 一个反样本（必须不命中）+ 断言输出结构里**不含样本密钥子串**——AC-10「规则集内样本 100% 被阻断」由这个遍历式单测直接承载。
- **何时该重新考虑**：误报率高到开发者开始想办法绕（表现：`generic_high_entropy` 被反复投诉）→ 引入**行级抑制注释**（`# bisheng:allow-secret <理由>`）并把抑制计入审计，而不是放宽规则；或平台内发布（PRD-2）接入后规则需要按来源分档 → 那时 `SecretRule` 加 `applies_to` 字段。

### D6：版本记录写入时点与终态标注 = 「先 Gate 后 INSERT」+ 过程态派生显示

- **备选（写入时点）**：
  - A. **接收即落版本行**（`status='precheck'`）— 与 AC-02 / 决议-9「预检失败不进版本列表」直接冲突，且要给 `app_version` 加过程状态列（F054 定死只 INSERT + `terminal_state` 单列例外）
  - B. **预检 + 扫描通过即 INSERT，随后调 Gate**（顺序 INSERT → Gate）— **致命缺陷**：Gate 会抛（场景未 seed → `ApprovalScenarioDisabledError`，`approval_gate.py:109-111`；路由缺失 → EXCEPTION），此时版本行已写且 **AC-40 规定它不可删除** → 版本列表里留下一条永远没有终态、也没有审批单的僵尸版本
  - C. **先调 Gate 拿到实例（或 EXCEPTION）、再 INSERT `app_version` + 回写 `app_deployment`**（选定）
- **选定**：**C**。
  - `business_key = deployment_id`（一次发布尝试 = 一个审批单），`applicant_user_id = app.owner_user_id`（D7）。
  - Gate 返回 `PENDING` **或** `EXCEPTION`（approver_empty）都算"已进入审批流"→ 照落版本记录（AC-18 要求不放行也不卡死，异常态下版本记录必须存在，否则管理员处理完异常后没有对象可上线）。Gate **抛异常**（场景未启用 / 未注册 handler）→ `app_deployment` 置 `failed(stage='approval_created', code=16225)`、**不落版本**（`16225` **专指「审批场景未启用」**；构建期容量不足是 `16226`，两者不可同码，D4）。
  - **⚠️ Gate 自带写库与 commit**（`approval_gate.py` 用自己的 session），因此它**不能与 `app_version` 的 INSERT 放进同一个 SQLModel 事务**。补偿口径：Gate 成功而随后的 INSERT 失败 → 立即调 `cancel_instance_by_business(...)`（D10）取消刚建的审批单 + `app_deployment` 置 failed + 审计 `app.release.rollback`。这是一个**显式的两阶段补偿**，不是"假装它是原子的"。
- **终态标注（决议-6 的落地）**：`app_version.terminal_state` 只有 F054 定的四个取值（`online` / `rejected` / `withdrawn` / `NULL`），**F055 不给它加过程值**。
  - 审批通过 + 上线成功 → `online`；驳回 → `rejected`；撤回 → `withdrawn`；**应用删除致取消 → 保持 `NULL`**（应用整体已删，版本列表不可见，不需要第五个取值）。
  - **「待上线」是派生显示不是列值**：读侧按 `terminal_state IS NULL ∧ app.pending_version_id == version.id` → 显示「待上线」；`terminal_state IS NULL ∧ 存在在途审批单` → 显示「待审」。这样两条正交状态线（版本终态线 / 应用可用性线，§3.0.2）在库里也保持正交。
  - **手动上线成功 → `terminal_state` 由 NULL 改 `online`，不产生新版本记录**（决议-6）。这是 `app_version` 唯一被 UPDATE 的列，写入方只有 F055 的 `VersionService.mark_terminal_state()` 一个函数（F054 §4.2 已授权此例外）。
- **版本号**：`version_no = SELECT MAX(version_no)+1 WHERE app_id=?`，在 INSERT 的同一事务里取，并靠 `UNIQUE(app_id, version_no)` 兜并发（AC-03 已经把同应用并发提交挡在前面，唯一约束是第二道闸）。`kind = 'initial'`（该 app 首条）/ `'iteration'`。
- **何时该重新考虑**：PRD-2 引入平台内造应用的草稿版本语义（则 `terminal_state` 要扩、"只 INSERT"约束要重审，F054 D8 已同步登记）；或出现"版本可被物理清理"的合规诉求（那时 AC-40 本身要先改）。

### D7：审批场景接入 = `app_publish_request` 四件套 + 结构化 `build_detail` + 出口过滤申请人

- **备选（详情载荷形态）**：
  - A. **扁平 key-value**（照既有三场景，`menu_access_handler.py:15-20` 只回 3 个扁平键）— 走 client 通用两列网格 `ApprovalCenterDialog.tsx:696-724`；**装不下 AC-24 的四分区**：数组会被 `Array.isArray(v) ? v.join(", ")` 拍平（`:718`）、对象直接变 `[object Object]`、未映射的 key 原样显示英文键名（`localizeFieldKey :138-150` 只有 8 条硬编码）
  - B. **结构化嵌套 payload + client 按 `scenario_code` 分派自定义面板**（选定）
  - C. 结构化 payload + 后端预渲染成 HTML 片段 — 否决：把渲染责任推给后端，i18n 三语与主题适配全部失守
- **选定**：**B**。`build_detail(req)` 返回结构化载荷（字段表见 §4.2 ④），client 在 `TaskDetailPanel`（`:682`）内按 `detail.scenario_code === 'app_publish_request'` 早分派到新组件 `AppPublishDetailPanel`（D14）。
  - **⚠️ 必须同时给旧渲染路径兜底**：`detail_snapshot` 顶层**再放三个扁平键**（`app_name` / `release_kind_text` / `tier_name`）供未识别该场景的路径显示，并把结构化子树的键（`capabilities` / `visibility_snapshot` / `tier` / `schema_change` 等）加进 `DETAIL_INTERNAL_KEYS`（`ApprovalCenterDialog.tsx:136`）——否则通用网格会把它们渲染成 `[object Object]` 一坨（坑 7）。
- **四件套落点**（K1）：
  1. **preset**：`approval_registry.py:16-44` 加一条
     `ApprovalScenarioPreset(scenario_code='app_publish_request', scenario_name='应用发布', handler_key='app_publish_request', approver_source_types=['department_admin','tenant_admin','direct_user'])`。
     ⚠️ **`handler_key` 是无默认值的必填字段**（`approval/domain/schemas/approval_center_schema.py:38-43`；既有三条 preset 全都传了它，`approval_registry.py:19/30/40`）——漏传会在 `with_default_presets()` 求值时直接 `ValidationError`，**import 期就崩**，不是运行到发布才报。`direct_user` 是为 AC-19「租户管理员可改配审批人」留的。
  2. **Gate 组装**：`app_publish/domain/services/publish_approval_service.py`，照 `channel_service.py:1524-1530` 范式（`ApprovalRegistry.with_default_presets()` → `register_handler(code, handler)` → `ApprovalGate(registry=...)`）。
  3. **runtime handler 工厂分支**：`approval_runtime_handler_factory.py:17-35` 加 `app_publish_request` 分支——**漏加 = 审批通过后应用永远不上线**（`build_runtime_handler` 抛 KeyError → `_record_outbox_task_failure`）。
  4. **seed**：见 D8。
- **Handler**（`app_publish/domain/services/app_publish_scenario_handler.py`，鸭子类型、无 ABC，完整协议见 `knowledge_space_subscribe_scenario_handler.py:55-157`）：
  - `resolve_approvers(node_config, req)`：**必须自己实现并显式转调** `approver_resolver.resolve_approvers_from_sources(...)`（`approval_gate.py:195` 由 handler 自己实现，不转调就是零审批人 → 直接 approver_empty，坑 9）；随后做 **AC-17 的出口过滤**：
    - 候选中含 `req.applicant_user_id` → 过滤掉本人；
    - 过滤后为空 **且** 原候选 == `{applicant}` → **保留本人**（允许自审）并标记本次为自审，由 Gate 调用侧写审计 `app.release.self_approval`（AC-17 强制标注）。
    - **⚠️ 自审标志怎么带回调用侧（AC-17 唯一可实现的落点）**：引擎侧**没有通道**——Gate 只取 `approvers = await handler.resolve_approvers(...)` 一个 `list[int]`（`approval_gate.py:195`），`ApprovalGateResult` 只有 `decision / instance_id / task_ids / exception_type` 四个字段（`approval/domain/schemas/approval_center_schema.py:31-36`），**没有任何字段能承载额外标志**，返回值也塞不进去（类型是 `list[int]`）。→ **走 handler 实例属性**：handler 在 `resolve_approvers` 里置 `self.last_self_approval = True`，`publish_approval_service` 在 `request_or_pass` 返回后读它并写审计。
      - **成立前提（必须写死在实现里）**：**每次发布请求新建一个 handler 实例**——`_build_publish_approval_gate()` 每次调用都 `ApprovalRegistry.with_default_presets()` + `register_handler(...)` + `ApprovalGate(registry=...)`，范式逐字照 `channel/domain/services/channel_service.py:1523-1530`（**引擎本就没有全局单例注册表**，K1 ②）。**绝不可**把 handler 提成模块级单例或缓存复用，否则并发发布之间会串标志。
      - 单测必须覆盖：并发两个发布（一个自审、一个非自审）→ 审计里 `self_approval` 恰好一条且挂在对的 deployment 上。
    - **不改 `approver_resolver`**——自动跳过申请人是本场景的产品规则，塞进公共解析器会污染频道 / 知识空间两个既有场景（那两个场景的 owner 就该收到自己发起的申请）。
  - `build_title(req)` → `「{应用名} · {首发|迭代} 发布审批」`；`build_business_link(req)` → 指向 platform 应用详情页发布 tab。
  - `on_approved(instance_id, payload)` → D9；`on_rejected` / `on_withdrawn` / `on_cancelled` → D10。
- **申请人身份（AC-16 / INV-29）**：`applicant_user_id = app.owner_user_id`（自然人，即密钥所属服务账号的 `resource_owner_user_id`），**不是** `principal.subject_user_id`（服务账号）；`applicant_department_id = UserDepartmentDao.aget_user_primary_department(owner_user_id).department_id`（`database/models/department.py:1377-1388`，**只取主部门、不向上回溯**，正好是 AC-14）。owner 无主部门 → 传 `None` → `department_admin` 来源贡献 0 人（`approver_resolver.py:53-54`）→ 落到租户管理员（AC-14），并在 `detail_snapshot.approver_note` 标注「无部门管理员来源」（AC-16）。
- **首节点通知必须自发**：`approval_gate.py:232-248` 只建 task + 写审计、**不发站内信**，三个既有场景都在自己那侧补发（`channel_service.py:1514-1520` / `knowledge_space_service.py:4214` / `approval_center_service.py:581`）。F055 在 Gate 返回 PENDING 后调 `ApprovalNotificationService.notify_users(..., action_code='approval_task_pending', scenario_code='app_publish_request')`（AC-64）。
- **何时该重新考虑**：出现第二个需要自定义详情面板的场景 → 把 client 的 `scenario_code` 早分派抽成 `SCENARIO_DETAIL_RENDERERS: Record<string, FC>` 注册表（D14 同判据）；或产品要求发布审批走多节点 / 会签 → handler 无需改（引擎已支持 `node_mode` 与顺序流转），只需改 seed 的节点定义。

### D8：三项阻塞前置的修复方案 = 就地改解析器 + 抽公共回退 + seed 参数化并挂两条路径

- **备选（`tenant_admin` 修正范围）**：
  - A. **只对 `app_publish_request` 生效**（在 handler 里绕过公共解析器自己算）— 优点：零爆炸半径；**否决**：spec AC-21 明令「对**一切**使用该来源的既有场景与人工配置同样生效」，且留两套 `tenant_admin` 语义比一次行为变更坏得多（下一个人会踩）
  - B. **就地改 `approver_resolver.py:63-74`，全局生效**（选定）
- **选定**：**B**。三项修复的精确落点：

  | # | 前置 | 落点 | 做法 |
  |---|---|---|---|
  | 1 | `tenant_admin` 改真租户管理员（AC-21） | `approval/domain/services/approver_resolver.py:63-74` | 把 `UserRoleDao.aget_roles_user([AdminRole])` 换成新函数 `resolve_tenant_admin_user_ids(tenant_id)`（下条） |
  | 2 | Root 租户回退平台超管（AC-15） | **新函数** `resolve_tenant_admin_user_ids(tenant_id)`，放 `approval/domain/services/approver_resolver.py` 顶部 | `ids = await TenantAdminService.list_tenant_admins(tenant_id)`；`if not ids and tenant_id == ROOT_TENANT_ID: ids = AdminRole 用户`。**是新写的第二个函数，不是复用既有那个**——理由见下方 ⚠️ |
  | 3 | 新建租户 seed 钩子（AC-20） | `common/init_data.py:342-436` 参数化 + **两条**租户创建路径 | 见下 |

  - **⚠️ 别和 `approval_notification_service.py:122-152 _get_admin_recipient_ids` 合并成一个函数**（本文早期版本要求"抽公共函数两处共用"，**是错的**）：两者语义不同且**不可共用**——
    - 既有那个是**无条件 union**：`AdminRole` 全站超管 **∪** 本租户 `list_tenant_admins`，对**任何**租户都并入超管（`:129-148`，两个 try 各自 `recipient_ids.update(...)`）。它的用途是**审批异常态通知收件人**，"多通知一个超管"是安全的。
    - D8 前置 2 要的是**条件回退**：`list_tenant_admins` 为空 **且** `tenant_id == ROOT_TENANT_ID` 时才落到超管。它的用途是**审批人解析**，多解析出一个人就是多一个能拍板的人。
    - **合并的两种错法都致命**：用无条件 union 做审批人解析 → **每个租户的审批人都并进全站超管**，正是 AC-21 要消灭的那个缺陷；反过来把既有函数改成条件回退 → **悄悄改掉审批异常态的管理员通知收件人**（非 Root 租户从此不再通知超管），是一次没人要求过的行为变更。
    - → **两个函数各自存在**：`_get_admin_recipient_ids`（通知侧，**一行不改**）· `resolve_tenant_admin_user_ids`（审批人解析侧，新增）。真要复用只能复用最内层的"取 `AdminRole` 用户 id"那两行，不值得。
  - **为什么不用 `TenantService._get_tenant_admin_users`**：它是 private、分页上限 100、返回 dict 列表且**含 super_admin**（`tenant_service.py:771/780-790`）。`list_tenant_admins`（`tenant_admin_service.py:90-106`）是干净公共 API、返回 `list[int]`、权限后端异常 `return []`（fail-closed 成空 → 走 approver_empty 异常态，正合 AC-18）；Root 恒空由回退补。PRD-1 §3.3 锚点表也明确要求用前者、并点名"不是 `TenantService`，后者只有 check 型接口，按它实现会绕到「拉租户用户 → 逐个 check」且有分页截断"。
  - **seed 参数化**：`_init_default_approval_scenarios(session)` → `_init_default_approval_scenarios(session, tenant_id)`，六处硬编码 `DEFAULT_TENANT_ID`（`:365/374/384/402/414/425`）改为参数；对外暴露 `seed_approval_scenarios_for_tenant(tenant_id)`（放 `approval/domain/services/approval_seed_service.py`，`init_data` 与租户创建路径都调它）。幂等判据不动：**按 `tenant_id + scenario_code` 存在即 `continue`**（`:362-371`）——这就是 AC-19「平台升级不重置人工改动」的落地。
  - **两条挂钩路径（只挂一条必漏）**：
    - `TenantService.acreate_tenant`（`tenant/domain/services/tenant_service.py:88-157`，管理后台新建租户）——照 **Step 6 `:140-149` `seed_builtin_skills([tenant.id])` 的形状**（`try/except` 包住 + `logger.warning`，注释明说"startup seeding 只覆盖当时存在的租户，没有这一步后建的租户永远拿不到"）；
    - `TenantMountService.mount_child`（`tenant/domain/services/tenant_mount_service.py:158-272`，把部门挂载成子租户，`:231-233` 已调 `acopy_root_builtin_tools_to_tenant`）。
    - ⚠️ `mvp-114-path.md:50` 与 PRD-1 §3.3 锚点表都**只写了 `tenant_mount_service`，口径不全**——`acreate_tenant` 才是管理后台主路径（坑 3）。
  - **新 seed 条目**：`{scenario_code:'app_publish_request', scenario_name:'应用发布', flow/node 名, sources:[{"type":"department_admin"},{"type":"tenant_admin"}]}`，落 5 行（`ApprovalScenario(enabled=True)` → `ApprovalFlowDefinition(is_active=True)` → `ApprovalFlowVersion(version_no=1, is_active=True)` → `ApprovalNodeDefinition(node_order=1, node_mode='or')` → `ApprovalRouteRule(route_type='flow', match_config={})`，**`match_config={}` 就是 catch-all**，`approval_gate.py:443-445` 无 field 直接返回该 route）——单条无条件分支 + 单节点或签，正是 AC-12。既有 seed 只覆盖 channel / knowledge_space 两条，F055 **不顺手扩到 menu_access**（那是另一条产品决策）。
- **原因**：三项都在 PRD-1 §3.3 被标为 ⚠️ 阻塞前置，且都有精确到行的现状证据；B 的爆炸半径已由 spec §3 与 AC-21 显式接受并要求 release note。
- **何时该重新考虑**：`list_tenant_admins` 的 Root 短路被移除（那时回退分支变成死代码、应删而不是留着）；或平台引入"审批管理员"这一独立角色（那时 `tenant_admin` 来源要再分化）。

### D9：上线终检与 F054 状态动作调用 = `on_approved` 内三分支，待上线不是失败

- **备选**：
  - A. **审批通过即在 `decide_task` 同步拉起** — 否决：拉起是分钟级，会把审批人的"通过"按钮卡住；且审批中心的既定语义就是"通过 → outbox → 异步执行业务"（skill §1）
  - B. **`on_approved` 里走 F054 状态动作**（选定）
  - C. `on_approved` 只置标记，另起 Beat 轮询拉起 — 否决：又引 Beat（D1 同判据），且失败原因回传路径更长
- **选定**：**B**。`on_approved(instance_id, payload)` 的编排：
  1. 取 `app` 与 `app_version`（**按 `version_id` 起手必须先借道 `app` 行校验归属**，K6 / 坑 20）；应用已删除 → **正常返回**（删除时已取消审批单，这是竞态兜底，D10 的防御条款）。
  2. `AppStateService.stage_version(app_id, version_id)`（F054 §6.1，写 `app.pending_version_id`、**不改应用态**）。
  3. 分派：
     - 应用态 ∈ {草稿, 已上线, 待上线} → `AppStateService.publish(app_id, version_id)`；
     - 应用态 == **已下线** → **只 stage、不 publish**（AC-36 / F054 AC-04：审批通过仅落为待运行版本、不自动重新上线；owner 重新上线时 F054 取 `pending ?? current`）；
     - 应用态 == 已删除 → 同步骤 1。
  4. `publish` 的三种结果（F054 D11 / AC-65）：
     - **`online`** → `VersionService.mark_terminal_state(version_id, 'online')` + 审计 `app.release.online` + 通知 owner；
     - **容量不足** → 应用态「待上线（资源不足）」；审批单**保持通过**；`terminal_state` 保持 `NULL`（派生显示「待上线」，D6）；通知 **owner + 租户管理员**（Root → 平台超管）——这里**是通知**不是审批人解析，故可**直接复用** `_get_admin_recipient_ids` 的无条件 union（多通知一个超管无害；与 D8 前置 2 的条件回退是两码事，别混用）；
     - **拉起 / 探活非容量失败**（决议-8） → 应用态「待上线（上线失败）」；同上通知，成因文案区分。
  5. **⚠️ 后两者必须"正常返回"而不是 raise**——它们是产品定义的终态（AC-31），有应用态、有通知、有发布面呈现，不是 K3 所禁的"静默失败"。**只有系统性失败才 raise**：编排器不可达（16121）、版本记录不存在、`stage_version` 前态冲突（16102）——这些抛出去让 outbox 置 `execute_failed` + 建异常 + 通知管理员，正是想要的。判据写死为一句：**"应用最终会不会自己好起来"——会（等资源 / 点手动上线）就返回，不会（代码或基建坏了）就抛**。
- **手动上线（AC-32）**：发布面按钮 → `POST /api/v1/apps/{app_id}/actions/manual-publish`（F054 提供）；**不重走审批**；owner-only 由 F055 在发布面 service 侧前置拦截（C4：管理员在权限运行时被身份短路，不能靠它）；成功 → `mark_terminal_state('online')` + 审计 `app.release.manual_publish`；仍失败 → 保持待上线并回原因（不改审批结论）。
- **何时该重新考虑**：出现"通过后需要人工排期上线"的诉求（那时 `on_approved` 只 stage、上线全部走手动）；或 publish 的耗时把默认 celery 队列拖垮（D1 的拆队列触发条件）。

### D10：驳回 / 撤回 / 删除致取消与 `withdraw` 终态守卫

- **驳回（AC-33）**：`on_rejected` → `mark_terminal_state(version_id, 'rejected')` + `app_deployment` 置 `failed(stage='approved', code=None)`（区分于预检失败）+ 审计 `app.release.rejected`（`reason` = 驳回理由全文）。**应用态不动**：首发保持草稿态、迭代保持已上线且当前版本继续运行（F054 AC-05 天然成立，因为被驳回**不写** `pending_version_id`）。驳回理由全文来源 = `approval_task.comment`，经状态只读接口回传（D15）。
- **撤回（AC-34）**：owner 在发布面点撤回 → 直接调既有 `POST /api/v1/approval/instances/{instance_id}/withdraw`（`approval_center_service.py:418-492`），owner-only 由它已有的 `applicant_user_id` 校验天然成立（`:430`）；`on_withdrawn` → `mark_terminal_state('withdrawn')` + deployment 置 failed + 审计。通知"已收到待办的审批人"由既有 `withdraw_instance` 负责（skill §8）。
- **`withdraw` 终态守卫（AC-22）**：`withdraw_instance` 今天**只校验申请人**（`:430`），已 EXECUTED / EXCEPTION / WITHDRAWN 的实例可被**反复撤回并重复触发 `on_withdrawn`**（`:481-482`）。修点 = `:432` 之前加 `if instance.status != ApprovalInstanceStatus.PENDING: raise <18xxx>`。
  - **错误码归属**：这是**审批模块的通用缺陷修复、不是应用发布特有** → 用 approval 自己的段 **181xx**（`common/errcode/approval.py`），**不占 162 段**。
  - 爆炸半径：既有前端只在 `status === "pending"` 时显示撤回按钮（`ApprovalCenterDialog.tsx:376`），正常路径不受影响；受影响的只有并发 / 重放 / 直接打 API。
- **删除致取消（AC-35）**：
  - **没有可复用的"取消在途实例"通用入口**——唯一置 `CANCELLED` 的路径 `approval_exception_service.py:159-230 cancel_exception_api` **从 exception 记录起手**且通知的是**申请人**（`:221` `approval_exception_cancelled`），与 AC-35 要求的"通知审批人"相反（坑 6）。
  - → **新增** `ApprovalCenterService.cancel_instance_by_business(*, instance_id | (scenario_code, business_key), reason, operator_user_id)`：置 instance=CANCELLED + 全部 PENDING task → CANCELLED + 写 `approval_action_log` + 审计 + **通知审批人**（新 action_code `approval_instance_cancelled`）+ 调 handler `on_cancelled`。放**审批模块**（它操作的是审批实体，放 F055 里就是跨模块直写别人的表）。
  - 触发路径：F054 的 `lifecycle_hooks.register_app_deleted_hook(fn)`，**F055 在组合根注册**（F054 §4.1-C）。
  - **F054 已明示"钩子失败不回滚删除"** → **F055 侧必须自带防御**（F054 §6.1 契约行）：状态只读接口与审批单读侧对"应用已删除"**独立判定**并按已取消呈现，不把正确性全押在钩子送达上；`on_approved` 步骤 1 的"应用已删除即正常返回"是同一防御的另一面。
- **何时该重新考虑**：出现第三个需要"按业务键取消在途单"的场景（如频道被删）→ `cancel_instance_by_business` 已经是通用形状，直接复用即可，届时只需把它写进 skill §7 的 API 列表；或审批引擎引入"实例状态机"统一守卫（那时 D10 的守卫应并入引擎而不是留在 `withdraw_instance` 一处）。

### D11：资源档位实体 = 独立平台级表 + 只可停用不可删 + seed 从 F054 常量读

- **备选（存储位置）**：
  - A. **塞进 `tenant.quota_config`**（`database/models/tenant.py:95-98`）— **否决**：语义完全不同（配额 = "能创建几个 X" 的计数上限；档位 = "这个容器 CPU/内存上限" 的运行时限额），且 `role/domain/services/quota_service.py:57 VALID_QUOTA_KEYS` 是**闭合白名单**（`validate_quota_config` 会拒未知 key）、三级取值（admin 短路 → 角色 max → 租户 min）会把档位算成一个荒谬的数、`/me/quotas` 前端面也会跟着污染
  - B. **写死为代码常量、不建表** — 缺点：AC-45 要求超管可行内编辑规格与说明、可停用，常量做不到
  - C. **独立表 `resource_tier`（平台级、无 `tenant_id`）**（选定）
- **选定**：**C**。
  - 列：`id`(PK) · `code`(唯一，`light` / `standard` / `performance`) · `name` · `cpu_millicores`(int) · `memory_mb`(int) · `description` · `enabled`(bool) · `sort_order` · `create_time` / `update_time`。**用整数毫核与 MB**，不用浮点 vCPU（浮点在 DM8 与 JSON 往返里会给出 `0.30000000000000004` 这种值）。
  - **平台级 = 无 `tenant_id` 列**（AC-44 跨租户共享）；登记进 `_TENANT_AWARE_MODEL_MODULES` 只为保证 metadata 被 import（K6），不受自动过滤。
  - **模型文件落 `database/models/resource_tier.py`，不落 `app_publish/domain/models/`**：`ResourceTier` 实体归 F055、**F054 只读**（F054 design D11），放在 `app_publish` 里会逼 `app_runtime` 反向 import，双向依赖当场成立且**没有任何 arch-guard 规则会拦**（C1 / D16 的订正）。业务逻辑仍全在 `ResourceTierService`。
  - **只可停用、不可删除**（管理 tab 不提供删除入口）：`app_version.tier_id` 是历史快照的引用，档位被删 → 老版本重新上线时解析不出规格。F054 D11 的"何时重新考虑"里假设了"F055 支持删档"这一情形——**本设计明确不支持**，从而 `tier_id` 永远可解析；已回写为 §6.1 的 Outgoing 契约行。
- **三档 seed 与数值裁定（F054 与本 spec 的直接冲突，必须裁一套）**：
  - F054 design:294 `DEFAULT_TIERS` = 轻量 0.5 vCPU/512 MiB · 标准 1/1024 · **增强** 2/2048；本 spec **AC-44** = 轻量 **1C/2G** · 标准 **2C/4G** · **性能** **4C/8G**。
  - → **以本 spec 的产品口径为准**（AC-44 是写进 PRD 与 ui-demo 的产品承诺，F054 的数值是实现期临时值），**回写 F054 的 `DEFAULT_TIERS` 常量与第三档名称**（"增强" → "性能"）。
  - **seed 仍从 F054 `DEFAULT_TIERS` 常量读取落库**（F054 D11 已把这条登记为 Outgoing 契约），保证"表未落"与"表刚 seed 完"两个时刻规格恒等。
  - **规格初始默认值是部署配置项**（AC-44）：优先级 = `settings.app_runtime.default_tiers`（K10）> `DEFAULT_TIERS` 常量。⚠️ **114 上必须用这个覆盖**：114 曾长期 available ~0.9G（F054 K2），1C/2G 的轻量档会在容量准入闸上直接被拒 → 演示前把 114 的 `light` 下调到 0.5C/512M（坑 27）。
  - seed 时机：`init_default_data` 内（与审批场景 seed 同批），**幂等按 `code` 判存在即跳过**（超管调过的规格不被升级重置，与 AC-19 同判据）。
- **选档与停用**（AC-46 / AC-47）：CLI 取 manifest `tier`、未声明取 `light`；声明了不存在或 `enabled=False` 的档 → 预检拒（16223）。停用**只拦新选择**：存量应用照常运行、迭代发布沿用原档位（迭代若在 manifest 里仍写着已停用的档 → 拒，owner 需改声明；**这是有意的**：停用的语义就是"新发布不可再选"）。
- **写入快照**：`app_version.tier_id`（F054 已定的显式列）记**档位标识**，规格取运行时当前值（AC-48）→ 规格调整自下一次发布 / 重新上线生效（F054 AC-64 由此成立）。
- **管理 tab（AC-45）本轮后置**，落点方向：platform `pages/SystemPage` 加一个 tab（**仅平台超管可见**，与 F054 的 `app_runtime_enabled` 开关联动、未部署不出现）；表用 `bs-ui/table` + `bs-ui/pagination`，**平台无表单库**（无 react-hook-form / formik / zod）→ 行内编辑用手写 `useState` + `bs-ui/input`，保存前 `bsConfirm`；"使用中应用数" = `SELECT COUNT(DISTINCT app_id) FROM app_version WHERE tier_id=? AND terminal_state='online'`。
- **何时该重新考虑**：出现自定义规格诉求（PRD 明确不做，重议前先回 GOV-03）；或多形态下同一档位在 compose 与 k8s 需要不同映射（那时 `resource_tier` 加 `runtime_profile` 列而不是分两张表，INV-33）。

### D12：元信息更新时点与审计 = 通过预检即更新 + 自建 `app.release.*` 事件族

- **元信息（AC-05）**：预检 + 扫描通过后**立即**调 F054 的 `AppMetaService.update_meta(app_id, patch, actor)`（**不等审批**；元信息不属发布、不经审批、计审计 `app.meta_update`）——**F055 不另写一份更新逻辑**（F054 §6.1 契约行）。预检或扫描失败 → 不更新。
  - **图标是包内文件、不能复用 `/upload/icon` 端点**（那是 HTTP 上传路径）：解包取字节 → 校验（≤ 1 MiB、扩展名 ∈ `jpeg/jpg/png`）→ `put_object(bucket=public_bucket, object_name=f"icon/{uuid4()}.png")` → 把 **`object_name` 写进 `app.logo`**。
  - ⚠️ **落库存 `relative_path` 不是 `file_path`**：`api/v1/endpoints.py:178-194` 的 helper 返回 `{file_path, relative_path}`，其中 `file_path` 是 `get_share_link` 的**预签名 URL（默认 7 天过期）**（`core/cache/utils.py:202-206`）——存它进库，一周后全站图标 403（坑 16）。另注：既有实现**对象名恒写死 `.png`** 不管原扩展名，与 flow / assistant 保持一致即可。
  - 公共桶匿名策略**不覆盖 `icon/*` 前缀**（`minio_storage.py:305-306` 只覆盖 `knowledge/images/*` 与 `tmp/images/*`），图标今天是靠 nginx `/bisheng/` location 转发访问的——同路即可，不要为它去改桶策略。
- **审计事件族（AC-01「均计审计且携带应用标识与版本号」+「须能按对象应用筛选」）**：
  - **审批族审计不够用**：`approval.request.submit` / `approval.task.approve` 等虽已在 `_UI_VISIBLE_V2_ACTIONS`（`database/models/audit_log.py:193` 起，元组止于 `:259`）里天然可见，但它们的 `target_type` **恒为 `approval_instance` / `approval_task`**（`approval_gate.py:159` 等），**按"对象 = 应用"筛不到**（坑 21）。
  - → **另起 `app.release.*` 事件族**（**不用 `app.publish.*`**：F054 已把 `app.publish` 用作"上线动作"的 action 名，`app.publish` 与 `app.publish.submit` 混在同一前缀下会让审计筛选与命名空间映射两头别扭）。清单见 §4.2 ⑥。
  - 写法：`AuditLogDao.ainsert_v2(tenant_id=…, operator_id=…, operator_tenant_id=…, action='app.release.submit', target_type='app_version', target_id=str(version_id), metadata={'app_id':…, 'version_no':…, 'deployment_id':…, 'stage':…}, object_name=app.name, reason=…)`。该方法（`AuditLogDao.ainsert_v2`，`audit_log.py:428` 起）**内部自带 `bypass_tenant_filter()` + 独立 session + commit** → 调用方**不需要也不应该**再包事务；写失败会抛，用 `approval_outbox_service.py:105-121` 的"审计失败不影响主流程"包法。
  - `operator_id`：CLI 触发的用发起 deploy 的**服务账号 user_id**（真实执行者）+ metadata 里带 `owner_user_id`；系统触发（如钩子取消）用 `0`（`operator_name` 自动填 `system`，`operator_tenant_id` → `ROOT_TENANT_ID`）。
  - **四处 lockstep 必须同批改**（`audit_log.py` 注释已明确要求）：`_UI_VISIBLE_V2_ACTIONS`（`:193` 起）+ `_V2_NAMESPACE_TO_ACTION_PREFIX`（`:261`；**`"app": "app."` 已由 F054 落码建好（`:266`），F055 只追加 action 值**）+ platform `controllers/API/log.ts` 的 `actions` / `getModulesApi` + `bs.json` 的 `log.systemIdEnum` / `log.eventTypeEnum` **三语**。漏任一处 = 写库了但审计页看不到（坑 21）。
- **何时该重新考虑**：F050 的审计 `subject` 列落地 → AC-55 的双归属（actor=应用 / subject=访问用户）从 `metadata` 升为正式列（spec 已允许"落地前以附加字段承载"）；或审计事件数量让 `_UI_VISIBLE_V2_ACTIONS` 的手工白名单不可维护 → 那时该把可见性做成 action 的声明属性而不是一张 tuple。

### D13：能力总线注入通道与运行期凭据 —— 落点方向（**本轮后置**）

> **本轮不做**（`mvp-114-path.md` §6：不集成平台能力）。本节只钉住落点方向，避免后置波次重新论证。**MVP 期的诚实表达见 D16**：manifest 的 `capabilities` 非空 → 预检**拒绝**并提示「本环境未启用能力总线」（16231），**不静默忽略**——静默忽略会让开发者以为声明生效了。

- **运行期凭据主体**（决议-4）：F049 底座已备好第二类主体——`PRINCIPAL_KIND_HOSTED_APP = "hosted_app"`（`open_api/domain/context.py:23`）与 `SUBJECT_KIND_HOSTED_APP`（`api_credential.py:46`，`CREDENTIAL_SUBJECT_KINDS` 已含它）。**只差 F049 design D2 说的 `SUBJECT_RESOLVERS['hosted_app']` 解析器**（F049 明确"随 F055 定义并注册"，未注册前该 kind 在 `/api/v2` 上按 `26002` 拒绝）。
  - **方向**：`subject_user_id = app.owner_user_id`（能力按 owner 权限的边界由能力声明白名单收窄，不是由主体放大）、`tenant_id = app.tenant_id`、`scopes` 由能力声明派生（声明模型 → `model:invoke`；声明知识库 → 检索位）。**审计双归属（AC-55）与执行身份是两件事**：执行身份是应用，审计 actor = 应用、subject = 当前访问用户（由 F054 AC-34 注入的 OBO 令牌确立）。
  - 签发 / 重签在**审批通过、拉起新容器之前**（新凭据随环境变量 `BISHENG_APP_TOKEN` 注入新容器）；旧凭据**撤销**即 5 秒内失效（INV-28；F049 凭据缓存 TTL 3s < 5s 上界，天然满足）。下线 → 主体停用语义（**不新增状态枚举**）；删除 → 撤销。全程无管理界面、不进服务账号列表（AC-59）。
- **模型注入**：经 F051 的平台 OpenAI 兼容面；应用侧用**行业标准客户端**（`openai` SDK）+ 平台注入的 `BISHENG_PLATFORM_API_BASE` + `BISHENG_APP_TOKEN`，平台不做薄封装（PRD-1 DEV-07 已定"模型调用与应用数据库刻意不进 SDK"）。
- **知识库注入**：**白名单由平台侧按该应用当前生效版本的 `capabilities` 确定**（AC-50「应用不可自报白名单」）；运行期可及范围 = 白名单 ∩ 当前访问用户可见范围（文件级、fail-closed，经 F052 统一检索门面，INV-36）。无访问用户上下文 → **拒绝检索**（AC-52），**仅模型调用**允许以应用自身发起并把 subject 显式标为「应用自身」（AC-55）。
- **能力收回（AC-53）不做轮询检测**：调用期由能力总线入口判定"声明里有、平台侧已不存在或已收回" → 返回**带能力名与 `revoked` 原因的错误码**（162 段 `16273`），可与普通失败区分、不回退旧值、应用整体可用。owner 侧的「已失效 + 原因」标记由发布面读接口**按需计算**（`declared ∖ 当前可解析`），**不落库、不起定时任务**——落库就会有状态漂移，而这个信息只在 owner 打开发布面时才需要。
- **何时该重新考虑（即何时开工）**：预算恢复且 F051 / F052 的面已可用；或出现"应用必须调模型才有意义"的客户场景（那时能力总线从后置升为阻塞项）。**开工前必读**：F049 design D2「主体解析器」段与 F052 的门面契约。

### D14：审批人侧界面落位 = client 弹窗内早分派 + 审读视图走弹窗放宽（**后置部分已标注**）

- **落点**（决议-3）：审批人侧全部界面在 **client 审批中心弹窗**（既有处理面）；场景配置在 **platform 审批中心场景配置**。
- **四分区（AC-24）—— MVP 做**：新组件 `client/src/components/approval/AppPublishDetailPanel.tsx`（新文件，避开 `ApprovalCenterDialog.tsx` 已 1037 行 + 600 行硬规），在 `TaskDetailPanel`（`:682`）内按 `detail.scenario_code` **早分派**。
  - **备选**：先建 `SCENARIO_DETAIL_RENDERERS: Record<string, FC<{detail}>>` 注册表再分派 — **本轮否决**：一个场景不值得建注册表，且本仓既有的"场景专属"先例（`canRevoke` `:378-382` 只对 `menu_access_request`）就是"顶层算个布尔 + 条件渲染"。**何时重新考虑**：出现第二个需要自定义详情的场景，那一刻抽注册表（届时两个场景的差异已经能告诉你注册表该长什么样）。
  - 分区映射：① 头部基本信息 → 复用 `DetailHeader`（`:650-680`）+ `InfoGrid`（`:152-166`），把「来源 / 首发·迭代」两行加进 `basicRows`（`:686-694`）；② 能力声明白话摘要 → 新分区（`InfoGrid` 签名是 `[string,string][]`，装不下"图标 + 名称 + 说明 + 失效标记"三段行）；③ 可见范围快照 + 「仅供参考」黄注 → 新分区（可参考「申请理由」灰底块 `:726-731`）；④ 资源档位（+ 含结构变更时的「结构变更」行）→ 并进 ① 或独立一行。
- **驳回理由必填（AC-24）—— MVP 做**：`runTaskDecision`（`:328-334`）的 `:331` 今天在评论为空时兜底成**硬编码中文** `"同意"/"驳回"`；改为 ① 驳回按钮 `disabled={actionLoading || !decisionComment.trim()}`（现成范式：撤销弹窗确认按钮 `:613` `disabled={!revokeReason.trim()}`、`confirmRevokeGrant :362-368` 的空值 toast）② 去掉中文兜底。**通过仍可空**——AC-24 只要求驳回必填，别一刀切。
- **审读视图（AC-25）—— 后置**：受 K11 的 800px 上限约束，两案：
  - **案 A（选定方向）**：同弹窗内 `viewMode: 'list' | 'review'` 切换，review 态把 `DialogContent` className 放宽到 `md:max-w-[1200px]`（改 `:388-393` 的表达式即可，**零结构改动**）；
  - 案 B：client 另开一条路由页 — 否决：脱离决议-3「处理面在弹窗」的口径，且要新建路由 + 权限守卫 + 返回态。
  - **MVP 期整块不渲染**（连「查看待上线版本」按钮也不出），避免死链。只读代码 / 文件树 / diff **platform 与 client 都无现成件**，client 侧 `pages/knowledge/FilePreview/` 与 `components/Messages/Content/CodeBlock.tsx` 可参考。
- **审批期临时预览实例（AC-26～28）—— 后置**：走 F054 已登记为 Outgoing 的预览入口路由 `/apps/preview/{session}`（F054 §6.1，后置 Wave）；**实例生命周期归 F055**：以待上线版本快照拉起（复用 `POST /v1/intents/probe` 的临时形态 + `deploy` 意图但不占应用实例名额）、连一个临时空库、注入**审批人本人身份**、平台能力按 **owner** 权限放行（NFR-1.2 审批例外，INV-36 已登记）并计审计；审批出终态或超时（默认 **7 天**，`settings.app_runtime.preview_ttl_days`）即回收，回收后可再拉起。
- **站内消息（AC-64 / AC-65）—— MVP 做（改动极小）**：
  - **审批类**沿用既有通用动作码，差异靠 `scenario_code` → **一处代码**：`client/src/components/NotificationsDialog.tsx:96-100 APPROVAL_TASK_SCENARIO_TEXT_KEYS` 加 `app_publish_request: 'com_notifications_action_request_app_publish'`；**三处 i18n**：`client/src/locales/{zh-Hans,en,ja}/translation.json`（同族键 `com_notifications_action_request_channel` 在 `zh-Hans:489` / `en:501` / `ja:486`）。
  - **非审批类新事件**（待上线-资源不足 / 上线失败）→ 新 `action_code` **只要不进** `APPROVAL_CENTER_ACTION_CODES`（`:77-88`），`getNotificationText` 的兜底 key `com_notifications_action_{action_code}`（`:470`）自动生效 → **零前端代码，只加三语 key**。
    - **⚠️「天然没有跳转按钮」有一个必须写进发送契约的前提**：按钮显示条件是 `isApprovalMessageType(message_type, action_code) && isPendingApprovalStatus(status) && !APPROVAL_NO_BUTTON_ACTION_CODES.has(...)`，而 `isApprovalMessageType`（`NotificationsDialog.tsx:152-156`）在 **`message_type === "request" || "approve"` 时也为真**，并不只看 `action_code` 白名单。→ **发送这两类非审批通知时，`message_type` 一律不得为 `request` / `approve`**（用中性类型），否则按钮照样长出来，AC-65「消息只通知不承载操作」当场破。已写进 §4.2 ⑦。
  - platform 侧**不加铃铛**（PRD §3.0.3：管理后台不设消息面）。
- **platform 场景配置（AC-19）—— MVP 做（两处小改）**：
  - 场景 seed 落库后**自动出现在左栏列表**（`ApprovalPage/index.tsx:1632-1700`），且因为已存在而不出现在「新增」下拉（`:232` 减去已存在的 `scenario_code`）→ **AC-19 的"展示"部分零前端改动**。
  - **必改**：`APPROVER_SOURCE_OPTIONS`（`ApprovalPage/index.tsx:590-597`）**补 `tenant_admin` 一项**——今天这个下拉只有 6 项且没有它，而 `APPROVER_SOURCE_LABEL_KEYS`（`:180-188`）与三语 i18n（`platform/public/locales/zh-Hans/bs.json` 的 `approverSource.tenant_admin`，**两处** `:1832` / `:1842`）**早就有**。不补 = 租户管理员改配后**没法把「租户管理员」这个来源加回来**，AC-19 半残。
  - **场景名 `应用发布` 是后端硬编码中文**（与既有三场景 `approval_registry.py:19/30/40` 一致），前端直接渲染 `s.scenario_name`（`:1660`）——**接受中文单语**，不另开映射表（一致性 > 单点完美）。
- **i18n / lint 债（触碰即还，根 AGENTS.md）**：`ApprovalCenterDialog.tsx` 在 `client/eslint-suppressions.json:1714-1723` 有冻结违规（`no-explicit-any ×16` / **`no-restricted-syntax ×4` 硬编码中文** / `exhaustive-deps ×3`）；F055 改该文件的 PR **必须**顺手把 4 条中文抽成 i18n 并 `pnpm lint:prune`。这是实打实的任务成本，tasks.md 单列。
- **何时该重新考虑**：见上文注册表触发条件；或审读视图的 1200px 仍不够（那时才考虑案 B 的独立路由）。

### D15：发布面最小区块与状态只读接口 = 区块组件填 F054 的 slot + 一个 service 供两处消费

- **承载**：F054 已定死壳——目录 `platform/src/pages/BuildPage/hostedApp/{index.tsx,Header.tsx,tabs/PublishTab.tsx,...}`、路由 `build/apps/:appId`（`permission:'build'`、**零新增菜单与权限点**）、**发布 tab 用 slot / children 给 F055 与 F056 留位**（F054 design:321 / :548）。**F055 只填内容、不碰壳**。
- **区块落点**：新建子目录 `hostedApp/publish/`，每块一个文件（避免与 F054 的 `PublishTab.tsx` 抢同一文件，600 行硬规同样适用）：
  - `ApprovalStatusCard.tsx`（**MVP**：待审 / 通过 / 驳回 / 已撤回 / 待上线成因 + **驳回理由全文** + 结构变更提示位 + 在途时「撤回」按钮）
  - `VersionListCard.tsx`（**MVP**：只读列表，与版本 tab 同数据源）
  - `OpsActionsCard.tsx`（**MVP**：下线 / 重新上线 / 待上线态出现「手动上线」——**复用 F054 抽出的 `useHostedAppActions`**，不另写一套确认文案，F054 D13）
  - `DangerZoneCard.tsx`（**MVP**：显式删除调 F054，仅 owner；已上线态置灰「请先下线」）
  - `CapabilityListCard.tsx` / `TierSelectCard.tsx` / `SchemaChangeNotice.tsx`（**后置**）
  - **可见范围区是 F056 的槽位**，F055 只留位、不写内容。
- **数据拉取**：K11 ① → 版本列表用 `util/hook.ts:215 useTable`（要求接口返回 `{data,total}`，否则 `:238` 直接 console.error），状态卡用裸 `useState + useEffect`。
- **⚠️ 不要复用 `CardSelectVersion`**（`platform/src/pages/BuildPage/CardSelectVersion.tsx`）：它**切换即写库**（`handleChange :25-31` 调 `changeWorkflowCurrentVersion` / `changeCurrentVersion`），且 `version_list` 对托管应用**恒空**（来自 `FlowVersionDao.get_list_by_flow_ids`，F054 坑 13）。AC-39 的版本列表是**只读、无回滚入口**，与那个可写下拉语义相反（坑 29）。
- **状态只读接口（AC-38）**：`GET /api/v1/apps/{app_id}/publish-status` —— 字段见 §4.2 ②。
  - **同一个 service 方法** `PublishStatusService.get_publish_status(app_id, actor)` 供**发布面**与 **F052 MCP 应用状态工具**消费 → AC-38「两处返回一致」由"只有一处实现"结构性保证，不靠约定。
  - **K11 ② 红线**：对无权者**不能回 403/404**（整页跳 `/403`）→ 无权时返回 200 + 业务码 `16254` 或让前端以 `silent: true` 调用。
- **撤回按钮**：直接调既有 `POST /api/v1/approval/instances/{instance_id}/withdraw`（owner-only 由后端 applicant 校验天然成立，D10）。
- **WB-15 版本差异（AC-41）后置**：落点方向 = 版本 tab 与审读视图**同一呈现组件**（`hostedApp/publish/VersionDiff.tsx`），数据源 = 服务端比对两个版本快照的 tar 条目（`GET /api/v1/apps/{app_id}/versions/{a}/diff/{b}` → `{files:[{path, change, additions, deletions}], patches:[…]}`），**服务端算 diff 不下发两份 tar**（下发等于把代码明文交给浏览器，且 50MB 包会直接卡死页面）。
- **何时该重新考虑**：发布面区块数量超过 8 个或状态卡需要实时刷新（那时才值得为 platform 引入轮询 hook 或重估 react-query 冻结令）。

### D16：MVP-核心边界（本轮做哪些 AC、哪些后置）与模块划分

- **备选（模块划分）**：
  - A. **并入 F054 的 `bisheng/app_runtime/`** — 优点：一个"应用"模块；缺点：`app_runtime` 已有 8 个 service，再塞 10 个就是一个 20 文件的巨模块，且发布管线与运行时的 owner / 发版节奏不同（F054 首波已落码、F055 未开工），同模块会让两边的改动互相卡 review
  - B. **新模块 `bisheng/app_publish/`**（选定）
- **选定**：**B**。判据是**文件规模与 owner 边界**，不是机器护栏。`app_publish` 调 `app_runtime`（`AppStateService` / `AppMetaService` / `orchestrator_client`），反向由 F054 的 `lifecycle_hooks` 回调解耦（F054 §4.1-C）。模块内文件清单见 §4.3。
  - **⚠️ 本文早期版本称"分成两个模块是为了让 arch-guard 把方向钉死"，该论证是假的、已删**：
    - `scripts/arch-guard.sh` 里唯一涉及跨模块的是 **RULE-5**，而它只匹配 `/api/endpoints/` 与 `/api/router.py`（`:71-82`），**domain 层跨模块 import 完全不检查**；RULE-2/3/4 也都不管方向。**没有任何 hook 会拦下 `app_runtime` import `app_publish`**。
    - 而且方向本就不是纯单向：`ResourceTier` 归 F055、**F054 只读**（F054 design D11「表存在时以表为准」；本文 §6.1 也把消费者列为 F054）——只要模型放在 `app_publish/domain/models/`，`app_runtime` 就必须反向 import，双向依赖当场成立。
    - → **落地口径**：`ResourceTier` 的 **SQLModel 定义落 `database/models/resource_tier.py`**（两模块共读，与 F054 把 `app_version` 放 `database/models/` 同形），**业务逻辑（seed / 选档解析 / 停用 / 使用中应用数）仍归 `app_publish` 的 `ResourceTierService`**。方向靠 §6.1 / §6.2 的契约表 + code review 维持。
  - **⚠️ 组合根注册必须在两类进程都执行**：`register_app_deleted_hook` 的注册点在 API 进程与 **Celery worker 进程**都要跑到（outbox 里的 `on_approved` 在 worker 里重建 handler；删除钩子在 API 进程触发）。仓内教训：初始化只挂 API lifespan 会在多进程 / 多节点下静默半失效（memory `feedback_multinode_default_assumption`）。落点 = 一个可被两处 import 的 `app_publish/composition.py`，由 `main.py` lifespan 与 `worker/main.py` 启动各调一次（幂等）。
- **裁剪逐项对照**（`mvp-114-path.md` §6 F055 行；tasks.md 以 `[MVP-核心]` 标记首波，其余排后但**不删**）：

  | 分组 | `[MVP-核心]` 首波 | 后置 Wave（release 仍必做） |
  |---|---|---|
  | 管线 | AC-01（管线主链 + `app.release.*` 审计）· AC-02 · AC-03 · AC-04（`app:manage` + 归属人 owner-only + 拒 delegate 文案）· AC-05（元信息 + 档位入快照）· AC-06 · AC-07（manifest / runtime / 端口 / 档位）· AC-10 · AC-11 | AC-07 的**能力声明引用校验**（模型 / 知识库存在性）· AC-08 的静态依赖判据（本期由探活兜）· AC-09 结构变更确认 |
  | 预置审批流 | AC-12～AC-21（含三项阻塞前置）· AC-23 | AC-22 `withdraw` 终态守卫（**紧随首波、优先级最高的后置项**） |
  | 审批人侧 | AC-24 **除「查看待上线版本」入口外**（四分区 + 驳回理由必填） | AC-24 的「查看待上线版本」按钮（随审读视图一起出，D14：MVP 期整块不渲染以免死链）· AC-25 审读视图 · AC-26～AC-29 临时预览实例 · AC-30 的"经审读视图与预览试用"部分 |
  | 结果与终检 | AC-31 · AC-32 · AC-33 · AC-34 · AC-35 · AC-36 · AC-38 | AC-37（能力 5 秒失效，随能力总线） |
  | 版本记录 | AC-39 · AC-40 · AC-43 | AC-41 差异 · AC-42 结构演进与迁移前快照 |
  | 资源档位 | AC-44 三档 seed · AC-46 选档 / 默认轻量 · AC-47 停用只拦新选 · AC-48 快照记标识 | AC-45 管理 tab |
  | 能力总线 | — （**声明非空即拒并提示本环境未启用**，16231） | AC-49～AC-56 全部 |
  | 运行期凭据 | — | AC-57～AC-60 全部 |
  | 发布面 | AC-61 的**审批状态区 / 版本列表 / 运营动作 / 危险操作 / 入口链接槽位** · AC-62 · AC-38 只读接口 | AC-61 的能力声明清单与档位选择 · AC-63 失效标记 |
  | 触达 | AC-64 的**审批单生成 / 通过 / 驳回 / 撤回 / 删除致取消 / 待上线**六类 · AC-65 | AC-64 的全表复核 |

- **原因**：裁剪判据 = `mvp-114-path.md` §1 演示剧本**步 3–4**（`bisheng deploy` → 预检 / 扫描 / 预置审批 → 审批人通过 → 上线）能不能跑通。凡不在这条链路上、且属"完整性 / 治理增强"的（审读视图、预览实例、能力总线、凭据、结构演进、差异、档位 tab）后置；凡剧本必经的（管线全链、预置审批流与三前置、档位 seed 与选档、发布面状态区、六类触达）全在首波。
  - **⚠️ AC-24（审批人侧详情面板）是对 §6 裁剪基准的一次显式扩张，判据记在这里**：`mvp-114-path.md:77` 的 F055 「`[MVP-核心]` 只做这些」列**没有**审批人侧详情面板（它只写到"审批单 → 审批通过 → 调 F054 上线动作"）。仍提进首波的理由是**演示剧本步 4 必经此屏**：审批人打开审批中心才能点通过，而 `detail_snapshot` 是结构化的，走通用两列网格会渲染成 `[object Object]` 一坨（坑 7）——即"不做四分区"不是少一个功能，而是**步 4 当场露怯**。驳回理由必填同批（改动只有两行，`:331` 那行本来就要动，坑 25）。**扩张仅限这两项**：审读视图 / 预览实例 / 「查看待上线版本」入口一律不在首波。
- **何时该重新考虑**：预算恢复 → 按 §8 的优先级顺序补回（**`withdraw` 守卫排第一**，因为它是一个可被直接打 API 触发的既有缺陷）；或本 Feature 要发给 114 之外的环境（那时能力总线的"声明即拒"会变成产品级阻塞，必须先补 D13）。

---

## 4. 系统现状（接手必读）

> 本节写"建成后代码长什么样"。F055 尚未开工，除三项阻塞前置外全为绿地。

### 4.1 数据流

**A. 主链：一次 `bisheng deploy`（AC-01 的全景）**

```
CLI: POST /api/v2/apps/deploy  (multipart: package.tar.gz + app_id? + confirm_schema_change?)
  │  Depends(open_api_subject("app:manage"))         # F049，缺位→26xxx；delegate 位发不出来
  ├─ ① 同步前段（秒级，deploy_endpoint → PublishPipelineService.accept）
  │    │  ⚠️ 本段不发任何 RPC：manager 不可达就会把 deploy 变成挂在超时上的请求（D4 / D1 选 C 的兑现）
  │    ├ 归属判定：principal.resource_owner_user_id == app.owner_user_id ?  否→16205
  │    ├ 大小闸 settings.app_runtime.max_package_mb（默认 50）→ 落临时盘 → put_object(file=Path) 到 bisheng-apps
  │    │    键 apps/{app_id}/versions/{version_id}/code.tar.gz     # version_id 此刻生成（D2）
  │    ├ 解包安全闸（拒 abs / .. / symlink / hardlink / dev / fifo）+ 解包大小闸 + 条目数闸
  │    ├ 读 bisheng-app.yaml → yaml.safe_load → AppManifest 校验（D3）  失败→16221/16203
  │    ├ 本地引用校验：runtime ∈ 本地枚举常量 / tier 查本地表 / 能力声明格式 / 密钥引用
  │    │                                              失败→16222/16223/16224/16230
  │    ├ 首发：AppProvisionService.create_draft(...) 建草稿应用（D2；⚠️需 F054 补）
  │    ├ 闸：在途审批单？→16251   待上线态？→16252                       # AC-03（K2）
  │    └ INSERT app_deployment(stage=received, status=running) → 返回 {deployment_id}
  │
  └─ ② Celery 后段（bisheng.worker.app_publish.run_pipeline，默认 celery 队列）
       ├ secret_scan     密钥扫描（D5；**排在构建之前**——秒级正则先跑，
       │                 命中即终止就不必白烧一次分钟级构建）      命中→16241，终止
       ├ precheck_build  起手向 manager 复核 runtime（supported_runtimes）→ 16222
       │                 → build → 轮询 builds      容量不足→16226 / 失败→16227，终止
       ├ precheck_probe  orchestrator_client.probe                失败→16228，终止
       ├ AppMetaService.update_meta(name/description/logo)         # AC-05，不等审批
       ├ approval_created:
       │    ├ ApprovalGate.request_or_pass(business_key=deployment_id,
       │    │      applicant=owner 自然人, applicant_department_id=owner 主部门)
       │    │    ├ PENDING   → 自发站内信给审批人（Gate 不发，坑 5）
       │    │    ├ EXCEPTION → approver_empty：已通知管理员，不放行不卡死（AC-18）
       │    │    └ raise ApprovalScenarioDisabledError → deployment failed(16225)
       │    └ INSERT app_version(terminal_state=NULL) + 回写 deployment   # 先 Gate 后 INSERT（D6）
       └ status=waiting_approval → CLI 轮询到此返回（--wait 继续）
```

**B. 审批终态 → 上线（AC-31 / AC-33 / AC-34 / AC-35）**

```
审批人在 client 弹窗「通过」
  → ApprovalCenterService.decide_task → 或签：同节点其余 PENDING task 置 SKIPPED（AC-13）
  → 最后节点 → instance=APPROVED + 写 approval_outbox → Celery execute_approval_outbox
  → build_runtime_handler('app_publish_request')  ← 工厂分支漏加则永远走不到这里（K1 ③）
  → AppPublishScenarioHandler.on_approved:
       ├ AppStateService.stage_version(app_id, version_id)            # 写 pending_version_id
       ├ 应用态==已下线 → 到此为止（AC-36），正常返回
       └ AppStateService.publish(app_id, version_id)
            ├ online          → mark_terminal_state('online') + 通知 owner + 审计
            ├ 容量不足        → 应用态待上线(资源不足)；审批单保持通过；通知 owner+租户管理员
            └ 拉起/探活失败   → 应用态待上线(上线失败)；同上           # 三者皆「正常返回」（K3/D9）

驳回 → on_rejected  → terminal_state='rejected'  + 理由全文回发布面（AC-33）
撤回 → withdraw_instance（+ 新增终态守卫 AC-22）→ on_withdrawn → 'withdrawn'
删除 → F054 lifecycle_hooks.on_app_deleted → cancel_instance_by_business
        → instance=CANCELLED + PENDING tasks 取消 + 通知审批人 + 审计（AC-35）
        （钩子失败不回滚删除 → 读侧对"应用已删除"独立判定，D10 防御）
```

**C. 手动上线（AC-32）**

```
发布面「手动上线」（仅 owner）→ POST /api/v1/apps/{id}/actions/manual-publish（F054）
  → 成功 → mark_terminal_state('online') + 审计 app.release.manual_publish  # 不重审、不产新版本
  → 仍失败 → 保持待上线 + 原地提示成因（不改审批结论）
```

**D. 状态自查（AC-38，无推送）**

```
platform 发布面 / F052 MCP 应用状态工具
  → GET /api/v1/apps/{app_id}/publish-status
  → PublishStatusService.get_publish_status(app_id, actor)   ← 唯一实现，两处返回一致
     （能力「已失效」标记在此按需计算，不落库、不起定时任务，D13）
```

### 4.2 关键数据结构 / 字段约定（对外契约）

**① 管线接收与轮询端点**（新 router `/api/v2/apps`，逐端点 `Depends(open_api_subject("app:manage"))`）

| 端点 | 入参 | 返回 | 消费者 |
|---|---|---|---|
| `GET /api/v2/apps/deploy-limits` | — | `{max_package_mb, max_unpacked_mb, max_package_entries}`（读 `settings.app_runtime.*`，默认 50 / 200 / 20000） | **F053** 打包后上传前自查（AC-32「按部署配置的上限」的取值途径；取不到 → 直接上传、服务端 16201 兜底，D2） |
| `POST /api/v2/apps/deploy` | multipart：`package`（tar.gz，≤ `max_package_mb`）· `app_id`（迭代必填、首发省略）· `confirm_schema_change: bool`（本期只接受不消费，D3） | `{deployment_id, app_id, version_id, entry_url?}` | **F053** `bisheng deploy` |
| `GET /api/v2/apps/deployments/{deployment_id}` | — | `{stage, status, failure{stage,code,message,details,hints[]}, app_id, version_no, approval{instance_id,status,reject_reason}, app_state, pending_reason}` | **F053** 轮询 / `--wait` |
| `GET /api/v2/apps/{app_id}/logs` | `tail, since, keyword` | `{lines[]}`（**转发 F054 `GET /api/v1/apps/{id}/logs` 的同一服务方法**，只加 `app:manage` + 归属人判定） | **F053** `bisheng logs` |

**② 发布状态只读接口**（`/api/v1`，登录态；AC-38）

`GET /api/v1/apps/{app_id}/publish-status` →

```
{ app_state, pending_reason: "capacity"|"deploy_failed"|null,
  current_version: {version_id, version_no, kind, submitted_at, terminal_state},
  pending_version: {…} | null,
  deployment: {id, stage, status, failure{stage,code,message,details,hints[]}},
  approval: {instance_id, status, submitted_at, decided_at, reject_reason, approver_names[]},
  tier: {code, name, cpu_millicores, memory_mb, enabled},
  capabilities: [{kind, name, state:"active"|"revoked", revoked_reason}],
  schema_change: {has_breaking, items[]} | null,
  can: {withdraw, manual_publish, submit} }
```

**③ AppManifest（`bisheng-app.yaml` 对外形态 —— 本 Feature 拥有，release-contract 表 1）**

| 字段 | 类型 / 取值 | 必填 | 说明 | 谁消费 |
|---|---|---|---|---|
| `manifest_version` | int，默认 `1` | 否 | 兼容闸：大于平台支持值 → 提示升级平台 | F055 |
| `name` | str 1–64 | **是** | 应用名（→ `app.name`，随提交更新，AC-05） | F055 / F054 |
| `description` | str ≤ 500 | 否 | → `app.description` | F055 |
| `icon` | 包内相对路径 | 否 | 图片文件（≤1 MiB，jpeg/jpg/png）→ MinIO 公共桶 `icon/{uuid}.png` → `app.logo` | F055 |
| `slug` | str（小写字母数字连字符） | 否 | 未声明由平台按名称生成；**全局唯一**（F054 AC-08） | F054 |
| `runtime` | 枚举，MVP 期仅 `python3.11` | **是** | 取值集合来自 manager `GET /v1/runtime/status.supported_runtimes` | F054（Dockerfile 模板） |
| `port` | int 1–65535 | **是** | 容器监听端口与探活目标 | F054 |
| `tier` | `light` / `standard` / `performance`，默认 `light` | 否 | 档位 **code**；不存在或已停用 → 16223 | F055 → `app_version.tier_id` → F054 限额 |
| `capabilities.models[]` | `[{name}]` | 否 | 模型管理页原名 | F055（本期非空即拒 16231）/ F051 |
| `capabilities.knowledge_bases[]` | `[{name}]` 或 `[{id}]` | 否 | 声明即授权（审批通过后） | F055（同上）/ F052 |
| `database.tables[]` | 表结构声明 | 否 | 本期不建表、只给 hints（D3） | F055（后置）|
| `egress.domains[]` | `[str]` | 否 | 出站白名单；本期只校验格式 | F054 D12（后置） |

**未知字段一律拒绝**（`extra='forbid'`，D3）。**密钥引用字段（任何形式）出现 → 16230**（AC-56）。

**④ 审批场景契约**

- `scenario_code = "app_publish_request"`；`business_key = str(deployment_id)`；`applicant_user_id = app.owner_user_id`（**自然人，非服务账号**，INV-29）。
- **⚠️ `ApprovalGateRequest` 还有两个无默认值的必填字段**（`approval/domain/schemas/approval_center_schema.py:19-20`，漏填 = 构造即 `ValidationError`）：`business_resource_type = "app"` · `business_resource_id = str(app_id)`。
  - 它们是**审批单自身**的业务对象挂点（审批中心按它定位"这单在审什么"），**不是 AC-01「审计须能按对象应用筛选」的落点**——审批族审计的 `target_type` 仍恒为 `approval_instance` / `approval_task`（`approval_gate.py:159`，坑 20），筛选面靠 F055 自建的 `app.release.*` 族（`target_type='app_version'`，§4.2 ⑥）。两条路径**互不替代**：前者让审批单可回指应用，后者让审计页可按应用筛。填 `app` / `app_id` 顺带让"以后审批侧也能按应用查"成为可能，但 AC-01 不依赖它。
- `build_detail(req)` → `detail_snapshot`（**结构化，不是扁平 key-value**）：

```
{ "app_name": str, "release_kind_text": str, "tier_name": str,        # ← 扁平兜底三键（D7）
  "app_id": str, "app_slug": str, "owner_user_id": int, "owner_user_name": str,
  "source": "cli" | "workbench",
  "release_kind": "initial" | "iteration",
  "version_id": str, "version_no": int, "submitted_at": iso8601,
  "tier": {"code","name","cpu_millicores","memory_mb"},
  "capabilities": [{"kind":"model"|"knowledge_base","name","summary","state"}],
  "visibility_snapshot": [{"subject_type","subject_name"}],
  "schema_change": {"has_breaking": bool, "items":[{"table","column","op"}]} | null,
  "approver_note": "no_department_admin_source" | null }
```

  **client 侧必须把嵌套键加进 `DETAIL_INTERNAL_KEYS`**（`ApprovalCenterDialog.tsx:136`），否则通用两列网格会把它们渲染成 `[object Object]`（坑 7）。
- 节点配置（seed 落库形态）：单条 catch-all 分支（`match_config={}`）→ 单节点 `node_mode='or'`，`approver_config.sources = [{"type":"department_admin"},{"type":"tenant_admin"}]`。

**⑤ 新表**

| 表 | 关键列 | 说明 |
|---|---|---|
| `app_deployment` | `id` · `tenant_id` · `app_id`（首发时在 create_draft 后回填）· `owner_user_id` · `submitted_by_user_id`（服务账号）· `version_id`(nullable) · `approval_instance_id`(nullable) · `stage`(VARCHAR32 显式列) · `status`(VARCHAR16) · `code_object_key` · `manifest`(JsonType) · `tier_code` · `failure`(JsonType) · `scan_result`(JsonType) · `create_time` / `update_time` | 一次发布尝试；**预检失败的尝试只有这张表有记录**（AC-02）。带 `tenant_id`、走自动过滤（K6） |
| `resource_tier` | `id` · `code`(unique) · `name` · `cpu_millicores` · `memory_mb` · `description` · `enabled` · `sort_order` · `create_time` / `update_time` | **平台级、无 `tenant_id`**（K6）；只可停用不可删（D11） |

**⑥ 审计事件族 `app.release.*`**（`target_type='app_version'`，`target_id=version_id`；metadata 恒带 `app_id` / `version_no` / `deployment_id`）

`submit` · `precheck_failed` · `scan_blocked` · `version_created` · `approval_created` · `approval_exception` · `self_approval` · `approved` · `rejected` · `withdrawn` · `cancelled` · `online` · `pending_online` · `manual_publish` · `capability_declared`（能力声明变更，AC-55）· `rollback`（D6 的两阶段补偿）

**四处 lockstep**：`audit_log.py` 的 `_UI_VISIBLE_V2_ACTIONS`（`:193` 起、元组止于 `:259`）+ `_V2_NAMESPACE_TO_ACTION_PREFIX`（`:261`）、platform `controllers/API/log.ts` 的 `actions` / `getModulesApi`、`bs.json` 的 `log.systemIdEnum` / `log.eventTypeEnum` 三语（坑 21）。

> ✅ **`app` 命名空间已是既成事实**：`_V2_NAMESPACE_TO_ACTION_PREFIX` 里的 `"app": "app."` 已由 F054 落码写入（`audit_log.py:266`），`app.*` 的 UI 白名单条目也已就位。**F055 只需往 `_UI_VISIBLE_V2_ACTIONS` 追加 `app.release.*` 的 action 值**（外加前端两处 + 三语），不要重复建命名空间。

**⑦ 通知事件名（`action_code`）**

| 事件 | action_code | 接收方 | 前端成本 |
|---|---|---|---|
| 审批单生成 | `approval_task_pending`（既有） | 审批人 | **一处代码**：`APPROVAL_TASK_SCENARIO_TEXT_KEYS` 加 `app_publish_request` + 三语 |
| 通过 / 驳回 / 撤回 | `approval_instance_approved` / `approval_task_rejected` / `approval_instance_withdrawn`（既有） | owner / 审批人 | 零 |
| 删除致取消 | **`approval_instance_cancelled`（新）** | 审批人 | 三语 key（既有 `approval_exception_cancelled` 通知的是申请人，语义相反，坑 6） |
| 待上线（资源不足） | **`app_publish_pending_capacity`（新，非审批类）** | owner + 租户管理员（Root→超管） | **零代码**，只加三语（走 `com_notifications_action_{code}` 兜底，D14） |
| 待上线（上线失败） | **`app_publish_deploy_failed`（新，非审批类）** | 同上 | 同上 |

> **⚠️ 非审批类两条的发送契约（写死，别只记 action_code）**：`message_type` **不得为 `request` / `approve`**。
> `isApprovalMessageType(message_type, action_code)`（`client/src/components/NotificationsDialog.tsx:152-156`）在 `message_type === "request" || "approve"` 时**也为真**，并不只看 `APPROVAL_CENTER_ACTION_CODES` 白名单——按钮显示条件是 `isApprovalMessageType(...) && isPendingApprovalStatus(status) && !APPROVAL_NO_BUTTON_ACTION_CODES.has(...)`。
> → D14「新 action_code 天然没有跳转按钮」**只在发送侧用中性 `message_type` 时成立**；用错类型 = 通知里长出一个点了会报错的跳转按钮，AC-65「消息只通知不承载操作」当场破。
| 资源释放后可手动上线 / 能力被收回 | — | — | **不主动提示**（AC-64），发布面自查 |

**⑧ 错误码段 162**（`bisheng/common/errcode/app_publish.py`；落码同 PR 回写 constitution C5 + 三语 `api_errors`）

| 段 | 用途 | 示例 |
|---|---|---|
| 16200–16219 | 接收与包 | `16201` 包超出大小上限 · `16202` 包解析失败 / 非法路径条目 · `16203` 缺 `bisheng-app.yaml` · `16205` 该应用归属他人 · `16207` 工场运行时层未启用 |
| 16220–16239 | 预检 | `16221` manifest 校验失败 · `16222` `runtime` 取值不支持 · `16223` 档位不存在或已停用 · `16224` 能力声明引用不可解析 · **`16225` 审批场景未启用**（Gate 抛异常，D6）· **`16226` 运行环境容量不足**（构建 / 上线准入闸，D4）· `16227` 依赖构建失败 · `16228` 启动探活失败 · `16229` 结构变更未确认 · `16230` 能力声明含密钥引用（本版不支持）· `16231` 本环境未启用能力总线 |
| 16240–16249 | 密钥扫描 | `16241` 发布前密钥扫描命中 |
| 16250–16269 | 发布流程 | `16251` 已存在在途审批单 · `16252` 待上线态不接受新提交 · `16253` 版本记录不存在 · `16254` 仅 owner 可执行 · `16255` 当前应用态不允许该动作 |
| 16270–16289 | 能力总线 | `16273` 该能力已被收回 · `16274` 未在能力声明中的能力 |
| 16290–16299 | 运行期凭据 | `16291` 应用运行期凭据主体不可用 |

> **一码一义（C5）——两处曾经犯过的错，落码前对照**：
> - **`16225` 只归「审批场景未启用」**。构建期容量不足是 **`16226`**（本文早期版本把两者写成同一个 16225）。二者的 CLI 处置南辕北辙：前者是"平台没 seed 审批场景，找管理员"，后者是"机器没资源，等一会儿或手动上线"，三语文案也必然写错一条。
> - **档位失败只有 `16223` 一个码**（"不存在或已停用"）。原表里的 `16271` 档位不存在 / `16272` 档位已停用 **已删**——同一次失败落两套码，三语文案写了也永不出现。若日后产品要求区分两种成因，用 `details` 里的 `reason: "not_found" | "disabled"` 表达，**不要拆码**。
> - **原 `16226`「依赖托管契约外的中间件」已删**：D4 明确本轮不做静态依赖分析，判据下沉为探活失败（`16228`），该码**没有任何写入方**。号已改派给容量不足。
>
> `withdraw` 终态守卫用 **approval 段 181xx**，不占 162（D10）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng/app_publish/api/router.py` · `api/endpoints/{deploy,deployment_status,publish_status,resource_tier}.py` | `/api/v2/apps` 管线端点（逐个挂 `open_api_subject("app:manage")`）+ `/api/v1` 发布状态与档位读写端点 | 不直接 import `database/models`（RULE-3）；不自建鉴权（K8） |
| `domain/services/publish_pipeline_service.py` | 管线编排：同步前段 `accept()` + 异步后段 `run_pipeline()` 的阶段机与 `app_deployment` 推进 | 不直连 docker；不写应用态（只调 F054） |
| `domain/services/package_service.py` | 落 MinIO、解包安全闸、大小 / 条目闸、孤儿快照清理 | 不解析业务语义 |
| `domain/schemas/app_manifest.py` | **AppManifest 权威 schema**（pydantic v2，`extra='forbid'`） | 不含校验之外的业务逻辑；F053 / F054 只消费不改 |
| `domain/services/precheck_service.py` | 预检阶段编排（manifest → 引用 → 构建 → 探活）与失败五元组构造 | 不做扫描（`secret_scanner` 的事） |
| `domain/services/secret_scanner.py` | `SECRET_SCAN_RULES` 常量表 + 扫描执行 + 命中上报（**永不含值**） | 不判鉴权对错（presence check）；不做抑制机制 |
| `domain/services/publish_approval_service.py` | Gate 组装、在途 / 待上线前置闸、首节点通知自发 | 不实现 handler 协议本体 |
| `domain/services/app_publish_scenario_handler.py` | 场景 handler（`build_detail` / `resolve_approvers` 出口过滤 / 四个回调） | **不改 `approver_resolver`**（AC-17 的过滤只在本场景出口做） |
| `domain/services/version_service.py` | `app_version` 的 INSERT 与 `mark_terminal_state()`（**唯一被授权 UPDATE `terminal_state` 的地方**） | 不 UPDATE 其它列（F054 D8 的只增不改） |
| `domain/services/resource_tier_service.py` | 档位 CRUD（**无删除**）、seed、选档解析、使用中应用数 | 不进 `quota_config`（D11） |
| `domain/services/publish_notification_service.py` | 六类触达的收件人解析与发送（复用 `ApprovalNotificationService` / `message_service`） | 不承载操作（AC-65） |
| `domain/services/publish_status_service.py` | AC-38 的唯一实现（发布面 + F052 MCP 共用） | 不写库 |
| `app_publish/domain/models/app_deployment.py` | `app_deployment` 表的 SQLModel 定义与 DAO | 不参与构建页 UNION（故**不必**像 F054 三表那样放 `database/models/`） |
| **`database/models/resource_tier.py`**（**不放 `app_publish/domain/models/`**） | `resource_tier` 表的 SQLModel 定义与 DAO —— **F054 只读、F055 读写**，放共享层避免 `app_runtime` 反向 import `app_publish`（C1 / D16） | 不含业务逻辑（seed / 选档 / 停用判定全在 `ResourceTierService`） |
| `app_publish/composition.py` | 组合根：注册 F054 删除钩子 + 场景 handler；**API 与 worker 两处各调一次**（D16 ⚠️） | — |
| `bisheng/worker/app_publish/tasks.py` | Celery 任务 `run_pipeline(deployment_id)`（默认队列） | 不重复实现阶段逻辑（调 service） |
| **存量改动** `approval/domain/services/approver_resolver.py` | `tenant_admin` 分支改真租户管理员 + Root 回退（D8） | 不在这里做申请人过滤（那是场景 handler 的事） |
| **存量改动** `approval/domain/services/approval_center_service.py` | `withdraw_instance` 终态守卫（AC-22）+ 新增 `cancel_instance_by_business`（AC-35） | — |
| **存量改动** `common/init_data.py` + `approval/domain/services/approval_seed_service.py` | seed 参数化 `tenant_id` + 新场景条目 | 不改幂等判据（按 `tenant_id+scenario_code`） |
| **存量改动** `tenant/domain/services/{tenant_service,tenant_mount_service}.py` | **两条**新建租户路径各挂一次 seed 钩子 | 不改租户创建的其它步骤 |
| `client/src/components/approval/AppPublishDetailPanel.tsx` | 审批单四分区渲染（按 `scenario_code` 早分派） | 不建通用注册表（D14，等第二个场景） |
| `platform/src/pages/BuildPage/hostedApp/publish/*.tsx` | 发布面各区块（填 F054 的 slot） | 不碰 F054 的壳与 `PublishTab.tsx`；可见范围区留给 F056 |

---

## 5. 已知坑 / 反直觉事实

> 代码里看不出、踩过才知道的东西。每条带"如果不知道会怎样"与"在哪处理"。

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **`approver_resolver.py:63-74` 的 `tenant_admin` 解析的是全站系统超管**（`UserRoleDao.aget_roles_user([AdminRole])`），与 `req.tenant_id` 完全无关；注释 `:64-66` 自认 "pragmatic approximation" | 多租户下所有租户的发布审批压到超管一人；以为"配了租户管理员就行"，实际那个人根本收不到 | D8 前置 1；改动**对一切既有场景立即生效** → release note（AC-21） |
| 2 | **`list_tenant_admins` 对 Root 租户恒返回 `[]` 是显式设计不是 bug**（`tenant_admin_service.py:95-96`，注释 `:10-12` 说明是 INV-T3 的设计） | 单租户部署（114 大概率如此）首次发布必然 approver_empty → 发布卡死在异常态 | D8 前置 2 **新写一个条件回退函数**；⚠️ **不要复用 `approval_notification_service.py:122-152 _get_admin_recipient_ids`**——它是**无条件 union**（任何租户都并入全站超管），拿它做审批人解析等于把 AC-21 要修的缺陷原样搬过来（D8 的 ⚠️ 段） |
| 3 | **新建租户有两条路径**：`TenantService.acreate_tenant`（管理后台，`tenant_service.py:88-157`）**和** `TenantMountService.mount_child`（`tenant_mount_service.py:158-272`）。`mvp-114-path.md:50` 与 PRD-1 §3.3 锚点表**都只写了后者** | 从管理后台建的租户永远没有发布审批场景，第一次 deploy 就 `ApprovalScenarioDisabledError`；且这类 bug 要等到客户建第二个租户才暴露 | D8 前置 3，**两条都挂**；形状照抄 `tenant_service.py:140-149` 的 `seed_builtin_skills` |
| 4 | **`withdraw_instance` 无终态守卫**（`approval_center_service.py:418-492`，`:430` 只校验申请人） | 已 EXECUTED / EXCEPTION / WITHDRAWN 的实例可被反复撤回并**重复触发 `on_withdrawn`** → 已上线的版本被反复标成 `withdrawn` | D10；修点 `:432` 之前，错误码走 approval 段 181xx |
| 5 | **Gate 建完首节点 task 后不发站内信**（`approval_gate.py:232-248` 只建 task + 审计），三个既有场景都在自己那侧补发 | 审批人永远收不到"有单待审"的通知，只能自己去审批中心翻 → AC-64 直接不成立 | D7；`publish_approval_service` 在 Gate 返回 PENDING 后自发 |
| 6 | **没有"取消在途实例"的通用入口**：唯一置 `CANCELLED` 的 `cancel_exception_api`（`approval_exception_service.py:159-230`）**从 exception 记录起手**，且 `:221` 通知的是**申请人** | 想复用它做 AC-35 → 应用删除时通知了 owner（人已经知道，是他删的）而审批人还在待办里看到一个不存在的应用 | D10 新增 `cancel_instance_by_business`（放审批模块，通知**审批人**） |
| 7 | **`detail_snapshot` 无任何 schema**（`approval_instance.py:62` 是裸 `JsonType`），前端把它拍平成两列网格（`ApprovalCenterDialog.tsx:696-724`）：**数组被 `join(", ")`**（`:718`）、**对象变 `[object Object]`**、未在 `localizeFieldKey`（`:138-150`，仅 8 条）里的 key **原样显示英文键名** | 能力声明数组渲染成一坨逗号串、档位对象显示 `[object Object]`、字段名显示 `release_kind` —— 审批人看不懂在审什么 | D7 结构化 payload + client 早分派 + 嵌套键加进 `DETAIL_INTERNAL_KEYS`（`:136`） |
| 8 | **Gate 的重复提交拦截是"静默返回既有实例"**（`approval_gate.py:93-103`，按 `(tenant_id, scenario_code, business_key, applicant_user_id)` 且 status ∈ `pending/exception/execute_failed`） | AC-03 靠 Gate 兜 → 第二次 deploy 得到 200 + 上一个审批单，CLI 显示"提交成功"但实际什么都没提交 | K2；`publish_approval_service` 在**调 Gate 之前**自查并抛 16251 |
| 9 | **`resolve_approvers` 由 handler 自己实现**（`approval_gate.py:195`），通用来源要**显式转调** `resolve_approvers_from_sources`（范式 `knowledge_space_subscribe_scenario_handler.py:111-118`） | handler 里返回 `[]` 或忘了转调 → 每次发布都 approver_empty 异常态，且现象与"没配审批人"完全一样、极难定位 | D7 handler 契约；单测断言"seed 后首次 Gate 返回 PENDING 且 approvers 非空" |
| 10 | **outbox 判成败只看是否抛异常**（`worker/approval/tasks.py:111-120`），但**"待上线（资源不足 / 上线失败）"是产品终态不是失败**（AC-31 要求审批单保持通过） | 把容量不足 raise 出去 → instance 变 `execute_failed` + 建异常 + 通知管理员，产品上是"审批失败了"，与 AC-31 直接矛盾；反过来把编排器不可达吞掉 → 假成功 | D9 的判据：**"应用最终会不会自己好起来"——会就返回，不会就抛** |
| 11 | **`_dispatch_outbox` 在 `approval_center_service.py:993-997` 无 try/except**（而 `approval_gate.py:387-396` 的 PASS 分支有） | broker 抖动时 instance 已置 APPROVED 但 outbox 未派发 → 审批显示通过、应用永远不上线，且没有任何异常记录 | F055 不改它，但要知道补偿入口是管理端 `POST /approval/admin/exceptions/{id}/retry`；发布面的"待上线"自查是第二道网 |
| 12 | **Celery 租户 ContextVar 经 header 自动透传**（`worker/tenant_context.py:63-90`，无 header 时兜底 `DEFAULT_TENANT_ID`），但**组合根注册不会自动在 worker 进程执行** | `on_approved` 在 worker 里重建 handler 时工厂分支存在、但删除钩子 / handler 注册若只挂 API lifespan，则 worker 侧行为半失效且只在多进程下暴露 | D16 ⚠️；`composition.py` 由 `main.py` 与 `worker/main.py` 各调一次（幂等） |
| 13 | **公共桶经 nginx `location ~ ^(/workspace/bisheng|bisheng|tmp-dir)/`（`src/frontend/nginx.conf:49`）把任意 key 匿名转发出去** | 代码快照放公共桶 = 知道路径就能匿名下载别人的源码 | K5；独立桶 `bisheng-apps`，不挂 nginx location、不设匿名策略 |
| 14 | **`MinioStorage._init_bucket_conf`（`minio_storage.py:291-330`）只建 `public_bucket` 与 `tmp_bucket`**，且 `:311-316` **只在 `NoSuchBucketPolicy` 时才 set 策略**（存量环境既有策略不会被覆盖） | `bisheng-apps` 桶不存在 → 第一次上传直接 `NoSuchBucket`；以为改了 `_init_bucket_conf` 就能收窄存量环境策略（不会） | `package_service` 启动时显式 `create_bucket_sync`（`:335-337`，幂等） |
| 15 | **tar 比 zip 多四类危险条目**：符号链接 / 硬链接 / 设备文件 / FIFO。仓内唯一解包先例 `skill_store.py:171-176 _safe_rel_path` 只防绝对路径与 `..`（zip 没有前四类） | 解包时符号链接指向 `/etc/passwd`，后续写入即越狱；硬链接可读取宿主任意文件 | D2 解包安全闸；单测覆盖六类恶意条目 |
| 16 | **`/api/v1/upload/icon` 返回的 `file_path` 是 `get_share_link` 预签名 URL（默认 7 天过期）**，`relative_path` 才是 object_name（`core/cache/utils.py:202-206`）；且对象名**恒写死 `.png`** 不管原扩展名（`api/v1/endpoints.py:178-194`） | 把 `file_path` 存进 `app.logo` → 一周后全站托管应用图标 403 | D12；落库存 `relative_path`（object_name） |
| 17 | **`flow_version` 是可变指针不是版本记录**：有 `update_version` / `delete_flow_version` / `change_current_version`（`database/models/flow_version.py:73/196/207`），且 `data` 全量 JSON 入库曾在 DM8 上撑爆 undo | 向它借语义或借表 → AC-40「正式版本记录不被覆盖或删除」当场破功 | D6 用 F054 的 `app_version`（只 INSERT + `terminal_state` 单列例外） |
| 18 | **`quota_service.py:57 VALID_QUOTA_KEYS` 是闭合白名单**，`validate_quota_config` 会拒未知 key；配额还有三级取值（admin 短路 → 角色 max → 租户 min） | 把档位塞进 `tenant.quota_config` → 保存直接被拒；即便绕过，三级取值会把 CPU 规格算成一个荒谬的数，还污染 `/me/quotas` 前端面 | D11 独立建表 |
| 19 | **`app_version` 没有 `tenant_id` 列**（F054 K5 ②），登记进 `_TENANT_AWARE_MODEL_MODULES` 后**仍不受自动过滤** | 任何 `select(AppVersion).where(id=...)` 起手的读写都是跨租户裸奔 | 一切按 `version_id` 起手的操作**先取 `app` 行校验归属**（`on_approved` 步骤 1、状态接口、版本列表） |
| 20 | **审批族审计的 `target_type` 恒为 `approval_instance` / `approval_task`**（`approval_gate.py:159` 等） | AC-01「须能按对象应用筛选」筛不到任何东西；以为"审批中心已经计审计了"就不写自己的事件 | D12 另起 `app.release.*` 族 |
| 21 | **审计 UI 可见性是手工白名单**：不在 `audit_log.py` 的 `_UI_VISIBLE_V2_ACTIONS`（`:193`–`:259`）里的 v2 action **写库但不出现在平台"系统操作"页与筛选下拉**；注释（元组前后两段）要求与前端 `controllers/API/log.ts` 及 `bs.json` 三语 **lockstep** | 事件写了、DB 里有、审计页一条看不到，排查半天以为审计没写 | D12 的四处 lockstep；tasks 单列一条 |
| 22 | **platform 拦截器对 `403/404` 整页跳转 `/403`**（`platform/src/controllers/request.ts:160-166`） | 非 owner 打开别人的应用详情页 → 整页跳走，而不是看到一个"你没有权限操作"的区块 | K11 ②；发布面只读接口用业务码或 `silent: true` |
| 23 | **platform 场景配置的 `APPROVER_SOURCE_OPTIONS`（`ApprovalPage/index.tsx:590-597`）没有 `tenant_admin`**，而 `APPROVER_SOURCE_LABEL_KEYS`（`:180-188`）与三语（`platform/public/locales/zh-Hans/bs.json` 的 `approverSource.tenant_admin`，`:1832` / `:1842` 两处）早就有 | 租户管理员一旦改配审批人，就**再也没法把「租户管理员」这个来源加回来**（下拉里没有），AC-19 半残 | D14；同批补该选项 + preset 的 `approver_source_types` 含它 |
| 24 | **审批场景名是后端硬编码中文**（`approval_registry.py:19/30/40`），前端直接渲染 `s.scenario_name`（`:1660`） | 以为新场景会自动三语，结果日语环境显示"应用发布" | D14 接受中文单语（与既有三场景一致），别默认它三语 |
| 25 | **`ApprovalCenterDialog.tsx` 有 4 条冻结的硬编码中文违规**（`client/eslint-suppressions.json:1714-1723`），其中 `:331` 的 `"同意"/"驳回"` 正是 AC-24 要改的那一行 | 改了这行但没抽 i18n → `pnpm lint` 挂；或者不知道"谁触碰谁还债"规则，PR 被打回 | D14；tasks 单列"抽 4 条中文 + `pnpm lint:prune`" |
| 26 | **F054 没有提供"创建草稿应用"的服务方法**（§4.2 ② 只有五个状态动作 + `stage_version` + `update_meta`），而 release-contract 定「本册唯一创建路径 = CLI 首发」 | 首发 deploy 时无处建 `app` 行 → 要么 F055 直写 `app` 表（违反决议-8「F054 是应用态唯一写入方」），要么整条剧本卡在第一步 | D2；需 F054 补 `AppProvisionService.create_draft(...)`，已登记 §6.2 |
| 27 | **F054 `DEFAULT_TIERS`（design:294 = 0.5/512 · 1/1024 · 2/2048「增强」）与本 spec AC-44（1C/2G · 2C/4G · 4C/8G「性能」）数值与命名都冲突**，而 F054 D11 要求 F055 的 seed **从该常量读取落库** | 两边各按各的实现 → seed 一落库，F054 的兜底常量与 DB 表给出两套规格，`docker inspect` 核对 AC-63 时必然对不上 | D11 裁定以 spec 为准并**回写 F054 常量**；114 上另用 `settings.app_runtime.default_tiers` 下调（否则 1C/2G 过不了容量闸） |
| 28 | **申请人必须是自然人 owner、不是发起 deploy 的服务账号**（INV-29：服务账号不出现在任何面向人的场景），主部门也要取 **owner** 的（`principal.subject_user_id` 是服务账号，它没有部门） | 审批单申请人显示成一个服务账号名；`department_admin` 来源按服务账号的部门解析（服务账号会被自动兜底进 guest 部门）→ 审批人解析到完全无关的人 | D7；`applicant_user_id = principal.resource_owner_user_id` |
| 29 | **`CardSelectVersion`（`platform/src/pages/BuildPage/CardSelectVersion.tsx`）切换即写库**（`:25-31` 调 `changeCurrentVersion`），且 `version_list` 对托管应用**恒空** | 想复用它做版本列表 → 点一下就去改了某个工作流的当前版本；或者渲染出来永远是空 | D15 另起只读组件 |
| 30 | **client 审批弹窗宽度上限 800px**（`ApprovalCenterDialog.tsx:392`） | 审读视图（左文件树 + 右只读代码 + 4 tab）实施到一半发现塞不进去，当场返工 | D14 案 A（review 态放宽到 1200px）；MVP 期整块不渲染 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v2/apps/deploy` · `GET /api/v2/apps/deployments/{id}` · `GET /api/v2/apps/{id}/logs`（§4.2 ①） | HTTP（`Bearer bs-sak-…` + `app:manage`） | **F053** CLI `deploy` / `logs` |
| **AppManifest 形态**（§4.2 ③，权威 schema `app_publish/domain/schemas/app_manifest.py`） | 数据契约（YAML） | **F053**（打包 / 本地必填校验 / 技能包「部署纳管」包的写法章节）· **F054**（`runtime` / `port` / `tier` / `egress.domains`）· release-contract 表 1 |
| `GET /api/v1/apps/{app_id}/publish-status` + `PublishStatusService.get_publish_status()`（§4.2 ②） | HTTP + 内部 Python | platform 发布面 · **F052** MCP 应用状态工具（**同一方法**，AC-38 两处一致） |
| `ResourceTier` 实体（模型落 **`database/models/resource_tier.py`** 供两模块共读）+ `ResourceTierService`（三档 seed / 选档解析 / **只可停用不可删**） | 表 + 内部 Python | **F054**（按 `tier_id` 解析规格设实例限额，AC-63/64；「不可删」是 F054 可以依赖的不变量；**F054 只读**——模型放共享层就是为了不让 `app_runtime` 反向 import `app_publish`，C1） · **F056**（列表展示） |
| `app_version` 的 INSERT 与 `terminal_state` 单列更新（`VersionService`） | 内部 Python（F054 授权的唯一例外） | 版本 tab · 发布面 · **F056** |
| 审批场景 `app_publish_request`（preset / handler / 工厂分支 / seed）+ `detail_snapshot` 结构（§4.2 ④） | 审批模块扩展点 + 数据契约 | 审批中心引擎 · **client 审批弹窗**（`AppPublishDetailPanel`） |
| **`approver_resolver.tenant_admin` 的语义修正**（真租户管理员 + Root 回退超管） | **行为变更**（全场景） | 频道订阅 / 知识空间加入两个既有场景与一切人工配置的流程 —— **release note 必须声明**（AC-21） |
| `seed_approval_scenarios_for_tenant(tenant_id)` + 两条租户创建路径的钩子 | 内部 Python + 注册点 | 新建租户（`acreate_tenant` / `mount_child`）；后续任何新审批场景 seed 复用同一入口 |
| `ApprovalCenterService.cancel_instance_by_business(...)`（置 CANCELLED + 取消 tasks + **通知审批人** + `on_cancelled`） | 内部 Python（放审批模块） | **F054** 删除钩子 → F055 组合根注册的实现；未来任何"业务对象消失需取消在途单"的场景 |
| `withdraw_instance` 终态守卫（非 PENDING 一律拒） | 行为变更（全场景） | 审批中心所有场景（AC-22） |
| `SECRET_SCAN_RULES` 规则集 + `scan_package()` | 内部 Python 常量 + 函数 | **PRD-2 平台内发布**（AC-10「与平台内发布同一规则集」的落地手段 = 只有一份常量） |
| `app.release.*` 审计事件族（§4.2 ⑥） | 审计事件 | **F056** 审计查询面（登记 + 查询归它，写入归本 Feature） |
| 新通知 action_code：`approval_instance_cancelled` / `app_publish_pending_capacity` / `app_publish_deploy_failed` | 站内信契约 | client `NotificationsDialog`（前两者需三语 key，后两者零代码） |
| 错误码段 **162**（§4.2 ⑧） | 错误码 | 全部调用方；**分配已在上游登记完毕**（release-contract「已分配模块编码」表 + constitution C5 均已写 `162 = F055`）→ 落码同 PR 只需新建 `common/errcode/app_publish.py` + 三语 `api_errors`，**不要再去改那两张表**（K9） |
| `GET /api/v2/apps/deploy-limits`（包体 / 解包 / 条目三闸的当前值，§4.2 ①） | HTTP（`app:manage`） | **F053** 打包后上传前自查（AC-32）；取不到时退化为服务端 16201 兜底 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| **F054 `AppStateService.{publish, manual_publish, stage_version}`**（应用态唯一写入方，决议-8） | 内部 Python | 方法签名或"前态断言 → 16102"语义变化 → `on_approved` 的三分支判定失准；`publish` 若改成抛异常表达容量不足，会撞上 K3 的 outbox 语义 |
| **F054 `AppMetaService.update_meta`** + `PATCH /api/v1/apps/{app_id}` | 内部 Python | AC-05 的元信息更新与详情页共用一处实现；若 F054 给它加上"必须经审批"的闸，AC-05「不等审批」当场破 |
| **F054 `AppProvisionService.create_draft(...)` —— ⚠️ 尚不存在，需 F054 补**（坑 26） | 内部 Python | 不补则首发 deploy 无处建 `app` 行；F055 **不得**绕过它直写 `app` 表 |
| **F054 `lifecycle_hooks.register_app_deleted_hook`**（删除钩子；**失败不回滚删除**） | 内部 Python 回调 | 钩子未送达 → 在途审批单成僵尸 → **F055 侧的读侧防御是硬要求**（D10） |
| **F054 `orchestrator_client.{build, probe, admission}`** + `GET /v1/runtime/status.supported_runtimes` | 内部 Python 门面 | manager 不可达 → **异步段**全部预检 16121/16227（**同步段不发 RPC**，D4）；`supported_runtimes` 是 AC-07 的取值真相，F055 同步段用的本地枚举常量是它的**副本**——**F054 加运行时模板时必须同批改这个常量**，否则新 runtime 会在同步段被误拒 16222（这是本设计为"秒级反馈"付的显式代价） |
| **F054 `DEFAULT_TIERS` 常量**（档位 seed 的唯一代码来源） | 内部 Python 常量 | 数值与本 spec AC-44 冲突（坑 27），**需回写 F054**；改常量而不重跑 seed 不会影响存量表（幂等按 `code` 跳过） |
| **F054 `app_version` 表**（含 `terminal_state` / `tier_id` / `code_object_key` 列）与 `app.pending_version_id` | 表结构 | 列改名 → 版本记录与派生显示同时坏；`app_version` 无 `tenant_id`（坑 19） |
| **F054 MinIO 桶与键布局**（`bisheng-apps`、`apps/{app_id}/versions/{version_id}/code.tar.gz`） | 存储契约 | 键布局改动 → 快照取回、审读视图、预览拉起三处同时失效 |
| **F049 `open_api_subject(scope)` / `verify_open_api_access` / `OpenApiPrincipal`**（含 `resource_owner_user_id`） | 内部 Python `Depends` | 工厂签名变化 → 全部 v2 端点失守；`resource_owner_user_id` 若改成"可追溯变更"，AC-04 的归属判定要重议 |
| **F049 `api_credential.KEY_PREFIX` / `KEY_SECRET_LENGTH`** | 内部 Python 常量 | 前缀变更时扫描规则自动跟随（这正是不硬编码的理由） |
| **F049 `CredentialService.issue/revoke` + `SUBJECT_RESOLVERS` 注册点**（`hosted_app` 主体，**后置**） | 内部 Python | 未注册解析器前该 kind 在 `/api/v2` 上按 `26002` 拒绝（F049 design D2 已声明） |
| **审批中心引擎**：`ApprovalGate.request_or_pass` · `ApprovalRegistry` · `approval_runtime_handler_factory` · `ApprovalCenterService.decide_task` / `withdraw_instance` · `approval_outbox_service` · `ApprovalNotificationService` | 内部 Python + 注册点 | Gate 的两个"静默"语义（K2）· outbox 的抛异常判据（K3）· 工厂漏分支（K1 ③）—— 三者任一变化都会让发布流程静默半失效；**改这些代码必须同 PR 更新 `.claude/skills/approval-module/SKILL.md`** |
| `UserDepartmentDao.aget_user_primary_department`（`database/models/department.py:1377-1388`，只取主部门不回溯） | 内部 Python | 若改成向上回溯，AC-14「只取主部门」当场破 |
| `AuditLogDao.ainsert_v2` + `_UI_VISIBLE_V2_ACTIONS` / `_V2_NAMESPACE_TO_ACTION_PREFIX` | 内部 API + 白名单 | 白名单未加 = 写库但审计页看不到（坑 21） |
| `MinioStorage`（`put_object` / `get_object` / `create_bucket_sync`）+ 独立桶 `bisheng-apps` | 基础设施 | `_init_bucket_conf` 不建新桶（坑 14）；桶策略在存量环境不会被收窄 |
| Celery 默认队列 + `worker/tenant_context.py` 的 header 透传 | 基础设施 | 部署缺 default worker → 管线后段与审批 outbox 双双不执行（K12） |
| `settings.app_runtime.*`（档位默认值 / 预览超时 / 包体上限覆盖） | 部署配置 | `load_settings_from_yaml` 对未知顶层键 `raise KeyError` → **必须先发代码再改 YAML**（K10） |
| client / platform 既有件：`ApprovalCenterDialog` · `NotificationsDialog` · `ApprovalPage` · `hostedApp` 壳 · `useHostedAppActions` · `bs-ui/*` | 前端组件 | `ApprovalCenterDialog` 是 1037 行单文件且有冻结违规（坑 25）；`hostedApp` 壳归 F054，F055 只填 slot |

---

## 7. 测试与可观测

**分层策略**（不重复 tasks.md 的清单）：

- **单元**（`test/app_publish/`，`asyncio_mode=auto`）：
  - **AppManifest 校验矩阵**：三个必填项各缺一次 · `runtime` 越界 · `port` 越界 · 未知字段（`extra='forbid'`）· `manifest_version` 超前 · 密钥引用出现 → 各自断言 `failure.code` 与 `details` 结构（AC-07 / AC-11 / AC-56）。
  - **密钥扫描规则集遍历**（AC-10 的直接承载）：每条规则一个正样本必命中、一个反样本必不命中，且断言输出的 JSON 序列化结果**不含样本密钥子串**；另测二进制跳过、大文件 `skipped` 可见、`bs-sak-` 规则随 `KEY_PREFIX` 常量变化。
  - **解包安全闸**：绝对路径 / `..` 穿越 / 符号链接 / 硬链接 / 设备文件 / FIFO 六类恶意条目全部被拒（坑 15）；条目数闸与解包大小闸。
  - **审批人解析**：seed 后首次 Gate 返回 PENDING 且 approvers 非空（坑 9）· 申请人在候选中被过滤（AC-17）· 仅一名管理员且无其他候选时保留本人 + `self_approval` 标注（**并发两单：一自审一非自审 → 审计里 `self_approval` 恰一条且挂对 deployment**，验证 handler 未被复用，D7）· owner 无主部门时落到租户管理员（AC-14）· **Root 租户回退超管**（AC-15）· 两来源皆空 → `decision=EXCEPTION`（AC-18，**断言不抛异常**）。
  - **`on_approved` 三分支**：online / 容量不足 / 上线失败三种 `publish` 返回值下 **均正常返回**；编排器不可达 **抛异常**（K3 / D9 的判据）；已下线态只 stage 不 publish（AC-36）。
  - **版本记录**：`先 Gate 后 INSERT` 的补偿路径（Gate 成功 + INSERT 失败 → 审批单被取消）· `terminal_state` 四态标注 · 「待上线」是派生显示不是列值（D6）· `UNIQUE(app_id, version_no)` 并发兜底。
  - **档位**：seed 幂等（跑两次不重复）· 停用只拦新选择（存量版本仍可解析规格）· manifest 未声明取 `light`（AC-46）· 不提供删除（AC-47 的前提）。
- **集成**（pytest + httpx，连 test 中间件 MySQL / Redis / MinIO / OpenFGA）：
  - **管线全链**：造一个最小 tar 包 → `POST /api/v2/apps/deploy`（mock `orchestrator_client` 的 build / probe）→ 断言 `app_deployment` 阶段推进、`app_version` 落行、审批单生成、`app.release.*` 审计落行且在 UI 白名单内。
  - **权限矩阵**（AC-04）：无 `app:manage` 位 → 拒 · 归属人不同的密钥 deploy 既有应用 → 16205 · 普通登录态（非 v2 凭据）打 `/api/v2/apps/deploy` → 拒。
  - **前置闸**（AC-03）：在途审批单存在时再次 deploy → 16251（**断言不是"静默返回既有实例"**，坑 8）· 待上线态提交 → 16252。
  - **三项阻塞前置的回归**：既有两个场景（频道 / 知识空间）在 `tenant_admin` 修正后仍能正常解析审批人（**这是行为变更的护栏测试**）· 新建租户（两条路径各一次）后立即 deploy 能生成审批单（AC-20）。
  - **`withdraw` 守卫**（AC-22）：对已 approved / executed / withdrawn 的实例撤回 → 拒（181xx）。
  - **删除致取消**（AC-35）：注册钩子 → `DELETE /api/v1/apps/{id}` → 断言实例 CANCELLED + PENDING task 取消 + 审批人收到通知；**钩子抛异常时删除仍成功**，且审批单读侧仍按已取消呈现（D10 防御）。
  - **多租户**：子租户账号看不到别租户的 `app_deployment`；按 `version_id` 起手的读接口跨租户被拒（坑 19）。
- **E2E**（`/e2e-test`，AC 全覆盖 + 页面手动清单）：CLI 侧由 F053 承接；本 Feature 侧覆盖发布面区块（审批状态 / 驳回理由全文 / 撤回 / 手动上线出现条件）与 client 审批弹窗（四分区渲染 / 驳回理由必填 / 通过仍可空）。

**114 手动验证**（对应 `mvp-114-path.md` §1 **步 3–4**；前置：F049 / F054 首波已部署 + `bash /opt/bisheng-ops/deploy.sh` + **先发代码再往 `config.yaml` 加 `app_runtime` 键**并全量重启 + 确认 default celery worker 在跑）：

0. **前置自检**：
   - `curl -s http://127.0.0.1:7860/api/v1/env | jq '.app_runtime_enabled, .open_platform_enabled'` → 均 `true`；
   - `SELECT code, cpu_millicores, memory_mb, enabled FROM resource_tier;` → 三行；**114 上确认 `light` 已按 `settings.app_runtime.default_tiers` 下调**（坑 27）；
   - `SELECT tenant_id, scenario_code, enabled FROM approval_scenario WHERE scenario_code='app_publish_request';` → 有行；
   - `ps -ef | grep 'celery.*worker'` → 有消费默认队列的 worker（K12）。
1. **步 3（deploy → 预检 → 扫描 → 审批单）**：用步 1–2 拿到的服务账号密钥执行 `bisheng deploy`；观察 CLI 分阶段输出 `manifest → 扫描 → 构建 → 探活 → 审批单已生成`（D5 已拍板扫描前置）；
   - **故意验证扫描**：在包里塞一行 `token = "bs-sak-<43位>"` 再 deploy → 断言被阻断、输出含 `文件:行号`、**输出里 grep 不到那 43 位串**（AC-10）；
   - **故意验证 manifest**：删掉 `runtime` 再 deploy → 16221 且 `details` 指出缺哪个字段（AC-11）；
   - **验证在途闸**：不撤回直接再 deploy → 16251（AC-03）。
2. **步 3 续（审批人解析，114 是单租户 → 必然走 Root 回退）**：`SELECT approver_user_id FROM approval_task WHERE instance_id=<N>;` → 应为平台超管（AC-15）；若 owner 有主部门且该部门设了部门管理员，则应同时出现（AC-12）；`SELECT applicant_user_id FROM approval_instance WHERE id=<N>;` → **是 owner 自然人不是服务账号**（AC-16 / 坑 28）。
3. **步 4（审批人处理 → 上线）**：用**审批人账号**（非发起人）登录 client → 铃铛应有一条"提交了应用发布申请"的站内信（AC-64；若显示裸 action_code 说明 `APPROVAL_TASK_SCENARIO_TEXT_KEYS` 没加，坑 24 邻近）→ 打开审批中心 → 详情应是**四分区**而不是两列网格（坑 7）→ 不填理由点「驳回」应**置灰点不动**（AC-24）→ 填理由点「通过」；
   - 观察 `docker ps` 出现 `bisheng-app-*` 容器、应用态 → 已上线、`app_version.terminal_state='online'`；
   - 审计页筛选「应用」命名空间应能看到 `app.release.submit` / `approval_created` / `approved` / `online` 四条且带应用名（AC-01；看不到 = 坑 21 的四处漏了一处）。
4. **待上线分支**（AC-31，可选但强烈建议）：把 `settings.app_runtime.reserve_mb` 临时调到极大值使容量闸必然拒 → 再走一遍审批通过 → 断言**审批单仍是"通过"**、应用态「待上线（资源不足）」、owner 与超管各收到一条**无跳转按钮**的站内信（AC-65）；恢复配置后在发布面点「手动上线」→ 成功且**不产生新版本记录**（决议-6）。
5. **驳回 / 撤回**：驳回一次 → owner 在发布面能看到**理由全文**（AC-33）；再提交一次后 owner 点「撤回」→ 审批人待办消失（AC-34）；对已撤回的实例再调一次 withdraw API → 应被拒（AC-22，若守卫已实现）。
6. **删除致取消**：新建一个应用提交到待审 → 删除该应用 → 断言审批单 CANCELLED 且审批人收到通知（AC-35）。

**关键日志 / 指标**：
- `app_publish.pipeline`（结构化：`deployment_id / app_id / stage / status / duration_ms / failure_code`）——**每个阶段一条**，构建阶段的 `duration_ms` 是 114 容量问题的第一指标。
- `app_publish.scan`（`deployment_id / files_scanned / files_skipped / hits`，**不含命中值**）——`files_skipped` 异常高 = 包里全是大文件或二进制，扫描等于没做。
- `app_publish.approval`（`deployment_id / instance_id / decision / approver_source_counts`）——`approver_source_counts` 记两个来源各解析出几人，approver_empty 排查第一手材料。
- 审计页 `app.release.*`；审批侧 `approval.*`（已在 UI 白名单内）。
- 排障 SQL（照 skill §11 的形状）：`SELECT stage, status, failure FROM app_deployment WHERE id=?` → `SELECT status FROM approval_instance WHERE id=?` → `SELECT status, error_summary FROM approval_outbox WHERE instance_id=?`（outbox `pending` 不动 = 没有 worker 消费默认队列）。

---

## 8. 后续改进 / 不打算做的事

- **紧随 MVP-核心（按此优先级补齐，release 必做）**：
  1. **`withdraw` 终态守卫（AC-22）** —— 排第一：它是一个**可被直接打 API 触发的既有缺陷**（坑 4），修点只有一行，却能造成已上线版本被标成已撤回；
  2. **审读视图（AC-25）+ 审批期临时预览实例（AC-26～29）** —— 没有它们，审批人审的仍是"元信息两行字"，RT-03 的核心承诺落空；落点见 **D14**（弹窗 review 态放宽 1200px）与 F054 的预览入口路由；
  3. **能力总线（AC-49～56）+ 应用运行期凭据（AC-57～60）** —— 落点方向已钉在 **D13**，开工前必读 F049 design D2「主体解析器」与 F052 门面契约；
  4. **结构演进（AC-09 / AC-42）** —— 预检加 `precheck_schema` 阶段 + 平台建表 + 改删列显式确认 + **迁移前自动留生产数据快照**（键 `apps/{app_id}/db-snapshots/{ts}.tar`，F054 design:264-273 已定）；
  5. **WB-15 版本差异（AC-41）** —— 服务端算 diff、不下发两份 tar（D15）；
  6. **资源档位管理 tab（AC-45）** —— 落点见 D11 末段；
  7. **AC-64 触达全表复核**（含催办 / 超时提醒**不做**的显式确认）。
- **已知短板（暂不投入，理由如实）**：
  - **密钥扫描是 presence check**：只查有无裸密钥 / 连接串，不判鉴权对错；运行时隔离（F054 的笼子）仍是主保障。不引入 `detect-secrets` / `gitleaks` 的理由见 D5。
  - **无行级抑制机制**：`generic_high_entropy` 会有误报，但抑制机制一开就会被用来绕过——先看真实误报率再说（D5 的重估触发条件）。
  - **AC-08 不做静态依赖分析**：读 `requirements.txt` 猜"是不是连了 MySQL"是幻觉级判据，判据下沉为探活失败 + `hints`（D4）。
  - **两阶段补偿不是原子事务**：Gate 自带 commit，无法与 `app_version` 的 INSERT 同事务（D6）——补偿路径已写死并有单测，但极端情况下（补偿本身失败）会留一个孤儿审批单，靠管理端异常处理兜。
  - **孤儿快照清理挂在下一次 deploy 上**（不起 Beat，D2）：一个再也不 deploy 的应用，其失败快照会永久留在 MinIO。存储量级（≤50MiB × 失败次数）可接受，等有第二个清理诉求时一起做定时任务。
  - **`app.release.*` 的审计 UI 可见性仍是手工白名单**（坑 21）：第三次新增事件族时才值得把可见性做成 action 的声明属性。
- **明确不做**：
  - **平台侧回滚**（RT-05 顺延；等价手段 = 本地 `git checkout` 后重新 deploy；应急止血始终是下线）· **迭代审批单变更摘要** · **应用标签设置** · **租户级实例数配额** · **审批单催办 / 超时提醒 / 升级机制** · **任何免审配置项**（INV-34）。
  - **应用运行期凭据的产品化**：管理入口 / 强制吊销 tab / 会话 key 已取消（PRD-1 §5.2）；应急处置只有下线一条路（AC-59）。
  - **密钥引用**（GOV-05 第三项）：本册不做（Discovery N4），声明中出现即预检拒（16230）。
  - **发布期 CVE 扫描 / SBOM**：v3.1。
  - **平台内造应用的发布面提交入口**：随 PRD-2（决议-2）；DEV-06 改码权交接落地后对已交接应用开放。
  - **k8s 形态下的构建 / 上线 / 终检差异**：F059；**本 Feature 的管线对形态无感**（INV-33）——这是设计约束不是巧合，任何在管线里出现 `compose` / `container` 字样的代码都是 bug。
- **必须回写上游的三项（tasks.md 首波内完成）**：
  1. **F054 design 的 `DEFAULT_TIERS`** 数值与第三档名称按 D11 的裁定回写（1C/2G · 2C/4G · 4C/8G，"增强"→"性能"），并把 D11「何时重新考虑」里的"支持删档"改为"档位只可停用不可删"；
  2. **F054 需补 `AppProvisionService.create_draft(...)`**（坑 26）——在 F054 的 §4.2 ② 与 §6.1 各加一行；
  3. **F053 spec AC-32 的上限取值口径**——补一句「上限经 `GET /api/v2/apps/deploy-limits` 取，取不到则直接上传由服务端 16201 兜底」（D2；否则 CLI 只能硬编码 50 MiB，正是 K7 反对的形态）。
  - ~~原第 1 项「把 `release-contract.md:98` 的 `_待分配_` 落定为 161/162/163/164 并回写 constitution C5」~~ **已删除：该项早已完成**（F054 落码时一并写入），release-contract 全文已无「待分配」，constitution C5 也已登记 `162 = F055 (publish pipeline)`。照原文写进 tasks.md 会产生一条空转任务，还可能让实现者去"修正"本已正确的表（K9）。
- **待 ★ 确认后才动的一项（不在 tasks.md 首波，确认前按 spec 字面顺序实现）**：**密钥扫描提前到构建之前**（D5）。它同时推翻 F055 AC-01 与 F053 AC-31a 两份已确认的 spec；确认通过后同批改三处（两份 spec 的阶段序 + 本文 D4 / §4.1）。
- **必须同步的 skill**：本 Feature 改动了审批中心的 `approver_resolver` / `withdraw_instance` / 新增 `cancel_instance_by_business` / 新增预置场景 / 新增站内信触发时机 → **同一 PR 必须更新 `.claude/skills/approval-module/SKILL.md` 的 §3 / §4 / §5 / §7 / §8**（该 skill 的维护契约明写"改完代码后问自己：本 skill 里有没有哪句话现在变成假的了"）。
- **重写 / 拆分触发条件**：管线阶段数超过 8 个或出现分支 → 阶段表升级为有向图（D4）；构建把默认 celery 队列饿死 → 拆独立队列（D1）；出现第二个自定义审批详情场景 → 抽 `SCENARIO_DETAIL_RENDERERS` 注册表（D7 / D14）；`app_publish` 的 service 数超过 12 个 → 按"管线 / 审批 / 档位与能力"三段再拆。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-17 | **评审修订（15 条，1 high / 7 medium / 7 low）**：① **错误码 16225 一码双义拆解**——构建期容量不足改 `16226`，`16225` 专归「审批场景未启用」；同批删死码（原 16226 中间件，无写入方）与重叠码（16271/16272 与 16223），成因区分改用 `details.reason`（C5，D4 / D6 / §4.2⑧）；② **D5 扫描顺序回退为 spec 字面顺序**——"提前到构建之前"降级为**待 ★ 确认的偏离**（原文自行拍板且"仍满足 F053 AC-31a"的说法**被证伪**：AC-31a 逐字要求"托管预检 → 安全扫描 → 审批单"，`053/spec.md:109`），D4 / §4.1 阶段序同改；③ **C1 / D16 的 arch-guard 论证被证伪并重写**——RULE-5 只匹配 `api/endpoints/` 与 `api/router.py`（`arch-guard.sh:71-82`），domain 层跨模块 import 无护栏，且 `ResourceTier` 归 F055 / F054 只读已构成双向依赖 → 模型改落 `database/models/resource_tier.py` 两模块共读，拆模块判据改为文件规模与 owner 边界；④ **D8 前置 2 撤销"抽公共函数两处共用"**——`_get_admin_recipient_ids` 是**无条件 union**、D8 要的是**条件回退**，合并的两种错法各自致命，改为两个函数并存（坑 2 同改）；⑤ **AC-17 自审标注补落点**——引擎侧无通道（`resolve_approvers` 返回 `list[int]`、`ApprovalGateResult` 四字段），改走 handler 实例属性并写死"每次请求新建 handler"前提；⑥ preset 补必填 `handler_key`（漏传 = import 期 `ValidationError`）；⑦ **K9 / §8 回写项 1 删除**（161–164 分配早已写进 release-contract 与 constitution C5，原文会产生空转任务）；⑧ **包体上限三处统一**为 `settings.app_runtime.max_package_mb` 并新增 `GET /api/v2/apps/deploy-limits` 给 CLI 取值（F053 AC-32），§8 增回写 F053 一项；⑨ 波次表 AC-24 改为「除『查看待上线版本』入口外」并补对 §6 裁剪基准扩张的判据；⑩ §4.2④ 补 `business_resource_type/id` 两个必填字段并厘清与 `app.release.*` 审计筛选的关系；⑪ 预检第 2 步归属定死为同步段本地校验、`runtime` 与 manager 的复核下沉异步段；⑫ 死码 / 重叠码清理（并入①）；⑬ D14「零前端代码」补前提——`isApprovalMessageType` 也认 `message_type`，非审批通知禁用 `request`/`approve`（写进 §4.2⑦ 发送契约）；⑭ K5 出处订正 F054 **D10**（非 D8）；⑮ 行号漂移与 HEAD 口径订正（`_UI_VISIBLE_V2_ACTIONS :193-259` / `_V2_NAMESPACE_TO_ACTION_PREFIX :261` / `ainsert_v2 :428` / platform `bs.json :1832,:1842` / client `zh-Hans:489 en:501 ja:486`），并声明 **F054 已落码**（`app_factory.py` 与 `app` 审计命名空间已就位，§4.2⑥ 由待办改为既成事实） | design 评审（15 条 ISSUE）逐条处理 |
| 2026-08-17 | 初版：D1–D16 决策 + 30 条坑 + 对外契约（管线端点 / 状态接口 / AppManifest / 审批场景 payload / 两张新表 / 审计事件族 / 通知 action_code / 错误码 162 段）+ 测试与 114 手动验证（对应 `mvp-114-path.md` §1 步 3–4）+ MVP-核心边界表。**三项显式偏离 / 待回写**：① **密钥扫描位置提前到构建之前**（D5，对 spec AC-01 字面顺序的偏离，行为与 AC-10 完全一致，回改成本为零）；② **档位数值以本 spec AC-44 为准并回写 F054 `DEFAULT_TIERS`**（D11 / 坑 27）；③ **F054 需补 `AppProvisionService.create_draft`**（D2 / 坑 26）。另登记 `release-contract.md:98` 与 constitution C5 的错误码回写、approval-module skill 的同步义务。**（本行为历史记录：其中 ① 已在上一行的评审修订中降级为待 ★ 确认项、错误码回写项已确认为无需再做——以上一行为准）** | F055 design 编写（spec 65 AC + 两份探查笔记 E1/E2 + `mvp-114-path.md` §6 裁剪基准 + F054/F049 design 契约 + approval-module SKILL） |

<!-- self-check: design-checklist 24 项自检 —— 第 1–11、13–21、23 项满足；未满足 / 部分满足 3 项：
  · 第 12 项「与 spec §5-§7 的实际实现一致」——本文以"要建成的样子"口径写（F055 尚未开工），实现后须按现状覆盖本文，届时逐节复核；**三项回写上游**（档位数值 / F054 `create_draft` 缺口 / F053 AC-32 上限取值口径）与**一项待 ★ 确认的偏离**（密钥扫描位置，D5）已在修订历史与 §8 登记；
  · 第 22 项「修订历史在 feature 完成时已记初版」——已记初版，但 feature 尚未完成，属提前记录（F049 / F054 design 同口径）；
  · 第 24 项「反映 tasks.md 实际偏差记录」——tasks.md 尚未编写，暂不适用，实现后回填。
-->
