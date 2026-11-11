# Design: 管理租户一致性与策略角色生效

**关联**：[已确认 spec.md](spec.md) · [版本契约](../release-contract.md)\
**版本**：v3.1.0-beta1 / F009\
**基线**：`codex/3.1.0-beta1/managed-tenant-bugfix`，`24c02859e2582ed319281bb52285c99930daf81c`。\
**状态**：技术设计已评审（SDD LGTM、独立架构复核PROCEED），待用户确认；本文件描述基线现状和拟实现目标，不表示已修改业务代码。\
**规格确认**：2026-11-10 用户回复“确认规格，继续设计”。\
**最后更新**：2026-11-10。\
**评审**：[SDD结果](design-review.md) · [检查依据](design-review-evidence.md) · [独立首轮](design-architecture-critique.md) · [独立复核](design-architecture-critique-v2.md)。

## 1. 目标与非目标

将账号身份、管理目标、组织业务归属、资源归属和预算责任分开，使六条管理创建/编辑路径正确，并让角色、菜单、配额及异步恢复采用同一可验证政策。用户策略变更必须同时处理绑定终止、当前消费者和可恢复的失效传播。优先质量属性依次为隔离正确性、失败可恢复性、兼容影响可判定。

非目标沿用 spec §1.2：不提供普通多租户身份、不增加部门来源授权、不做通用计费/恢复引擎、不改FGA模型或资源PDP、不自动修生产数据，不在本轮部署。QA参考用例和tasks在设计确认后生成，当前不把它们标成已完成。

## 2. 关键约束与分层

遵循 [constitution.md](../../../docs/constitution.md) C1–C8，引用而不重定义其规则。本特性新增约束：

- 只有一个当前主属H。普通角色E与平台super、租户/部门管理员身份分别解析，后者不由E推断。
- M来自管理准入；B来自有效挂载和根部门；S只是部门存储位置；O来自已验证资源/定义；T是本次冻结执行目标。绑定写H，资源写T，菜单关联写定义O。
- `UserRole`目前没有来源、状态和唯一的“每部门授予”。不补造历史来源；终止绑定采用受控删除并在业务操作记录保留前后事实，不让旧行因范围扩大再次生效。
- 普通额度是检查快照，允许轻微并发超额；用户/角色政策变更和复制幂等则需要版本、锁与明确恢复，不将两种保证混为一谈。
- 权限模块已有持久投影账本，但没有公开的业务恢复查询门面；新增窄应用协议复用其冻结计划，业务模块不能查询权限ORM或重造tuple。
- 下文标为“拟新增/拟扩展”的类、字段、接口和任务当前不存在。设计不依赖未部署的新FGA模型，也不增加默认启用的新顶层配置。

### 2.1 依赖方向

`Endpoint → 所属业务Service → 所属Repository → DB`。跨域调用通过 `user.application.policy`、`role.application.definitions`、`department.application.business_scope`、`permission.application.lifecycle`、`dsh.application.policy_refresh` 等拟新增窄协议；API/worker组合根装配实现。core只提供已有ContextVar/数据库能力，不导入这些业务实现。

角色Repository只拥有角色定义/菜单查询；用户Repository拥有绑定和人员策略操作；组织协议返回授权后的当前成员/挂载事实。角色定义更新通过用户应用端口请求逐人绑定变更，不在role Service拼接用户/部门ORM。共享的纯计算DTO和判定函数放所属应用层，不引入任意动作注册的“政策引擎”。

## 3. 关键决策与被否方案

### D1：按用户主属解析E，分开读取定义

- 备选：重写LoginUser.tenant_id；放宽所有Role/UserRole DAO；所有成员部门角色并集。
- 选定：`load_effective_policy(user_id, verified_home)`返回当前主属内合法绑定，再通过定义协议读取合法全局/本租户定义和菜单，组织协议验证作用域。身份管理员资格独立。
- 原因：现有管理ContextVar与认证归属本就分离，原观察已复现环境过滤让相同绑定时有时无；全局定义共享不能扩大绑定范围。
- 重考虑条件：产品正式引入普通用户多租户执行身份，并同时定义可信切换/凭据/预算/缓存契约。

### D2：终止绑定而非保留失效行等待复活

- 备选：仅在E里临时过滤；新增每部门来源账本；把旧绑定搬到新H。
- 选定：成员、角色作用域和H变更均通过用户策略变更协议。失去资格的普通绑定在受控事务中删除，操作记录保存终止原因和前后快照；之后的新合法授予是新事件。全局/无作用域直接角色在同H离部门时保留。
- 原因：AC-09、AC-10、AC-12已确认不允许旧行隐式复活，而现有表不能表示部门来源。前端本身也按人/角色共享选择。
- 重考虑条件：明确要求按授予来源独立撤销；届时另立来源化授权及历史LEGACY处理，不把本操作日志当来源账本。

### D3：先封闭、再提交、再传播，完整成功才返回成功

- 备选：修改绑定后只清Redis；用token_version承载所有政策版本；跨数据库/Redis/FGA做假定的全局事务。
- 选定：SQL保留独立政策代次与进行中操作；复用既有部门投影、身份同步及DSH用量结算，为普通政策单独补齐按人版本化刷新协议（§4.3.3），不把现有单模型direct接口冒充该能力。业务事务不持锁调用外部系统；失败留进行中状态并前向恢复，读者对其依赖的未收敛政策拒绝，不能按空角色降级。
- 原因：SSO/调岗现有路径已经跨多个提交；普通LegacyRBACSync对非AdminRole直接返回，不能证明缓存或DSH已同步。
- 重考虑条件：集中验证证明现有版本化传播可提供更小的同等正确协议；不能仅为减少新字段移除持久状态。

### D4：ORM计量加明确的未知错误，不重造额度账本

- 备选：在raw SQL后拼接未经验证的tenant；统计异常回0；统一所有quota的MAX；用分布式锁解决所有问题。
- 选定：受影响指标迁为Repository内的ORM计量，在已验证T的strict执行范围读取；明确指标的责任人、单位、去重和父对象。真实0/空集合与统计失败不同；普通检查比较增量和独立剩余。
- 原因：已运行观察证明raw user count跨租户、剩余与累计混比；上传MIN、flags OR和DSH allowance又是不同合同。
- 重考虑条件：普通配额需要严格无超额时，为具体指标设计预留，不修改本批并发保证。

### D5：业务pending先于权限投影，恢复原冻结计划

- 备选：只改tenant后继续commit/refresh/hook；用权限CURRENT代替资源可用；每次重试重新从当前授权生成复制计划。
- 选定：业务先持久化pending资源和所属意图，确认提交后再调用现有权限adapter。意图保存可公开查询的稳定权限幂等key；异常后先查原账本，存在则恢复原计划，不另生成计划。业务READY必须晚于权限CURRENT及所需审计。
- 原因：super会短路资源权限，不能拿FGA门禁单独保护半成品；当前父提交后refresh失败和复制源/目标残留均已实跑。
- 重考虑条件：业务与权限应用已有公开的完整创建协调协议可等价替代；仍不能把权限模块变成业务ORM读者。

### D6：复制operation/outbox与逐项映射，外部不确定写隔离重试

- 备选：依赖Celery task_id/acks_late提供恰好一次；出现异常就删目标；在可能auto-id的向量库里盲目重插同一批。
- 选定：knowledge自己的复制operation和copy_item；同意图只产生一个目标及稳定文件/QA映射。worker每个尝试使用隔离外部命名空间；向量写结果未知时废弃该尝试并换新命名空间重建，胜出尝试通过SQL条件发布。旧尝试只有隔离写，不得发布或改源状态。
- 原因：现有worker只有局部去重/异常捕获，外部索引不共享SQL事务；未验证的auto-id upsert不能承诺幂等。采用重建成本换取初版正确性，不提前建设增量复制引擎。
- 重考虑条件：目标存储和所有消费路径实证支持稳定主键/条件upsert后，再优化为可证明的分片续跑。

### D7：严格新规则上线前先盘点，不静默兼容错误归属

- 备选：读时把所有旧绑定改成H；先部署严格读再处理数据；初始化时全局补写。
- 选定：独立只读影响报告与部署前置核对；已确认非法不恢复，不明确归属不自动搬迁。需要的数据修复另行授权；源码交付不等于可直接启用或部署。
- 原因：SSO在Root+bypass中先重建角色后sync H，既有行tenant可能是历史归属也可能是写错，列值不能独自证明用户意图。
- 重考虑条件：权威历史和运维批准给出确定映射时，另行提供受控修复步骤；不在DDL中读写旧数据。

### D8：重叠操作在修改业务事实前解决冲突

- 备选：各角色先改一批用户再等待其他操作；一次长事务锁住全部人员；全平台政策变更串行。
- 选定：领域批量操作先预留全部受影响用户，冲突时在任何绑定/拓扑改变或DSH封闭前退出；完成全部预留者才可进入APPLYING。用户只能属于一个父操作；§4.3.1定义跨事务规则。
- 原因：角色A/B共享人员时，SQL锁顺序无法避免持久pending互相等待。现有操作体积未知，分批预留比无界长事务或全平台串行更合适。
- 重考虑条件：真实负载显示频繁冲突影响可用性，再引入有确定先后顺序的领域队列；本批不建设通用调度器。

## 4. 系统现状与拟实现数据流

### 4.1 已核实基线

| 链路 | 当前实现及失败点 | 本次变化 |
| --- | --- | --- |
| 管理范围 | `admin_scope.py`准入后设置management_tenant_scope，不改登录H | 复用准入，业务目标协议冻结T；不扩大管理前缀到个人quota/info |
| 角色保存 | 首次单条查询允许global，事务内重查/RoleAccess仍被M过滤 | 定义Repository统一解析，定义O内修改/查重/菜单，合法范围内flush/refresh |
| 人员绑定 | 部门候选按操作者tenant；UserRole写入无显式H；同一人角色在多个下拉重复展示 | 部门B与目标H双校验；统一人员策略事务，跨租户兼属只维护组织字段 |
| SSO/迁移 | SSO绕过过滤且设Root，重发全部默认；两种主属入口分别降旧主属或删除旧关系，后置sync | 保留各入口原组织关系结果，不悄悄统一为一种；共用前后事实校验、种子差集、H与政策收敛流程 |
| 菜单/配额/审批/DSH | 不同查询有时bypass、有时环境过滤；审批异常可吞掉，DSH无匹配不限 | 所有普通政策消费者接同一E；故障不转为空；身份/资源授权仍独立 |
| 工具/工作流 | 错写账号H；工具父子分两次提交；workflow主和v0落不同租户 | 资源T显式继承，父子单SQL事务，权限/审计完成前pending |
| 知识复制 | 文档建库helper覆写H并初始化索引；QA不覆写H但同样缺投递前补偿 | 拆SQL预留/权限/外部准备/复制发布，复用现有KnowledgeState加操作占用 |
| 投影恢复 | `ProjectionService.reconcile_operation`可从已持久tuple还原计划，但业务无窄应用门面 | 新增生命周期receipt/inspect/resume应用协议，内部复用现有服务，非直接业务查权限表 |

基线现状及运行限制仍见[核查报告](../../../docs/reviews/managed-tenant-investigation-20261110.md)和[边界梳理](../../../docs/reviews/managed-tenant-boundary-assessment-20261110.md)。以下全部是拟实现目标。

### 4.2 正常读与管理写的目标协议

拟新增 `department.application.business_scope`：`resolve_verified_department_scope(dept_id, actor)`返回 `VerifiedDepartmentScope(department_id, business_tenant_id, storage_tenant_id, ancestor_ids, context_version)`。先检查部门管理权限，再有界读取其祖先、挂载与租户根指针；最近有效业务边界必须一致，无效/断链/循环拒绝，不复用登录解析器跳过禁用挂载的Root回退。事实提供器可读取跨存储租户祖先，但不扩展资源许可。

**另设** `read_subject_policy_facts(VerifiedPolicySubject)`：只接收认证/受控内部流程签发的主体引用，返回该主体当前成员、祖先、B/H和拓扑版本，不要求普通成员拥有部门管理权；不能接收外部任意dept_id扩展查询。E使用此受限事实reader，管理候选/最终管理写使用前述resolver。两者共享边界纯计算，不共享授权前置条件；内部候选事实仅由持有相应父操作预留的服务端协议返回。

拟新增 `user.application.policy`：

- `load_effective_policy(user_id, verified_home)`及sync等价入口，读取权威active UserTenant、用户状态/进行中标记、该人普通绑定、合法定义/菜单及当前作用域事实。普通调用只可处理已验证主体；任意HTTP user_id/P不能当可信范围。
- 读定义使用role应用协议，限定精确角色ID，global与本租户自定义分支分别校验；不从“Root可查到”推导合法。无作用域直接角色不要求成员部门来源。
- 返回不可变 `EffectivePolicySnapshot`：`user_id, home_tenant_id, policy_generation, role_versions, role_ids, role_quotas, web_menu, menu_modes, fingerprint`。fingerprint包含H、成员/定义版本；无跨请求常驻E缓存。
- 真实无角色可返回空E并应用已确认默认。合法绑定缺定义、依赖不可读、FENCING及之后的在途变更或事实不完整报24006/24008，不能返回空集合；RESERVING阶段按§4.3.1读取稳定旧事实。已明确非法旧行只输出受控诊断，不暴露外国定义名称。
- 平台身份用既有身份协议；兼容 `LoginUser.user_role` 时平台AdminRole仍来自独立确认的身份事实，不把E整体覆盖成导致is_admin失效的列表。服务账号与受限凭据保持既有PermissionActor，不拼装自然人角色。
- 在一次调用中复用纯计算结果，sync和async共享纯判定函数，分别用其数据库入口，不在已有事件循环里同步等待async。

管理写T通过已准入的scope与业务授权确定。后台从持久operation读T并绑定 `tenant_execution_scope(T)`；上下文管理器不是授权接口。global角色管理的O可以是Root、M可以是Child，仍只放行已授权平台super维护global定义；普通租户定义和人员政策写要求目标与其业务范围匹配。

### 4.3 人员策略变更、种子及终止

拟新增 `UserPolicyMutationPort`，由user领域实现，所有绑定生产者调用，不让DAO自己推测tenant。输入为已授权 `UserPolicyChangeIntent`：操作ID、目标用户、预期政策代次、前后H/成员事实版本、拟增删角色及原因、操作者引用。旧接口未带预期代次时服务器在受理阶段读取并冻结；不能跳过最终重读。

1. 先计算最终成员、主属、组、角色与B/H，完成所有资格检查和只读影响预览；跨租户角色参数在姓名/组/成员提交前拒绝。外籍兼属返回 `policy_editable=false`、`role_apply_status=NOT_APPLICABLE_CROSS_TENANT`；前端不提交角色字段。
2. 保留本地编辑“删除旧主属”和canonical服务“降为兼属”的既有组织结果，但二者必须提交明确前后成员集合，经同一政策计算器处理，不能在嵌套DAO中先提交再悄悄继续。
3. SQL预留用户policy_transition_id和操作，重读H/成员/定义版本；写冲突按24007重试或返回。锁顺序统一为角色定义ID升序→用户行ID升序→本操作的关系行稳定顺序；组织owner事务适配到同一UoW，不持数据库锁调用DSH/FGA。预读角色集合在拿用户锁后变化则整个事务重试，不能遗漏新绑定。
4. 若DSH启用，按§4.3.3先持久注册并封闭受影响用户的旧gate（H迁移还包括新租户分区），并取得版本化确认，再提交改变角色资格的SQL；外部故障时只留下可恢复意图，不先改变政策后靠清缓存追赶。
5. 业务SQL原子完成本操作可共同提交的成员/UserTenant/绑定/代次/审计事实；需要部门投影时复用既有预记录与绑定协议。H迁移保持用户token_version失效、管理选择清理和PAT既有政策；H/投影不完整期间敏感政策读拒绝，不猜Root。
6. 只对真实新增成员差集或新H激活产生默认种子。SSO重建同快照不是新事件。幂等事件由操作ID+目标代次+新增部门集合确定，操作重放不重复增删或重发种子。
7. 普通绑定显式写目标H。作用域失去最后合法支持、H迁移离开旧租户或角色定义使其不合法时，删除该份绑定并将完整逻辑键/原因记入操作；AdminRole不参与此删除。之后扩大范围/回迁只检查现有绑定，不恢复旧快照；新合法授予可产生新绑定。
8. 提交后以新代次传播DSH策略/epoch（不重置已用量）、菜单/身份相关缓存与审计；所有必需效果确认后清进行中标记、操作SUCCEEDED。失败留RETRYABLE/REAUTH_REQUIRED/REPAIR_REQUIRED并停止依赖决策；不能因为LegacyRBACSync无动作就认为已完成传播。

正常用户操作与角色/部门父操作共用§4.3.1的预留规则；父操作未发布前，子操作不得自行清除用户标记。

`user.application.policy`还提供受控 `inspect_policy_change` / `retry_policy_change`。重试校验当前操作者资格、原目标及预期版本；已提交SQL只恢复未完成效果，不按旧快照覆盖更新。正常新操作遇到该用户进行中操作返回24008及operation_id。后台恢复不能提升原操作者资格。

### 4.3.1 持久预留与重叠操作（拟新增）

Role与Department批量操作均使用 `RESERVING → RESERVED → FENCING → APPLYING → PROPAGATING → SUCCEEDED`。`user_policy_transition`记录typed parent_ref（ROLE_CHANGE或DEPARTMENT_CHANGE）、用户和预期代次；User.policy_transition_id是该用户唯一预留。没有全平台锁，也不持SQL锁跨外部调用。

- RESERVING只读旧事实、预留及冻结扫描上界，不删除绑定、不改变拓扑、不调用DSH封闭。角色标记只禁止该定义新增授予/编辑；部门标记禁止涉及其冻结子树的新成员/移动/挂载。正常读可用已确认旧快照；全部预留成功并CAS进入FENCING之后，受影响读才拒绝。
- 按用户ID升序分批CAS预留。发现其他操作占有用户，或候选用户依赖另一个RESERVING角色/拓扑时，**不等待**：本父操作转ABORTING_RESERVATION，CAS释放仅属于自己的用户预留，最后清自身角色/部门标记，终态CONFLICT（24007）。此阶段尚无政策副作用，不能调用恢复绑定。API/worker不能无限自动重建票据争抢；调用者重新读取再明确提交。
- A/B共享用户、扫描方向相反时允许一方或双方预留失败，绝不允许两方持有部分用户后进入APPLYING。已进入FENCING者只依赖稳定旧定义及自己的候选；后来RESERVING的冲突方退出，不能把其pending变成当前执行者的依赖。若进程退出，原票据先完成释放，不新建操作越过孤立预留。
- 全部预留完成后禁止出现新受影响绑定/成员；变化入口重读父标记与用户预留，并校验定义/成员事实版本。父操作的用户列表、游标、阶段持久化，不能以每次当前查询结果丢掉已终止者。
- 普通E能读RESERVING的旧事实，但不能使用候选；FENCING后需拒绝。候选reader只接受内部已验证的预留收据，读取本父操作的新事实及其他已提交旧定义；公共operation_id不构成许可。SQL阶段完成后，子操作停在WAIT_PARENT；父定义/组织发布及所有效果确认后父操作才逐项CAS释放，释放可重入。
- 进入FENCING后不再因冲突回滚绑定。失权/故障转明确恢复状态，必要时由具有原领域管理权的人员按当前资格接管原票据，重新审计授权；不冒用原主体，不扩展目标。新接管者无资格则保持封闭。预留前失败可安全取消；业务SQL已提交后只能前向收敛或受控修复，不能恢复已终止授予。

### 4.3.2 部门树/挂载变更的完整生产者（拟新增）

当前 `DepartmentService.move_department`在路径提交后仅best-effort同步主部门用户（`department_service.py`原1621/1651）；这不等于本设计的政策完成。需要新增department所属 `department_policy_change`，保存原/目标子树及挂载版本、全部相关用户扫描边界/预留游标、逐人操作收据、部门投影收据、阶段和错误；Department增加 `policy_operation_id`。本领域协议与角色共用用户预留端口，不把部门ORM交给user或permission写。

纳入生产者：手工部门move/archive/delete、SSO部门upsert/reparent/archive、租户根部门挂载/解除/重新挂载，以及直接成员增删和两种主属更改。Tenant拥有挂载记录，其应用UoW端口提交挂载；Department拥有拓扑，其端口提交路径；user拥有H/绑定。组合流程使用同数据库UoW，域外不直接读写这些ORM。

变更先锁定涉及旧/新根的版本和子树边界，阻止新的相关拓扑与成员写；从变动子树的**全部成员关系（主属+兼属）**、受影响角色作用域和挂载边界生成去重用户集合。成员事实、祖先路径或B变化均要算影响；不能只调用sync_subtree_primary_users。真正跨H者处理迁移，H不变的兼属者也必须处理最后作用域支持及绑定终止。

全部用户预留且DSH旧分区已封闭后，才提交拓扑/挂载事实与既有部门投影durable binding。逐人使用冻结新事实执行§4.3，原合法绑定只保留或终止，不因移回恢复旧行。部门投影CURRENT与人员政策完成是两个条件；所有H/策略及传播都收敛后清父操作，方可报告组织变更完整成功。进程在拓扑提交后退出，父操作记录全部待处理人并继续扫描/恢复；不能依赖下次登录补齐。SSO相同拓扑事件幂等，遇进行中返回明确恢复状态。

部门归档即使现有规则要求无成员，仍需校验作用域引用及后代/挂载影响；无影响才可走空集合快速路径。批量预留冲突依§4.3.1在拓扑修改前退出，已提交拓扑后不做反向数据恢复。普通政策事实reader检查其成员祖先上的父操作阶段，避免只检查当前节点而漏掉在途祖先。

### 4.3.3 DSH普通政策刷新桥接（拟新增，不是现有能力）

已核实活跃 `dsh/runtime.py::read_policy` 使用UnifiedPolicyRepository；其输出版本来自ModelVisibility.version，相同可见模型下角色额度变化不改变版本。既有 `QuotaRedis.install_policy` / `lua/policy.lua`是单模型direct版本+1协议，**不直接复用为普通角色刷新**。保留其结算和direct版本语义，另设以下窄协议。

`dsh.application.policy_refresh`提供 `prepare_refresh(VerifiedPolicyTransition)`、`fence_refresh(receipt)`、`install_refresh(receipt,candidate)`、`finish_refresh(receipt)`及inspect/resume。DSH复用自己的DshAdminOperation新增action=REFRESH_POLICY（DDL更新action约束），PersonalLedgerState扩展 `subject_policy_generation`、`pending_refresh_operation_id`；操作payload保存父引用、from/to H、预期/目标generation、完整模型集合、共享额度、候选fingerprint、effects和lease。新User.policy_generation是业务代次，DSH subject_policy_generation是**每个(T,user)分区独立**的提交代次，两者显式记录映射，不与direct_version、quota_epoch或ModelVisibility.version混用。

1. prepare在短SQL事务锁该(T,user)账本并设置持久pending，幂等key绑定父操作+用户+T。与现有direct UPDATE_POLICY/RECONCILE_USAGE/DSH重分配等按人有冲突的操作共用账本准入：新方不得占有已pending的分区；预留阶段冲突即拒绝，不能各占一边后等待。已有direct操作先完成，普通政策尚未改变时才能重新受理；普通刷新占有后direct新操作拒绝。所有相关生产者都要接入此准入。
2. fence使用DSH新Lua在用户hash slot登记 `SUBJECT_POLICY_SYNC:<operation_id>`、lease_generation、expected/target subject generation；这是全模型阻止新admit/probe的block，不能用单模型POLICY_SYNC。重复同key可确认，旧lease不能覆盖/释放。已admit请求仍按原T、原request/epoch结算；保持旧租户账本与结算依据，不因H迁移删除已接收请求的责任事实。
3. SQL业务资格改变前，所有涉及分区的fence必须确认。H迁移先按T升序预留旧/新分区，无任意等待；任一冲突则在业务变化前释放自己的未提交预留；已封闭项按原代次显式恢复旧合法政策后释放。无旧gate不能按新用户0用量初始化：经既有完整账本恢复证明后封闭；恢复未知则停止。
4. install只替换本操作冻结的完整可见模型集合、credit_rate和共享monthly_token_limit及目标generation，不加总各模型共享额度；不重置used、running、usage stream、quota_epoch或direct_version。模型/额度候选由受控E候选协议+当前DSH政策生成，fingerprint含User/Role政策代次、成员/拓扑版本、ModelVisibility和CreditRule的稳定ID/版本/值，不再只对可见版本求和。
5. Lua admit（包含dynamic与unmetered路径）必须比对调用时的subject generation且检查全模型block。封闭前读取的旧快照，即使封闭后才调用，也因generation不匹配而拒绝；已admit可继续结算。DSH普通read_policy拒绝在途，恢复使用专用候选收据。现有direct接口仍保留direct版本，不借ordinary刷新改写direct行。
6. SQL与Redis恢复均保留pending：`DshUsageRepository.automatic_recovery_snapshot`输出按人refresh收据，AutomaticQuotaRecovery恢复block/目标代次；不能只遍历model rows的pending_operation_id。即使零可见模型也保留按人pending。健康检查、快照完成CAS及Lua recovery finish均验证持久refresh；Redis清空/重建不能把在途用户恢复成可admit。父操作发布确认且install收据一致后，DSH先完成SQL目标代次再按owner+lease+generation清自己的block；任何不确定维持不可用，同票据重试。

DSH未启用时显式记录该效果NOT_APPLICABLE，不伪造成功回执。现有ModelVisibility/CreditRule管理写也必须与受影响分区的refresh协调：规则写入先登记受影响人员刷新/版本冲突，刷新候选在finalize重验；不得在候选冻结后静默发布新规则。额度匹配MAX及无匹配不限不变，故障/未收敛绝不是“无匹配”。

### 4.4 角色定义和菜单的原子/批量变更

Role/RoleAccess修改归role领域Repository。按已授权定义O在一个SQL事务中完成查重、字段、菜单替换和必要refresh，commit前可回滚；未提供字段保留，显式null清部门作用域、显式空菜单清菜单。读取定义菜单不放宽其他AccessType。

对影响政策的作用域、quota或菜单变更，拟新增 `RolePolicyChange`记录冻结的旧/新定义、预期版本、最大绑定扫描边界、游标和效果进度。Role挂进行中ID，禁止新的该角色授予或另一政策编辑插入；依§4.3.1区分RESERVING可读旧事实与FENCING后不可用，不能暂时忽略该角色而回默认。名称/备注单独修改且不影响政策时无需此流程。

- 先按§4.3.1完成全部受影响用户预留，冲突退出不得先删除一批绑定。角色作用域修改持久影响计划，再按有界批次（初始100人）读取绑定，逐人经用户政策端口验证最终成员关系与新作用域。仍合法的保留；失去资格者终止。跨H或归属不明旧数据先进入待核查，不因遍历就自动修复。
- 全部预留完成后先按§4.3.3封闭全部受影响DSH，再按批提交绑定变化/子操作阶段；内部消费者使用本操作已验证的候选快照，不以普通读绕过进行中门禁。普通路径不能传一个operation_id就取得候选权限。
- 所有绑定处理完，角色新定义/菜单同事务发布（仍为pending，不对普通政策读开放）；角色标记与各用户标记在必要效果确认前保留。DSH新策略、审计及缓存效果完成后释放标记，才向调用者报告完整成功。
- 小集合请求内推进到终态；未完成返回24008和票据，前端轮询，不把“开始处理”显示为保存完成。失败保留阶段和已完成批次，可在同票据前向恢复；不回放已删除绑定为旧状态。
- 角色删除同样先处理绑定及消费者；不复活F048已退役的RoleAccess资源授权，也不触碰资源Grant。

### 4.5 配额：责任、计量和错误

拟新增 `VerifiedQuotaContext(actor_ref, budget_user_id, policy_tenant_id, target_tenant_id, metric, delta, resource_ref)`，只由拥有该业务的服务构造。普通个人额度要求P=H(q)=T；super、系统/凭据、存储、DSH按现行专门策略处理，不通过伪造H满足等式。

| 指标/场景 | 责任及计量 |
| --- | --- |
| workflow/assistant/tool等本人创建 | q为创建人，个人统计(q,T)，租户统计T，Root链只聚合有效子租户 |
| channel资讯源新增 | q沿当前合同为channel.user_id，资源T为频道O；对(q,T)范围全部频道的source ID并集去重，delta为尚未计入的新ID，不按编辑者或当前频道条数计费 |
| 空间/频道订阅 | q为订阅人，按容器业务租户及有效成员状态计量；成员身份枚举不是普通UserRole |
| 上传/存储 | 按现有上传者限制、容器存储责任和真实字节单位分别计量；角色GB限制、租户storage硬限制不混为创建条数 |
| 责任人已迁离T的旧资源增量 | 返回19405止增；合法读取、缩减、删除不调用增量额度检查。未真正交接计量责任时，只有FGA owner变化不能解除 |

受影响计量转换为ORM Repository，在 `tenant_execution_scope(T)` + strict范围执行，普通条件只含已验证user/父对象；避免新拼接raw tenant SQL。保留现有公共quota方法兼容薄适配层，逐调用者提供VerifiedQuotaContext，不从裸int推断授权；根链聚合逐节点绑定其自己的T。

数量：独立检查 `user_used + delta <= role_limit` 与每层租户剩余容纳delta；不限单独处理。`available=min(max(role_limit-user_used,0), each_tenant_remaining)`。上传MIN、flags OR和DSH allowance不调用数量MAX聚合。读取失败抛19404并记录失败指标/操作ID，不能返回0或空集合；展示整体不可用，不让部分失败表现为余额充足。统计成功的0仍是正常值。

`/quota/effective`保留旧字段含义，新增 `available` 和 `usage_state=AVAILABLE`；统计未知时整个响应返回19404并给 `usage_state=UNAVAILABLE`，前端保留上次数据只作旧值标识，不能仍显示可用余额。`/quota/usage`同样不得假0。检查使用明确上限/增量，不把旧effective用于写入判断。普通quota无严格并发预留；DSH和应用容量协议不改。

### 4.6 工具和工作流创建

分别拟新增tool/workflow领域的创建操作表，不引入公共资源恢复引擎。业务资源增加 `creation_state` 与 `creation_operation_id`，历史行DDL默认READY（上线前仍需排查历史半成品，不能由默认值证明其合法）。新创建显式PENDING。

1. 在业务Service冻结T、真实actor及请求摘要，完成schema/菜单/配额校验。现有workflow预期管理头继续检查；工具现有POST不在本批无声新增必填头，新恢复写入口则必须防陈旧管理范围。
2. 同一SQL事务预留操作、插父和非空children或flow/v0，全部显式继承T，flush/refresh后commit；子记录失败整体回滚。commit不确定先按请求键查询结果，不直接再插。
3. 资源和意图已确认持久化后调用现有权限adapter，传入提前保存在意图中的稳定幂等key；操作记录保存receipt。权限CURRENT后追加同事务可追溯审计事实，最后CAS发布业务READY。该顺序符合权限最终化与业务可用性的先后，业务pending不代表SQL已正式可用。
4. 任一异常返回对应业务模块的pending错误及operation_id，不无条件删除父记录；恢复先通过权限应用协议inspect既有key，已存在则resume原冻结计划，禁止因请求重试重建新的tuple计划。
5. 所有正常Repository列表/详情/版本/导出、tool executor及workflow运行/队列入口检查父资源READY，位于super/资源授权短路之前。恢复读取是领域内精确operation绑定的专门方法，不接受公共include_pending参数绕过。
6. 创建worker/dispatcher默认celery队列推进该领域到期操作；API请求可内联推进，失败进周期恢复。新操作可选Idempotency-Key，旧调用缺省由服务生成；失败响应票据由前端保留，重复同票据恢复，不靠名称猜测复制意图。同名pending查重返回其票据，避免用户反复创建同名不可用资源。

### 4.7 权限生命周期应用门面（拟扩展，当前不存在）

新增 `permission.application.lifecycle`，暴露 `LifecycleProjectionReceipt`、`inspect_lifecycle_projection`、`resume_lifecycle_projection` 和稳定key生成协议。内部使用已有ProjectionRepository/ProjectionService及Owner状态finalize，业务模块不导入它们。

- 创建/复制adapter接受可选显式idempotency_key；旧调用默认语义保留。业务预留时即保存该key和不可变目标，只有业务SQL确认存在后才首次调用投影。
- 结果含 tenant、key、目标type/id、投影operation_id、state、目标权限版本；inspect必须匹配全部范围和CURRENT Catalog/store/model，不只按一个数字ID查询。
- 请求失败但receipt未写回时，按保存的key找原账本；若存在，从tuple账本还原计划并reconcile，不能重新从当前源授权生成计划。若不存在且业务意图仍合法，才允许首次生成；并发由现有幂等唯一约束协调。
- 权限CURRENT与业务READY分开。自动权限恢复只推进已经有持久业务预留的操作；业务意图和父记录在结果不确定期间不得被删除。终止新资源需先走权限delete及其账本，再做外部清理/SQL撤销。
- FAILED_CLOSED不由业务retry强行重发：门面报告REPAIR_REQUIRED，使用已有权限检查/受控恢复流程验证冻结计划后续办。禁止创建新key跳过失败闭锁。

### 4.8 文档/QA复制状态机与数据幂等

复制不再调用会覆写H和提前初始化索引的同步create_knowledge_base。当前路由通过菜单/读权限并检查source PUBLISHED及无在处理文件；新编排在同一SQL事务内锁源、保存源原状态/时间和冻结manifest、预留唯一目标UNPUBLISHED、设置源COPYING及 `copy_operation_id`，操作为RESERVED。目标tenant=源O=合法T；不符在任何写前拒绝。

`KnowledgeCopyOperation`本身持久化投递意图（`dispatch_state/next_attempt_at/task_id`），不用再单设第三份通用outbox。状态及恢复：

| 阶段 | 动作 | 失败/重入处理 |
| --- | --- | --- |
| RESERVED | SQL资源、源占用、请求key、清单已提交 | 结果不确定按同key读；不得建第二目标 |
| PROJECTING | 现有adapter复制授权；记录稳定权限key | 先inspect/resume原账本；不因异常删目标；FAILED_CLOSED转REPAIR_REQUIRED |
| PREPARING | 准备可重建外部尝试namespace与审计事实 | 只接续本operation；没有权限CURRENT不投递复制任务 |
| DISPATCH_PENDING | operation行内的投递意图持久化 | Broker失败保留；发送成功但确认失败可重复发，消费者领租约 |
| COPYING | worker读取copy_item映射复制数据 | 单项失败不标全部成功；不确定外部写换尝试重建；SQL目标映射复用 |
| VERIFYING | 清单/校验和/文件、QA、向量数量及必要动作资格检查 | 不完整留失败/可重试；不能只凭task返回发布 |
| SUCCEEDED | CAS发布胜出attempt索引/对象引用、目标PUBLISHED，释放本操作源占用 | 目标、operation终态与源释放同业务事务；重复finalize返回同结果 |
| RETRYABLE_FAILED / REAUTH_REQUIRED / REPAIR_REQUIRED | 可诊断错误、已完成进度、lease及下次尝试 | 可重试项周期续办；资格失效须重新授权/取消，不能使用super替原actor补权限 |
| CANCELLING / CANCELLED | 停止派发，封闭发布，撤销已投影目标后安全清理 | 仅按本op清理；未知运行attempt隔离留manifest，不猜测已停或盲删 |

worker每次只携operation_id，消息header携可信T；入口要求有效header并和持久operation一致，不沿用普通任务缺header回Root的兼容。每次尝试使用新的attempt_uuid、lease_token与单调lease_epoch。初始租约120秒、每30秒续约，SQL变更/发布均CAS operation状态、epoch和token；该数值是实现默认，不是超时后可以安全清理的证明。

copy_item逻辑唯一键 `(operation_id,item_kind,source_id,source_revision)`，记录源不可变校验摘要、目标file/QA ID、对应attempt进度。目标SQL行首次分配与映射同事务，重放查询同映射，不再分配第二行。目标业务不可用期间，文件状态写也必须验证操作租约；旧worker不能在目标发布后覆盖元数据或源状态。

外部尝试namespace按tenant、operation、attempt隔离，源对象版本/摘要冻结并复核。MinIO相同尝试的固定对象键可按校验和确认；向量写结果未知时不往同一可能auto-id集合重插，改新尝试重建。只有胜出epoch可将其index/collection/object引用发布为正式目标；旧attempt迟到写入无正式引用，也无权发布。旧namespace保留在operation manifest中，确认其worker主动结束后再清理；无法证明停止时保留受控隔离，不能仅以租约过期删除。

源恢复只更新 `copy_operation_id==本op` 且仍为本op占用的COPYING行；不会覆盖下一次复制或后续合法修改。源内容在占用期间的正常写入/解析/导入入口受业务门禁保护；受理前排除在处理文件，冻结清单中源版本变动则失败，不把新旧内容混复制。源资格和当前actor在投递/执行/发布前复核；纯浏览器关闭或会话自然到期不撤销已受理意图，禁用、身份版本/主属变化及失去必要权限会停止推进。恢复采用服务端保存的受理主体引用，不能由目标owner构造一个替身actor。

### 4.9 拟新增持久结构与迁移

| 所属领域/结构 | 关键内容 | 约束/用途 |
| --- | --- | --- |
| user：`user_policy_transition` | operation_id、tenant_id、user_id、请求key/摘要、from/to H、目标代次、前后事实版本、增删绑定、审计与DSH效果步骤、状态、租约、错误 | 按人变更/种子/迁移的恢复记录，不是部门授予来源；幂等键非空 |
| department：`department_policy_change` | 原/目标拓扑/挂载版本、全员扫描边界/游标、预留/子操作及投影收据、阶段 | 包含兼属人员；发布组织事实前预留，进程退出后继续完成 |
| role：`role_policy_change` | 角色O、role_id、旧/新定义、预期代次、binding扫描边界/游标、关联用户操作、状态和效果进度 | 序列化定义政策变化，支持大绑定集合批次，不产生任意工作流 |
| tool：`tool_creation_operation` | T、请求key/摘要、tool_type_id、真实主体引用、权限key/receipt、状态、审计步骤、租约/重试 | 父子SQL与创建恢复；不存api_key或schema密钥 |
| workflow：`workflow_creation_operation` | T、请求key/摘要、flow_id、主体引用、权限key/receipt、状态与恢复步骤 | 对应workflow创建，不接管通用flow其他类型的产品语义 |
| knowledge：`knowledge_copy_operation` | 请求key/摘要、源/目标、T、真实主体、源占用/manifest、权限key、投递状态、attempt/lease、进度/错误 | 唯一目标和投递意图；源/目标/actor不可重试时变更 |
| knowledge：`knowledge_copy_item` | operation、kind/source/revision、稳定目标file/QA ID、校验和及尝试进度 | SQL唯一映射；拒绝不同清单伪装同请求 |
| User拟扩展 | `policy_generation`（默认0）、`policy_transition_id`（nullable） | 全局身份行上的政策版本和临时封闭标记，不改变H定义 |
| Role拟扩展 | `policy_generation`（默认0）、`policy_operation_id`（nullable） | 稳定定义版本，不能用秒级update_time替代并发版本 |
| Flow、GptsToolsType拟扩展 | `creation_state`（旧行默认READY）、`creation_operation_id`（nullable） | 资源可用性在权限短路前检查 |
| Department拟扩展 | `policy_operation_id`（nullable） | 拓扑/挂载政策父操作，祖先范围读取须检查 |
| DSH既有表拟扩展 | PersonalLedgerState的subject generation/pending；DshAdminOperation的REFRESH_POLICY action约束 | 沿用DSH账本，不新建第八张刷新表；零模型也能持久封闭 |
| Knowledge拟扩展 | `copy_operation_id`（nullable） | 精确源占用，避免无条件恢复覆盖后续动作 |

新独立表依现有模型发现/create_all；上述已有表加字段走独立DDL revision。幂等唯一约束只放新operation/item表，userrole旧数据不加未经去重的唯一约束，不在migration扫描/修复旧行。JsonType/LargeText及时间字段用既有跨DB辅助；原生标识和PK在集中MySQL/DM8验证，新增数值ID用SQLite测试可兼容类型，不以SQLite代替双DB验收。

ID/序列化约定：operation_id/request_id/parent_ref中的操作ID为UUID字符串；actor/user/tenant/resource原生ID沿既有类型，HTTP按现有DTO序列化。phase表示流程步骤，status表示PENDING/PROCESSING/SUCCEEDED/RETRYABLE_FAILED/REAUTH_REQUIRED/REPAIR_REQUIRED/CONFLICT/CANCELLED等可观察结果，两个字段分离；每域只接受其状态机列出的合法组合，不建立共享动作执行器。时间用既有UTC存储约定；fingerprint为稳定排序、规范JSON的SHA-256，不能含凭据。新表按相应状态/next_attempt_at、parent_ref/user、业务目标建立索引；逐人预留通过User行CAS唯一持有，不依赖可空唯一键的跨DB差异。

H迁移的user操作tenant_id固定为受理时旧H（首次激活则新H），from/to明确记载；不能随执行到新H而修改账本归属。状态接口按已验证本人或合法管理范围精确定位，不能用当前H过滤掉本人进行中票据。平台恢复扫描由受控系统组合根分页枚举到期操作的tenant/key，再逐项绑定严格T执行；不能仅在Root环境默认扫描而漏子租户，也不能把跨租户扫描能力开放为HTTP旁路。

### 4.10 周期恢复、可用性与启用顺序

- 用户/角色/部门政策及工具/工作流创建恢复在默认celery队列；knowledge复制在knowledge_celery。API/worker组合根注册相同应用协议。拟新增扫描任务每60秒取到期操作，每批100项；超时只重领/隔离，不能视作回滚已经发生的外部效果。
- worker使用原操作key和版本，重试退避上限1小时，达到自动尝试阈值进入明确人工恢复状态而不丢意图。必需传播未完成不返回SUCCEEDED；持久恢复记录本身即为审计事实，独立审计日志通过拟新增审计应用UoW追加协议与操作同数据库事务提交并绑定record_id，避免提交未知后重放成第二次业务变更。
- 新规则切换前只读盘点先行：严格E前后差异、H/S/B不一致、来源不明绑定、角色/菜单归属错位、旧半成品及在途复制。新READY字段默认值不能替历史资源做合法性背书。未裁决歧义前不直接部署严格读；运维修复需另行授权。
- 复制升级需维护窗口暂停旧复制受理、排空/核对旧任务与旧worker，再启用新task名；不能新worker读旧消息就假装有完整operation。保留旧历史查询，不由新业务代码自动补造旧复制意图。
- 本批不增加顶层yaml键、不以临时全平台bypass开关切换政策。数据库结构升级、应用/worker同版本、预检与人工恢复顺序写入交付runbook；不编码一次性全局HTTP维护门禁。

### 4.11 审计与模块责任

现有 `AuditLogDao.ainsert_v2`自行新开session并commit，不能直接用于声称“审计与领域操作原子”。拟新增 `audit.application.records::append_in_uow`（sync/async适配），审计owner构建/stamp AuditLog并使用调用方UoW，不自行commit；同事务在领域operation写入audit_record_id。提交结果未知先查operation中的record_id，不以元数据模糊查重，也不新增全局审计唯一约束。本特性相关动作从旧后置插入改接该协议，避免再追加一份；其他旧调用不改语义。

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| user应用政策 | E、按人绑定/主属变更、预留与种子 | 不拥有部门拓扑、角色定义或资源授权 |
| role/department所属编排 | 定义/组织父操作、影响扫描及所属事实发布 | 不直接改其他域ORM，不提供通用编排语言 |
| dsh应用刷新 | 按人gate代次、模型/额度发布与账本恢复 | 不重置用量，不决定角色资格 |
| quota应用 | 已验证责任与T内计量、独立余额 | 不授予权限，不预留所有普通额度 |
| permission应用生命周期 | 原冻结投影查询/恢复及Owner finalize | 不查询业务ORM，不决定业务READY |
| tool/workflow/knowledge | 本域目标、pending消费面及恢复 | 不自行拼FGA tuple或代替其他资源的状态机 |
| audit应用追加 | 同UoW构建/stamp审计记录 | 不代业务决定变更，不私自commit |

## 5. 已知坑与处理位置

| 坑 | 不知道会怎样 | 处理处（拟） |
| --- | --- | --- |
| M与H不同，before_flush不改显式错误tenant | 请求报错但数据已落错误租户 | 目标协议、工具/flow创建Repository、真实ORM回归 |
| Department存储tenant仍可能Root | 子租户目录/DSH候选为空或取错角色 | business_scope协议，OrgDirectory/DSH部门消费者 |
| global Role能读不等于RoleAccess/UserRole可同scope读 | 保存修好但登录菜单/配额仍丢失 | 定义协议与E分别读取 |
| 普通LegacyRBACSync不传播政策 | 删角色后DSH旧gate/审批标签继续生效 | 用户策略operation及DSH应用效果 |
| 源或目标投影可能已生效但调用抛错 | 重建计划/删目标破坏冻结账本 | lifecycle inspect/resume协议 |
| super短路权限、旧worker可直查子对象 | pending资源进入正常执行 | 业务READY检查置于授权短路前，消费面清单全接入 |
| 文件/QA与向量可能只有部分成功 | task返回后把缺失数据当全部成功 | copy_item清单验证、尝试隔离与原子发布 |
| GB校验注释写999但生产允许99999 | 顺手收紧已合法配置 | 保留执行条件，spec AC-20及边界测试 |
| 原生count异常返回0/空集合 | 统计故障反而放行扩容 | 计量Repository统一19404 |
| 同H多部门下拉共享一条绑定 | 为UI造重复来源，或误删另一个合法支持 | 同一用户policy事务、前端共享提示/作用域判定 |

## 6. 对外契约、接口与依赖

### 6.1 HTTP与前端契约（拟）

正常成功仍用现有UnifiedResponseModel，不把待恢复操作包装成已完成资源。新pending错误的data包含 `operation_id,state,retryable`，不返回原始异常、SQL、向量地址或主体凭据。

| 接口/字段 | 变化及消费者 |
| --- | --- |
| 现有 `/roles` CRUD/menu及部门人员接口 | 路径不变；响应可增加 `policy_generation,operation_id,policy_editable,role_apply_status`。新前端携预期代次，旧写入无代次由服务器冻结并最终重验；进行中返回24008 |
| `GET /api/v1/roles/operations/{id}`、`POST .../{id}/retry` | 新增，先静态路由后动态role_id路由；必须具有该角色/人员策略管理资格；global定义按平台维护权限，普通目标匹配具体范围。retry增加精确预期管理头保护 |
| `GET /api/v1/user/policy-operations/{id}` | 本人只读状态（或有权人员管理者），不是任意user ID查询；个人读不随M |
| `GET /api/v1/departments/policy-operations/{id}`、`POST .../{id}/retry` | 部门/挂载父操作状态及恢复；按该组织操作原管理资格与目标授权，重试校验当前资格/精确预期管理头；预留阶段可受控取消，事实提交后仅前向恢复 |
| `/quota/effective`、`/quota/usage` | 旧字段保持；effective新增available/usage_state；未知统计19404，前端明确不可用而非假0 |
| `/knowledge/copy`、`/knowledge/qa/copy` | 路径不变，新增**必填UUID request_id**，同一意图重试复用。缺失/非法10994且源/目标不变；不同摘要重用10995；此为明确管理写契约升级，同批更新全部已查到平台调用者 |
| `GET /api/v1/knowledge/copy-operations/{id}`、`POST .../{id}/retry`、`POST .../{id}/cancel` | 显式状态/恢复；请求人或合法目标管理者可查看，写操作还要原意图及当前资格；管理员不能替失权原actor补权继续复制。不是普通pending资源详情绕过 |
| `/tool/operations/{id}`、`/workflow/operations/{id}`的GET/retry | 归所属业务Service核对T、原意图和当前资格；正常资源详情不能因此增加公共include_pending |

复制UUID由 `platform/controllers/API/index.ts::copyLibDatabase/copyQaDatabase` 调用者产生，在KnowledgeFile/KnowledgeQa复制对话的一次意图内保存，网络失败/重试不换key，用户主动另建复制才新key；关闭对话不自动取消已受理任务。此前已查到调用者只有这两组平台路径，未查到v2复制路由；落地前再扫一次。旧v1调用脚本须升级，不能在服务端用名称/时间猜“同一次复制”；该兼容变更随本设计确认，不隐式降级AC-33。

前端使用现有组件/通知和query失效机制；角色共享绑定提示、跨租户只读原因、pending票据与quota不可用状态都要i18n三语。新增操作在切M后不能把旧响应写入新视图。Client不增加普通切租户能力，用户信息与DSH主体变化继续通过既有同步通道刷新。

### 6.2 内部输出与消费面

| 应用协议/结果 | 生产者 | 消费者 |
| --- | --- | --- |
| EffectivePolicySnapshot及sync等价 | user，调用role/department窄协议 | LoginUser/info/入口选择、菜单断言/申请模式、Quota、ApprovalGate标签、OrgDirectory、DSH UnifiedPolicy及同步适配 |
| VerifiedDepartmentScope / SubjectPolicyFacts | department/tenant所属实现，管理resolver与受限事实reader分别授权 | 前者管理候选/最终写/OrgDirectory；后者E/DSH本人政策事实 |
| UserPolicyChangeIntent/结果 | 本地/旧user创建、默认、SSO、成员退出、两种主属变更、部门移动/归档/挂载及SSO树变化、role定义变更 | user所属UoW、政策worker、DSH/审计/缓存效果 |
| VerifiedQuotaContext和计量结果 | 所属资源Service | quota应用/计量Repository，不能由外部body直接构造 |
| LifecycleProjectionReceipt/inspect/resume | permission应用门面 | tool/workflow creation及knowledge copy领域，不让这些模块查询权限ORM |
| DshPolicyRefreshReceipt / subject generation | DSH应用刷新，候选来自受控E及当前DSH定义 | Lua admit/probe、direct准入、Redis恢复、父操作效果确认 |
| 创建/复制持久操作与阶段 | 各所属业务Service | 本域worker、状态UI、审计、受控重试；不作为其他资源的通用操作语言 |

个人菜单授予/撤销仍由approval owner负责；其grant/revoke和审批延迟执行必须先验证当前H及用户政策预留，通过拟新增approval应用UoW端口与相应政策代次/审计一起提交，不能从UserService直接写UserMenuAccess。迁移不搬运个人grant到新H；独立个人grant按自身租户、active/revoked及审批生命周期读取，UserRole的终止日志不冒充其来源账本。相关延迟动作不得以旧申请租户覆盖当前H资格。

资源Grant、个人审批任务资格、平台super、租户管理员解析继续走其既有应用协议，不把E接到PDP ALLOW短路。审批动态role标签故障不得降为regular_user免审，审批人来源resolver语义不变；实施若改审批公共逻辑须同步approval-module技能对应章节并跑跨场景回归。

### 6.3 拟新增错误码

已在当前 `common/errcode/*.py` 按真实Code字面量核对以下候选未占用，并在发布契约登记为F009设计预留；实现前再次检查。统一复用项目错误处理，不返回Exception字符串。

| 模块/码 | 名称及行为 |
| --- | --- |
| 24006 | PolicyUnavailable：政策事实/定义不可确定，不能退为空策略 |
| 24007 | PolicyVersionConflict：预期代次/事实已变更，重新读取后提交新意图 |
| 24008 | PolicyTransitionPending：已有进行中操作，返回票据 |
| 24009 | PolicyScopeMismatch：目标H/B或普通绑定范围不合法，无部分写入 |
| 19404 | QuotaUsageUnavailable：必需统计未知，拒绝增量，展示不可用 |
| 19405 | QuotaResponsibilityChanged：个人预算责任与资源T不一致，止增 |
| 10994/10995 | CopyRequestInvalid / CopyRequestConflict：缺失UUID或同key不同意图 |
| 10996/10997 | CopyPending / CopyFailed：持久阶段/错误票据，区别受理、可重试和终止 |
| 15090/10590 | ToolCreationPending / WorkflowCreationPending：资源仍不可用于正常执行 |

24003/既有资源拒绝用于无操作资格，不借新错误暴露外国对象。复制/恢复静态路由不包含config字样；新写操作登记精确method/path管理头检查，不扩大到共享读取或个人quota。

### 6.4 输入依赖及风险

| 依赖 | 风险与防护 |
| --- | --- |
| active UserTenant、主部门与当前用户状态 | 不唯一/无效/与进行中迁移不一致不能猜H；初始Root/访客使用原合法合同 |
| 部门projection CURRENT及挂载根指针 | S不等于B，版本/祖先不完整拒绝；不截取局部祖先作为完整事实 |
| 现有F048 Catalog/store/model与冻结账本 | 生命周期门面绑定全部目标和原key，模型不匹配不恢复；不更换Store或即时写模型 |
| DSH版本化政策/gate/epoch协议 | SQL政策完成不代表Redis门禁已更新；必须效果确认，不能重置已用量 |
| 同一业务数据库、Celery至少一次投递 | SQL事务不跨外部服务；意图先持久化，重复消息领租约且版本校验 |
| MinIO/ES/Milvus及当前RAG schema | 不假定auto-id支持幂等upsert；未知外部写换attempt、验证后发布 |
| 现有审计sink | 操作事实与sink记录关联到同一业务事务/步骤；未知提交重读，不报告假完整成功 |
| platform管理范围与复制调用者 | 必填UUID与pending状态是明确写契约更新；API/前端同批交付，不保留无key静默旁路 |

## 7. 验证、可观测与交付

### 7.1 适用测试层

- 纯计算测试：同一事实的E、作用域最后支持、默认差集、H迁移、新授予/旧行复活区别、MAX/MIN/flags OR/DSH独立、Quota增量和未知。
- SQLite真实ORM+HTTP集成：按已确认AC补到对应模块；角色定义/菜单关联同O、UserRole显式H、非空工具children、flow/v0、权限未知前后业务状态、复制SQL映射及所有正常消费者的pending拒绝。原观察脚本仍保留为缺陷证据，不移植其错误行为断言。
- 故障注入：计量失败不写业务、统计成功0、commit未知、权限receipt丢失、Broker发送后确认失败、worker租约丢失、旧attempt迟到、源占用变化、SSO同快照、定义缩小后扩大、DSH传播中断/零模型pending/Redis重建/旧快照迟到、重叠A/B角色相反预留与重启、兼属子树移出再移回、失权后恢复。
- 集中MySQL/DM8：新增DDL/新表发现、锁顺序/CAS/唯一幂等、事务刷新、跨批次角色变更、两请求争用最后普通名额（允许微超）、真实外部不确定写与隔离发布。不以SQLite通过宣称双DB正确。
- E2E覆盖API允许/拒绝配对，前端按仓库要求浏览器验证；QA八列表在设计确认后生成，不将本文的策略描述替代执行结果。

### 7.2 本机与环境复核

本机只用已有Python环境和临时空配置做隔离测试，不读取真实凭据。当前可复核命令：

```bash
cd /Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/src/backend
TEST_PYTHON=/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python
"$TEST_PYTHON" -c 'from pathlib import Path; Path("/tmp/bisheng-managed-tenant-review-config.yaml").write_text("{}\n")'
config=/tmp/bisheng-managed-tenant-review-config.yaml PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 "$TEST_PYTHON" -m pytest ../../docs/reviews/managed_tenant_investigation_20261110_repro.py ../../docs/reviews/managed_tenant_review_extra_20261110.py --asyncio-mode=auto -p no:cacheprovider -q
```

上述14项为已知缺陷观察，不是本设计验收；本轮只做设计，未重跑测试。实现期使用正式 `test/role/`、`test/user/`、`test/department/`、`test/quota/`、`test/tool/`、`test/workflow/`、`test/knowledge/` 等测试并在相同组合与旧基线比较。

真实环境手动步骤：在用户指定并批准的测试部署，用测试管理员创建A/B专用租户、A主属普通账号、B兼属和各自角色；确认A菜单/Quota不会因兼属B改变；缩小再扩大作用域验证不复活；超管H=A、M=B新建API/MCP/工作流并刷新详情/版本；复制文档/QA，注入投影/Broker/worker故障后用同request_id恢复，核对源、目标、文件/QA和向量内容；普通账号与super均验证pending不能执行。部署URL、测试账号、故障注入权限和中间件版本由测试环境准备，尚未提供，不使用真实生产账号代替。未完成时在验收记录标待执行。

### 7.3 可观测与恢复

结构化日志至少包含operation_id、domain、phase、tenant、actor_user_id、subject_user_id、policy_generation/lease_epoch、失败步骤及可恢复性，不记录schema密钥、原始token或敏感文档内容。状态接口只向有权者暴露票据、阶段、重试原因和必要进度。

只读CLI拟新增 `scripts/inspect_managed_tenant_policy.py`：默认仅输出绑定/政策/菜单/Quota/审批标签/DSH前后差异与历史资源检查，必须显式限定租户/用户范围；不提供本特性自动apply。恢复由领域状态入口及已批准测试/运维流程执行，copy FAILED_CLOSED还需现有权限受控修复流程。界面不给用户“删除数据库残留行”的操作。

## 8. 后续改进与不投入项

- 来源化策略授权、多租户执行身份、预算责任新交接能力各自是新产品能力；本批只提供已确认的直接策略、当前有效边界及旧资源止增。
- 复制在外部写未知时重建attempt，可能重新处理大量向量；先保证不重复发布和不破坏数据，再以真实负载决定稳定主键分片续跑。
- 大范围角色定义变更采用批次和pending，可暂时降低受影响人员可用性；先给出可见状态与前向恢复，不承诺跨系统瞬时线性一致性或任意规模无停顿。
- 不在本轮补齐所有全局tenant_filter局限或全部旧模块旁路；184模型分类是结构覆盖，不是全仓安全验收。
- tasks和QA参考用例将在本设计确认后生成；任何实现中推翻spec/本设计选定业务语义的偏差需重新确认，纯技术细节在此覆盖更新。

## 修订历史

| 日期 | 改动 | 触发 |
| --- | --- | --- |
| 2026-11-10 | 初版：已确认40条AC的技术落地、持久恢复和明确接口契约 | 用户确认规格并要求继续设计；无业务实现 |
| 2026-11-10 | 补齐全员部门生产者、按人DSH刷新、重叠操作预留、两类组织reader与审计UoW | 独立设计评审B1/B2/S1/S2及源码核对；不改变已确认业务AC |
