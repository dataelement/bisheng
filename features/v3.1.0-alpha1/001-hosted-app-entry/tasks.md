# Tasks: 托管应用入口理顺与桌面专用通道下线

**关联规格**: [spec.md](./spec.md)
**版本**: v3.1.0-alpha1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-23 Callum 确认 |
| design.md | ✅ 已评审 | 2026-11-23 Callum 确认（同时同意 AC-22 措辞修正）；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 2026-11-23 |
| 实现 | ✅ 服务端 + 两个网页端完成（未提交） | 2026-11-23；真实环境未验证；桌面配套在 bisheng-desktop `V1.3.1` 另做 |
| test-cases.md | ✅ 已补 | 2026-11-23，24 条；TC-HAE-004 与实现的差异见 design 文末 |
| AC-03 口径 | ⏸ 待用户确认 | design 文末「待用户确认」 |

---

## Tasks

> 设计论证见 design.md 对应决策，这里只写做什么、改哪里、覆盖哪些 AC。

### Wave 1：服务端拆除与兼容（无相互依赖）

- [x] **T01** 错误码 16149 + 三语文案。文件：`common/errcode/app_factory.py`、`frontend/packages/locales/src/api_errors/*`。覆盖 AC: AC-19。设计：决策 4。
- [x] **T02** 桌面列表接口保留原形状并加 `runtime_enabled`，`managed=true` 与 launch / deploy-limits / deploy / deployments / source 返回 16149。文件：`dsh/api/endpoints/apps.py`、`app_runtime/domain/services/desktop_apps_service.py`。覆盖 AC: AC-17、AC-18、AC-19、AC-20、AC-22。设计：决策 3、4。
- [x] **T03** 拆桌面票据、会话、入口鉴权分支、运行时 `dsh_session`、桌面发布与取源码、`deployment_status`；保留准入锁。文件见 design §4.3「后端」。覆盖 AC: AC-17、AC-18、AC-21、AC-25。设计：决策 1、6。
- [x] **T04** app-proxy 拆 `_desktop` 换票路由、`redeem_desktop`、桌面 Cookie 读取；保留 SSE 撤权与 Cookie 过滤。文件：`src/app-proxy/app_proxy/`。覆盖 AC: AC-18、AC-21。设计：决策 1、6。
- [x] **T05** 删 `/api/v1/apps/workbenches`、workbench-guide 路由与文件、`workbench-realtime/` 样例、`SKILL.md` F113 段；SDK 历史版本保留。覆盖 AC: AC-06、AC-23、AC-24。设计：决策 6。

### Wave 2：类型分类接口（依赖：无）

- [x] **T06** `/workstation/app/uncategorized`、`/workstation/app/used` 加可选 `flow_type`。文件：`workstation/api/endpoints/apps.py`、`api/services/workflow.py`。覆盖 AC: AC-02、AC-03、AC-04。设计：决策 5。

### Wave 3：员工端网页（依赖：T06）

- [x] **T07** 删云端工作台页面、接口封装、路由（旧地址跳「应用」）、「应用」页链接、`AgentCard.openLabel`。覆盖 AC: AC-06、AC-07。设计：决策 8。
- [x] **T08** 卡片右上角类型标签；「应用」「发现广场」类型分类并传 `flow_type`，未开通时隐藏「托管应用」，空列表文案。覆盖 AC: AC-01、AC-02、AC-03、AC-04、AC-05、AC-08、AC-10。设计：决策 5。

### Wave 4：管理后台（依赖：无）

- [x] **T09** 构建页去「云端工作台」链接；「应用模板」页托管应用可选中、右侧说明、搜索禁用、运行时提示、卡片说明与链接文字。覆盖 AC: AC-11、AC-12、AC-13、AC-14、AC-15、AC-16。设计：决策 7。

### Wave 5：收尾

- [x] **T10** 测试：删除失效测试，补 design §7 列出的新测试；与干净 alpha1 基线逐文件对比。
- [x] **T11** 文档：F130 spec / design 顶部撤销说明；test-cases.md。

---

## 实际偏差记录

- T08 → AC-03：发现广场的标签与搜索词沿用现有互斥规则，类型分类分别与二者组合，三者不会同时生效；推翻已确认的 AC，已提请用户确认（design 决策 5、文末）。
- T08 → 卡片类型标签用默认灰色 `Tag`，不按类型上色（Tag 规范；原型为彩色）：design 决策 5。
- T01/T02 → 16149 服务端文案为中英双语一句话（1.3.0 原样显示 `status_message`）；路由壳不再读请求体：design 决策 4。

## 验证记录

2026-11-23，本机没有中间件，失败的测试都和干净 alpha1 基线（`origin/feat/3.1.0-alpha1`）逐条对比过：

- 后端 `test/app_runtime test/app_publish test/dsh test/dev_toolkit test/workstation test/admin test/api`：本分支 5611 条 / 失败 868，基线 5605 条 / 失败 868，新增失败 0；有意删除 12 条，新增 18 条全部通过。
- app-proxy 276 条全部通过。
- 网页 jest `src/pages/apps src/routes` 56 条通过；`explore.navigation.test.tsx` 在基线同样失败（缺 `~/components/ui/Tooltip2`）。
- 管理后台 vitest 全量 2936 条 / 失败 76，这 76 条在基线上逐条同样失败，新增失败 0；新增 `appTempSheetHostedGuide.test.tsx` 3 条通过。
- `packages/api-client` 38 条通过。
- 静态检查：`ruff check` 通过；`ruff format --check` 只有 app-proxy `tests/test_sse_revocation.py` 不合格，改动前就不合格（本次只改了其中一行 Cookie）；arch-guard 41 个文件只有 2 条改动前就有的 WARNING（`workstation/api/endpoints/apps.py` RULE-3、`test_sse_revocation.py` RULE-7）；两个应用的 lint（含 `lint:prune`，无变化）、`check-i18n` 通过；typecheck 剩 3 条错误（client `packages/knowledge/src/VersionHistoryTable.tsx`、platform `src/test/sidebarSpaceActions.test.tsx` 两处），基线同样存在。
