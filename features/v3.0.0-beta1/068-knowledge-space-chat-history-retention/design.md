# Design: F068 知识空间问答与目录解耦、历史对话按空间保留

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 定义做什么和验收边界。
> - 本文定义为什么采用 `MessageSession.entry_flow_id` 作为展示入口覆盖、删除/移动如何触发回收、存量数据与并发如何处理。
> - `tasks.md` 在 Design ★ 确认后创建，记录实施顺序与实际偏差。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [release-contract.md](../release-contract.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-15
**状态**: ✅ 修订后的 Design 已于 2026-09-15 确认；尚未生成 `tasks.md`

---

## 1. 目标与非目标

- **目标**：在不改写既有会话和消息 `flow_id` 的前提下，为知识空间问答会话增加可变的展示入口；资源删除或跨空间移出时，会话从原目录/文件入口稳定回收到原空间根目录，历史可见且可按全空间范围继续问答。
- **非目标**：不新建会话作用域表，不重写通用会话体系，不移动或复制消息，不把历史带到目标空间，不恢复用户删除内容，不改变其它会话类型，也不新增“失联会话”页面。

---

## 2. 关键约束与 Constitution Check

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C8；知识域 Service 负责编排，`MessageSessionDao` 负责会话字段查询与批量更新，资源授权仍只经 F048。
- 遵守版本契约 **INV-36**：原空间、本人会话、根目录回收、可继续问答、幂等、存量恢复、同空间不触发和回收后不回绑同时成立。
- `message_session.flow_id` 与 `chat_message.flow_id` 是已有内容链标识，多个会话类型和历史查询都依赖二者相等；F068 不改写它们。
- `MessageSession.update_time` 当前不是“最后一条消息时间”：知识空间写入/删除消息不会 touch session，知识空间会话列表固定按 `create_time` 排序；更新 `entry_flow_id` 会按 MySQL/DM8 既有机制刷新 session `update_time`，这是会话元数据变化，不影响消息时间、消息顺序或当前列表顺序。
- `MessageSession.tenant_id` 是用户叶子租户，不等于资源拥有租户；列表继续按 session tenant/owner 过滤，空间可见性由业务权限校验决定。
- 文件/文件夹删除是硬删除，跨空间移动保留资源 ID 但修改 `knowledge_id`；存量恢复依赖旧 `flow_id` 解析原空间和原资源类型/ID。
- 同一文件夹可有多个会话，同一文件当前通常复用一个会话；不得假定 `(space, entry)` 唯一，会话唯一键始终是 `chat_id`。
- Alembic 只增加 nullable 列和索引；存量识别/回填由 `src/backend/scripts/` 独立执行，默认 dry-run。
- F068 不新增对外 URL、响应字段、错误码段或领域表；存量入口不可判定时失败关闭并记录结构化错误。

### Constitution Check

| 条款 | 结论 | 设计落实 |
|---|---|---|
| C1 分层 | 通过 | endpoint → `KnowledgeSpaceChatService/KnowledgeSpaceService` → `MessageSessionDao`；Service 不直接写 ORM |
| C2 双 DB | 通过 | nullable `VARCHAR` 列、标准索引和 set-based UPDATE；MySQL/DM8 均验证 |
| C3 多租户 | 通过 | 在线列表走 tenant-aware 模型；资源回收是对所有会话所有者的受控系统 fan-out，DAO 仅在已授权资源操作后 bypass tenant filter，以源空间生成的精确 flow 集合、知识空间 flow type、活动状态和 null entry 限定更新；大批量再以 `(tenant_id, chat_id)` 有限集合分页；迁移逐租户处理 |
| C4 权限 | 通过 | 根入口先校验原空间，普通目录/文件入口继续校验具体资源；`entry_flow_id` 不产生 ALLOW |
| C5 错误码 | 通过 | 不新增错误码，复用知识空间/会话既有错误与通用服务错误 |
| C6 密钥 | 不涉及 | 脚本报告不输出配置密码或消息内容 |
| C7 前端 store | 通过 | 前端仍经 `chatApi.ts`，不新增 store HTTP |
| C8 多节点 | 通过 | `message_session.entry_flow_id` 是 DB 中的唯一入口覆盖，不以 React 内存或进程缓存判定归属 |

---

## 3. 方案对比与选定

### 决策 1：用会话字段覆盖展示入口，不新增投影表

- **备选**：
  - A. 删除/移动时把 `message_session`、`chat_message` 和 `message_citation` 的 `flow_id` 全部改为根目录——需要跨三张表一致更新，并与生成中的迟到消息竞态。
  - B. 新增 `knowledge_chat_scope` 表——结构化能力最完整，但当前只需要决定展示入口，会增加表、join、双写、完整性校验和迁移面。
  - C. 在 `message_session` 增加 nullable `entry_flow_id`；null 表示入口沿用 `flow_id`，回收时只写根目录 flow ID。
- **选定**：C。`flow_id` 是内容链标识，`entry_flow_id` 是可见入口覆盖；两者职责严格分开。
- **原因**：当前业务只需要“入口是否仍跟随原 flow，还是固定到原空间根目录”这一位状态。原空间和原资源仍能从不可变 `flow_id` 得到，无需为恢复原因、时间等非当前需求字段建表。
- **何时该重新考虑**：只有产品要求多种独立作用域、展示恢复来源、全局历史或复杂入口生命周期时，才升级为结构化 SessionScope 表；当前不提前设计。

### 决策 2：入口查询使用显式覆盖语义

- **有效入口**：`effective_entry_flow_id = entry_flow_id if entry_flow_id is not null else flow_id`。
- **选定**：知识空间列表和会话打开先按 effective entry 验证位置；消息历史和持久化始终使用真实 `session.flow_id`。
- **查询形态**：避免 `COALESCE` 让索引整体失效，DAO 使用两个互斥分支合并并统一按 `create_time DESC` 排序：

```sql
entry_flow_id = :target
OR (entry_flow_id IS NULL AND flow_id = :target)
```

- **原因**：原生根目录会话命中第二分支，回收会话命中第一分支；一个 chat 只会命中一支，不会重复。
- **何时该重新考虑**：若数据量和双方言执行计划证明 OR 无法稳定使用索引，可改为两个索引查询 `UNION ALL` 后外层分页；语义不变。

### 决策 3：删除/移动前同步回收，入口保持 sticky

- **备选**：资源操作成功后异步回收、先删后回收、不可逆写入前同步回收。
- **选定**：授权和影响范围校验完成后、不可逆资源写入前同步更新受影响 session；跨空间移动在同一 DB transaction 内更新入口与资源 `knowledge_id`。
- **执行方式**：只对 `message_session` 做索引驱动的 set-based UPDATE，不读取或更新 `chatmessage/message_citation`；中等规模直接按精确 flow 集合更新，大量候选按稳定 chat_id 游标分批选择 `(tenant_id, chat_id)` 再批量更新，但所有批次仍属于当前资源操作的同步完成条件，不投递 fire-and-forget 任务。
- **失败方向**：回收失败立即终止资源操作；若删除路径在入口更新后、后续硬删除阶段失败，入口仍保持 root，整体返回失败，重试把已回收会话视为 no-op。
- **原因**：删除前才能取得完整子树和版本链；“资源尚在但会话已在根目录”比“资源已消失且会话无入口”更安全。
- **何时该重新考虑**：资源删除引入统一 durable operation/UoW 后，可把前后步骤放入同一可恢复操作；不能改成无 ledger 的异步最终一致。

### 决策 4：并发生成继续写原内容链

- **选定**：删除/移动不取消在途生成。迟到消息继续写原 `chat_id/flow_id`；`entry_flow_id` 一旦设置为 root，消息写入和标题生成均不得清空或覆盖它。
- **原因**：知识空间消息写入不会更新 session；首次标题生成虽会更新同一 session 行，但使用字段级 UPDATE，数据库行锁串行化后不会覆盖 `entry_flow_id`。新建知识空间会话与资源删除/移动必须按同一顺序锁定并复核资源行：会话创建先锁定/复核资源归属再插入，资源操作先锁定资源再扫描 session。这样聊天先获得锁时 session 会在回收扫描前提交，资源操作先获得锁时后续会话创建因资源已删除/移出而失败，不会产生扫描后的漏网 session。下一轮请求重新读取入口，root 入口固定按全空间检索。
- **额外约束**：已回收资源日后移回原空间时，单文件会话查找不得只按原 `flow_id` 复用 recovered session；必须要求 effective entry 仍等于当前文件入口，否则创建新会话。
- **何时该重新考虑**：若产品要求删除资源立即终止相关回答，需要独立内容治理 Feature 明确终止和历史裁剪语义。

### 决策 5：存量只更新真正失联的活动会话

- **备选**：Alembic 全量 backfill、运行时懒修复、独立脚本识别失联会话。
- **选定**：Alembic 只加 nullable 字段；独立 DB-only 脚本扫描知识空间 session，仅对“原资源不存在或已属于其它空间”的活动会话写 root `entry_flow_id`。正常 root/folder/file 会话保持 null。
- **原因**：nullable override 让正常存量天然兼容，无需更新每一条 `message_session`，减少锁和 `update_time` 刷新范围；同时一次性恢复未访问用户的失联历史。
- **何时该重新考虑**：若实测数据量超过维护窗口，脚本可带 checkpoint 分批执行；仍须保留 checksum、幂等和启用门禁。

### 决策 6：前端不新增视图或归属状态

- **选定**：复用现有根目录会话列表、历史面板和输入框；后端返回既有 `FolderSession`，内部 `entry_flow_id` 不进入响应。
- **原因**：现有 `useFolderChat` 已按 space/folder 重新加载；前端只需在删除/跨空间移动成功后刷新源空间根会话列表，不保存入口真相。
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
- 写入口可以刷新 `MessageSession.update_time`；不得修改 `create_time`、原 `flow_id`、消息/引用内容及其时间。

### 4.3 在线数据流

#### 新建和查找会话

- 新建知识空间会话仍只写原 `flow_id`，`entry_flow_id=NULL`，不增加双写。
- 文件夹列表按 effective entry 过滤，可保留多个会话。
- 单文件“查找或新建”必须按 effective entry 查找：已回收到 root 的旧 session 不得因资源同 ID 移回而被复用。

#### 列表、历史与继续问答

1. endpoint 仍接收 `space_id + folder_id/file_id + chat_id`。
2. Service 校验当前用户对 space 的访问；非 root 再校验具体 folder/file。
3. DAO 按 effective entry 查询 `MessageSession`，同时过滤 tenant、`user_id`、知识空间 flow_type 与 `is_delete=false`，按既有 `create_time DESC` 排序。
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

1. `delete_folder/delete_file/batch_delete` 在授权后锁定受影响资源并生成完整只读删除计划：folder、全部后代 folder/file，以及版本链扩展出的 file/version/document ID。现有会写数据的 `_cascade_version_links_on_delete` 必须拆成“只读计划 + 计划执行”。知识空间会话创建使用相同资源锁顺序，防止计划生成后再插入旧入口 session。
2. 根据计划生成受影响的精确原 flow ID 集合；调用 retention service 回收这些 flow 下所有会话所有者的 session，而不是只处理当前操作者。DAO 在受控 bypass 中按知识空间 flow type 和精确 flow 集合读取 `(tenant_id, chat_id)`，再将这些行中仍为 null 的 `entry_flow_id` 批量设为原空间 root flow。
3. 入口更新成功后才继续权限 tuple 清理、业务硬删除和异步文件清理；更新失败时不执行硬删除。
4. 父项和子项重复输入按 chat_id/flow 集合去重；已回收行保持不变。
5. 若入口已更新而后续删除失败，整体返回失败但不自动回绑；重试时入口更新为 no-op。

#### 移动

1. `move_items` 完成 valid/invalid 筛选后，只处理实际移动的 valid rows。
2. 同空间移动不更新会话入口。
3. 跨空间移动在现有 DB transaction 内、资源 `knowledge_id` 更新前，按源空间与 valid 子树生成原 flow ID 集合，将所有会话所有者对应 session 的 `entry_flow_id` 设为源空间 root。
4. 入口与资源变更一起 commit；目标空间查询使用目标 flow，不能命中这些会话。后续 FGA parent tuple、tag 和检索数据迁移不改变会话入口。

#### 大批量执行与事务边界

- 变更量按“受影响会话数”计算，不按消息数计算；每个会话至多更新一列一次，消息和引用表零写入。
- 先把删除/移动计划转换为原空间的精确 flow 集合：每个 folder 生成 `space_{source_space_id}_folder_{folder_id}`，每个 file 生成 `space_{source_space_id}_file_{file_id}`；root entry 固定为 `space_{source_space_id}_folder_0`。
- 中等规模可直接执行下列等价更新；不得添加当前操作者 `user_id` 条件，因为同一资源可能存在多个用户的会话：

```sql
UPDATE message_session
SET entry_flow_id = :source_root_flow
WHERE flow_type = :knowledge_space_flow_type
  AND is_delete = false
  AND entry_flow_id IS NULL
  AND flow_id IN (:affected_original_flows);
```

- `affected_original_flows` 只能来自已授权并锁定的源空间删除/移动计划，不接受客户端 flow 字符串；`source_root_flow` 必须与这些 flow 的 source space 相同。DAO 在受控 `bypass_tenant_filter()` 中执行该跨会话所有者更新，精确 flow + flow type 是系统 fan-out 的硬边界。
- 大量候选采用两层分批：第一层按配置的 `flow_batch_size` 切分 `affected_original_flows`，控制 `IN` 参数数量和 SQL 长度；第二层在每个 flow chunk 内按稳定 `chat_id` keyset 游标、配置的 `session_batch_size` 读取有限 `(tenant_id, chat_id)`，再按这些主键 UPDATE，控制单条语句更新行数、锁持有量和内存。禁止使用 OFFSET 分页，禁止把全部 session 或任何消息正文加载到内存；每批仍保留 `flow_type/is_delete/entry_flow_id` 条件，防止状态变化后误写。
- 两个 batch size 不在 Design 中拍脑袋固化：实施时以 MySQL/DM8 的 bind 参数限制、执行计划、锁等待和压测结果确定保守默认值，并允许通过后端配置调整；测试必须覆盖 `flow_count > flow_batch_size` 且 `session_count > session_batch_size` 的组合。
- **跨空间移动**：所有入口批次与资源 `knowledge_id` 更新处于同一事务；任一批失败则整体 rollback，移动不成功。
- **硬删除**：所有入口批次必须在硬删除前同步完成。若中途失败，硬删除不执行；已提交的 root 入口允许保留，重复请求跳过这些行并继续，不能为追求回滚而重新绑定旧资源。
- 请求超过数据库 statement/transaction timeout 时返回资源操作失败，不允许先返回删除/移动成功再依赖 Celery 补偿。候选数、批次数、更新数和耗时必须进入结构化日志，以实测决定 batch size。
- 异步任务只允许做“检测仍失联会话并告警/触发受控修复”的 reconciliation，不能成为删除或移动正确性的唯一保障。若未来确需超大规模异步化，必须把资源操作本身改为有持久状态的 `PENDING → REHOME_DONE → RESOURCE_DONE/FAILED` 工作流，并调整 API/UI 成功语义；不在 F068 当前合同内以普通后台任务替代同步门禁。

#### 并发生成

- 在途请求开始时已通过旧 folder/file 权限，可以完成；消息仍写原 `chat_id/flow_id`。
- 入口 UPDATE 与首次标题 UPDATE 由数据库行锁串行化，两个 SQL 都只写各自字段；标题生成不得使用整对象 merge 覆盖 `entry_flow_id`。
- 迟到消息不会触碰 session 入口；后续请求重新按 effective entry 验证，root 入口只走全空间检索。

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
| 原知识空间不存在 | 保持 null，不建立可见入口；报告 `deleted_space_skipped` |
| `MessageSession.is_delete=true` | 保持 null，不恢复用户删除会话 |
| 活动会话 flow 无法解析、跨租户事实冲突 | 不猜测，计入 blocker，脚本非零退出 |

安全运行合同：

- 默认 dry-run，只读并输出数据库身份（不含密码）、分类数量、chat_id 掩码样例和输入 SHA-256。
- `--apply` 必须提供 dry-run 的 `--expected-input-sha256`；输入集合变化时拒绝写。
- 支持 `--tenant-id`、`--batch-size` 和 checkpoint；每批独立提交，只更新 `entry_flow_id IS NULL` 的失联活动会话。
- apply 后全量校验：活动失联会话的 entry 均为原空间 root；非知识空间 entry、跨空间 entry、错误 grammar 均为零。第二次 apply 必须零更新。
- 脚本只访问 DB，不初始化 OpenFGA/Redis/Milvus/ES；跨租户盘点使用 `bypass_tenant_filter()`，写操作显式限制 session tenant。
- apply 会按现有 DB 机制刷新被恢复 session 的 `update_time`；报告该数量，但不得更新消息、引用或 `create_time`。

### 4.5 前端行为

- `chatApi.ts` 的 URL、`FolderSession` 类型和请求参数不变，`entry_flow_id` 不返回前端。
- `useFolderChat` 的 `spaceId/folderId` 变化继续触发 session reload；当前目录删除后导航到根目录，即可读取 recovered session。
- 删除/跨空间移动成功后，源空间 root session list 必须失效/刷新；使用页面局部 reload token 或现有 mutation 完成回调，不新增 Recoil/global store，也不在前端解析 flow_id。
- 同名会话不合并；UI 继续使用 chat_id 做选择、改名和删除。
- 无视觉样式变化；实施时若触及 UI 结构，仍须先读当时最新的 `src/frontend/packages/ui/docs/`。

### 4.6 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `database/models/session.py` | 声明 `entry_flow_id`；提供 effective-entry 查询和受控批量更新 | 不解析 HTTP，不调用 OpenFGA，不改变通用 flow 语义 |
| `knowledge_space_chat_history_retention_service.py` | 根据已验证资源集合生成原 flow 集合和 root entry，编排幂等更新 | 不直接写 ORM，不决定资源是否可删除/移动 |
| `knowledge_space_service.py` | 在 delete/move/batch 的既有授权和影响范围中调用 retention service | 不从 session 推导资源权限 |
| `knowledge_space_chat_service.py` | 列表/打开/继续问答使用 effective entry；消息使用原 flow | 不把 `entry_flow_id` 返回客户端，不动态跟随移回资源 |
| `chat_session/domain/chat.py` | 使用已验证 session 的真实 flow_id 读取消息 | 不全局放宽 session.flow_id 与 message.flow_id 一致性校验 |
| `migrate_f068_knowledge_chat_entries.py` | dry-run、校验、仅恢复失联存量、终态对账 | 不恢复消息内容，不访问外部存储或权限引擎 |
| `useFolderChat.ts` / 知识空间页面 mutation | 消费既有 session list，并在资源操作后刷新源 root | 不保存或推断权威入口 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 当前历史通常没有物理删除；是入口先校验资源、再按 flow 精确匹配导致不可见 | 误做消息恢复或从备份复制，制造重复会话 | chat service + migration dry-run |
| 2 | 不能直接修改 `MessageSession.flow_id` | session 与 message flow 不一致，历史读取失败；还会与迟到消息竞态 | 只写 `entry_flow_id`，原 flow 全程不变 |
| 3 | nullable override 查询必须排除已有 entry 的旧 flow | recovered session 会同时出现在根和旧目录 | effective-entry DAO；两个互斥条件 |
| 4 | 更新 `entry_flow_id` 会刷新 session `update_time`，但知识空间消息写入不会、列表也按 `create_time` 排序 | 把 update_time 误当最后消息时间，或为避免刷新而引入无必要新表 | Spec 明确元数据时间语义；测试列表顺序不变 |
| 5 | 跨空间移动后再移回可能保留相同 file/folder ID | 单文件按原 flow 查找会错误复用已回收会话，破坏 sticky | 查找/复用按 effective entry，不只按 flow_id |
| 6 | `MessageCitation.flow_id` 主要用于内容链，不是展示入口 | 为改入口批量更新 citation，增加失败面 | citation 保持原样 |
| 7 | `MessageSession.tenant_id` 是会话所有者的用户叶子 tenant，不是知识空间 owner tenant；管理员删除资源必须回收该资源下所有用户会话 | 按当前操作者 user/tenant 更新会漏掉其他合法会话；无界跨租户 UPDATE 又违反 C3 | 授权后受控 bypass；精确 flow + flow type 选出 `(tenant_id, chat_id)`，再按该有限集合更新 |
| 8 | 用户清空历史会硬删消息但保留 session；删除会话则 `is_delete=true` | 以无消息当删除会误跳过空会话，或恢复软删会话 | entry 管 session 入口；迁移过滤 is_delete；消息不回填 |
| 9 | 文件夹删除会扩展版本链，现有 `_cascade_version_links_on_delete` 在“计算”时已写数据 | 只按 children 会漏会话，或回收失败前已删版本 | 拆为只读 delete plan 与 plan execution |
| 10 | bulk UPDATE 无 tenant 自动注入，资源操作与聊天可能在不同副本 | 无界跨租户更新或依赖进程锁都会出错 | 只允许 DAO 内受控 bypass，按已选出的 tenant/chat 对更新；DB 字段为唯一真相 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/knowledge/space/{space_id}/chat/folder/session?folder_id=0` | 既有 HTTP，响应结构不变但包含 recovered sessions | client 根目录历史面板 |
| folder session/history/chat endpoints | 既有 HTTP/SSE，服务端按 effective entry 验证 | `useFolderChat` |
| single-file history/chat endpoints | 既有 HTTP/SSE，服务端按 effective entry 查找/复用 | `useFileChat` |
| `KnowledgeSpaceChatHistoryRetentionService.rehome(...)` | 内部 async Python API | delete folder/file、batch delete、cross-space move |
| `MessageSessionDao` effective-entry/rehome 方法 | 内部 DAO contract | chat service、retention service、migration verification |
| `message_session.entry_flow_id` | DB nullable 字段 | 所有 API 副本和维护脚本 |

现有 `FolderSession.flow_id` 继续返回原内容 flow；前端和新代码不得用返回值推断当前入口。内部 `entry_flow_id` 不进入响应。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `MessageSession` / `ChatMessage` | chat_id、flow_id、user_id、tenant_id、is_delete、时间字段 | 改 flow grammar 或删除 session 过滤语义会破坏迁移与历史读取 |
| `KnowledgeSpaceService.delete_folder/batch_delete/move_items` | 已授权的资源影响集合 | 新增删除入口却未调用 retention service 会重新产生失联历史 |
| `KnowledgeFile.file_level_path/knowledge_id/file_type` | 子树与当前空间事实 | hard delete 前必须取全；跨空间判断不能只看 id |
| F034 move 返回与 `skip_invalid` | valid/invalid 集合 | 只能回收实际 moved 项，不能处理被跳过的 invalid 项 |
| F048 permission application API | space/folder/file action | entry 不能代替资源权限，root 仍须校验原空间 |
| `ChatSessionService.get_chat_history` | session.flow_id 与 message.flow_id 精确一致 | recovered root 必须传数据库 session 的原 flow |
| client `useFolderChat` | folderId 变化触发 reload、chatId 驱动历史 | 若客户端直接按返回 flow 判断入口，会破坏 recovered root 行为 |
| MySQL/DM8 | nullable column、索引、row locking、update_time | 查询计划、行锁和 session update_time 刷新需要双方言验证 |

---

## 7. 测试与可观测

### 7.1 分层策略

- **单元测试**：effective-entry 条件、原生 root/recovered root 不重复、普通 folder/file、sticky、同空间 no-op、父子重复去重、deleted session 过滤、非知识空间 entry 拒绝、原空间权限。
- **DAO/Service 集成测试**：单文件/文件夹/多层子树/版本兄弟删除，跨空间移动，`skip_invalid`，batch 混合项；验证只更新 session.entry_flow_id，原 flow、消息、引用和 create_time 不变，列表仍按 create_time。构造超过单批大小的 session 集合，验证 keyset 分批无遗漏/重复、内存有界、移动事务整体回滚以及删除中断后重试收敛。
- **历史与继续问答测试**：入口用 root 验证，历史用原 flow 读取；继续问答使用 whole-space retriever，新消息仍写原 flow。负向覆盖“未回收旧 folder/file chat_id 传给 root”“recovered chat 传给旧入口”“其他空间/用户/flow type chat_id”，均须在读写消息和构造 retriever 前拒绝。
- **并发测试**：生成/标题开始后回收、回收后迟到消息、重复删除/移动、两个请求同时回收；entry 最终稳定 root，标题与消息完整，无 lost update。
- **回绑测试**：跨空间移出后再移回原空间，旧 recovered session 保持 root；单文件入口创建/选择新的有效 session。
- **迁移测试**：root/folder/file、missing/moved/deleted space、soft-deleted、空会话、未知 grammar、checksum 变化、分批续跑、第二次 apply 零更新；MySQL 与 DM8 集中验证。
- **E2E**：页面创建 folder/file 会话 → 删除或跨空间移动 → 回原空间根查看、打开、继续、改名、删除；目标空间不可见；无原空间权限用户不可见；存量 fixture 可恢复。

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

- 结构化日志：`knowledge_chat_entry.rehome`（tenant/space/reason/source_count/candidate_count/batch_count/updated_count/duration_ms）、`knowledge_chat_entry.migration_summary`、`knowledge_chat_entry.invalid`。
- 不记录 query、answer、文件内容或完整 citation payload；chat_id 在批量脚本样例中掩码。
- 资源删除/移动成功前，日志必须存在同 trace 的 rehome success 或明确 `session_count=0`；rehome failure 直接抛出，不降级继续。
- 发布验收统计：活动知识空间 session 总数、recovered entry 数、仍失联数、非法非知识空间 entry 数、跨空间 entry 数；后三类必须为零。

---

## 8. 发布、后续改进与不做事项

### 8.1 发布顺序

1. Alembic 为 `message_session` 增加 nullable `entry_flow_id` 与索引；只做 DDL，不回填。
2. 部署识别 effective entry、同步处理新删除/移动且内部字段不出 API 的后端；迁移完成前知识空间问答入口处于维护窗口。
3. 运行迁移 dry-run，核对数据库身份、分类和 checksum；显式 apply，仅更新失联活动会话。
4. 未解析、仍失联、非法 entry 和跨空间 entry 归零后开放知识空间问答入口。
5. 验证新删除/移动、存量恢复、目标空间隔离、移回不回绑和并发迟到消息；再结束维护窗口。

**回滚**：新增列为纯增量，可保留不删。旧镜像会忽略 `entry_flow_id`，recovered 会话将再次失去入口，因此功能启用后不得把旧镜像回滚当作可用业务终态；应临时关闭知识空间问答及文件删除/跨空间移动入口，保留字段值并前向修复。禁止为兼容旧镜像清空 entry 或改写原 flow，因为这会丢失恢复状态或破坏消息链。

### 8.2 后续 / 不做

- 当前不新增独立 SessionScope/投影表；只有入口模型扩展为多状态、多来源时再演进。
- 暂不保存或展示 recovered 原因/时间/来源名称；日志用于运维追踪，避免扩大 schema 和泄露已删除资源名称。
- 不清理旧 flow_id，也不移动消息/citation；它们仍是历史内容链的稳定标识。
- 不为已删除知识空间创建隐藏恢复区；产品明确排除空间级恢复。
- 不用后台 worker 做关键回收；异步 reconciliation 可作为未来告警/修复工具，但不能替代同步成功条件。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-15 | 初版采用独立 `KnowledgeChatScope` 投影 | Spec ★ 已确认，进入 Design |
| 2026-09-15 | 按评审改为 `MessageSession.entry_flow_id` nullable 覆盖字段；取消新表与新会话双写，明确 update_time 是元数据时间、知识空间列表按 create_time | 用户确认单字段方案更符合当前需求复杂度 |
