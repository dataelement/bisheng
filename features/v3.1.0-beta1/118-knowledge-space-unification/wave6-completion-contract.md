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

## 14. 平台普通清单、创建初值与 scope 子合同 V1：已冻结

先补原T176/T178真实前置，不增加产品能力。`GET /knowledge/space/creation-settings`为静态路由，沿原`KnowledgeCreationPolicy.prepare(login_user)`核原web凭据和创建菜单/角色，不将普通创建改为仅管理员。应用用例`get_space_creation_settings(login_user, *, session)`用外部native Session读取真实`model_default_read`的`aget_default(linsight_llm, login_user=原identity, session=原session)`；这是修复/显示原配置的读取，不调用严格执行准入或先核所有默认模型。返回闭集`{embedding_model:{id:string,name:string}|null,system_defaults:ProcessingDefaults}`，只投影工作台Embedding原ID/名称；保留已失效原ID供显式修复，不回退其他默认、不选第一个模型、不输出provider/其他配置。系统规则复用已有`system_processing_defaults(0)`纯schema投影；0不作资源查询、授权或持久化。此GET零SQL写/无FGA变更/无任务/无模型执行，普通读取不加管理租户写头。

平台API新增`listVisibleSpaces({keyword?,page_size?,cursor?}={}) -> CursorPage<KnowledgeSpaceInfo>`（列表缺详情字段允许省略，不补造计数），`getCreationSettings() -> SpaceCreationSettings`，`createSpace(body:KnowledgeSpaceCreateRequest,expectedManagementTenantId:number|null) -> KnowledgeSpaceInfo & {initial_permission_result?:现原始结果}`。创建body严格镜像现有KnowledgeSpaceCreateReq，使用embedding_model_id/processing_defaults；无tenant/admin/type/旧model别名。任一高级字段非null时，API必须使用发起时捕获的正整数managementTenantId签`X-Management-Tenant`，缺失则拒绝发送；普通简化创建保持原无头路径。后端仍独立重验当前管理scope。无新通用request路由分类，不将所有普通POST空间操作改为管理操作。

hook新增`useKnowledgeVisibleSpaces(scope,queryWithoutCursor,api?)`（useInfiniteQuery，next_cursor保不透明，空data且has_more=true仍可继续）、`useKnowledgeCreationSettings(scope,api?)`、`useCreateKnowledgeSpace(scope,api?)`。query key带原identity/tenant/managementTenant/view和筛选；mutation开始捕获scope及管理tenant，切scope后旧返回不得给新scope写cache、跳转或返回可被新页面消费的成功值；仅成功后失效发起scope列表，失败保原ApiError。测试port扩相同方法，不设生产mock开关。

后续创建表单只在原ID为正整数字符串时转number；失效/非数字默认显示待修复并要求有效显式选择，禁止NaN→null触发默认回退。T178先做受控规则编辑/父级草稿边界，系统初值必须来自此GET；先不改T179旧上传到默认接线完成。T176拆为列表shell、单叶create、detail另卡，T177目录/版本另冻结；locale由INT统一三语提交，不全局替换仍并列的旧selector标签。
