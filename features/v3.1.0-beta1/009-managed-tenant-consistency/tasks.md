# Tasks: 管理租户最小修复

术语说明：本文技术符号和英文状态值统一见[术语与缩写说明](terminology.md)；H为用户主属租户，M为当前管理目标租户。业务阅读可直接参阅使用中文全称的[影响范围与测试重点](../../../docs/reviews/managed-tenant-impact-test-focus-20261111.md)。

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

## 2026-11-13 第一阶段追加任务

用户明确授权修订方案第一阶段；原任务属于旧批次，不计作本轮验收。以下按业务链的测试、实现和文档拆成至多两文件的原子步骤。测试行仅含测试，不混业务实现。列表是当前依赖及验收关系，不是执行时序日志：目标头缺陷已观察先红后绿，其余含实现后补充的回归，不追记为全部测试先行。

本次无新表列或迁移，无Worker实现任务：Celery headers传递及Worker ContextVar恢复格式保留，未新增从Redis读取后续选择。Client、Java及其他业务链无实现任务。

- [x] **T072**（文档）：同步第一阶段AC、用户授权及零历史修数边界。文件：`features/v3.1.0-beta1/009-managed-tenant-consistency/spec.md`、`features/v3.1.0-beta1/009-managed-tenant-consistency/scope-revision.md`。依赖：无。
- [x] **T073**（文档）：登记显式类型、导航响应及既有范围/消息格式兼容。文件：`features/v3.1.0-beta1/009-managed-tenant-consistency/design.md`、`features/v3.1.0-beta1/release-contract.md`。依赖：T072。
- [x] **T074**（文档）：按八列模板追加独立QA及真实验收清单。文件：`features/v3.1.0-beta1/009-managed-tenant-consistency/test-cases.md`、`features/v3.1.0-beta1/009-managed-tenant-consistency/e2e-checklist.md`。依赖：T073。
- [x] **T075**（后端测试）：验证六种写入缺/错/匹配目标、访客读取及当前资格/未知拒绝。文件：`src/backend/test/admin/test_f114_scope_middleware.py`、`src/backend/test/admin/test_current_super_qualification.py`。依赖：T074。 覆盖 AC: AC-41, AC-45, AC-46。
- [x] **T076**（后端测试）：验证窄HTTP响应不解析运行引用、展示不伪造个人政策。文件：`src/backend/test/workstation/test_navigation_config.py`、`src/backend/test/dsh/test_model_display_catalog.py`。依赖：T074。 覆盖 AC: AC-42。
- [x] **T077**（后端测试）：真实Home检索初始化、固定连接目标/恢复、错目标及受信设备隔离。文件：`src/backend/test/knowledge/test_space_flow_retrieval.py`、`src/backend/test/workflow/test_browser_scope.py`。依赖：T074。 覆盖 AC: AC-43, AC-48。
- [x] **T078**（后端测试）：显式类型/默认本地、普通用户拒绝及真实SQLite旧定义菜单归属。文件：`src/backend/test/role/test_role_service.py`、`src/backend/test/role/test_managed_tenant_role.py`。依赖：T074。 覆盖 AC: AC-02, AC-44。
- [x] **T079**（前端Platform测试）：写目标清单/通用上传兼容及辅助404保页、原403保持。文件：`src/frontend/platform/src/controllers/managementScope.test.ts`、`src/frontend/platform/src/controllers/requestCompatibilityMatrix.test.ts`。依赖：T074。 覆盖 AC: AC-41, AC-45, AC-47。
- [x] **T080**（前端Platform测试）：表单默认tenant及显式global的创建载荷。文件：`src/frontend/platform/src/pages/SystemPage/components/Roles.creation.test.tsx`。依赖：T074。 覆盖 AC: AC-44。
- [x] **T081**（后端Domain）：既有准入加入访客/上传写路径及当前资格，保留原Redis键和权威来源。文件：`src/backend/bisheng/common/middleware/admin_scope.py`、`src/backend/bisheng/utils/http_middleware.py`。依赖：T075。
- [x] **T082**（后端Domain）：按请求标记刷新资格；验证后才设置私有设备目标；冻结浏览器连接范围并核验流程。文件：`src/backend/bisheng/user/domain/services/auth.py`、`src/backend/bisheng/workflow/application/browser_scope.py`。依赖：T081, T077。
- [x] **T083**（后端Domain）：导航仅图标、无初始化；跨主属管理只展示已验证配置，执行仍用个人政策。文件：`src/backend/bisheng/workstation/domain/services/workstation_service.py`、`src/backend/bisheng/dsh/domain/services/model_catalog.py`。依赖：T076。
- [x] **T084**（后端API）：可选navigation窄响应及展示投影接线，完整配置仍校验引用。文件：`src/backend/bisheng/workstation/api/endpoints/config.py`、`src/backend/bisheng/llm/api/router.py`。依赖：T083。
- [x] **T085**（后端Domain）：不把资源目标当预期Home；权威当前身份且不改变ContextVar。文件：`src/backend/bisheng/knowledge/domain/services/space_flow_retrieval.py`。依赖：T077。
- [x] **T086**（后端Domain）：可选类型默认tenant、显式global平台资格、Root新定义及旧定义/菜单所有者保留。文件：`src/backend/bisheng/role/domain/schemas/role_schema.py`、`src/backend/bisheng/role/domain/services/role_service.py`。依赖：T078。
- [x] **T087**（后端API）：授权角色元数据展示及工作流连接窄端口接线，保留动作权限/结构化错误。文件：`src/backend/bisheng/role/api/endpoints/role.py`、`src/backend/bisheng/api/v1/workflow.py`。依赖：T082, T086。
- [x] **T088**（前端Platform）：匹配后台新增写路径；业务辅助404保页、现有刷新及403保留。文件：`src/frontend/platform/src/controllers/managementScope.ts`、`src/frontend/platform/src/controllers/request.ts`。依赖：T079。
- [x] **T089**（前端Platform）：全局导航用可选purpose，完整运行调用保留。文件：`src/frontend/platform/src/controllers/API/index.ts`、`src/frontend/platform/src/contexts/locationContext.tsx`。依赖：T084。
- [x] **T090**（前端Platform）：创建类型及可见定义owner类型增量。文件：`src/frontend/platform/src/controllers/API/user.ts`、`src/frontend/platform/src/types/api/user.ts`。依赖：T086。
- [x] **T091**（前端Platform）：默认本地/显式共享选择；编辑类型只读、展示owner；无部门不标共享。文件：`src/frontend/platform/src/pages/SystemPage/components/Roles.tsx`、`src/frontend/platform/src/pages/SystemPage/components/RolesView.tsx`。依赖：T090, T080。
- [x] **T092**（前端Platform）：新增中文/英文类型、所有者及作用域词条。文件：`src/frontend/platform/public/locales/zh-Hans/bs.json`、`src/frontend/platform/public/locales/en-US/bs.json`。依赖：T091。
- [x] **T093**（前端Platform）：对应日文词条，与已有组件语言一致。文件：`src/frontend/platform/public/locales/ja/bs.json`。依赖：T092。
- [x] **T094**（端到端测试）：追加导航与错误目标负向请求；专用fixture缺失本次9跳过，未变现场数据。文件：`src/backend/test/e2e/test_e2e_managed_tenant_consistency.py`。依赖：T087, T088, T089, T093。 覆盖 AC: AC-41, AC-42, AC-45, AC-48。
- [x] **T095**（文档）：标明仅第一阶段/角色第一步本地交付，历史修正和行政承接未实施。文件：`docs/reviews/tenant-context-unification-proposal-20261113.md`、`docs/reviews/tenant-role-minimal-change-plan-20261113.md`。依赖：T094。
- [x] **T096**（本地验证/审查）：本地定向/兼容/前端回归、Ruff/架构及合规自审，基线失败和真实验收缺口单列。文件：`features/v3.1.0-beta1/009-managed-tenant-consistency/phase1-delivery.md`、`features/v3.1.0-beta1/009-managed-tenant-consistency/phase1-code-review.md`。依赖：T095。
- [ ] **T097**（现场验收）：待专用身份/数据及匹配版本部署后验证HTTP、浏览器、MySQL/DM8及网关；禁止使用116已有业务数据代替。文件：`features/v3.1.0-beta1/009-managed-tenant-consistency/e2e-checklist.md`、`features/v3.1.0-beta1/009-managed-tenant-consistency/test-cases.md`。依赖：T096。 覆盖 AC: AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48。

T094打勾表示完成用例编写及执行尝试，端到端结果仍为PARTIAL（部分验证）；T097和旧T047保持待执行，未将跳过标为现场通过。任务自审和复盘偏差见[第一阶段审查](phase1-code-review.md)，实际验证结果见[第一阶段交付](phase1-delivery.md)。

## 第二、三阶段（2026-11-14）

用户授权继续完成，沿统一方案；历史修数与行政承接不纳入。以下为增量业务链依赖，原子文件步骤在交付记录保留。目标头/登记/流的新增测试已观察先红后绿，历史关系与任务恢复等为实现后补充，不能追记全量测试先行。组织页边界已由用户明确确认为所选租户挂载子树。实现及验证见phase23-delivery.md；真实现场验收单列。

- [ ] T098：范围登记和继承测试；文件test/admin/test_request_scope_registry.py；覆盖 AC: AC-49, AC-58。
- [ ] T099：准入/流及目标负向测试；文件test/admin/test_request_scope_admission.py、test/permission/test_management_target_boundary.py；覆盖 AC: AC-50, AC-52, AC-53。
- [x] T100：通用元数据与选路后准入；文件common/request_scope.py、admin/application/request_admission.py；依赖T098、T099。
- [x] T101：显式范围自举和管理证明；文件admin/api/endpoints/request_scope.py、admin/api/router.py；依赖T100。
- [x] T102：真实身份复用及严格选择；文件user/domain/services/auth.py、admin/domain/services/tenant_scope.py；依赖T101。
- [x] T103：根路由/生命周期和CORS；文件api/router.py、main.py；依赖T102。
- [x] T104：混合范围组接线；文件dsh/api/router.py、open_api/api/router.py；依赖T103。
- [x] T105：应用和审批组例外；文件app_runtime/api/router.py、approval/api/router.py；依赖T103。
- [x] T106：租户身份例外/冻结事实复用；文件tenant/api/router.py、admin/application/tenant_scope.py；依赖T103。
- [x] T107：资源动作前的目标边界；文件permission/application/business_authorization.py、resource_authorization.py；依赖T099。
- [x] T108：浏览器连接不重读选择；文件workflow/application/browser_scope.py、api/v1/workflow.py；依赖T100。
- [x] T109：统一前端范围会话及元数据生成；文件packages/api-client/src/browserScope.ts、backend/scripts/export_request_scopes.py；依赖T103。
- [x] T110：前端并发自举/外部URL测试；文件packages/api-client/src/browserScope.test.ts；覆盖 AC: AC-51, AC-58；依赖T109。
- [x] T111：Platform请求准入；文件controllers/managementScope.ts、controllers/request.ts；依赖T109。
- [x] T112：切换未知重读/原生流；文件controllers/API/admin.ts、controllers/requestStream.ts；依赖T111。
- [x] T113：Client请求准入；文件client/src/api/request.ts；依赖T109。
- [x] T114：Client对话SSE；文件hooks/useAiChatSSE.ts、hooks/useStreamChatSSE.ts；依赖T113。
- [x] T115：Client任务SSE；文件hooks/useLinsightManager.tsx；依赖T113。覆盖 AC: AC-51, AC-52。
- [x] T116：移除退役用户组资源前端残留；文件controllers/API/pro.ts、components/Pro/FlowControl.tsx；依赖T111。
- [x] T117：历史关系只读盘点；文件tenant/domain/repositories/context_preflight.py；覆盖 AC: AC-57。
- [x] T118：预检应用入口/命令；文件tenant/application/managed_tenant_preflight.py、scripts/managed_tenant_preflight.py；依赖T117。
- [x] T119：工作流/导出持久目标事实；文件workflow/domain/repositories/creation_repository.py、app_governance/domain/repositories/runtime_audit_export_repository.py；依赖T100。
- [x] T120：任务消息和执行体共同围栏；文件worker/tenant_context.py、worker/workflow/tasks.py；依赖T119。
- [x] T121：导出执行；文件worker/runtime_audit/tasks.py；依赖T120。覆盖 AC: AC-56。
- [x] T122：网关资源/部门窄证明；文件admin/application/gateway_scope.py；依赖T107。
- [x] T123：网关独立工作树的范围声明、后端证明和管理控制器接线及Java回归；依赖T122，具体Java文件步骤在网关交付记录；不恢复旧用户组资源，不改历史网关表。
- [x] T124：按用户确认接入所选租户挂载子树，含Root排除子租户、目录存储翻译及账号/角色边界；回归见T126/T127。
- [x] T125：生成资料一致性检查、后端/两前端/网关定向回归、架构及文档自审；依赖T098～T124，真实环境端到端单列待执行。


补充原子落点（以下为验收关系，不追记为全部测试先行；原T115/T117/T121/T122/T123为业务链汇总，测试与实现分开）：

- [x] T126（测试）：组织边界、真实SQL/HTTP、兼属及账号初始化回归；文件test/department/test_management_directory_scope.py；覆盖AC-59。
- [x] T127（测试）：范围自举/切换审计未知；文件test/admin/test_request_scope_bootstrap.py；覆盖AC-51。
- [x] T128（实现）：目录范围事实/仓储；文件department/domain/schemas/directory_scope.py、domain/repositories/directory_repository.py。
- [x] T129（实现）：组织局部存储作用域及业务数据归位；文件department/domain/services/directory_scope.py、department_service.py。
- [x] T130（实现）：组织API依赖/路由；文件department/api/dependencies.py、api/router.py。
- [x] T131（实现）：组织搜索SQL和计数裁剪；文件department/domain/repositories/organization_search_repository.py、management_search_repository.py。
- [x] T132（实现）：既有规范所有者算法提供归档目录事实；文件department/domain/repositories/policy_scope_repository.py；活跃角色事实合同不变。
- [x] T133（实现）：账号只操作所选租户真实主属；文件user/application/management_subject.py、user/api/user.py。
- [x] T134（实现）：账号检索/创建初始化；文件user/domain/repositories/management_search_repository.py、domain/services/user.py。
- [x] T135（实现）：已知部门身份展示跨模块端口/本人主部门；文件department/application/directory.py、department/api/endpoints/department.py。
- [x] T136（实现）：授权展示与部门userset事实；文件tenant/domain/repositories/permission_subject_repository.py、domain/services/f048_permission_subject.py。
- [x] T137（实现）：变量父资源/版本和动作校验；文件workflow/application/variables.py、domain/repositories/variable_repository.py。
- [x] T138（API）：变量入口接线；文件api/v1/variable.py。
- [x] T139（测试）：变量跨租户、混批、伪造所有者及拒绝；文件test/workflow/test_variable_tenant_boundary.py。
- [x] T140（实现）：技能权限端口补齐负向归属读取；文件linsight/domain/services/skill_permission.py。
- [x] T141（测试）：Java后端证明/统一过滤器；文件gateway的DshSafetyAdminClientTest.java、ManagementBoundaryFilterTest.java。
- [x] T142（实现）：Java声明和选路过滤器；文件gateway的scope/RequestBoundary.java、ManagementBoundaryFilter.java。
- [x] T143（实现）：Java请求证明及DSH接线；文件gateway的client/DshSafetyAdminClient.java、controller/DshSensitivePolicyController.java。
- [x] T144（实现）：Java敏感词与部门限流接线；文件gateway的controller/SensitiveWordsController.java、DepartmentLimitController.java。
- [x] T145（实现）：Java旧组入口退役；文件gateway的controller/UserGroupController.java、GroupResourceController.java。
- [x] T146（实现）：Java公开协议声明；文件gateway的controller/OauthController.java、LicenseController.java。
- [x] T147（实现）：Java旧拦截日志显式平台范围；文件gateway的controller/BlockRecordController.java。
- [x] T148（测试）：历史关系SQL/扩展SQL目录；文件test/tenant/test_context_preflight.py。
- [x] T149（测试）：Client请求兼容及SSE异步准备；文件clientRequestContract.test.ts、useAiChatSSE.failure.test.ts。
- [x] T150（测试）：原生流拒绝错目标；文件platform/controllers/requestStream.test.ts。
- [x] T151（持续集成）：登记/生成资料/边界回归门禁；文件.github/workflows/tenant-context-quality.yml。
- [x] T152（端到端）：更新新目标合同和新增读取/本人身份用例，执行尝试12跳过；文件test/e2e/test_e2e_managed_tenant_consistency.py；不代表现场通过。
- [x] T153（文档/自审）：增量设计、交付和验证记录；文件phase23-delivery.md、phase23-code-review.md。T125指本地完成，不指整体质量门禁全绿或现场通过。
- [ ] T154（现场验收）：匹配部署后执行两前端/Java/Worker/Redis/OpenFGA/MySQL/DM8/存储及真实历史只读盘点；文件e2e-checklist.md、test-cases.md；覆盖AC-49～59。未部署、未推送。

- [x] T155（文档）：增量设计与现状设计同步；文件phase23-design.md、design.md。
- [x] T156（测试）：消息持久目标恢复/拒绝与合法平台任务；文件test/tenant/test_durable_task_scope.py。
- [x] T157（测试）：网关业务所有者/旧角色回退负向；文件test/admin/test_gateway_scope.py。

## 可选 Gateway 兼容修订（2026-11-16）

用户本轮明确授权旧协议兼容与首次拦截按主属；规格AC-60～AC-65及技术边界见optional-gateway-compat.md，覆盖既有联合升级决定。

- [x] T128：两个聊天回写身份准入、消息/会话持久归属校验及首次拦截主属；不改其他租户业务目标检查。
- [x] T129：旧请求与无Gateway本地回归、负向隔离、资料生成和架构检查。
- [x] T130：同步QA、合同与交付记录，区分本地验证和真实旧Gateway/双数据库验收。

本轮结果见optional-gateway-delivery.md和optional-gateway-validation.json；T129完成表示本地回归及现场用例执行尝试，不代表真实旧Java/浏览器/双数据库通过。现场待执行任务保持原状态。

- [x] T131：闭环首次拦截主属会话与后续正常工作流/助手执行的会话衔接；影响评估确认SQL冲突机制后，用户已授权并完成本地修复，完整旧Gateway时序仍待验证。对应TC-MTG-008、TC-MTG-009。

### T131修复执行分解

- [x] T131a：窄会话存储范围与原子保存，保持执行目标和持久归属分离。
- [x] T131b：助手/工作流正常继续、输入更新、历史重连及旧Gateway回写接入；不扩展列表或独立凭据范围。
- [x] T131c：原首次拦截测试保持，补真实正常写入路径及拒绝/恢复回归，更新QA与审查记录。

T131完成表示本地源码/回归与文档交付，真实旧Gateway/浏览器/MySQL/DM8待验不改为通过；结果见continuation-fix-delivery-20261116.md。
