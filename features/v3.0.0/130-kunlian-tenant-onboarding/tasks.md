# 昆联多租户与新用户自动开通任务

- **Feature ID**：`F130`
- **Version**：`v3.0.0`
- **Updated**：2026-11-11
- **关联**：[spec.md](./spec.md) · [design.md](./design.md) · [verification.md](./verification.md)

## 状态

| 步骤 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | 已确认 | 用户确认自动开通与只授予 Workflow 专属创建能力。 |
| design.md | 已确认 | 用户已确认 create_workflow、三张领域状态表及完整修订设计。 |
| tasks.md | 已确认 | 用户回复“确认 继续”，按本表分批实施。 |
| 实现 | 进行中 | 12 / 42；T001–T012 已本地验证并经后续授权部署，其余未勾选，真实联合验收另记。 |

## 实施与验收约定

- Mock 优先；设计及任务已确认。本轮完成 T001–T012，不将整个特性标为完成。若源文件已有并发修改，先合并核对，不覆盖用户工作。
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

- [ ] **T013**：测试：租户与锚点开通
  - **文件**：`src/backend/test/tenant/test_kunlian_external_provision.py`、`src/backend/test/department/test_external_tenant_anchor.py`。
  - **内容**：覆盖两个有效租户、重名／更名、原人工映射、来源冲突、结构创建回执丢失、事务回滚和旧操作被栅栏拒绝；无管理员任命、无默认 Root 共享。
  - **覆盖 AC**：AC-01, AC-02, AC-10, AC-11, AC-13。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-10, AC-11, AC-13_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T014**：实现：部门锚点事务适配
  - **文件**：`src/backend/bisheng/department/application/external_tenant_anchor.py`、`src/backend/bisheng/department/domain/repositories/external_tenant_anchor.py`。
  - **内容**：提供经验证 Root 父节点下的新本地挂载锚点端口，参与租户专用结构 UoW；不移动旧部门或假造昆联组织树，不分配组织管理员。
  - **覆盖 AC**：AC-01, AC-10, AC-11。
  - _Requirements: REQ-01, REQ-06_
  - _Acceptance: AC-01, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T013_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T015**：实现：租户来源仓储与回执
  - **文件**：`src/backend/bisheng/tenant/domain/repositories/external_provision.py`。
  - **内容**：实现唯一来源预留、实际结构写入与回执同事务、当前操作核验及阻断 CAS；对手工映射只记录经过核验的已有目标，禁止按名称认领与重绑。
  - **覆盖 AC**：AC-01, AC-02, AC-09, AC-10, AC-11。
  - _Requirements: REQ-01, REQ-05, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T014_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T016**：实现：租户领域开通协议
  - **文件**：`src/backend/bisheng/tenant/domain/services/external_provision.py`、`src/backend/bisheng/tenant/application/external_provision.py`。
  - **内容**：暴露 reserve／ensure／read_receipt 与来源政策；协调锚点及必要权限 application 的原投影账本，保持无默认分发。失败保留结构并查回，不伪造管理员主体。
  - **覆盖 AC**：AC-01, AC-02, AC-09, AC-10, AC-11, AC-13。
  - _Requirements: REQ-01, REQ-05, REQ-06, REQ-07_
  - _Acceptance: AC-01, AC-02, AC-09, AC-10, AC-11, AC-13_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T015_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T017**：测试：基础角色模板
  - **文件**：`src/backend/test/role/test_external_basic_role.py`。
  - **内容**：验证固定 admin/build/create_workflow、不含 create_app 和资源 Grant；暂停、删除墓碑、显式恢复、并发模板修改和角色名碰撞均不能扩权或自动认领。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10, AC-11。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10, AC-11_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003, T004_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T018**：实现：角色模板仓储与服务
  - **文件**：`src/backend/bisheng/role/domain/repositories/external_basic_role.py`、`src/backend/bisheng/role/domain/services/external_basic_role.py`。
  - **内容**：实现模板操作栅栏、创建回执及事务锁；停用实际清除模板菜单，删除保留来源墓碑；显式恢复只恢复新固定三键。保护原角色租户与其他角色。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10, AC-11。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T017_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T019**：实现：角色 application 协议
  - **文件**：`src/backend/bisheng/role/application/external_basic_role.py`。
  - **内容**：导出模板 ensure/read、政策与受限事务锁适配；返回值对象，不让用户领域直接查询角色来源表或调用权限基础设施。
  - **覆盖 AC**：AC-03, AC-04, AC-09, AC-10。
  - _Requirements: REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-04, AC-09, AC-10_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T018_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T020**：测试：用户基础资格与撤销
  - **文件**：`src/backend/test/user/test_external_basic_access.py`、`src/backend/test/user/test_external_basic_access_races.py`。
  - **内容**：覆盖 UserRole 与来源回执原子提交、晚到操作、撤销／提交竞争、保留人工角色、缺失关联不自动补回、来源与本地用户不匹配。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T003, T019_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T021**：实现：用户资格仓储与服务
  - **文件**：`src/backend/bisheng/user/domain/repositories/external_basic_access.py`、`src/backend/bisheng/user/domain/services/external_basic_access.py`。
  - **内容**：按设计锁顺序核验模板和用户 Owner 原回执，持久操作与实际角色变更同事务；只追加指定自动关系，撤销提高栅栏并留墓碑，显式设置目标租户。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T020_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T022**：实现：用户资格 application 协议
  - **文件**：`src/backend/bisheng/user/application/external_basic_access.py`。
  - **内容**：导出 ensure/set/read 及有效资格检查，合并独立人工菜单的现有结果；不以来源标识冒充管理员，不回传令牌，不接管用户资料投影。
  - **覆盖 AC**：AC-02, AC-03, AC-04, AC-08, AC-09, AC-10。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T021_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T023**：测试：受管角色全部写入口
  - **文件**：`src/backend/test/user/test_external_basic_access_mutations.py`、`src/backend/test/role/test_external_basic_role_mutations.py`。
  - **内容**：覆盖 user_addrole、角色服务及旧兼容修改／删除路径；先提交撤销和标记再重试自动任务，确认不复活；非受管人工角色保持原值和授权检查。
  - **覆盖 AC**：AC-04, AC-09, AC-13。
  - _Requirements: REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-04, AC-09, AC-13_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T019, T022_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T024**：实现：受管写入口收口
  - **文件**：`src/backend/bisheng/user/api/user.py`、`src/backend/bisheng/role/domain/services/role_service.py`。
  - **内容**：受管分支交给原领域 application 的同事务变更；旧兼容角色写入同样经过模板保护。保留原操作者范围检查，禁止只在删除之后异步补标记。
  - **覆盖 AC**：AC-04, AC-09, AC-13。
  - _Requirements: REQ-03, REQ-05, REQ-07_
  - _Acceptance: AC-04, AC-09, AC-13_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T023_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

### 批次 D：目录、SSO 与 Worker 衔接

- [ ] **T025**：测试：目录到自动开通编排
  - **文件**：`src/backend/test/sso/test_kunlian_tenant_onboarding.py`、`src/backend/test/sso/test_kunlian_onboarding_directory.py`。
  - **内容**：覆盖完整发布后开通、失败分页不创建、当前批次补绑定、过期回执拒绝、已成功用户仍补资格、一个租户失败不阻塞其他就绪租户。
  - **覆盖 AC**：AC-01, AC-02, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-01, V-02；按上述批次记录实际结果_
  - _Depends: T016, T022_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T026**：实现：开通编排与成员补绑定
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/kunlian_onboarding.py`、`src/backend/bisheng/sso_sync/domain/repositories/kunlian.py`、`src/backend/bisheng/sso_sync/application/runtime.py`。
  - **内容**：按设计从当前有效完整批次协调 Owner、映射及成员；提取原成员协调，增加独立基础资格扫描；基础资格状态与用户资料投影分开。Runtime 只先装配新编排。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06_
  - _Acceptance: AC-01, AC-02, AC-03, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T025, T024_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T027**：测试：双端范围与已有会话
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_scope.py`、`src/backend/test/sso/test_kunlian_onboarding_login.py`、`src/backend/test/sso/test_kunlian_onboarding_admission.py`。
  - **内容**：验证 A/WA、B/WB 允许而 A/WB 拒绝，缺开通结果触发受控恢复并重登；内省往返中停用／撤销，HTTP 和 WebSocket 新动作拒绝；原 fixed 模式兼容。
  - **覆盖 AC**：AC-05, AC-06, AC-07, AC-08, AC-09, AC-13。
  - _Requirements: REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T001, T026_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T028**：实现：后端令牌、登录与会话准入
  - **文件**：`src/backend/bisheng/sso_sync/domain/clients/kunlian.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_login.py`、`src/backend/bisheng/sso_sync/domain/services/kunlian_session.py`。
  - **内容**：全部固定范围检查改为配置组合 helper；增加来源政策与资格核验，内省后重读角色／模板及阻断，保留原身份、签名、会话、重放和退出规则。
  - **覆盖 AC**：AC-05, AC-06, AC-07, AC-08, AC-09, AC-13。
  - _Requirements: REQ-04, REQ-05, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T027_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T029**：测试：网关组合模式
  - **文件**：`../bisheng-gateway/src/test/java/com/dataelem/gateway/config/KunlianSsoPropertiesTest.java`、`../bisheng-gateway/src/test/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClientTest.java`、`src/backend/test/sso/test_kunlian_scope_policy.py`。
  - **内容**：与后端共享同组组合输入及预期，覆盖空／错误模式和旧 fixed 配置；保留签名、audience、nonce、时间和一次性事务验证，不使用真实令牌。
  - **覆盖 AC**：AC-05, AC-06, AC-13。
  - _Requirements: REQ-04, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T005_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T030**：实现：网关令牌范围
  - **文件**：`../bisheng-gateway/src/main/java/com/dataelem/gateway/sso/kunlian/KunlianOidcClient.java`、`../bisheng-gateway/src/main/java/com/dataelem/gateway/config/KunlianSsoProperties.java`、`src/backend/bisheng/core/config/sso_sync.py`。
  - **内容**：使用组合 helper 统一身份范围检查；双端令牌与会话接入均完成后，同步解除两端 SCOPE_RUNTIME_NOT_READY，并按模式条件化旧固定字段必填。不开通真实范围；不改 HMAC 交接字段，不给网关目录 Key，不在真实失败后回落 Mock。
  - **覆盖 AC**：AC-05, AC-06, AC-13。
  - _Requirements: REQ-04, REQ-07_
  - _Acceptance: AC-05, AC-06, AC-13_
  - _Verification: V-04；按上述批次记录实际结果_
  - _Depends: T028, T029_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T031**：测试：恢复调度与漏投
  - **文件**：`src/backend/test/sso/test_kunlian_onboarding_worker.py`。
  - **内容**：覆盖先持久后投递、阶段独立游标、已扫描键之前新任务、Beat 重扫、Worker 退出及旧失败回执；验证 tenant_id=1 的控制面头必需。
  - **覆盖 AC**：AC-01, AC-07, AC-10, AC-11, AC-12。
  - _Requirements: REQ-01, REQ-02, REQ-06_
  - _Acceptance: AC-01, AC-07, AC-10, AC-11, AC-12_
  - _Verification: V-02；按上述批次记录实际结果_
  - _Depends: T026_
  - _Boundary: 只执行本任务列出的本地开发／Mock 范围；不部署_

- [ ] **T032**：实现：Worker 恢复衔接
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

## 验收覆盖与进度

| 阶段 | 任务范围 | 状态 |
| --- | --- | --- |
| 基础设施 | T001–T005 | 本地完成并后续部署；MySQL 三张空表已创建，组合模式保持拒绝启用 |
| 专属创建 | T006–T012 | 本地 API／组件与相关回归通过；完整浏览器另由 T038 验证 |
| 领域开通 | T013–T024 | 未开始 |
| SSO／恢复 | T025–T032 | 未开始 |
| 控制面与 Mock | T033–T038 | 未开始 |
| 文档与审查 | T039–T041 | 未开始 |
| 真实环境 | T042 | `NOT_RUN`，待双方条件及环境操作授权 |

## 实际偏差记录

- 规划修订：原通用 create_app 改为专属 create_workflow → design.md D-03／§4.4；T001–T012 已本地实施。
- 规划纠正：整表创建沿用当前模型发现／升级前补表，不重复添加空 Alembic 修订 → design.md §7.4。
- 路径核对：创建 API 实际位于 workflow.ts；原路由和管理路径 helper 已满足要求，直接复用而不制造无效改动。
- 集成夹具：模型过滤事件会影响同进程旧测试；新模型过滤验证改用独立解释器，旧登记夹具显式进入租户 7 严格上下文，不关闭过滤器。
- 分批保护：新组合配置先声明、暂拒绝启动登录；在既有 T030 内按 T028/T029 依赖解除双端阶段门禁，未新增业务范围或持久对象。
- L1 审查与证据：见 [verification.md](./verification.md) E-006–E-011。其余任务保持未勾选，真实环境保持 NOT_RUN。
