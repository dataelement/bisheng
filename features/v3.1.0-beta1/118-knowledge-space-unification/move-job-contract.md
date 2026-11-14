# F118 J1 下一阶段冻结候选（只读，2026-11-07）

本次源码核验：MIG clean `8e3be041e23737716e576e84e94b44bc7575c91f`；主树读取时为 `f74c6b43c1641f90b494b325d71385410f48ec82`。Job/Retry/identity/worker 相关现有叶两点间没有改动。此稿不是代码授权、上线接线或真实数据库升级证明。

## 1. 可以立刻冻结的 subject 索引事实

实际 PermissionActor 的 subject_type 仅 `user | service_account`，user_id 旧别名直接返回 subject_id。web 为 user；S 为 service_account；D 必须取实际 authorization subject（通常 user），不能取 credential.actor_id、resource_owner_user_id 或 Job.actor_user_id。后者继续只是原审计用户字段。

### 1.1 两表字段及唯一写口

`knowledge/domain/models/knowledge_processing_job.py` 与 `knowledge_processing_retry.py` 各增加：

- `actor_subject_type: str | None = None`，SQL String(32)，nullable；私有/exclude，不增原 HTTP wire。
- `actor_subject_id: int | None = None`，SQL BigInteger，nullable；私有/exclude。

不设 user/0 server default，不用 audit_user 自动补值。Job 按真实 job UUID/tenant 精确读取，暂不增加无消费者的 subject index。Retry 增加非唯一复合索引：
`ix_kpr_job_subject(tenant_id,job_id,actor_subject_id,actor_subject_type,accepted_job_revision,id)`。
保现有 request-key UNIQUE 和 revision index。

新 move Job 的唯一写入位置：实际 `acreate_move_reserved` 在原 K1 reservation 验证/消费的同 TX，按原 FrozenProcessingActor 的 reference.actor 生成两标量。新 move Retry 的唯一写入位置：实际显式 retry 接受、Job revision CAS 成功的同 TX；接受新原身份，旧 Job.actor_reference 不覆盖。幂等 retry 读取原真实 receipt，不新写/改主体。

冻结一个纯 Domain decoder（建议新 `knowledge/domain/schemas/processing_actor_subject.py`）：

```
@dataclass(frozen=True, slots=True)
class ProcessingActorSubject:
    subject_type: Literal['user','service_account']
    subject_id: int

def processing_actor_subject(reference: Mapping, *, tenant_id: int,
                             actor_user_id: int, source_space_id: int
                             ) -> ProcessingActorSubject
```

它只解析现 FrozenProcessingActor wire 的 subject 闭集：schema_version/tenant/audit/space/action='move'/entry_kind 与 actor typed facts 的一致性、严格 int 非 bool/float、正 ID、两种 subject、原 data_scope/管理集合形状。credential_reference 仍由原 capture/restore 验证，不在此重写 provider credential decoder，不拿历史 credential 过期当“从未接受”。原 `processing_identity.py` 的 move capture/restore subject 提取调用这一纯 SSOT；其 payload 字节、credential_reference、expiry/token version/ceiling/原 home+management pin 规则不变。四原 kind 不新加这层主体准入，也允许两列 NULL。

实际 current credential 的权限仍由原 restore_processing_actor + MoveOwner 准入；这两个索引列与历史 membership 都不是新授权。

### 1.2 有界真实 membership

将候选接口名从易混淆的 `actor_user_ids` 明确为 operator（原 P1 operator_id 是实际 subject_id）：

```
aoperator_membership(session, *, job_id: str,
                     operator_ids: tuple[int,...]  # <=200, 严格正 int
                     ) -> frozenset[int]
```

空候选 0SQL；当前 tenant 严格/native/no_autoflush。先精确 Job 一行并核原 reference.actor 与两标量一致。Retry 查询只针对本 job、候选 subject IDs、合法非 NULL 两种 subject、实际接受 revision；用数据库 scalar 分组为每 `(subject_type,subject_id)` 选一个真实 receipt PK（如 MIN(id)），再按 PK 有界取原 frozen reference 验证对应 subject。候选拆 <=100 可保证两种 type 的 grouped/PK 每 SQL <=200。不把所有历史 credential JSON 拉出，不按每个 change 查询，不用 JSON_EXTRACT/CAST(JSON)。标量索引范围内同 subject 的重复历史事实可以参与聚合，但输出/ref 读取只随候选 typed subjects 增长，不能宣称数据库完全不访问匹配的历史 index entries。

Job original + 任一真实 accepted retry 都可证明 membership；不能只看 alatest_retry_actor，否则旧部分 FINALIZED projection 的原 operator 会被新 retry 误排除。原 latest 方法仍只用于恢复本次 current 执行身份。

P1 现 ledger 只存 numeric operator_id，不包含 subject_type；本口只能兼容验证“该数字确属于本 Job 接受过的真实 subject”，不能虚称修复了原 ledger 的 typed actor 编码。完整当前身份/ceiling 仍在 Owner，不能用 numeric 集合代替。

### 1.3 DDL / 旧行 / 升级前置

源码 Git 事实：正式旧功能基点 `a1b1a2387949950eafe17679810f2df8eabae10b` 无 ProcessingJob/Item/Retry 表模型；Job/Item 引入于 `9547b78cf14ea0bc261ec670ad60b82c897c4ca8`，Retry 引入于 `f03b826ea5071a6a8854a312e15ba807a8420550`。MOVE_INDEX 枚举存在不等于生产已接：现 ProcessingJobService.available_kinds 仅四 kind；worker PROCESSING_HANDLERS 无 move，metadata 另原分支。故没有已接通的旧 move 产品路径。

这不证明任何实际库没 trial/手工行。启用前 root 做只读现表盘点：kind='move_index' Job 数与主体 NULL/非法数、相关 Retry 两标量缺失数；若存在无法证明主体的旧 move，显式 fail closed/运维处理，不按 audit 猜主体，不在线回填，不把其纳入 accepted membership。四原 kind 的 NULL 不拦原读取/运行/重试。

Root 独占 DDL：4 nullable columns + 1 index，DDL-only，不解析 JSON/写业务行；复用当前 Alembic helper/create_all 已有列和索引的幂等检查。当前本地实际 `alembic heads` 单 head=`f118_finalize_retry`，实施前必须 live 重核真实 parent，不能另造平行 head。Model 与 DDL 保 MySQL/DM8 C2 静态；用户免 DM8 实库，不能记 DM8 已实测。

## 2. reserved / ready：现 Repo 真实缺口与精确合同

原 `processing_job_repository.py` 1283 行。不能继续把所有增量塞进热叶；建议加一个 move-specific `move_job_repository.py`（<=600），原 public JobRepo 留薄委托/原 lease 的 move 精确分支。不抽通用任务平台/注册框架，不改变四原 kind 的结果。

```
acreate_move_reserved(session, *, reservation, idempotency_key,
                      actor_user_id, actor_reference, parameters,
                      items: tuple[NewProcessingItem,...]) -> JobRequestResult
amark_move_ready(session, *, logical_receipt, lease: JobLease) -> JobAccepted
aoperator_membership(...) -> frozenset[int]
```

K1 实际接口（作者确认，不猜同名 hash）：MoveReservation 含 `plan_request_hash`（实际 OperationPlan.request_hash）、plan_id/plan_digest、actor_reference_digest、source/destination IDs、scope_digest、index_item_count、完整原 Scope 私有引用。`aprepare_reservation` 尚无 Job，不能签 Job.request_hash。

- J1 自身用原 `_digest` SSOT 对完整实际 Job acceptance payload（含全部 leaf snapshot、compact header、scope digest、原 actor）算 Job.request_hash；不得拿 plan_request_hash 顶替。
- 必须实际 K1 原对象/issuer/native Session/同 TX 验证；`aconsume_reservation` 一次调用真实 plans.aconsume(operation_id=真实JobUUID,expected_digest)，只有 flush。裸 dict/dataclass/hash 不接受。
- 同 key 同真实请求返回原 Job；不重复消费。换 key 不得对同 consumed Plan 建第二 Job；同 key body/actor 变化冲突。错误与外层 catch+commit 均不留半消费/半 Job。
- Job.space_id=destination；Plan.space_id=source；Job UUID 由真实 reservation 固定，不另造 UUID。
- Job.parameters 仅紧凑闭集 locator（plan/confirmation/digests、source/dest、configuration8、完整逻辑 scope digest/changes digest/count）；不存完整 Scope/全部逻辑 rows/重复叶快照。
- Job.scope_manifest 只参与索引的真实 target 三元组 + expected destination/parent + snapshot_digest；完整 snapshot 仅 Item.processing_snapshot。完整逻辑 scope（目录/非 SUCCESS 文件也含）只原 Plan 一份。
- 普通 acreate 不放宽空集，且 move 不得绕过 reservation 进入普通 acreate。

### 2.1 0 items 与 ready 闭合

空目录/全原失败文件的跨空间 move：逻辑 rows 非空、index items 可为0。reserved 仍 accepted/pending_dispatch=True，必须由原 scanner/worker 执行真实 FGA+逻辑。

`amark_move_ready` 只能消费原 native K1 MoveLogicalReceipt，核当前 JobLease/claim generation、实际 Job request_hash、plan绑定/after scope/projection证据。同 TX 将 compact logical_move marker 写各真实 Item.checkpoint（不改 immutable parameters/request_hash）；非零保持可继续 pending，零仅此时转 succeeded/pendingFalse/finished。无 dummy Item。

必须同时封住真实现口：
- afinalize 当前对总0可直接 succeeded：move 未 ready 必须拒绝，不能绕过 receipt。
- aclaim_next_item 当前不知道逻辑 ready：move 必须单项实际 marker+链校验后才签 ItemLease，未 ready 不签。
- aretry_eligibility/aretry_failed 当前0 items不可 retry：失败但尚未 logical 的0-item move 需显式逻辑 retry，发原 RetryReceipt/accepted pending；不错误 finalize-only。
- 0-item logical 已完成成功不再 retry；非零 successes/result/checkpoint/attempt 不动，失败/pending 仅原显式 reset；lease/generation 复用。
- 全量 marker 原子写入一次；后续每 item 仅读自身 marker。无 marker 的 generic finalize 不可借 succeeded counts 绕过。

## 3. 热叶 exact move 分支与新 execution Repo

只扩 move，原 metadata 分支和另三 kind 回归保留：

1. `_job(...include_manifest=False)` 目前只对 metadata 不 refresh manifest，move 也必须 defer/raiseload；counts/retry 用 total_count，不 len(manifest)。public get/list 可读完整但已经 compact 的 targets。
2. `aclaim_next_item` 目前非 metadata 取全候选，move 增 expired/pending SQL 谓词+稳定 file/version ORDER+LIMIT1，防 N items × N candidates。批量失败/重试同样 defer Item.snapshot，不在改状态时读全快照。
3. Job claim/renew/item guard/checkpoint/complete/finalize/retry/fail 的 move 都由双 Root 实际 SQL 配置核验；原 ProcessingConfiguration 只有目标 R/G，不足。锁双 Root 按ID稳定顺序，然后 Job/Item，不先 Job 再取 Root。
4. source/destination 任一 R/G/index identity 变化：持久 obsolete/停止派发/失效 lease，caller commit ACK 后停；不抛错误回滚刚记的 obsolete，不清 source，不把历史 Job 值当当前配置。
5. actual EXECUTE_TASK proof、旧 token/generation/leaseUntil、失败保持原错误类型规则复用；无新 worker credential、queue、fence 或模型绑定。

新 `knowledge/domain/repositories/move_execution_repository.py` <=600：

```
aread_configuration(session, *, job_id) -> MoveConfiguration
aread_item(session, *, job_id, item_id) -> MoveExecutionSnapshot
aguard_item(session, lease: ItemLease, *, jobs) -> MoveExecutionSnapshot|None
acomplete_item(session, lease: ItemLease, *, jobs,
               source_count: int, milvus_count: int, es_count: int,
               source_digest: str, target_payload_digest: str) -> bool
```

configuration 为合同八字段；Snapshot 只有当前 Item MoveLeaf/checkpoint、实际 after File/Doc/Version/parent、双实际 Root/当前配置。Domain 完成口不 import Worker MoveIndexResult；上列五个 scalar 就是现 adapter 真实 result（另含 file_id，由当前 Item 核对）。真实 current checkpoint 必须已是 move_source_cleaned，并与这组 counts/digests 精确一致；不接 caller source_cleaned=True 取代 durable checkpoint，不复制第二摘要算法。

完整 scope 在 claim/逻辑 cutover 各线性核一次；逐 projection 只当前 parent change+两 Root+lease；逐 item 不读 Job.scope_manifest/Plan.target_manifest 或所有 retry。after proof 必须有：原 Plan consumed→本 Job、接受 scope/hash、当前实际 logical marker、当前单项 P1 durable anchor、after三行/parent与旧lease。坏尾部在首次外部 IO 前全scope核验；单项运行中坏链/旧代拒绝，不扩大为原file.edit。

失败后 source guard 仍依本 source Plan→Job→Item 真关系：成功项仅在自身 succeeded SQL ACK 后释放；failed/obsolete unfinished 仍阻断源删除/重建，不仅筛 active 状态。这个 guard/实际破坏性入口接线是后继 F1，不在 J1 仓储冒充完成。

## 4. 最小任务顺序（每实现卡最多2生产叶）

|组|测试先独立卡（建议新叶）|实现叶|闭合目标|
|---|---|---|---|
|J0a|test_processing_actor_subject.py|domain/schemas/processing_actor_subject.py + application/processing_identity.py|纯 typed subject SSOT；字节/原恢复不变，S/D/audit不混|
|J0b|test_move_actor_subject_schema.py|models/knowledge_processing_job.py + models/knowledge_processing_retry.py|nullable私有字段/真实index/四kind兼容|
|J0c Root|test_move_actor_subject_migration.py|新Alembic单叶（parent实施时核）|DDL-only单head/idempotence，无业务回填|
|J1a|test_move_job_reservation.py|processing_job_repository.py + 新move_job_repository.py|实际K1 reservation→真Job、compact/0pending、membership；实际K1固定前可写红测不假ready|
|J1b|test_move_job_ready.py|同两叶|实际P1+K1 logical receipt、0succeed/0failretry、no bypass、成功项不重置|
|J1c|test_move_execution_repository.py|processing_job_repository.py + 新move_execution_repository.py|双Root/current配置、单项after guard、lease takeover、线性claim/read与失败语义|

新 leaf<=600；现1283热叶只保精确 move 调度与可复用原 lease 分支，不在此轮大重构。若最小实际实现还需抽 SSOT DTO/helper 第三叶，先另报root登记，不暗增。

J1a/b必须等待 K1 actual fixed公开receipt验证/consume接口，再正常merge精确SHA；P1已真实native完成。J0可先独立实现但仍需root冻结授权。本轮不可开放新kind：
- 后继 A1 新 MoveOwner + 原实际 identity/capture/restore/preauth/continuation + privateK1/P1/J1，缺 composition拒绝。
- 后继 W1 move_jobs.py + processing_jobs.py；在旧 edit-only `_actor` 前按kind分流。旧 `_actor` 强制 reference.space_id==Job.space_id 且action edit，move是source reference与destination Job，不能复用该wrapper冒充move权限。
- 后继 Q1 真实query/retry/DI；不把 move 加到原四kind service available_kinds 来省资格。原API/KN入口/源fence另依合同后继组。

## 5. 原生验证清单与预算

复用现 native fixture：test_job_repo.py、test_job_acceptance_revision.py、test_job_cutover_receipt.py、test_job_query_dispatch.py、test_processing_identity.py、test_processing_dispatch.py、test_metadata_job_repository.py；保 lease/credential/token/retry/dispatch 原断言。

新增真实组合至少：
- web/D user7 vs S service_account50、同auditUser不同subject、同numeric不同type；标量/冻结ref不符拒；bool/float/0/foreign拒；四kind NULL原运行不扩鉴权。
- 200候选、多轮重复 retry、401真实 retries；只返回≤200 typed representative refs/SQL页，不整读历史JSON；原早期operator仍合法；empty0SQL。
- K1真实reservation原TX/issuer/tamper/reuse/换key/hash不等、外catchcommit零半行；0 items reserved pending，裸create/finalize/claim绕过均拒。
- 真实 P1 FINALIZED+CURRENT + K1 apply + Job.ready 同TX；同caller rollback后无逻辑/ready；旧JobLease/换TX/裸receipt拒；不同合法projection commitChecksum保留。
- 0 logical fail→explicit retry→lease takeover→actual ready succeeded；非零失败项retry而successes/result/checkpoint/attempt字节不变；original frozen actor不覆盖。
- 401/10001 items：acceptance/fullcutover仅线性；每claim/guard仅读一Item snapshot+固定Root/Job/anchor facts；SQL不得再次带manifest/Plan payload，计数/失败更新不取snapshot；额外大JSON sentinel+SQL列检查证明实际没读。
- source与destination配置任一改变，obsolete durable commit ACK；旧代File/Item不写。source guard后继未接时明示未验证，不伪称已安全删源。
- 队列/FGA/index运输可隔离，但 K1/P1/Job/Retry/Mode/Operation的SQL必须actual native；无 fake ready/假Lease。SQLite只报本地native，不冒MySQL/DM实测。

本次没有运行新测试或修改任何项目/Git/远端；仅此候选材料写入 /private/tmp。当前MIG8e3 clean。
