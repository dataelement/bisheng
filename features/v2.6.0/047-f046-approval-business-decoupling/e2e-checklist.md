# E2E 验证清单：F045/F046 审批与业务执行状态分离

**Feature**: F047（覆盖 F045、F046 Client 回归）
**Client**: `http://localhost:4001/workspace`
**审批中心入口**: Client 顶部审批中心
**数据前缀**: `e2e-f047-<run-id>-`（空间、频道、目录、文件和测试用户均使用此前缀）

> 本清单不保存账号密码。使用专用测试租户，开始前与结束后均只清理本轮前缀数据。页面人工项未勾选前，不得把自动化测试通过等同于页面验收通过。

## 1. 环境与账号

### 1.1 运行条件

- [ ] Backend、Client、MySQL/DM8、Redis、MinIO、OpenFGA、Elasticsearch、Milvus 可用，记录构建 SHA。
- [ ] default Celery worker、`knowledge_celery` worker 和 Beat 均运行；`resource_user_invite_confirmation`、`knowledge_space_file_change_request` 场景已启用。
- [ ] 准备租户 A 的资源 owner/manager、普通成员、被邀请用户、文件变更申请人；准备租户 B 用户做隔离对照。
- [ ] 准备可正常生效和可稳定触发业务执行失败的 F045 授权、F046 文件各一组。
- [ ] 开始前清理遗留的 `e2e-f047-<run-id>-` 测试数据；测试后再次按相同前缀清理，禁止宽范围删除。

### 1.2 验收证据

- [ ] 每组写操作后均刷新页面或重新 GET，截图记录服务端最终状态；toast、HTTP 200 或 Celery task id 不能单独作为业务完成证据。
- [ ] 打开浏览器 Network 与 Console；记录失败请求的响应码、业务错误码和 request id，确认无新增 console error。
- [ ] 分别保存审批中心、F045 权限列表、F046 文件页的终态截图，截图中不包含密码、token 或内部对象地址。

## 2. F045：个人用户邀请待生效与业务重试（AC-19）

### 2.1 待生效邀请属于 Permission

- [ ] 以资源 owner/manager 在知识空间设置中新增 `e2e-f047-<run-id>-invitee` 个人用户；同时新增部门或用户组作为 direct 对照。
- [ ] 预期：个人用户只显示“待生效/邀请已发送”，审批前没有有效 OpenFGA 授权；部门或用户组仍直接生效。
- [ ] 刷新权限列表，预期待生效行仍存在，资源、目标用户、首次角色快照正确；列表不依赖审批 payload 拼装。
- [ ] 待生效个人用户不可按 active 用户直接修改或移除；已有 active 用户的改角色/移除仍保持 direct 语义。
- [ ] 被邀请人拒绝，或邀请人撤回/取消后刷新列表，预期原待生效记录关闭且无有效授权；按产品规则可重新邀请。

### 2.2 审批终态与授权执行分离

- [ ] 被邀请用户本人同意，立即打开审批中心，预期只显示审批已通过和安全快照，不把尚未完成的授权显示为审批执行中/执行失败。
- [ ] 在 Permission 待生效列表观察原申请从排队/执行到已生效；最终刷新并验证只出现一组有效授权与 relation binding。
- [ ] 模拟授权执行失败，预期审批中心仍为“已通过”，业务列表显示原邀请失败及业务重试入口，失败原因不泄漏内部 token/tuple。
- [ ] 点击业务重试，预期复用原业务 request 和原 approval instance，不新建审批任务；刷新后状态回到排队/执行，成功后变 active。
- [ ] 连续点击或在响应丢失后重试，预期不重复创建授权、成员行、审批实例或待办。

## 3. F046：文件页六种业务状态与独立审批状态（AC-24）

### 3.1 六状态展示

- [ ] 在知识空间文件页依次构造并观察 `queued`、`applying`、`applied`、`failed`、`compensating`、`closed` 六种业务状态。
- [ ] 预期：页面分别显示“等待执行/执行中/已生效/执行失败/补偿中/已关闭”的当前语言文案，不出现旧词 `executing`、`executed`、`execute_failed`、`parsing`、`parse_failed`、`published`。
- [ ] 对仍待审批与已审批但待执行的两条申请比较：两者业务状态均可为 `queued`，但 `approval_status` 分别为 pending、approved。
- [ ] 审批 approved 后、Knowledge 尚未 applied 前刷新详情和列表，预期仍显示 approved + queued/applying，不伪装为已生效。
- [ ] Knowledge 执行失败后刷新，预期显示 approved + failed，不把审批状态回退成异常或待处理。
- [ ] 普通无审批详情权限的成员只看到其有权看到的正式资源，不看到申请人、失败原因、暂存对象或内部步骤。

### 3.2 原申请重试、补偿与清理

- [ ] `failed` 详情显示业务重试按钮；其他五种状态不显示重试按钮。
- [ ] 点击重试后刷新，预期复用原 Knowledge request 与 approval instance，使用新的 Knowledge execution token；审批中心不新增实例或待办，审批终态不变。
- [ ] 模拟重试请求响应丢失后再次点击，预期同一阶段副作用不重复，最终状态由权威业务读结果决定。
- [ ] 触发部分副作用后的补偿，预期状态为 `compensating`；未确认补偿完成前不得显示 `closed` 或 `applied`。
- [ ] 清理失败记录：清理成功后重新 GET 为 `closed` 且临时对象已删除；清理失败时保持原业务状态并允许再次清理。
- [ ] `closed` 详情不再显示清理按钮；清理和重试均不改变 Approval 的 approved/rejected/withdrawn/cancelled 事实。
- [ ] 上传或变更在 `applied` 前不进入正式文件列表、搜索、RAG、引用或预览；只有全部发布门禁验证完成才可见。

## 4. 审批中心只展示审批事实（AC-05）

- [ ] 分别打开一条 F045 和一条 F046 待办/已处理记录，确认展示申请人、资源、动作、审批流程、意见、时间线和允许公开的提交快照。
- [ ] F045 只展示资源类型、资源名称、被邀请用户和角色；不展示内部 user/resource/model id、角色指纹或授权 tuple。
- [ ] F046 只展示文件/目录名称、动作和相对路径；不展示 request/outbox id、execution token、内部对象地址或结构体原文。
- [ ] 即使业务正在执行或已失败，审批中心也不显示业务状态、失败详情、业务重试/清理按钮或 `approval_execute_failed` badge。
- [ ] 审批决定成功后仍停留“我的审批/待处理”，当前项移除并选中下一项；最后一项处理后显示空状态。
- [ ] F046 决定后文件页收到目标空间刷新事件；刷新只用于重新读取 Knowledge 事实，不把审批响应当业务完成。
- [ ] 暂停 Permission/Knowledge consumer 后打开审批中心，列表和详情仍能读取审批事实；恢复 consumer 后业务页收敛，不新增审批事件。

## 5. 通知职责边界（AC-29）

- [ ] F045/F046 的待办、通过、拒绝、撤回和取消通知可以打开审批中心，并定位到当前用户可见的审批实例/任务。
- [ ] former approver 点击旧通知时不能越权打开或处理已不可见任务；页面回退到当前可见列表，服务端拒绝仍为最终边界。
- [ ] `resource_user_invite_pending` 作为审批待办进入审批中心；F045 已生效/授权失败通知由 Permission 负责，不作为审批中心事实路由。
- [ ] F046 业务 applied/failed/compensating/closed 通知由 Knowledge 负责并落到业务页面，不以 `approval_execute_failed` 进入审批中心。
- [ ] 删除、已读或延迟接收通知均不改变 Approval 决定和业务执行状态；重复通知不触发重复业务副作用。

## 6. 简体中文、英文、日文

- [ ] 切换简体中文（zh-Hans），复跑 F045 待生效/失败重试、F046 六状态、审批中心和通知跳转；无裸 key、英文兜底或布局截断。
- [ ] 切换英文（en），复跑同一组路径；Approval status 与 Knowledge business status 用词可明确区分。
- [ ] 切换日文（ja），复跑同一组路径；重试、补偿、清理和通知文案语义正确。
- [ ] 三种语言均不出现旧业务状态文案作为审批中心 badge；浏览器 Console 无 missing-key 警告。

## 7. 自动化质量门禁（2026-08-13）

### 7.1 Focused Jest

- [x] T064、T067 与相关通知/业务内容测试：5 suites、43 tests 全部通过。

原生 `canvas.node` 在当前机器不可用，因此使用一次性 Node preload 拦截 `require("canvas")`；DOM canvas 仍由仓库 `test/setupTests.js` 中的 `jest-canvas-mock` 提供。临时文件路径为 `/private/tmp/bisheng-t064-preload-canvas.cjs`，内容为：

```js
const Module = require("node:module");

const originalLoad = Module._load;
Module._load = function loadWithoutNativeCanvas(request, parent, isMain) {
  if (request === "canvas") return {};
  return originalLoad.call(this, request, parent, isMain);
};
```

执行命令（cwd: `src/frontend/client`）：

```bash
NODE_OPTIONS=--require=/private/tmp/bisheng-t064-preload-canvas.cjs pnpm exec jest --runInBand --no-coverage \
  src/components/approval/approvalCenterFileChangeUtils.test.ts \
  src/components/approval/ApprovalCenterDialog.test.tsx \
  src/pages/knowledge/SpaceDetail/FileChangeApproval.test.tsx \
  src/components/NotificationsDialog.test.tsx \
  src/components/approval/ResourceUserInviteBusinessContent.test.tsx
```

### 7.2 ESLint 与 i18n

- [x] changed-file ESLint 通过（cwd: `src/frontend/client`）：

```bash
pnpm exec eslint --suppressions-location eslint-suppressions.json \
  src/api/approval.ts src/api/knowledge.ts \
  src/components/approval/ApprovalCenterDialog.test.tsx \
  src/components/approval/ApprovalCenterDialog.tsx \
  src/components/approval/approvalCenterFileChangeUtils.test.ts \
  src/components/approval/approvalCenterFileChangeUtils.ts \
  src/components/notificationApprovalRouting.ts \
  src/pages/knowledge/SpaceDetail/FileCard.tsx \
  src/pages/knowledge/SpaceDetail/FileChangeApproval.test.tsx \
  src/pages/knowledge/SpaceDetail/FileChangeApprovalDetail.tsx \
  src/pages/knowledge/hooks/useFileChangeApproval.ts
```

- [x] `pnpm check-i18n`（cwd: `src/frontend`）通过：`OK — no new i18n drift`；39 个 frontend-only error code 为脚本提示的既有候选，不是失败。

### 7.3 TypeScript strict 基线

- [ ] `pnpm typecheck`（cwd: `src/frontend`）未全绿：Platform 349 个 strict 文件通过；Client 1204 个 strict 文件在四处既有、与本次 F045/F046 变更无关的文件失败，workspace 因 Client first-fail 未继续执行 file-viewers。

精确基线错误：

1. `src/components/Chat/Input/AgentToolSelector.tsx:132:25` — TS2322，`ApiAppIconProps` 不接受 `{ size, className, strokeWidth }`。
2. `src/components/Chat/Input/ChatFormTools.tsx:118:30` — TS2339，`BsConfig` 不存在 `linsightConfig`。
3. `src/pages/knowledge/hooks/useFileStageUpload.ts:65:42` — TS2345，`string | undefined` 不能传给 `string` 参数。
4. `src/pages/knowledge/hooks/useFolderStageUpload.ts:118:21` — TS2322，`string | undefined` 不能赋给 `string`。

上述四个文件不在本次 changed-file 集合中，本任务未越界修改。

## 8. 执行记录

| 检查组 | 执行人 | 时间 | 环境/版本 | 结果 | 缺陷链接 |
|---|---|---|---|---|---|
| Focused Jest | Codex | 2026-08-13 | 本地 feat worktree | 43 passed | — |
| Changed ESLint | Codex | 2026-08-13 | 本地 feat worktree | 通过 | — |
| 三语言 key parity | Codex | 2026-08-13 | 本地 feat worktree | 通过 | — |
| Workspace typecheck | Codex | 2026-08-13 | 本地 feat worktree | 4 个无关基线错误 | 待单独修复 |
| F045 页面人工回归 |  |  |  | 未执行 |  |
| F046 页面人工回归 |  |  |  | 未执行 |  |
| 审批中心与通知 |  |  |  | 未执行 |  |
| 三语言页面人工回归 |  |  |  | 未执行 |  |

**整体状态**: 自动化 focused 门禁通过；workspace typecheck 被四个既有无关错误阻塞；页面人工回归尚未执行。
