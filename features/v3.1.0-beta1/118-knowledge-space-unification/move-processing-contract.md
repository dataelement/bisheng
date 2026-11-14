# F118 跨空间 move_index 合同：P1/K1 已冻结

只读事实基线：主树 `5ee671da957fddcea1bb449e6251cdbe14d448e9`。PROC 保持
`0100ebf1cb74748594313cdb98bf65a85abf7cf1` clean。本文由 root 复核后冻结P1/K1；§6–8的J1/A1/W1/Q1/KN/F后继仍是依赖候选，尚未授权写入，待分别精确冻结。

## 1. 固定范围与真实缺口

- 已有 `worker/knowledge/move_worker.py::apply_move_index_item` 是真实 ES/Milvus adapter，
  已有双步骤 checkpoint、精确 file replace、全量分页验证、持久 target_verified 后清源；不重写它。
- `ProcessingKind.MOVE_INDEX` 已存在，但 `processing_jobs.py` 没有 move 分支；
  通用 `_actor`、ProcessingJobService 查询及 retry 均硬性要求 space.edit，不能直接套用。
- 旧 `KnowledgeSpaceService.move_items` 仍先 SQL commit，再 project_move、清 tag、派旧
  `migrate_file_vectors`。旧 worker append/no-source-success 路径不能作为 J1 恢复实现。
- 现 Job 的 compact manifest、执行 defer/raiseload 只适用 metadata；move 必须显式加入，
  不能让每 item guard 把全量 manifest 读回来。
- 不增加一般 processing create/precheck kind；不建任务表、模型绑定、staging 或第二套队列。
  同空间 move 不生成索引任务、不重嵌入。普通读取与无关文件操作不泛禁。

## 2. 唯一存储与身份

复用现 `KnowledgeOperationPlan` / `KnowledgeProcessingJob` / Item / RetryReceipt，以及真实
`permission_projection_operation`、`permission_projection_tuple`、`resource_permission_mode`。

跨空间计划：Plan.space_id=源，operation='move'；Plan.operation_id=真实 Job.id；
Job.space_id=目标，kind='move_index'；同 SQL TX consume/create。
接受时沿现 J1 pending_dispatch=True（含合法0-index-item命令）；原 worker 首先完成 F048/逻辑
归属阶段，再处理索引 item。只让真实已组装的 move runner领取，不把“逻辑尚未完成”当索引ready。
领取复用原 JobLease、过期 running 扫描和 pending 标记，不另造接受恢复队列/lease。

precheck/accept 在真实旧归属核选中的 file/folder.move 和目标容器 upload_file，保旧入口资格。
不对历史版本额外加 edit/visible/move，不对已移动资源再次施加目标侧 move。
捕获/恢复唯一原 `capture_processing_actor` / `restore_processing_actor`，保 web/SA/D、
credential、subject、tenant pin、data_scope ceiling；actor_reference 仅是身份来源，不是权限证明。

continuation 的授权来源是同一持久接受操作 + 原 source move 已真实准入 + 完成的 F048 父关系
投影 + 精确 after 归属。每步仍恢复当前凭据及原 narrowing，并 fresh 核目标容器 upload_file。
P1部分断点须区分：原PREPARED且Mode仍before CURRENT时fresh核选中资源move；本job已改Mode但尚未FINALIZED只允许完整owned ledger支撑原operation前向恢复，不能误当completed continuation或进index。已FINALIZED还须实际Mode精确CURRENT after。新typed主体retry无法通过当前move即拒，不能沿旧主体接受事实放宽。精确候选读取与完整阶段规则见[W6§107](./wave6-completion-contract.md#107-p1精确操作者候选读取与原move断点分类已冻结)。

personal narrowing 用现 `permission.application.data_scope` 注册的 ownership resolver 对实际
冻结资源 ID 做 filter_owned；缺 resolver fail closed，不额外发一个 visible/move 动作代替 narrowing。

同主体换合法凭据的 retry 沿同操作 continuation；新主体的人工 retry 先对当前真实的冻结选中
资源核既有 move 动作，再核目标 upload_file，生成现 RetryReceipt。该新授权只授本 job 原失败
集合；worker 消费这个真实 retry 接受事实，不重复移动归属。成功项、版本、权限不重建。

## 3. 数据投影（新 DTO 均 frozen slots；同叶定义，不复制 Worker DTO）

K1 的业务 DTO 归 ScopeRepo；permission 的 expected/fact/evidence 归 P1 的 native Repo，
只由其 application bridge 对外导出/消费。Knowledge Domain 只声明窄 verifier Protocol 并由实际
App 工厂注入，不 import permission ORM/Repo/具体 App 实现；不需第三个纯 DTO/证据生产叶。

`MoveRoot(type:'file'|'folder', id:int)`：请求选中根；父子重选先归一。服务端展开整树/全部历史。

`MoveLeaf`：
```
target: ResourceVersionTarget                 # 真实 file/document/version 三元组
selected_root: MoveRoot                       # 该叶属于哪个已准入选中根
destination_parent_id: int|None
version_no: int
is_primary: bool
original_status: int|None
participates: bool                            # 沿旧实现仅 original SUCCESS=2 索引迁移
before_revision: str
after_revision: str
projection_anchor: MoveParentChange           # 实际变更自身parent或最近已移动根的anchor
```
`MoveParentChange`：resource_type/id、old_parent_type/id、new_parent_type/id、mode、
expected_permission_version。target_version 由原 build_move_plan 得出，不猜 +1。
未变 parent 的子项不虚构 projection；历史文件若 parent 也变，独立列入真实 parent changes。

`MoveScope`：tenant、源/目标真实 Root 的 R/G、index/collection identity 摘要、
accept 前双方 metadata schema revision/digest、source/target folder/path、归一 roots、
全部 logical rows/versions 的有序 scope digest、MoveLeafs、parent_changes、字段保留/清除及 tag 影响。
不保存 bearer、embedding、Chunk 或原模型凭据。必要对象 Key/WEB_LINK 身份只沿既有字段
核验或持久 digest，不把 URL/对象原始值输出到公开 impact/日志。

`MoveReservation`（私有 native-TX receipt）：tenant、server生成的job UUID、plan id/digest/request_hash、
actor_reference digest、source/target IDs、完整 move_scope_digest、index item集合与TX identity。
只用于同TX创建真实 reserved Job，不能带过commit当授权。
`MoveOperationLocator(job_id,source_space_id,destination_space_id,state)` 仅是commit后的定位结果，
不是proof；后续步骤按job_id重读真实Plan/Job/ledger。
`PreparedMoveCutover`（CutoverRepo 私有同 TX 原对象）：job/plan/lease generation、完整 scope、
确认的 before/after revisions、changes_digest、current source/target R/G 与 TX identity；
只由 aprepare_cutover 从真实持久 Job/Plan 重建，不能直接使用跨 commit 的 reservation。
`MoveLogicalReceipt`（私有 native-TX receipt）：tenant、job/plan IDs、job request_hash、actual after
scope digest、真实 projection evidence digest、index item数、当前JobLease generation及TX identity。
只 JobRepo 同TX一次消费。两种receipt均用原对象registry+TransactionIdentity验证，不接裸dict/重放。

after_revision 只覆盖移动后稳定归属/路径、File 身份/源对象/名称/元数据、Doc 主版本及版本关系；
不含本任务自己推进的 File.status、item step/attempt/lease 或 update_time。
受控 status 4→3→2 不会使自己 obsolete；安全拒绝 7 不得被写成成功。
非参与文件也一起迁移逻辑链，保原失败/安全状态，不造索引 item。

Row/scope 摘要复用现 `operation_plan_repository._digest` 内部 JSON SSOT；Plan request/plan hash
仍只由 OperationPlanRepository 算。FGA checksum 只用原 build_move_plan / normalize /
projection_request_checksum / restore_projection_plan。不在新叶复制 canonical/hash 算法。
Worker 的 MoveMetadataPolicy / MoveIndexCheckpoint / MoveIndexResult 沿现 class，不搬迁/镜像。

## 4. Native 业务仓储与接受接口

Scope 的 logical rows 含目录与全部历史文件；目录没有伪 ResourceVersionTarget。每行明确保
file_id/file_type、before/after knowledge_id、file_level_path/level、真实 parent、必要身份 revision、
before/after user_metadata 与原 status；Doc 行保 id/knowledge_id/file_level_path/level/primary_version_id，
Version 行保 id/document_id/
knowledge_file_id/version_no/is_primary。Blob 指针只核保留、不改写；TagLink 用真实 link PK 闭集
删除。路径以现 file_level_path/level 实际编码转换，不引入不存在的 File.parent_id 列。

新 `knowledge/domain/repositories/move_scope_repository.py`（DTO 同叶）与
新 `knowledge/domain/repositories/move_cutover_repository.py`（私有 receipt 同叶）：
```
aload_scope(session, *, source_space_id, destination_space_id, roots,
            destination_folder_id, for_update=False) -> MoveScope
aprepare_reservation(session, *, scope, confirmation_id, plan_digest,
                     actor_user_id, actor_reference) -> MoveReservation
aprepare_cutover(session, *, job_id, lease:JobLease) -> PreparedMoveCutover
aapply_logical(session, *, prepared:PreparedMoveCutover, projection_evidence) -> MoveLogicalReceipt
aassert_no_unsettled_move_inputs(session, space_id) -> None
assert_no_unsettled_move_inputs(session, space_id) -> None     # 原sync model/removal caller
```
aload_scope/input guard 属 ScopeRepo；reservation/prepare_cutover/apply 属 CutoverRepo。sync/async guard 共用
同一个 SELECT builder/validator，不复制 SQL。方法只 native SQL/flush，不开 Session、不 commit、不做 FGA/Blob/queue。
MoveReservation/MoveLogicalReceipt 为原对象、原 SessionTransaction 的私有签发 receipt；
verify/consume 比较完整 scope、job/plan、actual before 或已提交 after facts，深层数据不可借修改绕核。

完整性：物理 File 集合与 Doc/Version 链闭集分别核；不能 inner join 掉缺失；拒坏 tenant、
重复 file→version、目录被版本引用、缺 Doc/primary、跨空间链。每文档一次 primary 索引，
每 SQL ID 批≤200，避免独立 IN 乘积与每版本重扫整链。固定锁序为两个 Root 按 ID 升序，
再 Plan→Job→Item/RetryReceipt，再 File→Doc→Version→TagLink，各表主键升序；projection native
事实读放在同 TX 持有 Root/Plan/Job 锁之后，Mode/operation 如需锁也统一固定主键序。
无锁 scalar 读取仅用于确定上述锁键，取得锁后重读/验证；不先拿 Job 锁再反向拿 Root。
只读 scope/input guard 全程 no_autoflush，精确拒关键 pending、不覆盖无关 pending。变更入口
若需 begin_nested，进入前先拒会被隐式 flush 的 caller pending，原 pending 原样保留；生产 Owner
使用自有 clean 短 TX。局部 SAVEPOINT 失败不留下半链，caller 唯一 durable commit/rollback。

`aapply_logical` 只由实际 MoveOwner 在同 TX 先取到真实 F048 durable evidence 后调用；
它不接收 HTTP 传入的 ready/bool/projection JSON。它原子迁移目录及全部历史的 File/Doc 路径与归属、
清源空间文件 tag、按已确认同名同类型策略改 File 自定义 metadata，保 WEB_LINK 系统键、对象键、
版本 IDs/关系和 CUSTOM grants。参与项 status=REBUILDING；不改模型/R/G、处理默认或创建版本。
整笔 apply 后重读 actual after rows，签发同 TX receipt。同一 consumed Plan/Job 的实际行已全部在确认 after 则幂等返回，
不再次移动/删 tag/推进版本。

新 `knowledge/application/move_processing_owner.py`：
```
aprecheck(session, source_space_id, request:FileMoveReq, *, identity, entry_kind) -> OperationPrecheck
areserve(session, source_space_id, request:ProcessingCreateRequest, *, identity, entry_kind) -> JobAccepted
aproject_or_resume(*, job_id, lease:JobLease, identity) -> MoveProjectionProgress
afinalize_logical(session, *, job_id, lease:JobLease, identity) -> MoveOperationLocator
aensure_logical(job_id, lease:JobLease, *, identity) -> MoveOperationLocator
aauthorize_continuation(session, *, job_id, identity, item_id=None) -> MoveAdmission
aretry_failed(session, *, job_id, request:ProcessingRetryRequest, identity, entry_kind) -> JobAccepted
```
App 只编排，不写 SQL。另提供实际API协调入口
`aaccept(source_space_id,request,*,identity,entry_kind)->JobAccepted`，自有短session调用areserve并commit
ACK后返回；不在HTTP长连接中先跑全部FGA。precheck 只写确认计划、取消零业务/J1/投影写。
areserve内部消费Native MoveReservation创建同UUID真实Job后只返回JobAccepted，不把旧TX receipt跨commit传递。
afinalize_logical内部先验证same-TX permission evidence、调用CutoverRepo签发actual MoveLogicalReceipt，
再由JobRepo消费mark_ready，只返回定位DTO；恢复一律重新读持久事实，不重用旧TX对象。
areserve：重新真实授权、锁后比完整 source/target scope /影响 digest，与 Plan 消费及真实 reserved
Job 同 TX。同 key 相同完整请求复用，异请求/actor/plan conflict；已存在仍重新鉴权。
areserve 必须先 aget_by_request_key：既存操作按其真实 Plan/完整 request hash 与原 scope 核对，
按 continuation 重新鉴权，不从当前已移动后的源位置重新生成“原before”或再做一次移动。
换 actor_reference 不静默覆盖原接受身份，走明确新授权 retry；同 consumed Plan 不能用新 key 建第二 Job。
API/worker 不得手造 reservation/accept receipt，不接收任意 MoveLeafs 作为已接受事实。

实际顺序：短 TX reserve+consume+真实Job accepted/pending → commit ACK → 原 scanner/队列 →
move worker恢复原身份并claim原JobLease → 全部 parent projection（无业务 TX）→ fresh TX 取 durable
evidence + 比 before/after + apply logical + mark_move_ready（核同JobLease）→ commit ACK → 同runner索引。
每个projection前只重验双Root/JobLease和该parent change，不每次重载全manifest；全scope在claim/逻辑
cutover各线性核一遍。FGA/SQL 任一 unknown 停止，不宣布 logical 完成；同 Job/Plan 前向恢复。
原 adispatch_candidates 已覆盖accepted pending及running lease过期；无需第二恢复调度。
FGA 部分 FINALIZED 而 SQL 未变时，仍用真实 ledger 重建/恢复原 operation，不重新生成旧 target。

0 个索引参与项（例如空目录或全是原失败文件）仍可合法移动。reserved move 允许 0 index items
仅凭私有真实 reservation（logical rows 必须非空），不造 dummy file/item。逻辑/FGA 完成后凭实际
MoveLogicalReceipt 推进真实 0-item succeeded 审计、pending_dispatch=False；此前是accepted pending，
也由原worker执行真实FGA/逻辑阶段，不因items为空在create时假成功。其余 kind 非空限制不变。
同空间分支保同步 metadata 移动、无索引/J1；复用父关系 before-project-after 顺序，但不在本 T074
组件前缀声称旧同空间入口已经改好。

## 5. 真实 F048 move proof（必要前置，不复用假的 ProjectionOutcome）

P1 只有两个生产叶：`permission/domain/repositories/move_projection_repository.py` 与
`permission/application/knowledge_move_projection.py`。native Repo 同叶定义闭集 expectation/fact、
opaque evidence、私有原对象 registry 与 TransactionIdentity verifier；实际 App bridge 是业务模块
唯一入口。Knowledge CutoverRepo 的构造器只接 `MoveProjectionEvidenceVerifier` Protocol：
`assert_current(evidence, session, *, job_id, expected_changes, changes_digest) -> None`，实际工厂注入该 bridge 的
原 verifier，不接 ready/bool/任意 digest。evidence 必须是实际 native Repo 从真实 SQL 签发的
原对象，并绑定 issuer、当前 Session/原 TX、job/changes；不需跨模块 Domain import。
registry 只活本 TX，进程/事务恢复必须重新读 ledger 签发，不把 registry 当持久业务状态。

新 `permission/application/knowledge_move_projection.py`，只接 business Owner 已核实的
`VerifiedPermissionTarget` before/after、mode 和稳定 operation key；不导入知识 ORM/DAO/Repo。
`MoveProjectionExpectation`：job_id、tenant_id、resource_type/id、真实 before/after targets、mode、
expected_permission_version、changes_digest、allowed_operator_ids（≤200，来自真实本 Job/RetryReceipt
批事实）；key 在桥内按固定公式生成。`MoveProjectionProgress(total_count,finalized_count,complete)`
不含全量 tuple/outcome；count 只认本 job 实际 changes，各页 ≤200。
```
aexecute_or_resume(*, job_id, changes, actor) -> MoveProjectionProgress
arequire_finalized(session, *, job_id, expectations) -> MoveProjectionEvidence
assert_current(evidence, session, *, job_id, expected_changes, changes_digest) -> None
```
新 `permission/domain/repositories/move_projection_repository.py`（闭集 native facts 同叶）：
```
alist_owned_operations(session, *, expectations:tuple<=200, lock=False) -> tuple[MoveProjectionFact,...]
arequire_finalized(session, *, job_id, expectations:Sequence, changes_digest) -> MoveProjectionEvidence
```
`MoveProjectionFact` 只包含 operation id/tenant/key/type/scope、operator、expected/target_version、
store/model pin、request/before/after/commit checksum、operation status，以及实际 Mode 的
mode/parent/version/projection_state/operation_id；tuple_rows 只为当前有界 expectations 读取并用
原 restore_projection_plan 核验，不缓存全任务 tuple。Repo 不开 Session、不做 FGA、不 commit。
arequire_finalized 的 Sequence 是完整 parent-change 闭集，内部 SQL 每批≤200；它遍历全部
expectations 后才能签一份完成证据，不把一页当全任务。证据保闭集 count/不可变覆盖 keys+预期
parent/mode/version，与 CutoverRepo 私有 prepared.expected_changes 逐项精确相等；单凭外传全量
changes_digest 而漏页/少期望不能通过。只保 O(changes) 轻覆盖，不保全 tuple/config/JSON。
整个 logical cutover 只核这一遍；后续逐 item guard 只核自身真实 anchor。
operation key=`knowledge-move:<真实job UUID>:<resource_type>:<resource_id>`，≤192。
首次调用原 `F048PermissionRuntime.project_parent_change(...,idempotency_key=key)`；
恢复用真实 F048RuntimeComponents.projection 的 reconcile_operation(id)，必要时沿现
inspect_failed_closed_recovery/recover_failed_closed_operation 的原确认摘要，严格只恢复本 key/checksum
绑定的原 AFTER，不开放任意 operation ID 管理口。缺 runtime/marker/composition 立即失败。
首次 operation 的 operator 用当时实际 actor；已存在 operation 必须保原 operator/checksum 恢复，
不能用 retry actor 重建旧 plan。allowed_operator_ids 由 Owner 通过真实 J1/RetryReceipt scalar
批事实提供；只核本页实际 operator candidates，不拉所有 retry 历史。permission 模块不查知识表。

native proof 读取并逐一验证真实 operation：tenant、idempotency_key、RESOURCE_MOVE、resource scope_key、
operator（必须属于本Job原actor或真实RetryReceipt接受的actor）、expected/target_version、store_id/model_id、
request/before/after checksum、FINALIZED；commit_checksum只认原ProjectionService合法记录的64hex证据，
允许正常transport ACK与原reconcile/recovery记录，不错误要求commit_checksum==after_checksum；
tuple rows 从原 restore_projection_plan 还原并核请求/状态摘要。实际 ResourcePermissionMode 必须
CURRENT、operation_id 相同、version=target_version、parent=确认后 parent、mode 原样。
PREPARED/STAGING/COMMIT_UNKNOWN/COMMITTED/FAILED_CLOSED 均不是 durable ready。
`MoveProjectionEvidence` 是 native Repo 经本 bridge 私有签发、同 native Session/TX、job + changes_digest 绑定的原对象；
伪 dataclass/dict/换 TX/错 operation 不认。不把返回 status='FINALIZED' 的 mock 当 SQL 事实。
MoveOwner 在持有同 TX Root/Job 锁时 require+verify evidence，然后 native apply/ready；无业务 TX 跨 FGA。
Knowledge Domain 仅依上述窄 verifier Protocol，实际 MoveOwner 通过 permission application 组合：
先 actual permission Repo→bridge 私有 verify，再 same-TX CutoverRepo actual apply→私有 logical receipt→JobRepo ready。
MoveCutoverRepo同TX用实际issuer的verifier核证再apply并签logical receipt；JobRepo只消费此receipt。
Native SQL repo不是一般权限授予者；不提供“ready=True”或“裸actor_ref即可accept”的组合入口。
默认生产工厂必须注入实际 bridge/Repo；缺 port 在任何 reserve/dispatch 前失败。

### P1/K1 current parent 与 Catalog SQL 接缝：已冻结

P1 既登记两叶增加 `aread_parent_states(session, *, targets:tuple[(resource_type,str_id),...]≤200)`，
由 native Repo 返回 `MoveParentState(type,id,mode,version,parent_type,parent_id,projection_state,operation_id)`，
bridge 供 K1 的窄 `ParentStateReadPort` 注入；不让 Knowledge Domain 直接读 Permission ORM。
缺失或非 CURRENT 沿原 control_state.mode_for_target 的 NotReady，不猜 INHERIT/0。
这只是观察事实，source move / destination upload_file 仍由真实 Owner 准入。
projection evidence 的 store/model pin 在同 native TX 读 CURRENT Catalog SQL 权威，Owner不带hint；
不开另 Session/FGA，复用原 release/schema/hash SSOT，需要额外最小提取先交root登记。

## 6. J1 bounded move 接缝

`MoveConfiguration(source_space_id,destination_space_id,source_model_config_revision,
source_index_generation,destination_model_config_revision,destination_index_generation,
source_index_digest,destination_index_digest)`：全部是当前真实 Root scalar，无 caller model hint。
`MoveExecutionSnapshot`：tenant/job/item id、当前 MoveLeaf、原 Worker checkpoint、真实 after
file/document/version/parent facts、上述 configuration、已校验的原 source/destination Knowledge
模型读取结果；只有一个 item，无全 manifest/Plan parameters。原 Runtime 继续核真实模型归属/
可用性，不能把 Job 当模型绑定；有索引参与项的接受阶段也核两端真实模型准入。
`MoveAdmission`：真实恢复的 FrozenProcessingActor/当前 identity、MoveOperationLocator、当前
具体目标容器及 narrowing 已校验的选中根 ID；仅本调用授权结果，不是可跨 TX 的 durable proof。

新 `knowledge/domain/repositories/move_execution_repository.py`：
```
aread_configuration(session, *, job_id) -> MoveConfiguration   # 双真实 Root 的 R/G/index identity
aread_item(session, *, job_id, item_id) -> MoveExecutionSnapshot
aguard_item(session, lease:ItemLease, *, jobs) -> MoveExecutionSnapshot|None
acomplete_item(session, lease, *, jobs, outcome:MoveIndexResult事实投影) -> bool
```
Domain 不导入 Worker MoveIndexResult class；完成口接闭集 count/digest scalars，由 worker 拆现结果。
Snapshot 只当前 item 的 MoveLeaf/checkpoint、实际 after 三元组/parent/版本及双真实 Root；
不每次扫整空间/读取 Plan.target_manifest 或 Job.scope_manifest。
共同 proof：Plan consumed→此 Job、kind move、同 tenant、accepted manifest digest、真实已 logical-ready
receipt、真实 F048 anchor evidence、after File/Doc/Version 链与 current lease；双 R/G/index identity漂移
持久 obsolete，必须 commit 后停；旧代 worker 不能写 File/item，失败/安全状态不能复活。

原 `processing_job_repository.py` 仅 move-kind 增量：
```
acreate_move_reserved(session, *, reservation, idempotency_key, actor_user_id,
                      actor_reference, parameters, items) -> JobRequestResult
amark_move_ready(session, *, logical_receipt, lease:JobLease) -> JobAccepted
aactor_membership(session, *, job_id, actor_user_ids:tuple<=200) -> frozenset[int]
```
aactor_membership 只对实际 original actor/本 job RetryReceipt 接受 actor 做有界 scalar 查，
是业务事实而非授权；Owner 还必须核完整 subject/credential/ceiling。
amark_move_ready 同 TX 核原 lease，将 job/plan/request hash、after revision 与 projection evidence
digest 的紧凑 logical_move marker 写到各真实 Item.checkpoint；不改 parameters/request_hash，
非零 items 保 pending，零 items 仅凭实际逻辑完成 receipt 转 succeeded。
上述 receipt 只 native MoveRepo 发行，绑定原 TX/完整 request/actor/scope，JobRepo 一次消费；
同 key 相同既存 job 可复用，不重复消费，别的 key/其他 TX 拒绝。
普通 acreate 行为不放宽。move request_hash 仍覆盖完整实际 leaf snapshot；scope_manifest 只保
三元组/expected destination/parent/snapshot digest，完整 snapshot 只在 Item。
aget_execution、guard/claim/renew/complete/retry/afail/finalize 的 move 路径全部 defer/raiseload
manifest；afail 的批量 item 更新也不读全 snapshot；public get/list 保完整 compact target IDs。
双 Root 锁/CAS 集成在 move 路径，配置必须读取真实 SQL，不信任 caller 传来的历史 R/G。
失败仅失败项 retry，成功 item/result/checkpoint/attempt 不动；原 lease takeover 规则复用。

## 7. 实际 worker / 查询接线

新 `worker/knowledge/move_jobs.py`：
```
execute_move_job(job_id, expected_dispatch_revision, *, owner, proof) -> {job_id,state}
```
原 processing_jobs.py 在 edit-only `_actor` 之前按 kind 分支。只用实际 EXECUTE_TASK background proof，
原 scanner/headers→ContextVar，不新增 Celery 队列/公平调度器。
reserved/unready job 只能先claim原JobLease并运行实际Owner.aensure_logical；未有durable after proof不得
claim index item/调用索引adapter。缺真实Owner/projection composition，入口 fail closed，不能伪ready。
短 TX claim/renew/精确 guard → commit release → apply_move_index_item → fresh guard/同 TX File+item完成。
端口 aload/asave 每次 fresh scope/lease/原身份；asave 只有 SQL commit 明确 ACK 后才返回 None。
checkpoint 带现两个 step，不存 chunks/向量；commit unknown 不清源、不盲重试。
成功要求 durable move_source_cleaned，真实 target counts/digests；File status2 与 item succeeded 原子。
actor 失效只受控 afail/停派发，无新代 File 写；source/target R/G变更只 obsolete，不造成功。

源存在性保护直到每个 item 的 succeeded SQL ACK；source_cleaned checkpoint 不能提前释放。
全部 item 真 succeeded 后，Job 计数聚合可用原目标侧 finalize，不再重新执行已成功 item/源 IO。
0-item 操作须 logical completed/succeeded 后才释放。failed/obsolete 未完成项始终挡删源/破坏性 reset。
同一个sync/async source-input guard 用 Plan.space_id/source+operation_id=Job.id+Item.job_id/tenant
实际关系查询，不扫 JSON、不仅筛 active jobs；由源删除、源模型替换/全库 index reset 消费。

新 MoveProcessingAccess 应用门面 / API DI 增 move-only owner 分流：用自己短read Session预读kind/tenant后关闭，
再实际authorize，最后fresh Session读结果；不在caller事务里做FGA或commit/rollback caller。非move委托原Domain
ProcessingJobService，四kind方法完全不变。已存在move job走实际Owner，
不先统一 edit。保 get/items 的 visible 裁剪及 hidden count，retry 原 DTO，普通四 kind 原准入完全保留。
非 editor 的列表只扫描 move 候选轻行（原 actor_user_id coarse SQL 过滤、PK seek≤200），对真实
subject/ceiling/当前 upload 做筛选后才切 PageData，total 流式累计；SA/D 不把同 audit user 当同主体。
该分支成本 O(候选页)，不谎称 JSON 主体可用 SQL COUNT 精确筛；内存仅目标页，不拉全 manifest。
普通 editor 列表保持既有 SQL 分页。缺 MoveOwner DI 不接受/派发 move。

移动专用 HTTP 由 KN 原路由接线：新增 `/{space_id}/files/move/precheck` 接原 FileMoveReq；
原 `/files/move` 接同空间 FileMoveReq 或跨空间 ProcessingCreateRequest。旧跨空间裸请求拒确认缺失，
不能直接派旧 Celery。确认仅 confirmation_id/plan_digest/idempotency_key，不再相信第二份目标/参数。
同空间仍返回原 moved/invalid；跨空间确认返回现JobAccepted（不在逻辑尚未生效时伪报moved）。
accepted既不冒逻辑已完成也不冒索引完成；前端确认/取消和job_id进度跟踪按AC18同步接入。

## 8. 最小生产叶与依赖（每个实现卡≤2叶；各有单独先红测试卡）

|组|生产叶|真实交付与依赖|
|---|---|---|
|P1|permission/domain/repositories/move_projection_repository.py；permission/application/knowledge_move_projection.py|闭集事实/私有证据与实际F048首次project_parent_change/按ledger恢复；依现F048；两叶，不另加证据模块|
|K1|knowledge/domain/repositories/move_scope_repository.py；knowledge/domain/repositories/move_cutover_repository.py|DTO、完整闭集/metadata/tag/path计划与私有reservation/logical receipt；窄verifier签名先冻结，可与P1并行；真实apply最终用P1 native evidence组合验收，不先开放accept|
|J1|knowledge/domain/repositories/processing_job_repository.py；knowledge/domain/repositories/move_execution_repository.py|真实 reserved/ready、0-item narrow receipt、compact、双RG/after guard；依 K1/P1 接缝|
|A1|knowledge/application/move_processing_owner.py|组合真实 P1/K1/J1、原Actor与C4，真正accept/forward recovery；缺任何composition拒绝|
|W1|worker/knowledge/move_jobs.py；worker/knowledge/processing_jobs.py|现 adapter实际消费、租约/checkpoint commit/失败重试；依 A1/J1，未装配不开放kind|
|Q1|knowledge/application/move_processing_access.py；knowledge/api/dependencies.py|move-only query/retry门面+真实DI；依A1，普通Domain service四kind不改；不扩大通用create/precheck|
|KN1|knowledge/domain/services/knowledge_space_service.py；knowledge/domain/schemas/knowledge_space_schema.py|原move入口调用实际Owner，保普通同空间无index/noJ1；依A1/W1|
|KN2|knowledge/api/endpoints/knowledge_space.py；knowledge/api/dependencies.py|真实HTTP两阶段+服务装配，取消零写，退休旧跨空间派发；依KN1/Q1|
|F1|knowledge/application/model_reference.py；worker/knowledge/rebuild_knowledge_worker.py|同一source-input guard插实际sync/async prepare_removal、prepare_model_change/prepare_rebuild及worker reset；依K1/J1|
|F2|knowledge/domain/repositories/move_object_reference_repository.py；knowledge/domain/services/knowledge_service.py|实际整空间对象cleanup manifest减去target仍持有的精确共享key，再由原MinIO helper执行；依K1，source顺序fence依F1|

实际整空间链：KnowledgeSpaceService.clear_space/delete_space →
KnowledgeModelReferenceApplication.aprepare_removal → 原 KnowledgeService.delete_knowledge_file_in_vector/
delete_knowledge_file_in_minio → aapply_removal。同步旧入口同走 prepare_removal。
因此F1必须在 removal/model-change 的持锁Root受控口、任何FGA/向量/对象purge前检查；
不能仅改 knowledge_space_delete_repository（它当前是文件/目录 DirectDelete，并非整空间入口）。
对象manifest复用仍属源 File 收集 id/object_name/preview/bbox/thumbnails 的真实清单；移动稳定 file ID键不复制。
copy遗留跨file共享preview/thumbnail等结构化 key 必须减去目标仍持有的精确字段引用，不能按 source space prefix 清删。
原helper确实只读当前 knowledge_id 的 File，以key调用remove_object_sync，未按space前缀递归删除；不据注释复制所有对象。
任意手工跨file链接/原业务配置引用维持已确认manual-repair impact，不为此新增禁止移动或自动改配置。
对象共享保护与整空间删除验收未接前，T073/T074/相关源删除整卡不得标完成。

首冻仅 P1/K1（各两生产叶）；其余行是后继精确依赖候选，未授权实现。P1/K1 完成也不等于 T074。
P1 测试先真实 ledger/Mode/原 projection service，K1 先 native 全链读/变更/回滚；组合时必须用
P1 实际 issuer/verifier 验 K1 apply，不以 stub verifier/裸 ready 作为最终绿证据。
失败闭集沿既有确认失效/版本冲突/幂等冲突/身份拒绝/任务 obsolete；不新造笼统成功或错误回空。
所有新叶≤600。测试叶分组建议：test_move_projection.py / test_move_projection_repository.py；
test_move_processing_repository.py；test_move_job_repository.py / test_move_execution_repository.py；
test_move_processing_owner.py；test_move_job_worker.py + 原test_move_worker.py；
test_move_job_access.py；原move HTTP/space service测试与source deletion/guard测试（原叶登记后适配）。

必须的真实组合：native Source/Target/Doc/全历史→真实 Owner→实际 F048 SQL ledger + 原 projection service
（仅FGA/ES/Milvus运输隔离）→同TX逻辑切换/J1→现Celery入口→checkpoint故障/接管→File+item原子完成。
包含 move-only无edit、SA/D/personal narrowing、target-only-move不新增、0参与/空folder、401/10001版本/Chunk、
互相交错 tenant/parent/version坏链、before/after/ABA RG、partial failure同job retry、FGA已完成但SQL失败的恢复、
checkpoint unknown不清源、旧lease不finalize、source_cleaned未succeeded仍挡删源、最后source删除不损目标对象。
每批实际 SQL/返回列/JSON字节和分页实测，不以mock service或SQL条数掩盖N²。

本合同只授权P1/K1登记叶实施；不声称任何移动入口/worker后继已完成。
