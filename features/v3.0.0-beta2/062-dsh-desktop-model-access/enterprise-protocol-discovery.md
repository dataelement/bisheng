# 企业模型协议扩展 Discovery

状态：用户已于 2026-10-16 纠正命名并确认 spec、design，授权继续实现；实际进展见 enterprise-protocol-tasks.md。不使用 `dsh_reasoning`，使用 `reasoning_effort`。

依据：`docs/SDD-Guide.md` §1–3；本扩展涉及跨模块协议，按 Full SDD。沿用 F062 企业认证、授权和配额体系，后续 spec/design/tasks 分阶段确认；不提交、推送或部署。

## 已核实缺陷

1. Desktop 已序列化 `reasoning_effort`，但主进程白名单不接受。Bisheng `DshChatRequest` 也未接受，`DshChatAdapter` 未校验和传参，模型列表未声明档位。
2. Harness 提供 `GenerateOptions.sessionId`，企业适配器未使用。Sub2API 的 `GenerateSessionHash` 优先读取 `session_id` 请求头；当前内容推导无法保证压缩前后稳定。
3. 企业适配器图片超限使用不可恢复错误，没有接入公开的 `IMAGE_OFFLOAD_REQUIRED` / `failure.offloadImages`。
4. Bisheng 只有 Chat Completions 企业端点。底层 `ChatOpenAIReasoning` 支持构造上游 Responses 请求，不代表企业 API、SSE 和 Harness 持久化已经支持 Responses。

## 待确认范围与建议

### 思考深度

- 模型目录采用 Desktop 已实现的可选 `reasoning: {efforts: [{id,name}], defaultEffort?}`。`reasoning_content` 与深度独立；没有声明则不显示、不强加默认档位。
- 权威输入采用管理员维护的模型配置 `config.reasoning_efforts`（档位列表，每项为 `{id,name}`）和可选 `config.reasoning_effort`（默认档位 ID），与调用供应商的 `user_kwargs` 分开。严格校验结构、档位唯一性和默认值。不使用 `dsh_reasoning`，不根据模型名字或服务商类型猜档位。暂不新增管理 UI。
- Chat 请求接受可选 `reasoning_effort`，按当前授权模型的声明校验；不支持时在供应商调用和配额计费开始前拒绝。已声明默认值时应用默认值。
- 通用 OpenAI SDK 已能传递此参数，复用它，不另造 SDK。非 OpenAI 供应商若需要参数转换，必须单独声明并验证后才允许配置档位。

### 对话身份

- 建议新增受控请求头 `x-dsh-conversation-id` 和 `x-dsh-request-purpose`；用途仅 `chat`、`compaction`、`session-title`，格式及长度在 Desktop 和 Bisheng 双重校验。不放开任意头或任意 JSON extra。
- 普通对话使用 Harness sessionId，历史压缩和 system/tools 变化不改变 ID。辅助请求使用同一 Harness ID 加用途形成不同亲和作用域；没有 ID 的辅助调用不伪造为普通对话。
- Bisheng 以已认证 principal 的租户和用户，加模型 ID、用途和对话 ID 派生稳定摘要，只把摘要作为上游 `session_id`，不透传登录凭据或登录 session_id。不以客户端头中的租户/用户作为可信来源。
- 旧客户端不带头时维持旧行为；旧服务端忽略新头，仍可请求。账号限流、故障切换、上游策略变化不保证缓存命中。

### 原生 Responses

- 建议作为独立、可协商的 `responses-v1` 能力；仅真正实现并验收的模型可声明，旧 Chat 端点和模型继续兼容。不通过设置 `use_responses_api=True` 把 Chat 伪装为 Responses。
- 第一版采用无服务端会话存储的显式全历史往返，`store:false`；禁止客户端跨身份引用 `previous_response_id`。客户端持久化并原样回放 reasoning item 的 `encrypted_content`、function_call 的 call_id、function_call_output，不把密文当可显示文本。
- 新增企业 `/api/v1/dsh/responses` 以及受控本地 broker 路由；复用 F062 Bearer 身份、实时授权、租户作用域、配额 admission/settlement。不能直接透传供应商 URL、凭据或任意参数。
- 设计必须列出原生 input/tools/reasoning schema；SSE created/output_item/content_part/text/function_call_arguments/completed/incomplete/failed/error 状态机；事件终结、取消、断连、部分用量与 UNKNOWN 结算；输出大小和密文预算；错误脱敏；工具续轮和加密推理持久化。
- Harness 现有公开 provider metadata 能否完整保留原生输出须在 design 验证；不完整时先设计最小上游接缝，再实现，不能丢 reasoning item 后宣称原生支持。

## 验收证据要求

- 思考深度：真实 Desktop serializer → broker validator → Bisheng schema/adapter → 实际 SDK 构造出的供应商请求；默认、显式、缺省、非法、未声明、流式工具续轮及旧客户端兼容。
- 对话身份：多轮/压缩/辅助用途、租户用户隔离、非法/重复头、旧客户端；确认最终头被当前 Sub2API 识别而非只检查客户端输出。
- 图片：实际请求版本大小与重复 occurrence；超大单图/累计/工具图；由 Harness 卸载事件驱动重新派生请求并重试，取消可退出；原有大小和视觉限制不放宽。
- Responses：真实受控链路、工具两轮、encrypted_content 原样回放、计量、错误取消、租户/授权/配额失败。Mock 供应商不等于真实上游或正式安装包验收。

## 官方依据

已读取 [OpenAI reasoning guide](https://platform.openai.com/docs/guides/reasoning)：无状态 Responses 需要保留并回放输出中的 reasoning item / encrypted_content，尤其跨工具续轮；不能将其压成 Chat 文本。最终 wire schema 和事件集合在 design 阶段按 SDK 与官方 Responses 文档再核对。

## 本轮可独立处理

Desktop `reasoning_effort` 本地白名单是已有序列化能力的兼容修复；图片恢复使用锁定 Harness 已有公开协议，不改变服务端 API。它们可先验证，后端 reasoning、对话身份及原生 Responses 待 Discovery 确认后进入 spec。
