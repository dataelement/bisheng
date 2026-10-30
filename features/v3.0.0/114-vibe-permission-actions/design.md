# Design: Vibe 全操作权限动作统一与具体租户管理视角

> **统一 v2 修订设计已确认，实施中。** 2026-10-30 用户已确认 70 条 AC 并要求进入设计，随后明确“创建资源还是属于归属人，这个逻辑不变”。下文的“现状”是静态核对代码；“选定/拟改”是已确认目标；本地实现与定向验证见§4.1及verification，真实部署E2E与最终L2尚待完成。用户随后澄清：共用读取/调用接口维持已有可见性与最小权限，本轮不重做助手、工作流等资源鉴权；已据此收窄 D3 和 §4.4；用户随后要求统一保留运行协议 v2，已补 D9、§4.11，并将 spec 收敛为 71 条 AC。用户在 R3 实质评审后采纳建议：旧导入/升级/rebind 一并退役，环境变量确认重建与新版本发布各沿已有流程，不新增独立通用实例重建。独立评审提出 R4/R5/R6 后，用户再次要求“按照建议修改”；本稿补齐系统自愈意图、维护首个副作用前准入及预览原子登记/回收，71 条规格不变。

**关联**：[spec.md](./spec.md) · [规格复审](./spec-review.md) · [设计自审](./design-review.md)。版本 v3.0.0，基线 `bb62790ad22a3204493e7dce5878e0a4f7109599`，分支 `codex/114-vibe-permission-actions`。2026-10-30 用户已确认整份修订设计，tasks 已拆解并开始实施；设计复审哈希保留为确认前快照。

## 1. 目标与非目标

统一 Vibe 已有操作的资源鉴权，以真实主体和现有六个 F048 动作决定资格；平台管理数据始终绑定一个具体租户。保持资源归属自然人、发布必审和现有运行安全边界，补齐代发布、预览和异步执行的权限接线。

非目标沿用 spec：不迁移资源或批量补授权，不新增动作、权限体系、PAT 通道、明文读取、回滚/版本切换或编排后端。只保留运行控制协议 v2，不新增独立通用实例重建、编排后端或重写 v2 状态机。不会因保存环境变量自动重启应用。仅做本功能必要的定向验证。助手、工作流、知识库共用读取/调用接口继续按既有可见性、use 和业务条件处理，不新增接口拆分或统一必填请求头；本轮动作映射对象为 Vibe app。可见不等于获得编辑、删除或发布权限。

## 2. 关键约束

- 遵循 [constitution.md](../../../docs/constitution.md) C1–C7 与 [release-contract](../release-contract.md)，不在本文重抄全局规则。
- **归属不变**：服务账号首次创建 app 时，`app.owner_user_id` 仍取经 F113 校验的 `principal.resource_owner_user_id`，tenant 取既有经验证的账号/归属人租户；后续操作不改 owner/tenant。实际服务账号主体进入鉴权、可撤销初始 Grant 和操作者审计，受保护所有者仍是自然人。
- 服务账号、自然人会话、运行应用、审批任务、内部运维是不同来源；不能互相伪装。入口 scope、模式、F113、F066 约束继续成立。
- 已上线实例、自愈、清理与“新增一次用户授权效果”分开：用户意图复核当前主体/凭据和对应动作；系统自愈复核既有批准运行意图及来源围栏，不复用历史操作者。不得仅凭 deploy、auto_commit 或后台身份豁免。首次准入必须早于 maintenance 投影和停旧 writer；历史操作者撤权不主动停止既有服务。
- 同一 API 有不同内容层级；不能先返回源码、配置或数据，再靠前端隐藏。管理基础信息采用五个管理动作的 OR，组合写入采用 AND。
- **唯一运行协议**：Docker/K8s 共用 v2 任务、身份与阶段校验，不补 v1 阶段授权或保留回退执行；应用包格式、平台 API 版本与运行协议不混同。
- 单租户退化为具体 Root 租户；K8s/Docker 产品权限相同。SDK/运行入口和内部任务不继承浏览器租户选择。

## 3. 方案对比与选定

### D1：应用业务事实与 F048 动作判定分层

- **备选**：继续在每个服务补 owner/admin 特判；或把所有业务状态塞进 permission 模块；或薄的应用授权门面复用 F048。
- **选定**：在 app_runtime 新增 `AppAuthorizationService`，经 `app_runtime/application/authorization.py` 对外发布；负责验证 app/tenant/state、可信操作用途与内容层级，调用已有 app adapter/F048 runtime 判定具体动作。
- **原因**：现有 [业务鉴权入口](../../../src/backend/bisheng/permission/application/business_authorization.py) 对不受数据范围限制的超管有提前允许路径。调用者必须先验证目标事实，不能把这一允许当作存在、租户或状态验证。app adapter 的已加载记录批量校验可复用，不新增授权引擎。
- **何时重审**：F048 提供等价的统一已验证目标接口时，可收敛薄门面；不能借机改变其他资源动作。

### D2：首次创建传递真实主体，复用现有创建授权

- **备选**：借用自然人 owner 的权限；创建后由业务代码手写 Grant；重新创建一种发布者模型；复用已有 F048 创建生命周期。
- **选定**：创建函数同时接收“自然人归属事实”和经准入的真实 `PermissionActor`，二者不互相推导。`authorize_created` 继续为自然人登记受保护 owner；实际创建主体为服务账号时，复用 F048 已有、可撤销的 manager `CREATOR_GRANT` 来源。
- **原因**：[runtime.authorize_created](../../../src/backend/bisheng/permission/application/runtime.py) 已经有这条服务账号分支；[AppProvisionService._project_owner](../../../src/backend/bisheng/app_runtime/domain/services/app_provision_service.py) 当前人为构造自然人 actor，导致该分支未用于 Vibe 首发。只改真实主体传递，保持资源归属和权限投影真相。
- **约束**：读取 CURRENT Catalog 验证初始化后的真实主体确有 edit 与 publish，记录实际生效模型/动作；不把 manager 名称硬编码成固定动作，不升级成 owner 兜底。初始来源按既有 F048 规则可撤销、仅限新 app；历史 app 不自动补权。已有 CREATOR_GRANT 的 F048 语义原样保留，应用层不再另写创建者特判。
- **失败处理**：使用既有投影账本及 `rollback_created`，确认逆向投影完成后才删除孤立业务行；不确定结果保留围栏和可治理记录，返回失败，不排发布任务。不在 FGA 状态不明时直接 SQL 删除 app 留下孤立授权。
- **何时重审**：CURRENT 模型不覆盖首发所需动作时，先报告权限初始化失败；如需另造模型或扩大授予范围，回到已确认规格边界评审。

### D3：具体租户范围与既有共用接口保持解耦

- **备选**：对 middleware 前缀下全部接口强制新租户头并重划管理/业务路由；仅移除全平台 UI；收窄既有范围解析、只在明确管理写入口保护预期租户。
- **选定**：扩展 F019 `TenantScopeService` 和 application 门面，形成 `EffectiveManagementScope`。沿用 `admin_scope:{user_id}`、当前 TTL 和超管验证；空/失效选择回到本人合法租户，切换只接受 active 的具体租户，失败保留原值。
- **共用接口边界**：助手、工作流、知识库等共用读取/调用继续使用现有最小必要权限和可见性检查，不拆接口、不增加统一必填租户头、不要求 Vibe app 的 edit/publish；原写操作保持自己的原有动作要求。管理列表的具体租户数据过滤按 AC-09 至 AC-18 收窄，与这些资源的权限动作语义分开。
- **预期范围保护**：`X-Management-Tenant` 只用于服务端明确登记的 Vibe 管理写，以及会按当前视角确定目标租户的专用管理新建/批量写入口；不按 URL 前缀强制作用于共用读取或业务调用。服务端与已解析范围比较并 pin 本请求；不一致拒绝写入。F113 原 `X-Service-Account-Tenant` 合同继续有效。
- **原因**：用户要求保持共用接口既有可见即读/按原 use 调用逻辑；此前全路径强制请求头超出本轮 Vibe 动作映射需要。跨标签页与回退防错写保留在具体管理页及专用管理写入口，查询仍用 ContextVar 和 repository，不引入新鉴权体系或手写 tenant WHERE。
- **何时重审**：若未来单独提出其它资源权限重构、共用接口存在已证实的数据泄露，或需要标签页独立范围，再另行评审，不在 F114 顺带改造。

### D4：归属、审批申请人与实际提交主体分别留存

- **备选**：把 app owner 改成提交者；把审批申请人直接换成服务账号；保持申请人与路由，另补提交主体与自审关联人。
- **选定**：`app` 和 `AppDeployment.owner_user_id` 保持资源归属人；`ApprovalInstance.applicant_user_id` 仍为该自然人，部门路由仍按该人。新增发布授权上下文固定真实主体和自审关联自然人，供审批候选过滤与审计读取。
- **原因**：避免破坏 F113 冻结来源和自然人申请人合同；同时排除 app owner 与实际提交关联自然人。服务账号使用接收时固定的账号归属人参与排除，审计仍显示服务账号而非声称该自然人实际用钥。
- **限制**：过滤发生在应用发布 handler，后续节点/异常重试/指定审批人同样调用场景校验。通用审批服务只增加可选的场景校验扩展点，默认行为不变；其他三个场景不会套上 Vibe 规则。仅配置一人不代表全租户单管理员，无候选进入既有异常态。
- **何时重审**：产品改变申请人或审批路由依据时，作为独立合同变更处理。

### D5：预览用途与能力上下文显式绑定

- **备选**：按用户是否有 admin/edit 自动启用审批例外；两类预览共用同一会话/凭据；显式区分 management 与 approval。
- **选定**：在现有预览会话增加用途和审批绑定；管理预览要求 edit，使用本人；审批预览校验当前有效任务，使用本人身份、归属人能力例外。会话、数据库/附件空间和凭据按用途隔离；同一人双重身份也不能混用。
- **事务取舍**：否决先独立提交 running 会话/凭据再提交 operation。复用同一 SQL session/RuntimeDeliveryRepository UoW，以 AppVersion 行锁串行同版本的短期预览登记，会话、独立 credential、operation、sealed_env 及必要审计同事务提交；提交后才 wakeup。仅扩展既有状态/字段和 application 端口，不新增表、锁服务或补偿框架。
- **原因**：当前 `AccessSubject` 只保留 user_id，不能让能力层区分审批例外；只在页面判断角色不能闭合 INV-36。扩展已签名 OBO 的解析投影及现有组合根注册端口，以可信会话解析能力上下文，不信任应用自带的用途字段。
- **何时重审**：若产品取消审批预览例外，可将两类能力来源合并；若这些控制表迁出同一数据库，则另行评审跨库一致性。当前采用现有单库事务，不提前建设跨库机制。

### D6：异步记录身份来源，执行阶段复核当前权限

- **备选**：保存上传时的 allowed=true；每阶段模拟 owner；按 deploy/auto_commit 豁免后台操作；区分用户请求与可信系统恢复来源后逐阶段验证。
- **选定**：只在统一 v2 链路中保存服务端生成的 `authorization_context`，显式区分 `origin_kind=user_request` 与 `origin_kind=system_recovery`。用户来源按用途复核主体、凭据、F113/动作或审批任务；系统恢复来源绑定 backend 已核实的原 serving route、批准版本和原运行操作，逐阶段验证来源仍成立。源码准备、生成版本/审批、进入维护与停旧 writer、迁移、启动及提交路由各有准入；不保存永久允许结论、原 JWT 或密钥。
- **原因**：Celery、backend、manager 分进程，不能依赖 ContextVar 跨任务继承。现有 recover() 和用户配置重建都生成 deploy/auto_commit，通用标志无法区分授权来源；manager 还会先 report maintenance，再停旧实例，不能等到迁移/启动才查权限。用户来源不完整时拒绝新效果；系统恢复必须能由可信运行记录证明，必要清理独立续办。
- **何时重审**：若产品将已受理发布定义为不可撤销的系统授权，需重新确认 AC-40，而不能在实现中放宽。

### D7：取消依据业务用途，使用当前取消者资格

- **备选**：所有 deploy 取消仅校验 publish；复用原发起者的权限；按受信业务用途对当前取消者检查原动作集合。
- **选定**：服务端写入 operation 的 `authorization_context.purpose`，映射 spec §3.1。`config_restart` 和新内容发布准备取消需 edit AND publish，`approved_start` 需 publish，restore 按冻结的是否启动区分。不登记 `runtime_upgrade` 用途，旧 upgrade/rebind 入口退役；代码、镜像和运行环境变更沿新版本发布。`system_recovery` 不提供用户通用取消入口或按钮；当前有 unpublish 的用户通过既有应用下线流程终止运行意图、取消/清理相关在途恢复。系统停止与清理不模拟原发布人，也不依赖原发布人仍持权。
- **原因**：[secret_rebuild_service](../../../src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py) 与普通上线都使用 deploy kind；kind 不能作为唯一授权依据。操作用途、app/version/generation 一致性由服务端记录，取消请求不能重写它。
- **何时重审**：新增业务用途时必须登记动作集合和可取消阶段；未知用途拒绝用户取消，系统安全清理照常运行。

### D8：基础响应与私有内容分别授权

- **备选**：完整详情返回后由组件隐藏；复制 owner 判断到每个 tab；服务器按动作裁剪响应，前端按同一能力渲染。
- **选定**：基础 app/publish/runtime 状态返回 `allowed_actions` 和安全摘要，源码/完整 manifest/详细 failure/配置/数据/日志/完整授权名单使用对应独立接口。基础可见不触发所有 tab 的预取。
- **原因**：只有 publish、delete 或 manage_permission 的用户需要确认对象，但不因此取得 edit 管理内容。界面读取 action 集合和业务状态，移除 is_owner 作为操作资格的判断；后端每次重新验证。
- **何时重审**：将来增加只读/导出/密钥专用动作时另改 Catalog 与规格，当前不靠 owner 特判拆分 edit。

### D9：运行控制只保留 v2，删除旧兼容链

- **备选**：给 v1/v2 各补阶段授权；保留双协议并冻结 v1；统一 v2、退役旧入口。
- **选定**：按用户“尚未正式对外发布”和“收敛统一一下”的决定，仅保留 v2。backend/manager/app-proxy/egress-proxy 使用同一协议；默认及示例为 2，显式非 2 配置在启动工作/对账之前拒绝；旧运行 RPC 与旧绑定导入、升级、rebind 入口不再注册或被消费，不以旧签名/本地记录回退。
- **原因**：Compose 和 K8s Chart 已选择 v2；v2 的 Docker/Kubernetes executor 已覆盖 bundle、image 和 source-image；旧链主要为历史兼容。两套阶段授权会重复维护并留下旧入口绕过风险。本地代码已默认并强制 v2，旧控制路由不再注册；真实部署与旧环境处置尚未执行。旧 rebind 调用普通 deploy，正常在线同版本会直接返回已有实例；它服务旧导入重绑，不能作为通用 v2 重建依据。保留配置确认重建和正常新版本发布已能覆盖本轮真实需求。
- **保留**：F048 六动作、现有 v2 操作/状态机/围栏、构建及 SQLite 公共工具、SDK、OBO、入口鉴权和三种交付能力；不按 legacy 文件名整体删除。平台 `/api/v1`、`/api/v2` 以及 manifest_version 的数字不由本次退役规则决定。
- **何时重审**：未来确有已发布的外部兼容承诺或本轮盘点证明 v2 缺必要能力时，先报告证据并评审；不能在实现中自行恢复 v1 回退。

## 4. 系统现状与拟改数据流

### 4.1 当前关键事实

**2026-10-30 实施快照**：已完成六动作门面、管理范围、内容/生命周期、真实发布主体、候选与撤回、分阶段授权和系统自愈来源、双用途预览、模型/能力及前端接线。新增查询均在所属 Repository；实际任务与必要定向验证见 [tasks.md](./tasks.md)、[verification.md](./verification.md)。尚未执行真实部署 E2E；工作区 lint/typecheck 仍有未修改文件或既有依赖错误，不能宣称整项交付通过。

| 实际文件/入口 | 本地已接线行为 | 仍需证明 |
| --- | --- | --- |
| app_authorization_service / application.authorization | 目标事实先验；管理五动作 OR；组合 AND；真实 SA 不冒用 owner | 真实 F048 授权/撤权配对 |
| app_query / WorkFlowService 混合构建列表 | 分页前收窄 Vibe 动作并投影 allowed_actions；其它类型动作保持 | 页面真实多角色验证 |
| app_state / meta / data / secret | 六动作替代特殊 owner 门槛；线上删除拒绝、确认、CAS、清理保持 | 生命周期与配置差异实测 |
| runtime_management / runtime_profile_service | 私有依赖/快照 edit；恢复按是否启动叠加 publish；取消当前人检查原业务全部动作 | 私有材料、恢复与取消实测 |
| snapshot_browse / version_diff | 私有内容 edit；当前有效审批任务仅可审读冻结待审版本及合法基线 | 任务失效及租户配对 |
| app_provision / F048 adapter | 自然人 owner 固定，真实创建 actor，投影不确定不盲删 | 真实 SQL/OpenFGA 创建补偿 |
| publish_pipeline / precheck / release_tenancy | 当前资格前置，用户来源冻结，准备/建版本/审批前复核；worker 原 tenant headers 路径保留 | 真实异步受理与审批 |
| approval app_candidates / scenario handler / exception hooks | 正常/重试/指定审批者均过滤当前资格与自审；单管理员按真实总人数判定 | 真实异常分配流程 |
| app_publish.withdraw / 审批仓储 | 当前 publish + 冻结实例目标，同事务更新任务、实例、withdrawn日志 | 真实撤回与终态 |
| runtime_authorization / operation / coordinator | 用户当前凭据动作与系统批准意图分型；维护前许可与fact重验；auto_commit无豁免 | manager故障与撤权时序 |
| preview_operations / preview_runtime / PreviewRuntimeRepository | Version→operation→session/credential 锁序；同UoW登记/封装/回收，提交后wake | 真并发与提交响应丢失 |
| preview_access / runtime_identity / open_api.preview_context | 当前用途、viewer/task、credential/op/session、冻结版本、签名OBO；当前访问重新校验 | 实际HTTP/WS/SDK模型检索 |
| 模型范围 / capability_bus / composition | 声明取预览冻结版本，管理本人上限/审批owner上限，审计实际viewer；API/worker注册端口 | 真实底层资源拒绝配对 |
| admin scope service / middleware / permission adapter | 正整数具体租户；无效回合法所属；明确管理写校验范围；共用GET/use维持 | 跨页与跨标签切换 |
| platform HeaderTenantScope / request / appActions | 无全平台，真实响应范围快照和旧响应拒绝；按动作门控组件与请求 | 浏览器实际交互 |
| platform/client preview API | management/approval显式分开，starting不重复拉起 | 实际审批面板 |
| backend/manager/proxies config / main | 默认且只接受2；旧RPC/inventory/导入/upgrade/rebind不可达；共用工具保留 | Docker/K8s各一次定向部署 |
| runtime_materials 工具 | 私有包上传先读取实际范围头，冻结后写；冲突不重试到新租户 | 现场离线材料导入 |

### 4.2 归属与真实主体的处理

```text
已认证服务账号 → F113/通道准入 → 取既有自然人归属事实
                              ├→ app.owner_user_id / 受保护 owner：自然人
                              ├→ app.tenant_id：既有一致租户
                              └→ PermissionActor / 操作者审计：真实服务账号
```

首发将真实 actor 传到 app 创建授权；现有 F048 在同一创建投影中包含自然人 protected owner 和服务账号 ordinary CREATOR_GRANT。初始化完成且当前动作足够才保存平台源码快照、创建发布受理记录并投递。slug 冲突、已有 app_id 或重试都不能触发对历史 app 的重新初始化。

资源归属与授权主体的例子如下，所有字段均由可信身份/目标记录确定：

| 字段/事实 | 服务账号 24（归属人 849、租户 2）首发 |
| --- | --- |
| app.owner_user_id / 审批申请人 | 自然人 849 |
| app.tenant_id | 租户 2 |
| F048 判定主体 / 实际审计主体 | service_account:24 |
| 初始授权 | user:849 的 protected owner + service_account:24 的可撤销 CREATOR_GRANT |
| submitted_by_user_id | 0，服务账号类型与 ID 另行留存 |

迭代先加载并验证目标 app。`app.owner_user_id`、发布记录的 owner 和审批申请人始终取原 app，不改成当前服务账号的归属人；服务账号自己的当前归属关系仍按 F113 校验。归属人迁租户不迁 app，不靠新的 Grant 绕过冻结发布原归属人的资格要求。

### 4.3 管理请求与内容控制

```text
登录身份 → 解析/绑定具体管理租户 → 验证 app/版本/状态
        → 真实 PermissionActor → F048 当前动作集合
        → 原业务校验与执行 → 按动作裁剪响应/审计
```

- 薄门面接口拟为 `authorize_app(identity, app_id, operation)`、`management_actions(identity, loaded_apps)`；operation 为服务端枚举，不接收客户端 action 作为权威输入。Web 来源使用已验证的登录身份；开放通道读取公开 access_context 的真实 principal/permission actor，保留 authorization_subject_type/id、mode 与凭据引用，禁止从 resource_owner_user_id 构造自然人 actor。后台根据持久来源重新解析，不能复用进程内残留的当前 actor。
- 列表先取当前具体租户的合法候选，五动作批量检查、OR 过滤后组装；复用 adapter 已加载记录批量入口，分页按现有游标/总数契约处理，不混入未授权对象、不逐卡发五个 HTTP 请求。
- 详情/状态安全摘要：名称、图标、slug、owner 展示、状态、实例基础状态、版本号、发布说明、审批状态与时间；不包含完整声明、注入参数、环境引用、详细 failure、原始日志或 Grant 主体清单。
- edit 内容接口独立校验；完整授权名单与模式变更使用 manage_permission；应用记录 edit 与跨应用审计入口资格分别验证。导出创建、结果查询和下载再次查当前 edit，不能凭旧票据跨租户或延续已撤权资格。
- 权限 API 的 app Grant/mode/成员入口也须通过 app 资源 adapter 校验当前具体范围，不能仅在 Build 页面校验。公共 profiles/公共依赖仍是原平台运维资格。

### 4.4 管理视角协议与并发

`EffectiveManagementScope` 包含 `tenant_id`、`source=selected|own`、`expires_at`；来自已认证身份、当前租户关系与可用租户目录，不由请求头赋权。本节调整具体管理范围，不统一改造助手/工作流等共用接口的权限。

1. 超管 GET scope：没有选择、TTL 过期、目标不可用或缓存无效时返回当前合法所属租户；无法确定则拒绝管理数据。非超管直接使用本人当前租户，不读取超管选择。
2. POST scope：严格正整数 tenant_id、超管和 active 目标校验；null/global/不存在/禁用拒绝且保留原值。单租户使用具体 Root，隐藏切换。
3. **共用读取/调用保持原合同**：flows/assistant/knowledge 等被两端共用的读取和使用接口，不新增 `X-Management-Tenant` 必填条件，不拆分新 API，不要求 Vibe 管理动作。仍按原可见性及相应 use/业务条件执行。不能以“可见”授权编辑、发布、删除或返回原本不可见的敏感字段。
4. **专用管理写保护**：Vibe 管理写和明确的管理新建/批量写入口按 HTTP method + 既有写端点登记，校验预期具体租户后 pin ContextVar；旧表单范围不符或缺少规定的预期范围时拒绝并刷新。不能使用包含共用 GET 的前缀通配表执行此门禁。已有资源写还需核对目标资源范围与原动作，不能通过省略头或变更请求参数降级成只读调用。后台任务携带已验证 tenant，不能重读页面选择。
5. F113 服务账号管理仍接受原 `X-Service-Account-Tenant`，不因本次增加新头而使仅带旧头的合法请求失效；若同时携带新旧头，二者必须一致，并遵守原范围变化错误合同。服务账号页读取同一有效范围。
6. 管理页共享 hook 保存范围快照；切换/失效后清理 query 缓存、详情和可提交表单，通过 localStorage 事件同步标签页并在重新激活时复核。管理数据返回附实际生效范围；前端先核对范围和本地代次再展示，旧响应不能写入新视图。共用读取接口无需因此改变必填参数或调用方式。
7. 依赖故障时，管理读仅能回退到独立验证的本人租户并报告实际范围；无法确认选择的管理写拒绝。真实身份无法确认则拒绝，不退化为全平台。
8. SDK、开放 API、app-proxy HMAC、内部运行回调和个人审批继续使用已验证主体/任务及目标关系。用户提供的头不是身份或授权；本轮不为其它业务增加管理/客户端身份分类或拆分协议。

管理模块的范围收窄如下；这里只改变管理数据的有效租户范围，Vibe app 以外的权限动作保持既有逻辑。公共预置目录仍按现有合法共享规则读取。

| 范围 | 现有入口锚点 | 本轮边界 |
| --- | --- | --- |
| Vibe app | apps 管理路由及 app 权限目标 | 本轮六动作映射、内容裁剪与具体租户范围；个人审批用途单独校验任务 |
| 工作流/助手 | 现有 workflow/flows/assistant 管理读取及写端点 | 管理数据范围随具体租户；共用读取/调用的现有最小权限、参数和动作保持，不另拆接口 |
| 知识库/模型 | 现有 knowledge/llm 管理入口 | 仅核对管理数据过滤；共用读取/调用沿既有权限，不附加 Vibe 管理条件 |
| 审批管理/审计 | approval/admin、管理进度、audit、app-runtime-audit | 异常、进度、处理及导出同具体租户；个人任务资格独立 |
| 用户组/角色/服务账号 | 既有管理入口 | 具体范围解析统一；专用管理写防旧表单错租户；原资源动作不变 |
| 其它既有管理模块 | 既有范围接线 | 清理全平台分支；不因通用前缀把共用业务请求升级为管理请求 |

### 4.5 发布代行与异步复核

```text
用户请求 → 冻结真实主体/用途与目标 → Celery 准备/版本/审批复核
 → 维护准入 → 维护投影及停旧 writer → 迁移准入 → 启动准入 → 路由提交复核
可信 observation → backend 固定系统恢复来源 → 新 v2 operation
 → 同一阶段端口验证原运行意图/围栏 → 仅恢复原批准版本 → 路由提交复核
```

**两类来源及生产消费**：

| 来源 | 生产者及持久化 | 消费者及判定 |
| --- | --- | --- |
| `user_request` | 既有发布/上线/配置重建/预览入口生成 `schema=1`、actor、credential_ref、mode、self_review_user_id、purpose、target、required_actions；发布记录和新 operation 各保存其受信部分 | worker、authorize-step、fact 维护投影及 route commit：重载真实主体/凭据/目标，按注册用途查 F113/F048 或有效审批任务。客户端不能自填上下文 |
| `system_recovery` | `RuntimeOperationService.observation` 验证 manager 角色、node 与观测围栏后，`recover` 在同一 repo UoW 重读并冻结 source。保存原 route id/epoch/exec_ref、原 operation id、tenant/app、批准 version/delivery_digest 及已核实的 observation 绑定；不保存历史用户凭据 | authorize-step、维护 fact 和 route commit：重读上述来源及新 operation 围栏，确认 app 仍 online、current_version 与来源相同、无用户下线/删除/新运行意图取代，只恢复此 delivery；不查历史发起者是否仍有权限 |

- `origin_kind` 是服务器内部必填判别字段，两类结构不能混用。只有受信 observation/recover 入口能生成系统来源；普通发布、配置重建、手动上线及运行管理请求不能提交、复制或重标记该来源。manager 的 claim/fact/wakeup 也不能改写来源。系统分支不以空动作列表、deploy kind、auto_commit 或“来自后台”作为允许依据。
- 用户来源的 SA/personal 引用是 credential ID，续办重新加载主体、scope/模式及 F113。Web 来源保留可重验的会话版本/过期等材料，不存 JWT 原文。未知 schema、用途/目标不匹配、主体丢失、撤权或依赖不可判定均拒绝用户新增效果；保留审批结论与可解释原因，新的有权用户可按原流程发起新意图。
- 系统来源冻结的是当前 serving route 对应的原 operation，而非 assignments 中可能失败的另一次操作。证据来自已提交 route/current_version、原批准版本/RuntimeDelivery 与已验证观测，不要求历史 operation 具有新用户上下文，也不自动给历史用户发布补上下文。来源缺失、非原生 v2、版本或 delivery 不符、目标已下线/删除、新意图取代时拒绝恢复，并保留诊断与清理。
- `recover` 的冻结与 create 使用现有事务及锁重读 app/route/assignment；沿现有 `recover:{route.id}:{route_epoch}:{attempt}` 幂等键、次数及容量/隔离规则，只设置原批准版本、空 migration_plan，保留 pending_version。代码、profile、能力声明不得借恢复改变；环境变量仍按 F055 AC-70、AC-73 在本次受理时选定已保存配置，不另加“冻结旧值”规则。
- 若本操作进入维护，`fact(maintenance)` 将原 route before/after（id、epoch、operation、version、状态）和本 operation id/generation/owner_epoch/事实 sequence 一起写入现有 payload 的 `maintenance_transition`。系统来源的后续检查只允许原 route 原状，或这一已验证本操作造成的精确转换；不能因状态叫 maintenance 就允许其它操作接管。route commit 再核对该来源和当前运行意图，提交后重复请求只回读已提交结果，不重新产生效果。
- 系统自愈不暴露用户通用 cancel。用户以当前 app.unpublish 调用既有下线流程，先终止 online 意图并令在途恢复不能继续新增效果，再按原 stop/cleanup 围栏收尾；不得把 unpublish 改成要求历史发布人的 publish。系统来源、取消与审计都记为系统恢复并关联 source operation，不能记成自然人或服务账号代行。

**首次副作用与阶段顺序**：manager 经唯一 v2 HMAC `authorize-step` 请求一步准入，backend 分别验证用户或系统来源，再检查 app/version、operation、node/generation/owner_epoch、当前 stage、任务/控制租约和 deadline。`phase` 表示请求的受限业务步骤，必须由当前 stage 允许进入，不等于信任客户端宣称状态；返回相同绑定与短有效期。不持久化永久允许，不给 manager FGA 访问权。

| 顺序/步骤 | 准入必须早于什么 | 责任方与重复/拒绝行为 |
| --- | --- | --- |
| 准备、预检、生成版本/审批 | 新源码处理和创建新业务记录 | worker 复核用户来源；manager 的准备/预览步骤沿同一用途校验；预检/预览不能借此获得生产身份 |
| `maintenance` | backend 阻断正式 route/出站策略，以及 manager 停旧 writer | manager 先请求准入；backend `fact(maintenance)` 在投影前复核来源及围栏，并与事实/maintenance_transition 同事务提交。manager 得到该事实的有效确认后才停旧 writer；请求失败/结果不确定时不得先停或继续迁移 |
| 备份/迁移/数据恢复 | 新的生产数据写入步骤 | 在已确认停写和独占维护之后，再按用途检查；保留快照、writer、PVC/锁与迁移围栏，不沿用维护许可授权迁移 |
| `starting` | 创建或启动新正式执行体 | manager 再请求一步准入，后端仍验证相同受信来源；不以迁移成功或 auto_commit 替代授权 |
| `route_commit` | 新正式路由、正式凭据及出站策略生效 | backend 在提交路径复核来源、预期 route 转换和运行事实，auto_commit 分支同样经过此检查；提交后回收旧执行体属于原操作收尾 |

- 维护开始前撤权/来源失效时，不得 report 出可生效的 maintenance，不阻断旧 route/策略，也不停旧 writer。fact 的回复丢失时，按原 sequence 查询/幂等重放已提交事实并核对 maintenance_transition；不生成第二次状态转换或把未知结果当成功。
- 已经合法进入维护后发生撤权，不回滚已发生的事实。允许完成本步停写和必要清理，后续迁移、启动及新路由仍需新的准入。已变更数据只能按原快照/停止证据及原批准版本规则处理；没有可证明的安全恢复路径时保持可解释的维护/失败状态，由有权用户处理，不承诺无中断，也不启动未授权新版本。
- 用户授权失效不阻止既有幂等失败清理。自愈/清理不能扩大版本或能力；旧记录缺上下文时拒绝新的用户效果，但允许按上表由当前可信运行记录验证的系统恢复。唯一 v2 capability 缺失或结果过期/不确定时拒绝新步骤，既有观察、健康检查与必要清理继续。

### 4.6 应用发布审批的自审与撤回

- 发布 payload 含 `submission_actor` 与 `self_review_user_id`，由发布冻结记录投影；申请人仍是 app owner。多节点运行时 handler 从同一冻结来源重建这些信息，服务账号改绑不改写历史。
- 应用场景 handler 排除 `{app.owner_user_id, self_review_user_id}`，候选先经过现有有效人员/租户条件，重复 ID 去重。
- 单管理员例外需要从租户管理身份的可信端口确认实际管理员数量和候选，不用过滤结果或人工配置候选数代替。Root 的既有平台超管来源按原产品口径统计；无法确认时不启用例外。无合格候选沿现有 approver_empty 异常路径通知处理，不伪造任务或自动通过。
- 异常重试、指定审批人和后续节点调用同一应用场景资格钩子；明确候选不合格时拒绝指定。现有合法审批运维处理权仍存在，但不能把指定已排除者包装成正常审批。其它场景钩子为空保持原行为。
- 主动撤回由 app publish 资格授权。新增审批 application 层的应用发布业务撤回端口，验证可信 app/deployment/instance 对应、场景及可撤回状态，再复用引擎的 withdrawn 流程与真实操作者审计。保留 withdrawn 与 deleted/cancelled 的区别；公共用户撤回入口的 applicant 检查及其它场景不放宽。

### 4.7 两种预览及平台能力

| 用途 | 启动/继续访问资格 | 注入身份 | 能力授权主体 | 声明来源 |
| --- | --- | --- | --- | --- |
| management | 当前 app edit，且版本仍在允许预览阶段 | 实际预览者 | 本人 | 本次 version 的冻结声明 |
| approval | 当前有效审批任务绑定该 app/version/instance | 实际审批人 | app 原归属人，限审批例外 | 同一冻结 version |

- 扩展预览 GET/POST 的 `purpose=management|approval`；管理页显式传 management，审批页显式传 approval。客户端提交 purpose 是选择用途，服务器仍查 edit 或任务。省略时仅在恰好一种资格成立时推导用途：仅审批资格为 approval，仅 edit 为 management；两种资格同时成立则拒绝并要求显式选择，响应返回实际 purpose。DELETE 按服务器会话用途校验且仅限会话对应人。
- management 请求仍绑定当前具体管理租户；approval 请求使用可信任务的 tenant/app/version，属于个人审批业务授权，不因超管切换页面范围而改成另一租户任务，也不能凭 purpose 跳过任务校验。
- 沿用现有 `approver_user_id` 字段保存唯一预览者，避免重命名破坏旧读取；新增 purpose 和审批 instance/task 绑定。查询复用键含 version/viewer/purpose/任务，不把同一用户不同用途共用。
- 入口每次打开与能力调用都确认会话未过期/未回收、viewer 相同、用途资格仍有效、tenant/app/version 一致。OBO 签名携带 preview_session；签名通过后仍从可信会话解析用途和能力主体，不信任原始请求头中的 owner/purpose。
- 新增 `CapabilityAccessContext` 端口：返回真实 viewer、实际能力主体、tenant/app/version、purpose 和会话/任务绑定。模型面与检索/附件入口共用端口；组合根在 API 与 worker 所需进程均注册，默认未注册拒绝。OpenAPI 域只依赖端口/值对象，不直接读取 F055 ORM。
- 同步/异步认证和排队任务实际执行都校验预览绑定；队列快照保留 credential/session/version/purpose 引用，消费时复核，不缓存永久允许。预览凭据必须与同一会话的可信 OBO 配对；缺 OBO、正式凭据配预览 OBO、不同预览会话混配均拒绝。正式运行的既有 app_self 模型调用规则不因本次扩展改变。
- 普通检索仍按访问者；审批预览检索以 app owner 构造授权身份，同时保留实际审批人审计和冻结声明白名单。模型仍沿现有 F051 的租户启用范围/声明规则，不新增逐模型 F048 授权；预览必须读取冻结版本，不能读取正式 current_version 代替待审内容。
- 预检及两类预览的用户环境密钥全部为空。预览独立数据库和附件 namespace；不能获得生产数据 session、备份上传或正式部署用途。
- 每个新预览单独签发 hosted_app 凭据并在会话中绑定 credential ID；不调用会撤销 app 其它凭据的全局 reissue。预览凭据仅在其会话与用途有效时认证，不依赖 app.state=online，也不能被正式路由凭据检查接受。正式凭据继续用原 RuntimeCredentialBinding/route 校验。
- 回收只吊销本预览 credential，不对整个 app 执行 revoke_subject，不能中断正式实例。新预览仅经 v2 operation 创建，必须同时绑定会话凭据和 operation 围栏；不为支持预览而放开任意 staged 正式凭据。

**会话/凭据/operation 的原子登记（R6）**：

1. 先按用途做当前资格检查。进入同一 tenant 的 `RuntimeDeliveryRepository.transaction()` 后，锁定该 AppVersion 行，再查复用键 `(version_id, viewer_id, purpose, approval_task_id)`，管理预览的 task 为 NULL。所有预览创建入口使用该串行点，活跃状态为 `starting|running`；索引仅用于查询，不当作唯一性保证。复用时返回既有会话/操作，不能重新签发凭据或重复占容量。
2. 无活跃会话时在此事务内创建 `starting` 会话、提交尚未对外可见的新 preview operation、签发 per-preview credential、回写 `credential_id/operation_id`，并保存包含预览凭据和隔离存储凭据的 `sealed_env`、必要签发审计及容量记录。使用同一 repository 实例和 caller-owned SQL session；既有嵌套 transaction 仅复用此 UoW，不使用先独立 commit 的 `_insert_session` 或另建 repository。跨域经 application 端口，签发复用 `CredentialService.issue_in_transaction`，不复用正式 stage_binding，也不调用全局 reissue/revoke_subject。
3. 事务内不发 wakeup、Docker/K8s、MinIO 或其它远端调用；运行材料和节点资格使用已验证输入及本地控制记录，实际执行阶段再复核当前用途资格。成功提交后才 wakeup/wait；node plan 也可发现持久操作。明文凭据仅在本次内存中进入加密 env，不能返回前端或日志。所有新记录提交后必须具备完整 session/credential/operation 双向绑定，未确认 ready 前入口及能力调用拒绝。
4. `fact(ready)` 经用途/会话资格及运行围栏校验后，在现有事实与 route 事务内调用 preview lifecycle 端口，把同一会话从 starting 改为 running，并对齐会话/operation/凭据/存储的过期边界；不提前呈现可用预览。准备中的启动超时以 operation deadline 为准，运行后以会话 TTL 为上界，不等七天 TTL 才处理已失败的启动。
5. 预览生命周期采用一致锁顺序：先 Version 串行锁，再按现有 runtime 围栏锁操作，最后 Session/单个 credential。preview 的 fact/reclaim 分支须在获取 operation 写锁前安排 Version 锁；不能在持 operation 锁后反向取得 Version。锁内重查当前用途、目标与绑定；跨进程唤醒、执行和等待均在事务外。

| 情况 | 持久化与回收规则 |
| --- | --- |
| SQL 提交前签发/容量/环境准备失败 | 整个事务回滚；不留下会话、凭据或操作，也不通知 manager。不得调用独立提交的签发函数 |
| 提交回复未知 | 不假定失败，也不立即创建新会话或吊销不确定的凭据；恢复连接后按同一复用键和持久绑定查询。已提交则复用原 operation/密文 env，否则在 Version 锁下重试；仍无法确认则返回可刷新查询的失败原因，不宣称已回收 |
| 提交成功但进程在 wakeup 前退出/唤醒回复丢失 | node plan 或下一次同键请求唤醒同一 operation；不重新签发或创建第二个活跃会话 |
| 启动失败/取消/超时、用途资格失效、审批终态、TTL 或人工回收 | 同一数据库事务关闭会话并按 credential_id 吊销仅该预览凭据、登记其 operation 的取消/清理义务；重复回收是幂等的。执行体/附件清理由原 manager 围栏及 RuntimeCleanupService 续办，未确认停止不释放容量或宣称清理完成 |

预览 fact、终态处理、面板 describe/reclaim 与现有超时/cleanup 续办均调用 `app_publish.application.preview_runtime` 的窄端口核对和收敛绑定；该端口拥有会话状态，签发/吊销经 open_api 的事务端口，runtime 域不直接改 F055 ORM。无需新 Beat 任务或驻留预览服务。只有查询证明完整且当前仍合法的活跃会话才可复用；缺失/冲突绑定拒绝访问并进入原可解释失败清理，不借重新签发掩盖不确定结果。


### 4.8 运行操作、数据与内部存储

- `RuntimeOperation.payload.authorization_context` 携带 origin_kind、受信 purpose 和来源绑定；用户来源按当前 actor/动作，系统恢复按 §4.5 的原运行意图验证。用户请求/取消/重试先验证 app、scope、operation 归属，未知或不匹配用途拒绝。系统恢复没有用户通用取消，既有 unpublish 终止 online 意图并触发原 stop/cleanup。用户数据恢复是否包含启动在接收时固定。
- 数据 session、行修改、CSV 导出/恢复结果与私有快照读取均需当前 edit。内部 transfer 凭据继续绑定 tenant/app/version/op/用途；用户入口再次鉴权，manager 的必要快照上传、已受理维护结果写回和安全清理按原意图执行，不模拟自然人。
- 移除 `natural_owner_required`，不移除暂停 writer、独占 PVC/锁、generation/lease、digest/profile、迁移与恢复确认。环境变量确认重建与新版本发布为 edit AND publish；旧绑定升级/rebind 退役，不新增通用重建；停用为 unpublish；删除为 delete 且仍须先下线、确认及完整资产/Grant 清理。
- 在服务端取消请求写 cancel_requested 前，按原用途对当前取消者校验全部动作；serving/retiring 等原不可取消阶段仍拒绝；终态重复请求按原幂等结果处理，不借重复请求重新执行。

### 4.9 数据结构与数据库变更

不新增业务表；拟对既有表做 additive DDL，所有 SQL 变更遵循 C2 和 migration AGENTS，JsonType 仅在 Python 解析。以下是设计新增字段，不是已实现 schema。

| 载体 | 新增/沿用字段 | 生产者与使用者 |
| --- | --- | --- |
| app | owner_user_id、tenant_id 原样沿用 | 既有服务账号归属事实；所有后续操作不能改写 |
| app_deployment | 新增 nullable `authorization_context: JsonType`；沿用 submitted_by_user_id（SA 保持 0） | 接收业务生成；worker、审批与上线复核读取；不对 JSON 做 SQL 查询 |
| app_preview_session | 新增 nullable `purpose: String(16)`、`approval_instance_id: Integer`、`approval_task_id: Integer`、`credential_id: BigInteger`、`operation_id: String(36)`；沿用 status，增加 starting 值 | 新记录强制完整绑定；credential/operation 各有唯一索引（旧 NULL 保留），复用查询含 version/viewer/purpose/task/status；Version 行锁保证串行，不依赖可空/条件唯一索引；ready 才转 running |
| runtime_operation | 沿用 payload，新增内部 authorization_context schema 1 的 origin_kind 判别结构，用户 actor/凭据与系统 source 互斥；沿用/扩展 maintenance_transition | backend 用户入口或 observation/recover 生成；authorize-step、维护 fact、路由提交及取消分别验证；不新增表/列 |
| approval_instance.payload_snapshot | 投影提交主体、自审关联自然人及发布记录引用 | 只有业务 handler 生成，不能依赖当前服务账号新归属人 |
| api_credential / RuntimeCredentialBinding | 沿用表；预览凭据由会话 credential_id 区分，正式 binding 语义保持 | 认证、回收与生产路由各自验证 |

迁移不回填旧 owner/tenant/Grant/发布操作者，不猜测旧 SA 的自然人身份。旧在途发布缺上下文时拒绝新增用户授权效果并提示重新提交或有权重试，不伪造历史 actor；已提交原生 v2 路由可经 §4.5 的当前运行记录重新证明系统自愈来源，保留旧版本观察与必要清理。旧 purpose=NULL 预览不获得新增能力例外，拒绝继续入口，按原终态/TTL 清理，用户重新拉起新会话；不把旧生产凭据误吊销。

### 4.10 前端接线

- platform：HeaderTenantScope/useAdminScope 移除 global/null，展示实际具体租户。管理页增加范围快照、旧响应保护与清表单；预期头仅由登记的专用管理写 API 使用，不对助手/工作流等共用读取加必填头。服务账号页保持 F113 旧头保护，store 不发 HTTP。
- Build app：按 allowed_actions 决定列表、详情与 tab；publish-only 等用户仅加载安全摘要。数据/日志/密钥读取、管理预览需 edit，确认重建需 edit 与 publish，Grant 区需 manage_permission；上下线/删除沿原确认与状态守卫。移除额外 owner/admin 分支及未实现的提交发布按钮。
- client：现有助手、工作流、知识空间共用读取/调用保持原 API 及最小权限，不为 F114 新增管理租户头或接口分流。Vibe 审批审读/预览继续用任务接口并显式传 approval；通知区分申请人、实际提交主体和归属人。
- 已阅读 UI docs/index.md、components/index.mdx、Select 规范；复用现有 Header 中的 @bisheng/ui Select 与已有确认/通知实现。当前 Select demo 标为 draft，故沿用已在 Header 落地的用法，不新增组件或改视觉。其它组件按实施时当前 done 清单复核。
- 新提示三语同批交付，错误文案只写 packages/locales 源并生成，不手改产物。当前范围无法确认、范围已变化、缺少动作、审批/运行条件失败分别提示；403 继续由请求拦截器处理。

### 4.11 v2 收敛清单与测试环境处理

以下为拟改边界；本轮不执行真实环境盘点、停用、重建或资产清理。

| 位置 | 删除/收窄 | 必须保留/统一 |
| --- | --- | --- |
| backend 配置与调用分支 | runtime_protocol_version==1 路径；v1 deploy/build/probe/preview/stop/destroy/schema/数据调用及旧签名 RPC | 默认仅 2；RuntimeDeliveryCoordinator 和 v2 data/observe/material 端口；页面和 CLI 外部路径不变 |
| manager composition root、auth、reconcile | 旧 intents/routes/readonly/storage/appdb HTTP routers、本地 desired-state 控制循环、v1 专用 HMAC 校验 | operations/platform_data/platform_observe、PlatformReconcileLoop；v2 分角色签名/nonce/幂等/租约；节点本地材料与诊断缓存不作为控制真相 |
| app-proxy/egress-proxy | 向 manager 查询 v1 路由、读取旧本地 egress 真相的回退；协议选择分支及 v1 专用配置 | 从 backend 读取 v2 路由/出站投影；HTTP/WebSocket、backend entry HMAC、OBO 与 v2 身份密钥仍有效 |
| 构建及数据库公共逻辑 | BuildService 等仅服务 v1 的调度/记录壳；旧附件直接 MinIO 服务及专用依赖 | v2 legacy_prepare/source-image、OCI assembler 仍引用的模板函数；appdb 中 v2 预览/data_worker/K8s helper 使用的备份/迁移/查询工具；必要时先提取公共模块再删壳 |
| 旧绑定升级工具 | manager `/v2/upgrade/inventory`；backend `/apps/{app_id}/runtime/upgrade`、`/apps/{app_id}/runtime/upgrade/rebind` 及其 `RuntimeUpgradeService.import_binding/rebind`；旧 desired-state/存储凭据导入及专用恢复入口 | AC-57 明确一并退役，数字带 v2 也不保留旧导入/重绑；AC-26 配置确认重建和 AC-35、AC-36 正常新版本发布保持；不登记 runtime_upgrade，不新增独立通用重建或跨节点数据迁移 |
| 交付配置/文档/测试 | 旧 systemd/示例/CI fixture 中默认 1、双协议启动选项和旧协议成功路径 | Compose/Chart/安装校验统一 v2；更新实际受影响的镜像启动/配置烟测及必要失败配对；部署和运行能力报告不可冒充本轮实测 |

**保留能力与执行入口**：

| 业务操作 | 已有入口与执行链 | 本轮权限/范围 |
| --- | --- | --- |
| 同版本环境变量确认生效 | POST `/api/v1/apps/{app_id}/secrets/rebuild` → `runtime_secrets.rebuild_current` → `AppSecretRebuildService`；验证当前版本、配置 revision、route/确认指纹和旧 operation，生成 `config_restart` 新 deploy operation | AC-26：edit AND publish；保存环境变量不重启，取消确认不创建操作；保留固定 delivery/版本、幂等及旧 writer 围栏 |
| 代码、镜像、profile/运行环境或启动声明变更 | 现有 CLI/MCP/开放发布入口 → 发布管线 → 扫描/预检/冻结新版本 → 审批 → v2 部署 | AC-35、AC-36：edit AND publish；不直接修改冻结版本，不以同版本重绑绕过审批；公共 profile 运维仍按原平台资格 |
| 旧绑定导入、升级与 rebind | 上表的旧 manager inventory 与 backend upgrade/rebind 均不再注册，返回不可用/未找到 | AC-57、AC-71：即使拥有 edit/publish 也不执行，不创建 operation/实例或变更路由/存储 |

普通 `RuntimeDeliveryCoordinator.deploy` 对正常在线同版本返回现有实例是既有幂等行为，本轮保持；不会加 force 开关或新建通用重建入口。`runtime_upgrade` 不进入新操作用途映射；未知用途拒绝新增用户授权效果，必要失败清理保持原安全边界。原生 v2 应用无需仅为协议清理而重建。

**协议兼容矩阵（目标）**：

| 输入/环境 | 结果 |
| --- | --- |
| v2 Docker 或 K8s，所需 capability 与身份配置完整 | 进入同一持久 operation，按 §4.5 在准备、正式启动及路由提交前复核 |
| 未显式设置协议 | 唯一默认值 2；仍需通过既有 v2 身份、材料和运行前置检查 |
| 显式 protocol=1、未知值或混合配置 | 控制进程在启动工作前给出明确配置错误，不启动旧对账/部署；禁止静默回退 |
| 请求已退役的 manager v1 RPC 或旧绑定 upgrade/import/rebind | 不注册旧 handler，返回不可用/未找到；无业务、容器或存储副作用；无需另造兼容成功响应 |
| 平台 `/api/v1`、开放 `/api/v2`、已有 manifest_version:1 源码包 | 保留各自既有合同；旧格式源码经 v2 source-image，不调用旧 manager RPC |
| v2 历史在途记录缺本次身份上下文 | 保留旧版本服务/清理，拒绝新增效果并提示有权用户重新发起，沿 §4.9；不猜测 owner 代行 |
| 测试环境发现 v1 活跃实例/控制状态、旧附件绑定，或名义已为 v2 但仍指向旧导入执行体 | 列出并保留数据，停止该环境的切换实施；先按获授权范围备份、停写、显式以 v2 重发/重建并验证，再切换；不提供产品级双协议或自动收养 |

**实施顺序**：

1. 在升级实施前只读盘点实际涉及的测试环境：记录协议、镜像/配置、运行应用、SQLite 卷、附件对象及在途操作；同时核对真实 Engine 标签、legacy_exec_ref/导入绑定和旧存储端点引用，不能只看配置值为 2。source-image 或 manifest_version:1 本身不等于 v1 执行体，不因此重建。该文档不授权访问或修改其它环境。
2. 若有 v1 资产，先提供精确处理清单并在授权范围内停写、备份及按原 owner/tenant 受控重建；未完成前不把新镜像覆盖上去破坏管理能力。代码中不为这次测试资产处置保留长期导入 API。
3. 先梳理公共函数的调用者，提取 v2 复用能力，再删除旧控制入口与配置分支。保留 v2 数据/源码/附件对象引用，不改历史版本记录或自动补 Grant。
4. 本地仅跑必要定向验证；部署时统一 backend/worker/manager/proxies 的 v2 配置和所需 capability，再恢复新受理。新旧控制器不得同时管理同一 SQLite 数据卷。
5. 回退只使用理解 v2 任务/资产及本次身份用途字段的兼容构建；不以降到 v1 manager 为回退方式，不 drop 运行表或回写旧数据库快照。DDL 和业务数据恢复分别遵守原确认规则。

## 5. 已知坑与护栏

| # | 已核对的反直觉事实 | 不知道会怎样 | 处理位置 |
| --- | --- | --- | --- |
| 1 | F048 已支持服务账号创建的可撤销 CREATOR_GRANT，但 Vibe 传的是 owner actor | 错以为需要另造授权体系，或把 app.owner 改成服务账号 | D2、AppProvisionService 创建参数 |
| 2 | F048 manager 的动作随 CURRENT Catalog，且已有创建来源语义 | 用模型名字推定权限或意外扩大初始授权 | D2：复用原政策并检查真实有效动作，不新建模型兜底 |
| 3 | 归属人、申请人、实际 SA 主体和自审关联自然人可能不是同一对象 | 代发布后漏排真实提交方，审计冒用自然人 | D4、发布冻结上下文、场景 handler |
| 4 | 超管业务鉴权入口可能提前允许 | 未验证 app tenant/state 就跨视角读写 | D1、业务事实先验证、权限 adapter 入口 |
| 5 | admin_scope 无 key 当前代表全平台，且选择按用户跨标签页共享 | 只删 UI 后旧 API 仍读全平台或旧表单写错租户 | D3、范围解析、管理页快照与专用管理写入口 |
| 6 | set_current_tenant_id 后仍可能受 admin override 影响 | 将目标租户当作调用者身份，或内部任务继承页面范围 | tenant_execution_scope、真实 actor 独立留存 |
| 7 | deploy kind 同时用于普通上线与配置重建 | 仅有 publish 就能取消要求组合动作的操作 | D7、受信 purpose 和当前取消者校验 |
| 8 | 当前 AccessSubject 丢弃除 user_id 外的信息，默认声明读取正式版本 | 审批例外靠注释“存在”，或预览读错版本 | D5、能力上下文端口及冻结版本 |
| 9 | AppRuntimeCredentialService.issue 会先撤销该 app 旧凭据 | 拉起预览中断生产模型/知识库调用 | 独立 issue_preview 与按 credential ID 回收 |
| 10 | 运行 v2 正式凭据绑定 serving route，草稿不能按正式 app 凭据认证 | 为让预览工作而放开全部 staged 凭据 | 预览会话独立绑定与用途验证 |
| 11 | 源码包/manifest/operation payload 不等于可信权限材料 | 客户端伪造 owner/actions/context 获得执行资格 | 接收服务只生成受信字段，不原样透传 |
| 12 | 投影不确定时直接删 app 会留下授权真相与资源不一致 | 形成无法治理孤儿 Grant | F048 rollback_created 与原账本围栏 |
| 13 | flows/assistant/knowledge 路径包含两端共用读取/调用 | 仅按前缀强制管理头会误拒正常使用，并扩大本轮改造 | D3、§4.4：原最小权限不变；预期范围门禁限专用管理写 |
| 14 | v2 仍复用 builder/appdb/egress 中的公共函数，旧升级入口甚至以 /v2 命名 | 按文件名或 URL 数字误删 v2 能力，或漏留旧控制入口 | D9、§4.11 按实际调用链删除控制壳，保留公共工具 |
| 15 | 旧 rebind 调用 v2 deploy，但正常 online/serving 同版本只返回原实例；真正配置重建直接 submit 新 operation | 误保留无实际重建效果的入口，或在权限任务中扩展通用重建 | D7、D9、§4.11、§6.1：旧重绑退役，配置确认重建沿 AC-26，镜像/运行环境变更沿 AC-35、AC-36 |
| 16 | recover 与配置确认重建都用 deploy/auto_commit，但只有前者是系统恢复 | 按通用标志豁免用户请求，或因历史发布人撤权阻断正常自愈 | D6、§4.5/§6.2：受信 origin_kind、原 route/version 来源与当前意图复核 |
| 17 | maintenance fact 会先阻断正式 route/出站策略，manager 随后停旧 writer，早于迁移 | 把授权放在迁移前仍会先影响旧服务 | §4.5：维护准入先于投影/停写，记录精确转换，后续步骤分别准入 |
| 18 | 预览原先先提交会话再建 operation；新签发凭据若独立提交会加大部分失败窗口 | 并发双启动、孤立凭据，或未知结果时误吊销已启动预览 | D5、§4.7/§4.9：Version 串行点、同 repo UoW、starting 完整绑定、提交后 wakeup 与单凭据回收 |

新增实现护栏：PreviewRuntimeRepository 负责预览查询及行状态，CredentialRepository 负责精确单凭据吊销/审计和可用性；公开端口只传调用方 session 与不可变引用，不独立提交。应用候选 ID 读取单批 500 以兼容 DM8。预览 UTC 截止时间转 Unix 秒时显式使用 UTC，避免本机时区使有效期漂移；ready 同事务延长 operation、附件和 egress 到会话截止时间。旧控制 HTTP fixture 明确 retired skip，共用构建/SQLite工具测试继续保留，不能把 skipped 算作 v2 成功证据。

## 6. 对外契约与依赖

### 6.1 HTTP 与内部接口（本地已接线）

| 契约 | 设计行为 | 消费者/兼容性 |
| --- | --- | --- |
| GET `/api/v1/admin/tenant-scope` | scope_tenant_id 必为正整数，expires_at 可空；新增 source=selected/own | Header、服务账号选择；旧空值不再表示全平台 |
| POST 同路径 | 严格正整数 tenant_id；null/global 拒绝且保留原值 | 旧清空客户端须升级 |
| 专用浏览器管理写（method + 写端点） | X-Management-Tenant 核对具体范围并 pin；已有对象还验证目标；不使用共用 GET 前缀门禁 | 仅登记的 Vibe 管理写和管理新建/批量写包装入口；旧表单需刷新 |
| 共用助手/工作流/知识库读取与调用 | 原路径、参数、可见性/use 和业务条件保持，不增加统一必填管理头或 Vibe 动作 | platform/client 现有调用兼容，不拆 API |
| F113 服务账号管理 | 原 X-Service-Account-Tenant 单头继续合法；同时带新旧头必须一致 | 服务账号页沿原合同，不强制双头 |
| app 基础详情/列表、publish-status | 增加 allowed_actions:string[]，安全摘要；不以 is_owner 作操作资格 | 旧字段可保留作展示兼容，但不再授予操作 |
| 已有 apps 数据/日志/secrets/snapshots/runtime 操作 | 路径与请求主体保持；按 spec 映射且裁剪敏感内容 | Web、已有 CLI/MCP；范围和身份来源分别准入 |
| POST `/api/v2/apps/deploy` 与已有状态查询 | app:manage/mode S 保留；已有 app 要 edit AND publish；首次初始化真实主体 | 旧仅粗 scope 的历史 app 请求明确拒绝，主体侧正常补授权 |
| GET/POST `/api/v1/apps/{app_id}/versions/{version_id}/preview` | 新增 purpose 查询参数；响应含实际 purpose；approval 绑定从可信任务解析 | 新两端显式传用途；省略时仅按服务器可证明的单一资格兼容 |
| 新内部 POST `/api/v1/internal/app-runtime/v2/operations/{operation_id}/authorize-step` | manager HMAC/nonce；按持久 origin_kind 验证用户资格或系统 source，并核对 app/version/node/generation/owner_epoch、phase、当前 stage、租约/deadline；返回绑定和 valid_until；维护准入早于投影/停 writer | 唯一 v2 Docker/K8s executor；fact(maintenance) 与 route commit 仍各自复核并原子记录效果；auto_commit 不豁免，不透传用户令牌 |
| 已退役运行控制入口 | manager 旧 v1 routers、`/v2/upgrade/inventory`；backend `/api/v1/apps/{app_id}/runtime/upgrade`、`/api/v1/apps/{app_id}/runtime/upgrade/rebind` 不再注册；无新 operation/实例、路由或存储副作用 | 不改变其它前端 /api/v1 或开放 API /api/v2 合同；不保留 v1 回退或独立通用重建 |
| 已有配置确认重建 | POST `/api/v1/apps/{app_id}/secrets/rebuild` 请求/响应保持；本轮改为 edit AND publish，保留 expected_config_revision、运行版本/route/确认指纹及幂等检查，创建 config_restart 操作 | 复用现有 F055 交互与运行链路；保存不重启，不经旧 rebind，阶段授权按 §4.5 |
| `app_runtime.application.authorization` | 已验证 app 事实 + 操作用途 → F048 动作判定/安全投影 | app_publish、开放 API/MCP、状态/数据/运行管理 |
| `app_publish.application.preview_access` | 签名已验证材料 + 完整且 running 的会话/任务/credential/operation → CapabilityAccessContext | 模型范围端口、检索/附件；starting、绑定缺失或失效默认拒绝 |
| `app_publish.application.preview_runtime`、open_api 事务凭据端口 | caller-owned session 与受信值对象 → 预览签发绑定、ready 激活、关闭与单凭据吊销；不返回 ORM 或明文凭据给浏览器 | PreviewInstanceService 与 runtime 的 preview fact/cleanup 共用；Version→既有操作围栏→Session/credential 锁顺序，同一 UoW，提交后才 wakeup |
| 审批 application 场景资格/业务撤回端口 | 仅发布场景接入额外候选资格，业务撤回保留终态约束与操作者 | 发布 handler 与审批引擎；通用用户撤回和其它场景不放宽 |

**缺省用途规则**：仅有审批任务资格时兼容为 approval，仅有 edit 时兼容为 management；两者同时存在而省略 purpose 拒绝并要求明确选择，避免身份歧义。该规则覆盖上表预览 GET/POST，不由页面路径推定授权。

### 6.2 授权上下文示例（服务器内部，不接收用户自证）

```json
{
  "schema": 1,
  "origin_kind": "user_request",
  "actor": {"subject_type": "service_account", "subject_id": 24, "tenant_id": 2},
  "credential_ref": {"kind": "api_key", "id": 123},
  "self_review_user_id": 849,
  "purpose": "release_submit",
  "required_actions": ["edit", "publish"],
  "target": {"app_id": "example-app-id", "version_id": "example-version-id", "deployment_id": "example-deployment-id"}
}
```

owner 仍取 app 的自然人归属字段，示例 actor 不是资源 owner。续办读取当前凭据、主体及 F048 结果，required_actions 是受信用途的固定要求而不是已授予结果；与注册映射不一致则拒绝。上下文不含密钥/JWT、密文解密材料或完整授权快照。

系统恢复使用同一 schema 的另一分支示例，只有 backend 的 verified observation/recover 能生成；各引用在执行时重新核对，不把这段 JSON 本身当作已授权证明：

```json
{
  "schema": 1,
  "origin_kind": "system_recovery",
  "purpose": "system_recovery",
  "source": {
    "producer": "runtime_observation",
    "tenant_id": 2,
    "app_id": "example-app-id",
    "operation_id": "original-serving-operation-id",
    "route_id": "original-route-id",
    "route_epoch": 7,
    "exec_ref": "original-exec-ref",
    "version_id": "approved-version-id",
    "delivery_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "target": {"app_id": "example-app-id", "version_id": "approved-version-id"}
}
```

系统分支没有用户 actor/credential_ref；运行 operation 自身承载新 node/generation/owner_epoch。原观测的 node、operation、exec_ref、generation、route_epoch 等已验证绑定一同存入 source，示例只展开主要引用。后台每步按 §4.5 检查来源与精确的本操作维护转换；不能经公开请求创建或把用户配置重建重标记为系统恢复。

### 6.3 错误与审计

- 复用现有 app 不存在/状态、19000 动作拒绝、25020/25021 权限依赖、F113 身份/租户与运行数据冲突错误，补 `required_actions`、`reason` 等安全详情；不再返回 owner-only 文案。
- 拟在现有 197 模块新增 `19704 AdminScopeChangedError`（预期与实际范围不同）和 `19705 AdminScopeUnavailableError`（无法安全确定范围）。本基线源码及 v3.0.0 合同静态扫描未发现占用；登记本版本代码表，实施时再次运行错误码冲突检查。null/缺少具体选择沿用 19703，非法目标沿原目标/租户状态错误。
- 历史凭据缺 Grant：明确缺少目标动作并指向既有主体侧授权入口，不自动补权。跨租户或不存在对象沿原不可见语义，不泄露其它租户私有内容。
- 审计记录实际 actor_type/id、credential_id、actor_tenant、target_tenant/app/version/op、purpose、required_actions、结果/成因；资源 owner、申请人、审批人单独记录。SA 的 submitted_by_user_id 保持 0，不能用归属人冒充实际操作者。

### 6.4 Incoming 依赖与风险

| 依赖 | 复用方式 | 变化风险 |
| --- | --- | --- |
| F048 registry/adapter/runtime/Catalog/投影账本 | 唯一资源动作与创建初始授权 | 提前允许、模型变更、CURRENT 不就绪要安全拒绝；不能复制模型动作 |
| F113/开放通道 | 当前凭据/归属关系准入、冻结发布资格 | SA 改绑后新旧事实分离；人员停用标记不被误当新增租户失配 |
| F019 + Redis + 租户目录 | 共享具体范围、TTL、可用性 | 缓存缺失不再 global；故障不得静默扩大或写到回退租户 |
| F025 审批网关/handler/outbox | 发布必审、场景候选验证与业务撤回 | 不能修改其它场景资格；运行时 handler 必须读取冻结自审关联人 |
| F055/F086/F059 | 冻结版本/密钥、RuntimeOperation、执行租约、SQLite/PVC 围栏 | 新动作资格不替代既有容量、健康和 writer 停止证明 |
| app-proxy/OBO/模型范围/检索门面 | 可信 viewer 与用途上下文、版本声明 | 只验签不查会话会绕过用途/期限；能力端口必须在所需进程注册 |
| MySQL/DM8、MinIO、Redis、OpenFGA | 延用现有基础设施 | 无新增二进制或构建器；DDL 可空增列且不运行 JSON SQL，依赖故障明确拒绝 |
| UI 规范与包装请求/三语源 | 复用已有控件、错误拦截和缓存体系 | 不引入样式/状态库，跨页/跨标签旧响应不能污染新租户 |

### 6.5 上线与回退

实施遵循 §4.11 的盘点、v1 测试资产处置和公共能力提取顺序，再执行本次 additive DDL。暂停新受理，统一更新 backend/worker/manager/proxies 的 v2 配置；阶段授权 capability 对齐后恢复新受理。登记的专用管理写旧表单需刷新，共用读取/调用保持原格式。

经盘点确认控制记录、真实执行体标签和存储绑定均为原生 v2 的在线实例及正式凭据，不因协议清理被主动重建；旧导入绑定仍按 §4.11 单独处置。自愈按 §4.5 从现存批准路由/版本与真实 observation 生成系统来源；缺新用户上下文的在途记录按 §4.9 拒绝用户新增效果。预览新事务/状态与 lifecycle 端口应在所有 API/worker 和 v2 回调同时启用；旧 purpose=NULL 会话不升级或收养；部署前必须由旧版本完成回收并确认旧写入者已停止，再切新代码，历史行保留。新过期扫描只处理已有明确用途的新合同记录，避免无法识别的历史行占满每批200条。无法确认旧预览停止时不推进部署；不通过SQL补绑定或删除数据放行。必要清理沿原围栏。v1 实例不能套用这条“不重建”承诺，须先完成 §4.11 的精确处置。

回退只使用兼容 v2 及当前身份/用途字段的构建，先停新受理与临时预览；DDL 留存，不回退到 v1 控制或覆盖业务数据库。本文不授权本轮更新 116/189、改权限、迁移数据或公开推送。

### 6.6 受影响合同同步范围

本次已在原 spec 顶部增加 F114 后继合同说明并保留历史条款；同步范围为本版本 F054 的管理数据/生命周期资格、F055 的首发主体/代发布/预览/撤回、F056 的基础可见与记录查询、F086/F059 的运行管理、v1 退役及唯一 v2 阶段授权、F113 的具体管理范围兼容说明；以本次已确认 F114 替代目标为准，保留原状态与安全语义。F048 的动作/模型政策及 F019 历史版本线不重写。审批扩展点、通知字段或运行时 handler 改动时，在同一改动更新 approval-module skill。版本合同中已登记本轮 v1 退役目标对 F086 旧兼容条款的替代关系；旧 Feature 的历史验收证据保持原样，实施时同步当前部署指南/配置并清除仍宣称支持 v1 的目标条款。任务拆解后逐项登记，不把未实现方案写成交付完成。

## 7. 测试与可观测

### 7.1 定向策略

- 授权门面单元：六动作、五管理动作 OR、组合 AND、真实 SA/自然人、超管目标事实、数据范围、只持 use 与依赖故障；不改其它资源预期。
- 创建集成：自然人 owner/tenant 不变；真实 SA 可撤销 CREATOR_GRANT、Catalog 不满足时失败、投影不确定/逆向清理、历史 app 不重复初始化。
- 租户：具体 Root/子租户、null/global 拒绝、失效回退、故障管理读/写；F113 仅旧头及新旧头冲突；专用管理写的旧表单/多标签页/旧响应。共用读取按原可见性进行允许/拒绝定向对照，不新增其管理头测试门槛或全量助手回归。
- 发布/预览：A 代 B、双重自审排除、管理员数量例外、无候选异常、多节点/异常指定；两种预览与双重身份，预览凭据不影响生产，冻结版本和密钥空值；任务/会话撤销后下一请求拒绝。
- 异步与取消：上传后撤权、worker 重启、维护前/正式启动/route commit 前撤权、缺用户上下文；按用途/当前取消者配对。系统恢复验证历史用户撤权后仍恢复原批准版本、伪造来源拒绝、source route/epoch/version 变化拒绝、auto_commit 配置重建不豁免、unpublish 终止在途恢复；两后端共用同一判定。
- 首次效果：维护前撤权时 route/出站策略/旧 writer 均不变；maintenance 回复丢失按同 sequence 确认本次精确转换；维护后撤权只收尾、不新增迁移/启动/路由，不虚报恢复完成。
- 预览事务：同键并发只一套活跃 session/credential/operation，不同用途/任务不复用；提交前失败全回滚、提交未知不盲重建/吊销、提交后未 wakeup 仍可续办；启动失败/超时/撤销/重复回收只吊销本预览，生产凭据不变。针对新增锁顺序做定向并发检查，不跑全量回归。
- 前端：仅加载获授权内容，按钮无 owner 额外条件；现有确认与文案、请求范围和错误刷新；三语/i18n 与本次变更文件定向检查。
- 收敛功能界线：旧 inventory/upgrade/rebind 不再注册，授权用户也不能触发旧导入/重绑；配置确认重建沿现有确认指纹创建新 operation，取消确认不创建、重复提交保持幂等、固定版本/delivery 不变；代码/镜像/profile 变化仍产生待审新版本；不测试不存在的独立 runtime_upgrade 成功链。
- 协议收敛定向检查：默认仅 2；显式 1/混合配置拒绝且不启动旧控制循环；旧 RPC/导入不产生副作用；v2 bundle/image/source-image 与 SQLite/附件/日志/SDK 的实际调用仍通，不能只测端口404。对旧测试资产只读盘点不冒充已重建。
- Docker/K8s 仅用 v2 运行同一权限业务场景，不重跑全套编排故障；DM8 只静态检查模型/DDL。CI 明确要求的 lint/typecheck 为质量门禁，不能用业务全量回归替代本功能用例。

### 7.2 AC 到设计边界

| AC | 设计锚点 |
| --- | --- |
| AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08 | D1、D8、§4.2、§4.3 |
| AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18 | D3、§4.4、§6.1 |
| AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28 | D1、D8、§4.3、§4.8、§4.10 |
| AC-29、AC-30、AC-31、AC-32、AC-33、AC-34 | §4.3、§4.5、§4.8 |
| AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42 | D4、D5、D6、§4.5、§4.6、§4.7 |
| AC-43、AC-44、AC-45、AC-46、AC-47、AC-48 | D2、§4.2、§4.5、§6.2 |
| AC-49、AC-50、AC-51、AC-52、AC-53、AC-54 | D4、D5、D6、§4.6、§4.7、§4.8 |
| AC-55、AC-56、AC-57、AC-58、AC-59、AC-60 | D6、D7、D9、§4.3、§4.5、§4.7、§4.8、§4.11；AC-57 为旧绑定入口退役，非新增通用重建 |
| AC-61、AC-62、AC-63、AC-64、AC-65、AC-66 | D1、D3、D8、§4.10、§6.3 |
| AC-67、AC-68、AC-69、AC-70 | D4、D5、D7、§4.6、§4.7、§4.8 |
| AC-71 | D6、D9、§4.11、§6.1、§6.5；退役入口与能力/资产保留 |

### 7.3 可操作的真实验证

设计确认并完成代码后，在用户授权的环境使用独立临时租户 A/B、管理者 A、归属人 B、审批人 C、服务账号与应用；通过安全环境变量传入登录材料，不写入 Git/日志。116 既有应用保持原 owner/tenant/状态，不以测试修复存量资源。

建议命令入口（实现阶段新增的本特性用例，当前尚不存在，不能当作已运行证据）：

```sh
cd src/backend
uv run pytest test/app_runtime/test_f114_action_authorization.py test/app_runtime/test_f114_v2_only.py test/app_publish/test_f114_publish_actor.py test/admin/test_f114_concrete_scope.py
VIBE_E2E_BASE_URL=http://192.168.106.116:3001 uv run pytest test/e2e/test_f114_permission_actions.py -m e2e
```

人工核对 `/build/apps`、应用详情 publish/data/logs、顶部租户选择，以及 `/workspace/settings/my-tasks` 的审批入口：同一 app 分别用 use-only、edit-only、publish-only、组合权限及另一租户用户登录；验证页面内容、直接 API 与已撤权请求结果一致。浏览器流程采用现有 E2E 工具和本功能清单，截图和脱敏请求结果按 AC 留证，不以 HTTP 200 代替业务成功。

### 7.4 可观测与审查门禁

权限/范围拒绝按现有审计与 request_id/trace_id 关联；异步日志额外含 deployment_id/op_id/purpose/phase 与安全原因码。保留 app owner 与真实 actor 的区分，禁止日志输出密钥、完整环境值和原始访问令牌。

任务拆解后逐项 L1；仅运行对应配对测试及必要质量门禁；本功能专用真实 E2E 后按 `/sdd-code-review --base feat/3.0.0` 做 L2。未运行项标为未验证，CI/单测不冒充部署通过。

## 8. 后续边界

- 不提供历史 app 的自动 SA 补授权；失去旧粗 scope 兼容的账号由既有主体侧入口正常授权。
- 不做资源/服务账号移交迁移，不更改 owner 或用新提交人覆盖旧归属；其它资源创建逻辑也不在本轮改动。
- 不提供独立通用实例重建或 runtime_upgrade；配置确认生效复用已有 config_restart，代码/镜像/运行环境变更通过新版本发布。
- 不维护 v1 控制服务、旧绑定升级/rebind、长期 v1→v2 导入 API 或自动资产迁移；测试资产只按实际授权清单处置，保留数据后以 v2 受控重建。
- 不做跨请求全局事务、可撤销已完成业务效果或新增容器/K8s 故障恢复框架；沿原状态机和维护围栏。
- 不拆细 read/log/export/secret 动作；若未来需要，应重新评审粒度和 Catalog。
- 不在本轮扩展“全部租户”审计或管理视角；平台级运维资格与共享目录只读性按显式原合同保留。
- 不重构助手/工作流/知识库的共用读取与调用，不为其新增统一鉴权动作或强制管理头；具体管理租户过滤属于已有确认范围，独立于 Vibe app 动作映射。

## 修订历史

| 日期 | 改动 | 触发原因 |
| --- | --- | --- |
| 2026-10-30 | 初版设计草案，原含 70 条 AC 追溯；资源归属自然人保持不变 | 用户确认规格进入设计，并再次澄清创建资源归属规则 |
| 2026-10-30 | 收窄 D3、§4.4/§4.10/§6.1：共用读取/调用保持现有最小权限，撤去全前缀管理头门禁；当时 R2 仍待修订（已在下一条关闭） | 用户指出本轮重点是 Vibe app 权限映射，助手等共用接口维持既有逻辑 |
| 2026-10-30 | D9/§4.11 统一 v2；新增 AC-71 追溯、收窄 AC-57，关闭 R2；两类预览仅经 v2，旧控制与导入退役，公共工具/格式和资产保留 | 用户了解双协议差异后要求“收敛统一一下” |
| 2026-10-30 | R3 按用户“按照建议修改”收窄：AC-57/M22 只表示旧导入/升级/rebind 退役，移除 runtime_upgrade 用途；补齐现有配置确认重建与新版本发布的入口/契约/定向验证，不新增通用重建 | 旧 rebind 对正常在线同版本返回原实例，不能作为已存在的通用 v2 重建依据；设计仍待单独确认 |
| 2026-10-30 | 修订 R4/R5/R6：用户/系统来源分型并补 observation→recover→阶段准入→路由闭环；维护投影和停 writer 前准入；预览同一 Version 锁/UoW 原子登记及幂等回收 | 用户采纳独立评审建议；71 条 AC 未改，设计仍待单独确认，未编码或部署 |

**实施登记（2026-10-30）**：用户明确确认设计后进入任务拆解与开发。首批字段、scope与动作门面/业务资格已实施；T065补齐现有短票据生产者，T066补直接受影响的上下文回归，属于原设计接线细节，不改已确认动作/归属/协议边界。

| 2026-10-30 | 已确认设计实施快照：六动作/具体租户/真实主体、预览事务与阶段许可完成本地接线；补齐私有补包遗留门槛及工具范围头，新增SQL回滚与凭据配对验证 | task-review发现C1新增查询分层与唯一遗留选择器；无产品边界变化。真实E2E及最终L2待完成，未推送部署 |
