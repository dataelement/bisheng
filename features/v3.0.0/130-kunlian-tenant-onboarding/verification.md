# 昆联租户与用户自动开通：验证记录

更新日期：2026-11-12

## 当前结论

原计划 **32/42** 完成；后续发现“账号已同步但组织成员列表为空”，追加修复 **T043–T045 三项均完成**。用户批准后于 2026-11-12 19:38:53 +08:00 部署六个后端运行文件，104 的 15 名昆联用户成员关联和实际权限检查通过；重复两轮恢复保持数量，试点成员页与真实 SSO 回跳通过。详见 E-025–E-028 与 [本次修复部署记录](./deployment-20261112-membership-fix.md)。本次修复未暂存、提交或推送。

本次相关回归 **403 通过、4 失败**；4 项均与未修改 HEAD 基线的旧夹具失败一致，无新增失败，不标作整套绿灯。此前 378 项、补充 12 项和网关 77 项保留历史命令含义，不与本次结果累计；受本次源码影响的后端证据以 E-026 为准。控制面、完整隔离 Mock 浏览器、跨租户完整矩阵与真实故障验收仍待后续，整项真实验收为 `PARTIAL`。其他租户 SSO 仍受昆联客户端登记限制。

**环境异常尚未关闭**：前一领域实施批次早期误用另一工作区指向 `192.168.106.116/langflow` 的配置，旧入口测试曾漏注入默认会话；对测试角色 `role_id=91` 及关联是否产生影响目前不能确认。详见 E-013。已改为无真实凭据的 SQLite 配置并在测试启动前阻断 TCP，之后的本地验证不再连接该库。用户指定的联调环境是 `192.168.106.104`；此前本地批次不包含部署授权，后续明确授权的 104 部署另见 E-023，本轮未访问 116。

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

## E-012：后续授权的提交、服务器更新与冒烟

- **Status**：`PASS`，仅已实现首批的部署与冒烟；完整联合验收仍 `NOT_RUN`。
- **授权**：用户要求“更新到服务器上，并提交暂存区”。毕昇提交 `34198e6105`、网关 `bab8dd72`；均核对提交树与原 index tree 一致，无自动暂存和 Git push。
- **部署**：服务器 192.168.106.104，发布 `20261111-f130-2000`，3001 端口不变。17 个运行源码文件、813 个静态文件与 JAR 哈希核对通过；Platform 52.41 秒构建成功，JAR 离线构建成功。保留原 Client 产物、配置与凭据，重启 API／Worker／网关，Nginx 仅重载；SQL 全库备份通过。
- **实际数据库**：启动补齐计划内三张独立空表和 tenant_id 索引，无表删除或历史回填。仅关闭本批表结构冒烟缺口，不关闭真实并发、事务、DM8 或双租户开通验收。
- **运行**：API healthy，原容器、镜像、环境、挂载及网络名称保留；API／Worker 动态地址互换，网关受信地址不变。16 个运行配置文件哈希保持一致。原目录同步继续到第 26 批，自动开通仍关闭、范围仍 fixed。
- **访问**：内外网管理页、编辑深层路由、Client、env、登录方式及三语新增文案入口正常；公网授权返回 303，内网未登记 Origin 仍拒绝 403；未认证创建返回 401。Chrome 既有 admin 会话验证列表、新建表单和取消，未创建对象、未观察到控制台 error。
- **证据**：[部署与回退记录](./deployment-20261111.md)、[精简结构化证据](./evidence-deployment-20261111.json)。工具退出 0；诊断工具的排序／动态地址断言和一次性连接关闭已修正并复验，不通过改运行安全策略消除失败。
- **提交后的记录**：本条及部署记录为部署后新产生，留在工作区，未再暂存或追加提交。历史首次实现证据保持原含义。

## E-013：T013–T024 范围、隔离与环境异常

- **代码位置**：`/Users/wenruli/code/project/bisheng/bisheng-kunlian-tenant-onboarding`，分支 `feat/v3.0.0/118-kunlian-integration`，基线 `2ed971aed7`。主工作区已处于另一发版分支且有未提交工作，使用隔离 worktree 保留其现场；没有自动暂存、提交、推送或部署。
- **授权边界**：用户指定 T013–T024，本批使用已有三表模型，不改已有模型或真实 Schema。T025 起的目录、登录与 Worker 装配没有提前实施。
- **环境失误**：初次测试缺配置；尝试初始化配置又因旧键不兼容退出，均不能作为行为结果。之后误用主工作区另一分支的配置，其默认库指向 `192.168.106.116:3306/langflow`。早期新旧入口测试没有完整注入 RoleService／RoleDao 的默认会话：出现角色未找到、事件循环错误；旧同步删除路径在后续 Request 夹具报错前可能已调用真实默认 DAO。不能据此声称“没有真实写入”。
- **核查限制**：尝试一次受控只读核查，连接返回 `1045 Access denied`，没有获得可用审计证据。`role_id=91` 及其关联影响保持 **UNKNOWN / 待授权审计核对**；未猜测恢复、未回灌或清理。用户随后明确环境应为 104，已停止使用 116；本轮不连接 104 执行写入或部署。
- **纠正措施**：全部旧 DAO 的同步／异步工厂显式注入临时 SQLite；同时采用独立、无真实凭据的配置和在应用导入前执行的 socket TCP 阻断。后续完整回归在此隔离措施下通过。配置与阻断包装器位于本机临时目录，摘要见 [本轮校验记录](./evidence-local-20261112-c.json)，未修改受控运行配置。

## E-014：测试先行与实现中修复

- **本地预期失败**：在 `2ed971aed7` 的源归档上放入租户／锚点测试，7 项因缺少计划内 Owner application 失败；角色和用户用例分别出现缺模块失败，再新增实现。归档、测试均不代表真实环境验证。
- **旧写入口预期失败**：将本批 Owner 文件及正确隔离夹具放入基线归档，保留原角色服务／用户 API；两个 mutation 文件得 `6 failed, 2 passed`。失败为受管变更未置墓碑、模板扩权未拒绝、撤销绕过同事务入口。加入 application 分支后对应测试通过。日志 `/tmp/kunlian-f130-c-old-entrances.log`。早期误用默认数据库会话的失败不计入这一安全隔离红灯证据。
- **兼容性补测**：末轮检查发现管理员角色限制放在“是否受管”识别之前，会改变普通用户原路径。新增独立回归先得到 `1 failed`，把限制收回受管分支后通过；原入口仍先完成操作者授权。
- **串联夹具修正**：完整串联测试调用原成员接口前补上目标租户上下文，保留原接口的严格校验；没有放宽生产隔离。原普通角色测试只替换新增受管端口为普通分支，受管入口另用真实 SQL 测试；源码顺序断言改为不依赖引号形式。

## E-015：Owner 模块与旧入口最终相关回归

- **Status**：`PASS`，V2／相关 V3；命令退出 `0`。
- **运行环境**：复用既有 Python 3.11.14 环境 `bisheng-kunlian-sso-planning/src/backend/.venv`；不安装依赖。配置只含临时 SQLite、loopback 的不可用 Redis／Celery 地址与日志级别，不含真实服务器凭据。工作目录为隔离 worktree 的 `src/backend`。
- **隔离方式**：临时包装器在 `pytest.main()` 之前替换 `socket.socket.connect/connect_ex`，AF_INET／AF_INET6 一律抛出 AssertionError；夹具再次阻断网络并为旧 DAO 注入 SQLite。SQLite 使用真实 SQLModel 表、事务、项目 tenant filter；OpenFGA 调用采用 Mock，不把 SQLite 当作 MySQL 行锁证明。

以下 `PY311` 为上述环境的 `bin/python`，`MOCK_DIR` 为本轮临时目录 `/var/folders/06/935ggv0j2259kmb0t_3nvhpc0000gn/T/kunlian-f130-c-tests-bcibvvx4`。其配置／包装器内容与 SHA-256 已随证据 JSON 保存，可在其他临时目录按相同规则重建，不能替换为日常开发配置直接重跑。

```bash
config="$MOCK_DIR/config.yaml" PYTHONPATH=. "$PY311" "$MOCK_DIR/pytest-offline.py" \
  test/role/test_role_service.py \
  test/role/test_role_api.py \
  test/user/test_kunlian_external_identity.py \
  test/sso/test_kunlian_projection.py \
  test/sso/test_kunlian_workflow_creation_access.py \
  test/sso/test_kunlian_admission.py \
  test/user/test_menu_approval_scope.py \
  test/workflow/test_kunlian_workflow_management.py \
  test/workflow/test_kunlian_workflow_registration_e2e.py \
  test/database/test_kunlian_onboarding_metadata.py \
  test/tenant/test_kunlian_external_provision.py \
  test/department/test_external_tenant_anchor.py \
  test/role/test_external_basic_role.py \
  test/role/test_external_basic_role_mutations.py \
  test/user/test_external_basic_access.py \
  test/user/test_external_basic_access_races.py \
  test/user/test_external_basic_access_mutations.py \
  -q --tb=short --disable-warnings
```

- **最终结果**：`150 passed, 22 warnings in 8.55s`；日志 `/tmp/kunlian-f130-c-final-3.log`，退出码独立保存为 `0`。22 项警告及退出时 swig 弃用提示不作为失败或静默修复范围。
- **实际验证**：同名来源隔离、明确人工映射、事务回滚和结构提交后查回；模板三键且无管理员／资源 Grant、暂停与恢复、名称碰撞；用户原投影回执匹配、唯一实际自动关系、人工角色保留、来源栅栏变化、模板阻断、撤销先／应用先的交错及失败回滚；新旧角色和用户角色入口同事务保护；普通角色兼容。
- **串联结果**：真实租户 application 创建 Child／锚点 → 原用户影子投影 → 原成员 application（Mock 权限投影）→ 基础模板 → 用户基础关系；重复应用只有一条关系。没有从真实目录或浏览器登录触发这个过程。
- **证据限制**：交错验证由不同 application 实例读取持久状态，并非真实并发 Worker 的数据库行锁测试；浏览器、MySQL／DM8、OpenFGA 及昆联联调全部另记待执行。

## E-016：静态、QA 参考与文档一致性

- 新增 19 个 Python 文件 Ruff check／format 检查通过；全部 23 个改动 Python 文件无新增 lint 问题。原 `user/api/user.py` 的 60 项、原 `test_role_api.py` 的 2 项告警与基线逐条比对一致，未为清理历史告警批量格式化。全文件 Ruff 原始退出为 `1`，不能宣称全仓 lint 通过。
- 对本批 23 个 Python 文件运行 `scripts/arch-guard.sh`，未出现 VIOLATION；没有手写租户条件或在服务层增加 SQL。
- 当前 QA 模板要求新增 [test-cases.md](./test-cases.md)：九条八列人工参考用例、需求／设计依据和环境准备，测试结果均为“待执行”。这不替代后续 T038 的浏览器验收。
- 任务勾选／引用／文档空白与源码摘要以最终 [本轮校验记录](./evidence-local-20261112-c.json) 为准；规格只更新进度说明，需求与验收语义不变。

## E-017：T013–T024 L1 任务核对

按项目 task-review L1 适用项核对本批，配对测试与当前代码状态均引用 E-015；不代替 T041 全特性审查。

| 任务 | 结果 | 证据与边界 |
| --- | --- | --- |
| T013–T016 | PASS | 部门事务适配、稳定来源／回执、同事务结构、失败查回；无管理员和默认共享；E-014、E-015。 |
| T017–T019 | PASS | 模板固定三键、持久暂停及显式恢复、角色端口受限锁；没有资源 Grant；E-015。 |
| T020–T022 | PASS | 原用户回执验证、UserRole 原子提交、撤销不复活、人工角色保留；当前资格协议尚未接入 SSO；E-015。 |
| T023–T024 | PASS | 新旧写入口保留授权前置并收口至所属领域；普通角色兼容；E-014、E-015。 |

T013–T024 的勾选仅表示本地实现与指定 Mock 验证完成。环境误用事件仍未关闭，不能据此声称 116 无影响或 104 已更新。

## E-018：T025–T032 执行范围与测试先行

- **范围**：承接用户“好的帮我实施”与已确认方案，本批实施目录开通、双端准入和恢复的 T025–T032。沿用原隔离 worktree／分支，网关基线 `bab8dd72`，没有改实际 YAML、凭据、Schema，未连接 104 或 116 执行部署／核查。E-013 的早期环境异常继续保持未知影响，没有声称已关闭。
- **测试先行**：开通服务缺失时新目录文件 3 项 setup error；精确组合新增用例 `3 failed, 1 passed`，暴露阶段门禁及固定字段依赖；新增登录／会话用例 `5 failed`，暴露缺开通资格未拒绝、缺映射错误分类及内省后仍使用旧角色；Worker 新阶段参数在原代码得到 1 项 TypeError；网关新增组合令牌用例 1 项失败于未就绪。修改后分别通过。
- **实现核对补充**：检索仍发现后端客户端构造器要求固定字段，因此将初始化纳入相同组合验证，增强测试在创建客户端之前设置 map 模式并清空旧字段。原投影和资格协调增加可选当前连接政策校验，失去当前发布／修订不能继续派发原计划。
- **阶段证据**：目录与原发布回归 `30 passed`；登录／客户端／准入相关 `78 passed`；Worker 与兼容回归 `11 passed`；新增阶段模块与旧 Worker `24 passed`。这些是阶段记录，最终复用 E-019／E-020，不将阶段数量累计。

## E-019：后端最终相关回归与补充检查

- **Status**：`PASS`，V2／相关 V3；两次最终命令退出均为 `0`。
- **环境**：沿用 E-015 的 Python 3.11.14、独立临时 SQLite 配置和 TCP 阻断包装器；测试未使用日常开发库配置。不安装依赖，没有真实目录、Redis、OpenFGA、MySQL／DM8 或浏览器登录。
- **后端工作目录**：`/Users/wenruli/code/project/bisheng/bisheng-kunlian-tenant-onboarding/src/backend`；`PY311`、`MOCK_DIR` 含义同 E-015。

```bash
config="$MOCK_DIR/config.yaml" PYTHONPATH=. "$PY311" "$MOCK_DIR/pytest-offline.py" \
  test/sso/test_kunlian*.py \
  test/role/test_role_service.py test/role/test_role_api.py \
  test/role/test_external_basic_role.py test/role/test_external_basic_role_mutations.py \
  test/user/test_kunlian_external_identity.py test/user/test_external_basic_access*.py \
  test/user/test_menu_approval_scope.py test/tenant/test_kunlian_external_provision.py \
  test/department/test_external_tenant_anchor.py test/database/test_kunlian_onboarding_metadata.py \
  test/workflow/test_kunlian_workflow_management.py \
  test/workflow/test_kunlian_workflow_registration_e2e.py \
  -q --tb=short --disable-warnings
```

- **结果**：`378 passed, 22 warnings in 26.66s`。完整日志 `/tmp/kunlian-f130-d-final.log`，退出码文件为 `0`。该命令包括现有 FastAPI／WebSocket、SSO、目录、角色和工作流相关回归，不是全仓测试或完整浏览器验收。
- **之后的变更**：只增强三个新测试文件：加入现存人工映射的完整恢复、map 模式下已有会话，以及错误组合的直接内省拒绝；生产代码未再变化。随后仅对这三个文件执行以下命令，当前退出 `0`，结果保存在本批证据 JSON；复用其余未变化范围的通过证据。

```bash
config="$MOCK_DIR/config.yaml" PYTHONPATH=. "$PY311" "$MOCK_DIR/pytest-offline.py" \
  test/sso/test_kunlian_onboarding_scope.py \
  test/sso/test_kunlian_onboarding_admission.py \
  test/sso/test_kunlian_onboarding_directory.py \
  -q --tb=short --disable-warnings
```

- **已验证结果**：完整当前批次才创建、同批次补绑定、迟到 Owner 回执拒绝且复用结构；人工映射及名称不动；投影已成功但缺基础资格仍恢复；来源阻断不拖住其他就绪租户；双端严格组合、内省返回后的角色／来源复核和无剩余入口拒绝；分阶段续取、通知丢失重试、另一个服务实例从根扫描发现较早键；实际 runtime 将同一协调器装配到登录、会话、Worker。
- **限制**：持久 SQLite／Mock 的交错和实例重建不能证明真实数据库行锁、多进程 Worker 或消息中间件故障；真实客户端范围、实际身份、OpenFGA 和 104 浏览器联调继续 `NOT_RUN`。

## E-020：网关组合、令牌及原流程相关回归

- **Status**：`PASS`；JDK 17 + Maven 离线缓存，未安装依赖。工作目录 `../bisheng-gateway`。

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  mvn -o -q '-Dtest=Kunlian*Test' test
```

- **结果**：8 个测试类共 `77 tests, 0 failures, 0 errors, 0 skipped`，命令退出 `0`。从本次 Surefire XML 读取计数；日志 `/tmp/kunlian-f130-d-gateway-final.log`。
- **覆盖**：真实 Binder 在 map 模式不依赖旧固定字段；本机生成 RS256 测试密钥验证 A／WA、B／WB 并拒绝 A／WB；原 nonce、签名、PKCE、一次性事务、交接、登出和安全配置回归保留。网络适配为 ExchangeFunction 与现有 loopback Mock 服务，没有调用昆联真实地址。
- **改动**：仅配置就绪、令牌 scope helper 和对应 3 个测试文件。未新增接口、依赖、目录 Key 或运行凭据。

## E-021：静态检查、设计及 QA 同步

- 本批及前批工作树共 42 个改动 Python 文件执行架构检查，无 VIOLATION；Ruff 对比基线无新增问题。原 62 项历史问题未清理，不能写成全仓 lint 通过。新增／本批改动文件格式检查、文档链接／空白、32/42 勾选和 14 条八列 QA 参考用例由最终检查器记录。
- Spec 仅更新实施状态；design.md 同步成员协调复用、只读领域端口、组合初始化、内省后重读、恢复游标与预算。没有扩大到控制面或真实启用范围。
- [本批源码与验证摘要](./evidence-local-20261112-d.json)保存命令、退出码、源码 SHA-256、两仓库基线与当前本地边界。E-015／E-017 的上一批结论保留历史含义，受影响源码的当前覆盖引用 E-019。

## E-022：T025–T032 L1 核对

| 任务 | 结果 | 对照与证据 |
| --- | --- | --- |
| T025–T026 | PASS | 当前发布及政策、来源／映射修订、补绑定及独立资格恢复；跨领域只用 application；E-018／E-019。 |
| T027–T028 | PASS | 当前身份、组合及资格，不在回调写入开通；HTTP／WebSocket 网络返回后重读；E-019。 |
| T029–T030 | PASS | 后端和网关同时完成组合接入及初始化必填调整；fixed 默认不变；E-019／E-020。 |
| T031–T032 | PASS | 原任务的 Root header 保留、阶段独立游标、有界恢复、漏投和根扫描；E-019。 |

完整特性审查 T041 及真实联合验收 T042 尚未完成，不以本表代替。

## E-023：104 后续授权部署与保护检查

- **Status**：`PASS`，限定本次更新；完整特性仍未验收。用户已明确授权部署 104 并调通 SSO／用户同步，取代此前仅本地不部署的运行边界，没有追溯改写 E-018–E-022。
- **事实**：当前源码在隔离 worktree，部署的是未提交文件集合；24 个后端运行文件、网关 JAR 全部哈希通过。没有修改前端、安装依赖或重建应用镜像。源码仍目录挂载，网关切换到 `releases/20261112-f130-sso`。
- **配置**：仅后端开启 `auto_onboarding_enabled=true` 并将策略提高为 3；两端登录仍 fixed，客户端、凭据、Origin、回调及网关源信任不变。其余 12 个配置／凭据文件哈希相同；后端 YAML 排除上述两项后节点语义完全相同。
- **备份**：全库导出 10,507,132 字节及 SHA-256 已核对；私有源码、配置和容器备份在受限目录。回退脚本语法与无写入前置核查通过，恢复时关闭自动开通、策略提高到 4、保留所有业务数据；未实际执行回退。
- **运行**：API healthy，Worker／网关 running，重启计数 0；原容器、镜像、环境、挂载和网络名称保留，网关受信地址仍为 172.19.0.12。公网管理页 200、匿名 user/info 与 Workflow 创建 401、公网授权入口 303、未登记内网 Origin 403。
- **诊断修正**：首次批量只读命令包含服务器自身访问公网 NAT 地址的请求而整体超时，拆开并设置请求超时后完成核查；首次切换启动期出现暂时连接重置／502，健康就绪后恢复。没有通过放宽认证或 Origin 来消除错误。
- **证据**：[部署联调记录](./deployment-20261112-sso.md)、[结构化证据](./evidence-deployment-20261112.json)。本次没有新增 Schema、回填历史账号或访问 116。

## E-024：真实目录、基础资格与浏览器 SSO

- **Status**：`PASS`，仅下列已执行子集；T042 整项仍为 `PARTIAL`。
- **目录**：从实际后端使用已有 Key 完成真实全量发布，批次 `f3f044ff-0f2c-49a4-b1ab-16e00b935f6a`，请求／完成版本 302。13 个租户、18 个成员均保存；10 个 ACTIVE 租户与其 15 名有效成员物化，3 个 SUSPENDED 租户及其 3 名成员不自动开通。
- **原领域与存储**：10 条租户 READY、10 条基础模板 APPLIED、15 条用户资格 APPLIED；15 条实际自动 UserRole，与 15 个 ACTIVE／SUCCEEDED 身份一致。模板仅三键，无业务资源 Grant；原两条人工角色关系原样保留。真实 MySQL 写入及原成员权限投影的就绪结果已经执行验证，不继续将这部分写成仅 Mock。
- **浏览器**：Chrome 公网管理入口 → 昆联统一登录 → 已交付测试账号 → 真实回调 → user 2／tenant 2 管理页；打开新建表单后取消，刷新后仍可访问。毕昇退出 → 昆联确认退出 → 本站 `LOGOUT_CALLBACK_RECEIVED`；SQL 显示 REVOKED 1、ACTIVE 0（另有历史 EXPIRED 2），重新访问要求认证；再次登录回到管理页。
- **记录**：截图、匿名拒绝、当前准入范围和会话归属均在本次结构化证据中；没有保存原密码、Token、授权码或带 id_token_hint 的退出 URL。
- **限制**：仅已登记试点账号的真实 SSO 通过；其他租户的客户端准入、完整权限矩阵、并发撤销、真实行锁／故障注入、跨 Worker 中断与 DM8 仍待执行。单次真实同步／浏览器成功不替代整项联合验收，也不提前关闭 T033–T041。

### E-025：成员列表缺失的真实复现与测试先行

- **范围**：REQ-08、AC-15／AC-16、T043–T045；修复基线 `164917c721d1049d8e1e0de9a5ab1d2be7bf9bff`，使用当前昆联隔离工作树，不改主工作树或网关，不暂存、提交或推送。
- **104 只读证据**：15 名昆联用户均已有账号、有效租户关联和基础角色，但缺少部门关联；组织与成员页面选择“昆联Workflow联调”后显示 0 条。根因为只建立 `UserTenant`，成员页依赖 `UserDepartment`；原成功投影短路及候选筛选也漏掉历史补齐。首次只读 SQL 中误将响应模型的 `tenant_id` 当作 User 表列，查询报 1054；已按真实 `user_tenant` 表纠正，只读未写数据。
- **预期失败**：修复生产代码前，以真实隔离 SQL 和原部门成员查询运行新文件 `test/department/test_kunlian_external_membership.py`，得到 `3 failed`，均因新用户无关联或已成功用户仍查询到 0 名成员。退出 `1`，日志 `/tmp/kunlian-f130-member-red.log`。
- **环境**：沿用 E-015 的 Python 3.11.14、无真实凭据 SQLite 配置和 pytest 启动前 TCP 阻断；不连接 104、116、Redis 或 OpenFGA 执行开发测试。104 另外的 SSH 核查只读，非本地测试数据库。

### E-026：部门成员修复与成功回执恢复

- **实现**：租户成员 application 在原事务成功后调用部门 application；部门在原成员写事务内校验、锁定租户及用户，并复用既有部门持久权限投影。Root 挂载按专用受控上下文处理。已有合法人工主部门不迁移，旧账号不合并；投影成功短路和基础资格扫描均补齐当前有效成员，覆盖旧数据。
- **定向命令**：使用 E-015 的 `config`、`PYTHONPATH=.`、`PY311` 和 `pytest-offline.py`，运行 `test/department/test_kunlian_external_membership.py test/tenant/test_kunlian_external_membership.py test/sso/test_kunlian_projection.py -q --tb=short --disable-warnings`。阶段结果 `25 passed`、退出 `0`，日志 `/tmp/kunlian-f130-member-focused.log`。之后追加一条权限准备失败用例，由下述最终相关回归覆盖。
- **最终相关回归**：复用 E-019 的选择，额外加入 `test/tenant/test_kunlian_external_membership.py`、`test/department/test_kunlian_external_membership.py`、`test/department/test_dept_member_add_sync.py`、`test/permission/test_f048_department_scope_runtime.py`。实际完整命令和输出见 [本次结构化证据](./evidence-local-20261112-membership-fix.json)。当前结果 **`403 passed, 4 failed`、退出 `1`**，日志 `/tmp/kunlian-f130-member-regression-final.log`；不标作整套绿灯。
- **基线对照**：将 HEAD 的受控后端及 feature 样例归档到临时目录，用同配置、解释器、TCP 阻断和相同既有测试选择运行，得到 **`392 passed, 4 failed`、退出 `1`**。4 个失败 ID 和错误类别与当前一致，均为旧 `test_dept_member_add_sync.py` 的 SimpleNamespace 夹具缺 `permission_projection_state`／`tenant_id`，未新增失败。最初基线归档漏带样例文件引起额外 1 失败，补齐受控样例后重跑，使用最终结果；不把该环境缺件当作产品回归。
- **本次新增 11 项全部通过**：新增与旧用户补齐、常规扫描／成功回执重试、原成员查询可见、幂等、两个租户隔离、错误挂载／租户关联／来源／停用拒绝、保留人工主部门、权限准备失败回滚和持久投影迟后恢复。权限外部端口采用 Mock，SQL、成员查询和部门投影状态绑定／恢复使用真实隔离库；不证明 MySQL 行锁、DM8 或真实 OpenFGA 已验收。

### E-027：静态检查与上线准备（尚未部署）

- 10 个变更 Python 文件执行 Ruff 与未修改 HEAD 基线比较、逐文件 `scripts/arch-guard.sh`：**新增违规 0**；旧代码原有 89 条 Ruff 提示保持，不扩大格式化。新文件及所选适配文件 Ruff 通过；`git diff --check` 通过。
- 六个运行文件已打包，记录前后 SHA-256；四个服务器现存文件与 HEAD 前置摘要完全一致，两文件为新增。104 只读核查有一个 CURRENT Catalog、一个 ACTIVE 授权模型，12 个部门均为 CURRENT；本地补丁尚未上传或执行。
- **待批准的部署步骤**：104 保存源码及数据库备份 → 停止 API／Worker → 校验前置摘要并替换六个运行文件 → 启动并验证健康 → 用原目录／恢复流程补齐当前有效用户 → 真实成员查询、重复恢复和 SSO 冒烟。保持网关、前端、配置和 Schema 不变。
- **影响与回退**：预计补齐现有 15 名用户的租户根部门成员关系及相应持久权限投影；不删除／迁移账号，不覆盖已有主部门或角色。后端和 Worker 有短暂重启；失败恢复原源码并保留已合法完成的关系，不做权限或用户表批量 SQL 回写。
- **当前状态**：T043／T044 本地完成；T045 及 AC-15／AC-16 的真实补齐、页面验收 **NOT_RUN**，等待部署及数据／权限变更确认。此前“真实同步及 SSO 通过”只覆盖账号、租户、资格和试点登录，不代表组织成员页闭环已完成。

### E-028：授权后 104 部署、补齐及浏览器验收

- **授权及发布**：用户明确选择“部署到 104 并补齐、验证成员页”。发布 `20261112-membership-fix`，切换完成 `2026-11-12 19:38:53+08:00`；更新六个运行文件并仅重启后端／Worker。14 个受保护文件摘要保持；三个原容器的 ID、镜像、环境、运行配置及按 Destination 比较的目录映射保持，网关未重启。部署后 API、Worker、网关运行中，重启计数均为 0。
- **备份及回退**：私有备份 `/dataelem/bisheng-kunlian/source/backups/20261112-membership-fix`；全库导出 10,706,938 字节，SHA-256 `077134870a3fd3123b0c4ec49f76784086dc37305bc929fb7f556f6ac69786ca`。回退入口 `/dataelem/bisheng-kunlian/source/ops/20261112-membership-fix/rollback.sh`；语法与只读 rollback-check 通过，未实际执行回退。回退保留用户、角色及合法成员关系。
- **补齐与幂等**：没有直接 SQL 写成员表。重启后执行完整目录和两轮原恢复流程，各轮租户 10 成功、待资料投影 0、基础资格 15 成功、失败 0。最终 15 条昆联部门关联，缺失、错误根部门关联、未完成部门投影均为 0；User 16、Tenant 11、Role 13、UserRole 17 保持，原两条人工角色保留。成功脚本开始前已有 15 条关联，不能把这些首次写入归于手工探针；两轮脚本证明原恢复入口可重复执行并保持结果。
- **真实权限**：通过原 permission application 对 15 名实际用户逐一执行部门 member 的 HIGHER_CONSISTENCY Check，15／15 为真；没有使用超级管理员身份绕过这些检查。
- **浏览器**：原管理员会话刷新 `/sys`，选择“昆联Workflow联调”后显示用户“毕昇-WORKFLOW”、主部门、共 1 条。随后使用已交付试点账号，从公网真实授权入口重新登录，经实际回调返回 `/build/workflows`，SQL 确认 ACTIVE 会话归属 user 2／tenant 2；未创建、发布或运行新工作流。截图见 [成员页凭证](./membership-fixed-20261112.jpg)。
- **HTTP**：后端 health 200／OK，公网管理页 200，匿名 user/info 401。
- **操作中修正**：独立补齐探针首次缺 PYTHONPATH，第二次缺 Worker 的权限上下文注册；修正为 `/app` 模块路径并复用已有 Worker 生命周期后退出 0。第二次已发布目录但在成员权限步骤前失败，原始错误日志留在私有 ops 目录；后续未绕过权限。成功探针退出有 aiohttp 客户端未关闭警告，属于短生命周期探针的清理提示，生产服务健康未受影响。容器初次比对仅因 Mounts 数组次序变化误报，改按 Destination 比较确认映射定义完全一致。
- **当前结论**：本缺陷 T043–T045 完成；原 F130 完整联合验收仍为 PARTIAL，真实并发故障、MySQL 行锁竞争、DM8 和其他租户 SSO 范围不因此关闭。代码未暂存、提交或推送。
- **结构化证据**：[部署与补齐记录](./evidence-deployment-20261112-membership-fix.json)。

## 待执行

| 验证组 | 状态 | 未执行原因 |
| --- | --- | --- |
| V-01 开通与权限定向回归 | `PARTIAL` | 本地回归与真实有效成员开通／试点管理页通过；控制面及完整跨租户权限矩阵待后续。 |
| V-02 持久化、并发与失败接续 | `PARTIAL` | 真实 MySQL 开通写入与原成员权限投影通过；跨进程中断、行锁竞争、故障补偿及 DM8 待执行。 |
| V-03 隔离 Mock 浏览器 | `NOT_RUN` | 组件测试通过不替代完整双租户开通浏览器闭环，待 T038。 |
| V-04 网关与后端联动 | `PARTIAL` | 本地组合回归及 fixed 试点真实登录／刷新／退出通过；真实多租户范围与身份待确认。 |
| V-05 完整阶段文档核对 | `PARTIAL` | 前 32 项已核对；剩余实现、全特性交付审查待后续完成。 |
| T042 真实环境联合验收 | `PARTIAL` | 104 真实目录、有效成员开通和试点 SSO 已通过；完整多租户登录／权限矩阵、故障与 DM8 等未验，不勾选整项。 |

此前单租户试点的真实 SSO 验证不替代本批多租户验收。本批已有有效证据仅在受影响代码变化后才重验；未将不同层级或多次执行相加为全量通过。
