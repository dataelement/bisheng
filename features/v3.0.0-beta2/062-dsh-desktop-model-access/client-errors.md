# 客户端错误原因适配清单

整理日期：2026-10-08。用途：供 bisheng-work 企业插件、主进程和聊天界面统一适配错误原因；本文件是适配建议，不表示客户端代码已修改或部署。

核对基线：BiSheng `feat/3.0.0-beta2-pre / 48cef6967`、Gateway `feat/dsh-access / faed249a`、bisheng-work 本地提交 `b06e60e`。这是本地代码核对，不是对 109 当前所有错误场景的实测，也未判断远端是否另有未拉取提交。接口路径和错误码无需因本文调整，协议不需要升版。

## 1. 先保留原始错误，再决定展示和动作

DSH 业务错误的标准响应：

```json
{
  "error": {
    "message": "Monthly token limit reached",
    "type": "quota_error",
    "code": "monthly_token_limit_exceeded"
  },
  "request_id": "request-id-example"
}
```

- **判定优先级：`error.code` → 受限的历史关键字兼容 → `error.type` / HTTP 状态兜底。** 明确但未知的 code 应保留，不能靠 message 猜成另一种已知错误。
- 原样保留 `code / type / message / request_id / HTTP status`。`QUOTA / AUTH / FORBIDDEN / SERVER / PROVIDER_ERROR` 可作为聊天框架的分类，但不能覆盖服务端业务 code。
- 已知 code 展示下表的本地化说明，并可展开原始原因和请求 ID；未知 code 使用长度受限、纯文本的服务端 message 或安全兜底。不要渲染 HTML，不显示 Token、ticket、密钥和堆栈。
- `request_id` 优先从 JSON 顶层读取，缺少时取 `X-Request-ID`；请求 ID 不是 `error.code`，也不用于文案匹配。
- Python 内部注册的 `26101–26130` 不是客户端应依赖的 HTTP 状态，也不是标准 DSH 响应中的 `error.code`。客户端依赖下面的字符串。
- 错误清单同时包含当前路径的可达错误和注册的防御性兼容项；不能因为注册了某个 code，就推断每个版本/每个接口必然返回它。

建议在现有客户端错误结构中保留平台信息（字段名为建议，不新增服务端字段）：

```ts
interface EnterpriseFailureDetail {
  platformCode?: string;
  platformType?: string;
  platformMessage?: string;
  requestId?: string;
  httpStatus?: number;
  source: 'platform' | 'client';
  transport: 'json' | 'sse' | 'network';
}
```

聊天 UI 应优先使用已识别的企业错误说明，再使用框架通用提示。不要只修设置页：登录页、模型选择、聊天错误、流式错误都要保留同一套信息。

## 2. 服务端错误码：登录与凭证

本组 `error.type` 均为 `authentication_error`。

| HTTP | error.code | 原因 | 建议提示与客户端动作 |
|---|---|---|---|
| 400 | `invalid_grant` | 授权票据无效、已消费，或换证参数组合不合法 | “本次登录授权已失效，请重新发起登录。”结束本次登录事务，不重用 ticket；持续复现需检查客户端请求参数。 |
| 400 | `pkce_verification_failed` | verifier 与本次授权不匹配 | “登录验证失败，请重新发起登录。”丢弃本次 auth_id/verifier，不循环兑换。 |
| 400 | `authorization_expired` | 授权事务或票据过期 | “登录授权已过期，请重新登录。”重新打开浏览器授权。 |
| 401 | `invalid_access_token` | Access Token 缺失、无效或过期；不只表示到期 | 先按 §6 尝试一次串行刷新；无法恢复时提示“登录凭证已失效，请重新登录。” |
| 401 | `invalid_refresh_token` | 刷新凭证无效或不可用 | “登录已失效，请重新登录。”清除当前会话凭证并停用对应企业 provider。 |
| 401 | `refresh_token_reused` | 已轮换的 refresh token 被再次使用，可能导致会话族撤销 | “登录状态已失效，请重新登录。”清除当前会话凭证；排查并发刷新或旧凭证重试。 |
| 401 | `session_expired` | 会话绝对有效期已到 | “登录会话已过期，请重新登录。”不继续刷新旧会话。 |
| 401 | `session_revoked` | 当前登录会话被撤销/已不可用 | “本次登录会话已失效，请重新登录。”不能一律写成“管理员撤销”；其他设备/退出行为也可能导致会话失效。 |

HTTP 409、`authorization_conflict` 的 type 为 `conflict_error`：本次登录事务冲突。提示“本次登录状态发生冲突，请重新发起登录。”关闭重复事务，不自动创建第二个会话。

## 3. 服务端错误码：席位、授权、开关

本组 HTTP 为 403，`error.type` 为 `permission_error`。

| error.code | 原因/实际边界 | 建议提示与客户端动作 |
|---|---|---|
| `seat_not_assigned` | Gateway 换证时找不到已分配席位；Python 261xx 注册表没有此项，但 Gateway 实际会返回 | “你尚未获得客户端使用席位，请联系管理员分配后重新登录。”停止重复登录；不是先到先得抢席位。 |
| `seat_revoked` | 席位已撤销，或旧凭证的席位授权版本不再有效 | “你的客户端使用授权已失效，请联系管理员确认席位，重新授权后再登录。”停用当前凭证；仅反复登录不能恢复被撤销的席位。 |
| `seat_limit_reached` | 席位容量不足；当前主要在后台分配时出现，客户端保留兼容提示 | “可用席位已满，请联系管理员处理。”不自动重试抢席位。 |
| `license_invalid` | 注册的授权无效错误 | 若调用实际返回该码：“平台客户端授权无效，请联系管理员。”不要刷新 Token 解决。注意下面的免费版回退说明。 |
| `license_expired` | 注册的授权过期错误 | 若调用实际返回该码：“平台客户端授权已过期，请联系管理员。”注意下面的免费版回退说明。 |
| `dsh_disabled` | 平台关闭客户端功能 | “管理员已关闭客户端功能，请联系管理员。”停止新调用，不必据此直接销毁全部已保存凭证；重新开启后仍需重新确认会话有效性。 |
| `user_disabled` | 当前账号不可用，包括禁用/身份校验不通过等；不只表示管理员手动禁用 | “当前账号不可用，请联系管理员。”停用对应企业 provider。 |
| `tenant_unavailable` | 所属租户不可用 | “账号所属组织暂不可用，请联系管理员。”停用对应企业 provider。 |
| `model_not_allowed` | 该模型未授权、授权关闭或模型不可用 | “当前模型未获授权或已不可用，请刷新模型列表或联系管理员。”刷新列表并让用户重选，不自动换模型重放原请求。 |

**免费版边界**：当前 `DshLicenseState.snapshot()` 在商业授权缺失、无效或过期时仍返回有效的内置 10 席。管理接口的 `signed_license_status` 是商业授权状态，不等于有效授权整体失效。客户端以实际接口结果为准，不把“未配置商业 License”自行转换成 `license_invalid`。容量回落后，个别席位可能受席位治理影响，应展示调用实际返回的席位错误。

## 4. 服务端错误码：模型、额度、平台故障

| HTTP | error.code | error.type | 建议提示与客户端动作 |
|---|---|---|---|
| 400 | `invalid_request` | `invalid_request_error` | “请求参数不正确，请检查后重试。”持续出现时提供请求 ID 给开发人员；不原样自动重发。 |
| 400 | `unsupported_parameter` | `invalid_request_error` | “当前模型不支持此参数，请调整模型设置。”保留具体 message。 |
| 400 | `context_length_exceeded` | `invalid_request_error` | “当前对话内容超过模型上下文限制，请缩短内容或新建会话。”不能提示额度不足。 |
| 429 | `monthly_token_limit_exceeded` | `quota_error` | “当前模型本月额度已用尽，请联系管理员调整额度，或等待下月重置。”查询当前模型的 usage 展示额度和 reset_at；可由用户换模型，不自动重试、不要求重新登录。 |
| 429 | `too_many_requests` | `rate_limit_error` | “操作过于频繁，请稍后重试。”这是授权入口防滥用等限制，不等于模型月额度耗尽，也不代表一期支持模型 RPM/TPM 限流。若响应实际含 Retry-After 再据此提示等待。 |
| 502 | `upstream_error` | `upstream_error` | “模型服务调用失败，请稍后手动重试。”展示请求 ID；不是必然由 Token/账户余额导致。 |
| 504 | `upstream_timeout` | `upstream_error` | “模型响应超时，请稍后手动重试。”模型可能已执行，不自动重放。 |
| 503 | `authorization_unavailable` | `service_unavailable_error` | “平台授权服务暂不可用，请稍后重试。”是校验服务异常，不等于用户没有授权；不要清空凭证并强制重新登录。 |
| 503 | `quota_unavailable` | `service_unavailable_error` | “额度服务暂不可用，请稍后重试。”暂停新模型请求；不是额度为 0，不展示余额不足。 |
| 503 | `usage_unavailable` | `service_unavailable_error` | “本次调用的用量记录暂无法确认，请勿重复发送；可稍后查看用量或联系管理员。”可能已经生成结果；保留已有输出，不自动重放。 |
| 500 | `internal_error` | `server_error` | “平台服务异常，请稍后重试或联系管理员。”保留请求 ID；不据此重新登录或自动重放模型请求。 |

月度额度按“用户 + 模型”独立计算。默认北京时区每月重置，展示时间应读取 usage 的 `billing_timezone/reset_at`，不要由客户端自行算到下月 1 日或依赖本机时区。管理员提升额度后刷新 usage 即可，无需重新登录。

### 仅管理端使用的注册项

| HTTP | error.code | error.type | 建议处理 |
|---|---|---|---|
| 409 | `operation_in_progress` | `conflict_error` | “配置正在处理中，请稍后刷新。”后台操作正在进行，客户端登录/聊天不应把它作为常规分支。 |
| 409 | `operation_conflict` | `conflict_error` | “配置已发生变化，请刷新后重新操作。”版本或操作参数冲突；不要解释成登录失效。 |

## 5. 流式、降级与浏览器回调

### HTTP 200 也可能是流内失败

SSE 已开始后不能修改 HTTP 状态，错误会作为事件返回：

```text
event: error
data: {"error":{"message":"Upstream model request timed out","type":"upstream_error","code":"upstream_timeout"},"request_id":"request-id-example"}

```

客户端同时识别 `event: error` 和 JSON 的 `error` 对象。进入失败终态、保留部分回答和错误原因，不将 200 当成功，不再等待 `[DONE]` 才承认报错。没有业务错误事件却提前断流时，使用本地 `STREAM_CLOSED`，不要伪造 `upstream_timeout`。日志可保留真实 HTTP 200，UI 动作必须按业务 code 判断。

### 缺失用量不等于调用失败

- 生成成功但供应商没给 usage：`prompt_tokens/completion_tokens/total_tokens` 可为 null，仍可正常 200 / `[DONE]`。平台记 `USAGE_UNKNOWN` 和 `usage_missing` 明细，不冻结用户。显示“用量暂未获取”，不当成 0，不生成 `usage_unavailable`，不自动重发。
- `usage_unavailable` 指结算记录无法确认，和“供应商没有返回 usage”不是一回事。
- `/dsh/usage` 的 200 降级快照应按 [主接口文档 §8](client-api.md) 的状态与时间展示，不能靠 HTTP 200 或历史 remaining 判断当前能调用模型。
- `/dsh/models` 返回空列表属于成功响应：提示“暂无可用模型，请联系管理员授权”，不要编造鉴权错误或把整套账号退出。

### 浏览器回调关键字（不是统一 HTTP error.code）

| 回调 `error` | 提示 | 动作 |
|---|---|---|
| `access_denied` | “你已取消本次登录授权。” | 回到未登录状态，不循环弹出登录。 |
| `authorization_expired` | “本次登录授权已过期，请重新登录。” | 结束当前事务，用户重新发起。 |
| `authorization_failed` | “本次登录授权失败，请重新发起登录。” | 保留安全诊断信息，不执行回调中任意地址。 |

回调仍需验证 state/auth_id 和本机回调地址；文本适配不能绕过校验。

## 6. 凭证和重试策略

1. `invalid_access_token`：仅针对完整、明确的准入前 401，可串行刷新一次。GET 刷新后重试一次；模型 POST 仅在明确未开始执行的该类 401 下允许刷新后重发一次。
2. `invalid_refresh_token / refresh_token_reused / session_expired / session_revoked`：停止旧会话，清除当前会话凭证，提示重新登录。这里的“清除”不应删除其他平台账号或非企业 provider。
3. `seat_not_assigned / seat_revoked`：联系管理员确认/重新分配后再登录，不能用“登录已过期”掩盖席位原因。
4. 403、额度 429、服务 503 不走 Token 刷新循环。会话刷新必须有共享锁，不能多个请求各自刷新同一 refresh token。
5. 普通 GET 的网络或暂时性故障可有限退避。token 换证/轮换遇到网络中断、5xx、响应丢失时结果不确定：不自动重发旧 ticket/refresh，按主接口契约重新登录。
6. 模型 POST 的网络错误、502/504、流内错误、部分输出、用量结算不确定均不自动重放，避免重复调用和重复扣量。

## 7. 历史错误关键字与客户端本地错误

### code 丢失时的历史兼容

Gateway 当前 message 基本由 `code.replace('_', ' ')` 生成，例如 `seat not assigned`、`session revoked`；Python 使用更完整的英文 Msg。客户端不要依赖某一种英语句式。

仅在 **没有有效 code** 且明确属于企业接口错误时，可以精确匹配白名单：忽略大小写、首尾空格和一个末尾句号；不要用“包含 token/license/quota”等宽泛规则，也不要匹配模型回答正文。原有未知 code 应保留并走未知错误兜底。

| 已观察的原始文案/关键字 | 兼容业务码 |
|---|---|
| `seat not assigned` | `seat_not_assigned` |
| `seat revoked` / `DSH seat revoked` | `seat_revoked` |
| `session revoked` / `DSH session revoked` | `session_revoked` |
| `session expired` / `DSH session expired` | `session_expired` |
| `invalid access token` / `Invalid DSH access token` | `invalid_access_token` |
| `invalid refresh token` / `Invalid refresh token; sign in again` | `invalid_refresh_token` |
| `refresh token reused` / `Refresh token reuse detected; sign in again` | `refresh_token_reused` |
| `monthly token limit exceeded` / `Monthly token limit reached` | `monthly_token_limit_exceeded` |
| `authorization unavailable` / `DSH authorization is temporarily unavailable` | `authorization_unavailable` |
| `quota unavailable` / `DSH quota state is temporarily unavailable` | `quota_unavailable` |
| `usage unavailable` / `Actual request usage could not be confirmed` | `usage_unavailable` |

其他 Gateway 空格文案若需要兼容，可以从本文明确枚举的 code 生成白名单；不能将任意英文句子空格替换为下划线后当成可信 code。

### bisheng-work 本地错误（与服务端业务码分开）

| code 或精确关键词 | 原因和建议提示 |
|---|---|
| `network_error` / `Could not reach the BiSheng platform.` | 无法连接平台，可能是网络、地址、超时等；“无法连接毕昇平台，请检查地址和网络。”不要判断为席位未授权。 |
| `invalid_response` / `INVALID_RESPONSE` / `BiSheng returned a non-JSON response (...)` | 返回格式不符合协议，可能是代理、路由或版本问题；“平台响应异常，请检查服务地址或联系管理员。”不直接展示 HTML。 |
| `STREAM_CLOSED` | 流提前结束/帧不完整；“连接中断，回答可能不完整，请手动重试。”保留已收到内容。 |
| `EMPTY_RESPONSE` | 流结束却无模型输出；“模型未返回内容，请手动重试或联系管理员。” |
| `UNKNOWN_MODEL` | 本地 provider 中找不到所选模型；刷新授权模型列表并重选。不能直接推断席位失效。 |
| `UNSUPPORTED_CONTENT` / `UNSUPPORTED_OPTION` | 图片、工具或请求选项不被本地模型能力支持；按具体原因提示调整输入。 |
| `Enterprise models are unavailable.` | 客户端当前未能确认模型可用性；展示“企业模型暂不可用”，有服务端原始错误时优先展示该原因。 |
| `Enterprise session changed.` | 请求期间客户端会话/账号发生切换；“登录状态已变更，请刷新后重试。”不是管理员撤销的确定证据。 |
| `BiSheng DSH contract version is incompatible with this Desktop build.` | 客户端协议兼容性校验失败；“客户端与平台版本不兼容，请联系管理员更新。”不是平台业务错误，不因此改服务端错误码。 |
| `request_failed` / `PROVIDER_ERROR` / `UNKNOWN` | 兜底或分类，不是足够明确的根因；如有平台原始 code，必须优先保留并展示。 |

## 8. 当前适配缺口与验收清单

当前核对到的 bisheng-work 实现：

- `packages/dsh-desktop-enterprise/openai.js / requestFailure` 将部分业务码映射到通用 LlmError 分类，但未将平台 code/type/message 完整作为独立信息传下去。`responseFailure` 只读取响应头请求 ID，遗漏只放在 JSON 中的 request_id；SSE 路径则已经传入 payload.request_id。两条路径需统一。
- `packages/dsh-desktop-enterprise/client.js / formatEnterpriseSettingsError` 目前只有席位未分配/撤销的定向提示；设置页已有映射不能替代聊天错误映射。
- `src/main/enterprise/enterprise-request.ts` 的 JSON 请求已保留 code/type/requestId，可作为传递平台信息的参考；`isInvalidRefreshError` 当前只覆盖 invalid_refresh_token/refresh_token_reused/session_revoked，客户端应按本文检查 session_expired 等动作，不把它们泛化成临时网络错误。
- 截图指出的聊天 UI 固定 AUTH/QUOTA/FORBIDDEN 文案覆盖应按客户端实际版本复查。本文确认了插件侧信息丢失，不把截图中的旧行号当作现版本 UI 实测结论。

建议至少覆盖以下验收：

1. 每个登录/席位码有独立提示，特别是 seat_not_assigned 与 seat_revoked，不提示反复登录即可解决。
2. 普通 JSON 错误体只有顶层 request_id、没有响应头时，请求 ID 仍能展示。
3. monthly_token_limit_exceeded 显示“当前模型本月额度”，quota_unavailable 显示“额度服务暂不可用”，文案不能相同。
4. HTTP 200 + SSE event:error 在 UI 呈现失败，保留业务 code 和部分内容，不触发自动重发。
5. session_revoked/session_expired 触发当前会话失效处理；网络/授权服务 503 不被误当 Token 无效。
6. 成功输出且 usage=null 仍为成功，只标用量未知。
7. 未知 code、HTML 502、网络中断、用户取消，各有安全兜底，不能显示原始 HTML 或一律 UNKNOWN。
8. 未配置商业 License 的免费版可正常使用；商业状态不是整体授权结论。
9. 中英文文案均覆盖；若聊天框架只能使用通用枚举，也必须能展示更具体的平台错误原因。

## 9. 代码依据

- BiSheng：`src/backend/bisheng/common/errcode/dsh.py`（30 个 Python 注册项）；`src/backend/bisheng/dsh/api/responses.py`（JSON 适配）；`domain/services/access.py`（鉴权原因映射）；`domain/services/model.py`（错误转换、SSE、缺失用量处理）。
- Gateway：`src/main/java/com/dataelem/gateway/dsh/controller/DshControllerAdvice.java`（包括 seat_not_assigned 的 HTTP/code/type）；`service/DshSeatService.java`（席位检查）；`service/DshIntrospectionService.java`、`DshTokenService.java`（会话/刷新）；`DshLicenseState.java`（免费 10 席回退）。
- 主协议：[client-api.md §4–§9](client-api.md)。本文补齐逐码原因与客户端提示，不新增 API 或更改授权边界。
