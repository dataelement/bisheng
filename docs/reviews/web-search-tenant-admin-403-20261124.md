# 联网搜索设置租户管理员 403 修复

日期：2026-11-24。目标：`feat/3.1.0-beta2`。基线：`1ed9dd5e7d`。

## 现场与根因

用户报告 `/api/v1/tool/1410/web-search/settings` 返回 403。116 源码只读确认：搜索专用 `_require_search_admin` 要求 `user.is_global_super` 且再次通过 `_check_is_global_super`，未包含租户管理员。GET settings、PUT settings、POST schema、POST test 共用此限制，因此不只是保存失败。

只读核对目标分类 1410：属于租户 60，is_preset=1、is_delete=0；子工具为同租户未删除的预置 `web_search`。未读取配置、extra 或密钥。没有修改现场代码、数据、权限或服务。

通用 `/tool/config` 已采用当前租户管理身份，专用路径遗漏了此前用户要求的租户管理员支持；本次修复统一入口，不扩展仍待用户确认的普通工具 owner/manager 配置权限。

## 实现与边界

- `_require_search_admin` 复用 permission application 的 `is_current_tenant_administrator`；系统超管和当前租户管理员可管理当前租户搜索配置。该入口使用已认证身份/PermissionActor；登录依赖仍服务端验证系统超管，data_scope 收窄优先于管理员。
- 领域服务 `_target` 的当前租户、preset、删除态及 web_search 子工具身份校验保持。租户管理员看得到共享 Root 工具不代表可以读取、修改或测试 Root 配置。
- 四个路由统一生效；revision CAS、加密信封、密钥脱敏、provider 校验和出站策略保持。无新 API、SQL、DDL 或依赖。
- F017 AC-12、design、tasks 及人工验证清单同步本轮用户确认的管理身份规则，替代早期“仅全局超管”的描述。

## 验证

同一组合：`test/tool/test_{custom_web_search,f048_tool_permissions,web_search_deepseek,web_search_timeout,web_search_tool_config,tool_secret_projection}.py`。

- 基线：79 passed、1 failed；既有 `test_partial_preset_secret_explicit_clear_preserves_omitted_fields` 缺少当前租户上下文，通用配置服务已拒绝当前租户不符。
- 修复：**108 passed**。仅为该既有用例补 `tenant_execution_scope(1)`，作用域在同一个 async 测试上下文内退出，不放宽业务校验。
- 四个路由均覆盖本租户管理员、系统超管、其他租户管理员、普通身份、未被可信 actor 证实的管理员标记以及 personal_only 收窄。
- 实际 ASGI 路由 + SQLite 完成两种管理身份的导入、保存、读取、测试；只隔离上游传输。四个跨租户实际请求均 404，不写数据且不访问上游。现有受控回环 HTTP 导入/执行测试通过，不使用真实搜索凭据或服务。
- Ruff format/check、diff check 通过；逐文件 arch-guard 无 VIOLATION。原脱敏测试的合成 CANARY 字符串会触发既有 RULE-7 WARNING，并非真实凭据。

## 七维审查

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

**Overall: PASS。** 身份入口复用既有合同，目标范围和并发保存校验保持；没有按资源编辑授权放开配置。108 项为本地相关回归，不代表 MySQL/DM8 或在线页面验收。116 未部署，需部署后以租户 60 管理员重新打开对应设置验收。
