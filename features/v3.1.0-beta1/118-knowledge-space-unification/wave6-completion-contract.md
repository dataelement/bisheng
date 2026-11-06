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

用户后续确认109:3005属于中粮定制分支，要求另部署全新标准环境。此前3005仅做只读巡检、零数据或部署写入，现不再用它验证本功能。INT在109另建独立端口、网络、数据库及卷，使用标准版本源码；同机其他部署不得改动。凭据不入仓库/报告。停服升级须先一致备份再正式盘点冻结，脚本不探测/控制停服。完整双库、中间件、浏览器E2E及备份恢复需实际证据，不能用单元测试或HTTP健康替代。

## 4. KN 生命周期、创建与清单子合同 V1：已冻结

T077/078不依赖T064，容器adapter只验证存在/类型/租户和合法已知生命周期，复用现_lifecycle_target；继承/自定义仍统一F048。处理态不等于删除/不可见，不在adapter叠文件edit或父子visible动作。冲突写与检索暂停仍由真实用例T098/T102闭合，不把生命周期放行当作允许冲突写。

T080扩展现create_knowledge_space原参数后增加embedding_model_id:int|None、processing_defaults:ProcessingDefaults|None、web_creation_context:KnowledgeCreationContext|None，复用现KnowledgeCreationPolicy和原R2原生Session创建链。省略新字段与现前台行为相同：工作台默认Embedding仅创建时复制为自身model/ref，处理默认规则不回写历史文件。显式高级字段只能由真实web后台创建资格提供context，并在写前revalidate；保原user身份，管理执行tenant来自可信scope，不能用body tenant/admin标记或强换user tenant冒充。高级创建conditional核X-Management-Tenant，普通简化创建不新增头要求。现policy允许超管/租管及合法CREATE_KNOWLEDGE菜单资格；管理全量清单角色另严格限定，二者不混淆。

CreateReq仅新增可选embedding_model_id正整数、processing_defaults，原字段/响应/审批/安全/标签/配额保持。幂等payload hash包含规范化显式新字段；新行processing_config_version=0，初次PUT再递增。可用模型复用真实Model Owner/共享/类型检查；无合法model、R2失败或配置校验失败不能留半个space/ref/defaults。

普通新增GET /api/v1/knowledge/space/list：keyword?、page_size=20(1..200)、cursor?→PageInfiniteCursorData[KnowledgeSpaceListItemResp]，无page/total。固定update_time DESC,id DESC，cursor绑定实际tenant、原身份及筛选上下文，校验合法键并处理旧NULL时间。SQL仅具体tenant/type3候选seek，每批至多100、每请求至多消费1000候选；以loaded-row F048批量visible筛选，不做全量listObjects/5000上限前置。cursor取最后消费候选，预算耗尽允许空data但has_more且cursor前进；不漏过未消费项，不从子项授权推导root可见。数据连接释放后再做权限IO。

管理员GET /api/v1/knowledge/space/admin/list沿A1：keyword?、page=1、page_size=20(1..200)→PageData[ListItem]。Service list_admin_spaces无客户端tenant参数，核真实超管/所选租管和可信单一具体tenant；Repository COUNT/LIMIT/OFFSET，不按visible/置顶筛成普通清单。只放开既定管理资格，后续各操作仍校验业务限制，copy仍仅创建者。

KnowledgeSpaceListingRepository新增alist_candidates(keyword?,after?,limit)和alist_admin(keyword?,page,page_size)，SQL按C3具体tenant，服务list_visible_spaces负责预算/权限/消费cursor。T080/T082/T647同一KN Owner串行热文件；T649负责已有schema+router接线，静态list/admin路由在动态id之前。T646/T648用真实SQL候选与实际route转发验证。平台普通列表/创建页面消费者尚待后续明确卡接线，不以后台API单测标UI完成。

通用文件操作、R3删除、移动manifest/确认与结果扩展尚待下一子合同；不复用PROC版本三元manifest伪装folder/model，不改变旧null/boolean/url结果形状。T085/T087已识别的假串行依赖待真实计划接缝冻结后重排。
