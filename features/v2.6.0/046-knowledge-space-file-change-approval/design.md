# Design: 知识空间文件与文件夹变更审核

> **本文档定位 — 当前实现真相（Why this How）**
>
> - [spec.md](./spec.md) 定义产品范围与验收标准。
> - 本文定义 F047 解耦后的领域归属、审批接入、Knowledge saga、安全投影、失败恢复与发布方式。
> - F045/F046 尚未在生产上线；线上基线为 `v2.6.0`，本次停服直接升级，不保留 Gate/Deferred/runtime handler 开发实现兼容层。

**Feature ID**: F046

**场景编码**: `knowledge_space_file_change_request`

**版本**: v2.6.0

**最后更新**: 2026-08-13

**关联**: [spec.md](./spec.md) · [F047 解耦设计](../047-f046-approval-business-decoupling/design.md) · [release-contract.md](../release-contract.md)

---

## 1. 目标与非目标

### 1.1 目标

- 按租户保存文件变更审核总控和逐空间配置；私密空间免审，部门空间禁止设为私密。
- 编辑者的 upload/rename/move/delete 先形成 Knowledge 业务 request，经当前 owner/manager 单节点 OR 审批后，由 Knowledge 独立执行。
- 待审批上传不创建正式 `KnowledgeFile`；批准后文件在业务完成判据满足前仍受发布门禁保护。
- 正式资源变更在审批等待期保持原视图可用；执行通过 durable step、footprint、权威读后校验和补偿保证一致性。
- F025 只拥有审批事实和决定交付；Knowledge 拥有文件业务状态、token、step、watchdog、补偿、cleanup、重试和业务通知。
- 文件页独立展示 Knowledge 业务状态与 F025 审批状态；审批中心不展示业务 projection、outbox 或执行失败。

### 1.2 非目标

- 不改变 F044 权限设置入口、F045 个人邀请、频道内容审核或已废弃 `/approval/requests` 旧系统。
- 不允许租户修改 F046 固定审批流程；开关只由 F046 policy/setting 控制。
- 不把 ApprovalInstance、ApprovalOutbox、ApprovalException、Celery task ID 或审批 payload 作为文件执行事实。
- 不保留旧 `KnowledgeSpaceFileChangeScenarioHandler`、`ApprovalGate` 建单、Deferred token、runtime handler、F025 resume/complete/fail 或审批中心业务 projection。
- 不为未上线开发数据设计 backfill、双读、双写或新旧 worker 混跑。

---

## 2. 领域归属与关键约束

| Owner | 拥有 | 不拥有 |
|---|---|---|
| Knowledge | policy/setting、upload stage、file-change request、footprint、execution step、业务状态/token、mutation、发布门禁、补偿/清理/业务通知 | Approval ORM 和审批终态 |
| F025 Approval | 固定场景、instance/task、审批决定/日志/通知、动态 task 物化、`ApprovalDecisionOutbox` | Knowledge request/step、文件执行和业务状态投影 |
| Permission | owner/manager 变化后的对账触发；通过 Knowledge resolver 获取预解析候选，再调用 F025 application reconcile port | Knowledge request 和 Approval ORM |
| Composition root | 注册 Knowledge policy/subscriber 与 F025 registry，启动时校验后 freeze | 业务执行状态 |

硬约束：

- 权限校验先于策略判断，防止无权限用户借审批探测资源。
- owner/manager、私密空间或策略免审仍走原业务 owner 直接执行，不创建 F046 request/approval。
- 需要审核时，业务 request/stage/footprint 与审批 bundle 必须在 caller-owned UoW 一次提交/回滚；服务不 commit。
- 所有 tenant ContextVar、资源租户、审批绑定、business key、request fingerprint 必须相互一致；OpenFGA/resolver 故障 fail-closed。
- 跨域 broker 只携稳定 `tenant_id + request_id`，有 token 的 Knowledge 内部重投才携 execution token；worker 不解释 Approval payload。
- 业务执行、清理和补偿只写 Knowledge 表；任何业务失败都不改变 F025 的 approved/rejected/withdrawn/cancelled 终态。

---

## 3. 核心决策

### 决策 1：Knowledge request 是业务事实源

`KnowledgeSpaceFileChangeRequest` 保存不可变动作快照、审批绑定、业务状态、执行 generation 和结果 checkpoint。F025 只提供独立 `approval_status`；文件页不得从审批中心 detail/payload 推导业务状态。

### 决策 2：submission port 原子建单

需要审核时，`KnowledgeSpaceFileChangeService` 在 caller-owned UoW：

1. 校验权限、空间/策略、动作、目标、层级、循环、配额和冲突。
2. 锁定空间/资源，创建 request、stage 绑定和 footprint。
3. 生成 canonical `business_key/request_fingerprint`。
4. 解析当前 owner/manager 正整数 ID 集合。
5. 调用 `ApprovalSubmissionPort.submit_in_uow()` 创建 instance/task/log 并回填绑定。
6. 外层一次提交，随后执行审批待办通知和其他 post-commit effects。

F046 policy 拒绝 pass、多节点、AND、自定义审批人及空审批人；初始集合必须严格等于权威 owner/manager。

### 决策 3：决定事件只启动或关闭 Knowledge request

F025 最后节点 approve、reject、withdraw、cancel 或批量决定在终态 UoW 写唯一 `ApprovalDecisionOutbox`。`KnowledgeSpaceFileChangeDecisionSubscriber`：

- 只锁 Knowledge request，不 import Approval ORM/repository。
- 校验 tenant/instance/business type+ID/business key/fingerprint/event version 和事件顺序。
- `approved`：先提交 `queued + decision_event_id`，再由 Knowledge dispatcher 只派发 tenant/request；同事件可补派，成功后不重复。
- `rejected/withdrawn/cancelled`：先提交 `closed + decision_event_id`，再清理 stage/footprint；清理临时失败抛 retryable，同事件重投补清且成功后不重复。
- 绑定/乱序/协议错误 permanent；数据库、OpenFGA、broker 或 cleanup 暂时故障 retryable；F025 审批终态保持不变。

### 决策 4：动态资格由业务解析，F025 只物化待办

当前 owner/manager 是审批资格真相，ApprovalTask 是可对账的历史/待办物化：

- Permission 权限写成功事件、Knowledge 页面惰性检查和 Beat 补偿复用 `FileChangeApproverReconcileDispatcher`。
- Knowledge resolver 只返回 `instance_id + approver_user_ids`；F025 `reconcile_assignees(tenant_id, instance_id, ids, reason)` 在 instance 锁内取消失效 pending task、创建新增 task并维护 `approver_empty`。
- 历史 approved/rejected/cancelled task 永不复活；former approver 不因历史 task 获得详情可见性或决定资格。
- F025 普通列表/详情只查 Approval 表，不扫描 Knowledge；决定 UoW 在实例锁内调用已注册 policy 实时重读 owner/manager，故障 fail-closed，管理员不可绕过。

### 决策 5：durable saga 完全归 Knowledge

approved subscriber 只把 request 置 queued。之后由 `KnowledgeSpaceFileChangeExecutionCoordinator` 负责：

```text
queued → applying → applied
             └──→ failed → queue_retry(new token) → queued
             └──→ compensating → failed|applied(仅权威完整证据)
rejected|withdrawn|cancelled → closed
```

- 初次 coordinate 无 token，持 request 锁调用 `begin_execution()`；token 重投只加载当前 generation。
- durable step 的当前 token、依赖、状态、digest/idempotency key 和 read-after-verify 才是完成依据。
- dispatch/ACK、普通 dict、task ID、审批 approved 或 decision delivered 均不是业务成功证据。
- retry 按 action 恢复：delete 重新 token 化全部 step但保留已成功 step/digest，只把未成功 purge 置 pending；rename/move 重建相应 verify/cleanup 状态；旧 token 回调忽略。
- `finish_compensation(recovered=True)` 不能直接标 applied；必须通过 action-specific 权威完整判据，否则回滚完成后默认 failed。

---

## 4. 产品规则与数据流

### 4.1 策略判断

固定顺序：

```text
操作权限校验
  → 读取空间与部门绑定
  → 私密空间免审
  → 当前 owner/manager 直通
  → 读取租户 policy + 空间 setting
  → direct 或创建 F046 request
```

- policy 缺失默认：enabled=true、per-space、非私密空间默认需要审核。
- all-spaces 对所有非私密个人/集团/部门空间生效；per-space 保留逐空间设置。
- 关闭再开启保留空间设置；策略变化只影响新请求。
- F046 场景是系统只读场景，固定 enabled、catch-all flow、单 OR 节点、owner+manager sources；租户不能禁用、删除或改流程。

### 4.2 待审批上传

```text
multipart → KnowledgeSpaceUploadStage(upload_id)
  → request_change(upload)
  → caller-owned UoW 写 request/stage/footprint + Approval submission bundle
  → approval_status=pending, business_status=queued(内部 not_started 对外映射 queued)
  → approved event → Knowledge queued/applying
  → 正式文件图 + FGA 写入 + 普通解析调度成功接收
  → applied，随后解析按普通上传生命周期独立推进
```

- 审批前不创建正式 `KnowledgeFile`，不启动解析/索引/Embedding，不进入正式列表、搜索、RAG、citation、Knowledge Square 或 OpenAPI。
- stage 是 opaque upload ID；审批快照和 broker 不暴露 MinIO object name/path。
- 申请人和当前有效 owner/manager 可看待审批列表、详情和预览；其他用户不可见文件名/内容。
- approved 业务完成判据是正式文件图提交、OpenFGA 权威写入和普通解析调度成功接收，不等待完整解析；后续解析失败不回退审批终态或 Knowledge request applied。
- 从未绑定的临时对象依赖临时桶生命周期过期；Beat 只在确认对象已不存在后把 stage 标 cleaned，不主动误删可能仍在上传的对象。
- rejected/withdrawn/cancelled 进入 closed 并清 stage；failed 可以清理或按原 request 重试，不创建新审批。

### 4.3 rename / move

等待审批时不修改正式资源。saga 使用 request-owned manifest/step/footprint，不调用依赖 Approval payload 的执行入口：

```text
prepare immutable manifest
  → shadow build/verify
  → 激活 OLD_VIEW transition footprint
  → move 建新 parent 且保留旧 parent，权威校验
  → 同一 UoW 完成 DB cutover + NEW_VIEW
  → durable post-cutover cleanup
  → 权威 verify 后 applied，退役 footprint
```

- OLD_VIEW 始终以旧名称/旧位置和源空间权限展示；NEW_VIEW 同时切换名称/位置与目标权限。
- cleanup 崩溃时 NEW_VIEW 投影继续保证新名称/新位置可见且旧视图不可见；Beat 用稳定 token 恢复 cleanup。
- 跨空间移动按源空间策略与 owner/manager 审批；创建和执行时均校验源 move、目标 upload、租户、层级、循环、重名和目标存在。
- move 覆盖完整版本链并同步处理标签/parent/FGA/检索视图；不能只迁移当前版本。

### 4.4 delete

delete 把逻辑 cutover 与外部 purge 分离：

```text
prepare manifest/steps（零破坏）
  → 权威校验资源仍可用
  → 同一 Knowledge UoW 删除正式 DB 行 + 激活 deletion guard
  → FGA / MinIO / ES / Milvus durable purge + 各自读后验证
  → 全部当前 token step verified
  → request=applied + 退役 guard/footprint
```

- prepare/cutover 前失败：资源在 children/search/RAG/citation/preview/download 全部保持可用。
- cutover 后：DB 与 deletion guard 同时使所有读路径不可见，外部残留不得泄漏；purge 失败时 guard 持续生效。
- retry 为所有 step 换新 token，已成功 step 保留状态/digest且不重做，只恢复未成功 purge。
- 只有 phase=completed、guard 已释放且 required steps 均属于当前 token并权威成功，才可判定 applied。

### 4.5 文件夹、子树与冲突

- 文件夹动作一条根 request 覆盖整棵子树；列表只展示根申请，子项通过 inherited lock 禁止冲突操作，不伪造独立审批。
- 文件夹上传按文件建立申请并保存 relative path；批准后幂等创建目录，同批审批顺序不影响目录结构。
- footprint 用正式列保存 exact/subtree/destination、资源 ID、路径根、版本 sibling、源/目标空间和祖先；禁止在 JSON 上做冲突过滤。
- request/footprint 业务状态决定占用；不查询 ApprovalInstance 状态推进执行。active request 的重叠动作返回明确冲突且不创建第二审批。
- 锁序固定为 Knowledge request/footprint/step 约定，不与 Approval 表形成交叉锁；API、worker、watchdog、补偿使用相同顺序。

---

## 5. 数据模型与公开状态

### 5.1 Knowledge 表

| 模型 | 关键职责 |
|---|---|
| `knowledge_space_file_change_policy` | tenant 总开关与 all-spaces/per-space scope |
| `knowledge_space_file_change_setting` | 单空间 approval_required，保留关闭期间配置 |
| `knowledge_space_upload_stage` | opaque 上传对象、配额预占、绑定与 cleanup lifecycle |
| `knowledge_space_file_change_request` | canonical business key/fingerprint、动作快照、审批绑定、决定事件、业务状态/token/result/cleanup checkpoint |
| `knowledge_space_file_change_footprint` | exact/subtree/destination 冲突、transition/deletion guard |
| `knowledge_space_file_change_execution_step` | durable step、当前 generation、idempotency key、状态、digest、attempt/补偿游标 |

`business_key` 和 `request_fingerprint` 非空且无空默认；`decision_event_id` tenant 内唯一。绑定安全字段必须是正式列，不藏在 JSON。`result_snapshot` 只保存业务结果/dispatch/cleanup checkpoint，不复制审批 payload。

### 5.2 状态分离

Knowledge 对外业务状态只有：

```text
queued | applying | applied | failed | compensating | closed
```

- 内部 `not_started`（审批未决定）在 API 映射为 `queued`，同时独立返回 `approval_status=pending`。
- 合法组合包括 `queued+pending`、`queued+approved`、`applying+approved`、`failed+approved`、`closed+rejected|withdrawn|cancelled`。
- 文件页列表/详情展示 `status` 与 `approval_status` 两个字段；仅 `failed+approved` 可按原 request 重试。
- 审批中心只展示 `pending/approved/rejected/withdrawn/cancelled/exception` 与安全快照，不展示 Knowledge status、failure、step、token、projection 或 retry。

---

## 6. API、前端与通知

### 6.1 Knowledge API

```text
GET/PUT /knowledge/space/admin/file-change-policy
GET/PUT /knowledge/space/admin/file-change-settings[/<space_id>]
PUT     /knowledge/space/admin/file-change-configuration
GET     /knowledge/space/<space_id>/file-changes/uploads
GET     /knowledge/space/<space_id>/file-changes/<request_id>
GET     /knowledge/space/<space_id>/file-changes/<request_id>/preview
POST    /knowledge/space/<space_id>/file-changes/<request_id>/decision
POST    /knowledge/space/<space_id>/file-changes/<request_id>/retry-ingest
DELETE  /knowledge/space/<space_id>/file-changes/<request_id>
POST    /knowledge/space/<space_id>/file-changes/batch-approve
```

- 单条/批量决定委托 F025 public instance decision port；endpoint 不写 Approval ORM。
- list/detail/status/retry/cleanup/compensation 只调 Knowledge application/coordinator。
- retry 参数是业务 request ID；不接受 outbox ID、ApprovalException ID 或 execution token。

### 6.2 Client

- 文件页展示六个 Knowledge 业务状态，并单独展示 approval status；`failed` 才显示原 request retry。
- `queued+pending` 与 `queued+approved` 文案不同；审批 approved 不伪装 applied，业务 failed 不伪装审批 exception。
- F046 决定后统一 refresh event 刷新待审批列表、打开详情和正式文件列表。
- 审批中心只渲染安全业务快照和审批流程；不读取 `business_status_projection/outbox/token/ApprovalException`。

### 6.3 通知

- F025：初始/动态待办、approve/reject/withdraw/cancel 审批通知，仅表达审批事实。
- Knowledge：业务 applied/failed 通知，在业务状态提交后发送并以 request/generation checkpoint 去重；失败可重试，不回写 Approval。
- 对账新增 task 只通知新增审批人；首次 approver_empty 通知租户管理员且同一 open exception 不重复。

---

## 7. Celery 与恢复

所有 F046 执行/ack/watchdog/补偿/cleanup/动态审批人任务位于：

```text
bisheng.worker.knowledge.file_change_tasks.*
```

任务声明和 Celery route 均固定 `knowledge_celery`；F025 decision delivery 保持默认队列。Beat 注册四个无业务参数 coordinator：动态审批人对账、执行 watchdog、step recovery/compensation、stage/residue/delete cleanup。

- 跨租户 coordinator 仅在 `bypass_tenant_filter()` 枚举 active tenant，再以显式正整数 tenant header 逐租户派发。
- tenant task 设置 ContextVar 并在 finally 恢复；bool、0、负数或缺 header fail-closed。
- 逐租户查询使用 `(update_time,id)` 或 ID keyset 有界分页；raw page 即使过滤为空也用 raw last row 前进。
- 单租户、单空间、单 request 或 broker 失败隔离；任务指数 backoff；任务 ID 不作成功证据。
- 动态审批人 worker 调 Permission dispatcher/Knowledge resolver，不构造 runtime handler。

---

## 8. 代码锚点

| 文件 | 职责 |
|---|---|
| `knowledge/domain/services/knowledge_space_file_change_service.py` | 权限/策略/冲突校验、caller-owned request/stage/footprint/submission UoW |
| `knowledge/domain/services/knowledge_space_file_change_uow.py` | 单事务与 post-commit effects |
| `knowledge/domain/services/knowledge_space_file_change_approval_policy.py` | 初始严格 owner/manager 与决定实时资格/绑定校验 |
| `knowledge/domain/services/knowledge_space_file_change_decision_subscriber.py` | 幂等接收事件、queued/closed、补派/补清 |
| `knowledge/domain/services/knowledge_space_file_change_approver_resolver.py` | 权威 owner/manager ID 与 reconciliation target DTO |
| `permission/domain/services/file_change_approver_reconcile_dispatcher.py` | 权限事件/Beat/页面惰性对账编排 |
| `approval/domain/services/approval_dynamic_assignee_service.py` | 接收预解析 IDs，在 instance 锁内维护 task/approver_empty |
| `knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py` | generation/step/retry/补偿/完成判据 |
| `knowledge/domain/services/knowledge_space_mutation_executor.py` | request/token/step 驱动的 rename/move/delete owner 编排 |
| `knowledge/domain/services/knowledge_space_file_change_compensation_service.py` | 纯 Knowledge watchdog/step/cleanup keyset 查询 |
| `knowledge/domain/services/knowledge_space_file_change_terminal_cleanup_service.py` | reject/withdraw/cancel/failed upload 稳定清理 owner |
| `worker/knowledge/file_change_tasks.py` | Knowledge-owned worker、dispatcher、tenant header 与 `knowledge_celery` |
| `knowledge/domain/services/knowledge_space_file_change_application_service.py` | Knowledge list/detail/retry/cleanup 与 Approval status port 组合 |

Knowledge 包不 import Approval ORM/repository；F025 不 import Knowledge Service/ORM。旧 scenario handler、Approval Deferred UoW 和 approval worker F046 task 不存在。

---

## 9. 安全与测试门禁

- Policy/subscriber：tenant/instance/business key/fingerprint/version/order、OpenFGA故障、former approver、管理员旁路、同事件补派/补清。
- Submission：request/stage/footprint/approval bundle 同提交/同回滚，canonical key/fingerprint 非空，pass/空审批人拒绝。
- Saga：四动作每个 DB/FGA/MinIO/ES/Milvus/dispatch/ACK 崩溃点、旧 token、重复 task、权威读后校验、action-specific retry/compensation。
- Delete：prepare/cutover 原子性、guard 全读路径、四类 purge 残留、成功 step 保留、全部 current token verified 才 applied。
- Projection：rename/move OLD_VIEW/NEW_VIEW、版本链、目标权限、cleanup 崩溃、citation/preview/download/RAG 一致。
- Query/API：六词业务状态与 approval status 分离，failed 原 request retry，不读 Approval payload/outbox/exception。
- Worker：所有 F046 task/Beat/route 在 Knowledge+`knowledge_celery`，tenant header/ContextVar/keyset/失败隔离；decision delivery 默认队列。
- 回归：三个已上线 legacy approval outbox 场景、普通上传/解析、F027/F029/F030/F034、私密/部门空间与多租户边界。

---

## 10. 发布与兼容性

生产基线 `v2.6.0` 未上线 F045/F046，也没有对应数据。采用停服直接升级：

1. 停止 API、default/knowledge/permission workers 和 Beat，禁止旧消息继续处理。
2. 发布前只读检查 F045/F046 scenario 的 Approval 数据、新业务表和相关 broker 消息为零；非零则阻止发布并清理非生产开发数据。
3. 直接使用重写后的未发布 F046 migration：正式列/索引按当前模型创建，不 backfill、不保留 Deferred 列或旧状态。
4. 启动新 API/worker，验证 bootstrap、decision delivery 默认队列、全部 F046 task 的 `knowledge_celery` route 和 Beat 字符串，再开放流量。

不兼容旧 ApprovalGate bundle、Deferred outbox/token、runtime handler、旧 approval worker task、旧混合状态 API 或新旧 worker 混跑。菜单、频道订阅、知识空间加入三个已上线场景继续使用原 `approval_outbox → handler` 机制。

---

## 11. 变更历史

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-08-10 | 初版以 ApprovalGate/ApprovalOutbox/Deferred/runtime handler 驱动文件业务 | F046 初始设计 |
| 2026-08-13 | 全文改为 Knowledge request + submission/policy/subscriber + Knowledge saga/worker；纯 Knowledge 状态/API，删除 F025 业务 projection/Deferred 口径 | F047 解耦设计确认，F046 尚未上线且停服零兼容发布 |
