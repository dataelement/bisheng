# Spec Discovery — 3.0 应用工场 PRD-1（专业开发者通道与应用运行时）

> **定位**：SDD 全流程第 1 步（Spec Discovery）的产出。回答三件事：现状代码能承载 PRD-1 多少、缺口在哪、怎么拆 Feature——并汇总必须由用户拍板的关键决策（★ 暂停点）。
> **输入（v2，2026-08-17）**：《3.0 应用工场 PRD-1 专业开发者通道与应用运行时》**v2.0**（21 项：DEV×6 / RT×7 / GOV×8；§1.4 功能全集、§3.0 全册通用约定〔承载面 platform「构建 → 应用」/ 状态机 / 事件触达〕）+ 伴生《3.0 开放 API 鉴权与身份传递 PRD》**v2.1 草案**（R1–R9）+《3.0 应用工场 产品方案》§4–§5（F100–F113 技术特性）。
> **方法**：11 维并行代码调研（每维含文件/符号级锚点），完整记录在 [research/](./research/)（11 个维度文件，2026-08-06 于 `main` pre-F048 完成）+ 按 F048 基线重核的 [baseline-recheck.md](./baseline-recheck.md)——spec/design 阶段编写时**必读对应维度文件**，与 baseline-recheck 冲突时以后者为准。
>
> ⚠️ **本分支（`3.0-vibe`）含未修复安全缺口的行级定位**（research/ 各文件 + 伴生 PRD 附录）。origin 是公开仓——**未经确认不得推送本分支**，也不要把这些内容并入任何会推公开仓的分支。
> **日期**：2026-08-06 初版（输入 PRD-1 v1.5）；**2026-08-17 按 PRD-1 v2.0 重排为拆分 v2** ｜ 状态：**★ 已过（2026-08-17 用户授权全部按建议拍板）**——拆分 v2 与 §4 决策 N1–N6 生效，进入 design / tasks 阶段（MVP 纵切见 [mvp-114-path.md](../mvp-114-path.md)）

---

## 1. 总体结论

1. **地基厚、门面缺**。PRD-1 所需的领域能力（权限双层过滤、审批引擎、站内信、标签/广场、模型管理、MinIO 快照、审计）在代码中全部存在且可复用；缺的是四个「对外门面」——**API key 凭据体系、MCP Server、OpenAI 兼容模型面、CLI/SDK**——以及一整块绿地：**托管应用运行时**（per-app 实例编排 / 路由 / 隔离，全仓零先例；v2.0 起还要**双执行后端 compose + k8s** 与 k8s 多节点必需的**镜像构建与分发**）。
2. **伴生 PRD 是一切的地基**。开发者 key、应用运行期凭据、CLI/MCP/SDK 三面鉴权全部踩在《开放 API 鉴权与身份传递 PRD》R1 统一凭据底座 + R4 服务账号（含资源归属人）上；v2 开放面的鉴权现状与代用户通道存在已核实的安全缺口。**F049 必须首批交付，且不得脱离 F050 单独对外发版**（裸 `user_id` 须随 v3.0.0 移除）。
3. **检索强度分叉已被代码证实**。工作台双层过滤路径真实存在且能被任意 key 解析身份驱动；旧 v2 `/filelib/retrieve` 只有库级一次校验。PRD-1 DEV-02 / GOV-05 与伴生 §4.4.6 都要求收敛到同一条文件级双层路径 + fail-closed——需要一个**调用面隔离的统一检索门面**（F052 拥有，F050 模式 D / F055 托管运行期 / F057 retrieve 共用）。
4. **PRD-1 v2.0 已自行消解 v1.5 时的两处「与代码字面冲突」中的一处**：审批处理面落位——§3.0.3 明确「审批类事件进入审批中心待办、管理后台不设消息面、审批人在工作台侧接收」，与现状（处理面只在 client 工作台弹窗、platform 只有场景配置）吻合，原决策 D5 关闭。**另一处仍在**：现有版本机制是可变指针（`change_current_version` 原地切换），与 RT-05「只增不改、终态标注」语义相反——托管应用独立建版本表，不复用 `flow_version`。
5. **v2.0 把三块「待建能力被当成既有」的错误已在 PRD 侧订正**（存储配额只覆盖知识库文件、用量表无 app/key 维度、新建租户 seed 是新机制），Discovery 侧无需再替 PRD 兜底；但 PRD-1 v2.0 与伴生 v2.1 各仍有**内部残留**（见 §4 N5 / N6），spec 已按较新决议写，需产品回修。

---

## 2. 现状地图（按 PRD 域，Top 结论）

详细锚点见 research/ 对应文件；此处只列影响拆分与决策的要点。**每小节末「PRD v2.0 影响」为 2026-08-17 追加**，说明该维度的哪些结论因 PRD 变更而失效、加重或新增。

### 2.1 凭据与开放 API（DEV-01 / GOV-08 / 伴生 PRD）→ research: v2-open-api, auth-identity；baseline-recheck §1–§2

- **可复用**：合格随机源 `generate_short_high_entropy_string`；恒时比较 + fail-closed 鉴权依赖的唯一正确姿势 `sso_sync/hmac_auth.py`；「非 cookie 凭据 → UserPayload + set_current_tenant_id」收口模式（`get_default_operator_async`）；撤销 ≤5s = 照抄 `aincrement_token_version` 的「原子 UPDATE + 主动刷 Redis 缓存」；账号禁用联动挂接点 `ainvalidate_jwt_after_account_disabled`。
- **缺口**：全仓无任何 ApiKey 表 / bs- 前缀 / require_api_key 配置；v2 约 45 个端点（8 个路由文件）多数**内联调用**身份解析（非 Depends），鉴权改造必须逐端点替换；WS 握手鉴权需改走 Authorization 头（现有查询参数路径不生效，中间件已读 scope headers，可行）。
- **风险**：v1 端点只认 cookie（headers 分支零调用方）——密钥不能复用 v1 面，必须独立 router；`User` 表无 `user_type` 字段（服务账号主体需 Alembic）。
- **PRD v2.0 影响**：① 伴生 §4.9 改「平台侧零迁移」——原「默认操作员转型降权闸口」整条作废、`default_operator` 与 `enable_guest_access` 两配置项直接移除；② 6 个 `/chat/*` 端点不暴露（含全清单风险最高的 `sync/messages`），改造基数 44 → 36 HTTP + 2 WS；③ 新增**资源归属人**（服务账号必填自然人，创建关系落归属人 + 回授可编辑）与主体侧授权页 v2.1 形态（单列表 + 来源列）；④ 三扩展位 `model:invoke` / `identity:read` / `app:manage` 并入同一张权限位清单（无独立 scope 维度、无独立开发者 key 界面），与 `delegate` 互斥（INV-31）；⑤ 应用运行期凭据不作产品概念、无管理入口（由 F055 自动签发 / 回收）。

### 2.2 权限与可见范围（GOV-01 / RT-02 过滤 / NFR-1）→ research: permission-rebac ⚠️**已按 F048 基线重核，本节为重核后结论**

> research/permission-rebac.md 是在 `main`（pre-F048）上做的，其「七级链 + owner/manager/editor/viewer 四档 + FGA 故障降级 owner 兜底」结论**在本基线已全部作废**——`PermissionService` 降格为身份/LLM 兼容桥，对 F048 业务资源类型直接 raise。阅读该文件时以本节为准。

- **今天的判定链**：业务侧唯一入口是 `check_business_action` / `require_business_action` / `batch_check_business_actions`；链路 = 解析 actor → 业务 adapter 产出已验证目标 → runtime 检查动作。短路只剩两个 allow-all：**super_admin** 与**当前租户的租户管理员**（`_identity_shortcut` 中 `TENANT_ADMIN` 与 `SUPER_ADMIN` 并列，**批量列表路径同样适用**；Root 租户没有租户管理员这一档）。
- **fail-closed 已经是现状**：OpenFGA 故障、Catalog 未就绪、资源镜像非 CURRENT、动作未分级——全部 raise 明确错误，**没有任何 owner/creator 兜底分支**。NFR-1.4 在权限侧天然满足（INV-30 只补「部分过滤亦属失败」）。
- **列表过滤范式变了**：不再用 ListObjects，改为「SQL 出业务候选 → 批量 check 具体动作」，知识文件可见性预过滤就是这个形状。admin 短路仍在且位于策略检查之前。
- **可复用**：通用授权 API（`/permissions/resources/{type}/{id}/` 下的 grants / mode-drafts / my-permissions 等）+ platform `PermissionDialog` 及其子组件（user / department / user_group 三种主体检索）；创建即 owner 走 adapter 的 `authorize_created`（protected owner grant + 投影账本 + `scripts/reconcile_f048_projection_operations.py` 人工续跑）。
- **缺口**：新增 `app` 资源类型要动 **后端 12 处 + 前端 3 处联合类型**（`ResourceType` 前端硬编码 union）；且**存量环境仍有「只写一次」缺口**——授权模型有 checksum 检测 + 全站 503 迁移闸门，但 Catalog 的「动作↔资源类型范围表」只在首次迁移与草稿发布时写入，变更类型枚举里**没有「改资源范围」**，迁移脚本又因 checksum 不符无法重跑。给存量环境加资源类型必须新写运维脚本或扩展变更类型。
- **风险**：① 委托红线的正确谓词是 runtime 的 system-authorized 判定（super_admin ∪ 当前租户管理员），不是 legacy 的 `is_admin()`；② 身份构造有两条路径，同步路径不计算 super 标记，后台/工具执行路径自造的身份也不带；③ F048 判定**无缓存且每目标 3 次 SQL**，MCP/应用运行时的高频检索会放大；④ 前端三处类型里有 `linsight_skill` 但后端 registry 未注册（存量隐患）。
- **PRD v2.0 影响**：① `TENANT_ADMIN` 身份短路已被 PRD 吸收——GOV-09「管理后台应用列表」整条取消（列表天然可见）、「租户管理员代调可见范围」是既有行为而非待做功能、「草稿对管理员不可见」取消；② GOV-01 改为**完全复用**卡片 ⚙️ →「管理权限」（`PermissionDialog`），零新建授权界面，本册只需注册 `app` 类型 + 发布面第二触发点；③ 服务账号「不出现在任何选人场景」要求**资源侧授权弹窗的主体选择器**（`grant_subject_service.py`，不走 `/user/list`）同步过滤——伴生附录 E.2 已点名，F049 AC-16 覆盖面含此入口。

### 2.3 检索（DEV-02 / GOV-05 / NFR-1.4）→ research: knowledge-retrieval

- **可复用**：双层过滤引擎可整体复用——完整双层（索引层 + 结果层）现有 2 条链（chat_folder / space_flow_retrieval），仅结果层兜底 2 条链（workstation / citation）；知识库清单 `KnowledgeService.get_knowledge`（天然 ⊆ UI 可见范围）；Milvus + ES 双召回 + RRF。
- **缺口**：无「声明白名单」概念；无会话解耦的纯检索门面（`_retrieve_and_filter` 是聊天服务私有方法）；`/api/v2/filelib/retrieve` 只做知识资源级一次校验（调用方注释宣称已有 per-user 过滤，**与实现不符**）。
- **待澄清**：「与工作台检索集合相等」的基准锚点（chat_folder 有索引层预过滤 / workstation 变体没有）；type=0 文档知识库无文件级权限模型，「含文件级权限」是否只指 type=3。
- **PRD v2.0 影响**：① 伴生 §4.4.6 把「检索补文件级过滤」列为 P1 交付前提，PRD-1 DEV-02 ① / GOV-05 均明令「不得复用仅库级校验的旧路径」——统一检索门面成为**三处共用件**（F050 模式 D 集合相等 / F055 托管期「声明白名单 ∩ 当前访问用户」/ F057 retrieve），拆分 v2 定其 owner 为 **F052**；② 本地 dev 与 MCP 面锚定「开发者服务账号被显式授予范围」（决议-4 后的 NFR-1 口径），无个人权限继承。

### 2.4 审批（RT-03 / GOV-02）→ research: approval-center；`.claude/skills/approval-module`

- **可复用**：ApprovalGate 统一网关 + 或签 + 撤回 + 富 JSON payload（detail_snapshot 无 schema 约束）+ outbox + 站内信 + 审计，「应用发布」新场景 = 三件套注册（preset + Gate + handler 工厂分支）；`approver_resolver` 已支持 `direct_user` / `department_admin` / `tenant_admin` 三种来源，`node_mode=or` 现成。
- **缺口**：`approver_resolver` 的 `tenant_admin` 分支**错用系统超管近似**（`AdminRole=1`），多租户下会把所有租户的发布审批压到超管一人；`TenantAdminService.list_tenant_admins` 对 **Root 租户恒返回空**；`_init_default_approval_scenarios` 硬编码默认租户，唯一真实租户创建路径 `tenant_mount_service` 对 approval 零引用；`department_admin` 只查 owner 主部门、不上溯，`applicant_department_id` 须业务入口显式传；`withdraw_instance` 缺终态守卫；审批单详情四分区定制渲染 + 审读视图 / 预览试用入口全新。
- **PRD v2.0 影响**：GOV-02 改为**平台预置流程、部署即生效**（部门管理员 ∪ 租户管理员或签；单租户回退平台超管；新建租户同步落库；提交人自动跳过；两来源皆空进异常态不放行）——上列三条缺口被 PRD-1 §3.3 锚点表列为**⚠️ 阻塞前置**，全部归 F055；原决策 D5（审批处理面落位）已由 §3.0.3 关闭。

### 2.5 模型面（DEV-02 模型协议面 / GOV-04）→ research: model-llm

- **可复用**：llm_server / llm_model 双表 + Root 共享 + `BishengLLM`（19 服务商、全链路流式）+ 模型收回错误族（LlmModelOfflineError 等）+ telemetry 每调用全覆盖。
- **缺口**：OpenAI 兼容**入站**端点零现状（现有 `/api/v2/assistant/chat/completions` 是助手外壳、非模型直连）；按名称解析模型不存在（只认数字 model_id，且租户内跨服务商同名 model_name 合法——歧义规则要定义）；持久化用量表 `LLMTokenLog` **无 `app_id` / `api_key_id`**，app 维度只活在 ES 遥测事件里。
- **PRD v2.0 影响**：① 模型协议面收敛为**仅 OpenAI 兼容**（Anthropic 面本版不做；只讲 Anthropic 的工具如客户自装 Claude Code 只能走自带订阅）；② `model:invoke` 与 `chat:invoke` 互不蕴含（裸透传 vs 平台会话机制）；③ GOV-04 **聚合账单顺延 v3.1**、本版降为逐条调用审计（用量表补 key / app 列即够）；④ 模型名即平台模型管理原名、无逻辑档位转换。

### 2.6 广场 / 版本 / 构建页（RT-02 / RT-05 / §3.0.1）→ research: marketplace-versions

- **可复用**：标签体系整套（tag/tag_link + HOME_TAGS + 打标组件）；client 广场页（explore.tsx 标签 tab + 卡片 + 滚动加载）；platform 构建页 `BuildPage/apps.tsx`（卡片流 + 搜索 + 类型 / 状态 / 标签筛选 + 上下线开关 + 版本下拉 + `create_app` 权限点控新建入口）；菜单 gating（web_menu key）。
- **缺口**：第三应用类型接入 ≈ 8 处硬编码扩展点（FlowType / SUPPORTED_APP_TYPES / UNION 子查询 / FGA 映射 / TagDao / client flow_type map…）；RT-05 版本模型全新（现 flow_version 是可变指针语义，**建议独立版本表**）；卡片 ⚙️ 菜单按类型裁剪（现「删除」项在已上线时整项不渲染而非置灰，「创建模板 / 复制」为工作流与助手共用组件，有回归面）。
- **风险**：应用列表 UNION 子查询绕过租户 auto-filter（docstring 明示），新增分支必须手工注入租户条款（C3）；版本快照大 JSON 有 DM8 写放大前科——快照体建议 MinIO 引用而非行内 JSON。
- **PRD v2.0 影响**：① **界面承载面改到 platform「构建 → 应用」**——托管应用作为构建列表第三种类型（正式名「托管应用」），点卡片进应用详情页（发布 / 数据 / 运行日志 / 版本四 tab，无对话区无管家），PRD-2 最小面 WB-14 / WB-06 / WB-13 / WB-15 随本册落在这里；owner「我的应用列表」= 同一页按归属过滤视图，租户管理员因身份短路天然全租户可见；② GOV-09 管理后台应用列表**取消**；③ 应用标签设置、平台侧回滚、迭代变更摘要**顺延 v3.1**（版本记录本身保留）；④ 删除对标工作流：二次确认不要求输入应用名，改以「已上线态须先下线」前置状态闸补强。

### 2.7 审计 / 站内信（GOV-04 / §3.0.3 事件触达）→ research: audit-notify

- **可复用**：v2 结构化审计 `ainsert_v2`（新增事件 = 按命名空间加 action，建议 `app.*` 前缀）；超管跨租户查询后端已支持（tenant_scope=None）；站内信 `send_generic_notify` 任意模块→任意用户，铃铛 / 角标 / 弹窗全链路现成（展示面只在 client 工作台，platform 无消息中心——与 PRD「管理后台不设消息面」吻合）；审批引擎自动发 pending / approved / rejected / withdrawn / 异常站内信，首节点通知需场景侧自发。
- **缺口**：新增一类审计事件需同时改**四处**（后端枚举 + `_UI_VISIBLE_V2_ACTIONS` 白名单 + 前端 `controllers/API/log.ts` 常量 + 3 份 i18n），漏一处即「写了查不到」；「对象应用」筛选为新增；**访问记录 / 运行期能力调用是高频事件，直接进 auditlog 单表会写放大**——需分层（独立表或扩 llm_call_log）；`NotificationsDialog.tsx` 已超 600 行硬规，扩前先拆。
- **PRD v2.0 影响**：① 按 key / 按应用聚合账单顺延；② 审计双归属（actor=应用 / subject=访问用户）保留在 GOV-04 事件清单，其字段与伴生 §4.8.1 一次对齐（F050 引入 subject 列，F055 运行期复用）；③ 事件触达表已固化 11 类事件的接收方与渠道（PRD-1 §3.0.3），催办 / 超时提醒本版不做。

### 2.8 角色权限 / 部署开关 / 配额（GOV-07 / GOV-10 / GOV-03）→ research: quota-tenant-roles

- **可复用**：「菜单 + 功能点子开关」有 `create_app` 完整先例（`roleMenuSelection.ts` 中 `build` 的子项，`AccessType.WEB_MENU=99`；新建角色默认开 `build`、不开 `create_app`）；部署开关三段式（settings → /api/v1/env → appConfig）照抄 multi_tenant.enabled；admin-scope 切租户视图（F019）现成（只在管理后台两页接线）；tenant.quota_config JSON + `QuotaService`。
- **缺口**：资源档位实体全新（表 + 系统管理页 tab + seed 机制）；工场运行时层 / 开放能力层两个部署 flag；「整层不装」的条件路由注册模式（现 router 无条件注册）。
- **已核实缺陷（本版不再阻塞）**：租户配额是**整体覆盖写**（TenantQuotaDialog 只序列化自己的 quotaFields + `aset_quota` 整体替换）——租户实例配额已砍，本版不再触碰该入口；降为已知缺陷登记，补做实例 / 资源量配额前必先修。
- **PRD v2.0 影响**：① **GOV-07 零新增菜单、零新增权限点**——界面通道复用 `create_app`，CLI 通道由密钥 `app:manage` 位把关，两条通道互不校验（服务账号无角色）；② GOV-10 独立成条：三层部署形态（平台核心 / 开放能力层 / 工场运行时层），运行时 **compose 单机与 k8s 集群二选一、产品面一致**；③ 租户级实例数配额**已砍**（补做须以 CPU / 内存为单位）；GOV-03 只剩三档预置档位 + 上线终检「运行环境容量不足 → 待上线态」；④ 应用代码存档与附件本版均不计入存储配额（`storage_gb` 口径只 SUM knowledgefile，正文已按现状订正）。

### 2.9 运行时基建（RT-01 / RT-07 / RT-08 / DEV-04 托管 / GOV-10）→ research: mcp-runtime-infra, appdb-storage-sdk

- **可复用**：`mcp>=1.27.0` SDK 已在依赖内（server 原语可用，需 POC）；MinioStorage 全套 + 灵思 workspace 前缀隔离 / copy-forward 快照范式（代码快照可照搬）；cookie path=/ host-only → `/apps/{slug}` 同源免二次登录零后端改造；client 401→LOGIN_PATHNAME→登录→回跳链路现成（需补 query/hash）。
- **绿地（全仓零先例）**：per-app 实例编排（拉起 / 限额 / 健康探测 / ≤5min 自愈）——无 docker SDK、无进程管理器、无 cgroup 操作；`/apps/{slug}` 动态路由（nginx 纯静态 conf；商业版 Java 网关只认 /api，需 app-proxy 统一承接）；per-app 数据库供给（无动态建库代码）；schema diff 引擎与迁移前自动快照；bisheng-sdk / bisheng CLI（无任何可发布包工程、无 [project.scripts]）；安装件分发端点；内网 pip 镜像全仓不存在（托管契约「依赖包经平台内网镜像安装」= 全新建设）。
- **风险**：单机已合跑全家桶（114 曾因 linsight worker OOM 死机），叠 per-app 实例必须靠档位限额 + 运行环境容量准入强约束，否则与 RT-08「平台必须正常」直接冲突；docker.sock ≈ host root 权限（方案：独立最小权限编排器 runtime-manager 唯一持有、backend 零 docker 依赖）；app 附件不能混入 public bucket（匿名读策略）。
- **PRD v2.0 影响**：① **k8s 由 v3.1 提前到本版**——第二套执行后端（Deployment / Service reconcile、命名空间 RBAC、档位→requests / limits、RuntimeClass、NetworkPolicy）+ **镜像构建与分发**（多节点 Pod 调度到任意节点，镜像必须进仓库；不交 docker.sock → 无守护进程构建器）+ 三项集群前置探测（CNI NetworkPolicy / StorageClass / RuntimeClass）；k8s 侧 RBAC 反而比 docker.sock 更好收窄，不是额外风险面；② per-app 数据库形态已由方案定为 **SQLite-per-app（小）/ Postgres（中）**、与平台 MySQL / DM8 解耦（`bisheng dev` 本地起 sqlite 注入同名环境变量，DEV-05 / DEV-07）——原 D7「appdb 双库」问题消解，只剩 C2 适用性确认；③ 单应用单实例、无扩缩容；④ RT-08 两个过渡态（发布中 / 应用恢复中）不落报错页，两形态验收口径与时限相同。

---

## 3. Feature 拆分方案 v2（提议，待 ★ 确认）

编号从 **F049** 起（F043–F048 已被 `features/v3.0.0-beta1/` 占用）；不变量编号从 **INV-27** 起（详见 release-contract 编号约定）。**保留 F049–F057 编号与目录名（语义仍对得上），新增 F058 / F059**；F050 / F051 / F053 / F054 / F055 / F056 / F057 的范围相对 v1 拆分有实质变化，逐行见 release-contract 变更历史 2026-08-17。

| # | Feature | 批次 | 覆盖 PRD-1 v2.0 条目 / 伴生 PRD | 依赖 | 方案 F1xx |
|---|---------|------|--------------|------|-----------|
| F049 | openapi-auth-baseline | A | 伴生 P0：R1 底座 + R4 服务账号（含**资源归属人**）+ R5 端点接入（36 HTTP + 2 WS；6 个 `/chat/*` 不暴露）+ R6 管理界面（v2.1 授权页形态）+ R9 升级须知（**零迁移**）+ 三扩展位登记入权限位清单 + 开放能力层部署开关 + 分享链接通道 + 四处既有缺陷修复；PRD-1 DEV-01 表单层增量 + GOV-08 四条承诺 | — | F101 |
| F050 | identity-modes | A | 伴生 P1：R2 两种模式 + 外部用户标识头 + R3 五道准入 + R7 审计双归属 + 裸 `user_id` 收口 + **`delegate` 位与委托配置区**（含伴生 AC-48 互斥硬阻断 / AC-46 归属优先级） | F049（伴生 AC-12 检索等价依赖 F052） | F101 |
| F051 | model-protocol-gateway | A | DEV-02 模型协议面（**仅 OpenAI 兼容**、`model:invoke`、按名解析、流式；可用范围 = GOV-05 租户模型配置）+ GOV-04 模型调用逐条审计带 key / 应用维度（聚合账单顺延）+ 入口拒绝 `delegate`（INV-31） | F049 | F102 |
| F052 | mcp-server-face | A | DEV-02 MCP 六类工具（应用数据 / 状态日志两类随 F054 / F055 接线）+ **统一检索门面**（文件级双层 + fail-closed；伴生 §4.4.6 交付前提；GOV-05 运行时 / F057 共用）+ `identity:read` 组织查询 + 入口拒绝 `delegate` | F049 | F105 |
| F053 | dev-cli-skills | A 尾 / B | DEV-03 两包 + DEV-04 CLI `login`（自动 sync）/ `skills sync` / `dev` / `logs`（`deploy` 随 F055 启用）+ DEV-05 本地身份注入 + 本地 sqlite 同名注入 + CLI 安装件分发 + **DEV-01 接入信息区与一键复制** + `login` 拒 `delegate` | F049, F051, F052 | F106（部分） |
| F057 | bisheng-sdk | A 尾 / B | DEV-07 三件套（auth / retrieve / storage）+ 开发者指南；chat / appdb 刻意不进 SDK | F052, F053；storage 依赖 F054 | F106（部分） |
| F058 | openapi-responses（**新增，登记项**） | A | 伴生 P1「日常模式会话 Responses 子集契约」——**不在 PRD-1**；补齐版本层归属；是否进 v3.0.0 由产品定（N2） | F050 | F101 |
| F054 | app-domain-runtime | B | 托管应用领域模型 / 状态机（§3.0.2）+ GOV-01 `app` 资源类型注册 + compose 执行后端（runtime-manager）+ app-proxy + RT-01 入口与四类兜底页 + RT-07 资产持久 / 下线 / 重新上线 / 显式删除 + RT-08 稳定性 + GOV-03 档位→容器限额 + per-app 数据库 / 附件 + 构建页「托管应用」类型 + 应用详情页壳（**WB-13 / WB-06**）+ GOV-10 工场运行时层开关与未部署引导页。**spec 阶段可再拆** | F049 | F103, F107, F104（FGA） |
| F055 | app-publish-pipeline | B | RT-03 / RT-04 / RT-05 + DEV-04 deploy 管线（预检 / 扫描 / 审批 / 终检）+ **GOV-02 预置审批流 + 三项阻塞前置** + GOV-03 ResourceTier / 管理 tab / 选档 / 终检 / 待上线态 / 手动上线 + GOV-05 能力总线（声明→注入 / 收回错误态）+ 应用运行期凭据自动签发回收 + 审批人审读视图与临时预览实例 + **WB-14 / WB-15** + CLI `deploy` / `logs` 接线。**spec 阶段可再拆** | F054, F049, F051, F052 | F112, F104（审批） |
| F056 | app-square-governance | B | RT-02 广场 + GOV-01 授权两个入口接线与验收 + GOV-04 审计扩展 / 查询面 / 导出 + GOV-07 `create_app` 复用与 ⚙️ 菜单裁剪 + §3.0.3 事件触达接线 | F054, F055 | F104 |
| F059 | k8s-runtime-backend（**新增**） | B | GOV-10 k8s 形态：reconcile / RBAC / 档位映射 / **镜像构建与分发** / 集群能力探测 / 双形态一致性回归；方案 F113「不可裁剪」 | F054 | F113 |

**PRD-1 §1.4 覆盖矩阵**（21 项 → owner；多个 owner 时首个为主承接）：

| 条目 | Owner | 条目 | Owner | 条目 | Owner |
|---|---|---|---|---|---|
| DEV-01 | F049（表单层）/ F053（接入信息区） | RT-01 | F054 | GOV-01 | F054（类型注册）/ F056（交互与验收）/ F055（发布面入口） |
| DEV-02 | F052（MCP）/ F051（模型面） | RT-02 | F056 | GOV-02 | F055 |
| DEV-03 | F053 | RT-03 | F055 | GOV-03 | F055（档位实体 / 选档 / 终检）/ F054（限额落地） |
| DEV-04 | F053（四命令）/ F055（deploy 管线与 `deploy` / `logs`） | RT-04 | F055 | GOV-04 | F056（审计面）/ F051（模型调用逐条）/ F050（双归属字段） |
| DEV-05 | F053 | RT-05 | F055 | GOV-05 | F055（注入 / 收回）/ F052（检索门面）/ F051（模型范围） |
| DEV-07 | F057 | RT-07 | F054 | GOV-07 | F056（界面通道）/ F049（`app:manage` 位登记） |
| — | — | RT-08 | F054 / F059 | GOV-08 | F049 |
| — | — | — | — | GOV-10 | F054（层开关 / compose）/ F059（k8s）/ F051–F053（开放能力层 WHERE 条款） |

不映射项：DEV-06 / GOV-09 已取消；RT-06 / GOV-06 属 PRD-2；RT-09 顺延（方案 F109）；GOV-05 **密钥引用**（录入面 WB-05 属 PRD-2）待产品确认（N4）；DEV-07 验收 3 随 PRD-2 WB-01。

说明：
- **批次 A = 开放能力层**，按 GOV-10 可独立于工场运行时交付，且是批次 B 的鉴权 / 凭据地基。建议顺序 **F049 → F052 → F051 → F053 → F050 →（F058）→ F057**（F052 早于 F050 因检索门面是模式 D 集合相等的前提；F057 的 storage 面等 F054）。
- **批次 B**：F054 → F055 → F056，F059 与 F055 并行（须在发布管线联调前可用，方案 Wave-2）。
- F054 / F055 体量大，spec 阶段允许再拆（F054：编排后端 vs 领域模型 / 界面壳；F055：审批与版本 vs 能力总线注入）；拆分时在 release-contract 表 3 更新。
- **PRD-2 最小承载面逐面归属**：WB-13 运行日志 / WB-06 数据面 → F054；WB-14 发布面 / WB-15 版本与差异 → F055；WB-01 模板随 PRD-2。
- 审批中心前置修复（`tenant_admin` resolver 改用真租户管理员）属行为变更（存量频道订阅 / 知识空间加入两场景的实际审批人会变），需在 release note 声明。

---

## 4. 关键决策清单（★ 需用户逐项拍板）

### 4.1 v1 决策（2026-08-06）状态

| # | 决策 | 状态 |
|---|------|------|
| **D1** | 首批启动 feature：批次 A 先行、F049 第一个进 spec | **已定**（F049 spec ★ 已过；本次按 v2.1 重写后需第二次 ★） |
| **D2** | 开发基线分支 | **已定：`3.0-vibe`（含 F048）**，INV-8~26 无条件生效 |
| **D3** | app 资产载体：复用 flow 表新增 FlowType vs 独立 app 表 | **仍开放，随 F054 design 定**。倾向独立 app 表 + 构建页列表 UNION 第三支（版本 / 档位 / 状态机字段装不进 flow 表；PRD-1 §3.0.1 要求同列表 + 复用版本下拉与上下线开关） |
| **D4** | 运行时隔离选型 | **形态已由 PRD-1 GOV-10 + 方案 §4.5 定**：compose 单机 = docker API 经独立最小权限编排器 runtime-manager（backend 零 docker 依赖）；k8s 集群 = 命名空间 RBAC。**残留**：信创无 docker / 无 k8s 环境的沙箱档位（方案：加固 Docker 档兜底），F054 design 定 |
| **D5** | 审批处理界面落位 | **已解**：PRD-1 §3.0.3 明确处理面在 client 审批中心、配置面在 platform，与现状一致；审读视图 + 临时预览实例是 client 审批弹窗上的新增内容（F055） |
| **D6** | strict fail-closed 边界 | **已解**（INV-30）。残留「全局超管判定在 OpenFGA 故障时回落 legacy 角色位」是否收紧，随 F049 design |
| **D7** | appdb 双库范围 | **方案已定 SQLite-per-app / Postgres、与平台 MySQL / DM8 解耦**（PRD-1 DEV-05 / DEV-07 已按此写）；**残留**：宪法 C2 双 DB 法对 per-app 库的适用性 / 豁免在 F054 design Constitution Check 确认 |

### 4.2 v2 新增决策（2026-08-17 提出；**同日用户授权「全部按建议拍板」，以下各行「建议」即为决议**）

| # | 决策 | 决议（= 原建议） |
|---|------|-----------|
| **N1** | **拆分 v2 确认**：11 个 Feature（F049–F059）及批次 / 依赖 / 建议顺序（§3）；F054 / F055 是否**现在就拆**（各拆两个）还是留到 spec 阶段 | **已定**：11 个；F054 / F055 留到各自 spec 阶段再拆（拆早了依赖图先于 What 固化） |
| **N2** | **F058 openapi-responses 是否进 v3.0.0**：伴生 PRD 要求它与 P1 身份传递同期交付（12–15 人天，且估算需重算），但 PRD-1 全册零引用 | **已定**：登记为 v3.0.0 版本层 Feature、排期由产品定；不在 MVP-114 纵切上（见 [mvp-114-path.md](../mvp-114-path.md)） |
| **N3** | **统一检索门面 owner = F052**，批次 A 顺序 F049 → F052 → F051 → F053 → F050；F050 的模式 D 集合相等（伴生 AC-12）依赖 F052 | **已定**：是（门面归 F052） |
| **N4** | **GOV-05 密钥引用是否随本册**：录入面 WB-05 属 PRD-2、不在 PRD-1 §1 最小承载面清单；无录入面则 CLI 应用的密钥引用无值可注 | **已定**：本册能力总线只做**模型 + 知识库**两项，密钥引用整体随 PRD-2（F055 spec 按此写、注入通道预留引用名位） |
| **N5** | **伴生 PRD v2.1 草案内部残留三处**：§4.7 引言「绑定使用人可选 / 应用 token 另占一 tab」、§4.7.2「删除阻断」——与 §4.7.1 / §4.7.4 / AC-31 / PRD-1 GOV-08 矛盾。F049 spec 已按较新决议写（AC-23 / AC-48 / 排除应用运行期凭据 tab） | **已定并执行**：2026-08-17 已回修伴生 PRD 三处（只删残留、不动决议，见其修订记录） |
| **N6** | **PRD-1 GOV-10 / GOV-08「未部署开放能力层则 API key 管理页不出现」vs DEV-01 ⑥「服务账号模块本身随该 PRD 交付」**。F049 spec 按后者（AC-49：服务账号模块恒在，开关只 gate 三扩展位与接入信息区）——v2 开放 API 发布即带鉴权，服务账号与密钥是唯一接入方式，不能被部署开关藏起来 | **已定并执行**：spec 口径确认（AC-49）；2026-08-17 已回修 PRD-1 GOV-10 规则表 / 验收 4 与 GOV-08 界面表措辞 |

次级决策（spec / design 阶段随对应 feature 定，先登记）：模型名歧义规则（跨服务商同名 model_name，F051）；MCP Server 部署形态（同进程 mount vs 独立进程，F052）；`/apps/{slug}` 路由承接者（app-proxy 与 nginx / 商业版 Java 网关的接线，F054）；高频审计事件分层（F056）；CLI 安装包形态（wheel + 内网镜像 vs 单文件二进制，F053）；k8s 镜像仓库对接方式（复用客户 Harbor vs 平台自带，F059）；`app_factory` 错误码段位（161 起，F054）；F049 决议-6 f（`delegate` 位随 F050 而非 F049 只存不生效）与 决议-6 i（share-token 会话以分享创建者为执行主体）——**2026-08-17 已按建议拍板**（F049 spec §4）。

---

## 5. 重大风险登记（进 design 阶段必须消化）

1. **新资源类型的存量生效缺口**（按 F048 基线重核）：Catalog 的「动作↔资源类型范围表」只在首次迁移与草稿发布时写入，变更类型枚举里没有「改资源范围」，迁移脚本又因 checksum 不符无法重跑——给存量环境加 `app` 类型必须新写运维脚本或扩展变更类型。F054 design 必须前置演练（F048 存量被拦教训）。
2. **审批人来源三前置**（F055）：`tenant_admin` 来源错用系统超管 / Root 租户恒空 / 新建租户不 seed——任一未修，GOV-02「部署即生效」在多租户或单租户形态下即失效（首次发布卡死或全压超管一人）。修正对既有两场景是**行为变更**，须 release note 声明。
3. **单机容量**：租户实例配额已砍，per-app 实例叠在已合跑全家桶的单机上，RT-08「平台必须正常」的护栏只剩**档位限额 + 上线终检 / 重新上线的运行环境容量准入**（GOV-03）——F054 / F055 必须把容量准入做成硬闸门而非提示。
4. **k8s 形态三前置与镜像分发**（F059）：CNI 不支持 NetworkPolicy 则出站白名单为空、StorageClass 缺失则 SQLite-per-app 的 RWO 卷不成立、RuntimeClass 缺失则沙箱档位降级——必须部署前探测、不满足显式告警；镜像构建与分发是 k8s 多节点的**唯一新增必需件**（不交 docker.sock → 无守护进程构建器 + 仓库），排期未含。
5. **DM8**：版本快照大 JSON 有写放大前科（快照体走 MinIO 引用）；per-app 库已解耦 MySQL / DM8，但平台侧 app 表 / 版本表仍受 C2 约束。
6. **委托红线贯穿**：应用工场全册无模式 D 场景（INV-31）——MCP / 模型面 / CLI 三面入口必须按位拒绝 `delegate` 密钥、不得静默落回模式 S；托管运行期身份走平台登录态（app-proxy 注入），不得挂在委托头上（伴生检查 3 会把管理员挡在所有应用之外）。
7. **三个「漏一处即静默失效」的机械性坑**：应用列表 UNION 子查询手工注入租户条款；新表注册 `_TENANT_AWARE_MODEL_MODULES`；审计事件四处 lockstep（后端枚举 / UI 白名单 / 前端常量 / i18n）——写进各 feature design 的已知坑清单。
8. **PRD 残留被当成需求实现**（N5 / N6）：伴生 §4.7.2 删除阻断、§4.7 引言应用 token tab、PRD-1 GOV-10 API key 页隐藏——若开发只读 PRD 不读 spec 会实现出已被否决的行为；两 PRD 回修前以 spec 为准。
9. **审计与访问记录写放大**：应用运行期能力调用 / 访问记录是高频事件，直接进 auditlog 单表不可取（F056 design 分层）。

---

## 6. 下一步

**进度（2026-08-17）**：拆分 v2、release-contract（表 1 / 表 2 / 表 3、INV-31、候选 INV-32~36）、F049 spec（65 条 AC，经 `/sdd-review` 独立审查修订）全部就绪；**用户同日授权全自动模式：N1–N6 与 F049 决议-6 f / g / h / i 全部按建议拍板，后续 ★ 不再等待确认**。

1. 目标锚定 **MVP-114 纵切**（[mvp-114-path.md](../mvp-114-path.md)）：在 114 服务器上以 CLI 导入一个表单问卷小应用 → 预置审批流 → 上线 → 设可见范围为全员 → 所有人从应用广场打开使用。
2. 文档顺序：F049 design + tasks → F054 spec / design / tasks → F055 → F053 → F056（各按 MVP 纵切标注首波任务）；F050 / F051 / F052 / F057 / F058 / F059 的 spec 随后补齐、不在纵切上。
3. 每份 design 经 `/sdd-review design`（Constitution Check）、tasks 经 `/sdd-review tasks`；实现阶段按 tasks 波次推进，`/task-review` → `/e2e-test`。
4. **research/ 的时效性提醒**：11 份调研在 `main`（pre-F048）上完成，与本基线相差 242+ 个后端文件；本分支 2026-08-16 又合入 `feat/3.0.0-beta1` 最新提交。已按 F048 重核的三块结论收在 baseline-recheck.md，**与 research/ 冲突时以它和 §2.2 为准**；其余维度在 design 阶段被引用前由各 design 的探查阶段重核（尤其检索、模型面、审批锚点以 PRD-1 §3.3 锚点表为准）。
5. UI 参考：Claude Design 交互稿已拉取到 [ui-demo/](./ui-demo/)（含结构化摘要 README），design 引用时以 PRD 为准、demo 为参考。
