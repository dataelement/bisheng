# E2E 验证清单：OAuth 2.0 / OIDC Provider（F026）

**目标环境**：http://192.168.106.115:3001（SSO / Platform）  
**状态**：2026-11-25 已部署 115；真实 HTTP 6/6 通过（17.20s）。浏览器已检查匿名授权页、登录入口和返回地址保留；管理员三语页面及旧 Desktop 完整人工交互仍待用户验证。  
**依据**：[spec.md](spec.md) AC-01–AC-10；已读 exact e2e-test skill 和 references/test-template.md。

## 前置条件与运行

- 主会完成 115 部署，确保 MySQL/Redis、OAuth Provider、平台认证和 discovery 代理路由已就绪。
- 主会准备临时全局管理员 token，通过 E2E_ADMIN_TOKEN 注入（复用既有 get_admin_token）。
- 主会准备专用测试租户和其中的有效普通用户，通过 E2E_USER_TOKEN、E2E_TEST_TENANT_ID 注入；不在文件中写 token、密码、私钥。运行前普通用户必须已能正常登录，且不能拥有管理员资格。
- OAuth 客户端管理是平台全局数据；只创建/更新/删除 client_id、client_name 均以 e2e-oauth115- 开头、is_builtin=false 的测试客户端。用户和租户由主会准备，套件不创建或删除它们。
- 串行运行，不用 xdist，也不同时运行另一套相同前缀的进程。各用例独立 fixture 在 setup 清理残留、finally 清理本次数据；故不依赖方法顺序或 pytest-ordering。全量分页读取，删除前 GET 再核对双前缀与非内置标记；删除后 GET 断言 28102，并核对非测试客户端内容未变化。
- 运行端使用 Python 3.11+，已有依赖 pytest、pytest-asyncio、httpx、PyJWT[crypto]（无需安装完整 backend 或启动本地中间件）。

从仓库根进入 backend 后运行；下列 token 环境变量须由主会事先安全注入，命令中不填真实凭据：

~~~bash
cd src/backend
export E2E_API_BASE=http://192.168.106.115:3001/api/v1
: "${E2E_ADMIN_TOKEN:?inject temporary admin token first}"
: "${E2E_USER_TOKEN:?inject dedicated ordinary user token first}"
: "${E2E_TEST_TENANT_ID:?inject dedicated user tenant ID first}"
PYTHONPATH=. python -m pytest --noconftest -o addopts='' -o asyncio_mode=auto   test/e2e/test_e2e_oauth2_provider.py -v --tb=short
~~~

将上述 python 替换为包含这些依赖的虚拟环境解释器。--noconftest 隔离 test/conftest.py 的应用预 mock 和重型 fixture；所有业务验证都通过真实 httpx 网络请求，仍直接复用 helpers/auth.py、helpers/api.py。缺少普通用户 token 或 tenant ID 时明确 skip，不伪造认证。E2E_OAUTH_ISSUER 可覆盖预期公开 issuer，默认等于 E2E_API_BASE 的 origin；只有部署确实使用不同公开地址时设置。禁止为通过断言把 issuer 随意改为错误的内部地址。

只收集、不发送 HTTP 请求：

~~~bash
PYTHONPATH=. python -m pytest --noconftest -o addopts='' -o asyncio_mode=auto   test/e2e/test_e2e_oauth2_provider.py --collect-only -q
~~~

OAuth authorize/token/userinfo/JWKS 成功与错误断言标准 JSON，无平台信封；authorize 成功检查 302 和 Location，revoke 检查空 200。管理与 consent 成功检查平台信封；错误检查精确业务码。现有管理权限 HTTPException 由全局 handler 转为 HTTP 200 + status_code=403、status_message=Super admin permission required（legacy handler 可省略 data），不误断言 OAuth error。

## API 覆盖追溯（115 已执行）

测试文件：[test_e2e_oauth2_provider.py](../../../src/backend/test/e2e/test_e2e_oauth2_provider.py)。当前收集 6 个用例。

| AC | 自动化覆盖 | 方法 / 参数 | 状态与边界 |
|---|---|---|---|
| AC-01 | public/confidential 创建、GET 持久状态、列表、更新、禁用/启用、删除后 28102；confidential 密钥轮换后旧密钥拒绝、新密钥可换 token；GET 无明文/hash；普通用户 list/get/create/update/rotate/delete 全部 403，拒绝后 GET 核对 | test_ac01_management_permission_pairs × 2 | 已通过（115）；盐化 hash 的存储实现与内置删除保护需保留单元测试证据，HTTP 套件不读 DB、不尝试删除内置客户端 |
| AC-02 | S256 authorize → 302 consent、state/scopes/redirect/TTL；非法 redirect、缺失 PKCE、plain 拒绝；禁用客户端拒绝 | lifecycle × 2；invalid_redirect_pkce_and_denial；management | 已通过（115）；无 consent 的浏览器自动批准另见手动项 |
| AC-03 | 普通用户 GET consent、approve 回传 callback code/state、deny 回传 access_denied/state；消费后 28108 | lifecycle × 2；invalid_redirect_pkce_and_denial | 已通过（115） |
| AC-04 | code + verifier 换标准 token、openid id_token、offline refresh；code 二次使用 invalid_grant；错误 verifier 拒绝；confidential 鉴权 | lifecycle × 2；invalid_redirect_pkce_and_denial；management | 已通过（115）；TTL 到期与并发原子消费由既有单元/集成覆盖，不等待 120s |
| AC-05 | refresh 轮换；旧 refresh replay 拒绝且 family 当前 refresh/access 都失效 | lifecycle × 2 | 已通过（115） |
| AC-06 | Bearer userinfo、非空 profile/sub/tenant claims；tenant_id 与指定测试租户匹配；非法/撤销 access 返回 invalid_token | lifecycle × 2；invalid_redirect_pkce_and_denial | 已通过（115）；email 在用户未配置时可省略 |
| AC-07 | 独立新 session 验证 revoke；重复/未知 token 空 200；后续 refresh 与 userinfo 拒绝 | lifecycle × 2 | 已通过（115） |
| AC-08 | 公共 discovery issuer/endpoints/S256/ES256；JWKS 无私钥；按 kid 选择公开 JWK，ES256 实际验证 access/id_token 签名及 issuer/audience/exp/iat/sub/tenant/nonce | lifecycle × 2 | 已通过（115） |
| AC-09 | GET dsh-desktop 验证内置/public/PKCE/动态 loopback/标准 callback | test_ac09_builtin_client_read_only | 已通过（115）；旧 Desktop 完整交互见下 |
| AC-10 | API 角色控制配对 | management × 2 | UI、三语需手动验收，不能用 API 结果代替 |

## Platform 与授权页手动验证（待部署后）

### AC-01 / AC-10：管理入口与普通用户权限

- [ ] 全局管理员登录目标 Platform → 系统设置 → OAuth2 客户端 tab，列表正常加载；普通用户看不到管理 tab，直接访问管理路由也不能执行管理动作。
- [ ] 仅用 e2e-oauth115-ui- 前缀新建 public/confidential 测试客户端，填写 redirect/scopes/PKCE/consent；创建成功 toast、列表刷新，刷新页面后仍可 GET/展示。
- [ ] confidential 创建/轮换只当次展示明文；关闭后再进详情无明文；public 不显示 secret。编辑、禁用、启用和删除后刷新列表核对结果。
- [ ] 内置 dsh-desktop 的删除按钮不可操作；本清单不要求对已有非测试客户端发送变更请求。
- [ ] zh-Hans、en、ja 分别检查管理 tab、创建/编辑弹窗、scope 名称、错误与成功提示，无裸 i18n key。

### AC-02 / AC-03 / AC-10：浏览器 consent

- [ ] 从专用测试客户端发起 S256 authorization；未登录时登录后返回同一 request_id 的 consent 页，不丢 state/nonce/redirect。
- [ ] 以专用普通用户登录，显示正确客户端名称、说明、scope；批准回到精确 callback 且包含 code/state，拒绝返回 access_denied/state，重复提交和过期请求显示明确错误。
- [ ] 将仅本次创建的测试客户端设为 require_consent=false：当前登录用户直接获得 callback，未登录用户仍需认证；验证后删除测试客户端。
- [ ] zh-Hans、en、ja 切换验证 consent 文案、按钮、错误；Radix Select/Dialog 可鼠标、键盘操作，关闭再开无残留。

### AC-09：既有 Desktop 兼容性

- [ ] 使用旧版 DSH 客户端，通过现有 /api/v1/dsh/authorizations → /desktop-login 完成登录，原 code exchange / refresh 仍成功。
- [ ] 本地动态端口 loopback callback 路径正常；错误 host/path 的回调被拒绝。
- [ ] 对“禁用/consent 策略委托”的变更验证应在专用验证环境进行；115 不改内置客户端，记录既有集成测试证据或另行执行隔离验证。

## 回归与结果记录

- [ ] Platform 设置页、普通用户工作区、登录与退出正常，无新增浏览器 console 错误。
- [ ] 每次 API 测试 teardown 成功，前缀客户端清空；非测试客户端快照相同，专用用户/租户保留给主会管理。
- [ ] 连续执行两次均通过，记录运行时间、部署版本、6 个用例通过/失败/skip 数及手动项结果；所有凭据与 token 保持脱敏。

执行记录（2026-11-25）：Provider 本地 43 项通过；前端业务回归 69 项、API client 23 项及根 lint/typecheck/i18n/build 通过。115 首轮 4 通过、2 项因 iat 与本机时钟偏差失败；实测 HTTP Date 比本机快 48.18 秒后，设置 E2E_JWT_LEEWAY_SECONDS=60（代码上限 120，默认 0，不关闭 exp/iat/签名检查），最终 6/6 通过。临时客户端均在前后清理中删除，8 个测试 session、测试用户与租户也已删除。非测试客户端及旧客户端产物保留。API 结果 PASS，完整人工/UI/Desktop 覆盖仍为 PARTIAL。
