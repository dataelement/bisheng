# F003 开发验证记录

日期：2026-11-27。开发与本地单元验证完成；用户随后另行授权提交与推送，未部署。用户明确真实集成自行处理；本记录不把SQLite、ASGI或页面单元测试当作真实环境验收。

## 最终结果

| 范围 | 结果 | 证据与边界 |
| --- | --- | --- |
| 新后端平台认证 | 55 passed | 普通项目conftest及独立模式均通过；最终与旧组同进程全部通过 |
| 请求scope | 新平台55项加scope10项，共65 passed | 实际main导出/--check通过；1035条路由含9条auth，前端产物byte一致 |
| 前端共享api-client | 84 passed | 主执行者在持久工作树再次独立通过 |
| Platform | 89 passed | 登录、启动/切号门控、HTTP401/503、旧DSH授权与OAuth页面回归 |
| Client | 48 passed | 真实Recoil/query Provider、HTTP401/503、用户适配与回跳；本机需可选canvas进程适配 |
| 手机 | 209 passed | 主执行者在持久fix/mobile-session-refresh工作树最终全量通过，含10650/10656终态分类 |
| 原有OAuth2 | 43 passed | 原始alpha1和最终实现均独立协议回归；不等价真实第三方回调 |
| 类型/静态 | 三前端包typecheck通过；手机analyze无问题 | 迁移后主执行者再次复核三包类型；手机保留既有无关文件格式，未放宽规则 |
| 构建 | Platform和Client生产构建通过；Flutter darwin Dart/资源bundle通过 | 不是APK/IPA，未执行真机验证 |
| 架构/格式 | 66个改动源码守卫0发现；修改文件格式检查通过 | 后端Ruff新增问题0；原有7项保留，详见下文 |

前端合计221项。最后新增网关绑定恢复、可配置Cookie保留期及匿名边界用例均先红后绿：覆盖单点/多点、整包响应丢失、同秒发行、时钟回退、首代USED禁止重建和较晚选择优先。数据库私有发行序不进入JWT/Cookie/API；cookie_retention_seconds是非秘密策略metadata，RT和hint均按它保留，默认121天。

## 同进程广泛回归对照

| 代码 | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- |
| 原始alpha1 `572d5ecf77` | 2059 | 122 | 284 | 59 |
| 最终持久实现树，追加55项新套件 | 2114 | 122 | 284 | 59 |

相同旧组选取：`test/dsh test/sso test/sso_sync test/cloud_workbench/test_runtime_identity.py`；最终同进程追加`test/platform_auth`。逐个比较FAILED/ERROR nodeid，均为同样181个节点：**新增失败0，原有失败消失0**。最终组合耗时92.53秒。

这是差异回归通过，**不是整仓全绿**。原有失败包括缺隔离MySQL/Redis、已有fixture及其他业务断言；未为本特性改无关期望或屏蔽用例。原有OAuth2由于同名test_protocol收集冲突，放在独立进程执行，前后43项均通过。

原始证据日志：`/private/tmp/bisheng-auth-baseline-core.log`、`/private/tmp/bisheng-auth-delivery-combined55.log`、`/private/tmp/bisheng-auth-delivery-oauth43.log`。SQLite并发夹具显式串行，不能证明MySQL/DM8行锁和多实例语义。

## 工具环境与已有问题

- 后端完整改动范围Ruff仍有7项：UserService原5项RUF001、SSO_sync原RUF005、旧SSO测试原C408。按原始树相同源码行比较，新增0；修改文件format通过。另路由命名检查的`/api/v2/workstation/config/knowledge`失败在原始树同样复现，未改无关路由。
- 两SPA原生ESLint因既有失效suppression账本退出2；增加`--pass-on-unpruned-suppressions`后全量0 error，Platform保留既有BatchTagDraftDialog:58 unused-disable warning；未改账本。
- Client原生Jest收集受本机缓存缺失canvas.node阻断。仅在认证测试进程将未使用的可选canvas模块替换为空对象，48项通过；未替换认证逻辑、改业务预期或放宽规则。生产构建不需要该适配。
- 本机无Android SDK，未生成APK/IPA。Flutter3.47/Dart3.13由官方GitHub SDK运行，`pub get --enforce-lockfile`通过，pubspec.lock未变。darwin bundle成功仅证明Dart/资源编译。

## 可复跑命令

工作树路径见[handoff.md](./handoff.md)。后端cwd为bisheng工作树：

```sh
PYTHONPATH=src/backend /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python \
  -m pytest src/backend/test/platform_auth -q
```

本机旧组缺少的fakeredis仅安装于`/private/tmp/bisheng-auth-test-deps`，未改共享venv；广泛组合cwd=`src/backend`：

```sh
PYTHONPATH=.:/private/tmp/bisheng-auth-test-deps \
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  test/dsh test/sso test/sso_sync test/cloud_workbench/test_runtime_identity.py test/platform_auth -q
```

网页cwd=`src/frontend`：

```sh
pnpm --filter @bisheng/api-client test
pnpm --filter bisheng exec vitest run src/pages/LoginPage/platformAuth.test.tsx src/pages/LoginPage/RegistrationForm.test.tsx src/pages/DshLogin/dshAuthorization.test.tsx src/pages/DshLogin/dshLoginPage.test.tsx src/pages/OAuthConsent/oauthConsent.test.tsx src/utils/dshLoginReturn.test.ts src/contexts/userAuthStartup.test.tsx src/controllers/requestAuthSession.test.ts src/controllers/browserScopeRecovery.test.ts src/controllers/requestStream.test.ts --maxWorkers=1 --minWorkers=1
pnpm --filter @bisheng/api-client typecheck
pnpm --filter bisheng typecheck
pnpm --filter bishengchat typecheck
pnpm --filter bishengchat exec cross-env NODE_ENV=development jest --ci src/api/requestAuthSession.test.ts src/api/clientRequestContract.test.ts src/api/chat/data-service.identity.test.ts src/hooks/authStartup.test.tsx src/utils/loginRedirect.test.ts --runInBand --coverage=false
```

本机Client命令需加`NODE_OPTIONS='--require /tmp/bisheng-auth-jest-optional-canvas.cjs'`。临时脚本只拦截require('canvas')返回空对象，其余Module._load原样执行；其他环境优先正常安装依赖。

手机cwd为独立手机树：

```sh
CI=true DART_SUPPRESS_ANALYTICS=true FLUTTER_SUPPRESS_ANALYTICS=true \
XDG_CONFIG_HOME=/private/tmp/mobile-flutter-config \
/private/tmp/mobile-flutter-sdk-3.47/bin/flutter test --no-pub --reporter expanded
```

## 交接边界

任务表92项开发/单元/交付任务完成；T092～T094真实API、双DB、多副本、网关、旧DSH安装包、第三方真实应用及手机真机验收由用户执行，保持待执行。QA85条八列用例全部待执行。步骤见[e2e-checklist.md](./e2e-checklist.md)，配置、最低手机版本和回滚地板见[handoff.md](./handoff.md)，审查见[code-review.md](./code-review.md)。

原项目工作区保留原分支和已有改动；实施成果在持久隔离工作树。网关和桌面源码未修改。
