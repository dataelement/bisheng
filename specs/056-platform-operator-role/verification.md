# 056 平台管理员 — T024 自动化记录

日期: 2026-08-28。只跑本特性相关命令，未跑全仓套件。

## T022 / T023 Platform standalone

```bash
cd src/frontend/platform
npx vitest run src/test/platformOperatorStandalonePath.test.ts src/test/resolveRoutePermissions.test.ts --coverage=false
```

结果: **16 passed**（standalone 4 + resolveRoutePermissions 12）。

白名单: `/standalone/dashboard`（含子路径）、`/standalone/knowledge-tag-library`、`/standalone/content-security`。
非白名单 standalone → `standalone-403`；有壳 `/dashboard` `/sys` `/admin` → `kick`。
`userContext` 已登录且无管理端 WEB_MENU 时用 `resolveNoAdminConsoleAction`；未登录仍踢走。

## T024 毕昇后端（171 MySQL）

```bash
cd src/backend
uv run pytest \
  test/user/test_platform_operator_identity.py \
  test/role/test_platform_operator_reserved_name.py \
  test/points/test_platform_operator_points_admin.py \
  test/knowledge/test_platform_operator_migration.py \
  test/knowledge/test_knowledge_migration_auth.py \
  test/dictionary/test_platform_operator_dictionary.py \
  test/workstation/test_platform_operator_tag_and_sensitive.py \
  test/points/test_department_org_level.py \
  -q --tb=line
```

结果: **59 passed**。

AT-70 闸门回归: `require_platform_admin` 仍放行 `is_global_super`；`require_system_admin` 仍放行 `is_admin()`。

## T024 门户 BFF

```bash
cd backend
./.venv/bin/python -m pytest \
  tests/test_platform_operator_admin_acl.py \
  tests/test_admin_upload_api.py \
  tests/test_admin_config_api.py::test_admin_config_allows_bisheng_admin_role \
  tests/test_admin_config_api.py::test_post_admin_domains_updates_persisted_config \
  tests/test_admin_config_api.py::test_post_admin_bisheng_config_updates_runtime_without_echoing_secret \
  -q --tb=line
```

结果: ACL+上传 **16 passed**；AT-70 管理员 POST domains / POST bisheng / GET 管理配置 **3 passed**。

## T024 门户前端（隔离编译，避开全量 tsc 无关失败）

```bash
cd frontend
npx tsc --ignoreConfig --ignoreDeprecations 6.0 --target es2023 --lib ES2023,DOM \
  --module commonjs --moduleResolution node --esModuleInterop --skipLibCheck \
  --jsx react-jsx --outDir /tmp/ops-tests --rootDir . --types node \
  tests/adminAccess.test.ts tests/knowledgeMigrationAccess.test.ts
node --test /tmp/ops-tests/tests/adminAccess.test.js /tmp/ops-tests/tests/knowledgeMigrationAccess.test.js
```

结果: **12 passed**。`npm test` 全量仍会被既有无关用例 tsc 挡住（如 `home_icon`），与本特性无关。

## 跳过

- 毕昇/门户全仓 pytest、Platform 全仓 vitest、门户 `npm test` 全量
- Client / Worker
- T025 浏览器手测（见下）

## T025 UI 手测清单（未跑，不勾完成）

本地 `7860/8010/4001/3001/5173` 均 down，未启动联调。需 U-ops Cookie 后实点:

1. 门户 `/admin` 仅 11 项: 数据看板、积分管理、问答配置、写作模板、应用配置、知识分类、水印设置、字典配置、内容与安全审查、标签管理；Header「迁移记录」可见。
2. 直链 `?section=site`（及 domains/recommendation/search/banners/display）主区「无权限」，不发全量 config。
3. iframe 三条能开且接口可用: dashboard / knowledge-tag-library / content-security。
4. 改 URL 进 `/platform/standalone/approval` 或有壳 `/sys` 失败（403 或踢 workspace）。
5. 超管 / 「管理员」菜单仍全开；「管理员」仍不能进迁移。
6. 运营岗无「BiSheng 管理后台」外链、无回收站、无课程。
