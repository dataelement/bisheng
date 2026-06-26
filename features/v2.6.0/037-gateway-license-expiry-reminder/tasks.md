# Tasks: Gateway 到期提醒与到期降级

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认简化方案 B |
| design.md | ✅ 已评审 | 接手第一入口 |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🔲 未开始 | 0 / 9 完成 |

---

## 开发模式

- **两个独立仓库**：Gateway 改动在 `/Users/shanghang/dataelem/bisheng-gateway`（Java / Maven），前端在 `/Users/shanghang/dataelem/bisheng`（platform）。提交分别 commit。
- **后端 Python 零改动**（简化方案，见 design §3 决策 1）。
- Gateway Test-First：severity 映射与过滤器白名单逻辑写单测；前端手动验证。

---

## Tasks

### Wave 1 — 无依赖（可并行）

- [ ] **T001**: LicenseStatusHolder + severity 映射
  **仓库/文件**: `bisheng-gateway` · `src/main/java/com/dataelem/gateway/config/LicenseStatusHolder.java`（新，`@Component`）
  **逻辑**: 线程安全持有最近一次 license 状态 `{version, expireDay, daysRemaining, severity, expired, checkedAt}`（`AtomicReference` 或 `volatile` 字段）。提供 `update(...)` 与 getter。severity 映射静态方法：`>30 normal / (7,30] warning / (0,7] critical / <=0 expired / pro·null unknown`（边界：30→warning、7→critical、0→expired）。
  **覆盖 AC**: AC-05, AC-07
  **依赖**: 无

- [ ] **T002**: 前端 i18n 文案（三语言）
  **仓库/文件**: `bisheng` · `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/*.json`
  **逻辑**: 新增 license 提醒文案 key：剩余天数（warning/critical）、已过期（expired）、续期提示。三语言齐全。
  **覆盖 AC**: AC-11
  **依赖**: 无

### Wave 2 — 依赖 T001（Gateway 核心改造，可并行）

- [ ] **T003**: LicenseLoader 改造 —— 写状态 + 去 System.exit
  **仓库/文件**: `bisheng-gateway` · `src/main/java/com/dataelem/gateway/config/LicenseLoader.java`
  **逻辑**: `checkDate()` 每次跑都解出 `{version, expireDay}`、算 `daysRemaining = expireDay - today`（pro→null）、算 severity，写入 `LicenseStatusHolder`。两处 `System.exit(0)`（trial 过期 `:84`、配置异常/解密失败 `:95`）改为 `holder.markExpired(...)` + 记日志，不退出（配置异常 severity 记 `expired`，见 design §3 决策 3）。
  **覆盖 AC**: AC-01, AC-04, AC-05
  **依赖**: T001

- [ ] **T004**: LicenseController —— GET /api/license/status
  **仓库/文件**: `bisheng-gateway` · `src/main/java/com/dataelem/gateway/controller/LicenseController.java`（新，`@RestController`，仿 `SensitiveWordsController`）
  **逻辑**: `GET /api/license/status` 读 `LicenseStatusHolder` 返回 JSON `{version, expireDay, daysRemaining, severity, checkedAt}`。路径在 `/api/v1` 之外，确保 Gateway 自处理不转发后端（design §5 坑 2）。
  **覆盖 AC**: AC-06
  **依赖**: T001

- [ ] **T005**: LicenseExpiredGlobalFilter —— 降级拦截
  **仓库/文件**: `bisheng-gateway` · `src/main/java/com/dataelem/gateway/filter/LicenseExpiredGlobalFilter.java`（新，`GlobalFilter, Ordered`，仿 `PathRateGlobalFilter`）
  **逻辑**: `holder.isExpired()` 为真时，**只拦网关自处理的付费接口**（`isGatewayPaidEndpoint()`：`/api/*` 中非 `/api/v1`、`/api/v2`、`/api/license` 的，如 `/api/oauth2`、`/api/sensitive`、`/api/group`、`/api/getkey`）→ 返回降级错误体（HTTP 200 + `{data:"", status_code:11001, status_message}`）；**放行**透传 `/api/v1/**`、`/api/v2/**`（bisheng 核心）、`/api/license/status`、非 `/api/` 路径（静态/actuator）。order 取高优先级。详见 design §3 决策 4。
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T001

### Wave 3 — 验证与前端

- [ ] **T006**: Gateway 单元测试
  **仓库/文件**: `bisheng-gateway` · `src/test/java/com/dataelem/gateway/...`
  **逻辑**: severity 映射边界（31/30/8/7/1/0/-1、pro、null）；`LicenseExpiredGlobalFilter` —— 网关付费接口（oauth2/sensitive/group/getkey）被拦 vs 透传 `/api/v1,v2` 及 `/api/license` 放行；配置异常进入降级而非退出（mock `BishengConfig.getLicense` 返坏值，断言不抛/不退出、holder.expired=true）。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-07
  **依赖**: T003, T004, T005

- [ ] **T007**: 前端 license 状态 controller
  **仓库/文件**: `bisheng` · `src/frontend/platform/src/controllers/API/license.ts`（新）
  **逻辑**: `getLicenseStatus()` GET `/api/license/status`，走 `@/controllers/request`（禁止直接 import axios）。非 2xx / 404 / 空响应 → 返回 null（开源版/无 Gateway 静默，design §5 坑 5）。
  **覆盖 AC**: AC-09
  **依赖**: T004（契约）

- [ ] **T008**: LicenseBanner 组件 + MainLayout 接入
  **仓库/文件**: `bisheng` · `src/frontend/platform/src/layout/MainLayout.tsx` + 新增 `LicenseBanner` 组件（复用 `components/bs-ui/alert.tsx`）
  **逻辑**: MainLayout 顶部新增常驻条；仅超级管理员可见（`user.role === 'admin'` super admin）。拉 `getLicenseStatus`，按 severity 渲染：warning 黄 / critical 红 / expired 红+置顶；normal/unknown/null 不渲染。文案用 T002 i18n。
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-11
  **依赖**: T002, T007

### Wave 4 — 端到端手动验证

- [ ] **T009**: 端到端手动验证
  **逻辑**: 构造过期 / 临期 trial license（改测试日期或 mock `LicenseLoader`），启动 Gateway：① 过期后进程不退出；② **网关付费接口返 11001 错误体、透传 `/api/v1,v2` 与 `/api/license/status` 正常放行**；③ 超管登录 platform 看到红色置顶 Banner；④ 改 20 天临期看黄色 warning；⑤ 非超管不展示。
  **覆盖 AC**: AC-01~AC-11
  **依赖**: T006, T008

---

## 实际偏差记录

> 实现期与 design 的偏差在此留一行指针（论证写 design，不重复）。

（待填）
