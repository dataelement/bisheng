# Feature: Gateway 到期提醒与到期降级

**关联 PRD**: [2.6 release · §Gateway 到期提醒功能](https://dataelem.feishu.cn/wiki/NEtywYou0iJYfhka6RwcXkGAnpd)
**优先级**: P1
**所属版本**: v2.6.0
**依赖**: 无（仅商业版 bisheng-gateway 生效）

> **范围边界**
> - **本次纳入**：
>   - License 到期不再强制停服：trial 过期 / license 配置异常时 Gateway 进入「降级模式」（拦业务请求、放行登录与静态资源），而非 `System.exit(0)`。
>   - Gateway 暴露 license 状态查询接口，platform 管理台超级管理员登录后顶部常驻 Banner 按到期等级提示。
> - **本次明确排除**：
>   - 后端 license 模块 / Redis 缓存 / Gateway→后端 HMAC 上报（采用简化方案，状态由前端经 Gateway 直接获取，见 design §3 决策 1）。
>   - pro（永久版）参与提醒：pro 永久有效，不展示 Banner。
>   - 开源版（无 Gateway）的 Banner：开源版无 license 概念，状态接口不可达即静默不展示。
>   - License 续期 / 重新激活流程：本期只读展示，不做续期入口。

---

## 1. 用户故事

作为 **平台超级管理员**，
我希望 **license 临近到期或已到期时，在管理后台显著看到剩余天数与到期提醒**，
以便 **及时续期，避免业务在毫无征兆的情况下中断。**

作为 **使用商业版的终端用户 / 调用方**，
我希望 **license 过期后系统不是直接「全线 502 / 进程消失」，而是给出明确的「授权已过期」提示且管理员仍能登录后台**，
以便 **快速定位是授权问题而非系统故障。**

---

## 2. 验收标准

### 2.1 到期降级（Gateway）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 系统 | trial license 到期后 Gateway 运行 | Gateway 进程**不退出**，进入降级模式 |
| AC-02 | 终端用户 | 降级模式下访问业务路由（`/api/v1/**`、`/api/v2/**`，白名单除外） | 返回统一的「license 已过期」错误体（明确错误码 + 文案），非 502 / 连接拒绝 |
| AC-03 | 超级管理员 | 降级模式下访问登录 / 鉴权 / 静态 / 健康检查 / license 状态接口 | 正常放行，可登录后台 |
| AC-04 | 系统 | license 解密失败或未配置 | 与到期同样进入降级模式（不 `System.exit`），状态标记为过期/未知 |

### 2.2 状态查询与等级映射

- **AC-05** — THE SYSTEM SHALL 在每次 license 检查（启动一次 + 每小时整点）后，把 `{version, expireDay, daysRemaining, severity, checkedAt}` 写入 Gateway 内存状态。
- **AC-06** — WHEN 前端请求 license 状态接口, THE SYSTEM SHALL 返回当前内存状态（含 severity）。
- **AC-07** — THE SYSTEM SHALL 按剩余天数映射 severity：`>30 → normal`、`(7,30] → warning`、`(0,7] → critical`、`≤0 → expired`、`pro / 无 license / 状态缺失 → unknown`。

### 2.3 前端 Banner（platform）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-08 | 超级管理员 | 登录 platform 后台 | severity 为 warning/critical/expired 时，顶部常驻 Banner 按等级上色展示剩余天数 / 已过期文案 |
| AC-09 | 超级管理员 | severity 为 normal / unknown，或状态接口不可达（开源版/404） | **不**展示 Banner，不报错 |
| AC-10 | 非超级管理员（含组/部门管理员、普通用户） | 登录 platform 后台 | **不**展示 Banner |
| AC-11 | 任意角色 | 查看 Banner 文案 | 中 / 英 / 日三语言齐全 |

---

## 3. 边界情况

- Gateway 多实例时，各实例按自身内存状态各自应答（license 检查逻辑天然每实例独立，无需共享）。
- license 状态接口在降级模式下必须仍可访问（否则 Banner 取不到「为什么过期」）—— 须在降级过滤器白名单内。
- severity = `warning` 含 `daysRemaining` 恰为 30；`critical` 含恰为 7；`expired` 含恰为 0（边界归属见 design §3）。
- pro 版本 `daysRemaining` 为空，前端不渲染 Banner。

---

## 4. 设计与实现（指针，不复制）

| 你想知道 | 去哪看 |
|---|---|
| 为什么砍掉后端模块 / Redis / HMAC（简化方案对比） | design.md §3 决策 1 |
| 降级白名单、severity 阈值、状态接口契约 | design.md §4 |
| Gateway 现有 license 校验 / 过滤器 / Controller 模式 | design.md §4.3 |
| 任务拆解、文件清单、执行顺序 | tasks.md |

---

## 相关文档

- 设计真相: [design.md](./design.md)
- 执行与落档: [tasks.md](./tasks.md)
- 架构文档: `docs/architecture/11-gateway.md`
- PRD: https://dataelem.feishu.cn/wiki/NEtywYou0iJYfhka6RwcXkGAnpd
