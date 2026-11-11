# W4 剩余业务来源接线合同 V1

状态：2026-11-06 冻结供并行实现。基线 `24481f0ca12ce1a1ef666e194356e7620c7f2c0a`，421 卡中 248 项完成。延续已确认 spec 94 AC、R1/R2 与 W3 运行读取合同，不修改需求；本波补 `hosted_app_version/channel_sync/knowledge/model_default` 四类来源的真实增删改、读取及执行接线。

## 1. 全部 Owner 的共同边界

- source 取实际业务根/版本/租户，不接受 HTTP 自报 SourceKey、ownerTenant、receipt、ready 或 identity。原 ContextTenant、actor、OpenAPI/Public principal、credential scope、管理 pin 与 trace 保持；不靠改 ContextTenant、裸 user_id 或 owner 身份换人。
- 同一外部 SQL Session：读旧完整配置与索引 → 全部旧/新 targets 统一锁序 → 真实业务 root/版本/子行 current-read 并重授权 → 旧配置摘要与 set/raw 一致 → 业务保存及 R2 apply → 唯一 commit。新资源可为真实 ID 首次 flush；不得先 commit 业务再补绑定。Repository 不 begin/commit/rollback，读用 no_autoflush；批量 DML 显式可信 tenant/parent 边界。
- 现 `averify_batch_targets` 只支持同 root，不放宽其语义。Core 已实现通用混合来源 API `runtime.aprepare_mixed_source_bindings(session, changes)->tuple[PreparedSourceBindings,...]`，只允许同可信 tenant 的 model_default/knowledge 来源及 MODEL 目标；`SourceBindingChange` 含 source_key/references/extractor_version/lock_source_root/new_source/effective（回调不进 repr/HTTP）。Core 先候选读每个 source，再由新 `verifier.averify_mixed_source_targets` 一次全局纯物理预锁 MODEL server全组→model全组，并逐 source 单独发行原槽/legacy收据；各真实 root 按稳定类型/ID序当前锁并重验，各 guard/source CAS仍独立。同source重复、异tenant、其他target拒10996，任何集合漂移10998整Txn回滚，不在root后追加反序锁。返回按source_type/source_id/source_version规范序，各自root修订独立，不使用单base_root_revision批次。LLM Model Owner/Repository提供 `aprelock_mixed_targets(session,target_keys,source_keys)->None`，仅物理锁；旧同root `_sources` 保持严格。2026-11-06 起默认 Embedding 保存不调用此混合来源 API，不隐式枚举或更改任何空间。
- 新来源即使零引用也建 ready 的完整 source set。existing 来源缺 index/guard、版本不完整、未知 raw 或配置/索引漂移 10994，不在线自动 bootstrap。旧失效同 source/version/slot 原样保留或解除；新 slot/copy/version 仍需合法目标。deleting 冻结写，强删及存量失效证据沿既有协议。
- 按已确认 AC-92，**每个来源完整执行严格检查**，不增加 subset/slot 执行通道，不借 inspect 结果授执行许可。APP 每个版本、频道 current、各默认 key/current、空间 current 分别独立；同一来源尚有失效项不能执行/发布。管理读取可展示失效原 ID，不能静默丢项、sanitize 或换首个有效模型。
- 显式选择知识的新引用沿真实 0/1→library、3→space 和原主体/凭据检查原业务选择条件；旧同槽可逐项修复。不扩文件 edit，不更改 rename，也不新增 use、任务模型绑定或 worker 在途外部 IO 一致性方案。
- 真实双库/FGA/队列/检索/模型服务/E2E/迁移/部署单列，SQLite/SQL 形状不作其证明。所有实现逐卡红绿、单卡至多两个叶子、唯一文件 Owner、固定 SHA 交叉复查后主 agent 合流，无远端 push。

## 2. 来源键与完整提取范围

| 来源 | 固定身份 | 提取 / 生命周期 |
| --- | --- | --- |
| 托管应用 | 实际 App.tenant_id；source_id=App.id；source_version=实际 AppVersion.id UUID | 全部保存版本，不按 current/terminal/approval 状态清关系；原 manifest/capabilities 不改写。真正应用删除后解除所有版本，stop 不解除。版本号 version_no 只是业务编号。 |
| 频道 | 实际 Channel.tenant_id；source_id=Channel.id；version=current | 全部保留同步选项，关闭也保留。主槽 main.space/main.folder，子槽 sub.<sha256(canonical JSON exact rule name)>.space/folder；不 trim/casefold、不用每次替换重建的 sync UUID。相同槽可有多个 target。 |
| 空间/QA/旧库 | 实际 Knowledge.tenant_id；source_id=Knowledge.id；version=current | 当前实体真实 embedding 槽 `model`；存在业务切换时保留明确的 current/pending 模型槽。processing_defaults 目前只有处理规则，没有模型 ID，不扫描任意 JSON。clear 保留，实际删除 SQL finalize 才解除。 |
| 默认模型 | 实际原始存储 tenant；source_id=真实 key；version=current | 五 key 为 knowledge_llm/assistant_llm/evaluation_llm/workflow_llm/linsight_llm。工作台沿 linsight_llm，不能发明 workbench key。Root 继承只维护 Root 原始来源，Child 不复制引用。 |

默认槽：knowledge 的 embedding_model_id/source_model_id/extract_title_model_id/qa_similar_model_id/asr_model_id；assistant 的 auto_llm.model_id 和 llm_list.<modelID>.model_id；evaluation/workflow 的 model_id；linsight_llm 的 models.<ID>.id、linsight_default_model_id、chat_default_model_id、embedding_model.id/asr_model.id/tts_model.id/chat_title_llm.id/image_read_model.id。列表成员槽按真实 ID 稳定，不用数组下标；原配置列表和名字不重写。

## 3. 原生同步读取及权限关系只读 Port（INT 前置）

W3 async 调用和 UserPayload 身份合同不变。以下代码仅列方法名，不是可绕过 Runtime 的执行时序；全部真实 TargetOwner完成且私有target-plan登记后才能revalidate。INT 给同一 source authority 增加原生同步保存来源方法：

```python
scope = verifier.issue_scope(session, SourceReadRequest(...), identity)
snapshot = verifier.get_source_snapshot(session, scope, identity)
verifier.assert_target_keys(session, scope, identity, keys, allowed_types=...)
verifier.revalidate_scope(session, scope, identity)
index = repository.read_source(session, scope, identity, for_update=False)
result = runtime.inspect_source(session, scope, identity)
result = runtime.require_source_valid(session, scope, identity)
```

同步 identity Port 用 `capture`，业务 Owner 用 `resolve_source/revalidate_source`，TargetOwner 用 `inspect_source_targets`。同步/异步 scope 都绑定原对象、原 identity、完整 fingerprint、原 Session/transaction、用途和同 authority 的全部真实 target-plan；跨模式/换事务/clone 拒 10996。不实现同步临时 preview，不把 async DB 工作塞进 asyncio.run、另一个线程 Session 或租户切换。INT 为既有 legacy Reader/Repository 补 native `resolve`，LLM Owner 为两个既有 Model read Owner/Repository 补 native 方法。

原生 FGA 关系读由权限唯一应用边界提供：`get_permission_relation_api_sync().list_resource_ids_sync(subject=PermissionSubject("tenant", id), relation="shared_with", resource_type="llm_server")`。只允许该窄查询，要求 permission_runtime 已 READY，沿当前 pinned store/model 的原生 HTTP `_post_sync`；不初始化另一个 runtime、不绕过 contextual 要求、不把连接/不完整响应当空许可。业务 LLM 模块不得直导 FGA。所有共享读取仍结合真实 Root→Child 继承默认 server SQL；无静态 Root/is_shared 许可。

## 4. APP 声明冻结、版本及最终模型选择

APP 唯一维护纯提取器、同 Session resolver/Repository、SourceOwner/APP 原 principal identity、version/bus/state/preview/entry。LLM 唯一维护同 Session uncached 模型名称解析；INT 维护显式 access/composition、gateway/range 与 filelib 原 principal 透传。

```python
plan = await names.aprepare_model_names_current(
    session, tenant_id, requested_names, identity=identity, frozen_models=frozen_models, range=model_range,
)
refs = await resolve_app_references(
    session, declaration, identity=identity, source_tenant_id=trusted_tenant, model_name_plan=plan,
)
resolved = await names.resolve_model_name_current(
    session, tenant_id, requested, identity=identity, plan=plan, range=model_range,
)
await assert_resolved_model(identity, requested_name=..., resolved_model_id=..., resolved_server_id=...)
```

值DTO明确为 `FrozenModelIdentity(model_id:int, server_id:int)`（正整数，仅物理锁输入）及 `NameResolution(requested:str, resolved:既有ResolvedModel)`；requested_names按精确原字符串去重、字典序，不trim或改名。`resolve_app_references` 显式接 `model_name_plan`，只消费传入的原完整NamePlan，不能另行逐名准备、开Session、cache或补锁；完整模型计划位于KN目标及任何业务root之前。`get_model_name_resolution_port()` 返回LLM进程内同一Port实例，prepare与resolver/最终resolve必须使用该实例消费原Plan，不另造registry。名字 Port 返回既有 model_catalog.ResolvedModel；保持 bare exact 优先（含 slash）、多匹配歧义、qualified 及原可调用范围。prepare 对完整名字候选和冻结模型 ID 的 union 一次 server 全组→model 全组预锁；`PreparedModelNamePlan` 公开只读 tenant_id/requested_names/resolutions，私有保存原 weakref、SessionTxn、原 identity/principal/range、完整候选及 frozen_models。最终 resolve 只能消费该 plan，变更 10998 回滚重算，不在 root 后追加锁。不存在/离线/歧义/范围错误沿原 26511/26512/26514/26515；目录不完整 26516，scope 伪造 10996。不以 60 秒目录缓存作冻结事实。

frozen_models从持久冻结模型ID出发，server_id只可由真实当前模型事实派生或核验hint，目标已删且无server事实时不得猜server来凑DTO，沿原失效/Owner结果明确拒。知识按原数值 ID 优先、否则唯一 exact name，不能解析的历史 name 不编 ID 或假空 ready。slot 由声明语义稳定 hash，不用数组位置。名称后续改名/重名/改指另一 ID 必须失败，不能运行新目标；原不可变 manifest 留原文。

版本插入必须补真实 App 根锁；不是现有 max(version_no)+1 查询就已持锁。targets/名字计划在 App root 前，锁后重核原 authorization_context，再以真实 UUID insert 版本并 R2 一次提交；保既有 approval 失败撤销协议。应用删除完整盘点实际所有版本、全部 set 及全部 raw；缺 set 或未知 raw 在任何资产销毁前拒，stop 不解除。FGA 投影成功在 SQL finalize 前；外部资产销毁沿原持久生命周期，不伪装可 SQL 回滚。

运行身份：APP 原 OpenApiPrincipal 必须是当前认证 Context/连接 scope 中同一个对象，完整核 credential/HostedAppSubject/app/version/运行 route+credential binding 或真实 preview session/operation/viewer/capability/expiry；这些事实在同 Session 读，不调用内开 Session helper 假称原子。不能转为 owner/visitor 的 UserPayload。APP 独立 Runtime/Verifier/Model+Knowledge TargetOwner/Legacy 各实例同 authority；管理/审批预览保原 UserPayload/已发行 qualified authorization，不把 q 当 HTTP 自报许可，也不要求 viewer 等于 capability ceiling。

APP access冻结两个独立factory：运行principal用 `get_hosted_app_reference_runtime()`，身份为AppSourceReadIdentity；用户管理/审批用 `get_hosted_app_user_reference_runtime(authorization_context=None)`；`HostedAppReferenceSourceOwner(repository=None, authorization_context=None)` 为明确构造合同，未改W3 UserPayload identity，SourceOwner绑定原真实qualification并同Session当前重验。INT独占reference_access/composition，各authority必须独立实际Target/Legacy实例；两者不得相互替代。

版本写入发生后台时，在完整NamePlan/R2事务外围保持既有 `RuntimeAuthorizationService.user_context` 活跃，从真实deployment.authorization_context的frozen credential_ref恢复并传其yield的原UserPayload/OpenApiPrincipal。INT在既有 `app_runtime/application/runtime_authorization.py` 导出薄 `user_authorization_context(context,app,*,version_id)`；不从owner/submitted_by造人，锁后再核真实App/required_actions。该既有已验证来源的后台tenant_execution_scope属于可信恢复，必须还原上下文；不是请求自报tenant切换或W3身份放宽。

Gateway 在实际 resolve 后、provider `_instantiate` 前，必须比较 **实际 resolved ID/server、当下 uncached 结果、该 app/UUID 版本冻结 slot ID** 三者一致。filelib hosted retrieval 把原 principal 传 bus；不能仅返回一个名字白名单又自由解析。整个版本 strict，旧 drop 坏知识选项逻辑退出执行链，原 OBO/SAK/PAT、scope/可见性/子项规则保持。

## 5. 频道写入、展示及自动化身份

Channel、全部同步行及 R2 同一 Session，一次提交；同步表无 tenant_id，Repository 必须由真实 Channel parent 锚定，不以为 C3 会自动隔离无 tenant 列的表。候选读不改 ORM；配置替换、create 幂等、initial grants、member/folder/space 校验和 dismiss 只在拥有者编排。

新选目标保原“当前操作者创建的空间”等原业务门槛及真实 folder 属于所选 space；旧同槽失效保留/移除可保存。非数字 folder 不能回退根目录。仅改 filter_rules 而未提交 knowledge_sync 时保留原选项，不因当前不路由而清关系。查询保原 space/folder ID、开关和选项，返回裁剪状态，不伪造目标名称。

```python
prepared = await ChannelSyncExecutionAdmission.prepare(
    identity, channel_id, sync_config_id, detected_at, session=None,
)
```

自动delivery以恢复的同一身份校验当前频道visible，并沿现有add_articles_to_knowledge_space/add_file执行目标原写授权及当前folder→space归属；身份恢复、tenant相等、R2目标合法均不替代资源授权，不扩file edit。手动加文章保持原动作；自动 delivery 先读真实 Channel+sync，恢复真实当前 active user/唯一 active tenant membership/完整角色（可复用 resolve_preview_person 的实际当前身份语义），再核 root/config/header/current tenant、config.user_id 与原恢复对象一致。拒 ambient open/public 或冲突 actor，不清空 Context 降格，不伪造 web_session，也不用裸 user_id 构造空角色 UserPayload。每次执行使用实际快照、is_enabled/规则/时间与目标；旧 sync UUID 已替换则拒该旧队列，不猜新配置。全 channel/current strict 后才副作用。

INT 给普通 UserPayload 来源读图注册 Channel Owner；内部 automation facade 保本次恢复对象与完整环境指纹。KN 独占移除 delete_space/delete_folder/batch_delete 主动 `adelete_by_space_id/adelete_by_folder_ids` 清同步配置的三处调用，保失效选项和引用；CH 不越权修改 KN。

## 6. 空间/QA 独立模型业务配置（KN/INT）

KN 新提取器与外部 Session Repository/应用用例是唯一出向模型绑定写口，接真实 create_knowledge_base/acreate_knowledge_base、QA/space 真删除/clear、旧改 embedding 接口；默认 embedding 仅在空间创建时作为初始选择；原 permission 投影成功顺序不反转。创建模型验证/权限失败不得留下 Knowledge 或引用，索引创建等外部 IO 在 SQL/投影资格之后。metadata 修改不重置模型/索引修订；不改变 file edit/rename。

```python
prepared = await KnowledgeModelReferenceApplication.aprepare_model_change(
    session, knowledge_id, new_model_id, login_user=login_user,
    expected_model_config_revision=None, expected_index_generation=None,
    operation_id=None,
)
await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
```

工作台默认 Embedding 保存只更新 model_default 自身配置/R2。已撤销 aplan_workbench_model_changes / KnowledgeModelChangeBatch / aapply_workbench_model_changes 及整空间清单 Repository；不扫描、锁定、改绑已有空间或派发重建。前台创建读取当时默认并写入独立 model 槽，既有空间继续自身配置；显式改单个空间模型才使用上面的 prepare/apply。

prepare 不 commit/入队/外部 IO，targets 后当前锁该 Knowledge，校验旧 source/index/model 与原动作并冻结结果。该空间业务与 R2 同一调用者事务提交；仅显式空间重建命令在 commit 后派发，重试使用原业务 operation/revision，不能重新切一次模型。默认写没有任务命令。

需要阶段配置时 `model_transition` 仅识别明确 schema_version=1、operation_id、current_model_id、pending_model_id；两模型均为资源业务槽，未知形状拒 10994，不递归猜 ID。current 实际选择 `Knowledge.model`，变更单调推进 model_config_revision/索引 generation，名称/说明不推进。worker 从当前真实业务配置选模型，task 原 model_id 仅兼容校验提示；新派发携业务 operation/revision/generation 期望，缺有效业务或被后续操作替换则在外部 IO 前拒，不能恢复任务历史模型。资源 transition finalize 与 R2 同事务解除旧业务槽；任务本身没有引用。完整分代重建/处理任务框架仍按原任务依赖推进，不把本波接线当成该处理框架完成。

KN 的原 UserPayload 读取沿 W3；内部原生 sync/async 模型消费可用域私有、限真实 Knowledge ID/当前可信 tenant 的 ambient 身份，保原 actor/principal 和 scope，不能造人或作为 HTTP 许可。完整模型绑定/source 当前重验后，RAG/worker 才消费实际配置；外租户不得仅凭内部身份读取。

## 7. 默认保存、继承及读取

```python
await ModelDefaultApplication.asave(session, key, payload, login_user=login_user)
await ModelDefaultApplication.arestore_inheritance(session, key, login_user=login_user)
resolved = await reads.aget_default(key, login_user=None, session=None)
admitted = await reads.arequire_default_slot(key, slot_key, login_user=None, session=None)
# native 同语义 get_default/require_default_slot，不开替代 Session 桥
```

管理 raw getter 返回原配置供修复，不清失效 ID。运行读取全 key/current strict 后才取原 slot；slot 不是 subset 授权。Root 原始配置、Child override 和真实 root→child/share_default_to_children 条件分开；恢复继承只删除叶 override，并将叶 source 更新 inactive 零集合，不改 Root。现无恢复继承 API，本波新增沿 settings 路径/原管理员授权，保原 envelope/五 key alias，不接受任意配置 key。

私有 DefaultReadIdentity 捕获原 ambient tenant/visible/management/actor/OpenAPI/Public/trace，给原 UserPayload 时保持其对象；无 UserPayload 只内部域发行，不伪造个人或浏览器 session。多租户缺 current tenant 拒 10996，显式 tenant 参数只能校验相等而不能补授权；单租户沿 core 默认语义。独立 default Runtime/Verifier/Model Target/Legacy 同 authority，同步异步同根重验，不改 W3 用户身份接口。

所有五 setter、_base_update、set_default_model 均走唯一 writer。自动补默认只取 own 原始配置的真正空槽，不把 Root 继承配置复制成 override，不替换已有失效非空 ID。workbench embedding 更新不读取或修改已有 Knowledge，只保存默认来源。

API 启动取消 linsight_default_model_backfill/chat_default_model_backfill 的自动 DB 转换；未来只能纳入 M3 **停服、备份、正式盘点及冻结 baseline/plan 之后** 的受控转换。脚本不检测停服；本波不运行迁移，也不以 read/write 装配标记全量 Coverage ready。

## 8. 交付与唯一文件责任

APP：app_publish 域上述业务源文件与 app_runtime state/entry；CH：channel 域及原 knowledge_delivery worker；LLM：默认模型业务、同 Session 名称 Port、两个 native Model target 叶；KN/INT：knowledge 域、REF native-sync、权限窄 sync Port、APP access/composition/gateway/filelib、所有生产装配、main 启动及文档。所有 Agent 不写他人热点，新增接缝先登记叶子卡；INT 先交精确接口 checkpoint，消费者再接，fake 不进生产。

三个 W4 worktree从同一冻结合同 checkpoint创建；WF/AS/REF旧 worktree及主工作区不修改，不中途合入其他并发发版线变化。每组先测后实现，依赖具体 SHA，独立 reviewer 固定快照检查，INT 组合回归/架构增量/Ruff/文档完整性后勾选。其余权限消费面、目标删除协调、处理框架、两端 UI、正式回填/Coverage/迁移及完整 E2E 不因本波来源接线自动完成。


### W4接线补充合同

`pending_app_reviews(viewer_user_id,app_id,version_ids,*,session=None,for_update=False)` 及其Repository仅增加复用外部Session当前读，不改变pending任务/真实审批人/应用版本资格或流转；已加载App的原动作由 `app_runtime.application.authorization.authorize_loaded_app(identity,app,operation,*,resume=False)` 导出，避免SourceOwner调用另开Session的load。

Name Port增加 `await assert_plan_current(session,tenant_id,identity=identity,plan=plan,range=model_range)->None`，与resolve同一私有发行/完整目录重验，支持空名称Plan；不能以公开DTO字段当证明。KN名称计划在完整model物理预锁之后、任何source root前锁完整候选name/id+冻结KN集合，私有保存候选manifest；最终普通目录比较及仅已锁ID当前读，变化10998，不root后锁新候选。初始名称范围锁与真实双库隔离行为仍须中央验证；不把SQLite证明为实际gap锁。 同阶段多槽消费使用 resolve_model_names_current(session,tenant_id,identity=identity,plan=plan,range=model_range)->tuple[NameResolution,...]：完整重验一次后返回数据映射，不能把公开返回值当后续阶段的证明。候选/锁后阶段必须各自调用，空名称计划也不跳过身份、事务及共享检查。


### 实施边界补充（2026-11-06）

INT-APP薄Port及APP专属factory(T442/443、T511–516)显式临时转交APP agent唯一写；Root仍拥有总装配/REF/KN/权限/gateway/filelib与集成。APP用户factory采用新的AppManagementSourceReadIdentity：UserPayload委托未改W3，原SAK/PAT Principal沿原actor/credential/mode/授权上下文当前重验；不能把非hosted管理凭据误走hosted token身份或造owner个人。无q的current版本普通执行沿原visible；非current沿management_preview，q仍沿真实资格，inspect沿management_read。start/publish同样完整校验。

频道item级reference_states保原ID；自动化身份私有weakref原对象登记只绑定实际channel/config/tenant/完整指纹，不成为HTTP许可；Facade在同Session核当前DIR/parent及原SPACE会员和upload_file条件，不新增edit。新默认override对Root继承模型资格作前瞻核验，排除将被该own key覆盖的继承贡献；显式FGA共享或其他仍继承key可用，旧原槽保留/解除沿原规则，不允许保存即失效的新引用。

`SourceRootKey(tenant_id,source_type,source_id)`只用于真实根的完整set/raw盘点，不带假版本。既有root inventory方法接受该Root identity并strict当前tenant；零保存版本且set/raw为空的草稿根可沿原删除，任何未知残留先10994，不编current/app.id为版本。


## W4 集成接缝补充（T537–T540）

- 同步知识创建通过 `get_reference_binding_runtime_sync()` 读取与异步 getter 同一个显式注册对象，无 I/O、无懒装配、未注册 10994。SQL 与 R2 仍借原同步 Session。
- 知识 transition 当前槽 `model` 等于实际 `Knowledge.model=A`；building 时只新增 `model_transition.pending_model_id=B` 槽，current_model_id 必须等于 A。worker 从该业务 pending 读取 B，finalize 才将 model=B 并清 transition，与引用更新同事务；processing_defaults 无模型字段。
- 已删应用的 runtime-manager 清理读取仅允许实际同 node assignment 的 active_operation_id 绑定未终止、未过期的真实 destroy/purge intent，或既有精确恢复分支 status=timed_out、cleanup_status=pending、failure.reason=operation_timeout（仍须同一完整assignment绑定），完整 app/tenant/node/generation/owner_epoch 匹配；非该清理事实仍拒 application_not_found。不恢复已删业务的源读取、模型调用或凭证，不用客户端 flag 或旧 route 操作替代当前持久销毁事实。普通业务清理完成与 Docker/K8s 实机验收分开记录。
- 原生共享 API 未注册/未 READY 具有稳定 reason=permission_runtime_not_ready，可映射引用覆盖未就绪并保留 cause；READY 之后的 backend/组件/响应故障明确失败，不降为空共享集合。
- CH lane 已冻结，KN T482–T502 转交独立 `118-wave4-kn` 工作树唯一 writer；公共 REF、composition、main、gateway、filelib 与文档仍由 INT 写入。


### Gateway 最终模型身份核验端口（T445–T449）

`HostedAppDeclarationPort.assert_model_binding(principal, requested: str, resolved: ResolvedModel) -> None` 为 async。APP 在原 adapter/bus 叶实现，同 Session whole-source execute 准入后比 frozen 模型slot与实际resolved ID，server 从同 Session LLM真实 frozen-model facts核验；不从名字缓存或已删除目标猜 server。Gateway 在旧 resolve_range_and_subject（头/访问token优先顺序不变）与 resolve_model_name 之后、`_instantiate` 前通过原注册port调用。返回 None 才完成；原 ModelFaceError 保留，10994映射26516，其他引用无效/漂移映射26513，未知故障26516并保cause。非hosted原路径不变。filelib 的真实文件是 `open_endpoints/api/endpoints/filelib.py`，hosted retrieve 透传原 `principal=principal`，不能只传用户ID/credential ID后再造身份。


### 最终别名与人工修复闭合（T541–T544）

LLM新增 async `resolve_model_alias_current(session, tenant_id, requested, *, identity, plan, range=None) -> ResolvedModel`。只沿原私有NamePlan完整当前校验与已锁目录，用原bare exact优先/qualified规则解析；请求须为原planned模型的bare/qualified alias，结果ID/server仍是原planned结果，不扩大requested_names、不追加锁/另Session/读名称缓存，空plan拒。APP专属runtime显式持有同一 `source_owner`，成功whole-source require后由该Owner私有plan验证请求当前结果、其原语义slot冻结ID及Gateway实际ID/server，不把“属于其他声明槽”误认为同槽一致。泛用DTO和authority不扩展。

知识人工明确改绑修复时，若真实旧收据为INVALID_DELETED/INVALID_LEGACY，或VALID但new_binding_allowed=False，且不处于DELETING，可在业务+R2同事务解除旧A，将实际model=B、transition current=B/pending=B保operation，完整source只依赖合法B，finalize清stage。普通可执行A→B仍双槽；DELETING保原写冻结。禁止以pending子集执行绕过失效旧槽。embedding类型仅由已验证原收据约束的同Session精确模型/父server列事实读取，不能信req.model_type或裸客户端tenant。


空间创建不能以 skip_hook 永久跳过实际SPACE投影：真实flush资源后以同外部Session完成SPACE投影、creator成员、资源模型来源+R2唯一commit，再沿原initial grants/tag完成既有创建生命周期；普通文档库调用实际library创建投影。批量模型变更的commands显式带实际资源tenant_id与actor_user_id；后者只审计/telemetry，不由裸UID制造授权身份。命令 operation/revision/generation 为业务当前配置事实，worker模型仍从资源pending槽选择；派发在整体SQL提交后，队列失败不伪称业务已回滚。


### 原生共享读取启动与真实检索调用（T546–T552）

API正常已有配置与Celery启动原来都可能只注册lazy F048而从未初始化。两端启动在原生引用读取装配/业务接收前显式await既有get_f048_process_runtime：API沿当前事件循环，Celery用既有持久worker loop run_async_task；仅openfga.enabled时调用，错误明确阻止进入可接收业务就绪路径。原生getter保持只读READY对象，无懒初始化或SQL async/sync桥。

RetrievalEngine在原调用处向KnowledgeRag透传既有self.login_user，保留原身份对象及ambient Open/Public principal/PermissionActor，不从invoke_user_id补造人。标准模型执行仍whole-source strict；命名的清理专用vectorstore构造只消费已授权实际资源或持久删除job冻结manifest的index身份，不调用模型、不能用于标准执行准入。旧FakeEmbeddings清理两处调用转该构造，失效模型不能阻断文件删除；不能仅凭isFake跳过运行源校验。其他无原身份的Root共享调用先逐入口核验真实授权来源，不能用静态is_shared替代C4。


### 批量默认覆盖的提交后资格（T433/T435/T474/T475）

mixed API仅承接MODEL_DEFAULT的有效own override（effective=True）；恢复继承继续走单source既有专用API。该批全部MODEL_DEFAULT.source_id键构成私有prospective排除集：对同批每个KN/default来源的继承资格都排除这些即将不再继承的Root key，辅助模型/服务物理union锁也按该集合计算。逐source收据与legacy证据仍隔离，其他未修改key或显式共享贡献保持。否则旧Root embedding A只因该key获权时，保存override后KN currentA/pendingB会立即失效并阻断自身worker；统一prospective资格让其原槽得到new_binding_allowed=False，再由已冻结人工明确改绑修复分支解除A，业务和R2仍一次提交。不得以异步竞态排除此确定提交后状态。

DefaultRead facade追加 `require_default(key,login_user=None,session=None)` / async `arequire_default`，业务原五getter默认全key strict，router管理raw独立读；真实无源返回明确空schema，已有own '{}'需ready零集合。whole/slot结果取Core已准入snapshot payload，不能准入新B后返回先前raw A。


### 删除/finalize事务与后台身份（T553–T562）

KN出向delete/clear及transition finalize由同域Application+Repository在业务外Session实施：目标plan→root/current业务摘要→原投影成功→files/QA/资源SQL+R2同事务，clear保模型引用，实际删除才解除出向；不称完整入向R3协调器完成。finalize只认当前资源operation/revision/generation，不恢复job模型。

`core.context.background_execution.get_current_background_task()`返回内部只读 `BackgroundTaskContext(tenant_id,task_id,task_name)` 或None；后台proof来自真实Celery task_prerun的显式合法tenant header、request.id及called_directly=False，postrun原上下文回收。普通tenant_execution_scope数值不是worker证明，也不改变原C3 header/跨租户行为。502后台命令验证只接受此同对象/当前tenant后台上下文，跨task/退出后失效；普通内部模型配置消费与数据权限边界按下节，不从invoke_user_id补人。不得将客户端元数据当后台permit。缺tenant仍failclosed且默认配置两adapter将NoTenantContextError按已签合同转10996，保cause，不回退Root。


### 内部模型配置消费与数据权限边界

KnowledgeModelReadRuntime是内部配置消费门面，不是知识数据读取API。其dedicated graph始终由私有port包装实际own Knowledge/当前tenant、原User（若有）/actor/Open/Public原对象、完整fingerprint及原SessionTxn；只做业务配置、完整模型引用和资格的当前校验，不重复叠KN.visible。否则已确认的AS knowledge_auth=False及WF绑定库检索会被额外授权改变。数据权限继续由原AS/WF/检索与文件过滤负责，不造User、不从invoke UID授权，不接受外租户/客户端模型替代配置。无User/actor的合法同步内部RAG可消费实际同tenant配置，缺可信tenant仍拒；后台命令另须实际worker证明。Generic用户SourceOwner/状态查询保原UserPayload+visible，私有model port拒inspect，不成为HTTP执行许可。该方案不新增跨域父来源委托框架。

### Saved管理观察和最终默认写返回（T563–T574）

`ainspect_model_names_current(session,tenant_id,requested tuple,*,identity)`返回每项ModelNameInspection(requested,resolved|None,status=valid/unresolvable/ambiguous/offline)，完整uncached批次、原bare/qualified规则，只读无锁/prepare/cache/执行authority；IO/权限故障明确失败。APP `inspect_saved_capabilities(app_id,version_id,identity,*,session=None)`沿真实UUID/Core inspect/frozen ID与该findings比较，保存原ID/label逐行标失效/not_ready，不catch成[]；draft预检不造来源。普通SAK/PAT inspect允许context=None的原principal当前credential+management_read，不伪造RuntimeAuthorizationContext；execute/start/publish保持原严格上下文。

`ModelDefaultSaveResult(config,embedding_changed=False)` 从实际 old effective 配置生成。默认 application.asave 与 Service 外部 Session 均支持原事务回滚，不再有 asave_with_commands、命令派发或 workbench_model_change_requires_command_owner 拒绝。LLMService ownSession 沿原 provider probe→唯一 commit；embedding_changed 只控制默认模型变更探测，不代表空间发生改变。更换、清空默认及恢复继承均不修改既有空间或引用。

### 辅助锁与删除清理读取（T500/T575–T576）

混合批次的所有模型均为 own，或者完整模型 union 为空时，仍由模型 Target Owner 在 source root 前锁 Root/current Tenant 拓扑；空 union 不能跳过该辅助锁阶段。顺序为模型服务→模型→Tenant→KN/默认业务 root；无关默认 JSON 不作为该 own 资格的读取依赖。SQLite 用例核对发出的语句顺序，真实 MySQL/DM8 并发锁行为仍须中央环境验证。

T500 的 Repository 第二叶专供清理 index 身份核验。清理可读取当前 own Knowledge 的真实 index；持久删除 job 在资源行已消失时，只允许同 tenant 的实际 RUNNING job、当前 lease_token 与未过期租约以及冻结 manifest 的 knowledge/index/collection 全部匹配，再返回持久事实。不能从 caller DTO/isFake 取得执行许可；不调用模型或供应商，也不把完整入向 R3 删除协调器标作完成。T551 把实际领取的 job 交给该读取口。

### 旧重建消息的升级边界（T501/T502）

新重建命令必须具有真实当前 transition/pending 和显式 operation/config_revision/index_generation 期望，并核真实后台身份。旧消息仅带 knowledge_id/modelHint/auditUser，缺期望或业务已无 stage 时，在外部 IO 前明确 10998（缺可信身份为 10996）；不能从任务 model 选型，也不能从当下配置补造该旧消息的操作证明。保留业务、队列及诊断，不偷偷改模型/state。本波不新增 legacy metadata-only finalize 框架；M2 正式盘点该类待执行消息，未来 M3 受控转换或运维按新业务操作恢复，相关升级适配未完成前不称全特性可升级。其他已有合法消费任务仍依既有入口，不一概拒绝所有队列。

### 实际文件/QA清理消费者（T584–T585）

`api/services/knowledge_imp.py` 的 `delete_vector_files`（含 file_worker/原文件删除）和 `delete_vector_data`（QA 删除）也必须消费命名 cleanup 构造，不能沿 FakeEmbeddings 调标准模型准入导致模型失效阻断文件清理。INT 单独拥有此旧叶，仅改这两处构造，保 document_id/file_id 删除过滤、原上游动作/引用保护及投影顺序；copy 等其他执行路径仍 whole-source strict。该补漏不把完整入向 R3 标完成。

### 单租户 C3 有效上下文（T586–T587）

KN 私有模型身份和命名清理统一沿既有 `_resolve_tenant_id`：单租户模式无显式 Context 的合法默认 tenant=1 保留；多租户缺 Context 明确 10996 并保 typed cause，绝不从客户端 ID/参数补租户或跨租户降级。不能以裸 get_current_tenant_id 是否非空额外拒绝单租户内部执行；原对象、业务 own、Session、全源与后台 proof 均保持。

### APP业务类型与worker交接（T588–T591）

通用Knowledge目标0/1/3的生命周期规则不扩大具体APP RetrievalFacade原0/3能力。APP新保存及完整来源execute含QA(type1)时拒绝；历史管理保原ID逐行标unsupported，不改通用KN Owner/历史配置。此前type1仅由fake retrieval证明参数透传的首绿，不是APP支持QA的证据。

KN明确尚未写的T501/T502三叶（专用红测试、两个rebuild worker）转交WORKER独立lane，KN不并改。受控逐文件partial结果按原规则标失败文件，正常步骤完成后finalize B/PUBLISHED；全局异常、过期或准入失败不无条件发布成功/解除pending，保当前业务stage和诊断供后续处理恢复。旧无stage/无期望消息按前节IO前拒绝。T591将旧仅SimpleNamespace/DAO测试迁到真实stage，明确原全局异常强制PUBLISHED行为与新未完成stage保护的差异；不扩完整Processing/外部在途竞态框架。

### 状态查询不继续生成旧消息（T593–T594）

最后调用方盘点确认 Space.info 与旧个人库 status 仍对非 Published 状态派发无期望的三参数 rebuild。查询只保原可见准入、状态/错误提示与阶段诊断，移除该退休副作用，不从 GET 补造新操作/stage/任务命令。显式模型变更由已有事务 Owner 在 commit 后派发7字段；合法重试/恢复由后续任务处理入口承担，不借 visible 查询授予重建能力。已退役个人库恢复仍在spec排除项，不新增自动恢复框架。

独立Linsight进程按同一启动合同补齐：各ScheduleCenterProcess在自身事件循环注册F048上下文后，显式准备READY权限runtime并注册引用composition，再启动心跳/接收任务；关闭OpenFGA仍注册实际读取graph。准备/装配失败直接终止启动，不以模型getter懒装配掩盖入口遗漏。
