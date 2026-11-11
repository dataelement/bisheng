# 组织与成员改造验证记录

2026-11-11：已与最新发版线联合整合；当前合入检查、编号调整和环境限制见 [联合合入记录](../integration-account-organization-20261111.md)。以下保留 2026-11-10 的实施验证记录。

日期：2026-11-10。工作树：`feat/3.1.0-beta1`，未提交。按用户提供的三张截图、聊天确认方案及“部门名称（兼职部门）”修订实现。

## 实现范围

- 组织页统一名称搜索，成员与部门独立加载；可见兼职回退、成员去重、可见祖先路径、清空恢复组织树。
- 展开并选中结果对应部门；成员定位到实际页码、必要时调整所属关系筛选、滚动并高亮约 5 秒。
- 部门设置按钮与弹窗，流量控制合入页签，统一保存与未保存保护；保留归档、恢复、彻底删除和子租户能力。
- 新增两项只读接口；不新增数据库表、错误码或业务依赖。

## 已执行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 后端 SQL/服务/HTTP 与既有范围回归 | 24 passed | `.cache/organization-complete-backend-tests.log` |
| 前端交互与既有设置/归档回归 | 7 个文件，23 passed | `.cache/organization-complete-tests.log` |
| platform lint:prune | 通过；仅由 CLI 清理抑制项 | `.cache/organization-lint-prune.log` |
| 全工作区 typecheck | 通过 | `.cache/organization-workspace-typecheck.log` |
| 最终 platform typecheck | 通过 | `.cache/organization-final-typecheck.log` |
| Playwright 实际源码页面 | PASS；1280×800、1024×768；无页面错误/控制台错误 | `output/playwright/organization-search/verification.json`，7 张截图 |
| 架构守卫 | 本功能后端、API、页面与测试文件无发现 | `.cache/organization-arch-guard.log`；Git Bash 正常权限运行 |
| 新增 Python 文件 Ruff | 0 项 | `.cache/organization-ruff-baseline.json` |
| 本功能文案 | 三语 22 个 organization 键集合一致 | zh-Hans/en-US/ja `bs.json` |
| 全仓 check-i18n | 最后复查通过，no new i18n drift | `.cache/organization-i18n-final.log` |
| git diff --check | 通过 | 全工作树检查；换行转换提示不是空白错误 |

## 复现命令

后端（`src/backend`，使用 Python 3.11 隔离测试环境）：

```powershell
../../.cache/organization-test-venv/Scripts/python.exe -m pytest test/department/test_organization_search.py test/department/test_global_members_search.py test/department/test_department_scope_parity.py -q --tb=short
```

前端（`src/frontend/platform`，pnpm 9.15.9）：

```powershell
pnpm exec vitest run src/pages/DepartmentPage/components/OrganizationSearchPanel.test.tsx src/pages/DepartmentPage/components/MemberTableLocation.test.tsx src/pages/DepartmentPage/components/MemberTablePagination.test.tsx src/pages/DepartmentPage/components/DepartmentSettingsDialog.test.tsx src/test/memberTableToggleErrorToast.test.tsx src/test/departmentSettingsPayload.test.tsx src/test/systemDepartmentsArchivedDelete.test.tsx --maxWorkers=1 --minWorkers=1
pnpm lint:prune
pnpm typecheck
```

全工作区（`src/frontend`）：`pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`。本机使用 corepack 缓存的 pnpm 9.15.9；隔离的 tsc-strict 工具位于 `.cache/organization-types`，未为本功能改动依赖清单。

浏览器复现：运行 `.cache/frontend-dev/prepare-organization-preview.ps1` 恢复专用入口，以 `.cache/frontend-dev/organization.vite.config.mts` 启动 3011 端口，再执行 `.cache/frontend-dev/organization-browser.mjs`。临时入口已从 platform 根目录移除，截图保存在 output。此脚本与日志是本机调试材料，不是生产入口。

## 全仓检查的外部问题

以下检查已实际运行失败，不能声明全仓质量门禁通过：

1. `pnpm lint`：platform/client 及已有共享包通过，最后新增的 `@bisheng/identity/src/rules.test.ts` 有 9 处中文测试样例被规则判为硬编码。该文件属于同时开发的 F011 账号昵称功能，不在本功能改动范围。日志：`.cache/organization-workspace-lint.log`。
2. 部门旧服务 Ruff：HEAD 已有 89 项；检查时共享工作树为 93 项，额外 4 项均为 F011 修改带来的未使用导入。本功能在旧服务的业务改动仅为成员分页补充 `UserDepartment.id` 稳定排序。新仓库、服务、路由端点和测试 Ruff 为 0 项；旧 router 的 7 项已清理。

`pnpm check-i18n` 初次曾因 F011 错误码 10612–10615 缺翻译失败；该并行功能补齐文案后，本次最终复查已通过。本功能没有新增错误码，22 个 organization 键三语齐全。

以上记录的是检查时刻的共享工作树状态，未覆盖其他功能的进行中修改，也未对其他功能宣称验收。

## 验证边界

SQLite 用例执行真实查询，HTTP 用例经过实际 endpoint/service/repository，但替换了登录身份与外部权限范围依赖。浏览器装载真实页面与组件，API 使用专用模拟数据，验证交互与布局。完整部署的登录、管理视图切换、网关、OpenFGA、归档写入与流量生效，以及 MySQL/DM8 真实集成仍需 CI/目标环境验证。本次没有部署、提交或推送。
