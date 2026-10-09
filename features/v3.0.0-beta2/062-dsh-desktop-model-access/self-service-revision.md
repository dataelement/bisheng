# DSH 工作台与部门展示

2026-10-09 Beta3 产品修订。当前席位与登录管理范围见 [席位管理修订](./seat-management-revision.md)。

## 产品边界

- client 工作台通过桌面端及移动端头像菜单打开客户端弹窗，提供打开客户端、下载及本人的年度模型调用和 Token 用量。
- 管理端席位表展示用户、主部门、席位状态和操作。员工获得席位后自行登录使用。
- 登录会话和设备由内部认证模块维护；企业管理与工作台功能聚焦资格和模型使用。
- 浏览器读取身份与用量使用毕昇 JWT / HttpOnly Cookie，身份来自服务端，响应采用标准包装与 no-store。
- 部署开关和业务开关沿用现有职责。浏览器每 30 秒或回到窗口时刷新状态，业务关闭后菜单与弹窗退出。
- 部门仅在毕昇侧读取，用于当前用户身份和管理表展示。Gateway Profile 与 Outbox 继续维护最小身份资料。

## 本人接口

| 接口 | data |
|---|---|
| GET /api/v1/dsh/me/profile | username, department_name |
| GET /api/v1/dsh/me/usage | month, billing_timezone, source, as_of, unknown_pending, models |
| GET /api/v1/dsh/me/usage-summary | 本人年度消息数、调用数和 Token 时间聚合 |

本人会话列表与逐会话吊销接口在本次修订中移除。授权和模型调用继续沿用客户端认证协议。下载地址与启动深链来自 browser-config。

## 验证

历史 2026-09-10 本人会话管理交付已由本次 Beta3 产品范围替代。当前自动化、基线对照与现场验收边界以 [席位管理修订](./seat-management-revision.md) 为准。
