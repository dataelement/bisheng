# Design: F071 知识空间问答与目录解耦、历史对话按空间保留

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 定义做什么和验收边界。
> - 本文定义为什么采用 `MessageSession.entry_flow_id` 作为展示入口覆盖、删除/清空/移动如何触发回收、存量数据与并发如何处理。
> - `tasks.md` 在 Design ★ 确认后创建，记录实施顺序与实际偏差。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [release-contract.md](../release-contract.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-18
**状态**: ✅ best-effort 异步收敛及 `clear_space` 范围方案已于 2026-09-18 确认；`tasks.md` 已生成

---

## 1. 目标与非目标

- **目标**：在不改写既有会话和消息 `flow_id` 的前提下，为知识空间问答会话增加可变的展示入口；资源删除、清空知识空间内容或跨空间移出后，以定向异步任务 best-effort 回收到原空间根目录，正常收敛后历史可见且可按全空间范围继续问答。
- **非目标**：不新建会话作用域表或在线回收 outbox，不重写通用会话体系，不移动或复制消息，不把历史带到目标空间，不恢复用户删除内容，不改变其它会话类型，也不为低概率并发/派发故障引入分布式锁、会话创建复查或全量巡检。

---

## 2. 关键约束与 Constitution Check

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C8；知识域 Service 负责编排，新增 `KnowledgeChatSessionRepository` 负责 F071 会话查询与批量更新，资源授权仍只经 F048；不为新功能扩展 legacy `MessageSessionDao` entry point。
- 遵守版本契约 **INV-36**：原空间、本人会话、根目录回收、可继续问答、幂等、存量恢复、同空间不触发和回收后不回绑同时成立。
- `message_session.flow_id` 与 `chat_message.flow_id` 是已有内容链标识，多个会话类型和历史查询都依赖二者相等；F071 不改写它们。
- `MessageSession.update_time` 当前不是“最后一条消息时间”：知识空间写入/删除消息不会 touch session，知识空间会话列表固定按 `create_time` 排序；更新 `entry_flow_id` 会按 MySQL/DM8 既有机制刷新 session `update_time`，这是会话元数据变化，不影响消息时间、消息顺序或当前列表顺序。
- `MessageSession.tenant_id` 是用户叶子租户，不等于资源拥有租户；列表继续按 session tenant/owner 过滤，空间可见性由业务权限校验决定。
- 文件/文件夹删除是硬删除，跨空间移动保留资源 ID 但修改 `knowledge_id`；存量恢复依赖旧 `flow_id` 解析原空间和原资源类型/ID。
- 同一文件夹可有多个会话，同一文件当前通常复用一个会话；不得假定 `(space, entry)` 唯一，会话唯一键始终是 `chat_id`。
- Alembic 只增加 nullable 列和索引；存量识别/回填由 `src/backend/scripts/` 独立执行，默认 dry-run。
- F071 不新增对外 URL、响应字段、错误码段或领域表；存量入口不可判定时失败关闭并记录结构化错误。
- 在线删除、`clear_space` 与跨空间移动的会话入口回收采用 best-effort 异步收敛：资源操作不等待任务完成，派发失败也不改变资源结果；允许短暂或在派发/执行故障后持续无展示入口。任务只处理本次操作冻结的 flow 集合，不建设 durable outbox，也不周期扫描全量知识空间会话。
- 知识空间会话创建、既有重命名和消息生成链路保持原样，不增加锁、资源二次校验或回收状态感知。

### Constitution Check

| 条款 | 结论 | 设计落实 |
|---|---|---|
| C1 分层 | 通过 | endpoint/worker → Service → `KnowledgeChatSessionRepository` → DB；Service 不直接写 ORM，不扩展 legacy DAO |
| C2 双 DB | 通过 | nullable `VARCHAR` 列、标准索引和 set-based UPDATE；MySQL/DM8 均验证 |
| C3 多租户 | 通过 | 在线列表走 tenant-aware 模型；资源回收是对所有会话所有者的受控系统 fan-out，Repository 仅消费资源操作冻结的精确 flow 集合，并以知识空间 flow type、活动状态和 null entry 限定更新；迁移逐租户处理 |
| C4 权限 | 通过 | 根入口先校验原空间，普通目录/文件入口继续校验具体资源；`entry_flow_id` 不产生 ALLOW |
| C5 错误码 | 通过 | 不新增错误码，复用知识空间/会话既有错误与通用服务错误 |
| C6 密钥 | 不涉及 | 脚本报告不输出配置密码或消息内容 |
| C7 前端 store | 通过 | 前端仍经 `chatApi.ts`，不新增 store HTTP |
| C8 多节点 | 通过 | `message_session.entry_flow_id` 是 DB 中的唯一入口覆盖；定向任务经共享队列执行，不以 React 内存、节点本地文件或进程缓存判定归属 |

---

## 3. 方案对比与选定

### 决策 1：用会话字段覆盖展示入口，不新增投影表

- **备选**：
  - A. 删除/清空/移动时把 `message_session`、`chat_message` 和 `message_citation` 的 `flow_id` 全部改为根目录——需要跨三张表一致更新，并与生成中的迟到消息竞态。
  - B. 新增 `knowledge_chat_scope` 表——结构化能力最完整，但当前只需要决定展示入口，会增加表、join、双写、完整性校验和迁移面。
  - C. 在 `message_session` 增加 nullable `entry_flow_id`；null 表示入口沿用 `flow_id`，回收时只写根目录 flow ID。
- **选定**：C。`flow_id` 是内容链标识，`entry_flow_id` 是可见入口覆盖；两者职责严格分开。
- **原因**：当前业务只需要“入口是否仍跟随原 flow，还是固定到原空间根目录”这一位状态。原空间和原资源仍能从不可变 `flow_id` 得到，无需为恢复原因、时间等非当前需求字段建表。
- **何时该重新考虑**：只有产品要求多种独立作用域、展示恢复来源、全局历史或复杂入口生命周期时，才升级为结构化 SessionScope 表；当前不提前设计。

### 决策 2：入口查询使用显式覆盖语义

- **有效入口**：`effective_entry_flow_id = entry_flow_id if entry_flow_id is not null else flow_id`。
- **选定**：知识空间列表和会话打开先按 effective entry 验证位置；消息历史和持久化始终使用真实 `session.flow_id`。
- **查询形态**：避免 `COALESCE` 让索引整体失效，Repository 使用两个互斥分支合并并统一按 `create_time DESC` 排序：

```sql
entry_flow_id = :target
OR (entry_flow_id IS NULL AND flow_id = :target)
```

- **原因**：原生根目录会话命中第二分支，回收会话命中第一分支；一个 chat 只会命中一支，不会重复。
- **何时该重新考虑**：若数据量和双方言执行计划证明 OR 无法稳定使用索引，可改为两个索引查询 `UNION ALL` 后外层分页；语义不变。

### 决策 3：资源 DB 变更提交后 best-effort 定向回收

- **备选**：
  - A. 删除/清空/移动与会话入口处于同一事务或以分布式锁阻断新会话——一致性强，但扩大正常业务链路、增加长事务或大子树锁成本。
  - B. 周期任务全量扫描所有知识空间会话——无需传递影响集合，但绝大多数行无需修复，扫描成本与历史总量线性增长。
  - C. 复用资源操作已计算的受影响资源集合，在对应资源 DB 变更提交后按 flow 分片尝试投递短延时回收任务。
- **选定**：C。删除、清空空间内容和跨空间移动不等待会话回收；文件/目录硬删除的触发点是该次 `KnowledgeFileDao.adelete_batch(...)` 提交返回后，`clear_space` 的触发点是 `KnowledgeDao.async_delete_knowledge(..., only_clear=True)` 提交返回后，跨空间移动的触发点是 `move_items` 元数据 `session.commit()` 返回后。F071 只固定自身派发点，不重排既有文件清理、channel binding 清理、空间更新时间、权限或检索迁移动作；`clear_space` 派发位于既有空索引重建之前，跨空间移动派发仍位于既有 post-commit 权限与检索迁移之前。
- **执行方式**：派发在隔离的 `try/except` 中 best-effort 执行，失败只记录日志，不改变资源操作结果。F071 沿用平台现有 Celery 发布配置，本期不单独增加 broker 发布超时、发布重试强约束或可用性门禁。成功入队的任务默认短延时 5 秒，以覆盖“资源校验完成、会话稍后提交”的常见竞态；flow 默认每 500 个一批，执行索引驱动的幂等 set-based UPDATE，不读取或更新 `chatmessage/message_citation`。任务使用 `acks_late` 和有界重试提高已入队任务的成功率；不启动全量定时巡检。
- **失败方向**：本期不建设 durable operation/outbox，不承诺资源提交与 Celery 入队原子，也不承诺派发失败或 worker 终态失败一定自动恢复。失败不回滚、不中断已提交的资源删除、清空或移动；会话和消息仍在原内容链，但入口可能持续不可见。能捕获的派发/执行失败记录 source space、reason 和精确 flow chunk，供人工重试或受控运行迁移脚本；进程在提交后、记录/入队前退出仍属于已接受的 best-effort 缺口。
- **原因**：并发创建窗口很短且现状已存在竞态，业务接受 best-effort 异步收敛；定向延时任务不修改会话创建链路，也不让上万文件的目录产生上万把锁或全库扫描。
- **何时该重新考虑**：若线上持续失联超过可接受水平、回收 SLA 成为产品承诺，或 best-effort 缺口无法通过运维修复，再引入 durable operation/outbox 或更强一致性，不预先改造正常问答链路。

### 决策 4：接受并发残余窗口，生成继续写原内容链

- **选定**：删除、清空和移动不取消在途生成，也不为 F071 修改新建会话。迟到消息继续写原 `chat_id/flow_id`；延时任务执行时已提交且命中受影响 flow 的 session 会被回收到 root，任务扫描之后才提交的极低概率 session 允许保留现状竞态并进入运维修复范围。
- **原因**：知识空间 session 在 RAG 生成前创建，常见迟到写入可由短延时覆盖；消息写入不会更新 session，首次标题生成使用字段级 UPDATE，不会清空 `entry_flow_id`。用 best-effort 收敛换取不增加创建校验、分布式锁和跨业务事务。
- **额外约束**：已回收资源日后移回原空间时，单文件会话查找不得只按原 `flow_id` 复用 recovered session；必须要求 effective entry 仍等于当前文件入口，否则创建新会话。
- **何时该重新考虑**：若产品要求删除资源立即终止相关回答，需要独立内容治理 Feature 明确终止和历史裁剪语义。

### 决策 5：存量只更新真正失联的活动会话

- **备选**：Alembic 全量 backfill、运行时懒修复、独立脚本识别失联会话。
- **选定**：Alembic 只加 nullable 字段；独立 DB-only 脚本扫描知识空间 session，仅对“原资源不存在或已属于其它空间”的活动会话写 root `entry_flow_id`。正常 root/folder/file 会话保持 null。
- **原因**：nullable override 让正常存量天然兼容，无需更新每一条 `message_session`，减少锁和 `update_time` 刷新范围；同时一次性恢复未访问用户的失联历史。
- **何时该重新考虑**：若实测数据量超过维护窗口，脚本可带 checkpoint 分批执行；仍须保留 checksum、幂等和启用门禁。

### 决策 6：前端不新增视图或归属状态

- **选定**：复用现有根目录会话列表、历史面板和输入框；后端返回既有 `FolderSession`，内部 `entry_flow_id` 不进入响应。
- **原因**：现有 `useFolderChat` 已按 space/folder 重新加载；前端只需在删除、清空或跨空间移动成功后刷新源空间根会话列表，不保存入口真相。
- **何时该重新考虑**：产品后续要求显示“来自已删除目录”或全局历史时，再新增只读展示合同；当前不暴露内部字段。

---

## 4. 系统现状与目标结构（接手必读）

### 4.1 当前基线

- folder flow 为 `space_{space_id}_folder_{folder_id}`，根目录固定 `folder_0`；单文件 flow 为 `space_{space_id}_file_{file_id}`。
- `get_chat_folder_session/history/chat_folder` 和 `single_file_history` 先校验当前空间/资源，再精确匹配 `flow_id`；资源硬删除或 `knowledge_id` 改到目标空间后入口失配。
- `ChatSessionService.get_chat_history` 同时要求 session.flow_id 和 message.flow_id 相等，因此不能用根目录 flow 替换内容链 flow。
- 知识空间消息新增、清空不会调用 `MessageSessionDao.touch_session`；首次生成标题会调用 `update_session_name`。知识空间会话 DAO 按 `create_time DESC` 排序。
- `delete_folder`/`batch_delete` 不处理会话；`move_items` 跨空间会修改整棵子树和版本链的 `knowledge_id`。
- `useFolderChat(spaceId, folderId)` 本地只记忆当前选择，不能作为恢复真相。

### 4.2 `MessageSession` 增量字段

不新增表。在既有 `message_session` 增加：

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `entry_flow_id` | `VARCHAR(255) NULL` | 知识空间会话的展示入口覆盖；null 表示沿用 `flow_id`，非空时本期只能是该会话原空间的 `space_{space_id}_folder_0` |

索引：新增 `idx_message_session_entry_flow_id(entry_flow_id)`；保留既有 `flow_id`、`user_id`、`tenant_id` 和 `create_time` 索引。实施时以 MySQL/DM8 的列表执行计划决定是否需要包含 tenant/user/flow_type 的复合索引，不预设超宽索引。

字段不进入 `FolderSession` 或其它公共响应；若当前 endpoint 直接序列化 ORM，必须改用显式响应 schema/字段选择，避免扩展既有 API。

状态约束：

- 只有 `FlowType.KNOLEDGE_SPACE` 可以写 `entry_flow_id`；其它会话类型必须保持 null。
- 普通 root/folder/file 会话保持 null；本期非空值只表示 recovered root。
- `entry_flow_id` 中的 space 必须与原 `flow_id` 中的 space 相同，目标空间不得写入。
- 已有非空入口后，删除、重复移动或资源移回不得清空/覆盖，保证 sticky 和幂等。
- 完整删除知识空间沿用现状，不清理旧 session 或已有 `entry_flow_id`；此前已排队的 best-effort 任务即使在空间删除后执行，也允许留下指向已删除空间的失效入口元数据。空间权限/存在性校验保证该入口不可访问。
- 写入口可以刷新 `MessageSession.update_time`；不得修改 `create_time`、原 `flow_id`、消息/引用内容及其时间。

### 4.3 在线数据流

#### 新建和查找会话

- 新建知识空间会话仍只写原 `flow_id`，`entry_flow_id=NULL`，不增加双写。
- 会话创建、资源校验和提交顺序保持现状，不感知回收任务，不增加分布式锁或创建后的资源复查。
- 文件夹列表按 effective entry 过滤，可保留多个会话。
- 单文件“查找或新建”必须按 effective entry 查找：已回收到 root 的旧 session 不得因资源同 ID 移回而被复用。

#### 列表、历史与继续问答

1. endpoint 仍接收 `space_id + folder_id/file_id + chat_id`。
2. Service 校验当前用户对 space 的访问；非 root 再校验具体 folder/file。
3. Repository 按 effective entry 查询 `MessageSession`，同时过滤 tenant、`user_id`、知识空间 flow type 与 `is_delete=false`，按既有 `create_time DESC` 排序。
4. 打开具体会话时先验证 chat_id 属于请求入口，再把数据库中的真实 `session.flow_id` 传给 `ChatSessionService.get_chat_history`；不信任客户端 flow_id。
5. 从 recovered root 继续问答时使用原空间全量可见文件构建 retriever；消息仍写原 `session.flow_id`。

`chat_id` 是客户端输入，读取历史或写入本轮问题前必须完成以下校验，不允许“只按 chat_id 找到 session 就继续”：

```text
requested_entry = flow generated from request space_id + folder_id/file_id
session = session matched by chat_id + tenant + owner + knowledge-space flow type + is_delete=false
effective_entry = session.entry_flow_id or session.flow_id

require effective_entry == requested_entry
content_flow = session.flow_id
retrieval_scope = whole source space when requested_entry is source root
```

| 请求与会话状态 | 结果 | 历史/消息 flow | 检索范围 |
|---|---|---|---|
| 原生根会话：`entry_flow_id=NULL`，从同一空间 root 请求 | 允许 | 原 root `flow_id` | 原空间全量可见文件 |
| 普通旧目录/文件会话：`entry_flow_id=NULL`，伪装成 root 请求 | 拒绝；不得读取或新增消息 | 不执行 | 不执行 |
| 已回收会话：`entry_flow_id=原空间 root`，从该 root 请求 | 允许 | 保持旧 folder/file `flow_id` | 原空间全量可见文件 |
| 已回收会话从旧 folder/file 入口请求 | 拒绝；不得重新绑定 | 不执行 | 不执行 |
| chat 属于其他空间、其他用户、已删除或非知识空间 flow type | 拒绝 | 不执行 | 不执行 |

因此 recovered chat 在展示意义上已经属于 root，但内容链仍属于原 `flow_id`；入口归属、消息归属和检索范围分别由 effective entry、session flow、当前合法入口决定，不能混用。

#### 删除

1. `batch_delete` 在执行任何删除前规范化服务端输入：folder/file ID 各自去重；若选中父文件夹，则从顶层 folder/file 输入中移除已被该父文件夹子树覆盖的后代；随后沿用既有逐项授权。这样父子重复输入不会在父项硬删除后再次查询已消失的子项。
2. `delete_folder/delete_file` 复用既有子树枚举和版本链扩展结果；在对应 `KnowledgeFileDao.adelete_batch(...)` 前，把该删除单元实际影响的 folder/file ID 冻结为原空间 flow 集合。既有权限 tuple 清理和硬删除顺序保持不变，不把全部批量操作合并成长事务。
3. 每次 `adelete_batch(...)` 成功提交返回后，立即将该删除单元的 flow 集合去重、分片并 best-effort 投递延时任务；F071 不调整既有清理动作的相对顺序——原本在硬删除 commit 前执行或投递的动作仍在前，原本在 commit 后执行的动作仍在后。F071 自身不等待 commit 后剩余的 channel binding 清理、空间更新时间或整个 batch 全部结束；后续步骤失败时，已经提交的删除单元仍保留其派发结果。
4. worker 调用 retention service，以受控跨租户 fan-out 更新这些 flow 下所有会话所有者的活动 session，而不是只处理当前操作者；已回收行保持不变。
5. 任务重复投递因 `entry_flow_id IS NULL` 保持幂等；派发或执行失败不改变删除结果，并按 best-effort 边界允许会话持续失联。

#### 移动

1. `move_items` 完成 valid/invalid 筛选后，只处理实际移动的 valid rows。
2. 同空间移动不更新会话入口。
3. 跨空间移动在既有 DB transaction 中继续只更新资源、版本和文档元数据；在提交前从 source space 与本次 valid item 的直接 move rows（item 本身及目录后代）冻结原 flow ID 集合。当前可见主版本文件必然位于直接 move rows 内，其单文件会话正常回收。
4. `session.commit()` 返回后、执行 FGA parent tuple、tag 和检索数据迁移前，分片 best-effort 投递延时回收任务；后续副作用失败不撤销已经提交的资源变更或已完成的任务派发。
5. `_collect_version_chain_file_ids` 额外带出的、但不在直接 move rows 内的 sibling file 不纳入本期在线 flow 集合；它们通常是当前列表隐藏的非主版本，其旧 file_id 会话可能继续失联。这不影响当前可见文件问答，属于已接受的历史残余范围。

#### 清空知识空间内容

1. `clear_space` 继续使用其在清理前已取得的 `child_resources`；按资源类型将其中全部 folder/file ID 冻结为该空间的 flow 集合，不额外扫描会话或在资源删除后反查子树。
2. 既有 child permission projection、向量/ES/MinIO 清理和 `KnowledgeDao.async_delete_knowledge(..., only_clear=True)` 顺序保持不变；该调用只删除子资源并保留知识空间本身。
3. `async_delete_knowledge(..., only_clear=True)` 提交返回后，立即对冻结 flow 去重、分片并 best-effort 投递延时任务；空集合不派发。F071 派发完成后再沿用既有流程重建空索引，后续空索引重建失败不撤销已提交清空或已完成派发。
4. 完整删除知识空间的 `delete_space` 明确不新派发入口回收任务，也不新增会话清理；此前已排队的删除/`clear_space` 回收任务不取消，即使随后写入指向已删除空间 root 的 `entry_flow_id` 也作为现状兼容残留接受。由于所有列表、历史和继续问答均先校验空间存在性与权限，该元数据不构成可访问入口。

#### 定向任务、批量执行与一致性边界

- 变更量按“受影响会话数”计算，不按消息数计算；每个会话至多更新一列一次，消息和引用表零写入。
- 资源操作在相关行消失或改写 `knowledge_id` 前，把本期纳入范围的删除、`clear_space` 或移动计划转换为原空间 flow 集合：每个 folder 生成 `space_{source_space_id}_folder_{folder_id}`，每个 file 生成 `space_{source_space_id}_file_{file_id}`；root entry 固定为 `space_{source_space_id}_folder_0`。删除包含其实际硬删除的版本链扩展文件；`clear_space` 包含既有 `child_resources` 中的全部 folder/file；跨空间移动只包含 valid item 的直接 move rows，不包含 `_collect_version_chain_file_ids` 额外扩展的 sibling。任务不得在资源操作完成后重新扫描已删除子树。
- flow 集合按 `flow_batch_size=500` 分片作为任务载荷，避免上万 ID 进入单个消息或 SQL `IN`；任务只执行下列等价更新，不加载 session 对象、消息正文或引用。不得添加当前操作者 `user_id` 条件，因为同一资源可能存在多个用户的会话：

```sql
UPDATE message_session
SET entry_flow_id = :source_root_flow
WHERE flow_type = :knowledge_space_flow_type
  AND is_delete = false
  AND entry_flow_id IS NULL
  AND flow_id IN (:affected_original_flows);
```

- `affected_original_flows` 只能来自已授权资源操作的服务端计划，不接受客户端 flow 字符串；`source_root_flow` 必须与这些 flow 的 source space 相同。Repository 在受控 `bypass_tenant_filter()` 中执行跨会话所有者更新，精确 flow + flow type 是系统 fan-out 的硬边界。
- 删除、清空、移动和任务之间不共享数据库事务或连接。触发边界分别是每个硬删除 commit、`clear_space` 子资源删除 commit 和跨空间移动 metadata commit；派发调用失败被捕获，已入队任务可重复执行并由 Celery 有界重试，但整体仍是 best-effort，不宣称端到端至少一次。
- 任务默认 `countdown=5s`，用于覆盖常见的会话迟到提交；若 session 在最后一次任务扫描后才提交，可能继续保持旧入口。该低概率竞态由产品接受，不以修改会话创建链路或全量周期扫描消除。
- 任务不做全库/全空间会话扫描；候选 flow 数、批次数、匹配 session 数、更新数、排队与执行耗时、重试次数和终态结果进入结构化日志。

#### 并发生成

- 在途请求开始时已通过旧 folder/file 权限，可以完成；消息仍写原 `chat_id/flow_id`。
- 入口 UPDATE 与首次标题 UPDATE 由数据库行锁串行化，两个 SQL 都只写各自字段；标题生成不得使用整对象 merge 覆盖 `entry_flow_id`。
- 迟到消息不会触碰 session 入口；任务扫描前已提交的 session 在任务成功执行后回到 root，扫描后才提交的极低概率 session 可能保持失联，记录为已接受的 best-effort 残余窗口。
- 回收完成后的后续请求重新按 effective entry 验证，root 入口只走全空间检索。

### 4.4 存量迁移

脚本：`src/backend/scripts/migrate_f068_knowledge_chat_entries.py`；登记到 `src/backend/scripts/README.md`。

识别 grammar：

```text
space_{space_id}_folder_0          -> 原生 root，不更新
space_{space_id}_folder_{id>0}     -> 检查 folder
space_{space_id}_file_{id>0}       -> 检查 file
```

判定规则：

| 存量状态 | `entry_flow_id` 结果 |
|---|---|
| 原空间存在，资源仍属于原空间 | 保持 null，入口沿用原 flow |
| 原空间存在，资源不存在 | 设置原空间 root flow |
| 原空间存在，资源存在但属于其它空间 | 设置原空间 root flow |
| 原知识空间不存在 | 脚本不新增、不清空入口；null 保持 null，已有非空 entry 也保持原值；报告非阻断分类 `deleted_space_skipped`，不计入可恢复失联集合 |
| `MessageSession.is_delete=true` | 保持 null，不恢复用户删除会话 |
| 活动会话 flow 无法解析、跨租户事实冲突 | 不猜测，计入 blocker，脚本非零退出 |

安全运行合同：

- “可恢复失联集合”只包含原知识空间仍存在、资源不存在或已属于其它空间、`is_delete=false` 且 flow 可可靠解析的会话；`deleted_space_skipped`、用户软删会话不属于该集合，无法解析或跨租户事实冲突属于 blocker。
- 默认 dry-run，只读并输出数据库身份（不含密码）、分类数量、chat_id 掩码样例和输入 SHA-256。manifest 覆盖当前 `--tenant-id` 范围内全部知识空间 session，而不是只包含 `entry_flow_id IS NULL` 的待更新行；SHA-256 基于按 `(tenant_id, chat_id)` 稳定排序的不可变输入 manifest 计算，manifest 至少包含 `tenant_id/chat_id/flow_id/flow_type/is_delete` 与资源事实分类，不包含脚本会修改的 `entry_flow_id/update_time`。已由本次脚本处理的行仍在 manifest 内，因此分批写入本身不会改变摘要。
- `--apply` 必须提供 dry-run 的 `--expected-input-sha256`；首次 apply 和断点续跑均重新计算同一 manifest，摘要变化时拒绝写。
- 支持 `--tenant-id`、`--batch-size` 和 checkpoint；checkpoint 保存 expected manifest hash 与最后完成的 `(tenant_id, chat_id)` 游标，每批独立提交，只更新 `entry_flow_id IS NULL` 的可恢复失联会话。进程中断后从已提交游标之后继续，已处理行仍参与 manifest 校验但不会重复更新。
- apply 后全量校验：`recoverable_orphan_remaining=0`，非知识空间 entry、跨空间 entry、错误 grammar 和 blocker 均为零；`deleted_space_skipped` 单独报告且不阻断发布。第二次 apply 必须零更新。
- 脚本只访问 DB，不初始化 OpenFGA/Redis/Milvus/ES；跨租户盘点使用 `bypass_tenant_filter()`，写操作显式限制 session tenant。
- apply 会按现有 DB 机制刷新被恢复 session 的 `update_time`；报告该数量，但不得更新消息、引用或 `create_time`。

### 4.5 前端行为

- `chatApi.ts` 的 URL、`FolderSession` 类型和请求参数不变，`entry_flow_id` 不返回前端。
- `useFolderChat` 的 `spaceId/folderId` 变化继续触发 session reload；当前目录删除后导航到根目录，即可读取 recovered session。
- 删除、清空空间内容或跨空间移动成功后不等待异步回收，也不为 F071 增加前端轮询或全局状态；用户在任务完成前可能暂时看不到回收会话，重新进入或刷新根目录后按现有列表接口读取最终结果。
- 同名会话不合并；UI 继续使用 chat_id 做选择、改名和删除。
- 会话重命名维持既有通用接口和权限行为，F071 不增加 entry 校验或修改其它会话类型。
- 无视觉样式变化；实施时若触及 UI 结构，仍须先读当时最新的 `src/frontend/packages/ui/docs/`。

### 4.6 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `database/models/session.py` | 只声明 `entry_flow_id` 字段 | 不增加 F071 DAO entry point，不改变通用 flow 语义 |
| `knowledge_chat_session_repository.py` 及实现 | effective-entry 查询、按精确 flow 集合执行幂等回收 UPDATE | 不解析 HTTP，不决定资源权限，不扫描全量会话 |
| `knowledge_space_chat_history_retention_service.py` | 校验服务端 flow chunk 与 source root，编排定向幂等更新 | 不直接写 ORM，不决定资源是否可删除、清空或移动 |
| `knowledge_space_service.py` | 规范化 batch 父子输入，冻结删除/`clear_space`/移动纳入范围的 flow；在每个硬删除 commit、`clear_space` 子资源删除 commit 或 move metadata commit 后立即 best-effort 分片派发 | 不等待回收完成，不从 session 推导资源权限，不为完整 `delete_space` 建立入口，不建设 outbox |
| `worker/knowledge/knowledge_chat_history_retention.py` | 短延时消费 flow chunk、调用 retention service、重试与记录终态 | 不重新扫描已删除子树，不回滚资源操作 |
| `worker/__init__.py` | 显式导入 `rehome_knowledge_chat_sessions` 完成 Celery task 注册；任务名保持在 `bisheng.worker.knowledge.*` 命名空间并由既有 router 投递到 `knowledge_celery` | 不为 F071 新增独立 worker、queue 或 broker 发布配置 |
| `knowledge_space_chat_service.py` | 列表/打开/继续问答使用 effective entry；消息使用原 flow | 不把 `entry_flow_id` 返回客户端，不动态跟随移回资源 |
| `chat_session/domain/chat.py` | 使用已验证 session 的真实 flow_id 读取消息 | 不全局放宽 session.flow_id 与 message.flow_id 一致性校验 |
| `migrate_f068_knowledge_chat_entries.py` | dry-run、校验、仅恢复失联存量、终态对账 | 不恢复消息内容，不访问外部存储或权限引擎 |
| `useFolderChat.ts` / 知识空间页面 mutation | 消费既有 session list 与既有重命名/删除能力 | 不轮询回收任务，不保存或推断权威入口 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 当前历史通常没有物理删除；是入口先校验资源、再按 flow 精确匹配导致不可见 | 误做消息恢复或从备份复制，制造重复会话 | chat service + migration dry-run |
| 2 | 不能直接修改 `MessageSession.flow_id` | session 与 message flow 不一致，历史读取失败；还会与迟到消息竞态 | 只写 `entry_flow_id`，原 flow 全程不变 |
| 3 | nullable override 查询必须排除已有 entry 的旧 flow | recovered session 会同时出现在根和旧目录 | effective-entry Repository；两个互斥条件 |
| 4 | 更新 `entry_flow_id` 会刷新 session `update_time`，但知识空间消息写入不会、列表也按 `create_time` 排序 | 把 update_time 误当最后消息时间，或为避免刷新而引入无必要新表 | Spec 明确元数据时间语义；测试列表顺序不变 |
| 5 | 跨空间移动后再移回可能保留相同 file/folder ID | 单文件按原 flow 查找会错误复用已回收会话，破坏 sticky | 查找/复用按 effective entry，不只按 flow_id |
| 6 | `MessageCitation.flow_id` 主要用于内容链，不是展示入口 | 为改入口批量更新 citation，增加失败面 | citation 保持原样 |
| 7 | `MessageSession.tenant_id` 是会话所有者的用户叶子 tenant，不是知识空间 owner tenant；管理员删除资源必须回收该资源下所有用户会话 | 按当前操作者 user/tenant 更新会漏掉其他合法会话；无界跨租户 UPDATE 又违反 C3 | Repository 仅对任务携带的精确 flow + knowledge flow type 做受控 fan-out |
| 8 | 用户清空历史会硬删消息但保留 session；删除会话则 `is_delete=true` | 以无消息当删除会误跳过空会话，或恢复软删会话 | entry 管 session 入口；迁移过滤 is_delete；消息不回填 |
| 9 | 文件夹删除会硬删子树，版本链还会扩展出目录外 sibling file；跨空间移动也会联动版本链 | 任务启动后再查资源已经无法还原影响范围，或误以为在线移动覆盖全部历史版本会话 | 删除按实际硬删除集合冻结；移动只冻结 valid item 的直接 move rows，显式排除额外版本 sibling |
| 10 | bulk UPDATE 无 tenant 自动注入，且资源操作与任务运行在不同进程 | 无界跨租户更新或依赖进程内状态都会出错 | 只允许 Repository 对精确 flow chunk 做受控 bypass；DB 字段为唯一入口真相 |
| 11 | best-effort 任务只覆盖其扫描时已提交的 session | 把任务误当强一致门禁，会对极晚提交会话作错误承诺 | 默认短延时覆盖常见竞态；任务后提交的极低概率失联进入告警/运维修复，不改正常创建链路 |
| 12 | 完整删除空间不会删除旧会话，也不取消此前排队的回收任务 | 把失效 `entry_flow_id` 误判为可访问入口，或为清理元数据扩大删除链路 | `delete_space` 不新派发也不清 session；空间存在性与权限校验阻断访问，deleted-space 元数据作为非阻断残留保留 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/knowledge/space/{space_id}/chat/folder/session?folder_id=0` | 既有 HTTP，响应结构不变但包含 recovered sessions | client 根目录历史面板 |
| folder session/history/chat endpoints | 既有 HTTP/SSE，服务端按 effective entry 验证 | `useFolderChat` |
| single-file history/chat endpoints | 既有 HTTP/SSE，服务端按 effective entry 查找/复用 | `useFileChat` |
| `KnowledgeSpaceChatHistoryRetentionService.rehome_by_flows(...)` | 内部 async Python API | 定向回收 worker、迁移验证 |
| `KnowledgeChatSessionRepository` effective-entry/rehome 方法 | 内部 Repository contract | chat service、retention service、migration verification |
| `bisheng.worker.knowledge.knowledge_chat_history_retention.rehome_knowledge_chat_sessions` | 显式注册的 Celery task；source space + flow chunk，默认延时 5 秒，经既有通配 router 投递到 `knowledge_celery` | delete folder/file、batch delete、clear space、cross-space move |
| `message_session.entry_flow_id` | DB nullable 字段 | 所有 API 副本和维护脚本 |

现有 `FolderSession.flow_id` 继续返回原内容 flow；前端和新代码不得用返回值推断当前入口。内部 `entry_flow_id` 不进入响应。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `MessageSession` / `ChatMessage` | chat_id、flow_id、user_id、tenant_id、is_delete、时间字段 | 改 flow grammar 或删除 session 过滤语义会破坏迁移与历史读取 |
| `KnowledgeSpaceService.delete_folder/delete_file/batch_delete/clear_space/move_items` | 已授权且本期纳入范围的资源影响集合 | 必须在资源行消失或改空间前冻结 ID；删除按每个 hard-delete commit、清空按子资源删除 commit、移动按 metadata commit 触发；完整 `delete_space` 不触发；未派发时接受 best-effort 失联 |
| `KnowledgeFile.file_level_path/knowledge_id/file_type` | 子树与当前空间事实 | hard delete 前必须取全；跨空间判断不能只看 id |
| F034 move 返回与 `skip_invalid` | valid/invalid 集合 | 只能回收实际 moved 项，不能处理被跳过的 invalid 项 |
| F048 permission application API | space/folder/file action | entry 不能代替资源权限，root 仍须校验原空间 |
| `ChatSessionService.get_chat_history` | session.flow_id 与 message.flow_id 精确一致 | recovered root 必须传数据库 session 的原 flow |
| client `useFolderChat` | folderId 变化触发 reload、chatId 驱动历史 | 若客户端直接按返回 flow 判断入口，会破坏 recovered root 行为 |
| Celery / Redis broker | 定向延时任务、`acks_late` 与有界重试 | 入队失败、worker 终态失败或提交后进程退出可能使会话持续不可见；不把 broker 当成与资源 DB 原子提交的 outbox |
| MySQL/DM8 | nullable column、索引、set-based UPDATE、update_time | 查询计划、bind 参数和 session update_time 刷新需要双方言验证 |

---

## 7. 测试与可观测

### 7.1 分层策略

- **单元测试**：effective-entry 条件、原生 root/recovered root 不重复、普通 folder/file、sticky、同空间 no-op、父子重复去重、deleted session 过滤、非知识空间 entry 拒绝、原空间权限。
- **Repository/Service 集成测试**：单文件/文件夹/多层子树/版本兄弟删除，清空有内容空间、清空空空间、完整删除空间，跨空间移动，`skip_invalid`，batch 混合项和父子重复输入；验证输入先规范化、只更新 session.entry_flow_id，原 flow、消息、引用和 create_time 不变，列表仍按 create_time。`clear_space` 使用提交前 `child_resources` 且只在保留空间时派发；完整 `delete_space` 不新派发、不清旧 session，已排队任务可留下失效 entry，但所有会话接口因空间不存在而拒绝访问。跨空间移动覆盖直接 move rows 内的当前可见文件会话，并验证额外版本 sibling 不进入在线 flow 集合。构造超过 500 个 flow 的影响集合，验证任务正确分片、只处理实际提交项且重复执行零副作用。
- **历史与继续问答测试**：入口用 root 验证，历史用原 flow 读取；继续问答使用 whole-space retriever，新消息仍写原 flow。负向覆盖“未回收旧 folder/file chat_id 传给 root”“recovered chat 传给旧入口”“其他空间/用户/flow type chat_id”，均须在读写消息和构造 retriever 前拒绝。
- **异步与并发测试**：每个 `adelete_batch` commit 后立即派发，但不重排各删除路径已有的 commit 前后清理动作；`clear_space` 子资源删除 commit 后、空索引重建前派发；move metadata commit 后且其它 post-commit 副作用前派发。验证任务已由 `worker/__init__.py` 注册、任务名命中 `bisheng.worker.knowledge.*` 并路由到 `knowledge_celery`；后续清理失败不漏掉已提交单元的派发，派发失败不改变资源结果。覆盖任务默认延时、`acks_late`、失败重试与终态日志；任务扫描前提交的并发 session 被回收，扫描后提交的 session 保持已声明的竞态，不为此修改创建链路。标题与消息始终完整，无 lost update。
- **回绑测试**：跨空间移出后再移回原空间，旧 recovered session 保持 root；单文件入口创建/选择新的有效 session。
- **迁移测试**：root/folder/file、missing/moved/deleted space、soft-deleted、空会话、未知 grammar、checksum 变化、部分批次提交后以同一 manifest hash 续跑、第二次 apply 零更新；验证 `recoverable_orphan_remaining` 归零而 `deleted_space_skipped` 非阻断；MySQL 与 DM8 集中验证。
- **E2E**：页面创建 folder/file 会话 → 单项/批量删除、清空空间内容或跨空间移动 → 等待定向任务完成 → 回原空间根查看、打开、继续、改名、删除；任务完成前允许暂时不可见。完整删除空间后，即使旧 session 或排队任务留下 entry 元数据，列表、历史与继续问答仍不可访问；目标空间始终不可见，无原空间权限用户不可见，存量 fixture 可恢复。

### 7.2 手动验证

升级前从 `src/backend/` 运行 dry-run：

```bash
export config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml
uv run python scripts/migrate_f068_knowledge_chat_entries.py
```

核对数据库身份、待恢复分类、`unparseable=0`、`cross_tenant_conflict=0` 后，使用摘要执行：

```bash
uv run python scripts/migrate_f068_knowledge_chat_entries.py --apply --expected-input-sha256 <SHA256>
```

随后用两个用户分别验证：原用户可在源空间根目录看到并继续 recovered chat；其他用户和目标空间均不可见；回收前后消息内容/时间与会话 create_time 不变，session update_time 允许刷新。整个过程不得输出消息正文或真实配置密码。

### 7.3 可观测

- 结构化日志：`knowledge_chat_entry.task_dispatched`、`knowledge_chat_entry.rehome`（source_space/reason/flow_count/matched_count/updated_count/queue_delay_ms/duration_ms/retry_count）、`knowledge_chat_entry.task_failed`、`knowledge_chat_entry.migration_summary`、`knowledge_chat_entry.invalid`。
- 不记录 query、answer、文件内容或完整 citation payload；chat_id 在批量脚本样例中掩码。
- 资源删除、清空或移动日志记录触发点、source space、reason、flow chunk 数量和 hash；派发异常与任务终态失败额外记录该批精确 flow（每批最多 500），供日志仍可用时人工重试。日志不是 durable outbox，不对提交后进程退出提供恢复保证。
- 在线路径不回退为全库扫描；运维可在维护窗口受控运行迁移脚本修复失联会话。发布迁移验收仍要求未解析、非法非知识空间 entry 和跨空间 entry 为零。

---

## 8. 发布、后续改进与不做事项

### 8.1 发布顺序

1. Alembic 为 `message_session` 增加 nullable `entry_flow_id` 与索引；只做 DDL，不回填。
2. 部署识别 effective entry、按明确 commit 触发点 best-effort 投递定向延时回收且内部字段不出 API 的后端与 worker；迁移完成前知识空间问答入口处于维护窗口。
3. 运行迁移 dry-run，核对数据库身份、分类和 checksum；显式 apply，仅更新失联活动会话。
4. blocker、`recoverable_orphan_remaining`、非法 entry 和跨空间 entry 归零；`deleted_space_skipped` 已单独核对后开放知识空间问答入口。
5. 验证新删除/清空/移动不等待任务、任务最终回收、完整删除空间不恢复、存量恢复、目标空间隔离、移回不回绑和已声明的并发窗口；再结束维护窗口。

**回滚**：新增列为纯增量，可保留不删。旧镜像会忽略 `entry_flow_id`，recovered 会话将再次失去入口，因此功能启用后不得把旧镜像回滚当作可用业务终态；应临时关闭知识空间问答及文件删除、空间清空、跨空间移动入口，保留字段值并前向修复。禁止为兼容旧镜像清空 entry 或改写原 flow，因为这会丢失恢复状态或破坏消息链。

### 8.2 后续 / 不做

- 当前不新增独立 SessionScope/投影表；只有入口模型扩展为多状态、多来源时再演进。
- 暂不保存或展示 recovered 原因/时间/来源名称；日志用于运维追踪，避免扩大 schema 和泄露已删除资源名称。
- 不清理旧 flow_id，也不移动消息/citation；它们仍是历史内容链的稳定标识。
- 不为已删除知识空间创建隐藏恢复区；产品明确排除空间级恢复。
- 不为在线竞态引入分布式锁、会话创建复查或全量周期巡检；定向 worker 是在线回收的正常路径，存量脚本仍只负责上线前历史恢复和受控运维修复。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-15 | 初版采用独立 `KnowledgeChatScope` 投影 | Spec ★ 已确认，进入 Design |
| 2026-09-15 | 按评审改为 `MessageSession.entry_flow_id` nullable 覆盖字段；取消新表与新会话双写，明确 update_time 是元数据时间、知识空间列表按 create_time | 用户确认单字段方案更符合当前需求复杂度 |
| 2026-09-18 | 改为资源操作成功后按精确 flow 分片投递定向延时回收；新增 Repository 而非扩展 DAO；取消同步门禁、同事务、分布式锁、创建复查和全量巡检 | 用户确认接受低频并发窗口与异步收敛，要求减小对原业务流程的改动 |
| 2026-09-18 | 在线回收降级为 best-effort；明确删除按每个 hard-delete commit、移动按 metadata commit 后触发；batch 先规范化父子输入；跨空间移动暂不覆盖直接 move rows 外的版本 sibling | 用户确认维持现状一致性级别并接受残余失联风险 |
| 2026-09-18 | 沿用全局 Celery 发布策略；补充 `worker/__init__.py` 显式注册和 `knowledge_celery` 路由约束；F071 派发不重排各删除路径既有清理顺序 | 用户确认不单独强化发布校验，并采纳任务注册与顺序描述修订 |
| 2026-09-18 | 将保留空间本身的 `clear_space` 纳入在线回收，完整 `delete_space` 仍排除；明确迁移可恢复集合、非阻断 deleted-space 分类及稳定 manifest/checkpoint 合同 | 用户采纳设计复审意见 |
| 2026-09-18 | 接受完整删除空间后保留旧 session，以及此前排队任务写入失效 entry 的现状；以空间存在性/权限阻断访问，不扩大 `delete_space` 清理链路 | 用户确认该残留状态无需治理 |
