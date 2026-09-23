# DSH 工作台本人弹窗与部门展示修订

状态：2026-09-10 用户明确批准“本人查询和逐条吊销接口”。交付为两仓 feature 分支提交推送；不部署或修改 109。

## 产品边界

- client 工作台的桌面端及移动端头像菜单新增 DSH Desktop 弹窗，与现有消息/审批入口采用相同菜单与弹窗组件。
- 弹窗提供打开客户端、下载、本人的分页登录会话及按模型本月用量；只列出当前用户已授权模型，显示提供方 / 实际模型名。
- 吊销需要用户确认，只使所选会话及其刷新令牌失效。其他设备、固定席位、授权、额度上限和历史用量不变。相同 session_id 重试幂等，不需要新操作 ID。
- 未登录过 DSH 的毕昇用户可打开弹窗，会话为空；没有授权模型时提示联系管理员。读取不分配席位，不新增授权或额度。
- 部署开关与业务开关继续沿用既定职责。业务关闭后菜单消失、已打开的弹窗关闭；服务端每次请求检查开关。浏览器每 30 秒或回到窗口时刷新状态，短暂旧页面也不能绕过服务端拒绝。
- 管理端席位表将租户列替换为主部门名称；无部门显示“未设置部门”。“无登录会话”后不显示 0。
- desktop-login 授权文案显示用户名及主部门；无部门不显示空括号。不显示租户。
- 部门仅在毕昇侧批量读取，永不进入 Gateway Profile / Outbox，也不恢复部门筛选、部门授权、用户组、限流、PAT、批量吊销或 License 界面配置。

## 本人接口

以下均位于同一毕昇 Nginx origin，通过毕昇浏览器 JWT / HttpOnly Cookie 认证。服务端从 JWT 取得 tenant_id / user_id 并实时验证有效用户及租户；不接受页面提供的身份或管理范围。成功使用毕昇标准 `status_code=200, data=...` 包装；失败使用现有 DSH 错误封装，所有响应 no-store。

| 接口 | 输入 | data |
|---|---|---|
| GET /api/v1/dsh/me/profile | 无 | username, department_name（可空） |
| GET /api/v1/dsh/me/sessions | cursor 可空；limit 默认 20，1–100 | items、next_cursor、has_more |
| POST /api/v1/dsh/me/sessions/{session_id}/revoke | UUID 路径，JSON 空对象 | session_id、state=REVOKED |
| GET /api/v1/dsh/me/usage | 无 | month、billing_timezone、source、as_of、unknown_pending、models |

会话字段：session_id、device_label（可空）、client_version（可空）、state、created_at、last_seen_at（可空）、expires_at。保留过期/已吊销历史，只有 ACTIVE 行显示吊销操作。时间采用 RFC3339。

用量 models 每行：model_id、name、limit、used、remaining。额度不共用；未知值为 null，页面用“—”，不得伪装成 0。source 为 live / persisted / unavailable；页面标识快照和更新时间。unknown_pending 表示未获取用量的调用次数。月度范围沿用 Asia/Shanghai。

吊销 POST 校验精确 Origin=platform_public_url、Sec-Fetch-Site 与 application/json，避免 Cookie CSRF；会话归属在 Gateway 按 installation / tenant / user 再校验。越权和不存在会话统一拒绝，不返回他人会话信息。

## Gateway 内部增量

仅新增 HMAC 专用接口，复用已有用户同步密钥与 HMAC nonce 防重放：

- POST /api/internal/dsh/self/sessions：{tenant_id,user_id,cursor,limit}，回分页 SessionItem（内部仍含 seat_id）。根据本人查席位，不允许传入管理员 scope 或目标 seat_id。
- POST /api/internal/dsh/self/sessions/revoke：{tenant_id,user_id,session_id}。检查归属后复用已有 session repository 吊销事务、seat→session 锁顺序与 refresh family 失效，不改席位或 grant_version。
- `/api/v1/dsh/me/*` 的明确路由交给毕昇认证，其他 API 路由保持原行为。
- 无表结构和部署配置变更。毕昇和 Gateway 需使用本次配套代码后启用本人会话功能；不改 DSH 客户端 0.4.0 登录/模型调用协议。

## 调用顺序

1. 工作台读取 browser-config，业务开启才展示头像菜单入口。
2. 用户打开弹窗，并行读取 me/sessions 与 me/usage；下载地址沿用 browser-config。
3. 打开客户端使用 `dsh-desktop://login?server=<Nginx origin>`，不包含 `/workspace`。
4. 用户点击某设备“吊销”并确认 → 同源 POST → 毕昇检查身份与开关 → HMAC 到 Gateway 检查归属 → 吊销该会话/刷新令牌 → 刷新会话列表。
5. 该设备下一次 introspect/refresh 被拒绝，需要重新登录；其他设备继续使用，席位占用不变。已进入执行的模型请求仍按原结算路径处理。

## 验证

- Python：本人身份固定、匿名/关闭/用户迁移/禁用拒绝、CSRF、部门主次关系与 Outbox 无部门、仅授权模型用量；含独立 MySQL 回归。
- client：无登录会话、无授权、下载未配置、单设备吊销后刷新、未知用量、全局关闭时关闭弹窗。
- platform：部门授权文案、无空括号、席位列与无会话 0、两层开关及管理页回归。
- Gateway：HMAC 必需、跨用户/租户拒绝、同一会话幂等吊销及真实 MySQL 刷新令牌/多设备隔离；SQL 可移植性检查。
- 部署后的浏览器视觉与实际 DSH 客户端联调由用户部署后执行；本次没有修改 109。

验证结果：后端 43 passed（含独立 MySQL），platform 20 passed，client 4 passed，Gateway 16 passed（含真实 MySQL 单设备吊销与刷新令牌轮换）。pnpm lint / typecheck / check-i18n、架构守卫和 diff 检查通过。client 本机 Jest 的可选 canvas 原生模块缺失，运行时禁用该可选模块完成 DOM 测试；未改动项目测试环境或 canvas 业务。未进行 109、DM 实机或完整浏览器视觉联调。
