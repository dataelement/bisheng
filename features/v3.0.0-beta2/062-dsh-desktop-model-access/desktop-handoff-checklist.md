# DSH Desktop 客户端交接与联调清单

状态：服务端与平台 UI 的本仓实现已交付，**DSH Desktop 源码、负责人、版本与真机样本未提供，以下客户端项均待客户端团队实现/联调**。本文件没有向外部团队发送消息，也没有修改 `src/frontend/client` 的 Recoil 工作台。

契约 SSOT：[client-api.md](client-api.md)，版本 `0.3.0`。接口/字段/错误/时序变更必须更新此文档并同步客户端；不得增加私有“兼容”接口。内部身份/JWKS/管理端接口不是桌面端依赖。

## 接口与调用顺序

客户端只配置同一个 Nginx HTTPS BASE。固定七个客户端 API：

| 方法 | 完整路径 | 触发 |
| --- | --- | --- |
| GET | `/api/v1/dsh/config` | 首次输入地址、启动能力探测 |
| POST | `/api/dsh/authorizations` | 本地生成 state/verifier、绑定 loopback 后 |
| POST | `/api/dsh/token` | 票据换证或串行 refresh |
| POST | `/api/dsh/logout` | 单设备退出 |
| GET | `/api/v1/dsh/models` | 登录/启动/手动刷新、明确模型权限失效后 |
| POST | `/api/v1/dsh/chat/completions` | 用户问题或完整工具结果就绪后 |
| GET | `/api/v1/dsh/usage` | 登录/账号页/模型调用结束后 |

裸 JSON 与 envelope、参数白名单、真实错误 HTTP 状态、请求 ID、TTL、重试边界均以接口文档为准。七个时序图：[登录](client-api.md#seq-login)、[深链](client-api.md#seq-deeplink)、[启动](client-api.md#seq-startup)、[刷新](client-api.md#seq-refresh)、[模型与用量](client-api.md#seq-model)、[错误](client-api.md#seq-errors)、[退出](client-api.md#seq-logout)。

## C01–C18 客户端验收矩阵

每项状态均为「待联调」；负责人/客户端版本/系统版本/样本 request_id 由执行团队填写，不能用服务端 mock 结果替代。

| 编号 | 客户端待实现/验收 | 待交付证据 |
| --- | --- | --- |
| C01 | BASE 同 origin；SDK base 为 `{BASE}/api/v1/dsh`，不得重复 `/v1` 或 `/api` | 网络请求路径记录，脱敏 |
| C02 | 区分 disabled、404、代理 HTML、网络错误；不回退普通 JWT/PAT/SAK | 四个状态 UI 与请求样本 |
| C03 | 系统浏览器使用已有 Web 登录/SSO，当前事务回来后以换证响应显示可信姓名/租户 | 账号来源与事务状态记录 |
| C04 | `/desktop-login` 深链只 server；未运行/已运行均先确认地址再发起 PKCE；未安装提示下载或联系管理员 | macOS/Windows 真机协议注册与唤起 |
| C05 | 仅监听 127.0.0.1 动态端口 `/dsh/callback`；验证 state/auth_id/TTL/重复参数；票据复制只用于当前本地事务 | 回调拦截、粘贴、过期、错 verifier、旧票据/重放 |
| C06 | 拒绝只接收白名单错误、不发票据；关浏览器等待超时；重复回调不能重复换证 | 拒绝/取消/超时操作记录 |
| C07 | 同自然人两台设备共一席；第 11 人争抢 10 席显示明确满席；换证响应丢失不重放票据 | 专用 11 人、10 席测试 License 和并发样本 |
| C08 | 所有 provider/worker 共享会话刷新锁；access/refresh 原子写入 OS 安全存储；响应丢失重新登录、不重发旧 refresh | 安全存储实现审查、并发刷新计数 |
| C09 | 退出当前设备清理 provider/本地秘密，204 才确认服务端撤销；离线退出说明未确认；不释放席位；撤销/重分配后旧凭证不能恢复 | 两设备/离线/撤销/重分配样本 |
| C10 | DSH/普通 Web/PAT/SAK 凭证隔离；停用与租户变化重新验证；普通业务仍可用 | 负向鉴权与原登录回归 |
| C11 | 模型按 ID 唯一；空列表不注销账号；共享/同名/下线/移除正确刷新，不能自动重放原问题 | 模型列表与 provider 注册样本 |
| C12 | JSON/SSE UTF-8 拆包、粘包、心跳、空 choices；完整终止与 usage 不遗漏 | 原始脱敏 SSE 字节样本与解析单测 |
| C13 | 工具调用按 id/index 聚合分块 arguments；完整成功后才执行本地工具；工具结果多轮独立计量 | 单/多工具与分块样本、工具执行记录 |
| C14 | 900/1000 两个在途各 300 允许最终 1500；达到上限后的新请求 429，在途不中断 | 准入时间/最终实际量/拒绝样本 |
| C15 | UNKNOWN/Redis 故障/SQL 快照明确 unavailable 与 as_of，不能把未知显示为 0 或强制清除 | 降级截图、脱敏错误 ID |
| C16 | 半途断流/取消/上游失败不伪造 DONE、不自动重放；access 自然到期不截断已准入 SSE | 故障注入与取消样本 |
| C17 | 月归属依 billing_timezone 与准入月；0 禁用、提高上限后可刷新；切换 BASE/账号不得发送旧凭证 | 跨月/改限额/切换目标网络记录 |
| C18 | 只有 capability=true 才处理 reasoning_content；不能根据 DeepSeek 名字猜能力 | 指定适配器/模型版本的真实工具与计量 PoC |

## 可运行 live HTTP harness

文件：`src/backend/test/dsh/test_dsh_e2e.py`。通过真实网络访问单一 Nginx，不用 ASGITransport 或 mock。它模拟浏览器 authorize HTTP 请求（含真实 Web 会话与 Origin），**不模拟真实 OS/桌面客户端实现，也不执行普通登录密码/SSO UI**。

运行前由测试环境负责人准备：独立 Nginx HTTPS BASE（受信证书）、已启用 Gateway/Python、有效测试 License、T1/T2、专用 Root/T1 管理员/T2 管理员/T1 普通用户。四个用户名必须 `e2e-f062-` 开头，四个真实 Web JWT 分别放独立环境变量，manifest 只写变量名。harness 通过 `/api/v1/user/info` 验证实际 user_id/tenant_id/username/角色后才允许席位动作。

创建本机权限 `0600` 的 manifest（示例值必须按专用环境替换；不要提交真实凭据）：

```json
{
  "environment": "isolated",
  "base": "https://dsh-e2e.example.test",
  "backend_sha": "实际部署 BiSheng SHA",
  "gateway_sha": "实际部署 Gateway SHA",
  "config_version": "测试部署配置版本",
  "license_id": null,
  "seat_limit": 10,
  "model_id": null,
  "actors": {
    "root": {"username":"e2e-f062-root","user_id":"101","tenant_id":"1","token_env":"DSH_E2E_ROOT_WEB_TOKEN"},
    "t1_admin": {"username":"e2e-f062-t1-admin","user_id":"102","tenant_id":"21","token_env":"DSH_E2E_T1_ADMIN_WEB_TOKEN"},
    "t2_admin": {"username":"e2e-f062-t2-admin","user_id":"103","tenant_id":"22","token_env":"DSH_E2E_T2_ADMIN_WEB_TOKEN"},
    "user": {"username":"e2e-f062-user","user_id":"104","tenant_id":"21","token_env":"DSH_E2E_USER_WEB_TOKEN"}
  }
}
```

`license_id` 可以是 null，但必须与实时管理 API 一致；seat_limit 也必须匹配。SHA/config 字段是环境负责人提供的部署证据，不是 harness 通过 `/env.version` 验证的结果；请另附镜像 digest/部署修订信息。

在 B/src/backend 运行（先由安全方式注入四个 JWT 环境变量，不把 token 写入命令历史/日志）：

```bash
DSH_E2E_RUN=1 \
DSH_E2E_ISOLATED_ENVIRONMENT=1 \
DSH_E2E_ALLOW_TEST_SEAT_MUTATION=1 \
DSH_E2E_BASE=https://dsh-e2e.example.test \
DSH_E2E_MANIFEST=/absolute/private/dsh-e2e.json \
uv run pytest --confcutdir=test/dsh test/dsh/test_dsh_e2e.py -q -rs --tb=short --junitxml=/absolute/private/dsh-e2e-results.xml
```

`--confcutdir=test/dsh` 避免父层单元测试 conftest 的服务 premock/本地 app config 初始化；该 harness 本身不需要加载 BiSheng config.yaml。证书为内部 CA 时显式指定 `DSH_E2E_CA_FILE`；不支持关闭 TLS 验证，也不跟随重定向或使用环境代理。禁止 xdist 并行。

默认不调用供应商模型。仅在已配置专用用户模型策略和预算后追加 `DSH_E2E_ALLOW_MODEL_CALLS=1`，manifest 的 model_id 使用 models 返回的 `bisheng:<id>`。只发送固定无隐私提示，每次最多 16 输出 token，JSON/SSE 各一次；仍会产生真实模型用量。

清理仅作用于经核验的 `actors.user`：setup 撤销上次残留会话，若已有 REVOKED 席位则显式重分配；teardown 再撤销释放名额。测试保留 REVOKED 席位行、审计与已计量记录，不删除账号/租户/策略，不操作其他人员。中断后以相同 manifest 重跑可清理；清理失败保留具体 operation_id，负责人核对后通过管理页恢复，禁止全表/全实例删除。

缺开关/配置/凭据时输出具体 SKIP 原因，不构造网络客户端；已明确开启且配置错误或运行失败时应 FAIL。不要添加 `--showlocals`、HTTP DEBUG 日志或打印 token/票据/完整响应。JUnit 只附服务端 request_id 和部署版本元数据。

## 尚需独立环境验证

本 harness 没有执行 11 人并发满席、真实 OS keychain/深链、工具 PoC、跨月、UNKNOWN CLI 补记、DM8、故障切主、旧 License 二进制或性能 SLA。这些仍按本清单与 `tasks.md` T110–T115 执行，不能因基础 HTTP harness 通过而关闭上线门禁。

## 2026-09-09 必须同步的逐模型额度修订

- 切换模型后使用 GET usage?model=bisheng:<id> 查询该模型独立月额度；模型调用完成及月额度错误后同样刷新该模型。
- 无参数 usage 是汇总展示，remaining 不能由总 limit-used 推算，不能将模型 A 耗尽解释为所有模型均不可用。
- 接口形状/认证/登出保席位保持既定契约；本次查询参数与额度语义变动已记录 client-api.md 和 contract fixture，联调前需客户端确认已同步。
- 一期无限流配置。

## 0.1.0 → 0.3.0 交接状态

当前config返回0.3.0；旧客户端若只识别0.1.0须先完成版本与逐模型查询适配。接口文档/时序/JSON均已更新，客户端接收确认及真实联调尚未完成。该项不得因本地文档完成而勾选为已对外同步。
