# Tasks：昆联 Workflow 编辑与执行直达入口

**Feature ID**: F129
**版本**: v3.0.0
**Created**: 2026-11-11
**关联**: [已确认规格](./spec.md)、[已确认设计](./design.md)、[版本契约](../release-contract.md)

## 1. 状态与执行边界

| 步骤 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | ✅ 已评审、用户已确认 | 2026-11-11，执行入口使用当前已发布上线版本。 |
| design.md | ✅ 已评审、用户已确认 | 2026-11-11，复用现有两端页面、SSO、权限及运行机制。 |
| tasks.md | ✅ 已拆解；T001–T009 已授权实施 | 本轮继续实施 T004–T009，未扩大到执行页或后端。 |
| 本地与 Mock 实施 | `IN_PROGRESS`，9 / 27 | 共享规则、编辑入口与网关可信目标重试已完成本地验证，见 [验证记录](./verification.md)。 |
| 双方登记条件 | `WAITING_EXTERNAL` | T028，待确认；不阻塞本地 Mock。 |
| 真实环境验证 | `NOT_RUN`，0 / 3 | T029、T030、T031，待执行。 |
| 部署 | ✅ 后续授权的本批更新已完成 | T001–T009 已部署到 3001，管理员编辑侧冒烟通过，见 [部署记录](./deployment-20261111.md)；真实 SSO 与完整验收仍待执行。 |

**链接合同**：编辑 `/flow/{workflow_id}?from=workflow-management&entry=kunlian`；执行 `/workspace/app/{workflow_id}/10?entry=kunlian`。两条链接均以实际用户及可信当前租户校验权限。不得把 `entry` 当授权，不提供历史版本或草稿执行。

**路径前缀**：`S/` = `src/frontend/packages/api-client/src/`；`P/` = `src/frontend/platform/src/`；`C/` = `src/frontend/client/src/`；`L/` = `src/frontend/packages/locales/src/shared/`；`B/` = `src/backend/bisheng/`；`WT/` = `src/backend/test/workflow/`；`F/` = 本特性目录。`G/` = 独立仓库 `/Users/wenruli/code/project/bisheng/bisheng-gateway/`，本轮仅实施 T008、T009 的 controller 与测试。

- 复用既有用户、权限、数据库及浏览器测试夹具；Mock 身份、OAuth 响应和队列替身仅在测试装配中使用，不注册到生产、不内置可绕过鉴权的测试入口。
- 权限、安全、版本及运行副作用先写失败用例，再实现；测试任务只改测试。等价输入参数化，同一代码状态下复用有效证据，不按每个微任务重复运行全套。
- 每个任务限定明确的文件和行为。T020 为同一组文案在三种语言中的原子更新，涉及 3 个语言文件；其余实现任务最多 2 个文件，不通过拆开三语制造不完整状态。
- 不新增 ORM、Schema、依赖或运行配置，不迁移数据。既有 Worker 的租户上下文继续来自服务端可信执行上下文／Celery headers → ContextVar，不从 URL 或 WS 消息取得租户。本批不新增 Worker 状态机。
- 后续实施按 [design.md §4](./design.md#4-系统现状及拟实施流程) 执行，保持用户已有改动；不自动暂存、提交、切分支或清理工作区。遇到设计范围外改动按项目确认规则处理。
- 每批完成后更新本清单及 `F/verification.md`，记录命令、代码状态、结果、覆盖及未执行原因。`verification.md` 在实施期建立，本轮不虚填业务测试结果。

## 2. 批次与验收出口

| 批次 | 任务 | 验收出口与证据 |
| --- | --- | --- |
| W1 共享链接与登录尝试规则 | T001–T003 | B1：链接解析、构造、callback 阶段、尝试去重及过期单元测试通过；无网络或身份写入副作用。 |
| W2 编辑直达与 SSO 失败回跳 | T004–T009 | B2-P：Platform 目标、拒绝及登录回归通过；B2-G：网关可信事务重试链接及恶意目标用例通过。两个仓库证据分别记录。 |
| W3 发布版本与后端授权 | T010–T015 | B3：无权／跨租户／下线拒绝；普通、Agent、知识库图均使用服务端当前发布快照；只读查询零派发，V1 恢复不改为 V2。 |
| W4 执行页身份边界 | T016–T020 | B4：身份确认前不挂载业务页、不退出或重复授权；既有会话直达，回调失败停止重跳，三语检查通过。 |
| W5 执行直达与明确开始 | T021–T025 | B5：入口、会话切换及刷新保留标记；打开或刷新零新运行、零答案重投，明确操作才开始；原普通入口兼容。 |
| W6 浏览器闭环与交付草稿 | T026–T027 | B6：两端真实页面＋隔离 HTTP／WS Mock 的浏览器闭环，以及相关回归与生产构建；交付草稿区分已验证与待联验。 |
| W7 外部条件与真实验收 | T028–T031 | 双方登记、真实数据库／OpenFGA、SSO 和部署后运行分别验收；当前保持待确认／待执行。 |

W1 完成后 W2、W3 可独立推进，W4 复用 W1 并对接 W2 登录规则；W5 依赖 W3、W4，W6 在两端闭环后执行。这里描述依赖，不要求启动并行 Agent。

## 3. Mock 优先任务

### W1 共享链接与登录尝试规则

- [x] **T001** [共享前端测试] 在 `S/kunlianWorkflowEntry.test.ts` 先写安全入口用例。使用 32 位 Workflow／chat ID，验证编辑和执行两种路径、内部会话路径、basename、重复参数、凭据／版本／租户参数、站外及双重编码拒绝。Mock Storage、时钟和 location，验证 callback 提示消费后仍能识别初始阶段、10 分钟尝试记录、并发去重、手动重试、成功清理和存储不可用。不得测试中调用实际 IdP。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-05, AC-07, AC-08, AC-09
  - _Acceptance: AC-05, AC-07, AC-08, AC-09_ · _Verification: V-01，B1_ · _Depends: 无_ · _Boundary: 仅测试，不实现工具_

- [x] **T002** [共享前端] 在 `S/kunlianWorkflowEntry.ts`、`S/index.ts` 实现及导出严格解析、链接构造和登录尝试纯函数，按设计返回 `not-entry`／`invalid-entry`／安全目标。使用同标签页尝试记录，不写身份 Cookie，不消费旧全局回跳目标，不调用 HTTP。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-05, AC-07, AC-08, AC-09_ · _Verification: V-01，B1_ · _Depends: T001_ · _Boundary: 不改变非昆联路径及通用回跳白名单_

- [x] **T003** [共享前端] 在 `S/kunlianBrowser.ts` 保留来自 callback 的初始只读阶段，供入口边界在 hash 被消费后判断。保留清旧 Bearer、来源确认、CSRF 和退出语义；提供阶段信息不授予身份。
  - _Requirements: REQ-04, REQ-05_ · _Acceptance: AC-05, AC-07, AC-08_ · _Verification: V-01，B1_ · _Depends: T001, T002_ · _Boundary: 不重写 KunlianBrowserFlow 协议_

**B1 验收**：运行共享包定向 Vitest 及类型检查。断言安全目标稳定、无 Cookie 或网络调用、同一初始导航只允许一次自动授权；过期、存储失败及手动操作分别有明确结果。

### W2 编辑直达与 SSO 失败回跳

- [x] **T004** [Platform 测试] 在 `P/test/kunlianWorkflowEntry.test.tsx` 和既有 `P/controllers/kunlianSession.test.ts` 先写编辑入口回归。覆盖有效会话、无会话、回调失效、多个并发失败、旧第三方地址及旧回跳残留、目录未就绪、输入凭据和缺少编辑资格。断言原目标、一次导航、拒绝状态以及从画布返回的管理来源；覆盖 HTTP 错误和 HTTP 200 业务拒绝。
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-05, AC-06, AC-07, AC-08, AC-10
  - _Acceptance: AC-01, AC-05, AC-06, AC-07, AC-08, AC-10_ · _Verification: V-01，B2-P_ · _Depends: T003_ · _Boundary: 只改测试，不放宽资格_

- [x] **T005** [Platform] 在 `P/utils/workflowManagement.ts`、`P/contexts/userContext.tsx` 接入精确编辑目标识别，并在历史 URL token 处理之前拒绝不安全入口。复用当前身份查询及入口资格，不从链接写用户或租户；保留管理来源和未保存返回行为。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · _Acceptance: AC-01, AC-05, AC-06, AC-08_ · _Verification: V-01，B2-P_ · _Depends: T004_ · _Boundary: 原管理页和非昆联登录不扩大识别范围_

- [x] **T006** [Platform] 在 `P/pages/LoginPage/login.tsx`、`P/pages/LoginPage/loginBridge.tsx` 使用安全编辑目标衔接自动 SSO 与手动重试。仅在协议已配置、初次导航且未尝试时自动授权；callback 或明确失败后显示失败并保留原目标，手动重试不取旧全局残留。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · _Acceptance: AC-01, AC-05, AC-07, AC-08_ · _Verification: V-01，B2-P_ · _Depends: T005_ · _Boundary: 不新增登录方式或放宽 return_to_

- [x] **T007** [Platform] 在 `P/controllers/request.ts` 将匹配入口的身份失败交回同一入口处理者。阻止旧第三方跳转、独立 reauthorize 或通用 401 导航抢占，同时保留失败 Promise、实际错误类型和非本入口行为。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-05, AC-07, AC-08, AC-10_ · _Verification: V-01，B2-P_ · _Depends: T006_ · _Boundary: 不吞错、不绕过 CSRF 或服务端身份确认_

- [x] **T008** [网关测试] 在 `G/src/test/java/com/dataelem/gateway/controller/KunlianSsoControllerTest.java` 先写 beginLogin 取得事务后失败、callback 已消费事务后取消／目录未就绪的页面回执用例。验证重试 URL 保留可信编辑或执行目标、属性正确转义，无可信事务时不采用 query／Referer／请求头提供的目标，不能变成站外跳转。
  - _Requirements: REQ-04, REQ-05_ · 覆盖 AC: AC-05, AC-07, AC-08
  - _Acceptance: AC-05, AC-07, AC-08_ · _Verification: V-01，B2-G_ · _Depends: 无_ · _Boundary: Mock ProtocolRuntime，不调用真实昆联_

- [x] **T009** [网关] 在 `G/src/main/java/com/dataelem/gateway/controller/KunlianSsoController.java` 仅将已验证事务目标保存在本次 exchange 内，并用于固定失败页的安全重试链接。保留事务消费、编码、HTML 转义、安全响应头和无可信目标时的固定页面。
  - _Requirements: REQ-04, REQ-05_ · _Acceptance: AC-05, AC-07, AC-08_ · _Verification: V-01，B2-G_ · _Depends: T008_ · _Boundary: 不改 OIDC 参数、凭据、回调登记或信任策略_

**B2 验收**：Platform 定向测试连同原管理页会话、退出及登录回跳用例执行一次；网关单独执行 controller tests。核对已有会话不授权、缺失会话只授权一次、有效失败事务可重试原目标、恶意或无可信目标不回显。网关环境缺失时 B2-G 记 `NOT_RUN`，不能用 Platform Mock 代替通过。

### W3 发布版本与后端授权

- [ ] **T010** [后端 Domain 测试] 在 `WT/test_kunlian_workflow_browser_publication.py` 先写 repository 及应用加载测试。复用隔离 SQLite 与权限替身，覆盖唯一当前上线图、V1→V2、发布图不一致、无当前版本、类型错误、删除／下线、缺 `use`、跨租户、权限不可确认。通过受控前后顺序验证选图边界，记录 SQLite 不证明真实行锁竞争。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05_ · 覆盖 AC: AC-02, AC-03, AC-04, AC-06
  - _Acceptance: AC-02, AC-03, AC-04, AC-06_ · _Verification: V-02，B3_ · _Depends: 无_ · _Boundary: 仅局部测试装配，不建生产表或迁移_

- [ ] **T011** [后端 Repository] 在 `B/workflow/domain/repositories/browser_publication.py` 实现事务内锁定 Flow 后读取唯一当前未删除版本，核验上线、类型、归属和图一致性并深拷贝快照。复用现有会话及租户过滤，不手工拼 tenant_id 过滤，不新增 DAO 入口。
  - _Requirements: REQ-03, REQ-04, REQ-05_ · _Acceptance: AC-03, AC-04, AC-06_ · _Verification: V-02，B3_ · _Depends: T010_ · _Boundary: 无新增 ORM、Schema、存储或历史迁移_

- [ ] **T012** [后端 Domain] 在 `B/workflow/application/browser_workflow_entry.py` 实现 `load_published_browser_snapshot(user, workflow_id)`：复用既有可信身份、资源适配和 F048 `use`，通过 T011 选择当前快照，返回 `{workflow_id, workflow_version_id, graph}`。不可用或不一致时拒绝，不能改选草稿或历史版。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05_ · _Acceptance: AC-02, AC-03, AC-04, AC-06_ · _Verification: V-02，B3_ · _Depends: T010, T011_ · _Boundary: 服务层不写 ORM，不提供新 HTTP 接口_

- [ ] **T013** [后端 API／运行测试] 在 `WT/test_kunlian_workflow_browser_entry.py` 先写 WS 装配、状态查询与新运行测试。复用 WorkflowClient、FakeRedis、任务派发替身及节点 runtime 替身，覆盖无运行零派发、用户明确初始化、陈旧浏览器图被忽略、连接对象／会话不可替换、空 chat ID 调试须编辑权、加载器缺失拒绝，以及节点准备换版后 abort 且不派发。对普通、Agent、知识库图分别核对冻结图；模拟 V2 发布后原运行／Worker 消费仍为 V1，不将队列替身称为真实队列验证。核对 ChatManager 非浏览器调用的默认装配兼容，v2／v3 和反向运行不被要求使用本次浏览器加载器。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-02, AC-03, AC-04, AC-06, AC-09
  - _Acceptance: AC-02, AC-03, AC-04, AC-06, AC-09_ · _Verification: V-02，B3_ · _Depends: T012_ · _Boundary: 保留服务端 headers → ContextVar 的租户传递，不新增 Worker 实现_

- [ ] **T014** [后端 API] 在 `B/api/v1/workflow.py`、`B/common/chat/manager.py` 将可信发布图加载器注入浏览器 WorkflowClient，绑定连接目标与会话。非空会话按发布运行检查 `use`，空会话画布调试核验 `edit`；保留 F118 WS 消息准入及平台节点适配器。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05_ · _Acceptance: AC-02, AC-03, AC-04, AC-06_ · _Verification: V-02，B3_ · _Depends: T013_ · _Boundary: 依赖由端点注入，common 层不导入业务 repository_

- [ ] **T015** [后端运行衔接] 在 `B/common/chat/clients/workflow_client.py` 补无运行时的只读状态通知；发布新运行仅调用 T014 注入的加载器并使用其快照，忽略客户端图及版本。拒绝消息替换连接目标或降级为调试，节点准入不一致时撤销本次未派发准备结果。恢复原运行继续读取原图，不重新选择当前版本。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-03, AC-04, AC-06, AC-09_ · _Verification: V-02，B3_ · _Depends: T013, T014_ · _Boundary: 复用原 Redis、队列、继续／取消／交互协议，不新增运行状态机_

**B3 验收**：联跑两个新测试文件及原 `test_workflow_auto_rerun_status.py`、`test_workflow_offline_input.py`、平台 Agent／知识库 entrypoint 相关用例。比较任务派发次数、实际冻结图、原运行恢复、拒绝前后运行事实及准备记录。覆盖“选图前下线拒绝、选图后发布 V2 不替换 V1”的受控顺序；真实锁、权限服务和队列留给 T029、T031。

### W4 执行页身份边界

- [ ] **T016** [Client 测试] 在 `C/routes/KunlianWorkflowEntryBoundary.test.tsx`、既有 `C/api/kunlianSession.test.ts` 先写边界用例。覆盖身份查询未完成、旧缓存用户、有效会话、首次未登录、callback 后失效、并发 401、HTTP 200 业务拒绝、依赖错误及协议未配置。断言未确认时业务布局、logout、历史请求和 WS 均不发生；授权与失败重试保留原目标。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-02, AC-05, AC-06, AC-07, AC-08, AC-09
  - _Acceptance: AC-02, AC-05, AC-06, AC-07, AC-08, AC-09_ · _Verification: V-01，B4_ · _Depends: T003, T007_ · _Boundary: 仅测试，身份与 OAuth 用隔离替身_

- [ ] **T017** [Client] 在 `C/hooks/AuthContext.tsx`、`C/api/kunlianWorkflowEntry.ts` 暴露既有当前用户查询的确认结果，并通过现有 request 封装读取 OAuth 配置。身份成功以前不能使用旧用户缓存作为确认；仅接受配置的精确昆联入口，错误保持可识别。
  - _Requirements: REQ-02, REQ-04, REQ-05_ · _Acceptance: AC-02, AC-05, AC-06, AC-07_ · _Verification: V-01，B4_ · _Depends: T016_ · _Boundary: 不建立第二份身份查询／状态，不新增 axios 客户端或 Recoil atom_

- [ ] **T018** [Client] 在 `C/routes/KunlianWorkflowEntryBoundary.tsx`、`C/routes/index.tsx` 实现条件边界，放在 AuthLayout 内、MainLayout 外。有效入口按查询确认结果和既有工作台资格进入 READY，其他路径保持原行为；失败或已尝试时展示手动重试，不挂载业务子树。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-05, AC-06, AC-07, AC-08, AC-09_ · _Verification: V-01，B4_ · _Depends: T017_ · _Boundary: 入口资格和 Workflow 使用权限分别判断，不要求编辑权_

- [ ] **T019** [Client] 在 `C/api/request.ts`、`C/utils/loginRedirect.ts` 协调匹配入口的身份失败，抑制旧自动 reauthorize／第三方导航与边界竞争；由边界及共享尝试规则处理首次授权和手动重试。成功、异常及 READY 后失效均保持同一原目标规则，非昆联入口不改。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-05, AC-07, AC-08, AC-09_ · _Verification: V-01，B4_ · _Depends: T018_ · _Boundary: 不吞拒绝，不放宽 return_to、CSRF 或 Cookie 规则_

- [ ] **T020** [共享三语文案] 在 `L/zh-Hans.json`、`L/en.json`、`L/ja.json` 同步补齐本入口必要的开始运行、登录及失败文案，优先使用既有共享键。通过现有生成器生成两端产物；错误码源文案仍归 api_errors，不手改生成文件。
  - _Requirements: REQ-02, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-07, AC-10_ · _Verification: V-01、V-04，B4_ · _Depends: T018_ · _Boundary: 同一文案的三语原子任务，不新建业务组件或修改语言基线_

**B4 验收**：运行 Client 新边界测试与现有 `kunlianSession`、`loginRedirect`、退出相关 Jest 用例，并核对三语生成与键一致性。断言已登录不再授权、未登录不先退出、失败不循环、旧残留不覆盖原目标；测试环境缺包时记录阻塞，不自动重装依赖。

### W5 执行直达与明确开始

- [ ] **T021** [Client 测试] 在 `C/pages/appChat/kunlianWorkflowEntry.test.tsx`、既有 `C/pages/appChat/workflowAutoRerun.test.ts` 写入口到会话、历史切换、新会话、刷新与恢复用例。记录 WS action 和新运行次数：打开／SSO／刷新只查状态，明确开始才初始化；不自动提交已有答案，不受分享页自动重跑配置影响。有使用权无编辑权可开始，无使用权或下线不能开始，普通入口原行为回归。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-02, AC-03, AC-04, AC-05, AC-06, AC-09, AC-10
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-09, AC-10_ · _Verification: V-01，B5_ · _Depends: T015, T019, T020_ · _Boundary: 前端测试 Mock 的版本事实不代替 B3 后端证据_

- [ ] **T022** [Client 导航] 在 `C/pages/appChat/AppChatEntry.tsx`、`C/routes/AppRoot.tsx` 使用共享构造工具保留校验后的昆联标记，区分 Router 内部路径和浏览器完整路径，继续采用现有最近会话选择。不同对象变化时清理旧页状态，不短暂显示上一对象数据。
  - _Requirements: REQ-02, REQ-04, REQ-06_ · _Acceptance: AC-02, AC-05, AC-06, AC-09_ · _Verification: V-01，B5_ · _Depends: T021_ · _Boundary: 不改变历史选择策略或给普通入口追加标记_

- [ ] **T023** [Client 导航] 在 `C/pages/appChat/ChatView.tsx`、`C/pages/appChat/hooks/useAppSidebar.ts` 补齐新建会话与侧栏历史切换的同一链接规则；只复制经过校验的入口标记，不复制凭据或任意 query，保持目标 Workflow 及会话一致。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-05, AC-06, AC-08, AC-09_ · _Verification: V-01，B5_ · _Depends: T022_ · _Boundary: 本任务只处理导航，手动开始展示由 T025 增量处理_

- [ ] **T024** [Client WS] 在 `C/pages/appChat/useWebsocket.ts` 为有效昆联入口启用状态查询优先：首次、刷新、重连只发 `check_status`，活动运行按既有机制恢复，空闲／完成只通知显示开始操作。仅用户明确操作发送初始化；响应未知先查状态，不自动重投开始或答案。关闭本入口的自动重跑分支，非昆联入口保留原行为。
  - _Requirements: REQ-02, REQ-03, REQ-06_ · _Acceptance: AC-02, AC-03, AC-04, AC-09, AC-10_ · _Verification: V-01，B5_ · _Depends: T015, T021_ · _Boundary: 复用原停止、文本表单、Agent 交互和运行恢复协议_

- [ ] **T025** [Client UI] 在 `C/pages/appChat/ChatView.tsx`、`C/pages/appChat/ChatInput.tsx` 衔接 T024 的空闲状态及开始操作。新会话明确显示“开始运行”，运行中禁用重复操作，完成后采用现有重新运行；按钮在空会话视图也可见，输入节点及结果使用现有组件，使用权撤销或目标不可用时显示拒绝。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-04, AC-06, AC-09, AC-10_ · _Verification: V-01，B5_ · _Depends: T020, T023, T024_ · _Boundary: 复用 @bisheng/ui、现有变量与表单，不重建执行页面_

**B5 验收**：联跑 Client 两个行为测试文件和已有交互／长任务状态相关用例，检查 WS action、派发与答案提交计数，以及按钮状态。无历史、已完成和活动运行分别验证；同一链接指向 V2 的后端事实复用 B3，不在前端另造一套版本判定。

### W6 浏览器闭环与交付草稿

- [ ] **T026** [E2E／浏览器 Mock] 在 `WT/f129_browser_mock.py` 仅建立本地隔离 HTTP／WS 测试装配，复用前序身份和发布事实夹具，模拟 OAuth 成功及失败、权限角色、普通 V1／V2 流程及派发计数。通过统一浏览器工具操作实际 Platform、Client 页面，验证两个直达链接、SSO 目标、手动重试、未保存返回、执行开始、文本输入、刷新和原运行恢复；将启动方式、步骤、截图及计数写入 `F/verification.md`。本地用空闲回环端口，不占用用户现有服务或连接测试服务器。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10_ · _Verification: V-01、V-02，B6_ · _Depends: T007, T009, T015, T025_ · _Boundary: Mock 验证不标为真实昆联 SSO、真实锁或实际队列通过_

- [ ] **T027** [交付文档] 在 `docs/architecture/proposals/昆联Workflow编辑与执行页面接入说明.md` 编写可发给昆联的简洁说明：两条模板、Workflow ID 含义、完整示例、实际用户及权限／发布条件、首次登录回跳和失败重试。当前未部署联验的实际站点示例明确写待验证，最终由 T030、T031 回填已验证示例；不放本地 Mock 地址、内部任务号或多余回执模板。同步 `F/verification.md` 中的实现、Mock、构建及待执行状态。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-07_ · _Acceptance: AC-01, AC-02, AC-05, AC-10_ · _Verification: V-04，B6_ · _Depends: T026_ · _Boundary: 交付草稿不等于真实链接已验收_

**B6 验收**：在同一代码状态执行一次相关回归、两端生产构建和必要静态检查，然后完成一次隔离浏览器闭环。保存两端所观察到的导航、权限拒绝、WebSocket 消息与派发计数，确认不依赖 Vite 专属资源。真实 SSO、FGA、锁与队列仍为待执行；此前批次有效证据可直接引用。

## 4. 真实环境任务：当前待确认／待执行

- [ ] **T028** [双方登记条件] 在 `F/design.md`、`F/verification.md` 回填 `TODO [F129]` 的最终浏览器 Origin、两个按钮完整 URL、对象 ID、测试身份、回调及允许前缀。继续使用 3001 的约定，不假设内网地址已对昆联浏览器可达。当前 `WAITING_EXTERNAL`；不要求新增昆联 Agent 或其他业务接口。
  - _Requirements: REQ-04, REQ-05, REQ-07_ · _Acceptance: AC-05, AC-07, AC-08, AC-10_ · _Verification: V-03、V-04 准备_ · _Depends: T027_ · _Boundary: 仅外部条件确认，不改信任策略或自动部署_

- [ ] **T029** [真实数据库／权限验证] 在 `F/verification.md` 记录受控 MySQL／DM8 和 OpenFGA 的发布读取、当前版本切换、并发下线／发布、权限拒绝和撤权验证。用编辑者、使用者、无权者及其他租户核对实际结果；检查选图前下线拒绝、选图后原快照保持。当前 `NOT_RUN`，待执行，不用 SQLite 模拟替代。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-06
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-06_ · _Verification: V-02、V-03_ · _Depends: T027_ · _Boundary: 需受控数据、账号和环境使用授权，不安装或迁移生产数据库_

- [ ] **T030** [真实昆联 SSO 验证] 在 `F/verification.md` 及对外接入说明记录从昆联两个按钮到目标页面的实际结果：有效会话、首次登录、编辑与使用权限分离、取消、目录未就绪、callback 后仍失败、手动重试和跨租户拒绝。当前 `NOT_RUN`，待执行；本地管理员直达不能替代该验收。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-10
  - _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-10_ · _Verification: V-03、V-04_ · _Depends: T028, T029_ · _Boundary: 新版本部署及测试账号使用须已另获授权，本任务不自行部署_

- [ ] **T031** [3001 静态入口与实际运行验证] 在已另行授权并完成部署的环境，从昆联打开实际页面，直接刷新编辑及执行深层路由。核对 HTML、静态资源、REST／WS，验证空闲零派发、用户明确开始后的文本输入和结果、V1 原运行在 V2 发布后恢复、新运行使用 V2；核对实际队列及 Worker，回填对外已验证示例及 `F/verification.md`。当前 `NOT_RUN`，待执行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-09, AC-10
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-09, AC-10_ · _Verification: V-03、V-04_ · _Depends: T030_ · _Boundary: 保留静态目录映射及 3001，不新增端口，不将 Mock 派发计数当真实运行结果_

外部 `TODO` 仅用于待双方确认和真实环境条件，不能用来延后 T001 至 T027 中已确认的功能。部署不是本轮授权，也不是自动执行的隐含任务。

## 5. 验证命令与证据记录

以下为实施期命令计划，**本轮没有执行业务测试或构建**。命令来源是各项目现有 package scripts、测试配置和 AGENTS；新增测试文件名按上述任务确定。先核对实际解释器、Node、pnpm 和 Java／Maven 环境，不使用会自动同步依赖的命令修复环境。

| 证据 | 计划命令／操作 | 结果要求 |
| --- | --- | --- |
| B1 | `src/frontend/`：`pnpm --filter @bisheng/api-client test -- src/kunlianWorkflowEntry.test.ts`，共享包类型检查。 | 解析、安全及尝试状态通过。 |
| B2-P | `src/frontend/`：Platform Vitest 运行 `kunlianWorkflowEntry.test.tsx`、`controllers/kunlianSession.test.ts` 及既有退出、管理列表／创建表单回归，单 Worker。 | 编辑目标、拒绝和登录回跳通过。 |
| B2-G | `G/`：`mvn -Dtest=KunlianSsoControllerTest test`。 | Mock controller 通过；无环境则 `NOT_RUN` 并保留原因。 |
| B3 | `src/backend/`：使用已确认的隔离测试配置，`.venv/bin/python -m pytest test/workflow/test_kunlian_workflow_browser_publication.py test/workflow/test_kunlian_workflow_browser_entry.py test/workflow/test_workflow_auto_rerun_status.py test/workflow/test_workflow_offline_input.py -q`，补受影响的平台节点 entrypoint 回归。 | 断言实际冻结图、身份／租户、派发与准备回滚；测试配置不得指向部署数据。 |
| B4、B5 | `src/frontend/`：`pnpm --filter bishengchat test:ci --runInBand --coverage=false --runTestsByPath <本批测试路径>`。按批选择新入口、kunlianSession、loginRedirect、退出及 workflowAutoRerun 用例。 | 单一 Jest 层主验行为；不为同一状态重复造第二套测试。 |
| B6 | `src/frontend/`：`pnpm build:platform`、`pnpm build:client`；按已有前端质量门执行 `pnpm lint`、`pnpm typecheck`、`pnpm locales:check`、`pnpm check-i18n`；后端定向 Ruff／架构守卫及 `git diff --check`。 | 生产构建及相关质量门通过；既有告警、失败及环境缺口单独记录，不修改基线掩盖。 |
| 浏览器 | 使用统一浏览器工具打开本地隔离 Mock 站点并执行 T026；真实站点仅在 T030、T031 条件满足后访问。 | 界面、原目标及后端可观察副作用一致，保存截图及相关统计。 |

`verification.md` 按证据记录代码状态、命令／步骤、退出码、结果、覆盖 AC、跳过原因和真实／Mock 类别。测试失败先修复对应行为再复验；没有执行证据不能勾选完成。任务批次、AC 和验证方法允许引用同一有效证据，不机械重复运行。

## 6. 追溯与完成口径

| 规格验收 | 主要测试任务 | 真实补充 |
| --- | --- | --- |
| AC-01 | T004、T026 | T029、T030、T031 |
| AC-02 | T010、T013、T016、T021、T026 | T029、T030、T031 |
| AC-03 | T010、T013、T021、T026 | T029、T031 |
| AC-04 | T010、T013、T021、T026 | T029、T031 |
| AC-05 | T001、T004、T008、T016、T021、T026 | T030 |
| AC-06 | T004、T010、T013、T016、T021、T026 | T029、T030 |
| AC-07 | T001、T004、T008、T016、T026 | T030 |
| AC-08 | T001、T004、T008、T016、T026 | T030 |
| AC-09 | T001、T013、T016、T021、T026 | T031 |
| AC-10 | T004、T021、T026；T027 文档核对 | T030、T031 回填真实示例 |

Mock 任务完成只能报告本地实现与隔离验证完成；不能报告真实 SSO、双方入口或正式运行已交付。全部 31 项完成前，不将整个特性标记为完成。

## 7. 实际偏差记录

任务拆分时无设计偏差。实施期如出现已确认范围内的细节调整，在此记录任务与 design 章节指针；推翻已确认规格／设计时先停止并重新确认。
