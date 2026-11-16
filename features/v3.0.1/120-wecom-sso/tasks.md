# Tasks: 企业微信单点登录（WeCom SSO，无网关）

**关联规格**: [spec.md](./spec.md) · **关联设计**: [design.md](./design.md)
**版本**: v3.0.1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-16 评审 8 条已修订（AC-24/AC-25 新增） |
| design.md | ✅ 已评审 | 8 条决策、9 条坑；接手第一入口 |
| tasks.md | ✅ 已拆解 | 12 个任务，4 个 Wave |
| 实现 | ✅ 12 / 12 | 后端 349 行新代码 + 5 个测试文件（35 用例全绿）；前端 platform 入口与文案三语；真实企微租户 E2E 待执行（见偏差记录） |

---

## 开发模式

- Wave 1 = 无依赖基础设施（可并行）；Wave 2 = 领域服务（Test-First）；Wave 3 = API；Wave 4 = 前端 + 收尾。
- 后端测试基座已存在：`src/backend/test/sso/`（`test_sso_api_integration.py` 等），沿用其 fixture 风格，不新建框架。
- 前端为手动验证（Playwright 仍未落地）。

---

## Tasks

### Wave 1 — 基础设施

- [x] **T001**: 错误码 19330–19334
  **文件**: `src/backend/bisheng/common/errcode/sso_sync.py`
  **逻辑**: 19330 企微登录未配置 · 19331 企微配置不唯一 · 19332 state 无效/过期 · 19333 授权码无效 · 19334 企微接口失败（携带 errcode 描述）
  **覆盖 AC**: AC-02, AC-03, AC-16, AC-17, AC-21
  **依赖**: 无

- [x] **T002**: 错误码三语文案
  **文件**: `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 为 19330–19334 补 copy（`check-i18n` 要求后端码全覆盖）；生成物不手改
  **覆盖 AC**: AC-02, AC-16, AC-17, AC-21
  **依赖**: T001

- [x] **T003**: 配置项（嵌套在既有 `sso_sync` 下）
  **文件**: `src/backend/bisheng/core/config/sso_sync.py`
  **逻辑**: `WeComSSOConf`：`state_ttl_seconds=300`、`allowed_return_origins: list[str] = []`、`request_timeout_seconds=10`
  **约束**: 不新增顶层 key（旧镜像会起不来）；凭据仍只读组织同步配置（INV-45）
  **覆盖 AC**: AC-04
  **依赖**: 无

- [x] **T004**: `LoginSyncService` 首登超管开关
  **文件**: `src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`, `test/sso/test_sso_login_sync_service.py`
  **逻辑**: `execute(..., bootstrap_first_user_admin: bool = False)`；仅在**新建用户**分支且 `UserDao.get_all_users(1,1)` 为空时 `add_user_and_admin_role` + `AdminRole` RBAC 同步（照搬 legacy `/user/sso`）；默认 False 保证既有链路不变
  **覆盖 AC**: AC-11, AC-22
  **依赖**: 无

- [x] **T005**: OAuth state 存储
  **文件**: `src/backend/bisheng/sso_sync/domain/services/wecom_login_state.py`, `test/sso/test_wecom_login_state.py`
  **逻辑**: `put(state, payload)` / `consume(state)`（GETDEL；Redis < 6.2 用 Lua 原子 GET+DEL）；TTL 取配置；Redis 故障 → 19332 fail-closed
  **覆盖 AC**: AC-16
  **依赖**: T003

### Wave 2 — 领域服务

- [x] **T006**: 企微 OAuth 客户端 + 测试
  **文件**: `src/backend/bisheng/sso_sync/domain/services/wecom_oauth_client.py`, `test/sso/test_wecom_oauth_client.py`
  **逻辑**: `build_authorize_url(mode, corpid, agent_id, redirect_uri, state)`；`exchange_code(code)` → `auth/getuserinfo` → userid（只有 `openid` 时视为不在可见范围）；`fetch_member(userid)` → `user/get`；token 复用 `org_sync:wecom:token:{config_id}` 缓存键；errcode 40001/40013/60011/42009/40029 → 19334
  **覆盖 AC**: AC-05, AC-09, AC-21
  **依赖**: T001
  **注意**: 企微接口路径见 design §2（**未在真实租户联调**，E2E 阶段核对）

- [x] **T007**: 登录编排服务测试
  **文件**: `src/backend/test/sso/test_wecom_login_service.py`
  **逻辑**: 覆盖唯一配置判定（0/1/多）、`bisheng_pro` 关闭入口、return_to 白名单、UA→mode、部门存在性探测与降级、payload **不含** `account_disabled`、首登开关透传
  **覆盖 AC**: AC-01~AC-04, AC-08, AC-12, AC-24
  **依赖**: T005, T006

- [x] **T008**: 登录编排服务实现
  **文件**: `src/backend/bisheng/sso_sync/domain/services/wecom_login_service.py`
  **逻辑**: `availability()` / `authorize()` / `callback()` 三段编排；凭据读取 `bypass_tenant_filter()`；部门探测只读；组装 `LoginSyncRequest(source='wecom')`；调用 `LoginSyncService.execute(..., bootstrap_first_user_admin=True)`
  **测试**: T007 全绿
  **覆盖 AC**: AC-01~AC-12, AC-19, AC-20, AC-22, AC-24, AC-25；AC-13 / AC-14 / AC-23 为**沿用既有 LoginSyncService 语义**（并发锁 19311、跨来源冲突 19304、leaf 租户限定），由回归用例断言而非新增实现
  **依赖**: T004, T007

### Wave 3 — API 层

- [x] **T009**: API 端点集成测试
  **文件**: `src/backend/test/sso/test_wecom_login_api.py`
  **逻辑**: 三个 GET 端点的 302 目标、`Set-Cookie` 属性（含 `httponly=False`）、`?wecom_error=` 跳转、免登录可达
  **覆盖 AC**: AC-02, AC-03, AC-15~AC-18
  **依赖**: T008

- [x] **T010**: 端点 + 路由注册 + 免登录白名单
  **文件**: `src/backend/bisheng/sso_sync/api/endpoints/wecom_login.py`, `sso_sync/api/router.py`, `bisheng/utils/http_middleware.py`
  **逻辑**: `GET /user/wecom/availability|authorize|callback`；callback 用 `AuthJwt.set_access_token(token, httponly=False)` 下发 cookie 后 302；三路径加入公开路径集合
  **测试**: T009 全绿；`test/api/test_route_path_naming.py` 通过（路径不含 config）
  **覆盖 AC**: AC-15~AC-18
  **依赖**: T008, T009

### Wave 4 — 前端与收尾

- [x] **T011**: platform 登录入口
  **文件**: `src/frontend/platform/src/controllers/API/user.ts`, `pages/LoginPage/login.tsx`, `pages/LoginPage/loginBridge.tsx`, `contexts/userContext.tsx`
  **逻辑**: 调 availability；`enabled` 时渲染「企业微信登录」按钮（与现有 SSO/微信按钮同区）；读取 `?wecom_error=` 展示错误；落地后把 cookie 镜像进 `ws_token`（决策 2）
  **覆盖 AC**: AC-01, AC-05, AC-09, AC-18, AC-19
  **手动验证**: 无配置时无按钮；配好后 PC 扫码可登录并回到首页；企微内打开不弹扫码
  **依赖**: T010

- [x] **T012**: UI 文案三语 + 收尾验证
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 按钮/失败提示文案三语；`pnpm lint`、`pnpm typecheck`、`uv run ruff check`、`uv run pytest test/sso/`
  **覆盖 AC**: AC-18, AC-22
  **依赖**: T011

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。

- T008 偏离 → availability 返回 `login_path` 而非 `authorize_url`（`return_to` 只有浏览器知道），design §4.2 已更新。
- T008/T010 偏离 → 新增 design §5 坑 8（`LoginSyncRequest.ts` 必填，登录填当前时间）与坑 9（login-sync 拒绝抛 `HTTPException`，端点必须一并捕获）。
- T011 偏离 → platform 的 `LoginBridge` 受 `appConfig.isPro` 门控，自建入口改为独立组件 `wecomLogin.tsx` 无条件按 availability 渲染。
- T012 偏离 → **真实企微租户 E2E 未执行**（本机无企微租户与中间件）：以 5 个测试文件的 35 条 API/单元用例替代；首次部署必须按 design §7 的手工清单逐条走一遍（含坑 3 的改密验证）。
- 回归基线：`test/sso` 改动前 10 failed / 96 passed，改动后同为 10 failed（同一批用例）/ 131 passed，无新增失败。
