# 昆联租户与用户自动开通：验证记录

更新日期：2026-11-11

## 当前结论

规格、修订设计和 42 项任务规划均已获用户确认。本轮完成 T001–T012 的本地开发与 Mock 验证：配置及三表模型基础、Workflow 专属创建门禁、角色菜单和管理页新建／复制衔接。后端合并回归 142 项通过，随后补充的创建门禁文件 9 项通过；Platform 6 文件 57 项及模板权限 15 项通过；网关相关回归 75 项通过，随后增加配置绑定用例的文件 3 项通过。

自动建立实际租户、自动角色及用户关系、目录／Worker 协调和多租户令牌／会话接入尚未实施。两端组合模式保持 SCOPE_RUNTIME_NOT_READY，不可据此启用多租户登录。本轮不部署、不修改真实数据库、服务器或运行配置，不安装依赖、不提交推送。E-001–E-005 为实施前的历史记录，其“未实施”描述不代表本轮结束状态。

## E-001：规划与规格静态检查

- **Status**：`PASS`
- **Level**：`V0`
- **环境**：本机仓库 `/Users/wenruli/code/project/bisheng/bisheng`，Node.js `v24.14.0`。
- **范围**：中文改造规划、`discovery.md`、`spec.md`。
- **实际方法**：使用 `node --input-type=module` 执行内联检查；通过 `fs.existsSync` 检查 Markdown 本地链接；通过 `git diff --no-index --check -- /dev/null <file>` 检查新增文件空白；提取规格表格，检查 AC 唯一、需求覆盖和验证引用。
- **结果**：3 份文档链接与空白检查通过；7 项需求均有验收覆盖；14 条 AC 唯一且均引用已定义的验证组，无未知需求引用。命令退出码 `0`。
- **检查器修正**：第一次包装器错误地将 `git diff --no-index` 表示“存在差异”的退出码 `1` 视为失败，未报告文件内容问题。修正为同时检查退出码与诊断输出后完成上述核对。没有据此修改源代码或服务器。

新增验证记录本身随后执行同类链接与空白核对，结果见本轮工具回执。

## E-002：规格清单审查

依据项目 `sdd-review` 的 `references/spec-checklist.md`，对照改造规划、需求发现、F118／F128／F129 既有边界、v3.0.0 版本契约与架构约束执行人工静态审查。

```text
LGTM
```

该结论表示规格编写当时的范围、可测性、需求追踪和已识别契约边界一致。其后用户已确认规格；实现、真实数据库和真实登录仍未验收。

## E-003：设计与确认状态静态检查

- **Status**：`PASS`
- **Level**：`V0`
- **范围**：本特性 4 份文档、中文整体规划，以及版本契约的 F130 增量登记。
- **实际方法**：`node --input-type=module` 内联脚本，检查 5 份文档本地链接、`git diff --no-index --check` 的诊断、规格需求／AC 数量和设计追踪表；另执行 `git diff --check` 核对已有跟踪文件的空白。
- **实际结果**：5 份文档链接及空白通过，7 项需求、14 条 AC 保持完整，设计覆盖 `7/7` 项需求，跟踪文件空白检查通过；命令退出码 `0`。
- **边界**：没有运行行为测试。新增三张状态表只是设计内容，没有创建模型或执行迁移；待昆联确认的多租户范围与真实测试身份保持 TODO。

## E-004：设计清单与架构约束审查

按项目 `sdd-review/references/design-checklist.md` 的 24 项清单，对照已确认规格、版本契约和架构约束执行静态审查。本特性 `tasks.md` 尚不存在，未将任务拆分或实施标为完成。

审查中已修正：模板与成员提交需要同一顺序的事务锁；来源墓碑不得被角色级联删除；过期修订不能因布尔目标相同而接受；缺表时必须停止新版上线；来源政策阻断不借用旧冻结映射的启用操作。角色模板显式停用会清除实际菜单授权，不只改诊断状态。

修正后清单结论：

```text
LGTM
```

该结论对应当时的设计版本，不证明行锁、权限或真实身份行为已经通过。用户随后确认将通用创建能力收窄为 Workflow 专属能力；旧设计的这一选择已被修订，本轮结果见 E-005，不继续以旧结论证明新行为。

## E-005：工作流专属创建修订与任务草案检查

- **Status**：`PASS`，仅 V0 文档静态检查。
- **变更依据**：用户在说明 `create_app` 也允许助手创建后确认“好的 请继续”。按此收窄 REQ-03、AC-03／AC-04／AC-13；保留原 ID，不改变其他租户与身份要求。
- **当前设计**：自动角色固定 `admin/build/create_workflow`，不自动授予 `create_app`；后端仅 Workflow 创建入口兼容两种能力，其他应用和通用模板保留原门禁。旧人工通用能力不撤销。
- **任务草案**：42 项全部未勾选；前置基础声明后先完成专属创建的后端／Platform 闭环，再接 Owner 开通、目录／SSO／Worker、控制面及隔离 E2E。真实联合验收独立保持 `NOT_RUN`。
- **实际命令**：`node --input-type=module` 内联脚本检查文档本地链接、空白、稳定 ID、设计覆盖、任务 metadata、AC 引用及依赖顺序；并执行 `git diff --check`。
- **实际结果**：6 份文档的本地链接与空白检查通过；7 项需求、14 条 AC、42 个唯一任务；设计覆盖 `7/7`，任务覆盖 `14/14`，全部依赖存在且指向前序，自动模板不含通用键；退出码 `0`。
- **检查修正**：初次检查发现任务草案文件末尾多一个空行，已删除后重跑通过；未据此运行或改写业务代码。
- **审查口径**：按项目 spec／design／tasks 清单核对本次增量，包含专属能力兼容、其他类型直接接口拒绝、原默认角色不扩权及任务测试先行。清单中的文档追踪检查不是权限行为验证。
- **建表描述纠正**：已读取数据库局部规则 §5 与 `alembic/README.md`，三张缺失整表应使用现有模型发现／升级前补表流程，不添加重复空迁移。旧表演进仍归 Alembic；本轮没有建表或执行迁移。

本轮文档更新后，对验证记录本身增量检查链接及空白，回执随本轮工具结果记录。没有运行 Python、前端或网关行为测试；当前源码仍没有 `create_workflow` 的新增实现，不能按此设计宣称已授权或已验收。

## E-006：实施范围、环境与测试先行

- **Status**：`PASS`，范围与红灯记录。
- **代码状态**：毕昇 `feat/v3.0.0/118-kunlian-integration`，基线 `02b22c810d72601cba50bf7ca5a6968a565876af`；网关 `feat/kunlian-integration`，基线 `4e15750f922454ed87587d857c3b7bb6f4e17816`，均为未提交工作树。本轮不切换分支，保留此前联调修复。文件摘要见 [源码校验记录](./evidence-local-20261111.json)。
- **Python**：当前仓库 `.venv` 是 3.14，不作为本批基线；复用既有 Python 3.11.14 环境 `/Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning/src/backend/.venv`。下文 `PY311`／`RUFF` 分别指其 `bin/python`／`bin/ruff`，不安装依赖。后端工作目录 `src/backend`，`PYTHONPATH=.`。
- **前端**：复用现有 Vitest、上层工作区 ESLint 和 tsc-strict；工作目录 `src/frontend/platform`。
- **网关**：复用本机 Homebrew JDK 17 与 Maven 缓存，`JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`；使用 `mvn -o`，不安装依赖或更改服务配置。
- **基线**：旧创建门禁及 Alembic 单 head 6 项通过；前端原三文件 30 项通过。
- **预期红灯**：后端新文件初次 3 失败／2 通过，暴露专属键被拒及类型 5／35 未拒绝；前端组件在修正缺失 selectLabel 的夹具后 3 项失败，暴露新建、旧目标及复制请求缺失。补真实有效菜单计算后再次 1 失败／7 通过，发现新键缺 build 父项时仍放行，已针对新键剥离孤儿项。原 create_app 兼容语义保留。

## E-007：后端定向与相关回归

- **Status**：`PASS`，V2／相关 V3；全部退出码 `0`。
- **新行为**：使用真实 FastAPI 路由及真实有效菜单计算，DAO 侧使用隔离适配器；验证专属／原通用能力创建、撤权后相同幂等键被拒、scope 不授予权限、助手拒绝、父菜单缺失、其他应用类型拒绝及无效会话。配额、幂等与越租户请求复用既有 Workflow API／仓储集成测试。
- **模型**：临时 SQLite 三表创建、模型发现、控制面与业务租户隔离、索引及持久 fence CHECK；没有真实 MySQL／DM8 或完整 Owner 事务验证。

```bash
PYTHONPATH=. "$PY311" -m pytest \
  test/sso/test_kunlian_workflow_creation_access.py \
  test/sso/test_kunlian_scope_policy.py \
  test/database/test_kunlian_onboarding_metadata.py \
  test/api/test_create_app_permission_gate.py \
  test/database/test_alembic_single_head.py \
  test/role/test_role_service.py \
  test/user/test_menu_approval_scope.py \
  test/workflow/test_kunlian_workflow_management.py \
  test/workflow/test_kunlian_workflow_registration_e2e.py \
  test/sso/test_kunlian_directory.py \
  test/sso/test_kunlian_login_contract.py \
  test/sso/test_kunlian_admission.py \
  -q --tb=short --disable-warnings
```

- **结果**：`142 passed, 22 warnings in 9.66s`。之后仅在创建门禁测试补充无效会话用例，单跑 `test/sso/test_kunlian_workflow_creation_access.py` 得 `9 passed, 7 warnings in 0.18s`；未把两次结果相加为同一次全量执行。
- **集成失败与修复**：早先合跑出现租户上下文失败。新测试的全局过滤事件已移入独立解释器；旧登记夹具显式使用租户 7 严格上下文。没有禁用过滤或放宽授权；修复后上述 142 项合跑通过，无未处理失败。

## E-008：Platform 组件、请求与权限

- **Status**：`PASS`，V1／组件集成；退出码 `0`。不是完整浏览器验收。

```bash
./node_modules/.bin/vitest run \
  src/test/roleMenuSelection.test.ts \
  src/test/resolveRoutePermissions.test.ts \
  src/test/gov07NoNewPermissionPoint.test.ts \
  src/test/kunlianWorkflowCreationPermissions.test.tsx \
  src/test/kunlianWorkflowEntry.test.tsx \
  src/controllers/API/workflow.test.ts --reporter=dot
./node_modules/.bin/vitest run src/test/appTemplatePermissions.test.tsx --reporter=dot
```

- **结果**：第一条 `6 files, 57 passed`（1.69s）；第二条 `1 file, 15 passed`（1.04s）。验证专属键保存、父项联动、默认无创建能力、路由不转换通用键；管理页新建、复制需源编辑权、固定类型／来源／幂等键及旧新建目标。模板管理不会从 create_workflow 推导，保留原管理员门禁。
- **提示**：有既有 Vite CJS 和 React Router Future Flag 警告，未导致失败。

## E-009：网关配置与旧登录回归

- **Status**：`PASS`，V2 相关回归；网关目录执行，退出码 `0`。

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  mvn -o -q '-Dtest=Kunlian*Test' test
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  mvn -o -q -Dtest=KunlianScopePolicyTest test
```

- **结果**：首条 Surefire 汇总 `75 tests, 0 failures, 0 errors, 0 skipped`。随后补充真实 Spring 配置绑定用例，第二条 `3 tests, 0 failures, 0 errors, 0 skipped`。源实现未再改变，不把两次运行写成一次 76 项回归。
- **边界**：组合不混用、非法整组拒绝、旧 fixed 模式兼容、配置绑定与阶段门禁通过；新组合令牌和双端实际交接待 T028–T030，真实昆联未连接。

## E-010：静态门禁与文档核对

- **Status**：`PASS`，V0／V1。
- 后端触达及新增文件执行 `RUFF check`；对新增／短文件执行 `RUFF format --check`，`9 files already formatted`。初次新注释全角标点及测试 import 排序已修复，未格式化无关代码。
- Platform 触达实现及测试执行 `../node_modules/.bin/eslint <文件列表> --suppressions-location eslint-suppressions.json`，通过；补充模板测试后定向 ESLint 也通过。
- `../node_modules/.bin/tsc-strict`：`1053 strict files` 全部通过。其后仅增加模板测试等价案例，无生产逻辑或类型更改。
- 逐文件运行 `scripts/arch-guard.sh`：无 VIOLATION；`workflow.py` 保留既有 RULE-3 WARNING，本批未新增复杂 DAO 业务。
- 三种语言 JSON 解析、两仓库 `git diff --check`、文档本地链接／稳定 ID／任务依赖／进度及新增文件空白已核对；42 个任务唯一，12 个完成、30 个未完成，未把真实验收勾选。
- **检查器纠正**：末次空白检查曾错误地将已跟踪文件整体与空文件比较，命中原有注释尾空白；改为跟踪文件只检查实际 diff、新文件检查全文后，37 文件及两仓库检查通过。未为此修改原有无关空白。

## E-011：T001–T012 任务级审查

按项目 task-review L1 的适用项审查；本批不代替最终特性审查 T041。

| 任务 | 结果 | 核对与证据 |
| --- | --- | --- |
| T001 | PASS | 配置 helper 纯数据，无领域依赖；默认关闭与新模式拒绝，E-007。 |
| T002 | PASS | 三表属于原领域、标准 tenant_id 索引及时间；无角色级联删除，E-007。 |
| T003 | PASS | 模型发现与严格过滤；临时建表和单 head 通过，集成夹具显式租户，E-007。 |
| T004 | PASS | 仅新增专属枚举，无数据或既有 Grant 修改。 |
| T005 | PASS | 无凭据变更，组合及绑定测试；阶段门禁见设计 §4.2，E-009。 |
| T006 | PASS | 测试命名、AC 追踪及预期红灯；兼容旧 API 用例，E-006／E-007。 |
| T007 | PASS | 原可信主体与有效菜单，当前授权先于回执；配对测试通过，E-007。 |
| T008 | PASS | 菜单／路由清单测试保留旧安全目标，E-008。 |
| T009 | PASS | 现有组件、默认无创建权、路由直接复用，E-008／E-010。 |
| T010 | PASS | 三语同键，无生成文件手改，E-010。 |
| T011 | PASS | 组件及请求独立断言，模板权限拒绝，E-008。 |
| T012 | PASS | 现有 API 封装及路径复用，源编辑权和固定类型／幂等保留，E-008／E-010。 |

设计、任务落点和验证状态已同步。不包含真实数据库并发、自动开通浏览器验收或服务器部署。

## 待执行

| 验证组 | 状态 | 未执行原因 |
| --- | --- | --- |
| V-01 开通与权限定向回归 | `PARTIAL` | 专属创建已通过；自动租户／角色／用户资格及阻断待 T013 起实施。 |
| V-02 持久化、并发与失败接续 | `PARTIAL` | 模型及临时隔离通过；Owner 编排／事务、真实 MySQL／DM8／OpenFGA 待执行。 |
| V-03 隔离 Mock 浏览器 | `NOT_RUN` | 组件测试通过不替代完整双租户开通浏览器闭环，待 T038。 |
| V-04 网关与后端联动 | `PARTIAL` | 纯配置及原登录回归通过；组合模式令牌和会话待实施，真实范围与身份待昆联提供。 |
| V-05 完整阶段文档核对 | `PARTIAL` | 首 12 项已核对；其余实现、全特性交付审查待后续完成。 |
| T042 真实环境联合验收 | `NOT_RUN` | 未连接真实昆联、数据库或服务器；缺多租户范围及测试身份，不部署。 |

此前单租户试点的真实 SSO 验证不替代本批多租户验收。本批已有有效证据仅在受影响代码变化后才重验；未将不同层级或多次执行相加为全量通过。
