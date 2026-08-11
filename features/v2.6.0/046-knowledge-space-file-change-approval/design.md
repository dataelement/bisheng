# Design: 知识空间文件与文件夹变更审核

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 回答做什么、验收标准和范围边界。
> - 本文回答为什么采用当前实现、运行时数据流、契约和已知风险。
> - [tasks.md](./tasks.md) 在设计确认后生成，记录实施顺序和实际偏差。

**Feature ID**: F046
**关联**: [spec.md](./spec.md) · `tasks.md`（待创建）
**版本**: v2.6.0
**最后更新**: 2026-08-10

---

## 1. 目标与非目标

### 1.1 目标

- 在不把未审批上传写入正式知识空间文件表的前提下，为上传建立独立暂存和审批链路。
- 对正式文件和文件夹的重命名、移动、删除增加审批网关；审批通过前保持当前正式状态不变，通过后复用现有权威业务链路执行。
- 文件夹申请覆盖整个子树；通过统一互斥检查阻止同资源、祖先文件夹和子树中的并行变更审批。
- 文件列表和审批中心展示同一审批实例；详情明确动作及待生效变更。
- 每个租户独立保存审核策略；私密知识空间免审，部门知识空间禁止变为私密。

### 1.2 非目标

- 不扩展已废弃的 `approval_request` 部门空间文件上传审批系统。
- 不给频道内容增加上传、重命名、移动或删除审核。
- 不替换解析、版本、F034 移动、删除、OpenFGA 或检索链路；为审批重试增加的幂等检查、发布门禁和补偿编排属于本期范围。
- 不把业务暂存表作为审批状态事实源；审批状态仍只认 F025 的 `approval_instance` / `approval_task`。
- 不为私密知识空间保留“可强制开启审核”的例外开关。

---

## 2. 关键约束

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C7 与 [release-contract.md](../release-contract.md)，本功能新增对象和跨 Feature 写行为以 release contract 的 F046/INV-8 登记为准。
- 审批统一走 F025 `ApprovalGate → ApprovalInstance/Task → ApprovalOutbox → Celery → handler.on_approved()`；审批通过不代表业务执行成功。
- 审批回调必须重新校验当前权限、资源状态、目标位置和结构约束；失败必须抛异常，使实例进入 `execute_failed`，不能返回假成功。上传解析是业务注册完成后的独立异步阶段，其状态从正式文件解析状态派生，不把 `ApprovalInstance.executed` 伪装为“解析完成”。
- `KnowledgeFile` 同时表示正式文件和文件夹。未审批上传不得提前创建 `KnowledgeFile`、`KnowledgeDocument`、版本、FGA child tuple 或解析任务。
- 审批通过后 `add_file()` 会先创建 WAITING 正式行再异步解析；F046 必须在所有正式读路径增加未发布门禁，只有解析成功才解除，申请人/当前审核人通过独立变更列表查看“解析中/解析失败”。
- F034 跨空间移动会迁移版本链、检索数据、标签和 parent tuple；本功能只能在审批通过后调用该权威执行路径，不复制移动实现。
- 文件夹变更覆盖子树。冲突判断必须同时检查“当前资源的祖先存在审批”和“待操作文件夹子树存在审批”，并发下不能只靠应用层先查后写。
- 租户策略不得继承根租户配置。现有 `WORKSTATION_KNOWLEDGE_SPACE` 配置具有 root-share fallback，不适合本功能。
- `/api/v1/knowledge/upload/{space_id}` 当前返回短期分享 URL，原文件名只在 Redis 短期保存，不能作为长审批业务标识；F046 使用服务端持久化的 opaque `upload_id` 引用 MinIO 对象、文件名、大小和 hash。
- 文件列表沿用 F027 cursor 契约；审批状态补充必须批量查询，禁止逐行查询审批实例或形成 N+1。
- 默认策略是开启审核，因此固定审批场景必须在默认租户初始化、新租户创建、策略保存和首次需审 mutation 四个入口幂等确保存在；不能要求管理员先保存配置。

---

## 3. 方案对比与选定

### 决策 1：独立变更申请表，不给正式文件表增加审批状态

- **备选**：
  - A. 给 `KnowledgeFile` 增加审批状态、动作和审批实例字段。
  - B. 只使用 `approval_instance.payload_snapshot`，列表实时扫描审批表。
  - C. 新增知识空间变更申请业务表，正式文件表保持原语义；审批状态通过关联实例读取。
- **选定**：C。
- **原因**：A 会让未审批上传必须提前创建正式文件，并迫使检索、列表、版本和 FGA 链路识别新状态，违背“尽量不改主流程”。B 无法可靠保存上传临时对象和批量查询资源锁，也难以表达文件夹子树占用。C 让业务表只承载暂存、动作快照、资源关联和查询索引，审批状态仍来自 F025。
- **何时重新考虑**：未来正式文件模型原生支持 draft/published 双态，且所有检索入口统一基于发布态过滤时，可合并暂存模型。

### 决策 2：租户总控和单空间配置使用专属关系表

- **备选**：
  - A. 扩展 `WORKSTATION_KNOWLEDGE_SPACE` JSON 配置。
  - B. 在 `Knowledge` 增加单空间布尔字段，并另建租户总控表。
  - C. 新建租户策略表和单空间设置表。
- **选定**：C。
- **原因**：A 具有根租户继承语义，违反“不同租户保存不同配置”，且 JSON 内的空间列表无法建立约束。B 会改动正式知识空间主表，并让总控关闭后恢复单空间配置的语义分散。C 可用 `(tenant_id)` 和 `(tenant_id, space_id)` 唯一约束清楚表达归属，不触碰 `Knowledge` 主表。
- **何时重新考虑**：若平台形成统一、无继承且带强类型 schema 的租户策略中心，可迁入该中心。

### 决策 3：上传先暂存，审批通过后才调用现有正式上传链路

- **备选**：
  - A. 先调用 `add_file()` 创建 WAITING 文件，审批通过后再派发解析。
  - B. 保留上传返回的临时对象路径，审批通过后调用现有正式注册和解析流程。
- **选定**：B，并将现有短期 `file_path` 升级为服务端持久化的 opaque `upload_id`。上传接口创建 `KnowledgeSpaceUploadStage`，客户端后续只提交 `upload_id`；object name 永不出现在业务 API。
- **原因**：A 会提前创建正式文件、版本和权限 tuple，要求所有列表与检索路径识别草稿。现有 `file_path` 是会过期的分享 URL，原文件名依赖短期 Redis，不能支撑长审批。持久化 stage 可稳定预览、清理、重试和按内容 hash 判断“同内容重试/内容变化重提”。
- **幂等**：`(tenant_id, upload_id)` 唯一；同一 stage 只能关联一个未结束 upload change request。客户端注册超时重试返回原 `change_request_id/approval_instance_id`，不得重复建审批；重新上传形成新 `upload_id`，服务端 hash 变化时按新申请处理。
- **代价**：审批等待期间的用户/租户容量预占不能靠正式文件统计完成，需要在变更申请表记录文件大小并纳入配额校验；执行时仍要再次校验实际配额。
- **何时重新考虑**：上传基础设施改为统一 multipart upload/session 模型时，可让暂存申请引用 upload session。

### 决策 4：现有 mutation 入口薄包装，直接执行体保持单一

- **备选**：
  - A. 在 endpoint 复制权限与策略判断，再决定调审批或原 Service。
  - B. 在 `KnowledgeSpaceService` 的公开 mutation 方法前接入 `KnowledgeSpaceFileChangeService`，把当前直接执行体提取为内部权威 executor。
- **选定**：B。
- **原因**：endpoint 只应做 DTO/response；复制逻辑会让单条、批量、文件夹上传和审批回调产生多套规则。公开入口统一执行“权限校验 → 策略判断 → 直接执行或创建审批”，审批 handler 只调用受控 executor；原重命名、移动、删除主体不重写。
- **防绕过**：executor 不暴露为 HTTP/公共 application API，只由编排服务和审批 handler 注入调用；所有 executor 在真正执行前仍重新校验申请人身份下的业务权限。
- **重试边界**：现有 rename/move/delete 都包含“DB 变更 + FGA/MinIO/ES/Milvus/Celery”等多阶段副作用，并非天然原子。F046 以 `change_request_id` 为 saga id，每个副作用先原子写 `KnowledgeSpaceFileChangeExecutionStep(request_id, step_code, idempotency_key, state=pending)`，提交后才派发；worker 以稳定 idempotency key 执行并 ack，coordinator 通过权威状态读后校验再置 step succeeded。副作用已成功但 ack 丢失时，重试必须能观察或幂等重放，不能靠“副作用后写 JSON checkpoint”跨越 crash gap。
- **异步完成协议**：executor 返回 `Completed` 或 `Deferred(execution_token, deadline)`；F025 收到 Deferred 后把 outbox 持久化为专用 `deferred` 状态，保存 token/deadline/heartbeat_at，并保持 `ApprovalInstance=executing`。普通 `claim_outbox()` 永远排除 deferred，不能因 processing claim TTL 重领 handler；仅 coordinator 可心跳续租、完成或失败，watchdog 在 deadline/心跳超时后持实例锁调用 fail。下游任务以稳定 step idempotency key 执行并携带当前 token 回调。
- **执行代次**：同一代补投复用 token 和稳定 idempotency key；失败/超时后的人工或自动 resume 必须生成新 token。F025 `resume_deferred_execution()` 在一个 session-bound UoW 内锁 instance/outbox，调用 handler `prepare_resume(session,new_token)` 更新 request 与未完成 steps，再原子把 `execute_failed/failed` 恢复为 `executing/deferred`；提交后才补投。旧代 ack 因 token 不匹配忽略，同代重复 ack 幂等。
- **动作完成判据**：rename 必须完成 DB 名称与 chunk/index 元数据重建并读后校验；move 必须完成版本链 DB 位置、parent tuple、标签与跨空间索引/存储迁移并校验源/目标；upload 必须完成正式行/版本/FGA、解析、全文索引和向量入库且 `KnowledgeFile.status=SUCCESS`。delete 则采用“非破坏性 prepare → 原子可见性 cutover → 权威 purge 验证 → 原子终态”：prepare 只校验并持久化完整资源/版本/FGA/对象/索引清单，不删除任何可见数据；cutover 在同一 DB UoW 内删除正式 DB 行并激活 request/footprint deletion guard，但 request 保持 `APPLYING`、F025/outbox 保持 `EXECUTING/DEFERRED`；随后 durable steps 清理 FGA/MinIO/ES/Milvus，并分别执行强一致 tuple 回查、对象存在性回查、按本次 file IDs 的 ES/Milvus 定向计数验证。仅当四类验证全部通过，才在同一 UoW 完成 F025/outbox、置 request=`APPLIED` 并退役 guard footprint。派发 task id、普通 dict 或 DB cutover 均不是 delete 的完成证据。
- **rename/move 跨存储可见性协议**：MySQL/DM8、OpenFGA、Elasticsearch 与 Milvus 不存在分布式原子提交，因此采用 durable `OLD_VIEW/NEW_VIEW` 投影而不是隐藏资源。prepare 在 request 隔离的 shadow index/collection 中构建并读后校验；激活 `mutation_transition_active + OLD_VIEW` 并写源/目标 EXACT footprint 后，children/search/preview/download/RAG/citation 仍按不可变 manifest 投影旧名称、旧位置与旧空间权限，目标位置和新名称不得提前暴露。move 可以预装目标检索并以 HIGHER_CONSISTENCY 增加新 parent，但保留旧 parent；OLD_VIEW 的二次授权强制使用旧空间，不能被临时双 parent 放宽。随后在固定 `instance → outbox → request → space/resource → steps` 锁序的单一 UoW 内完成 DB 名称/位置/版本链/标签 cutover、把 phase 切为 `NEW_VIEW`，并原子完成 Deferred outbox/instance。NEW_VIEW 只展示新名称/新位置并强制目标空间权限；源残留被排除。rename 在 phase 切换前不覆盖正式旧索引，切换后若 metadata cleanup 尚未完成，则返回值名称投影为新名称且检索查询执行 `new_name → old_name` 扩展以保持召回。
- **crash/补偿判据**：parent prepare 成功而 DB 未提交时仍为 OLD_VIEW，旧位置、旧权限和旧检索持续可用；明确未提交的异常把新 parent/目标预装幂等回滚并读后校验。事务提交 ACK 不确定时必须用新 session 重读 request phase、manifest 应用结果及 F025 终态：已是 NEW_VIEW 就续清理，明确 OLD_VIEW 才回滚，未知状态保持 transition 并重试。DB+NEW_VIEW+F025 提交后，post-cutover cleanup 才幂等提升 rename shadow、删除 move 旧 parent/源检索残留并 drop shadow；成功时同事务清 active 并退役 projection footprint。清理崩溃保持 APPLIED+active，由 Beat 扫描稳定 token 并调用 `continue_post_cutover_cleanup()`；`continue_compensation(request_id, execution_token)` 只按 durable steps 逆序补偿，旧 token 或终态返回 ignored，绝不接受 task id 作为完成证据。
- **实现偏差记录**：原计划“原重命名/移动主体不重写”仅保留业务校验与底层存储 primitive；不能复用 `rename_file()` / `move_items()` 这类先提交正式 DB、再派发索引/FGA 的 legacy orchestrator。F046 最小新增 `ProductionMutationStepOwner`、token-bound `execute_and_verify_step()` / `continue_post_cutover_cleanup()`、`MutationReadProjectionService` 与 durable cutover/finalize/compensation 协议，worker 只负责恢复 tenant 和调用 owner API，不解释 manifest。
- **补偿**：rename/move 优先执行可逆步骤或影子状态，面向用户的 DB 名称/位置在末端切换；delete 在 cutover 前任一步失败都不改正式资源，仍保持目录、搜索、问答、引用、预览、下载可用，且直接暴露 `execute_failed`。delete cutover 提交后不做业务回滚：deletion guard 持续阻止外部残留被正式读路径访问，F025 保持 executing 直至 purge 全部验证；purge 失败则显示 execute_failed，新 token 续跑未成功 step。`applying/compensating/failed` 均继续占用 footprint；取消只允许在尚未产生业务写时执行，已部分执行必须补偿或继续重试。
- **何时重新考虑**：知识空间 mutation 已整体迁入新的 command bus 时，再把 wrapper 变为 command middleware。

### 决策 5：单一审批场景，动作随不可变快照保存

- **备选**：
  - A. 上传、重命名、移动、删除各建一个场景。
  - B. 共用 `knowledge_space_file_change_request`，用 `action` 区分操作。
- **选定**：B。
- **原因**：四类动作共享相同策略、审批人和 OR 节点，拆场景会让每租户重复配置并产生漂移。`action`、资源、原值、目标值和上传暂存信息进入申请快照；handler 按动作分派。
- **何时重新考虑**：某一动作需要不同审批人、节点或 SLA，且路由条件无法清晰表达时拆场景。

### 决策 6：空间行锁串行化冲突检查，业务表负责资源占用索引

- **备选**：
  - A. 依赖 ApprovalGate 当前“申请人 + business_key”去重。
  - B. 仅在业务表加目标资源唯一索引。
  - C. 创建申请前对涉及空间按 ID 升序 `SELECT ... FOR UPDATE`，随后查询活跃审批的资源/祖先/子树重叠，再创建申请。
- **选定**：C，并要求锁、申请和 ApprovalGate 共用一个 session-bound Unit of Work。
- **原因**：A 允许不同申请人或不同动作并行；B 无法表达父文件夹与子资源重叠。C 在 MySQL/DM8 都可用，按空间串行的临界区只覆盖低频变更申请创建，可可靠阻止父子竞态。跨空间移动同时锁源、目标空间，固定升序避免死锁。现有 ApprovalGate/Repository 各自开 session 并提交，若不改造，空间锁会在创建审批前失效并留下 orphan request。
- **原子创建**：`KnowledgeSpaceFileChangeService` 开启 `FileChangeRequestUnitOfWork`，依次锁定源/目标空间、计算真实 footprint、检查冲突、写 change request，再调用支持同一 session 的 `ApprovalGate.request_or_pass_in_uow()` 原子写 instance + tasks + submitted log 并回填 `approval_instance_id`，最后一次提交。审计、站内信和 Celery 均作为 post-commit effects 执行；事务失败不留下业务申请或半审批实例。
- **footprint**：申请显式保存 `affected_resource_ids/affected_path_roots`。文件/文件夹包含根资源和祖先路径；文件夹删除/移动扩展子树；版本文件扩展同一 `KnowledgeDocument` 的全部版本；跨空间移动同时覆盖源/目标空间、目标父目录及其祖先。冲突查询按关系列和路径前缀批量完成，不在 JSON 上过滤。
- **活跃定义**：关联审批实例状态属于 `pending / exception / approved / executing / execute_failed` 均视为占用；只有 `executed / rejected / withdrawn / cancelled` 释放。`approved` 在 outbox 执行完成前仍必须锁定。
- **何时重新考虑**：单空间变更申请达到高并发并出现明显锁等待时，升级为规范化祖先锁表；不能退回无事务的先查后写。

### 决策 7：文件夹审批锁覆盖整棵子树，但只展示根申请

- **备选**：A. 文件夹和每个子项分别建审批；B. 只锁文件夹根，不阻止子项操作；C. 一条根申请覆盖整树，并用 footprint 向下阻止冲突。
- **选定**：业务表只创建文件夹根申请。冲突检查通过 `file_level_path` 判断祖先和子树；子项不生成审批实例。列表在根文件夹显示“审批中”，进入子目录时返回 `inherited_approval_lock` 使子项操作置灰，但不把每个子项伪装成独立审批。
- **原因**：符合“一次文件夹动作覆盖内部元素”，避免千文件夹生成千任务；同时用户在子目录操作时仍能获得明确阻止原因。
- **何时重新考虑**：产品要求子项可从父审批中排除时，必须升级为可编辑的批次清单，当前根快照不支持部分批准。

### 决策 8：动态资格是真相，审批任务是可对账的物化待办

- **备选**：
  - A. 空间权限变化时直接把旧 `ApprovalTask.approver_user_id` 改成新审批人。
  - B. 不调整任务，只在最终审批时动态校验当前 owner/manager。
  - C. 当前 owner/manager 关系作为资格真相；已创建任务保留审计历史，通过对账取消失效待办并为新增审批人补建待办，最终处理前仍动态校验。
- **选定**：C。场景节点固定为 `knowledge_space_owner + knowledge_space_manager`、单节点 OR。`ApprovalTask` 只表示某一时刻的任务分配和处理历史，不能作为当前审批资格或详情可见性的唯一依据。
- **资格解析**：F025 通过 handler 调用知识空间严格 resolver，按 OpenFGA 权威 owner/manager 关系展开有效用户（包含允许的 userset 展开），排除申请人并去重。查询失败必须 fail-closed：抛可重试 `SpaceFileChangeApproverUnavailableError`，不回退可能陈旧的 membership，也不创建/恢复 `approver_empty`；只有权威查询成功且结果为空才是无人审批。
- **对账规则**：F025 `ApprovalDynamicAssigneeService` 在实例 UoW 内解析当前集合，与当前节点 pending tasks 做差异：失去资格的 pending task 改为 `cancelled`，新增资格者补建 pending task；已批准、拒绝、跳过或已取消任务不改写，保留完整历史。同一实例、节点、审批人在任一时刻最多存在一条 pending task；用户被移除后再次加入时新建 task，不能把已取消的历史任务改回 pending。MySQL/DM8 不依赖 partial unique，幂等由“所有 task 创建入口先锁实例、锁内查 pending”保证。
- **状态集合分离**：资源互斥使用 `RESOURCE_LOCK_BLOCKING_STATUSES={pending,exception,approved,executing,execute_failed}`；审批人对账只允许 `APPROVER_RECONCILABLE={pending, exception 且当前节点存在 open approver_empty}`，绝不向 approved/executing/execute_failed 实例补 task。
- **空审批人处理**：F025 提供事务内 `ensure_approver_empty_locked()` / `resolve_approver_empty_locked()`。同一实例节点最多一个 open 异常；恢复只关闭对应异常，`resolved_by_user_id=NULL`、`resolved_action=approvers_reconciled`，随后实例回 pending 并补建 tasks。通用管理员异常动作与自动恢复都使用同一实例锁；但 F046 的场景 policy 禁止 assign/assign-flow/skip/mark-complete，只允许 strict retry 或 cancel，不能绕过当前 owner/manager。
- **三层触发**：
  1. owner/manager 授予、撤销、转移事务成功后异步触发空间级对账；对账失败不能回滚已经成功的权限变更，由重试和后续两层补偿。
  2. 知识空间文件变更列表对本页可见实例执行批量惰性对账；单条和批量审批在决策事务内同步对账，保证页面与操作入口可以自愈。列表禁止逐实例 N+1 查询，只有检测到差异的实例才加锁写入。
  3. Celery 定时任务按租户扫描存在活跃文件变更审批的空间，补偿漏事件和长期失败。
- **原子决策 UoW**：F025 新增 session-bound `ApprovalDecisionUnitOfWork`，固定锁序为 `instance → current-node tasks → open exception/outbox`。task-ID 与 instance-ID 两个入口均在一次事务中执行“锁实例 → 对账 → 重读/定位当前 pending task → 严格资格校验 → task/sibling/instance/action log/exception/outbox 状态迁移”，一次提交后再派发通知、终态 hook 和 Celery。`withdraw`、通用异常动作也先校验场景 policy，再采用相同 instance-first 锁序。
- **统一入口**：`ApprovalCenterService.decide_instance_for_current_approver()` 供文件页单条/批量审批；既有 `decide_task()` 复用内部 `_decide_locked_task()`。F045 `resource_user_invite_confirmation` 的 target-user 自确认、原子 `decide_single_task` 和专属通知属于回归不变量，可保留专用分支，不能被普通 OR 逻辑覆盖。
- **详情可见性**：runtime handler 增加 `authorize_view(instance, viewer_user_id)`。F025 `list_my_tasks/get_task_detail/get_instance_detail` 和 F046 preview/detail 都按当前 owner/manager 重新校验；已取消的历史 task 只保留数据库审计，不再让 former approver 看文件名、动作或 snapshot。申请人继续可见自己的申请。
- **查询与通知**：文件变更列表的 `can_approve` 按当前 owner/manager 动态计算，不依赖旧 task 是否已存在。初始 Gate PENDING 提交后通知首次 tasks；对账只通知新增 tasks；首次进入 approver_empty 只通知管理员一次；恢复通知新增审批人。通知均 post-commit best-effort，失败记录指标但不回滚审批。集合变化写 `approval.approvers.reconciled` action log，记录 `added_user_ids/removed_user_ids/trigger/operator_user_id`；lazy/beat 的操作者为空，权限变更触发可记录实际操作者。
- **影响**：这是 F025 的可复用动态审批人扩展；统一复用 Approval* 模型、异常服务和权威 decision service，不扩展 legacy `/approval/requests` 或 `/approval/department-knowledge-space`。实现后必须同步更新 `approval-module/SKILL.md`。
- **何时重新考虑**：审批中心原生提供声明式动态候选人和可靠的任务对账机制时，将 reconciler 下沉为引擎能力，业务 handler 只保留资格解析。

### 决策 9：终态 hook 只做业务清理，锁状态不复制

- **备选**：A. 在 request 表复制审批状态并以它释放资源；B. 锁状态实时读取 F025，仅在 request 保存执行/清理 checkpoint。
- **选定**：业务申请表保存 `approval_instance_id`，活跃/终态实时读取审批实例。`on_rejected/on_withdrawn/on_cancelled` 负责清理上传临时对象等副作用，但不维护一份决定锁定的独立状态。
- **原因**：F025 当前终态 hook 失败会记录日志但不回滚审批终态；若锁依赖业务表状态，hook 失败会永久锁死资源。以审批实例为事实源符合 INV-1，清理失败可由补偿任务重试。
- **何时重新考虑**：审批引擎提供事务性 domain event/outbox 后，可把清理也改为可靠事件消费。

### 决策 10：跨空间移动按源空间策略发起，执行时校验两端

- **备选**：A. 按源空间策略和审批人；B. 按目标空间策略和审批人；C. 源、目标各发一张审批形成隐式双阶段。
- **选定**：是否需要审核由资源当前所在的源空间决定；私密源空间直接执行。申请创建时校验源资源 move 权限和目标 upload 权限，审批通过执行前再次校验两端、目标是否存在、层级、循环、重名和租户一致性。
- **原因**：动作发生在源资源上，审批人也是源空间 owner/manager。若按目标策略，会出现审批人归属不清和同一动作双审批。目标变化通过执行失败暴露，不静默改目标。
- **何时重新考虑**：产品要求跨空间接收方也必须确认时，应设计双阶段审批，不能在当前单节点 OR 流程上叠加隐式确认。

### 决策 11：审批上传的正式行以发布门禁隔离解析期

- **备选**：
  - A. 审批通过后同步等待整个解析链路完成，再让 approval outbox 返回。
  - B. 给 `KnowledgeFile` 增加通用 draft/published 字段并改造所有上传。
  - C. 继续异步解析；仅对关联 F046 upload request 的正式文件建立发布门禁，解析状态成功后自动解除。
- **选定**：C。`on_approved` 通过 session-bound `add_file_in_uow()` 在同一数据库事务内创建正式行/版本并回填 request 的 `executed_resource_id`；提交前发布门禁已可由 file ID 查询，不存在“正式行已提交、request 关联尚未提交”的窗口。提交后才建立 FGA、派发解析并返回 Deferred，instance/outbox 保持 `executing/deferred`；`KnowledgeFile.status=SUCCESS` 且全文索引/向量 step 均回执成功后才是 `published/executed`。FAILED/VIOLATION/TIMEOUT 映射为 `parse_failed/execute_failed`，专用 retry API 复用现有文件 ID 和原审批、但通过 F025 resume UoW 开启新 execution token 代次，不重新申请。
- **原因**：A 会让 approval worker 长时间阻塞且无法可靠等待外部解析；B 会扩大所有上传主流程。C 用 F046 request 与 `executed_resource_id` 建立发布关系，保持正式表语义不变，同时满足解析完成前不进入正式列表/检索/OpenAPI/RAG/citation。
- **防泄漏**：`KnowledgeSpaceFilePublicationGuard` 批量提供 `list_unpublished_ids(space_id)`、`filter_published_ids()` 和 `require_published_or_stakeholder()`。F027 children/search、F030 对外文件 API、F029 index prefilter/post-filter、citation resolve、preview/download 都必须组合该 guard；即使解析过程中已经写入部分 ES/Milvus chunk，也不得被召回或泄露文件名。
- **状态真相**：审批状态仍来自 F025；解析/发布状态实时来自 `KnowledgeFile.status` 与 durable step 回执，request 只保存关联、execution token 和执行摘要，不复制解析状态。runtime handler 的 `get_business_status_projection()` 让文件页和审批中心读取同一 `parsing/parse_failed/published + failure_reason` 投影；普通用户永远看不到未发布文件。
- **何时重新考虑**：所有知识文件统一引入正式的 draft/published 生命周期，并且列表、OpenAPI、RAG 与 citation 全部以该字段为共同入口时，再移除 F046 专用 guard。

### 决策 12：文件变更审批场景是系统固定场景

- **备选**：A. 允许租户管理员像普通场景一样任意配置；B. 仅限制审批人来源；C. 审批中心可查看但不可禁用、删除或修改路由/流程/节点。
- **选定**：C。固定 `enabled=true`、单 catch-all flow、单 OR 节点、owner+manager 两类来源，禁止 pass route、AND、多节点和自定义审批人；审核是否启用只由 F046 租户/空间策略决定。
- **原因**：spec 的 owner/manager 单节点 OR 是业务规则，不是租户可配置项。若场景可禁用或改 pass，默认开启策略会报错或绕过审核。
- **bootstrap**：默认租户启动初始化、新租户创建、管理员保存策略及首次有效需审 mutation 均调用幂等 `ensure_system_file_change_scenario(tenant_id)`；既有租户无需运维先写数据。管理 API 对该场景的 update/delete/route/flow/node 写请求返回明确只读错误。
- **何时重新考虑**：产品明确允许租户自定义文件变更流程，并同步修改 spec 的固定审批人和 OR 语义后，才开放配置。

---

## 4. 系统现状（接手必读）

### 4.1 当前代码基线

- `knowledge/api/endpoints/knowledge_space.py` 暴露文件/文件夹创建、重命名、移动、删除入口。
- `KnowledgeSpaceService.add_file()` 当前会立即创建 `KnowledgeFile`、`KnowledgeDocument`、V1、FGA child tuple，并派发解析 scheduler。
- `add_file()` 返回时解析尚未完成；`list_space_children()` 默认不按 status 排除 WAITING，审批上传若直接复用会提前进入正式列表。
- `/knowledge/upload/{space_id}` 当前返回临时分享 URL，原文件名依赖 24h Redis 映射，不能直接持久化为审批对象引用。
- `rename_file()` / `rename_folder()` 当前直接改名称；成功文件重命名后会触发 chunk rebuild。
- `move_items()` 是 F034 权威实现，含权限、层级、循环、跨租户、版本链、FGA parent tuple、跨空间向量迁移和标签处理。
- `delete_file()` / `delete_folder()` 是权威删除实现，含版本级联、MinIO/索引清理任务和 FGA tuple 清理。
- rename/move/delete 都跨 DB、OpenFGA、对象/索引和 Celery 多阶段，部分步骤会在前一步已经提交后失败；审批重试必须识别并续跑，不能假定调用失败等于“完全未执行”。
- F025 `ApprovalGate` 当前只按 `(tenant_id, scenario_code, business_key, applicant_user_id)` 查重，不能实现跨申请人的资源/子树互斥。
- F025 普通 Gate、decision 和 exception service 当前多次开 session/commit，无法仅靠外层行锁形成原子操作；任务详情也以历史 task 归属判断，former approver 仍可能看到 snapshot。
- client `useFileUpload.ts` 当前对删除做乐观移除；接入审批后必须改为根据 `direct/pending` 响应决定是否移除。
- `ApprovalCenterDialog.tsx` 当前处理旧 task 后会切到 processed，不满足“留在待处理并选择下一条”。

### 4.2 目标数据流

#### 4.2.1 策略判断

`mutation 入口 → 校验现有操作权限 → 读取空间及部门绑定 → 私密空间直接执行 → owner/manager 直接执行 → 读取当前租户策略和单空间设置 → 无需审核直接执行 / 需要审核创建申请`

判断顺序固定：权限校验优先，防止无权限用户借审批探测资源；之后是私密免审和 owner/manager 直通；最后计算租户/空间策略。

#### 4.2.2 待审批上传

`multipart 上传 → 服务端持久化 KnowledgeSpaceUploadStage 并返回 upload_id → POST files/folders-upload 提交 upload_id → 逐文件校验权限/配额 → 同一 UoW 锁空间、创建 KnowledgeSpaceFileChangeRequest、ApprovalGate → 返回 pending → 独立待审批上传列表`

审批通过：

`approval outbox → KnowledgeSpaceFileChangeScenarioHandler.on_approved → 重新校验申请人权限/空间状态/配额 → 同一 DB UoW 内 add_file_in_uow + 回填 executed_resource_id → 提交后建立 FGA 并派发解析 → 返回 Deferred，instance/outbox 保持 executing/deferred → 独立列表显示 parsing → KnowledgeFile SUCCESS 且索引/向量 step 回执完成 → complete_deferred_execution → 发布门禁解除并置 executed`

`KnowledgeFile FAILED/VIOLATION/TIMEOUT 或 step 超时 → fail_deferred_execution → 独立列表显示 parse_failed/execute_failed → POST retry-ingest → F025 resume UoW 生成新 token、原子恢复 instance/outbox/request/steps → 复用 executed_resource_id 与稳定 step idempotency key 派发既有 retry → 不创建新审批 → 全部回执成功后发布`

拒绝、撤回、取消：删除临时对象并保留最小审计元数据；清理失败进入补偿扫描。待审批上传从不进入正式列表。

文件夹上传按文件分别创建申请，`relative_path` 保存在每条快照。审批通过时按路径幂等创建缺失目录；同一批中的审批顺序不影响最终目录结构。目录创建本身不单独审批。

#### 4.2.3 正式资源重命名/移动/删除

`请求 → 权限/策略 → 计算版本链/子树/目标目录 footprint → 同一 UoW 锁空间行 → 检查 footprint 重叠 → 创建业务申请及 ApprovalGate bundle → 一次提交 → 返回 pending`

审批期间不修改 `KnowledgeFile`。列表批量关联活跃申请并展示根资源“审批中”；详情来自申请的不可变动作快照。

审批通过：

`outbox → handler → 重新校验当前资源与申请快照 → 读取 durable execution steps → 调幂等 rename/move/delete executor 执行缺失步骤 → 同步完成则 Completed；存在下游任务则 Deferred 并保持 executing → coordinator 汇总回执、读后校验、必要时补偿 → 完成判据满足后 complete_deferred_execution 将 ApprovalOutbox=success、ApprovalInstance=executed`

执行失败：durable step/权威读后校验记录失败摘要，由 F025 标记 `execute_failed`。该状态继续占用完整 footprint；resume 以新 token 从未完成步骤续跑。只有完全未开始的请求可直接取消，部分执行请求必须补偿或执行完成后才释放。

rename/move 的生产 owner 不调用先改正式 DB 的 legacy `rename_file/move_items`。步骤顺序固定为：`durable manifest → request-scoped ES/Milvus shadow build/verify → 激活 OLD_VIEW projection/footprint → move 增加新 parent、保留旧 parent并以 HIGHER_CONSISTENCY 校验 → 目标检索 ready（仍不对目标视图开放）→ 同一 UoW 完成 DB cutover（含 move 标签删除）+ NEW_VIEW + Deferred outbox/instance terminal → durable post-cutover cleanup → 清 active 并退役 footprint`。OLD_VIEW 始终展示旧名称/旧位置并强制旧空间权限；NEW_VIEW 同时切换展示和目标空间权限，旧位置/旧 parent/源检索只作为被排除的可清理残留。rename 的正式旧检索在 phase 切换前不覆盖；NEW_VIEW cleanup 崩溃期间以新名称结果投影和新→旧查询扩展保证新名称仍可召回，cleanup 最终从 durable shadow 幂等更新正式 metadata。明确 DB 未提交才回滚新 parent；提交 ACK 不确定时先重读 durable phase/F025 终态，禁止把已提交 NEW_VIEW 回滚为旧外部状态。APPLIED+active 清理由 Beat 以稳定 token 调 `continue_post_cutover_cleanup()` 恢复。

delete 单独遵循可见性与执行终态分离协议：`prepare manifest/steps（零破坏） → 校验资源仍可用 → 同一 UoW 删除正式 DB 行 + 激活 deletion guard（request=APPLYING，F025/outbox=EXECUTING/DEFERRED） → FGA/MinIO/ES/Milvus durable purge + 各自权威读后验证 → 同一 UoW 完成 F025/outbox + request=APPLIED + 退役 guard footprint`。prepare 或 cutover 前失败时原资源完整可用；cutover 后正式 children/search/RAG/citation/preview/download 同时按 DB 与 guard 排除，即使外部残留仍在也不可见。任一 purge 失败时 request/F025/outbox 原子进入 `FAILED/EXECUTE_FAILED/FAILED`，guard 与已成功 step 保持；外层重新执行分配新 token，仅把未成功 purge step 重置为 pending，已成功 step 不重复执行。全部当前 token step 均经读后验证后才可发布执行成功。

### 4.3 数据模型

#### `knowledge_space_file_change_policy`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 主键 |
| `tenant_id` | bigint | 非空、唯一；无跨租户继承 |
| `enabled` | bool | 总开关；默认 `true` |
| `scope` | varchar(32) | `all_spaces` / `per_space`，默认 `per_space` |
| `create_time/update_time` | datetime | 双 DB 通用时间默认值 |

#### `knowledge_space_file_change_setting`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 主键 |
| `tenant_id` | bigint | 当前租户 |
| `space_id` | bigint | 知识空间 ID；与 tenant 组成唯一约束 |
| `approval_required` | bool | 单空间是否审核，默认 `true` |
| `create_time/update_time` | datetime | 更新时间用于后台展示 |

总开关关闭不删除 setting；重新开启恢复原值。`all_spaces` 忽略 setting 但不删除。无 policy 行时读取默认 `enabled=true, scope=per_space`；无 setting 行时默认 `approval_required=true`。私密空间最终结果始终为 false。

#### `knowledge_space_upload_stage`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `upload_id` | bigint / varchar(64) | 内部主键与客户端 opaque UUID；`(tenant_id, upload_id)` 唯一 |
| `tenant_id` / `space_id` / `uploader_user_id` | bigint | 租户、上传目标空间和上传人 |
| `object_name` | varchar(1024) | MinIO 内部对象引用，任何业务响应都不返回 |
| `file_name` / `file_size` / `content_hash` | varchar / bigint / varchar(128) | 服务端确认的原名、大小和 hash |
| `state` | varchar(32) | `uploaded / attaching / attached / consumed / cleanup_pending / cleaned`，只表示暂存对象生命周期；`attaching` 表示申请已提交、生命周期标签尚待移除 |
| `expire_at` / `create_time/update_time` | datetime | 未关联对象回收游标 |

索引：唯一 `uq_ks_upload_stage_tenant_upload(tenant_id, upload_id)`；清理扫描 `idx_ks_upload_stage_cleanup(tenant_id, state, expire_at, id)`；上传人列表/配额 `idx_ks_upload_stage_user(tenant_id, uploader_user_id, state)`。stage 创建、attach、consume 和 cleanup 均先通过 `ensure_policy_row(tenant_id)` 使用 insert-if-absent；唯一键冲突时回滚 savepoint、重新读取并 `SELECT ... FOR UPDATE` 锁定这条保证存在的 tenant policy 行，再按正式已用量 + 未 consumed stage bytes 做配额预占或释放。无 policy 的业务默认值仍等价于该行的默认列值；不能对不存在的行直接 `FOR UPDATE`。

#### `knowledge_space_file_change_request`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 业务申请 ID |
| `tenant_id` / `space_id` | bigint | 源租户和源空间 |
| `action` | varchar(32) | `upload / rename / move / delete` |
| `resource_type` | varchar(32) | `staged_upload / knowledge_file / folder` |
| `resource_id` | bigint nullable | 正式资源 ID；上传审批前为空 |
| `applicant_user_id` | bigint | 业务执行时重新校验的身份 |
| `approval_instance_id` | bigint nullable unique | F025 实例；创建 gate 后回填 |
| `upload_stage_id` | bigint nullable | upload 动作引用，`(tenant_id, upload_stage_id)` 唯一；object name 不复制到申请 |
| `file_name` / `file_size` / `content_hash` | varchar/bigint/varchar nullable | 待审批展示和不可变内容指纹快照 |
| `source_parent_id` | bigint nullable | 发起时父目录 |
| `target_space_id` / `target_parent_id` | bigint nullable | move 目标 |
| `action_snapshot` | `JsonType` | 原名称/新名称、原路径、relative_path、版本指纹等不可变详情；不通过 JSON 字段做过滤 |
| `executed_resource_id` | bigint nullable | 上传成功后的正式文件 ID |
| `execution_state` | varchar(32) | `not_started / applying / applied / failed / compensating`；业务 saga 状态，不是审批状态 |
| `execution_token` | varchar(64) nullable | 当前 Deferred 执行代次 token；同代补投复用，失败/超时 resume 生成新 token，旧代回调忽略 |
| `execution_checkpoint` | `JsonType` | 仅保存面向详情的执行摘要；步骤真相在 execution step 表，派发 task id 不是完成证据 |
| `cleanup_state` | varchar(32) | `none / pending / success / failed`，只表示临时对象清理，不表示审批状态 |
| `create_time/update_time` | datetime | 审计和清理扫描 |

索引：唯一 `uq_ks_change_request_instance(tenant_id, approval_instance_id)`、`uq_ks_change_request_upload(tenant_id, upload_stage_id)`；列表 `idx_ks_change_request_space_created(tenant_id, space_id, create_time, id)`；发布门禁 `idx_ks_change_request_executed_file(tenant_id, space_id, executed_resource_id)`；补偿 `idx_ks_change_request_compensate(tenant_id, execution_state, cleanup_state, update_time, id)`。bulk update/delete 必须显式带 tenant 条件，因为租户自动过滤不覆盖非 SELECT。

#### `knowledge_space_file_change_execution_step`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `tenant_id` / `request_id` | bigint | step 主键、租户和所属申请 |
| `step_code` / `attempt_token` | varchar(64) | 固定步骤名与当前执行代次 token；step 行跨代复用，resume 时只更新未完成 step 的 attempt_token |
| `idempotency_key` | varchar(192) | 下游稳定幂等键，不使用 Celery task id |
| `state` | varchar(32) | `pending / dispatched / succeeded / failed / compensating / compensated` |
| `attempt_count` / `next_retry_at` | int / datetime nullable | 重试计数和补偿扫描游标 |
| `task_id` / `result_digest` / `error_summary` | varchar nullable | 调度证据、读后校验摘要与脱敏错误；不保存对象路径 |
| `create_time/update_time/acked_at` | datetime | 审计、超时和 ack 时间 |

唯一 `uq_ks_change_step(tenant_id, request_id, step_code)`；扫描索引 `idx_ks_change_step_retry(tenant_id, state, next_retry_at, id)`。`idempotency_key` 跨代稳定，coordinator 在提交 step 后派发；ack 必须同时匹配 tenant/request/step/attempt_token，重复 ack 幂等，旧 token ack 忽略。resume 只重置未成功 step 的 state/attempt_token，已成功 step 通过权威读后校验复用。Beat 对 `pending/dispatched/failed/compensating` 做状态观察和补投，不以 task id 推断成功。

#### `knowledge_space_file_change_footprint`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `tenant_id` / `request_id` / `space_id` | bigint | 申请及受影响空间 |
| `resource_type` / `resource_id` | varchar(32) / bigint nullable | 文件、文件夹、版本文件或目标目录的精确占用 |
| `path_root` | varchar(2048) nullable | 规范化 `/{folder_id}/.../` 路径根，前缀判断祖先/子树重叠 |
| `lock_scope` | varchar(16) | `exact / subtree / destination` |

按 `(tenant_id, request_id)` 批量写入；索引 `idx_ks_change_fp_resource(tenant_id, space_id, resource_type, resource_id)` 与 `idx_ks_change_fp_path(tenant_id, space_id, path_root)` 支撑活跃实例 join 后的冲突查询。路径比较使用显式转义的等值/前缀 LIKE，不使用 JSON 函数。

审批实例的 `business_key` 使用 `knowledge-space-change:{request_id}`，避免依赖可变文件名；`business_resource_type` 为 `knowledge_space_file_change`，`business_resource_id` 为业务申请 ID。正式资源互斥由空间锁内的 footprint + 审批实例活跃查询保证，不依赖 ApprovalGate 的申请人级去重。

所有六个模型放在 `knowledge/domain/models/`，Repository 放在 `knowledge/domain/repositories/`。表由 SQLModel 创建；本功能依赖唯一约束和复合索引参与上线即刻行为，因此补 Alembic DDL。downgrade 删除 F046 新表/索引，并按下述前置检查回退 F025 协同列，不触碰正式 Knowledge 数据或 Approval 业务行。不得在 migration 中 seed 或回填租户数据。

同一个 F046 migration 还以 F025 owner 协同方式给 `approval_outbox` 增加 nullable `execution_token/deferred_deadline/heartbeat_at`，并扩展 status 接受 `deferred`；旧行字段均为空且语义不变。downgrade 前必须确认无 deferred 行，存在时拒绝降级而不是静默丢失正在执行的业务。

### 4.4 审批场景和 handler

新增 preset：

```text
scenario_code = knowledge_space_file_change_request
handler_key   = knowledge_space_file_change_request
condition_fields = applicant_role, action, resource_type
approver_source_types = knowledge_space_owner, knowledge_space_manager
```

这是系统固定场景：单 catch-all flow、单节点、`node_mode=or`，来源同时包含 owner 和 manager。默认租户初始化、新租户创建、策略保存和首次需审 mutation 都幂等调用 `ensure_system_file_change_scenario()`；已有租户不继承根租户且无需人工 seed。管理员可在审批中心查看，但场景/route/flow/node 的修改、禁用和删除 API 对该 code 一律拒绝。

`KnowledgeSpaceFileChangeScenarioHandler`：

- `build_title/build_detail`：输出空间、资源名称、动作、原值和目标值；不暴露 MinIO object name。
- `resolve_approvers`：先严格读取 OpenFGA owner/manager（含允许的 userset 展开），再合并当前租户内仍有效的知识空间数据库创建者；创建者按 F044 的永久 owner 语义生效，即使其 best-effort owner tuple 仍在补偿队列也不能产生 `approver_empty`。最终去重并排除申请人；OpenFGA 不可用时仍抛可重试错误，不把数据库创建者或 membership 当作故障降级。
- `validate_decision`：处理前实时确认任务用户仍是目标空间 owner/manager；该校验是最终授权边界，不能因已完成对账而省略。
- `authorize_view`：申请人或当前有效 owner/manager 可查看业务详情；former approver 仅保留历史 task，不再获得 snapshot/preview 权限。
- `filter_visible_instances`：`list_my_tasks/my_requests` 的批量可见性 hook，同 tenant/space 合并 owner/manager 查询，避免逐 task OpenFGA N+1。
- `discover_candidate_instances`：F025 查询当前用户待办、待办数或未读数之前，先用严格 resolver 批量取得该用户当前有效管理的空间，再由 F046 以 `(tenant_id, space_ids, APPROVER_RECONCILABLE)` 分页找出活跃实例并交给原子对账。这样新 manager 即使没有任何历史 task，也能正向发现待办；使用 instance 游标和有界 batch，禁止全租户 fetch-all。
- `get_business_status_projection`：实例详情实时拼接 upload 的解析/发布状态和可用失败原因；不回写 approval instance。
- `reconcile_pending_approvers`：把严格 resolver 的当前集合交给 F025 `ApprovalDynamicAssigneeService`，handler 本身不直接写 Approval*。
- `on_approved`：按 action 调业务 executor，成功才返回；任何前置条件或副作用失败都抛出。
- `on_rejected/on_withdrawn/on_cancelled`：上传动作触发临时对象清理；正式资源动作无需回滚，因为尚未执行。

`KnowledgeSpacePendingApproverReconciler`（知识空间侧触发器）：

- `reconcile_space_pending_approvers(space_id, trigger)`：按 tenant + space 查询活跃文件变更实例，并逐实例调用对账；不扫描其他审批场景。
- `reconcile_instance_pending_approvers(instance_id, trigger)`：只调用 F025 原子动态审批人 Service；知识模块不直接创建/更新 ApprovalTask/Exception。
- 权限变更成功后只投递异步对账任务；触发点覆盖通用 `/resources/.../authorize` 的知识空间 owner/manager 变更、`sync_direct_space_user_permissions`、部门管理员同步和 SSO/组织清理。遗漏由列表、decision 和 Beat 补偿。
- 文件页列表按本页 instance IDs 一次批量读取 task/资格，只对发生差异的实例逐一调用原子对账；F025 `list_my_tasks/count_pending/unread` 在原 task 查询前调用 `discover_candidate_instances`，完成候选对账后再查询和分页 task；decision 前同步对账。对账只处理 `APPROVER_RECONCILABLE`，不修改业务申请、资源锁或已处理 task。
- Beat 单次跨租户枚举使用 `bypass_tenant_filter()`；逐租户 `set_current_tenant_id()`，按 `(update_time,id)` 游标分批。任务参数显式携带 `tenant_id`，worker 恢复 ContextVar；走默认 `celery` 队列，指数 backoff 重试，单租户失败不阻断其他租户。

统一审批中心扩展（所有 Approval* 写行为归 F025）：

- runtime handler 增加可选 `reconcile_pending_approvers`、`discover_candidate_instances`、`validate_decision`、`authorize_view/filter_visible_instances`、`get_business_status_projection` 与 `exception_action_policy`；未实现的场景保持现有行为。
- `ApprovalGate.request_or_pass_in_uow()` 原子写 instance + tasks + submitted log；`ApprovalDecisionUnitOfWork` 原子处理 task/instance/exception/outbox，返回 post-commit effects。
- F025 `ApprovalOutbox` 增加 `status=deferred` 及 `execution_token/deferred_deadline/heartbeat_at`；`claim_outbox()` 只领取 pending/failed 或过期 processing，明确排除 deferred。增加 `Completed/Deferred` 执行结果和 `heartbeat_deferred_execution/complete_deferred_execution/fail_deferred_execution/resume_deferred_execution` 原子 API；旧 handler 默认返回 Completed，行为不变。watchdog 是 deferred 超时的唯一状态迁移者，先锁 instance/outbox 并再次核对 deadline/token；resume 通过 handler 的 session-bound `prepare_resume` 联动业务 request/steps，提交后才补投。回调必须匹配 tenant、instance、outbox 与当前 token，重复/过期回调幂等忽略。
- F046 的 `exception_action_policy` 禁止通用 `assign_approvers/assign_flow/skip_node/mark_manually_completed`，防止绕过当前 owner/manager 单节点 OR；`retry` 只能调用 strict resolver 恢复当前完整审核人集合，`cancel` 保留并走同一实例锁。exception API 在变更任何数据前调用 policy，不能只靠前端隐藏按钮。
- `ApprovalCenterService.decide_instance_for_current_approver()` 是按实例处理的唯一权威入口，供文件详情和批量通过使用；endpoint 不自行创建 task，也不直接迁移实例状态。
- `decide_task()` 与按实例决策共用 `_decide_locked_task()`；`withdraw` 及通用异常动作在场景 policy 校验后同样锁实例。F045 邀请确认专用分支保留并加入回归测试。

`approval_runtime_handler_factory.py` 注册运行时 handler；`approval_registry.py` 注册 preset；审批 skill 的场景、代码锚点、通知矩阵同步更新。

### 4.5 API 契约

#### 4.5.1 管理后台策略

- `GET /api/v1/knowledge/space/admin/file-change-policy`
- `PUT /api/v1/knowledge/space/admin/file-change-policy`
- `GET /api/v1/knowledge/space/admin/file-change-settings?keyword=&page=&page_size=`
- `PUT /api/v1/knowledge/space/admin/file-change-settings/{space_id}`
- `PUT /api/v1/knowledge/space/admin/file-change-configuration`

仅当前租户管理员可访问，不接受客户端 `tenant_id`。策略响应：

```json
{
  "enabled": true,
  "scope": "per_space"
}
```

单空间列表返回 `space_id/name/auth_type/space_kind/approval_required/effective_required`；私密空间 `effective_required=false` 且设置控件禁用，部门空间不允许 private。

Platform 保存总控和多个单空间配置时只调用 `file-change-configuration`，请求体为
`{policy?: {enabled,scope}, settings:[{space_id,approval_required}]}`。服务端从当前 tenant ContextVar 取租户，
拒绝 body/query 中的 `tenant_id`，先锁定并校验全部 `(tenant_id, space_id)`，再在同一个数据库事务中写策略、
所有单空间设置并幂等确保固定场景；任一空间不存在、跨租户或任一写入失败时整体回滚。旧的 policy/单空间
PUT 仅保留兼容，Platform 不以多个独立请求拼装一次“保存”。

#### 4.5.2 mutation 统一结果

所有路径带 `/api/v1` 前缀。单条重命名/删除使用：

```json
{
  "decision": "direct | pending",
  "approval_instance_id": 123,
  "change_request_id": 456,
  "resource": null
}
```

直接执行时 `resource` 使用原接口结果，审批字段为空；pending 时正式资源不变。现有单条路径保持：

- `POST /knowledge/space/{space_id}/files`
- `PUT /knowledge/space/{space_id}/files/{file_id}`
- `PUT /knowledge/space/{space_id}/folders/{folder_id}`
- `DELETE /knowledge/space/{space_id}/files/{file_id}`
- `DELETE /knowledge/space/{space_id}/folders/{folder_id}`

`POST .../files` 从短期 `file_path[]` 迁移为 `upload_ids[]`，按文件返回 `FileMutationItemResult[]`；`POST .../folders/upload` 的 item 使用 `upload_id + relative_path`，文件名/大小/hash 只认 stage 服务端数据。直接、待审和失败文件互不回滚：

```ts
interface FileMutationItemResult {
  inputId: string; // upload_id 或资源 id
  resourceType: 'file' | 'folder';
  decision: 'direct' | 'pending' | 'invalid';
  resource?: KnowledgeFile;
  approvalInstanceId?: number;
  changeRequestId?: number;
  errorCode?: number;
  errorMessage?: string;
}
```

F034 `POST /knowledge/space/{space_id}/files/move` 保留 `moved/invalid`，新增 `pending`：

```json
{
  "moved": [],
  "pending": [{"id": 1, "type": "file", "approval_instance_id": 123, "change_request_id": 456}],
  "invalid": []
}
```

`POST /knowledge/space/{space_id}/files/batch-delete` 改为逐项 `deleted/pending/invalid`；新增 `POST /knowledge/space/{space_id}/files/batch-rename`，请求 `items:[{id,type,name}]`，返回 `renamed/pending/invalid`，满足 AC-49。所有逐项失败包含 error code/message，客户端只能移除 `deleted`、只能本地更新 `renamed/moved`，不能把 HTTP 200 当成全批成功。

#### 4.5.3 待审批上传和资源审批详情

- `GET /knowledge/space/{space_id}/file-changes/uploads?status=&cursor=&page_size=`：申请人看自己的未清理记录；当前 owner/manager 看未清理的可审批记录。`cleanup_state=success` 的申请保留为审批审计数据，但必须退出待审批文件列表。响应为 F027 `PageInfiniteCursorData{data,page_size,has_more,next_cursor}`，不返回 object name。
- `GET /knowledge/space/{space_id}/file-changes/{request_id}`：返回动作详情和可见的审批/执行摘要；former approver 不可见。
- `GET /knowledge/space/{space_id}/file-changes/{request_id}/preview`：申请人/当前有效审核人获取 stage 或未发布正式文件的短时预览 URL。
- `POST /knowledge/space/{space_id}/file-changes/{request_id}/retry-ingest`：仅 `parse_failed/execute_failed` upload 可调用；委托 F025 `resume_deferred_execution()` 在实例锁内生成新 token，并通过 handler `prepare_resume` 原子恢复 request/outbox/instance/未完成 steps，提交后复用 `executed_resource_id` 和既有解析重试链路，不创建审批。
- `DELETE /knowledge/space/{space_id}/file-changes/{request_id}`：仅 upload 清理。pending/approver_empty 先经 F025 权威 withdraw/cancel；rejected/withdrawn/cancelled 直接清 stage；parse_failed 清理未发布正式文件及 stage且不创建删除审批；approved/executing/parsing 返回不可清理，避免与执行任务竞态。
- `POST /knowledge/space/{space_id}/file-changes/batch-approve`：接受 `approval_instance_ids` 或 `change_request_ids`（二选一，禁止混传），逐项调用 `ApprovalCenterService.decide_instance_for_current_approver()`；统一服务在实例锁内完成对账、定位当前用户 pending task 和权威 decision。实例必须属于当前 tenant、space 和文件变更场景。

批量审批逐项响应：

```ts
interface BatchApprovalItemResult {
  changeRequestId: number;
  approvalInstanceId: number;
  result: 'approved' | 'invalid' | 'failed';
  latestStatus: string;
  errorCode?: number;
  errorMessage?: string;
  retryable: boolean;
}
```

批量接口独立提交每个实例，成功项不回滚；顶层返回 `successCount/failureCount/items`，满足 AC-37 的最新状态和可重试反馈。

正式文件/文件夹列表项扩展：

```ts
interface FileChangeApprovalView {
  status: 'pending' | 'exception' | 'approved' | 'executing' | 'execute_failed';
  action: 'rename' | 'move' | 'delete';
  instanceId: number;
  requestId: number;
  canApprove: boolean;
  inherited: boolean;
  rootResourceId: number;
}
```

只有申请人和当前有效审核人收到完整字段。`canApprove` 按当前 owner/manager 关系动态计算，不以是否已有 pending task 为前提；返回前的批量 enrichment 触发惰性对账，但字段本身不能作为服务端授权依据。其他用户继续看到普通资源且字段为空。子树内项目可返回 `inherited=true` 以禁用操作，但 UI 只在根资源展示审批标签。

待审批上传投影只有一套真相：F025 `pending/exception/approved/rejected/withdrawn/cancelled` 原样展示；instance `executing + outbox deferred` 时按 steps/`KnowledgeFile.status` 展示 `parsing`；instance `execute_failed` 展示 `parse_failed/execute_failed + failure_reason`；只有 instance `executed` 才展示 `published`。不存在“instance executed 但仍 parsing/parse_failed”的组合。

#### 4.5.4 错误码

| 错误 | Code | 语义 |
|---|---:|---|
| `SpaceFileChangeConflictError` | 18072 | footprint 已被未结束变更占用 |
| `SpaceFileChangeRequestNotFoundError` | 18073 | 当前租户/空间内申请不存在或不可见 |
| `SpaceFileChangeInvalidStateError` | 18074 | 当前状态不允许撤回、清理、重试或审批 |
| `DepartmentSpacePrivateForbiddenError` | 18075 | 部门知识空间禁止创建/切换为 private |
| `SpaceFileChangeApproverUnavailableError` | 18076 | 权威 owner/manager 查询暂不可用，操作可重试且审批状态未改变 |

无权操作继续复用 18040，审批任务已处理/无权等通用错误复用 F025 181 段；不能用 `str(exception)` 作为客户端分支依据。

### 4.6 前端设计

#### Client

- `api/knowledge.ts` 扩展 upload_id、逐项 mutation 结果、待审批上传列表、详情、预览、解析重试和批量通过 API；不在 store 中发 HTTP。
- `useFileUpload.ts` 删除“调用前乐观移除”。只有 `decision=direct` 或批量结果进入 `deleted` 才移除；`pending` 原地标记审批中。
- `useKnowledgeMove.ts` 对 `pending` 保持源位置，关闭移动弹窗并刷新；不得提供 F034 同空间撤回 toast，因为动作尚未执行。
- `FileTable.tsx` / `FileCard.tsx` 在根资源显示“审批中”，详情展示动作及待生效值；资源或祖先带 lock 时重命名/移动/删除菜单禁用。
- 新增待审批上传面板，与正式文件列表分离；支持 `pending/parsing/parse_failed` 展示、预览、撤回/清理、解析重试和审核人批量通过。批量选择依据动态 `canApprove`，提交实例/变更申请 ID，不能缓存或提交旧 task ID。
- `ApprovalCenterDialog.tsx` 消费通用 `detail_snapshot + business_status_projection`，展示动作、解析中/失败原因；修复当前“处理后切到 processed”的行为：始终停留 `pending_me`，移除已处理项并选择下一条，空时显示待办空状态。
- 三语言 locale 同步新增；不引入新 UI/state 库。

#### Platform

- 在现有 Platform 工作台 `/build/client` 的“知识空间”配置页增加“知识空间文件变更审核”总控、范围和单空间表格，仅平台/租户管理员可见可写；知识库 `/filelib` 不再展示独立设置 Tab。
- `controllers/API/knowledgeSpaceFileChange.ts` 封装管理 API；页面只保存本地表单，点击保存成功后才更新基线。
- 总控与当前编辑过的单空间设置通过一次 `PUT .../file-change-configuration` 原子提交；失败时全部草稿保持 dirty，
  不得以 `Promise.all` 并发调用旧 policy/setting PUT 造成部分成功。
- 私密空间行显示“无需审核”且禁用；部门空间不提供私密选项。

### 4.7 部门知识空间禁止私密

- `DepartmentKnowledgeSpaceService.batch_create_spaces()` 对显式 `auth_type=private` 返回领域错误，不静默改写。
- `KnowledgeSpaceService.update_knowledge_space()` 在目标空间存在 `DepartmentKnowledgeSpace` 绑定且请求切换为 private 时拒绝；不能只依赖前端隐藏选项。
- 创建默认继续使用非私密类型。若历史数据存在私密部门空间，部署前由独立运维脚本审计和修复；Alembic 不做数据迁移。
- 普通知识空间在等待期改为 private 只影响后续新申请；已有 request 继续执行原审批，handler 重验权限/资源状态但不重新套用当前免审策略。

### 4.8 关键模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `knowledge_space_file_change_policy` models/repository/service | 租户策略与单空间设置 | 不读取根租户 fallback，不判断用户业务权限 |
| `knowledge_space_upload_stage` model/repository | opaque upload、对象元数据、容量预占和清理游标 | 不向客户端暴露 object name，不表示审批状态 |
| `knowledge_space_file_change_request/footprint/execution_step` model/repository | 动作快照、实例关联、真实资源占用、durable step/outbox、批量状态查询 | 不复制审批状态，不直接调用外部副作用 |
| `KnowledgeSpaceFileChangeService` | 策略判断、跨聚合 UoW、冲突检查、gate 编排、列表 enrichment | 不直接写审批表，不复制 rename/move/delete 主体 |
| `KnowledgeSpaceFileChangeScenarioHandler` | 审批详情、动态审核人、终态 hook、批准后执行 | 不吞执行异常，不返回 HTTP response |
| `KnowledgeSpacePendingApproverReconciler` | 收集触发和调用 F025 原子动态分配 Service | 不直接写 Approval*，不扫描其他场景 |
| `KnowledgeSpaceMutationExecutor/ExecutionCoordinator` | 按 durable step 复用/续跑现有上传、重命名、移动、删除权威步骤，汇总 ack/读后校验并驱动 Deferred 完成、失败和补偿 | 不自行决定是否审批，不把“任务入队”伪装成下游完成 |
| `KnowledgeSpaceFilePublicationGuard` | 正式列表/OpenAPI/RAG/citation 的未发布 ID 批量门禁 | 不替代 ReBAC 权限，不复制解析状态 |
| `KnowledgeSpaceDeletionGuard` | 依据已 cutover delete request/footprint 批量排除尚未物理清理的文件、版本和子树残留；purge 失败时继续生效 | cutover 前不提前隐藏，cutover 后不因 execute_failed 放行残留，也不替代 durable purge |
| `ProductionMutationStepOwner/KnowledgeSpaceMutationTransitionGuard` | 从 durable manifest 执行 shadow、parent replace、正式检索提升/源清理并读后校验；cutover 未完成时在源/目标空间 fail closed | 不信任 broker manifest/task id，不复用 DB-first legacy rename/move，不承诺跨存储零不可用窗口 |
| F025 `ApprovalGate/ApprovalCenterService/ApprovalDynamicAssigneeService` | 原子 Gate bundle、task/instance decision、动态 task/exception 对账 | 不硬编码知识空间角色，不允许 F046 直接改 Approval* |
| client knowledge 页面 | 状态展示、禁用操作、待上传面板、逐项结果 | 不把本地状态当审批事实，不直接处理 403 |
| platform 知识空间配置 | 当前租户策略表单和单空间配置 | 不传 tenant_id，不缓存其他租户设置 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | ApprovalGate 去重包含 applicant_user_id，不能满足资源级互斥 | 两个编辑者可同时删除/移动同一文件 | `KnowledgeSpaceFileChangeService` 的空间锁 + footprint 活跃查询 |
| 2 | `approved` 不是完成，outbox 执行前资源仍未变更 | 提前解锁后第二个动作与执行任务竞态 | request repository 的 `RESOURCE_LOCK_BLOCKING_STATUSES` |
| 3 | 终态 hook 失败不会回滚审批终态 | 若清理只靠 hook，会泄漏 stage 或错误释放锁 | request cleanup checkpoint + Celery 补偿扫描 |
| 4 | `add_file()` 在解析前创建正式行，若 request 关联后写还会出现发布窗口 | 审批上传在解析完成前泄露名称，部分 chunk 还可能被召回 | `add_file_in_uow()` 同事务回填关联 + `KnowledgeSpaceFilePublicationGuard` 组合 children/search/F029/F030/citation |
| 5 | client `useFileUpload.ts` 删除是乐观移除 | pending 响应会让仍存在的文件从页面消失 | `useFileUpload` 按逐项 decision 决定移除 |
| 6 | 文件夹锁不是单资源唯一约束，版本 sibling 和目标祖先也可能冲突 | 父删除、子移动或版本删除可同时获批 | `KnowledgeSpaceFileChangeFootprintRepository` 的 resource/path 查询 |
| 7 | 文件夹上传当前先建目录再逐文件 add_file | 会提前创建正式目录，且审批顺序影响结果 | upload request 保存 `relative_path`；executor 幂等建缺失目录 |
| 8 | F034 move 先提交 DB，再写 FGA/标签/派发迁移 | 简单重试可能把已移动文件当源缺失并留下半状态 | durable execution step + coordinator 续跑/补偿 |
| 9 | workstation knowledge config 会继承 root | 子租户读到根租户开关 | 专属 policy repository，tenant 唯一、无 fallback |
| 10 | private 在 `Knowledge.auth_type`，部门身份来自绑定表 | 仅看 auth_type 无法禁止部门空间切私密 | `update_knowledge_space` + `DepartmentKnowledgeSpace` repository |
| 11 | 审核人关系会增删 | 旧用户仍持待办，新管理员无法一键处理 | F025 `ApprovalDynamicAssigneeService` + 动态 `can_approve` |
| 12 | stage 也占 MinIO/租户额度，且默认 policy 可能尚无行 | 首次并发上传无可锁记录并绕过容量 | `ensure_policy_row` 冲突重试 + policy 行锁 + stage bytes 预占/释放 |
| 13 | rename DB 更新与 chunk rebuild 入队是两步 | 名称已改但 outbox 重试再次改名，或索引仍是旧名 | rename checkpoint 观察目标名并幂等补派 rebuild |
| 14 | approval snapshot 会返回给申请人/审批人 | 放入 object path 会泄露内部存储 | upload stage 保存 object name；detail_snapshot 只放业务字段 |
| 15 | 现有 F025 repository 多次开 session/commit | “持有实例锁”仍可能半提交 task/instance/outbox | `ApprovalDecisionUnitOfWork` 一次提交 + post-commit effects |
| 16 | 现有 owner/manager resolver 在 FGA 故障时会降级，且只读 tuple 会漏掉 F044 永久创建者 owner | 故障可能被误判为无人审批；创建者 tuple 补偿期间也会错误进入 `approver_empty` | 文件变更 strict resolver 始终要求 FGA 可用并解析显式 owner/manager，再合并当前租户有效的数据库创建者；故障抛 18076，不改审批状态 |
| 17 | cancelled 历史 task 仍可让旧审批人在 F025 查看详情 | former manager 继续看到文件名和动作，违反 AC-14/23 | runtime handler `authorize_view` 接入 task/instance list/detail |
| 18 | 默认 policy 开启但既有租户未必有场景 | 首次编辑操作报 scenario disabled | `ensure_system_file_change_scenario` 四入口幂等 bootstrap |
| 19 | 当前 upload file_path 是短期 URL，原名仅短期缓存 | 长审批后不能预览/清理或名称退化 | `/knowledge/upload` 返回 opaque upload_id，元数据持久化 stage |
| 20 | `ApprovalCenterDialog` 处理后会切到 processed | 违反留在待处理并自动选下一条 | dialog decision success 分支留在 `pending_me` 并选择下一项 |
| 21 | 新 manager 尚无历史 task 时，先查 task 再过滤无法发现实例 | 权限已生效但审批中心长期无待办 | `discover_candidate_instances` 在列表/count/unread 查询前正向发现并对账 |
| 22 | Celery task id 仅表示已入队 | 下游失败但审批已显示 executed | F025 Deferred + F046 durable step/ack/读后校验 |
| 23 | 通用异常 assign/skip/人工完成可绕过固定 OR 审批人 | 非 owner/manager 可被临时指派或实例被人工完成 | handler `exception_action_policy` 服务端禁止旁路动作 |
| 24 | processing outbox 超 claim TTL 会被普通 worker 重领 | 长解析期间 handler 重跑并与原 steps 并发 | 专用 deferred 状态/heartbeat/deadline，普通 claim 排除，watchdog 独占超时迁移 |
| 25 | 现有 delete 先删 DB 再异步清外部数据 | instance 尚 executing 时资源先消失，失败也难恢复 | 零破坏 prepare + DB/guard cutover + 四类 durable purge 权威验证 + F025/request/guard 原子终态 |

---

## 6. 对外契约与依赖

### 6.1 Outgoing

| 契约 | 消费者 | 兼容风险 |
|---|---|---|
| `/knowledge/upload` 增加 opaque `upload_id`，files/folders-upload 改提交 upload_id | client uploader | 旧 file_path 注册协议与新客户端必须同版本迁移；object name 不上行/下行 |
| 现有文件/文件夹 mutation 响应增加 `decision` | client knowledge 页面 | 所有调用方需迁移，尤其删除不能再假定 200=已删除 |
| upload/folder-upload/move/batch-rename/batch-delete 逐项结果 | client 批量操作 | 旧客户端会忽略 pending/invalid，必须同版本发布 |
| 文件列表增加可选 `file_change_approval` | client table/card/tree | 字段按可见性裁剪，不能用于服务端授权 |
| 管理策略 API | platform 知识空间配置 | 只作用当前 tenant，不接受 tenant_id |
| 待审批上传/详情/预览/解析重试/批量通过 API | client | 客户端提交实例/变更申请 ID；服务端回到 F025 原子 decision，不直接改 task |
| `KnowledgeSpaceFilePublicationGuard` | F027/F029/F030/citation | 任一消费者漏组合都会泄露未发布文件；必须有跨入口合同测试 |
| `KnowledgeSpaceDeletionGuard` | F027/F029/F030/citation/preview | delete cutover 后所有读路径立即排除残留索引/对象；cutover 前不得过滤正式资源 |
| `KnowledgeSpaceFileChangeScenarioHandler` | ApprovalGate/outbox/runtime factory | handler key、snapshot 或动态 hook 变化会破坏存量实例重试 |
| F025 task/instance decision + dynamic discovery/visibility/Deferred hooks | Approval Center 和所有审批场景 | 必须保持 F045 邀请确认专用语义及未实现 hook、旧 Completed handler 场景行为不变 |

### 6.2 Incoming

| 依赖 | 风险点 |
|---|---|
| F025 ApprovalGate/Outbox/Decision UoW/异常服务 | 锁序、状态集合、post-commit 时机、Deferred token、exception policy 或 `approver_empty` 恢复语义变化会影响原子性、锁释放和任务对账 |
| F034 `move_items` | 移动请求/结果和跨空间执行语义必须保持一致 |
| KnowledgeSpaceService add/rename/delete | executor checkpoint 化不能改变无需审核直通路径的既有结果和副作用 |
| PermissionService/OpenFGA | 有效 owner/manager 严格解析依赖可用性；故障必须 fail-closed，不能降级授权 |
| MinIO upload object | stage 持久化 object name；bucket/key 或生命周期变化会影响预览、消费和清理 |
| F027 cursor list | enrichment 必须批量，不得恢复 total 或 fetch-all |
| F029/F030/citation | 未发布 ID 必须同时进入索引前置过滤、结果后置过滤和对外响应过滤 |
| DepartmentKnowledgeSpace binding | 部门空间私密校验依赖绑定完整性 |
| Celery default `celery` queue | F025 outbox、动态审批人对账、deferred watchdog、step coordinator/补偿/清理均走默认队列；不可用时实例保持 approved/executing/execute_failed，不得假成功，并告警最老待执行/待补偿时长；普通 claim 不领取 deferred |
| knowledge worker + 解析/索引链路 | upload 解析、全文索引、向量入库及跨空间迁移由 knowledge worker 完成，并以稳定 step key 回传或供 Beat 权威对账；worker 不可用时保持 parsing/executing，超时后明确 execute_failed |

版本级 `release-contract.md` 已登记 F046 拥有 policy/setting/upload stage/change request/footprint/execution step 六个领域对象和 INV-8 发布门禁；F034 仍拥有移动写行为，F025 仍拥有所有 Approval* 对象，F029/F030 仍拥有各自权限/对外读路径。

---

## 7. 测试与可观测

### 7.1 自动化策略

- **策略单元测试**：租户隔离、默认值、总控/scope/单空间优先级、私密免审、owner/manager 直通。
- **场景 bootstrap/锁定测试**：无 policy 的既有租户首次 mutation 可自动创建固定场景；重复 ensure 幂等；管理 API 不能 disable/delete/改 pass/AND/多节点。
- **upload stage/发布门禁测试**：upload_id 长期稳定、注册重试幂等、hash 变化重提、stage 配额并发预占；审批前无正式行，批准后 WAITING/PROCESSING 在 children/search/F030/RAG/citation 均不可见，申请人/当前审核人独立列表可见；SUCCESS 发布，FAILED 重试不重新审批。
- **冲突并发测试**：同资源不同申请人、不同动作；父子树双向竞争；版本 sibling；跨空间源/目标祖先；空间固定锁序；故障注入证明 request + ApprovalGate bundle 要么全提交要么全回滚。
- **Saga/Deferred 故障测试**：在 rename/move/delete/upload 的每个 DB/FGA/step dispatch/ack 边界注入失败；普通 claim 永不重领有效 deferred；心跳/超时 watchdog 与 resume 并发遵循实例锁；“仅入队”保持 executing；同代重复/旧代 token ack 幂等；resume 新 token 并联动恢复 instance/outbox/request/steps；重试不重复业务副作用。
- **删除 cutover/终态合同测试**：prepare 与 cutover 前任一步失败时资源在 children/search/RAG/citation/preview/download 均保持可用；DB deletion 与 deletion guard 要么同事务提交要么全回滚，且此时 F025 仍为 `EXECUTING/DEFERRED`；cutover 后即使 purge 未完成或失败，所有读路径也持续不可见。FGA/MinIO/ES/Milvus 各自必须有残留故障注入以证明读后验证会阻止成功；purge 失败进入 execute_failed 且 guard 不退役，新 token 只续跑未完成 step；四类全部 verified 后 F025/request terminal 与 guard footprint 退役同事务提交。
- **审批人对账测试**：严格 resolver 故障不生成 approver_empty；移除旧 manager 取消其 pending task且失去详情可见性；新增 owner/manager 在无历史 task 时由 list/count/unread 正向发现、补任务且只通知一次；重复/并发对账幂等；open exception 单例及恢复；F046 禁 assign/assign_flow/skip/mark-complete，retry 只恢复 strict 当前集合；task/instance decision、withdraw/cancel 与 Beat 并发遵循实例锁。
- **F025 原子回归**：普通 OR/AND、多节点、withdraw、exception、outbox 及 F045 `resource_user_invite_confirmation` 自确认/专属通知不退化。
- **Repository 双 DB 约束**：命名唯一键、`JsonType`、NULL、LIKE path escape、cursor、bulk tenant 条件和复合索引；MySQL 本地覆盖，DM8 由中央回归验证。
- **API E2E**：四类 mutation、普通/文件夹上传、batch rename/move/delete、拒绝/撤回/取消/执行失败、批量审批部分失败最新状态、跨租户不可见、部门空间禁止 private。
- **前端组件/E2E**：审批标签/动作详情/动态 `canApprove`、禁用菜单、逐项结果、解析状态/重试/清理、former approver 不可见、ApprovalCenter 留在 pending 并选择下一条、三语言。
- **回归**：无需审核/私密/owner-manager 直通与改造前结果一致；F027 cursor、F029/F030、F034 同/跨空间移动/版本链/文件夹上传、F044 权限配置和审批中心其他场景不退化。

### 7.2 手工验证主路径

环境启动后使用 Platform `http://localhost:3001/build/client` 的“知识空间”Tab 配置策略，Client `http://localhost:4001/workspace/knowledge/space/{spaceId}` 验证文件页；准备租户 A/B 各一个 tenant admin、owner、manager、editor 和普通成员账号，不在文档保存密码。后端聚焦测试命令：`cd src/backend && uv run pytest test/approval/ test/knowledge/ -k "file_change or dynamic_approver"`。

1. 租户 A 开启、租户 B 关闭，分别以 editor 上传同类型文件；A 仅出现在待审批上传，B 直接进入解析，且互不读取配置。
2. A 的 owner 批准上传，确认解析期间只在独立列表显示 parsing，正式列表/F030/RAG/citation 均不可见；解析成功才发布，失败显示原因且重试不重新审批。
3. editor 对文件重命名，确认列表保持旧名称并显示审批中；详情显示新名称；批准后才变更。
4. editor 移动文件夹，确认根文件夹及子树不可再次变更；批准后整树移动且只有一个实例。
5. editor 删除正式文件，确认普通用户仍可检索；批准且执行成功后才消失。
6. 先移除旧 manager、再新增 manager/转移 owner：确认旧 pending task 被取消但历史保留，新审批人无需重新发起申请即可在文件页看到 `canApprove` 并一键批量通过；模拟异步对账失败后，确认列表或审批前惰性对账可以修复。
7. 将普通空间改为 private 后新操作直通；确认部门空间切 private 被服务端拒绝。
8. 在 OpenFGA 不可用时尝试对账/审批，确认返回可重试错误且旧 manager 不会获批、实例不会误进 approver_empty；恢复后惰性对账自愈。
9. 从审批中心处理一条任务，确认仍停留待处理、自动选择下一条；移除 manager 后其历史 task 仍在审计时间线但详情不可见。

### 7.3 日志与指标

- 统一结构化日志字段：`tenant_id, space_id, change_request_id, approval_instance_id, action, resource_type, resource_id, decision, execution_step`；审批人对账额外记录 `trigger, added_user_ids, removed_user_ids`，禁止记录 object name、下载 URL 或用户敏感信息。
- 指标：创建申请/直通、按 action 审批结果、Gate/UoW 回滚、outbox/saga 步骤失败、资源锁冲突、unpublished count、staged bytes/count、临时清理失败和最长等待；补充对账成功/失败、按 trigger 新增/取消 task、`approver_empty` 和最老未对账时长。
- 上传沿用统一上传入口：以文件流写入临时 bucket，并保持已有 `file_path/repeat` 响应；知识空间调用同时登记 opaque stage。发起审批并绑定 stage 后，post-commit effect 使用稳定目标键把临时对象幂等复制到永久 bucket，成功后置 `attached`；失败保持 `attaching` 并由 Beat 补偿。未绑定对象始终只存在于临时 bucket，由其既有生命周期自动过期；应用只在确认临时对象已不存在后清理 stage 元数据与配额预占。
- 业务清理补偿任务只扫描已绑定的终态上传申请且 `cleanup_state != success`；用户显式清理或审批终态 cleanup 失败时抛出供 Celery 重试，不静默吞掉。

### 7.4 AC → 设计追踪

| AC | 设计落点 |
|---|---|
| AC-01～AC-11, AC-53 | §3 决策 2/12，§4.2.1，§4.3 policy/setting，§4.5.1，§4.7 |
| AC-12～AC-21 | §3 决策 3/11，§4.2.2，§4.3 upload stage/request，§4.5.2～4.5.3 |
| AC-22～AC-27 | §3 决策 4/6/9，§4.2.3，§4.5.2～4.5.3 |
| AC-28～AC-32 | §3 决策 6/8/9/12，§4.4，§4.8 |
| AC-33～AC-38 | §4.5.3，§4.6 Client，§6.1 |
| AC-39～AC-42 | §3 决策 10/12，§4.2.1，§4.7 |
| AC-43～AC-52 | §3 决策 4/6/7/10，§4.2.3，§4.5.2，§4.6 Client |

---

## 8. 后续改进 / 本期不做

- 本期不做目标空间接收方二次审批；若需要必须新增双阶段流程设计。
- 本期不做审批中的申请编辑；目标名称或目标位置变化需撤回后重提。
- 本期不把 file change lock 下沉为审批中心通用资源锁；其他场景出现同类需求后再抽象。
- 本期不处理历史私密部门空间的自动数据修复，只提供审计/修复脚本和部署前置说明。
- 临时 bucket 必须持续配置对象过期策略；发布前需验证未绑定对象按 bucket 生命周期自动过期、绑定申请会复制到永久 bucket 的稳定对象键，且应用 Beat 不承担未绑定 orphan 的物理删除。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-11 | 上传恢复统一流式临时桶流程；`attaching` 持久态表示申请绑定后待复制到永久桶，未绑定对象完全由临时桶生命周期清理 | 用户确认不需要应用管理 unbound tag，避免内存上传和重复生命周期管理 |
| 2026-08-10 | 补齐同事务上传发布关联、durable execution step + Deferred 完成协议、无历史 task 的动态候选发现、固定场景异常动作策略及首次配额锁 | 最终设计审查发现正式行泄漏窗口、异步假成功、漏事件后新管理员不可发现待办和通用异常旁路 |
| 2026-08-10 | 设计审查修正：编号迁移 F046、跨聚合/决策 UoW、strict resolver、历史任务可见性、opaque upload stage、解析发布门禁、mutation saga/footprint、固定场景 bootstrap 和完整批量契约 | 对照 release contract、spec、F025 与现有 Knowledge/F034 代码审查发现阻断问题 |
| 2026-08-10 | 增加动态审批人资格、三层任务对账、实例级批量审批和并发锁设计 | 空间 owner/manager 变化后新管理员需继续处理存量待审批变更 |
| 2026-08-10 | 初版：上传暂存、正式资源变更审批、子树互斥、租户策略和私密边界 | spec 确认后进入设计阶段 |
