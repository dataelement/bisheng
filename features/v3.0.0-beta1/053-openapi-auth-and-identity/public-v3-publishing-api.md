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

## 与 v2 的边界

相同工作流或助手能力在 `/api/v2` 下是密钥鉴权版本，必须携带：

```http
Authorization: Bearer <bs-sak-or-bs-pat-key>
```

platform“对外发布 → API访问”恢复完整 v2 对接文档，与免登录页面加载链路分开；v2 接口不能匿名调用。现有分享链接的参数、凭据和数据模型不属于 v3，保持原行为。

2026-09-11 范围纠正：移除 `POST /api/v3/assistant/chat/completions`、`POST /api/v3/workflow/invoke`、`POST /api/v3/workflow/stop`；这三个 HTTP 接口不是免登录页面加载或聊天所需，现仅保留其 v2 密钥版本。
