# Tasks: 管理租户最小修复

**关联**：[spec](spec.md) · [已确认范围](scope-revision.md) · [design](design.md)。
**版本**：v3.1.0-beta1 / F009。2026-11-10用户确认“采用最小修复范围，继续开发”。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 原40条规格及已确认scope共同定义本批目标 |
| design.md | ✅ 已评审 | 最小修复独立PROCEED，范围high由用户确认关闭 |
| tasks.md | ✅ 已拆解 | 仅28纳入+11部分结果；AC-33不进入本批 |
| 实现/验收 | 🟡 本地实现完成，集成待验 | 业务实现及本地回归完成；T047真实环境验收、T048发布线集成及最终合入门禁仍待完成，详见verification/code-review |

## 开发与范围

按Wave/依赖顺序实施；角色/组织/配额关键回归曾实测先红后绿，其余为实现后补充回归，不宣称每项均为TDD。基础设施先行。每项目标不超过两文件；tests只断言本批scope的部分结果，不宣称完整恢复。新ORM查询放Repository，修现有DAO不新增DAO入口；不用全局bypass解决业务范围。四列downgrade需先停止新版写入并核对pending，不自动清业务数据。QA参考表独立，不作为任务输入。

每完成一任务按task-review检查适用项并记录；最后e2e和sdd-code-review。无新增业务表/多层任务账本/周期恢复/必填复制UUID；部分结果延期见scope-revision，开发不重新加入。

## Tasks

### Wave 1

- [x] **T001**：工具/工作流创建状态模型（基础设施）
  **文件**：`src/backend/bisheng/database/models/flow.py`、`src/backend/bisheng/tool/domain/models/gpts_tools.py`
  **逻辑/验证**：各加creation_state，旧server_default READY，新创建由Service显式PENDING；不复用发布status/is_delete。
  **覆盖 AC**：AC-28, AC-29, AC-30
  **依赖**：无

- [x] **T002**：复制关联模型（基础设施）
  **文件**：`src/backend/bisheng/knowledge/domain/models/knowledge.py`
  **逻辑/验证**：仅copy_source_id/copy_target_id nullable两列，不新增表、不级联删；拒绝把参数公开为任意body写。
  **覆盖 AC**：AC-31, AC-32, AC-34
  **依赖**：无

- [x] **T003**：四列可回滚DDL（基础设施）
  **文件**：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_f009_managed_tenant.py`、`src/backend/test/database/test_managed_tenant_migration.py`
  **逻辑/验证**：alembic heads定位唯一父revision；四列idempotent双DB DDL，无数据读取/回填；downgrade仅drop四列，先停止新版写及检查pending再回滚。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-32
  **依赖**：T001, T002

- [x] **T004**：角色/统计错误（基础设施）
  **文件**：`src/backend/bisheng/common/errcode/role.py`、`src/backend/bisheng/common/errcode/tenant_quota.py`
  **逻辑/验证**：核实未占用24006/19404/19405并新增明确错误；不把异常当空政策/0。
  **覆盖 AC**：AC-18, AC-23, AC-24
  **依赖**：无

- [x] **T005**：创建未完成错误（基础设施）
  **文件**：`src/backend/bisheng/common/errcode/tool.py`、`src/backend/bisheng/common/errcode/flow.py`
  **逻辑/验证**：新增15090/10590；响应可定位pending资源，敏感异常不透传。
  **覆盖 AC**：AC-30
  **依赖**：无

### Wave 2

- [x] **T006**：角色事务与定义范围回归（测试）
  **文件**：`src/backend/test/fixtures/managed_tenant.py`、`src/backend/test/role/test_managed_tenant_role.py`
  **逻辑/验证**：内存SQLite真实Role/RoleAccess，H=A M=B；global各保存入口、查重、tenant外拒绝与显式空/null；外部身份授权以窄替身隔离。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-10
  **依赖**：T004

- [x] **T007**：角色定义与菜单精确事务（后端Domain）
  **文件**：`src/backend/bisheng/role/domain/repositories/role_definition_repository.py`、`src/backend/bisheng/role/domain/services/role_service.py`
  **逻辑/验证**：Repository负责O内查重/读写/flush/refresh和WEB_MENU替换；Service先验证管理员/定义范围；不放宽所有DAO。
  **覆盖 AC**：AC-02, AC-03, AC-10
  **依赖**：T006
  **配对测试**：T006通过后实现；结合本任务实际消费入口验证。

- [x] **T008**：部门挂载业务事实回归（测试）
  **文件**：`src/backend/test/department/test_managed_tenant_scope.py`
  **逻辑/验证**：Root存储/B挂载、断链/禁用/嵌套边界；管理resolver与本人事实reader授权分开。
  **覆盖 AC**：AC-03, AC-04, AC-05, AC-38
  **依赖**：T006

- [x] **T009**：部门业务范围事实（后端Domain）
  **文件**：`src/backend/bisheng/department/application/business_scope.py`、`src/backend/bisheng/department/domain/repositories/policy_scope_repository.py`
  **逻辑/验证**：复用根挂载权威事实，按精确部门/祖先核对B/S；导出有限管理/本人事实接口，不向普通主体开放任意目录查询。
  **覆盖 AC**：AC-04, AC-05, AC-38
  **依赖**：T008
  **配对测试**：T008通过后实现；结合本任务实际消费入口验证。

### Wave 3

- [x] **T010**：有效普通角色集合回归（测试）
  **文件**：`src/backend/test/role/test_effective_roles.py`
  **逻辑/验证**：实际H绑定+global/H/外国定义、成员scope、重复绑定、正常空/故障、AdminRole独立，sync/async一致。
  **覆盖 AC**：AC-04, AC-07, AC-15, AC-16, AC-18
  **依赖**：T007, T009

- [x] **T011**：有效角色公共读取（后端Domain）
  **文件**：`src/backend/bisheng/role/application/effective_roles.py`、`src/backend/bisheng/role/domain/repositories/effective_role_repository.py`
  **逻辑/验证**：提供精确主体/H的有效普通role结果，纯资格算法共用；无generation/cache；跨域通过事实/绑定公开接口，ORM只在Repository。
  **覆盖 AC**：AC-04, AC-07, AC-15, AC-16, AC-18
  **依赖**：T010
  **配对测试**：T010通过后实现；结合本任务实际消费入口验证。

- [x] **T012**：登录/菜单当前身份回归（测试）
  **文件**：`src/backend/test/user/test_managed_tenant_policy.py`
  **逻辑/验证**：init/info/菜单在不同M一致；global菜单取O、个人授权H；政策失败不回空；身份入口保留。
  **覆盖 AC**：AC-15, AC-16, AC-19, AC-37, AC-38
  **依赖**：T011

- [x] **T013**：登录与菜单消费者（后端Domain）
  **文件**：`src/backend/bisheng/user/domain/services/auth.py`、`src/backend/bisheng/user/domain/services/user.py`
  **逻辑/验证**：init sync/async/info/menu接有效普通角色，AdminRole独立读取；个人grant按H；不覆盖真实tenant_id。
  **覆盖 AC**：AC-15, AC-16, AC-19, AC-37, AC-38
  **依赖**：T012
  **配对测试**：T012通过后实现；结合本任务实际消费入口验证。

- [x] **T049**：本人信息读取接入（后端API）
  **文件**：`src/backend/bisheng/user/api/user.py`
  **逻辑/验证**：info使用已验证LoginUser的同一有效角色/请求内snapshot，不再在M中重查原始绑定；保留平台/部门身份及字段裁剪。
  **覆盖 AC**：AC-15, AC-16, AC-18, AC-38
  **依赖**：T013
  **配对测试**：T012；后续T047实际HTTP覆盖。

- [x] **T014**：额度计量与失败回归（测试）
  **文件**：`src/backend/test/quota/test_managed_tenant_quota.py`、`src/backend/test/quota/test_managed_tenant_creation_gates.py`
  **逻辑/验证**：真实ORM(q,T)统计、0/-1/MAX/MIN、10/5/3增量、Root链失败、source去重/迁出creator止增；测试未知统计无业务写。
  **覆盖 AC**：AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27
  **依赖**：T011

- [x] **T015**：配额检查与读取（后端Domain）
  **文件**：`src/backend/bisheng/role/domain/services/quota_service.py`、`src/backend/bisheng/role/domain/repositories/quota_repository.py`
  **逻辑/验证**：只迁受影响统计到ORM Repository，显式q/T，独立角色和租户余额，新增available；保留例外和预检查微超；故障raise。
  **覆盖 AC**：AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27
  **依赖**：T014
  **配对测试**：T014通过后实现；结合本任务实际消费入口验证。

- [x] **T050**：实际创建/订阅配额入口接入（后端Domain）
  **文件**：`src/backend/bisheng/channel/domain/services/channel_service.py`、`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑/验证**：频道创建/前瞻、空间创建/前瞻/订阅改用独立预算检查；角色超限保留原资源错误，租户链错误不伪装个人上限。T014真实ORM业务gate先红后绿。
  **覆盖 AC**：AC-21, AC-22, AC-23
  **依赖**：T015
  **配对测试**：T014

### Wave 4

- [x] **T016**：部门候选/最终写前拒绝（测试）
  **文件**：`src/backend/test/department/test_managed_tenant_members.py`
  **逻辑/验证**：单批候选按B；目标H绑定；兼属混合姓名/组/角色请求写前整体拒绝；同H共享绑定。
  **覆盖 AC**：AC-04, AC-05, AC-06, AC-07
  **依赖**：T009, T011

- [x] **T017**：人员候选和编辑边界（后端Domain）
  **文件**：`src/backend/bisheng/department/domain/services/department_service.py`、`src/backend/bisheng/user/domain/repositories/policy_binding_repository.py`
  **逻辑/验证**：候选和最终写共用B/H资格；新绑定显式H；表单policy_editable/原因；Repository可接受现有UoW，无先改姓名再拒绝。
  **覆盖 AC**：AC-04, AC-05, AC-06, AC-07
  **依赖**：T016
  **配对测试**：T016通过后实现；结合本任务实际消费入口验证。

- [x] **T018**：绑定终止与回迁回归（测试）
  **文件**：`src/backend/test/user/test_managed_tenant_bindings.py`
  **逻辑/验证**：同H最后作用域支持、无scope直接策略、定义缩小再扩大、H迁移回迁、成员移动含兼属；只验scope本批结果。
  **覆盖 AC**：AC-09, AC-10, AC-11, AC-12, AC-13, AC-40
  **依赖**：T017

- [x] **T019**：同步绑定合法性/终止公开入口（后端Domain）
  **文件**：`src/backend/bisheng/user/application/policy_bindings.py`、`src/backend/bisheng/user/domain/repositories/policy_binding_repository.py`
  **逻辑/验证**：以最终事实同步保留/删除普通绑定，绑定变更附现有审计事实；不造来源/操作账本；提供给所属领域UoW。
  **覆盖 AC**：AC-09, AC-10, AC-11, AC-12, AC-40
  **依赖**：T018
  **配对测试**：T018通过后实现；结合本任务实际消费入口验证。

- [x] **T020**：角色定义变更同步终止（后端Domain）
  **文件**：`src/backend/bisheng/role/domain/services/role_service.py`、`src/backend/bisheng/role/domain/repositories/role_definition_repository.py`
  **逻辑/验证**：定义scope/删除与失效绑定在同SQL事务经user公开端口完成；统一角色→用户锁序，新授予锁内重验；不是只读过滤。
  **覆盖 AC**：AC-10, AC-11, AC-40
  **依赖**：T019
  **配对测试**：T018通过后实现；结合本任务实际消费入口验证。

- [x] **T021**：成员/组织SQL变更的终止（后端Domain）
  **文件**：`src/backend/bisheng/department/domain/services/department_service.py`、`src/backend/bisheng/user/domain/services/user_department_service.py`
  **逻辑/验证**：把user终止接口接现有成员退出/归档/move/主属UoW；枚举主属+兼属，保持两种主属关系结果；同步异常明示。
  **覆盖 AC**：AC-09, AC-11, AC-12, AC-13, AC-14
  **依赖**：T019, T020
  **配对测试**：T018通过后实现；结合本任务实际消费入口验证。

- [x] **T022**：迁移/挂载后的策略收敛检查（后端Domain）
  **文件**：`src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py`、`src/backend/bisheng/tenant/domain/services/tenant_mount_service.py`
  **逻辑/验证**：触及的迁移/挂载在正常流程终止旧绑定；不一致读拒绝，异常不伪装成功；不重做凭据/后台全效果编排。
  **覆盖 AC**：AC-09, AC-12, AC-13, AC-14, AC-40
  **依赖**：T021
  **配对测试**：T018通过后实现；结合本任务实际消费入口验证。

- [x] **T023**：SSO默认差集回归（测试）
  **文件**：`src/backend/test/sso_sync/test_managed_tenant_defaults.py`
  **逻辑/验证**：同快照人工撤销不重发、真正新成员/新H激活合法种子、外国兼属不发；现有事件幂等/管理身份保留。
  **覆盖 AC**：AC-05, AC-08, AC-14, AC-15
  **依赖**：T019

- [x] **T024**：SSO角色发放修复（后端Domain）
  **文件**：`src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`
  **逻辑/验证**：捕获前后成员差集、权威H后发种子、显式H，保留直接策略；不在Root+bypass先造普通绑定。
  **覆盖 AC**：AC-05, AC-08, AC-14, AC-15
  **依赖**：T023
  **配对测试**：T023通过后实现；结合本任务实际消费入口验证。

### Wave 5

- [x] **T025**：审批和DSH消费者回归（测试）
  **文件**：`src/backend/test/approval/test_managed_tenant_labels.py`、`src/backend/test/dsh/test_managed_tenant_role_policy.py`
  **逻辑/验证**：角色label/ROLE匹配接E；读取故障拒绝；DSH普通/probe/unmetered原合同；不验强撤权屏障。
  **覆盖 AC**：AC-17, AC-18, AC-27
  **依赖**：T011

- [x] **T026**：审批/DSH当前角色读取（后端Domain）
  **文件**：`src/backend/bisheng/approval/domain/services/approval_gate.py`、`src/backend/bisheng/dsh/domain/repositories/subject_policy.py`
  **逻辑/验证**：审批异常不降regular_user；DSH role IDs接有效集合；不改Lua/direct/epoch；同步approval技能和公共场景回归。
  **覆盖 AC**：AC-17, AC-18, AC-27
  **依赖**：T025
  **配对测试**：T025通过后实现；结合本任务实际消费入口验证。

- [x] **T027**：创建权限原账本恢复回归（测试）
  **文件**：`src/backend/test/permission/test_managed_tenant_creation_recovery.py`
  **逻辑/验证**：receipt丢失按稳定key恢复原冻结计划，Owner finalize、目标/actor/租户/model冲突拒绝；FAILED_CLOSED不另造key。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-36
  **依赖**：T001, T005

- [x] **T028**：固定创建权限窄恢复入口（后端Domain）
  **文件**：`src/backend/bisheng/permission/application/creation_recovery.py`、`src/backend/bisheng/permission/application/control_state.py`
  **逻辑/验证**：只暴露固定创建查询/原计划恢复和owner finalization；校验完整资源范围/原actor；业务不读权限ORM。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-36
  **依赖**：T027
  **配对测试**：T027通过后实现；结合本任务实际消费入口验证。

### Wave 6

- [x] **T029**：工具非空父子创建回归（测试）
  **文件**：`src/backend/test/tool/test_managed_tenant_creation.py`
  **逻辑/验证**：API/MCP非空children同T，子SQL失败无父，hook失败pending，按原key受控恢复。
  **覆盖 AC**：AC-01, AC-28, AC-30, AC-36
  **依赖**：T001, T028

- [x] **T030**：工具原事务及权限就绪（后端Domain）
  **文件**：`src/backend/bisheng/tool/domain/models/gpts_tools.py`、`src/backend/bisheng/tool/domain/services/tool.py`
  **逻辑/验证**：修现有insert父子一次commit/继承T；Service冻结合法T，PENDING→权限→READY；未知不删。
  **覆盖 AC**：AC-01, AC-28, AC-30, AC-36
  **依赖**：T029
  **配对测试**：T029通过后实现；结合本任务实际消费入口验证。

- [x] **T031**：工具所有正常消费pending拒绝（测试）
  **文件**：`src/backend/test/tool/test_managed_tenant_readiness.py`
  **逻辑/验证**：sync/async单批executor、列表详情/编辑/删除/派生在super前拒绝PENDING；预置工具保持。
  **覆盖 AC**：AC-30, AC-37
  **依赖**：T030

- [x] **T032**：工具消费就绪门禁（后端Domain）
  **文件**：`src/backend/bisheng/tool/domain/services/executor.py`、`src/backend/bisheng/tool/domain/services/f048_tool_permission.py`
  **逻辑/验证**：消费父creation_state，位置在super前，单批路径均覆盖；必要列表/详情复用同业务检查。
  **覆盖 AC**：AC-30, AC-37
  **依赖**：T031
  **配对测试**：T031通过后实现；结合本任务实际消费入口验证。

- [x] **T033**：工作流父版本及消费回归（测试）
  **文件**：`src/backend/test/workflow/test_managed_tenant_creation.py`
  **逻辑/验证**：真实Flow/v0同T；权限未知PENDING；列表/详情/版本/运行/发布/队列/派生前拒绝；其他flow类型保持。
  **覆盖 AC**：AC-01, AC-29, AC-30, AC-37
  **依赖**：T001, T028

- [x] **T034**：工作流目标与创建就绪（后端API）
  **文件**：`src/backend/bisheng/api/v1/workflow.py`、`src/backend/bisheng/database/models/flow.py`
  **逻辑/验证**：flow/v0显式继承T；保持单事务；原creator权限adapter确认前PENDING，正常SQL失败回滚。
  **覆盖 AC**：AC-01, AC-29, AC-30
  **依赖**：T033
  **配对测试**：T033通过后实现；结合本任务实际消费入口验证。

- [x] **T035**：工作流正常消费者门禁（后端Domain）
  **文件**：`src/backend/bisheng/api/services/flow.py`、`src/backend/bisheng/database/models/flow.py`
  **逻辑/验证**：精确workflow父READY检查和列表过滤；让现有版本/运行/发布/派生调用复用，避免改assistant产品语义。
  **覆盖 AC**：AC-30, AC-37
  **依赖**：T034
  **配对测试**：T033通过后实现；结合本任务实际消费入口验证。

### Wave 7

- [x] **T036**：复制预留/关联/未知提交回归（测试）
  **文件**：`src/backend/test/knowledge/test_managed_tenant_copy.py`
  **逻辑/验证**：文档QA真实SQL同源T；权限/Broker失败可关联；未知commit按固定target读，不盲删/重建。
  **覆盖 AC**：AC-01, AC-31, AC-32, AC-34
  **依赖**：T002, T028

- [x] **T037**：复制同SQL预留与前置路径（后端Domain）
  **文件**：`src/backend/bisheng/knowledge/domain/repositories/copy_repository.py`、`src/backend/bisheng/knowledge/domain/services/knowledge_service.py`
  **逻辑/验证**：source/target/两指针原子预留，不用覆写H的建库helper；actor真实，projection原key；错误携定位ID。
  **覆盖 AC**：AC-01, AC-31, AC-32, AC-34
  **依赖**：T036
  **配对测试**：T036通过后实现；结合本任务实际消费入口验证。

- [x] **T038**：复制worker唯一领取/失败回归（测试）
  **文件**：`src/backend/test/knowledge/test_managed_copy_worker.py`
  **逻辑/验证**：UNPUBLISHED→COPYING唯一CAS；重复不推进；条件发布释放不覆盖新占用；已观察局部失败不得全成功。
  **覆盖 AC**：AC-30, AC-34, AC-35, AC-36
  **依赖**：T037

- [x] **T039**：文档复制worker修复（Worker）
  **文件**：`src/backend/bisheng/worker/knowledge/file_worker.py`、`src/backend/bisheng/knowledge/domain/repositories/copy_repository.py`
  **逻辑/验证**：可信Celery headers→ContextVar，核对持久T和source/target，唯一领取；正确报告失败和条件finalize；未知无自动重放。
  **覆盖 AC**：AC-30, AC-34, AC-35, AC-36
  **依赖**：T038
  **配对测试**：T038通过后实现；结合本任务实际消费入口验证。

- [x] **T040**：QA复制worker及入口保护（Worker）
  **文件**：`src/backend/bisheng/worker/knowledge/qa.py`、`src/backend/bisheng/knowledge/domain/models/knowledge.py`
  **逻辑/验证**：同样可信headers→ContextVar、唯一领取/条件终态；普通/super对未准备copy目标拒绝；保留正常库/共享。
  **覆盖 AC**：AC-30, AC-34, AC-35, AC-36, AC-37
  **依赖**：T039
  **配对测试**：T038通过后实现；结合本任务实际消费入口验证。

### Wave 8

- [x] **T041**：部门角色编辑状态（前端Platform）
  **文件**：`src/frontend/platform/src/pages/DepartmentPage/components/OrganizationMemberEditDialog.tsx`、`src/frontend/platform/src/controllers/API/department.ts`
  **逻辑/验证**：消费policy_editable/原因，跨租户不提交role字段，同H共享提示；仅platform，API经controllers，三语现有文案体系。
  **覆盖 AC**：AC-05, AC-06, AC-07
  **依赖**：T017
  **手动验证**：测试部署用A主属/B兼属及管理员分别打开部门人员表单，核对字段禁用/不提交、错误提示三语；环境未提供时记录未验收，不伪造。

- [x] **T042**：错误/状态必要文案第一批（前端Platform）
  **文件**：`src/frontend/packages/locales/src/api_errors/en.json`、`src/frontend/packages/locales/src/api_errors/zh-Hans.json`
  **逻辑/验证**：新增5码对应清晰文案，未知配额非0；保留全部既有翻译。
  **覆盖 AC**：AC-18, AC-23, AC-24, AC-30
  **依赖**：T004, T005
  **手动验证**：测试部署用A主属/B兼属及管理员分别打开部门人员表单，核对字段禁用/不提交、错误提示三语；环境未提供时记录未验收，不伪造。

- [x] **T043**：错误文案日语（前端Platform）
  **文件**：`src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑/验证**：对应新错误三语齐全，按前端i18n规则验证；不建新页面/轮询。
  **覆盖 AC**：AC-18, AC-23, AC-24, AC-30
  **依赖**：T042
  **手动验证**：测试部署用A主属/B兼属及管理员分别打开部门人员表单，核对字段禁用/不提交、错误提示三语；环境未提供时记录未验收，不伪造。

- [x] **T044**：额度输出适配（后端API）
  **文件**：`src/backend/bisheng/role/api/endpoints/quota.py`、`src/backend/bisheng/role/domain/schemas/role_schema.py`
  **逻辑/验证**：effective保留原字段+available/usage_state，统计未知明确错误，不变个人H语义。
  **覆盖 AC**：AC-16, AC-22, AC-23
  **依赖**：T015

- [x] **T045**：只读盘点与拒绝回归（测试）
  **文件**：`src/backend/test/tenant/test_managed_tenant_preflight.py`
  **逻辑/验证**：精确租户/主体盘点归属差异、pending/无关联旧孤儿；断言不执行数据写、不自动移动/删除。
  **覆盖 AC**：AC-39, AC-40
  **依赖**：T011, T015, T037

- [x] **T046**：只读交付盘点脚本（后端Domain）
  **文件**：`src/backend/scripts/managed_tenant_preflight.py`、`src/backend/scripts/README.md`
  **逻辑/验证**：只读输出范围内绑定/菜单/配额/审批/DSH差异及pending/复制关联，限定租户/用户；无apply，先读scripts规则。
  **覆盖 AC**：AC-39, AC-40
  **依赖**：T045
  **配对测试**：T045通过后实现；结合本任务实际消费入口验证。

### Wave 9

- [ ] **T047**：API端到端覆盖与浏览器清单（测试）
  **文件**：`src/backend/test/e2e/test_e2e_managed_tenant_consistency.py`、`/Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/features/v3.1.0-beta1/009-managed-tenant-consistency/verification.md`
  **逻辑/验证**：按e2e技能覆盖本批API允许拒绝、GET确认最终状态；专用数据前缀+cleanup；环境缺失如实记录；browser只验证platform必要交互。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-34, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40
  **依赖**：T001, T002, T003, T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015, T016, T017, T018, T019, T020, T021, T022, T023, T024, T025, T026, T027, T028, T029, T030, T031, T032, T033, T034, T035, T036, T037, T038, T039, T040, T041, T042, T043, T044, T045, T046, T049, T050

- [x] **T048**：任务/特性级最终审查（审查）
  **文件**：`/Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/features/v3.1.0-beta1/009-managed-tenant-consistency/task-reviews.md`、`/Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/features/v3.1.0-beta1/009-managed-tenant-consistency/code-review.md`
  **逻辑/验证**：逐任务L1及特性SDD七维审查；arch-guard、必要pytest/ruff/i18n、DDL单head；只报真实结果，不标延期AC完成；无合并部署。
  **覆盖 AC**：AC-01, AC-30, AC-39
  **依赖**：T047

## 调用链复核补充任务（已实施，未增加功能范围）

- [x] **T051**：旧人员入口接入本人H绑定（后端API）
  **文件**：`src/backend/bisheng/user/api/user.py`、`src/backend/bisheng/user/domain/services/user.py`
  **逻辑/验证**：旧建人接口先验证Root合法角色；角色重置走公共绑定端口，不以管理M或外国兼属授予。
  **覆盖 AC**：AC-04, AC-06, AC-15
  **依赖**：T019

- [x] **T052**：旧人员入口回归（测试）
  **文件**：`src/backend/test/user/test_managed_tenant_legacy_roles.py`
  **逻辑/验证**：真实绑定写入H、外国管理员拒绝、无效角色在User插入前拒绝。
  **覆盖 AC**：AC-04, AC-06
  **依赖**：T051

- [x] **T053**：复制可信执行上下文（Worker）
  **文件**：`src/backend/bisheng/worker/tenant_context.py`、`src/backend/bisheng/knowledge/application/copy_execution.py`
  **逻辑/验证**：仅两个复制任务要求可信header；持久源目标、当前actor与T核对，执行前及发布前授权。
  **覆盖 AC**：AC-30, AC-36
  **依赖**：T038

- [x] **T054**：工具内部创建状态端口（后端Domain）
  **文件**：`src/backend/bisheng/tool/application/creation.py`、`src/backend/bisheng/tool/domain/repositories/creation_repository.py`
  **逻辑/验证**：精确恢复读与READY CAS；负向状态门禁不提供权限ALLOW。
  **覆盖 AC**：AC-28, AC-30
  **依赖**：T031

- [x] **T055**：工作流内部创建状态端口（后端Domain）
  **文件**：`src/backend/bisheng/workflow/application/creation.py`、`src/backend/bisheng/workflow/domain/repositories/creation_repository.py`
  **逻辑/验证**：精确恢复读与READY CAS；不公开include_pending。
  **覆盖 AC**：AC-29, AC-30
  **依赖**：T033

- [x] **T056**：权限正常消费前置门禁（后端Domain）
  **文件**：`src/backend/bisheng/permission/application/business_authorization.py`、`src/backend/bisheng/api/services/f048_application_permission.py`
  **逻辑/验证**：single/batch、super/public之前拒绝半成品，生命周期创建保留原接口。
  **覆盖 AC**：AC-30, AC-37
  **依赖**：T031, T033

- [x] **T057**：工作流版本消费门禁（后端Domain）
  **文件**：`src/backend/bisheng/database/models/flow_version.py`
  **逻辑/验证**：父READY约束版本读/写；创建v0沿父事务；联合应用列表和simple读另由T035覆盖。
  **覆盖 AC**：AC-29, AC-30
  **依赖**：T033

- [x] **T058**：只读盘点所属接口（后端Domain）
  **文件**：`src/backend/bisheng/tenant/application/managed_tenant_preflight.py`、`src/backend/bisheng/tenant/domain/repositories/managed_tenant_preflight.py`
  **逻辑/验证**：范围/上限显式；报告绑定、普通菜单/配额/标签、可选DSH、权限SQL及pending/关联；未知不当0。
  **覆盖 AC**：AC-39, AC-40
  **依赖**：T045

- [x] **T059**：DSH普通读取去除无用全树查询（后端Domain）
  **文件**：`src/backend/bisheng/dsh/domain/repositories/unified_policy.py`
  **逻辑/验证**：当前调用只读本人政策事实，目录管理仍按B读取；sync reader可沿现有session读取同UoW。
  **覆盖 AC**：AC-17, AC-18, AC-27
  **依赖**：T026

- [x] **T060**：人员共享绑定提示英中（前端Platform）
  **文件**：`src/frontend/platform/public/locales/en-US/bs.json`、`src/frontend/platform/public/locales/zh-Hans/bs.json`
  **逻辑/验证**：外国兼属不可编辑和同H共享绑定提示，沿既有i18n。
  **覆盖 AC**：AC-05, AC-07
  **依赖**：T041

- [x] **T061**：人员共享绑定提示日语（前端Platform）
  **文件**：`src/frontend/platform/public/locales/ja/bs.json`
  **逻辑/验证**：日语键与中英一致。
  **覆盖 AC**：AC-05, AC-07
  **依赖**：T060

- [x] **T062**：工具实际增量与责任范围（后端Domain）
  **文件**：`src/backend/bisheng/tool/domain/services/tool.py`、`src/backend/bisheng/tool/domain/models/gpts_tools.py`
  **逻辑/验证**：非空创建按子项delta，更新按责任人净增量/租户净增量独立判断；子项继承父T及creator；零增量维护保留。
  **覆盖 AC**：AC-21, AC-22, AC-23, AC-27
  **依赖**：T015, T030

- [x] **T063**：工具增量回归（测试）
  **文件**：`src/backend/test/tool/test_managed_tenant_update.py`
  **逻辑/验证**：有限额度所有有效角色一致配置，覆盖净增/替换/迁出/父子T。
  **覆盖 AC**：AC-21, AC-22, AC-23
  **依赖**：T062

- [x] **T064**：创建账本恢复实现（后端Domain）
  **文件**：`src/backend/bisheng/permission/application/runtime.py`、`src/backend/bisheng/permission/domain/repositories/creation_recovery_repository.py`
  **逻辑/验证**：固定key、冻结计划、原actor与catalog校验；PREPARED缺owner使用同key；FINALIZED后owner/assignee/visible镜像完成。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-36
  **依赖**：T027

- [x] **T065**：角色和配额旧单测接口迁移（测试）
  **文件**：`src/backend/test/role/test_role_service.py`、`src/backend/test/quota/test_quota_service.py`
  **逻辑/验证**：替身从旧DAO/SQL字符串转为E和定义仓储；保留业务断言，真实SQL另见F009回归；缺失租户明确不可用。
  **覆盖 AC**：AC-02, AC-20, AC-23
  **依赖**：T007, T015

- [x] **T066**：租户配额链旧回归接口迁移（测试）
  **文件**：`src/backend/test/quota/test_quota_service_check_chain.py`、`src/backend/test/quota/test_quota_service_tenant_tree.py`
  **逻辑/验证**：独立角色余额/租户链；未知指标19404，保留Root/存储错误。
  **覆盖 AC**：AC-22, AC-23, AC-27
  **依赖**：T015

- [x] **T067**：额度装饰器与DSH事实回归（测试）
  **文件**：`src/backend/test/quota/test_require_quota_decorator.py`、`src/backend/test/dsh/test_subject_policy.py`
  **逻辑/验证**：断言delta；修复测试域主属/组织事实，DSH同session当前绑定消费及原预算优先规则。
  **覆盖 AC**：AC-17, AC-21, AC-27
  **依赖**：T026, T062

- [x] **T068**：审批技能同步（文档）
  **文件**：`.claude/skills/approval-module/SKILL.md`
  **逻辑/验证**：文档指向统一E及对应测试，不复制技能源。
  **覆盖 AC**：AC-17, AC-18
  **依赖**：T026

- [x] **T069**：旧同步编排测试端口适配（测试）
  **文件**：`src/backend/test/sso/test_sso_login_sync_service.py`、`src/backend/test/user/test_user_tenant_sync_service.py`
  **逻辑/验证**：新增绑定端口作窄替身；失败投影不得伪装同步成功；历史基线失败另列。
  **覆盖 AC**：AC-08, AC-12, AC-13
  **依赖**：T022, T024

- [x] **T070**：工具执行器旧测试父状态事实（测试）
  **文件**：`src/backend/test/tool/test_tool_executor_permissions.py`
  **逻辑/验证**：旧替身增加真实模型原有preset与新READY事实；FGA允许拒绝断言保留。
  **覆盖 AC**：AC-30
  **依赖**：T032

- [x] **T071**：组织后置同步结果显式失败（后端Domain）
  **文件**：`src/backend/bisheng/tenant/application/sync_result.py`
  **逻辑/验证**：部门/挂载已有SQL提交后，返回19102及committed/failed_user_ids；不伪装全员同步成功，不新增续办账本。
  **覆盖 AC**：AC-13, AC-14
  **依赖**：T022

## 实际偏差记录

T011前置完成T017/T019的只读主体事实接口；写入/终止随后完成。T049/T050补足调用链发现的实际info/Quota业务消费者，未扩大已确认需求；论证同步design §4.2/§4.4。

补充T051–T070记录实际生产者/消费者和旧单测替身适配；没有增加表、恢复中心或延期AC承诺。前端生成错误码产物由源locale生成，六份产物不作为手写目标。T047仅3条HTTP用例已编写且本地skip，完整QA矩阵和浏览器尚待隔离环境；T048本地七维审查记录已写，但合入门禁未通过，均不打勾。

最终基线核对：本地缓存origin发布线已领先2156提交、38路径重叠；未fetch/合并，不能将当前局部实现称为对当前发布线已集成。T048明确包含后续同步、冲突/迁移head核对与重跑，保持未勾选。

## 2026-11-11 用户要求合并后的集成记录

实际fetch df927a7f6e，解决13文件冲突；保留F118 workflow参考绑定/迁移来源个人豁免/挂载覆盖事务及worker执行证明。新增空merge migration；补挂载factory真实同事务终止用例，适配F118创建/配额旧合同测试及unmount窄替身，修复人员弹窗类型推断。不是新增AC或新业务表。

T048本地集成复核已完成并按用户明确授权合并；T047真实HTTP/浏览器仍未执行，依赖例外为本次用户已知待验项后的明确合并指令，不伪造完成。最新去重353 passed / 10基线失败及87本批回归见merge-validation.json；此前“未fetch/未合并”的记录为历史快照。
