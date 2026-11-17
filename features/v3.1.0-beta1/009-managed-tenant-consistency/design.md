# Design: 管理租户缺陷的最小修复

术语说明：本文技术符号和英文状态值统一见[术语与缩写说明](terminology.md)；H为用户主属租户，M为当前管理目标租户。业务阅读可直接参阅使用中文全称的[影响范围与测试重点](../../../docs/reviews/managed-tenant-impact-test-focus-20261111.md)。

**版本**：v3.1.0-beta1 / F009。\
**状态**：2026-11-10按用户“最小改动、最小影响范围”重新收敛的设计；用户已确认“采用最小修复范围，继续开发”。业务实现及发布线集成本地回归已完成；用户已明确授权合并，真实环境验收仍待完成，见tasks.md。原设计的LGTM/PROCEED不适用于本稿。\
**进展**：[tasks.md](tasks.md)及[验证记录](verification.md)持续更新；已实现部分不代表全部验收。\
**集成状态**：2026-11-11按用户指示合并；已集成实际fetch的发布线df927a7f6e，保留F118/后台执行契约，单head已核实；真实中间件/浏览器仍待集中验收，见merge-validation.json。
**基线**：`codex/3.1.0-beta1/managed-tenant-bugfix` / `24c02859e2582ed319281bb52285c99930daf81c`。\
**需求**：[已确认的完整40条AC](spec.md)；本批保留/收窄/延期结果逐条见[范围调整](scope-revision.md)，不宣称零新表即可交付全部原AC。\
**审查**：[最小化独立复审](minimal-change-architecture-review.md)（针对原设计，REVISE）；[修订稿最终复核](minimal-change-architecture-review-v3.md)为PROCEED；[SDD检查](design-review.md)原剩余范围确认已由用户关闭；实现验证和未完成门禁见code-review，不套用旧LGTM。\
**历史**：[七表设计快照](design-full-recovery-superseded.md)，保留作取舍依据，不作为当前开发目标。

## 1. 目标与非目标

修正六条已核实的租户读写错误，补上会直接影响同一判定的角色、菜单和Quota读取/计量。优先保证租户边界正确、失败不扩大权限、变更面可控。

本批不建设角色/部门/用户多层恢复编排，不重构DSH结算和Redis门禁，不建设通用操作中心，不新增业务操作表。复制的全过程自动恢复、重启后逐项续传及外部恰好一次不在本批承诺内；这些是原完整规格的待延期部分，并非声称已由现有账本解决。

## 2. 关键约束

遵循[架构宪法](../../../docs/constitution.md) C1–C8。特有约束：

- H是权威当前主属；M是已授权管理选择；B是部门挂载业务租户；S是部门存储租户；O是资源/定义归属；T是验证后冻结的写入目标。H不随M改写。
- global仅共享角色定义，绑定按人员H；普通自定义角色只允许H内合法作用域。跨租户兼属仅产生组织事实，不发外国策略。
- 不修改全局tenant_filter、不新增全站bypass、不扩大管理中间件白名单。跨存储读取在owner Repository内限定精确主体/角色/部门，不把客户端tenant_id当授权。
- 不恢复RoleAccess的资源授权；WEB_MENU与F048资源动作分开。管理员身份独立保留。
- 普通quota仍为提交前检查，保留轻微并发超额合同。SQL与FGA/Redis/Celery不伪装成一个事务。
- 除下述三个已有业务表的四个小字段外，不新增持久结构；不把七表payload搬入大JSON字段冒充精简。

## 3. 选定方案与备选

2026-11-13增量决策及重新考虑条件见[第一阶段实现设计](#2026-11-13-第一阶段实现设计)：保持旧选择/数据库格式，采用窄入口修复，不引入全平台登记框架。

### D1：直接修正目标和局部查询，不改全局隔离框架

- 选定：目标在所属Service验证，事务内显式继承T/O/H；只给角色定义及WEB_MENU增加精确合法范围的读取方法。
- 否决：改LoginUser.tenant_id、统一放宽Role/UserRole DAO、把所有Root数据当共享。
- 证据：工具和workflow显式写H覆盖自动填T；角色单条查询允许global但事务内重查不允许，菜单关联又填M。
- 重考虑：产品正式提供普通多租户执行身份时另立设计。

### D2：少量公共判定函数，沿现有Service和Repository接入

- 选定：一个有效普通角色读取入口（sync/async共享纯资格判断），一个部门业务归属事实入口；复用现有身份、DAO和管理授权，不迁移整个模块目录。
- 否决：新增政策引擎、跨域动作注册器、每类变更一个后台父子状态机。
- 证据：多数缺陷来自同一事实被不同scope读取，不来自缺少调度框架；目前没有人员规模数据证明必须异步批量发布。
- 重考虑：测得同步事务的人员/绑定规模无法接受，且明确要求跨批次自动恢复时，另设计有界批次及持久意图。

### D3：父资源保存可用状态，权限继续用原账本

- 选定：Flow和GptsToolsType各加一个creation_state；PENDING先提交，权限确认后READY。权限key按已有资源身份确定，恢复原账本，不另建创建操作表/轮询任务/HTTP操作中心。
- 否决：SQL父提交后失败直接删除；用is_delete或已有发布status伪装创建pending；每种固定创建各建操作表。
- 证据：工具父子可同SQL事务；flow/v0本已同SQL事务。另有权限projection账本和ResourcePermissionMode，但super可短路权限，业务仍需可用性门禁。
- 重考虑：要求新建资源在进程重启后自动补齐审计/外部效果时，再论证持久调度；本批受控前向修复不假装自动完成。

### D4：DSH修读取，保留其账本与Lua合同

- 选定：现行ROLE匹配接入有效角色集合；政策读取失败向上传递；保留现有direct版本、额度MAX/无匹配不限、quota epoch和已用量。
- 否决：把普通角色修复升级为按人subject generation、全模型封闭、direct协调、Redis恢复重写。
- 证据：`dsh/runtime.py::read_policy`每次读取UnifiedPolicy；`model.py::complete`和`chat_credits.py::start`每次传入当前monthly_token_limit；QuotaRedis把该值传给Lua动态路径。不能笼统称“旧Redis gate使所有新请求仍用旧角色额度”。
- 边界：普通调用与round probe按现有合同执行月额度判断；已准入round内的unmetered子调用虽读取当前模型资格/政策，仍按既有合同跳过月额度比较，不因角色额度变化重新中断该轮。不能宣称每次子调用都会按最新余额拒绝。并发请求可使用决策时的已验证快照，不引入跨SQL/Redis线性化屏障；旧快照已读但尚未admit的严格撤权竞态不在本批解决。现有ModelVisibility版本不完整表达角色变化的审计问题另列，不修改结算事实。
- 重考虑：明确要求撤权瞬间连已读取的在途快照也失效，或集中实测发现后续新决策未读取新政策时，另立DSH专项。

### D5：复制记录最小关联，完整数据恢复另交付

- 选定：Knowledge增加copy_source_id和copy_target_id，源/目标SQL同事务关联，保留现有state；按目标ID诊断和受控处置，不新增copy operation/item表，不强制客户端UUID。
- 否决：不留关联只在异常时无条件恢复源/删除目标；把所有文件映射塞无限JSON；用Celery task_id证明恰好一次。
- 证据：现有复制在投影/审计/投递前有多次提交，异常会留下无法关联的源/目标；QA及文件worker又不能天然重放幂等，只有两个指针无法提供逐项续传。
- 重考虑：完整AC-32～AC-35恢复工作被纳入交付时，需独立论证复制任务/明细；本批不因减少表数否认这些状态的必要性。

## 4. 基线与最小修改

本节原批次实现保持；第一阶段新增数据流、字段和模块职责见[实现落点与验证边界](#第一阶段实现落点与验证边界)。

### 4.1 数据流与所属模块

`真实账号/已准入M → 业务对象或部门事实核验 → 冻结T/O/H → 所属SQL事务 → 现有权限adapter → 原响应`。E读取不继承M，恢复读取不得向普通调用者暴露任意pending旁路。

| 链路 | 已核实位置/问题 | 必要变化；不做什么 |
| --- | --- | --- |
| MT01 | RoleService.update_role_with_menu/update_menu事务内重查；_replace_menu_access_in_session；查重使用login tenant | 定义O内读写/查重/refresh，菜单显式O；不普遍放开其他AccessType |
| MT02 | RoleDao.aget_role_by_ids受环境过滤，Quota回默认；LoginUser/info/menu独立读 | 精确读取合法global+H定义及H绑定，统一当前E；不替换平台AdminRole |
| MT03 | ToolServices.add_tools写H；GptsToolsDao.insert_tool_type父子两commit | T验证后父子都显式T，flush父ID后插children再一次commit；不建tool operation |
| MT04 | workflow.create_flow写H，FlowDao.create_flow初始版本未继承T | flow/v0显式同T；保持原单事务；不改assistant/linsight等无关产品语义 |
| MT05 | KnowledgeService.copy_knowledge调用覆写H/提前建索引helper；QA复制前也已改源 | 私有复制预留方法保持源O、真实actor，源/目标同SQL事务，关联后再投影/准备外部存储；不改普通建库helper的全局身份语义 |
| MT06 | 单个/批量部门角色候选按操作者tenant；最终写依赖候选 | 从有效挂载/根路径算B并在最终写重验；人员绑定写H；不把Department.tenant_id当B |

### 4.2 E及菜单：修正共同事实，不建设新政策快照系统

拟新增小型 `role.application.effective_roles` 入口，结果仅有 `user_id,home_tenant_id,role_ids,roles`；不带新generation/全局缓存或进行中操作引用。身份已由当前用户/合法目标解析；任意user_id不能直接拿来扩大读取。

- User owner提供目标H/绑定读取；Role owner读取精确ID的global或H内定义；Department owner提供该主体计算资格所需的成员、祖先和B。普通成员事实读取不要求部门管理权；管理候选resolver另行校验管理员资格。
- E对普通role去重，要求绑定H、定义合法、当前作用域有效；正常无角色与读取故障区分。缺失定义/组织事实不可确定抛明确错误，不回空角色。归属不明历史行进入只读盘点，不自动搬迁。
- Menu只通过WEB_MENU定义关联读取O；个人UserMenuAccess显式取H，保持父子依赖及身份派生入口。资源权限仍走原F048。
- 仅接当前实际消费者：LoginUser init/info、菜单断言/申请模式、Quota、ApprovalGate动态role标签、DSH ROLE读取。sync/async共享纯判断，不在事件循环中阻塞等待async；不添加常驻跨请求E缓存。
- 部门候选和管理写复用现有挂载权威校验（tenant owner的grant department事实），只新增需要的应用包装，不直接向外暴露跨tenant DAO。

### 4.3 绑定生产者：同步校验/删除，移除三层恢复编排

纳入本地人员创建/编辑、批量默认发放、SSO角色替换、成员退出、部门归档/移动、两种主属更改中**直接产生策略结果的步骤**。不重做组织同步、凭据或身份投影框架。

- 所有字段先预检：跨租户兼属提交角色变更，在姓名/组/成员提交前拒绝；候选可见不等于写入合法。前端提供只读原因，后端独立拒绝。
- 新绑定显式写目标H。无作用域/global直接策略离开同H单部门时保留；作用域角色失去最后支持才删除；不引入部门授予来源。
- 定义缩小、显式成员变化和部门移动（不含标记子租户）以同数据库UoW调用user owner的“按最终事实删除非法普通绑定”方法；Role/Department Service不能直接接管UserRole ORM。Role定义及其失效绑定在同事务提交；部门移动要枚举受影响主属与兼属成员，不能只做sync_subtree_primary_users。
- 同步事务成功才报告该SQL步骤完成，失败整体回滚；不异步删除一批再返回成功。锁采用既定角色ID→用户ID顺序，所有相关新增绑定入口在锁内重验资格。规模/耗时需要集中测试；超时失败回滚，不未经测量加批量状态机。
- SSO保存变更前成员事实，只对真实新增的合法同H成员/新H激活发默认；不重发相同成员快照下人工撤销的角色。将角色发放放在权威H解析之后，不在Root+bypass先写角色。
- 真正调岗、部门移动及解绑派生的H迁移终止旧普通绑定，不复制同名角色/旧global授予；标记子租户及主属补同步保留原绑定且不发默认角色，按当前H和定义资格判定可用性；平台身份独立。现有主属入口组织结果保留，不把“降为兼属”和“删除旧关系”顺手统一。
- 现有组织/身份后置同步失败必须明确报错，不称完整成功；E读取发现当前主属与权威主部门/挂载不一致则拒绝敏感政策决策。恢复仍依现有身份同步及受控重试，不承诺新父子操作账本/全系统效果屏障。此为原AC-13/AC-14的范围收窄。
- 绑定终止记录走现有业务审计，包含actor、subject、当前H及增删ID/原因；旧/新H由既有迁移审计事件记录；不把审计表当任务队列。审计和跨系统效果的原子恰好一次保证延期，不改全站审计sink。

### 4.4 Quota：修查询与公式，不建额度基础设施

在现有QuotaService方法中显式传入已验证的责任人q和执行租户T；保留现有公共方法的兼容适配，不新增外部可伪造的授权DTO。只迁移受影响的计量模板到ORM条件，限定(q,T)和父对象；租户链逐个限定自身T，不改全局filter。

- 数量MAX，0与-1保留；文件上传取有限正值MIN，历史0/缺省及99999上限不暗改；flags OR、DSH单独聚合。
- 写检查分别验证 `user_used+delta <= role_limit` 与各层租户剩余容纳delta。展示available取角色剩余与租户链剩余最小值，不能把tenant_remaining和user累计混比。
- 必需计量/去重统计失败抛QuotaUsageUnavailable，不返回0/空集合；真实0正常。展示明确不可用；合法减量不被增量检查拦截。
- 频道/空间创建与前瞻、空间订阅的实际Service也改接同一独立预算检查，保留各自角色超限错误。个人订阅计量保留当前H及Root订阅，排除外国子租户；订阅是独立预算项，不当新增业务资源。Channel责任仍为channel.user_id，source ID跨(q,T)频道去重，delta只算新ID。责任人迁离资源T则拒绝新增，保留有权读取/缩减；编辑者/仅FGA owner交接不改变计量责任。不新增预算交接产品能力。
- super、凭据、存储、DSH专门政策沿原合同，不借管理M改H。

### 4.5 工具/工作流：两列创建状态，复用权限账本

Flow与GptsToolsType各新增 `creation_state: str`（旧行server_default=READY；新创建明确PENDING；业务SQL失败回滚不留行）。其他业务表不加对应字段。旧行默认READY不代表历史孤儿已验证，启用前必须盘点。

父子/v0同T同SQL事务commit确认后，调用现有adapter.authorize_created。权限稳定key由 `(T,type,id,CREATE)` 的固定规范计算并显式传给现有可选key参数；原主体为已有user_id，目标身份从已有父记录读取，不另存整份请求。

权限确认后CAS PENDING→READY；权限未知/失败保持PENDING并返回资源ID/明确错误，不删记录、不通过重新创建绕过原账本。既有permission应用层增加窄的创建查询/恢复包装：绑定验证过的T/type/id/key及当前actor；存在原账本则恢复原冻结计划及Owner finalize；不存在且原父记录与当前资格合法才首次调用创建；FAILED_CLOSED保持受控修复。业务不查权限ORM、不构造tuple。

正常列表仅返回READY，详情/版本/执行器/队列/导出/发布/派生写在super短路前检查父READY；对恢复只提供领域内精确ID入口，不能公开include_pending。系统预置工具及Flow非workflow类型沿既有路径，测试证明不误拦。

不加扫描worker或恢复中心。受控运维调用所属Service的resume_creation：原受理人当前仍合法且目标一致才继续；原用户失权不冒用super完成。普通审计沿原入口，失败显式报告；本批不保证其跨提交重放恰好一次，也不让审计失败倒退权限或删除已确认资源。

### 4.6 复制：两个关联字段，安全诊断，不承诺全程幂等

Knowledge新增 `copy_source_id: int | null`（目标记源）与 `copy_target_id: int | null`（源当前占用的目标），均默认null；不加文件/QA映射表或隐藏无限manifest。该关联仅用于本次复制，不取代资源owner/授权关系，不新增级联删除。

1. 校验source可复制、权限及业务T；同源同T复制，合法共享读取不自动允许跨租户创建。写前完成检查。
2. 私有预留方法锁源、重验PUBLISHED/无当前占用，SQL生成目标UNPUBLISHED且明确target.tenant_id=T、user_id=真实actor；源COPYING+copy_target_id、目标copy_source_id同事务commit。正常建库helper保持原语义，复制不调用覆写H/提前建索引分支。
3. 之后按既有adapter投影，再准备目标索引、必要审计及投递；参数携source、target、真实actor、经资源核实的T，worker入口恢复严格T并对照两行，不继承稍后M。具体资源动作仍重新授权。
4. 预留前或已确认回滚的SQL失败不占源。**commit抛异常不等于确认回滚**：本次flush已获得的target ID保持不变，先在严格T下读取该target及source.copy_target_id/target.copy_source_id；确认已提交则继续原关联，确认未提交才允许重新预留，仍未知则明确失败并保留受控核查，不恢复源、不建第二target。预留后失败保留关联和可诊断状态，错误返回source/target ID；权限/消息结果未知不自动删目标、不盲重投。不新增必填request_id，也不拿名称猜同一意图。
5. worker入口在同一短事务锁内核对源占用指向当前target、目标仍属本次复制，并CAS目标state从UNPUBLISHED→COPYING作为唯一执行领取。只有成功领取者继续；已COPYING的重复消息直接拒绝推进，不能以同一个source/target关联当作第二次许可。崩溃/未知保持COPYING与源占用，不自动超时抢占；须受控证明原worker及其子任务已停止后才能改回可重试状态。发布目标和源释放同SQL事务，均要求目标仍COPYING且源copy_target_id匹配；失败确认退出才可结束占用，外部/子任务仍不确定则保留。旧worker不能发布新一次占用的结果。目标未准备完成不可被普通使用/发布，super也检查。
6. 按源target关联提供领域内inspect供受控脚本诊断。已确认未发任务才可按现有授权恢复准备步骤；可能已运行/未知外部写只人工核查，不能自动接续，未证明旧worker结束不得清理。每个清理仍走原权限删除流程。
7. 当前worker局部吞错及把部分失败标成功要纠正为明确FAILED/未完成结果；不把task返回当完整内容验证。没有逐项映射/manifest，因此**不保证**任意重启重试下文件/QA/向量不重复，不自动重跑未知任务，不提供分片续传。

这修正MT05的错误归属与“前置失败后源/目标无法关联诊断”，只覆盖原AC-32～AC-35的一部分。旧的无关联孤儿不能凭名称自动补造关系；独立盘点/人工处理。旧任务需在交付时排空/核对，新worker不猜旧消息的原始占用。

### 4.7 实施接口补充（2026-11-11）

- 旧 `/user/info` 使用LoginUser请求内E；旧建人UserService.create_user改async（API唯一调用方同步await），初始Root无主属账户先校验合法角色，再同步H/发放；旧role重置不写操作者M。
- E sync及部门业务目录接受内部可选session，DSH同UoW读当前事实；普通模型调用不先加载全组织目录。无新缓存或全模型刷新。
- 工具更新按父creator预算、T及子项净增量判断；角色delta与租户delta分别计算，合法零增量替换保留。新增子项继承父T及creator。
- 发布线FlowService.create_workflow负责父/v0/F118绑定同事务，SQL提交后complete_creation投影/READY，保留PENDING故障定位；挂载创建沿tenant_creation coverage factory建立边界及覆盖证明，保持原角色绑定不变，历史migration_origin只豁免个人空间数量。
- 工具/Flow内部CreationRepository负责精确load/READY CAS；permission business_action负责super/public前负向就绪门禁。Flow联合应用查询、simple读和版本查询同样覆盖；这些都不提供新的权限ALLOW。
- 原权限创建恢复使用现有稳定key（包含原owner）、冻结checksum与store/model；PREPARED且owner SQL未准备时按同key重新prepare；原操作FINALIZED后核实mode.operation_id/version=1/CURRENT和CREATOR，再完成owner/assignee/visible镜像。FAILED_CLOSED不重放。
- 复制可信header仅两条copy任务启用，body T需匹配可信ContextVar；领取前和发布前复核当前actor。Knowledge复制过的库仍可再作源，copy_source_id是其历史来源，copy_target_id才是当前占用；正常未发布草稿不视为复制目标。
- role绑定审计显式operator，系统同步为-1；显式组织变更在激活前终止所有历史H普通绑定，首次显式主部门激活可承接明确账户默认角色；挂载、登录及定时/手工主属补同步不改绑、不补默认，真正调岗回迁不恢复。scope扩大和新增成员支持前先清旧无效绑定，避免历史脏行获得新资格。
- 人员表单E不可确定返回24006；政策混合请求在姓名/组写前验证H一致，跨租户兼属返回policy_editable=false、role_apply_status=NOT_APPLICABLE_CROSS_TENANT。同H为APPLICABLE；不新增UNAVAILABLE静默空政策。
- SSO组织父路径变更同SQL更新后代路径，终止涉及主属+兼属的失效绑定；禁用挂载必须报政策不可确定，不能采纳旧resolver的Root回退。

## 5. 已知坑

第一阶段补充：导航不可走完整运行解析；资源目标不能当用户Home；F048超管快捷通过前要核验流程目标；受信设备会话不读浏览器选择。各处理点见[实现落点](#第一阶段实现落点与验证边界)。

| 事实 | 不知道会怎样 | 处理处 |
| --- | --- | --- |
| 显式tenant会覆盖自动填充 | 自动filter存在但仍写错租户 | ToolServices.add_tools、workflow.create_flow、父子DAO |
| S不等于B | 子租户部门候选仍取Root角色 | 部门业务事实包装、候选及最终写 |
| global定义与H绑定不是同一scope | 放宽定义时顺手放开外国绑定 | effective_roles、WEB_MENU精确O读取 |
| 普通LegacyRBACSync不传播E | 调回调就误称已生效 | 当前消费者按次读取；不新增全模型屏障 |
| super可能短路PDP | 权限失败半成品可执行 | 父creation_state、copy关联目标状态前置门禁 |
| Broker异常不等于消息没发 | 重投/清理破坏正在写的目标 | copy关联诊断、未知不自动重试 |
| 同一人/角色没有部门来源 | 下拉编辑误删或重复授予 | 按人去重、剩余作用域支持、现有绑定审计 |
| 禁用挂载旧resolver会回退Root | 登录可能错改H并撤销绑定 | sync前verify_resolved_policy_home核对部门B |
| 旧无效绑定可在scope扩大/回迁时获得资格 | 无新授予却恢复权限 | 定义变更/成员支持变化前清无效行；H切换清历史普通绑定 |
| 联合应用查询隐藏底层实体 | 单改select(Flow)仍展示PENDING | _build_apps_subquery内Flow分支过滤 |
| source也可能是历史copy target | 将正常再复制源误判为不可用目标 | pending目标排除有当前copy_target_id的源 |
| 源update_time不能作为唯一操作token | 旧worker可能覆盖下一次复制 | copy_target_id条件释放 |

## 6. 对外契约与影响范围

第一阶段新增可选role_type/可见定义tenant_id、navigation用途窄响应及写入口目标校验；精确兼容及前后端配套要求见[交付记录](phase1-delivery.md#2-历史数据和接口兼容)。无新增表列、依赖或迁移。

| 输出/输入 | 本批变化与限制 |
| --- | --- |
| 现有role、部门人员、tool、workflow、copy路径 | 路径保持；copy不新增必填UUID；不新增操作中心/扫描接口 |
| role表单 | 同H多部门共享绑定提示，跨租户policy_editable=false及原因；最终服务端预检不可省 |
| 有效角色应用函数 | 供LoginUser/info/menu/Quota/审批标签/DSH读取；不能用于资源PDP ALLOW |
| quota响应 | 保持原字段；新增available/明确不可用语义，失败非0；错误文案三语 |
| 创建状态 | Flow/GptsToolsType内部枚举PENDING/READY；旧发布status和is_delete不改语义；普通pending拒绝可携资源ID |
| copy关联 | 内部int/null，由服务端写，不能让用户传入任意关联；响应只按原授权裁剪状态/对象ID |
| permission应用 | 只增加固定创建原账本查询/恢复包装，复用CURRENT Catalog/store/model与原tuple账本；不改FGA模型、Lua或全局快捷判断 |
| 中间件/任务 | 复用管理准入和租户上下文；仅改本次copy任务的可信目标恢复，不重做所有Celery任务 |
| 既有表DDL | Flow、GptsToolsType各1列；Knowledge2列。无新表、无数据backfill；旧NULL/READY仅默认兼容，存量先盘点 |

候选新错误仅保留24006（有效政策不可确定）、19404（统计未知）、19405（预算责任迁出）、15090/10590（工具/工作流尚未就绪）；其余优先用现有资源/权限错误。实施前再次查Code占用及三语翻译，不沿用原稿全部12码。

依赖风险：部门挂载断链/active H不唯一则拒绝；权限账本不是业务复制账本；SQL未知提交先按已确定资源ID查询，不无条件重建；MinIO/ES/Milvus未知写不自动重放；旧前端不得把失败显示成余额0或成功。本批仅按现有组件/API层更新必要提示与状态，client无新增普通切租户能力。

## 7. 验证与可观测

- 用真实ORM测试定义O、绑定H、资源T、父子/版本一致；以非法租户/无权主体构造拒绝配对，不只mock空children。
- 对scope清空/扩大、部门退出/移出再移回、SSO同快照、H迁移再回迁验证触及入口不隐式复活；平台身份/共享通道保留。
- 同一主体在不同M下info/menu/quota不变；审批/DSH政策读取失败不得转空；DSH提交后的新调用读取当前E，不把并发旧快照屏障当本批保证；分别测试普通调用、round probe、已准入round内unmetered保持原额度比较合同。
- quota覆盖真实0/未知、0/-1/MAX/MIN、(q,T)计量、10上限/5已用/3租户剩余仍允许新增1、频道原责任止增。
- 注入父/子SQL失败、权限receipt未知、copy投影/Broker异常，验证pending不可执行、关联可查、未知不盲删/重投；不声称复制重复投递幂等已完成。
- MySQL/DM8集中验证四列DDL、原子事务/锁、真实FGA创建恢复、Celery可信T；本机SQLite不能替代。E2E按仓库要求在scope/设计确认后形成任务并执行。

本机观察复核命令（仅缺陷证据）：

```bash
cd /Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/src/backend
TEST_PYTHON=/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python
config=/tmp/bisheng-managed-tenant-review-config.yaml PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 "$TEST_PYTHON" -m pytest ../../docs/reviews/managed_tenant_investigation_20261110_repro.py ../../docs/reviews/managed_tenant_review_extra_20261110.py --asyncio-mode=auto -p no:cacheprovider -q
```

运行前临时配置文件须为隔离空配置，不读取生产凭据。真实手工验证在批准测试部署建立A/B、A主属B兼属、平台管理M=B；依次保存global菜单、新建非空工具/flow/v0、复制文档和QA，核对T与pending拒绝；再测迁移/作用域/Quota。URL/测试账号及故障注入权限待测试环境准备，不使用生产身份替代。

当前工作树已实施并执行新的正确行为回归；实际命令、结果、基线失败与未执行项见verification.md。原14个观察测试只证明旧缺陷可复现，不作为修复验收。日志记录actor、subject、T、source/target、失败阶段，禁止原token/schema密钥。新建pending与copy关联缺失可由只读盘点脚本按精确租户/对象输出，不能自动修旧数据。

## 8. 删减结果、遗留与确认边界

- 删除七张新操作/明细表、七表对应扫描/租约/parent-child编排、全模型DSH刷新、全站审计UoW重做、HTTP恢复中心、复制必填UUID。
- 保留三个现有表四个小字段、原SQL事务和权限账本、必要消费者门禁与拒绝。四列有各自失败窗口依据，不能只为做到“零DDL”复用is_delete/status或把缺权限的资源视为可用。
- 全过程自动恢复、复制逐项幂等、跨系统强收敛按[范围调整](scope-revision.md)延期。若坚持原40条完整交付，需要为这些结果保留必要持久事实，不能以本稿替代并标全绿。
- 2026-11-10用户已确认本稿及scope-revision；后续生成QA/tasks并实施，不再重复请求设计确认。原规格AC正文保留，不静默删除已确认需求。

## 修订历史

| 日期 | 变化 | 依据 |
| --- | --- | --- |
| 2026-11-10 | 从七表全恢复方案收敛为零新表、四个必要字段的缺陷修复候选；拆出明确延期结果 | 用户要求最小改动/最小影响，独立复审REVISE及当前调用链核对 |
| 2026-11-10 | 用户确认最小范围后开始实施：定义O事务、E/组织事实、登录菜单/Quota及实际gate、四列DDL | 31项局部回归通过；完整消费与业务任务继续进行 |
| 2026-11-11 | 最小范围业务实施完成；补齐旧人员入口、真实工具增量、SSO后代路径/兼属终止、创建恢复镜像和联合列表门禁；四列无新增表；验证限制见verification | 当前源码及真实SQLite回归/静态检查；真实中间件与浏览器仍待验收 |

2026-11-11合并补充：不改已发布迁移父链，新增空merge revision v310b1_merge_f009_release_heads汇合F009/F118删除/work130。没有新业务表/列。合并回归353通过/10基线已有失败；影响与测试重点见对应交付文档。

## 2026-11-13 第一阶段实现设计

基线：远端发布线 fe4ae2cdd17d42c95dfe9d03e0b7070b57ac97b0；用户已指示按修订方案实施第一阶段。以下覆盖AC-41～AC-48，既有设计未涉及的契约保持。

- 访客链接仅管理设置路径加入既有管理范围；PATCH和4类上传预览写入复用现有请求目标检查，前后端同步。匿名执行不接选择，保留资源权限、上传人/空间归属和版本检查。
- 原 `/workstation/config` 增加导航用途的窄响应，平台全局初始化只取菜单/图标，不触发模型、工具或知识运行配置校验；完整配置继续验证引用。跨主属超管的模型展示只投影目标合法配置，不构造目标人员政策、不提供执行或计费放行。
- `abuild_scoped_login_user` 从权威真实身份初始化，不把资源租户作为预期Home；不切换执行ContextVar。检索资源动作仍由原权限入口判定，开关开/关保留运行人/创建者语义。
- 角色创建DTO增加可选role_type，缺省tenant；本地取已验证管理目标，共享显式平台资格且新定义Root，查重/部门/菜单归属一致；编辑不接受类型/所有者转换。沿现有定义仓储事务，无新表/列，不改旧共享定义/普通绑定。
- 敏感管理准入增加跳过超管正缓存的资格核实，依照现有权威关系和合法AdminRole来源；事实不可核实拒绝。不得仅删选择后称资格撤销，既有本人及独立凭据范围不变。
- 辅助GET业务404作为结构化请求错误展示，不全页导航；403及资源动作门禁保持。切换仍用现有整页刷新，Redis仍存十进制租户。
- 工作流认证长连接在资源查询前取得验证后的管理目标并固定到连接结束，结束恢复上下文；资源租户和use动作继续验证，Worker沿已有流程持久归属执行，不读之后选择。

选择以上窄入口是为了修已证明的混用，不引入全路由元数据框架、新视图标识或全局SQL钩子改造；全平台覆盖留第二/三阶段。若必须支持新计费身份、无法证明的跨租户执行或历史搬迁，需另行定范围，不能在本批添加兜底。

已知坑：导航解析不可调用会同步工具/解析模型引用的完整parse链；角色菜单跟随定义所有者而非当前目标；实际用户主属不同于资源目标；刷新只能清页面，不能作为服务端权限证明。

### 第一阶段实现落点与验证边界

- `get_navigation_config`只解析assistantIcon；`GET /workstation/config?purpose=navigation`提供窄响应，缺配置不初始化运行默认项。平台全局导航使用它；旧完整配置请求形态保留。
- `workbench_models_for_display`仅用于完整配置和模型展示API：跨主属时要求已核验平台资格、管理上下文与目标一致，并重新验证配置归属/共享；普通用户和执行通道继续走原个人政策。未新增跨主属管理调试或计费身份。
- 角色创建/维护统一消费已有平台资格（含FGA事实和合法旧管理员来源），不要求给FGA超管补AdminRole。新建显式role_type，tenant取管理目标、global取Root；RoleListResponse增加定义tenant_id。角色类型编辑不开放转换。
- `_check_is_global_super(force_refresh=True)`绕过旧正缓存并在权威关系不可判定且无合法独立管理员来源时拒绝。已知敏感管理请求标记其后续LoginUser初始化也需当前资格，避免再读旧缓存；普通未标记初始化保持原调用兼容。检索及浏览器工作流连接亦要求当前资格。
- `browser_workflow_scope`先读取真实身份，再取得目标、通过已有创建仓储精确核验流程归属/类型/READY，最后进入原use动作和连接分发；整个连接固定范围，异常/断开恢复上下文。Worker生产/恢复格式未改，继续按消息上下文和Flow持久目标执行。
- DSH桌面端受信Web会话在原设备凭据验证成功后带请求内私有租户标记；该标记不进入API序列化、不由请求体提供。此类连接只使用凭据目标，不读取浏览器Redis选择。v2/匿名执行通道保持原入口，不改为管理身份。
- 第一阶段不全局更改选择过期后的读取/自举语义；已触及写入的页面目标校验和连接的资源资格防止错目标提交。全入口生命周期、个人业务分类及网关自有能力仍属第二/三阶段。现有撤权清理钩子未被宣称已接通所有生产者；本批以敏感入口重新核实权威资格防止旧选择/正缓存放行，不新增撤权API或跨系统原子撤权机制。

重新考虑条件：若以后要求所有读取都强制明确目标、所有旧客户端/设备同步或所有调试通道计量，则按第二/三阶段扩展；不要在本补丁里新增凭据、恢复中心或历史搬迁。

验证以定向服务/HTTP测试、真实SQLite定义菜单事务、上下文/权限负向及前端请求/角色表单回归为主。真实MySQL/DM8、外部服务和浏览器验收见第一阶段交付记录，不能以本地测试数替代。

第一阶段修订历史：2026-11-13，按用户明确开发指令完成AC-41～AC-48及显式角色类型增量；复用现有选择/仓储/动作权限，零新增表列、零历史修数。当前实现与本地/现场验证边界见[交付记录](phase1-delivery.md)。


## 2026-11-14 第二、三阶段实现快照

用户批准继续统一上下文第二、三阶段，并确认组织仅管理所选租户挂载子树。最终技术决策、数据流、字段及兼容边界见[第二、三阶段设计](phase23-design.md)，此处作为原设计的增量入口。

- **数据流**：唯一端点声明 → 最终选路准入 → 冻结请求事实 → 原业务权限/SQL；流和连接发送完毕再释放。2026-11-17修订：两套前端按浏览器业务默认携带目标，不再根据生成接口清单运行选路；生成资料仅用于检查，暂停恢复规则见phase23-design.md。Java自有控制器通过后端窄证明，不改变网关执行归属。
- **接口/字段**：GET /api/v1/admin/request-scope（严格确认）、POST .../bootstrap（仅首次默认选择）、POST .../resources（网关部门/资源证明）。X-Management-Tenant由页面确认的scope_tenant_id产生；响应带固定目标、来源及私有禁缓存。home_tenant_id独立保留。没有新业务表、列、迁移或新令牌格式。
- **模块**：common/request_scope仅登记；admin/application/request_admission负责ASGI生命周期；部门DirectoryRepository/组织依赖负责挂载与存储翻译；user负责账号和主属；permission维持动作判断并做独立目标负向边界；worker复核持久目标。不是用LoginUser替换字段来传播管理目标。
- **已知坑**：组织存Root不代表业务属Root；组、角色及审计不能继承组织临时存储上下文。Celery信号异常不保证中断执行，关键任务执行体必须再次证明。旧自举响应可能晚于新选择，按当前Promise身份拒绝旧响应。详见增量设计。
- **契约**：超管租户GET也需要有效目标；老页面须匹配更新。普通人员仍按真实主属。本人主部门供网关执行读取，不是管理视图查询。旧组资源410及旧拦截日志平台汇总均为明确例外。
- **不变量**：既有共享/继承、角色作用域、配额与权限账本不放宽；历史只读预检不修数。角色历史修正/行政承接不随此批自动交付。

修订：2026-11-14，按用户授权完成上下文二、三阶段本地源码及定向验证，包含组织决策和网关退役范围澄清；上线验收仍独立。

## 2026-11-16 可选 Gateway 兼容修订

本轮用户确认修订联合升级前提及首次拦截归属，当前规则以[可选Gateway兼容修订](optional-gateway-compat.md)为准；业务资源归管理目标、本人身份不变，旧回调不再统一要求管理头。原Java增强保留独立待合并，本轮不修改Java或历史数据。

## 首次拦截后继续聊天修复

用户明确授权T131。已由公共持久化协议注入窄会话存储适配器，保持资源执行与消息归属分离、父/消息原子保存及合法已知会话历史/重连；最终数据流、边界及验证以[本轮交付](continuation-fix-delivery-20261116.md)和optional-gateway-compat.md最终实现段为准。首次记录不因继续而迁移，Java/表结构不变。旧架构依赖不在本轮扩大，现场仍待验。


## 2026-11-17 子租户登录及挂载兼容修订

依据本轮用户指令及 spec.md 同日修订。v3.0.0 已有 is_child_admin 前端管理放行和租户内资源权限，但其登录无角色检查也遗漏独立子租户管理员；本次补齐登录与管理端默认落点，不将身份转换为 AdminRole。

LoginUser.is_home_tenant_admin 通过 permission.application 核验真实主属；不使用管理选择，不信任传入角色编号，Root及平台身份跳过子租户身份查询。管理入口只合并 admin/sys/system_config，原侧栏路由仍按 is_child_admin 放行租户业务功能；普通角色/额度及具体资源权限不变。权限服务错误传播，撤销后重新读取不放行。

create_mounted_tenant_with_coverage 删除自动退役绑定步骤；UserTenantSyncService 仅在 DEPT_CHANGE、DEPT_MOVED、UNMOUNT_REDERIVE 显式组织变更时执行原角色终止及默认规则。MOUNT_BACKFILL、LOGIN、CELERY_RECONCILE、MANUAL 只同步主属与既有身份后置步骤，原绑定所有字段保持，目标部门有默认配置也不补授。这样挂载后首次补同步失败再经登录/Beat恢复，不会重新解释成角色授权操作。账号/SSO/显式角色写入入口不纳入此次角色语义改造。

此选择保持 v3.0.0 的挂载角色存储行为及当前有效角色隔离；不新增持久字段或挂载请求协议。若将来要求行政划分自动承接策略，应另行明确映射、原子性和撤权重试规则，不能重新在通用主属同步中推导授权。

已知坑：仅按 mount.backfill 跳过角色操作不足以覆盖后续 login/Celery 补同步；保留记录不表示跨租户生效。既有挂载提交后人员同步/初始管理员授予仍分步骤，此补丁不承诺整流程原子恢复。

修订记录：2026-11-17，按用户指定的 v3.0.0 兼容语义修订挂载及管理员入口；本地证据及现场待验见 child-admin-mount-compat-delivery-20261117.md。
