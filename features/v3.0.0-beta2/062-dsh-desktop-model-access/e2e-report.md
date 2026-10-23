# F062 E2E 覆盖报告

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

日期：2026-09-09。整体状态：**PARTIAL（live E2E 待执行）**。

## 本轮实际执行

```text
cwd: B/src/backend
PYTHONPATH=. /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  --confcutdir=test/dsh test/dsh/test_dsh_e2e.py test/dsh/test_dsh_e2e_guards.py -q -rs
```

结果：**3 passed, 7 skipped**；ruff format/check 通过。

- 3 个 PASS 为本地 harness 安全门测试：缺总开关、缺隔离确认、缺 BASE/manifest 时均 SKIP，且不构造网络客户端。它们不是真实 API E2E。
- 7 个 live 用例均因 `DSH_E2E_RUN` 未开启而 SKIP。当前没有已明确配置的完整独立 Nginx HTTPS/Gateway/Python/SSO 与专用四身份 manifest，也没有 DSH Desktop 版本或实际模型样本。
- 未探测默认 localhost、未使用 helpers 的默认 API_BASE/admin 密码、未访问正式环境、未创建或撤销真实账号席位。
- 原父级 test/conftest 会在收集前初始化应用服务与 config.yaml；可运行命令明确用 `--confcutdir=test/dsh`，避免把本地服务 premock 带入 live harness。
- 部署 BiSheng SHA、Gateway SHA、配置版本、测试 License 摘要和真实 request_id：**未取得**。未来运行的 manifest/JUnit 可记录操作者提供的部署版本与服务端 request_id；不能将输入的 SHA 当作已在线证明。

## Live harness 用例

| 方法 | 覆盖范围 | 本轮状态 |
| --- | --- | --- |
| test_ac32_config_and_normal_platform_identity | 同 HTTPS Nginx config 与既有 Web 身份 | SKIP：live 总开关未开启 |
| test_ac02_denial_and_wrong_origin | deny 无票据、跨 Origin 拒绝、席位未改变 | SKIP：同上 |
| test_ac25_three_roles_and_tenant_scope | 普通用户 19801、T1/T2 管理范围、Root 跨范围读取、分页 | SKIP：同上 |
| test_ac05_session_refresh_logout_revoke_reassign | PKCE/authorize/token、同人双会话、models/usage、轮换/重放、登出保席、撤销/重分配、操作审计 | SKIP：同上 |
| test_ac03_pkce_failure_and_web_token_separation | 错 verifier、普通 Web JWT 不可代替 DSH Bearer | SKIP：同上 |
| test_ac19_optional_real_model_and_usage[json] | 固定无隐私提示、真实模型 JSON/usage、后续读用量 | SKIP：同上；另需模型调用开关与预算 |
| test_ac19_optional_real_model_and_usage[sse] | 真实 SSE 帧、终结 usage 与 DONE、有界消费 | SKIP：同上；另需模型调用开关与预算 |

## AC 逐项追溯

下表描述已提供的执行入口，**所有 live 结果都尚未通过**。ASGI/Redis/MySQL/前端单元结果分别见对应模块验收记录，不记入本表 live PASS。

| AC | 验收入口 | 状态 |
| --- | --- | --- |
| AC-01 | harness 身份核验 + PKCE；真实 SSO 见 C03 | SKIP / SSO 待联调 |
| AC-02 | approve/deny harness，C05/C06 真机回调 | SKIP |
| AC-03 | 错 PKCE harness；过期/重放见 C05 | SKIP / 待联调 |
| AC-04 | C10 停用/删除/租户变更专用账号 | 待场景执行 |
| AC-05 | lifecycle 首次无席位时自动分配；重跑 REVOKED 先显式 reassign | SKIP |
| AC-06 | lifecycle 同人两会话、一 seat_id | SKIP |
| AC-07 | C07 专用 11 人/10 席并发 | 待容量场景 |
| AC-08 | lifecycle logout 后仍 ASSIGNED | SKIP |
| AC-09 | cleanup/显式 revoke 后 GET 核对 | SKIP |
| AC-10 | C09 revoked 用户不能自动复活 | 待场景执行 |
| AC-11 | lifecycle 显式 reassign 后新登录 | SKIP |
| AC-12 | C07 多进程并发首次登录 | 待容量场景 |
| AC-13 | lifecycle token 类型/真实 user 与 tenant | SKIP |
| AC-14 | C09 无席/撤销后的签发与刷新负向 | 待场景执行 |
| AC-15 | lifecycle 旧会话/旧 grant 拒绝；到期由 C08/C16 | SKIP / 待联调 |
| AC-16 | Web JWT 混用 harness；PAT/SAK 见 C10 | SKIP / 待联调 |
| AC-17 | lifecycle 撤销后 DSH 拒绝、普通 user/info 可用 | SKIP |
| AC-18 | lifecycle models；共享/下线完整矩阵 C11 | SKIP / 待联调 |
| AC-19 | 可选真实 JSON | SKIP |
| AC-20 | 可选真实 SSE；取消/故障 C16 | SKIP / 待联调 |
| AC-21 | C11 当前合法模型与模型撤销/共享权限 | 待场景执行 |
| AC-22 | C14/C17 限额/0 额度 | 待计量场景 |
| AC-23 | 可选模型 terminal usage；完整 SQL 审计待对照 | SKIP / 待场景执行 |
| AC-24 | C15 DSH 与其他场景审计对照 | 待场景执行 |
| AC-25 | 三角色 license/users | SKIP |
| AC-26 | 管理分页数据与 UI 席位/模型视图分离 | SKIP / UI 待现场验证 |
| AC-27 | C17 修改策略后新请求；policy 更新真实环境 | 待场景执行 |
| AC-28 | command 轮询到终结，不将处理中当成功 | SKIP |
| AC-29 | command operation_id/actor 与 GET 后置条件；前后值完整现场对照 | SKIP / 待场景执行 |
| AC-30 | 三角色 T1/T2/Root 页面；模型/用量跨租户 C10/C11 | SKIP / 待联调 |
| AC-31 | C15/C16 故障闭合与正常业务回归 | 待故障注入 |
| AC-32 | enabled config 与 Web identity；关闭/无 Gateway C02 | SKIP / 待场景执行 |
| AC-33 | limit=1 权限页；大数据执行计划见数据库验收 | SKIP / 待规模验收 |
| AC-34 | C14/C15/C17 实时实际用量、并发超额、UNKNOWN CLI | 待故障/计量场景 |

## 后续执行入口

- [客户端 C01–C18 与安全 manifest/命令](desktop-handoff-checklist.md)
- [平台现场手动验证](e2e-checklist.md)
- [本地平台 UI 测试证据](frontend-progress.md)
- [Gateway 实际数据库/HTTP 回归证据](gateway-progress.md)

T109 的文档交接已提供；T110 的 harness 可运行，但完整 live E2E 验收条件尚未满足。用户允许本轮跳过缺失的外部环境，此结论不等价于上线门禁通过。

## 2026-09-09：0.3.0 修订回归

当前验证见 [用量与检索修订记录](./usage-and-search-revision.md#本轮验证)。HTTP/ASGI、真实隔离 MySQL/Redis 与前端组件测试已完成；这不等同于真实 Desktop/Nginx/供应商联调。
