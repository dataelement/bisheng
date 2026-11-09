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


## 31. M2同事务准备上下文与原来源业务修订事实：已冻结

T769测试→T770唯一生产`knowledge/application/unification_sources.py`，在现SourceInventory内补必要事实与只读复用；不写BRR/SourceSet/Coverage/run/artifact或改线上Owner。完整T161/T162与初始回填仍另接，不能借context声称已签授权收据或正式freeze。

同叶定义frozen/slots PreparedSourceInventoryContext，保存可信tenant/run/writer、原TransactionIdentity及本tenant一次实际采集的shared_server_ids、NameCatalog、KnowledgeRow tuple和预编译UnificationNameIndex；raw目录及索引repr=False，仅该实例/原TX内存，不序列化、不全局缓存。`aprepare_tenant_context(session,*,run_id,writer_contract_version)`沿现具体tenant/native原TX/拒bypass与run标识校验，调用原tenant orphan一次、原pin sharing一次、实际model name catalog一次、knowledge主键页一次完整消费。原`aiter_tenant_source_records`增加可选`context=None`，None保持旧行为委托prepare；提供context时核本实例/tenant/run/writer/原native TX，每yield仍核当前范围，不重复这四类准备读取。foreign tenant、别run/writer、别实例、commit/rollback或新TX、bypass均拒绝；不因同SQLSession对象就跨TX复用。预检后续使用同context已采集目录/共享事实，不能再重读全目录或逐槽FGA。physical-target缓存仍该次stream局部，不当跨阶段授权cache。

现RootInventoryRecord/SourceInventoryRecord/RetiredInventoryRecord各补必填`business_revision_digest`（64hex），与原configuration/reference digest和R2初始化source_revision独立。它只摘要现Raw Repository真实已投影业务行身份/tenant/状态/原update_time及完整原引用配置，不伪称数据库有单调版本。WF/APP根以原RawRootRow摘要一次，版本来源和退休版本同时绑定该根摘要+原RawVersionRow（含真实version id/update_time/is_current/terminal等）；不把根mirror当额外Source或每version重读根。AS/CH根及current来源绑定原RawRootRow与完整原links/sync行（含disabled及更新时间），各根只组装一次；defaults绑定实际own RawDefaultRow.id/key/tenant/value/update_time，None/空仍原值。

KN原业务修订摘要从现KnowledgeRow明确排除本轮neutral字段model_transition_json/model_config_revision/index_generation/processing_config_version/metadata_schema_revision/migration_origin，其余已投影旧字段含type/owner/model/物理索引/原update_time均保；neutral事实仍由§28 ResourceRow.neutral独立冻结，配置摘要仍覆盖原model/transition，不删任何事实。0→3或其他计划内变化必须由后续M3显式before/planned-after摘要核对，不能把configuration_digest或新BRS revision=1冒原业务修订。未知SQL字段不凭空加入；当前RawRepo缺字段须另冻结真实投影后再接。

测试用原native六源fixture和真实extractor/name/target流程，覆盖context单次share/catalog/knowledge读取、提供context不重扫、0/401知识页及多source/slot线性计数、跨tenant/run/writer/实例/TX拒绝、所有原6来源/retired/零root语义保持。独立变更真实row更新时间、WF/APP父及版本状态、AS/CH links、defaults row id和值、KN旧model/owner/type/索引必须改变相应business_revision_digest；KN neutral单列变化不混旧业务摘要。保无raw配置泄露、外部no_autoflush/零DML及原20用例回归；新header消费者仅未来M2，不改extractor版本/当前引用业务协议。


§31旧闭集断言接缝（已冻结）：T771唯一test_migration_source_inventory.py，仅在原fields(SourceInventoryRecord)精确列表追加必填business_revision_digest，并断言真实64hex；所有原slots/frozen/秘密字段/数量/退休及物理事实断言保留。先T769红→T770实际实现→T771单叶独立提交；不改旧fixture来造业务修订或删除断言。

## 32. M2六来源闭集分页artifact编码：已冻结

INT负责T772测试→T773唯一生产`knowledge/application/unification_source_codec.py`，只纯JSON编解码，供后续正式M2和初始回填读取同一真实artifact。复用§31四种真实Root/Source/Reference/Retired记录及现两类MigrationTargetFact/SourceKey/SourceRootKey/TargetKey，不接Raw Repository Row/任意dict/ORM/provider配置，不开SQL/网络、不授Owner收据/legacy证据、不写run/BRR/ready。

`encode_source_page(*,run_id:str,tenant_id:int,page_index:int,records:tuple[四种record,...])->bytes`；`decode_source_page(content:bytes,*,run_id,tenant_id,page_index)->DecodedSourcePage`。DecodedSourcePage为frozen/slots，tenant_id/page_index/records只保存闭集DTO。run沿现artifact合法标识规则（长度≤64），tenant正int非bool，page_index非负int非bool；records严格tuple、≤199项，允许空页（明确空租户）。保持顺序、不静默去重；完整跨页source count/reference digest/唯一性仍由后续编排校验，不称该codec完成完整盘点。

内容沿现UnificationArtifactStore envelope恰好{schema_version:1,run_id,kind:'sources',records:list}。records第一个固定闭集header恰好{record_type:'page',tenant_id,page_index,record_count}，其后≤199业务record，所以含header每对象≤200闭集record；空页仍有tenant/index头，不混用其他tenant的空对象。各业务record仅增加record_type:'root'|'source'|'reference'|'retired'判别，字段严格等现四DTO（含business_revision_digest）；keys只现真实显式字段/枚举值，lifecycle以标量list编码并还原tuple；Reference中的physical_fact仅现实际Fact闭集并与target相同key，不能塞名称/内容/config。不同target tenant/不在线/坏父等原始scalar事实可编码，它们是预检事实而非授权；不能在codec把foreign过滤成missing或赋予可调用性。

规范UTF8 JSON用ensure_ascii=False/sort_keys/separators及allow_nan=False，最大16MiB，零字节/超限/非bytes/重复键/非规范编码/NaN/额外字段/未知记录/枚举/错run-tenant-index/count/target与fact键错明确10998机器reason，不输出payload；所有digest字段严格64小写hex。Source/Root/Target键走现构造及规范投影，bool/float不能冒整数；nullable原fact scalar按真实类型保留，不借shape校验修数据。只接受精确已登记DTO类型，不因dataclass未来加字段自动导出；新字段必须显式改闭集合同。编码的canonical bytes能直接交现持久store.aput_canonical(kind='sources')，读回decode后仍须后续全页manifest/hash/原业务事实验证才可引用初始化，绝不单凭客户端字典签发证据。

测试必须真实四DTO+双physical Fact roundtrip、跨页199/200边界/空页区分tenant、中文及原lifecycle、dataclass frozen/slots与非法shape/duplicate JSON/错header/错fact/digest/nonfinite/16MiB预算；既有实际UnificationArtifactStore fake-transport读回可组合，但不假称MinIO实测/正式M2。可按已冻结§31 DTO接口与T770并行编码，最终真实组合绿及固定独立审后才合入/闭卡；不为并行给生产加兼容旧缺字段或伪造header事实。

## 33. SPACE原上传协议的显式批次规则接线：已冻结

T775测试→T776只扩展真实POST `/api/v1/knowledge/space/{space_id}/files`：原`file_path:list[str]`与`parent_id`、响应及原上传动作/容器不变，新增可选`overrides:ProcessingOverrides|null`。字段闭集直接使用现public ProcessingOverrides：document/table部分字段，未知字段、bool整数、非正table行数等沿原严格DTO拒绝；不允许客户端传有效快照、配置版本、索引/模型或actor。省略/null/空对象都继承本次实际空间默认，只显式非null规则作为本批覆盖，不能由DTO默认补全将空间默认盖掉。

真实KnowledgeSpaceService.add_file内部kw-only接`processing_overrides`，公开handler仅传req.overrides。以本叶窄纯组合将显式document字段及table字段分别投影到原FileProcessBase输入（table放excel_rule），让已有capture_processing_input产生原输入收据；复用原process_one_file→真实有效快照→保存split_rule→preview key→V1→原scheduler。每个文件继续按真实类型裁剪、表格不吃文档规则、媒体专用约束保留，不能把一个文件的解析规则回写空间默认或另一个文件的收据。旧内部caller省略新kw，旧批量补偿、去重、审批、配额与权限全保。

本节是原T083/T084的实际入口必要接线，不新建upload JobKind、不扩大文件edit、不做在途IO竞态治理，不将批次覆盖等同于per-file覆盖或完整上传/版本验收。测试至少覆盖真实ASGI DTO→service转交、普通省略与显式部分覆盖的实际process_one_file保存快照、mixed table/document隔离、非法请求零写零派发，以及原失败补偿。production Owner仅INT占用schema/endpoint/service三叶，PLATFORM不得改这些叶。

## 34. 正式M2完整入口与全租户原子冻结实施合同：已冻结

本组统一交付正式维护入口，不以某个codec/helper或注入假ports关闭原T161/T162。生产Owner：MIG独占`application/unification_inventory_codec.py`、`unification_preflight.py`、`unification_inventory.py`、既有`unification_run_repository.py`和`permission/domain/repositories/f118_migration_snapshot_repository.py`；INT另接真实physical/队列/FGA只读适配和运维CLI。首次入口`UnificationInventoryApplication.arun(session,*,run_id,writer_contract_version,environment,backup_ref,schema_ref)->FrozenGlobalInventoryResult`，外部native原TX，descriptor均恰好object_key/sha256。入口与最终freeze前拒绝非账本pending/dirty/deleted，不以账本flush顺带写业务。脚本不探测停服或自动证明备份一致性。

固定顺序：读实际schema/全部Tenant（含Root、停用及保数据者）/既有run→全局完整性探针每run一次、原Catalog/pin一次及真实PinnedReader→每tenant实际resource/control/permission/task/六来源完整消费与预检，SourceContext每tenant一次→所有闭集事实及计划页上传且读回验证→单SQL TX `afreeze_all`锁实际完整Tenant集合、按ID锁Tenant/run并绑定同一global baseline/plan。Repository新增`aget_global_freeze(session,*,run_id,writer_contract_version,tenant_ids)`、`afreeze_all(session,*,run_id,writer_contract_version,tenant_ids,baseline_ref,plan_ref)`；不begin/commit/rollback。若末tenant失败，全部冻结回滚。应用只委托该Repo写run，不写业务/BRR/SourceSet/ready、不自动进入converting。完整原freeze幂等只验证并返回原对象；混合状态、不同hash、tenant集合漂移/failed明确拒绝；已冻结不重新盘点或重分missing。

artifact沿现Store闭集envelope，每页头加记录总≤200、≤16MiB。sources沿§32，其余codec显式白名单，不asdict全DTO自动导出。事实页头包含section/scope(global|tenant)/tenant_id(全局必须null)/page_index/record_count。resource只原ID/type/owner/状态、转换必要模型/索引/创建幂等安全标量、完整原业务摘要及neutral摘要；file只真实ID/归属/type/父链/level/status/source/size/必要私有对象定位和整行/split_rule/user_metadata独立摘要；doc/version/tag保真实键、父关系、主指针及全业务摘要，标签正文仅摘要；control保组织/关系/历史状态、quota摘要与标量额度；permission沿原Catalog/pin及四baselineDTO明确字段（含inactive/protected）；source沿原四DTO/双Fact。QA原文、abstract/remark/user_metadata内容、prompt/graph/provider config/凭据和actor_reference原文不得导出；完整恢复依一致备份。必要私有定位键不打印。manifest也有界分页/分层，不单对象塞无限页列表；先baseline root descriptor再生成引用它的plan，无自身hash环。

预检沿已确认语义：物理User.user_id存在才算creator存在，不因deleted/历史成员/不在当前tenant判missing；type0→3、QA1/type2只盘点不转换、未知type不静默过滤。文件ancestor聚合批查，同tenant/space/DIR/路径前缀/无环，保合法NULL/空和历史overdeep。Doc/File/Version全链/唯一关联/主指针一致；完全无注册旧FILE仅计划补V1，不提前造ID/写入。标签映射按真实Tag/TagLink不同枚举，不统一文本替换。原元数据完整摘要保留。显式offline数字ID仍物理存在；Root撤共享原数字槽保provenance，不新增全局online门槛或伪造missing；APP无ID名称失败、foreign/type2/坏父链阻断。权限四表不漏inactive，按资源一次聚合、批量编译现retirement plan，无Grant×Assignee或user×resource枚举；保namespace映射和纯可见等级/来源。quota只读原配置/原计数，合法存量超限不阻断、不调用在线剩余额度执法；个人迁移空间数量豁免、存储不重复计。任务只盘点真实关联/参数摘要，无task-model绑定、队列删除/派发或停服状态检查。

必需原生只读端口：`PhysicalInventoryReader.aiter_facts(*,resource_requests,object_requests)`读真实MinIO/ES/Milvus存在/大小/必要摘要、index/schema/实际标识兼容；合法空索引/零分段按原契约，不强制非空，不embedding/建索引。`QueuedTaskInventoryReader.aiter_facts(*,tenant_ids)`读实际Redis scheduler queue/payload/inflight与SQL J1/items/delete账本，安全摘要而非payload全文。`PinnedMigrationPermissionReader.aiter_original_tuples()`只读实际固定Store一次，输出user/relation/object；condition或未知权威字段明确拒绝，不静默剥除。冻结原SQL/tuple/catalog/pin与compiler可证投影及预期use变化，不构造全主体笛卡尔矩阵。上述required端口缺失/异常均fail closed，无allow_partial或仅SQL通过就正式freeze的分支。MIG可先实现codec/确定预检/原子Repo/实际app组合，原T162需这些原生适配和CLI全部闭合才勾。

## 35. 跨空间移动的真实索引替换与恢复合同：已冻结

T785/T786由PROC独占既有`worker/knowledge/move_worker.py`和新`test/knowledge_unification/test_move_worker.py`，先交付后续真实J1消费的索引adapter，不以此完成整个T073/T074或归属业务。新增`async apply_move_index_item(*,operation_id,target:ResourceVersionTarget,source:Knowledge,destination:Knowledge,invoke_user_id,metadata_policy:MoveMetadataPolicy,guard,checkpoints:MoveCheckpointPort)->MoveIndexResult`。两个空间只能来自后续Owner真实原身份/业务准入，严格同具体tenant、真实SPACE、不同物理index/collection；预期双方R/G取真实对象。每次初始化、外部写、验证、清理前后guard，SQL不得跨外部IO。模型仍读目标当前业务模型，不用job历史hint。metadata_policy只确认保留/清除自定义字段，保实际Chunk人工值、正文、系统metadata/对象路径及file/document/versionID，只换knowledge_id。WEB_LINK系统keys不得按自定义metadata全部清空。

source ES精确term document_id，size≤1000 scroll至EOF并finally清cursor，缺索引在target_verified前失败，不能当零Chunk。无合法checkpoint先精确清目标本file局部并验空，再分页重嵌入/写两库；ES稳定ID由operation/file/version/source_ES_id摘要，refresh且禁止自动建索引。Milvus auto_id=True，不能假定传ids能upsert；未验证重投一律精确replace整个本file，不逐批追加续跑。两目标分页核真实count及规范正文/metadata payload digest（Milvus仅实际schema可投影字段、排生成pk/vector）；不能只返回ids/count就成功。目标全量验证且checkpoint持久提交后才清源；重投target_verified先复验目标，匹配则不再写目标，只补源清理。ES/Milvus精确清源并flush/refresh，两者验0后保存source_cleaned。失败保持原checkpoint，不改File状态/Job终态。

MoveCheckpointPort只有aload()->MoveIndexCheckpoint|None与asave(checkpoint)->None；asave成功意味着后续J1租约核验且SQL已commit，保存失败立刻停、不清源。闭集checkpoint：schema_version/operation/真实三元组/源目标空间/双R-G及index-collection摘要/policy摘要/step/source count-digest/双目标count/target payload digest；常量大小，不存chunk/embedding/URL。step仅move_target_verified或move_source_cleaned；未知/错operation/target/RG/policy不当合法完成，明确失败。

后继KN/runner组须接原操作确认/F048 durable投影/J1 compact读取，源动作move与目标容器upload_file，不能复用space-edit硬门禁；暂无新版kind可从HTTP接受。最小SQL关联允许OperationPlan.space_id=源、operation='move'、operation_id=真实Job.id，Job.space_id=目标，kind='move_index'，同TX consume/create。源删除依赖用真实plan.operation_id=job.id与item.job_id关联/tenant过滤，不JSON查询，不仅筛accepted/running；源输入保护至少保到source_cleaned（含failed/obsolete），后续精确合同再实施。普通稳定对象键优先保；现copy遗留共享preview/thumbnail必须由删除manifest保护/精确共享分支处理，不照旧注释全量复制。固定space=A/folder=F配置移后可能需手动修复，只列确认impact，不自动改业务配置、禁止全部引用或搬其他文件。源空间删除与目标仍引用对象的真实验收继续原T073/T074/T089后继。

## 36. 平台普通上传实际闭环：已冻结

T787–T792由PLATFORM独占5生产叶：新`controllers/API/knowledgeUploads.ts`、`pages/KnowledgePage/filesUpload.tsx`、新`components/SpaceFileUploadPanel.tsx`、现`components/Files.tsx`、新`components/SpaceDirectoryToolbar.tsx`；API/路由面板/真实目录入口三对任务。原`/filelib/upload/:id`文档路由直接接SPACE，QA实际ImportQa弹窗不经过它，不为判断类型先GET root/info而增加root visible条件，不修未注册的孤立QA跳转。

API只原wrapped axios：POST `/api/v1/knowledge/upload/{sid}` multipart file暂存（返回原file_path等）、POST `/api/v1/knowledge/space/{sid}/files`原注册。注册支持§33可选overrides typed字段，但此组UI先只继承模式（省略整个overrides），不借原legacy process/preview/retry或edit-only processing-settings。API可接受可选AbortSignal，不附新认证/管理pin；暂存沿现可信管理上下文，注册沿普通具体tenant。所有positive safe ID、ApiError、原响应保留。

页面使用真实useKnowledgePageScope及严格sid/parent_id，只核当前root或folder `upload_file`，不额外读root信息/space.edit；无资格/unknown显示真实拒绝或重试，不直接消费旧upload流。Panel自持队列/AbortController/epoch，只读复用现DropZone的file input/格式/媒体capability和既有容量规则；scope/space/parent/卸载永久退休upload/register/polling旧响应，切回相同scope亦不复活，取消已注册资源不伪报服务端回滚。暂存成功不等于注册或解析成功，按注册实际file ID用listChildren(file_ids)核真实状态，不能靠filename/返回序号匹配。原错误保留可重试，不能吞错误或补造完成。

Files将当前容器已读取的真实upload_file能力挂实际入口，Toolbar按需抽取保持单叶≤600、保目录现scope/keyword/filter/ABA及动作生命周期。所有URL保持parent与原目录语义，无全局管理列表替代普通授权。新文案优先复用已有三语key；必须新key交INT唯一locale集成，不硬编码、不加ts-ignore/eslint抑制。此闭环不宣称目录上传、per-file/高级预分段、完整版本或原T177/T179全部完成；版本需先补服务端原管理资格/目标权限及引用保护，不能前端space.edit补洞。

§36状态文案唯一键冻结：f118.upload_staged、upload_registered、upload_cancelled、upload_status_unavailable、upload_may_continue，由INT的T793/T794三语集成，分别表示暂存完成、已提交处理、已取消、暂时无法获取处理状态，以及停止跟踪不撤销已提交处理；不得把前两者写成解析成功。

## 37. M2原固定Store完整tuple流：已冻结

T795先测试→T796只扩现`permission/application/migration_read.py`，新增frozen/slots `OriginalTupleFact(user,relation,object)`及`PinnedMigrationPermissionReader.aiter_original_tuples()`。只能在现真实原pin discovery成功并进入reader后，沿同一原FGAClient.iter_tuples(consistency='HIGHER_CONSISTENCY')无过滤完整读Store一次；不按tenant或资源重复扫描、不list_objects推断完整原tuple，不写FGA/SQL、不读provider/token/配置或导出客户端。流生命周期不允许同reader第二次采集，关闭/重pin/途中错误明确失败，不缓存全Store、不丢重复或只保知识namespace。

每个真实tuple key严格恰user/relation/object三个非空字符串（各有界4096，不含NUL）；condition或未知权威字段阻断，不静默删除。每yield前重验reader仍open、客户端仍原store/model；输出闭集fact，不泄露raw key至错误文本。普通共享读取aget_shared_server_ids及原tenant/native TX限制完全保持。全Store事实供§34同run原基线，不代表全主体×资源授权矩阵已核；M4仍按原冻结SQL/compiler及实际既定用例验证。

§34全局freeze续跑澄清：原子性要求不能存在preparing/未冻与已冻混合；不要求M3/M4各tenant后继阶段锁步。全部tenant已冻结、tenant集合/writer/原baseline及plan完全一致、无failed时，合法baseline_frozen/converting/backfilling/verifying/verified/completed阶段差异仍返回同一原global proof并零flush，不重盘点/重冻/倒退阶段。任一failed沿原显式恢复协议，不借getter恢复；未解释的证据/集合差异继续拒绝。

§36测试叶澄清：原f118SpaceDirectory.test.tsx已达600行，T791采用新f118SpaceDirectoryUpload.test.tsx单叶，复用实际Files/FilesUpload与wrapped API验证入口全链；原22目录断言保持并列入必跑回归，不压缩或移除原断言以腾行。生产Owner与5叶范围不变。

## 38. 正式M2真实物理只读端口与受限artifact存储：已冻结

T799/T800由INT独占新`knowledge/application/unification_physical.py`与`unification_minio.py`，及对应两个native边界测试叶。`PhysicalInventoryReader.aiter_facts(*,resource_requests:tuple[InventoryRecord,...]=(),object_requests:tuple[InventoryRecord,...]=())`每种≤199，原resource(仅本轮0/3)/file闭集记录；object直接接file，不传未完成的physical_object事实。实际当前具体tenant、非bypass、全部输入先校identity与重复再IO，每yield复核原scope；文件归属仍由完整M2已核真实SQL决定，不接HTTP任意索引/路径。输出真实codec InventoryRecord physical_index或physical_object，同请求身份，漏/重复/foreign由app完整核对。QA/type2保原SQL facts/摘要，不在这个新端口治理/重建其物理内容。

Index只读真实原ES index和Milvus collection：存在/schema摘要/原native报告count/identifier_compatible。名称缺失和物理不存在作为原事实，不自动建索引/collection、不load或flush、不调用模型在线/共享准入或embedding。已有schema按实际document_id/knowledge_id及正文契约核标识；合法未建空空间与空dynamic ES mapping不能按“必须有分段”拒绝。两库count仅记录，不因相等声称内容一致，不强迫两库count相等。所有schema原文只参与有界摘要，不导出客户端/provider配置。

对象从file的nonempty object_name/preview_file_object_name/bbox_object_name/thumbnails/html_snapshot_object_name逐个展开，thumbnails按已核原transformer的单key，不猜JSON或复制原文。只stat原精确permanent bucket/key，不换Root前缀或fallback其他tenant；NoSuchKey仅记exists=False，NoSuchBucket/AccessDenied/网络/非法统计明确失败。输出原size和ETag（ETag不是SHA）。同批共享key去重，有限并发，所有已启动IO收尾并检查；不下载文件正文或构造全File×Object比较。

`UnificationMinio`使用raw miniopy_async和专属aiohttp session，不能实例化会建桶/改policy/lifecycle的通用MinioStorage。显式aopen/close管理自有客户端；只提供stat及UnificationArtifactStore所需bucket/tmp_bucket、object_exists/get_object/put_object。artifact读写仅既有永久桶的`f118/unification/`内容寻址JSON、≤16MiB，流式读严格预算并finally释放响应；不自动建桶/改策略/签发公开URL/写tmp。原配置只在内存且不repr/错误回显。ES/原Milvus客户端沿当前实际vectors配置，生命周期关闭全owned clients，即使前一close失败仍关闭后续，保持原异常cause。此为§34required真实port，不以本地native transport替代真实M2与升级演练。

§36静态收口T797沿官方lint:prune只收缩已替换filesUpload失效条目，保其他原抑制；T798仅共享SQLite fixture补与已发布候选Model/DDL一致的metadata_schema_revision列（INTEGER NOT NULL DEFAULT0），不改生产或削减原断言。旧15个move fixture缺列反例用于核修复，后续行为失败仍如实报告。

## 39. 版本历史与候选搜索真实读取闭环：已冻结

T801–T806由EDGE独占6生产叶、3测试叶。A新`domain/repositories/knowledge_version_read_repository.py`及现`domain/schemas/knowledge_version_schema.py`；B新`domain/services/knowledge_version_read_service.py`及现`knowledge_version_service.py`只委托原三个read（list_versions_for_file/search_associable_documents/search_version_sources）；C现`api/dependencies.py`及`api/endpoints/knowledge_version.py`实际装配与两个新cursor路由。旧VersionService超长属原范围，委托删除read后不得为600行拆无关write，新叶≤600；不动link/merge/set-primary/delete/recommendations等其余写/读，更不提前开放管理UI。若旧read夹具需补新port，先报告真实失败与最小叶登记，不直接改其他测试。

原requested File须真实knowledge_file.visible，不加root.visible/edit/SUCCESS/idle或CREATOR/ADMIN；原CREATOR/ADMIN只是管理按钮资格，不改成历史读取门槛。真实File→Version→Document→SPACE完整链、具体tenant/type/主指针及唯一关系验证，坏/foreign关系明确失败。历史版本按每个实际File独立F048 loaded-target visible批量裁剪，不按同链/历史自动放行。隐藏版本不返名称/编码/上传者/状态，hidden primary时title/doc_code取可见anchor，current_primary_version_no=null，不由header泄露。preview/download仍独立原动作。

实际授权复用`resolve_permission_actor(login_user)`→`get_f048_resource_adapter('knowledge_file')`→`resolve_permission_targets_from_rows(rows=loaded_files,knowledge=loaded_space,actor=actor,action='visible')`→`batch_check_verified_business_visible(actor=actor,targets=targets)`；不得raw IDs直FGA或扩大管理shortcut。home1超管selected具体tenant沿已冻结KN窄管理pin规则，保原actor/home/S-D/token/data_scope。native只读Repo每批连接先释放再FGA：`aget_anchor(*,tenant_id,file_id)`；`alist_chain(*,tenant_id,document_id,after_version_id=None,limit=100)`按Version真实PK；`alist_candidates(*,tenant_id,space_id,after_document_id=None,limit=100)`按Doc PK+1，本批primary/version/file实事实与singleton一次GROUP聚合，不每doc读/读全空间JSON。LEFT/独立批查保坏关联可诊断，不能因过滤掉foreign就当空。

新增GET `/{space_id}/document/search-page`及`/{space_id}/document/version-search-page`（均原knowledge/space前缀）：keyword、current_file_id、page_size默认40、cursor。返回`VersionCandidatePage{data:AssociableDocumentEntry[],page_size,has_more,next_cursor}`。source模式沿原singleton业务，当前file同space且visible、排自身Doc、候选真实SUCCESS primary.visible。每SQL批≤100、单页至多消费1000候选，按最后消费Doc PK推进（非visible offset），空页可有后续。cursor绑定真实tenant/space/currentfile/mode/归一keyword及原actor/凭据/数据范围/管理pin上下文，错/非法复用KnowledgeSpaceInvalidCursorError。

旧两个array URL保完整结果语义，显式线性全量兼容例外：复用相同批量SQL/FGA直至EOF，不1000截断、不新增任意“缩小搜索”错误。保原DTO/排序/合法业务匹配语义，不对特殊字符模糊改成通配符或更宽搜索。新页端点供后继新UI，旧wire不变；此组只关闭真实read接缝，不宣称原版本管理写、文件直接引用删除保护或整T177已完成。

## 40. M2实际SQL任务及原Redis调度器只读盘点：已冻结

T807–T810由PROC独占新`domain/repositories/unification_task_repository.py`和`application/unification_tasks.py`及两个测试叶，不实例化会改queue/File状态的FileScheduler、不跑Lua/reconcile/complete/recover、不派发/ack/清任务，不建立任务模型绑定。此reader只覆盖明确SQL及scheduler；fair_scheduler关闭时直发消息、旧rebuild实际broker仍为正式M2后继required，不能冒充已全盘点。

Repo外部native原TX/no_autoflush，只读真实全状态Job/Item/DeleteJob的PK seek每页≤200，接口`alist_jobs/alist_items/alist_delete_jobs(session,*,after_id=None,limit=200)`；不在每item JOIN复制Job.scope_manifest。`aget_file_facts(session,*,file_ids:tuple[int,...])`每≤200，按精确PK批查实际File→Knowledge及可空Version/Doc。不能File×Version重复关系展开无界返回，先独立批查/计数聚合发现坏重复并拒绝；无注册旧FILE仍是事实，不提前补V1。运维全局读后严格真实tenant属于完整tenant_ids，不能按user当前tenant/default或payload claim猜归属，不commit/flush。配置/状态/完整原参数只做确定摘要，不导出JSON原文、actor/回调/URL/credential。

`QueuedTaskInventoryReader(session,*,repository=None,redis_connection=None).aiter_facts(*,tenant_ids:tuple[int,...])`每run全局一次，默认真实`(await get_redis_client()).async_connection`。只用SCAN/LRANGE/SSCAN/HSCAN读`{bisheng_fs}:queue:* /payload:* /inflight:* /parse_lock:*`及真实inflight_queue；scan count仅hint，实际SQL/记录切≤200，queue保offset和重复occurrence，cursor重复/返回类型错误明确处理，不因重复迭代产生重复事实或无限循环。正常输出原queued_task十字段；task_kind为scheduler_queue/payload/inflight/dispatch/parse_lock/processing_job/item/delete_job，保真实原状态/计数/lease/checkpoint摘要，不根据状态判断停服。SQL原始scope/parameters每Job仅一次摘要，不在items重复完整读取。

队列项+真实File存在但payload缺失只记录queued_payload_missing，不恢复；confirmed inflight的正常DEL payload记inflight_confirmed，非数据丢失，不把unconfirmed推为活跃。明确物理File缺失且无法权威归tenant时输出global `queued_task_orphan`，恰字段task_kind/task_id/space_id?/file_id?/document_id?/version_id?/payload_tenant_id?/state/reason/configuration_digest/record_digest，无tenant_id；reason只file_missing/space_missing/unresolved_tenant。payload_tenant_id只是原claim，不授予归属。此旧不可执行任务保原证据/队列供M5处置，不造BRR/引用/模型或强删标记；明确缺目标诊断不自动硬阻整个M2。File↔Root跨tenant、与非空payload tenant矛盾、坏链/SQL/解码/WRONGTYPE/网络等异常继续阻断，不能降成missing。

T811/T812由MIG在原codec两叶补闭集：queued_task_orphan仅tasks/global/tenant=None；app全局消费reader一次，正常facts按真实tenant分页，orphan进global页并纳入同manifest/hash。另补已被实际app红测暴露的sources manifest_entry（sources正文仍唯一§32codec，不能用通用codec重编）；补evidence/verification有界材料页：`store.aload_canonical(ref,run_id,kind='verification')`→decode_inventory_page(section='evidence',scope='global',tenant_id=None,page_index=0,kind='verification')，≤199 evidence_material，每项恰material_kind(backup|schema)/environment/writer_contract_version/tenant_inventory_digest/material_ref descriptor。app验证本manifest bytes/hash/身份/全部tenant集合及相应kind至少一项；material_ref只原运维声明材料定位/摘要，不下载大型备份或自动证明一致性/停服。完整备份由M1运维持有和核验，本增量不放宽其他record闭集或原ready。

§37目标模板纯协议补充：T813/T814在现permission.application.migration_read公开无参`target_authorization_model_checksum()->str`，内部只对仓库SSOT build_authorization_model_f048()计算authorization_model_checksum，不IO/seed/bootstrap、不读旧pin或接收CLI裸hash。M2 app经permission application协议取得目标模板checksum，禁止Knowledge application直接import core.openfga（C4/RULE-9）。旧pin仍是原基线授权模型，不能冒目标版本。

§39旧read夹具T815单叶已授权：test_knowledge_version_service_read.py原3项保原业务断言，补真实身份/tenant/loaded-target fixture，不以假Reader整返回绕新门禁。原Service.list_versions_for_file仅将新read的SpaceFileNotFound窄译回既有HTTP404及原version chain not found说明；PermissionDenied等保持真实错误，不将全部异常伪装404，不动其他write。原7路径控制另13项既有异常/无tenant失败如实保留。


## 41. 平台真实文件行只读版本历史子合同 V1：已冻结

由T816–T821三组测试/实现接线，INT独占T822三语词条。A仅types/api/app.ts与contexts/locationContext.tsx：映射实际env `knowledges.version_management.enabled`，缺失/false默认关闭，仅严格true开启；AppConfig类型可保原simhash_similarity_threshold，不消费或制造新开关。B仅新controllers/API/knowledgeVersions.ts与pages/KnowledgePage/components/SpaceVersionHistorySheet.tsx；C仅原Files.tsx与SpaceDirectoryRow.tsx。每实现卡最多两生产叶，Files只透传完整scope/space/parent，不在596行文件加面板状态；context旧过长不扩张为新业务Owner。所有新叶≤600行，读当前设计规范和已落地组件；不引入库、样式体系或strict/lint抑制。

沿旧client实际历史入口条件：featureEnabled && 非folder && is_multi_version，并由现lazy getMyPermissions(knowledge_file,id)确认visible才展示。历史不要求SUCCESS/管理员/file.edit/space或root可见；管理入口原资格不动。Dropdown关闭清actions不能当作权限撤销立即关面板。行点击捕获可信target/open token，后端仍以实际file.visible逐条裁剪。只typed GET原 `/api/v1/knowledge/space/file/{fid}/versions`，正安全整数及AbortSignal，保原ApiError；完整镜像VersionListResponse/VersionEntry的nullable code/uploader/time/status/current_primary_version_no，不造值。不接版本删除/链接/合并/set-primary/预览/下载动作，不改client或后端。

Sheet props为scope:KnowledgeQueryScope、spaceId、parentId:number|null、fileId:number|null、open、onOpenChange及同形测试readPort。仅open读取，复用现bs-ui Sheet与TanStack Query；key含完整scope/space/parent/file及每opening/实例epoch，queryFn消费AbortSignal。关闭/卸载/切scope/parent/file/行消失/flag关闭永久退休该opening，只取消自己的请求；A→空→A不复活旧响应。不得共享全局key或用cancelRefetch:false绕过隔离，结果不能异步重开Sheet。标题来自当前真实DTO，hidden primary只按后端visible anchor/current_primary_version_no=null显示；空/未知字段中性占位，错误不显示旧缓存metadata，原ApiError保留供重试。

四新测试叶均在src/frontend/platform/src/test：knowledgeVersionFeature.test.tsx、knowledgeVersionsContract.test.ts、f118SpaceVersionHistory.test.tsx、f118SpaceDirectoryHistory.test.tsx（路径若现测试组织不同可在首提交前精确纠正，不扩生产叶）。覆盖flag缺失/false/true、仅子树visible、custom历史裁剪/hidden primary/null、读错重试、完整scope/parent/file/open ABA及abort、菜单关闭不误退休、实际row→Sheet→API、原rename/download/QA回归。原目录600行测试保持不加字。INT新增f118.version_history/version_no/primary_version/version_uploader/version_upload_time/no_visible_versions/document_code七三语键，其他loading/retry/fileName/status/bs:close复用原键。此slice仅原T177后继，完整版本写入与其他高级功能保持待办。


## 42. M2真实Celery broker只读盘点子合同 V1：已冻结

PROC独占三组：T823/824新application/unification_broker_codec.py及test_migration_broker_codec.py；T825/826原domain/repositories/unification_task_repository.py及test_migration_task_repository.py增精确批查；T827/828新application/unification_broker.py及test_migration_broker.py。INT独占T829/830原unification_inventory_codec.py、unification_inventory.py两叶及各配对测试的broker闭集/装配接缝，须与MIG后继精确交接，不并写。原worker/Celery路由、Model/DDL/队列均不改。每新叶≤600，单生产卡≤2叶；不创建Kombu channel/Consumer/QoS、不ACK/requeue/restore/unacked锁，不执行任务、不证明停服、不造任务模型引用。

纯codec公开frozen BrokerReadConfiguration/DecodedKnowledgeMessage；配置默认取实际bisheng_celery.conf broker_url/read_url/write_url/transport_options（含CELERY环境覆盖），不用cache redis_url或result_backend。专用raw redis.asyncio与Sentinel.master_for，支持当前single redis/rediss与真实builder Sentinel master、DB/TLS/ACL/global_keyprefix。非Redis、多独立broker failover/读写源不一致、未知driver/options明确required-port fail closed，不能报空。原配置凭据repr=False不输出。Reader为RedisBrokerInventoryReader(session,*,repository=None,configuration=None,redis_connection=None).aiter_facts(*,tenant_ids:tuple[int,...])，每run全局一次；外部native Session/TX、no_autoflush、原tenant严格窗口，只读原事实。aclose只关自建raw客户端、借用不关；取消及原异常完整settle owned生命周期，不能Kombu close引发重投。

遍历生效knowledge/ocr/default与静态knowledge routes、SCAN实际LIST候选和只读SSCAN _kombu.binding.*历史queue；含生效priority_steps/sep及global_keyprefix。SCAN COUNT是hint，处理切批≤200；cluster cursor映射/重复键去重沿已冻结task reader规则，不按消息内容去重重复occurrence。LRANGE逐条offset读取，单次1条以控制原始消息内存；共享queue仅凭严格解码已知非knowledge task跳过，不读其业务。未知/畸形且无法证明非知识不能静默漏；已知知识签名非法拒绝。全局unacked HSCAN值按真实Kombu `[raw,exchange,routing_key]`，ZSET score与mutex只读事实，不按时间推停服；index孤立metadata仅global诊断。有效同任务不同物理位置分别计occurrence，稳定ID含UUID/位置/offset或delivery tag摘要。

只stdlib JSON：UTF8、拒重复键/nonfinite、content-type application/json、encoding utf-8、strict base64，v1 body task/id/args/kwargs与v2 headers task/id、body=[args,kwargs,embed]均真实Kombu离线产物测试。单raw及decoded≤16MiB；不支持的压缩/serializer、不可辨知识签名/非空未冻结canvas明确拒绝，禁pickle/yaml/decoder registry。headers含argsrepr/properties/body/callback只一次安全digest，不入artifact；不执行任何签名。

精确追真实知识任务：parse/retry/rebuild_file_chunk按File→Root及可空Doc/Version；move当前target及显式source、copy真实source/target；整库/QA rebuild读knowledge_id，旧三参modelHint只hash标legacy_requires_reissue，不补operation/RG或模型绑定；七参Root operation/RG只match/obsolete事实。execute_processing_job以实际J1 Job/dispatch_revision/kind，purge以DeleteJob；delete已删File须真实Root/ledger依据，QA按原QA而非File。控制型scheduler/recovery/projection/chat-retention任务无单业务目标记global_control，不造Root归属；未知knowledge任务拒绝。Repo扩精确批查每批≤200、空零SQL，globalPK仅安全标量，无名称/原配置泄漏；完整SQL链坏/foreign、header claim与权威tenant矛盾、ACL/IO/WRONGTYPE均阻断；明确物理目标missing只global/M5诊断不假授权。

T829/830新增唯一broker_task闭集，只tasks页，原queued_task十字段加header_tenant_id（nullable）、其中tenant_id允许null，task_kind真实task_name，state为上述明确闭集；tenant来自SQL归属，null仅global_control/明确target_missing/unacked_metadata_orphan。QA/job ID不塞file槽；完整target集合/count/顺序/SQL事实入record_digest。M2全run一次消费required真实broker port，known tenant分tenant页，null分global页，合原manifest/hash；scheduler和broker均必须存在，不以一个代替另一个。各message摘要一次、targets去重批查≤200，不逐target重编整个消息、不message×space/file×version相乘；10001消息/targets与优先级/unacked重复投递预算必须实测，读取前后raw字节/队列不变。

§42原生分类补充：broker_task.task_kind仅明确unacked_index-only无message的transport metadata孤儿允许null，不伪造知识task_name；此类state使用unacked_metadata_orphan。真实消息保完整原task_name。同broker DB共用cache时，已配置或_kombu.binding登记queue的坏/不可分类消息拒绝；未登记未知LIST只有外层满足真实Kombu envelope才纳入候选，确定普通业务LIST不纳入。有效Kombu未知历史queue中的知识前缀必须捕获，已辨非知识任务只隔离，不核其业务参数；不把任意聊天LIST坏JSON变成本次M2故障。


§42固定实现补充：原始LIST每次LRANGE一条，SQL目标仍≤200，非一批200条原始消息；HSCAN COUNT=1仅为Redis提示，整个已接收响应另以64MiB预算拒绝，不能声称网络响应分配前有硬上限。带glob字符的global_keyprefix仅在Redis SCAN/MATCH处转义为字面前缀；实际键值不改。Job/DeleteJob有实际父空间时须核对同tenant；J1缺父空间仅保明确target_missing诊断，原DeleteJob父空间已删仍是合法删除账本，不伪造新目标。root消费者在所有broker事实与artifact读回成功后才freeze，取消/异常必须settle reader owned关闭并使外部事务不能误提交部分Run。


## 43. M2精确可执行SQL阶段转换计划子合同 V1：已冻结

本阶段仅M2只读/纯计划，不执行M3业务DML，不闭合T163/164或正式迁移。MIG分组：T831/832原unification_sources.py单叶提取真实inventory KN修订纯SSOT，配原test_migration_source_context.py；T833/834新application/unification_conversion_plan.py及原unification_inventory_codec.py两叶，配新test_migration_conversion_plan.py与原codec测试；T835/836原unification_resource_repository.py单叶补精确全局Tag关系probe，配原resource repo测试；T837/838原unification_preflight.py与unification_inventory.py两叶实际委托，配原preflight与inventory_application测试。每实现≤2叶，所有新叶≤600；INT broker接缝T829/830必须等MIG固定交付后独占接手相同codec/app，不并写。

ConversionPlanBuilder(*,run_id:str,writer_contract_version:str,planned_at:datetime)只三参；add_resources/files/documents/versions/tags/tag_links/defaults(rows:tuple[原Row,...])每批≤200，阶段有序一次消费，finish()->Iterator[ConversionCommand]只一次。只留安全标量索引/摘要/命令，不保存完整File/defaults/metadata/prompt/凭据；原Row本批瞬时hash即丢。资源/File/Version/TagLink各线性一次，以creation/file/doc/tag/最终link tuple索引，不每file扫描全部版本、不tenant×来源/消息×targets笛卡尔。planned_at由app全run一次确定，冻结显式datetime；M3不得DB时钟改变未计划字段。

所有命令闭集含schema_version=1/run_id/writer_contract_version/tenant_id/command_key64及明确操作类型。ResourceConversionCommand仅原type0：knowledge_id、before/after_business_digest、before/after_neutral_digest、after_inventory_business_revision_digest、after_owner_configuration_digest、target_type=3、target_is_released=False、target_migration_origin=run_id。保原其余旧20/neutral6及update_time、model/index/collection/state/metadata/defaults/R/G/creation key；auth_type不硬设private，另依真实冻结权限finalize计划。after_inventory业务修订明确SQL阶段，不冒权限最终态：复用unification_sources提取knowledge_business_revision_digest(row)的原13字段算法；原_configured与builder同调用，原header摘要必须不变。after_owner_configuration_digest取真实ModelReferenceRepository13字段projection→KnowledgeReferenceSourceOwner._snapshot的纯configuration_digest（不authorize/IO/造授权证据），native对照实际repo.aload_source→Owner._snapshot。后续权限若改auth_type须整体M2 freeze前另冻其最终依赖，不覆盖SQL阶段hash。

creation目标键用(tenant,user,最终type,非空request_id)一次去重；原type0投3与原3冲突明确预检拒绝，不修改creation ID/hash、不等M3 IntegrityError。已有type3资源列全不改，QA1/type2保原。所有KnowledgeFile列零写，不把upload改space_upload。InitializeV1Command仅实际FILE=1且冻结证明全局Version关联恰0，适用0/3资源；DIR不建、已有任何版本关系/主指针须完整验证并保原，不用first()/online上传helper/成功态筛选。命令含knowledge/file ID、file_business_digest、before_relation_digest、自然键SHA(run,writer,tenant,file,register_v1)、Doc/Version模板digest、原file_level_path/level、planned_at；Doc仅knowledge/path/level/primary及冻结timestamp，Version仅真实新DocID/原fileID/no1/primary及冻结timestamp。M2不猜新自增ID；M3后继同TX获得ID+原子outcome/checkpoint，重跑不得重复V1。

Tag owner只Tag(tenant,business_type,business_id)，不借首个Link猜。仅business_type=knowledge且规范business_id精确命中原type0，并完整反查该Tag所有links同owner File、类型9/8时才转换knowledge_space。其他0/3/QA/nonKN/cross-tenant共享或不明parent明确预检拒绝，不clone/合Tag/全局替其他业务。Tag命令精确tag/knowledge ID、before/after digest、from/to。Link9→8只实际type0 File且Tag同tenant同owner；ResourceType1/其余不替。相同最终(resource_id,8,tag_id)保已有8、每冗余9单独drop_duplicate命令，含link/file/knowledge/tag ID、before/after?、from/to/action/survivor ID+digest，不塞无界数组；同名不同TagID冲突先报，不猜casefold或跨tenant合名。T835836补整个run一次raw LEFT LIMIT1闭集probe：TagLink→Tag存在/tenant及9/8→File存在/tenant，不能INNER吞坏链；不改其他Tag业务。

DefaultConversionCommand仅own tenant_system_model_config的linsight_llm真实行。纯plan_default_conversion(row,*,run_id,writer_contract_version)严格校原IDs，依次复用现transform_linsight_llm_config、transform_chat_default：原task_model.id在models保它否则first/empty，移除task_model/linsight_executor_mode；仅原chat_default空才取models最后。保其他JSON键/值/顺序及models次序，artifact只摘要/闭集选择ID、不输出JSON；同值skip零写。其他4keys原样；own缺失不复制Root/新Child覆盖，不用APP NameIndex猜旧默认名。命令含row/key、before_raw_row/config digest、after_config/业务修订digest、before/after_refs_digest、action、selected_linsight/chat ID?、drop flags、algorithm_version及同run旧models槽→新default槽provenance。M3重读真实JSON复算哈希，不调用整库backfill/宽松skip/commit wrapper，不在线bind或造legacy自举。

B实际app/preflight委托仅在全部资源链/精确plan检测及artifact上传读回后afreeze_all；源事实与来源流保持完整，plan闭集禁止raw内容。401稀疏分页/大量多版本/creation投影碰撞、Tag跨owner/重复link/同名、before/after篡改、半链/多主、非法defaultID/Root own缺省及现六来源完整组合必测。后继M3真实锁/白名单SQL、默认SQL、阶段outcome/namespace/FGA finalize尚未授权源码实施，须另冻协议。个人quota迁移豁免后继只count-only predicate三处（sync/async KnowledgeDao及QuotaService user branch），不得改通用排部门predicate/租户总量/文件SUM。


## 44. 迁移来源个人配额计数真实接线子合同 V1：已冻结

INT独占原T165测试test/knowledge_unification/test_quota.py与T166两生产叶knowledge/domain/models/knowledge.py、role/domain/services/quota_service.py；先在独立118-w6-kn lane红绿，固定后交非作者复查。沿§43迁移来源run_id字段稳定合同，前置为实际Model T010及原创建门禁T082，不必等待M3实现才写count-only谓词；正式转换后的真实配额联验仍归T203，不以本卡替代迁移。

在Knowledge模块新增私有纯count-only谓词（无数据库入口），以migration_origin非空标记持续排除迁移空间；NULL/空串无来源仍计个人数。仅现KnowledgeDao.count_spaces_by_user/async_count_spaces_by_user及QuotaService._knowledge_space_count_stmt(user_id)复用；不改通用_exclude_department_spaces、不影响任何空间列表/详情。原DAO按当前tenant listener，QuotaService全局per-user原bypass口径保持，不能借此统一成不同租户语义。user创建/显示计数均type3，原部门排除参数保持；tenant_id分支仍统计包括迁移和部门的全部实际SPACE，原tenant链总量超限保留存量并限制新增；文件SUM仅原channel/space_upload、不按处理status，不改file_source/大小/usage。

测试真实sync/async SQLite SQL、原创建_assert_space_creation_quota实际计数、各scope/跨tenant/global per-user原语义、重新Session/owner变更后origin不丢、native/dept/migrated/QA/type2、tenant超限与storage SQL稳定；C2编译type等标识符MySQL/DM8引用，无数据库专有函数/raw type SQL。无新增Model/DDL/API/配置或权限绕过，不执行M3写来源字段。原legacy两叶既有静态诊断冻结比对，新增0。


## 45. APP最终模型绑定原任务闭合验证合同 V1：已冻结

EDGE完成只读历史固定ce4后，仅独占原T139的test/knowledge_unification/test_app_model_binding.py补实际preview principal→ModelGatewayService.complete与真实删除LLMModel→provider不调用两条native回归。保已有同名实际ID/server漂移、原identity/TX、整Source无效、inspection不授权及missing port用例；真实Gateway/Adapter/SourceOwner/Core/SQL绑定参与，只有已有外部provider/传输或必要credential clock可隔离，不能固定准入结果。preview由真实credential/operation/route/qualification及preview_version，运行版本不同也不能套用active版许可。

生产T140已由W4 694859943→2a4e7e991及后续真实APP接线实现，gateway在provider前取原主体完整来源并核实时alias ID/server与冻结版本槽集合；同名解析不等于可换模型。源码未发现SDK依赖，故T139依赖由T134改为真实T136/T447。若新测试首绿明确记录首绿，不伪造红或改无关生产；若真实失败先报最小范围与证据，原T140仅允许登记的model_range_policy.py/model_gateway_service.py内必要修正，其余Owner需另核文件Owner。主agent复查与现四叶组合后按实际完成勾原卡，不以此声称SDK或全产品E2E完成。

§43标签预检精确范围补充：Tag-parent全局probe仅link.resource_type IN(8,9)或Tag确证business_type=knowledge且真实owner Knowledge.type=0的全部入向links；File-parent仅8/9。相关Tag/File缺失、foreign/tenant矛盾和转换Tag被nonKN/他空间共用继续阻断；纯workflow/app等不参与转换的旧Tag孤儿仅保原事实，不成为新增升级障碍。Builder对缺本tenantTag且非8/9的非相关Link不计划转换，不据app UUID猜Knowledge。标准SQL CASE只对知识/File相关字符串ID转换；Knowledge/File主键不CAST，保PK索引查找，不做Link×File全扫描。该收敛不改其他Tag业务、未知知识关系仍拒绝。


## 46. 工作台与开放工作流原任务实际使用准入合同 V1：已冻结

INT按已满足前置T150/T042实施原T151测试test/knowledge_unification/test_edge_apps_rpc.py、T152两生产叶workstation/api/endpoints/apps.py与open_endpoints/api/endpoints/workflow.py。仅将record_used_app、pin_used_app、invoke_workflow内部原use gate显式交现visible协议；原推荐/最近列表已visible，不改其他列表、排序/分页/分享签发。v1路由/UsedAppPin/envelope、app型recent与workflow/assistant型pin的原存在/在线检查、用户link幂等原样。v2原workflow:invoke scope/modes/session依赖、PublishedWorkflow读取/版本状态、原principal/PermissionActor与兼容operator、部门并发lease、enqueue/event/stop/错误保持；不把可见变为发布/分享/管理许可，不改历史配置/对话或新增引用。

先写实际ASGI v1/v2入口回归：仅visible授权可达原写link/prepare边界、不可见零写/零派发、类型与offline原错误、原返回/idempotence；v2 SAK/PAT/OBO原主体/scope/缺scope/业务错误保留。可隔离原认证传输和外部FGA/队列/telemetry，但真实scope dependency与principal→PermissionActor上下文必须执行，不mock整个endpoint或将original operator当授权主体。生产只必要三处literal，不做SDK/MCP/聊天或一般流程重构。配对与原开放invoke/身份回归通过后独立复核再闭原卡，完整E2E留后继。


§43有限双投影读取补充：SourceContext当前默认配置仅tenant/key/value，缺精确转换所需row ID/update_time。preflight对own五key做一次≤5行原Row投影，既有source inventory另做一次原Row投影；同native TX、固定五key，不按slot/resource重读。目录与共享仍每tenant一次。此阶段明确是最多两次不同消费的own-default有限投影，不能写成总计一次；不为五行强行扩大Context/sources接口。

## 47. 聊天原任务HTTP规范化与Manager可见性合同 V1：已冻结

EDGE原T141新test/knowledge_unification/test_edge_chat.py，T142仅api/v1/chat.py与common/chat/manager.py两生产叶。HTTP action默认visible，继续只接受visible|use，显式legacy use在HTTP边界归一visible后交原ranked get_online_flows_cursor或update_time get_all_flows_envelope；保ONLINE/flow_type/tag/keyword/search_description/limit/sort与can_share独立装饰。新默认/use/visible共canonical cursor语义，旧use上下文cursor仍按原AppInvalidCursorError拒绝，不猜重写。

Manager仅原check_business_action的action字面值改visible，保私有_has_use_action名字以原旧spy/tenant重验全部复用，不因名字含use新建权限模型；原_dispatch_message先message_admission再以execution.operator核visible，exact execution_snapshot/session_subject/workflowPort和消息对象保留，拒绝零handle_message。无重建actor/凭据、历史改写、引用或队列变更，不碰root §46两叶/WorkflowService/SDK。T141依实际T026/T136/T383，原T134无调用关系，移除人为串行依赖；T418可信根旧回归照常复跑。

ASGI真实默认/use/visible及两sort分支、非法action422，Manager两WorkType可见无use/隐藏、原operator不替换、fresh准入拒绝先于权限/handle均测。现F048 normalize_legacy_action已能使Manager可见行为首绿，如实记录；新增红以HTTP默认及canonical下传为据，不造假产品红。原websocket_tenant_revalidation/wf_client_admission/f040_app_square回归保持；只本任务两生产叶和单新测试叶，超过叶子先交接。

§46旧pin回归夹具补充T839（仅两个已登记旧测试叶）：实际组合暴露旧test_used_app_pin SQLite只建Flow/Assistant/UserLink，但现FlowDao union早已读App，缺空App表；另原两叶gate断言字面use需按新内部visible合同对齐。先用固定未改生产源码archive运行同旧选集核明原缺表失败，再只加空App表/必要import和对应action断言，原其他业务断言原样，不fake FlowDao或跳过失败。T151新测试叶保持独占，T839承接旧两叶，生产仍只三处字面替换；既有apps.py两条格式差异和RULE-3导入告警与基线同集则单列，不改无关代码。

§42消费者装配顺序补充：root T829先原inventory_codec测试/实现的纯前缀（不更改生产入口）供PROC真实reader联装；该前缀7真红49首绿→三路径108绿，作者reader联装三路径86绿后再接实际app，避免reader与全app测试依赖环。T829第二测试叶改为新test_migration_broker_application.py，单独覆盖required broker/tenant/global/异常/once/readback/frozen重入；原inventory_application测试仅T840单叶补独立broker fixture与缺口矩阵，原全部断言保持。T830仍只原codec/app两生产叶，无新一般协议层；codec属已存在598行的中央闭集文件，只增加broker类型/状态/页面校验，保全部原字节协议与白名单，避免为行数无关重构；所有新叶仍≤600。新app构造参数broker_reader，missing首次盘点拒绝，不能以scheduler空代替broker；同已freeze getter重入只验证原材料，不重新盘点。


## 48. SQL转换纯DTO的Domain边界前置 V1：已冻结

本前置不依赖待答AC80，不执行namespace/M3。PROC独占T841新test_migration_conversion_schema.py；T842仅新knowledge/domain/schemas/unification_conversion.py及原application/unification_conversion_plan.py两生产叶。根核真实七个dataclass为ConversionCommand、ResourceConversionCommand、InitializeV1Command、TagConversionCommand、TagLinkConversionCommand、DefaultSlotProvenance、DefaultConversionCommand；不是把ConversionPlanBuilder当第八DTO。字段/默认值/frozen/slots/继承完全不变、同一class对象唯一SSOT，纯initial_version_templates同移并显式re-export；App生产者原公开导出和COMMAND_RECORD_TYPES入口保持，原codec lazy type映射不动。新Domain仅stdlib dataclasses/datetime，不反向import App/IO；不复制canonical/hash算法、不镜像协议、不新增SQL/DDL/权限或新业务用例。

新测试缺模块真实红、逐旧公开对象identity/字段与模板实际canonical字节保持，原转换/codec/source/原app消费完整回归；任何老fixture/相同测试初绿如实，不造红。两生产叶固定后交INT/非作者验证再合流。M3实际service/repo/verified batch/恢复outcome仍仅候选，DM原无条件update_time触发器与保时间的实现前置未解，不授权本卡修改trigger/Model/DDL或开始转换。


## 49. 六业务来源批量安全展示 V1：已冻结

原T111/112已有目标锁/全租户真实计数/完整摘要，但尚无按原读取资格的展示。此波只补内部批量展示端口与六Owner，不提前关闭原卡，不接公开DELETE/PUT，不补假Coverage ready或任务模型引用。先协议，再六业务可并行；核心消费/HTTP来源分页留后续明确接口。与namespace/AC-80选择无依赖。

唯一frozen slots DTO `SourceDisclosure(source:SourceKey,name:str,version_label:str|None,entry:str|None)`；Port/Runtime与六Owner同名方法 `adisclose_sources(session,*,identity,source_keys:tuple[SourceKey,...])->tuple[SourceDisclosure|None,...]`。每次≤200、输入tuple、空批零SQL/FGA/身份IO，输出数量/顺序一一对应，重复key保原位置，任何展示对象的完整SourceKey须精确匹配输入；不收任意dict。None仅原资格不允许展示（含当前具体tenant之外），当前tenant缺真实业务/版本或元数据坏链不能伪装隐藏，应10994/fail closed。名称/版本来自当前业务安全列，entry只原已存在页面，未知深链给None，不拼假version路由。此DTO仅内部，后续HTTP不得序列化隐藏来源Key/名称/URL。

Runtime使用现AuthenticatedSourceReadIdentity捕获原身份并在批次后核对，保当前具体tenant/context/scope/凭据；foreign source不切ContextVar、不冒充来源tenant、该部分业务SQL/FGA为0，仍由影响核心完整计数阻删除。按SourceType分派，每Owner用真实批量轻投影（不读graph/config/manifest/provider设置）及原loaded-target F048 batch能力，空页不查、不得逐ID调用aresolve_source。资格正常拒绝回None，FGA/SQL/解析异常传递明确失败，不能降格成可删除。禁止新permission层、newadminshortcut、写锁/commit及跨租户新读取权。

协议生产仅新resource_reference/application/source_disclosure.py、新resource_reference/disclosure_composition.py；后者纯构造六Owner和singleton get_runtime，不改现bootstrap，不进行IO。每业务只原Owner与Repo两叶，数据轻DTO放对应Repo；WF visible且非当前另edit；AS原assistant.visible；APP原management_read（不能用根visible替代版本管理资格）；CH原channel.visible、停同步仍展示/计数；KN按实际type对应space/library.visible；defaults按下列§53已核实际读取入口资格，保原own/Root存储来源、不复制继承来源。均保持原PublicApiPrincipal/管理边界，不接分享token。

| 卡 | Owner | 实际生产叶（src/backend/bisheng/） | 单测试叶（src/backend/test/knowledge_unification/） |
| --- | --- | --- | --- |
| T843/844 | EDGE | resource_reference/application/source_disclosure.py、resource_reference/disclosure_composition.py | test_source_disclosure.py |
| T845/846 | EDGE | workflow/application/reference_source_owner.py、workflow/domain/repositories/reference_source_repository.py | test_workflow_source_disclosure.py |
| T847/848 | PERM | assistant/application/reference_source_owner.py、assistant/domain/repositories/reference_source_repository.py | test_assistant_source_disclosure.py |
| T849/850 | PERM | app_publish/application/reference_source_owner.py、app_publish/domain/repositories/reference_source_repository.py | test_app_source_disclosure.py |
| T851/852 | EDGE后继 | channel/application/reference_source_owner.py、channel/domain/repositories/reference_source_repository.py | test_channel_source_disclosure.py |
| T853/854 | root后继 | knowledge/application/reference_source_owner.py、knowledge/domain/repositories/model_reference_repository.py | test_knowledge_source_disclosure.py |
| T855/856 | INT | llm/application/model_default_source_owner.py、llm/domain/repositories/model_default_repository.py | test_defaults_source_disclosure.py |

同组先真实红后实现；所有新叶≤600、每实现≤2生产叶。用原数据库和原资格拼装，至少含401源/重复slot预算、foreign无读、非当前WF/APP历史、原资格变化/IO失败、无完整配置列和无写证明。无真实Coverage adapter时影响核心仍拒绝，本波端口不创建ready状态。


## 50. M2新建V1可表示时间 V1：已冻结

现Doc/Version为通用DateTime无MySQL fsp，不能冻结带微秒新建时间再由数据库舍入。INT独占T857单新测试叶test_migration_plan_time.py、T858原unification_inventory.py单生产叶；正式M2仅全run一次unification_now()后去microsecond再交所有tenant builder（UTC整秒）。原业务时间从SQL读出后保持，Domain模板/字段/codec/canonical/digest不改，不变更Model/DDL，也不在M3临时归一已冻结材料；旧微秒计划不满足可写前置时应明确失败/重新正式规划，不能同run静默替换。实际微秒clock+跨tenant新V1命令、模板hash及整秒clock均须回归。

M3时间保留另有C2静态前置：DM当前managed updater会无条件覆盖update_time，故停服且中性DDL完成后，在业务事务之外独立运维连接仅对白名单涉及表updater保存原定义摘要与启用状态、临时禁用；原disabled/absent不更改，不触FK/其他trigger；阶段结束恢复原状态并核验，失败保持维护，不再执行bootstrap/Alembic重建触发器。DM DDL前隐式commit，绝不能在M3业务Session里ALTER。M3本体显式写原time并flush后真实重读摘要校验；未做好前置就回滚，不能放宽hash或假设DDL回滚。此处是运维要求，不扩展自动触发器管理协议/代码；DM实测继续免除。


## 51. 迁移纯指纹SSOT的Domain前置 V1：已冻结

PROC独占T859860：原unification_inventory_codec.py的canonical/digest与其私有_invalid错误构造原样迁新knowledge/domain/services/unification_fingerprints.py，原codec显式同对象re-export（仍可供原lazy闭集读取），保所有成功字节与拒绝语义；仅两生产叶。不迁整record_from_row/权限映射，不再实现第二套json/hash，不改变MAX_BYTES或协议白名单。新单测试叶test_migration_fingerprints.py锁真实旧字节/异常、同对象、无App/Core/SQLAlchemy反向依赖，配原codec/plan与native M2选集。M3 Repo/Service后继只import Domain SSOT与现Domain Repository唯一列集，不反向导入App。此卡非M3转换。

§49 KN实现载体补充：可用实际Knowledge ORM的SQLAlchemy load_only安全标量投影且raiseload其余字段，保持原loaded-target Loader接口，不复制其permission snapshot/context hash算法。该局部投影不加载model/config/description，不写入或创建假业务事实；原Session在当前批次使用，字段不可隐式重读。


## 52. M3原生SQL转换组件 V1：已冻结

PROC独占T861/862新domain/repositories/unification_conversion_repository.py及其新test_migration_conversion_repository.py；T863/864新domain/services/unification_conversion.py及其新test_migration_conversion_service.py。每实现单生产叶、新叶≤600；依赖§43精确M2命令、§48纯DTO/模板、§50可表示时间与§51 Domain canonical/digest。只实现可组合Domain，正式manifest消费App/全局Catalog-namespace/FGA/CLI另冻，不提前闭合原T163164、R2/Coverage或开放执行命令，不绕过待用户答复的AC-80选择。

接口：Repo.alock_scope(session,*,run_id,writer_contract_version,baseline_hash,plan_hash,commands:tuple[ConversionCommand,...])->LockedConversionScope；aapply_and_read_after(session,*,scope)->tuple[ConversionOutcome,...]；aread_after(session,*,scope)为恢复复用同一写后核验。Service.aapply_batch(session,*,batch:VerifiedConversionBatch)->SQLConversionBatchResult；aget_progress(session,*,run_id,writer_contract_version,baseline_hash,plan_hash)->SQLConversionProgress纯读；averify_committed_page(session,*,batch)只读回算前缀。batch只由后继真实App校验冻结manifest membership/全页hash/当前cursor后经Domain私有issuer签发原对象，绑定同native Session、原TransactionIdentity、Run/hash/具体tenant、expected checkpoint/命令ordinal/EOF，registry一次消费，拒bare dict/伪造DTO/跨TX及篡改。单元fixture使用私有issuer不代表正式App已接线，不提供verified=True之类外部布尔绕过。

每批最多200个现有五类命令（ResourceConversion/InitializeV1/TagConversion/TagLinkConversion/DefaultConversion），不跳过未知kind计完成。原current具体tenant、no_autoflush；锁Run converting及精确checkpoint→Knowledge PK→File PK→Doc→Version→Tag→TagLink→own default实际rowID，全部升序/去重且每SQL IDs≤200。坏version链先COUNT聚合查重，Root JSON仅本批ResourceCommand所需Root一次，不在每file重复；survivor联合IDs超200分批，不做File×Version/Source×slot笛卡尔积。现RunRepo只flush，调用方唯一commit/rollback；组件无Session工厂、DDL、FGA/存储/provider IO。出错传播，外层整个批次必须回滚；若错误被外层捕获，也不得将部分业务与游标当成功提交。

唯一原行列集复用Domain原unification_resource_repository的RESOURCE_COLUMNS/NEUTRAL_COLUMNS/FILE_COLUMNS/DOCUMENT_COLUMNS/VERSION_COLUMNS/TAG_COLUMNS/LINK_COLUMNS及_values，不复制字段表；所有canonical/digest只§51 Domain SSOT，模板只§48同函数。Resource仅原type0→3、is_released=False、migration_origin=run，旧其余业务20/neutral7按冻结允许差异；File全列零UPDATE（包括time/state/source/chunk/metadata），QA1/type2及无命令原Space不改；仅实际无Version FILE补新Doc/V1及互指真实ID。Tag/Link仅§43已冻type9→8/精确重复删除，保其余列。Default仅own真实row/key，复用原llm Domain两个纯transform，保持其他四key/Root来源不变。所有UPDATE显式旧update_time，新V1两时间显式planned_at，flush后真正SQL标量重读，不信ORM旧缓存；任何trigger/时间或完整planned-after摘要不符失败。M3不对已冻微秒模板临时截断。

after业务/neutral核全部实际SQL事实；新Doc/Version实际互指ID归一回已冻natural_key再核唯一模板hash，并将真实分配ID纳入瞬时Outcome摘要（仅command_key/operation/actual_after_digest/docID/versionID）。两个Source派生digest和Default REF digests/provenance保留命令、由后继App/M4真实SourceOwner/提取器复核，SQL不反向import App、不伪造AuthorizedSnapshot/引用完成。

原Run converting.checkpoints键sql_conversion仅四字段；cursor为sql-v1:<已处理命令ordinal>:<末command_key>、processed_count为该tenant实际命令数、digest=前digest与本批命令/实际after/分配ID的闭集滚动hash，complete只已验frozen EOF。初值/编码/空EOF固定在单一service，不放Outcome全量JSON、不新表。锁内核原expected checkpoint，业务写后核验成功才同TX写新checkpoint；旧bare批重投拒，getter零写。恢复只启动时按≤200分页线性重核已提交prefix并累计同digest，后续新批不每次重扫prefix（禁N²）；实际ID漂移、半链/unknown commit须凭真实checkpoint与完整prefix证明，不猜已执行。SQL complete仅子步，不推进Run backfilling/ready。

最小真实测试含0→3及其他type不变、真实自增与互指、半链/多版本/foreign拒、Tag survivor精确处理、File逐列快照、Default五key与继承、SQL触发器覆盖旧time后真实读回失败且外TX rollback；签发/跨TX/phase/hash/cursor/取消/外rollback、401/10001恢复线性预算、每查询ID上限。DM实库免测，使用SQLite触发器反例和MySQL/DM编译检查静态边界，真实MySQL/升级事务仍需后继环境证明。


## 53. M3批次原子性及默认来源原读取资格补充：已冻结

§52原子性精确补充：Service在拒任何caller new/dirty/deleted pending后开启本批begin_nested SAVEPOINT（避免其隐式auto-flush caller），将业务和checkpoint同包；Repo单独aapply_and_read_after亦以自有savepoint保护写后核验失败。失败/取消仅rollback各自savepoint，成功仅release，均不commit/rollback caller原事务、不丢caller pending；外层catch再commit也不能留下半批业务或游标。原生savepoint项目已有使用，DM官方确认SAVEPOINT/ROLLBACK TO/RELEASE；macOS当前未安装被marker排除的DM dialect，不伪报其实际编译/执行通过，不安装。SQLite测试显式真正parent BEGIN规避legacy driver的savepoint释放即提交行为，产品无SQLite特判。原MySQL事务验证仍保留。

INT接手T855856两已登记默认来源叶，以让PROC专注M3，生产边界不变。实际原router GET /llm/knowledge、assistant、evaluation、workflow均get_login_user；原GET /llm/workbench为用户可选投影，原始metadata GET /llm/workbench/settings另需get_tenant_admin_user及_assert_can_write_system_config。故本port五key的名称元数据均沿已认证UserPayload/原actor与scope可读；不读取linsight_llm原始配置内容或候选模型。管理entry仅现设置管理资格（super或当前非Root tenantadmin）用户给出，其他entry=None，不凭链接授予管理权。源name使用实际原key字符串，无虚构数据库显示名或新hardcoded翻译。入口tabs沿现SystemModelConfig的knowledge/assis/evaluation/workflow/workbench；不修改/workbench投影或公开API/认证。

仅本current tenant的实际TenantSystemModelConfig五key轻投影id/tenant/key，单批≤200且unique最多5，空/foreign不查；不读value、不解析模型、不走resolve Root fallback、不复制继承来源。自身无原行即bad metadata fail10994，foreign Root来源在当前Child只记restricted，需原Root concrete view才可展示。原ModelReferenceService全平台删除影响入口的管理员准入不变，这不是新增默认配置访问权。Owner用现ModelDefaultReadIdentityPort绑定原UserPayload/actor/current scope前后，不接伪造private身份；Default新port不影响原私有执行读取五key。


§52依赖精确说明：允许复用现Domain已统一使用的跨模块公共纯合同resource_reference.application.contracts.TransactionIdentity；禁止反向依赖knowledge.application的计划/codec/SourceOwner编排实现，不为路径名重造原事务身份协议。


## 54. APP来源展示的原SA创建者删除例外批读 V1：已冻结

PERM审实际原F048Runtime单条fallback发现新批量展示会继承SQL N+1：50根全拒508 SELECT、50根仅CREATOR_GRANT允许delete556 SELECT；Catalog/Mode/Grant分别逐target读取，原语义正确、预算失败。只优化此既有例外所需批量读取，不新建授权政策、SQL跨业务自验或移除例外。T865新test/permission/test_creator_delete_batch.py、T866仅原permission/application/runtime.py与control_state.py两生产叶，APP Owner/Repo不在此卡并写；APP交固定后再做本组。

SqlPermissionControlState新增load_grants_batch(*,targets:tuple[VerifiedPermissionTarget,...],models:tuple[GrantModelSnapshot,...])->dict[(tenant_id,resource_type,resource_id),tuple[GrantSnapshot,...]]。empty零SQL，targets≤200去重，当前caller只传active manager模型；查询按精确三元目标分组AND/OR，不能tenant/type/id独立IN乘积扩围；实际Grant/Assignee IDs每SQL≤200。复用现_source_snapshot/stable_grant_key/GrantSnapshot，同tuple键完整映射（无grant也空tuple），active/source及version完全同单条load_grants，不读其他模型/其他tenant、不为批量做bypass。

Runtime.batch_check_actions只在既有SA+delete且决策剩余拒绝项触发；一次_runtime_catalog核原process pin，从现permission_snapshots按批取Mode。CUSTOM仅同actor.tenant且原version/parent/projection_state=CURRENT精确匹配才调用上述batch；manager/Grant.active/model.active、CREATOR_GRANT active、同service_account subject_id、userset_relation=None逐项原条件不变；原log保留。INHERIT保原nearest CUSTOM ancestor单条fallback，不新改文件继承策略；非SA/非delete/原决策已允许/foreign不多读、原单条check_action不变。不能误将主路径DECIDABLE的PROJECTING许可套在本例外严格CURRENT上；任何原读失败按原方式拒例外，不将异常变ALLOW。

同测试锁原50/50两例语义及实际SQL预算，再覆盖重复目标、空/foreign、撤销source/换model/非creator/非SA/版本或parent漂移/PROJECTING、Catalog pin或IO异常、INHERIT原路径对照。规模须50→200查询不逐项增长，401分批线性，禁止target×model×source关联乘积；不把原产品策略首绿伪称行为红。APP T849850待此预算接缝联装后才能闭合；既有权限其他全库性能不在本卡扩改。


## 55. 模型影响核心的完整来源分类与有界分页 V1：已冻结

EDGE先§56大目标集T873874，再T867868纯cursor/DTO、T869870实际核心。生产仅新llm/domain/services/model_reference_cursor.py与原model_reference_service.py，分两实现卡；测试新test_model_reference_sources.py及原test_llm_refs.py。新叶≤600。复用既有ModelDeletionRepository/真实Owner receipts/ReferenceRepository全BRR的200行seek、全局Coverage；constructor增disclosure_runtime:SourceDisclosureRuntime|None，默认纯disclosure_composition.get_runtime，不造另一ImpactCore、不假Ready。生产Coverage仍缺时保持10994，公开HTTP/确认plan/删除后继另冻，不据此验收整特性。

ainspect_removed_models(...原参数...,source_page_size:int=50)全量distinct完整SourceKey(tenant,type,id,version)只分类一次，六业务真实端口每批≤200。source_counts完整全集，新增qualified_counts，必须source_counts=qualified+restricted；slot_counts与inbound_digest不随展示过滤。foreign完整计数restricted但不进入业务Owner，不切scope/身份；当前metadata/IO异常10994，不能当正常隐藏。仅保首个有界详情页names，其余临时metadata处理后丢。页ModelReferenceSourcePage(data:tuple[ModelReferenceSourceEntry,...],page_size,has_more,next_cursor)，Entry只已qualified SourceDisclosure+matched_slot_count（同source本removed目标集合的实际BRR行数），不吐无界slot_keys。当前tenant候选按(type,id,version)稳定排序，消费候选数分页，空data仍可has_more。每页1..200/default50，bool/错类型拒绝。

alist_removed_model_sources(session,*,identity,server_id,retained_model_ids,delete_server=False,cursor:str,page_size:int=50)重新原管理员/目标/Owner/Coverage及完整BRR数据集核验，仅本页≤200候选重新资格，不重复全S资格计数，不将初次qualified_counts伪称后续实时汇总。cursor用现common.cursor封装source ordinal整数，context为规范command/server与实际target/server revisions、完整inbound hash、Coverage epoch/inventory、稳定原UserPayload/actor/闭集runtime credential/scope摘要及page_size（排trace）。隐藏SourceKey/名称/URL、原始凭据均不进入cursor。common.cursor未签名，只是上下文一致性，不能充当授权；篡改ordinal仍每个候选fresh授权，拒错上下文/负数/bool/越界/非法或超长payload。新session/新trace同原资格可继续，credential/scope/dataset变化拒复用。保Core现可接受user管理员身份，不借旧plan web-only形状新增限制。

v2完整摘要明确为SHA256(b'f118-model-inbound-v2\0'+每条原BRR.id的8字节big-endian+原_binding_digest(row)32字节)，按原Repo.id全局严格递增流；拒非正/bool/重复/倒序/uint64溢出。去hashes全量列表与sort，任何实际行ID/语义字段变化要重确认；旧内部v1确认不能伪兼容。全仓源码核当前无公开生产调用/实际构造，既有两测试仅64hex/变化/原样存储，不约束排序/ID无关；此证据不等于已查线上绝无记录。独立100001slot/1source的聚合峰值8.5MiB→约2.7KiB，仅证明hash-list额外内存消除，完整Core仍O(S) distinct集合+≤200页，不能称O(1)。测试需100001slot峰值、401source批量、跨binding页重复source、多target、最后页变化/ID重插、每页fresh scope及无隐藏Key，完整Scope/计数/摘要失败仍阻删除。

## 56. 原生目标规模及旧测试适配边界 V1：已冻结

EDGE T873874仅原llm/domain/repositories/reference_target_repository.py与resource_reference/domain/repositories/reference_repository.py，配新test_model_target_scale.py。原401目标425 SELECT含401 tombstone逐键预锁（server3/model4/tenant2/Run14/BRR1），1001合法目标在每Target一OR处触发SQLite max depth1000，原13+401绿/1001真红已实证。完整Owner authority/receipt/原Scope与目标全集不变，无业务总量新上限。Model业务行已批读，不伪称其逐model SQL。

TargetRepo仅将实际Tombstone(目标type/id/owner)读锁按完整集合预取分批≤200、复用原DeletionEvidence/_revision及missing/original/prelock proof校验，不每target一SQL；同步/异步共用原计划，原Server→Model→Tombstone锁顺序保持，分批内部与全局排序一致，注意数字ID/字符串索引顺序不可跨批交叉。不搬Owner认证到调用方、不读额外tenant、不改model默认/共享资格。原较大Model ID IN按便携条件分组，不改变实际锁定全集。RefRepo将等价目标谓词按target_type分组并按≤200 ID的IN片段组合，整条仍唯一SELECT、id seek/order与完整四键Source JOIN不变；不能拆成每目标组×每BRR页的重复扫描/用户×资源枚举。此处≤200是IN片段及Tombstone预取批次，不假报完整owner Scope总参数≤200；不另加Ref SQL总量限制或截断。401/1001多模型实际SQL、缺模型/合法tombstone/foreign/两Owner/全旧Owner/Reference paging选集须通过；真实MySQL锁/并发仍T202实测。

INT T871只原test/open_api/test_service_account_creator_delete.py的State fake补permission_snapshots/load_grants_batch，复用原mode_for_target/load_grants语义，不删旧断言、不改生产兼容fake。T872只原APP注册测试：真实F118实现前a1b1a2387为43pass/1既有super bare-scope fail/7skip，当前41pass/3fail/7skip；其中2个use Catalog期望随本次退休已过期。对齐非可分配visible/5原动作与真实模型visible关系，保legacy use wire单测；旧super场景补原已存在可信management_tenant_scope fixture，不变任何生产跨tenant策略。7个原中间件placeholder仍明确skip，不伪报E2E。


## 57. 冻结产物到真实SQL执行入口 V1：已冻结

PROC独占T875–T880三组：T875/876原application/unification_inventory.py及新test_migration_frozen_plan_reader.py；T877/878新application/unification_conversion_codec.py及新test_migration_conversion_codec.py；T879/880新application/unification_conversion.py及新test_migration_conversion_application.py。均在knowledge模块与test/knowledge_unification下，每实现一生产叶、新叶≤600。依赖T842/858/860/862/864；这六卡仅真实SQL子步，不包含namespace/Catalog、AC80待答、M4引用/Coverage或正式CLI，不提前关闭T163164。

原InventoryApplication提取只读aiter_frozen_pages(result,*,environment,backup_ref,schema_ref,current=None)，yield唯一frozen slots叶DTO(kind,section,scope,tenant_id,page_index,record_count,descriptor,content)；_verify_frozen仅完整drain同一reader，保原字节/合法图语义，不另复制DFS。原深度64、重复/循环object_key、root run元数据、plan→baseline绑定、材料hash/身份/计数均保留；增加实际tenant闭包和每(kind,section,scope,tenant)页索引连续、顺序唯一检查。合法空section/tenant无需伪造零页，不能将原M2合法材料变成新协议。

decode_sql_conversion_page(content,*,run_id,writer_contract_version,tenant_id,page_index)->DecodedSQLConversionPage(commands:tuple[五Domain命令,...],deferred:tuple[InventoryRecord,...])只复用现decode_inventory_page、COMMAND_RECORD_TYPES与record_from_row精确roundtrip，不改595行中央codec/新建hash算法。显式恢复whole-second naive datetime与DefaultSlotProvenance tuple；只接受五SQL command及原permission_plan/source_decision后继记录，未知tag/section拒绝，SQL命令必须原Run/writer/tenant/ordinal闭包。不得将deferred静默执行或宣称namespace完成。

UnificationSQLConversionApplication(*,artifact_store,session_factory,sql_service=None).arun(*,run_id,writer_contract_version,environment,backup_ref,schema_ref)->SQLConversionExecutionReport。caller不提供Session、raw commands或plan ref；从RunRepo.aget_global_freeze读取唯一真实refs，实际全量tenant含disabled宇宙及各Run的run/hash/refs必须一致，仅baseline_frozen/converting允许；合法逐tenant恢复可混合这两阶段，不要求phase字面相同。完整baseline及plan图和所有叶/坏尾先验证完，才允许任何业务DML。完整第一遍后按实际conversion membership/hash第二遍线性消费，禁止一批一遍全图或只验证已用页。

按tenant稳定升序，实际批≤199命令，每批新native Session/外事务，精确锁Run/refs/hash；baseline_frozen首批phase与业务/checkpoint同TX进入converting。仅durable commit确认后才携原Service continuation给下一新Session；fresh App每tenant一次线性核真实已提交prefix/实际分配ID/digest，再从partial artifact page的真实ordinal继续suffix。commit失联立即停止、报告unknown，不盲重放/自动failed/重新M2/替换baseline；下次由真实持久checkpoint恢复。EOF来自完整verified SQL命令数，零命令tenant亦用真实空EOF checkpoint；不能借最后artifact页含deferred误算SQL EOF。安全进度不含原配置/凭据。

中间SQL after摘要仅适用本子步未完成后继namespace转换前；未来总编排在SQL子步已完成且后继步骤开始时应按步骤checkpoint跳过，不能以预期namespace变化误判SQL漂移。Domain/Repo算法/phaseReady规则不改。测试含真实M2 artifact→typed Domain→native SQL，三tenant、foreign/缺tenant、坏尾零业务写、空tenant、部分已提交页恢复、unknown commit前后、File全列不变及401/10001线性查询/产物读预算。SQLite/native组件验证不替代后续MySQL正式停服升级。


## 58. 后台初始上传原子注册前置 V1：已冻结

PERM在模型核心独立复核完成后实施T881/882，仅新knowledge/domain/repositories/upload_registration_repository.py（DTO同叶）与新test/knowledge_unification/test_kn_upload_registration_repository.py。本组只原子SQL注册，不接旧上传/网页/文件夹/历史重链、不修改CommonBaseRepository/权限/调度；原T083084继续待办。上传仍原upload_file，不套Space.edit的J1 reprocess，不新增upload job kind或wire target_document_id。

DTO NewUploadFile(frozen slots)仅原file_name/file_size/md5/split_rule/file_source/user_metadata/user_id/user_name/updater_id/updater_name，所有配置/metadata repr=False；RegisteredUpload(file repr=False,document_id,version_id)为本Repo私有登记的receipt，不可由任意IDs伪造回删。aregister_initial(session,*,space_id,parent_id,files:tuple[NewUploadFile,...]<=200)->tuple[RegisteredUpload,...]；aset_materialized(session,*,registration,object_name,user_metadata=None)->RegisteredUpload；arollback_created(session,*,registrations:tuple[RegisteredUpload,...])。空批零SQL/flush，实际Session/原TX/具体tenant、正int与FILE/type3/实际parent folder同空间同tenant路径服务端导出，不信client路径/ID。File+Doc+V1+真实自增互指在同caller事务仅flush，独立savepoint失败无半链；不commit/rollback caller、不覆盖caller pending，不使用bypass或自建Session，按原严格scope守卫处理。每读/写ID批≤200。

首版本沿原initial version事实/状态/时间及原File等待处理语义；effective processing snapshot作为原split_rule完整保存，不在Repo重新resolve。永久key由旧KnowledgeUtils按实际FileID的唯一算法在后继应用计算；Repo仅接已物化object_name，不调用MinIO/FGA/queue/provider。materialize/cleanup只对本Repo发行、同Session/事务、仍匹配本次独立V1链和当前File事实的receipt生效，不能删历史或别次同ID；失败/cancel局部savepoint整笔回滚。rollback_created仅补偿本次新链SQL，不宣称分布式原子性。跨TX receipt需求须先交root冻结，禁止自行放松成裸ID。

native测试含实际autoincrement+全链互指、真实SQL触发器打断Doc/V1/物化写后外层catch再commit无半链、foreign/跨parent/坏path/空批/超批/pending拒且caller修改不丢、伪receipt/换TX/链被历史化拒补偿、200项有界查询与非笛卡尔积。原已有版本重链原生触发器反例确认两个primary的事务缺口，后继须另冻原子link Repo/Service/DI；其原权限动作尚未冻结，不能猜file.edit或扩大权限。原审批skip参数当前未消费，不凭任务标题新增审批行为；实际大小/配额按原限额在注册前核对。格式沿原FileExtensionMap及原解析阶段，不前移白名单/另造guard；unsupported及解析后内容安全失败按原状态保留File与完整版本链。无残留仅禁止孤立Version/半链，不承诺所有解析失败零File/版本。


## 59. 原上传staging与有效规则唯一生产者 V1：已冻结

EDGE T883/884仅新test/knowledge_unification/test_kn_upload_preparation.py及原knowledge/domain/services/knowledge_service.py一生产叶。原process_one_file入口/参数/返回保持，由新prepare_one_file(cls,login_user,knowledge,file_info,split_rule,file_kwargs=None,processing_rule_request=None)->PreparedUpload承接原download、真实大小/md5/原名和effective snapshot解析。DTO frozen slots置同Service叶：local_path repr=False、download_name、original_file_name、md5、file_size、split_rule repr=False（原JSON字符串）、file_info repr=False（原/按原规则copy后的KnowledgeFileOne）。这不是新授权层；下载保原file_download唯一路径，不在此处新建format/size/quota规则。

准备方法不读写SQL/FGA、不上传/删除MinIO对象、不telemetry/投队列、不创建Doc/V1。实际processing_snapshot_for_legacy_request、capture_legacy_processing_overrides、legacy_rule_from_snapshot仍唯一SSOT，原per-file Excel规则/actual_name/媒体类型、原原始md5获取顺序与split_rule JSON格式保留，不重复实现resolver。原无processing_rule_request的Excel/原split_rule变更语义保留，有请求时继续按原方式copy file_info，不覆盖调用方显式字段。

旧process_one_file消费该DTO后，原DAO md5优先于filename去重、skip_dedup可信内部用途、重复tmp对象/remark/FAILED返回、普通/QA投影、实际对象key、原cleanup/异常、telemetry及dispatch边界保持。不把原lib/QA改用新SPACE注册、不改审批/内容安全/版本/队列租户、不提前完成T083084。首准备是供后继SPACE共享的生产者；SQL注册和外部IO协调仍待真实接线。

新测试至少缺prepare真红、真实实际文件大小/原md5/归一名称、SPACE默认/显式sparse/per-file Excel/专用媒体规则与snapshot版本、prepare零DAO/FGA/对象写/queue以及IO/规则失败明确传播。原test_legacy_file_processing_callers.py和test_kn_upload.py/test_kn_upload_overrides.py断言不改并组合回归；若现结构import stub必须复用现source_module真实类，不测试复制方法。不因extract扩原大叶重构；新测试≤600，原Service只本段提取。固定SHA非作者复核和主组合后才闭两卡。


## 60. 原模型绑定证据匹配的线性内存扫描 V1：已冻结

INT T885/886仅新test/knowledge_unification/test_model_original_evidence_scale.py与原llm/domain/repositories/reference_target_repository.py。独立审代码确认bind的每target _original(originals,key)重复扫描完整原BRR集合，虽无SQL笛卡尔JOIN仍有M×B内存工作；owner_query原originals为空，因此§56大目标测试未覆盖此路径。以真实SQL 401/1001模型及单来源多slot计数实际helper收到的候选行数证明，不按wall clock阈值猜性能。

只在非union facts消费前将已读originals按完整MODEL目标ID分组一次，原_original在对应同ID候选中运行；保其所有target_tenant/space/legacy reason/run/evidence一致性与首原行选择，空/重复slot/不同source/version/foreign精确SQL谓词不变，旧helper可保。不得更改SQL、锁序、sharing/inherited/default/原source证据、Scope或授权，不为此group扩全资源优化。prelock_sources仅物理union原分支不发行或混用来源证据，仍原流程。测试需原生规模实际O(B+M)计数、相同目标多slot合法相同证据与冲突拒绝、不同source/version不串、既有Owner/混合prelock/删除影响回归；新增叶≤600、原大叶只窄改，不写其他叶。


## 61. 本次初始上传commit ACK及短事务重绑定 V1：已冻结

PERM T887/888仅原knowledge/domain/repositories/upload_registration_repository.py（现439行，扩后仍≤600）与新test/knowledge_unification/test_kn_upload_committed_registration.py。§58原aregister_initial/aset_materialized/arollback_created继续同Session/TX，不放宽它们；本前置只供后继本次上传App在SQL/Blob/FGA分阶段时安全处理自己新建的独立V1链，不接历史/任意IDs/跨进程恢复。普通上传继续原upload_file及原scheduler。

新增areserve_object_key(session,*,registration,object_name)->RegisteredUpload仅SQL预留确定永久key，要求本次原对象receipt/原native TX及当前完整链、原object_name为空，只改object_name并保初始时间/其他三行事实，不证明blob已存在。key由后继App用原KnowledgeUtils按实际FileID计算，Repo不import应用Service或外部IO。复用现materialize的单一SQL写后核验实现，不复制链算法。原aset_materialized亦只是SQL字段登记，不提供对象存在或派发就绪证明。

新增私有_acknowledge_committed_initial(*,registrations:tuple[RegisteredUpload,...]<=200)->None，仅在App实际await原根Session.commit()明确返回ACK后调用。Repo须同时有该原根Transaction的实际SQLAlchemy root after_commit证据（savepoint release、rollback、别的Session/TX或之后空commit不得充当）；原receipt及完整typed字段未变、当前具体tenant相同，登记只对这些原发行对象生效。用原Session实例级短生命周期observer/私有registry，不加全局event/新表/Model/DDL。after_commit虽已发生但外层commit wrapper报unknown时，App不会调用ACK，仍不得rebind/dispatch；原回滚或仅savepoint成功亦拒ACK。实现若需额外event处理须保持原caller生命周期，不主动commit/rollback。

新增私有_arebind_committed_initial(session,*,registration)->RegisteredUpload：须原Repo私有发行且已明确ACK的原对象，fresh另一native Session/原已开新TX、同具体tenant/无pending/bypass，原Session根TX已结束。真实重读原File/Doc/V1全事实、当前parent/path、精确独立V1链/无额外history或primary alias、仍原WAITING及未改名/未派发；全部与ACK时原facts完全相同才签发新TX局部receipt。原已ACK receipt保留作后继再次短TX核验，新局部receipt按原§58规则消费；不能构造新dataclass/拷贝/裸ID/客户端nonce授权。后继App仅本次调用实例保留registry，进程崩溃丢registry不宣称自动恢复。

后继顺序固定但本卡不接App：短TX完整注册+确定key→commit ACK→释放业务Session后blob/FGA→成功才原dispatch；pre-dispatch补偿先fresh短TX重绑定核当前链、释放Session，再原creation ledger resolve/inverse，成功后fresh rebind再次核链并SQL删除commit明确成功，最后清理本次owned blob。任何链漂移、投影/SQL commit unknown均保blob与可核SQL，不先删对象、不dispatch、不持业务锁跨外部IO。原actor/home/Scope由后继可信App保持，Repo本身不新增身份/授权协议。

native测试包括原47回归；root commit vs nested release/rollback/后续另TX、commit已发生但没有App ACK/commit wrapper抛unknown；fresh/local receipt边界、完整三行漂移/历史化/别名/改名/pending、读验证失败0写且保caller、reserved key纯SQL/不可替换原对象key及200项observer/SQL预算。普通DataScope/管理pin身份留App原准入测试；本扩展不新增一般跨TX删除服务、不冒正式恢复命令。


§61真实App idle读取补充：同一登记Repo新增alock_space_for_upload(session,*,space_id)->实际detached Knowledge，仅current具体tenant/type3精确FOR UPDATE、_scope(clean=True)/no_autoflush，不开/提交Session、不复制guard。后继App在自身短TX先读实际Root，再调用原require_space_processing_idle(actual,operation='upload_file')，随后aregister_initial同TX提交；原guard仅state==REBUILDING/model_transition非None，错误10999保持，materialize/cleanup不额外叠idle。此读只App调用，原47/200项注册预算不变，新App多固定1次Root读。原API DI实际构造Message/Version/Doc/File repositories仅存session/model且get_db_session不自动begin，独立witness确认0 SELECT/transaction=False；新App仍只收独立session factory，不借请求Repo跨外部IO。


## 62. 原重复上传暂存分支复用 V1：已冻结

EDGE T889/890仅新test/knowledge_unification/test_kn_upload_duplicate_preparation.py及原knowledge/domain/services/knowledge_service.py；不改SpaceService/App/DI/新注册Repo，后继真实消费者另冻。新增stage_prepared_duplicate(cls,*,prepared:PreparedUpload,repeat_files:tuple[KnowledgeFile,...]|list[KnowledgeFile])->KnowledgeFile，接原已下载/已解析effective快照与原DAO取得的非空重复候选；不新授权或查询SQL，不注册Doc/V1，不投队列。

将原process_one_file重复分支的md5优先/filename次级选择与完整tmp暂存、remark、FAILED、大小/split_rule赋值原样移至此方法；旧process在repeat_files and not skip_dedup时委托，正常创建/skip_dedup整段保持。新helper仅用prepared字段，不再file_download、不重复resolver；tmp key后缀仍prepared.download_name原扩展、展示名仍original_file_name，remove_unused_file仍原file_info.file_path且只tmp put成功后。保原返回同一候选对象及仅客户端失败响应的语义，不给旧行新commit、不重写旧历史或重新处理，不在这里增加visible/edit动作或扩大去重范围。

测试须真实准备/原SQL候选与原process调用，md5优先、同名不同内容、显式skip_dedup保原正常创建，helper零DAO/下载/新版本/queue；tmp put失败不提前cleanup、不持久修改旧数据库行。原test_legacy_file_processing_callers/test_kn_upload/test_kn_upload_overrides及T883新测试原断言保留组合，真实缺方法红与原业务首绿分列。生产只本段提取，原大Service不顺便重构，Ruff既有诊断只作准确基线对照，新增0；测试≤600。


## 63. 有序引用摘要流的唯一SSOT前置 V1：已冻结

PROC T891/892仅新test/knowledge_unification/test_reference_digest_stream.py及原resource_reference/application/contracts.py（现474行，新增后≤600）。此项只为后继M4分页核原reference_set_digest，未实现SourcePlan/初始写或Coverage；AC80/namespace待答不受影响。不复制canonical协议，不改DTO/字段/Source/TargetKey与任何权限/SQL方法。

新增ReferenceSetDigestAccumulator.update(reference:ReferenceSpec)->None、hexdigest()->str，以已有normalize_references的canonical tuple键(slot_key,target_type.value,target_id)非递减顺序接收已规范化行流；target_id按原字符串lex，绝不用numeric lock_order。仅保last key、hash和首项标记，不缓存完整refs；update不做集合归一/去重，允许相等canonical key以精确保留旧API可接受ReferenceSpec子类去重后仍同canonical键的成功行为，但拒倒序/非法reference类型。后继SourcePlan reader负责严格增序/重复拒绝，再调用此SSOT，不能把累加器当输入去重器。

原reference_set_digest(references)继续原normalize_references（原类型/集合去重/排序完全不变），随后委托同一Accumulator；所有成功SHA、Unicode/转义UTF8/空列表、旧重复/列表或generator可接受语义保持。统一编码只能有一处：原json.dumps tuple行的sort_keys/separators/ensure_ascii参数保持，以 '['、原逐行JSON及逗号、']'流式组合，与原完整JSON array逐字等价。hexdigest不破坏状态，可继续update；不新增版本前缀或把旧摘要改成新算法。旧normalization仍O(N)，仅去掉额外canonical整表；已排序stream才是O(1)辅助内存，不谎报全链常数内存。

测试用变更前原函数/其实际固定字节作oracle，空/Unicode/引号斜线/数值字符串lex/重复/ReferenceSpec子类/非tuple旧输入/异常边界逐项一致，流式有序/倒序/重复输入区别与反复hexdigest；100001 generator实际tracemalloc证明辅助内存不随N增长，不能先建全refs列表再声称流式。原R2/source/M2/Model批量选集回归、固定非作者复核后合流。只新纯stdlib逻辑，无外部IO/新一般框架。


## 64. M4原来源闭包与有界索引只读前置 V1：已冻结

PROC依§63后实施T893/894新knowledge/application/unification_reference_plan.py+test_migration_reference_plan.py；T895/896明确交接EDGE，独占新resource_reference/domain/repositories/reference_backfill_repository.py+test_migration_reference_backfill_repository.py。索引只读只依现T374 DTO/索引表，不依SourcePlan实现，两组合同相同可并行，不制造T894串行。每卡一生产叶、新叶≤600，不写初始BRR/BRS/guard、Run/ready、不变更任何普通bind/Owner/legacy规则。AC80后继联合namespace及实际Owner最终修订证明未齐，readonly结果均不是写authority，不能以SQL中间after source/ref摘要冒最终namespace证明。

SourcePlan最小DTO：ReferencePageRef(section:sources|conversion,tenant_id,page_index,record_count,object_key,sha256)；RecordPosition(page:ReferencePageRef,record_index)用实际decoder.records零基位置；RecordSpan(first,last)首尾含实际记录；SourcePlanEntry(header:原SourceInventoryRecord,header_at,references:RecordSpan|None,decisions:RecordSpan|None,decision_digest)。Root/retired保原DTO+实际Position，不复制其业务字段。FrozenReferencePlan只原FrozenGlobalInventoryResult、页目录及entries/root/retired定位摘要，无content/config/refs数组。Reader(*,inventory,artifact_store).aprepare(frozen,*,environment,backup_ref,schema_ref,current=None)->FrozenReferencePlan须完整drain原frozen reader（含所有材料/坏尾）才返回；aiter_reference_chunks(plan,*,tenant_id,after_source_ordinal=0,current=None)按已完成source数跳过，0为从头，yield ReferenceSourceChunk(source:SourcePlanEntry,records:tuple[ReferenceInventoryRecord,...]<=199,complete:bool)。零ref仅空complete chunk，无假artifact页。

源header到下个非reference记录闭包，源key精确、tuple键严格增序/重复拒，计数与§63Accumulator核原header.reference_count/digest。每reference调用原source_decision SSOT；H0=Domain digest({kind:'source_decision_stream_v1',source:(tenant,type,id,version)})，每步digest({previous:H,record_type:decision.record_type,data:decision.data})。实际conversion中同SourceKey decision按相同顺序/fold核count/digest，闭集SQL/permission tag跳过，未知/缺/多/倒序/关闭后重开拒。此为当前reader派生内存摘要，不改原artifact/hash/descriptor协议；不缓存全decision/ref JSON。

Root允许前/后/跨页，tenant EOF后核唯一Root.retained_version_count==实际active source数；active/retired root、同SourceKey active/retired不可并存；retired version须有同parent root，retired root不容active source；zero-version root合法。保原lifecycle/digest，不以泛化退役重新分类业务。实际M2已证401ref单源跨5页且Root在refs之后另页，禁止相邻假设。内存仅P页定位+active sources/roots/retired摘要；读取完整图一遍、顺序消费引用页一遍，共页缓存一页，不按source重扫全图。测试真实M2产物及401/10001源槽/多versions、root前后/跨页/zero/retired、计数/digest/decision坏尾、GET/内存/零写。initial_missing只原explicit ID且原missing；未来写口另冻，不能伪造旧BRR或放宽普通new_invalid限制。

索引readonly DTO SourceBackfillHead(source_key,root:SourceSetReadFact|None,source:SourceSetReadFact|None)复用原fact；IndexedReference(id:int,fact:ReferenceReadRow)只包真实BRR.id；ReferenceBackfillPage(items,next_after)。aload_heads(session,*,source_keys:tuple[SourceKey,...]<=200)->按输入顺序tuple，keys唯一且全current具体tenant，空0SQL；恰两有界SELECT：source每完整四键AND以OR，root去重三键AND+原__root__版本（record_kind/ready/effective等原事实不筛成missing），不做独立IN乘积/Source×Root JOIN。alist_source_rows(session,*,source_key,after_id:int=0,limit:int=200)精确四键、实际id seek/order/limit≤200；满页next_after=末实际id，否则None，恰满EOF允许下一空页；无offset/count/伪id。原生TX/currenttenant/非bypass/no_autoflush/strict，Core scalar frozen DTO、零ORM refresh/flush/commit，不改caller pending/map。未知/缺guard/readyFalse原样返回供后继核，不自动修复或冒完整root一致性。测试200keys恰2SQL、交错tenant/type/id/version反例、10001实际ID与间隙、换pagesize同摘要、pending/expired/stale不污染、cursor/foreign/nativeScope SQL前拒。


## 65. 普通新上传短事务应用前置 V1：已冻结

PERM T897/898仅新knowledge/application/space_upload.py+test_kn_space_upload_application.py（INT明确交接，主agent负责集成/真实Service及DI）。依§58/59/61，原重复暂存§62不由本App重做；原SpaceService/DI消费后继另卡，不提前关闭83/84。每次add_file invocation创建独立App，不做跨请求/跨进程恢复平台。

SpaceUploadApplication(*,login_user:原UserPayload,session_factory,admit_upload,make_permission_record,actor_provider,repository=None)。admit_upload为原Service仅对应容器upload_file的可信回调；record factory为原_new_file_permission_record纯SSOT，actor provider返回原Service实际actor对象，无新UserPayload/PermissionActor/凭据。acreate_file(*,knowledge:原已准入Knowledge,parent_id:int|None,prepared:PreparedUpload,file_source:FileSource)->KnowledgeFile；arollback_created()->None仅本实例已记录receipt，无裸ID/rows入参。初始上传保原scheduler，App本身零dispatch/J1/业务引用写。

App要求caller已绑定真实具体execution tenant==knowledge.tenant_id，strict/非bypass/非all；不自行按输入ID切tenant。原actor.home/主体/dataScope必须保真，跨home仅原full-scope super路径，普通/narrowed/SA不增加跨tenant读取或写权。后继Service将在原upload_file授权及可信selected pin验证后，局部绑定整个add_file（含最后原scheduler）的实际tenant并恢复ambient，不仅App内部换scope；防止队列账本落回home tenant。App用现AuthenticatedSourceReadIdentity和原管理pin事实核同原User/actor/credential/scope，所有核验在业务TX外，不复制凭据hash算法、重造actor或以旧snapshot放行变更身份。

新文件步骤：准入回调/身份核验→fresh本App独占native Session短TX→alock_space_for_upload真实Root+原idle guard→原子注册单File/Doc/V1→原KnowledgeUtils按实际ID确定key并areserve→commit明确ACK并私有acknowledge→释放业务Session→原telemetry、原永久blob保存及原临时对象cleanup→原adapter.authorize_created(record,actor) durable prepare/project/finalize正常成功才返回File。沿现同步storage调用语义，不为本前置另加线程/后台调度或新事务框架。make_record/actor原对象，不以wrapper DAO先commit拼半链；所有Blob/FGA/telemetry均无悬挂业务Session/TX，实际key/状态/时间/元数据及effective快照原样。

每次commit前已记录本实例新receipt；commit失联即停止、不ACK/重绑/IO/dispatch，不猜未提交，附闭集阶段/实际自建ID进度并保留可核事实，不复制raw配置/凭据/path。取消或普通异常保持原异常类型/trace，当前owned TX回滚，不rollback caller。成功ACK后才记录可补偿creation；进程崩溃丢registry无自动回收承诺。

pre-dispatch失败由后继Service统一调用arollback_created；按本实例逆序逐项：身份原样且fresh rebind核完整WAITING独立链→释放Session→原creation ledger rollback_created先reconcile unknown再inverse→成功才fresh rebind再次核链、原Repo SQL回收并commit ACK→最后清理本次owned永久blob。SQL删除commit unknown/投影uncertain/链漂移/身份变化均不删blob、不dispatcher、不伪Ready；不能先删对象后发现SQL无法回收。不回收重复上传旧行/历史/别次已提交资源，不触高级历史link/审批/格式前移。新App失败只做本次receipt限定补偿，具体恢复命令后继。

测试真实Repo/原actualPrepared/真实SQL自增互指及原record maker；仅Blob/FGA/telemetry传输边界隔离且不冒真实投影验证。至少含原upload_file容器动作/visible-only拒且零SQL、Root idle锁内、sameScope/home/pin/SA及scope drift、commit前后unknown、blob/投影/SQL回收失败和顺序、改名/历史化拒回收、取消、无业务TX跨IO、同App prefix回收、原时间/effective值/paths。新叶≤600、旧上传/准备/原permission creation-rollback选集组合，非作者独审后合流，再接原Service及DI。


## 66. 原SPACE普通上传入口与实际DI接线 V1：已冻结

INT T899/900仅新test/knowledge_unification/test_kn_space_upload_wiring.py、原knowledge/domain/services/knowledge_space_service.py与knowledge/api/dependencies.py两生产叶，依T898/T890。Service构造增upload_application_factory，API DI注入每次add_file独立新SpaceUploadApplication，session_factory为get_async_db_session，admit/maker/actor使用该实际Service原绑定方法；Domain Service不反向import新App、不借请求Repo Session，不提供缺port时的旧非原子fallback。T901只旧test_kn_upload.py的共享fixture及test_kn_upload.py/test_kn_upload_overrides.py原调用次数期望，接实际App与原nativeSQL、原Prepared；其余原业务断言保留。新测试≤600、原大Service只本入口及必需私有helper，不顺便重构。

入口保持原upload_file授权、实际Knowledge/parent及原idle检查。先拒无具体tenant/绕过/target不符，再将整个本次上传和最后原scheduler绑定实际目标tenant；只恢复原可信management flag/pin，原UserPayload/PermissionActor/home/credential/dataScope不改，异常亦恢复ambient。新App继续锁内实际Root idle校验及原身份复核，Service不以资源tenant字段伪造认证。仅原full-scope super的可信selected tenant可跨home，普通/SA/narrowed不扩权；不改全局_ensure_space_async_task_tenant_consistency。

循环每项只调用原prepare_one_file一次、原get_file_by_condition一次，重复项委托stage_prepared_duplicate，维持md5优先/同名/skip_dedup及FAILED响应/旧链不变。非重复用原真实prepared.file_size按现角色与目标tenant配额在注册前核，不加格式白名单/审批；Service原_resolve_upload_file_source得到FileSource枚举交App。App返回完整File/Doc/V1后才记实际preview cache key，整批预派发失败由同次App.arollback_created限定补偿，禁止原裸IDs/blob先删的_rollback_uploaded_files处理本次普通链。取消也补偿已明确ACK前缀且保原异常；unknown保可核事实、不派发。

所有项目成功后沿原enqueue_or_dispatch/preview_cache_key/callback_url及文件夹/空间更新时间。初始上传不走J1 reprocess、不要求Space.edit/visible等额外动作、不绑定任务模型。实际格式和内容安全错误仍原解析期保失败完整链。原文件夹跨目录批次、网页覆盖、历史重链的整体事务与收据传递后继另冻，本卡不把T083084整项勾选，也不声明跨外部队列分布式原子性。

测试覆盖真实Service+App+Repo+Prepared/nativeSQL/实际DI，Blob/FGA/队列仅运输隔离；原effective快照/媒体、dedup、大小配额注册前零新增链、批次失败逆序、安全unknown/取消、无业务SQL事务跨IO、可信selected super真实队列tenant及ambient恢复、普通/narrowed/SA越界零写。缺DI/入口仍旧writer须真实红，固定独立复核后主组合，真实MySQL组件证据不冒完整接口E2E。


## 67. 原历史link/merge/set-primary原子事务前置 V1：已冻结

EDGE独占T902–905，两新生产叶knowledge/domain/repositories/knowledge_version_mutation_repository.py、knowledge/application/knowledge_version_mutation.py与各自新test_kn_version_mutation_repository.py/test_kn_version_mutation_application.py；每实现卡一叶，各叶≤600，先Repo再App。原VersionService/API/DI此组零修改，后继接线另冻≤2叶。只原link_file_to_document、merge_source_document_into_current、set_primary_version三用例；delete-version/普通上传/移动/Blob/queue/引用删除保护不混入。

Repo锁口alock_link_state(session,*,knowledge_file_id,target_document_id)、alock_merge_state(session,*,current_file_id,source_document_id)、alock_primary_state(session,*,version_id)返回本Repo同nativeSession/TX发行的私有Locked事实；arelink(session,*,state,new_version_no)和aset_primary(session,*,state)只flush、不commit/rollback caller/自开Session、不调用旧自commit仓储。具体事实DTO由同叶声明并交App唯一复用，含实际Source/Target Doc、完整Version与对应File/Root状态；不能由外部裸ID/自造DTO取得重链权。先hint解析关系，再当前具体tenant真实Space→数值排序Doc→Version/File有界规范锁，重读关系拒漂移；ID查询片段≤200，不能每版本查询/独立IN乘积或缺File的INNER丢失。严格tenant/非bypass/no_autoflush，caller pending不覆盖。Doc/Version无tenant列，须完整实际Space/currentTenant/type3及File.tenant/knowledge/type闭包证明。

App构造session_factory与原require_version_management_enabled回调；alink_file(*,login_user,knowledge_file_id,target_document_id)、amerge_document(*,login_user,current_knowledge_file_id,source_document_id)、aset_primary(*,login_user,version_id)。保持真实原UserPayload/actor/context，不自行切tenant/伪造主体。原开关在SQL前读取；每次fresh独占Session单短TX，实际locked Root复用原idle guard，保原源SUCCESS/单版本、目标primary完整、同space、重复MD5和原业务错误/先后语义；next_no锁内max+1。源可无版本的原link规则保留；多版本源继续原现实现拒绝，不按一个过期旧测试放宽。

后端原三write实际只有login dependency+功能开关/业务状态，前端CREATOR/ADMIN按钮不是后端既有gate。本组只整链事务化，沿现入口资格，不新增file.edit/Space.edit/visible或角色门槛，不将缺失的后台权限声称已存在；此处不扩大文件edit适用范围。跨tenant非法链按C3拒，不能借无tenant的Version/Doc访问foreign。事务内新Version、target pointer、旧primary demote、原独立Source Doc/V1清理、similar_status=2一次完成；原File目录/解析快照/对象/索引/BRR均不改，不悄做move。primary保持唯一，foreign/破链/非法多引用原子拒绝。

唯一commit ACK后返回最小结果（document_id/new_version_no或new_primary_version_no及原审计所需space/file名），原Service后继沿原Telemetry。commit unknown停止/保原异常+安全进度，不自动重试或补偿，不能凭返回前异常猜未提交；无外部IO/审计跨业务锁。测试实际native每写阶段失败/外层rollback/唯一primary、缺链/foreign/MD5/次序/开关、401+有界查询及实际App同TX；旧版本测试与精确基线矛盾单列，不删断言假绿。此组辅助原子能力不提前完成T083084或整历史入口/E2E。


## 68. 新上传初始物化时间的双库静态闭合 V1：已冻结

PERM T906/907仅原upload_registration_repository.py与新test_kn_upload_database_timestamp.py（每新叶≤600），测试原SQLite真实UPDATE trigger模拟已有DM updater的“任何UPDATE覆写update_time”，不是DM实库验证。用户只免DM实跑，并未免C2开发规范。原connection.py的无条件updater是现有部署事实，不能为普通上传依赖停用它或借本卡改全平台trigger。

areserve/aset_materialized仅本次独立新File；key登记UPDATE后将真实数据库返回的File.update_time纳入新receipt，原期望其他全部列/Doc/V1/链保持核验。不得把普通上传物化的旧时间逐字不变要求套在既有无条件updater上；不重写历史、迁移M3保持原业务时间及§50运维规则不变。File对象key/metadata仍精确，非时间任意trigger改值须fail closed，当前事务/savepoint/issuer/私有ACK/重绑定边界不变。Doc primary初始化后真实时间也沿原实际重读，不猜server timezone/时钟单调。

测试必须在精确父5e真实失败，再新Repo触发器绿，原47/42+App45+入口组合保留。真实C2 SQLModel/Repository/通用SQL，不判断dialect走分支或加migration-only开关；作者先确认事实，再只窄修新File时间校验且固定交root非作者审。


## 69. 原v2/MCP上传工厂接缝 V1：已冻结

INT T908/909只原open_endpoints/api/endpoints/filelib.py、open_mcp/application.py两个工厂叶与新test_kn_open_upload_wiring.py。实际rg调用链确认除v1 DI外，这两处自行构造SpaceService并调用add_file；必须同样注入每调用新App及独立get_async_db_session、原该Service admit/maker/actor绑定方法。保持原resolved operator及ambient SA/D/MCP principal，不转成web身份、不自己按资源切tenant，不从request-bound Repo Session拼初始链。只factory接线，不改路由/表单/SDK/MCP wire、原资格/回调/解析参数/下载入口，不借本卡重设计协议。构造零SQL、测试缺factory真实红/真实对象与隔离RepoSession验证；既有v2/MCP用例组合，运输fake不当真实E2E。


§66原重建冲突fixture补充T910：仅test_kn_rebuild_write_entries.py声明新必需upload_application_factory（若进入即显式失败）并将原副作用哨兵同时接prepare。忙空间仍须在quota/prepare/factory前失败，idle对照仍到原quota哨兵；不以缺port RuntimeError替代原idle行为证明。只fixture对齐，不改断言/production或令假App声称完整上传成功。


## 70. 原历史版本三写入口与DI接线 V1：已冻结

INT T911/912只原knowledge_version_service.py与knowledge/api/dependencies.py两生产叶、新test_kn_version_mutation_wiring.py。实际生产只有该DI构造VersionService；构造注入version_mutation_application（Domain不import App），API DI用独立get_async_db_session与该原Service._require_version_management_enabled回调构造实际App。link_file_to_document/merge_source_document_into_current/set_primary_version委托同名§67 App方法，原login UserPayload对象传递，返回既有LinkResponse/SetPrimaryResponse，提交ACK后沿原Telemetry参数。移除这三方法的旧自commit多步写，不留无port旧writer fallback；其他read/similar/delete-version保持原消费者。

不新增任何动作/角色授权，不把仅前端CREATOR/ADMIN UI说成已有后端权限。业务资格/错误/次序仍由§67唯一App处理，原disabled开关及busy guard均保。DML期间无请求Repo Session借用或Telemetry IO；unknown不补偿/重试，二次rollback/close不得改掉原异常，必须独立复核关闭后才接线。T913只原test_kn_rebuild_write_entries.py为VersionService补实际App及新的独立native Session factory，保所有原busy/idle/开关/历史断言；不把fake App当native证明、不改10个精确旧基线失败。

T911必须真实DI→原Svc→实际App/Repo→nativeSQL及三原HTTP路由/响应、原审计调用/开关/busy/unknown组合。原请求repos可用禁止调用的sentinel确保不再自commit；真实绑定ID/primary指针和完整旧File列核验，外部审计运输隔离不当完整E2E。新叶≤600，旧Service只这三写及必需注入，不重构整个版本功能。


## 71. 原版本遗留原生测试明确装配 V1：已冻结

INT T914仅test/knowledge/test_knowledge_version_service_link.py及set_primary.py两测试叶。精确旧五路径beda/c340为22绿10红；真实接线后516bea变21绿11红，不能把新增缺port误称旧失败。两helper补actual UserPayload/具体tenant1、实际新App与独立native Session factory；原request Session仅读断言，在该fixture的无pending边界expunge旧identity map，避免跨Session Core写后的陈旧对象。不得借原Session当新App Session/构造fake App/改任何生产资格。

更新已经在精确旧实现失配的HTTP403/412/409期待为现已存在的VersionManagementDisabled/VersionLinkFileNotReady/VersionLinkSourceMultiVersion业务错误，重复MD5/切失败primary的原HTTP语义保持。旧“多版本源可拆历史V1”测试与改动前生产len>=2一律拒矛盾，按§67原现规则改为拒且源/目标整链不变，不借旧测试放宽产品。保其余成功主指针/旧链清理/历史保留/缺失/重复/失败状态断言。不是新增产品行为红；五路径须真实原生闭合并非作者复核。

## 72. 文件夹上传同次登记、末尾派发及限定补偿 V1：已冻结

EDGE先T915916提取现已修复原commit观察者SSOT，再T917918目录Repo及T919920同次App；INT负责T921922原SpaceService接线，旧folder两测试叶T923明确适配。均每实现≤2生产叶、新叶≤600。不得复制file准备/规则resolver、去重、配额、File/Doc/V1 writer、原permission maker或权限policy。保持原HTTP/schema/1000项限制、relative path规范化、深度9、顶层name-only重复、reported-size预检及各组实际大小配额。上传目录仍原upload_file，不调用add_folder引入create_folder动作。

T915916新增domain/repositories/upload_commit_observer.py：UploadCommitObserver.observe(transaction:原TransactionIdentity)、acknowledge(transactions:tuple[原TransactionIdentity,...])->None，以及原root遍历helper。只将原UploadRegistrationRepo._observe_root及ACK中native commit/ancestry/ended校验原样提取，现File Repo仍先核本issuer/initial/tenant/full事实，再委托同一observer并标自身ACK；Folder复用它，不跨Repo窥私有map、不复制监听器。保持原native事件/弱引用、explicit awaited commit ACK后同步retire、unknown/rollback等到当前Task.done清理；不call_soon/call_later/新timer/全局事务框架。原error code及File receipt/API/SQL形状保留，重放原caller after_transaction_end真实SQL SELECT1与89项/C2/上传组合。observer本身不授任何资源补偿权。

新FolderUploadRegistrationRepository同叶DTO NewUploadFolder(name及原creator/updater)、私有StagedUploadFolder/OwnedUploadFolder/local receipt。aregister_folder(session,*,space_id,parent_id,folder)仅current具体tenant/type3/实际父链导出path+level，保存原DIR type0/SUCCESS字段；同caller短TX只flush，拒pending/forged/foreign，不self commit/Session。_acknowledge_committed_folder(*,registration)须原issuer/full事实及共享原root observer ACK才发行Owned；_arebind_owned_empty_folder(session,*,registration)只新nativeTX重核原整行、原父链及实际全状态/种类子项与Doc/Version关系均为空，发行local；arollback_created_empty(session,*,receipt)再重核才删除，不接受裸ID/旧row/跨process。含literal escaped后代path查询，不能SUCCESS筛掉child/INNER吞破链或反复枚举每file；未解析metadata仅全行原类型精确比较。目录父链与空性SQL都由Repo拥有，事务内真实Root由App复用原idle guard。

SpaceUploadApplication新增acreate_folder(*,knowledge,parent_id,folder_name)，只用现原identity/admit/maker/actor/session ports；SQL root commit/私有ACK→释放Session→原make_record(folder)/authorize_created完成父投影后才子。一个实例拥有一次folder请求的所有目录和文件，file仍唯一acreate_file。预派发失败先原file逆序补偿完全确认，再自有folder逆序：fresh私有full-row+empty预核→释放Session→原creation ledger reconcile/inverse→fresh再核/SQL删除commit ACK。unknown/changed/extra child保留树并保原错误，safe进度不含原配置/URL/path/凭据。目录无永久Blob；不能用泛project_delete或闲置裸ID_rollback_uploaded_files。

Service仅内部_application/_deferred成对可选参数串add_file→现helper；私有_UploadDispatchBatch只file/previewKey和folder_paths。普通调用两者都无，保现App/rollback/dispatch；folder入口原授权/真实Root/具体scope预检后，一App一batch建树，再各目录走原add_file，保各组upload_file/最新规则/实际quota/dedup与FAILED响应。共享组不另建App、不局部补偿、不dispatch/更新时间。整次staging全成功后现enqueue_or_dispatch按原顺序唯一tail，再目录/空间时间。staging期间提前更新时间会使自有目录receipt失效，必须延后；第一次dispatch起若queue或时间写失败只保已注册/已派发前缀和原错，禁止反删可能已运行文件。不是队列事务/Worker在途竞态或崩溃自动恢复。

新native三测试叶分别commit/receipt/整行空树、实际App父FGA顺序与文件后目录逆序、原HTTP/DI双目录第二组失败0dispatch/全前缀补偿与selected租户/队列unknown。T923只旧knowledge_space_folder_upload.py与_api.py必要factory/边界fixture适配，保count/depth/name/path/quota/permission/dedup原断言。固定非作者复核和主组合后各叶闭合；网页入口未接时原T083084仍不提前验收。


## 73. 跨空间移动实际投影证据与闭集SQL前置 V1：已冻结

先冻[移动合同](./move-processing-contract.md)P1/K1，来自PROC365行固定候选040e8c749fde3c825488f4dccd84c489c23690572598f73e3e10e24d38074d89，root已全读并核现Runtime.project_parent_change为原ledger计划/模式投影。PERM独占T924925 P1两个叶：permission/domain/repositories/move_projection_repository.py与permission/application/knowledge_move_projection.py；PROC独占T926927 K1两个叶：knowledge/domain/repositories/move_scope_repository.py与move_cutover_repository.py。两组可并行，只冻窄verifier合同，不跨模块Domain依赖具体App/ORM，不另建证据/任务框架。每新叶≤600。

真实native FINALIZED op+CURRENT Mode+完整changes覆盖才签本native Session/TX/issuer私有evidence；K1实际apply最终必须消费P1原对象/verifier，不以stub ready作正向最终证明。scope完整物理File/Doc/Version闭集、双Root→Plan→Job→Item/Retry→File→Doc→Version→TagLink锁序、metadata/tag/稳定对象、所有历史与非索引项规则均见完整合同。原Model/RG/permission策略及hash SSOT不复制；若现唯一metadata/常量实现需从热Svc/worker提取而超两叶，先给root窄接缝登记，不私自复制算法/跨层导入。

Owner/Job/worker/API/查询/源删除消费端尚未授权实现；本前置不开放move kind或提前闭T073074。原move/source+target upload_file，完成归属后同操作continuation不新增target move/edit；source输入保护到item succeeded ACK，failed/obsolete未完成不提前删源/破坏性重建。维持已排除的Worker在途外IO/用户改动竞态，不新增attempt围栏或其他框架。


§73 P1/K1读事实接缝冻结：P1既登记两叶新增aread_parent_states(session,*,targets:tuple[(resource_type,str_id),...]≤200)->tuple[MoveParentState,...]，closed事实为type/id/mode/version/parent_type/id/projection_state/operation_id，native Repo读取并由bridge暴露给K1注入的ParentStateReadPort。缺失/非CURRENT沿原SqlPermissionControlState.mode_for_target的NotReady语义，不猜INHERIT/version0；这是SQL观察事实，不是move授权。evidence核store/model pin由P1在同native TX读CURRENT Catalog SQL权威，Owner不提供自猜hint，proof阶段不开另Session/FGA。复用原release/schema decoder/hash，若确需第三leaf最小SSOT提取先交root登记，不能复制协议。


## 74. 网页新建的闭集材料计划前置 V1：已冻结

EDGE T928929只新knowledge/application/web_link_upload.py及新test_kn_web_upload_material.py（各≤600），并行不写现SpaceUploadApp/热Svc/DI。PreparedWebLink frozen slots保存原file_name/content_hash、markdown_bytes/html_snapshot_bytes、已解析split_rule字符串及服务端user_metadata；bytes/rule/metadata repr=False，不解析URL/下载/读写SQL/FGA/对象/queue，不接受客户端object key或发issuer/ready。DTO只材料，不是授权或新writer。

build_web_link_objects(prepared,*,file_id:真实正int)->WebLinkObjectPlan返回冻结自有对象项（name/content_type/bytes私有）和deepcopy metadata。Markdown key复用原KnowledgeUtils.get_knowledge_file_object_name(file_id,固定md扩展)得到original/{id}.md；HTML沿原preview/{id}.html，metadata.html_snapshot_object_name由服务端强制为该实际ID key，不信input覆盖。Markdown始终一项，HTML空字节不产生PUT项，但metadata仍保原html key语义。原display文件名可为.html而对象仍.md，不改原名称/内容hash/bytes/rule/其他系统metadata值；metadata输出与输入隔离。固定content-type仍原text/markdown与text/html;charset=utf-8。不新建hash/格式策略/对象版本/备份/通用补偿框架。

后继新建App仍实际Repo同TX File/Doc/V1+key/HTML metadata登记、私有ACK后才两Blob及原投影；此处不接线/不提前闭T08384。overwrite保持旧FileID/DocV关系及旧key覆盖/失败语义，不把旧row/key当initial receipt清理、不新增Blob分布式原子性；以后仅实际规则snapshot/完整性与tenant/原guard/调度必要差异另冻。Space默认快照/原Web专用分隔规则的实际producer后继由热Svc唯一消费，不在材料叶复制resolver。

测试用原Utils源码唯一方法及原web key作为oracle，真实Bytes/Unicode展示名/html空非空/深拷贝metadata/强制服务器key/非法内部ID/安全repr及0外IO，缺模块真实红。原Web import/overwrite测试前后实际差异分列，不以材料通过冒完整Web链/E2E。


## 75. 移动闭集纯 Domain DTO 前置 V1：已冻结

T930/T931由PROC在K1实施前抽取新knowledge/domain/schemas/move_processing.py，仅Scope/闭集/ParentState窄口所需的纯DTO、类型与值校验。ScopeRepo显式reexport同一class对象供既冻消费者使用；不复制原digest、projection协议或metadata算法，不引入SQL、Session、App或权限控制面行为。此纯前置作为独立一生产叶卡，Scope和Cutover继续原两生产叶/每叶≤600，不压行、不为行数造反向依赖。真实native Scope/401与10001历史、source-input guard、P1实际证据组合覆盖原样保留。原P1/K1边界和后继未授权范围不变；actor.operator沿原PermissionActor.user_id实际subject事实，S为服务账号ID，不以Job自然人owner替代。


§73 P1恢复窄口补充：原Runtime.parent_change的prepare已提交但mark_projecting前退出时，仅native PREPARED且完整原plan/id/key/checksum已核、实际Mode仍CURRENT且before parent/mode/expected version精确相符，bridge可用原components.state.mark_projecting（原old_target/opid/after parent/实际runtime Catalog release_id）补完原保留步骤，再原reconcile。禁止换actor重建plan。其他nonfinalized先核Mode确属本op和冻结parent/version，不能把其他op blanket fail_closed；特定ProjectionFailed后仅fresh重读同id/key/checksum确FAILED_CLOSED才原inspect/confirmation/recover。原Runtime/State不改，无新投影协议或worker竞态框架。真实prepare-only、不同op、错误parent/version/取消和S/D原operator必须覆盖。


## 76. 网页初始上传实际同次 App V1：已冻结

EDGE T932/T933只既有knowledge/application/space_upload.py一生产叶及新test_kn_space_web_link_upload_application.py；直接复用§74 PreparedWebLink/build_web_link_objects，Repo/observer/Folder/Svc/DI/overwrite均不改。新增async acreate_web_link(*,knowledge:Knowledge,parent_id:int|None,prepared:PreparedWebLink)->KnowledgeFile，同原身份/具体tenant pin/upload_file，不处理URL/规则/临时文件/telemetry/queue。

唯一_register加type(prepared) is PreparedWebLink闭集分支，name/实际Markdown bytes大小/原content hash/rule按材料原值，source固定WEB_LINK；实际aregister_initial得到FileID后纯key计划，同TX现aset_materialized一次保存md key及完整HTML metadata，然后原root commit/私有ACK/释放Session。普通File仍areserve原路径，不复制writer/receipt。Creation增加冻结objects tuple及attempted ownkeys tuple均≤2；每PUT前先记attempted，前后重验原身份，固定同bucket/storage/MIME。HTML空仍metadata有key但不PUT/不当已写。Blob后原record/authorize_created。

同次arollback_created沿原完整双fresh预核/creation inverse/SQL三行删除ACK后才逆序删实际attempted私有keys；metadata或返回File变化不能重定向删除key，未知ACK/链变保资源，旧overwrite不参与。普通单key回收保原语义。新代码预计≤585行，formatter后若超600先报，不压行/不拆第二writer；最多最小提取重复destination/admission，但原identity/session/observer算法不变。真实SQL/DocV1/两PUT间无Session、HTML或投影失败/取消/原unknown、空HTML/篡改返回值/原权限与selected原身份测试，原普通及Folder组合回归。Web成功telemetry留原Service后继。

## 77. 网页实际规则与原入口接线 V1：已冻结

INT T934/T935只既有knowledge/domain/services/knowledge_space_service.py及新test_kn_space_web_link_wiring.py；T936仅必要旧test/knowledge/test_web_link_import_dedup.py夹具适配，原fetch提取测试不改。原入口upload_file/真实Root/tenant一致/idle之后复用§72具体scope包围fetch→去重/原Markdown大小quota→新App或overwrite→旧scheduler/时间tail；保持原User.home/actor与可信pin，不新增visible/file.edit/create_folder/审批或URL政策。原低价值三Markdown跳过hash、其余content优先再name、overwrite=False原两个错误均保。

_build_web_link_split_rule改内部实际Knowledge/file_name输入，唯一KnowledgeUtils.processing_snapshot_for_legacy_request(FileProcessBase(id),knowledge,file_name,file_source=WEB_LINK)及现legacy_rule_from_snapshot生成原legacy字段和_effective_processing；不把默认参数当显式覆盖，system→space/config_version沿SSOT，Web最终11separators/after/overlap0仍原专用规则。新建实际PreparedWebLink→同factory.acreate_web_link，pre-dispatch失败同App自有补偿且保主错误；telemetry在成功返回之后。原scheduler/callback保持，preview改现preview_cache_key_for_split_rule以实际保存rule+原content_hash，队列unknown不回收。现DI无新增生产改动。仅Web新建旧自commit writer与专用cleanup/helper若实际无生产caller则移除；其他旧入口不顺带清理。

覆写只窄接线：用现KnowledgeVersionReadRepository.aget_anchor（独立短只读Session）验证实际duplicate完整File/Doc/V/SPACE同tenant与同当前Root，不新增动作、不自行建V1。原File ID/DocV IDs/统计/primary以及旧两个key覆盖和Blob失败语义保留，不套初始receipt或逆删旧对象、不增备份/revision keys/分布式原子性。原单File字段更新→必要parent project_move→scheduler顺序保留，沿实际新规则快照/preview fingerprint。Doc.path不借此移动全历史，不扩大版本移动业务。原Parent/owner/updater语义保留。新HTTP/native组合含规则变更/cache、dedup/权限/pin/unknown、完整初始链、覆写primary及historical/坏链及旧对象失败边界；原rebuild早拒和普通/目录上传回归。未装配新App前不改原Service，更不提前闭T083/T084。


## 78. 移动保留网页系统元数据的唯一过滤 V1：已冻结

root对3e09361ca独立native反例确认：源schema合法含html_snapshot_object_name:string而目标无时，Scope按removed_fields直接pop会丢WEB_LINK历史文件的快照指针（`/private/tmp/f118-move-web-key-private-probe.log`）。这是§73保系统键的修正，不增字段命名禁令或新产品政策。PROC T937/T938新增纯Domain knowledge/domain/services/move_metadata_policy.py并改原move_scope_repository.py（两生产叶）；原test_move_scope_repository.py补真实反例。

WEB_LINK_SYSTEM_KEYS唯一定义原实际六键source_type/source_url/final_url/web_title/imported_at/html_snapshot_object_name；effective_move_removed_fields(*,file_source,removed_fields:tuple[str,...])->tuple[str,...]只在原WEB_LINK来源剔除这六键，其余来源保持原集合/顺序。无SQL/IO/hash/授权/字段名禁令。Scope每实际row用该helper执行pop；同名非Web自定义字段仍按AC21清理，Web系统键始终保留。后继MoveOwner对单item用同helper构造原MoveMetadataPolicy，来源为已与冻结row/revision核实的实际File.file_source，不假定当前MoveLeaf有file_source属性，不先改DTO/worker/热Svc。Scope仍原digest/类型/DTO同对象/锁序，helper不是第二metadata算法或新版worker policy。Native覆盖六键与Web/普通对照，现Scope/Schema及Cutover真实P1组合保留。


## 79. 移动任务原主体索引 J0 前置 V1：已冻结

[Job合同候选](./move-job-contract.md)原157行来自PERM只读af6e467091fda348cf3f5f2597aba24032a2deb2d15a5b4a8c04b8efbac8e524，root已全读。本次仅§1/J0a/J0b/J0c授权；reserved/ready/execution/worker/query仍候选，不提前开放move kind。Job.actor_user_id只是审计用户；F048 operator原alias等实际subject_id，S不能用auditUser代替。为有界可移植membership增加窄标量事实，不在JSON上查主体/每change扫重试历史，不新增任务模型绑定。

PERM T939/T940新domain/schemas/processing_actor_subject.py及既有application/processing_identity.py（两叶）：ProcessingActorSubject frozen类型/processing_actor_subject(reference,*,tenant_id,actor_user_id,source_space_id)只解析原FrozenProcessingActor闭集的主体事实。校验外层schema/执行tenant/audit/sourceSpace/action move/entry与嵌套actor形状/严格正int和原data_scope管理集合；不将nested actor.home tenant与执行tenant强制相等，保原合法全量超管home1选tenant101；不将subject_id与audit_user_id强制相等。原credential/token/expiry/ceiling/capture/restore算法不复制，历史membership不以旧credential过期否定真实曾接受事实。原move capture/restore只改主体提取委托同SSOT，原payload字节/原身份scope规则保留；四原kind不新增主体gate。

PERM T941/T942只既有models/knowledge_processing_job.py和knowledge_processing_retry.py：各nullable/exclude actor_subject_type String32及actor_subject_id BigInteger，无user/0默认；Job按PK读不增subject索引；Retry非唯一ix_kpr_job_subject(tenant_id,job_id,actor_subject_id,actor_subject_type,accepted_job_revision,id)。普通四kind允许NULL并保原恢复/鉴权；实际move写口后继J1只从同FrozenReference decoder生成，不以模型字段本身授予权限。

INT T943/T944只新Alembic revision单叶：实施前live alembic heads确定唯一parent、实施后单head/offline测试，4 nullable列+1索引DDL-only，沿现helper幂等/create_all已有列索引兼容；不在DDL解析JSON/回填业务。旧正式a1b无三Processing表、当前service/worker均未接move是已核Git事实，不能代实际库COUNT。启用前只读盘点move Job及相关Retry的subject NULL/非法数；存在无法证明主体的trial行failclosed/运维判断，不按audit猜、不在线回填。原四kind NULL不被阻。DM8免实测，C2静态保留。实际J1 accept/ready等待K1私有receipt固定再单独冻，两种request hash不混。


## 80. 移动闭集的真实 owned Root 读取 V1：已冻结

PROC独立native反例已确认：源Folder50下File90为tenant202/knowledge_id10/DIR/path50时，旧Scope裸child查询被全局C3裁掉，错误签完整scope。旧foreign-root测试不能代这个坏后代场景；未修前K1整卡不验收。T945/T946新knowledge/domain/repositories/move_row_repository.py及原move_scope_repository.py两生产叶，测试原test_move_scope_repository.py并可新增test_move_row_repository.py；Scope委托/继承原_rows/_by_ids同签名，Cutover既冻消费者保持，不造通用查询平台。

按原MetadataRepo真实ORM owned Root列作C3锚、raw children沿实际FK加入：File/Doc经真实knowledge_id；Version按file-FK、doc-FK读取入口分别锚其实际Root，保证目录被Version引用、缺File/缺Doc/跨tenant坏链可见或以完整已知集合差异明确拒；Tag经File，实际Job/Item/Retry消费如有则沿真实Job/Root关系。不能bypass、TRUE Root×数据假关联或INNER丢坏链后仍签完整scope。未知目录子项必须从真实FK闭集完整枚举；已知ID集合因锚缺失而未返回必须set/count失败，不当成功遗漏。Root锚辅助列不泄到原DTO/摘要；不返回foreign payload给调用者。具体支持模型白名单与原实际消费者一致，新reader/Scope各≤600，不压行，不借此改worker/权限/接口/Hash。

保NoAutoflush/原事务/只读无DML，200 keyseek与实际C3模式，真实Source/Destination Root锁顺序；Native覆盖foreign后代、目录版本、坏Doc/File/FK、Tag/Job已用关系及401/10001规模，原Scope/Schema/P1/Cutover组合必须继续通过。只在全部closed事实通过后签scope/私有receipt。


## 81. 知识目标 tombstone 精确元组批锁 V1：已冻结

EDGE T947/T948仅原 knowledge/domain/repositories/reference_target_repository.py 一个生产叶及新 test/knowledge_unification/test_knowledge_target_scale.py。固定2116636cd真实native基线已测：owner401文件802次RRT SELECT、10001文件20002次，prelock401为402次；sync/async一致且零DML。预算反例6真红/原Owner控制1绿，/private/tmp/f118-kn-tombstone-candidate-red.log。本卡只消除该重复tombstone读取，不暗改尚存original_statement的OR、业务大IN、original_for扫描；10001 bind/prelock旧OR深度错误独立保留，不能以owner_query绿冒称整条大集合已通过。

私有 _tombstone_statements(entries) 接受完整(TargetKey,owner)事实，按(type.value,target_id字符串,owner)全局lex排序/完整元组去重后每批≤200；SQL同ORDER BY，按(type,owner)分组ID IN并同时限定tenant_id及target_tenant_id==owner，禁止独立类型/ID/owner集合交叉配对。缺owner不猜；bind缺row且无original为零RRT，owner_query缺row可用原可信tenant，foreign owner只能来自原实际绑定证据。每批最多200元组不等于总参数≤200（上界至800），T个元组RRT SELECT预算ceil(T/200)。这是RRT由旧逐目标numeric交错改成全局lex锁序；原业务Space→File numeric顺序不变，不宣称物理锁序完全相同。

保持完整ORM/populate_existing/FOR UPDATE、原_deletion、revision(row,parent,direct,ancestor)字节及TargetKey observation顺序。结果按完整(key,owner)映射，异常/重复行明确拒；prelock所有source versions仅锁其union，实际当前版本observation仍只消费该版本original，不混用证据。原_check_prelock、逐目标_check_tombstone_prelock、session.info同TX私有proof与TransactionIdentity边界不变。不加跨调用/版本/TX缓存，不新增flush/commit或clean-session/pending限制，不改R2 writer、FGA、动作、身份、原权限和外部接口。先真实红测试提交、后生产；新旧相关native及语义矩阵、固定非作者复核后闭卡。新测试叶≤600；生产目标保持≤600。下一卡再冻结同Repo便携IN/OR和证据分桶，之后才接KN/Model source_read，禁止本卡越界。


## 82. 移动祖先路径沿既有空路径编码 V1：已冻结

PERM固定932b09e3c独立native反例：合法nested tree仅Root目录file_level_path由空串换NULL，移动其后代File就被move_parent_path_invalid误拒；空串对照通过。原SpaceService认可NULL/空串为根路径，两者不构成新业务政策。探针/private/tmp/test_f118_k1_932_independent.py及/private/tmp/f118-perm-k1-932-independent.log保留原样。本卡PROC T949/T950仅原move_scope_repository.py一生产叶及原test_move_scope_repository.py：祖先路径比较用现唯一move_path_ids/path_ids的解析结果和原祖先前缀比较，不直接拿raw None与空串比较、不复制第二路径解析、不改持久原编码。严格非法路径、缺祖先、跨tenant/space、循环/错误level等原断言保留；不增加历史层级修复或新深度限制，不改DTO/hash/FGA/worker。先同等native红测试后实现；Root独立原probe的NULL格转绿、9路径组合与作者外复验后闭卡。另一个历史File在所选folder而主版本在folder外的边界仍独立调查，本卡不偷偷决定其归属。


## 83. 目录覆盖历史File的整版本归属 V1：已冻结

PERM固定932b09e3c原native两对照及真实Web覆写producer确认：全空间md5去重可命中历史File82，overwrite移动其path到目录55，Doc/primary path仍原位置；这是§77明确保留的已有合法行为。选择历史File本身Scope通过，但选择包含它的目录会被move_document_outside_selection误拒；AC19与移动合同§4要求目录子项及整版本，不能当坏链隐藏。原证据/private/tmp/test_f118_k1_932_independent.py、test_f118_k1_932_web_producer.py保留不改。

PROC T951/T952接T950，仅原move_scope_repository.py与新增test_move_scope_history.py；先真实反例后实现。保原逻辑Doc.path被选中目录覆盖时的relative路径，以及原显式File选择的destination_path规则。仅Doc.path不在任何所选folder且无显式File归属时，遍历实际Version→File一次，按各实际File旧path中被选中folder的原relative映射，按Doc建立候选目的(path,root)集合；只有一个实际候选时整Doc及全部历史沿它一起移动，其他在树外版本也保持ID/链并进入同一Doc目标路径。不得逐Doc再扫全部Files/Versions、不得只迁所选历史或猜Doc字段，不改版本/对象key/原主版本/权限与metadata规则。

若同Doc有多个不同候选目标路径，不任取第一条：预检明确归属冲突，可通过显式选择该File并指定目的目录消除歧义；原Doc自身有选中逻辑路径或显式File选择时沿原优先级，不新增动作/角色/修复任务。候选范围只选中subtree实际覆盖的File，不把扩展出来但不被选中folder覆盖的外部历史误作候选。测试含真实Web覆写后移动、root/嵌套relative、两历史同候选、分歧拒绝及显式File规则；原9path、metadata系统键、完整闭集、0DML/401/10001线性预算不降。单Scope≤600，若自然表达超限先报root另冻纯路径叶，不压行或偷偷增叶。此卡只闭AC19范围，后继Owner/J1仍未开放。


## 84. 知识目标便携查询及原证据线性匹配 V1：已冻结

EDGE T953/T954接T948，仍仅原knowledge/domain/repositories/reference_target_repository.py一生产叶；新test_knowledge_target_original_scale.py与既有test_knowledge_target_scale.py保语义预算。真实旧10001 bind/prelock因10000 OR/20006参数触SQLite深度1000；401三槽original_for候选482403。实际flow删除及APP版本批写均形成各版old/new完整union，稀疏S版本各1互异目标时S=T，所以不保留每版×全union目标页的查询乘积。

业务SQL producer改按numeric ID排序每页≤200，完整Root全部页先于File全部页，原ORM/populate_existing/锁阶段保持；原original_statement只内部消费者时改plural有界producer，single bind按完整(type,id)≤200键页、按type分组ID IN，保原tenant/source_type/id/version与完整ORM，禁止类型/ID交叉组合。结果一次按(type,id)分桶，_facts仍调用原original_for但仅该桶，冲突五字段及第一原native候选沿原算法/该SQL返回次序，不新按owner/slot排序；旧SQL无ORDER，不能承诺不同DB优化器物理顺序一致。original_for作为读侧现consumer的SSOT签名/算法不改。无跨调用缓存/新flush/commit/pending限制/权限变化。

多版本physical prelock独立按已选source_version≤200页读同exact tenant/source_type/source_id且仅KN两type的原BRR，每SQL真实PK seek≤200行，cursor取raw页最后id。raw(type,id)在精确选中键set中才纳入union，过滤前不构造TargetKey、不让未选target坏证据触发计划、不读未选version；不依赖匹配行推进或版本×targets双循环。P=ceil(S/200)，B=所选版本里的KN原行（含未选target），原证据流SELECT≤P+floor(B/200)，每raw行一次键集过滤；保原ix_brr_source和PK，不增DDL。bulk只签physical union/proof，不给observation挑original；后续每版独立bind仍只用自己版本桶。该上界不包括业务/RRT锁及后续每版verification，T/RRT排序仍O(T log T)，不泛称全系统线性。

新测试先实测固定本卡父上的原10001错误与401/1001候选、稀疏401/1001source版本读取预算；再测10001 native成功、每页SQL参数/返回行、末页全未选/刚好200及foreign/混type同ID/同key三槽冲突、版本隔离/旧proof复用拒绝。原§81RRT预算/原Owner与batch组合保留，10001成功需实际alock/prelock而非捕异常即绿。新Repo≤600，超限先报不压行，不改source_read两叶或跨模块库；独立固定复核后闭卡。

## 85. 删除闭集事实与现仓储前置 D1 V1：已冻结

PERM固定5aa46b80d只读候选经Root核原DeleteRepo266行及实际Version Facts。T955/T956最多两生产叶：新knowledge/domain/schemas/direct_delete_scope.py与既有knowledge_space_delete_repository.py；新测试test_direct_delete_scope.py（规模可另test_direct_delete_scope_scale.py）。本卡只读物理闭集/可选原生锁读，不签授权或计划、不写/cutover、不接Service/worker；旧prepare/cutover暂不改，避免纯读委托暗降旧行锁。新Schema只DTO，不跑SQL/hash；VersionDocumentFact/VersionRowFact复用现knowledge_version_mutation_repository原类型（纯类型引用可TYPE_CHECKING，生产Repo构造原对象），不复制版本算法。

DTO：DeleteSelection(resource_type:knowledge_file|folder,resource_id:int)；DeleteSelectionIssue(positions:tuple[int,...],reason:not_found|type_mismatch)；DeleteResourceFact含id/tenant_id/knowledge_id/file_type/file_name/file_level_path/level/status/user_id/update_time以及repr=False原object_names元组；DeleteUnit含selection_positions/resource_ids/version_ids/deleted_document_ids/unregistered_file_ids/processing_file_ids；DeleteScope含tenant_id/space_id/selections/resources/documents/versions/units/issues、repr=False原八字段cleanup_identity及完整object_names。所有facts全局去重只存一次，unit仅ID，不复存整版本链。严格原生ID/类型，NULL/未知status作为明确unsupported事实供后继分类，不猜SUCCESS。

aread_delete_scope(session:AsyncSession,*,space_id:int,selections:tuple[DeleteSelection,...],for_update:bool=False)->DeleteScope。无新客户端数量限制；空选择参数合法后空scope/0SQL，不借空结果证明Root存在。非空要求原生外部TX、严格具体tenant/拒bypass，真实own/type3 Root；no_autoflush/Core scalars，不刷新调用方ORM/新Session/commit/DML。Root锚沿真实FK读取raw子项，坏foreign后代不能被C3裁掉或INNER吞；已知ID不完整明确拒。查询至多200行+明确201 lookahead，PK seek/精确ID页≤200；for_update按Root→实际File/Doc/Version稳定PK锁及重读比较，不能JOIN带入无序Root锁。目录字面路径用分隔符及autoescape，不让/20匹配/200；原NULL/空路径/level编码保留，不新增深度/层级修复。

主版本选中扩整链；历史单删仍只自身、其他版本/Doc保留；目录含后代和真正删除范围扩展的外部历史siblings。完全无Version的FILE按原行为保留于删除scope并列unregistered；已有V却缺Doc/File、跨Root/tenant、引用DIR或复用File均拒。批量Doc/全部链及File FK，以现纯检查/_check_links等SSOT验证唯一primary/指针/完整链，不每Doc两SQL、不要求全部历史File.path等于Doc.path；实际祖先同Root/DIR、前缀/无环核对。实际原对象键集合仅原File object/preview/bbox/thumbnails及File ID字符串，不扩覆盖语义。

D1输出状态而不新增单删gate：原单删FILE1–7仍候选；batch FILE1/4/5为processing，2/3/6/7候选；DIR自身已知状态不判忙，unknown/NULL unsupported。目录/扩展版本内任一FILE忙则整unit忙，后继App分类，不部分删目录。先归并重复/被有效祖先覆盖请求，后以真实删除Resource/Version/待删Doc集合重叠合并unit并保全部原positions；仅共享仍保留Doc不合并，避免DSU键丢失。后继R3将每unit全部resource_ids（含DIR）映KNFILE精确targets并接Coverage/原Plan/hash/真实F048证据。D1不新增force/动作、对象IO或删除许可，不提前闭原T105–108。

原生测试：无版本FILE/空目录、完整与历史链、401目录/Doc、10001历史链有界预算、NULL路径、前缀邻居、跨租户坏后代/缺FK不隐形、原pending不flush、目录WAITING/忙历史/unknown、真重叠与仅共享保留Doc两格。生产新增叶≤600、原Repo增量自然≤600；若实际最小实现超过先报Root拆职责，不压行或暗增第三叶。固定非作者复核后闭接缝，不冒称最终删除/升级完成。


## 86. 同原SourceAuthority的KN/Model读取性能 V1：已冻结

Root已实测两个source_read_target_repository的真实SQL：401/1001目标每目标3原槽位，original匹配482403/3006003候选；KN RRT402/1002、Model401/1001，且business IN params超过1000（W6记录）。T957由INT先新test_source_read_target_scale.py真实native红测试，T958由EDGE在T954之后仅knowledge/domain/repositories/source_read_target_repository.py与llm/domain/repositories/source_read_target_repository.py两叶实施；两个叶各≤600，不改SourceVerifier/SourceOwner/App/权限/writer。

保原公开方法/DTO/最后资格重验、原scope issuer/identity/TX/purpose/credential、SourceRepository精确source版本及完整source-set校验。仍用原SQL scalar/no_autoflush/经授权bypass读取实际source owner tenant，不切换ambient tenant或合并origin/target身份；原DB identity_map不污染。saved originals一次raw(type,id)键set过滤、一次按完整key分桶，各key仅交原original_for/_original该桶，保同key多slot冲突及native次序；Model过滤目标IDset不可在每original行重建。transient仍无original且缺owner不猜，不把read facts当binding receipt。

业务Space→File、Server→Model各原阶段/数值顺序不改，只每ID≤200精确页，继承拓扑/五默认锁与显式共享策略照旧。Model同步saved读和async saved/transient均实现同语义。RRT使用各模块现write TargetRepo的纯_tombstone_statements完整tuple producer，再with_only_columns选原operation/stage+完整type/id/target_owner/tenant定位；不调用写侧权限/current_tenant或返回ORM对象、不复用ORM_add_tombstones。local结果校验完整expected tuple/重复/tenant，构造原DeletionEvidence。RRT统一全局lex索引顺序、每批≤200，明确是由旧逐目标numeric读锁改变，与§81及原Model写侧对齐；不声称物理锁序未变。KN direct/ancestor去重，Model仅实际owner tuples，缺owner零RRT，原原始四owner谓词不降。

真实预算：401/1001三槽original候选变1203/3003（另一次O(B)建桶），T个删除标记tuple的SELECT≤ceil(T/200)；business精确IN每SQL≤200 IDs、代表性单owner测试总params≤250（不是声称任意200tuple多owner总参数≤250）。native还测10001 transient/actualbusiness分页、同步Model路径、全局lex、缺失/ancestor/legacy/Root共享及未选scope/坏TX早拒。原knowledge/model read Owner、source runtime/native及composition组合保留；0DML/原subject不变，局部优化不代正式升级/E2E。原PrivateRoot baseline4绿是旧复杂度见证，不删或改其原断言；正式新预算必须先实际红后实施。


## 87. 原任务接受值与canonical投影SSOT前置 V1：已冻结

J1a候选复核发现真实接缝：TransactionIdentity绑定当前nested/root；外TX签的K1 reservation不能放进后来SAVEPOINT。原不可改native探针/private/tmp/test_f118_k1_j1a_transaction_probe.py验证1绿。后继公开move-create将接原confirmation/key/actor，在同一私有SAVEPOINT中才签/consume真实K1原receipt；重放按真实Plan→Job接受hash判定，不放松issuer/TX。本段仅记录后继方向，不授权现在实现accept/ready/worker。为避免旧JobRepo↔MoveRepo循环和第三套hash，先PROC T959/T960两生产叶：新domain/schemas/processing_job_acceptance.py及原processing_job_repository.py，测试新test_processing_job_acceptance.py。

同对象搬原ProcessingConfiguration/NewProcessingItem/JobRequestResult/JobLease/ItemLease以及_digest到纯Schema（原defaults/validators/Field/slots行为不改），旧Repo显式import reexport保持既有消费者同类型/同函数。_digest原json sort_keys/ensure_ascii=False/separators/allow_nan=False与sha256字节原样，既有所有digest消费者不换算法。原acreate中完整manifest的target校验/expected_space/排序/重复及processing_snapshot复制逐段提为processing_manifest；原request_facts键集/metadata-only两个字段提为processing_request_facts，旧acreate在原先次序和相同位置消费。新Schema不含SQL/clock/UUID/权限/credential/receipt/mutation，不成为第二任务平台；不额外复制完整大payload或把compact manifest当接受hash。

原_actor/key/settings/nonempty gate、metadata空scope私有proof、事务/锁/幂等/flush/四kind结果全部保留；本卡不开放move、不改metadata参数/claim/retry/worker，也不改Job SQL schema。测试先固定四原kind完整canonical oracle及排序/同对象reexport/NaN/重复/invalid scope、原错误顺序；原Job/acceptance revision/cutover/query/metadata/identity组合及固定作者外检查通过才闭卡。新Schema≤600、旧热叶只搬原职责与薄消费。若最低实际投影还需第三叶先报Root。J1a exact public signature、compact字段及read replay将在此与K1完成后再单独冻，不沿未实现旧候选的跨TXreceipt API猜接口。


## 88. AC-80 namespace适用范围产品决定：已确认

2026-11-09已收到用户最终确认：沿用同一模型在知识空间现有的动作范围，并登记预期变化。该适用变化来自文档库转SPACE的资源类型统一；全平台单独移除use不改变其他资源的动作范围。保原model_key、非use动作选择、管理等级、主体/Grant/Source/可见集合，标准模型按既有SPACE规则派生动作；自定义不补未选动作，纯use仅保可见与撤销，rename不并edit且文件edit不扩展。正式停服后逐模型冻结前后适用动作与差异原因，只有上述适用变化和可见代use属于允许差异；其他差异阻断切换。联合namespace/Catalog计划可按此口径继续冻结开发，尚未执行正式发布或迁移。

本节解除前文历史记录的AC80待答条件，不追认任何未实施接口或正式发布。权限联合计划仍须按精确新接口另冻、真实native对账及MySQL停服/恢复验证，不能把产品确认记成T157158或M3/Coverage完成。


## 89. 移动Job真实reserved受理与原接受重放 J1a：已冻结

依实际K1 fixed47563与acceptance SSOT9d253；原Job合同§2外部传reservation候选由本节取代，旧receipt/TX不放松。T961先native新test_move_job_reservation.py（规模可test_move_job_membership.py），T962仅新domain/repositories/move_job_repository.py+原processing_job_repository.py两叶。MoveJobRepository(*,cutover:MoveCutoverRepository,clock=...)持稳定实际issuer；旧JobRepo可选move_jobs注入，只三个新薄delegate，没有配置时明确failclosed，不借普通构造开move/worker。单向import新acceptance Schema/K1/models，MoveRepo不import旧JobRepo，不靠lazy import消环。

公开aget_move_request及acreate_move_reserved均接(session,*,source_space_id,confirmation_id,plan_digest,idempotency_key,actor_user_id,actor_reference)，不接caller items/parameters/裸receipt/Model hint；返回JobRequestResult|None（read）及JobRequestResult（create）。read依据exact tenant/kind/key真实Job和Plan→Job：move/source/原actor与两subject标量、原plan_digest/plan_request_hash、consumed operation_id==Job UUID、target Job.space及完整接受hash/compact投影一致；无existing而Plan已consumed冲突。重放不重验已改变的File before/当前Root R/G，不重复消费或写；并不授执行资格，后继Owner仍fresh原credential/ceiling/业务准入。当前key换confirmation/actor/body拒，unknown commit后只按真实持久事实reuse，新TX旧receipt拒。

create要求原生外部TX/具体tenant/拒bypass/无caller pending，先进入本次SAVEPOINT，按原Source/Dest Root数值→Plan→Job锁后再判重；只新分支在这个SAVEPOINT内调用原K1.aprepare_reservation（scope从原Plan恢复并按实际库重新核）、建立真实Job/Item并消费同issuer的aconsume_reservation，UUID只原res.job_id。异常回滚自身SAVEPOINT，外catch再commit无半Job/半consume；不新开Session或commit、不跨IO。read无写/no_autoflush；create中root锁与K1实际边界统一。旧普通acreate精确拒move_index，不改变四原kind的非空/metadata空proof/lease等规则，不提前开放Service available_kinds。

只从res._scope/原Plan唯一样本单遍建映射并构造每个participates的NewProcessingItem。snapshot闭集：move_schema=1,leaf(原Scope序列化该MoveLeaf),file_before,file_after,document_after,version,metadata_policy{retained_fields,removed_fields}；实际File来源用原effective_move_removed_fields，保网页系统键，不修改Worker。零参与项合法但logical scope必须非空，无dummy；Job accepted/pending_dispatch=True且started/finished为空，必须等待后继真实logical ready才可能成功。双Root八配置只原source/destination IDs、各model_config_revision/index_generation、各_digest([index_name,collection_name])；space_config_version固定0，move不消费默认解析快照。

compact Job.parameters闭集：move_schema/operation_id/confirmation_id/plan_digest/plan_request_hash/source_space_id/destination_space_id/destination_folder_id/scope_digest/changes_digest/logical_file_count/logical_document_count/logical_version_count/index_item_count/configuration。Job.space=destination、actor_reference保原source frozen，subject两列仅同processing_actor_subject解析。完整Scope只原Plan一份；完整snapshot只Item；Job.scope_manifest仅原target三元组/expected_space_id/expected_parent_id/processing_snapshot_digest。Job.request_hash沿原processing_manifest+processing_request_facts+_digest完整snapshot投影，不能以compact manifest或plan_request_hash代替；replay用persisted UUID+原Plan投影重建同接受事实，lease/state/attempt及当前配置变化不进入该hash。每次完整重放/受理线性，不每Item重新展开Scope或遍历全部链。

aoperator_membership(session,*,job_id,operator_ids:tuple[int,...]<=200)->frozenset[int]：空0SQL，严格正int非bool/native/currenttenant/noautoflush；原Job typed主体由真实frozen ref/两索引标量核一致，Retry只同job/tenant、合法typed subject及实际已接受revision，按(subject_type,subject_id)选真实代表PK再≤200批读原ref，原早期Retry也保留，不只最新、不过期旧credential否定接受事实。只查compact Job/Plan header/有限Retry refs，不每projection读全PlanScope/Job manifest/整Retry历史JSON；索引列不是授权。不猜audit_user，承认原F048 operator仅numeric alias的既有限制，不宣称新typed权限协议；foreign/NULL trial无法证明则failclosed。

native至少同TX/跨TX重复、同key冲突/换key已consume、未知commit后实库查询、外catchcommit原子性、真假issuer/0items pending、S/D/audit不同及旧Retry成员、401/10001接受线性/轻量membership、原四kind/metadata全回归。J1b ready/零项retry/generic finalize与claim旁路封闭、J1c双Root execution、Owner/Worker/入口仍后继另冻，当前只内部Repo能力且不发布运行入口。新Repo≤600，实际超限先报Root拆职责，不能压行或暗第三叶。


## 90. 原OwnerScope精确引用流 R3读取前置：已冻结

T963先新test_inbound_owner_stream.py原生反例；T964仅原resource_reference/domain/repositories/reference_repository.py一个生产叶。只新增aiter_inbound_for_owner_pages(session:AsyncSession,scope:OwnerTargetScope,*,limit:int=200)->AsyncIterator[tuple[BusinessResourceReference,...]]，不实现D3授权/披露/App或修改旧公开方法默认结果/顺序/错误。原Repo为历史大叶，只必要helper/流增量，不借此大重构压行；新test叶≤600。原owner_page LEFT SourceSet完整身份/record_kind/source/ready/effective/revision和原错误是唯一校验算法，两方法抽共用private SQL/rows helper，不复制canonical或Verifier注册/receipt算法。

先原_check_scope完整验证及limit严格1..200；随即无await捕获独立TransactionIdentity、具体owner、原registered scope identity、detached raw(type.value,id)元组（不能保原TargetKey对象别名）。SQL始终只用这份私有初始集合，每≤200 exact targets一组、每组BRR.id seek每次≤limit行，按目标组序/组内PK序，不承诺跨组全局BRRid锁序；foreign Source tenants只按原target-owner scope读取，原SourceSet完整LEFT join保证缺损显式拒、不因暂停过滤引用，不增加space-contents范围。

内循环O(1)检查捕获TX.assert_current/session/current_tenant_id（原方法拒bypass/无具体tenant）及同Repo weak scope registration identity，必要同authority/owner常量检查；不每页重新扫描全部receipts/targets，不读Verifier私有字段、不造子scope/新authority。尾部再原_check_scope完整校验；异常、提前aclose或取消均不能证明检查完成。后继D3必须完整耗尽并通过原identity/Coverage尾验后才返回任何可展示impact/确认结果，流本身不是删除许可。篡改scope/原TargetKey在yield之间也不能改变后续SQL目标，末验拒绝；旧page首尾完整验证照旧。

预算单列：T目标/R引用/G=ceil(T/200)，SQL≤G+floor(R/limit)，每SQL≤200 IDs/≤limit rows，代表性KNFILE页总params≤250；原TargetOwner/D1/Disclosure成本独立测，不泛称全系统线性。流完整scope验证仅首尾各一次（编译/排序另计），内guard常数；无T×引用页。真实401/1001/10001目标、稀疏/密集/整200空尾、完整身份LEFTjoin缺口/旧scope复制/切TX/tenant/bypass/Key篡改/取消/无DML及旧owner_page/Model impact控制。真实owner receipts/native Session，不fake scope或SQL字符串替代。Controller预auth和SourceDisclosure先不实现，避免新增派生child删除gate或持本SQL事务跨FGA。


## 91. 迁移等级floor独立受控事实 P0：修订后已冻结

旧正式API已证use=3+download=1模型原tier3，直接移除use会掉到1；但普通visibility3+download1原全局tier1是已有合法语义，不能用visibility_level普遍取max或改旧oracle。原§91 generic visibility floor候选撤回，尚无生产实现，不沿用其算法。实际旧native2格及十格AST探针保留；它们证明迁移问题，不能用来证明可改变普通visibility语义。

T965先新test_permission_retired_use_floor_schema.py，T966仅permission/domain/models/catalog.py与permission/domain/services/model_policy.py两生产叶。新增nullable Integer retired_use_level_floor defaultNone（Model私有/exclude），在CustomModelSelection与DerivedPermissionModel为optional server-owned事实。canonical只有该独立字段非None时才保其floor；visibility_level原逻辑完全不动，原test_perm_policy的download1/tool visibility3仍派生1。field严格native int非bool、1..4，只有CUSTOM且有合法visibility provenance、原visibility_level与floor一致才接受；标准/无provenance/非法floor拒。不据空动作任意授可见，原空模型/allow_same规则不动。

canonical _model_payload只在floor非None时纳入该事实；默认None的普通/标准旧payload与checksum完全不变，旧legacy_source_key不覆盖，不用sentinel/第二授权模型。模型存储仅事实且nullable无server猜测默认，旧行NULL；本卡不让API或bootstrap签发，HTTP请求继续拒写。Model/Policy各历史大叶只窄增量，不无关重构压行，新测试≤600。原两生产叶Plan+Policy方案未实施，Plan此卡不改。

正式floor签发后继仅当旧CUSTOM before确有effective use、移除后仍有具体动作且其最大等级低于原合法derived_level时，取原等级；pure-use/普通visibility metadata均不设，原等级一致性门继续保留。Snapshot/typed codec/Catalog保存加载与编辑原样携带、正式DDL、签发及namespace声明/hash/verify必须后继逐卡冻结装配；缺接缝前不发布、不能关闭T157158。T965/966只证明默认None存储和原canonical不变/受控floor类型，不假报完整pipeline。

原namespace_type_mappings仅空或library→space、须进入原Plan/hash且不改action scopes的方向保留，但其接口本阶段仍未实现；现有SPACE需后继逐资源对Grant/Source/可见矩阵核验，不能仅Catalog成功就放行。


## 92. 退役use管理等级中性结构准备：已冻结

Root已读Alembic AGENTS，实施前实际alembic heads唯一f118_move_actor_subject（2026-11-09），新revision f118_retired_use_floor父接此head，编写后再验单head及原database/test_alembic_single_head。INT T967968单revision仅permission_model.retired_use_level_floor Integer nullable/defaultNone、无server_default，无JSON解析/回填/签发/seed/新授权；shared table_exists/column_exists大小写兼容守卫，缺整个表留原Model.create_all，已有列/值保持，重复upgrade无改。标准DDL/C2静态保，DM8免实测。downgrade仍要求停服一致备份恢复，不删除业务或猜历史值。

旧Model行新列NULL，不据visibility_level/derived_level自动补；正式floor来源只后继已核旧mixed Plan，Snapshot/API/codec/联合verify未装配前不发布。正式停服→备份→此中性DDL→全局实际权限盘点/基线冻结→计划/转换时序不变，脚本不探测停服。升级演练/MySQL验证另执行，不以SQLite原生DDL替代。测试覆盖缺文件红、旧表无列/已有列3/缺表/create_all同形/重复/保旧行及同parent/DDL-only，禁止迁移扫描业务表推导floor。


## 93. 删除精确引用SQL事实收集 D3a：已冻结

T969新test_direct_delete_reference_query.py（规模可另test_direct_delete_reference_query_scale.py）先红；T970仅新knowledge/application/direct_delete_reference_query.py单叶≤600。DirectDeleteReferenceQuery(*,runtime:ReferenceBindingRuntime,coverage_factory:Callable[[AsyncSession],CoverageRepository],scope_repository:KnowledgeSpaceDeleteRepository|None=None)；acollect(session:AsyncSession,*,space_id:int,selections:tuple[DeleteSelection,...])->DeleteReferenceFacts。显式真实runtime且repository.verifier同一issuer，actual D1/Owner/stream/coverage公口，不接caller Scope/receipt/Actor/权限callback/新Session/披露。原生已有外TX/具体tenant/拒bypass/入口无pending，保持no_autoflush；这只是内部SQL事实，不对外路由、不授删除许可。后继App才在SQL前原选中目标资格、SQL close后SourceDisclosure；本卡无FGA/provider/外IO，不新增派生child delete门槛。

同叶detached immutable DTO：DeleteReferenceSlotFact(reference_id,unit_index,source:SourceKey,slot_key,target:TargetKey,source_revision)全部reprFalse；DeleteReferenceFacts(scope:DeleteScope,references:tuple[DeleteReferenceSlotFact,...],sources:tuple[SourceKey,...],source_counts,slot_counts,unit_source_counts,unit_slot_counts,observed_source_tenant_ids,coverage_epoch,inventory_hash)，除epoch均reprFalse。计数tuple((SourceType.value,int),...)固定六类，unit数组按D1原顺序；Source/version全局/每unit各自去重，slots按真实每BRR计。无ORM/OwnerScope/receipt/can_*或自造hash，不复制全版本链。调用方不得把内部DTO直接HTTP回传或作为确认authority。

步骤固定：捕获TX/tenant→factory须真实CoverageRepository SQL ledger adapter→globalReady+tenant六类ready→D1 for_update=False→一次resource_id→unit索引（全部unit资源含DIR转KNFILE，绝不SPACE/contents范围）→非空targets一次原averify_owner_targets/target_owner_scope，精确覆盖并stateVALID、owner/space同D1→完整耗尽新stream→单遍构造detached命中/计数/observedtenants→globalReady重验observed/原epoch/inventory，再own六类ready→TX/tenant尾验→才返回。任何末页/coverage/上下文/取消异常无部分成功结果。

空选择或all issues无targets，不造空OwnerScope，但仍Coverage首尾；D1空scope不证明Root存在，mixed保issues，只查实际units；busy/unsupported/unregistered不在此分类过滤。全局ready验证observed外租户，不把source tenant冒充target owner，不过滤paused/history/legacy直接引用，不把无依赖当可删除。真实status端口可在native测试隔离，但Owner/receipts/ReferenceRepo/LEFTjoin必须真SQL。

预算索引O(T)、聚合O(R+S+U)，排序另计；owner receipt验证合3T（创建1+流首尾2），不是T×pages；OwnSpace真Owner SQL 2ceil(T/200)+1+ceil((T+1)/200)，stream≤ceil(T/200)+floor(R/200)，T0均0。Coverage12 local+2global公口调用，适配器SQL单列；D1预算独立，输出内存O(T+R+S+U)不声称恒定。native含primary/history/DIR/外sibling、space-only不阻、跨unit/source多槽/外tenant受限原事实、空/mixed/legacy、篡改/尾验/缺adapter/epoch源集变化、401/1001/10001实际SQL及无DML/FGA/新Session。原Actor与展示接线必须后继另冻。

## 94. 零Item逻辑ready持久槽 S0：已冻结

只读native原probe三断言证明：K1 logical receipt在后来SAVEPOINT被拒、回原TX可consume；现generic item claim/finalize有未ready缺口，不算功能完成。0Item没有Item.checkpoint，immutable params/manifest/state/error不能伪装proof。因此先T971测试test_move_logical_marker_schema.py、T972仅原knowledge/domain/models/knowledge_processing_job.py一叶，加move_logical_marker:dict|None默认None、private exclude/reprFalse、Column(JsonType,nullable=True)，无默认ready/索引/actor/model绑定。新test≤600。原四kind构造/序列化/字段与scope_manifest、原acceptance哈希不受影响；只存事实，Shape/ready证明留B1，不在Model猜actor或签发marker。

T973/T974 INT新test_move_logical_marker_migration.py及单Alembic revision v3_1_0_beta1_f118_move_logical_marker.py；实施前live唯一head为准（当前f118_retired_use_floor），仅同表nullable JsonType列，shared幂等/缺表留create_all/已有列数据保持，无JSON解析或补marker。MySQL原JsonType None可能是JSON null，旧加列为SQL NULL，后继以Python None/合法dict判定，不写MySQL JSON函数/不假设SQL IS NULL即全部未ready。DM静态JsonType→CLOB，用户免实测。DDL-only/单head/备份恢复规则同§92，未启用B1前不可发布move入口。

后继B1新MoveJobReadyRepo+旧JobRepo：同原receipt TX、不再后来nested；Item marker全写/flush后，尾验/consume原receipt，最后才写Job marker（零项同原子写succeeded），partial Item commit仍因Job markerNone被拒；claim JobLease需在ready前允许，封item/guard/finalize及checkpoint覆盖。候选Job marker闭集move_schema/job_id/plan_id/request_hash/after_scope_digest/projection_evidence_digest/index_item_count/ready_claim_generation，最后generation只是历史，takeover/retry不清/重签。B1/retry/J1c exact API后继另冻，此S0不假报缺口已封。


## 95. 原权限floor事实完整快照/typed artifact P1：已冻结

Root已核实际SnapshotRepo select(*table.c)+_record(fields(cls))可自动读新字段，但codec为显式_SCHEMAS/_ROWS且强制字段全集；因此T975新test_permission_floor_inventory_roundtrip.py先native/typed红；T976仅原permission/migration/f118_plan.py与原knowledge/application/unification_inventory_codec.py两叶，不能只加Baseline漏codec或改第三Snapshot叶。PermissionModelBaseline最后加optional retired_use_level_floor=None，保旧positional顺序，严格None/native1..4非bool、CUSTOM/合法visibility且visibility_level==floor、原derived_level>=floor；std/不一致事实拒，借原canonical校验不另造授权规则。

_compile_catalog显式携带已有floor给CustomModelSelection，afterModel保同floor，原model_key/等级/nonuse/actions/allow_same/active/legacy_source全部一致性门继续；此卡只保已有事实，不签发旧mixed的新floor、不加namespace mapping/发布。标准floor拒，合法existing floor在use已退休时可正常重建；真实old mixed use3/download1的新签发仍后继，不放宽blocker冒完成。

codec permission_model闭集schema新增nullable严格floor，None/3 native记录、页、完整graph roundtrip且原canonical/hash统一；多/缺/float/bool/越界/被改数据或hash明确拒。新字段是中性DDL后正式M2盘点事实，旧准备artifact不冒正式基线；默认None不改变动作语义，不宣称旧preparatory artifact字节相同。SnapshotRepo无需修改但必须native实测从实际PermissionModel列读回floor（exclude不丢事实）。新test≤600；原大叶只必要增量。原库存/graph/permissions plans/verify全回归，无SQL/FGA写/自动签发/Coverage ready。Catalog API/control_state读写携带、正式签发与联合namespace后继另冻，未全部闭合不发布。


## 96. 既有受控floor的Catalog保存编辑与CURRENT核验 P2：已冻结

T977先真实API/SQL反例，T978仅permission/application/catalog_api.py及control_state.py两叶。_load_models从原PermissionModel携带retired_use_level_floor至CustomModelSelection，STANDARD raw非空明确拒；_replace_children保存canonical同字段；_apply_changes初始selection携带已有字段，原replace保留，CREATE_MODEL保持None。CURRENT canonical/原SQL列比对加入floor。不得开放HTTP字段/响应、不得签发新floor、不改GrantSnapshot/运行授权或普通visibility语义。HTTP extra-forbid继续拒caller floor，既有合法floor经过load→edit→save→reload/CURRENT不丢；非法/raw漂移fail closed；默认None普通/标准checksums及动作等级原控制保留。历史大叶仅必要窄增量，不扩大权限功能。测试新叶≤600，真实native存取、API允许原操作及原失败顺序、CURRENT含非管理员路径；作者外固定复核后闭组件。正式旧mixed签发/namespace仍后继，不以本卡完成T157158。

## 97. move逻辑ready原事务封口 B1：已冻结

T979先native反例，T980只新knowledge/domain/repositories/move_job_ready_repository.py（≤600）+原processing_job_repository.py两叶；原MoveJobRepository不改。新MoveJobReadyRepository(*,move_jobs:MoveJobRepository,clock=...)使用原move_jobs.cutover唯一issuer，不反向import旧JobRepo，不复制hash/manifest/lease算法。amark_move_ready(session,*,logical_receipt:MoveLogicalReceipt,lease:JobLease)->JobAccepted，返回原JobAccepted类型；旧JobRepo可选move_ready注入及薄委托，缺配置对move ready/item路径fail closed。若原JobAccepted实际类型/返回不足，先报告Root，不暗造新DTO。

同receipt当前TX，不能后来创建SAVEPOINT绕TransactionIdentity；Owner后继须在K1.prepare/P1之前创建共同SAVEPOINT。原Job claim/renew仍可在未ready时取得JobLease，供K1执行；只封move的item claim/_guard_item/finalize及checkpoint覆盖。Job marker严格闭集move_schema/job_id/plan_id/request_hash/after_scope_digest/projection_evidence_digest/index_item_count/ready_claim_generation，generation仅首次历史，不因takeover/retry清除或要求等于新generation。校验原issuer/TX/实际JobLease/Plan与完整接受hash、实际after scope/P1 proof；不能用caller裸dict或state猜ready。

mark先分页读取原真实items，按原_digest构造checkpoint.logical_move，绑定Job marker摘要、实际target三元组、expected space/parent和原snapshot摘要；保全部其他checkpoint键。每页≤200，flush Item标记后尾验原lease/receipt并consume_logical，最后才写Job marker。零Item同原子marker+succeeded/finished/pendingFalse，非零保持running，原item状态/attempt/result不改。中途异常即使外层catch+commit也只有partial Item，无Job marker，故执行口必拒；Job marker落盘后不能把未知提交当未成功补偿。重试新receipt接线留B2，不签旧receipt替代。

move执行读沿原metadata模式total_count/defer大manifest、claim SQL LIMIT1，不能每item读全Job manifest/全部pending集合；checkpoint API保私有logical_move、拒caller重写，普通kind行为不变。native覆盖0/非0、错issuer/TX/subject/plan/hash/lease、partial Item catchcommit、取消、takeover保历史marker、改snapshot/target/marker拒、checkpoint保留、原四kind控制和401/10001有界SQL/无重复全scope验证。此卡不接API/Owner/worker/RG或用户异步竞态。若两叶不能保持现lease/actor约束，先报Root拆合同，禁止复制旧算法。


## 98. QA既有生命周期端到组件核验：已冻结

Root核原W4实际KnowledgeModelReferenceApplication及KnowledgeService：QA create/base、model change/rebuild、clear/delete已接真实R2，同Knowledge事务。T093/T094只核闭该既有实现与补原生consumer测试，不为满足剩余任务数重写业务。T093原依赖T092只是顺序编排，QA不调用跨空间移动；改实际前置T018/T258/T052与既有KN模型生命周期，不等move完成。新test_qa_bindings.py≤600，原生Knowledge/QA/File/Model/R2/原UserPayload，external projection/index/object/queue是测试边界。测试actual sync/async create wrappers与base、缺embedding沿原拒绝不新增zero-model创建、投影/R2失败回滚、clear保模型/源/引用且只清本tenantQA内容、delete解除实际outgoing、失败完整回滚、改模型保旧+pending直到原QA finalizer。type仍1，不加入SPACE处理Job或新页面。已覆盖且未改生产的行为用现有红绿历史+本次组合证明，不伪造新缺陷红；如发现真缺陷先记录实际红再窄修原叶。旧v2 FakeUser/DAO测试未代表真实新消费者，应后继改为同真实事务行为断言，不能放宽UserPayload校验。


§98补充原行为证据：固定旧1b83a1c6的delete_knowledge只在type1显式删除QA表。当前model_reference_repository._content_deletes无条件包含QA表，原普通资源清空意图不应扩展。T093新增原生实际consumer+SQL语句断言；若确认真实红，T094实际根因叶改为model_reference_repository.py，仅保原QA条件，不改Service事务/外IO顺序/授权。旧协议两个FakeUser用例迁入test_qa_bindings.py并保留原测试名、改真实consumer原生fixture，保“QA清、NORMAL不触QA”原行为断言；列入T093写文件，不能用移除测试掩盖新行为。


## 99. 旧effective-use mixed模型原等级受控签发 P3：已冻结

依P0/P1/P2已携带独立字段，T981先native真实旧Catalog输入反例，T982仅原permission/migration/f118_plan.py一个生产叶（历史大叶只窄增量），新test_permission_floor_retirement_signing.py≤600。_compile_catalog只在CUSTOM、原floorNone、before effective含use、去use后仍有active具体动作、具体动作最高等级低于before合法derived_level时，签floor=before derived。签发前严格验证原derived等于before原effective动作的原canonical最高等级（native int1..4非bool），不据人为抬高或不一致baseline签权限。原use是active且有合法原scope/level，原selected/effective一致性门继续；visibility provenance来自原effective use.resource_types与已有受控metadata，不改action scopes，不改legacy_source_key、不用sentinel。已有visibility_level若与原tier冲突明确阻断，不覆盖已有证据。

pure-use不设floor，去use仍同tier/普通metadata模型不设，已有floor按P1原样携带；普通visibility3/download1全局1控制不变。原全部非use选择/动作、key/name/kind/active/configscope/allow_same和derived_level一致性仍强制；floor变化只允许本次确切受控签发的预期值，不放宽为任意max(metadata)。签发进入原after Baseline/canonical checksum/plan checksum，typed codec沿既有完整字段，不增新wire；verify重建同一pure计划，篡改/移除floor失败。实际SnapshotRepo→plan→typed artifact→Catalog保存/重载/CURRENT完整native组件闭环，不开放HTTP写floor或新发布流程。

P1临时测试“旧mixed仍阻断直到后继签发”在本卡按精确新功能更新，保留真实old mixed native oracle与旧普通模型对照，不能简单删断言；原被调高use的其他pure模型也须维持其正确旧tier，不编造不一致before以求通过。测试还含inactiveuse、不选use、无具体动作、原derived坏值/等级不一致、既有floor、原scope不覆盖SPACE、自定义未选动作不补、artifact/CURRENT篡改以及原纯可见可撤销控制。此卡不实施namespace mapping/资源SQL/FGA发布，不能关闭T157158或正式迁移验收。若需第三生产叶先报Root，禁止改核心Policy普通规则凑迁移。


## 100. 模型影响复用精确流并保原v2摘要顺序：已冻结

Root核ModelReferenceService._dataset仍每BRR页调用旧alist_inbound_for_owner_page：重复全T scope验证且每页SQL带全T目标，未因KN新stream自动解决。T983先实测旧多目标/多引用native预算反例，T984仅resource_reference/domain/repositories/reference_repository.py及llm/domain/services/model_reference_service.py两生产叶。新测试test_inbound_owner_global_stream.py及test_model_impact_scale.py各≤600；既有test_model_reference_sources.py的测试端口随实际新消费更新但原v2摘要oracle/100001slots峰值/无效ID拒断言不变。

既有aiter_inbound_for_owner_pages加global_id_order:bool=False（严格bool），默认分组顺序/原KN消费者完全不变。True用同原精确target≤200分组、同_inbound_owner_statement完整LEFTjoin/source-set验证与捕获cursor的分页，按各组原BRR.id有序页作有界多路merge，产出的每页≤limit且全局BRR.id递增。首尾完整scope验证各一次、内TX/tenant/issuer/registration guard O(1)，保持初始raw targets副本和尾部篡改检查。不得每组重新签OwnerScope、每页再验证T receipts或用单个超大IN回避分组。每组仅保当前≤limit页，堆每组一个候选；空间O(T+G*limit)而非O(R)，G=ceil(T/200)，SQL≤G+floor(R/limit)，参数≤200精确targets的原上界。不会承诺物理行锁全局ID顺序；原分组锁已有变化，全局merge只保证输出/摘要顺序。完整耗尽前不提供完成证明，取消/异常/部分关闭不假成功，无新Session/DML/flush/FGA。

ModelReferenceService只改_dataset消费True流，保原_reference binding字段、原sha256 f118-model-inbound-v2 prefix和ID/row hash更新字节、scope/owner/coverage/legacy/管理员/原身份/受限来源及cursor context算法。不得改为排序全部R row/hash列表，也不因改遍历顺序使原plan/cursor摘要漂移。已存在100001slots精确hash与<1MiB单目标端口测试仍需绿，native多组交错ID必须与旧page全局序列逐字节一致。旧native5种模型、跨租户摘要/禁止共享Root编辑与失效/尾Coverage测试保，真实401/1001/10001 sparse/dense SQL+候选验证预算独立量测，0引用也测完。若两叶实现不能保原语义/预算先报Root，不另造影响runtime/算法。此卡闭性能接缝，正式Coverage adapter/计划执行/外部入口仍后继，不直接勾T111112。


## 101. 创建者业务成员转换之前的正式事实准备：已冻结

非作者native证明type0/user7转3后Member仍空，“我创建的”漏9000；PermissionLoader仍从Knowledge.user_id取owner，不能泛称creator权限丢失。Member无tenant且无自然键unique，M2目前只盘control.UserTenant、没盘SPACE Member；禁止M3盲insert/选first/改角色、重跑F048 exporter或重建Grant。完整后继拟沿原ResourceConversionCommand追加受控子计划：旧owner自然键不存在且无其它CREATOR则insert原SPACE/CREATOR/ACTIVE默认；唯一同owner ACTIVE/CREATOR则keep全字段；owner其它role/status、重复、其它creator、缺原creator事实均在M2阻断。其它非creator成员原样保留。insert模板时间来自原planned_at；before完整set含空集，after实际新PK与set摘要进入原Outcome/resume，原Root+Member同owned SAVEPOINT/checkpoint。此完整方案仅方向，本节先实施事实准备，不签计划/写Member。

T985基础设施定义例外：只新application/unification_inventory_schema.py与原unification_inventory_codec.py，将原_spec/_SCHEMAS/_CONVERSION_COMMON/_CONVERSION_FIELDS完整搬为唯一wire schema，旧codec同对象import reexport；不得改任何既有key/spec/canonical/封闭验证，原全typed/plan/codec测试证明既有字节完全相同。原codec597行已接近600，提纯schema为后继成员事实腾位置；不复制第二套规则。纯定义迁移不伪造红，原控制必须绿。

T986先native成员事实测试，T987仅新domain/repositories/unification_space_membership_repository.py（含detached DTO/列SSOT≤600）与原codec消费。apage_headers(session,*,after_id:int|None=None,limit:int=200)->InventoryPage[SpaceMembershipHeader]按真实own tenant且type0/3 Root PK读≤200/201 lookahead，header含knowledge_id/tenant_id/knowledge_type/creator_user_id/member_count，member_count按该精确Root页一条分组COUNT（SPACE+canonical business_id），零显式0；不得每Root查。apage_members(session,*,knowledge_ids:tuple[int,...],after_id:int|None=None,limit:int=200)->InventoryPage[SpaceMembershipRow]只接≤200严格唯一positive原Root IDs，原生TX/具体tenant/拒bypass，验证全部原Root真实own tenant且0/3；再按exact canonical business_id及SPACE、PK seek≤200/201返回完整Member raw列+派生knowledge_id/tenant_id，枚举归原value，原时间/nullable/subject/model/binding/pin全保。空IDs0SQL不证明Root存在。无tenant Member不能靠C3假装过滤；只可信Root派生tenant、不切tenant或跨owner猜主体。

私有header/member typed记录和row_digest由原codec canonical，Member字段闭集全覆盖真实SQL列、不丢受控source字段；显式schema而非dataclass自动接受。完整nativeCount/Member页含空、QA/retired2排除、foreign同busID通过ownRoot分类原事实、wrongtenant/缺Root拒、枚举/nullable/时间/多source行都保、200/401/10001 Roots总SQL随Root页/Member页增长，零DML/不flush调用方pending。此leaf只读、不把冲突值修好或当有效；非canonical业务ID/全局孤儿的全局探针和M2 preflight/planbuilder接线须后继单独冻结，不能当前漏读便宣布正式基线完整。旧无Header的artifact不得用于新正式转换，§101不关闭T163164。


§101字段定义接缝T988由Root单独维护提纯后的wire schema叶，在T986真实红之后、T987消费之前：新增space_membership_header闭集(knowledge_id/tenant_id/knowledge_type/creator_user_id/member_count/row_digest)与space_member闭集(派生tenant_id/knowledge_id+全部真实Member列+row_digest)，不改任何已有wire。T987仍仅MemberRepo+codec两叶，不把Schema修改暗算为第三生产文件。私有库存允许原角色/状态/nullable值作事实，业务冲突判定由后继preflight；fact不构成可见性或授权。


## 102. Catalog显式namespace声明与一次逐模型适用矩阵 C4：已冻结

用户已确认AC80按同模型现有SPACE能力并记录预期差异。原NORMAL0/QA1都属于knowledge_library，不能全局字符串替换资源；本卡先签Catalog声明，资源转换资格/SQL/FGA后继。T989真实pure/native Catalog红测，T990仅permission/migration/f118_plan.py+f118_verify.py两叶；新test_permission_namespace_catalog.py≤600。

CatalogRetirementPlan尾追加namespace_type_mappings:tuple[tuple[str,str],...]=()，以及namespace_applicability_changes:tuple[ModelApplicabilityChange,...]=()。同文件新frozen ModelApplicabilityChange字段model_key/from_resource_type/to_resource_type/before_action_codes/after_action_codes/reason；动作tuple沿原Catalog canonical有效动作顺序，不复制资源/Grant/subjects。build_catalog_retirement_plan新增同名mapping keyword，仅接受严格native tuple空或(("knowledge_library","knowledge_space"),)，其它/重复/反向/链/可变结构拒。每模型仅一次按before Library与after SPACE精确action scopes过滤，reason固定document_library_to_knowledge_space_existing_capabilities；actions scopes/非use选择/key/tier/active/allow_same不变，文件edit不扩。矩阵包括未变化模型，精确一行/model，不Nresources×M重建。action差异包含已单列use退休，并能明确现有SPACE动作差异。

_compile_catalog在原effective use scope与原受控visibility provenance合并后，只有types含knowledge_library且声明mapping时额外保knowledge_space可见provenance，保留library（QA及历史资源仍用），不把SPACE加入CatalogAction.resource_types。pure-use仅可见可撤销，mixed floor沿§99严格签原tier；无library provenance不无端补space，标准按原canonical。全局既有SPACE资源的实际Source/可见集合不得因此放宽，后继资源级原before矩阵/范围洞校验必须阻断非预期变动，不能Catalog成功即放行。

非空mapping及完整matrix进入原_catalog_payload/checksum；空mapping必须matrix空且保持原payload/模型/checksum字节。_resource_context及verify_catalog_retirement重建须显式传原mapping并比完整计划，伪造/删mapping或matrix/改理由/动作/排序/after metadata均拒。C4尚无target namespace资源证明，所以非空mapping的resource builder/verify当前统一failclosed，不让旧resource==before验证误绿；后继C5才显式签actual before/after与target Mode。旧无mapping全部行为继续。测试含pure/mixed/自定义未选动作/标准editor manager差异、QA library marker保留、原scopes逐项相同、原Grant不变/不发布，以及401/1001模型矩阵候选次数预算。不得改Policy/CatalogAPI/codec第三叶，正式artifact接线另冻；本卡不关闭T157158。


## 103. 原move失败重试算法的逻辑阶段与typed主体 B2：已冻结

B1只封ready/item执行，旧aretry_failed仍拒零项逻辑失败且未写typed Retry主体；T991先真实native反例，T992只原move_job_ready_repository.py+processing_job_repository.py两叶。旧四kind重试算法不复制、不改；只在原aretry_eligibility/aretry_failed各自move分支消费ready纯校验，原RetryReceipt/锁/CAS/幂等hash/Job状态reset/失败pending reset/计数刷新/flush顺序复用。新test_move_job_retry.py（规模可另叶）≤600。

MoveReady新增纯retry_logical_pending(job,counts)->bool：markerNone且无实际/已存succeeded才为逻辑阶段；markerNone但有success明确failclosed（未接旧trial不猜补ready）。marker存在沿require_job_ready原闭集验证、原historical generation规则，返回False；不清/改旧marker。aretry_eligibility继续detached scalar投影，不为move加载/expire公共manifest；必要原move专用小SELECT取id/parameters/marker/request_hash/claim_generation/succeeded_count，普通kind不多读JSON。真实_state_counts总数须等total_count；零项未ready终态失败can_retry=True、finalize_only=False，非零未ready只有原failed/pending可重置，不能把运行中项当可重试。零项已ready成功不再retry；伪造零项ready失败不变成普通可重试。非零ready原failed/pending/finalize-only行为保持。

aretry_failed仍单原算法，move先校原完整资格再改行；零项逻辑重试允许无Item进入原accepted/pending_dispatch和真实RetryReceipt，item_count=0，原revision/hash幂等重放/CAS保持。非零move仿既有metadata defer大processing_snapshot，失败pending reset原字段，success的attempt/result/checkpoint/snapshot/marker字节不动；不每Item重读Scope/manifest，不另起SAVEPOINT、Session或commit，不重签原K1 receipt。

move RetryReceipt.actor_subject_type/id必须由原processing_actor_subject解码当前真实retry actor_reference（tenant/actor_user_id/source_space_id取原Job实际compact事实），不据audit numeric代替，也不覆盖原Job.actor_reference/typed原主体。新receipt写两typed标量；旧同key重放除了原request_hash还须与本次decoded主体相符，NULL/错typed旧trial failclosed，不在线补猜。新重试主体可不同于原受理主体，沿已授权retry事实保留，由后继Owner重验实际来源/目标动作与credential ceiling；本卡不引入权限动作或任务模型绑定。

native覆盖零项logical失败→retry→fresh K1/P1 logical ready成功，nonzero before/after marker，same-key actor/key/CAS冲突、service account/user类型和最新membership读取、伪旧NULL receipt拒、partial success原值与原Job actor保留、false/True marker拒、wrongtenant/bypass/丢scope/总数不全、过期R/G obsolete，原四kind组合以及401/10001避免全snapshot/manifest重读。此卡不装Owner/worker/API，不把内部资格当授权；B1固定窄修与独立复验通过后才实施。


## 104. 原NORMAL创建者成员纯子计划 B：已冻结

T993先native事实驱动反例，T994仅新domain/schemas/unification_space_membership.py与domain/services/unification_space_membership_plan.py两叶各≤600。纯值/规则，不SQL/IO/Session/UUID/now/Grant。新frozen CreatorMembershipPlan字段tenant_id/knowledge_id/creator_user_id/membership_action(insert|keep)/before_member_count/before_member_digest/existing_creator_member_id(nullable)/creator_template_digest/planned_at(nullable)。Schema同文件creator_membership_template(*,knowledge_id,creator_user_id,planned_at)输出原SPACE创建者Member全部默认列（除自增id）和签入时间，必须与实际aadd_space_creator/Model defaults等值，不复制授权算法。原Reader DTO留原Repo；Schema不反向import Repo/Service，后继Writer可安全复用模板无循环。

plan_space_creator_membership(header:SpaceMembershipHeader,members:tuple[SpaceMembershipRow,...],creator:CreatorFact|None,*,planned_at)->CreatorMembershipPlan|None。真实完整头/成员属于同一tenant/root/canonical SPACE business_id，严格native typed/唯一递增MemberPK/count相等，原完整raw成员set按既有fingerprint digest签入（含实际ID/来源/nullable/time；派生tenant/root也绑定），O(R)一次检查/索引，不能每用户/每Root重扫全R。已存在SPACE3只保完整事实、返回None，不修其历史成员；QA/retired2输入拒。NORMAL0要求header原creator_user_id为positive native int，并有同ID真实CreatorFact.exists=True；物理存在但软删除delete1仍历史owner，不任换owner。原M2 resources.user_id关联在后继builder接线再比，本纯函数本身不是迁移授权。

NORMAL0无owner自然键且无其它CREATOR→insert；唯一同owner CREATOR+ACTIVE→keep全部原字段；owner已有其它role/status、重复owner行、其它用户CREATOR、缺creator事实/不完整/跨scope明确阻断，不提升/激活/选first。其它用户非creator行原样保持，不据其成员身份授新Grant。insert模板SPACE/CREATOR/ACTIVE/manual与其余原模型默认值，create/update_time均原planned_at（严格naive/秒精度），不现场取now；keep既有完整row除ID的digest作为templateDigest、planned_at=None，existingID保原。旧Member来源、relation/grant/binding/pin全冻，不将Member当新F048 Source。

测试复用真实MemberReader和raw模型默认作oracle，空/keep/各冲突/跨tenant/错Root/缺末页/重复PK/坏Header/软删除creator/全部source字段保留；401/10001其它成员单遍预算，不建用户×成员表。此卡只纯子计划，不改原ResourceConversionCommand/codec/M2 App/M3写，后继显式冻结接线；不冒原“我创建的”迁移缺口已执行修复。


2026-11-09完整主树c456回归5560绿/4红/7原占位skip：T094只保QA而漏保SPACE共享仓储既有问答内容清理，Root修正为QA或SPACE沿原清理、仅NORMAL不发QA表DELETE；原space native delete/clear两红是现成红证据，保持原断言不改。T983另两旧test_model_target_scale原要求全targets单BRR SQL，现与§100明确精确分组预算冲突；只改旧oracle为ceil(T/200)次空引用查询及每查询<=204params，保llm_model4/RRT ceil/总SQL<=40/每IN<=200/结果/租户断言。生产模型流不改、不为旧1次查询回退超大IN。T094/T983暂重开，修后加入同选集复验；这四红不能记作既有失败。


## 105. 显式目标Mode的资源namespace before/after纯计划 C5：已冻结

C4 fixed80cd已独立PASS；T995先真实Mode/Grant/Assignee/VisibleSource native事实红测，T996仍仅permission/migration/f118_plan.py+f118_verify.py两叶（历史大叶必要窄增量，不改原Compiler/Policy/SQL/CatalogAPI）。新test_permission_namespace_resource.py（规模可另叶）≤600。ResourceRetirementPlan尾追加after:PermissionResourceBaseline|None=None及namespace_target:ResourceModeBaseline|None=None；builder生成实际after，旧无mapping after与before同对象即可，旧_resource_payload不纳新增字段、原checksum保持；非空mapping将namespace_target/完整after纳checksum。

single build_resource_retirement_plan新增namespace_target keyword；batch build_resource_retirement_plans新增target_modes iterable。空Catalog mapping只允许旧None分支，原API/行为/字节保留。非空Catalog mapping每个resource必须显式给实际typed目标Mode，连未变化QA/existingSPACE/其它模块也用原Mode作明确声明；漏target不可默认“不变化”。batch目标与before严格逐一配对/zip_longest，缺/多/非法item拒，显式两空流可空结果（纯值本身非迁移authority）；context/Catalog重建只一次。不得仅凭Catalog library→space映射盲改每个library或parent：NORMAL0/child物理归属资格仍由后继FrozenGraph Reader核验。

targetMode只可与原Mode完全相同，或显式library→space资源rtype，或原parent_type library→space且parent_id原样；其它tenant/id/resource_id/mode/version/projection_state/operation_id以及parent_id全部保持，反向/其它namespace/改owner层级/清parent拒。资源改名后Grant行同ID/modelkey/state/version/projection，只有rtype随资源改；Assignee tuple原样，含CREATOR protected/sourceRef/locator/fingerprint/subject/userset/children/version/state，绝不因新Member重建。原ID保留；不新增授权/动作，file edit/rename原规则不变，原非use选择仍严格，根适用差异只C4已签矩阵。

ACTIVE与RETIRED VisibleSource全保原rowID和原字段，仅明确改资源rtype和原Compiler派生tuple_fingerprint；contribution fingerprint不含namespace必须不变，source_version/operation/migration_item/state不擅改。先原before canonical/visibility核验，逐Grant建sources桶，再一次按实际原GrantSource→原VisibilityProjectionCompiler._compile_source生成同contribution索引，匹配原每行（含inactive backing source用于RETIRED），namespace后的canonical tupleFP从同SSOT取得，不复制hash算法。原Compiler._assert_same_canonical_source保护其它immutable字段，不得把old namespace sources直接传after compiler当碰撞然后放宽Compiler。遇无canonical原Grant/Assignee映射的历史row明确block/report，不按subject或新Member造来源。metadata版本字段沿原Compiler的既有可变字段规则保原stored值，不趁迁移重写或新增通用漂移修复。

原direct可见subject集合必须逐资源相同，source identity/contribution集合一致；可见tuple改名用原Compiler._aggregate_deltas产生旧删新写，parent-only不伪称新增visible来源。Mode parent的FGA完整关系、继承闭包与全部实时tuple核验属于后继namespace Publisher/全量对账，本卡只提供before/after事实，不假报已投影。既有SPACE因新增可见metadata出现原scope洞/非预期Source/subject变化则block，不能发布新可见。after actual verifier重建完整同计划并与plan.after精确比，不再盲比plan.before；新增target/after篡改及原before mutable坏证据拒，完整迭代才证明batch完成。

测试含NORMAL显式root变、QA相同Mode控制、existingSPACE不变/原scope洞拒、只parent变child、protected creator/department userset/同subject多sources、inactive/RETIRED原ID/版本/来源保持、坏tuple/contribution/缺canonical历史阻断、wrongtenant/改ID/反向/缺target/晚batch缺项、空mapping旧checksum；401/1001资源和独立models预算context编译一次、按真实G+S候选，不资源×全Catalog重编或Grant×Source积。本卡不改codec/preflight/Reader/M3权限表/FGA，不能关闭T157158；正式资格与写authority后继单独冻结。


## 106. 原Member全局完整性实际前置 A：已冻结

T997/T998仅原unification_space_membership_repository.py与unification_control_repository.py两叶；新native测试test_migration_space_membership_global.py（可另规模测试叶）≤600。新增MemberRepo.avalidate_global_integrity(session)->None；由原ControlRepo.avalidate_global_integrity末尾真实await调用。原M2 arun已经调用Control门禁，不另建CLI或新Session。先前四张控制表的检查保留。只读阻断，不修角色、合并、删除或授新Grant；本卡不关闭正式M2/M3任务。

Member无tenant：先全局原SPACE成员PK顺序seek，每页≤200/201，不漏其它租户、inactive、其它角色、其它membership_source。Python对business_id做ASCII canonical positive decimal且<=2**63-1严格校验，拒空白、+、前导0、非ASCII数字、零、负数、超范围及alias。然后每页唯一Root.id≤200的直接numeric IN，LEFT JOIN真实Tenant.id numeric PK核父存在、tenant positive且真实Tenant存在。不得CAST Root.id/Member.business_id做全表join，不做Member×全部Root/tenant积，不逐member查父、不把无法归属的行因inner join吞掉。合法原QA1/retired2父记录可存在但原样保留；只canonical parent能分类，未知knowledge type阻断；CHANNEL完全排除。

全局读只在方法内部no_autoflush+strict_tenant_filter+短bypass_tenant_filter查询包裹，不改变ambient tenant；入口及每await前后核原concrete tenant/原TransactionIdentity。缺TX/ambient bypass/tenant变化或TX变化failclosed，原pending无flush且不被覆盖；异常退出恢复上下文。不可把global读变成普通scope Reader宽泛开关。成本O(M)原member扫描+每页有界索引父查，内存O(200)；空SPACE零误写，401/10001规模证明参数上限、页数、无CAST/笛卡尔积，真实脏alias/orphan阻断原Control入口。

## 107. P1精确操作者候选读取与原move断点分类：已冻结

T999先native红测，T1000仍仅permission/domain/repositories/move_projection_repository.py与application/knowledge_move_projection.py两叶各≤600，不改knowledge Owner/worker/Job或业务权限动作。Repo同叶新增frozen slots MoveOperatorCandidate(resource_type,resource_id,operator_id)，bridge导出并转发：alist_operator_candidates(session,*,job_id,targets:tuple[(resource_type,resource_id),...])->tuple[MoveOperatorCandidate,...]。真实canonical Job UUID、exact target tuple≤200、folder|knowledge_file、canonical正ID（沿原operation_key）、去重或拒重复须一致且输出按输入顺序。空targets返回空；不存在原operation正常无candidate。不接任意operation_id、LIKE前缀或全Job扫描。

原operation查询仅实际tenant+每个exact canonical idempotency_key闭集，scalar fields足够校验tenant/key/RESOURCE_MOVE/resource scope_key与positive native operator；每资源最多一条，重复/坏row拒。原native scope/TX/no_autoflush/pending控制沿用，跨tenant operation不返回；不加载tuple ledger/JSON/其它Job/所有RetryReceipt，不做FGA或写。candidate只是定位事实，不是原operator已准入证明，不替代CURRENT pin/Mode/tuple/checksum核验。后继Owner每页候选IDs经真实J1 aoperator_membership≤200验证，再为每expectation给actual candidate和当前actor的小允许集；原alist_owned_operations仍完整验证scope/pin/original ledger与Mode，不能只信candidate。无原operation也要允许本次合法actor新建；不把允许集扩大到全部租户用户或只猜原+最近retry（会遗漏中间重试操作者）。

原move-processing-contract §2 continuation政策不变，补实际阶段：无operation或本job PREPARED且Mode仍before CURRENT时，fresh核实际冻结selected file/folder.move和目标upload；本job已经nonfinalized且Mode已PROJECTING/FAILED_CLOSED或CURRENT after时，只有同持久接受操作+当前credential及原narrowing+fresh目标upload+完整本job owned ledger可恢复原P1 forward，不能当完成证明或跑index；本jobFINALIZED且Mode精确CURRENT after才可作已投影subset依据。foreign operation/错parent/version/裸status或marker拒。全部P1完成后fresh K1 prepare+durable evidence+logical apply+Job ready同TX commitACK后方入index。新typed主体retry仍先当前selected.move+目标upload，partial状态无法满足则拒；不能借旧主体接受事实授权新主体。实际独立native探针19通过，证据/private/tmp/f118-move-continuation-probe.log；本卡仅candidate reader，不提前装Owner。


## 108. 原成员计划接入正式Command/wire/M2 producer三卡组：已冻结

EDGE按T1001–T1006先测试后实现，每实现卡两生产叶；③④⑤强耦合按同组验证，不在中间态合流或装正式入口。T1002只domain/schemas/unification_conversion.py+application/unification_inventory_schema.py；T1004只原inventory_codec.py+conversion_codec.py；T1006只原conversion_plan.py+preflight.py。既有历史大叶仅必要窄增量，新测试叶≤600，既有相关fixture/constructor/golden按真实事实同步，不改SQL Writer/原inventory App（INT）或权限namespace（PERM）。

ResourceConversionCommand必填追加creator_user_id:positive int、membership_action:insert|keep、before_member_count:nonnegative int、before_member_digest:64hash、existing_creator_member_id:positive int|None、creator_template_digest:64hash、creator_planned_at:datetime|None。insert要求existingID=None和签入naive秒精度plannedAt；keep要求existingID positive和plannedAt=None。保持原schema_version/五kind/资源目标业务digest，不给全None或省略字段兼容分支；旧artifact必须重新停服盘点冻结。原inventory schema闭集给wire time str?；codec校验互斥及native类型，Resource恢复time后沿record_from_row(command)==record原canonical回比，旧四类commands不受影响。

ConversionPlanBuilder.add_resources(rows:tuple[ResourceRow,...],*,creator_memberships:tuple[CreatorMembershipPlan,...])显式必填。type0每root必须唯一计划且tenant/root/user_id与原Resource精确相等，不能默认空、凭新Member猜owner或到finish再补；type3/QA1/retired2无转换计划且不修成员。每batch先一次index，不每root扫全部plans；拒多余/重复/错scope/无配对计划。stage0..6与原finish排序/其它四种command算法保留。Resource command从既有纯计划逐项写七字段，不能改Member为F048 Source。

原UnificationPreflight增加实际UnificationSpaceMembershipRepository依赖（可显式注入原Repo），creator_facts缓存实际CreatorFact而非仅seen IDs，缺creator拒，物理exists但delete1仍历史owner。对原resources阶段实际type0/3 roots按≤200 Header组读取原Header+完整成员分页，验证同原Resource/tenant/type/user_id，不可用空Header补齐。Member按root一次分桶，原PK有序完整集合原样交§104纯planner，planned_at只用原aiter_tenant传入值；原ResourceRow.user_id是唯一历史owner。使用原Header/Member wire tags输出control，顺序每Header后紧随该Root全部Member，保持原raw字段及metadata；再将NORMAL纯计划交stage0。资源循环仍输出原resources/control/conversion各section，不新建执行器/Session/now。原permissions/catalog/source/quota业务不扩展。

真实控制覆盖空insert、完整原owner keep、重复owner/他人creator/owner错role状态、软删除creator、existingSPACE原样、QA/type2不误转、跨tenant/错Header/缺末页/错count、全部原来源字段保留、401/10001多Root/Member读及候选成本，三卡组跑原schema/codec/plan/preflight/inventory/conversion服务组合。完整Header/Member的正式新freeze/已freeze重验与M3写前门禁由INT随后接原inventory App；实际Member与Root原子写由原MemberRepo+ConversionRepo后继接，未合流两者前不得声称正式转换完成。


## 109. 正式成员基线完整性原入口门禁：已冻结

INT T1007先事实驱动红测，T1008仅新application/unification_space_membership_inventory.py（≤600）与原unification_inventory.py（历史大叶必要窄增量）。新纯值MembershipInventoryVerifier，observe(*,kind,section,tenant_id,record)、finish()->None；不SQL/IO/Session/now、不生成计划或授权。原_Sections.control接space_membership_header/space_member；原_tenant在preflight每条输出时observe，流完整耗尽后finish，未通过不得freeze。原aiter_frozen_pages在原graph每leaf校closure后observe，完整baseline→plan遍历后finish，原material/hash/manifest/counter/页序/tenant验证不替换。原_verify_frozen和原M3 _plan已耗尽该实际reader，自动覆盖既有freeze重验及写前门禁，不加新执行入口/预扫描器。

每个原type0/3 resource必须唯一匹配Header，tenant/root/type/原user_id相同；QA1/retired2无Header、无ResourceConversionCommand、不修历史成员。control中每Header紧随其完整Member集合，按真实Member PK严格递增、same tenant/root/canonical business_id及business_type=space，count必须完整；零Member必须显式Header。对每Root只缓冲当前原Member完整raw字段（去wire row_digest，保其余实际字段），以原fingerprints.digest原有序raw rows求beforeDigest，保count/owner自然键行数、原ownerPK/role/status/17持久列templateDigest及其它CREATOR标志，再释放原Members；存全局O(Root+Creator)轻摘要及O(Member)唯一PK轻索引，不缓存所有租户全部Member，不Root×Member反扫。原row_digest亦须按原raw事实重算一致，拒全局重复Member PK或scope冲突。CreatorFact须实际exists且同原owner；软删除仍合法，重复一致Creator可复用、不一致拒。

baseline与plan原顺序保留，七字段Resource command可晚到，finish才要求全部NORMAL0恰一条对应Command并逐项核tenant/root/user/count/beforeDigest。insert必须无owner自然键/无其它CREATOR、existingIDNone，使用该命令真实签入plannedAt调用原creator_membership_template验templateDigest；keep必须唯一CREATOR+ACTIVE owner且无其它CREATOR，existingID与原PK、原17列templateDigest相同、plannedAtNone。原SPACE3仅完整事实/无Command，不对其角色冲突做迁移修复。不要为调用要求时间的纯planner造临时时间，不复制canonical算法；独立少量验证谓词与原pure planner同组冲突native用例核一致性。

缺Root/Header/Member/Creator/Command、错tenant/id/type/user/digest/template、重复/跨Root/丢尾页和旧缺七字段artifact均failclosed，不能补空Header或兼容默认None。fresh消费可能conversion晚于某Header，frozen图不同section页可交错，使用闭集摘要而非错误假设resources页必先落盘；每section内原顺序保留。测试含实际原Reader/Builder/codec、原App fresh/frozen重验+M3任何写前拒不完整图、401/10001单遍候选和内存边界，原业务SQL写不在本卡。


## 110. P1完整owned事实应用窄口：已冻结

PROC T1009先原test_move_projection.py的native红测，T1010仅原permission/application/knowledge_move_projection.py一生产叶（≤600），导出原MoveProjectionFact类型（不复制DTO）及alist_owned_operations(session,*,expectations,lock=False)->tuple[MoveProjectionFact,...]薄转发实际nativeRepo。Owner不得经bridge.repository读permission Domain；permission Repo不导知识表。只延续原外部Session/TX，不开Session/commit、不做FGA、不新增receipt或重新编译ledger。完整Repo原scope/CURRENT pin/expectation/allowed_operator_ids/完整tuple/checksum/Mode facts校验与≤200原边界不变；lock只原语义，不用候选或裸status替代。此口可返回own nonfinalized实际事实供§107分类，FINALIZED/after仍由原arequire_finalized同TX证据证明，业务权限准入仍Owner职责。原P1桥/Repo全部控制及实际candidate→membership后继一致，未提前开放API/worker。


## 111. 原M3 Root与创建者Member原子写：已冻结

PERM T1011先native旧Writer真红，T1012仅原unification_space_membership_repository.py（现271，新叶逻辑留此且≤600）及原unification_conversion_repository.py（历史恰600叶，明确允许必要薄hook增量，不压行规避）。依赖§108 fixed4418fc539c与§106 fixed94c1，等合主树固定后实施；新test_migration_membership_writer.py及scale叶各≤600，现M3 fixture接口仅必要修正，INT App/EDGE producer/Service/Outcome schema不抢写。

保原Run→Root升序→Member全局PK升序→File/Doc/Version→Tag/Link→Default锁序。原_load minimal Root header补user_id后，在原Root锁之后批量锁本页Resource commands完整Member set；按真实owned Root0/3与user_id=command.creator_user_id核scope，exact canonical SPACE business_id IN≤200，每页Member.id seek≤200/201 FOR UPDATE，一次分桶；不逐Root反扫全部成员、不C3过滤无tenant的Member、不CAST/多独立列IN拼组合。零Member每root仍显式完整空tuple。仅原NORMAL ResourceConversionCommand触发，QA/type2/既有SPACE或V1-only不造成员计划；原NORMAL已转SPACE只供原aread_after验证，不收养未checkpoint的after状态。

MemberRepo私有_alock_conversion_sets(session,*,roots,commands,current)->dict[root_id,tuple[SpaceMembershipRow,...]]、_assert_conversion_before(*,command,root,members)->None、_aapply_conversion_member(session,*,command,current)->int、_assert_conversion_after(*,command,root,members,expected_member_id=None)->tuple[actualPK,fullAfterSetDigest]。current为实际tenant/TransactionIdentity轻守卫（非新authority），原alock_scope入口第一次await前capture、每SQL await前后核同Scope并最终assert后写原scope value；apply/aread_after取当前实际original/owned SP轻守卫，不在每Member页重算200commands seal。完整commands仍原_bound首尾核，不新建receipt/registry/session/commit/SP。MemberRepo只复用原MEMBER_COLUMNS/SpaceMembershipRow、schema creator_membership_template及fingerprints.digest，不反向import Service/pureplanner。

原_before Resource分支保Root业务/neutral before校验，另核七字段native strict（尤其拒True==1），原Root.user_id匹配、完整count及原20字段有序rawMember set digest；insert须无owner自然键/无其它CREATOR，existingIDNone、签入naive秒时间模板digest相同；keep须唯一同原owner CREATOR+ACTIVE、existingPK和17持久列模板digest不变、plannedAtNone。原软删除creator事实可保历史owner，不任换owner/激活/提升其它Member；metadata/source/binding/pin/null/time原样保留。

原aapply_and_read_after既有owned SP内Resource UPDATE后执行Member hook：insert按签入模板ORM add/flush取实际DB PK；keep零Member DML。actualPK暂存在原scope私有value用于本次尾验，不外传当authority。原aread_after重新完整set锁读；keep全set必须等原before；insert找唯一actual owner新row（17列==模板，PK等本次flush实际PK），去掉它后完整余集count/digest必须复原before。正常resume无本次expectedPK时仍从实际唯一模板owner定位并纳实际摘要，不根据形状收养未checkpoint转换。

Resource actual_after_digest固定为digest((rootBusinessHash,rootNeutralHash,actualCreatorPK,fullAfterMemberSetDigest))，原Root after两hash核验保留；ConversionOutcome字段/其它四kind实际Outcome字节、Service._fold/checkpoint算法与App commit ACK均不改。原Service外owned SP继续把Repo内SP写入和Run checkpoint同包；晚SQL/取消/触发器改模板即便caller catch+commit也无Root3但Member0的半转换。恢复沿原verified committed prefix，实际PK换掉/原Member增删改source等使摘要变动拒；unknown commit停止，重新原prefix核验后再继续，不新重试框架。

§108独立/tmp actual原Writer已证1真红：原SQLService完成且Root3，creator Member仍0（/private/tmp/f118-member-writer-unmet-dependency.log/.xml）；另只读原实际Member creator_ids/我创建集合也空（/private/tmp/f118-member-writer-readonly-gap.log）。新官方native须覆盖真实SQLService/App路径insert/keep/旧source全保、晚失败与cancel外catchcommit、触发器改Member/Root、原after PK及fullset漂移resume、缺/foreign Root/原creator字段错、pending/TX、ACK重复与zero extra insert、401/10001和多Root参数≤200/单遍候选，原四kind不变。正式permission namespace Publisher/Coverage/全升级仍后继，本卡不冒全部迁移已完。


## 112. 原move native执行与原Job算法接线 J1c：已冻结

PROC T1014–T1017两卡组：T1015新knowledge/domain/repositories/move_execution_repository.py（同叶frozen slots小DTO，≤600）及原move_row_repository.py仅必要SQL点查复用；T1017原processing_job_repository.py历史大叶必要窄hook增量例外，不复制原Job lease/count/Receipt算法。每测试叶≤600，可按实际上下文追加明确测试叶；原B1/B2夹具必须升级真实组合与原P1证据，不软放行未配置的move。原Scope/K1/MoveJob/Ready/P1数据与私有receipt不变。若两组3叶仍无法合理≤600，先报精确拆分，不压行/另造任务框架。本波只内部native执行，不写MoveOwner/API/worker。

MoveExecutionRepository构造绑定同一实际MoveJobRepository、MoveJobReadyRepository及原cutover.projection_verifier（同一真实P1 issuer）；不import旧ProcessingJobRepository而由调用参数jobs复用实际内核。小值DTO MoveConfiguration（原source/destination八配置字段，带target ProcessingConfiguration投影）、MoveAttemptFacts（原MoveScope+before|after position+Job/Plan定位）、MoveProjectionFacts（单个实际File/parent+双Root/compact Job/Plan事实）、MoveExecutionSnapshot（一个Item原MoveLeaf/snapshot/checkpoint+实际File/Doc/Version/primary/parent+双Root）。全部仅detached数据，不是跨TX proof，不存权限凭据/模型绑定/全manifest或整doc历史。

公开内部口：aread_configuration(session,*,job_id)->MoveConfiguration；avalidate_attempt(session,*,lease:JobLease,jobs)->MoveAttemptFacts|None；aread_projection(session,*,lease,resource_type,resource_id,jobs)->MoveProjectionFacts|None；aread_item(session,*,job_id,item_id)->MoveExecutionSnapshot；aguard_item(session,lease:ItemLease,*,jobs,projection_evidence)->MoveExecutionSnapshot|None；acomplete_item(session,lease,*,jobs,projection_evidence,source_count,milvus_count,es_count,source_digest,target_payload_digest)->bool。私有_alock_prefix只native SQL，_aassert_item_after只SQL+原same-TX P1 verifier；不得反调Job guard造成递归。helper可复用原RowRepo/MoveLeaf类构造及原checksum SSOT，不导知识App或permission Domain/ORM。

首次每attempt外IO前一次完整验证：原双Root ID升序→Plan→Job（再Item），复用真实MoveJob.aget_move_request/_replay完整接受hash/compact manifest，而非只K1；真实Item snapshots/targets集合按≤200分页一次索引与原accepted projection逐项等值，再原K1 fullScope/closure/position，返回detached事实后丢弃原prepared receipt。K1.aprepare_cutover本身不证明完整J1接受和Item snapshot，不能误报已核。逻辑cutover稍后仍fresh同TX全量重核；逐projection从此真实Scope一次建索引，仅处理接受changes，当前dual roots/lease+单个actual资源/parent读取，不重载Plan.parameters/全manifest；detached facts本身不能证明接受成员关系。

逐Item必须原ready marker/snapshot digest、actual File/Doc/Version/primary精确PK关系和实际after_revision/target ownership，duplicate file→version用indexed exact count/EXISTS；不把K1._position缩成小Scope调用（它仍会扫doc全部历史），不每item拉全Scope/manifest/其它Item snapshots。单anchor原P1 evidence必须同实际issuer/session/TX/job/accepted changes_digest，expected anchor来自该Item已绑定snapshot；None/复制对象/旧TX/错anchor均拒，不用裸FINALIZED dict或新receipt。原4→3→2允许范围沿K1实际(2,3,4)状态规则，7不能变成功。source与destination的R/G/index identity均当前核，正常配置变化沿原obsolete落库尾部并返回停止结果，caller commit ACK，不能抛错回滚obsolete；tenant/TX/pending严格、每await O(1)守卫。

原_job保持getter原样，不全局探测/拦move，原scanner arecord_dispatch仍只更新transport intent。新增私有_execution_job(session,job_id,*,_move=False)->(Job,MoveCurrentFacts|None)：False仅一次原_job(lock=True,include_manifest=False)，普通kind原样、实际move在任何变更前拒；True须真实composition，先_alock_prefix锁Root↑/Plan后原_job锁Job，并核compact绑定。_move只选择实际SQL前置，不表示已授权，禁止Session缓存/ContextVar隐式许可。aclaim/arenew/claim_next/finalize/aretry_failed等执行/重试方法增私有_move=False；原四kind零额外SQL/compact JSON探测，原lease/CAS/count/retry hash与状态算法不复制。prefix不提前推进obsolete，特别retry必须原receipt重放优先后再当前配置判定，不因新配置破坏已完成幂等重放。

_guard_item/asave_checkpoint/arenew_item/acomplete_item增加_move=False及move_projection_evidence=None，显式move才先真实prefix，再原lease/ready，再bounded after/P1 guard。仅旧move_jobs+move_ready DI即便marker齐全仍不能执行；完整DI默认普通口也拒move；配置完整但缺原P1仍拒Item变更。claim前可在同持锁TX peek一项的anchor取得P1 evidence，再原LIMIT1 claim，最终实际选中Item还必须核同证据，不信peekID。成功完成必须原内核ACK路径内检查durable move_source_cleaned checkpoint与真实MoveIndexResult五标量/source digest/target digest精确匹配，并同TX实际File status/脱敏remark更新（tenant/space/file/version精确条件）；失败沿原public error code及FAILED策略，不持久凭据/provider原文，成功项不重置。不能只外围wrapper更新File而留可绕过通用成功口。guard/checkpoint本身不新开SP；若具体原子ACK需SP，调用方必须在签P1 evidence前建立，避免nested导致证据TX漂移。

afail_attempt已读无锁candidate，move直接同prefix→Job，普通仍原目标Root→Job，不能先锁目标再补较小source。alatest_retry_actor仅move分支用原已加载字段+ready.retry_subject核真实typed列、audit/reference及accepted revision<=当前revision，原四kind读/字节不变，不扫描所有Retry历史。原areset_target_state/aacknowledge_cutover不作move替代路径；move logical ready沿原K1/B1。

测试先native红再两卡组绿：401/10001的单次projection/item guard SELECT数相同，每次最多一个snapshot、零fullScope/manifest；accepted首次/最终全Scope各线性，原_refresh_counts原group聚合扫描成本另实测，不能只固定SQL条数称全任务O(N)。实际双Root锁序、source/dest drift→obsolete durable、zero-item逻辑、partial retry/主体、原P1坏proof、ready历史marker、原ordinary四kind同输入SQL数/JSON/lease/count字节等价、missing DI/default wrongpath拒、source_cleaned与File/Item/count ACK及外catchcommit行为均需覆盖。完成后实际MoveOwner→runner原EXECUTE_TASK/scanner→旧move_items/确认DTO/DI再分别冻结接线，不向edit-only普通kind白名单直接加move。


§112签名补正：aread_projection显式接jobs，与attempt/item口相同，只复用原Job内核obsolete落库/lease算法；不import旧JobRepo、不复制obsolete尾部、不以callback或Session隐式许可绕开实际native前置。该口同样Root↑/Plan→Job后判source/dest当前配置，None结果也须caller commit ACK。原只读aread_configuration不制造状态写。无实际生产调用方，freeze后再实现。


## 113. 保存QA知识引用的原类型资格保留：已冻结

INT T1018官方native红测、T1019仅原unification_preflight.py的source_decision窄改。现真实workflow reference_extractor已把qa_retriever.qa_knowledge_id解析为knowledge_space TargetKey，原ReferenceTargetRepository._facts对Root及file父允许NORMAL0/QA1/SPACE3；但source_decision硬限0/3会拒原已保存QA。按spec AC-37/55/65/88，保存QA槽位应沿相同原native物理资格保留existing_saved_slot，QA仍type1、旧模型/内容/权限namespace/成员不转换。只把该物理类型集合与原Owner统一0/1/3；exact tenant/父记录存在/file kind、type2/未知拒、explicit missing initial_missing、无新bind授权和不造Grant均原样。测试从实际qa_retriever提取器＋native KnowledgeMigrationTargetRepository读原QA（可含原File父为QA）构造真实来源事实，before source_decision拒→after保原ID/source/slot/disposition；并真实M2冻结后QA仍type1无ResourceConversionCommand或成员计划，原type2/跨tenant/坏file父继续拒。此非QA合并，不因改集合扩任意线上资源准入。

## 114. 全M2复用原纯Catalog编译上下文：已冻结

EDGE T1020先native C4/C5事实驱动红测，T1021仅permission/migration/f118_plan.py历史大叶必要窄API增量。新增frozen slots ResourceRetirementPlanner(*,catalog_plan)纯类，构造仅一次原_resource_context的Catalog重建/完整matrix校验，并以只读映射保原before/after model与scope索引；不公开可写dict，避免普通字段重赋值或映射修改。Context不是authority/receipt/registry，不Session/SQL/FGA，不缓存资源或跨run全局单例。

build(*,before:PermissionResourceBaseline,namespace_target:ResourceModeBaseline|None=None)->ResourceRetirementPlan直接复用原_build_resource_retirement_plan；build_many(*,before:Iterable,target_modes:Iterable|None=None)->Iterator复用原exact zip_longest/mapping规则及所有baseline/target/visible canonical验证。旧point/batch APIs保持签名/返回/错误语义和payload/hash字节；可共享该class实现，但不得改变C4/C5/旧无mapping checksum或绕badCatalogPlan原重建。单条build与旧point一样：有mapping必须显式target，无mapping拒多余target。空批、late missing/more/错target、跨合法tenant纯资源不同输入均原约束，不按资源数重编Catalog。

后继原InventoryApp每正式freeze显式构造一次planner，并交原tenant preflight复用；frozen verifier每graph一次。先交此纯接口再冻原M2 wire/资格/consumer卡，不为了消除tenant×Model把所有租户G/S全局堆进内存，也不把private_context跨层强拿。测试实际旧C4/C5 native Source/Mode/retired数据与旧point/batch全等/旧payload字节，badCatalog/mutable target/canonical source照拒、compiled映射不能普通改；401/1001 models独立混合tenant批/资源预算总Catalog derive与matrix各1、模型候选M、资源Source O(G+S)，SQL0。后继actual Parent namespace完整frozen wire/SQL/FGA Publisher仍未接，本卡不闭T157158。


## 115. 原ModelReferenceCore完整原事务保护：已冻结

PERM只读审计确认T111112内部缺口：原SqlLedger第二次global Coverage已取合法ready后真实rollback并SELECT建新TX，原5类Model完整inspection仍check_complete=True，目标锁原TX已丢。T1022先官方native真红，T1023只原llm/domain/services/model_reference_service.py一生产叶必要窄修；不改ModelDeleteRepo/ReferenceRepo/Coverage协议/六Owner或公开API。普通API/执行删除仍T113–120、正式Coverage adapter/启用仍T169170，不能把这些后继错算本卡未实现。原T111112完整Source/目标锁/ASR_RT/规模已由作者外审计293通过，真实TX缺口闭合后再验是否关闭。

同一次ainspect_removed_models/alist_removed_model_sources沿实际native Session的原tenant/TransactionIdentity保护目标锁和全部结果，轻守卫O(1)、零额外SQL/全targets扫描。既有TX在入口先捕获，再跨原authorize/stable identity/removal/Owner/Coverage/完整BRR/disclosure及尾Coverage/identity核原TX/tenant；实际callback rollback/rebegin或换nested均failclosed 10994，不能check_complete=True。保原合法fresh native AsyncSession：目标锁前先await原session.connection()自然checkout/autobegin并立即pin（早期原callback已开TX则直接pin），不要求客户端预先begin，不新开Session/显式BEGIN SQL/SELECT1/commit，不加Session事件监听/ContextVar或registry；actual原Repository内部无commit，capture完成后不得重捕替换pin。末尾§115补正保留独审实证及旧缺口历史。同新HTTP页可新Session按原cursor continue，每次inspection各自pin，不把上一页SQLTX当跨请求capability。

可在私有facts保当前原session/tenant/transaction或显式传原session到_finish，均不入公开Inspection/cursor hash/JSON/result。每个有返回结果的关键await前后检查，特别tail全局/tenant Coverage和最后身份复验；_disclose批次及_dataset返回前要检。原full scope digest/actor/credential/data_scope narrowing、v2 f118-model-inbound-v2字节/ID顺序、global ordered stream和count/分页资格/受限名规则保持。缺少nativeSession/丢TX不得用None兼容放行；原模拟规模fixtures如需适配必须用真实AsyncSession而非改弱assert。不得每guard调用全Owner重验、重编Catalog/扫全Model，不能倒退为source×targets。

native覆盖existingTX/fresh-autobegin、合法new-session continuation、首/中/尾rollback重开、nested scope漂移、tenant改变、Coverage/FGA disclosure/最后身份await时漂移均拒无业务DML；原Target锁/5产品类+实际ASR_RT、第0个模型服务、全源跨tenant摘要、oldcursor/lastID重插、epoch/hash/未ready/异常、source各Owner资格及401/10001预算必须保持。修后原同选集及作者外复查，未跑正式Coverage/Middleware仍不宣称真实删除可启用。


## 116. 正式namespace plan独立section闭合wire：已冻结

C6三卡组T1024–1029整体接正式原路径后合流，不在wire中间态伪装旧plan兼容。EDGE T1025仅原application/unification_inventory_schema.py+unification_inventory_codec.py；T1027仅新unification_permission_namespace.py（≤600）+原preflight历史大叶窄改；INT T1029仅新unification_permission_inventory.py（≤600）+原inventory App历史大叶窄改。test叶各≤600，可必要精确适配原正向M2夹具以真实旧Mode/闭合图为基线；生产绝不补造缺Mode。§111 Writer、六业务Owner、Source提取、当前运行接口、SQL/FGA Publisher均不在三卡组改动。

新增SECTIONS='permission_namespace'，只kind=plan，加入原App section allowlist。不得用任意JSON扩展：以下字段闭集，沿原record_from_values/encode/decode canonical，不另造serializer/hash；plan/runtime影子旧artifact缺明细应重盘点冻结。新增tag：

| tag | 字段（原schema类型） |
| --- | --- |
| namespace_catalog | run_id:str writer_contract_version:str before_catalog_checksum:hash target_model_checksum:hash catalog_plan_checksum:hash action_checksum:hash model_checksum:hash from_resource_type:str to_resource_type:str model_count:nonnegative |
| namespace_applicability | catalog_plan_checksum:hash model_key:str from_resource_type:str to_resource_type:str before_action_codes:strings after_action_codes:strings reason:str |
| namespace_target_mode | mode_id:positive + 原resource_mode完整字段（含id/tenant/type/resource_id/mode/parent/version/projection_state/operation_id） |
| namespace_after_grant | mode_id:positive + 原grant全部字段 |
| namespace_after_assignee | mode_id:positive + 原assignee全部字段 |
| namespace_after_visible_source | mode_id:positive + 原visible_source完整id/source（source原完整闭集） |

namespace_catalog/applicability全局page tenant=None，固定唯一mapping knowledge_library→knowledge_space；target_mode.id须等mode_id；各after原id不改，mode_id是所属原Mode ID，不是Grant ID。具体row与page tenant一致性由原page检查与§118共同核，visible的tenant在nested source中不可漏。from/to恒上述固定对；保所有动作tuple顺序而非set。catalog声明只有一个、完整模型矩阵每model_key一行，不逐grant复制。原after_grants是带模型快照的编译结果，不能误与原after.grants的SQL基线行混淆。

原permission_plan tag仍位于conversion，原SQL decoder继续deferred；在既有tenant_id/resource_type/resource_id/target_resource_type/plan_checksum/before_digest/after_grants_digest/visibility_deltas_digest/expected_use_changes_digest上追加mode_id:positive、catalog_plan_checksum:hash、target_mode_digest:hash、after_digest:hash、grant_count:nonnegative、assignee_count:nonnegative、visible_source_count:nonnegative。摘要全部用原permission.migration.f118_plan._checksum SSOT（ensure_ascii=True），不混用inventory.digest（False）；新record JSON本身仍原inventory canonical。after_digest绑定完整plan.after，target_mode_digest绑定plan.namespace_target；counts包括inactive/retired全部原行。target_resource_type hint必须和完整target相同，不再独自当资格。

## 117. 每tenant真实物理资格到显式namespace完整计划：已冻结

PermissionNamespacePlan(*,permission_planner:ResourceRetirementPlanner)纯有限collector，observe(*,section,tenant_id,record:InventoryRecord)->None，finish()->Iterator[ResourceRetirementPlan]。同叶可提供catalog_namespace_records(permission_planner)->tuple[InventoryRecord,...]与namespace_plan_records(plan)->Iterator[(section,InventoryRecord)]供INT复用，不重复hash/typedRow恢复；需要的原Catalog/Mode/Grant/Assignee/Visible恢复函数同叶导出窄纯helper供§118用，日期/tuple/VisibleSourceProjectionDTO依原闭集恢复并用record_from_row原样回比。原Root/File索引只留资格字段，每tenant保一套R/G/S桶，不同时保旧preflight完整桶和新collector副本，不全局积全部tenant G/S。

只复用原resources/files各页及权限四类PK≤200页事实，无新SQL Reader；Root+File.tenant/id/type/RootID实际一致，Mode/Grant/Assignee/Source全量由原Repo读取，不丢inactive/RETIRED来源。NORMAL0必须有唯一真实同tenant原knowledge_library Mode、CUSTOM/no parent，才声明rtype=knowledge_space；原资源0→3资格与旧Mode绑定，缺原Mode阻断报告、不补造。QA1/retired2/已有SPACE3及其它模块已有Mode显式原样；已有knowledge_library/space Mode必须匹配原物理类型（retired2原library可原样），不把同名ID或未知namespace猜成目标。

对已存在folder/knowledge_file Mode核实际File kind0/1、tenant、所属Root；原parent为library必须精确其物理Root ID，且仅Root0时改parent_type为space；原parent space仅其原SPACE3 Root；原folder parent核真实同tenant/同Root DIR且有原folder Mode。原Mode图闭合无环，原parent_id/mode/version/operation/projection全保，不重选物理path末项或最近目录。原业务loader/F048 exporter虽按path末级生成，但Mode mapper只保已传边，不能据此修原继承。非知识业务原边不借机重排，不明知识关联或跨Root报告。type2及files原F048未覆盖，明确STALE_FAILED_RESOURCE也可跳过：**不新增所有物理File/Folder必须有Mode的门**，只强制待转NORMAL0 Root有原Mode，其余已存在Mode的实际资格与所需parent闭包必须完整。

原UnificationPreflight.aiter_tenant(session,*,permission_planner:ResourceRetirementPlanner,planned_at)显式替换catalog_plan参数，不设None或旧分支fallback。原Member计划/creator缓存/stage0..6/physical/source/quota流程保；collector在相同原输出事实观察，取代旧permission groups桶与旧hint-only生产。每tenant沿原Mode顺序创建显式target，再同一个全局compiled.build_many消费；after Row顺序沿原plan.after tuples，不能重新按PK排序改变Assignee按Grant分组的原序。namespace_plan_records每Mode一组target→全部after Grant→全部after Assignee→全部after Visible，page199条自然跨页；permission_plan摘要仍独立conversion缓冲，不假设跨section页谁先。所有原Mode都要完整target/after，连不变者也不省。

## 118. 正式namespace语义门、原Artifact顺序与峰值：已冻结

INT原InventoryApp从真实native Catalog初建plan时显式mapping=(('knowledge_library','knowledge_space'),)，只构造一次ResourceRetirementPlanner并传每tenant。原global baseline Catalog、plan after Catalog及catalog_namespace_records完整写入后先await pages.finish()，再原PinnedReader/FGA/各tenant；finish仅提前原artifact上传/回读/current，无SQL flush/commit、不重跑source/FGA、不改业务TX。新permission_namespace与conversion输出都kind=plan，其它section原样。原M2 fresh通过同语义checker后才freeze，原existing freeze重验/原M3 _plan完整耗尽aiter_frozen_pages沿同一门，无新执行入口/SQL变更。

PermissionInventoryVerifier(*,run_id,writer_contract_version,target_model_checksum,catalog_plan_checksum)，observe(*,kind,section,tenant_id,record)->None，finish()->None。constructor target/model checksum来自已SHA验证的**原plan根run metadata** authorization_model_checksum/catalog_digest，FrozenReader开始先预读该root并复用bytes，后续原verify不重复read、不跳root metadata/descriptor/hash/counter/material验证；不从当前代码猜targetChecksum，也不预读全部plan catalog造第二图框架。baseline根run声明的原catalog/auth checksum与原Catalog实际facts须一致；完整baseline Catalog在首个相关tenant事实前闭合，晚到catalog拒。建CatalogPlan一次+compiled原_context校验一次=全局两次derive/matrix，O(M)固定，不声称整链只有1次；fresh同理，不随tenant追加。

Frozen顺序仍baseline全图→plan全图：baseline只按原resources(resource/file)/permission四类相关事实分tenant段；用同§117资格及同compiled在每段结束生成每Mode轻摘要（full before/target/after hashes、各after tuple hashes/counts、原plan checksum及header摘要），释放该tenant完整G/S。忽略physical/source/tasks等跨后段资料对tenant切换的干扰，原queued/broker可在所有tenant后再按tenant输出，不能误报重复业务段。全局仅保O(Mode)轻摘要与O(M)Catalog，不堆所有tenant G/S；峰值O(M+R+最大tenant G/S+当前Mode after)。plan namespace明细按mode_id组验证完整after，仅持当前Mode，group跨page可继续，结束立刻比counts/full after及部分摘要并释放；原permission_plan late conversion独立收小声明对同summary。after行显式mode_id，避免全局Grant→Mode大索引。原catalog after行+完整model矩阵在late plan精确比早期重建期望，不把提前finish误当已读到plan after。

缺/多/重复mode/target/after行、错page/nested tenant、target_hint不一致、漏模型/改动作顺序、重签hash的错误计划/错Root/错parent/不明physical资格均拒；旧无namespace摘要图拒，不假补空模式。不把编译器当SQL/FGA proof，实际before与实时FGA parent全量对账、发布source版本与legacy_source_key保存仍后继。测试先native正反C4/C5+现真实QA/retired/已有SPACE/STALE缺Mode控制，actual fresh/frozen/M3任何写前阻断、深层页缺项/错matrix与顺序、多个tenant/4011001模型共享预算全局2、40110001资源线性/单tenant峰值/不重复sourceIO、catalog提前flush无SQL均要证明。正向M2夹具需明确真实原Mode，不能生产补默认Mode消红。


§118 fresh复用细化：PermissionInventoryVerifier增加仅内部可选permission_planner=None；冻结回读默认以已验证根metadata重建，fresh原App可显式传本轮原compiled实例，经actual baseline Catalog完整恢复与plan.before/run/writer/target/mapping精确等值后复用，不重复derive。原_verify_frozen/aiter_frozen_pages仅私有_permission_planner参数承接；不存在HTTP接口、Session缓存或artifact hint赋权。fresh写完artifact后沿原完整图/metadata/material校验耗尽，再正式afreeze；基线SQL/FGA/source均不重读。这样fresh与独立frozen各自global derive/matrix都是2次，不能因fresh回读再重编成4次。


§115 fresh锁前pin补正（独审实证）：cfefdc9dc9仅在removal返回后pin不能保护fresh原锁，actual Repo await结束前rollback/rebegin或nested切换3项真红；不可交付为已闭合。仍只原Service单叶：在第一次actual removal锁调用前，guard.transaction为空时，如原Session尚无TX则await session.connection()取得其原生checkout/autobegin（无新Session、无SELECT/显式BEGIN SQL/commit/事件/private API），返回立即guard.pin；如早期合法callback已自然开启TX，直接pin不再checkout。其后原guard.call包裹actual removal整个await，此时任何锁内换TX/nested/tenant都已受before/after guard保护，禁止锁后重捕替换。连接尚未返回前无目标锁，pin连接返回的原TX不会丢原锁；连接异常须沿原公开口保cause、target lock调用0。独立候选6通过：existing额外checkout0/fresh1，25条原SQL逐条同、Inspection及cursor字节同；正式作者仍须先固化3漏检真红，再源修及相关组合/作者外复查，不能拿/tmp候选直接闭合T111112。


## 119. 移动逻辑切换的原直接File引用归属维护：已冻结

原T091/T092中的R2前置，由PROC先native红再三生产叶窄实现，不新编号/不提前关闭整卡。独立实际P1→K1→ready证明File50/81/82已经归目标11而3条BRR.target_space_id仍10，旧空间影响3条/新空间0条；修派生归属属于原design R2，不增加业务绑定种类或任务模型绑定。

仅原knowledge/application/reference_target_owner.py、原resource_reference/application/write_runtime.py、原resource_reference/domain/repositories/reference_repository.py（原746行旧叶窄方法例外）。KnowledgeReferenceTargetOwner constructor追加可选move_cutover=None保持原非move构造；新增amove_file_ownership(session,*,logical,reference_runtime)要求注入真实K1 issuer及原ReferenceBindingRuntime，同issuer.assert_logical_current(logical,session)通过后取原logical._prepared.scope.files全部真实ID（具体原字段由实际typed receipt接口取得，不私造scope），含DIR、历史、failed及非索引参与项。不得以leaves/selected roots/Item集合代替logical全闭包。新归属仅原实际registered verifier的owner_query receipts所得；源空间只来自原prepared.scope.source。原构造及普通target read语义不变。

Runtime新增arefresh_file_target_ownership(session,*,receipts,expected_space_id)：必须本runtime原verifier验证原同Session/TX receipts，且repository.verifier为同实例，非空keys全knowledge_file、原VALID、同concrete tenant且actual after空间唯一；用原repository.target_owner_scope，不新capability/receipt。Repo新增aupdate_file_target_ownership(session,*,scope,expected_space_id)，新值由原Scope receipts取，不接任意caller destination；先原_check_scope与native context，按原Owner exact-target bounded stream（不include_space_contents）锁BRR.id seek≤200，先完整验证所有候选再第二遍有界UPDATE，避免后页坏行已有半修改。保持一页Rows及一次TargetKey→actual space索引，不留全BRR行，不逐Source重保存，不锁SourceRoot。

精确命中BRR必须source tenant和target tenant均当前tenant、target_type=knowledge_file、target_id为scope实际keys、target_space_id为expected before或actual after；任意NULL/foreign/其它归属、legacy_invalid_reason/run_id/evidence_key任一非NULL均拒且校验阶段0 UPDATE。原因沿原resolve_target_state的live+legacy_target_reappeared拒绝规则，不修复/猜测存量失效；scope外legacy行不读取、不修改。已是actual after只幂等不写。只set target_space_id；原PK/source type/id/version/slot/SourceRevision/config/set digest/显式space binding/所有legacy证据与tombstone不变。DML绑定page实际rowPK+tenant+targettenant+knowledge_file+真实target IDs+expected before空间，IN每组≤200，实际参数上界如两个IN合并可≤406固定项，必须实测而不误报204。

共同原业务SAVEPOINT由后继MoveOwner在签P1/K1之前建立，覆盖K1 prepare（Root↑→Plan→Job→Items→File/Doc/Version）→P1同TX finalized→K1 apply→本R2→ready；本三叶不在已有receipts后新建nested/SP，不提交/换Session。任何R2/ready错误由该共同SP回滚，SP外catch+commit不能留下File after/BRR before/ready混合。本Repo独立方法不是自动commit API；异常传递给实际业务Owner。先持真实Root/File再BRR，原绑定writer target-first故不新增SourceRoot反向锁。外部worker IO/用户并发仍按既有排除，不追加新控制体系。

仅在入口/尾部做完整原logical及OwnerScope/receipt验证、每await O(1)检查native tenant/TX，原Owner有界分批读取/原stream fullscope验证数量单独测，禁止每BRR页重扫full logical/files或逐slot重验全部targets。401/10001文件及同file多Source/Slot实际SQL、参数、验证次数/读取字段/峰值均实测，不以固定SQL条数冒O(N)。native先红覆盖真实before→after入向空间查询、DIR/history/非参与项、显式space/model/其它File不变、scope/issuer/TX缺失/复制/嵌套错误、后页invalid与foreign/NULL、重放0UPDATE、故障/晚cancel/外catchcommit回滚共同SP。完成后Root复查合流，再冻结实际MoveOwner、runner、HTTP装配，不在本卡提前加move到普通kind白名单。


## 120. 原模型删除确认计划内部协调：已冻结

PERM先实现原T113/T114内部子片，原T113依赖T110的空间删除为无共享写叶的伪串行依赖，本子片只依赖已闭合T112；整卡仍待真实业务入口装配后关闭。本片只新增llm/application/model_delete_plan.py（≤600），同叶frozen slots ModelDeletePrecheck(inspection:ModelReferenceInspection,confirmation:ModelDeleteConfirmation)。ModelDeletePlanApplication(*,references:ModelReferenceService,plans:ModelDeletePlanRepository|None=None,ttl_seconds=300)，默认TTL沿现Processing预检5分钟，clock只用原plans.clock。公开内部方法：aplan_removed_update(session:AsyncSession,*,identity:UserPayload,server:LLMServerCreateReq)->ModelDeletePrecheck；aplan_server_delete(session:AsyncSession,*,identity:UserPayload,server_id:int)->ModelDeletePrecheck。不改Core、不新增prepared Writer context，不传HTTP receipts，不改API/原LLMService/DAO/分享或tombstone。

入口须原native active caller TX、concrete tenant、无pending ORM业务写；本片可在签Core检查前建立自身原native SAVEPOINT，内捕获tenant/TransactionIdentity，每关键await前后O(1)核验，保护唯一plan INSERT/flush，异常回滚自身SP、保外层无关已执行DML，不能锁后重捕或签证后新nested。外层原TX退出SP后仍核原identity；不新Session/commit/显式BEGIN SQL。Core沿原单次ainspect_removed_models（含原真实授权与Coverage/Owner/完整摘要/披露），再恰一次原PlanRepo.acreate_model_delete_plan，不重读/重扫targets或inbound、无share/provider IO/业务DML。

update仅未来原LLMService真实确认有removed的分支调用：server必须实际typed DTO且id正整数，retained从原models各原id提取，None/0沿原新模型哨兵不作retained，重复/负ID由实际严格资格拒；不能根据client hint宣称存在移除，实际Core返回空targets时本口拒不写确认。真正非移除PUT保持原Service路径，不调用本口、不新增Coverage门；实际caller分流后续另冻。整删无论服务0模型都沿原Core需要完整ready。

command_digest沿原ModelDeletePlanRepo._hash：update为{operation:'model_update_server',server:server.model_dump(mode='json')}，包括原id/name/description/type/limit_flag/limit/config/share_to_children/models及每model原字段、原list顺序；delete为{operation:'model_delete_server',server_id}。DTO先snapshot/deepcopy供单次操作用，不能await间让caller修改请求被hash成另一清单。只存digest，绝不将body/config/API key进plan、错误、repr或日志。operation固定两原Literal，实际server:<id> revision和仅removed model:<id> revisions沿Core事实完整入原Plan，目标/完整provider变化均重确认。

actor_reference沿原PlanRepo闭集：actual current tenant、identity.user_id审计、原web五字段_runtime_credential_reference、真实resolve_permission_actor(identity).data_scope和原explicit management pin，保home tenant，不排除窄scope、不把全量超管home1强制改成执行tenant101，不存trace。原credential形状/当前合法性/真实tenant admin与Root readonly规则由原Runtime/Core保持；入Core前快照、Core后及create尾核当前actor/credential/pin一致，失败不用临时新凭据重签。可必要额外常数次原actor解析，但需独立报实际成本；不按Model/Source循环解析。

先native真红后绿：实际SQL Plan读回重验，三移除口（PUT保留差集单/多模型、server全删及empty）、无移除update本口拒且原PUT未改、跨tenant/shared Root/非管理员/真实Coverage未ready/异常/租户或TX/actor变化、到尾INSERT失败/cancel外catchcommit均无业务变更且无半plan；exact command hash与敏感字段不落artifact、真实原revisions/TTL/actor pin、同一Core仅调用1次。原10001target/30003ref budget275SELECT（server3/model4/RRT51/Tenant2/Run14/BRR201）只对应现native夹具，precheck仅新增1plan INSERT及已声明常数actor开销；真实Coverage/metadata另算，不能拿mock冒adapter证明。原T113/T114整卡不因内部helper提前勾。模型分享尚无业务prepare→projection→SQLfinalize口，permission project_delete只删enabled marker不能替代llm_server shared_with；后继正式冻结，不在本片触碰，也不以原Projection原子90条上限给模型分享新增任意业务上限。


## 121. 实际跨空间移动应用Owner及执行短事务口 A1：已冻结

PROC先native红再仅两新应用叶knowledge/application/move_processing_owner.py、move_processing_admission.py（各≤600，正常format不压行）。原T087–T092/T073–T076内部接线子片，不另编号、不提前关闭整个旧业务/API/worker卡。admission叶只承载该Owner实际消费的原身份/阶段与P1 expectation纯材料，不SQL、不新receipt/capability/registry或通用事务callback框架。原Repo/P1/K1/J1/Execution/R2/Schema/旧Service/runner/API/DI本片不改；真实缺窄接口须先报Root另冻，不绕private数据库访问。

KnowledgeMoveProcessingOwner(*,session_factory,projection:KnowledgeMoveProjectionApplication,reference_runtime:ReferenceBindingRuntime,clock=_now,chat_rehome=dispatch_knowledge_chat_rehome)。前三项显式必需，内部构造同一原OperationPlanRepository、MoveScopeRepository(parent_states=projection)、K1(projection_verifier=projection)、MoveJobs、Ready、Execution及完整ProcessingJobRepository。R2使用原KnowledgeReferenceTargetOwner(move_cutover=同K1)与同registered reference_runtime；不自行改注册Owner/仓储。默认chat用knowledge_space_chat_history_retention_service原真实dispatcher，不以空callback宣称交付。session_factory每次须实际新native AsyncSession、入时无TX/无pending；Owner拥有短read或write事务、commit/rollback，不接caller Session/Scope/snapshot/receipt/actor_reference。实际同tenant/bypass/原TX每关键await O(1)核，不把FullScope校验塞每item。只move_index，普通四kind硬拒，不能增加全局白名单。

| 方法 | 精确输入/结果 |
| --- | --- |
| aprecheck | (source_space_id:int,request:FileMoveReq,*,identity,entry_kind:str)->OperationPrecheck |
| aaccept | (source_space_id:int,request:ProcessingCreateRequest,*,identity,entry_kind:str)->JobAccepted |
| astart_attempt | (job_id:str,*,expected_dispatch_revision:int,lease_seconds:int=900)->JobLease|None |
| aensure_logical | (lease:JobLease)->JobAccepted|None |
| aguard_item | (lease:ItemLease)->MoveExecutionSnapshot|None |
| aclaim_item | (lease:JobLease)->ItemLease|None |
| asave_item_checkpoint | (lease:ItemLease,*,step:str,checkpoint:Mapping)->bool |
| acomplete_item | (lease:ItemLease,*,source_count:int,milvus_count:int,es_count:int,source_digest:str,target_payload_digest:str)->bool |
| afail_item | (lease:ItemLease,*,error_code:int)->bool |
| arenew_attempt / arenew_item | (lease:JobLease/ItemLease)->bool |
| afinalize_attempt | (lease:JobLease)->JobAccepted|None |
| afail_attempt | (job_id:str,*,expected_job_revision:int,error_code:int,lease:JobLease|None=None)->bool |
| aretry_failed | (job_id:str,request:ProcessingRetryRequest,*,identity,entry_kind:str)->JobAccepted |

成功ACK保持原5scalar，不从App import worker DTO，W1沿实际MoveIndexResult拆值。错误只原5位int，失败Item走原jobs.acomplete_item(succeeded=False,result={})和同TX P1；不持久provider异常原文。除afail_attempt外，所有worker执行/续租/Item口短读实际Job/latestRetry actor并关闭SQL，沿原restore_processing_actor恢复当前credential/收窄+fresh目标upload，再fresh TX核prefix/lease/configuration/原P1证据/业务事实并调用原kernel。afail_attempt专为凭据恢复等先决失败落诊断，不以恢复已失效credential为前提；只可信native Job locator/当前tenant/observed revision/可选原lease→原kernel失败并commit，0外部IO、不从audit造身份或业务执行许可。

precheck：短TX载detached原Scope→关闭SQL→原selected folder/file.move与目标容器upload（无额外space.move/edit gate）/narrowing/原capture→fresh TX重载Scope精确等值后仅写原Plan，5分钟expires，commit。原OperationPlan.acreate的can_execute默认由index manifest导出，本Owner仅返回DTO改为bool(scope.files)、valid_items真实logical roots，保证0-index的非空逻辑可执行；不改原Plan/Schema算法。A1仅跨空间有效全量请求；source==destination交后续KN保原同步语义，本口拒。FileMoveReq.skip_invalid=True在此内部片明确拒，不能忽略、不逐root重拉fullScope；原T08586批量分类随后接入，在此之前不开放KN/API，也不声称完整批量预检已完成。

accept：先实际Plan/J1完整replay探测短读后关闭；新接受核旧归属selected.move/目标upload。已有Job当次允许同typed主体的新合法JWT做continuation：可信native Plan/Job给原actor_reference及audit字节输入原J1 _origin/replay，当前identity另核真实有效凭据、同typed主体、原ceiling相交及§107阶段资格；不恢复过期旧凭据作为门、不用新capture重签旧Plan。非同主体必须明确retry。fresh写TX仍原acreate_move_reserved再次裁定竞争/新建/replay并commit，不凭首次read猜成功；不复制或改原hash/lease/RetryReceipt算法。

ensure：短TX原Execution.avalidate_attempt首次全接受+Items/Scope一次（None也commit），关闭SQL后在实际Job/operator候选≤200→原J1 membership→完整原pin/tuple/Mode owned facts基础做§107当前continuation与P1 aexecute_or_resume。外部FGA IO不持业务SQL；P1使用自有原sessions。然后fresh业务TX在签任何原K1/P1 proof之前建立共同SAVEPOINT：K1 prepare→P1 require_finalized(full expected changes)→K1 apply→R2维护全部logical File IDs→Ready；释放SP后commit。0items同完整链，不走ordinary reset/finalize捷径。任一R2/Ready失败/cancel/outer catchcommit不能留下半归属/半ready。

Item写口：同一个fresh native TX、原双Root↑/Plan/Job/Item锁序，先actual bounded Item snapshot/anchor及真实P1 evidence，再原Kernel guard/claim/checkpoint/ACK。K1逻辑proof要求full sequence；Item原Execution.assert_current要求该实际snapshot的单anchor及job global changes_digest，沿原Bridge/Repo即可签该单anchor（不是每item重取fullScope/全部operations），不能用裸digest或FINALIZED dict代证据；peek与最终claim实际Item须相同anchor。无receipt跨TX给W1，aguard只返回detached原Snapshot供外IO。状态或配置导致None/False必须正常commit原obsolete ACK再返回，不能在TX内抛错把obsolete回滚。afinalize调用原move kernel，成功项/历史ready/lease/CAS/重试hash不改。

同真实logical commit成功或确定ready重放后、SQL全部关闭，按原scope.files（DIR→folder，FILE→knowledge_file）的真实int IDs调用原build_knowledge_chat_flows(source_space_id,resources)，再chat_rehome(source_space_id=...,source_flow_ids=...,reason='cross_space_move')。不能accept即派或删旧副作用；replay沿原幂等flow补commit后未派发窗口，失败保原best-effort日志，不回滚已commit归属。不新增chat/model任务绑定或通用补偿系统。

测试实际Application接受/逻辑/Item ACK三叶可分，每叶≤600：原真实P1/K1/J1/R2多Session、selected move仅子项可用/目标upload/tenant/home-pin/S-D主体、fresh凭据same-subject replay及不同主体仅retry、P1部分前向及FINALIZED after、operator候选必须membership、0item、未知commit/幂等恢复/chat时序、None obsolete确实durable、凭据失效能afail_attempt、坏/跨TX证据/after/version、真实ACK File+Item/count原子。401/10001须含独立projection changes也达N的selected-file集合，不只单DIR下N叶；每Item P1与snapshot成本恒定，不FullScope×Items。完整attempt/最终cutover各线性另报，既有count聚合成本单列。W1/HTTP/query/DI留后继，无mock helper替代实际短事务装配。


§121 claimpeek窄补（接口先行）：PROC已确认原kernel在内部LIMIT1选择后需要P1，App不能自行SQL或扫描fullScope获得anchor。先单独原生红/绿子提交，仅原move_execution_repository.py+原move_row_repository.py，新增MoveExecutionRepository.apeek_claimable_item(session,*,lease:JobLease,jobs)->MoveExecutionSnapshot|None。前缀原_execution_job(_move=True)、active job lease、require_job_ready、实际配置（obsolete沿原flush/None由caller commit）后，原MoveRow新增aread_move_claimable_id(session,*,job_id,now)仅native current tenant、pending/running且pending或lease_until NULL/<=now、file_id/version_id升序、LIMIT1/FOR UPDATE读id，tenant/TX每await核。随后复用原aread_item完整单项actual-after/snapshot/anchor读取，不发P1 receipt/不改变Item或Job lease。Owner在同一持锁TX据peek真实anchor签P1后仍调用原claim内核，并核actual claimed item_id及anchor等于peek；peek不是claim授权。

原普通四kind/kernel query完全不改；peek双条件必须用真实pending、未到期running、NULL/过期running、排序/空集与原claim同输入逐项比较做防漂移控制。两个predicate各写在其真实SQL查询中，不把普通内核改成额外SQL/新路径。新Exec仍≤600：允许把现纯私有_pending(session,ids)原AST完整移入已使用的MoveRow基类（该叶原已依赖这些Knowledge实体），Exec继承调用不改行为，以免压缩format或设新大叶例外；不挪DTO/不增第四叶。MoveRow单id getter不依赖Exec业务属性。原transport/_job/getter/Retry算法不改。测试401/10001参与项/独立projection变化下peek SELECT/row读取恒定、0fullPlan/manifest，坏TX/tenant/DI/ready/default路径拒；peek→P1→actualclaim真实同TX、错peek actual差异整SP回滚，None obsolete确实commit。此窄口先提交后再A1两个应用叶消费，原T09192仍整卡待办。


## 122. 正式权限Catalog DRAFT精确SQL物化：已冻结

EDGE原T157/T158内部首片，先native红再仅新permission/domain/repositories/f118_catalog_write_repository.py（≤600）+原f118_migration_snapshot_repository.py窄事实读取口，不新任务编号/不提前闭整卡。原F048 writer固定initial key、重建ACTIVE来源且tuple前CURRENT，其PermissionMigrationRun/Item不是F118账，不复用该coordinator。generic SqlCatalogState._replace_children虽保floor却丢legacy_source_key，不能照抄该缺口；本片保所有typed provenance，不借机改无关在线发布流程。

新增F118CatalogWriteRepository（可注入同原SnapshotRepo，默认实际原实例），方法：averify_before(session,*,expected:PermissionCatalogBaseline)->None；astage_catalog(session,*,permission_planner:ResourceRetirementPlanner,draft_id:int,target_authorization_release_id:int,operator_id:int,idempotency_key:str)->PermissionCatalogBaseline；averify_staged_catalog同后五参数→PermissionCatalogBaseline。原SnapshotRepo新增aload_catalog_release(session,*,release_id:int)->PermissionCatalogBaseline，按原完整原始typed列/Action scope/Model selected-effective links读取，允许DRAFT/STAGED作为事实，不冒已满足CURRENT/ACTIVE。原aload_catalog_baseline签名/行为/SQL预算保持，可抽原相同内容读取helper，不新旧逻辑分叉或反复全Catalog；不再导任何business ORM。

caller须实际AsyncSession、active原TX、concrete tenant、非bypass、无pending ORM业务写；每受控await前后O(1)检查原tenant/TX/pending，不新Session/commit/事件/ContextVar。global表读取不依赖猜tenant1，原Snapshot严格scope。首片SQL与后继原Run checkpoint由实际App同一原caller事务/SAVEPOINT拥有，Repo可在签任何live proof前用自有原SP保护本片批量children写；不提交父事务，不新ledger/queue。晚失败/cancel/外catchcommit不能留下半children、改旧CURRENT或auth。

真实原序列：完整before核验→现OpenFGAMigrationModelPublisher.aget_or_publish以实际target builder/checksum发布或复用并持久化真实auth row→原SqlCatalogState.reserve_draft(base_release_id,operator_id,idempotency_key,expires_at)得到持久reservation→caller原TX调用astage_catalog、写原Run checkpoint→commit ACK。本片不实现Publisher/CLI/App/checkpoint，不伪造target auth、不调用旧bind_draft_authorization_release自开事务来冒原子提交。原reserve native已证：空DRAFT/zero checksum/无children，predecessor原CURRENT、version全局max+1、原auth继承；不改原CURRENT/write_fenced、不复制children。本片不能假设reservation已绑target。

先真实锁读原CURRENT、实际DRAFT、实际target auth并规范锁序；before全部原typed facts精确等冻结plan.before（包括原CURRENT header/auth/原active与inactive Models/actions、legacy/floor等）。draft_id不是许可：同时核actual status=DRAFT、predecessor=before.id、version>before.version、唯一合法原release_key、draft_owner_id=operator_id、原idempotency_key一致、未有publication commit/projection checkpoint/write fence等越阶段字段，原reservation expiry初次应仍有效；operator沿原reserve规则为严格int且≥0（保留运维operator=0），其它release ID严格正int；key须非空无NUL且≤64字符，实际release_key严格使用原catalog-v{version}-{sha256(key)[:10]}配方；不接受bool或别的run reservation。禁止拿任意传入ID重选基线。已有完整staged结果走精确只读重验，不因expiry本身重写；半成品、额外/缺行或不同checksum/绑定直接拒，不静默replace/修复。更晚STAGING/READY/CURRENT等恢复属于后继相应阶段验证，不扩本片状态白名单。

target auth从实际row判两支，不接bool hint：若plan.target_model_checksum==before.authorization.model_checksum，只允许exact before ACTIVE原ID、全部原pin字段相同，原predecessor不改；真实builder+原publisher已证此路remote list/write0、新STAGED0。若不同，必须新实际STAGED、相同environment/store、目标checksum、predecessor_model_id==before.model_id，model_id非空且与before不同；required_relations_checksum等实际publisher metadata须合法完整并保原值，后继固定pin/FGA body验证才可证明真实schema，无本片激活。最终同ID分支auth不写状态；异ID激活新/退役旧留后继。不能无条件强制新STAGED或将同一auth自身退役。

首次只在正确空reservation物化plan.after_actions及完整resource scope、plan.after_models及selected/effective action links；所有原模型policy字段按原typed After保留，特别legacy_source_key/retired_use_level_floor/visibility-only scope/level/kind/derived_level/allow_same/active/name/normalized_name。新children用实际DB分配PK，与before可全不相交；按model_key对照原pure verifier的ID规范化，不强行复用原PK，不动旧CURRENT children/Grant/Assignee/VisibleSource/业务表。IN/写入批≤200，按表有界批量读写、不每Model重读全Catalog，不依赖MySQL方言或JSON SQL。

new draft checksum使用已实测与真实在线CURRENT相同的SSOT payload：permission._checksum({actions:plan.action_checksum,models:plan.model_checksum,predecessor_release_id:before.release.id,release_key:actual_draft.release_key})；这组字符串/整数与SqlCatalogState算法字节同，不另造checksum。stage仅填完整children、该checksum和required auth targetID；新DRAFT的update_time允许数据库按原规则维护，不新增应用时钟容差，其余原raw身份/expiry/audit字段（含create_time）严格原样并在写后逐列复核；旧CURRENT及auth原raw全列完全不写。读回恢复原typed facts，actions精确等plan.after_actions、models按model_key规范化id后全字段等plan.after_models；同时用实际SqlCatalogState.load_snapshot/原canonical action/model checksum算法核一致，不仅比较在线checksum（该checksum不含legacy_source_key，native已证丢legacy仍在线绿但纯F118拒）。不得将DRAFT/STAGED包装成CURRENT/ACTIVE给pure最终verify；实际status始终保留。

测试native真实Snapshot/原reserve/实际STAGED（和exactACTIVE复用）及所有tables：正常完整全字段/新PK、既有结果0DML重放、旧CURRENT逐行全列不动、auth全行不动；wrong原before/actor/key/pred/version/expiry/target checksum/env/store/model predecessor/status、首空/半写/额外行/metadata漂移、真实中后页SQL失败/cancel/outer catchcommit都拒且零半写。含非空legacy/floor3/纯可见/ inactive/Unicode，缺legacy在线checksum绿而本片拒的控制、同schema ACTIVE复用0外IO原行为控制。401/1001 Models及完整links读取/写入SQL/参数/内存按O(M+A+links)测，derive固定常数不随资源/tenant乘增；source/resource/count/FGA IO全0。MySQL与ANSI Core编译静态兼容，DM8 live用户免测。

后继资源SQL、原Run CAS/checkpoint、FGA全量before与发布/active pointer/最终SQL切换各另冻。FGA before原无稳定页序，允许明确一次全Store tuple identity集合/重复计数精确差集，CPU/内存O(F)，不以两次rollinghash冒集合等值或漏extra；本SQL首片不实现排序/第二存储框架。最终同短TX维护新Catalog CURRENT/旧RETIRED以及必要auth状态和原Run checkpoint，不能仅stage成功解除停服、开Coverage或宣称正式权限升级完成。


§121确认只读公口补正：A1需要可信原Plan bytes才能接same-subject新凭据replay，原public get-for-execution先要actor且强expiry，不能冒替；不让App直接耦合原私有_plan。PROC先独立native红/绿，仅原MoveJobRepository窄增aread_move_confirmation(session,*,source_space_id:int,confirmation_id:str,plan_digest:str)->KnowledgeOperationPlan，委托原_plan完整tenant/原Plan hash校验(check_expiry=False)，再严格operation='move'/space_id/sourceID/plan_digest精确相等（错沿原idempotency/plan错误），无新SQL或算法。它只返回原事实、不授权/消费/续期；expired未consumed的新接受仍由原acreate_move_reserved实际expiry门拒，已consumed合法重放可读旧facts。App不接外来actor bytes、不回传private参数，当前身份资格另核；worker逐item不能用此口读大Plan。只此2–3行窄转发/校验，不扩原普通PlanGetter/Schema。与claimpeek两Repo子片可同波独立提交后再A1消费，原方法AST不改。


## 123. 原真实目标删除证据RRT的受信写边界：已冻结

PERM为原T115–118及T109110准备共享小前置，不新任务编号、不提前勾业务删除整卡。现RRT已有模型/DDL、原TargetOwner/resolve_target_state读协议，但无受信生产写入口；只新增resource_reference/domain/repositories/target_deletion_repository.py（≤600）+原application/write_runtime.py必要窄桥。不改Model/Knowledge业务Repo/Core、PlanRepo、API、FGA、任何Source/Brr或Coverage。不是通用任务/依赖平台，只写已有3种Target的原RRT证据。

原ReferenceBindingRuntime constructor可追加可选target_deletions=None，默认创建与本实例repository关联的实际TargetDeletionRepository，构造0IO/0SQL；原构造两位置参数及全部Source writer行为保。Runtime新增aprepare_target_deletion(session,*,receipts,operation_id:str,operation_type:str,actor:PermissionActor)->int与afinalize_target_deletion同参→int，返回本次新增/推进数，exact replay0。它们用本runtime.verifier.validate_owner_receipts及原repository.target_owner_scope，不新receipt/capability/issued registry；repository.verifier必须同runtime实例，复制/他issuer/旧TX/跨tenant Scope拒。新Repo对应aprepare/afinalize(session,*,scope:OwnerTargetScope,operation_id,operation_type,actor)->int，只消费原受信scope，不从裸TargetKey生成许可，不查business ORM。

这些口只记录事实，不授权业务删除、检查引用/force或证明外部FGA完成。实际业务Owner必须先核原动作/管理员、完整影响及原确认Plan，持实际Root/Model/File target锁，关联原同operation；调用方保证真实业务SQL已删/清对应target后才finalize，并将最后业务SQL+finalize+原Plan/进度置于同一原TX/SAVEPOINT。不能用此RRT helper当删除或强制许可，也不以先写DELETED替代业务验证。模型分享IO前若需持久DELETING fence，其prepare原事务与原Plan.consume要由后继Owner协调；本片不打开API或另造协调账。

只原已有stage='deleting'→'deleted'，不降级、不删除/改写其它operation evidence。operation_id原非空无NUL≤64字符串，固定业务operation_type闭集：model_update_server/model_delete_server仅MODEL；knowledge_file_delete仅KNOWLEDGE_FILE；knowledge_space_clear仅KNOWLEDGE_FILE（space保留，不能标space）；knowledge_space_delete仅KNOWLEDGE_SPACE/KNOWLEDGE_FILE。actor只真实PermissionActor的user/service_account及严格正int subject_id，以typed主体存actor_type/id，不用audit user替代、不存credential/角色/姓名；home tenant不强制等执行tenant，实际目标Owner必须全部同当前concrete tenant。空receipts可在全部native上下文/参数检查后返回0，不造scope/tombstone，支持空server；空结果不授权任何业务写。

native active AsyncSession、concrete tenant/非bypass、无pending业务ORM；Context在入口固定、每await O(1)检查原tenant/TX与UOW，不重新capture替换。**实际caller须在签receipts之前建立共同SAVEPOINT**；已签receipts后新增nested会使原证据TX失效，故本两叶不begin/nested/commit/rollback。错误传播给业务Owner；其外catchcommit不得留下半证据。所有候选先完整有界锁读和验证、再批量写，后页冲突/无效Evidence校验阶段0DML；SQL/取消等异常由共同caller SP回滚。

新Repo按scope真实keys/owner tenant分组seek/批≤200查询RRT（不用全表/Source扫描）；一次建立TargetKey→verified事实索引。先完整核现有行唯一、owner/type/id、operation/type/actor精确一致、stage与deleted_at合法；缺行仅prepare可插入，finalize缺行拒。prepare首次只VALID目标可新建deleting；原INVALID_LEGACY禁止造‘被删’原因。已有同op deleting/deleted只幂等不退回；若fresh receipt为DELETING/INVALID_DELETED，其真实DeletionEvidence也须exact同目标/owner/operation/stage，不能拿ancestor或别的op当本target直接记录。已有同TX原VALID receipt可完成其自身新建RRT，前提actual RRT行与该operation精确一致；不让receipt状态替代实际表核验。不同op/metadata/NULL owner/未知stage/缺末页或copy均拒，不覆盖原证据。

只原RRT插入及stage/deleted_at/update_time推进，actor/operation/target/create_time一经存在原样；stage deleting.deleted_at为NULL，deleted.deleted_at非NULL，同op重放保第一次时间。clock使用UTC naive秒精度（可构造注入测试），不靠方言upsert/JSON SQL；真实唯一target owner锁保证并发次序，bulk Core每批≤200。最终DML明确PK+owner tenant+type+id+原stage+operation，rowcount准确；不update任何BRR.target_*或legacy字段、Source revision/digest、模型配置/任务或Grant。完整Scope/receipts核入口/尾部固定常数次，不每行/每页重扫全targets，跨await仅O(1)guard。

native先红再绿：实际registered模型及知识TargetOwner facts、Source真实包含共享跨tenant绑定但Source/Brr全表字节不变；VALID→deleting→实际business SQL删除→deleted及fresh Owner读取INVALID_DELETED、同op两阶段0DML重放/时间不变。错op/type/actor/foreign/NULL/legacy/祖先删除证据/未签或copy/旧TX/nested/tenant/pending、后页冲突、第二批SQL异常和asyncio.CancelledError共同SP外catchcommit全部0半证据，外层无关已执行DML保。empty server无RRT、clear不能标space。401/10001 Targets实际读取/验证次数/SQL/参数峰值线性，Source/BRR SQL0，per-batch≤200/C2 Core编译静态，DM live免。实际业务Owner/强删确认/分享投影/模型缓存与运行准入失效仍后继，不以本helper通过宣称force delete可用。

§123实际受信写补正：按exact(type,id)每批≤200短bypass读取RRT，不能用owner WHERE把同key的NULL/foreign owner行过滤掉，再逐行核两侧owner。原同TX DELETING直接证据经本operation finalize后，实际DELETED允许同op单调幂等重放0；反向证据DELETED而实际仍DELETING、祖先证据、别的operation均拒。此补正不允许helper新开SAVEPOINT。
