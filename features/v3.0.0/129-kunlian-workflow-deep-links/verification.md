# F129 实施与验证记录

**Date**: 2026-11-11
**范围**: 已完成 T001–T009 的本地实现与 Mock，即共享规则、Platform 编辑入口及网关可信事务重试。后续经用户授权，已部署本批运行代码并完成管理员编辑侧冒烟，见第 8 节。本特性仍为 `IN_PROGRESS`，9 / 27 项本地任务完成；Client、后端发布图及完整特性验收待后续任务，未运行真实工作流。

## 1. W1 代码状态与实际改动（历史证据）

基线为 `5be98459b3` 加当前工作区。保留了此前的卡片样式、部署记录及其他会话的联调文档改动，没有暂存、提交、推送、改依赖或改服务器。

| 文件 | 本批结果 |
| --- | --- |
| `src/frontend/packages/api-client/src/kunlianWorkflowEntry.ts` | 严格解析及构造编辑／执行／会话路径；保留失败原因并清理重试目标中的错误参数；尝试记录与手动恢复。不包含 HTTP、导航、Cookie 或权限授予。 |
| `src/frontend/packages/api-client/src/index.ts` | 导出工具、类型、Storage 端口及尝试键／10 分钟时限。 |
| `src/frontend/packages/api-client/src/kunlianBrowser.ts` | 增加只读 `isCallbackEntry()`，保留该实例创建时是否来自回调；不更改来源确认、CSRF、退出及原状态重置语义。 |
| `src/frontend/packages/api-client/src/kunlianWorkflowEntry.test.ts` | 保留并合并并发测试修改，最终 64 项参数化测试覆盖本批共享合同。 |

最终相关代码指纹为 `91810c25b8ec6a146c358a3e8bc43c4a4245118b5550e73b25de6180a649992e`。计算顺序是上表四个代码文件按 `index.ts`、`kunlianBrowser.ts`、`kunlianWorkflowEntry.test.ts`、`kunlianWorkflowEntry.ts` 排列；逐项向 SHA256 写入仓库相对路径加换行、文件内容、换行。下述最终通过证据对应此代码状态；文档更新不改变该指纹。

## 2. 环境与命令

最终验证使用已有 Node `v24.14.0`、pnpm `9.15.9` 缓存、Vitest `3.2.7` 和现有依赖，无安装或重建依赖。共享包测试为 Node 环境，Storage、时钟、location、history、身份提示及网络均使用局部替身。

在 `src/frontend/` 中执行以下命令。为避免当前 shell 在该目录选用旧 Node 或全局 pnpm 10，使用命令级 Node 路径和缓存中的 pnpm，不改项目或用户运行配置：

```bash
TASK_NODE=/Users/wenruli/.nvm/versions/node/v24.14.0/bin/node
TASK_PNPM=/Users/wenruli/.cache/node/corepack/v1/pnpm/9.15.9/bin/pnpm.cjs
export PATH="$(dirname "$TASK_NODE"):$PATH"

"$TASK_NODE" "$TASK_PNPM" --filter @bisheng/api-client test
"$TASK_NODE" "$TASK_PNPM" --filter @bisheng/api-client typecheck
"$TASK_NODE" "$TASK_PNPM" --filter @bisheng/api-client lint

"$TASK_NODE" "$TASK_PNPM" --filter bisheng exec vitest run \
  src/controllers/kunlianSession.test.ts src/test/kunlianLogout.test.tsx \
  --maxWorkers=1 --minWorkers=1

"$TASK_NODE" "$TASK_PNPM" --filter bishengchat test:ci \
  --runInBand --coverage=false --runTestsByPath \
  src/api/kunlianSession.test.ts src/hooks/kunlianLogout.test.tsx \
  src/utils/loginRedirect.test.ts

"$TASK_NODE" "$TASK_PNPM" typecheck
"$TASK_NODE" "$TASK_PNPM" lint
```

架构守卫在仓库根目录针对本批四个代码文件逐个执行 `bash scripts/arch-guard.sh <file>`；差异检查使用 `git diff --check`。

## 3. 执行证据

| Evidence | 实际执行／阶段 | 结果与范围 |
| --- | --- | --- |
| E-001 | 修改前共享包 `test`。 | `PASS`，19 项，退出 0。该次 shell 选择 Node 20.13.1，出现引擎版本警告；最终回归已用显式 Node 24 路径重新验证，不以旧环境作为最终通过依据。 |
| E-002 | T001 测试先行；新增模块前运行新测试，完成 T002 后再运行。 | 新模块尚不存在时测试收集按预期失败；T002 后 51 项通过、2 项 callback 访问器缺失失败，证明 T003 尚未实现。此为开发过程红灯，非最终结果。 |
| E-003 | 保留并合并并发改动后，最终共享包全部测试。 | `PASS`，83 项，退出 0：新增共享规则 64 项，原 API 错误合同 19 项。 |
| E-004 | 最终 Platform 现有昆联会话、CSRF 和退出相关回归。 | `PASS`，26 项，退出 0：`kunlianSession` 14 项、`kunlianLogout` 12 项；保留 React Router 的既有 future-flag 提示。未接入新页面，不代表编辑／执行入口已完成。 |
| E-005 | 最终共享包 typecheck、lint，四文件架构守卫和差异检查。 | `PASS`，均退出 0，守卫无输出。 |
| E-006 | 最终全前端 `pnpm typecheck`。 | `PASS`，退出 0；Platform、Client、file-viewers、chat、api-client 的既有类型质量门通过。 |
| E-007 | Client 三个既有 Jest 回归文件。 | `BLOCKED_ENV`，退出 1，3 个 suite 在 jsdom 初始化时失败，0 项业务测试运行：缺少 `canvas/build/Release/canvas.node`。未安装、重编译或移除依赖，不能将此记为 Client 回归通过。 |
| E-008 | 全前端 `pnpm lint`。 | `FAIL`，退出 2：Platform 提示抑制清单有已失效项（`There are suppressions left that do not occur anymore`）。本批未修改该清单或基线；全局 lint 门禁仍未关闭，不能用共享包 lint 通过替代。日志为本机 `/tmp/f129-frontend-lint.log`。 |

Node／pnpm 输出保留 DEP0169 的既有 `url.parse()` 弃用警告，没有据此修改依赖。全前端最终类型日志位于本机 `/tmp/f129-frontend-typecheck-final.log`。

## 4. 并发修改的处理

初轮共享包 74 项、Platform 26 项通过后，共享测试文件于 11:56:18 被其他操作替换，出现 `callback`、`isCallbackEntry()` 及其他导出与本批初版不匹配的类型错误。发现后暂停覆盖并保存当时四个文件到本机 `/var/folders/06/935ggv0j2259kmb0t_3nvhpc0000gn/T/f129-concurrent-snapshot-Vbfogy`。

用户随后确认由本会话接管，保留并合并当前修改。已向另一会话明确本批代码／测试及任务状态的写入边界，保留其无关联调文档任务。最终以当前测试接口统一实现，补齐未知 callback 阶段、损坏／未来记录阻断自动授权、读取／写入／清理失败及不同 Workflow 保护。初轮通过和并发期间的类型失败仅作历史记录，最终状态以 E-003 至 E-006 为准。

该合并未改变已确认需求：尝试状态仍不授予身份；损坏记录只要求手动恢复，成功后按 Workflow＋动作清理记录，包括入口跳到会话后的同目标清理。

## 5. 任务级审查与完成口径

按项目 task-review 检查 T001、T002、T003。结果为 `PASS_WITH_NOTES`：本批功能及配对测试通过，Client 测试环境和全局 lint 问题见 E-007、E-008，未对这两项做范围外修复。

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 文件与命名 | `PASS` | 代码限共享包四文件；新工具、类型及访问器明确导出，无页面或网关接线。 |
| 分层、序列化、数据库 | `N/A` | 本批无后端、ORM、Schema、Worker 或公共 HTTP 变更。 |
| 前端约定 | `PASS` | TypeScript、无新库／store／网络封装，新文件均小于 600 行；遵循最近层前端规则使用英文代码注释。 |
| 信息边界 | `PASS` | 固定错误标识、不回显输入；记录只有 kind、Workflow ID、规范化目标和时间，不写身份或业务权限。 |
| 设计同步 | `PASS` | design §4.1、§4.6 已写明 W1 实际合同及尚未接入部分。 |
| 配对测试、依赖及状态 | `PASS` | T001 测试先行，T002、T003 共用最终共享包证据；只勾选本批三项。 |

T001、T002、T003 完成的是共享规则和阶段信息，**不能据此宣称两个页面直达、SSO 回跳或当前上线版本执行已经交付**。

## 6. 验收覆盖及未执行项（更新至 W2）

| 规格验收 | 已有共享层证据 | 页面／运行完整验收 |
| --- | --- | --- |
| AC-05 | E-003、E-011：编辑原目标、当前身份确认及首次单次授权；E-012：网关两种目标的安全重试。 | 编辑侧局部 Mock 已通过；Client 与真实 SSO 回跳 `NOT_RUN`。 |
| AC-07 | E-003、E-011：callback、目录／依赖失败、存储禁用时停止自动授权并允许手动；E-012：有效失败事务重试与重放拒绝。 | W2／B2-P、B2-G `PASS`；两端浏览器及真实联验 `NOT_RUN`。 |
| AC-08 | E-003、E-011：非法参数在历史 URL-token 导入及身份请求前拒绝；E-012：拒绝站外目标，不采用 query／Referer／请求头。 | 当前早期校验与网关 Mock 已通过；服务端授权完整验收 `NOT_RUN`。 |
| AC-09 | E-003：共享工具没有请求、导航、Cookie 或身份写入副作用。 | `NOT_RUN`，尚未验证 WS／队列零派发、人工答案及运行恢复。 |
| AC-01、AC-06 | E-011：已有会话不授权、入口资格拒绝、保留管理来源；沿用原管理编辑详情接口，不放宽对象权限。 | 实际画布、对象 edit／跨租户与真实权限服务闭环 `NOT_RUN`。 |
| AC-02、AC-03、AC-04、AC-10 | E-011 仅覆盖相关旧登录、会话、退出及创建接口头兼容，不承担执行与完整交付闭环。 | `NOT_RUN`，待后续任务。 |

| 后续范围 | 状态 | 完成条件 |
| --- | --- | --- |
| T004–T009 | `PASS`（本地／Mock） | B2-P 63 项、B2-G 12 项通过，见下节。 |
| T010–T027 | `NOT_STARTED` | Client、后端及完整 Mock 浏览器闭环按任务依赖实施；本轮未扩大范围。 |
| T028 双方登记 | `WAITING_EXTERNAL` | 最终 Origin、按钮参数、回调及受控账号确认；设计中的外部 `TODO [F129]` 保留。 |
| T029 真实数据库与 OpenFGA | `NOT_RUN` | 受控环境、数据及使用授权，验证实际锁与权限事实。 |
| T030 真实昆联 SSO | `NOT_RUN` | 正式回调、用户目录准入及两类入口可联验。 |
| T031 静态入口与实际队列运行 | `NOT_RUN`（完整验收） | 已完成第 8 节的编辑侧部署冒烟；执行入口、固定快照和真实队列仍待实施及验收。 |

以上 W1／W2 本地实施阶段没有部署；随后授权的构建与部署见第 8 节。未执行真实昆联登录、用户同步、数据库变更或业务 Workflow，未推送 Git。

## 7. W2：T004–T009 实施与验证

### 7.1 改动及代码状态

毕昇基线 `5be98459b3`；网关基线 `38f3a876`。继续保留无关样式、三语文案、部署文档和其他会话的联调访问文档；本批没有暂存、提交、推送、部署、改依赖或运行配置。

| 仓库／文件 | 已实施内容 |
| --- | --- |
| Platform `utils/workflowManagement.ts`、`contexts/userContext.tsx` | 精确编辑入口与 basename 识别；非法标记入口在历史 token 导入前拒绝。当前用户查询和既有入口资格继续复用；清理旧全局回跳，成功后清理当前尝试，失败交回登录页。 |
| Platform `pages/LoginPage/login.tsx`、`loginBridge.tsx` | 配置精确协议后才允许首次自动授权；callback、明确失败、目录／依赖错误、已尝试和存储禁用保持手动。手动重试只用规范化原目标，失败文案复用现有三语键。 |
| Platform `controllers/request.ts` | 新入口的普通 401、严格匹配的昆联拒绝，以及 HTTP 200 业务拒绝均保持原始错误并交给同一页面处理，不独立导航。后续身份失败通过本地事件关闭业务子树；CSRF、退出和非本入口保留原处理。 |
| Platform `test/kunlianWorkflowEntry.test.tsx`、`controllers/kunlianSession.test.ts` | 页面／Provider 与真实请求封装的隔离 Mock：既有会话、首次／并发／回调失败、旧目标残留、输入拒绝、入口权限及后续拒绝。 |
| Gateway `KunlianSsoController.java` | beginLogin 取得验证事务或 callback 消费事务后，才在本次 exchange 保存目标；失败页重试链接执行 URL 编码与 HTML 转义。未放宽允许回跳规则。 |
| Gateway `KunlianSsoControllerTest.java` | 使用真实本地事务存储和 Mock OIDC／Identity，验证失败重试、点击重试后相同目标、消费重放、属性安全及无可信事务时固定安全页。 |

W1 共享四文件指纹仍为 `91810c25b8ec6a146c358a3e8bc43c4a4245118b5550e73b25de6180a649992e`，复用 E-003，无需重复跑相同共享包测试。W2 最终指纹：

- Platform：`7448264d53d2791c9d7e0631c7a4f37e17ca0baff5687708e8972099b99f2257`。以 `src/frontend/platform/src/` 为前缀，顺序为 `contexts/userContext.tsx`、`controllers/kunlianSession.test.ts`、`controllers/request.ts`、`pages/LoginPage/login.tsx`、`pages/LoginPage/loginBridge.tsx`、`test/kunlianWorkflowEntry.test.tsx`、`utils/workflowManagement.ts`。
- Gateway：`82f36258e9c3609631420587f03df566db6bb3f4012b60dc3e193ceb564ff282`。顺序为仓库相对路径 `src/main/java/com/dataelem/gateway/controller/KunlianSsoController.java`、`src/test/java/com/dataelem/gateway/controller/KunlianSsoControllerTest.java`。

计算方法与 W1 一致：逐文件写入相对路径＋换行、原始内容＋换行，计算 SHA256。代码指纹清单为本机 `/tmp/f129-w2-fingerprints.json`，最终证据对应此状态。

### 7.2 实际命令

前端继续使用第 2 节的已有 Node 24／pnpm 9 缓存，在 `src/frontend/` 执行：

```bash
"$TASK_NODE" "$TASK_PNPM" --filter bisheng exec vitest run \
  src/test/kunlianWorkflowEntry.test.tsx \
  src/controllers/kunlianSession.test.ts \
  src/test/kunlianLogout.test.tsx \
  src/controllers/requestErrors.test.ts \
  src/controllers/requestCompatibilityMatrix.test.ts \
  src/controllers/requestSessionFailure.test.ts \
  src/controllers/API/workflow.test.ts \
  --maxWorkers=1 --minWorkers=1

"$TASK_NODE" "$TASK_PNPM" typecheck

"$TASK_NODE" "$TASK_PNPM" --filter bisheng exec eslint \
  src/test/kunlianWorkflowEntry.test.tsx src/controllers/kunlianSession.test.ts \
  src/utils/workflowManagement.ts src/contexts/userContext.tsx \
  src/controllers/request.ts src/pages/LoginPage/login.tsx \
  src/pages/LoginPage/loginBridge.tsx \
  --suppressions-location eslint-suppressions.json --pass-on-unpruned-suppressions

"$TASK_NODE" "$TASK_PNPM" lint
```

网关在其独立仓库执行（使用已有 Java 17，不使用默认 Maven 选择的 Java 25）：

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
  mvn -Dtest=KunlianSsoControllerTest test
```

毕昇七个本批代码／测试文件分别执行 `bash scripts/arch-guard.sh <file>`，两个仓库执行 `git diff --check`。前端新文件无 TypeScript 严格模式忽略标记；没有扩充或手工修改 lint 抑制基线。

### 7.3 证据与任务级审查

| Evidence | 执行阶段／命令 | 结果及边界 |
| --- | --- | --- |
| E-009 | Platform 测试先行，未接入页面时运行新页面与会话用例。 | 预期红灯：15 failed、15 passed，Vitest 退出 1；复现缺少目标处理、重复跳转、非法输入与后续身份拒绝未交回页面。历史日志 `/tmp/f129-w2-platform-red.log`。 |
| E-010 | Gateway 测试先行，未修改 controller 时执行定向测试。 | 2 项可信目标重试断言失败，另有 1 项 Mock 重设触发空参数的夹具错误；夹具改用 `doReturn`，未据此记业务通过。历史日志 `/tmp/f129-w2-gateway-red.log`。 |
| E-011 | 最终 Platform 七文件相关回归，12:31。 | `PASS`，63 项、7 个文件、退出 0：新入口 17、会话 17、退出 12、错误合同 6、兼容矩阵 6、踢下线 1、Workflow API 4。日志 `/tmp/f129-w2-platform-final.log`；只有既有 Router future-flag 提示，没有 act 警告。 |
| E-012 | 最终 Gateway controller 测试，12:31。 | `PASS`，12 项，Failures 0、Errors 0、Skipped 0，退出 0；包括编辑和执行目标的错误页重试链接及实际跟随后的事务目标。日志 `/tmp/f129-w2-gateway-final.log`。仅本地 WebTestClient／Mock，不是实际昆联或 Redis 验收。 |
| E-013 | 最终全前端 typecheck。 | `PASS`，退出 0，Platform、Client 及共享包通过；日志 `/tmp/f129-w2-typecheck-final.log`。 |
| E-014 | 本批七文件定向 ESLint。 | `PASS`，退出 0。`--pass-on-unpruned-suppressions` 仅允许无关旧抑制项未清理，不关闭实际规则；未新增抑制记录。日志 `/tmp/f129-w2-lint-final.log`。 |
| E-015 | 七文件架构守卫及两个仓库差异检查。 | `PASS`，退出 0，无守卫输出；文档更新后再次检查差异与任务状态。 |
| E-016 | 全前端 `pnpm lint`。 | `FAIL`，退出 2，仍是 Platform 的失效抑制记录：`There are suppressions left that do not occur anymore`。与 E-008 同类，未扩展本批去修改全仓基线；全局 lint 门禁未关闭。日志 `/tmp/f129-w2-full-lint.log`。 |

T004–T009 任务级审查结果：`PASS_WITH_NOTES`。配对测试先行，六项任务的文件、依赖和验收出口一致；无数据库、后端权限 Owner、OIDC 凭据或协议合同变更。入口标记不授予身份或对象权限，错误不回显上游正文，事务目标不从请求头／回调 query 获取。W2 的 design 同步已完成；全局 lint 的已知阻塞作为门禁备注保留。

### 7.4 未执行与下一批

- T010–T027 尚未实施，包括后端当前发布快照、Client 执行边界及两端真实页面的隔离浏览器闭环；本批以 Provider／LoginPage 组件 Mock、请求适配器和网关 WebTestClient 验证，不能替代真实画布／对象权限验收。
- T028 外部登记继续 `WAITING_EXTERNAL`；T029–T031 继续 `NOT_RUN`，包括实际 MySQL／DM8、OpenFGA、昆联 SSO、部署后深层路径及真实队列运行。
- Client Jest 在 E-007 记录的 canvas 环境限制未处理；本批未改 Client 行为，也未把其类型检查当成业务测试通过。
- 保留正式接口及联调配置的现有 `TODO [F129]`。上述 W2 本地实施阶段没有安装依赖、调整配置、构建发布产物、连接服务器或部署；随后授权的部署见第 8 节。

## 8. 后续授权：服务器更新与部署冒烟

用户随后要求更新到服务器，已于 2026-11-11 12:53:57 切换 `20261111-f129-1247`。完整路径、构建校验、回退方法及边界见 [部署记录](./deployment-20261111.md)。没有因此勾选尚未开发的任务或把真实 SSO 验收改为完成。

| Evidence | 实际操作 | 结果及边界 |
| --- | --- | --- |
| E-017 | 源码、JAR 及静态产物校验与构建。 | `PASS`，8 个运行源码文件与本地校验一致；Platform 48.52 秒、Client 1 分 24 秒构建成功；813 个文件校验通过。新 JAR 本地／服务器／运行容器 SHA256 相同。构建插件下载失败经校验补缓存后成功，不改依赖声明。 |
| E-018 | Compose、配置保持、切换与运行检查。 | `PASS`，配置和 Nginx 检查通过；新网关完整环境变量、基础镜像及网络与原容器相同，原配置／License 挂载保留；API、Worker、Nginx 容器 ID 和启动时间一致。Nginx 仅重载配置，网关重建，回退脚本 `sh -n` 通过但未执行回退演练。 |
| E-019 | Chrome 使用既有 admin 会话验证管理页、标记编辑链接、刷新及画布返回。 | `PASS`，Test v0 画布打开，目标不变；返回时保留未保存提醒，选择“不保存”后回到管理页。Client 普通入口加载，两个标签未观察到 error 日志。没有创建、保存、发布或运行 Workflow。 |
| E-020 | 服务器 HTTP 与实际昆联登录配置探针。 | 管理页、编辑路由、Client 及两端 env API 返回 200。登录方式列表为空，授权入口返回 503／`DEPENDENCY_UNAVAILABLE`；**真实 SSO 为 `NOT_RUN`，不记为通过**。权限矩阵与完整执行入口／队列验证仍待执行。 |

服务器备份、构建日志和核验数据保存在 `/dataelem/bisheng-kunlian/source/backups/20261111-f129-1247` 及前端 `.static-builds/20261111-f129-1247/`。网关 JAR 通过只读目录映射运行；3001 端口不变，未新增对外端口、数据库对象、凭据或安全策略。
