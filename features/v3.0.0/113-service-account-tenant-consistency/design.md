# Design: 服务账号与应用操作租户一致性

**关联**：[spec.md](./spec.md)（38条AC已确认） · [需求发现](./discovery.md) · [设计评审记录](./design-review.md)

**版本**：v3.0.0；发版线 `feat/3.0.0`。
**最后更新**：2026-10-28（Asia/Taipei，修订R2三项评审问题）。
**阶段**：用户已单独确认修订设计并授权拆任务和开发（确认版SHA-256：`d16fbbd1519c404fdcddeb20c5146bf8fba4dc891c72b7f2cd0ed433a1062ed4`）。实施中，进度见[tasks.md](./tasks.md)；已实现与待实现分开记录，未完成真实E2E，不表示已交付。

## 1. 目标与非目标

在服务账号公共业务准入处阻断归属人租户失配，在应用业务入口阻断调用者跨租户操作，并为超管提供明确的服务账号管理/创建租户。异步发布资格失败时，保持当前及待生效版本不变。

不做资源移交或迁移，不改已有账号、密钥、应用的租户和owner，不自动停用应用/账号或撤销密钥；不新增发布幂等、人员迁移锁、跨阶段事务或运行时权限。本轮不改runtime-manager/代理的编排实现，不新增数据库表/列、Alembic或数据修复脚本，不改变PAT生命周期、审批引擎状态、owner-only权限和原有超管例外。

## 2. 关键约束

遵循[constitution.md](../../../docs/constitution.md) C1–C8及[版本契约](../release-contract.md)，不在本文重抄全局法律。特有约束：

- **两个独立的租户判定**：服务账号请求比对“服务账号租户—归属人当前有效租户”；应用操作比对“已认证调用者租户/有权管理范围—应用租户”。前者通过不代替后者。
- 归属人关系变更后下一次调用必须见到新关系，不能依赖principal缓存TTL；查询使用现有权威数据库会话，不增第二套关系缓存。
- 资源owner不等于请求执行主体。模式S仍是service_account主体，模式D仍采用既有受限被代表身份，不能构造拥有owner角色的临时管理员。
- 应用自动恢复和用户新发布不同。原批准版本的可信恢复保持原运行合同，不能因为owner迁租户自动停止；用户请求和新发布仍执行本次规则。
- 管理范围以F019共享状态为真相；单次请求接受时验证并固定范围，随后其他标签页切换不撤销已接受操作，不持有跨Redis/SQL全局锁。
- 不对116三个存量应用、账号24、审批414/415实施维护变更；真实验收使用临时对象。只做本功能定向验证；DM8仅静态兼容核对。

## 3. 方案对比与选定

### D1：服务账号准入采用实时关系校验

- **备选**：只在发布API检查；依靠人员迁租户事件清凭据缓存；自动撤销所有密钥；每次业务准入读取当前绑定。
- **选定**：保留原凭据有效性缓存，在其后对service_account执行实时绑定校验；HTTP、MCP工具执行和WebSocket新业务消息共用同一公开资格能力。
- **原因**：`credential_validator.validate_bearer`缓存的是完整principal，热命中跳过resolver；只改resolver仍允许旧owner继续使用。事件清理还依赖所有人员变更路径和消息成功，不满足AC-03；自动撤销违反AC-07。
- **重新考虑条件**：测得实时查询成为瓶颈后，另行评审具有明确变更顺序保证的共享版本机制；本轮不以TTL代替资格准确性。

### D2：应用校验前先固定调用者来源，按动作保留原权限

- **备选**：依赖SQL自动租户过滤；加载App后比较ContextVar；所有应用动作改成相同管理员权限；抽取仅验证租户的公共边界，再执行各动作原规则。
- **选定**：在app_runtime提供租户边界应用接口，以请求已认证的actor/principal及管理范围为输入；先拒绝租户不符，再执行原owner/管理员/状态检查。对既有允许超管跨租户的入口显式传入例外策略，默认不允许。
- **原因**：子租户SELECT可能包含Root行；`AppStateService._load`、`AppMetaService`、`AppDataService`读取App后会切执行租户，比较此时的ContextVar等于自证。数据管理本来owner-only，不能因复用生命周期管理员判断而扩权。
- **重新考虑条件**：将来权限领域正式统一这些业务动作时，沿其应用协议演进；本轮不新增FGA关系、action或投影模型。

### D3：服务账号管理复用F019状态，增加本模块范围准入

- **备选**：直接复制模型页ScopeBar；给账号增加可编辑tenant_id；新增独立的本页租户状态；复用F019共享状态并补范围确认。
- **选定**：共享F019底层管理范围，在服务账号模块增加受控scope读写及请求范围确认；Root必须显式1，未选择时不可创建。管理写操作携带表单打开时的预期租户，后端与权威范围比对。
- **原因**：模型页Root映射为null，而服务账号无scope时可能按owner推导创建租户；直接复制会再次误建。改已有账号租户违反AC-21；仅本地保存无法发现其他标签页切换。
- **重新考虑条件**：F019将来改为标签页独立、带请求级scope的统一协议时整体迁移；不在本feature私建第二个共享状态源。

### D4：发布校验放在选择待生效版本前，失败与清理解耦

- **备选**：仅接收时检查；先stage_version再在容器启动时查；在每个已明确阶段入口、stage前检查。
- **选定**：接收、Worker开始、版本/审批生成前、审批执行stage前和新增预览分别校验冻结owner/tenant。拒绝采用现有failure/outbox执行失败通道，清理独立推进。
- **原因**：`bring_online`先stage_version再分支；停用应用只登记pending也属于发布副作用。审批回调正常return会被记为executed，不能通过返回一个失败字典表达租户拒绝。
- **重新考虑条件**：发布流程将来提供统一阶段资格协议时再收敛；不为本次引入人员迁移锁或通用发布工作流重写。

### D5：存量数据不动，使用原状态与原存储

- **备选**：迁资源、改owner、复制授权、增加失配状态表；在调用时判定资格。
- **选定**：无数据迁移；不新增失配状态或owner快照表。已接收发布用现有AppDeployment，后台运行用现有任务/赋值记录，账号管理使用现有F019及审计。
- **原因**：用户明确不移交/迁移；新增状态副本会与人员关系和凭据启停漂移。修复不能靠改116数据使问题暂时消失。
- **重新考虑条件**：用户以后明确提出资产移交/迁移，再立独立规格及运维流程。

## 4. 系统现状与设计接线

### 4.1 已核对现状

本地基线 `3d0406bc6615a4c04dcc3e846879d8e7524df47f`，分支`codex/113-service-account-tenant-consistency`。本会话已取得远端`feat/3.0.0@5a2df47decdefcb1bc00b5b6bf17c8ced64c625f`；本次关注的凭据、应用状态/发布核心文件无差异，不把其他功能的远端变化混入当前worktree。

| 现状入口 | 实际行为 | 本次设计增量 |
|---|---|---|
| `open_api/domain/services/credential_validator.py` | 校验凭据与账号租户、账号启停；热缓存不重新resolve主体 | 缓存之后仍校验当前账号/owner关系 |
| `owner_repository.py` | PAT/选人查有效自然人；批量结果按user覆盖 | 新增专用于服务账号执行的唯一关系读取，不改变PAT查询语义 |
| `open_mcp/auth.py`、`server.py` | stateless Streamable HTTP；传输层调用公共access_context，工具取ContextVar身份 | 工具执行前再进入公共准入，覆盖同请求内延迟执行，不修改会话协议 |
| `credential_watcher.py`、`common/chat/manager.py` | WS周期复查凭据，但dispatch_client循环使用建连时operator | 每条新业务消息先复核并安装当次身份；不能只依赖3秒watcher |
| `app_state_service.py` | `_require_operator/_require_deleter`有owner直接返回分支；`_load`切执行租户 | 先租户边界，后原角色/owner分支 |
| `app_meta_service.py`、`app_data_service.py` | 也存在只比owner的入口；数据无管理员绕过 | 元信息、数据/导出补租户边界；保留差异化权限 |
| `app_query_service.py`、`f048_app_permission.py` | 详情和F048目标已有租户判断；平台日志部分入口先判owner | 复用正确边界并补日志缺口，不新建旁路授权 |
| `publish_status_service.py` | publish-status独立装配版本/审批信息；平台viewer先按owner放行，手动上线也有独立入口 | 读取和人工重试均先检查认证租户，不能只修AppQueryService |
| `snapshot_browse_service.py`、`version_diff_service.py` | 共用ReviewAccess；先按owner返回，App加载仍受Root共享规则影响 | 在共享审阅入口检查租户，再执行原角色/任务判定 |
| `app_secret_service.py`、`secret_rebuild_service.py` | 已有同租户owner检查、用户确认重建 | 保留校验与确认；统一来源约定，不增加保存后自动重启 |
| `PublishPipelineService` | 当前先建draft/存包再登记deployment；Worker用持久owner/tenant | 加资格闸门，不重排成接收占位、不加新幂等表 |
| `PublishOnlineService.bring_online` | 先stage，再回收预览；停用时仅stage | 校验先于stage；资格失败仍回收预览并抛错 |
| `PublishOnlineService._settle/_owner_actor` | 协议v1先迁移，再把由App字段构造的owner交给人工启动入口 | 人工校验移到迁移前；批准执行改用有持久来源的内部启动合同 |
| `admin/application/tenant_scope.py` | 已有`current_admin_scope`直接读权威scope，读取失败不靠中间件fallback | 复用此公开入口；选定租户可用性与预期范围在服务账号层确认 |
| 平台服务账号页面 | 无scope选择器；创建不传范围确认；通用选人器不按账号scope查询 | scope选择及候选资格来源，读写请求均绑定页面scope |

### 4.2 服务账号调用链（设计）

```text
原token哈希/有效性/前缀检查（允许原缓存）
  → 实时载入可信账号ID的当前账号、owner及唯一有效成员关系
  → 账号租户=凭据租户，账号启用；owner当前租户=账号租户
  → 更新当次principal的owner/name，保留凭据scope及原主体
  → 原delegate、路由scope、PAT/hosted_app及业务权限流程
  → 业务执行
```

**公开资格能力**：新增`open_api/application/service_account_tenancy.py`，导出：

- `revalidate_service_account(principal) -> OpenApiPrincipal`：仅service_account执行实时检查；其他主体直接交给原校验流程。保留mode及授权主体，不改delegate目标。
- `require_owner_tenant(owner_user_id, tenant_id) -> None`：供发布消费者校验冻结owner，抛出同一错误族；它不查询原服务账号当前owner，因此不追溯换提交归属。

实现逻辑由open_api域service编排、repository查询；其他模块只依赖application入口，不导入owner仓储或直接查询成员关系。查询不接受外部参数作为已认证账号ID。

**仓储查询**：为执行新增account/owner/成员关系的读取，使用现有权威数据库会话与受限`bypass_tenant_filter`；仅对已验证principal的账号、或可信发布记录的owner做精确查询。账户未启用/删除仍按现有26027处理；凭据与账号租户不同按26002处理。成员必须`is_active=1`且`status=active`，且结果唯一；不以`first()`或字典覆盖判定唯一。不把`User.delete`标记作为新准入条件，但硬缺失用户或不存在唯一有效关系按无法确认拒绝，保留AC-08语义。

新增关系判断不缓存，使用单次查询/受限关联查询避免逐行查成员。热命中请求增加一次当前绑定读取；冷请求仍可有原resolver读取，不为消除这一次读取引入跨请求状态。绑定变化完成后下一请求读取新关系；同一已开始阶段不承诺与人员变更保持全局事务隔离。

`validate_bearer`在命中/未命中合流后调用实时资格能力；不将更新后的owner资格结果写回为长期真相。原凭据撤销、有效期和scope缓存仍按既有上界工作，资格拒绝不删除/改写密钥。

**MCP**：传输层维持原准入；`call_tool`在执行工具及读取其principal前，根据本次真实MCP请求的Authorization/身份头，再进入公共`open_api_access_context`，以工具marker限定scope/modes；不使用构造的空Request作为鉴权来源。工具内ContextVar绑定本次新principal，退出恢复，不把并发工具身份写到共享全局对象。重新校验失败直接返回现有MCP错误格式；工具体不执行。现有stateless模式不增加服务器会话缓存。

**已实现的消息接线**：`ChatMessageExecution`冻结每消息operator、执行快照及session主体；后台用连接的浅副本执行，单独初始化身份绑定的agent/callback，原连接共享的会话/取消机制保留。复制是消息内部实现，不产生新用户身份。会话partition比对排除仅用于历史兼容的owner字段，因此owner合法改绑不会把会话变成owner的自然人会话。

**WebSocket**：在`ChatManager.dispatch_client`接受每个新业务消息、执行权限检查/投递任务之前，接入由v2端点传入的可选异步准入回调。common模块仅接受中性callable，不导入open_api域；未传回调的既有Web/匿名路径保持原行为。v2回调完整复核凭据、服务账号关系、委托，刷新本消息的operator、PermissionActor及执行快照；`ChatClient.handle_message`新增可选的消息级执行上下文参数，后台投递也捕获该不可变快照，不通过覆盖共享client.login_user或连接scope字典改变正在执行的旧消息身份。默认未传仍使用原连接身份，只有v2端点传入此准入回调。仍以服务账号会话subject分区，不把新owner变成会话所有人。请求返回/抛错后重置ContextVar。身份失败发送现有结构化错误并拒绝该消息/关闭1008；不能仅靠后台watcher的时间窗。原watcher继续处理原有凭据失效策略，不扩展成新会话治理功能；本次不要求中断已开始的单次流式业务。

### 4.3 应用请求的租户边界（设计）

新增`app_runtime/application/tenant_access.py`与其域service，提供只读且可单测的`require_app_request_tenant(app_tenant_id, actor, *, allow_global_super=False)`。入口校验使用不可变的请求来源：

1. v1平台请求取已认证`UserPayload.tenant_id`；入口本来支持超管管理范围时，从`admin.application.current_admin_scope`读取并限定该范围；普通人不能采用scope头改变自己租户。
2. v2/MCP取已认证principal.tenant_id及原PermissionActor；兼容的owner UserPayload只用于既有字段和业务owner检查，不借其角色推导服务账号权限。
3. 先检查租户，后允许切换执行ContextVar到应用租户；已经切换也仍比较上述actor/principal，而非`get_current_tenant_id()`。当前`/api/v1/apps`没有被F019管理范围中间件列入，本次不新增该全局范围，也不把服务账号页面的scope头套到应用操作；原来允许的超管跨租户动作保持原入口语义。
4. 跨租户拒绝复用AppNotFoundError/既有不可见语义；不返回对方tenant或确认目标存在。只有本来允许的全局超管入口可按其管理范围继续操作。

| 动作/调用方 | 插入位置 | 保留的原规则 |
|---|---|---|
| 人工publish/manual_publish/resume/stop | `AppStateService._require_operator`的owner分支之前；`_start`前置条件一致；发布页另一手动入口另见下一行 | owner/该租户管理员/既有超管动作权限；状态机、资源档位和容量 |
| 发布页`publish/manual-publish` | `PublishStatusService.request_manual_publish`进入`_is_owner`前；`PublishOnlineService.manual_publish`在`_settle`前复核已认证人工入口及冻结版本资格 | 此入口仍为owner-only；不能借下层生命周期的管理员例外放宽；v1迁移前完成拒绝 |
| delete | `_require_deleter`之前 | owner-only；owner失效时原有管理员清理例外；在线不可删 |
| name/description/logo | `AppMetaService._require_editor`之前 | 不产生版本，不改应用态；保留原编辑权限 |
| detail/instance/versions | `AppQueryService._load_visible` | 复用已有正确租户判断，不放宽 |
| 平台/CLI/MCP publish-status | `PublishStatusService._require_viewer`的owner分支之前，且早于版本/审批/部署信息装配 | 平台原owner/管理员/超管；CLI/MCP仍为同租户owner-only |
| review-context/源码tree/file/版本diff及其预览消费者 | `ReviewAccess.require`共用租户闸门，先于owner/admin/task角色判断和快照读取；精确路径见§4.3.1 | 保留同租户owner/租户管理员/该版本审批人及既有全局超管角色；不增加跨租户审批任务例外 |
| platform/CLI/MCP日志 | `_require_log_access`进入owner判断之前 | 平台原管理员读取；凭据门owner-only，不添加管理员绕过 |
| 数据schema/rows/update/export/结果恢复 | `AppDataService._load_owned/_require_owner`及结果恢复重新授权 | 数据owner-only；生产编辑确认；管理员不因super获得新权力 |
| 环境变量get/save/delete/rebuild | 原AppSecretService、AppSecretRebuildService校验保留并对照公共边界 | 保存不重启、确认才重建、revision/版本CAS和掩码输出 |
| 旧导出结果/任务引用 | 返回结果/文件前重新检查App、actor和operation归属 | 过期/删除等原判定保留；不以曾创建任务替代当前授权 |

`allow_global_super`仅在生命周期/元信息/原平台详情与日志等本来允许的路径使用；数据、CLI/MCP owner-only门及环境变量写/确认重建为false。全局super即使恰好是App的旧owner，也不能从owner相等分支绕过owner-only入口的同租户条件。无actor请求不能调用该人工检查API后获得默认允许。

请求被拒时不进入资源分配、数据库/MinIO写入、实例操作或投影删除；可记拒绝日志。租户一致仍须原权限运行时/业务规则允许，不建立“同租户就允许”的替代授权器。

**内部调用区分**：`actor=None`不作为通用豁免。发布对元信息的内部调用改走显式的`update_meta_for_release(deployment_id, *, app_id, name, description, logo)`应用入口，由内部可信部署记录解析app/tenant/owner并检查冻结资格；人工入口继续要求actor。stage版本采用F055公开的审批执行入口而不是对外暴露无来源版本指针写入。原AppStateService已承担状态写入，仍是唯一状态写入方。

### 4.3.1 发布状态、版本审阅与源码的独立读取入口

这些读取不经过`AppQueryService._load_visible`，必须单独接入同一租户边界；不能用详情页面被拒绝推断API已安全。对应路由是既有入口，不新增HTTP API：

| 读取入口 | 既有调用链 | 本次校验及副作用边界 |
|---|---|---|
| `GET /api/v1/apps/{app_id}/publish-status`，CLI/MCP的发布状态调用 | PublishStatusService.get_publish_status → _require_viewer | 用认证actor/principal检查租户；再按entry保留原权限；拒绝后不装配deployment、approval、current/pending版本及schema/capabilities |
| `GET /api/v1/apps/{app_id}/versions/{version_id}/review-context` | SnapshotBrowseService.review_context → ReviewAccess.require | 共享入口先租户、后原审阅角色；不能因owner迁出后ID仍相同放行 |
| `GET /api/v1/apps/{app_id}/versions/{version_id}/snapshot/tree`、`snapshot/file?path=...` | SnapshotBrowseService.list_tree/read_file → ReviewAccess.require | 在下载/物化源码快照、返回文件目录或正文前拒绝 |
| `GET /api/v1/apps/{app_id}/versions/{base_version_id}/diff/{target_version_id}` | VersionDiffService.diff → ReviewAccess.require | 两个版本始终带已验证app_id；拒绝后不读取两侧快照 |

**ReviewAccess的角色顺序**：全局超管仅沿原来已允许的审阅例外；其他actor须先满足认证租户=App租户，再按owner、该租户管理员、该版本审批任务的原顺序判断。审批任务不是租户通行证；持有旧任务的迁出人员不能借owner或task分支绕过本次租户约束。原同租户审批人仍可按既有“任一比较侧有任务”规则查看待审版本与已发布基线的diff，不改审批人解析或通用审批决定权限。

ReviewAccess的已有预览describe/start/reclaim消费者也沿用该人工边界；新增start另需§4.4的冻结owner资格。自动到期/终态回收继续由原可信后台任务执行，不通过伪造人工actor收回预览。不改通用审批中心的任务列表/决定协议。纯内部`runtime_hint`无独立外部入口，仍要求调用方已完成同一App的日志授权，不新增无身份读取通道。

后台停止/回收/运行观测继续使用已认证服务身份与持久RuntimeOperation/Assignment，校验node、app、tenant及现有epoch；不构造来自App租户的假登录用户绕过人工入口。维持旧current批准版本的自动恢复不查询当前服务账号owner，也不被本次自然人请求闸门误伤；新代码发布/新增预览必须走下节冻结资格。

### 4.4 发布、审批及预览（设计）

F055新增应用入口`app_publish/application/release_tenancy.py`：`require_release_eligible(app_id, version_id=None, deployment_id=None)`。域service从现有AppDeployment查冻结owner/tenant，加载App并比较两者；调用open_api的`require_owner_tenant`。版本场景按(app_id,version_id)定位唯一发布记录，再校验既有版本/审批来源。不存在或不唯一时失败，不借当前服务账号改绑修补历史；不新增快照表。

### 4.4.1 批准执行与人工启动的接线合同

**批准执行入口**：F055的`AppPublishScenarioHandler.on_approved(instance_id, payload_snapshot)`仍由原Celery/outbox调用，转到`PublishOnlineService.bring_online`。新增`app_publish.application.release_tenancy.qualify_approved_release(instance_id, payload_snapshot) -> ApprovedReleaseSource`；它只接受服务端回调的引用并重读持久记录，不把传入payload本身视为已授权。新增只读`approval.application.execution_source.get_business_approval(instance_id)`包装审批域的现有repository读取，返回不可变的实例引用/状态/业务键/快照；不改通用审批引擎、outbox回调参数或状态。

批准来源必须同时符合：

1. 持久实例属于`app_publish_request`、business_resource_type=`app`；instance.tenant_id、business_resource_id、business_key及持久快照指向同一个App、AppDeployment和AppVersion。
2. deployment.approval_instance_id=instance.id，deployment的app/version/tenant/冻结owner与App一致；外部回调快照的这些引用必须与持久快照相等。缺失、歧义或不一致拒绝，不使用`_deployment_ref`的审计兜底对象作为授权来源。
3. 持久审批状态代表已批准决定（`approved`、`executing`、`executed`，或原有显式重试流程中的`execute_failed`），拒绝pending/rejected/withdrawn/cancelled/exception。状态检查不另赋予重试权，调用仍只能来自原outbox或已授权人工入口；不新增重放API/自动重试策略。
4. 固定owner当前唯一有效租户仍与发布租户相等。以上资格必须在stage、数据迁移、停止旧实例或启动新实例之前完成；App已删除时保留原取消/清理分支，不借此启动版本。

`ApprovedReleaseSource`是本次阶段的不可变内部值：`approval_instance_id:int`、`deployment_id:str`、`app_id:str`、`version_id:str`、`tenant_id:int`、`owner_user_id:int`，另带服务端批准执行的审计动作来源。由资格入口生成，不能由HTTP请求体反序列化或持久缓存，也不是新凭据/管理员身份。

**启动接线**：新增`app_runtime.application.approved_release.start_approved_release(source: ApprovedReleaseSource) -> ActionResult`，仅供F055成功资格检查后的批准执行路径使用。F055的`_settle`显式区分“人工actor”与“批准source”，两者必须且只能选一个；批准分支不再调用`_owner_actor(app)`，也不把source转换为UserPayload/SimpleNamespace后送入人工`publish`。runtime应用入口先比对source与重新加载的App/所选pending版本/tenant/owner；冲突沿原状态冲突返回，不能用另一版本的批准来源启动当前新pending。

两类入口共用AppStateService内部的既有启动体：人工入口先做认证租户与原动作权限，批准入口先验证可信source，再进入共用的容量、编排、探活及CAS代码。启动体不提供`skip_tenant_check`或`actor=None`通行开关，不新增外部路由。AppStateService仍是状态唯一写入方。审计使用独立的执行来源字段和批准记录中的owner归属，不把它当自然人认证身份或借用owner角色鉴权；原审计action/owner通知判定保持。

**阶段边界**：本次资格在stage之前完成，stage与其后的同一次批准启动共用该阶段source；不在stage后才新增owner资格拒绝再回写旧pending。source仅用于本次调用，后续回调重试、人工重试或重新提交均重新验证，不把旧source跨阶段复用。人员变更与已接受阶段不新增全局锁/跨阶段事务；版本并发仍由现有状态CAS处理。持久来源/版本对照不是再次构造调用者身份。

**人工启动顺序**：发布页`request_manual_publish`先检查认证租户，再做原owner-only；`PublishOnlineService.manual_publish`在`_settle`前验证该人工来源及冻结版本资格。独立`actions/manual-publish`、人工publish/resume在AppStateService的人工入口先做各自原权限，再在维护/实例动作前确认选定版本资格。配置确认重建也保持原owner-only。特别是协议v1的`_settle`调用`migrate_for_release`之前必须完成上述两层检查，不能只在迁移后的`_start/_require_operator`补检查；协议v2同样先检查后创建持久部署操作。

批准路径主线：`outbox → on_approved → 持久批准来源与冻结owner资格 → stage_version → 清理预览 → 停用则仅保留pending / 否则_settle(source) → start_approved_release(source) → 原启动体`。资格失败在stage前记录失败、继续终态清理并raise，沿原execute_failed通道；同版本自动恢复仍走原RuntimeOperation/Assignment，不调用本次人工或新批准入口。

| 阶段 | 精确时点与持久来源 | 拒绝结果 |
|---|---|---|
| 同步accept | 公共准入后，`PublishPipelineService.accept`在create_draft/store_package/元信息变更前再次检查principal的当前owner/tenant；迭代保留_assert_owned | 新提交不留app、快照、deployment/审批；临时HTTP文件按原流程清理 |
| Worker开始 | 在materialise/build之前，用已加载deployment校验 | `_fail`保留失败五元组；不启动准备容器 |
| 版本/审批前 | `_record_version`进入VersionService之前；`_update_meta`也使用同一资格避免准备期间迁租户后改元信息 | 不创建新审批/版本；不覆盖原应用元信息；原临时产物按既有生命周期回收 |
| bring_online | 加载app/version/发布来源后，**stage_version之前**检查；停用仅stage分支也不豁免 | 不改current/pending/route，不迁DB/停旧/启动新；记录发布失败并抛错给outbox |
| manual_publish/resume及用户配置重建 | 人工App租户/权限检查后，选定版本和发布来源资格检查，均早于维护/实例动作 | 保留原状态、current/pending及路由；复用原错误呈现与确认 |
| 新审批预览 | PreviewInstanceService.start原ReviewAccess允许后、创建session/配额/实例前 | 拒绝新预览；已有预览终态/到期清理继续 |

**先校验不等于先退出清理**：bring_online的资格失败捕获后，按原终态入口尝试`reclaim_on_release_terminal`；若清理失败，保留可重试的session/运行任务事实，不伪造已回收，也不掩盖主要资格错误。先持久记录发布失败，再抛原资格错误；审批outbox沿用FAILED/execute_failed、异常记录与通知。成功分支才stage_version并走原停用/容量/启动流程。普通容量不足等既有产品结果不因此一律改成审批执行失败。

后台旧任务重试每次重读来源和owner关系。恢复关系不自动重启该失败发布；用户按既有权限主动重试或新提交；若原审批execute_failed阻止新提交，先由有权管理员通过现有异常处理/重试收口，不新增绕过审批锁的入口。失败审批决定不改写为驳回。原待生效版本可能属于另一并行正常提交，拒绝分支不写指针、不用旧快照“恢复”覆盖别人已经完成的合法操作。

### 4.5 超管服务账号管理（设计）

**状态与身份**：F019仍是唯一共享状态源。服务账号模块通过`admin.application`公开接口读取/设置scope；通过admin.application新增受控setter包装与租户可用性查询协议，仅为该模块增加可用租户确认，不修改模型/知识等其他管理页的业务权限；服务账号域不直接访问Redis或Tenant ORM。设置目标先验证全局超管、Tenant存在且active；Root选项提交1，不提交null。

新增静态路由置于`/{service_account_id}`之前：

| 路由/调用方 | 入参/结果 | 规则 |
|---|---|---|
| GET `/api/v1/service-accounts/management-scope` / platform超管 | 返回F019的scope_tenant_id、expires_at | 仅超管；读失败明确不可用，不把异常当Root |
| PUT 同路径 / platform超管 | `{tenant_id: positive-int}`，返回同上 | 目标active，复用F019 setter和原scope-switch审计；不提供此处null清除 |
| GET `/api/v1/service-accounts/owner-candidates` / 原有账号管理员 | keyword（≤128字符）、page（≥1）、page_size（1–100），PageData候选 | 仅当前scope的活跃自然人和唯一当前成员关系；列表不包含服务账号；bounded分页、按user_id稳定排序 |

以上均是设计新增，当前代码不存在。scope的GET/PUT返回`{scope_tenant_id: int|null, expires_at: string|null}`；PUT请求字段必须为正整数。owner候选响应沿统一envelope，data内为`{data: [{user_id:int,user_name:string,tenant_id:int}], total:int}`，由服务端在管理范围内分页，不返回密钥或其他租户用户。不给ServiceAccountCreate/Update增加可编辑tenant_id。

**范围确认头**：`X-Service-Account-Tenant: <positive integer>`仅表达客户端看到的预期范围，不能授予租户或管理员权限。新UI在本模块所有读写请求携带该头，写操作必须用表单/确认框打开时固定的值，不能在axios拦截器发送前读全局最新值替换。后端公共管理依赖：

1. 原get_service_account_admin确认身份，再由服务账号范围service从F019权威存储确认超管scope；非超管仅用其认证租户。
2. 多租户超管写操作必须提供头，必须已有明确scope且与头相等；缺头、scope到期/清除或不符统一拒绝为范围变化，提示选择/刷新，不猜Root。
3. 非超管可省头（保持原客户端行为），如提供则必须等于本人认证租户；不能借头选择别租户。单租户省头仍采用原Root行为。
4. 验证所选Tenant仍active。scope读取故障拒绝，不能采用中间件已有的读取失败回退。验证通过后，本请求固定current/visible为该租户并在结束重置；后续标签页切换只影响下一请求。
5. 所有管理写路由统一接入，包括批量授权变更；Pure-read POST候选过滤按读取处理，不以HTTP方法代替业务动作清单。详情/密钥等仍由get_row检查账号tenant，不以仅命中ID放行。
6. 新UI的读请求也带预期头，若范围已变化即拒绝并要求刷新，旧响应不被显示。既有不带头的读请求保持当前管理范围语义，服务端仍校验active及目标范围；不将“没有预期头”变成跨租户不检查。

**兼容性**：多租户超管的旧脚本管理写请求需要补头并显式选择scope；这是防误写的有意收紧，后台/前端同步发布，升级说明给出示例。普通租户管理员和单租户写行为保持；业务密钥调用不读取该管理头。

### 4.6 页面与候选（设计）

平台`SystemPage/components/ServiceAccount`增加业务scope栏/局部hook；复用已有F019接口状态源和模型页现成选择交互，不能把模型页Root→null映射复制过来。未选择时提示选择租户，暂不发列表/创建请求；已有有效scope原样显示；只有用户选择Root才写1，不在挂载时覆盖别页scope。

- 用`useServiceAccountManagementScope`调用本模块scope接口；scope变化、窗口重新聚焦及提交范围变化错误后刷新。列表、详情、弹窗、key确认、grant确认均带scope快照，scope查询key含user，列表请求闭包及挂载key包含scope/关键词和revision。
- 选择切换前取消本scope query，避免旧GET覆盖成功PUT；切换中禁写；成功后清旧详情、关键词结果、owner及未提交表单，取消旧请求并增加本页请求序号；返回租户/请求序号不符的迟到结果丢弃。失败保留先前页面scope，不提前显示切换成功。
- 租户候选按现有Tenant API完整分页获取active选项，不能硬截前100个；过滤null/空id。创建/编辑owner的候选通过新owner-candidates接口分页搜索，按选定scope查询，不把全局部门成员结果当租户成员。
- 归属人选择复用现有用户选择控件的搜索/选项呈现，接入可注入的候选数据源；默认数据源不变，不能为了F113改变其他页面用户选择逻辑。指定candidateSource时使用本租户平铺分页候选，未指定的默认组织树与过滤接口保持不变。只渲染后端返回的合格候选，切scope后清值，保存时仍重验。
- 已读UI规范入口、组件总览和Select规范。Select页面标为draft（桌面已落地、手机待做），本轮跟随已有ScopeBar/用户选择实现，不新增样式、设计系统组件或移动端底部面板。只新增业务接线、scope提示和错误文案；所有新增键同时交付zh-Hans/en/ja。
- 复用统一request/错误拦截；业务组件不新增403分支。scope变化采用可识别的业务409/code，经`handleUiRequest/showApiError`处理；hook只对范围变化清页面并要求刷新，不自动重放写请求。已有全局确认框新增可选signal随本页范围失效关闭；不传signal的旧调用保持行为。

## 5. 已知坑与处理位置

| # | 已核对事实 | 忽略后的结果 | 处理位置 |
|---|---|---|---|
| 1 | principal缓存含owner，热命中不resolve | 修了冷请求仍能用旧owner | validate_bearer合流后实时校验 |
| 2 | 原OwnerRepository过滤User.delete，批量按user覆盖 | 人员标记被误判为迁租户；多条当前关系被静默选一条 | 专用执行关系查询；PAT/选人保留原方法 |
| 3 | App加载会改执行ContextVar，子租户SELECT含Root | 看不到列表但直接ID操作通过；比较ContextVar自证 | tenant_access使用认证actor/principal |
| 4 | 应用数据原本owner-only | 复用operator管理员短路导致越权 | 调用级allow_global_super策略默认false |
| 5 | stage_version早于实际启动，停用分支仅stage | “上线失败”却改变下次启动版本 | bring_online资格必须早于stage |
| 6 | 审批回调正常return等于执行成功 | 返回失败字典仍成为executed | 记录失败后raise，清理独立 |
| 7 | F019共享scope会到期，middleware异常可能回退 | 旧表单写到Root/其他租户 | 权威scope读、预期头与active检查 |
| 8 | 模型页Root表示null，账号创建null可能随owner | 超管以为建Root，实际落到子租户 | 本页Root显式1；无选择不能创建 |
| 9 | WS监视器每3秒，dispatcher保留旧operator | 已迁租户仍在时间窗发送新业务 | 新业务消息回调，不只依赖watcher |
| 10 | v2平台后台恢复不等于人工resume | 统一封所有无actor调用会停掉存量恢复 | 明确可信运行任务与新发布两种入口 |
| 11 | AppVersion无tenant列 | 只按version_id读取泄露别的app历史 | 查询始终带已验证app_id，发布来源二次对照 |
| 12 | publish-status不经过AppQueryService，平台owner仍直接放行 | 主详情已拒绝但独立API泄露版本/审批/部署内容 | PublishStatusService._require_viewer先检查认证租户 |
| 13 | 源码/审阅/diff及预览共用ReviewAccess，owner分支无租户判断 | 旧app/version引用仍可读源码；预览资格闸门不能保护只读接口 | ReviewAccess共享人工边界及§4.3.1消费者清单 |
| 14 | _settle以App字段构造owner，且协议v1先迁移再进入AppStateService | 租户检查自证或正常批准启动被误拒；人工检查太晚已迁移 | §4.4.1批准source与人工actor分流；检查必须早于_settle迁移 |

## 6. 对外契约与依赖

### 6.1 提供的契约（设计，尚未落码）

| 契约 | 生产者/调用者 | 数据与认证 | 失败与兼容 |
|---|---|---|---|
| 服务账号实时资格 | open_api application / validate_bearer、MCP、WS | 已验证principal，返回当次新principal | 不改token、scope、mode来源；失配403，依赖503 |
| 冻结owner资格 | open_api application / F055发布资格 | 持久owner_id/tenant_id | 不接受外部指定owner覆盖；不读账号后来owner |
| App请求租户边界 | app_runtime application / F054、F055业务service | 认证actor/principal、目标App租户、入口明确super策略 | 原无权/不可见错误，不能越过原owner规则 |
| 发布资格 | F055 application / Worker、审批、人工启动、预览 | deployment或(app,version)可信引用 | 缺来源/不一致拒绝；不变版本指针 |
| 批准来源只读投影 | approval.application.execution_source / F055资格service | 可信instance_id，返回状态/tenant/resource/business_key/快照的不可变数据 | 原repository读取；不改通用审批权限或outbox协议 |
| 批准阶段资格 | app_publish.application.release_tenancy.qualify_approved_release / bring_online | 持久approval/deployment/app/version及冻结owner，返回ApprovedReleaseSource，字段见§4.4.1 | stage前拒绝；无引用兜底、无source长期缓存 |
| 内部批准启动 | app_runtime.application.approved_release.start_approved_release / F055 _settle的source分支 | 已验证的ApprovedReleaseSource；不接受人工actor替代来源 | 无HTTP端点；同租户/所选版本对照，共用原启动体/CAS，保留恢复入口 |
| 发布状态与版本审阅 | PublishStatusService、ReviewAccess / 既有平台API及CLI/MCP消费者 | 认证actor/principal、App、版本引用/原审批任务 | 先租户后原权限；读取/下载内容前拒绝，精确消费者见§4.3.1 |
| 管理scope读写 | service-accounts管理API / platform | 登录超管；positive tenant_id；F019原状态 | active检查；不设置账号tenant_id |
| 预期管理头 | platform API层 / 全部账号管理写依赖 | 每个表单固定的X-Service-Account-Tenant | 非授权用户不能借头扩权；超管旧脚本需升级 |
| owner候选 | open_api管理API / owner选择器 | 已认证范围，PageData(data,total)；id/name等既有展示字段 | 不返回不合格用户；最终提交再次校验 |

**错误设计**：代码占用已扫描`common/errcode/open_api.py`；26070已用，以下26071–26073在核查基线未占用，实施前已重新扫描并在C5登记；当前代码分配26071–26073，未覆盖其他工作。

| 候选错误 | 候选码/传输 | 可观察原因 |
|---|---|---|
| ServiceAccountOwnerTenantMismatchError | 26071 / v2 HTTP403 | 归属人租户与服务账号租户不一致；返回处理指引，不返回别租户资源 |
| ServiceAccountOwnerTenantUnresolvedError | 26072 / v2 HTTP403 | 不能确认唯一有效租户 |
| ServiceAccountManagementScopeChangedError | 26073 / 业务冲突409语义 | 预期scope与实际不符、超管scope缺失/到期或必需头缺失；不自动重试写 |
| 关系/管理依赖失败 | 复用26030 / v2 HTTP503 | 依赖不可用，不把故障报失配 |
| App跨租户 | 复用16101及各入口原拒绝族 | 不可见；MCP沿原26305折叠，不额外泄露 |

v1按现有统一业务错误envelope返回（应用/服务账号前端不靠HTTP403新增分支）；scope API新增路由也采用本模块业务envelope。MCP保留现有工具错误格式，WS新消息拒绝按现有错误消息/1008表达。具体字段沿`BaseErrorCode`的既有shape，服务端新增码及消息同时进入三语api_errors源目录，不手改生成文件。既有全局身份/权限失败的403处理保持原样。

### 6.2 依赖及风险

| 依赖/Owner | 接口/内容 | 风险与处理 |
|---|---|---|
| 自然人/租户 | User、UserTenant当前唯一成员；Tenant.status | 不把部门树、历史成员或JWT单字段作为owner当前关系；无唯一关系拒绝 |
| F019/admin | current_admin_scope及setter、共享TTL/审计 | 其他页可切换，读取故障不能回退；不改已有其他页权限 |
| F048/permission | 原业务动作、actor及原管理员关系 | 租户边界不代替PDP，不新增直接FGA访问 |
| F055/AppDeployment | app_id/version_id/owner_user_id/tenant_id及失败五元组 | header缺失不能换tenant；旧任务重试重读，来源缺失明确拒绝 |
| F025/审批 | on_approved、批准来源只读应用协议、outbox失败、终态预览清理 | 只读封装原repository；不修改引擎状态/回调签名/审批人来源；回调raise才失败，后台清理需可继续 |
| F054/F086/F059 | 原App状态、current/pending、受控RuntimeOperation恢复 | 不修改编排API/镜像，不将同版本恢复误当新代码发布；Docker/K8s复用backend判定 |
| Redis | 原credential cache、F019 scope | 不新增资格缓存/本地文件状态；不可用不放行业务 |
| 前端请求及UI | controllers/API、useAdminScope契约、现有控件及三语文案 | 多租户超管新写头需前后端同步；旧接口/控件默认来源不受污染 |
| 平台存储/运行时 | 仅通过原业务service接口 | 本功能无新增第三方服务、CLI、Docker权限或MinIO直连 |

## 7. 定向验证与可观测

### 7.1 AC覆盖策略

| 分组 | 覆盖AC | 必要定向验证 |
|---|---|---|
| 准入/缓存/身份 | AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09 | 热缓存后迁租户；改owner；A→B→A；有效成员0/1/多条；禁用标记与无成员区分；同scope允许/缺scope拒绝；模式D也不豁免；依赖失败；PAT/hosted_app不加此闸门 |
| 发布与审批 | AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16 | 接收不留资源；阶段间关系变更；冻结owner不随改绑；在线/停用两状态current/pending/route不变；审批仍通过而执行失败；预览/临时资源清理继续；批准source真/假引用配对、不再构造owner；人工手动上线在v1迁移/v2部署操作前拒绝 |
| 管理页 | AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27 | Root显式1、子租户、无scope/到期、另标签页改变、Redis失败、非法/disabled租户；完整写动作清单参数化测试；普通管理员伪造头拒绝；候选分页/无非法ID/迟到响应；三语与窄屏人工清单 |
| 存量 | AC-28、AC-29、AC-30、AC-31、AC-32 | 升级无数据迁移；独立凭据/旧运行任务不改；116原对象只读核对；新账号与旧app无自动映射 |
| 应用操作 | AC-33、AC-34、AC-35、AC-36、AC-37、AC-38 | 同owner异租户对全部动作拒绝、同租户有权/无权配对；Root/子租户与叶租户相互；publish-status装配前拒绝，review-context/tree/file/diff在快照读取前拒绝；同租户审批人/无权用户/原super配对；旧任务不豁免租户；旧导出引用；super仅原例外、数据owner-only；ContextVar已被换成App租户仍拒绝；可信任务来源失配拒绝、正常旧版本恢复允许 |

后端测试放`test/open_api/`、`test/app_runtime/`、`test/app_publish/`、`test/admin/`中本功能的新增/受影响用例；MCP/WS分别验证工具/新消息执行体未被调用及正确身份。只对新增WS回调运行有/无回调配对，不跑聊天全量。前端只跑本功能组件/hook、修改文件lint/typecheck及i18n相关检查；Ruff、架构守卫仅针对改动及必须门禁。DM8使用静态查询/模型约束核对，不声称真实运行。

不重跑runtime-manager全量、Docker/K8s故障升级、arm64或通用审批所有场景；本方案不改审批来源解析/通用流转规则。若实现发现必须改其公共行为，先记录影响和必要验证，不默默扩大本特性。

### 7.2 可执行的验收路线（后续任务阶段）

使用专用测试租户A/B、临时owner、服务账号及临时应用，不使用116三个存量app做状态操作。凭据通过环境注入，调用日志和文档不记录明文。

1. 以A的账号密钥调用`GET /api/v2/whoami`（若目标环境已提供该既有路由）及一条有权业务；将owner按原人员流程移到B，复用同密钥再次调用应得到26071；管理登录仍可处理该账号。路由以执行时实际注册表为准，不以示例路径当新增接口承诺。
2. 超管用scope PUT选B、带预期头在`/api/v1/service-accounts`创建B账号；另页改scope到A，旧创建/密钥/授权确认提交拒绝且没有写入。省头的单租户和普通管理员配对检查。
3. A的临时app分别在线/停用，构造受权发布在阶段间迁owner后继续：失败记录、审批执行失败及预览清理符合设计，current/pending/route均不因拒绝改变。
4. 使用迁出owner的新租户会话对临时A app直接请求`actions/stop`、`actions/resume`、PATCH、DELETE及logs/data，均拒绝；源租户有权用户及原超管例外配对，同租户非owner仍拒绝owner-only数据。
5. 用合法持久操作观测既有同版本恢复/清理，检查没有经过新自然人actor路径，也不能用篡改tenant的任务执行另租户app。停止/删除仅限临时对象。
6. 为Root及子租户的临时应用保存旧app/version引用，迁出owner后直接请求publish-status、review-context、snapshot/tree、snapshot/file和两个版本的diff，均拒绝；对同租户owner、合法审批审阅者、无权用户及原super例外做允许/拒绝配对，并断言未调用快照存储读取。预览describe/start/reclaim共享人工边界，后台到期/终态清理仍可执行。
7. 用临时已批准记录验证outbox→source→批准启动，instance/deployment/app/version/tenant任一不符时在stage前拒绝；原有显式失败重试重新读取资格。人工发布页手动上线和actions/manual-publish分别验证，拒绝时v1 migrate/v2部署操作均未调用；旧版本正常恢复不受影响。

具体文件与执行命令已落在tasks.md、task-reviews.md及verification.md；脚本collection不代表真实验收。实施阶段完成本功能真实E2E和L1/L2后才能合入。当前未执行上述路线。

### 7.3 日志与排障

使用现有trace_id及动作审计；资格失败记录reason、credential/service_account或deployment/app引用、当前阶段，不记录Bearer、密钥、环境变量值或完整包内容。owner成员关系故障保留异常堆栈，不能仅转字符串。

拒绝审计不修改资源状态；审批的原执行失败通知保留。UI只有范围变化会清本页状态并要求刷新，租户失配不自动替用户切租户、改owner、重试写请求或停应用。

## 8. 后续改进与交付界限

- 资产移交/迁移另立需求；本功能确认不授权修116资源或恢复人员旧租户。
- 实时数据库查询增加成本，先用单次有界查询和定向测量，不预建版本表、广播系统或全局迁移锁。
- F019共享scope的跨标签页相互影响通过明确展示与预期范围确认处理，不扩为所有管理页改造。
- owner已迁出的旧应用仍可能持续运行而无人能用旧owner身份提交新代码，这是用户明确接受的资源隔离边界，不用管理员冒充owner弥补。
- 无新增系统二进制、部署容器、资源表、数据回填或运行时镜像；交付涉及backend/worker/platform及三语文案同步。密钥发行格式与已存token不变。
- 本稿设计已获单独确认并进入tasks/编码。当前仅完成部分准入和复用消息接线及定向测试，完整功能/真实E2E未完成；未部署、提交或推送，进度和证据分别见tasks.md及task-reviews.md。

## 修订历史

| 日期 | 变更 | 原因/状态 |
|---|---|---|
| 2026-10-28 | 初版设计草案 | 38条AC修订spec已确认；覆盖统一准入、应用边界、冻结发布和管理scope；待设计评审及用户确认 |
| 2026-10-28 | 修订R2-01、R2-02、R2-03 | 补齐发布状态/源码审阅读取、共享ReviewAccess的租户/角色顺序、批准source启动与人工迁移前校验；规格38条AC不变，待复审及用户单独确认 |

实施记录（2026-10-28）：代码及必要定向用例51/53项已完成L1（新增5项均为原范围拆分）。实时绑定、MCP/WS、人工应用边界、冻结发布、管理范围及UI请求均已接线；具体分组证据见verification.md。T047真实E2E及T048最终合入门未完成，不表示已交付。

实施说明：配置确认重建的既有SQLite fixture已补真实发布来源和成员关系；仓储读共享该fixture UoW以避免单连接嵌套BEGIN，不修改生产事务实现。MCP handler兼容用例仅隔离本机既有SDK构造参数差异，不将其作为真实传输验收。

MCP兼容记录：新工具执行准入保留原scope/mode/local-dev可见性拒绝的`PERMISSION_DENIED`工具结果与审计码；新增26071/26072资格错误沿MCP既有BaseErrorCode封装，保留明确原因。

### 2026-10-29 统一管理视角入口

依据用户本次统一租户视角要求，F019 选择器移至平台右上角；模型、工作台、服务账号页的重复选择器移除。全平台(null)与 Root(1)现在可分别选择。切换成功清理查询缓存并重载页面，避免局部 effect 数据和旧表单残留；不修改人员/服务账号/已有应用归属。

服务账号全平台视角支持只读分页列表，并标明每条账号的租户名称。仅全局平台管理员可通过 `X-Service-Account-Tenant: all` 访问列表接口；该范围不能读取账号详情或进入密钥、授权管理，创建及其他写操作仍须选择具体租户。切换到具体租户后，旧的全平台列表请求被拒绝；普通管理员不能使用 all 扩大范围。不改具体租户的 X-Service-Account-Tenant 快照、写入前范围重验、租户可用性和 stale-form 拒绝合同。最后使用时间的 60 秒节流维持，Redis NX 与 TTL 使用一个原子 SET；获取失败不得续期，否则持续调用时会一直停留在首次使用时间。
