# 验证记录

- Status: `LOCAL_VERIFIED`
- 本地复现（修复前）：目录查看者+库编辑者，页面接口 allowed=true，业务 add_file 抛出 SpacePermissionDeniedError。

## 实际证据

以下命令均在对应 src/backend 或 src/frontend/client 目录运行。代码状态为本次未提交工作区，2026-10-14。

- E-001：`.venv/bin/python -m pytest test/permission/test_knowledge_child_permission_check.py -q --disable-warnings` 修复前 8 failed / 4 passed（拒绝查询错误返回 true）；见 `/tmp/folder-permission-backend-red.log`。
- E-002：`npm run test:ci -- --runInBand --coverage=false --runTestsByPath src/pages/knowledge/portal/components/PortalHeaderActions.test.tsx` 修复前 2 failed（无权限按钮仍存在）；见 `/tmp/folder-permission-ui-red.log`。API 缓存回归修复前 2 failed / 3 passed（跨账号复用 true），见 `/tmp/folder-permission-cache-red.log`。
- E-003：后端以下相关回归 37 passed / 242 deselected，退出 0，3.13s；见 `/tmp/folder-permission-backend-final.log`。覆盖路由真实调用、最近目录授权、无独立授权继承、内层编辑恢复、空模型、组织/用户组主体、FGA 读取故障绑定降级、隐式 owner 和业务上传拒绝。

```sh
.venv/bin/python -m pytest test/permission/test_knowledge_child_permission_check.py test/permission/test_empty_knowledge_relation_model.py test/test_permission_api_integration.py test/test_knowledge_space_service.py -k '(child or empty or permission_check or manage_permission_id_only or custom_model or parent_folder_upload or effective_permission) and not (shougang_portal_non_public_space_keeps_child_permission_filter or shougang_portal_department_share_link_allows_child_department_member or list_space_children_filters_each_child_by_view_permission)' -q --disable-warnings
```

- E-004：前端以下回归 4 suites / 19 passed，退出 0，1.596s；见 `/tmp/folder-permission-ui-clean.log`。覆盖失败默认拒绝、目录加载/账号/租户/跨库切换、迟到响应、同资源跨账号短缓存及在途请求隔离、权限分别控制三个写入口。

```sh
npm run test:ci -- --runInBand --coverage=false --runTestsByPath src/api/permission.test.ts src/pages/knowledge/hooks/useKnowledgeContainerWritePermissions.test.tsx src/pages/knowledge/portal/components/PortalHeaderActions.test.tsx src/pages/knowledge/hooks/useKnowledgeSpacePermissions.test.tsx
```

- E-004a：门户集成 `npm run test:ci -- --runInBand --coverage=false --runTestsByPath src/pages/knowledge/portal/PortalKnowledgeWorkbench.pageHistory.test.tsx --testNamePattern '知识库编辑者进入查看者目录'`：1 passed / 7 skipped，退出 0，1.342s；见 `/tmp/folder-permission-workbench-integration.log`。运行真实 Workbench、权限 hook 和操作栏，列表及 HTTP 为既有 fixture；验证加载期间隐藏、最终查看权限保持隐藏。
- E-004b：最终 `npm run build` 退出 0，22.80s；见 `/tmp/folder-permission-build-final.log`。保留既有字体、Browserslist、CSS 及 chunk 大小提示，未改依赖或构建配置。
- E-005：内置浏览器访问独立 localhost fixture，使用真实 hook、Recoil 和 PortalHeaderActions，本地 HTTP 返回测试授权。根目录和编辑目录显示三个写入口，查看目录及新目录权限加载阶段只保留筛选；保存 `/tmp/folder-permission-viewer.png` 并检查截图。未上传文件或操作线上。迟到响应的机械证据以 hook 回归为准。
- E-006：新 Python 测试 Ruff 通过；修改的权限服务 py_compile 通过；git diff --check 通过。
- 权限服务完整文件 Ruff 存在 9 项既有问题（旧类型注解、闭包和 zip 等）；新增代码没有新增检查错误，未扩大修改。见 `/tmp/folder-permission-service-lint.log` 及 HEAD 静态对照 `/tmp/folder-permission-service-lint-baseline.log`。

## 扩展测试的既有失败

没有修复与本缺陷无关的旧测试：

- 扩展后端权限集：59 passed / 6 failed。用 HEAD 的原 has_any_permission_async 在同一进程 fixture 和同一测试集对照，14 failed / 51 passed，差异恰好为本缺陷的 8 个新失败；原 6 项仍失败。失败涉及成员列表新增字段、旧订阅 tuple 语义及组织模拟数据，见 `/tmp/folder-permission-backend-regression.log`、`/tmp/folder-permission-api-baseline.log`。
- 扩展知识服务集：37 passed / 3 failed；HEAD 方法对照 29 passed / 11 failed，原 3 项不变（两个测试缺少数据库模拟、一个仍传旧 page 参数），见 `/tmp/folder-permission-backend-focused.log`、`/tmp/folder-permission-backend-baseline.log`。最终定向集排除这三项。
- 原门户 pageHistory 的 5 项测试仍断言已过时的分页控件，另外未改动的上传 hook 有 1 项音频选择测试失败。HEAD Workbench 临时副本在相同 fixture 上复现相同 6 项（17 passed）；见 `/tmp/folder-permission-ui-baseline.log`。本次新增门户目录权限用例通过，不把旧分页失败归为本修复。
- 首轮接入发现残留旧 setter，已清除；新增门户 fixture 补齐真实操作栏和成员管理异步 mock 后通过。临时基线副本和本地浏览器 fixture 仅供验证，交付前清理。

## 覆盖与限制

| Acceptance | Status | Evidence |
|---|---|---|
| AC-1 | PASS | E-001, E-003, E-004a |
| AC-2 | PASS | E-003 |
| AC-3 | PASS | E-002, E-004, E-004a |
| AC-4 | PASS | E-002, E-004, E-005 |

真实部署环境、真实 OpenFGA/数据库授权数据未验证；没有修改数据、迁移、提交、推送或部署。部署需同时更新后端和前端，并用实际编辑者账号验收查看者目录。前端单独部署只能隐藏后端已正确返回拒绝的入口；后端需本修复消除错误允许结果。
