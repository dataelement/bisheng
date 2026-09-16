# 模型协议面（OpenAI 兼容）

`POST /api/v2/model/v1/chat/completions` · `GET /api/v2/model/v1/models`

平台把自己已配好的模型以 **OpenAI 兼容协议**对外开一条直连面：拿一个 base URL 和一把服务账号密钥，官方 `openai` 客户端、各家 coding agent、以及托管在平台上的应用都能零改造调用，不必再各自申请厂商 key、也不用把厂商 key 复制到第二个地方。

本文是这条接口的对外契约。实现侧的决策与坑见 [`features/v3.0.0/051-model-protocol-gateway/design.md`](../../features/v3.0.0/051-model-protocol-gateway/design.md)。

---

## 1. 接入

| 项 | 值 |
|---|---|
| base URL | `{平台地址}/api/v2/model/v1`，**末尾的 `/v1` 是 base 的一部分**，官方客户端只会在其后拼 `/chat/completions` 与 `/models` |
| 鉴权 | `Authorization: Bearer bs-sak-…`（服务账号密钥）；托管应用用平台注入的应用运行期凭据 |
| 权限位 | `model:invoke`，**仅模式 S**（不承载委托） |
| 地址从哪来 | 持密钥调用的一方读 `GET /api/v2/auth/whoami` 的 `model_base_url` 字段（`bisheng dev`、技能包走这条）；服务账号详情页的接入信息区读 `GET /api/v1/dev-toolkit/versions` 的 `model.base_url`，值同上 |

**地址只有一个生产者。** 上面两个字段都由后端的 `model_gateway_base_url()` 算出，没有第二份拼法：页面、CLI、技能包都不许自己用 `location.origin` 或配置里的主机名拼——平台前端在开发期跑在另一个端口，拼出来的地址在客户机器上是死链。

环境变量名（`bisheng dev` 与托管运行期**同名注入**，应用代码本地线上零差异）：

| 变量 | 值 |
|---|---|
| `OPENAI_BASE_URL` | base URL。官方 `openai` 客户端直读 |
| `OPENAI_API_KEY` | 凭据明文 |
| `BISHENG_MODEL_BASE_URL` | 同 base URL 的平台保留名，供不读 OpenAI 惯例变量的引擎使用 |

**未部署开放能力层的环境上这条路径不存在**（404，与任何不存在的路径无差别），接入信息区也不展示地址。翻 `open_platform.enabled` 需要重启后端。

---

## 2. 模型名怎么写

**页面上「模型名称」填的是什么，代码里 `model` 就写什么。** 不是显示名，也不是内部 id。

解析规则固定，按顺序：

1. **精确匹配模型名**。命中一个即调用。
2. 命中多个（不同服务商配了同名模型）→ **拒绝，不替你挑**（`26214`），错误体的 `candidates` 列出这个裸名命中的全部限定名。
3. 裸名没命中且请求里带 `/` → 按 **`{服务商名}/{模型名}`** 再解析一次。限定名在任何时候都可用，写死它就不会因为别人新配了一个同名模型而突然歧义。
4. 仍未命中 → 只分两种：模型**已下线** `26212`，其余一律 `26211`——不存在、不属于本租户、不是对话类、服务商已被删除（删服务商会连它的模型行一起删，与「从未存在过」无从分辨），**「没有」与「不归你」不区分**，否则这条接口就成了模型清单的探测器。
   `26213`「服务商已删除」不来自这一步：名称解析走一层模型目录缓存（`open_api.model_catalog_ttl_seconds`，默认 30 秒、上限 60 秒），窗口内名字还解析得出、真去取模型时行已经没了，那一次才答 `26213`。模型被管理员下线同样最多滞后这一个窗口。

`GET /models` 只列**当前可调用**的对话类模型：`id` 在名称唯一时是裸名、歧义时只给限定名；`owned_by` 是服务商名；另有两个扩展键 `bisheng_model_type`、`bisheng_qualified_name`（恒为限定名，想写稳定名的取它）。

---

## 3. 承诺的请求参数

`POST /chat/completions`，请求体是 OpenAI 的子集：

| 字段 | 说明 |
|---|---|
| `model` · `messages` | 必填 |
| `stream` · `stream_options` | `stream_options={"include_usage": true}` 时末块带 `usage` |
| `temperature` · `top_p` · `max_tokens` · `max_completion_tokens` · `stop` | 原样转给服务商 |
| `presence_penalty` · `frequency_penalty` · `seed` · `response_format` · `user` | 同上 |
| `tools` · `tool_choice` · `parallel_tool_calls` | 工具调用往返支持，流式增量可被官方 SDK 累加 |
| `n` | **只接受 1**；`n>1` 直接拒（`26203`）。底层一次只产一个候选，静默少给比报错更难查 |
| 其它未列出的键 | **原样转发，不做保证**——平台不改写、不注入任何系统提示词 |

响应就是 OpenAI 的 `chat.completion` / `chat.completion.chunk`。思考类模型的推理内容放在 `reasoning_content`——流式增量里为空即不出现，非流式响应体按 OpenAI 结构完整给出、为空时是 `null`。官方客户端忽略这个它不认识的键，两种形态都不影响它解析。

**本版只提供上面两条端点。** 其余 OpenAI 协议族路径（`/embeddings`、`/completions`、`/responses`、`/images/*`、`/audio/*` …）一律 404 + 可读原因（`26201`），不是框架的空 404。Anthropic 的 `/v1/messages` 单列一码（`26202`）并说明本面只提供 OpenAI 兼容协议——把 `ANTHROPIC_BASE_URL` 指到这里的人，得到的是一句能看懂的话而不是协议层乱码。

---

## 4. 错误体

本面**不用平台信封**，用 OpenAI 错误体 + 真实 HTTP 状态，官方客户端才能 `except` 到正确的异常类：

```json
{"error": {"message": "…", "type": "invalid_request_error", "code": "model_not_found", "param": null, "bisheng_code": 26211}}
```

`bisheng_code` 是 OpenAI 体之外的扩展键，官方客户端忽略它，平台侧脚本据它精确分类。流式途中出错：先发一条 `data: {"error":{…}}`，再 `data: [DONE]`。

| `bisheng_code` | 含义 | HTTP | `type` / `code` |
|---|---|---|---|
| 26001 / 26002 / 26027 / 26043 | 没带凭据 / 凭据无效 / 服务账号已停用 / 个人令牌持有人已失效 | 401 | `authentication_error` · `invalid_api_key` |
| 26003 | 缺 `model:invoke` 位 | 403 | `permission_error` · `insufficient_scope` |
| 26051 | 委托专用密钥（本面不承载委托，另发一把） | 403 | `permission_error` · `delegate_only_credential` |
| 26004 / 26005 / 26010 / 26018 / 26019 | 带了身份传递类请求头或 `user_id` 入参（`/api/v2` 共用底座判的） | 400 / 403 | `invalid_request_error` · `identity_header_not_accepted` |
| 26205 | 本面自己再拒一次 `X-End-User`（共用底座会默默采纳它） | 403 | `permission_error` · `identity_header_not_accepted` |
| 26201 / 26202 | 端点不支持 / Anthropic 协议 | 404 | `invalid_request_error` · `endpoint_not_supported` / `anthropic_protocol_not_supported` |
| 26203 | 请求体不合法（`messages` 为空、`n>1` …） | 400 | `invalid_request_error` · `invalid_request` |
| 26204 | 服务账号密钥附带了访问者凭据，或托管应用的访问者凭据验不过 | 403 | `permission_error` · `access_token_not_accepted` |
| 26211 / 26212 / 26213 | 模型不存在 / 已下线 / 服务商已删除 | 404 | `invalid_request_error` · `model_not_found` / `model_offline` / `model_revoked` |
| 26214 | 裸名歧义，`error.candidates` 给限定名 | 400 | `invalid_request_error` · `model_name_ambiguous` |
| 26215 | 托管应用调了未声明的模型能力 | 403 | `permission_error` · `capability_undeclared` |
| 26216 | 模型目录 / 能力声明不可判定 → fail-closed | 503 | `server_error` · `model_catalog_unavailable` |
| 26217 | 服务商日调用上限 | 429 | `rate_limit_error` · `provider_daily_limit_exceeded` |
| 26231 / 26232 / 26233 | 上游失败 / 上游拒绝（上下文超长、参数不支持、内容拦截） / 上游限流 | 502 / 上游自己的 4xx / 429 | `server_error` · `upstream_error` / `invalid_request_error` · `upstream_rejected` / `rate_limit_error` · `upstream_rate_limited` |
| 26234 | 流式中途中断（只出现在 SSE 错误事件里） | — | `server_error` · `stream_interrupted` |

**不可判定一律 fail-closed**（`26216` / `503`）：目录读不出来时报错，不退回「按空清单放行」或「按上次结果放行」。

---

## 5. 身份与边界

- **一律以密钥主体自身的身份执行**：服务账号不继承它的资源归属人，可调用范围 = 该主体在本租户可见的、已上线的对话类模型。
- **不承载委托**：持 `delegate` 位的密钥在入口即被拒（`26051`），不静默降级。
- **不接受任何身份传递请求头**（`X-On-Behalf-Of` / `X-End-User` 及其变体）与 `user_id` 入参：收下再忽略，会让调用方误以为调用跑在别人的身份下。
- **托管应用**走同一条面，Bearer 换成平台注入的 `BISHENG_APP_TOKEN`，可调用范围额外 ∩ **该应用当前生效能力声明**里的模型——声明外的模型答 `26215`，应用不能自报范围。
- **不在这条面上做配额与账单**：本版只逐条记录调用（模型、token 数、时延、结果、归属人），不做聚合、不加上限；服务商自身的日调用上限照旧生效（`26217`）。

---

## 6. 引擎与客户端配置

官方 Python 客户端：

```python
from openai import OpenAI

client = OpenAI(base_url="https://<平台地址>/api/v2/model/v1", api_key="bs-sak-…")
print([m.id for m in client.models.list().data])

resp = client.chat.completions.create(
    model="qwen2.5-72b",                    # 页面上的「模型名称」；歧义时写 "服务商名/模型名"
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
    stream_options={"include_usage": True},
)
for chunk in resp:
    print(chunk.choices[0].delta.content or "", end="")
```

`curl`：

```bash
curl -N https://<平台地址>/api/v2/model/v1/chat/completions \
  -H "Authorization: Bearer bs-sak-…" -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-72b","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

读 OpenAI 惯例环境变量的引擎（Qwen Code、Codex CLI 的 chat-completions provider、Kimi Code、各类 IDE 插件）：

```bash
export OPENAI_BASE_URL=https://<平台地址>/api/v2/model/v1
export OPENAI_API_KEY=bs-sak-…
```

**Claude Code 走不通**，这是设计如此：把 `ANTHROPIC_BASE_URL` 指到这里会得到 `26202`，说明本面只提供 OpenAI 兼容协议。需要在 Claude Code 里用平台模型的，改用它的 OpenAI 兼容 provider 配置。

托管应用里不必自己配地址与密钥——两者由平台按同名环境变量注入，`openai` 客户端零参数构造即可：

```python
from openai import OpenAI

client = OpenAI()  # OPENAI_BASE_URL / OPENAI_API_KEY 由平台注入
```

---

## 7. 调用记录

每次调用落一行（`model_call_record`）：凭据（掩码）、主体与资源归属人、托管应用 id、请求的模型名与解析结果、是否流式、三个 token 数（未知写 NULL，**不写 0**）、结果与错误码、时延与首字时延、`request_id`。请求体正文、密钥、服务商配置**都不进记录，也不进日志**。

凭据层就被拒的调用（401 / 403 / `26051`）不落本表，落既有的 `open_api.call` 审计行——那不是一次模型调用。
