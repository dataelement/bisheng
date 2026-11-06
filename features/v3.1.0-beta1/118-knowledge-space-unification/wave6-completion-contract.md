# W6 完成阶段接口合同（2026-11-06）

基线 `2364add1bb80a7fef670d42a99b2833558dc3231`，工作区干净，剩余137张原卡。继续94条AC和既定范围；不合入并发发版线变化。接口按下列子合同分别冻结，未冻结的接口不得由消费者猜测。新增叶子只补原卡真实接缝，不计新产品功能。

## 1. 两端 API 子合同 V1：已冻结

字段权威为现有 `processing_settings.py`、`processing_job.py` 与 contracts.md A1。TypeScript逐字段保留snake_case；数字实体ID/版本为number，日期为ISO string，job/confirmation为string。四类processing precheck用kind判别联合；targets三元组保留真实file/document/version身份，输入document_id允许省略。JobAccepted保留原state/reused，accepted不代表完成。create请求只有idempotency_key/confirmation_id/plan_digest；retry只有idempotency_key/expected_job_revision。

`PageData<T>={data:T[],total:number}` 与目录现有 `CursorPage<T>={data:T[],page_size:number,has_more:boolean,next_cursor:string|null}` 不混用。OperationPrecheck完整镜像已存在DTO，impact暂为 `Readonly<Record<string,unknown>>`，只透传、不据未知子字段推断操作。隐藏项不推导名称/内容，invalid item可无id/type/name。接口错误保留原status_code/status_message/data，不吞异常、无失败fallback。

平台API在现有knowledgeSpace.ts，hooks在controllers/hooks/knowledge.ts；客户端新增api/knowledgeProcessing.ts，保留旧knowledge.ts的2012行原调用兼容，展示types只做消费。不跨两应用导入页面/hooks/store，不新增公共框架/依赖。

API导出 `getSpaceInfo(spaceId)`、`listChildren(spaceId,原query)`、`listAdminSpaces({keyword?,page,page_size})`、`getProcessingSettings(spaceId)`、`updateProcessingSettings(spaceId,ProcessingSettingsWrite)`、`precheckProcessing(spaceId,ProcessingPrecheckRequest)`、`createProcessingJob(spaceId,ProcessingCreateRequest)`、`listProcessingJobs(spaceId,{page,page_size,kind?,state?})`、`getProcessingJob(spaceId,jobId)`、`listProcessingItems(spaceId,jobId,{page,page_size,state?})`、`retryProcessingJob(spaceId,jobId,ProcessingRetryRequest)`。路径严格沿用A1和既有目录路由；平台独有admin能力不在客户端添加管理入口。

缓存键显式包含可信当前身份、tenant、space/job、筛选及普通/admin范围；平台另含managementTenantId。异步mutation捕获发起scope，scope变更后不能写入新scope缓存或复用旧确认计划。默认使用原wrapped axios/request；测试注入同形API port，不设生产mock开关。客户端React-query/Recoil、平台React-query/Zustand保持。T175/T187只交付请求与Mock合同，真实路由尚未装配，T200/T201及后续页面联调仍是独立门禁。

待后续冻结：file-operation五类请求和执行confirmation扩展、R3影响/强删路由、创建模型/默认策略字段。当前不得实现猜测的force/skip协议或新路由。T184模型真实删除在ModelConfig/ModelItem；T185真实来源选择器在selectComponent/knowledge和KnowledgeSelectItem，原任务叶子后续先校正登记。T193平台、T194/T195客户端，单一Owner串行。

## 2. PROC / KN 子合同：待补齐真实前置后冻结

T064与T076派发依赖须拆最小前置；确认计划持久应用、job查询/扫描、最新retry actor、当前业务Owner同Session与真实worker尚未闭合。不能以fake Service或未接入helper交付。T074还依赖移动的整版本/对象manifest；元数据与文件旧入口内部commit需显式整合。全部保持文件原edit/rename动作、业务配置读取模型、AC54代际规则，在途外部IO竞态治理仍不在范围。

## 3. 执行与环境边界

INT统一合同、任务、locale、共享装配与合流；各lane从冻结提交建立独立worktree，只写登记叶子。测试先提交，再实现，已有正确行为如实记首绿。禁止repo-wide stash/reset/clean/无path restore及整文件theirs；不覆盖其他worktree。不push、不自动合入发版线。

用户已提供109:3005专用验证环境并授权准备场景数据、验证迁移升级。首次只读确认该入口是DM8部署，后续限定其关联服务与隔离测试租户；同机其他部署不得改动。凭据不入仓库/报告。停服升级须先一致备份再正式盘点冻结，脚本不探测/控制停服。完整双库、中间件、浏览器E2E及备份恢复需实际证据，不能用单元测试或HTTP健康替代。
