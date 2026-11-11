# F011 实现与验证记录

日期：2026-11-10。工作区：`C:/Users/30388/Desktop/bisheng`；分支：`feat/3.1.0-beta1`；基线：`cd02c8344`。变更保留在本地工作区，未提交、推送或发布。

## 当前状态

注册、登录、后台创建与编辑、本人改名、成员列表、身份解析及同步保护均已完成本地实现。后台组合编辑已按用户确认的 [事务范围](./design-adjustment.md) 接入：先校验，原所属操作完成后，最后原子提交昵称及其附属状态。公司后端、真实数据库及原生桌面端未作为已验收范围。

## 已执行检查

| 检查 | 结果 | 证据与范围 |
| --- | --- | --- |
| F011 后端隔离检查 | 119 通过；8 跳过 | 真实 User 映射、SQL 仓库、领域规则、后台保存编排及本人/成员 FastAPI 路由。SQLite 模拟旧字段大小写比较；不是 MySQL/DM8 运行证明。 |
| 共享前端规则 | 52 通过 | packages/identity/src/rules.test.ts：码点长度、空白/不可见、账号语法、历史原值、密码组合。 |
| 平台相关回归 | 55 通过 | 注册规则与组件、后台创建/编辑、列表搜索/复制/事件、异步响应归属、聚焦刷新及原定位/分页/启禁回归。 |
| Client 相关回归 | 20 通过 | 资料映射、严格 API 响应、个人改名、失败保留、原值复制、同身份缓存更新。 |
| 根 pnpm lint | 通过 | platform、client、共享 UI、file-viewers、chat、api-client、identity。只通过工具移除已失效的旧 suppressions。 |
| 根 pnpm typecheck | 通过 | platform 1092 个 strict 文件、client 1848 个 strict 文件及共享包。后台两个表单已移除原 ts-strict-ignore。 |
| pnpm check-i18n | 通过 | 三语言键及错误码无新增漂移；共享错误文案由 locales 构建生成。 |
| 架构守卫 | 43 个文件，无 VIOLATION | 覆盖本次前后端实现入口；保留旧 api/v1/schemas.py 的 RULE-3 WARNING，该旧导入在基线中已存在。模型内旧 DAO 不反向导入 service。 |
| UI优化 detect | 空结果 [] | 注册、后台创建/编辑/列表、旧创建入口、个人账号和改名组件；另已目视检查实际截图。 |
| 浏览器交互 | 53 项通过，运行错误 0 | Chrome，实际本地两个 SPA，1440×960 与 390×844。API 全部由独立浏览器的合成 fixture 拦截。 |

后端命令使用隔离 Python 3.11 环境、`pytest --noconftest -p pytest_asyncio.plugin` 及工作区独立临时目录；不加载缺失本地配置的全局测试环境。相关测试没有启动或访问公司数据库。

## 后端行为证据

- `test_identity_rules.py`：账号 1–64、昵称 1–32、实际变更才校验、Unicode 和密码策略。
- `test_account_identity_repository.py` / `test_account_identity_service.py`：全局占用、大小写身份、唯一候选、旧匹配、禁用、登记及绑定回滚。
- `test_account_login_rules.py`：实际 UserService 注册/登录；32 字符昵称、首次管理员初始化、验证码先校验、歧义先于密码、单身份密码判断。
- `test_legacy_identity_adapters.py`：旧 DAO 创建/查询不绕过新规则，账号查找不改变可见用户范围。
- `test_nickname_repository.py` / `test_nickname_service.py` / `test_nickname_api.py`：本人身份派生、额外目标字段拒绝、原值 no-op、昵称/保护标记/资料版本/审计原子提交及回滚。
- `test_nickname_sync.py`：主动昵称不会被旧 detached 同步对象覆盖，其他权威字段继续更新。
- `test_account_identity_compatibility.py`：旧 SSO 改名前识别名称保留；新昵称不成为登录 ID；歧义拒绝。
- `test_f011_account_identity_migration.py`：只增元数据、不缩列、幂等与降级保护；保留 MySQL 原 user_name 比较配置；MySQL 与 DM8 实际方言 DDL 编译通过。
- `test_member_nickname_edit.py`：16 项覆盖昵称预检、历史原值、用户组/角色后续失败、真实角色事务先完成、最后昵称审计失败回滚、只读来源、原授权保护，以及真实路由的操作者 IP 和字段错误。测试先复现早期改名的 5 项失败，再完成接入后通过。原成员编辑管理范围的 7 项回归也已通过。

真实双库并发的 2 项及已部署 HTTP 的 6 项，因未配置专用环境而跳过。对应文件已提供，运行条件见 [upgrade.md](./upgrade.md)。这些跳过项不计为真实环境通过。

## 既有回归与静态检查基线

扩展执行原首次注册、用户字符串长度、SSO 登录同步和 token_version DAO 回归，结果为 **44 通过、2 失败**。失败均为旧 SSO 部门授权断言：

- `TestDepartmentAdminFgaReconcile.test_empty_admin_list_removes_fga_admin_on_sso_member_dept`
- `TestDepartmentAdminFgaReconcile.test_leader_dept_grants_admin_tuple`

使用 `git show HEAD:<path>` 在独立缓存目录准备改动前的后端源文件覆盖层及原测试，两个用例均复现相同的 `len(admin_ops) == 1`、实际为 0 的失败。没有重置或覆盖共享工作区。这两个结果不计为本功能通过，也没有改动原部门授权实现。

Ruff 对目标文件执行格式化和安全修复。完整检查保留原文件既有的中文标点、Optional 等规则欠账；通过同文件 HEAD 诊断对比确认无新增诊断。不能将此项表述为原有整个后端 lint 全绿。检查细节保存在 `.cache/backend-dev/f011-ruff-report.json`。

## 实际页面与截图

Browser 插件在本会话不可用，使用已有 Playwright 1.62.1 和独立 Chrome。流程为：登录 → 注册校验及规则 → 重复账号纠正 → 后台列表/改名/创建/搜索 → 个人改名失败重试 → 手机布局及 Esc 取消。

| 页面或状态 | 截图 |
| --- | --- |
| 登录占位 | [01-login.png](../../../output/playwright/account-nickname/01-login.png) |
| 注册默认状态 | [02-registration.png](../../../output/playwright/account-nickname/02-registration.png) |
| 注册字段错误 | [03-registration-errors.png](../../../output/playwright/account-nickname/03-registration-errors.png) |
| 注册规则与密码两项 | [04-registration-rules.png](../../../output/playwright/account-nickname/04-registration-rules.png) |
| 昵称/账号并列成员列表 | [05-member-list.png](../../../output/playwright/account-nickname/05-member-list.png) |
| 后台编辑昵称 | [06-admin-edit.png](../../../output/playwright/account-nickname/06-admin-edit.png) |
| 后台创建本地成员 | [07-create-local.png](../../../output/playwright/account-nickname/07-create-local.png) |
| 个人账号查看 | [08-account-info.png](../../../output/playwright/account-nickname/08-account-info.png) |
| 个人昵称编辑 | [09-self-edit.png](../../../output/playwright/account-nickname/09-self-edit.png) |
| 手机昵称编辑 | [10-mobile-self-edit.png](../../../output/playwright/account-nickname/10-mobile-self-edit.png) |

断言、请求及控制台证据：[checks.json](../../../output/playwright/account-nickname/checks.json)。证据中的密码仅记录为 `[encrypted]`；浏览器未登录公司账号，远端业务写入为 0。警告包含预期的未登录 401、已有 Router future flag 提示，以及 fixture 关闭项目订阅产生的断连提示；没有相关页面运行错误或框架错误遮罩。

截图证明实际前端在合成数据下的渲染与交互。保存操作的目标后端行为由隔离服务/API 检查补充，不能用这些截图证明公司后端已经部署。

## 剩余验证

1. 在 MySQL、DM8 专用环境执行升级、创建并发、改名/同步竞争和完整 HTTP 认证回归。
2. 在公司测试构建验证真实注册、登录、全部管理范围、DSH 原生嵌入及既有会话。按 [e2e-checklist.md](./e2e-checklist.md) 执行。
3. 本地代码审查已完成，目标环境验收后再做发布审查并进入合并和发布。本次未提交、推送、升级共享库或发布服务。
