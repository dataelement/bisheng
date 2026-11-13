# 跨租户角色语义、创建租户与升级兼容：独立评审交接

## 1. 本次交接的目标与状态

用户要求将跨租户角色问题交给另一个agent单独评审处理。本文件是问题说明和评审入口，不是已经确认的实施设计。

需要评审的业务闭环是：**角色定义与分配 → 创建/划分租户或人员调动 → 主属及绑定变更 → 登录、菜单、配额、审批与DSH一致生效 → 撤销和重试不复活旧授权。** 不应仅为消除10609而修改登录一个入口。

目前没有实施本文的角色语义变更、角色复制或绑定转换，也没有因此修改114/116等环境。之前已交付的频道兼容、前端创建时序及配额排序规则修复不是角色问题已经解决的证据。

- 工作区：`/Users/zhangguoqing/works/bisheng`，发布线：`feat/3.1.0-beta1`。
- 本次源码核验基线：`664091a47821532cc0ad2b64e07fac6601ce2c6d`。整理时本机已知远端为`c9918ba14e5d6729e883878c776954b983b0aec2`；比较两者的role/tenant/user/department及F009相关路径未发现差异，但接手时仍须fetch并重新核对。
- 已有F009合同见[spec.md](../../features/v3.1.0-beta1/009-managed-tenant-consistency/spec.md)及[design.md](../../features/v3.1.0-beta1/009-managed-tenant-consistency/design.md)。
- 之前的[配额修复及历史绑定提案](f009-quota-collation-and-legacy-role-bindings-20261112.md)只提出了历史转换候选；它没有完整覆盖在线创建租户场景，不能直接当成已确认方案。

## 2. 用户原意与尚未确认的语义

用户此前指出：“全局角色只是说这个角色是所有部门都可以使用，和租户没有关系”。随后询问：超管在界面创建新租户时，是否应复制父租户角色并修改绑定；又确认当前代码是否默认支持跨租户角色定义。

**这些是业务语义质询，不代表用户已经批准以下任一方案：** 全局定义永久跨租户共享、将所有global改成tenant、批量复制父租户角色，或自动搬迁所有旧绑定。

必须分开讨论四个维度：

| 维度 | 要回答的问题 |
| --- | --- |
| 定义的可用租户范围 | 一个角色定义可由哪些租户选择？仅定义所属租户、明确共享，还是所有租户？ |
| 部门作用域 | 在可用租户内，哪些部门/人员有资格使用？空department_id与指定部门如何解释？ |
| 人员绑定的生效归属 | 用户对该角色的绑定属于当前主属租户，还是全局人员策略？换租户后是否保留？ |
| 资源授权 | 进入菜单或具备策略角色，是否仍须独立通过资源归属与资源动作权限？必须保持此边界。 |

不能把“所有部门可选”“所有租户可复用定义”“用户在所有租户都有角色”“能访问所有租户资源”当作同一个含义。

## 3. 已核实的当前实现

| 项目 | 当前行为 | 源码入口 |
| --- | --- | --- |
| 模型字段默认 | Role.role_type默认tenant | `bisheng/database/models/role.py:RoleBase` |
| 创建服务的实际选择 | create_role/create_role_with_menu按`login_user.is_admin()`选择global，否则tenant；请求schema没有让调用方显式选择role_type的字段 | `bisheng/role/domain/services/role_service.py`、`bisheng/role/domain/schemas/role_schema.py` |
| global定义资格 | eligible_role对global不要求Role.tenant_id等于用户主属；仍要求部门作用域满足。资格目录查询包括global，不限定于父子租户 | `bisheng/role/application/effective_roles.py:eligible_role`、`bisheng/role/domain/repositories/effective_role_repository.py:assignable_definitions` |
| 普通人员绑定 | _binding_ids仅取UserRole.tenant_id等于当前home_tenant_id的普通绑定，平台AdminRole另行处理 | `bisheng/role/application/effective_roles.py:_binding_ids` |
| 菜单归属 | WEB_MENU按角色定义的tenant_id读取，不按人员绑定租户猜定义归属 | `bisheng/role/domain/repositories/effective_role_repository.py:_menu_statement` |
| 管理列表与分配候选 | 有不同的入口和管理权限，不能据某管理页面不显示global就断言它不可分配；须一起评审列表、候选、最终写入 | `bisheng/role/domain/services/role_service.py`、`bisheng/department/application/business_scope.py` |
| 10609 | 普通用户无有效角色、且没有原登录规则认可的部门/用户组管理资格时，被拒绝登录；没有有效菜单还可能触发另一个入口错误 | `bisheng/user/domain/services/user.py:_reject_login_if_user_has_no_usable_access` |
| 主属变化 | 终止旧普通绑定，切换主属，再按当前合法部门默认配置授予；不会自动搬迁全部原手动global绑定 | `bisheng/tenant/domain/services/user_tenant_sync_service.py:sync_user` |

**更正之前对话中“新建角色默认tenant”的不完整表述：** 那只是ORM字段默认。当前服务会覆盖它，超管创建角色走global。评审必须检查实际入口，不能只读模型默认值。

当前代码结论是：**global定义可跨租户复用，但普通绑定只在人员主属内生效。** 这是实现事实，不是用户已经确认的最终产品定义。

## 4. 必须分别处理的业务场景

### A. 升级后旧绑定被排除

示例：Root维护global角色G；用户A的实际主部门/主属为租户13，但旧UserRole的tenant_id仍为1。定义可以合法复用，旧绑定却不在Home内；若没有其他有效入口，用户升级后可能10609。

对话截图描述114环境有4位此类用户并曾做现场改绑；本次没有连接114重查，不应把截图数量、现场处置或历史日志当作当前环境状态证明。更不能把“角色已允许跨租户复用”误当成旧绑定迁移已经完成。

### B. 超管将已有部门设为新租户

当前3.1主要界面入口是[MountTenantDialog](../../src/frontend/platform/src/pages/DepartmentPage/components/MountTenantDialog.tsx)，调用`mountTenantApi`，不是直接使用旧租户编辑对话框创建空租户。

已核实链路：

1. `TenantMountService.mount`创建新租户并标记部门挂载点。
2. `create_mounted_tenant_with_coverage`在创建事务里调用`retire_invalid_policy_bindings(..., derive_primary_home=True)`。
3. 创建链调用子树成员同步；`UserTenantSyncService.sync_user`处理主属切换并授予当前合法默认策略。
4. 界面再对选中的人员逐个调用租户管理员授予接口，管理员授予并非普通Role整体复制。

这里人员的实际工作部门可能没变，只是该部门被划成了独立租户。当前没有完整的“原有效手动角色→新租户角色”承接步骤；仅清旧绑定和发默认角色，可能令原本可登录的普通用户失去角色。

评审应在**改变部门租户边界之前**取得原有效策略。边界改变、旧绑定被清理后再试图读取原有效集合，可能已经丢失源事实。只处理本次实际改变主属的人员；主属在外的兼属成员不得跟着改绑。

### C. 人员真正从租户A调到租户B

这与“原部门被设成新租户”不同。F009 AC-12当前要求终止旧普通策略，目标租户合法授予，回迁不复活旧绑定。不能为了兼容B场景而让所有人员调动都自动携带父租户/原租户权限。

### D. 新建空租户及后续新增人员

新租户需要合法的角色/默认策略配置和独立管理员安排，但并不天然需要复制父租户全部角色。要同时验证新加入成员能否正常获得合法默认策略，以及重复SSO/成员同步不会重发已人工撤销的角色。

## 5. 请独立评审的方案选择

### 先确定产品语义

| 选项 | 含义与主要代价 |
| --- | --- |
| 保留现有跨租户定义复用，绑定按Home生效 | 可复用同一global定义；必须补历史兼容及划分租户时的承接，管理/分配界面需明确角色来源、可用范围和只读性 |
| “全局”仅表示本租户所有部门 | 需要收紧创建、候选、读取和绑定；已有global及其跨租户引用必须有迁移映射，不能只改过滤或把所有global字段改成tenant |
| 角色绑定作为随人跨租户的长期全局政策 | 需统一授予、撤销及全部消费者，并明确谁能影响用户未来所在租户；不能仅在读取时增加Root兜底。不是本次已有共识 |

还要单独决定：超管是否应能明确创建“指定租户的普通角色”，而不是仅因操作者是超管就自动创建global。权限足够与角色共享范围是不同问题。

### 此前讨论过的候选，不是实施指令

若选择“定义可复用、绑定归Home”，可评估以下承接方式：

| 角色类型 | 定义 | 划分新租户时的绑定候选 |
| --- | --- | --- |
| 新范围内仍合法的global | 保持定义和角色ID | 对本次主属变化人员的原有效绑定归到新Home |
| 父租户私有普通角色 | 超管明确选择继承时，在子租户创建独立模板副本和新ID；不整体复制父角色目录 | 按明确的旧ID→新ID映射改绑，父租户其他人员不动 |
| 不继承/不再合法的普通角色 | 不猜同名映射、不清空部门范围来放行 | 配置新的合法角色/默认策略，预览新增不可登录人员并解决 |
| 管理员身份、资源授权 | 按独立权威与既有明确共享通道处理 | 不随普通角色批量复制 |

私有角色不能只把UserRole.tenant_id改成子租户后继续引用父租户私有定义；当前资格校验仍会拒绝。复制模板还应检查菜单、角色额度、部门范围及默认角色引用，不复制父租户资源授权或平台管理员身份。资源共享仍走现有明确共享机制。

若对部门划分增加保留global绑定的例外，它与AC-12现有广义主属迁移条款有边界冲突，须先明确触发条件并同步合同，而不是直接给`sync_user`加无条件例外。

## 6. 各方案都必须满足的保护条件

- 角色定义、UserRole绑定、UserTenant管理员身份、个人菜单授权及F048资源授权分别处理，不以菜单角色替代资源权限。
- 不整体复制父角色、按名称猜ID、复制外租户资源授权，或为了避免10609给所有人补默认/管理员角色。
- 升级修正与在线划分使用当前可确认的事实和有限变更集合；已开服且发生过角色操作的环境，需要结合当前管理员确认与可用审计，不能把“Root行还在/没有撤权日志”当成仍有授予意图。
- 原位条件变更、必要去重及审计应受同一用户/创建操作的事务和事实重验保护。备份供核对，不能作为角色INSERT恢复指令。
- 完成后再撤权、换部门、改角色范围或删除角色，重试不得重授。默认角色只在真实新增成员/新主属的合法授予时生效，不能被同一SSO快照反复补回。
- 主属切换与角色承接不能留“创建成功但账号已坏”的静默中间态。评审SQL事务与外部投影的真实接缝、完成/失败回执和续办方式，复用现有边界，不另造全平台恢复中心。
- 以典型业务及边界场景验证，沿用当前事实，不重建首次F048全过程或要求逐项重证全部历史权限。无法确认的个别关联单列，不借兼容扩大授权。

## 7. 最小验收矩阵

| 场景 | 需要证明的结果 |
| --- | --- |
| 超管创建角色，含管理视角切换 | 实际类型、定义归属及共享范围符合选定语义；不能只测ORM默认值 |
| global定义的跨租户候选与维护 | 候选、管理列表、编辑资格及部门范围一致；可选不等于可修改 |
| 合法历史Root绑定 | 所选兼容方案能恢复预期入口；角色数据变更可定位、可审计 |
| 外租户私有角色、越部门或归属不明 | 不猜绑、不放宽、不因登录修复取得外租户权限 |
| 部门划为新租户 | 以原有效策略为源，主属真正变化的人员有明确承接结果；兼属及父租户其他人员不变 |
| 私有角色模板复制（若选定） | 稳定ID映射、合法菜单/额度/部门范围；重复操作无重复定义或授予 |
| 真正跨租户调岗、回迁 | 按目标合法授予；不隐式复活旧角色 |
| 角色撤销后重试、SSO重放 | 不从旧源、默认配置、备份或旧操作重新补回 |
| 角色范围/定义改变与操作并发 | 重新校验当前事实，旧快照不得覆盖后续意图；失败无半提交 |
| 登录、info、菜单、配额、审批、DSH | 有效策略一致；角色额度和租户上限均受约束，历史用量/余额不清零 |
| 管理员与资源隔离 | 独立管理员身份保持；无权外租户资源拒绝，明确共享通道正常 |
| 原本无角色的普通用户 | 不因本次处理自动被授予角色；按选定的无角色业务规则处理 |

先跑真实入口到关键存储/消费者的最小冒烟，再扩展边界。不要只测helper或模拟一个角色列表就宣称在线创建/升级已完成。

## 8. 源码与测试定位

后端路径相对`src/backend/`，前端路径相对仓库根；接手后按函数名定位，行号可能漂移：

- 定义及创建：`bisheng/database/models/role.py`、`bisheng/role/domain/schemas/role_schema.py`、`bisheng/role/domain/services/role_service.py`、`bisheng/role/domain/repositories/role_definition_repository.py`。
- 有效策略及菜单：`bisheng/role/application/effective_roles.py`、`bisheng/role/domain/repositories/effective_role_repository.py`。
- 绑定读写/清理/审计：`bisheng/user/application/policy_bindings.py`、`bisheng/user/domain/repositories/policy_binding_repository.py`、`bisheng/database/models/user_role.py`。
- 登录：`bisheng/user/domain/services/user.py:_reject_login_if_user_has_no_usable_access`；错误码`bisheng/common/errcode/user.py:UserNoRoleForLoginError`。
- 在线租户划分：`bisheng/tenant/domain/services/tenant_mount_service.py`、`bisheng/tenant/application/tenant_creation.py`、`bisheng/tenant/domain/repositories/tenant_creation_repository.py`。
- 主属和默认角色：`bisheng/tenant/domain/services/user_tenant_sync_service.py`、`bisheng/department/application/business_scope.py`及部门成员/默认策略写入入口。
- 预检：`scripts/managed_tenant_preflight.py`、`bisheng/tenant/application/managed_tenant_preflight.py`；现有脚本只读且有limit/truncated，不是已实现的全量转换器。
- 现有测试：`test/role/test_role_service.py`、`test/role/test_effective_roles.py`、`test/user/test_managed_tenant_policy.py`、`test/user/test_user_tenant_sync_service.py`、`test/tenant/test_tenant_mount_service*.py`、`test/department/test_managed_tenant_members.py`。
- 前端：`src/frontend/platform/src/pages/DepartmentPage/components/MountTenantDialog.tsx`及`controllers/API/department.ts`；旧`TenantPage/components/CreateTenantDialog.tsx`当前主要用于编辑，不要仅按文件名判断创建入口。

F009 AC-02/03涉及全局/租户定义，AC-08/09/10/12涉及默认、撤销和主属迁移，AC-16～20涉及策略消费者，AC-39涉及启用前存量差异。实现变更需与选定合同一致。

## 9. 给评审agent的任务边界与回执

建议由一个Owner负责同一修复所需的定义、分配、主属变更、调用方和测试接线，避免拆成多份helper后无人负责创建流程。当前本轮交付只是本文，未启动其他agent。

接手任务：先独立评审上述语义与机制，给出推荐选择、合同影响、最小实施范围和验收计划；不要把本文候选当作已批准设计。实施遵守用户在接手会话中的实际授权及项目SDD流程，已有明确授权不因本文重复询问。

代码可修改范围由最终选定方案决定，重点为role/user/department/tenant及真实消费者。不要顺手重做知识迁移、配额SQL、资源存储、全平台审计或登录恢复中心；这些不是本次新增问题。生产数据修正、角色复制和部署需有相应授权及具体计划，不因本交接自动执行。

共享工作树：保留他人的未提交及未跟踪文件；禁止repo-wide Git写操作，包括`git stash`（含pop/apply）、`git checkout .`、`git reset --hard`、`git clean`、无路径`git restore`。只提交本人明确路径，冲突逐处核对，不用整文件`--theirs/--ours`覆盖。主工作区已有用户未提交文档，建议从最新发布线创建独立worktree；提交、推送和部署分别记录状态。

评审回执至少包含：选定/待决语义、实际缺陷与预期行为的区分、现有合同冲突、在线创建与历史数据两条闭环、撤权/重试保护、代码与测试范围。实施回执再列真实入口接线、对应提交、验证环境与替身边界、未执行项、迁移/部署状态；不能以测试数替代业务验收。

此前配额修复的101项回归包含既有有效角色/登录测试，只证明该次变更未破坏现有行为；不证明本文角色转换或在线承接目标已实现。真实MySQL/DM8、114/116当前数据与完整业务验收均需另列证据。
