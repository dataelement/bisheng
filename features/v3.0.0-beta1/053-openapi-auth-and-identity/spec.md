# Feature: 开放 API 鉴权与身份传递（F053）

> 需求正文与验收标准的唯一真相是上游 PRD：`docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` v2.6。本 spec 只登记 beta1 范围裁定和本轮缺陷修复验收，技术实现见 [design.md](./design.md)。

**所属版本**: v3.0.0-beta1
**最后同步**: 2026-09-08
**依赖**: F048 权限运行时、既有 workstation / knowledge / public endpoints

## 1. 范围裁定

- `/api/v2/**` 只接受 `bs-sak-` / `bs-pat-`；JWT、cookie 和默认操作员不能替代密钥。
- 服务账号使用独立 `service_account` 表和 F048 `service_account:{id}` 主体，不创建影子 User/UserTenant。
- R8/P2（IP 白名单、限流、配额、幂等）移出本期；不预埋运行时代码或字段。
- 现有分享链接不改；工作流/助手免登录发布使用 `/api/v3` allowlist。
- 日常模式 v2 复用既有 v1 业务能力；不开放任务模式和异步执行。
- 身份头只接受 `X-On-Behalf-Of` / `X-End-User`；query、JSON、multipart、urlencoded 中的裸 `user_id` 均明确拒绝。

## 2. 本轮补充验收

- **AC-R1 管理操作反馈**：创建、启停、删除、密钥签发/吊销、资源授权/撤销在请求期间禁用重复触发；成功显示 Toast；失败显示统一错误反馈；破坏性操作先确认并说明影响。
- **AC-R2 资源选择**：服务账号详情直接列出全部资源授权；新增授权通过“资源类型下拉 + 名称/ID 搜索 + 资源勾选 + 权限模型下拉”完成，不要求管理员输入资源类型或资源 ID。创建时自动回授可单条撤销，但必须给出集成立即失去写权限的确认提示，并排除在“全部撤销”范围之外。
- **AC-R3 服务账号 FGA 闭环**：F048 允许 `service_account` 直接授权，并为其同步 Catalog、模型、动作、grant level、permission enabled 和资源模式技术标记。新资源实时投影；存量 CURRENT 资源可用 dry-run/apply 脚本补齐并对账。授权后 v2 具体资源动作生效，不再因主体技术标记缺失返回 18040。
- **AC-R4 QA 防越权**：QA 详情、更新、删除、追加和批量查询均以 QA 所属知识库为授权边界；读需要 visible，写需要 edit。失败时不得访问后续写 DAO、索引或异步任务，并按防枚举策略返回 403/404。
- **AC-R5 知识空间列表**：PAT、服务账号模式 D 和普通用户调用 `GET /api/v2/filelib/?type=3` 时，非空结果稳定包含 `user_name` 和 `actions`，不发生响应模型字段赋值异常。
- **AC-R6 v2 传输状态**：业务错误码保持不变；权限拒绝使用 HTTP 403，防枚举使用 404，权限依赖故障使用 503，其余请求类业务错误使用 400。逐调用审计同时记录业务码和 HTTP 状态；SSE 记录最终 success/failed/unknown，失败终态记录业务码。
- **AC-R7 废弃身份输入**：任一 v2 multipart 文件上传携带 `user_id` 时返回 HTTP 400 / 26019；字段不得被静默忽略，文件处理不得开始。
- **AC-R8 PAT 迁租户**：持有人活跃租户变化时，同一把未撤销 PAT 迁移凭据租户并清理缓存，调用能力随新租户权限生效；记录旧/新租户审计。重复同步可以修复中断状态。用户禁用/删除仍使 PAT 失效。
- **AC-R9 发布页语音闭环（2026-09-10）**：工作流、助手免登录页读取语音配置、录音转文字、点击朗读均使用 v3，不依赖登录态或 API Key。三个请求绑定当前已发布应用，沿用发布开关、默认操作员与资源租户；配置仅返回语音控件所需字段。ASR/TTS 按交互触发；配置缓存按应用隔离。现有 v2 密钥端点暂时保留，是否删除另待需求确认。

## 3. 非目标

- 不新增 UI / 状态管理库，不修改设计规范或共享组件视觉样式。
- 不让服务账号继承资源归属人的权限，不让模式 D 叠加服务账号权限。
- 不允许前端直接写 OpenFGA tuple；资源授权写入只走 F048 mutation。
- 不以 HTTP 200 包装 v2 的权限和依赖失败。

## 4. 验证要求

- 后端单元/契约测试覆盖 AC-R3～R8；MySQL + Redis + OpenFGA 集成在 CI 执行。
- platform 执行 `pnpm lint`、`pnpm typecheck` 和相关组件测试；三语 key parity 通过。
- 执行 `/e2e-test features/v3.0.0-beta1/053-openapi-auth-and-identity`，输出 API E2E 结果和服务账号页面手动验证清单。
