# Design: 审计功能优化

> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档，只留今天的状态；每个决策保留「为什么 + 被否方案」。推翻已 ★ 确认的决策要停下与用户重新确认；纯实现细节直接改本文档。`tasks.md`「实际偏差记录」只留一行指针。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · 草稿 [`docs/审计功能优化方案.md`](../../../docs/审计功能优化方案.md)（已被本文取代；两者冲突时以本文为准）
**版本**: v3.1.0-beta1
**最后更新**: 2026-11-03

---

## 1. 目标与非目标

- **目标**：给审计三页签加上「记录发生时的操作者主部门」这一维度（存储、展示、筛选、导出），按身份把审计数据收窄到租户加部门范围；补齐 5 个旧动作的筛选文案和显式模块映射；在应用使用页按查询时已有的记录归出四类使用类型。
- **非目标**：不新增动作类型，不改 17 类结构化动作的业务写入；不回填历史组织；不做逐消息组织；不改运行记录的采集范围；不新增错误码。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C8。本功能里最容易踩到的是：
  - **C1 / RULE-2**：审计写入口 `AuditLogDao`、`MessageSessionDao` 在 `database/models/`，不能导入任何 `domain/`。快照解析因此只能用 `database/models/department.py` 里已有的 DAO 方法。
  - **C1**：新功能不新增 DAO 入口。新查询（部门闭包、候选、会话用户）放进领域模块的 `domain/repositories/`；改既有 DAO 方法的条件、加参数不算新入口。
  - **C2**：组织列只用 `Integer` / `String`；`LIKE` 前缀匹配、`EXISTS` 子查询两种方言都支持；不用 JSON 函数。
  - **C3**：快照查询按 id 定位部门和成员关系，包在 `bypass_tenant_filter()` 里，避免 Celery 或系统触发的写入因缺少租户上下文失败。
- 迁移只做 DDL（`core/database/alembic/AGENTS.md` §5），不回填。当前 head 为 `f114_app_authorization`。
- 写入路径上的快照查询不能拖慢或打断主业务：失败留空并记日志；`open_api.call` 这类高频写入按批解析，不逐行查。
- 审计列表本身是热路径：组织条件按 `operator_dept_id IN (部门 id 子查询)` 实现，不 JOIN 部门表，不把下级 id 摊成大参数。

---

## 3. 方案对比与选定

### 决策 1：组织快照的存储形态

- **备选**：
  - A. 五张来源表各加两列：`operator_dept_id`（可空、单独索引、无默认值、无外键）和 `operator_dept_path`（名称路径）。用 `NULL` / `0` / `-1` 三个哨兵区分未记录、无所属部门、不适用。
  - B. 新建归属表（记录 id → 部门），列表时 JOIN。
  - C. 不存快照，查询时 JOIN 用户当前主部门。
- **选定**：A。
- **原因**：C 违反「按发生时」和「调动不回写」的要求（AC-09、AC-24）。B 每次列表多一次 JOIN，五张表要建五套关联。A 只加一个可索引的整数列，筛选是单列 `IN`。`department.id` 从 1 起，三个哨兵不会和真实部门冲突。不加外键：`0` 和 `-1` 不是部门主键。不加 `server_default`：旧行会被填成「无所属部门」，违反 AC-10。
- **列名**：用 `operator_dept_id` / `operator_dept_path`，不用 `dept_id`。部门表里 `department.dept_id` 是字符串业务编号，同名会让人把整数主键和字符串编号混用（用户在 Spec Discovery 时确认）。
- **何时重新考虑**：需要多部门归属，或需要按发生时的部门编号（而非主键）检索时。

### 决策 2：快照在哪写

- **备选**：
  - A. SQLAlchemy `before_insert` 映射器事件，挂在 `AuditLog` / `MessageSession` 上，一处覆盖所有写入。
  - B. 在既有插入收口里显式填写：`AuditLogDao.insert_audit_logs` / `ainsert_audit_logs` / `ainsert_v2`、`MessageSessionDao.insert_one` / `async_insert_one`、运行记录的三个构造点；绕过 DAO、直接 `session.add(AuditLog(...))` 的站点逐个补调用。再用守卫测试防止新增站点漏掉。
- **选定**：B。
- **原因**：映射器事件运行在 flush 内部，只能同步查询。异步会话里同步查询会阻塞事件循环；`open_api.call` 每个开放接口请求都写一行，阻塞会落在热路径上。事件里也不能复用正在 flush 的会话。B 让异步路径用异步查询，批量写入用批量查询。
- **已知站点**（2026-11-03 实现核对）：
  - 会话：12 个构造点全部经 `MessageSessionDao.insert_one` / `async_insert_one`（含 `ChatSessionService.create_subject_session`），只改这两个方法。
  - 审计行经 DAO 盖章，构造处不再单独调用：
    - `AuditLogService` 的写入都进 `insert_audit_logs` / `ainsert_audit_logs` / `ainsert_v2`。
    - `open_api/api/middleware.py`、`open_mcp/server.py`、`open_mcp/auth.py` 构造后交给 `open_api_call_audit_service.enqueue`，批量写入时走 `ainsert_audit_logs`。
    - `public_endpoints/domain/services/guest_link.py` 自己调用 `ainsert_audit_logs`。
  - 绕过 DAO、直接 `session.add(AuditLog(...))`、必须在 `add` 前调用 `astamp_audit_logs` 的有 5 处：
    - `open_api/domain/repositories/credential_repository.py`（3 处）
    - `app_publish/domain/repositories/app_secret_repository.py`（1 处）
    - `linsight/domain/services/personal_skill_service.py`（1 处）
- **守卫**：测试扫描 `src/backend/bisheng/**/*.py` 中的 `AuditLog(` 构造（跳过 alembic）。所在文件必须出现 `stamp_audit_logs`、`AuditLogDao.insert_audit_logs`、`AuditLogDao.ainsert_audit_logs` 或 `open_api_call_audit_service.enqueue` 之一。
- **何时重新考虑**：项目统一成单一审计写入服务时，收回到那一处。

### 决策 3：快照取值规则

- **选定**：
  - 先判断不适用：审计行 `operator_id == 0`（系统触发和服务账号都写 0）写 `-1`。会话行 `api_subject_type` 不为空（`service_account`、`public_v3`）写 `-1`，因为开放接口会话的 `user_id` 是兼容用的用户编号，按它查部门会记成某个人。运行记录按各自的主体字段判断，见 §4.1。
  - 否则取该用户 `is_primary = 1` 的 `UserDepartment.department_id`；没有就写 `0`。
  - 名称路径由 `department.path`（`/1/2/3/`）里的主键批量换成 `department.name`，用 `/` 连接。
  - 查询异常时两列都留空，`logger.warning` 后继续写入。
- **原因**：spec AC-07、AC-10、AC-11 和 §3 第一条。`UserDepartment.id` 是成员关系主键，不是部门主键，是最容易写错的地方。
- **何时重新考虑**：服务账号改为写真实 `operator_id`，或审计行新增显式的主体类型列时，改用那一列判断不适用。

### 决策 4：数据范围的计算位置

- **备选**：
  - A. 写在 legacy `api/services/audit_log.py` 里，运行记录（`app_governance`）也去调它。
  - B. 放在部门领域：`department/domain/services/audit_dept_scope.py` 负责从身份解析出范围，查询放 `department/domain/repositories/audit_dept_repository.py`；系统操作、应用使用、运行记录三方都调用。
- **选定**：B。
- **原因**：A 会让 `app_governance` 领域依赖 `api/` 包。范围本质是部门闭包查询，归部门模块。一个函数供三方共用，保证列表、候选、详情、导出口径一致（AC-18）。
- **范围对象** `AuditDeptScope`：
  - `unrestricted=True`：全局超管、租户管理员，不加部门条件。
  - 否则带 `admin_paths`（部门管理员所管部门的 `path` 列表）或 `exact_ids`（菜单角色的本人主部门 id）。闭包不含 `NULL` / `0` / `-1`。
- **身份判定顺序**：
  1. `is_global_super`，或当前租户的租户管理员 → `unrestricted`；即使 `aget_user_admin_departments` 也有结果。
  2. 否则必须有审计菜单，没有则 `UnAuthorizedError`。
  3. 当前审计租户内有所管部门 → `admin_paths`。
  4. 否则取本人主部门 → `exact_ids`；连主部门都没有 → 空闭包，结果为空。
  - 菜单判定在 `AuditDeptScopeService._has_audit_menu`。旧的 `_user_has_log_web_menu` 已删除：它对租户管理员直接返回真，拿它当「只有审计菜单」会把租户管理员收成主部门范围。租户管理员必须在第 1 步就判成不限。
- **部门管理员的闭包**：所管部门 `path` 前缀下的全部部门，含 `status = archived`（Spec Discovery 确认）。不用 `aget_active_descendants_under_path`：它排除自身，且只要 active。
- **何时重新考虑**：审计范围需要与部门管理页的 `_aget_user_scope`（租户挂载点并集）统一时。

### 决策 5：组织筛选条件的表达

- **选定**：
  - 一个纯函数 `build_dept_predicate(column, scope, selection)`，放在 `database/models/org_snapshot.py`，`AuditLogDao` 和各 repository 共用（`database/models` 可被 domain 导入，反之不行）。
  - 选择展开：「包含下级」为真时，每个选中的有效部门生成 `department.path LIKE '<path>%'` 且 `status = active` 的 id 子查询。`path` 自带结尾 `/`，所以 `/1/2/` 不会命中 `/1/20/`。为假时用精确 id。再并上单独选中的归档部门 id、`include_none` → `= 0`、`include_unrecorded` → `IS NULL`。
  - 与范围求交：`unrestricted` 时只用选择；否则丢掉 `include_none` / `include_unrecorded`，再 AND 闭包。闭包分两段：`admin_paths` 是 `department.path` 前缀子查询（含归档）；`exact_ids` 是主部门 id 的直接 `IN`，不走 path 子查询。主部门只有一个 id，不是下面被否的「把下级摊成大 IN 列表」。
  - 不选任何组织：`unrestricted` 不加条件；受限时只加闭包。
- **原因**：AC-22、AC-23、AC-16。子查询让数据库在小表上展开，不把几百个下级 id 塞进参数。
- **被否**：在 Python 里先展开下级 id 再 `IN` —— 参数爆炸，DM8 对 `IN` 列表长度更敏感。
- **何时重新考虑**：部门表大到 `path LIKE` 子查询成为瓶颈时（如超过十万个部门），改为闭包表。

### 决策 6：组织与用户候选用审计专用接口

- **备选**：
  - A. 复用 `GET /api/v1/departments/children|search|{id}/path-tree` 和 `getUsersApi`。
  - B. 新增 `GET /api/v1/audit/departments` 和 `GET /api/v1/audit/session/users`。
- **选定**：B。
- **原因**：部门接口走 `_aget_user_scope`，只有审计菜单的用户会被 `DepartmentPermissionDeniedError` 拒绝；搜索不匹配字符串 `department.dept_id`；`include_archived` 把归档插进树层，而需求要平铺列表。`getUsersApi` 是公共组件的数据源，改它会让其他页面的用户选择也变成审计范围。契约见 §6.1。
- 未进入指定管理租户、也未传 `tenant_id` 的全局超管，顶层返回各租户的根部门，前端按 `tenant_id` 分组（AC-27）。
- **何时重新考虑**：部门接口提供「按调用方传入的范围对象裁剪」的能力时，可改为复用。

### 决策 7：使用类型在查询时判定

- **备选**：
  - A. 会话表加 `usage_type` 列，写入时决定。
  - B. 查询时用 `flow_type` 加 `EXISTS (linsight_session_version.session_id = chat_id)` 判定。
- **选定**：B。
- **原因**：需求说「类型依据查询时已有记录判定」，一条日常会话后来产生任务版本就要变成任务模式。A 需要在任务版本写入时回写会话，还要回填历史。`EXISTS` 不放大行数；`JOIN` 会让多版本会话在列表和总数里重复。`linsight_session_version.session_id` 有索引。
- **规则**：
  - `flow_type = 5` → 助手会话；`10` → 工作流会话。
  - `flow_type` 为 15、20、25、30：有版本 → 任务模式，没有 → 日常对话。
  - `get_session_list` 的类型白名单从 5/10/15 扩到 5/10/15/20/25/30，不含 35（HOSTED_APP）。
- 列表行和导出行带 `usage_type` 字段，值为 `daily` / `assistant` / `workflow` / `task`。分页后对本页 `chat_id` 批量查一次版本存在性，不逐行查。
- **分层**：`get_session_list` 现有的 `select(MessageSession)` 拼装留在 legacy service，不搬家。本期新增的子句（类型条件里的 `EXISTS`、组织条件）和「本页哪些 `chat_id` 有版本」的批量查询，由 `chat_session/domain/repositories/audit_session_repository.py` 提供。service 只负责组合，不新写 ORM（C1）。
- **何时重新考虑**：任务模式需要按版本状态（如仅成功的任务）细分时，或列表规模让 `EXISTS` 成为瓶颈时，再考虑落库列。

### 决策 8：会话详情的范围校验点

- **选定**：
  - `GET /api/v1/session/chat/messages/{conversationId}`（日常、任务、知识空间、频道详情）：先取 `message_session`，按其 `tenant_id` 和 `operator_dept_id` 用与列表相同的范围判定，不通过返回 `UnAuthorizedError`。会话不存在也拒绝。
  - `GET /api/v1/session/chat/history`（助手、工作流详情；构建页调试也经 `historyAdapter` 走它）：会话 `user_id` 等于当前用户时放行（AC-38）；当前用户在 `markappuser` 中被分配到含该会话应用（`flow_id`）的标注任务时也放行；否则同上校验。会话不存在时不校验，原函数本就返回空列表。
    - 标注人放行（实现期补充，2026-11-03 用户确认）：前端 `getChatHistory` 的 `indexOf` 判断让标注页 `/label/:id` 也走这个端点，标注人通常没有日志菜单，只按审计范围校验会把标注功能挡掉。
  - 校验写在这两个 endpoint 调用的审计专用函数里，不写进 `ChatSessionService.get_chat_history`，因为 `/api/v1/chat/history` 也调它。
- **原因**：AC-37、AC-38。
- **被否**：只在列表加范围。详情接口现在只要登录就返回消息，改参即可读到范围外的会话。
- **何时重新考虑**：日志页详情改走专用的审计详情接口时，校验随之迁移，原接口恢复原样。

### 决策 9：用户组身份不再授予审计访问

- **选定**：删掉三处「用户组管理员」分支：`_resolve_audit_groups`、`get_session_list`、`get_all_operators`。入口改为决策 4 的身份判定。用户组筛选保留，只做缩小。
- **原因**：需求 2.2.1，Spec Discovery 确认接受现网行为变化。
- **被否**：保留用户组管理员入口、只加部门范围。需求明确用户组身份不授予审计访问。
- **何时重新考虑**：产品重新要求「用户组管理员可审计所管组」时，作为独立授权项加回，不混进部门范围。

### 决策 10：运行记录的部门范围

- **选定**：
  - `runtime_audit_scope.resolve_scope` 在现有判定后调用决策 4 的范围函数，结果存进 `AuthorizedRuntimeAuditScope` 的新字段 `dept_scope`。
  - `RuntimeAuditRepository.statement` 和候选查询按 `dept_scope` 加条件。
  - 导出任务的 `job_scope` 每次都会重新调用 `resolve_scope`，所以列表和导出口径一致。
  - `dept_scope` 进入 `digest()`：范围变化后旧游标失效。导出不靠 `check_snapshot_scope`（它只比对冻结的应用列表），而是按执行时重新解析的范围取数；导出过程中范围变化时，`run` 循环里现有的 `current != scope` 比较会终止任务。
  - 只对审计菜单入口（无 `app_id`）解析部门范围；全局超管和租户管理员 `dept_scope` 为空即不限；带 `app_id` 的请求走应用自己的 `audit_read` 授权，不加部门条件（实现期补充）。
  - CSV 的 `operator_dept_path` 为空时按 `operator_dept_id` 写「未记录」「无所属部门」「不适用」，与 AC-10 文案一致。
- **原因**：前端只对 `admin` / 子管理员显示该页签，但后端 `resolve_scope` 也放行只有审计菜单的人，并按可编辑应用限制。不加部门条件，这些人直接调接口就能拿到其他部门的记录（AC-20）。
- **被否**：因为页签隐藏就不加条件。
- **何时重新考虑**：`resolve_scope` 改为只放行全局超管和租户管理员时，`dept_scope` 恒为不限，可以删掉。

### 决策 11：前端组织面板做成一个共享组件

- **选定**：在 `platform/src/pages/LogPage/components/OrgFilter/` 新建一个组件，三个页签共用：触发器加弹层，内含搜索、懒加载多选树、历史组织平铺列表、「包含下级部门」开关、「清除所选」和「确定」。数据源只用 `GET /api/v1/audit/departments`。
- **原因**：需求图 04；现有 `TreeDepartmentSelect` 是单选，也没有历史组织和下级开关。
- 「确定」只把选择写进页面草稿筛选，点「查询」才生效（AC-26）。
- **被否**：扩展 `TreeDepartmentSelect`。它被组织管理等页面使用，加历史组织和下级开关会改变那些页面。
- **何时重新考虑**：其他页面也需要「历史组织加下级开关」时，再把组件上移到 `components/bs-comp`。

---

## 4. 系统现状（接手必读）

### 4.1 写入数据流

- **系统操作**：业务代码 → `AuditLogService._*_log` → `AuditLogDao.insert_audit_logs`（同步）；结构化动作 → `AuditLogDao.ainsert_v2`（异步）。
  - 三个 DAO 方法在 `add` 前调用 `org_snapshot.stamp_audit_logs` / `astamp_audit_logs`，只填两列仍为空的行。经 DAO 或 `open_api_call_audit_service.enqueue` 写入的构造点（含 `open_api` 中间件、`open_mcp`、`guest_link`）不再单独盖章。
  - 直接 `session.add(AuditLog(...))` 的 5 处在 `add` 前调用 `astamp_audit_logs([entry])`：`credential_repository` 3 处、`app_secret_repository`、`personal_skill_service`。
- **应用使用**：12 个构造点 → `MessageSessionDao.insert_one` / `async_insert_one`。这两个方法已经在这里补 `group_ids`，组织快照在同一处补。之后的更新不改这两列。
- **应用运行**：三个构造点调用同一个快照函数：
  - 模型调用：在后台批量写入器 `ModelCallRecordWriter._write_record_batch` 里整批解析（实现时从 `_start_record` 挪过来：`_start_record` 在网关请求热路径上，同步查库会阻塞事件循环；写入器本来就在同处批量补 `credential_mask`，快照时间晚于请求不到一个刷新周期）。只认 `subject_kind` 为 `user` / `natural_person` 且 `subject_id` 有值；`subject_id` 为空时留空，不要用 `actor_id` 或 `resource_owner_user_id`。
  - 访问记录 `app_access_log_service.record_access`：用 `user_id`，放进函数已有的 `try`，这个函数约定永不抛出。
  - 能力调用 `capability_audit.record_retrieval`：`subject_kind` 为 `user` 时用 `subject_user_id`，查询放进已有的 `try`；其余写 `-1`。

### 4.2 查询数据流

- **系统操作**：`GET /api/v1/audit` → `AuditLogService.get_audit_log` → `_prepare_audit_query`（身份、租户、范围）→ `AuditLogDao.get_audit_logs(..., dept_predicate)`。导出 `/audit/export/data` 走同一个 `_prepare_audit_query`。操作者候选 `GET /audit/operators` → `get_all_operators` 也加范围。
- **应用使用**：`GET /api/v1/audit/session` → `AuditLogService.get_session_list`（直接拼 `select(MessageSession)`）。加组织条件、使用类型条件和类型白名单；返回的 `AppChatList` 增加 `operator_dept_id`、`operator_dept_path`、`usage_type`。导出 `/audit/session/export/data` → `get_session_messages` 循环调 `get_session_list`，自然沿用。
- **运行记录**：`/api/v1/app-runtime-audit/records/{kind}` → `router.filters()`（白名单，拒绝未知键和重复键）→ `normalize()` → `RuntimeAuditRepository.statement`。
  - 新增 `dept_ids`（逗号分隔整数）、`include_descendants`、`include_none`、`include_unrecorded`（字符串 `true` / `false`）；`filters()` 和 `normalize()` 都要改。
  - `FIELDS` 三组都加 `operator_dept_id`、`operator_dept_path`。
  - CSV 由 `csv_bytes(FIELDS[kind], ...)` 直接写值，组织列在导出时换成文案。
- **会话详情**：见决策 8。

### 4.3 字段与取值约定

| 字段 | 类型 | 说明 | 消费方 |
|---|---|---|---|
| `operator_dept_id` | int，可空，索引 | `NULL` 未记录 · `0` 无所属部门 · `-1` 不适用 · `>0` `department.id` | 筛选、范围、列表、导出 |
| `operator_dept_path` | varchar(1024)，可空 | 发生时名称路径，如 `总公司/研发部/平台组`；哨兵行为空 | 列表、导出展示 |
| `usage_type` | 响应字段，不落库 | `daily` / `assistant` / `workflow` / `task` | 应用使用列表、导出 |

- 五张表都加这两列：`auditlog`（`AuditLog` 的实际表名）、`message_session`、`model_call_record`、`app_capability_call_record`、`app_access_log`。
- 展示文案三语 key：`log.org.unrecorded` / `log.org.none` / `log.org.notApplicable`。

### 4.4 模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `database/models/org_snapshot.py`（新） | 快照解析（同步、异步、批量）、`build_dept_predicate`、哨兵常量 | 不判断身份，不导入 domain |
| `department/domain/repositories/audit_dept_repository.py`（新） | 闭包、候选树节点、归档列表、名称路径的查询 | 不做身份判定 |
| `department/domain/services/audit_dept_scope.py`（新） | 身份 → `AuditDeptScope`；候选接口的业务逻辑 | 不写 ORM |
| `chat_session/domain/repositories/audit_session_repository.py`（新） | 范围内会话发起人去重查询；使用类型的 `EXISTS` 子句；本页会话的版本存在性批量查询 | 不判断身份 |
| `api/services/audit_log.py` | 三页签编排、入口判定、使用类型、详情校验 | 不再有用户组管理员分支 |
| `api/v1/audit.py` | 新参数、两个候选接口 | — |
| `chat_session/api/endpoints/session.py` | 两个详情接口调用范围校验 | 不改 `ChatSessionService.get_chat_history` |
| `app_governance/...` | 运行记录的参数、范围、列、导出文案 | 不改启用条件 |
| `platform/.../LogPage` | 组织面板、组织列、使用类型、动作映射、文案 | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `database/models/` 禁止导入 `domain/`（RULE-2），审计 DAO 就在这一层 | 快照解析写进部门领域服务后，DAO 无法调用；硬导入会被 arch-guard 拦下 | 快照函数放 `database/models/org_snapshot.py`，只用已有部门 DAO |
| 2 | `UserDepartment.id` 是成员关系主键，部门主键在 `department_id` | 快照记成随机数，筛选全错 | `org_snapshot` |
| 3 | `department.path` 是 `/1/2/3/` 主键路径，不是名称 | 列表显示数字串 | 批量换名 |
| 4 | 服务账号和系统触发都写 `operator_id = 0`；开放接口会话 `user_id` 是兼容值 | 服务调用被记到某个人的部门，扩大部门管理员范围 | 决策 3 |
| 5 | 直接 `session.add(AuditLog(...))` 的只有 5 处：`credential_repository` 3 处、`app_secret_repository`、`personal_skill_service`。中间件和 `open_mcp` 只入队，`guest_link` 自己调用 `ainsert_audit_logs` | 在入队文件里再盖一次章，或漏掉这 5 处，新行显示「未记录」 | 决策 2；守卫认快照函数、两个 DAO 插入方法和 `enqueue` |
| 6 | 旧函数 `_user_has_log_web_menu` 已删除。它对租户管理员直接返回真 | 把租户管理员当成「只有审计菜单」，范围收成主部门 | `AuditDeptScopeService._has_audit_menu`；租户管理员在决策 4 第 1 步就是不限 |
| 7 | 部门接口 `_aget_user_scope` 拒绝只有审计菜单的用户 | 组织面板对菜单角色报错 | 决策 6 |
| 8 | 运行记录 `filters()` 拒绝未知键和重复键，且只拷贝固定的六个键 | 只改 `normalize()` 时参数被拒绝或丢失 | `router.filters()` |
| 9 | 查询串里的 `"false"` 是真值字符串 | 取消「包含下级」仍然展开 | 只接受 `true` / `false`，在解析处转布尔 |
| 10 | `RuntimeAuditPanel.tsx` 的列是按 kind 写死的数组，不读 `FIELDS`；空值显示 `log.runtime.unknown` | 后端加了列，页面没有；`0` / `-1` 显示成数字 | 前端列和单元格渲染 |
| 11 | `useAppLog` 只对 `flow_type === 15` 把应用名换成「日常对话」 | 把 20/25/30 并进去，知识空间和频道名称丢失 | 前端保持只对 15 |
| 12 | `get_session_list` 对 15 的应用名送 `FlowDao` 查 | 20/25/30 送去查会得到空名 | 只对 5/10/15 查，其余用 `flow_name` |
| 13 | 应用使用 CSV 是前端按消息行拼的，会话在 `item`，消息在 `msg` | 组织和类型取自 `msg`，全为空 | `useAppLog/index.tsx` |
| 14 | `AppChatList` 是独立响应模型，未声明的字段会被丢掉 | 接口和导出拿不到组织列 | `api/v1/schema/chat_schema.py` |
| 15 | `api/v1/audit.py` 的参数逐个写在签名上 | 只改 DAO，页面传了也不生效 | 签名和前端 `buildAuditParams` / `getAuditAppListApi` / `exportCsvDataApi` 同步改 |
| 16 | 5 个旧动作的文案 key 是原样的 `log.eventTypeEnum.<event_type>`，不走 `actionToI18nKey` | 文案 key 写成驼峰，显示原始值 | 三份 `bs.json` |
| 17 | `getActionsByModuleApi` 现在用字符串包含判断模块 | 选「系统」时工具和沙箱进不去；选「知识库」时混入知识空间 | 显式映射表 |
| 18 | 快照查询在 Celery 或系统触发下可能没有租户上下文 | `NoTenantContextError` 导致每行「未记录」 | `bypass_tenant_filter()` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

**新增**

- `GET /api/v1/audit/departments`
  - 参数：
    - `parent_id`：int，可省。省略时返回顶层和归档列表。
    - `keyword`：str。非空时忽略 `parent_id`，在闭包内平铺匹配名称、`dept_id`、`external_id`。
    - `tenant_id`：int，可省。经 `_resolve_tenant_scope` 处理。
    - `limit`：1–200，默认 50。
  - 返回 `data`：`{active: Node[], archived: Node[], show_none: bool, show_unrecorded: bool}`。
  - `Node`：`{id, dept_id, external_id, name, path_name, parent_id, tenant_id, has_children}`。
- `GET /api/v1/audit/session/users`
  - 参数：`keyword`、`limit`。
  - 返回 `[{user_id, user_name}]`，与 `/audit/operators` 结构相同。

**扩展参数**（省略时行为与现在相同）

- `GET /api/v1/audit`、`/audit/export/data`、`/audit/session`、`/audit/session/export/data`：
  - `dept_ids`：重复参数，int。
  - `include_descendants`：bool，默认真。
  - `include_none`、`include_unrecorded`：bool，默认假。
  - `/audit/session` 两个接口另加 `usage_type`：`daily` / `assistant` / `workflow` / `task`。
- `/api/v1/app-runtime-audit/records/{kind}`、`/candidates/{dimension}`、`POST /exports`：
  - `dept_ids`：逗号分隔。
  - `include_descendants`、`include_none`、`include_unrecorded`：取值为 `true` / `false`。

**响应新增字段**

- 系统操作行、应用使用行、运行记录行都加 `operator_dept_id`、`operator_dept_path`。
- 应用使用行另加 `usage_type`。

**行为变化**

- 用户组管理员（无审计菜单）调用上述接口改为拒绝。
- 应用使用列表新增 `flow_type` 20/25/30 的行。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `UserDepartment.is_primary`、`department.path` / `status` / `tenant_id` | 数据契约 | 部门模块改路径格式（结尾 `/`）会让前缀匹配误命中 |
| `DepartmentDao.aget_user_admin_departments` | DAO | 部门管理员定义变化直接改变审计范围 |
| `linsight_session_version.session_id = message_session.chat_id` | 数据契约 | 任务模式识别依赖它 |
| `SessionSubject.stamp` 写 `api_subject_type` | 数据契约 | 开放接口会话识别依赖它 |
| `_UI_VISIBLE_V2_ACTIONS` 与前端 `V2_ACTIONS` 锁步 | 既有锁步测试 | 17 类可查依赖白名单 |

---

## 7. 测试与可观测

- **后端单元**（`test/audit/`）：
  - `org_snapshot`：哨兵规则、成员关系主键陷阱、名称路径、异常留空、批量。
  - `build_dept_predicate`：前缀带结尾 `/`、包含与不包含下级、归档、两个固定项、与闭包求交、受限用户丢弃固定项。
  - 范围解析：五类身份，以及租户管理员兼部门管理员。
  - 守卫测试：直接构造 `AuditLog(` 的文件都调用了快照函数。
- **后端集成**（SQLite fixture 沿用 `test/audit` 现有 `audit_session`）：
  - 系统操作、应用使用列表和导出的组织筛选，部门管理员和菜单角色的范围。
  - 使用类型的四类加多版本去重；20/25/30 进入列表。
  - 两个候选接口。
  - 两个详情接口的范围与本人放行。
  - 运行记录参数解析与范围。
  - 用户组管理员被拒。
- **迁移**：`test/database/test_alembic_single_head.py`。
- **前端**（Vitest，沿用 `LogPage/*.test.tsx`）：
  - 组织面板交互：确定后不立即查询、清除、重置。
  - 模块到动作的映射、5 个旧动作文案。
  - 组织列三种哨兵文案。
  - 日常、助手、工作流、任务的路由，20/25/30 进日常详情。
  - CSV 列。
- **E2E**：`/e2e-test`，按 spec AC 走 API 层，用非管理员账号验证范围（`src/backend/AGENTS.md` 已知坑：管理员会短路权限）。
- **手动验证**：
  1. `cd src/backend && uv run alembic upgrade head`，启动后端（:7860）和 platform（:3001）。
  2. 准备三个账号：租户管理员；部门 A 的部门管理员，并授予含「审计」菜单的角色；部门 A1（A 的下级）的普通用户，也授予含「审计」菜单的角色。
  3. 用普通用户在工作台发一条日常对话、建一个任务，再用管理员改一次沙箱配置。
  4. 进入 `/log`，逐个页签检查：组织列文案；组织面板的搜索、「包含下级」、归档项；使用类型筛选；导出 CSV 的列。
  5. 换部门管理员，确认只看到 A、A1 的记录；换普通用户，确认只看到 A1 的记录。
  6. 拿范围外的 `chat_id` 直接请求 `/api/v1/session/chat/messages/{id}`，应被拒绝。
- **可观测**：快照失败打 `logger.warning("audit org snapshot failed ...")`，按这句日志检索失败率；没有新增指标。

---

## 8. 后续改进 / 不打算做的事

- 历史组织回填：本期不做。如需要，另写 `scripts/` 运维任务按当前主部门回填，并明确标注为「回填」。
- 应用使用页的用户组列仍显示用户当前用户组，筛选仍用会话上的 `group_ids` 快照，本期不统一。
- 部门很多时，组织面板顶层的懒加载按 `limit` 截断；超出时提示用搜索。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-03 | 初版：以 `docs/审计功能优化方案.md` 为基础；列名改为 `operator_dept_*`；会话快照从 ORM 钩子改为 DAO 收口；范围计算移到部门领域 | Spec 确认后进入 design |
| 2026-11-03 | 实现核对：直接盖章改为 5 处（入队和 `guest_link` 走 DAO）；删除 `_user_has_log_web_menu`，菜单判定改到 `_has_audit_menu`；表名写明 `auditlog`。决策 8 增加标注人放行；决策 10 改为导出按执行时范围取数，带 `app_id` 不加部门条件 | T016 审查：design 与代码偏离 |
| 2026-11-03 | 决策 5：闭包拆开写。`admin_paths` 用 path 前缀子查询；`exact_ids` 用主部门 id 的直接 `IN` | T016 第二轮：原文把两段都写成闭包子查询 |
