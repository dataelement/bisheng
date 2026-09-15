# v3 免登录发布 API

v3 仅承接已发布工作流和知识助手的免登录访问。调用方不需要登录态，也不应携带 API Key。服务端会校验系统默认操作员的 guest access 开关、默认操作员状态、资源发布状态和会话归属。

## HTTP allowlist

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v3/assistant/info/{assistant_id}` | 获取发布页助手详情 |
| `GET` | `/api/v3/flows/{flow_id}` | 获取发布页工作流详情 |
| `GET` | `/api/v3/chat/history` | 获取当前发布会话历史 |
| `POST` | `/api/v3/chat/gen_title` | 生成当前发布会话标题 |
| `GET` | `/api/v3/llm/workbench` | 读取当前发布应用的语音模型 ID |
| `POST` | `/api/v3/llm/workbench/asr` | 录音转文字 |
| `POST` | `/api/v3/llm/workbench/tts` | 文字朗读 |

## WebSocket allowlist

| Path | Purpose |
|---|---|
| `/api/v3/workflow/chat/{workflow_id}` | 已发布工作流对话 |
| `/api/v3/assistant/chat/{assistant_id}` | 已发布知识助手对话 |

除以上七个 HTTP 和两个 WebSocket 路由外，v3 不提供其它端点。例如 `/api/v3/assistant/list` 必须返回 404。

## Security contract

- v3 不读取 JWT 或 `bs-sak-` / `bs-pat-` API Key，也不回落到 v2 鉴权。
- 不得发送 `X-On-Behalf-Of` 或 `X-End-User`；匿名调用方不能声明自然人身份。
- `history`、`gen_title`、WebSocket 停止和续聊会同时校验 tenant、`public_v3` 来源、目标资源和会话 ID；猜中其它来源的 `chat_id` 仍返回 404。
- 工作流执行、输入和停止沿用发布页的 WebSocket 消息协议。
- 语音配置/ASR/TTS 均要求 query `flow_id` 绑定已发布资源；配置只返回 `asr_model.id` / `tts_model.id`。
- guest access 关闭、默认操作员失效或资源未发布时，请求会被拒绝。

## 执行身份

访客没有账号，所以每个 v3 请求都以**默认操作员**（`initdb_config` 的 `default_operator.user`）的身份执行。

**该账号的真实身份被完整继承**：真实角色、真实全局超级管理员标记，管理员短路照常生效。平台不在这条通道上人为降权。

这条口径的理由与边界：

- **它等于今天的行为。** 免登录链接的工作流对话此前就走 `init_login_user` 继承真实身份，改成剥权反而是行为变更。
- **权限边界由配置决定，不由代码兜底。** 这个账号的权限范围就是访客能触达的范围。客户若认为风险不可接受，正确做法是不要把它配成超级管理员，而不是让平台在通道上偷偷降权 —— 后者会让「我明明授权了却不生效」变成一类无法自解释的故障。
- **随之失效的保护**（配成超级管理员时）：资源可见性判定、`use` 判定、以及 WebSocket 逐条消息的运行期撤权保护都会被短路。残余护栏仍在：资源必须已上线、URL 必须给出精确 id、v3 没有任何列表端点、租户被锁死为资源所属租户。
- **`can_share` 恒为 `false`**：匿名通道没有创建分享链接的入口，超级管理员短路下的 `true` 是误导，适配层统一覆盖。
- **服务账号永不继承特权**：异步执行段从快照重建身份时按主体类型闸住。

身份解析在存活校验**之后**：默认操作员被删除、不是该租户成员、成员状态非 active、或租户非 active 时，请求在解析特权之前就被拒绝。授权后端不可用时同样拒绝（fail closed）。

## 同步段与异步段的一致性

工作流对话分两段执行：WebSocket 握手在后端进程内，实际运行在 Celery worker 内。握手期解析出的特权事实（超级管理员标记、租户管理员集合）随执行快照传到 worker，两段依据同一份身份判定。

快照新增的两个字段带默认值，因此升级前已入队的消息仍可校验；v2 的服务账号快照不写这两个字段，行为不变。**约束**：worker 与后端必须同版本发布，或先升 worker —— 旧 worker 收到带新字段的消息会校验失败。

## 拒绝的呈现

| 情况 | 业务码 | HTTP |
|---|---|---|
| 链接无效、资源不存在、类型不符、助手已删除 | `26101` | 404 |
| 应用已下线 | `26102` | 404 |
| 免登录访问开关关闭，或默认操作员不可用 | `26103` | 403 |
| 匿名请求携带身份标识请求头 | `26104` | 403 |

两个 404 共用同一个传输状态，差异只在响应体的业务码里，访客据此看到「应用已下线」还是「链接无效」两种不同的提示页。

「类型不符」与「已删除」归入链接无效而非已下线：助手 id 在工作流侧探测时必然不匹配，若记成下线会把整条链路误判。两侧探测中只要任一侧探到下线，结果即为下线。

**WebSocket 必须先 accept 再报错。** 握手完成前调用 close，服务端会以 HTTP 错误应答升级请求，浏览器只能拿到空 reason 的 1006，拒绝原因根本传不到前端。正确顺序是 accept、发送一帧 `{"category":"error","type":"end","message":{...}}`、再以 1008 关闭。

## 与 v2 的边界

相同工作流或助手能力在 `/api/v2` 下是密钥鉴权版本，必须携带：

```http
Authorization: Bearer <bs-sak-or-bs-pat-key>
```

platform“对外发布 → API访问”恢复完整 v2 对接文档，与免登录页面加载链路分开；v2 接口不能匿名调用。现有分享链接的参数、凭据和数据模型不属于 v3，保持原行为。

2026-09-11 范围纠正：移除 `POST /api/v3/assistant/chat/completions`、`POST /api/v3/workflow/invoke`、`POST /api/v3/workflow/stop`；这三个 HTTP 接口不是免登录页面加载或聊天所需，现仅保留其 v2 密钥版本。
