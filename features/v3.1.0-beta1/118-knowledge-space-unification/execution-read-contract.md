# W3冻结合同：运行准入与共享来源只读

**状态：V1冻结，2026-11-05。** 基线d52825f9e；需求沿用已确认94AC，不增权限动作、任务模型绑定或worker在途IO治理。接口补足T041/T042/T283/T294/T295，未装配保持10994，不用测试fake填生产依赖。

## 1. 授权边界

来源租户与原请求身份分开：SourceOwner从真实业务配置导出source tenant/type/id/version；原user、PermissionActor、OpenApiPrincipal、credential/data scope、guest/session边界继续负责业务授权和召回过滤。不得修改ContextTenant、重建普通user冒充PAT/SCA，或用请求自报tenant/共享开关读取外tenant。

当前仅llm_server保留Root→Child默认共享写路径；workflow/assistant是LEGACY清理类型，ResourceShareService三个授权adapter未生产装配。新只读合同不恢复业务默认共享，静态Root关系、is_shared、残shared_with不构成ALLOW。合法超管仍须过原凭证收窄；真实share-token仅依其既有授权作inspect，不得提升为execute或preview。public_v3继续使用真实public_execution，而非Source接口自造guest许可。

## 2. 内部DTO与端口（source_contracts.py）

- `SourceReadRequest(source_type, source_id, source_version=None, purpose='execute', inspect_token=None)`。purpose仅execute/inspect；无tenant字段。inspect_token不进repr/日志/HTTP输出，仅inspect允许，由业务Owner在同一外部Session重新核真实ACTIVE token及资源绑定，不能信自报meta_data，沿用现有ACTIVE语义、不另加expire_time规则。
- `AuthorizedSourceSnapshot(source_key, references, extractor_version, configuration_digest, payload_json)`。SourceKey来自真实持久来源；references规范完整；payload_json是不可变canonical JSON文本，configuration_digest是其SHA256。包含业务实际配置，不能只凭引用摘要证明任意画布。不得返回受管ORM。
- `TransientTargetRequest(resource_type, resource_id, payload_json)`和`AuthorizedTransientSnapshot(resource_type, resource_id, owner_tenant_id, references, extractor_version, configuration_digest, payload_json)`。仅workflow实际root edit准入，purpose固定preview，无SourceKey/index/旧槽/legacy保留资格。
- `ReferenceSourceOwnerPort.aresolve_source(session, request, identity)`候选读取并原授权；`arevalidate_source(session, request, identity, expected)`在targets后锁定当前读真实root/version/links、重授权、返回完整快照。
- `ReferenceTransientOwnerPort.aresolve_transient/arevalidate_transient`同理，只对真实root edit与实际临时payload，不能把source_version伪造成preview。
- `SourceReadIdentityPort.acapture(identity) -> ReadIdentityFacts(request_tenant_id, fingerprint)`，fingerprint由真实原actor/principal/credential及trace上下文生成，不从HTTP接收。

canonical JSON统一UTF-8、ensure_ascii=False、sort_keys=True、separators=(',',':')、allow_nan=False，DTO验证输入已canonical；configuration_digest=SHA256 UTF-8文本。identity固定为原认证依赖UserPayload对象（不另包业务ctx），Scope身份适配统一读取当前PermissionActor/OpenApiPrincipal/PublicApiPrincipal/credential/trace Context；SessionSubject和execution_snapshot留在实际入口绑定Port，不当作HTTP自报identity。

所有请求/快照构造器校验形状；构造DTO本身不授予权限。payload、token、credential facts不进公开结果或日志。

## 3. 私有scope与只读Runtime

`SourceReadVerifier(owners, identity_port)`真正调用注册的业务Owner，私有登记原scope对象、Owner、完整snapshot、active Session/transaction、原identity对象与完整指纹、当前request tenant、purpose及本次发行nonce。复制/替换字段/换Verifier/跨Session或transaction/换身份或凭证/切tenant/跨purpose重用拒绝。

冻结调用：

```python
scope = await verifier.aissue_scope(session, request, identity)
result = await runtime.ainspect_source(session, scope, identity)       # inspect only
result = await runtime.arequire_source_valid(session, scope, identity) # execute only
scope = await verifier.aissue_transient_scope(session, request, identity)
result = await runtime.arequire_transient_valid(session, scope, identity)
```

`arevalidate_scope`只能由Runtime在真实全部目标读取/锁定完成后调用，须核私有已发行target-plan标记；业务不得在Runtime前单独锁root。各scoped Repository、TargetOwner及legacy入口均显式接`*, identity`，并在bypass前经同SourceReadVerifier核当前身份。每个TargetOwner接其负责的精确目标分组（KN space/file同组），Runtime核完整覆盖、无缺项/重复。

`ReferenceSourceReadRuntime(verifier, repository, target_owners)`对外返回不可变`SourceReferenceReadResult(snapshot,target_states,source_revision,root_revision)`或`TransientReferenceReadResult(snapshot,target_states)`。`ReferenceTargetReadFact(key,state,is_valid,target_tenant_id=None,target_space_id=None)`内部保事实归属，不是R2 receipt；`is_valid`是state==VALID且当前绑定共享资格有效。不能用于R2/入向owner_scope，不能使调用者取得目标grant。

已保存来源读取顺序固定：Owner候选及原授权（不先锁root）→scope限定精确来源索引→按完整target union既定顺序取得当前目标锁/状态→原Owner真实root/version/links current-read并重授权→guard/source/raw refs current-read，比revision/digest/extractor及完整业务configuration_digest→结果。变化10998；缺index/未ready/配置索引漂移10994；scope无效10996。execute/preview拒deleting、deleted、legacy失效及共享撤销；inspect返回状态供业务裁剪。

临时预览另走独立链：原root/edit候选授权 → 从canonical输入提取完整临时targets → 目标当前读及可见/资格准入 → 真实root/edit/current及canonical输入重验 → TransientReferenceReadResult。该链不读取或要求source/index/coverage/legacy，不创建来源或借保存版证据。

来源/目标Repository只读、`no_autoflush`、不add/flush/begin/commit/rollback。跨tenant仅在已发行scope精确tenant/type/id/version和其完整targets条件下短范围bypass，列投影返回不可变facts，避免外tenant实体污染Session identity map。旧R2和owner_query仍严格当前tenant。

实际KN/LLM TargetOwner新增`ainspect_source_targets(session, scope, target_keys, *, identity)`、`ainspect_transient_targets(session, scope, target_keys, *, identity)`，消费同发行authority，不接受裸foreign SourceKey。所有完整targets由scope导出并核一致；目标事实按SourceOwnerTenant核知识归属、model/server及其真实Root共享资格，原请求身份仍用于业务授权/召回。Legacy读取也须同scope限定原source/target/run/key及冻结账本，不借其他来源证据；复用既定冻结阶段和artifact协议。

Runtime公开其已装配`verifier`供业务issue_scope；`get_reference_read_runtime()`为async显式装配getter，未装配10994。API/worker均注册实际SourceOwner/TargetOwner/身份与legacy adapter，不使用宽松默认。

## 4. 工作流准入与common Port

workflow application facade三个入口`prepare_saved(identity,workflow_id,version_id=None,supplied_graph=None,override=None)`、`prepare_preview(identity,workflow_id,graph,version_hint=None)`、`prepare_node_preview(identity,workflow_id,node_data,node_input)`。返回可执行深拷贝graph/node数据，身份仍用原入口提供的完整对象。

workflow业务统一normalize执行图为完整`{nodes,edges}`，保节点/边全部内容及数组顺序，仅排除viewport与外层Flow UI元数据；GraphEngine实际不读这些外层字段。该投影由WF唯一helper定义，Owner与supplied_graph共用。普通WS非current版本仍需原edit，public拒非current hint。

已保存运行由Owner定位真实版本并读取完整payload；有supplied_graph时须与真实执行图一致，不能只比refs。API override先在深拷贝的真实保存图上按现有规则应用：先验证原saved source，非引用参数只在其深拷贝应用，不改scope原payload/digest；提取后references变化明确10996、不入队，需先保存修复或经独立edit preview，不借base source授予新增目标。

`common/interfaces/resource_execution.py`仅声明Port（无全局业务factory），不import domain。`WorkflowExecutionPort.prepare_initial(claimed_flow_id,graph,chat_id,execution_mode=None,version_hint=None)->dict`实例由两个WS端点绑定可信client_id、原identity和是否允许preview；ChatManager.dispatch_client新增optional workflow_execution_port并转交WorkflowClient，两个Owner端点实际注入，缺少时执行前10994；body flow_id不等连接ID拒绝。调用在会话创建、WAITING/Redis数据及enqueue前，保BaseErrorCode业务错误不改500。

wire可选`execution_mode=saved|preview`、`version_id`；它们只是提示，不能自行授权。平台ChatPane可带真实当前version；旧消息与current完整图一致走saved，否则仅普通端点经edit后走临时preview。public禁止preview降级。临时所有知识目标须真实visible、模型按实际归属/共享与既有可用性，不能造来源/index。

各渠道现有ONLINE条件保持：common有chat_id要求ONLINE、无chat_id保既有调试；public先强制ONLINE；v2 RPC原无独立ONLINE检查，不借source层擅加全局限制。saved运行不增加知识个人visible门槛，原knowledge_auth及空间view_file召回过滤保持。

## 5. 助手Agent/缓存/Info

Agent保`invoke_user_id`仅用于既有召回兼容，新增keyword `login_user`及可选`reference_session`。所有生产构造入口传原对象；不得user_id→person fallback。`before_save`局部callback接(session,row)，ONLINE初始化共用原事务，不另开Session、不用skip布尔值。普通RPC/WS由assistant facade开自己的读Session；在锁有效期间从同一业务snapshot取得配置和links，不Guard后独立DAO重读。

每次实际run/stream及缓存复用都核当前source/targets；旧缓存只能用于已核一致配置，变更应重建或明确10998并使下次可重建，不能执行旧配置。HTTP temperature等运行参数覆写与持久配置digest分开。auto_update_llm修复工具不是完整Agent执行，不误加全source门槛。

Info保原model_name及真实有效`knowledge_list`，增`knowledge_ids`保全部原ID、`reference_states[{slot_key,target_type,target_id,state,is_valid}]`供失效展示。新binding资格仍仅内部，不公开`new_binding_allowed`权威字段；is_valid是裁剪后的展示事实，不是权限动作。已删/隐藏目标不伪造name、owner、metadata或tenant/evidence。share-token只inspect，源缺index/漂移10994，不冒充空列表。

## 6. 评测、分工与验证

评测仅现有JWT内部入口，无v2/PAT入口；BackgroundTasks需显式携原login_user并在调度及任务入口核真实evaluation owner/tenant，不凭任意evaluation_id恢复创建者。WF评测执行真实指定version，AS评测用真实当前source；在写Redis/执行模型前经各业务facade。不会给任务新增模型绑定，既有目标业务配置仍为执行来源。

REF唯一拥有scope/verifier/scoped索引与实际target读取/legacy适配；WF拥有workflow SourceOwner/facade/WS/open/node接线；AS拥有assistant SourceOwner/facade/Agent/Info/ChatClient接线；INT拥有公共DTO/access、身份/公共Port/总装配、评测耦合与文档验证。REF不得写WF/AS文件，WF/AS不得修改REF内部发行或其他lane，INT不与Owner并写热点。共同基线提交后独立W3worktree，每卡最多两叶子、红测与实现分提交，依赖精确checkpoint合入。

验证须有真实SQLModel AsyncSession/C3 listener、同源/合法跨源inspect/非授权Root拒、scope伪造/复制/换身份/换事务/换用途、全targets状态与共享撤销、原槽legacy、预览无来源、body换root、reference override拒、缓存失效及发布同事务回滚。跨源facts不能写入identity map或供R2写使用。主agent最终合流组合验证；本地SQLite/SQL形状不等价真实MySQL/DM8/FGA/队列/E2E或迁移。


## 7. 实际接线澄清（2026-11-05）

临时快照payload_json保canonical执行输入原文（graph及可选node_input），不混入客户端无从提供的root字段；实际resource_id/owner_tenant_id及target后的真实root edit/current重授权仍验证。saved快照保graph/root/version完整执行事实。

助手token只授权既有Info查看，来源root候选仍遵原C3可见/pin；真token不新开Root/任意Child源业务bypass。WORKBENCH_CHAT必须读真实MessageSession而非meta.flowId，核chat_id/flow_id/type/未删、tokenTenant=sessionTenant、issuer=sessionUser；用户叶会话tenant不等资源ownerTenant是合法事实。Direct ASSISTANT维持原ACTIVE+实际resource_id映射及原C3范围。已确认旧生成接口未校验资源share动作，原 T404/T405 已按用户决定移出 F118，单列[签发授权独立待办](../../../docs/backlog/share-link-issuance-authorization.md)，不作为本次依赖或验收条件；既有查看绑定/真实来源约束保持，不声称签发端已修，也不修改旧 token 的撤销联动或 expiry 语义。

GET Info填完整knowledge_ids/reference_states；create/update写响应填已知原IDs，reference_states=None表示未执行状态查询；禁止SQL已commit后再inspect失败而向调用者伪称保存失败。

WeakKey/WeakSet的eq=False不足以约束可重载相等性的子类copy；私有登记同时保存weakref并用is确认原发行对象，不改公开授权模型。旧R2相同边界经真实probe复现后同样补核。


## 8. 最终集成接口补充

所有WorkflowClient消息中的flow_id只可缺省为端点绑定ID或等于该ID；check_status直接调用也先核同根再改chat_id/读取会话及Redis。执行Port仍只由业务端点装配，common仅依赖Protocol，不新增domain/API反向依赖。

评测原JWT会话的_runtime_credential_reference为web_session；若存在，kind及整数user_id/home tenant_id/token_version须与原UserPayload一致。管理pin由可信ContextTenant独立决定，不强等JWT homeTenant；拒绝OpenAPI/Public/bypass/非web引用。创建调度与后台入口都核当前具体tenant及真实evaluation owner，每题重新准入真实存储版本再入队，不以首题或预检快照替后续题授权。

ReadLegacyReferenceEvidencePort.aresolve与实际Reader签名一致，显式接session/scope/target/run_id/evidence_key/identity。未装配10994、非法scope/身份10996、实际读取变化10998；这些业务错误在WS中保留原code，不改写500。
