# 昆联多租户与新用户自动开通任务

- **Feature ID**：`F130`
- **Version**：`v3.0.0`
- **Updated**：2026-11-13
- **关联**：[spec.md](./spec.md) · [design.md](./design.md) · [verification.md](./verification.md)

## 状态

| 步骤 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 原规格及 REQ-09 全租户 SSO 修订均已获用户确认。 |
| design.md | ✅ 已评审 | 原设计及 D-06／§9 全租户准入已获用户确认。 |
| tasks.md | ✅ 已拆解 | 全租户设计确认；按最新指令真实联调优先，取消独立 Mock 环境。 |
| 实现 | 进行中 | 原计划 32 / 42；追加成员列表修复 3 / 3 完成并经授权部署到 104，15 名用户关联与页面／SSO 验证通过；完整联合验收仍未完成；全租户 SSO 双端代码与必要回归完成；独立 Mock 环境取消，104 已经授权部署，双租户登录／切换／隔离通过；新增／停用与其他租户待执行。 |

## 实施与验收约定

- 2026-11-13：REQ-09 规格和 D-06／design.md §9 设计均已确认；本轮拆分全租户 SSO 增量 T046–T067，当前按用户最新指令直接真实联调；代码和回归已实施，部署已获后续明确授权。
- 历史开通批次采用 Mock 优先，T001–T032 及成员显示修复已按各自记录实施；本轮只推进全租户 SSO 增量，不改旧任务完成状态，不将整个特性标为完成。若源文件已有并发修改，先合并核对，不覆盖用户工作。
- 实施前核对工作树、分支及依赖提交；保持未提交联调修复，不自动暂存、提交、切换或清理用户工作。隔离分支遵循项目发版线规则，依赖未齐时先说明，不自动扩展到其他功能。
- 批次 A 完成后先做 B，尽早证明“可建 Workflow、不可建其他类型”，再接 C／D 的自动开通；E 证明完整链路。
- 权限、持久状态、并发及事务任务测试先行，先记录预期失败，再实现通过。基础声明不强制逐项红灯；同一批定向证据可复用，不每个任务重跑全套。
- 已完成任务的实际落点如下，未完成任务的新增源码仍为计划。任务只改列出范围；接口值对象、最小辅助函数放入对应文件，超出设计或新增持久对象须暂停确认。
- 后端测试使用已有 Python 环境，前端使用现有 pnpm；本表不授权安装依赖、改运行配置、真实建表、提交推送或部署。
- `# TODO [F130][EXT-01]` 多租户客户端范围、`EXT-02` 真实身份、`EXT-03` 时效契约保留；本批自身的角色门禁和补偿逻辑不得以 TODO 延后。
- 批次 B：定向后端／Platform 权限测试；C：Owner 模块测试；D：范围和调度联动；E：一组集成与浏览器闭环；F：一次相关回归和交付审查。真实 MySQL／DM8／OpenFGA／昆联验收保留 `NOT_RUN`。
- 后续部署授权：用户要求更新服务器及提交暂存区，已部署首批并核验三张 MySQL 空表及入口冒烟；记录见 [deployment-20261111.md](./deployment-20261111.md)。未启用自动开通或多租户新模式，不勾选尚未实施的任务。

## 任务

### 批次 A：基础设施

- [x] **T001**：基础设施：后端开通与范围配置
  - **文件**：`src/backend/bisheng/core/config/sso_sync.py`、`src/backend/bisheng/core/config/kunlian_scope.py`。
  - **内容**：声明默认关闭的自动开通、fixed／组合模式及受限组合解析；helper 只处理配置数据，不调用业务领域。
  - **覆盖 AC**：AC-06, AC-13。
  - _Requirements: REQ-01, REQ-04, REQ-07_
  - _Acceptance: AC-06, AC-13_
  - _Verification: V-01, V-04；按上述批次记录实际结果_
  - _Depends: 无_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T002**：基础设施：三个领域状态模型
  - **文件**：`src/backend/bisheng/tenant/domain/models/external_provision.py`、`src/backend/bisheng/role/domain/models/external_basic_role.py`、`src/backend/bisheng/user/domain/models/external_basic_access.py`。
  - **内容**：声明设计 §4.5 三表、稳定键、栅栏与墓碑；使用双库类型及标准 tenant_id，不改已有表、不回填数据。回退保留表与记录，只停准入及新预留。
  - **覆盖 AC**：AC-01, AC-09, AC-10。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-09, AC-10_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: 无_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T003**：基础设施：模型发现与租户过滤
  - **文件**：`src/backend/bisheng/core/database/tenant_filter.py`、`src/backend/test/database/test_kunlian_onboarding_metadata.py`、`src/backend/test/workflow/conftest.py`。
  - **内容**：登记三模型并验证模型发现、控制面／业务租户范围、整表创建及已有 Alembic 单 head。沿用升级前缺表补齐，不添加空迁移或在线建表；测试可用临时数据库。
  - **覆盖 AC**：AC-01, AC-06, AC-10, AC-13。
  - _Requirements: REQ-01, REQ-04, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-06, AC-10, AC-13_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T002_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T004**：基础设施：工作流创建菜单声明
  - **文件**：`src/backend/bisheng/database/models/role_access.py`。
  - **内容**：只新增 CREATE_WORKFLOW=create_workflow；不把它映射为 CREATE_APP，不改默认角色数据或已有 Grant。生效与门禁逻辑由后续任务完成。
  - **覆盖 AC**：AC-03, AC-04, AC-13。
  - _Requirements: REQ-03, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-13_
  - _Verification: V-01；按上述批次记录实际结果_
  - _Depends: 无_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T005**：基础设施：网关组合配置
  - **文件**：`../bisheng-gateway/src/main/java/com/dataelem/gateway/config/KunlianSsoProperties.java`、`../bisheng-gateway/src/main/java/com/dataelem/gateway/sso/kunlian/KunlianScopePolicy.java`。
  - **内容**：新增默认 fixed 的组合配置与纯判断 helper；拒绝空值、通配符及混用；保留旧配置。正式范围标记 TODO [F130][EXT-01]，不填写或更换真实凭据。
  - **配套验证文件**：后端 `test/sso/test_kunlian_scope_policy.py`，网关 `src/test/java/com/dataelem/gateway/sso/kunlian/KunlianScopePolicyTest.java`。包含真实配置绑定；新模式保持阶段门禁，T030 在双端接入后解除。
  - **覆盖 AC**：AC-06, AC-13。
  - _Requirements: REQ-04, REQ-07_
  - _Acceptance: AC-06, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T001_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

### 批次 B：工作流专属创建最小闭环

- [x] **T006**：测试：专属创建与通用权限兼容
  - **文件**：`src/backend/test/sso/test_kunlian_workflow_creation_access.py`、`src/backend/test/api/test_create_app_permission_gate.py`、`src/backend/test/workflow/test_kunlian_workflow_registration_e2e.py`。
  - **内容**：先构造只有 create_workflow、只有 create_app、两者均无、无效会话和越租户主体；验证 Workflow 成功、助手／托管应用／通用模板拒绝、类型伪造拒绝、配额及旧幂等查回前重新鉴权。断言 HTTP 与业务码。
  - **覆盖 AC**：AC-03, AC-04, AC-06, AC-13。
  - _Requirements: REQ-03, REQ-04, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-06, AC-13_
  - _Verification: V-01；按上述批次记录实际结果_
  - _Depends: T004_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T007**：实现：工作流专属后端门禁
  - **文件**：`src/backend/bisheng/user/domain/services/auth.py`、`src/backend/bisheng/api/v1/workflow.py`。
  - **内容**：新增 get_workflow_creator_user，并纳入有效菜单集合；Workflow 创建接受专属或既有通用能力，强制类型 10。助手等继续使用原通用依赖；不按来源或 scope 放行，不改配额、Owner 和幂等命名空间。
  - **覆盖 AC**：AC-03, AC-04, AC-06, AC-13。
  - _Requirements: REQ-03, REQ-04, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-06, AC-13_
  - _Verification: V-01；按上述批次记录实际结果_
  - _Depends: T006_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T008**：测试：角色菜单、路由与清单
  - **文件**：`src/frontend/platform/src/test/roleMenuSelection.test.ts`、`src/frontend/platform/src/test/resolveRoutePermissions.test.ts`、`src/frontend/platform/src/test/gov07NoNewPermissionPoint.test.ts`。
  - **内容**：增加 create_workflow 保存、父菜单关闭级联、默认未勾选及无通用能力的断言。F056 清单只登记新 Workflow 子能力，保留托管应用无专属权限点和旧默认菜单安全断言。
  - **覆盖 AC**：AC-03, AC-04, AC-13。
  - _Requirements: REQ-03, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-13_
  - _Verification: V-01；按上述批次记录实际结果_
  - _Depends: T004_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T009**：实现：角色配置与路由白名单
  - **文件**：`src/frontend/platform/src/pages/SystemPage/components/roleMenuSelection.ts`、`src/frontend/platform/src/pages/SystemPage/components/Roles.tsx`。`src/routes/index.tsx` 的现有解析已保留显式新键，直接复用并由 T008 验证，无需改动。
  - **内容**：将 create_workflow 作为 build 子项展示与保存；不默认勾选，不推导 create_app。保留角色编辑权限与通用路由规则，使用现有组件，不改变样式。
  - **覆盖 AC**：AC-03, AC-04, AC-13。
  - _Requirements: REQ-03, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-13_
  - _Verification: V-01；按上述批次记录实际结果_
  - _Depends: T008_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T010**：实现：三语角色文案
  - **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`、`src/frontend/platform/public/locales/en-US/bs.json`、`src/frontend/platform/public/locales/ja/bs.json`。
  - **内容**：同步新增“创建工作流”的菜单标签及必要说明；不手改生成的 api_errors 文件。按触达文件实际检查既有冻结中文与键一致性。
  - **覆盖 AC**：AC-03, AC-13。
  - _Requirements: REQ-03, REQ-07_
  - _Acceptance: AC-03, AC-13_
  - _Verification: V-05；按上述批次记录实际结果_
  - _Depends: T009_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T011**：测试：专用管理页的创建边界
  - **文件**：`src/frontend/platform/src/test/kunlianWorkflowCreationPermissions.test.tsx`、`src/frontend/platform/src/controllers/API/workflow.test.ts`、`src/frontend/platform/src/test/appTemplatePermissions.test.tsx`。复用未改动的 `src/test/kunlianWorkflowEntry.test.tsx` 验证原入口。
  - **内容**：仅专属能力时可新建 Workflow，不能打开通用类型选择器；旧 create_app 保持原能力；只读用户不能复制，原有新建目标与刷新不重复创建。
  - **覆盖 AC**：AC-03, AC-04, AC-07, AC-13。
  - _Requirements: REQ-03, REQ-04, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-07, AC-13_
  - _Verification: V-03；按上述批次记录实际结果_
  - _Depends: T004_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T012**：实现：新建、复制与入口衔接
  - **文件**：`src/frontend/platform/src/pages/BuildPage/apps.tsx`、`src/frontend/platform/src/controllers/API/workflow.ts`。直接复用 `src/utils/workflowManagement.ts` 原路径函数；原读取 API `flow.ts` 不变。
  - **内容**：拆分 canCreateWorkflow 和 canCreateApp；管理页新建及 Workflow 复制走专属能力，复制保留源编辑权。兼容旧新建目标仅打开 Workflow 表单，保留 Idempotency-Key 和来源标记，不开放通用模板／其他复制。
  - **覆盖 AC**：AC-03, AC-04, AC-07, AC-13。
  - _Requirements: REQ-03, REQ-04, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-07, AC-13_
  - _Verification: V-03；按上述批次记录实际结果_
  - _Depends: T007, T010, T011_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

### 批次 C：原领域自动开通与撤销保护

- [x] **T013**：测试：租户与锚点开通
  - **文件**：`src/backend/test/tenant/test_kunlian_external_provision.py`、`src/backend/test/department/test_external_tenant_anchor.py`。
  - **内容**：覆盖两个有效租户、重名／更名、原人工映射、来源冲突、结构创建回执丢失、事务回滚和旧操作被栅栏拒绝；无管理员任命、无默认 Root 共享。
  - **覆盖 AC**：AC-01, AC-02, AC-10, AC-11, AC-13。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-10, AC-11, AC-13_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T014**：实现：部门锚点事务适配
  - **文件**：`src/backend/bisheng/department/application/external_tenant_anchor.py`、`src/backend/bisheng/department/domain/repositories/external_tenant_anchor.py`。
  - **内容**：提供经验证 Root 父节点下的新本地挂载锚点端口，参与租户专用结构 UoW；不移动旧部门或假造昆联组织树，不分配组织管理员。
  - **覆盖 AC**：AC-01, AC-10, AC-11。
  - _Requirements: REQ-01, REQ-06_
  - _Acceptance: AC-01, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T013_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T015**：实现：租户来源仓储与回执
  - **文件**：`src/backend/bisheng/tenant/domain/repositories/external_provision.py`。
  - **内容**：实现唯一来源预留、实际结构写入与回执同事务、当前操作核验及阻断 CAS；对手工映射只记录经过核验的已有目标，禁止按名称认领与重绑。
  - **覆盖 AC**：AC-01, AC-02, AC-09, AC-10, AC-11。
  - _Requirements: REQ-01, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T014_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T016**：实现：租户领域开通协议
  - **文件**：`src/backend/bisheng/tenant/domain/services/external_provision.py`、`src/backend/bisheng/tenant/application/external_provision.py`。
  - **内容**：暴露 reserve／ensure／read_receipt 与来源政策；协调锚点及必要权限 application 的原投影账本，保持无默认分发。失败保留结构并查回，不伪造管理员主体。
  - **覆盖 AC**：AC-01, AC-02, AC-09, AC-10, AC-11, AC-13。
  - _Requirements: REQ-01, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-09, AC-10, AC-11, AC-13_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T015_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T017**：测试：基础角色模板
  - **文件**：`src/backend/test/role/test_external_basic_role.py`。
  - **内容**：验证固定 admin/build/create_workflow、不含 create_app 和资源 Grant；暂停、删除墓碑、显式恢复、并发模板修改和角色名碰撞均不能扩权或自动认领。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10, AC-11。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10, AC-11_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003, T004_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T018**：实现：角色模板仓储与服务
  - **文件**：`src/backend/bisheng/role/domain/repositories/external_basic_role.py`、`src/backend/bisheng/role/domain/services/external_basic_role.py`。
  - **内容**：实现模板操作栅栏、创建回执及事务锁；停用实际清除模板菜单，删除保留来源墓碑；显式恢复只恢复新固定三键。保护原角色租户与其他角色。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10, AC-11。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T017_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T019**：实现：角色 application 协议
  - **文件**：`src/backend/bisheng/role/application/external_basic_role.py`。
  - **内容**：导出模板 ensure/read、政策与受限事务锁适配；返回值对象，不让用户领域直接查询角色来源表或调用权限基础设施。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T018_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T020**：测试：用户基础资格与撤销
  - **文件**：`src/backend/test/user/test_external_basic_access.py`、`src/backend/test/user/test_external_basic_access_races.py`。
  - **内容**：覆盖 UserRole 与来源回执原子提交、晚到操作、撤销／提交竞争、保留人工角色、缺失关联不自动补回、来源与本地用户不匹配。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003, T019_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T021**：实现：用户资格仓储与服务
  - **文件**：`src/backend/bisheng/user/domain/repositories/external_basic_access.py`、`src/backend/bisheng/user/domain/services/external_basic_access.py`。
  - **内容**：按设计锁顺序核验模板和用户 Owner 原回执，持久操作与实际角色变更同事务；只追加指定自动关系，撤销提高栅栏并留墓碑，显式设置目标租户。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T020_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T022**：实现：用户资格 application 协议
  - **文件**：`src/backend/bisheng/user/application/external_basic_access.py`。
  - **内容**：导出 ensure/set/read 及有效资格检查，合并独立人工菜单的现有结果；不以来源标识冒充管理员，不回传令牌，不接管用户资料投影。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T021_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T023**：测试：受管角色全部写入口
  - **文件**：`src/backend/test/user/test_external_basic_access_mutations.py`、`src/backend/test/role/test_external_basic_role_mutations.py`。
  - **内容**：覆盖 user_addrole、角色服务及旧兼容修改／删除路径；先提交撤销和标记再重试自动任务，确认不复活；非受管人工角色保持原值和授权检查。
  - **覆盖 AC**：AC-04, AC-09, AC-13。
  - _Requirements: REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-04, AC-09, AC-13_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T019, T022_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T024**：实现：受管写入口收口
  - **文件**：`src/backend/bisheng/user/api/user.py`、`src/backend/bisheng/role/domain/services/role_service.py`。
  - **内容**：受管分支交给原领域 application 的同事务变更；旧兼容角色写入同样经过模板保护。保留原操作者范围检查，禁止只在删除之后异步补标记。
  - **覆盖 AC**：AC-04, AC-09, AC-13。
  - _Requirements: REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-04, AC-09, AC-13_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T023_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

### 批次 D：目录、SSO 与 Worker 衔接

- [x] **T025**：测试：目录到自动开通编排
  - **文件**：`src/backend/test/sso/test_kunlian_tenant_onboarding.py`、`src/backend/test/sso/test_kunlian_onboarding_directory.py`。
  - **内容**：覆盖完整发布后开通、失败分页不创建、当前批次补绑定、过期回执拒绝、已成功用户仍补资格、一个租户失败不阻塞其他就绪租户。
  - **覆盖 AC**：AC-01, AC-02, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T016, T022_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T026**：实现：开通编排与成员补绑定
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/kunlian_onboarding.py`、`src/backend/bisheng/sso_sync/domain/repositories/kunlian.py`、`src/backend/bisheng/sso_sync/application/runtime.py`。
  - **内容**：按设计从当前有效完整批次协调 Owner、映射及成员；提取原成员协调，增加独立基础资格扫描；基础资格状态与用户资料投影分开。Runtime 只先装配新编排。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-03, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T025, T024_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T027**：测试：双端范围与已有会话
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_scope.py`、`src/backend/test/sso/test_kunlian_onboarding_login.py`、`src/backend/test/sso/test_kunlian_onboarding_admission.py`。
  - **内容**：验证 A/WA、B/WB 允许而 A/WB 拒绝，缺开通结果触发受控恢复并重登；内省往返中停用／撤销，HTTP 和 WebSocket 新动作拒绝；原 fixed 模式兼容。
  - **覆盖 AC**：AC-05, AC-06, AC-07, AC-08, AC-09, AC-13。
  - _Requirements: REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T001, T026_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T028**：实现：后端令牌、登录与会话准入
  - **文件**：`src/backend/bisheng/sso_sync/domain/clients/kunlian.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_login.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_session.py`。
  - **内容**：全部固定范围检查改为配置组合 helper；增加来源政策与资格核验，内省后重读角色／模板及阻断，保留原身份、签名、会话、重放和退出规则。
  - **覆盖 AC**：AC-05, AC-06, AC-07, AC-08, AC-09, AC-13。
  - _Requirements: REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T027_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T029**：测试：网关组合模式
  - **文件**：`../bisheng-gateway/src/test/java/com/dataelem/gateway/config/KunlianSsoPropertiesTest.java`、`../bisheng-gateway/src/test/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClientTest.java`、`src/backend/test/sso/test_kunlian_scope_policy.py`。
  - **内容**：与后端共享同组组合输入及预期，覆盖空／错误模式和旧 fixed 配置；保留签名、audience、nonce、时间和一次性事务验证，不使用真实令牌。
  - **覆盖 AC**：AC-05, AC-06, AC-13。
  - _Requirements: REQ-04, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T005_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T030**：实现：网关令牌范围
  - **文件**：`../bisheng-gateway/src/main/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClient.java`、`../bisheng-gateway/src/main/java/com/dataelem/gateway/config/KunlianSsoProperties.java`、`src/backend/bisheng/core/config/sso_sync.py`。
  - **内容**：使用组合 helper 统一身份范围检查；双端令牌与会话接入均完成后，同步解除两端 SCOPE_RUNTIME_NOT_READY，并按模式条件化旧固定字段必填。不开通真实范围；不改 HMAC 交接字段，不给网关目录 Key，不在真实失败后回落 Mock。
  - **覆盖 AC**：AC-05, AC-06, AC-13。
  - _Requirements: REQ-04, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T028, T029_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T031**：测试：恢复调度与漏投
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_worker.py`。
  - **内容**：覆盖先持久后投递、阶段独立游标、已扫描键之前新任务、Beat 重扫、Worker 退出及旧失败回执；验证 tenant_id=1 的控制面头必需。
  - **覆盖 AC**：AC-01, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-01, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T026_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [x] **T032**：实现：Worker 恢复衔接
  - **文件**：`src/backend/bisheng/worker/sso_sync/tasks.py`、`src/backend/bisheng/sso_sync/application/runtime.py`。
  - **内容**：复用恢复入口，按有界阶段扫描并续投；Celery headers tenant_id=1 经 ContextVar 进入 Root 控制面，Owner 按已验证映射切目标租户；不新增调度服务。Runtime 在既有编排装配上追加 Worker 协议。
  - **覆盖 AC**：AC-01, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-01, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T031, T028_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

### 批次 E：控制面、并发与 Mock 验收

- [ ] **T033**：测试：控制面与诊断游标
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_management.py`、`src/backend/test/sso/test_kunlian_onboarding_cursor.py`。
  - **内容**：覆盖即时管理员资格、四个增量接口、过滤游标签名／过期／混用、旧修订冲突、来源／模板／成员分别恢复以及敏感字段不返回。
  - **覆盖 AC**：AC-06, AC-09, AC-11, AC-12。
  - _Requirements: REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-06, AC-09, AC-11, AC-12_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T032_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T034**：实现：游标与状态／政策协调
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/kunlian_onboarding_cursor.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_onboarding.py`。
  - **内容**：实现域分离签名游标、阶段诊断和 Owner 政策命令；只用现有秘密引用。统计不覆盖原 directory_status，恢复返回处理中而非冒称已完成。
  - **覆盖 AC**：AC-09, AC-11, AC-12。
  - _Requirements: REQ-05, REQ-06_
  - _Acceptance: AC-09, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T033_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T035**：实现：管理 API 入口
  - **文件**：`src/backend/bisheng/sso_sync/api/endpoints/kunlian.py`、`src/backend/bisheng/sso_sync/application/kunlian.py`。
  - **内容**：扩展 status，提供 GET onboarding 及 tenant/basic-role/member 三个 PUT；延续当前全局管理员即时复核、受限根上下文、CAS 与 no-store，不开放给外部身份参数。
  - **覆盖 AC**：AC-06, AC-09, AC-11, AC-12。
  - _Requirements: REQ-04, REQ-05, REQ-06_
  - _Acceptance: AC-06, AC-09, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T034_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T036**：测试：跨实例与并发补偿集成
  - **文件**：`src/backend/test/integration/test_kunlian_onboarding_consistency.py`。
  - **内容**：用隔离数据库及两个独立服务实例构造租户创建已提交但 F118 回滚、通知丢失、模板暂停／成员撤销与旧任务竞争；确认对象不重复，人工授权不丢失。临时数据库不作为真实行锁通过证据。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-08, AC-09, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-03, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T024, T030, T035_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T037**：测试：自动开通 API 最小闭环
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_e2e.py`。
  - **内容**：复用现有 SSO/管理页 API 隔离夹具，贯通双租户目录、投影、专属创建、查询、越权拒绝、撤销后重试及旧会话拒绝。以业务结果断言，不为每条 AC 另建同构测试。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13_
  - _Verification: V-01, V-02, V-04；按上述批次记录实际结果_
  - _Depends: T012, T036_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T038**：隔离 Mock 浏览器验收
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`、`features/v3.0.0/130-kunlian-tenant-onboarding/evidence-mock/`。
  - **内容**：复用原本地隔离 SSO/浏览器工具，执行设计 §7.2：双租户登录回跳、新建及复制源权限、只读拒绝、其他应用按钮与直接接口拒绝、缺目录后重新登录。记录页面与请求回执，不连接真实昆联或服务器。
  - **覆盖 AC**：AC-03, AC-04, AC-05, AC-06, AC-07, AC-09, AC-13。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07, AC-09, AC-13_
  - _Verification: V-03；按上述批次记录实际结果_
  - _Depends: T037_
  - _Boundary: 仅隔离 Mock 浏览器；不连接真实昆联或服务器_

### 批次 F：交付记录与真实环境待办

- [ ] **T039**：同步既有身份文档
  - **文件**：`features/v3.0.0/118-kunlian-sso-user-sync/spec.md`、`features/v3.0.0/118-kunlian-sso-user-sync/design.md`、`features/v3.0.0/118-kunlian-sso-user-sync/tasks.md`。
  - **内容**：限定补充 F130 启用范围的自动基础资格与多租户模式；其他旧合同保留。历史完成记录不重写成多租户已通过，不修改旧 AC 含义而不注明增量覆盖。
  - **覆盖 AC**：AC-13, AC-14。
  - _Requirements: REQ-03, REQ-07_
  - _Acceptance: AC-13, AC-14_
  - _Verification: V-05；按上述批次记录实际结果_
  - _Depends: T038_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T040**：更新版本与交付规划
  - **文件**：`features/v3.0.0/release-contract.md`、`docs/architecture/proposals/昆联多租户接入与Workflow资产调用改造规划.md`。
  - **内容**：按实际实现登记三个 Owner 状态对象与专属菜单，记录原 F056 清单增量；不宣称真实多租户登录已交付，不改 F048、反向调用及跨租户资产合同。
  - **覆盖 AC**：AC-13, AC-14。
  - _Requirements: REQ-07_
  - _Acceptance: AC-13, AC-14_
  - _Verification: V-05；按上述批次记录实际结果_
  - _Depends: T039_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T041**：模块验收、审查与验证落档
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`、`features/v3.0.0/130-kunlian-tenant-onboarding/tasks.md`。
  - **内容**：复用本批有效定向证据，执行一次受影响模块回归、lint/类型及架构检查，并按 sdd-code-review 做特性级审查；修复后只重跑失效范围。落档命令、退出码、代码状态、未运行项和最终任务状态，不提交推送或部署。
  - **覆盖 AC**：AC-13, AC-14。
  - _Requirements: REQ-07_
  - _Acceptance: AC-13, AC-14_
  - _Verification: V-01, V-02, V-03, V-04, V-05；按上述批次记录实际结果_
  - _Depends: T040_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T042**：真实环境联合验收（待执行）
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`。
  - **内容**：仅在双方客户端范围、两租户测试身份、真实 MySQL/DM8/OpenFGA 及另行环境操作授权就绪后执行。覆盖多租户 SSO、实际菜单／资源权限、真实行锁、补偿及停用；缺条件保持 NOT_RUN，不以 Mock 勾选。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14_
  - _Verification: V-01, V-02, V-03, V-04；按上述批次记录实际结果_
  - _Depends: T041_
  - _Boundary: 真实验证待条件与单独授权；不部署_

## 全租户自动 SSO 增量任务（REQ-09）

规格 §9、设计 D-06／§9 已于 2026-11-13 获用户确认。本增量从 T046 连续编号，不重排、重做或勾选旧任务；本轮状态及证据见 E-029 起；T060–T062 已取消，不计为完成。

### 2026-11-13 执行方式调整（用户要求真实联调优先）

- 不搭建独立 Mock 认证、目录或浏览器环境。T060–T062 取消执行，保留编号和原描述供追溯，不计为已完成；真实浏览器验证由 T067 承接。
- T054／T056 复用现有登录和会话测试，不新建整套全租户 Mock 夹具；A／B 实际用户映射由 T067 验证。T058 的新增／停用外部测试数据场景待双方授权，暂不阻塞当前已同步用户的真实登录验证。
- T046–T059 保留与改动直接相关的配置、签名及准入拒绝回归，它们是发布前检查，不代替真实验收。T063 不再依赖 T062 或 T058 的真实新增外部数据；当前已同步成员的登录可先验证，T058 不冒记完成。
- 直接对接 104 与现有昆联测试服务；先检查客户端范围、受控测试身份，再准备已验证代码、备份和回退。未确认的外部范围不通过修改本地配置绕过。
- 允许准备真实联调及候选发布；实际扩大服务器登录范围须有客户端已开放的依据。真实多租户未通过前保持待执行。

### 本增量的范围与验证节奏

- 新模式统一为 `directory_active_tenants`。配置／声明前置检查通过不是最终登录授权；后端当前目录、有效成员、冻结映射、本地资格及在线验证全部保持。

- 本地开发不依赖尚未实施的旧控制面 T033–T038；通过现有内部应用及受控测试夹具验证，不提前开发新管理页面。各任务最多列出两个直接修改文件；未标“新增”的文件已核对存在。

- 基础设施配置合同先做，再接令牌和业务门禁；因涉及认证，配对测试先于实现。测试任务只写测试，不混入生产实现。已被原逻辑满足的门禁直接复用并引用行为证据，不制造无效 diff；出现计划外缺口先更新设计／任务。

- 单元／SQL 集成使用无真实凭据配置，并在 pytest／应用导入前建立进程级 TCP 阻断，禁止读日常开发配置后才打桩；浏览器 Mock 只在显式 loopback 夹具和隔离临时服务中运行，禁止借连 104／116，不安装依赖、不改全局运行配置。缺环境如实标 NOT_RUN。

- G1、G2、G3 分别批次验证，G4 完成一次相关回归和增量审查；同一代码状态的成功证据复用。配置、令牌、最终目录、浏览器清旧身份是不同风险边界，避免同一行为跨层重复生成用例。

- T064–T067 不阻塞前 18 项的本地 Mock 开发；T064 的正式条件与 T066／T067 的真实操作必须另行满足。计划内不新增登录接口、数据库表、凭据主体、用户体系或逐租户 Workspace 名单。

- 默认不部署、不提交或推送。T066 必须取得针对实际候选与数据／权限影响的部署授权。T067 只完成本增量的真实子集，不自动勾选原 F130 联合验收 T042。本次用户已批准候选发布并执行，见 E-031／E-032。

### 批次 G1：三种登录模式与双端配置合同（T046–T049）

- [x] **T046**：基础设施：后端三模式配置测试
  - **文件**：`src/backend/test/sso/test_kunlian_scope_policy.py`。

  - **内容**：在原配置夹具中增加 directory_active_tenants：无需静态租户／Workspace 名单即可通过配置前置校验；非法声明仍拒绝。参数化保留 fixed／组合模式的精确匹配、空值和通配符拒绝。先观察预期失败，不把本层通过当作目录授权通过。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；先运行此文件；作为 T047 的红灯与绿灯依据。_
  - _Depends: T001, T030_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T047**：基础设施：后端模式声明与纯配置策略
  - **文件**：`src/backend/bisheng/core/config/sso_sync.py`、`src/backend/bisheng/core/config/kunlian_scope.py`。

  - **内容**：增加第三模式和就绪校验，显式区分静态组合解析与声明前置校验；新模式不读取旧名单作为限制，不靠空配置启用全租户。core 不查目录、不调用领域、不签发身份；默认仍为 fixed，原两模式行为保持。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；T046 通过；核对 helper 仅为前置判断，未触碰运行配置。_
  - _Depends: T046_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T048**：基础设施：网关配置与范围合同测试
  - **文件**：`../bisheng-gateway/src/test/java/com/dataelem/gateway/config/KunlianSsoPropertiesTest.java`、`../bisheng-gateway/src/test/java/com/dataelem/gateway/sso/kunlian/KunlianScopePolicyTest.java`。

  - **内容**：按后端同一组模式／标识样例测试真实配置绑定及就绪检查。新模式不要求逐租户名单；未知模式、错误 Origin、缺少协议配置仍拒绝。旧 fixed／组合模式及交叉组合拒绝保持；先观察不支持第三模式的预期失败。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；两个原网关测试文件的红灯／绿灯证据，不运行服务器。_
  - _Depends: T005_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T049**：基础设施：网关模式与范围前置校验
  - **文件**：`../bisheng-gateway/src/main/java/com/dataelem/gateway/config/KunlianSsoProperties.java`、`../bisheng-gateway/src/main/java/com/dataelem/gateway/sso/kunlian/KunlianScopePolicy.java`。

  - **内容**：声明同名第三模式并与后端样例一致。只校验配置及合法租户／Workspace 声明，不复制目录、不添加目录 Key，不把合法声明当作可登录用户。保留旧模式和默认值，不能通过删掉所有范围检查实现全开放。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；T048 通过；G1 检查两端共享样例结果一致。_
  - _Depends: T048_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

### 批次 G2：双端令牌链路（T050–T053）

- [x] **T050**：后端 Domain：OIDC 初始化与令牌合同测试
  - **文件**：`src/backend/test/sso/test_kunlian_idp_client.py`。

  - **内容**：先验证第三模式可以构造真实客户端，避免只修改回调却仍被初始化中的静态组合解析拒绝。用已有 MockTransport／测试签名验证任意合规 A／B 声明，以及签名、iss、aud／azp、nonce、时效、缺失字段和内省 tuple 不一致拒绝；不接真实凭据或外网。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；原 OIDC 测试文件红灯／绿灯；外部 HTTP 为 Mock。_
  - _Depends: T047_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T051**：后端 Domain：OIDC 各入口统一使用新策略
  - **文件**：`src/backend/bisheng/sso_sync/domain/clients/kunlian.py`。

  - **内容**：同时处理构造器、ID Token 及 introspect 的范围前置检查；保留 client_id、iss、sub、tenant_id、workspace_id、sid、active 和时效的精确在线匹配，禁止补默认 Workspace 或用目录内容代替签名。复用现有超时、流式预算与错误边界。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；T050 通过；客户端合同不新增端点或重试旁路。_
  - _Depends: T050_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T052**：后端 Domain／网关：真实签名令牌回归测试
  - **文件**：`../bisheng-gateway/src/test/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClientTest.java`。

  - **内容**：在现有网关测试内使用测试 RSA/JWKS、事务 nonce 和 Mock 令牌响应验证 A／B 可进入原身份交接；第三模式仍拒绝错误签名、发行方、接收方、nonce、缺字段、非法标识及过期令牌。原模式拒绝其他租户保持。测试只验证网关职责，不模拟后端已经授权；已有实现已满足的部分复用通过证据，不强造红灯。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；先运行网关 OIDC 合同；有缺口先观察预期失败，已满足部分作为 T053 复用依据。_
  - _Depends: T049_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T053**：后端 Domain／网关：OIDC 校验接入第三模式
  - **文件**：`../bisheng-gateway/src/main/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClient.java`。

  - **内容**：令牌范围检查复用 T049；保留 RSA、aud／azp、nonce、时效等原校验和 KunlianIdentityClient 内部交接。只有后端返回成功本地会话后原回调才写 Cookie，不在网关独立签发或回退到其他登录身份。若原 OIDC 已由统一 helper 完成接入，保留原代码并以 T052 证据验收，不制造无效 diff。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；T052 通过；G2 合并双端 OIDC 相关测试一次验证。_
  - _Depends: T052_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

### 批次 G3：当前目录、最终登录及已有会话（T054–T058）

- [x] **T054**：后端 Domain：全租户最终登录准入测试
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_login.py`（复用）。

  - **内容**：复用现有登录／目录／Owner 隔离夹具，验证同一客户端的当前有效身份经真实登录应用路径得到原映射的本地用户和租户（双租户浏览器由 T067 验证）；声明结构合法但目录未知、停用、local_override、错误发行方／subject 绑定、未物化映射、无当前投影或无基础资格时不发本地会话。开通未就绪只登记补同步并拒绝本次授权，完成后必须新登录。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20。

  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-06；隔离 SQL／签名交接主合同；缺口必须先有可观察失败，不以源码顺序断言代替。_
  - _Depends: T051, T053_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T055**：后端 Domain：接入当前目录与资格最终准入
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/kunlian_login.py`。

  - **内容**：明确新模式的范围检查仅为前置条件，始终通过原 _login_qualification、当前目录／绑定／Owner 及登录入口能力后才 issue_or_replay_handoff 和签发本地会话。保持原连接、策略、修订和原子重放判断。原链路已覆盖的部分复用并提供 T054 证据，不为任务强制造无效改动；不另建全租户允许缓存。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20。

  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-06；T054 通过；未知有效格式租户必须在后端最终拒绝。_
  - _Depends: T054_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T056**：后端 Domain：已有会话与策略变化测试
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_admission.py`（复用）。

  - **内容**：复用会话仓储及在线内省夹具，对 HTTP／WebSocket 参数化验证第三模式仍检查当前成员、映射、资格和实际租户；内省往返期间停用、撤权或提高策略导致 auth_epoch 改变时拒绝。内省 tuple 不一致、目录过期及新模式回退后的旧会话不能继续访问；保留合法人工授权。
  - **覆盖 AC**：AC-19, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-19, AC-20, AC-21_
  - _Verification: V-06；会话应用路径测试，复用现有 SQL policy/epoch 更新，不依赖真实存储。_
  - _Depends: T055_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T057**：后端 Domain：已有会话统一接入第三模式
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/kunlian_session.py`。

  - **内容**：在 _policy 及 admit_kunlian_session 接入新范围前置规则，保留内省前后当前事实重读、token_version、auth_epoch、source_revision、角色／模板及本地实际租户核验。单纯声明合法不能覆盖任何来源拒绝；原行为已满足的逻辑不重写，使用 T056 证明。
  - **覆盖 AC**：AC-19, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-19, AC-20, AC-21_
  - _Verification: V-06；T056 通过；内省期间状态改变的拒绝证据必须保留。_
  - _Depends: T056_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [ ] **T058**：后端 API：新增租户、同步与登录集成验证
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`（真实新增／停用场景待授权测试数据）。

  - **内容**：真实环境使用双方授权的测试数据及正常昆联入口新增未登记 C，复用原目录发布／自动开通／部门成员及基础资格流程；开通前拒绝、完成后重新登录成功，配置全程不改名单。经过原内部登录／用户接口核对实际 user_id／tenant_id，验证 A 对 B 的 Workflow 仍拒绝及停用后拒绝。只调用现有 Worker 业务驱动，不新增任务；有 Celery 调用时保持 headers.tenant_id=1 到 ContextVar，进入目标 Owner 后恢复原上下文。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20。

  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-05, REQ-06, REQ-08, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-06；V-06 集成；不修改生产代码，发现未列入设计的直接缺口先记录并更新计划。_
  - _Depends: T055, T057, T045_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

### 批次 G4：现有回跳回归与模块收口（独立 Mock 环境取消）（T059–T063）

- [x] **T059**：前端 Platform／共享包：回调身份更新回归
  - **文件**：`src/frontend/packages/api-client/src/kunlianWorkflowEntry.test.ts`、`src/frontend/platform/src/controllers/kunlianSession.test.ts`。

  - **内容**：基于原 KunlianBrowserFlow／入口 helper 验证 A 已有本地身份时，从统一 SSO 回调进入 B 后清旧 Bearer／提示并重读 B 当前用户；保留 return_to、安全跳转、失败后手工重试和无自动回调循环。只补测试并复用现有共享实现，不混用 Client 的 Recoil 或新建登录页面。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；现有前端单测；共享实现变化时只补相关 Client 兼容回归，不展开 Client 新功能。_
  - _Depends: T057_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [ ] **T060**（取消，不计完成）：基础设施：隔离 Mock 启动入口安全测试
  - **文件**：`src/backend/test/sso/test_kunlian_all_tenant_harness.py`（新增）。

  - **内容**：对 T061 拟提供的最小测试入口先写防误连与协议夹具合同：默认不启动，不读取日常 config，持久存储只能是本轮临时 SQLite；外部模拟只允许声明的 loopback 服务和隔离临时 Redis。拒绝 104、116、业务库、默认 Redis DB 及任意外网；输出不得有凭据／Token。目录、签名与内省 fixture 对同一账号上下文一致，不能直接构造毕昇登录成功结果。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；只对启动入口安全及协议夹具做离线测试，不将它计作浏览器或真实 E2E。_
  - _Depends: T059_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [ ] **T061**（取消，不计完成）：基础设施：最小全租户隔离 Mock 夹具
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/mock-all-tenant/fixture.py`（新增）、`features/v3.0.0/130-kunlian-tenant-onboarding/mock-all-tenant/README.md`（新增）。

  - **内容**：实现显式启用的测试专用夹具与启动说明：只模拟 IdP/JWKS/内省／目录等外部边界，提供有效 A／B、后增 C 和停用控制；生成测试密钥与受控临时数据，不复制登录、绑定或本地 JWT 授权逻辑。真实网关与后端原应用路径使用候选构建，数据库／权限服务 Mock 边界在清单中注明。复用既有本机工具和依赖；缺少本地隔离 Redis／运行条件时记录待执行，不安装软件或借连 104／116，不改全局配置。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20, AC-21_
  - _Verification: V-06；T060 通过；说明准确启动命令、manifest、loopback 端口、私有产物与停止方式，随后交给 T062 真正走浏览器。_
  - _Depends: T060_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [ ] **T062**（取消，不计完成）：前端 Platform：隔离 Mock 浏览器闭环
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`、`features/v3.0.0/130-kunlian-tenant-onboarding/evidence-all-tenant-mock-browser.json`（新增）。

  - **内容**：在 T061 的隔离服务就绪后，用浏览器操作原入口：A 登录 → 昆联模拟上下文切 B → 再走 SSO → 用户及列表归属 B；验证 B 无权编辑／运行 A 的 Workflow，新 C 开通后可登录，成员停用后旧会话拒绝。捕获实际回调及当前主体证据，不以 fake user/info 或手工写本地 JWT 代替；缺服务时保持 NOT_RUN，不勾选。截图只保留脱敏测试页面，不保存回调 code／Token。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20。

  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-06；V-06 浏览器证据；Mock 外部权限不算真实 OpenFGA 验收，内省并发拒绝复用 T056，不重复跑同一风险。_
  - _Depends: T059, T061_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

- [x] **T063**：后端 Domain／交付：相关回归、审查与进度落档
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/tasks.md`、`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`。

  - **内容**：按代码状态复用本批有效定向证据，集中运行双端 scope／OIDC／登录／会话、同步资格和受影响前端回归一次，补 arch-guard／静态及增量审查。与相同选择的未修改基线比较旧失败，不合并多次计数，不把跳过当通过。记录命令、退出码、源码摘要、已完成任务及环境缺项。新增模式必须始终经后端最终目录资格，不修改旧 T033–T042 的状态掩盖尚未完成事项。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20, AC-21_
  - _Verification: V-06；本地模块阶段收口；不提交／推送或部署，真实验证仍待执行。_
  - _Depends: T054, T056, T059_
  - _Boundary: 本任务只改代码与必要回归，不创建独立 Mock 环境；服务器操作由 T066 承接。_

### 批次 G5：正式条件、部署准备及真实验收（T064–T067）

- [ ] **T064**：基础设施／联调准备：正式登记与候选配置
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/ops/all-tenant-client-registration.md`（新增）、`features/v3.0.0/130-kunlian-tenant-onboarding/ops/all-tenant-scope.example.yaml`（新增）。

  - **内容**：准备两端仅范围键的候选配置，保留原固定配置作回退参考；新模式不填逐租户 Workspace 清单。核对昆联一次性开放现有客户端给全部有效租户，并确认签发／内省实际上下文一致，优先复用 client_id、受控凭据引用、Origin 和原回调。外部条件未交付时只准备模板，任务不得冒记完成或改变服务器；# TODO [F130][EXT-01] 和 EXT-02 仅标记对方登记及授权测试身份，不推迟我方实现。
  - **覆盖 AC**：AC-17, AC-20, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-20, AC-21_
  - _Verification: V-06；待昆联正式登记依据与两个租户测试身份；仅保存受控文件位置／脱敏确认，不发送外部消息。_
  - _Depends: T063_
  - _Boundary: 只在任务所列门禁内推进；外部或环境条件不足标待执行，不自行扩大授权。_

- [x] **T065**：基础设施／联调准备：部署与回退检查预案
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/ops/all-tenant-deploy-plan.md`（新增）；复用受控发布目录中的独立运维脚本检查，不新增通用部署工具。

  - **内容**：只准备受控预案及计划检查：备份双端配置与源码、并发摘要保护、兼容代码先行、策略修订按实时值递增、旧 auth_epoch 会话重登、目录同步／开通复核和失败回退。默认 dry-run；缺客户端确认、环境标识、已验证候选摘要或部署授权时不得执行。回退恢复明确受限模式并用更高修订，不回灌业务库、不删账号／角色／成员关系；不引入 Schema 或新端口。
  - **覆盖 AC**：AC-19, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-19, AC-21_
  - _Verification: V-06；可在等待 T064 时准备；只校验脱敏计划和失败前置，不连接或修改实际服务。_
  - _Depends: T063_
  - _Boundary: 只在任务所列门禁内推进；外部或环境条件不足标待执行，不自行扩大授权。_

- [x] **T066**：基础设施／发布：授权后部署全租户模式
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/deployment-all-tenant-sso.md`（新增）、`features/v3.0.0/130-kunlian-tenant-onboarding/evidence-all-tenant-deployment.json`（新增）。

  - **内容**：仅在候选与回退准备完成、对当前测试身份的真实签发验证通过，并获得具体部署／授权范围变更确认后执行；T064 的其他／未来租户约定未完成时仍保留待确认，不记作全量验收。重读指定 104 环境，备份并验证候选与现场摘要；按预案更新兼容代码及网关／后端新模式、提高策略修订并运行原同步恢复，核验健康和真实权限上下文。保留静态 Nginx、3001 及已登记公网 50055，Origin、凭据、回调不擅改。失败保留证据并按已确认预案处理，不能把仅有 303 当作登录通过。
  - **覆盖 AC**：AC-17, AC-19, AC-21。

  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-19, AC-21_
  - _Verification: V-06；待单独部署授权；本轮不执行，也不因代码任务完成而自动部署。_
  - _Depends: T064, T065_
  - _Boundary: 只在任务所列门禁内推进；外部或环境条件不足标待执行，不自行扩大授权。_

- [ ] **T067**：前端 Platform／联调：真实多租户与切换验收
  - **文件**：`features/v3.0.0/130-kunlian-tenant-onboarding/verification.md`、`features/v3.0.0/130-kunlian-tenant-onboarding/test-cases.md`。

  - **内容**：使用 Workflow、模型两个真实授权账号，经统一公网 SSO 入口验证登录与各自本地 user_id／tenant_id、同一浏览器 A → B 无旧数据、原试点行为保持及跨租户对象拒绝。新增／停用／恢复使用双方授权的测试数据，范围或环境不足逐项标待执行。提高策略后的旧会话重新认证和回退检查按预案核对；不擅自操作已有业务账号／资产。仅更新实际执行的 QA 子项，不据此关闭旧 T042 中未验的 MySQL 并发／DM8／其他控制面。
  - **覆盖 AC**：AC-17, AC-18, AC-19, AC-20, AC-21。

  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20, AC-21_
  - _Verification: V-06；真实联合验收待执行；缺昆联条件不得以 Mock 结果替代。_
  - _Depends: T066_
  - _Boundary: 只在任务所列门禁内推进；外部或环境条件不足标待执行，不自行扩大授权。_

### 本增量验收与依赖总览

| 批次 | 范围 | 完成依据 | 当前状态 |
| --- | --- | --- | --- |
| G1 | T046–T049 | 双端范围合同 | PASS：E-029 |
| G2 | T050–T053 | 双端签名与内省 | PASS：E-029 |
| G3 | T054–T058 | 最终准入与会话 | PARTIAL；T054–T057 通过，T058 真实新增场景待执行 |
| G4 | T059、T063；T060–T062 取消 | 原页面回调与相关回归 | PASS：E-029；浏览器改在 T067 真实验收 |
| G5 | T064–T067 | 正式登记、门禁、部署与真实多租户 | PARTIAL：T065、T066 完成；T064 全量约定及 T067 剩余场景待执行 |

| Acceptance | 主要本地证据任务 | 真实验收 |
| --- | --- | --- |
| AC-17 | T046、T048、T050、T052、T054、T058、T059、T062 | T067 |
| AC-18 | T054、T058、T062 | T067 |
| AC-19 | T054、T056、T058、T062 | T066、T067 |
| AC-20 | T046、T048、T050、T052、T054、T056、T058、T059、T062 | T067 |
| AC-21 | T046、T048、T050、T052、T056、T059、T060、T063、T065 | T064、T066、T067 |

实际：E-029 完成双端与最终准入回归，E-030 验证真实模型令牌，E-031 完成 104 备份；用户已批准发布。新增／停用及全量客户端约定未验收，不能标全特性完成。

本次任务审查：`LGTM`（仅新增 T046–T067）。编号、依赖、每项至多两个文件、七组测试先行配对、AC-17 至 AC-21 追溯及真实条件门禁已核对；仅执行文档 V0 检查。此为规划时结论；实施后状态以 E-029 起为准，旧任务状态保持，取消项不计完成。


## 验收覆盖与进度

| 阶段 | 任务范围 | 状态 |
| --- | --- | --- |
| 基础设施 | T001–T005 | 已部署；源码已支持组合模式，实际配置仍 fixed |
| 专属创建 | T006–T012 | 本地 API／组件与相关回归通过；完整浏览器另由 T038 验证 |
| 领域开通 | T013–T024 | 已部署；真实 10 个有效租户、15 个有效成员及基础资格通过 |
| SSO／恢复 | T025–T032 | 已部署；真实目录及 fixed 试点登录／刷新／退出通过；故障矩阵待验 |
| 控制面与 Mock | T033–T038 | 未开始 |
| 文档与审查 | T039–T041 | 未开始 |
| 真实环境 | T042 | `PARTIAL`；本次专项联调通过，不勾选完整联合验收 |

## 实际偏差记录

### 成员列表缺失修复（REQ-08）

- [x] **T043**：先复现组织成员缺失，再复用部门成员与权限投影入口补齐；校验目标租户、根挂载、来源和主部门，保留人工关系。_Requirements: REQ-08_；_Acceptance: AC-15、AC-16_；_Verification: E-025、E-026；新增 11 项 SQL 集成与拒绝／失败恢复用例通过_。
- [x] **T044**：覆盖已投影成功成员的常规恢复和重复执行，执行相关隔离回归、架构检查并更新验证记录。_Requirements: REQ-06、REQ-08_；_Acceptance: AC-15、AC-16_；_Verification: E-026、E-027；403 项通过，4 项与未修改基线一致的旧夹具失败，无新增失败；静态检查无新增违规_。
- [x] **T045**：104 备份、部署补丁、通过原恢复流程补齐，并核对成员页与 SSO。_Requirements: REQ-08_；_Acceptance: AC-15、AC-16_；_Verification: E-028；15 名用户的成员关系和实际权限检查通过，重复两轮恢复无新增，真实成员页与试点 SSO 回跳通过；并发故障和 DM8 仍待执行_。

- 规划修订：原通用 create_app 改为专属 create_workflow → design.md D-03／§4.4；T001–T012 已本地实施。
- 规划纠正：整表创建沿用当前模型发现／升级前补表，不重复添加空 Alembic 修订 → design.md §7.4。
- 路径核对：创建 API 实际位于 workflow.ts；原路由和管理路径 helper 已满足要求，直接复用而不制造无效改动。
- 集成夹具：模型过滤事件会影响同进程旧测试；新模型过滤验证改用独立解释器，旧登记夹具显式进入租户 7 严格上下文，不关闭过滤器。
- 分批保护：新组合配置先声明、暂拒绝启动登录；在既有 T030 内按 T028/T029 依赖解除双端阶段门禁，未新增业务范围或持久对象。
- L1 审查与证据：见 [verification.md](./verification.md) E-006–E-011。其余任务保持未勾选，真实环境保持 NOT_RUN。

### 领域开通批次记录（2026-11-12，T013–T024）

- 当前隔离工作树：`/Users/wenruli/code/project/bisheng/bisheng-kunlian-tenant-onboarding`，分支 `feat/v3.0.0/118-kunlian-integration`，基线 `2ed971aed7`。主工作区已在其他发版分支且有未提交修改，本轮没有覆盖或切换它。
- T013–T024 采用现有三张状态模型，新增部门／租户／角色／用户领域适配及 application；不增加第四张表，不迁移历史数据，不配置真实环境。
- 配套测试落点：`src/backend/test/fixtures/kunlian_onboarding.py` 为这些任务共用的临时 SQLite／网络阻断夹具；`test/role/test_role_service.py` 给原普通角色桩补齐新 application 边界，受管路径另用真实 SQL 验证；`test/role/test_role_api.py` 只修正源码断言对引号形式的依赖。
- 按当前 QA 模板补充 [test-cases.md](./test-cases.md)，九条人工参考用例均保留“待执行”，不以开发脚本结果冒充人工验收。
- 当前有效证据见 verification.md E-013–E-017 与 [本轮源码校验记录](./evidence-local-20261112-c.json)。早期测试误用了另一工作区指向 116 的配置，影响尚未确认，详见 E-013；纠正后全部使用隔离配置和 TCP 阻断。用户指定的真实环境为 104，本轮不部署。
- 截至该批次，T025–T042 尚未完成；后续实施进度见下节，原领域串联证据不冒充全链路验收。

### 目录、登录与恢复批次（2026-11-12，T025–T032）

- 本批沿用已确认计划与上一批隔离工作树；网关在 `../bisheng-gateway` 的 `feat/kunlian-integration` 上实现，原基线 `bab8dd72`，没有暂存、提交、推送或部署。
- T026 复用 `_reconcile_members` 支持当前已发布批次补绑定；来源快照带批次、政策、映射修订，旧回执不能写入新目录。三阶段独立分页，同步已成功的用户仍单独补基础资格；无新增表、运行配置或默认开关变化。
- 必要配套落点：tenant application／repository 追加只读来源状态值对象；原 user application／repository 追加当前已应用投影回执读取；`kunlian_projection.py` 增加可选当前政策校验，沿用原连接锁。它们属于已确认领域端口的最小衔接，不变更原用户资料投影和固定模式合同。
- T028／T030 同步接入后端客户端初始化、RS256、内省、登录和会话，以及网关令牌；移除源码中的阶段门禁，按模式校验必填字段。真实配置仍未启用新模式；不得只复制 Mock 的 A／WA、B／WB 配置上线。
- 配套测试修改 `test/sso/test_kunlian_admission.py` 的资格读取次数为网络前后各一次；`test_kunlian_scope_policy.py` 和网关 `KunlianScopePolicyTest.java` 将旧临时门禁断言改为已接入语义。
- 当前证据见 verification.md E-018–E-022 及 [本批源码校验记录](./evidence-local-20261112-d.json)。后端相关回归 378 项通过，后续仅测试增强的三个文件 12 项通过；网关 77 项通过。不同命令不相加为一次全量执行。
- T033–T042 保持未勾选：控制面、完整 Mock 浏览器、真实数据库竞争和联合验收等仍需后续完成。104 未更新；真实租户／Workspace 范围、账号和 OpenFGA 验证仍待执行。

### 后续授权的 104 部署与专项联调（2026-11-12）

- 用户明确要求部署 104 并调通用户同步／SSO。本次授权覆盖已实现运行代码、后端自动开通启用及真实验证；没有开启未登记的多租户 OIDC 范围。
- 发布 `20261112-f130-sso`：24 个后端文件及网关 JAR，目录映射不变；仅开启自动开通和策略修订 3。代码未暂存、提交或推送。
- 实测目录 13 租户／18 成员，10 个有效租户及 15 名有效成员完成开通；3 个暂停租户及对应成员未开通，原人工授权保留。试点账号真实登录、刷新、新建表单打开／取消、退出回调与再次登录通过。
- 原本地批次“不部署”描述保留历史含义；当前部署事实与证据见 verification.md E-023／E-024 和 [部署联调记录](./deployment-20261112-sso.md)。
- T033–T041 仍待后续开发／验收；T042 已执行上述真实子集，状态 PARTIAL，完整权限／多租户范围／故障／DM8 等未验，不因此次部署勾选整项。

### 2026-11-13 实施与真实验收检查点

- **已完成**：T046–T057、T059、T063、T065、T066。双端共四个运行源码文件发生修改；登录与会话最终准入复用原实现。E-029 为 163 项后端、79 项网关、81 项前端及构建检查；E-030 为真实模型令牌；E-031 为备份，E-032 为部署及真实登录。
- **取消**：T060–T062，不创建独立 Mock 服务／浏览器夹具，不计完成。原描述仅供追溯；本节和最新执行方式优先于原 Mock 边界。
- **部分／待执行**：T064 已准备范围模板并实测两个租户，其他／未来租户客户端约定仍待昆联确认；T058 新增、停用／恢复测试数据待授权；T067 已完成真实双租户登录、双向切换、刷新、退出与跨租户编辑拒绝，剩余来源变化及回退完整矩阵仍待执行，故保留未勾选。
- 发布后人工检查首轮恢复 10 个租户、15 名成员成功；重复检查与后台新批次相遇，被栅栏拒绝，已停止人工重跑。只读核验确认后台完成收敛，未将竞争拒绝写作恢复全绿。三名未映射成员属于暂停租户，不自动开通。
- 当前源码未暂存、未提交、未推送；旧控制面 T033–T041 与完整联合验收 T042 的状态不因本轮变更而关闭。
