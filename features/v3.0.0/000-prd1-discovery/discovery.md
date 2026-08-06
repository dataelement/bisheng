# Spec Discovery — 3.0 应用工场 PRD-1（专业开发者通道与应用运行时）

> **定位**：SDD 全流程第 1 步（Spec Discovery）的产出。回答三件事：现状代码能承载 PRD-1 多少、缺口在哪、怎么拆 Feature——并汇总必须由用户拍板的关键决策（★ 暂停点）。
> **输入**：《3.0 应用工场 PRD-1 专业开发者通道与应用运行时》v1.5（22 条目：DEV×7 / RT×7 / GOV×8）+ 伴生《3.0 开放 API 鉴权与身份传递 PRD》v2.0（R1–R9）。
> **方法**：11 维并行代码调研（每维含文件/符号级锚点），完整记录在 [research/](./research/)（11 个维度文件）——spec/design 阶段编写时**必读对应维度文件**，锚点已核实到行号。
>
> ⚠️ **本分支（`3.0-vibe`）含未修复安全缺口的行级定位**（research/ 各文件 + `docs/product/3.0 开放 API 鉴权与身份传递 PRD.md`）。origin 是公开仓——**未经确认不得推送本分支**，也不要把这些内容并入任何会推公开仓的分支。
> **日期**：2026-08-06 ｜ 状态：待用户确认（★）

---

## 1. 总体结论

1. **地基厚、门面缺**。PRD-1 所需的领域能力（权限双层过滤、审批引擎、站内信、配额引擎、标签/广场、模型管理、MinIO 快照、审计）在代码中全部存在且可复用；缺的是四个「对外门面」——**API key 凭据体系、MCP Server、OpenAI/Anthropic 兼容网关、CLI/SDK**——以及一整块绿地：**应用托管运行时**（per-app 实例编排/路由/隔离，全仓零先例）。
2. **伴生 PRD 是一切的地基**。个人 key（DEV-01）、应用 token（GOV-08）、CLI/MCP/SDK 三面鉴权全部踩在《开放 API 鉴权与身份传递 PRD》R1 统一凭据底座上；v2 开放面的鉴权现状与代用户通道存在已核实的安全缺口（细节见私有调研记录）。**F049（开放 API 鉴权改造）必须首批交付**。
3. **检索强度分叉已被代码证实**。工作台双层过滤路径（`KnowledgeFileVisibilityService` 索引层预过滤 + `view_file` 结果层兜底）真实存在且能被任意 key 解析身份驱动（`init_login_user` + `request=None` 均有生产先例）；旧 v2 `/filelib/retrieve` 只有库级一次校验（其端点注释与实现不符）。PRD 的「声明白名单 ∩ 用户文件级权限」有现成引擎可接——但**资源权限评估/检索过滤链路上 strict fail-closed 不存在**（`PermissionService.check`/`list_accessible_ids` 及结果层兜底三处全是静默降级为缩小集；仓内 fail-closed 参照实现只有 `has_tenant_admin`（user_deps.py）与 `hmac_auth.py`，不在检索链路上），需新建调用面隔离的严格模式。
4. **两个「与 PRD 字面冲突」的现状**需要产品确认：审批单处理界面只存在于 client 工作台弹窗（platform 只有场景配置）；现有版本机制是可变指针（`change_current_version` 原地切换），与 RT-05「前向新建、不可变、终态标注」语义相反——工场应用应独立建版本表，不复用 `flow_version`。

---

## 2. 现状地图（按 PRD 域，Top 结论）

详细锚点见 research/ 对应文件；此处只列影响拆分与决策的要点。

### 2.1 凭据与开放 API（DEV-01 / GOV-08 / 伴生 PRD）→ research: v2-open-api, auth-identity

- **可复用**：合格随机源 `generate_short_high_entropy_string`；恒时比较 + fail-closed 鉴权依赖的唯一正确姿势 `sso_sync/hmac_auth.py`；「非 cookie 凭据 → UserPayload + set_current_tenant_id」收口模式（`get_default_operator_async`）；撤销 ≤5s = 照抄 `aincrement_token_version` 的「原子 UPDATE + 主动刷 Redis 缓存」；账号禁用联动挂接点 `ainvalidate_jwt_after_account_disabled`。
- **缺口**：全仓无任何 ApiKey 表 / bs- 前缀 / require_api_key 配置；v2 约 45 个端点（8 个路由文件）多数**内联调用**身份解析（非 Depends），鉴权改造必须逐端点替换；WS 握手鉴权需改走 Authorization 头（现有查询参数路径不生效，中间件已读 scope headers，可行）。
- **风险**：v1 端点只认 cookie（headers 分支零调用方）——**PAT 不能复用 v1 面**，必须独立 router；`User` 表无 `user_type` 字段（服务账号主体需 Alembic）。

### 2.2 权限与可见范围（GOV-01 / RT-02 过滤 / NFR-1）→ research: permission-rebac ⚠️**已按 F048 基线重核，本节为重核后结论**

> research/permission-rebac.md 是在 `main`（pre-F048）上做的，其「七级链 + owner/manager/editor/viewer 四档 + FGA 故障降级 owner 兜底」结论**在本基线已全部作废**——`PermissionService` 降格为身份/LLM 兼容桥，对 F048 业务资源类型直接 raise。阅读该文件时以本节为准。

- **今天的判定链**：业务侧唯一入口是 `check_business_action` / `require_business_action` / `batch_check_business_actions`；链路 = 解析 actor → 业务 adapter 产出已验证目标 → runtime 检查动作。短路只剩两个 allow-all：**super_admin** 与**当前租户的租户管理员**（Root 租户没有租户管理员这一档）。
- **fail-closed 已经是现状**：OpenFGA 故障、Catalog 未就绪、资源镜像非 CURRENT、动作未分级——全部 raise 明确错误，**没有任何 owner/creator 兜底分支**。这意味着 NFR-1.4 在权限侧天然满足（见 D6 已解）。
- **列表过滤范式变了**：不再用 ListObjects（生产装配 DenyListObjects 策略、无调用方），改为「SQL 出业务候选 → 批量 check 具体动作」，知识文件可见性预过滤就是这个形状。admin 短路仍在且位于策略检查之前。
- **可复用**：通用授权 API（`/permissions/resources/{type}/{id}/` 下的 grants / mode-drafts / my-permissions 等）+ platform `PermissionDialog` 及其子组件；创建即 owner 走 adapter 的 `authorize_created`（protected owner grant + 投影账本 + `scripts/reconcile_f048_projection_operations.py` 人工续跑）。
- **缺口（比 pre-F048 更重）**：新增 `app` 资源类型要动 **后端 12 处 + 前端 3 处联合类型**；且**存量环境仍有「只写一次」缺口**——授权模型本身已有 checksum 检测 + 全站 503 迁移闸门（比 main 好），但 Catalog 的「动作↔资源类型范围表」只在首次迁移与草稿发布时写入，且变更类型枚举里**没有「改资源范围」这一种**，迁移脚本又因 checksum 不符无法重跑。给存量环境加资源类型必须新写运维脚本或扩展变更类型。
- **风险**：① 委托红线的正确谓词是 runtime 的 system-authorized 判定（super_admin ∪ 当前租户管理员），不是 legacy 的 `is_admin()`；② 身份构造有两条路径，同步路径不计算 super 标记，后台/工具执行路径自造的身份也不带——同一个人在不同入口的判定结果可能不同；③ F048 判定**无缓存且每目标 3 次 SQL**，MCP/应用运行时的高频检索会放大；④ 前端三处类型里有 `linsight_skill` 但后端 registry 未注册，对它调通用授权 API 会直接报错（存量隐患）。

### 2.3 检索（DEV-02 / GOV-05 / NFR-1.4）→ research: knowledge-retrieval

- **可复用**：双层过滤引擎可整体复用——完整双层（索引层+结果层）现有 2 条链（chat_folder / space_flow_retrieval），仅结果层兜底 2 条链（workstation / citation）；知识库清单 `KnowledgeService.get_knowledge`（天然 ⊆ UI 可见范围）；Milvus+ES 双召回 + RRF。
- **缺口**：无「声明白名单」概念；无会话解耦的纯检索门面（`_retrieve_and_filter` 是聊天服务私有方法）；**检索/权限评估链路 strict fail-closed 不存在**（三处全是静默降级，且 check 曾被刻意从硬 fail-closed 改成兜底——严格模式必须做成调用面隔离，不能全局翻转）。
- **待澄清**：「与工作台检索集合相等」的基准锚点（chat_folder 有索引层预过滤 / workstation 变体没有，两者边界样本可能不同）；type=0 文档知识库无文件级权限模型，「含文件级权限」是否只指 type=3。

### 2.4 审批（RT-03 / GOV-02）→ research: approval-center

- **可复用**：ApprovalGate 统一网关 + 或签 + 撤回 + 富 JSON payload（detail_snapshot 无 schema 约束）+ outbox + 站内信 + 审计，「应用发布」新场景 = 三件套注册（preset + Gate + handler 工厂分支），框架零阻塞。
- **缺口（四条场景规则全是新活）**：未配置兜底租户管理员（现状三条失败路径全都不兜底，且 `approver_resolver` 的 tenant_admin 分支**错用系统超管近似**，须先修）；提交人自动跳过；应用删除→系统级 cancel API；审批单详情四分区定制渲染 + 审读视图/预览试用入口。另需补 `withdraw_instance` 终态守卫（现状已通过的实例也能被翻成 WITHDRAWN）。
- **⚠️ 界面落位歧义（决策 D5）**：PRD 写「平台审批中心」，现状审批处理面只在 client 工作台弹窗。

### 2.5 模型面（DEV-02 双协议 / GOV-04 账单）→ research: model-llm

- **可复用**：llm_server/llm_model 双表 + Root 共享 + `BishengLLM`（19 服务商、全链路流式）+ 模型收回错误族（LlmModelOfflineError 等）+ telemetry 每调用全覆盖 + F017 账单表结构。
- **缺口**：OpenAI/Anthropic 兼容**入站**端点零现状（现有的 v2 助手对话端点是助手外壳、非模型直连，且同属 F049 鉴权改造范围）；按名称解析模型不存在（只认数字 model_id，且租户内跨服务商同名 model_name 合法——歧义规则要定义）；账单表无 key 维度，落账点只覆盖 workflow 节点（建议下沉 BishengLLM 层统一落账）。

### 2.6 广场 / 版本 / 管理列表（RT-02 / RT-05 / GOV-09）→ research: marketplace-versions

- **可复用**：标签体系整套（tag/tag_link + HOME_TAGS + 打标组件）；client 广场页（explore.tsx 标签 tab + 卡片 + 滚动加载）；platform 管理表格模板（Users.tsx / useAppLog）；菜单 gating（web_menu key）。
- **缺口**：第三应用类型接入 ≈ 8 处硬编码扩展点（FlowType/SUPPORTED_APP_TYPES/UNION 子查询/FGA 映射/TagDao/client flow_type map…）；RT-05 版本模型全新（现 flow_version 是可变指针语义，**建议独立版本表**，否则波及存量版本 UI）；GOV-09 的档位/来源/改码权三概念数据模型不存在。
- **风险**：应用列表 UNION 子查询绕过租户 auto-filter（docstring 明示），新增分支必须手工注入租户条款（C3）；版本快照大 JSON 有 DM8 写放大前科——快照体建议 MinIO 引用而非行内 JSON。

### 2.7 审计 / 站内信（GOV-04 / 事件触达）→ research: audit-notify

- **可复用**：v2 结构化审计 `ainsert_v2`（新增 ~12 类事件 = 按命名空间加 action）；超管跨租户查询后端已支持（tenant_scope=None）；站内信 `send_generic_notify` 任意模块→任意用户，铃铛/角标/弹窗全链路现成；「管理后台不设消息面」现状即吻合。
- **缺口**：审计双归属（actor=应用 token / subject=访问用户）无 subject 列——与伴生 PRD §4.8.1 一次对齐字段；按 key 账单聚合 API/UI 全新；审计页导出与租户筛选列。
- **风险**：三处白名单 lockstep（后端 `_UI_VISIBLE_V2_ACTIONS` ↔ 前端 getActionsApi ↔ i18n）漏一处即「写了查不到」；**访问记录/运行期能力调用是高频事件，直接进 auditlog 单表会写放大**——需分层（独立表或扩 llm_call_log）；`NotificationsDialog.tsx` 已 1221 行超 600 行硬规，扩前先拆。

### 2.8 配额 / 角色 / 部署开关（GOV-03 / GOV-07）→ research: quota-tenant-roles

- **可复用**：tenant.quota_config JSON + `QuotaService`（缺 key/-1=不限，与 PRD 语义天然一致）；配额弹窗 quotaFields 数组加一行即并列展示；「菜单 + 功能点子开关」有 `create_app` 完整先例（roleaccess type=99，后端不校验白名单→近零 schema 改动）；部署开关三段式（settings → /api/v1/env → appConfig）照抄 multi_tenant.enabled；admin-scope 切租户视图（F019）现成。
- **缺口**：资源档位实体全新（表 + 系统管理页 tab + seed 机制）；应用实例计数源（依赖应用表，状态过滤要排除审批期临时实例）；工场/开放能力层两个部署 flag；「整层不装」的条件路由注册模式（现 router 无条件注册）。
- **⚠️ 已核实缺陷**：租户配额是**整体覆盖写**（TenantQuotaDialog 只序列化自己的 quotaFields + `aset_quota` 整体替换）——实例配额与存储配额两入口会互相清 key，必须先改成合并写语义（本仓已有同类事故先例）。

### 2.9 运行时基建（RT-01/07/08 / DEV-04 托管）→ research: mcp-runtime-infra, appdb-storage-sdk

- **可复用**：`mcp>=1.27.0` SDK 已在依赖内（server 原语可用，需 POC）；MinioStorage 全套 + 灵思 workspace 前缀隔离/copy-forward 快照范式（代码快照可照搬）；cookie path=/ host-only → `/apps/{slug}` 同源免二次登录零后端改造；client 401→LOGIN_PATHNAME→登录→回跳链路现成（需补 query/hash）。
- **绿地（全仓零先例）**：per-app 实例编排（拉起/限额/健康探测/≤5min 自愈）——无 docker SDK、无进程管理器、无 cgroup 操作；/apps/{slug} 动态路由（nginx 纯静态 conf）；per-app 数据库供给（无动态建库代码，MySQL database-per-app vs DM8 ?schema= 语义不对称）；schema diff 引擎与迁移前自动快照（DM8 侧连 mysqldump 等价物集成都没有）；bisheng-sdk / bisheng CLI（无任何可发布包工程、无 [project.scripts]）；安装件分发端点。
- **风险**：单机已合跑全家桶（114 曾因 linsight worker OOM 死机），叠 per-app 实例必须靠 GOV-03 配额强约束，否则与 RT-08「平台必须正常」直接冲突；docker.sock ≈ host root 权限，信创客户环境 docker 权限不确定（决策 D4）；app 附件不能混入 public bucket（匿名读策略）。

---

## 3. Feature 拆分方案（提议，待 ★ 确认）

编号从 **F049** 起（F043–F048 已被 `features/v3.0.0-beta1/` 占用，该目录目前**仅存在于 origin/feat/3.0.0-beta1 分支**、未合入主线）；不变量编号从 **INV-27** 起（INV-1~7 v2.6.0、INV-8~26 v3.0.0-beta1；v2.5.0 INV-1~9 与 v2.5.1 INV-T1~T19 是独立历史编号空间，引用时须带版本前缀）。

| # | Feature（暂名） | 覆盖 PRD 条目 | 依赖 | 批次 |
|---|----------------|--------------|------|------|
| F049 | openapi-auth（开放 API 鉴权与身份传递） | 伴生 PRD **R1–R7、R9**（R8 限流/配额/幂等属 P2，两册均显式顺延）；GOV-08 的凭据底座/服务账号/兼容窗口/审计双归属字段（§4.8.1 对齐）/**会话 key 派生机制**（接线随 PRD-2 工作台启用，GOV-08 验收 2/3 的会话 key 部分随 PRD-2 验收） | — | A |
| F050 | personal-api-key（个人 API key 与管理面） | DEV-01；GOV-08 个人 key tab、「我的 API key」；GOV-07 开放能力层部署 flag 与入口隐藏。※与伴生 PRD R1-P1「个人访问令牌」是否同一凭据实例 = PRD-1 §6 开放问题 3，spec 阶段定夺 | F049 | A |
| F051 | model-protocol-gateway（模型双协议直连 + 按 key 账单） | DEV-02 双协议面；GOV-04 按 key 用量账单 | F050 | A |
| F052 | mcp-server-face（MCP 工具面 + 统一检索门面） | DEV-02 MCP 六类工具（应用数据/状态日志两类随批次 B 接线）；GOV-05 检索范围规则的检索门面（strict fail-closed + 白名单收窄，GOV-05 运行时/F057 共用） | F050 | A |
| F053 | dev-cli-skills（CLI + 开发技能包 + 本地身份注入） | DEV-03、DEV-04（login/skills sync/dev；deploy/logs 命令随 F055 启用）、DEV-05；安装件分发 | F050–F052 | A尾/B |
| F054 | app-domain-runtime（应用领域模型与托管运行时） | RT-01、RT-07、RT-08；DEV-04 托管运行契约；app 表/状态机/FGA app 类型/实例编排/per-app 数据库与附件/代码快照；**GOV-03 实例配额执行闸门**（复用 tenant.quota_config + QuotaService，实例拉起/重新启用的内置校验——先于档位实体存在，堵「无护栏窗口」）；PRD-2 最小面 **WB-13 运行日志、WB-06 数据面** | F049 | B |
| F055 | app-publish-pipeline（发布管线、版本、审批与能力总线注入） | RT-03、RT-04、RT-05；GOV-02；**GOV-05 主体**（模型/密钥引用的运行时注入通道、「发布审批即授权」、能力收回→明确错误态与 owner 失效提示）；**GOV-03 资源档位**（ResourceTier 实体 + 档位管理 tab + 发布选档/入快照/预检/终检/待上线态）；GOV-08 应用 token；DEV-06（本册恒「在本地」）；DEV-04 deploy/logs；事件触达接线；PRD-2 最小面 **WB-14 发布面、WB-15 版本差异**。含审批中心前置修复（tenant_admin resolver、withdraw 终态守卫） | F054、F049 | B |
| F056 | app-square-governance（广场接入与治理面） | RT-02；GOV-01；GOV-04 审计扩展；GOV-09 + PRD-2 最小面**「我的应用列表」**（同一入口页并列 tab）；GOV-03 租户实例配额设定 UI 与用量条（含覆盖写语义修复）；GOV-07 角色权限配置面与工场运行时层开关（开放能力层 flag/入口隐藏已随 F050、未部署引导页已随 F054 RT-01、CLI 新建权限校验已随 F055——本行只做剩余部分） | F054、F055 | B |
| F057 | bisheng-sdk（DEV-07 五件套 + 开发者指南） | DEV-07（※验收 2「与平台内模板同范式」依赖 PRD-2 WB-01，随 PRD-2 验收；本版验收范围 = 验收 1/3） | F049/F051/F052（auth/chat/retrieve）+ F054（appdb/storage） | B |

说明：
- **批次 A = 开放能力层**，按 GOV-07 可独立于工场运行时交付，且是批次 B 的鉴权/凭据地基。
- F049、F054、F056 体量偏大，spec 阶段允许再拆（尤其 F054 的「运行时编排」与「per-app 数据库」可分）；拆分时在 release-contract 表 3 更新。
- **PRD-2 最小承载面逐面归属**：WB-13 运行日志 / WB-06 数据面 → F054；WB-14 发布面 / WB-15 版本差异 → F055；「我的应用列表」→ F056；WB-01 模板明确随 PRD-2（仅影响 DEV-07 验收 2）。
- **GOV-05 密钥引用的录入面是 PRD-2 WB-05**，而 PRD-1 §1 最小承载面清单不含 WB-05——密钥引用能力随本册交付还是顺延 PRD-2，需与产品确认（已列入 §4 次级决策）。
- 审批中心前置修复属行为变更（存量 tenant_admin source 节点的实际审批人会变），需在 release note 声明。

---

## 4. 关键决策清单（★ 需用户逐项拍板）

按影响面排序；D1/D2 决定第一步走向，必须先定。

| # | 决策 | 选项与建议 |
|---|------|-----------|
| **D1** | **首批启动 feature**：是否按「批次 A 先行、F049 第一个进 spec」推进？ | 建议：是。F049 是 DEV-01/CLI/MCP/SDK/应用 token 的共同地基，且 v2 开放面的鉴权缺口在产，越早关越好。 |
| ~~**D2**~~ **已定** | ~~开发基线分支~~ | **2026-08-06 定：3.0.0 线（含 F048）**——开发在 `3.0-vibe`（基于 `feat/3.0.0-beta1`），F048 权限重写已实装并经代码核实。连带：beta1 的 INV-8~26 无条件生效；§2.2 已按此基线重核（research/permission-rebac.md 的 pre-F048 结论作废）。 |
| **D3** | **app 资产载体**：复用 flow 表新增 FlowType（广场/标签/权限链路自动继承，但混入存量语义）vs 独立 app 表（干净，但 ~8 处硬编码点全要显式扩）？ | 倾向独立表 + 列表 UNION 第三支（版本/档位/改码权等字段本就装不进 flow 表），spec 阶段定稿。 |
| **D4** | **运行时隔离选型**：docker SDK+docker.sock（与现单机 compose 最兼容，但 sock≈host root，信创环境 docker 权限不确定）vs 裸进程+cgroup v2（无 docker 依赖，跨发行版差异大）？ | design 阶段决策，但需要产品先回答：目标客户环境（含信创）是否保证有 docker 且允许平台持有 socket 权限。 |
| **D5** | **审批处理界面落位**：PRD 写「平台审批中心」（platform 管理后台），现状审批处理面只在 client 工作台弹窗（platform 只有场景配置+异常处理）。复用 client 弹窗（改造小、PRD 措辞需修订）vs platform 新建整套处理面（符合字面、工作量大）？ | 建议复用 client 弹窗 + 场景定制详情渲染，PRD 措辞同步修订。 |
| ~~**D6**~~ **基本自解** | ~~strict fail-closed 的边界~~ | **随 D2 落定而消解**：F048 基线上权限判定已硬 fail-closed（FGA 故障/Catalog 未就绪/动作未分级全部 raise，无 owner 兜底），NFR-1.4 在权限侧天然满足，无需再为开放面单开 strict 模式。已登记为 INV-30（只补充「部分过滤亦属失败」这一判据）。**残留一处需拍板**：全局超管判定在 OpenFGA 故障时会回落到 legacy 角色位判定——故障时反而可能把人判成超管并命中 allow-all，是当前唯一带 fail-open 味道的分支，是否一并收紧待定。 |
| **D7** | **appdb 双库范围**：per-app 数据库首发是否 MySQL+DM8 双库同步交付？DM8 的 schema-per-app 与迁移前自动快照均无先例，「首发仅 MySQL、DM8 二期」可大幅降险但违背 C2，需显式豁免决策。 | 需产品/交付侧拍板。 |

次级决策（spec/design 阶段随对应 feature 定，先登记）：模型名歧义规则（跨服务商同名 model_name）；MCP Server 部署形态（同进程 mount vs 独立进程）；/apps/{slug} 路由承接者（nginx 增强 vs FastAPI 反代 vs 独立 ingress，商业版 Java gateway 联动）；高频审计事件分层；实例配额存储形态与覆盖写修复；CLI 安装包形态（wheel+内网镜像 vs 单文件二进制）；PAT 与开放 API 个人访问令牌是否合并（PRD-1 §6 开放问题 3）；**GOV-05 密钥引用是否随本册交付**（录入面 WB-05 属 PRD-2 且不在 §1 最小承载面清单，需产品确认）。

---

## 5. 重大风险登记（进 design 阶段必须消化）

1. **新资源类型的存量生效缺口（按 F048 基线重核）**：授权模型侧已有 checksum 检测 + 全站 503 迁移闸门，但 Catalog 的「动作↔资源类型范围表」只在首次迁移与草稿发布时写入，**变更类型枚举里没有「改资源范围」**，迁移脚本又因 checksum 不符无法重跑——给存量环境加 `app` 类型必须新写运维脚本或扩展变更类型。F054 design 必须前置演练（F048 存量被拦教训）。
2. **租户配额整体覆盖写**（已核实缺陷）：新增实例配额前必须先改合并写语义，否则两入口互清。
3. **单机容量**：per-app 实例叠在已合跑全家桶的单机上，GOV-03 实例配额是 RT-08 承诺的唯一护栏——为此实例配额**执行闸门已划入 F054 自身**（复用 tenant.quota_config，先于档位实体存在），F054 单独合入不会出现无护栏窗口。
4. **DM8**：版本快照大 JSON / appdb 迁移快照均有写放大与工具缺失风险（快照体走 MinIO；D7 决策）。
5. **委托红线贯穿**：禁代表 super_admin/tenant_admin 的六道准入必须在 MCP/SDK/dev 注入/审批人预览各面复检，防 key 泄漏=全租户知识外泄。
6. **UNION 子查询租户注入**、**新表注册 _TENANT_AWARE_MODEL_MODULES**、**审计三白名单 lockstep**——三个「漏一处即静默失效」的机械性坑，写进各 feature design 的已知坑清单。

---

## 6. 下一步

**进度（2026-08-06）**：D2 已定（3.0.0 线含 F048），D6 随之消解；F049 已按伴生 PRD 的 P0 阶段线收窄并完成 spec 初稿（`049-openapi-auth-baseline/spec.md`），release-contract 表 1/表 2 已正式登记（ApiCredential、ServiceAccount；INV-27~30）。

1. ★ 待用户确认：F049 spec（含其 §4 的三项 [待澄清]——WS 端点与免登录分享页的冲突、统一身份构造导致的权限放宽、无身份端点的归属基准）+ 仍未拍板的 D1 / D3 / D4 / D5 / D7。
2. 确认后：`/sdd-review 049-openapi-auth-baseline spec` → 修订 → 写 design.md（Constitution Check）→ ★。
3. **research/ 的时效性提醒**：11 份调研在 `main`（pre-F048）上完成，与本基线相差 242 个后端文件。已按 F048 重核的三块结论收在 **[baseline-recheck.md](./baseline-recheck.md)**（44 端点按身份来源分类的改造基数、两层改造方案、WS 分享页冲突取证、F048 判定链与 fail-closed 现状、新增资源类型 12+3 处清单与 Catalog 范围表存量缺口）——**与 research/ 冲突时以它和 §2.2 为准**。其余维度在被引用前需重核，尤其检索（`knowledge_file_visibility_service` 有 139 行改动）、模型面、审批。
