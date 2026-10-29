# Vibe 应用及租户管理问题修复记录

日期：2026-10-28。分支：`codex/vibe-qa-fixes`。基线：`origin/feat/3.0.0@d2ff49e591e0f602f7ae41387f8b8c90bbccf90b`。

## 范围与流程

这是 11 项既有功能缺陷的修复批次，按 SDD-Guide §1 的 hotfix 路径恢复已有约定：隔离分支、定位、修复、定向验证和七维度自审。没有新增发布方式、审批流程、数据表或资源迁移。新增的 `approval_status` 是版本查询的可选读字段，原有字段和数据库终态保持兼容。

2026-10-28 开发阶段未提交、推送、合并或部署；116 仅执行日志、已部署源码和只读事务查询，未修改存量应用、人员、用户组或审批记录。2026-10-29 用户授权提交本批修复、合入最新 `feat/3.0.0` 并推送，本次 Git 交付不涉及环境部署。

## 逐项结果

| # | 问题与定位 | 处理与证据 |
|---|---|---|
| 1 | 发布面存在永久禁用的「提交发布」按钮。应用提交实际上由 CLI 完成，没有网页待提交的包。 | 移除该按钮，保留 CLI 发布说明及实际可用的撤回操作。 |
| 2 | 无审批人、路由缺失是否生成异常实例。 | 当前引擎已经创建 `exception` 实例和异常记录，发布侧保留版本，不绕过审批。本轮定向验证审批人为空、路由缺失、异常版本留存。116 还读到应用发布异常实例 432（`route_missing`）。不另建重复异常机制。审批场景本身未启用仍按既有配置错误拒绝，不冒充已提交审批。 |
| 3 | 已上线 Vibe 应用仍可展开版本下拉框。 | 在线状态禁用下拉框。该控件原本只是只读版本列表，没有切换执行入口；未新增离线版本切换能力。 |
| 4 | 草稿点击上线只显示泛化状态错误。 | 在缺少可运行版本时，先读取对应发布/审批状态，返回稳定原因：审批中、驳回、撤回、取消、审批异常、审批执行失败、发布准备中或准备失败等。前端使用三语言文案解释处理方式，操作请求由页面统一展示错误，避免拦截器和页面重复弹出泛化提示。此分支始终拒绝启动，不允许未审批版本上线。 |
| 5 | 上下线需要二次确认。 | 当前源码的列表和详情已经共同调用 `useHostedAppActions`。保留其确认弹窗；定向验证取消不发请求、确认后才执行。确认真实调用者，没有再加第二层弹窗。 |
| 6 | 租户管理员设置用户组返回 23006。 | 用户组选择器允许租户管理员选择组，但成员写入只识别超管/创建者/公开组部门管理员，存在权限判断不一致。另有「原样带回不可管理的已有组也被拒」的问题。补齐本租户管理员写入资格，限制目标组和新操作人员的租户；不可编辑的既有关系保持原样，拒绝新增越权组。 |
| 7 | 租户管理员审计页 403。 | 116 日志确认失败接口为 `/api/v1/audit/session`。后端原先依赖 RBAC 管理员、菜单或用户组管理员身份，遗漏独立租户管理员资格。复用权限模块的实时租户管理员检查，查询仍使用本租户谓词；不开放跨租户审计。 |
| 8 | 通知不能定位对应审批。 | 撤回/业务取消通知接收者是原审批人，改到「我的审批」已处理项。解析 task/instance 两种 ID；同一栏目目标变化重新加载；程序切换筛选项不再用首条记录覆盖目标；不可用目标不跳到无关记录。发布首节点通知不再把首个 task_id 共用给所有接收者，而由接收人按 instance_id 找自己的 task。 |
| 9 | 草稿数据页 500 且无法解释。 | 授权完成后，无当前及待上线版本直接返回既有业务码 16163，不启动数据库 helper/RPC。页面复用未创建数据库的空状态，说明草稿需完成审批上线，以及仅使用浏览器存储的应用不会产生数据表。运行过的应用仍按原数据路径查询，未因停用而隐藏持久化数据库。 |
| 10 | 版本页审批状态为空。 | 原页面把 `terminal_state` 当审批状态；该字段记录最终上线结果，审批时可以为空。现在通过发布记录关联对应审批实例，校验租户、场景、应用和发布记录后投影 `approval_status`；版本页显示真实审批状态。读取分批进行，兼容旧后端的终态回退，不改历史记录。 |
| 11 | 日志行数文案与箭头挤在一起。 | 使用现有共享 Select 和其本地化配置，提供 160px 且不收缩的宽度，行内不足时沿原布局换行。验证选中标签和刷新请求使用一致的行数。未声称已完成真实浏览器各尺寸视觉验收。 |

## 116 的已核对事实与边界

- `gzx0001`（868）、`gzx0004`（871）的当前有效成员关系均为租户 60；截图用户组 182 同属租户 60，创建者为 868。不能将该组数据解释成跨租户错误。
- 未完整恢复截图中那一次成员保存请求的实际操作者与请求体，因此没有把某一拒绝分支冒充唯一的线上根因；上表第 6 项两条确定的代码缺陷均已修复并配对验证。
- 草稿应用 `69c165e3ac9b410aac2ec0f6e99d868c` 的 `current_version_id`、`pending_version_id` 均为空；对应最近发布所关联审批为 `withdrawn`。恢复已有终态提示无需修改其数据。
- 日志能确认另一个应用数据库尚未创建时 manager 返回 404（平台有既定业务映射）；未取得截图那次 500 的完整历史堆栈。新增草稿前置检查消除了截图应用所处条件下不必要的数据库 RPC，未把所有 500 都归为同一个原因。
- 以上为只读核查；本分支的修复尚未在 116 替换服务验证。

## 代码入口

- 发布操作、版本禁用：[HostedAppCard](../../src/frontend/platform/src/pages/BuildPage/HostedAppCard.tsx)、[useHostedAppActions](../../src/frontend/platform/src/pages/BuildPage/useHostedAppActions.ts)、[ApprovalStatusCard](../../src/frontend/platform/src/pages/BuildPage/hostedApp/publish/ApprovalStatusCard.tsx)。
- 发布原因及版本审批投影：[version_review_service](../../src/backend/bisheng/app_publish/domain/services/version_review_service.py)、[version_review_repository](../../src/backend/bisheng/app_publish/domain/repositories/version_review_repository.py)、[execution_source](../../src/backend/bisheng/approval/application/execution_source.py)。
- 数据页：[AppDataService](../../src/backend/bisheng/app_runtime/domain/services/app_data_service.py)。
- 租户管理：[UserGroupService](../../src/backend/bisheng/user_group/domain/services/user_group_service.py)、[MemberIdentityRepository](../../src/backend/bisheng/user_group/domain/repositories/member_identity_repository.py)、[AuditLogService](../../src/backend/bisheng/api/services/audit_log.py)。
- 通知：[notificationContent](../../src/frontend/client/src/components/messageApproval/notificationContent.ts)、[ApprovalPane](../../src/frontend/client/src/components/approval/ApprovalPane.tsx)。

## 定向验证

没有运行仓库全量回归。已通过的用例来自以下限定集合，合计后端 57、平台 47、客户端 13；修复测试问题后仅重跑受影响集合，不重复运行无关集合。

### 后端（57）

| 集合 | 数量 | 验证重点 |
|---|---:|---|
| `test/app_runtime/test_app_data_service.py` | 19 | 数据授权、查询/写入既有路径、草稿未初始化不调用 manager |
| `test/app_runtime/test_app_query_service.py` 指定版本列表用例 | 4 | 版本兼容字段；真实 SQLite 发布记录与审批实例关联，覆盖 pending/rejected/withdrawn |
| `test/app_publish/test_version_review.py` | 14 | 上线阻断原因、审批各状态、跨租户审批拒绝关联 |
| `test/user_group/test_user_group_tenant_admin_access.py` | 11 | 管理身份、同租户允许/跨租户拒绝、不可管理的既有关系保留/新增越权拒绝 |
| `test/audit/test_tenant_admin_entry.py` | 3 | 实时租户管理员与普通用户配对、目标租户范围拒绝 |
| `test/app_runtime/test_app_state_actions.py::test_draft_start_reports_review_reason_before_release_source_lookup` | 1 | 缺少版本时不进入启动和发布来源执行 |
| 审批引擎/发布的四个指定异常用例 | 4 | approver_empty、route_missing、异常时不通知普通审批任务 |
| `test/app_publish/test_version_service.py::test_gate_exception_approver_empty_still_inserts_version` | 1 | 审批异常仍留版本和审计记录 |

### 前端

- 平台：`useHostedAppActions.test.tsx`、`VersionsTab.test.tsx`、`hostedAppDataTab.test.tsx`、`hostedAppMenuTrim.test.tsx`、`PublishTab.test.tsx`、`LogsTab.test.tsx`、`hostedAppApi.test.ts`，共 47 条通过。
- 客户端：`notificationContent.test.ts`、`ApprovalPaneErrors.test.tsx`，共 13 条通过。
- 本地 Jest 的可选 `canvas` 原生二进制缺失。仅测试进程将未使用的 canvas 视为不可用后运行上述两份测试；没有改业务代码、依赖版本或共享安装目录。最终运行关闭覆盖率收集，不代表全量覆盖率检查。
- 平台 8 份、客户端 2 份变更业务源码的定向 TypeScript 语义诊断均为 0；平台和客户端变更业务源码 ESLint 通过。不是整个前端工作区 typecheck/lint 全量通过的声明。
- 更新错误文案的三语言源文件，并由 `packages/locales/scripts/build.mjs` 生成产物；`--check` 通过。
- 架构守卫和 `git diff --check` 通过。
- 除 `audit_log.py` 外变更 Python 文件 Ruff 通过。`audit_log.py` 原基线 36 项、当前 10 项存量诊断，按规则码和消息比对无新增；没有把这份文件标为全量 lint 干净，也未扩展清理无关旧审计逻辑。

## 七维度自审

| 维度 | 结论 |
|---|---|
| 边界条件 | 空版本、空审批、未知状态、不可用通知目标均受控；未回退打开无关审批。 |
| 权限认证 | 应用鉴权先于原因投影/数据空状态；租户管理员的新增成员写入资格校验人员归属；跨租户审批投影拒绝。 |
| 并发安全 | 不改发布状态机和审批写入；通知列表与详情沿用请求 revision，取消筛选 effect 对指定目标的覆盖。 |
| 错误处理 | 用稳定业务原因和本地化文案，保留既有错误码；未知故障不伪装为未初始化成功。 |
| 前端规范 | 复用共享 Select、已有确认弹窗和本地化设施；无新组件库，变更文件均在 600 行以内。 |
| 数据与兼容 | 无 DDL/数据迁移；业务读取关联显式核对归属，使用兼容 MySQL/DM8 的列查询，不使用数据库 JSON 提取。 |
| 验证证据 | 定向模拟/SQLite/组件测试与 116 只读事实分别记录。真实部署、浏览器尺寸视觉检查、DM8 实测均未宣称完成。 |

## 提测时需核对

更新 backend、worker 及前端到本分支后，在测试环境检查：草稿撤回提示与数据空状态、列表/详情上下线确认、版本审批状态、租户管理员成员保存及本租户审计、撤回/取消通知定向详情；最后检查宽屏与窄屏日志控件文案。存量资源无需迁移，也无需重放历史审批。
