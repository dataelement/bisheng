# Design: Gateway 到期提醒与到期降级

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-24（初版）

---

## 1. 目标与非目标

- **目标**：让 license 到期从「Gateway 进程 `System.exit(0)` 硬停服」改为「降级模式（**只拦网关自处理的付费接口、透传 bisheng 后端的接口照常放行**）+ 管理后台常驻 Banner 提示」，给管理员留出感知与续期窗口，同时不影响免费的 bisheng 核心。
- **非目标**：不动后端 license 校验语义（后端本就对 license 无感）；不做后端缓存 / 上报 / HMAC；不做续期入口；pro 版与开源版不展示 Banner。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7。本功能特有约束：
  - **License 私钥只在 Gateway**：能解密、判断到期的只有 `bisheng-gateway`（RSA 私钥硬编码在 `LicenseLoader.java`），后端与前端对 license 一无所知。任何「让前端/后端知道到期状态」的方案都必须由 Gateway 提供数据。
  - **部署形态**：Gateway 仅商业版（PRO）存在，作为前端与后端之间的反向代理；开源版无 Gateway。拓扑：`浏览器 → Nginx → 前端 → Gateway → Backend`，**所有 `/api/**` 均先过 Gateway**（见 `docs/architecture/11-gateway.md`）。
  - **前端不直连后端**：PRO 模式下 platform 的 `/api/**` 流量穿过 Gateway，这是简化方案成立的前提。

---

## 3. 方案对比与选定

### 决策 1：License 状态如何送达前端 Banner —— 砍掉后端模块

- **备选**：
  - A.（PRD 原方案）Gateway 每小时 HMAC 上报后端 → 后端新建 `bisheng/license/` 模块 + Redis 缓存 `license:status` → 前端读后端。优点：Gateway 不可达时管理员仍能从后端看到过期原因；缺点：新增后端模块 + Redis + 一套从零写的 HMAC 校验（PRD 误以为后端已有 `/api/v1/internal/sso/login-sync` 可复用，实测后端无此端点、无任何 HMAC 校验），改动面最大。
  - B.（选定）Gateway 自处理一个 license 状态接口，前端登录后直接经 Gateway 拿状态。后端、Redis、HMAC 全部不碰。
- **选定**：B
- **原因**：PRO 模式下 platform 流量本就穿过 Gateway（决策前已核实拓扑 + Gateway 已有 `/api/getkey`、`/api/group/*`、`/api/sensitive/*` 等「自处理不转发」的 Controller 先例），所以「前端经 Gateway 取状态」天然可行，无需后端中转。砍掉整个后端 license 模块 + Redis + HMAC，工作量与风险大幅下降。
- **代价 / 何时该重新考虑**：Banner 状态依赖请求那一刻 Gateway 可达；若 Gateway 彻底不可达（非降级、是真挂），前端取不到状态、Banner 不展示——但此时整个产品入口也不通，属另一类故障。若未来出现「Gateway 挂了也要在独立后台解释过期」的硬需求，回到方案 A。

### 决策 2：severity 阈值计算放在哪

- **备选**：A. 前端按 daysRemaining 算；B. Gateway 算好直接下发。
- **选定**：B（Gateway 算）。
- **原因**：阈值是业务规则，集中在一处（Gateway）避免散落前端；前端只渲染。边界归属：`warning` 含 30，`critical` 含 7，`expired` 含 0（即 `daysRemaining <= 0`）。

### 决策 3：license 配置异常 / 解密失败的处理

- **备选**：A. 保持 `System.exit(0)`；B. 同样降级。
- **选定**：B（降级，标记 expired/unknown）。
- **原因**：硬退出同样导致「全线不可达、无从解释」，与本 feature 目标相悖。配置缺失视作无有效授权 → 进入降级、severity 记为 `expired`；具体取 `expired`（无有效授权应拦网关付费接口）。

### 决策 4：降级拦谁、放谁 —— 只拦网关付费接口，透传 bisheng 放行

- **备选**：
  - A.（最初理解，已废弃）拦所有业务路由 `/api/v1,v2`，只放行登录/状态/静态 —— 即「活着但拒绝业务、放行登录」。
  - B.（选定）只拦**网关自处理的付费接口**（`/api/oauth2`、`/api/sensitive`、`/api/group`、`/api/getkey` 等网关增值能力），**透传给 bisheng 后端的 `/api/v1`、`/api/v2` 照常放行**；`/api/license/status` 始终放行。
- **选定**：B
- **原因**：付费的是**网关自身的增值能力**（SSO、敏感词、流控、用户组同步…），不是对 bisheng API 的代理透传。bisheng 核心是开源免费的，license 过期不应拦它。所以过期只停用网关付费功能、核心产品继续可用；管理员经透传的登录正常进后台看 Banner。
- **判定规则**：`/api/*` 路径中，凡不属于 `/api/v1`、`/api/v2`（代理）且不是 `/api/license`（状态）的，即视为网关付费接口 → 拦；其余一律放行。
- **何时该重新考虑**：若未来把某些付费能力放进 `/api/v1` 代理族下，需改判定规则（不能再简单按前缀）。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

`LicenseLoader.checkDate()（启动@Order(1) + ReloadTask 每小时）→ 解密 license → 写内存状态 LicenseStatusHolder{version,expireDay,daysRemaining,severity,expired} → (a) LicenseExpiredGlobalFilter 读 expired 决定拦/放 (b) LicenseController GET /api/license/status 下发状态 → platform LicenseBanner 渲染`

- **检查入口**：`LicenseLoader.checkDate()`，启动 `ApplicationRunner @Order(1)` + `ReloadTask.java:25` 的 `@Scheduled(cron="0 0 * * * ?")` 每小时整点。
- **改造点**：`checkDate()` 每次跑都把结果写入 `LicenseStatusHolder`（不止过期时）；两处 `System.exit(0)`（`LicenseLoader.java:84` trial 过期、`:95` 配置异常）改为置 `expired=true` + 记日志。

### 4.2 关键数据结构 / 字段约定

**状态接口契约** —— `GET /api/license/status`（Gateway 自处理，不转发后端）：

```json
{ "version": "trial", "expireDay": "2026-09-15", "daysRemaining": 27, "severity": "warning", "checkedAt": "2026-06-24T10:00:00+08:00" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | `trial` / `pro` |
| `expireDay` | string `yyyy-MM-dd` | trial 到期日；pro 可为 null |
| `daysRemaining` | int / null | 剩余天数；pro 为 null |
| `severity` | string | `normal`/`warning`/`critical`/`expired`/`unknown` |
| `checkedAt` | string ISO8601 | 最近一次检查时间 |

**severity 映射**：`>30 normal`、`(7,30] warning`、`(0,7] critical`、`<=0 expired`、pro/缺失 `unknown`。

**降级错误体** —— 网关付费接口被拦时返回（沿用 Gateway 现有响应风格，HTTP 200 + 业务错误码 `11001`，参照 `PathRateGlobalFilter` 限流返回）：
```json
{ "data": "", "status_code": 11001, "status_message": "软件授权已过期，请联系管理员续期" }
```

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `LicenseLoader.java`（改） | 解密 license、算 daysRemaining/severity、写 Holder、置 expired | 不再 `System.exit` |
| `LicenseStatusHolder.java`（新，@Component） | 持有最近一次 license 状态（线程安全，`volatile`/`AtomicReference`） | 不做解密 |
| `LicenseController.java`（新，@RestController） | `GET /api/license/status` 读 Holder 下发 | 不暴露解密内容 / 私钥 |
| `LicenseExpiredGlobalFilter.java`（新，**`WebFilter`**+Ordered，类名沿用历史） | expired 时拦网关自处理付费接口、放行透传(`/api/v1,v2`)与 `/api/license` | 不做限流 / 鉴权 |
| platform `controllers/API/license.ts`（新） | GET `/api/license/status`，404/错误吞掉返 null | 不直接 import axios |
| platform `LicenseBanner`（新） | 超管可见，按 severity 渲染 | 不算阈值 |

**Gateway 现有可复用先例**：
- 自处理 Controller：`SensitiveWordsController` / `UserGroupController`（`@RestController`，路径 `/api/sensitive/*`、`/api/group/*` 不转发后端）—— `LicenseController` 仿此。
- 短路返回写响应体：参照 `PathRateGlobalFilter`（限流时 HTTP 200 + 业务错误码短路）。但 `LicenseExpiredGlobalFilter` 用的是 **`WebFilter`** 而非 GlobalFilter（原因见 §5 坑 7），order 取高优先级（更早拦截）。
- Gateway 路由：`/api/v1/**`、`/api/v2/**` 默认代理后端；自处理路径需确保不落入代理（`/api/license/*` 不在 `/api/v1` 前缀下，天然由 Controller 接管）。

**降级拦截范围**（见 §3 决策 4）：过期时**只拦网关自处理的付费接口**——`/api/*` 中不属于 `/api/v1`、`/api/v2`（代理透传）且不是 `/api/license`（状态）的路径（如 `/api/oauth2`、`/api/sensitive`、`/api/group`、`/api/getkey`）。**放行**：`/api/v1/**`、`/api/v2/**`（透传 bisheng 核心，免费不拦）、`/api/license/status`、非 `/api/` 路径（静态 / actuator 健康检查）。判定逻辑见 `LicenseExpiredGlobalFilter.isGatewayPaidEndpoint()`。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | PRD 说后端有 `/api/v1/internal/sso/login-sync` 的 HMAC 校验可复用 —— **后端实际不存在该端点、无任何 HMAC 校验、settings 无 gateway_hmac_secret** | 照 PRD 走会发现「复用」无从复用，被迫从零写后端 HMAC | 简化方案直接绕开后端，不需要 HMAC |
| 2 | Gateway license 状态接口必须放在 `/api/v1/**` 之外（如 `/api/license/*`），否则会被默认路由代理到后端而非 Gateway 自处理 | 接口被转发到后端 → 后端无此路由 → 404 | `LicenseController` 用 `/api/license/*` 路径 |
| 3 | 状态接口必须排除在降级拦截外 | 过期后 Banner 取不到状态，反而看不到过期提示 | `LicenseExpiredGlobalFilter.isGatewayPaidEndpoint()` 显式放行 `/api/license` |
| 6 | 降级只拦网关付费接口，**不能拦透传 bisheng 的 `/api/v1,v2`** | 拦错了会把免费核心也停掉，与「付费的才是网关」相悖；普通用户聊天等会全断 | `isGatewayPaidEndpoint()` 对 `/api/v1,v2` 返 false |
| 7 | **Spring Cloud Gateway 的 `GlobalFilter` 只对代理路由生效，看不到网关自处理的 `@RestController` 端点**（getkey/sensitive/group/license 由 DispatcherHandler 直接分发，不进 gateway 过滤链） | 用 GlobalFilter 实现会发现付费 controller 接口过期时根本拦不住（返 200 不返 11001） | 必须用 **`WebFilter`**（包住整个 WebFlux 链，代理路由 + controller 都过）—— 见 `LicenseExpiredGlobalFilter implements WebFilter` |
| 4 | `checkDate()` 当前仅在过期时动作，平时不记状态 | warning/critical（未过期）阶段 Holder 为空 → Banner 拿不到剩余天数 | `checkDate()` 每次跑都写 Holder |
| 5 | platform 前端在开源版直连后端、无 Gateway，`/api/license/status` 会 404 | 若不吞错，控制台报错 / 弹窗 | `license.ts` 对非 2xx / 空响应返 null，Banner 静默 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/license/status` | HTTP API（Gateway 自处理） | platform `LicenseBanner` |
| 降级错误体 `{status_code, status_message}` | HTTP 响应 | 终端用户 / 调用方（过期时） |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| PRO 模式 platform 流量穿过 Gateway | 部署拓扑 | 若某部署让 platform 直连后端，Banner 取不到状态（需回方案 A） |
| `LicenseLoader` 解密结果 `{version, expireDay}` | Gateway 内部 | license JSON 字段名变更会影响 daysRemaining 计算 |

---

## 7. 测试与可观测

- **Gateway 单元测试**：daysRemaining/severity 映射（含 30/7/0 边界）；`LicenseExpiredGlobalFilter` —— 网关付费接口（oauth2/sensitive/group/getkey）被拦 vs 透传 `/api/v1,v2` 及 `/api/license` 放行；配置异常进入降级而非退出。
- **手动验证**：构造一张已过期 trial license（或改系统时间 / mock `LicenseLoader`），启动 Gateway → 确认进程不退出、**网关付费接口返 11001 错误体**、**透传 `/api/v1,v2` 与 `/api/license/status` 正常放行**；超管登录 platform 看到红色置顶 Banner；改成 20 天后到期看黄色 warning。
- **前端**：Banner 按 severity 渲染快照；非超管 / normal / 404 不渲染。
- **可观测**：降级触发、上次检查结果打 INFO 日志（含 daysRemaining/severity）。

---

## 8. 后续改进 / 不打算做的事

- 不做后端缓存兜底（Gateway 彻底挂时无法解释过期）——出现硬需求再回方案 A。
- 不做续期入口 / license 在线激活。
- pro 版到期提醒（pro 永久有效，暂无意义）。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-24 | 初版 | feature 设计定稿（用户选定简化方案 B） |
