# W6 完成阶段接口合同（2026-11-06）

基线 `2364add1bb80a7fef670d42a99b2833558dc3231`，工作区干净，剩余137张原卡。继续94条AC和既定范围；不合入并发发版线变化。接口按下列子合同分别冻结，未冻结的接口不得由消费者猜测。新增叶子只补原卡真实接缝，不计新产品功能。

## 1. 两端 API 子合同 V1：已冻结

字段权威为现有 `processing_settings.py`、`processing_job.py` 与 contracts.md A1。TypeScript逐字段保留snake_case；数字实体ID/版本为number，日期为ISO string，job/confirmation为string。四类processing precheck用kind判别联合；targets三元组保留真实file/document/version身份，输入document_id允许省略。JobAccepted保留原state/reused，accepted不代表完成。create请求只有idempotency_key/confirmation_id/plan_digest；retry只有idempotency_key/expected_job_revision。

`PageData<T>={data:T[],total:number}` 与目录现有 `CursorPage<T>={data:T[],page_size:number,has_more:boolean,next_cursor:string|null}` 不混用。OperationPrecheck完整镜像已存在DTO，impact暂为 `Readonly<Record<string,unknown>>`，只透传、不据未知子字段推断操作。隐藏项不推导名称/内容，invalid item可无id/type/name。接口错误保留原status_code/status_message/data，不吞异常、无失败fallback。

平台API在现有knowledgeSpace.ts，hooks在controllers/hooks/knowledge.ts；客户端新增api/knowledgeProcessing.ts，保留旧knowledge.ts的2012行原调用兼容，展示types只做消费。不跨两应用导入页面/hooks/store，不新增公共框架/依赖。

API导出 `getSpaceInfo(spaceId)`、`listChildren(spaceId,原query)`、`listAdminSpaces({keyword?,page,page_size})`、`getProcessingSettings(spaceId)`、`updateProcessingSettings(spaceId,ProcessingSettingsWrite)`、`precheckProcessing(spaceId,ProcessingPrecheckRequest)`、`createProcessingJob(spaceId,ProcessingCreateRequest)`、`listProcessingJobs(spaceId,{page,page_size,kind?,state?})`、`getProcessingJob(spaceId,jobId)`、`listProcessingItems(spaceId,jobId,{page,page_size,state?})`、`retryProcessingJob(spaceId,jobId,ProcessingRetryRequest)`。路径严格沿用A1和既有目录路由；平台独有admin能力不在客户端添加管理入口。

缓存键显式包含可信当前身份、tenant、space/job、筛选及普通/admin范围；平台另含managementTenantId。异步mutation捕获发起scope，scope变更后不能写入新scope缓存或复用旧确认计划。默认使用原wrapped axios/request；测试注入同形API port，不设生产mock开关。客户端React-query/Recoil、平台React-query/Zustand保持。T175/T187只交付请求与Mock合同，真实路由尚未装配，T200/T201及后续页面联调仍是独立门禁。

待后续冻结：file-operation五类请求和执行confirmation扩展、R3影响/强删路由、创建模型/默认策略字段。当前不得实现猜测的force/skip协议或新路由。T184模型真实删除在ModelConfig/ModelItem；T185真实来源选择器在selectComponent/knowledge和KnowledgeSelectItem，原任务叶子后续先校正登记。T193平台、T194/T195客户端，单一Owner串行。

## 2. PROC 最小接收/派发子合同 V1：已冻结

T064与T076派发依赖须拆最小前置；确认计划持久应用、job查询/扫描、最新retry actor、当前业务Owner同Session与真实worker尚未闭合。不能以fake Service或未接入helper交付。T074还依赖移动的整版本/对象manifest；元数据与文件旧入口内部commit需显式整合。全部保持文件原edit/rename动作、业务配置读取模型、AC54代际规则，在途外部IO竞态治理仍不在范围。

最小前置T608–T619按下列签名先行，T064补依赖到T613/T611/T609；T619和T617完成真实入口/投递组合后，才算应用用例组合闭合。T076仍是最终多kind派发装配，不以其原后继依赖阻塞最小接收链。全部Repository接外部native AsyncSession，只flush，不自行commit/rollback、不外部IO。

- `OperationPlanRepository.acreate(session, *, operation,space_id,actor_reference,targets,target_revisions,source_revisions,parameters,impact,expires_at)->OperationPrecheck`；`aget_for_execution(session,confirmation_id,*,space_id,operation,actor_reference,plan_digest)->KnowledgeOperationPlan`锁行核tenant/actor/digest/expiry；`aconsume(session,plan_id,*,operation_id,expected_digest)`，同plan只复用原operation。当前版本/模型/索引/来源变更重新确认，precheck不建job、不加业务删除围栏。
- 现有job repo补 `alist_jobs(session,space_id,*,page,page_size,kind?,state?)->JobPage(rows,total)`、`alist_items(session,job_id,*,page,page_size,state?,visible_file_ids)->ItemPage`。固定排序(accepted_at,id)/(file_id,version_id,id)。Service按当前actor批量解析文件visible，隐藏项不返回ID/名称/文本，只汇总hidden_item_count和状态。不能先泄露全部items再在HTTP层裁剪。
- `alatest_retry_actor(session,job_id)`取最新accepted retry receipt，否则原job actor；`adispatch_candidates(session,*,now,after_id?,limit=200)`仅具体tenant扫描accepted pending或running过期lease；`arecord_dispatch(session,job_id,*,expected_revision,published,error_code?,next_at)` CAS不覆盖新retry。broker成功只延后再投时间，pending由有效claim清除。claim增加expected_job_revision可选CAS，旧消息不能接走新retry。
- `capture_processing_actor(identity,*,space_id,required_action,entry_kind)->FrozenProcessingActor`与`restore_processing_actor(reference,*,tenant_id)`异步context manager。web恢复核验真实web_session；API窄出口重验原credential、S/D delegation并与原scope/data_scope相交；不能从audit user_id重造人，不能借写死app:manage/S的恢复上下文。仅存标识与收窄元数据，无bearer/provider秘密。业务模型始终读当前Owner业务配置，不给job新增模型绑定。
- 最小Celery `dispatch_pending_processing_jobs()` / `execute_processing_job(job_id,expected_dispatch_revision)`与Beat/worker装配，headers保可信tenant/proof。消息只job ID/revision，不传模型/actor。Job、items、dispatch intent、consume在同一事务落地；失效状态必须commit后再呈现错误，不能raise导致obsolete回滚。SQL finalize核业务revision/index及租约，当前操作自身切换不得误判为外部改配置。
- 薄 `knowledge/api/endpoints/processing.py`和router装配前移最小precheck/create/query/retry/settings实际入口，路径/DTO严格A1。settings高级/processing按原容器edit、文件rename等原动作保持，可信管理scope不扩到所有普通写入。该前移不等于T124全量通过：T124在KN完备后复核所有真实边界。尚无handler的kind不得接受成永远pending的job或伪造成功；按既有明确错误拒绝直到该kind装配完成。

PROC唯一写上述repo/identity/service/processing worker/薄endpoint，旧worker、metadata、knowledge_imp、moving热文件仍按后续叶子逐一冻结移交。KN业务移动、删除与完整文件处理子合同仍待冻结；不允许本子合同改写其规则。

### 当前业务Owner与自身切换补充 V1：已冻结

T620–T625补`processing_owner.py`与现有`model_reference.py`的最小真实能力。Owner的`aprepare`/`aread_current`使用外部native Session，经现KnowledgeModelReadRuntime核实际当前/待切换业务槽，模型不能从job参数或历史快照回退。显式同模型重建也创建新operation和相关revision/generation；修改工作台默认Embedding仍只影响未来创建。

`afinalize_and_ack(session,job,lease)`核原job lease及业务R/G，调用已有模型finalization/R2，在同事务完成业务切换。Owner只在成功切换后签发进程内私有receipt（对象身份登记，绑定SessionTransaction、jobID、lease token/generation、operation和实际before/after），repo仅消费这个receipt推进job预期修订，随后finalize；不公开可凭before/after参数任意rebase的接口。保留最初accepted审计值，部分失败可在本操作切换后同job重试；用户后续操作/A→B→A仍obsolete。

index_generation是受控业务操作代际。本轮复用原物理索引与model_transition，不要求新物理collection命名/多代staging/双写；全量分页和失败保源仍必须完成。元数据schema CAS与移动manifest待下一子合同，不能复用model revision让无关任务过期。

### 元数据结构CAS存储接缝 V1：已冻结

既有MetadataSchemaParameters.expected_schema_revision为非负整数，实际Knowledge缺对应持久修订。新增仅Owner可写的`Knowledge.metadata_schema_revision`，非空Integer、Python/server default均0，沿服务器私有列排除旧通用响应；既有字段内容不转换。新增结构revision挂当前唯一Alembic head `f118_knowledge_unification`，DDL幂等/双库、无数据循环；不修改已存在revision历史。旧接口字段不强行改名。

后续T072及实际旧metadata服务的add/rename/delete须在锁定空间的同事务核schema revision、持久更新并递增；结构任务确认也绑定该revision。名称、说明、处理默认策略、模型修改不能冒充schema更新；不得用model_config_revision或processing_config_version代替。此存储卡不等于元数据任务/旧入口整合完成，HTTP返回revision与全部写端接线仍由后续精确卡承担。

## 3. 执行与环境边界

### PROC 原始审计、域内收据与真实版本范围补充 V1：已冻结

T636/637给J1新表补accepted_model_config_revision，仅创建时写入实际接受R，cutover/retry永不覆盖；expected_R仍可由本操作合法切换推进。不把审计元数据混入用户parameters。该列可空保留试跑旧结构缺证据事实，正常acreate必须显式写值；缺原始证据的旧试跑任务不得伪造accepted R或用任意rebase继续执行，应明确拒绝所需审计核验。J1首次随F118发布，3005旧版本没有该表，不需要在线回填；结构升级只加nullable列，无数据复制。

T638/639由INT编排下一DDL revision，实际head已验证为f118_metadata_schema。T640/641在knowledge/domain/services/processing_cutover_receipts.py放域内私有收据登记/消费窄协议，Owner引用域能力、Repository引用同域能力，禁止domain反向依赖application。仅同一真实SessionTransaction/JobLease/operation的受控Owner完成实际R2切换后签发、一次消费，伪造dataclass/其他事务或旧lease拒绝；不得以通用before/after函数替代。

T642/643实际版本范围仓储`aload_scope(session,space_id,targets=None,for_update=False)`使用现KnowledgeDocument/Version/KnowledgeFile的真实键JOIN、整版本、稳定file/version顺序、具体tenant，返回Owner manifest所需标量；无Session自开/commit，不在application写SQL。不把仅匹配document_id和space_id的独立列表组合成笛卡尔积，也不把目录主版本误当全部版本。Owner查询/锁后再验均走该实际仓储。

### 两端通用授权子合同 V1：已冻结

平台T630/631只补Catalog模型只读visibility_only_resource_types/visibility_level、Grantable模型visibility_only；客户端T628/629只补Grantable模型只读visibility_only。optional字段兼容既有标准模型/fixture，不加到CatalogChange/GrantMutation请求，不新增可授visible/use动作。

两端grantable列表由服务端核合法性，客户端不从没有actions字段的DTO自行推断空模型是否合法。T192、T194/195与知识页无实际依赖，改为依赖各自API/DTO及真实组件测试；T186的知识页adapter仍等待页面接入。首绿证明现有正确逻辑时不强改实现。测试覆盖pure-visible原level不降、inactive来源仍可撤、REMOVE精确assignee/version、原can_manage/LOCAL/editable/protected及继承边界，撤一个Source保其他Source。T193全员只按服务器all_members_model_key授予、按all_members_sources撤销；app按钮仍逐个独立动作判断。

### 平台高级命令管理头接缝：已冻结

前端managementScope的精确写路径须与已落地后端T221相同：PUT单空间processing-settings；POST单空间processing-jobs、processing-jobs/precheck、processing-jobs/{job_id}/retry。复用原request snapshot和X-Management-Tenant，不变更authority来源/response guard；GET、普通文件上传/rename/move/delete及v2机器调用不新增网页管理头要求。此接缝由INT独写，不占两端API lane文件。

INT统一合同、任务、locale、共享装配与合流；各lane从冻结提交建立独立worktree，只写登记叶子。测试先提交，再实现，已有正确行为如实记首绿。禁止repo-wide stash/reset/clean/无path restore及整文件theirs；不覆盖其他worktree。不push、不自动合入发版线。

用户后续确认109:3005属于中粮定制分支，要求另部署全新标准环境。此前3005仅做只读巡检、零数据或部署写入，现不再用它验证本功能。INT在109另建独立端口、网络、数据库及卷，使用标准版本源码；同机其他部署不得改动。凭据不入仓库/报告。停服升级须先一致备份再正式盘点冻结，脚本不探测/控制停服。用户已明确本轮免除DM8实测，Model/Repository/DDL继续按C2规范开发和静态复核；实际MySQL、中间件、浏览器E2E及备份恢复需证据，不能用单元测试或HTTP健康替代。上游模型/ETL按用户选择使用专用mock，不声称真实provider验证。

## 4. KN 生命周期、创建与清单子合同 V1：已冻结

T077/078不依赖T064，容器adapter只验证存在/类型/租户和合法已知生命周期，复用现_lifecycle_target；继承/自定义仍统一F048。处理态不等于删除/不可见，不在adapter叠文件edit或父子visible动作。冲突写与检索暂停仍由真实用例T098/T102闭合，不把生命周期放行当作允许冲突写。

T080扩展现create_knowledge_space原参数后增加embedding_model_id:int|None、processing_defaults:ProcessingDefaults|None、web_creation_context:KnowledgeCreationContext|None，复用现KnowledgeCreationPolicy和原R2原生Session创建链。省略新字段与现前台行为相同：工作台默认Embedding仅创建时复制为自身model/ref，处理默认规则不回写历史文件。显式高级字段只能由真实web后台创建资格提供context，并在写前revalidate；保原user身份，管理执行tenant来自可信scope，不能用body tenant/admin标记或强换user tenant冒充。高级创建conditional核X-Management-Tenant，普通简化创建不新增头要求。现policy允许超管/租管及合法CREATE_KNOWLEDGE菜单资格；管理全量清单角色另严格限定，二者不混淆。

CreateReq仅新增可选embedding_model_id正整数、processing_defaults，原字段/响应/审批/安全/标签/配额保持。幂等payload hash包含规范化显式新字段；新行processing_config_version=0，初次PUT再递增。可用模型复用真实Model Owner/共享/类型检查；无合法model、R2失败或配置校验失败不能留半个space/ref/defaults。

普通新增GET /api/v1/knowledge/space/list：keyword?、page_size=20(1..200)、cursor?→PageInfiniteCursorData[KnowledgeSpaceListItemResp]，无page/total。固定update_time DESC,id DESC，cursor绑定实际tenant、原身份及筛选上下文，校验合法键并处理旧NULL时间。SQL仅具体tenant/type3候选seek，每批至多100、每请求至多消费1000候选；以loaded-row F048批量visible筛选，不做全量listObjects/5000上限前置。cursor取最后消费候选，预算耗尽允许空data但has_more且cursor前进；不漏过未消费项，不从子项授权推导root可见。数据连接释放后再做权限IO。

管理员GET /api/v1/knowledge/space/admin/list沿A1：keyword?、page=1、page_size=20(1..200)→PageData[ListItem]。Service list_admin_spaces无客户端tenant参数，核真实超管/所选租管和可信单一具体tenant；Repository COUNT/LIMIT/OFFSET，不按visible/置顶筛成普通清单。只放开既定管理资格，后续各操作仍校验业务限制，copy仍仅创建者。

KnowledgeSpaceListingRepository新增alist_candidates(keyword?,after?,limit)和alist_admin(keyword?,page,page_size)，SQL按C3具体tenant，服务list_visible_spaces负责预算/权限/消费cursor。T080/T082/T647同一KN Owner串行热文件；T649负责已有schema+router接线，静态list/admin路由在动态id之前。T646/T648用真实SQL候选与实际route转发验证。平台普通列表/创建页面消费者尚待后续明确卡接线，不以后台API单测标UI完成。

通用文件操作、R3删除、移动manifest/确认与结果扩展尚待下一子合同；不复用PROC版本三元manifest伪装folder/model，不改变旧null/boolean/url结果形状。T085/T087已识别的假串行依赖待真实计划接缝冻结后重排。

### 重建实际处理器接缝：已冻结

T063/064是可组合接收用例，不得把未装配kind接受成永远pending；T614/615的真实闭环前置增加T065/066。先实现既有rebuild_knowledge_worker.py超过10000的完整分页，失败保ES文本和人工Chunk/metadata；同文件中实际单file处理能力供J1逐item调用，返回实际处理结果，不伪造成功。J1业务Owner负责租约/代际与SQL finalize；旧task入口不伪装成job，也不让整库旧worker自行finalize新job。tenant/proof/原业务模型来源保持当前合同，不新增physical staging、外部CAS或任务模型绑定。

失败保ES必须配合T657/658真实retrieval过滤：在现knowledge_file_visibility_service的空间候选和post_filter路径，按当前SQL真实文件成功状态排除处理中/失败文件，保现F048、primary/显式版本和QA既有语义；只裁检索，不据此禁止目录/预览/下载。不能只清Milvus而让失败ES源继续召回。T066完成依赖此过滤，最后真实API/E2E验证保源可重试、成功项可检索、失败项不可检索。

PROC原ProcessingOwnerRepository允许补受控文件状态写端（原643叶及原测试叶），必须在当前item/job lease、R/G和归属核验之后，同外部native Session按真实file ID/tenant/expected space更新status及已脱敏错误，不调用自commit旧DAO；结果提交与子项终态原子落地。preview/download仍沿原资格。

原Owner增加apreview(session,space_id,*,identity,parameters,operation_id=None,expected_configuration=None)只prepare现ModelReference计划、不apply新业务/R2配置；旧invalid模型显式repair只验新合法目标。JobRepo增加aget_by_request_key(session,kind,idempotency_key,*,lock=False)用于幂等优先检查，但始终重新鉴权，异plan/规范请求/actor不得复用。

T078已知生命周期放行使原adapter测试把COPYING视为非法的断言退休；T650只将该例改为未知/已删除的非法态，保原租户、类型和隐藏断言，不放宽任何权限。

## 5. LLM 目标影响与持久计划核心 V1：已冻结

T111/112移除T104功能串行，依赖T652/T654；T113/114的T110串行待后续sharing/执行合同补齐后再解除。本子合同只交付真实Owner核验、完整影响快照与模型专用确认仓储，不提前改现有llm.py/DAO/sharing/公开路由。

REF在原ReferenceRepository补`alist_inbound_for_owner_page(session,issued_scope,*,after_id=None,limit=200)`：scope必须来自当前真实Owner目标全集/同SQL事务，不能接受HTTP任意target/tenant或无界bypass。按真实reference ID稳定seek，limit严格有界；源集合JOIN完整tenant/type/id/version键，当前有效来源的原绑定状态不被随意裁掉。计数/摘要覆盖全部批次，不能只统计首屏或用独立多列IN拼成笛卡尔积。必要的count/group聚合仍在同受信scope中完成，distinct SourceKey/version与多slot明细数量区分。后续tombstone写入仍须真实持锁Owner receipt，不能从裸ID制造目标租户。

新ModelDeletionRepository接外部native Session，仅flush；服务/模型按已冻结target锁顺序核真实owner tenant和当前具体管理scope。retained模型ID必须全部属于当前server及owner，重复/异服务ID拒绝，server实际全部model集合锁后重取。禁止沿用旧DAO只有server_id/model.id的跨tenant bulk DML；本阶段只做读/锁，无share副作用。

`ModelReferenceService.ainspect_removed_models(session,*,identity,server_id,retained_model_ids,delete_server=False)`先验证原管理员/共享只读规则和真实Model Owner，再核同一完整Coverage证明，最后有界读取精确removed目标的完整入向集合，返回内部不可变inspection：真实targets/revisions、完整inbound_digest、distinct source数量/slot数量分组、coverage_epoch/inventory_hash。六源/含停用但仍有配置的完整tenant inventory缺项、epoch/hash不符或未装配真实Coverage时10994；异常不能当零引用。模型目录按有界tenant批量读取，不按每个slot重复扫。只针对已保存业务配置来源，job/聊天/审计不入表。

内部impact核心不伪造SourceReader或隐藏名称。批量来源名称/版本入口和逐业务读取资格仍待独立接缝，尚无合法展示资格的来源只计restricted数量；不能仅凭APP根visible展示历史私有版本。最终公开影响接口在后续接线前必须补齐真实Reader。

新ModelDeletePlanRepository独立处理model manifest，复用既有KnowledgeOperationPlan存储但space_id=None、operation=model_update_server/model_delete_server；不把模型ID伪装file/space，不改PROC已冻三元manifest。`acreate_model_delete_plan(session,*,operation,actor_reference,command_digest,targets,target_revisions,inbound_digest,coverage_epoch,inventory_hash,expires_at)`及`aget_model_delete_plan_for_execution(session,*,operation,confirmation_id,actor_reference,command_digest,plan_digest)`/同operation consume，只flush，绑定tenant/稳定原身份/全部目标修订/完整影响摘要/到期时间。身份排除trace_id，不持久化bearer、API key或整个服务请求，仅存规范请求hash；最终当前原资格仍重验。更新清单和删服务才是真实HTTP两变体，单/批模型移除是PUT清单差集，不新增伪既有单模型路由。

普通/force执行、原分享prepare→projection→finalize同原生事务、精确公开precheck路径/DTO、批量SourceReader和正式Coverage adapter仍pending。未冻结这些边界前不得改服务清单写入口或声称模型删除已闭合；普通删除任一有效业务引用整次零修改，force只跳已确认引用阻断、保原配置ID与失效绑定的业务规则保持。

模型确认补充：operation显式必填并由create/get/consume一致核验；target_revisions精确覆盖model:<id>和单server:<id>，值由真实Owner事实规范为64hash，不能把裸hash当目标授权。可信身份捕获排trace，仓储拒trace和秘密，不默默吞非法字段。

### 模型确认稳定身份闭集 V1：已冻结

实际LLM PUT/DELETE仅Web租户管理员入口，本轮不引入API凭据或复用PROC恢复框架。T655/T656原两叶修订为闭集：actor顶层必需`tenant_id,actor_user_id,credential_reference,data_scope`，仅可选`management_tenant_id`，未知键拒绝。执行tenant为当前具体tenant；actor ID正int且非bool；data_scope只现常量`all_visible/personal_only`，不收非真实`all`。management pin如有须等当前执行tenant。

credential严格真实Web五字段`kind,user_id,tenant_id,token_version,expires_at`，kind固定web_session；user_id等actor_user_id，home tenant正int保持原值，token_version非负int，expires_at可解析ISO datetime字符串；不接受嵌套dict/list或任意额外键。home不同于执行tenant必须存在明确相同管理pin，是否真实超管/可信pin由上层原身份重验，仓储不发资格。仓储只校形状，不拿expiry字段替代实际登录有效性；当前权限、原凭据和管理scope在公开命令执行时重新核验。create/get/consume及加载校验统一此闭集，拒provider key的所有别名、任意扩展键与trace/body；不靠可绕过的秘密名称黑名单。

## 6. J1 全局失败与仅finalize恢复补充 V1：已冻结

原凭据在claim前或受控步骤失效不能使job永远pending重投。原JobRepo增加afail_attempt(session,job_id,*,expected_job_revision,error_code,lease=None)：可信BG与具体tenant、原revision/lease CAS，锁内读取实际Knowledge R/G；相关配置失配持久obsolete，不信任外来configuration。仍未完成的pending/running项失败、保checkpoint/attempt，成功/obsolete不改，重算实际failed/partial_failed并停止本轮dispatch/lease；不从audit重造身份，不擅自完成模型切换。人工retry用新原凭据重验，保持同job/原冻结scope。

若实际所有items已成功，仅Owner/R2 finalize因凭据或投影故障未提交，job保明确global error且failed。此窄场景允许人工retry重置0个item：仅failed/partial_failed、持久error、所有实际items succeeded、pending/failed为0；succeeded/obsolete终态仍禁止。同job新revision/原身份receipt记item_count=0，成功items/attempt/checkpoint完全不动。新claim后只续原Owner.afinalize_and_ack，仍核真实R/G/operation/acceptedR/新lease；不重跑provider或重置索引。Service详情和retry资格复用同一判断，不能按钮和写端冲突。

T660/661只将retry receipt的ck_kpr_revision里item_count>0放宽为>=0，其他tenant/actor/accepted revision条件保持；业务窄例外由实际Repo/Owner判定，不因DDL放宽就允许任意0项retry。T662/663由INT将结构revision挂实际head f118_processing_acceptance，复用现get_check_constraint与table_exists，识别已有新定义为no-op、仅替已知旧定义、未知定义fail closed。DDL-only，不复制任务数据或改最初接受R。

## 7. MIG 持久账本 V1：已冻结

T159/160实现仅依T011，移除T158假串行；正式M2全平台盘点与冻结总装仍等T158，且全部转换写入前先冻结正式基线。唯一类KnowledgeUnificationRunRepository，外部native AsyncSession，只add/flush，不begin/commit/rollback，不ObjectStore/FGA/网络，不停服检测/控制。无新Model/DDL/HTTP。

所有入口使用当前可信具体tenant+strict_tenant_filter，无tenant/bypass入参；首次create/freeze先精确锁该真实Tenant.id（含停用但保配置者），再锁run。不允许同tenant/同writer另起不同migration run重冻转换后数据；origin=empty_tenant不能冒作migration。结构预检只select现模型列limit0，缺结构失败，不建表/补值。

精确async接口（session首参，除schema外run_id、writer_contract_version为关键字必填）：aschema_precheck(session)；aget(session,*,run_id,writer_contract_version)；aget_or_create(session,*,run_id,writer_contract_version)；afreeze(session,*,run_id,writer_contract_version,baseline_ref,plan_ref)；aadvance(session,*,run_id,writer_contract_version,baseline_hash,plan_hash,expected_phase,next_phase)；acheckpoint(session,*,run_id,writer_contract_version,baseline_hash,plan_hash,expected_phase,checkpoint_key,expected_checkpoint,checkpoint)；afail(session,*,run_id,writer_contract_version,baseline_hash,plan_hash,expected_phase,error_code,error_reason)；aresume(session,*,run_id,writer_contract_version,baseline_hash,plan_hash)。

Descriptor严格{object_key,sha256}，hash小写64hex且列值从descriptor派生，与现legacy Reader同形；key非空、非/绝对路径、非file:、无://URI。ObjectStore上层实际上传返回指针，Repo不验bytes、不存本机路径/signedURL/完整配置/秘密。已冻结相同refs/hash幂等，不同值拒绝且不重置阶段。

阶段preparing仅afreeze进入baseline_frozen，然后converting→backfilling→verifying→verified→completed，不跳阶倒退，completed终态。锁行后核expected_phase/writer/原hash。checkpoint为phase内key，值严格{cursor:str|null,processed_count:int>=0,digest:64hex|null,complete:bool}，expected_checkpoint精确CAS，同值重投幂等、count/complete不倒退，不收任意config。afail保全部refs/hash/业务checkpoint并内部记录failed_from_phase；aresume只同原hash恢复原阶段（pre-freeze只回preparing），不能提交新baseline/目标phase。phase不意味着Coverage ready，source_coverage/verification_report写入与发布须后续真实M4合同，不开放任意dict setter。现错误复用10998/10994。

## 8. 专用mock模型/ETL上游 V1：已冻结

用户选择mock模型/ETL，本轮DM8实测免除；DB/FGA/ES/Milvus/MinIO/队列仍真实，mock只属E2E辅助，不是生产新协议。两叶：test/e2e/helpers/f118_mock_upstreams.py与test/knowledge_unification/test_mock_upstreams_contract.py。helper仅stdlib+现FastAPI/uvicorn，无bisheng/config/DB导入，CLI显式host/port、单worker，独立私有测试网络。测试真实现有SDK/loader+loopback或ASGI，不访问远端。

- POST /v1/embeddings：只f118-embed-8/f118-embed-16，固定真实8/16维、非零有限确定float32；input为str/list[str]。省略/base64编码返回base64 float32，float返回数组；dimensions不匹配400，不静默改变真实维度。响应按真实OpenAI list/data/index/model/usage wire，实际SDK默认base64须解码验证。
- POST /v1/chat/completions：只f118-chat；非stream标准chat.completion，stream为SSE role/content delta→stop→按include_usage发空choices usage帧→[DONE]。支持真实messages/现有可选推理字段，不扩tools/Responses/视觉协议。
- POST /v1/etl4llm/predict：这是mock自选完整ETL配置URL，生产loader不拼路径。实际JSON filename+b64_data:[base64]、mode=partition及原OCR/formula/header/parameters/request_kwargs字段。标准status_code=200与合法text/partition响应，真实Etl4lmLoader须得到非空Document正文；有partitions/text优先级时按真实loader消费，不强塞空partitions造成空结果。txt/md实际走本地loader，ETL调用数0；ETL链用合法小PDF或image样本，保真实MinIO下载，不新增multipart/文件GET。
- GET /healthz；GET /__control/stats返回embedding/chat_nonstream/chat_stream/etl总数、按model+input_sha256及filename+content_sha256的attempts/failed与pending_failure，不存原文/密钥/header。POST /__control/reset清状态；POST /__control/fail-next只kind(embedding/etl)、非空marker、可选embedding模型，一次一个规则、原子只消费一次。Embedding目标marker一次HTTP400标准OpenAI error（避免SDK自动重试吞掉任务失败），ETL目标filename一次503，后续正常；探针不命中规则。

模型保存合法probe会调用hello/Test text等，不以全局调用数不增判断默认Embedding联动。E2E按旧文件输入hash/model分桶，结合实际space.model/ref/revision、job数与真Milvus schema/数据证明未重建。上游合同单测不替代后续真实中间件、HTTP/浏览器和升级恢复。

## 9. KN重建状态接缝 V1：已冻结

完整T083/084上传委托须等T067–T070实际file handler/规则适配，不把新上传伪装embedding重建，不接受永远pending kind。本节先交付AC-51已开始重建时的顺序调用限制，不新增跨请求原子准入/外部IO围栏。

T667/T668新增窄纯函数`require_space_processing_idle(space: Knowledge, *, operation: str) -> None`，仅消费业务已按当前tenant和原动作核过的实际空间；`state=REBUILDING`或非空/非None model_transition明确10999。不得自行授权、推断actor、读FGA或用旧private模型校验器冒充公共状态判断。operation仅固定业务诊断名，不是新的权限动作；其他生命周期继续原用例校验。

T669/T670在原SpaceService的add_file/import_web_link/upload_folder_items及move_items真实入口接此gate，移入/出双方都查实际空间；在原VersionService的link/merge/set_primary接同gate，原版本开关、同空间/MD5、原权限及整版本语义保持。在原动作通过后、fetch/对象/SQL/索引副作用前判断。空folder创建、rename、目录/预览/下载不因这张卡新增阻断；原拒绝照旧。原Chunk/元数据写端由后续精确卡继续接，完整T097/T098保持未完成。

T671/T672在现FileVisibilityService的实际space候选和post-filter读取路径，已核原visible后、检索IO前，对重建态明确10999供调用方说明暂停原因；不把重建误报无权限/零命中，不改变QA和显式历史版本资格。成功态文件裁剪T658继续独立生效。每组先实际红测，消费者用真实SQL/业务调用证明，不以纯helper绿测宣布接线完成；已有正确行为记录首绿。

检索授权补充：原file-visible集合非空即已有对应资格，不新增强制space.visible gate而误拒仅子项可见主体。只有重建态且候选/过滤全空时，可复用既有is_space_visible作原空间可见证明，证明通过才返回暂停；全无权保持原empty/False且不暴露处理状态。ready/QA不增加额外空间资格检查；内部精确tenant root状态读取不作为权限授予。

## 10. 文件实际处理与旧规则接缝 V1：已冻结

T069/T070规则适配前移为T068真实worker前置，不再假串行等worker后做。application/file_processing_adapter.py增加`capture_legacy_processing_overrides(request: FileProcessBase)->ProcessingOverrides`、`resolve_file_processing_snapshot(*,file_name,file_source,system_defaults,space_defaults,space_config_version,batch_overrides=None,file_overrides=None,legacy_split_rule=None)->EffectiveProcessingSnapshot`、`legacy_rule_from_snapshot(snapshot,*,space_id)->FileProcessBase`。原schemas.py在填默认前以私有属性捕获原raw非null显式字段（含每file ExcelRule）；不进wire/model_dump，不把补默认的fields_set当显式。不改变既有字段/默认，输入不原地污染。

新操作system→space→batch→file→现支持能力/专用规则；表格只TableRule，网页保持原separator及overlap=0，音视频显式选择现ASR/local能力，不新增OCR/解析类型。hierarchical等仅沿既有pipeline支持范围处理，不为不支持类型新增能力；结果快照明确实际规则。原已保存完整legacy split_rule是实际配置，规范化后直接保留，不重新套新space默认。修改默认不改历史文件快照或使已接受任务过期。

历史文件的新一轮reprocess/resplit以原完整实际legacy规则为基底，明确提供的batch/file overrides仍按顺序覆盖，再应用原专用规则；省略部分不被后来space默认覆盖。否则会使用户明确选择的新重切分参数无效。同一已接受job的retry则直接使用item.effective_processing，不再合任何新默认或覆盖。该差异由原T069/T070测试与adapter叶补回归，不新增请求协议。

旧表格不限行补充V1已冻结：真实旧renderer对slice_length=None/0/负数表示不限行，不能猜成10或当前空间默认。T690/T691仅增加内部`LegacyTableProcessingRule`（slice_length固定0、legacy_unbounded固定true，其余沿真实旧loader规范后的表头和append规则），EffectiveProcessingSnapshot支持该明确分支；`legacy_rule_from_snapshot`去内部marker回旧ExcelRule(slice_length=0)。新ProcessingDefaults/TableProcessingRule/公开ProcessingOverrides仍严格正数，拒该marker，不增加UI能力。旧3.x明确0/负数经内部`LegacyTableProcessingOverrides/LegacyProcessingOverrides`捕获并合法传递；新请求null仍未指定，已保存完整legacy null则按原实际不限行。最后显式正数覆盖后回普通TableRule；重试原内部实际快照不变。header沿原max((value or1)-1,0)并end>=start的真实语义，已存append_header=None按原false规范0。T692只给两端只读effective snapshot镜像补明确legacy分支，不加入默认/新命令类型或新增页面。

T067/T068在原file_worker.py/knowledge_file_pipeline.py复用真实PipelineConfig(TRANSFORMER)：`prepare_processing_file(file_id,*,space_id,invoke_user_id,kind,processing_snapshot,expected_model_config_revision,expected_index_generation)->PreparedFileProcessing`真实加载/转换为内存docs、count和受控file patch；`write_processing_file(prepared,*,space_id,invoke_user_id,expected_model_config_revision,expected_index_generation)->FileProcessingResult`再验当前业务配置后只替换该file的ES/Milvus。两kind保持独立但复用原重跑原文件pipeline能力，不捏造持久全文源；重切分必须确认会覆盖该版本人工Chunk。禁旧addEmbedding/finally自commit路径、整collection reset、新建File/Version/Grant、大docs入账本或持久本地路径。准备物只在进程内，崩溃按原source+冻结规则重跑，不凭checkpoint假定内存docs还在。

T673/T674在现Owner与ScopeRepo增`apreview_file_processing(session,space_id,*,identity,kind,targets,overrides)->PreparedFileProcessingPlan`和`aprepare_file_processing(session,...,expected_configuration,expected_source_revisions,operation_id)->tuple[NewProcessingItem,...]`，真实当前模型/整版本键/对象来源/元数据与settings，外部native Session、固定锁序、仅flush。item snapshot限`schema_version:1,mode,original_status,effective_processing,source_revision`；source_revision是实际对象位置/MD5/大小/来源/版本及原元数据等相关事实摘要，不含受控status/remark/进度字段以免本操作自变造成过期。无provider/model绑定、signedURL、cache/name/sheet临时字段。split_rule保存legacy可消费完整实际规则；实际对象仍从当前File取并验摘要。

T675/T676/T677/T678在原Service/worker/endpoint实际串联后才装配file_reprocess/file_resplit。现kind+精确targets+parameters.overrides、opaque create和原retry请求足够；impact显式overwrite_manual_chunks/实际指定版本数量并绑定确认摘要，不另加request布尔。当前模型无效明确失败，不回退历史模型。file任务不改空间model/R/G/R2、不调用embedding cutover或整空间retry fence；实际操作绑定目标file/version与源摘要，model R/G仍核验过期。

接收仅原合法可重处理状态2/3/6/7，1/4/5及目标重叠活跃任务冲突；安全状态7只有真实重新安全检测后可成功，不直接改成功。接收同job事务置选中文件5，claim置1，真实成功2/失败3/安全拒绝7。ScopeRepo增`acomplete_processed_file(session,item_lease,*,jobs,outcome)`，真实tenant/归属/版本/源/lease/RG核后只写白名单artifact/status与item，再由调用者commit。afail同事务只把本轮仍拥有的unfinished 5/1置失败，不能动成功、别操作或新代状态。人工retry只失败项回5，保原snapshot和全部成功项；无模型/凭据拒绝不能永远pending。已在途IO竞态仍按原排除范围。

T679/T680仅串联原KnowledgeService save/asave及KnowledgeUtils旧rebuild真实调用者；SpaceService上传调用者由KN后续T084按同adapter接入，PROC不抢其热叶。T070只写schema+adapter两叶，不伪称全旧链完成；完整T068须真实wire组合后才勾选。

旧调用接缝补充：`process_one_file`可加可选内部`processing_rule_request:FileProcessBase|None=None`，save/asave传原请求，在真实file_download已得到实际文件名后才解析分类型规则，不以URL/签名query猜类型或重复下载；每file Excel仅原显式值覆盖，向真实消费者传本地副本，不改原request。实际snapshot可随原split_rule JSON的私有`_effective_processing`保存provenance，无URL/name/model/cache/id，不新增HTTP输入或表列，旧FileProcessBase照常消费扁平实际字段。旧rebuild先核真实File.knowledge_id等原已鉴权请求空间，异空间按原not-found拒绝；真实Root重建或File1/4/5冲突在任何规则/状态/queue副作用前10999，不新增权限动作或补visible。此为原T679/T680实际目标/状态接线，其他旧批量和协议仍由T125/T126等完整兼容卡收口。

空配置单列T683/T684：手动纯rebuild无参与文件仍不可执行；显式改模型的空/全部非参与空间可由原ModelReferenceApplication受控prepare/apply直接完成current新槽/R2、清transition、PUBLISHED和单调R/新逻辑G，不伪造0-item新job或BG proof。必须同时核物理非目录File、Document/Version完整链及无活跃操作，不能凭JOIN返回空认定空空间；有未挂版本或活跃解析明确拒绝。保存仍须目标当前有效与二次确认，公开旧/新入口的真实响应由后续KN合同冻结后接。空metadata修改走实际schema CAS的SQL结果，不能伪造文件任务。

## 11. 全平台权限M2子计划与采集接缝 V1：已冻结

T157/T158纯plan/verify前移不等T120；不复用会检测停服/回填dashboard的旧f048_runtime_source/coordinator，也不调用会拒旧use/自开Session的current_catalog冒原始盘点。此内部核心不等于正式M2采集、实际FGA转换或发行放行。

原两prod叶内定义闭集immutable DTO：PermissionCatalogBaseline含原release全部身份/checksum/required auth、实际environment/store/model/checksum/relations/status pin、旧CatalogAction全部语义、模型原id/key/name/kind/config_scope/level/active/allow_same_level/selected/effective actions/visibility元数据/legacy_source_key。PermissionResourceBaseline含tenant/type/id、原Mode(parent/version/projection/operation)、Grant(id/model/state/version/projection)、原Assignee全部身份/Source定位/投影主体/protected/state/version、原visible-source投影全部字段和id。非terminal投影显式阻断，不擅自归零；不存凭据。

精确纯接口：`build_catalog_retirement_plan(*,run_id,writer_contract_version,before:PermissionCatalogBaseline,target_model_checksum)->CatalogRetirementPlan`；`build_resource_retirement_plan(*,catalog_plan:CatalogRetirementPlan,before:PermissionResourceBaseline)->ResourceRetirementPlan`；`verify_catalog_retirement(*,plan,actual:PermissionCatalogBaseline)->PermissionVerification`；`verify_resource_retirement(*,plan,actual:PermissionResourceBaseline)->PermissionVerification`。canonical SHA256绑定原snapshot、run/writer/pin/目标model checksum；run/hash/checksum错、非use或可见性差异均明确PermissionMigrationBlockedError，不将异常当零差异。

规模补充V1已冻结：增加纯迭代入口`build_resource_retirement_plans(*,catalog_plan:CatalogRetirementPlan,before:Iterable[PermissionResourceBaseline])->Iterator[ResourceRetirementPlan]`及`verify_resource_retirements(*,catalog_plan:CatalogRetirementPlan,plans:Iterable[ResourceRetirementPlan],actual:Iterable[PermissionResourceBaseline])->Iterator[PermissionVerification]`。原single入口包装一项batch保持兼容，正式MIG编排必须用batch。每次batch消费前完整验证同run/hash/目录一次并编译before/after模型key和scope索引一次；每资源Source按grant_id一次分组，前后编译共用，不再N资源重建M目录或G Grant遍历S Source。只在该迭代器栈内复用不可变冻结事实，无全局/跨阶段缓存或持久状态。每资源计划/源/visible/non-use事实仍重算核验、精确对应当前actual，输入长度/身份/目录绑定变化拒绝，未全部验证不能正式冻结或执行转换。原T157测试先记录12资源×27模型×20 Grant×100 Source的12次目录重建/48000次Source访问，再验证目录只一次及Source线性；原两pure叶实现，不新造权限框架。

只退休use；global download及原folder/file scopes、rename/edit/publish/share/owner/manage等所有其他语义保持。use-only或按目标类型退役后动作空的模型，只在有原可见/use provenance的类型记录pure-visible和原合法1..4等级；保持key/active/allow_same_level/Grant/Source，任意非法空模型不合法化。若mixed模型无法在不变更原非use/管理边界前提下转换则block，不猜补。复用现GrantModelSnapshot/model_snapshot_for_target与VisibilityProjectionCompiler检验来源贡献和union，撤一Source保其他Source，inactive/retired不当active。原可见无use者新增使用资格是已确认预期差异，不签新use Source，不展开部门成员。

T681/T682采集仓储接外部native Session，所有只读no_autoflush、具体当前tenant/strict，global catalog原始物理行与真实Auth pin读，不经过新derive_action_release。Grant/Assignee/Mode/VisibleSource按各自真实整型PK独立seek分页(limit1..200)，完整保inactive/retired；Assignee真实父Grant/tenant链核验，悬空/坏归属显式失败，无Cartesian/N+1目录读取。方法`aload_catalog_baseline(session,*,environment)`及`alist_resource_modes/alist_grants/alist_assignees/alist_visible_sources(session,*,after_id=None,limit=200)`；catalog全模型/关联读取按真实ID分批，不以旧5001上限当完整。只读无网络/DDL/业务修改/停服参数。

后续真实FGA采集/投影、六源inventory和artifact adapter另冻结，不提前写大装配。正式global manifest含全部tenant（含停用保配置）、权限/六源artifact hash、数量/零集/原失效证据；plan含权限子plan/目标model checksum及每tenant转换/回填plan hash。先持久MinIO对象读回验hash，再同run冻结每tenant，未全部冻结禁止转换；不形成自身hash环，重跑只读原artifact/不重冻。投影仍durable prepare→所有FGA成功→SQL finalize/checkpoint，既有COMMIT_UNKNOWN恢复和批量限制不改。脚本不检测/控制停服。

## 12. MIG持久artifact最小接缝 V1：已冻结

INT独占T688/T689：`UnificationArtifactStore(storage)`消费现MinioStorage的真实async object_exists/put_object/get_object，固定现持久bucket且不得等tmp_bucket。`aput_canonical(*,run_id,kind,content:bytes)->dict`与`aload_canonical(descriptor,*,run_id,kind)->bytes`不接Session、不写SQL/FGA、不开放HTTP。kind只baseline/plan/permission_catalog/permission_resources/sources/conversion/verification；run_id合法长度64标识。外层canonical UTF8 JSON严格`{schema_version:1,run_id,kind,records:list}`，重复键/NaN/非规范编码拒绝；records由上层闭集DTO投影，禁止业务完整配置/画布/manifest/provider请求/凭据直接dump。每对象≤16MiB，完整大数据靠原分页artifact+manifest组成，不设业务总量上限。

key精确`f118/unification/{run_id}/{kind}/{sha256}.json`，descriptor恰好object_key/sha256。SHA256由canonical bytes计算，不把put返回值当hash；写后实际get读回验canonical bytes/hash，全部通过才返回可冻结指针。已有相同内容幂等；已有损坏同key明确失败，不覆盖原冻结证据；读拒绝错run/kind/hash、路径穿越/绝对路径/URL及额外字段，不生成share link或写tmp生命周期bucket。失败保异常因果、对外只机器reason，不输出payload/credential。所有artifact先上传验证，再在单外部SQL事务按Tenant.id升序切可信scope冻结完整tenant集合，全部成功才commit；不用分批phase冒全局M2已闭合。

## 13. 六来源原始inventory仓储 V1：已冻结

T693/T694仅UnificationInventoryRepository及配对测试两叶；原生AsyncSession、当前具体tenant>0、拒bypass，SELECT全no_autoflush+strict，不开Session/flush/commit，不网络/停服检测或写source ready。值是原始停服盘点事实，不是在线AuthorizedSourceSnapshot或R2授权收据。全局Tenant页读全状态，服务编排切可信tenant后再读该tenant源页；不能接HTTP自报tenant。

同实现叶定义frozen/slots `InventoryPage[T](items:tuple[T,...],next_after:int|str|None)`，真实PK升序seek、默认/max200、limit+1 lookahead，不OFFSET；空集next_after=None，完整消费到None才算盘完。签名均async、session首参：`alist_tenants(after_id:int|None,limit=200)`；`alist_workflow_roots(after_id:str|None,limit=200)`；`alist_workflow_versions(after_id:int|None,limit=200)`；`alist_app_roots(after_id:str|None,limit=200)`；`alist_app_versions(after_id:str|None,limit=200)`；`alist_assistants(after_id:str|None,limit=200)`；`alist_assistant_links(assistant_ids:tuple[str,...],after_id:int|None,limit=200)`；`alist_channels(after_id:str|None,limit=200)`；`alist_channel_syncs(channel_ids:tuple[str,...],after_id:str|None,limit=200)`；`alist_knowledge(after_id:int|None,limit=200)`；`alist_model_defaults(after_id:int|None,limit=200)`；`alist_model_servers(after_id:int|None,limit=200)`；`alist_models(after_id:int|None,limit=200)`。after_id默认None；非法/bool游标、limit或父ID批拒绝且零SQL；父ID批空返空、去重最多200、一次查验完整父集合后整批分页，不逐root/slot重扫。

闭集Row字段依真实Model投影：Tenant(id,parent_tenant_id,status,share_default_to_children)；WorkflowRoot(id,tenant_id,user_id,flow_type,status,is_delete,update_time,data_json)；WorkflowVersion(id,flow_id,tenant_id,flow_type,is_current,is_delete,update_time,data_json)；AppRoot(id,tenant_id,owner_user_id,state,current_version_id,pending_version_id,update_time)；AppVersion(id,app_id,tenant_id由真实父派生,version_no,kind,terminal_state,update_time,capabilities_json)；Assistant(id,tenant_id,user_id,status,is_delete,update_time,model_name原模型ID)；AssistantLink(id,assistant_id,tenant_id,knowledge_id,tool_id,flow_id,update_time)；Channel(id,tenant_id,user_id,is_released,update_time)；ChannelSync(id,channel_id,tenant_id由真实父派生,sub_channel_name,knowledge_space_id,folder_id,is_enabled,user_id,update_time)；Knowledge(id,tenant_id,type,user_id,state,is_released,auth_type,is_shared,model,model_transition_json,model_config_revision,index_generation,index_name,collection_name,processing_config_version,metadata_schema_revision,migration_origin,update_time)；Default(id,tenant_id,key,value原str|None,update_time)；ModelServer/Model复用现CatalogServer/CatalogModel闭集标量列，不读provider config/injections/代码/运行凭据。source原始graph/capabilities/transition JSON规范字符串仅内存、repr=False，default原值保None/空串且repr=False，不在artifact存完整业务配置或prompt。

Root页保零版本/零links，版本及子页不按current/online/enabled/terminal过滤、保原delete/state由后续显式分类。WF SourceKey是Flow.id+真实FlowVersion.id，Flow.data仅镜像不另建Source；APP为App.id+AppVersion UUID。AS/CH为真实root/current，links知识0/None合法零引用，CH停用sync仍引用；knowledge原type0/1/3为配置来源，只有0转3，QA=1保library、退休2只进历史清单不创建活动Source/转换/删除复活；未知type留原事实供后续明确失败。defaults仅实际own五key，不resolve、不复制Root继承。

FlowVersion/AssistantLink使用真实父+tenant+类型键核验，坏父显式报10998，不靠INNER过滤吞掉。APPVersion/ChannelSync无tenant列，正常页经真实父ORM JOIN隔离；另`avalidate_global_orphans(session)->None`只做无payload LIMIT1缺父存在性探针，发现孤儿报机器reason，不读取其他tenant内容。model页核真实server父及tenant相同。模型目录每tenant完整分页一次，不按声明槽重复；Root共享/默认继承名称候选资格及已保存旧名解析仍须后续冻结的真实M2协议，raw全目录不授予跨tenant引用。后续Service只编排分页/既有extractors/精确Target预检与闭集artifact，不写SQL或猜原ID。

孤儿完整性补充（大数据复查后冻结）：`avalidate_global_orphans(session)`只做无tenant列的APPVersion/ChannelSync无payload缺父证明，整个正式盘点调用一次；另`avalidate_tenant_orphans(session)`对当前tenant的AssistantLink作一次LEFT raw父的无payload LIMIT1存在性检查，缺父或父tenant不一致明确失败；仅从合法root批取links不能证明无此类孤儿。后者每tenant一次，不每root/子页重扫；前者正常无孤儿仍可能扫全表，严禁放进tenant循环造成T×全局子表扫描。两方法均保native/no_autoflush/strict/具体tenant要求，无进程缓存/跨事务记忆或跨tenant配置读取；正式Service显式编排global once+tenant once。原T693/694两叶补真实多tenant SQL计数回归与所有原拒绝，未改产品要求。

名称解析原事实补充：KnowledgeRow闭集还包含真实`name:str`，供原APP name-only知识声明在本tenant、type0/3候选中按原名称精确解析。name仅内存建立一次索引，不按slot反复SQL、不改type1/2参与范围、不输出完整业务配置；原T693/694两叶增量补真实同名/foreign/type行及SQL预算测试。没有该字段不得猜一个ID、造missing或绕道逐slot查全表。

## 14. 平台普通清单、创建初值与 scope 子合同 V1：已冻结

先补原T176/T178真实前置，不增加产品能力。`GET /knowledge/space/creation-settings`为静态路由，沿原`KnowledgeCreationPolicy.prepare(login_user)`核原web凭据和创建菜单/角色，不将普通创建改为仅管理员。应用用例`get_space_creation_settings(login_user, *, session)`用外部native Session读取真实`model_default_read`的`aget_default(linsight_llm, login_user=原identity, session=原session)`；这是修复/显示原配置的读取，不调用严格执行准入或先核所有默认模型。返回闭集`{embedding_model:{id:string,name:string}|null,system_defaults:ProcessingDefaults}`，只投影工作台Embedding原ID/名称；保留已失效原ID供显式修复，不回退其他默认、不选第一个模型、不输出provider/其他配置。系统规则复用已有`system_processing_defaults(0)`纯schema投影；0不作资源查询、授权或持久化。此GET零SQL写/无FGA变更/无任务/无模型执行，普通读取不加管理租户写头。

平台API新增`listVisibleSpaces({keyword?,page_size?,cursor?}={}) -> CursorPage<KnowledgeSpaceInfo>`（列表缺详情字段允许省略，不补造计数），`getCreationSettings() -> SpaceCreationSettings`，`createSpace(body:KnowledgeSpaceCreateRequest,expectedManagementTenantId:number|null) -> KnowledgeSpaceInfo & {initial_permission_result?:现原始结果}`。创建body严格镜像现有KnowledgeSpaceCreateReq，使用embedding_model_id/processing_defaults；无tenant/admin/type/旧model别名。任一高级字段非null时，API必须使用发起时捕获的正整数managementTenantId签`X-Management-Tenant`，缺失则拒绝发送；普通简化创建保持原无头路径。后端仍独立重验当前管理scope。无新通用request路由分类，不将所有普通POST空间操作改为管理操作。

hook新增`useKnowledgeVisibleSpaces(scope,queryWithoutCursor,api?)`（useInfiniteQuery，next_cursor保不透明，空data且has_more=true仍可继续）、`useKnowledgeCreationSettings(scope,api?)`、`useCreateKnowledgeSpace(scope,api?)`。query key带原identity/tenant/managementTenant/view和筛选；mutation开始捕获scope及管理tenant，切scope后旧返回不得给新scope写cache、跳转或返回可被新页面消费的成功值；仅成功后失效发起scope列表，失败保原ApiError。测试port扩相同方法，不设生产mock开关。

后续创建表单只在原ID为正整数字符串时转number；失效/非数字默认显示待修复并要求有效显式选择，禁止NaN→null触发默认回退。T178先做受控规则编辑/父级草稿边界，系统初值必须来自此GET；先不改T179旧上传到默认接线完成。T176拆为列表shell、单叶create、detail另卡，T177目录/版本另冻结；locale由INT统一三语提交，不全局替换仍并列的旧selector标签。

## 15. 元数据结构原子准备子合同 V1：已冻结

原T071/T072最终仍须真实J1、worker、旧v1/v2入口与指定版本值更新接线，本节只冻结T699–T702前置；不得以核心helper宣称原两卡或AC-47/49全部完成。现`metadata_schema_revision`与`MetadataSchemaParameters`为权威，无新DDL/kind。QA=1保原独立业务路径，不套SPACE整版本任务。

`MetadataProcessingRepository.aload_scope(session,space_id,*,for_update=False)->MetadataScope`接外部native AsyncSession、具体tenant/strict/no_autoflush，只读或flush、不commit。返回frozen/slots闭集快照：tenant/space、当前schema及schema修订、model R/G、完整物理文件与实际Document/Version三元组、parent、状态、物理source摘要、SQL user_metadata原JSON（repr隐藏）。SPACE实际File集合与全部逻辑链须一致；空JOIN不代表空空间，孤立/跨tenant/重复/目录被版本引用/错误primary/缺主链均明确拒绝。合法空目录允许。所有历史版本含失败/安全拒绝态都保留；1/4/5或重建/COPYING/model_transition、活动metadata任务及同范围处理冲突明确拒绝，不能默默只处理成功文件。SQL查询和集合/primary检查按文件/版本线性编译，无逐版本全扫、无逐slot目录读，无外部IO。

`MetadataProcessingService(repository=None).apreview(session,space_id,parameters:MetadataSchemaParameters)->PreparedMetadataSchema`读取上述scope，生成变更前后schema、n→n+1、精确targets、物理摘要、每item SQL值before/after及参数摘要；取消/preview零写。原Owner先行核原identity和容器edit，本内核不创造新授权入口。内核复用原字段命名/类型/内置字段保护及既有明确错误；批内重复、rename冲突/不存在、delete不存在全部先验再变更，不能返回部分成功。接受同批变更按声明顺序处理，但不接受两个操作触碰同一原/新字段的歧义计划。

SQL原值结构`{field:{field_value,field_type,updated_at}}`与索引的`field→primitive`分开：add使所有历史该field为空（清理残留同名值，不复活上次失败delete的数据），rename保值/类型并更新该field时间，delete移除；其他字段完整保留。新field在SQL缺key即空，不伪造历史值。before/after和变更timestamp接受后固定，重试不能用当前时间重算。纯物理source摘要不含本操作自己修改的user_metadata；其before/after摘要单独校验。

`aaccept(session,prepared)->PreparedMetadataSchema`只消费本实例在同一SessionTransaction签发的plan，锁并重读完整事实/原schema revision及摘要，漂移拒绝；然后CAS更新schema与metadata_schema_revision仅一次、只flush。外部J1/items/consume必须同事务一起落地；任一失败整体回滚，内核不自行提交、不写Model R/G/R2、不改File处理状态、不调用provider/索引。执行/重试未来须核接受后的schema revision及after schema和原Model R/G；不得重复接受递增修订。空scope直接真实SQL变更结果，不造零项异步job；有文件的add同样有索引清空残留步骤，不能仅Root append便称全部成功。

后续真实handler固定要求：逐version Milvus query_iterator分页保pk/vector/完整字段、只改user_metadata并finally close；ES参数化脚本、校验timed_out/failures/conflicts；不重新嵌入、不改Chunk文本/原文件、不limit10000截断。SQL文件值与leased item成功同事务，失败明示并只重试失败项。只对冻结目标范围和可控步骤校验；不新增物理staging、外部在途I/O竞态治理或与业务无关整空间写围栏。完整handler/旧公开确认桥与响应的具体叶子在本前置完成后另冻结，旧公开请求/响应和原授权不由前置helper改写。

## 16. 正式盘点目标物理事实子合同 V1：已冻结

M2不能将现在线bind Owner经tenant过滤后的exists=False当全局物理缺失，否则非法跨tenant会被伪装成invalid_legacy。T703/T704只提供两个业务Owner专用的迁移事实仓储：`knowledge/domain/repositories/unification_target_repository.py:KnowledgeMigrationTargetRepository`与`llm/domain/repositories/migration_target_repository.py:ModelMigrationTargetRepository`，各`ainspect(session,*,source_key:SourceKey,targets:tuple[TargetKey,...])->tuple[对应MigrationTargetFact,...]`。普通在线Owner/receipt协议不改；这些事实既不是R2授权收据也不是失效证据签发，不依赖BRR已有索引、不写Source/ready/tombstone。

外部native AsyncSession，调用前须可信具体tenant、strict、非bypass；source_key.tenant_id须等于原当前tenant。targets空返空、去重保持第一次顺序，每批≤200个唯一精确数字PK；非法类型/游标形状/bool/超批在任何SQL前拒绝。KN只接受knowledge_space/knowledge_file，LLM只接受model，禁止通用字符串目标。查询时只在最窄context内按这些精确PK跨tenant读取闭集标量，退出必恢复原scope；无全表扫描/OFFSET、无逐target查询、无provider/config/业务内容、no_autoflush/零写/无commit或外部IO。多target/parent用批量JOIN或IN，一批查询数只与目标kind有关，不随slot增长。

同叶frozen/slots事实不保存原ORM：Model含key、exists、target_tenant_id、model_type、is_online、server_id、server_exists、server_tenant_id、闭集revision_digest；Knowledge含key、exists、target_tenant_id、knowledge_id、knowledge_type、file_type、space_exists、space_tenant_id、闭集revision_digest。space目标knowledge_id即自身；file目标由真实File.knowledge_id和LEFT父空间派生，DIR可能是原频道的合法文件夹引用，不能一概过滤；type0/1/2/3都返回原type事实。digest只覆盖实际闭集标量及相关update_time/model R/G，不声称等价provider全配置摘要，不在事实中输出后者。

全局真实行存在即exists=True，包括foreign、offline、type2、父不存在或父tenant错误；这些必须保留可区分事实，不能因JOIN/资格条件过滤成missing。只有精确原数字ID在该实体全局不存在才exists=False。目标tenant不属于当前、类型不适用或父关系错误由后续真实迁移Owner资格组合明确拒绝；Root共享/默认继承必须使用原真实sharing证据，不能因全局目录已知便扩大资格。未能唯一解析出原ID的APP名称、离线仅名候选/歧义都不能造target_missing证据，仍待M2显式阻断/原语义解析。正式盘点、名称资格、原始失效证据bootstrap与Coverage转换消费者在后续子合同装配，当前两卡不等于完整T162/T168完成。

## 17. 平台处理默认策略受控草稿子合同 V1：已冻结

原T178仅写RuleFile/RuleTable两现有叶，新增具名受控`DocumentProcessingDefaultsFields`、`TableProcessingDefaultsFields`及各自Draft类型（真实Document/Table规则数字字段为number|null，其余逐字段保原类型）；旧默认export/上传/预览调用保持，禁止复用其清空自动补1000/0/10/1、fileList或逐文件开关进入默认保存。新分支复用既有布局/提示和已done共享InputNumber/Checkbox/Select，无新组件库/视觉规范；不得跨client导入。若共享同一旧render实现，必须同样保证所有新草稿边界，文件≤600行。

完整映射：splitMode→split_mode；chunkSize/chunkOverlap/hierarchyLevel/maxChunkSize→四snake数字；appendTitle→bool append_title；retainImages/forceOcr/enableFormula/pageHeaderFooter→0|1；strategies[].regex/position→有序separator/separator_rule。Table四snake字段直接对应，默认模式不展示逐file设置/预览。默认文档策略保现有PDF专用选项及既有适用范围提示，不能因无fileList全部隐藏；选项执行仍由真实文件能力过滤，不新增解析能力。

新`ProcessingDefaultsEditor.tsx`仅受控`value:ProcessingDefaultsDraft,onChange,disabled?`，统一两份草稿，类型切换不重置隐藏字段；含纯toDraft/validate-and-to-wire函数，只有合法完整schema_version=1的ProcessingDefaults才可保存。数字以InputNumber保持number|null；empty不得coerce到0/默认。所有类型一起校验finite/safeInteger、正数/非负、hierarchy1..6、overlap≤chunk_size、header_start≤header_end（append_header=0也校验）、separator非空且两个数组等长/position合法。不校验未展示类型的错误会构成漏口，不能仅依赖blur。

分隔符补充：上述“非空”指数组至少一项，元素允许已有空字符串（真实字符回退标记），原token/顺序/escape不trim或按译文重写。UI待添加pattern/position须由父草稿保留，非空未添加输入在保存前要求添加或清空，切类型不丢；可放在Draft专有UI字段，to-wire时仅投影真实规则字段。原FileUploadSplitStrategy局部输入及译文label→regex行为不接入默认编辑；默认分支可在Editor同叶复用布局实现受控行，旧上传不改。前端不以JS RegExp验证Python regex，本波不新增正则引擎或后端校验合同。

新`ProcessingDefaultsDialog.tsx`用现get/updateProcessingSettings和scope hooks，收到space_id/scope/open/onOpenChange等原页面props。打开先读服务端有效默认和config_version，不猜初值；编辑保持完整draft与发起scope/config_version，保存整体types提交expected_config_version。不为设置保存建J1、不改变历史文件。成功且scope仍原值才更新已保存状态/关闭；取消、校验失败、CAS/服务器失败不污染服务端旧值，失败不自动关闭；scope变化清除旧草稿并拒迟到成功。原资源edit/后台资格由页面与后端独立控制，Dialog不创造新权限动作。

T705先测两个受控fields→原T178；T706再测父Editor/Dialog→T707两叶。创建Dialog、T176三tab/detail与T179上传后续独立接线，不能以此四组件代替整入口完成。locale由INT唯一Owner：平台继续useTranslation与public/locales，不套skill通用client路径；新键统一knowledge:f118命名空间，原save/cancel/字段名及提示优先复用，新增键需报root三语同步，不修改API errors生成文件。

## 18. APP迁移原名称线性索引子合同 V1：已冻结

`knowledge/application/unification_names.py:UnificationNameIndex(model_catalog:NameCatalog,knowledge_rows:tuple[KnowledgeRow,...])`只编译一次本tenant原名目录；`resolve(requests:tuple[AppReferenceRequest,...])->dict[str,TargetKey]`按原slot返完整结果。它是纯内存解析，不是授权/缺失证明，不查SQL/FGA、不写Source/ready、不变更配置；后续M2生产组合必须由真实`ModelNameResolutionRepository.ainspect_catalog`及原auth pin的sharing读取构造NameCatalog（每tenant一次），不能用全局模型目录或任意共享ID扩大可选范围。相应真实sharing装配仍待下一子合同，当前纯索引不关闭T162。

模型原语义以`ModelNameResolutionPort._resolve`为对照：仅原visible_server_ids内llm，online精确裸名先于provider/name（名称本身可含slash），重复明确ambiguous；无online匹配而原同名eligible offline存在则offline，否则not_found。Root继承/共享候选已由原NameCatalog资格确定，本索引只消费、不补宽；坏provider/tenant链或重复ID目录拒绝。知识仅本tenant type0/3原name精确候选，QA1/退休2不参与普通APP知识名称解析；同名歧义/无候选沿原app_knowledge错误，不能登记invalid_legacy。APP原明确数字ID优先，直接保该ID交物理预检，绝不name fallback；不改原immutable declaration。非法request/重复slot不同含义/目录tenant不一致拒绝，不静默遗漏slot。

编译bare/qualified online、offline及knowledge名字索引均按目录线性一次；后续不同source/slot的lookup不得重新扫描整个Catalog或KN页，不调用原逐name扫描实现。每次resolve仅与请求数/实际同名候选数相关，不使用跨tenant/跨run全局缓存。测试以原NameCatalog+原Port对照优先级/歧义/离线、原APP extractor明确ID与名称边界，并以大量不同名称请求实测目录属性访问预算不随slot×模型增长。源目录/原配置仅内存，结果只slot/TargetKey，名称不额外落公开artifact。

## 19. M2原授权pin与模型共享读取子合同 V1：已冻结

`permission/application/migration_read.py:PinnedMigrationPermissionReader(config:OpenFGAConf,catalog:PermissionCatalogBaseline)`为显式停服操作专用async context manager。进入时使用现`discover_openfga_runtime(expected_model=None,allow_bootstrap=False,required_store_id=原SQL CURRENT授权pin.store_id,required_model_id=原pin.model_id)`验证唯一命名Store及原模型真实checksum；全部匹配原catalog.authorization（ACTIVE及与release的required ID一致）才构造同store/model的原FGAClient。升级前模型允许是已冻结的前驱，不通过普通在线expected新模型/ready gate，不创建/写模型/Store或发heartbeat，不检测/控制停服，不设置全局在线client或HTTP/worker准入。

`aget_shared_server_ids(session,tenant_id)->frozenset[int]`要求已进入reader、外部native事务、具体当前tenant且相等、非bypass，原Root返回空；其他tenant使用完整`stream_list_objects(user='tenant:{id}',relation='shared_with',type='llm_server',consistency='HIGHER_CONSISTENCY')`消费全部NDJSON。每次请求显式原model ID；非法prefix/非规范正整数/流中错误或中断全部失败，不能返回已读前缀或当空共享。每tenant一次，由SourceInventory编排，后续交真实`ModelNameResolutionRepository.ainspect_catalog`核原Root拓扑/默认继承/Provider父链。此读取只说明原sharing事实，不自行授予模型引用资格。

退出必关闭专属client；异常保持cause，旧reader/关闭后拒用；无进程全局缓存、SQL写/flush/commit/BRR/Coverage/授权收据或配置泄露。可为测试替换同形discovery/transport factory，生产默认始终真实现有discovery与FGAClient，不设mock开关。factory结果的store/model也须等于原pin，不接受客户端自行repin；不触碰通用online runtime。T712先测→T713单叶实现，真OpenFGA专项实测与正式M2装配另记。

## 20. 元数据逐版本索引处理子合同 V1：已冻结

先做T714/T715真实native索引handler，再由后续Owner/J1组合接线；未接线前metadata kind保持unavailable，原T071/T072不勾。`worker/knowledge/metadata_worker.py:apply_metadata_index_item(*,knowledge:Knowledge,invoke_user_id:int,file_id:int,affected_fields:tuple[str,...],after_values:dict|None,guard:Callable[[],Awaitable[None]]) -> MetadataIndexResult`为异步内部函数，结果frozen/slots为file_id/milvus_count/es_count。knowledge与file/version归属、after_values及guard必须由后续真实Owner从已接受J1快照及当前业务配置提供，不接受HTTP中的索引名、任意目标或历史模型回退。没有可用guard明确拒绝，任何SQL值写/完成记录均由后续Owner leased completion同事务执行；handler不自开Session/flush/commit、不改File状态或Model R/G/R2。

复用现KnowledgeRag原真实vector/ES初始化，只访问该knowledge原collection/index中document_id=file_id的记录。受影响字段是changes中原名/新名去重集合，以冻结该version的SQL after_values[field].field_value为权威，移除受影响旧键后设置这些字段的确定新值；add无该键即清残留为空。其余user_metadata/完整record字段、pk/vector/Chunk文本/原文件保持。该替换按同一接受快照幂等，ES失败后重试不会丢已rename值或复活残留。

Milvus沿现同步Collection.query_iterator(batch_size=1000,limit=-1,expr精确file,out_fields全部schema字段)，循环至真实EOF，逐批copy+upsert保原pk/vector，核真实upsert_count与该批一致；finally close迭代器，异常/guard拒绝后停止新IO。ES用参数化字段名和值、精确term(document_id)的update_by_query，结果timed_out/failures/version_conflicts或统计不完整均明确失败，cause保留，不把部分索引更新称成功；正常完成返回真实count。ES refresh=True确保完成后的读取可见。无记录的失败/安全态版本可为0，但物理索引缺失或native异常不能吞成0成功。

guard在初始化/每个受控批次写前、ES写前及返回前await；后续将验证原actor、item lease、当前Model R/G、接受后schema revision/after schema和该version物理摘要。外部在途IO与用户修改竞态仍按用户排除，不新增staging/双写/强制回退。单测用真实native方法形状与10001+行分页/故障注入，不冒称真实Milvus环境；正式E2E接线后再实测。原手动Chunk元数据以File业务值为权威只对本次字段变更，不修改其他内容。

## 21. 六来源原事实与引用流实际消费子合同 V1：已冻结

`knowledge/application/unification_sources.py:UnificationSourceInventory(repository=None,*,sharing_reader,model_names_repository=None,knowledge_targets=None,model_targets=None)`默认装配现真实UnificationInventoryRepository、ModelNameResolutionRepository和两个MigrationTargetRepository；sharing_reader须为已进入的PinnedMigrationPermissionReader。`aiter_tenant_source_records(session,*,run_id,writer_contract_version)`是async iterator，要求外部native活跃TX/可信具体tenant/非bypass，run/writer形状沿现ledger。先当前tenant孤儿探针一次；global APP/CH孤儿证明由外层整个run一次，不能放入本tenant iterator循环。没有真实共享读取依赖明确拒绝，测试可替换同形IO边界、生产默认无mock开关。

每tenant一次原sharing读取→一次真实ainspect_catalog→一次KN原名称目录→一次UnificationNameIndex编译，模型/服务商/KN目录不按slot重扫。复用现六extractor版本与真实原形状，WF每真实FlowVersion、APP每真实AppVersion UUID；零版本root只root记录不造current；Flow.data镜像不另Source。AS实际model_name为数字ID，links0/None为零；CH整批≤200根读子页至EOF，disabled sync仍引用；KN0/1/3原模型/transition为来源，2只退休清单；defaults仅本tenant实际own五key，None/空值零引用，不复制Root继承。旧0的引用域名是knowledge_space同ID，SQL/FGA namespace转换仍由后续计划执行。

已删除WF根/版本、AS根、APP根以及KN退休2只产生Retired记录，不猜恢复为有效来源；未删除APP所有历史版本包含rejected/withdrawn，非current WF、下线AS和关闭CH目标均保留。精确已知delete标志外的非法形状明确失败，不静默归成deleted或空配置。未知KN type仍作为明确预检错误，不复活/删除。创建者原ID仅保留，不猜测主体；完整creator存在性、文件/版本/标签/配额等全资源预检由后续外层M2完成，本消费流不冒充整个T162。

闭集frozen/slots输出四类（同一应用叶定义）：RootInventoryRecord(root_key,creator_id,lifecycle,configuration_digest,retained_version_count)；SourceInventoryRecord(source_key,extractor_version,configuration_digest,reference_digest,reference_count,lifecycle)；ReferenceInventoryRecord(source_key,slot_key,target,origin:explicit_id|resolved_name,physical_fact)；RetiredInventoryRecord(root_key,source_key可空,lifecycle,configuration_digest)。lifecycle只原状态/类型/版本等标量元组，不放名称/完整配置。config digest由该原source的完整实际引用业务配置规范JSON计算，原None/空值按各原语义处理；raw graph/capabilities/prompt/transition/default JSON仅内存，不存入record/repr或artifact。每个slot独立record，Source头不塞超大refs数组；后续外层每≤200闭集record/≤16MiB组现sources artifact，完整count/digest校验后才可全租户freeze。

同tenant同TX iterator-local physical事实缓存按TargetKey复用，所有新unique targets按≤200整批精确PK预检，查询数按unique目标数，不按重复slot×来源×目录增长。fact只物理存在/owner/parent/type，不在本流判valid/legacy或写证据：foreign/offline/type2/坏父不变成missing，Root旧数值槽撤共享的原槽provenance与资格分类须后续单独协议。APP原数字ID origin=explicit_id，名称解析origin=resolved_name；名字无候选/歧义/离线无明确原ID仍失败，不从全局同名猜缺失。每源原references经normalize/digest/count完整枚举，保持确定阶段/PK/slot顺序；所有缓存均当前iterator内，不跨tenant/run/事务。

本流仅只读实际SQL/FGA，不上传artifact、不写BRR/SourceSet/legacy/tombstone/Coverage/ready或ledger phase，不启停/探测服务、不做转换；全部依赖实际装配及分页/原extractor/原NameCatalog/physical预检集成后才能勾T716/T717，完整M2、初始回填/资格与CLI另卡。

## 22. 平台三页签与空间创建实际入口子合同 V1：已冻结

T718测试→T719：现knowledgeSpace API增加`updateSpaceBasicInfo(spaceId,{name:string,description:string,is_released:boolean}):Promise<KnowledgeSpaceInfo>`，既有PUT /knowledge/space/{id}；显式投影这三字段，不透传model/defaults/auth/share或其他body键，不新增全局管理头。此原空间用例继续容器edit，文件/文件夹rename仍原rename。现update DTO默认is_released=False，编辑必须先真getSpaceInfo捕获原bool并按原值提交；缺少原bool拒绝保存，不猜false。API及KnowledgeSpaceApi port更新限现单叶≤600行，配对两现测试的literal port fixture同步；无其他请求层或公共鉴权变更。

T720测试→T721：KnowledgeLibraryDialog单叶改为真实SPACE创建/基本信息编辑，新增必需scope:KnowledgeQueryScope及同形api测试口；原open/onOpenChange/onLoadEnd/mode/currentLib和datalist接口可保，后一页内容不充当全局重名证明。create从真实creation-settings取工作台默认ID/系统规则→新ProcessingDefaultsEditor，两类型全校验，发embedding_model_id+processing_defaults，不发旧type0/model/expected_tenant_id。默认ID只有canonical正整数字符串且在现online embedding候选中才可转number；无效已保存原ID/名称显示待手动修复，不选首个候选或null fallback。候选沿原wrapped getModelListApi(/llm)，在Dialog用带当前scope的query key投影原online embedding options，复用ModelSelect视觉，不改无scope旧useModel hook。edit仅名称/说明及原is_released，不展示可改Embedding或调用旧updateKnowledge。真实API错误沿原showApiError，已知本地scope_changed用本地化可读文案；禁止裸内部token入用户提示。

Dialog打开/关闭/换scope/卸载/ABA epoch及初次GET退休沿92e策略；其他活跃同key读取者保共享请求/cache；发出前、返回后及cache await后都重验，旧结果不设置新draft/跳转/关闭新Dialog。保存成功刷新原列表，正常创建/创建后导入可沿原/filelib/:id与/filelib/upload/:id路由；名称和资源资格必须重新从实际API读取，不将window.libname当权威。详情/目录/旧上传默认真正接线仍T177/T179等后续卡，本Dialog完成不代表那些消费者已完成；不改QA创建。原f115测试只document分支迁新scope/body，QA原pin/断言保留。

原T176生产两叶修正为KnowledgePage/index.tsx+KnowledgeFile.tsx（不含detail），由T722测试先行。index用现userContext的已认证user_id/leaf_tenant_id/is_global_super/is_child_admin，超管另用现useAdminScope(enabled=super)的服务器scope_tenant_id，null/失败不回home/leaf；该hook无error字段，refresh失败由原showApiError呈现。非超管仅已知active membership leaf；正整数具体tenant未定时禁数据请求/创建并给重试，不将0/null当全平台。identityKey=user:{user_id}仅缓存分区，保组件epoch和原服务端身份校验；现无auth-session epoch，不读JWT/ws_token/UUR_INFO、不新增认证store/退出流程。scope两tenant字段均可信执行tenant，view为ordinary/admin。

普通“知识空间”、独立QA及仅super或相应tenant admin的“知识空间管理”三tab；其他身份不因owner/manager/部门admin或旧role='admin'进入管理。普通创建仍super/tenantadmin或原create_knowledge菜单，不限制仅管理员。KnowledgeFile(scope,toolbarTarget?)按view分ordinary useKnowledgeVisibleSpaces opaque cursor与admin useKnowledgeAdminSpaces DB page/total；普通空页有has_more继续推进，不能客户端分页/过滤补管理数据，不造has_abnormal或详情统计。列表资源lazy actions与PermissionDialog仅该SPACE列表改knowledge_space，QA仍library；actions=null需真实懒读，不由admin身份补业务动作。scope/view变化重挂列表并退役对话框，不复用旧row确认状态。

verify edit后挂现ProcessingDefaultsDialog和基本信息Dialog，copy/delete/force等未装配能力不挪旧library调用或资格；后续T180–T183实际R3/操作再接。管理清单只扩列举范围，不扩具体资源动作。原file/qa tab key和已有路由可保，新admin key只对合资格身份接受；旧普通标签到新f118.spaces只限当前入口，不全局改仍未统一的selector。新翻译由INT在三语实际locale同批提交，标题严格“知识空间管理”；sidebar统一名后续词条接线由INT登记，不改MainLayout架构。


## 23. 统一列表保留既有异常文件标记与筛选子合同 V1：已冻结

本节补齐§14/§22的兼容遗漏，取代其中“不造has_abnormal”的临时字段限制；不扩展详情统计或文件权限。原F064已上线的文件异常布尔标记、异常筛选继续用于统一空间列表，普通与管理视图一致；QA独立且不受影响。只对已通过空间列表准入的最终返回页提供布尔值，不返回失败文件ID、名称或内容，不按逐文件ACL循环判断。此口径沿F064“库级可见即可知道异常布尔”，不是授予任何文件操作。异常仅有效FILE且status为3/6/7，文件夹及1/4/5不算；foreign tenant文件即使错误指向本空间也不能计入。点击行保持当前已发布行为`/filelib/:id`，不恢复旧预筛；依据原修复提交b1635e9d34及现F064断言，避免把已退休的AC05旧导航重新引入。

两个既有静态列表接口及对应service新增可选`has_abnormal:bool|None=None`，只有True筛异常；False与None同普通全集，cursor context绑定归一后的筛选值，不能复用另一筛选的游标。Repository在SQL名称匹配/seek/limit/count之前加原F064索引支持的相关EXISTS；不得先分页再客户端过滤、扫描全部文件或slot×file连接。仅最终response页≤200 IDs执行一次严格tenant约束的批量异常EXISTS查询，空页不查，列表轻DTO新增`has_abnormal_files:bool=False`。不修改Knowledge表、不造缓存列/新索引、不调用旧DAO新增业务入口；通过既有Repository承接，DB连接在FGA检查前释放。

前端KnowledgeVisibleQuery/KnowledgeAdminQuery与Info仅补真实布尔类型，沿原query key/参数透传，不引入假的前端统计。现KnowledgeFile恢复原FileAbnormalStatusCell与已上线共享Select/trigger内联筛选（原F064设计中的TableHeadEnumFilter已无实际定义，不新造组件），筛选重置各自普通cursor或管理page，在scope/view变更时退休；原文件夹/详情/QA不改。F064测试仅改新必需scope及实际查询hook夹具，保原五个能力断言，并验证普通/管理真实参数及分页重置。T176依赖本节后端+API及新测试，不能因为原DTO暂缺字段删断言来标绿。

T725先两叶repo/service测试→T726 repo/schema；T727一叶API测试→T728 service/endpoint，固定独立审后交T729旧前端测试夹具→T730 API；KnowledgeFile依然原T176两生产叶范围内，T729可同时补现Page测试。T731只执行官方lint:prune生成目标suppression收缩，禁止手改或增加冻结项；若生成无diff则记录验证不制造提交。保C2原生SQLModel，真实MySQL查询预算后续E2E，不将SQLite/native形状测试冒称实库证明。


§23测试接缝：T732仅补原test_kn_list.py catalog fixture的真实KnowledgeFile空表及tenant注册，保持原断言；真实final-page EXISTS不可用mock或缺表fallback绕过。


## 24. 元数据结构Owner/J1与实际消费闭环子合同 V1：已冻结

依赖已合MetadataProcessingService准备核、MetadataProcessingRepository完整链/CAS和native metadata index handler。继续原容器edit、原身份/凭据/tenant、全部真实历史版本，File edit不扩展、不触Model R/G/R2、不创建任务模型绑定、不做在途外部IO竞态治理。元数据只绑定本操作接受后schema revision及完整after-schema摘要，使用J1 parameters/每item snapshot现JSON存储；不新造schema列或以空间处理默认版本代替。全文件接受前范围完整核验只做常数次数；逐item/guard必须精确PK链读取，不能每个Chunk批次重扫全部空间items/版本而形成N²。

### 24.1 接受、配置与空范围

新增application/metadata_owner.py:MetadataProcessingOwner，唯一装配真实MetadataProcessingService、MetadataExecutionRepository和现jobs。`apreview(session,space_id,*,identity,parameters)`重验原identity和空间edit后返回实际core计划及source revisions；`aaccept(session,prepared,*,identity)`消费同一native TX私有计划，执行schema CAS并产真实job参数及NewProcessingItem tuple。业务Owner不得接受HTTP提供的after-schema/after-values/physical indexes。每item snapshot闭集包括schema_version/mode、真实target/parent、source_revision、before/after-values及digest、original_status、受影响字段；参数保存request_parameters、operation/confirmation/plan标识、accepted后schema revision/digest/after-schema/changed_at。源完整摘要/每版本source与values摘要参与precheck→create重验，其他事务/改动/伪造计划拒绝。

ProcessingConfiguration增加optional metadata_schema_revision与metadata_schema_digest（其他kind默认None保持兼容）。metadata的J1 claim/renew/item/retry/finalize必须比较这两个实际当前事实与job中接受后schema证据以及原Model R/G；缺证据不能继续，schema A→B→A仍由递增revision过期。`MetadataExecutionRepository.aread_configuration(session,space_id)`只读真实当前root scalars，保native TX/具体tenant；执行的模型由实际KnowledgeModelReadRuntime按当前原identity准入，不从job历史ID或File split_rule取模型。空范围不需要provider IO。

空空间是合法schema操作：aaccept真实CAS成功后建立kind=metadata_schema_change、items=0的已完成**结构操作记录**，state=succeeded/total=pending=0/finished_at真实提交时刻、无dispatch intent，不构造file_id=0或虚假文件item。现JobAccepted仍返回真实job_id/state=succeeded，区别于非空accepted；这不是把异步索引报成完成。J1只为该kind允许空items，其余kind原非空限制及幂等保持；事务回滚时schema与该记录都消失。新作业不授予模型/文件权限，不能作为迁移或业务引用来源。

### 24.2 精确执行、失败与重试

新增domain/repositories/metadata_execution_repository.py，只用外部native Session、严格tenant且非bypass、无commit/外部IO。`aread_item(session,job,item)`验证真实space/File/Document/Version精确链、原parent/source_digest及File状态2/3/6/7，当前值只允许冻结before或after摘要；目录/孤儿/foreign/移动/手动值漂移拒绝，guard不重扫整个空间。`awrite_values(session,job,item)`在有效租约/配置校验后原File.user_metadata写确定after值，同TX jobs.acomplete_item；不改变File.status、分段/解析规则、Chunk文本、版本或Model R/G。命名/签名内部可窄化但这些真实验证不可跳过，也不能增加通用exclude_job/跳权限参数。

KnowledgeProcessingOwner持有metadata Owner，metadata preview/create/retry走该Owner；其余kind的模型切换/文件恢复完全保持。metadata retry消费最新原actor receipt、原schema证据及实际当前模型，原任务只重排失败item，不加模型重建围栏/重新变更schema。原错误和obsolete必须在真实事务提交，不以raise把已判过期回滚；无效凭据/缺权限不继续下一IO。

新增worker/knowledge/metadata_jobs.py专用async runner，由现processing_jobs._execute_processing_job在确认真实worker proof/当前job kind后分流；不走existing_chunks或file parse逻辑。复用现原actor restoration及jobs leases，消息仍仅jobID/revision。每item真实索引handler受控guard每次恢复原凭据、重验edit/实际模型配置、schema、job+item lease及精确原版本，再提交guard事务后才执行下一IO；不长持SQL连接跨Milvus/ES。handler成功后重新原身份/guard，File值与item成功同事务，真实counts写checkpoint；单item索引错误记该item失败并可继续其他item，部分成功为partial_failed，不假全成功。重投按冻结after值替换幂等，ES失败后可重试；过期/租约丢失停止后续IO并保当前账本结果。全部item完成后真实配置/租约检查finalize，不改变空间published/rebuilding状态或借用rebuild retry fence。

只在runner/Owner/retry与真实API组合通过后，processing endpoint和service available_kinds开放metadata_schema_change；此前继续明确unavailable。T733–T740配对/ASGI→实际Owner/J1→实际Celery函数→native IO形状及失败注入证明，不以孤立helper完成原T071/T072；真实索引服务另E2E。

### 24.3 既有metadata协议桥接

随后T741/T742将原KnowledgeMetadataService的SPACE add/rename/delete接application/metadata_legacy.py真实Owner/J1，QA等原不在统一范围的逻辑保持。原三个路由、请求字段及已有响应字段不改；原已确认操作请求可在服务器同TX准备/接受，不要求旧SDK新增确认字段。原background_tasks参数可保签名但SPACE不再派原无账本BackgroundTask。仅使用原真实UserPayload，不从audit ID复造actor；原容器edit及二次确认UI仍保，原返回Knowledge字段为接受后schema，不声称全部File/index已完成。

响应可加只读processing_job={job_id,state,accepted,completed}指示真实结构操作状态，completed仅state=succeeded；不覆盖原字段。非空返回accepted/之后真实查询；空范围实际SQL完成无file item。相同新协议idempotency沿confirmation/request key；旧无幂等字段请求不猜跨请求同一intent，接受时产生服务器operation key并留账。旧自有Repository.update/commit不能先写schema再补job，整个SPACE桥接同一原native TX一次commit；失败全回滚。接口响应/现端UI提交文案与任务展示继续T183/T124复核，不能用HTTP200当索引成功。原T071先完整链测试，T072在桥接、查询/重试及固定独立复查后才勾。


§24内部依赖澄清：T734 aread_configuration先返回不可变MetadataExecutionConfiguration四个真实事实，T736再显式投影新增optional字段的ProcessingConfiguration；不提前依赖后继base DTO。aread_item返回不可变MetadataExecutionItem；awrite_values(session,job,item,*,lease)内部再次真实jobs._guard_item及四事实校验，失效持久obsolete返回False，File值与item完成同TX。旧桥接存在v1/v2调用与Domain依赖方向，T742后段装配在动笔前继续精确冻结DI/入口叶，禁止从Domain直接import application或拿v2投影UserPayload当新web登录恢复。

## 25. 开放Task mode统一知识准入与有界列表子合同 V1：已冻结

本节只承接原T149/T150，全平台use→visible和type0→3旧ID兼容，不新增任务模型绑定/会话引用、SA/D认证、worker用户权限恢复或RAG兜底。独立只读审已追原submit/config→WorkStation→Linsight持久版本和真实worker白名单；WorkStation原use已由统一façade转visible，worker原无该用户use判断，不为本需求扩展这些生产叶。知识实际执行继续读原业务资源当前模型/索引及原R/G，无配置明确失败，不取历史模型。

T744测试→T745仅现listing repo+SpaceService增加内部kw-only name_only:bool=False，不新增HTTP参数、不改变平台普通keyword语义。True仅在SQL lower(name)字面包含匹配（转义%/_及escape字符），原trim、大小写忽略、具体tenant；候选批次与EOF probe都传相同模式，cursor context绑定该模式。不能先page后客户端过滤、不重新全FGA list5000+内存offset。False现name/description搜索保持，既有has_abnormal与scope/page context保持；只内部True时传新kw以免无关既有port fixture全局变更。

T149先测试→T150仍唯一生产叶task_mode_service.py：check_knowledge_libraries先读原候选并严格原tenant/type，再按实际0/3分组批量visible，0用knowledge_library、3用knowledge_space；QA1、退休2和未知类型仍原拒绝，缺失保持原KnowledgeNotExist。原space槽只3及原Space错误；S/D用原ambient principal和数据范围，不借owner的user_id权限。重复IDs不形成逐ID FGA/modelSQL循环；有界批量沿原读/批查接口，false或缺结果拒绝。

旧knowledge_type='library'和'space'两个列表alias均消费同真实KnowledgeSpaceService.list_visible_spaces(keyword=name,name_only=True,page_size,cursor)，输出仍id/name/description/update_time四字段和原cursor envelope/page上限100。传原Request及原operator，统一服务须使用ambient原S/D actor，不读取管理全量清单；保稀疏空页has_more继续，不混入尚未转换NORMAL或QA。旧offset游标无法匹配新context时明确拒绝，不猜新cursor。F073公开错误约定保持：library的KnowledgeSpaceInvalidCursor窄转换KnowledgeInvalidCursorError(10991)，space仍18070；其他服务/权限/后端错误原样失败，不能吞成空页。公开文档只承诺名称模糊，无通配符/排序算法协议。

T746两叶和T747一叶仅原F073测试夹具适配实际visible结果键/统一Domain consumer；不得删除SA不能借owner、委托缺menu/scope、QA/retired/missing/不可见/异常传播断言。原已正确模型/worker/tenant白名单行为标首绿；T149补真实SQL分页/名称/tenant和原消费路径，不把mock接线等同执行E2E。此Domain调用不经过T126旧CRUD endpoint，因此T150依赖真实名称分页前置与T148，无需等待整T126；T126自身仍未完成，不因此勾选。


### 24.3原metadata桥接分层与双协议装配澄清：已冻结

已rg核所有生产调用：v1 knowledge endpoint与v2 open_endpoints/knowledge皆经KnowledgeService→KnowledgeMetadataService。因此不在Domain import application，也不复制两个API桥接分支。T742在原KnowledgeMetadataService定义窄注入port，SPACE add/rename/delete转交注入writer；writer缺失明确拒绝SPACE写，不回旧无账本路径。QA及其他未统一类型原逻辑保持。T748在knowledge/api/dependencies.py与open_endpoints/api/dependencies.py两个真实入口装配同一application/metadata_legacy.py组合工厂；原KnowledgeService facade不改。v2原工厂曾未传metadata_service，不能仅接v1即称双协议闭环。

writer在application中获取真实ambient OpenApiPrincipal（若有，必须与现上下文对象相同并保原knowledge:write/S-D/data_scope），否则原web UserPayload；此原身份用于capture及Owner，不以v2 persistence/audit投影UserPayload制造web session。space ID只定位真实SQL资源，传入旧knowledge对象不构成CAS或授权证明。全部schema+J1通过Owner自己的同一native TX且一次commit，旧先读Session不能先update/commit业务。v1现有字段保持，可加只读processing_job；v2原data=True保持其既有“接收操作”语义，不改成新的task response或声称索引完成。T741真实DI加v1/v2协议/原身份测试，不只mock三方法即宣称闭环；T072需T748实际装配及T071完整链复核后闭合。


### 24.1空结构操作完成证据澄清：已冻结

T736允许在现jobRepo同叶定义专用私有metadata acceptance authority/receipt，由真实application Owner单向import；不反向import application。只有Owner实际core.aaccept完成CAS后签发的原对象、同native Session/原TX、space/完整after-schema revision+digest/actor reference相符且一次消费，才可把空item的metadata结构操作记为succeeded。禁止仅凭kind+当前schema相等、dict/伪造dataclass、跨事务或重放创建空成功。该能力不泛化成任意before/after签发，不放宽其他kind；失败与schema及操作记录一起回滚，测试覆盖伪造/篡改/错事务/重复及回滚。

## 26. 停服维护中的中性结构准备顺序：已冻结

旧标准a1b基线数据库没有F118新增的Knowledge私有revision/来源列、PermissionModel纯可见元数据列及新账本表；实际新仓储不可在旧schema上直接ORM扫描。运维顺序因此明确为：完成旧任务收尾并停API/worker/所有写入者→一致备份与原schema/revision记录→只运行候选版**中性DDL结构升级**→正式M2全量原业务事实盘点/预检→全租户正式基线+计划freeze→任何M3业务转换/回填或新授权投影。正式基线仍是在停服后冻结，不使用早先准备数据。脚本不探测或控制停服。

中性DDL只允许模型新空表、既有列/索引结构及已冻结server_default填充；不运行default seed、R2回填、Knowledge.type/配额/版本/标签/配置/授权数据转换，不启动新版API/worker/FGA在线模型或把新列默认当新业务事实。原业务字段/ID/模型/索引/对象/授权pin必须保持，M2 artifact记录备份点、原/新schema revision与本次DDL版本摘要；baseline原业务摘要排除新中性字段，显式加入旧业务字段完整核对。DDL失败或非中性数据效果明确失败保持维护，不能把转换后状态冒充正式原基线。

这一区分沿仓库“revision只允许DDL及新增列server_default填充；业务数据迁移独立操作”的既有规则。正式脚本尚未完成前，只说明真实存在的alembic结构升级入口，不伪造inventory/convert命令或将原授权pin只读smoke称正式M2。恢复仍整套一致备份点，不只反改type或删新列。全部演练只在109独立项目，3005不操作，DM8实库免测但C2静态保持。


§25补T749：旧task_mode_personal_skills.py的permitted fixture仍回退休use，而已合UserSkillsService实际请求visible；同选集前驱/当前各两失败由该假结果导致。仅本叶改visible结果并保所有原行为断言，不扩改production Skill/WorkStation。


## 27. 平台真实目录、原文预览与基础文件动作子合同 V1：已冻结

本节是原T177/T179的真实前置小闭环，不代表版本/完整上传/批量删除/移动/高级Paragraphs已完成。实际路由/filelib/:id是detail.tsx，upload是filesUpload.tsx，QA独立qas.tsx。本节不改QA、legacy upload、版本或服务器动作模型；只消费已存在SPACE端点，不借旧/knowledge/process冒充同目录注册，也不把info.actions用于授file动作。

T750先测试→T751 hooks/useKnowledgePageScope.ts+index.tsx只抽取已验证W6§22的原userContext/useAdminScope逻辑。导出named useKnowledgePageScope()，返回{scopes:{ordinary,admin}|null,isLoading:boolean,canManage:boolean,user:Partial<User>|null,retry:()=>Promise<void>}。super仅服务器selected具体tenant、非super active leaf，原actor/home不改；retry保原异常呈现、身份/卸载epoch，ordinary仍reload。isLoading包括原management加载与retry，未定scope不给数据/动作。index三tab/menu/QA/toolbar行为不变，原Page测试全部保留；detail只用ordinary scope/cache分区，不因来自管理列表而新增Grant或绕过具体资源资格。

T752测试→T753新controllers/API/knowledgeFiles.ts容纳真实breadcrumb/create-folder/rename-file/rename-folder/preview/download/search窄API；现knowledgeSpace.ts仅补Child真实tags:{id:number,name:string}[]和has_failed_files/has_abnormal_files/has_processing_files可选bool，总行≤600。所有API原wrapped request、positive safe integer IDs、原ApiError传播，无新增管理头或认证参数。真实路由/方法/字段如下：GET /space/{sid}/folders/{fid}/parent→{id,file_name}[]；POST /space/{sid}/folders body{name,parent_id?}；PUT /space/{sid}/folders/{fid}或/files/{fid} body仅{name}；GET /space/{sid}/files/{fid}/preview→{original_url,preview_url,file_source,source_url,final_url,web_title,media_kind,html_preview_url}；GET同/download→{original_url,preview_url}。全部带原/knowledge前缀。搜索GET /space/{sid}/search仅接受{keyword?,parent_id?,tag_ids?:number[],file_status?:number[],page,page_size,order_field?,order_sort?}，不发送name或cursor，不把search伪造为children过滤；数组沿现API重复query key编码。父级路径含自身，原数字缺失祖先fallback保留，不把任意旧window名当事实。

T754测试→T755 Files.tsx+SpaceDirectoryRow.tsx：以scope/space/parent为真实key消费现listChildren opaque cursor，空页has_more仍可继续，不能用total/client分页。搜索独立真实search端点且page envelope，清搜索回目录首cursor，scope/parent/filter/ABA退休迟到list/preview/action/dialog结果，不复用未授权旧行。每行真实type为folder或knowledge_file；仅点击动作菜单时读现getMyResourcePermissionsApi(type,id)，本地缓存及epoch含完整scope/目标，不用原缺tenant的useLazyResourceActions公共cache，不按容器canEdit/canDelete给所有file授权。create_folder/upload_file用当前容器，rename用目标rename，download独立download；预览直接真实/preview（服务端visible），不因预览额外请求download。原始文档复用现PreviewFile/RichPreviewFile，不走旧Paragraphs file_share/Chunk的额外资格；高级Chunk按原空间edit后续另卡。state重建仍可目录/preview/download、空folder与rename不加新冲突门禁。删除/move/retry/标签/批量与版本未装配不调旧library接口或展示可执行假入口。

T756测试→T757 detail.tsx+Header.tsx实际挂上述目录，用实际info/breadcrumb的title/description受控props，不将window/localStorage历史标题当SPACE权威；Header旧QA consumer保兼容可选props。根info不是目录成功的额外前置；已准入子目录不先拉可能无权root info来阻断，面包屑可用真实当前目标名称。原space.info actions仅[visible]或[]提示，具体容器动作须原权限API；子目录只按folder.visible，不额外叠root.visible。root或隐藏壳只显示实际服务端准许信息，不从旧缓存补隐藏字段。原返回/filelib导航不变，原root/header菜单不显示未接能力。

本节目录闭环完成后原T177仍等版本前置，T179等T083/084真实SPACE上传快照接线（现add_file未传processing_rule_request，不能前端绕回legacy）；普通upload_file不因读取edit-only settings新增edit门槛。版本服务器原读取/设主/删历史授权缺口只记录原事实，后续按已有用例动作冻结，不能猜成file.edit或以本节扩大安全加固需求。两端版本开关/env消费另卡。

新增locale仅f118.create_folder/folder_name/current_folder/loading_directory/directory_empty/more_files，INT统一三语；其他rename/download/save/cancel沿现词条，不改API errors生成产物。T758/T759限三语登记叶。所有新UI先读当前共享组件规范，复用已落地组件和现页面布局，不新增库/公共组件/视觉风格。新测试需真实API port+query/cache与scope/仅子树可见/visible-only preview不download/rename-only/重建可读断言，不删除旧功能断言；独立固定review+主树组合后才闭各卡。


§27文件API导出固定为listSpaceFolderParents(spaceId,folderId)、createSpaceFolder(spaceId,{name,parent_id?})、renameSpaceFolder(spaceId,folderId,{name})、renameSpaceFile(spaceId,fileId,{name})、getSpaceFilePreview(spaceId,fileId)、getSpaceFileDownload(spaceId,fileId)、searchSpaceChildren(spaceId,SpaceSearchQuery)。query与返回保持上文真实wire。locale只有已冻结业务用语无API依赖，T758/T759可先于其consumer准备，实际页面通过后再计入口闭合。


## 28. M2原资源/物理树/版本/标签有界只读事实子合同 V1：已冻结

T760测试→T761唯一生产knowledge/domain/repositories/unification_resource_repository.py:UnificationResourceRepository。全部读口外部native AsyncSession+已开原TX、可信具体正整数tenant、strict/no_autoflush、拒ambient bypass，不开Session、不flush/commit、不写任何业务/ledger/FGA/对象/index，不探测停服；没有creator、quota或在线引用资格判断。本slice只读事实，不等于原T161/T162完整M2，完整artifact/预检/全部tenant正式freeze另接。

九个alist_resources/alist_files/alist_documents/alist_versions/alist_qa/alist_tags/alist_tag_links/alist_tag_libraries/alist_department_spaces(session,*,after_id:int|None=None,limit:int=200)->现InventoryPage[对应frozen/slots Row]，全部真实INTEGER id seek+limit+1（≤201）及确定next_after，各表独立连续分页不按每root重扫。九模型实际为Knowledge/KnowledgeFile/KnowledgeDocument/KnowledgeDocumentVersion/QAKnowledge/Tag/TagLink/KnowledgeSpaceTagLibrary/DepartmentKnowledgeSpace，TagLibrary与DeptSpace也按真实id。QA1/type2原事实保留，未知type不偷偷过滤；Repo不恢复或purge、不补V1、不转换标签。Tag/TagLink只读原事实，后续转换只能知识业务目标，不能扩大其他标签写范围。

ResourceRow显式旧20列：user_id,tenant_id,name,type,description,model,collection_name,index_name,state,is_released,auth_type,is_shared,auto_tag_enabled,auto_tag_library_id,metadata_fields,create_time,update_time,id,creation_request_id,creation_payload_hash（两个creation列在a1b已存在）。单列NeutralKnowledgeFacts保存processing_defaults/processing_config_version/metadata_schema_revision/model_config_revision/model_transition/index_generation/migration_origin七新增列，不混入old_business_digest。旧列全部参与确定canonical原业务摘要，非有限/非法JSON明确失败；原metadata/body只内存repr=False，不直接输出artifact。FileRow显式现真实KnowledgeFileBase旧列+id（无全ORM dump），split_rule/user_metadata/abstract/remark/其他原文只内存repr=False；Doc/Version/QA/Tag/Link/Library/Dept各按真实已核字段闭集，日期标准ISO摘要，禁止输出provider配置或raw异常内容。

Doc/Version无tenant，通过其真实父Knowledge锚定并保raw关系/父tenant/space/file-type scalar事实；不得INNER静默吞掉坏链。avalidate_global_integrity(session)为整个run一次的只读LIMIT1探针：七个有tenant表的NULL/<=0/找不到Tenant，File→Knowledge存在及归属、Doc→Knowledge、Version→Doc/File/各Knowledge存在同归属和FILE类型；只诊断闭集ID/reason，不读foreign名称/内容。内部跨scope窗口仅这些明确全局完整性探针和下述精确PK事实，不能拿其当授权或缺失legacy证据。完全无Doc/Version的旧物理FILE不是孤儿，保留给M2按design7.2列补V1计划；已有部分/多重/错误主指针/链必须可见于事实或明确拒绝，不能靠空JOIN当空空间。

ainspect_file_ancestors(session,*,file_ids:tuple[int,...])->tuple[FileAncestorFact,...]：positive非bool、去重≤500，内部每批≤200，空输入0SQL，按去重输入顺序返。Fact闭集{id,exists,tenant_id,knowledge_id,file_type,level,file_level_path,update_time}；只有全局PK真不存在才exists=False，foreign也返其真实tenant/type/path scalar，不读名称/内容/配置，入口仍拒ambient bypass。file_level_path是**祖先ID链、不含自身**，原NULL/''/'/'和path/level原样保留不normalize。现MAX_FOLDER_LEVEL9只管新写；存量level10+保持可访问/移动，不在M2设新上限/截断/flatten。后续coordinator聚合真实unique ancestor键按有界批查、验证无环/实际DIR/tenant/space/prefix一致，不逐file逐层SQL；本repo不签发preflight通过或自动修树。

本slice测试须真实native SQL覆盖401分页、完整旧20/neutral7区分、tenant NULL/未知/错误父/foreign链、未建V1事实、legacy overdeep原样、祖先500输入3批且重复IDs不重查、空0SQL及外部TX零写/no-autoflush/原pending保留；大root/多版本只线性PK页，不独立列表相乘或按tenant重跑global探针。标准SQLAlchemy/现JsonType保持C2，MySQL克隆实测尚待审批通路恢复，DM8实库免测不免静态。固定独立审+真实后续consumer之前不将helper记作正式M2完成。


### 24.2逐项执行规模与pending关系复核补充：已冻结

独立审已确认no_autoflush下其他既有dirty version的knowledge_file_id可改指目标、历史item的primary file可pending移出；提交前必须把真实当前primary version/file及关联FK history纳入精确必要集合，拒相关关键关系pending，不能先以旧SQL合法链判成功再flush落坏链；无关remark/name继续保留。只精确PK/有界pending候选，不重扫空间。

规模预算覆盖数据库实际JSON反序列化/SQL列，不能只数SELECT或Python属性读取。原401items×4KB快照、10项claim/renew/checkpoint/complete/finalize/retry已实测scope_manifest 55次/94,455,625 bytes及item snapshot 4,387次/18,201,663 bytes。修复中metadata持久scope_manifest仅target/space/parent+各snapshot digest，完整before/after仍在真实JobItem且request_hash仍覆盖完整快照；执行读取使用明确light projection/raiseload，业务查询/audit完整scope兼容保留，不能进程cache遮DB传输。领取下一项只读取实际可领取的最早一条（pending或租约已过期running，保NULL租约语义/原排序/Job锁），不可每次.all读取全部pending snapshots。metadata计数以冻结total_count及真实Item集合核完整性，不为读len而拉整清单；非metadata原行为需同选集回归不回退租约/幂等。原T733/735测试与734/736生产叶内闭合后，由同独立代理复验才允许后继738。


## 29. M2原创建者、组织与配额配置事实子合同 V1：已冻结

T762测试→T763唯一生产`knowledge/domain/repositories/unification_control_repository.py:UnificationControlRepository`。沿§28外部native AsyncSession+原TX+可信具体tenant/strict/no_autoflush/拒ambient bypass，不开Session或写/flush/commit，不做在线授权/配额执法、主体恢复或转换。事实只供后续完整M2预检与闭集摘要；原T161/T162、全平台权限采集、正式freeze仍未闭合。

`aget_tenant(session)`仅精确当前Tenant.id，返回闭集TenantControlFact(id,status,parent_tenant_id,root_dept_id,share_default_to_children,quota_config,update_time)，不存在明确10998。quota_config深拷贝且repr=False，有限canonical JSON；不读storage_config/联系信息/凭据。`alist_memberships/alist_departments/alist_roles(session,*,after_id:int|None=None,limit:int=200)`均按真实id seek与limit+1（≤201），返回现InventoryPage及确定next_after。MembershipRow仅原id/user_id/tenant_id/is_default/status/is_active/last_access_time/join_time；UserTenant是listener明确排除表，必须显式当前tenant谓词，不通过active条件吞历史记录。DepartmentRow仅id/tenant_id/parent_id/path/status/is_deleted/is_tenant_root/mounted_tenant_id/update_time，保原路径不改组织。RoleRow仅id/tenant_id/role_type/department_id/quota_config/knowledge_space_file_limit/update_time，普通页只本tenant，不把Root全局角色混成当前归属；quota JSON有限校验且repr=False。

`alist_user_roles(session,*,after_key:tuple[int,int,int]|None=None,limit:int=200)`使用真实复合主键(user_id,role_id,id)作完整字典序seek/order/next_after，不用非唯一id丢行；返回本叶定义frozen/slots ControlPage[UserRoleRow]，next_after仅上述tuple或None，Row保三键+tenant_id/create_time/update_time。输入和DB键均正整数非bool，非法明确失败。SQL用可移植and/or，不能数据库专有tuple函数。

`ainspect_users(session,*,user_ids:tuple[int,...])`去重≤500、每批≤200、空零SQL，按输入去重顺序返CreatorFact(user_id,exists,delete)，精确全局User.user_id，不猜User.id、不读姓名/密码/token。`ainspect_roles(session,*,role_ids:tuple[int,...])`同预算/顺序，精确全局Role.id返RoleFact(exists及上述RoleRow事实；missing其他字段None)，供解释原global角色/坏引用，不能授权。两个精确全局读内部受控跨scope窗口，不接任意tenant、不扩大ordinary页；只有物理不存在才exists=False。inactive/delete/historical membership都不能冒充creator物理不存在，是否异常由实际业务root/lifecycle的后续预检决定。

`avalidate_global_integrity(session)`整个run一次，只对UserTenant/Department/Role/UserRole四表做NULL/<=0/未知Tenant的LIMIT1存在性探针（闭集reason+id；UserRole诊断用完整三键），不按tenant重跑，不读foreign个人信息。关系存在性与活动资格分别留给精确事实和后续预检，不以INNER JOIN静默过滤历史记录。

不新增配额统计SQL：后续M2消费§28真实资源流线性汇总，原个人SPACE计数type3且排除部门空间，原租户计数包含部门空间；迁移来源长期个人豁免由M3及T165/166接线。存储只原file_source channel/space_upload且不按处理状态过滤。保Tenant/Role原quota配置及多角色/原管理身份语义，不自行新增user_count、重算租户用量或把全局每用户显示口径改成本tenant。测试以native SQL覆盖401页、同id不同user/role复合键、500精确ID三批、外部dirty零写、跨scope事实与普通页隔离、历史成员及deleted但存在creator、非法JSON；C2按既有模型/SQL静态复核，DM8实库按用户免测。


## 30. SPACE普通上传的实际配置快照与V1共用接线：已冻结

原T083测试叶与T084生产叶先闭合`KnowledgeSpaceService.add_file`默认配置遗漏，不新建普通上传J1 kind或改loader/scheduler。服务原root/folder upload_file、实际tenant归属、重建idle、角色字节及目标tenant链配额、dedup/失败结果、版本和权限补偿均保持；不得借此增加file.edit/空间edit/管理header，不能因edit-only settings读取接口阻止合法普通上传。

`FileProcessBase(knowledge_id=...)`仅作为未显式提供规则的原始请求传既有`KnowledgeService.process_one_file(...,processing_rule_request=...)`；`KnowledgeFileOne(file_path=...)`不手动填ExcelRule，让现实际snapshot解析器依文件类型消费空间/系统默认。实际File.split_rule在入队前保存完整有效规则与`_effective_processing`；preview缓存key与worker都读取该真实split_rule，不能用系统ExcelRule重新拼接。默认值读取内部已加载Knowledge的配置，不请求额外edit-only HTTP。后续保存默认不改这些已保存快照、不重处理历史。

每个新成功物理文件复用已存在`_create_primary_document_for_file`形成真实Doc/V1/主指针，去除add_file内重复注册代码；原版本开关只影响UI/显式版本操作，不能使普通上传无V1。dedup失败结果不造新版本、成功后才原scheduler派发，配额/格式/权限初始化失败走原补偿，不留Doc/Version。folder_upload_items按原目录分组调用add_file，自然使用同一配置解析；不改folder深度/同层重名规则。

测试需沿真实process_one_file和snapshot adapter读回File.split_rule，验证文档/表格空间默认、无默认系统fallback、专用音视频分支、实际preview key、后续改默认不改变既有快照；原native Doc/Version形成和回滚、历史版本不改、目录委托、重建拒绝零派发及旧上传回归组合。外部MinIO/模型/调度可隔离，不能把process_one_file自身替成固定结果来冒配置生效。网页独立专用separator/overlap0、原md/HTML与overwrite链不在此步骤改为普通文档默认。显式批次/文件参数新wire、版本UI/实际动作及整个T084其他用例须后续真实检查，首阶段不凭此默认修复勾完整T083/T084。


§30旧假结果兼容：T765只补两个原上传测试叶中process_one_file假返回行的已保存split_rule，保持原权限补偿/不新建审批断言。实际14路径对照：前驱770含新测试18红/72绿，候选18红/72绿；集合差异是新增快照3红已修而原假split_rule缺失另3红。其余15个旧version用例的缺metadata_schema_revision夹具/旧HTTPException断言前后完全一致，另记未绿，不扩大本次上传生产修复。真实process_one_file总是先写split_rule，生产不能给None静默补系统值。


§24失败落账接缝补充（已冻结）：T736原JobRepo与T735原metadata_job_repository测试叶负责`afail_attempt`在metadata kind下的完整四事实。沿原Root锁→Job锁顺序，从实际锁后Root的model_config_revision/index_generation/metadata_schema_revision及真实metadata_fields canonical digest构造当前配置，不能只传R/G导致合法schema任务被误判obsolete；schema/R/G变更仍明确obsolete。只在metadata分支补schema事实，其他kind保持原语义；不将修复塞进739 worker叶。metadata批量失败更新只读必要Item列、defer/raiseload完整processing_snapshot，不回读全manifest或全体item快照。先在原测试叶真实失败并核当前schema失败落账、过期schema、无快照传输，再单生产叶修，独立复验；不扩worker外部IO竞态范围或新任务绑定。


§24.3 T740原准入测试接缝（已冻结）：现HTTP precheck DTO只接受embedding_rebuild/file_reprocess/file_resplit/metadata_schema_change，metadata真实开放后四种都已装配。T766仅原test_processing_endpoints.py门禁用例使用FastAPI dependency override：调用原get_processing_service实际工厂，取得真实Owner/Service后仅在该测试实例缩窄available_kinds；仍以合法metadata请求验证10999。原bad pagination/state 422保持，其他测试继续生产默认工厂。不能编造file_move或放宽DTO、恢复生产metadata拒绝、删skip原门禁。T748的精确DI合同已在40553507f及本文件§24.3冻结，读主功能树即可，不依赖旧lane文档版本。


§24.3双DI真实调用补正（已冻结）：已实际读v2 `open_endpoints/api/dependencies.py:get_knowledge_service`，其原直接构造KnowledgeService(repo,file_repo)，并未Depends v1的metadata工厂。T748因此明确两个API DI叶。T742已有application/metadata_legacy.py内定义唯一纯组合函数`build_legacy_metadata_service(*,knowledge_repository,knowledge_file_repository,permission_service=None)`：构造原Domain KnowledgeMetadataService并注同一真实SPACE writer；未显式permission_service沿原KnowledgePermissionService语义，不改当前权限运行时。两个API DI分别调用此application工厂，v1保持原注入permission实例，v2把返回metadata_service传原KnowledgeService；不跨模块import API，不复制业务桥接，也不在Domain反向import application。T741真实双router/DI红测应先暴露v2未注入事实，再检验两端SPACE均通过同TX schema+J1且原v2 principal/data=True保留。


§27详情URL与Breadcrumb词条补充（已冻结）：维持现`/filelib/:id`，可选`?parent_id=<positive safe decimal integer>`表示当前目录；无该参数才是根。新query键不是授权证明，只定位真实后端parent；存在但为空、重复、非法格式、非正数或超safe integer时页面明确无效且不请求root/children，不静默退回根。点击folder或真实breadcrumb仅设置/删除parent_id，保fileStatus及其他原query；切目录沿真实完整scope重新读，不能复活旧行。直达合法子目录只读实际breadcrumb/children，不以root info或root.visible作前置；root info错误不阻止独立目录结果。Header新增可选受控title/description，空字符串仍受控，不以window/storage补SPACE权威；未提供props的原QA分支保兼容。

复用当前@bisheng/ui Breadcrumb折叠能力，ariaLabel用现f118.current_folder；新增唯一键f118.expand_folders（须保{{count}}），中文“展开省略的 {{count}} 层目录”、英文“Show {{count}} hidden folder levels”、日文“省略された {{count}} 階層のフォルダーを表示”。locale由INT独写，T767中英/T768日文，原所有key/value不变；不新建UI组件或设计风格。


§24.3旧空操作兼容补充（已冻结）：原legacy add/update/delete允许空字段列表。仅该协议writer对解析后changes=[]保原no-op：仍核实际ambient身份、真实SPACE/tenant和原容器edit等原业务准入，返回实际原schema，不把None改为空数组；不建Plan/J1/虚假item、不推进schema或R/G修订，不生成accepted/completed假任务。新processing precheck DTO的changes min_length=1保持。非空原完整schema+J1同TX逻辑不变；T741原叶先加三操作的空请求、无权限拒绝/SQL零写及两协议原响应测试，再在T742原writer叶窄实现。
