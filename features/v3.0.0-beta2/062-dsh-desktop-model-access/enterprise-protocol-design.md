# 企业模型协议扩展 Design

状态：spec、design 已于 2026-10-16 获用户确认，进入实现。源码与隔离验证进展见 tasks；不能据此认定已部署服务器、安装包或生产环境已支持。

关联：[Spec](./enterprise-protocol-spec.md) · [Discovery](./enterprise-protocol-discovery.md) · [版本契约](../release-contract.md)。遵循 [constitution](../../../docs/constitution.md) C1–C8；分阶段确认依据 [SDD Guide](../../../docs/SDD-Guide.md) §3。

## 1. 目标与边界

在既有企业模型访问链路中补齐思考深度、稳定对话身份、可恢复图片限制和原生 Responses。身份、模型授权与配额继续由 Bisheng 负责，企业凭据保留在 Electron main。

本轮不发布、不部署，不保证供应商缓存命中，不扩展 contextWindow、模型 UI、供应商托管工具或远端会话存储。Responses 第一版只开放文本、图片、function 工具和 reasoning；不支持的类型明确拒绝。

## 2. 设计前实现与约束

现有链路：`EnterpriseLlmAdapter → serializer → credential broker → EnterpriseService → /api/v1/dsh/chat/completions → DshModelService → DshChatAdapter → BishengLLM → supplier`。

| 当前模块 | 已有职责与缺口 |
| --- | --- |
| Desktop `contract.js`、`enterprise-service.ts` | 工作区已保留可选 reasoning 目录元数据；尚非完整服务端能力 |
| Desktop `openai.js`、`enterprise-chat.ts` | serializer 已生成 reasoning_effort，本地主进程白名单修复已有定向测试；后端 schema 尚不接受 |
| Bisheng `domain/schemas/chat.py` | strict/extra=forbid；没有 reasoning_effort；client_fields 只返回既有能力 |
| Bisheng `infrastructure/model_capabilities.py` | 从模型类型和权威视觉配置产生能力，尚无管理员 reasoning 档位声明 |
| Bisheng `domain/services/model.py` | 实时策略检查、READY 检查、prepare 后准入、实际用量结算；输出包装和 PreparedStream 为 Chat 专用 |
| Bisheng `infrastructure/chat_adapter.py` | LangChain Chat 转换，不能承载原生 Responses 全部输出项 |
| Bisheng `api/responses.py` | 企业错误响应封装，不是 Responses API 实现 |
| Desktop `request-images.js` | 工作区正在接入 Harness 卸载契约；真实 Session 重试和完整回归尚待完成 |

限制保持现状：单图原始数据 5 MiB、合计 20 MiB；Bisheng 单个 data URL 长度 7,000,000、合计 28,000,000；本地 Chat JSON envelope 32 MiB。broker 的 base64 解码长度估算包含 padding，客户端预算必须与它一致。

## 3. 关键决策

### 3.1 档位来自模型配置，使用现有协议名称

选定管理员模型配置 `reasoning_efforts: [{id, name}]`，可选默认 `reasoning_effort`；通过现有高级参数编辑器的 `config.user_kwargs` 读取，也兼容模型 config 直接声明（直接声明优先）。目录返回既有客户端结构 `reasoning: {efforts, defaultEffort?}`。不新增 dsh_reasoning，也不根据模型名猜测档位。

配置最多 32 档，ID 为 1–128 个 ASCII 字符，匹配 `[A-Za-z0-9][A-Za-z0-9._-]*`；name 非空且最多 256 字符；ID 唯一、默认值必须在列表内。默认字段存在但列表缺失也是配置错误。目录省略错误配置的模型并记录脱敏诊断，直接请求则拒绝；不得退回猜测能力。

请求显式值优先，未指定则采用管理员默认，均未配置则不发送。Bisheng 每次读取当前模型快照重新验证，发生在供应商调用及配额 admission 前。客户端目录仅用于选择与提前校验，不是授权来源。

Chat 使用 `reasoning_effort`，Responses 使用 `reasoning.effort`。供应商适配器必须声明可接受的参数及值；只有管理员声明和适配器支持的交集可服务。非 OpenAI 节点通过其明确映射实现，否则拒绝深度参数。`reasoning_content` 只表示思考文本输出，与深度独立。

否决“所有模型固定 low/medium/high”：不同供应商值域不同。未来有权威能力发现接口时，才考虑以发现结果辅助管理员声明；不能仅以 SDK 接收任意 kwargs 证明供应商支持。

### 3.2 对话身份使用受控头，服务端生成隔离摘要

选定 `x-dsh-conversation-id` 和 `x-dsh-request-purpose`；前者来自 Harness GenerateOptions.sessionId，后者仅允许 `chat`、`compaction`、`session-title`。缺省用途为 chat；没有会话 ID 时不生成亲和头，单独携带用途拒绝。

conversation ID 必须为 1–256 字符，匹配 `[A-Za-z0-9][A-Za-z0-9._:-]*`，拒绝首尾空白、控制字符和重复头；purpose 同样拒绝重复。辅助调用必须在自己的调用入口标记用途，不能从提示词猜测。实现时逐一验证当前 Harness 标题/压缩入口是否传入 sessionId；缺失时只省略身份，不能替换为登录会话。

三处独立白名单同步：插件 attribution、本地 broker 解析、main 的 enterprise-request 发送。额外头不允许成为任意转发通道；native pi-ai 发出的 session_id、prompt_cache_key 等也不能直接进入供应商。

服务端计算：`SHA256(UTF8(JSON(["dsh-conversation-v1", tenant_id, user_id, model_id, purpose, conversation_id])))`，输出小写 64 位 hex；整数身份先规范化为十进制字符串。租户和用户只取 DshPrincipal。受控上游 `session_id` 覆盖同名配置，Responses 的 prompt_cache_key 如发送也使用同一摘要。该摘要用于隔离而非访问授权。

通过请求级 SDK extra_headers 合并传递，保留供应商原有其他配置头，不修改持久模型配置或共享 client 对象。API key/登录 token 不进入摘要。原始对话 ID 不进入供应商或常规日志。

否决登录 session_id：同一登录有多个对话，刷新也不应改变对话归属。否决直接转发客户端 session_id：无法隔离租户、用户和辅助调用。Sub2API 当前已优先识别 session_id，可先不改其核心；其前置代理的真实转发仍需联调验证。未来上游头名称变化时重审映射。

### 3.3 原生 Responses 单独协商，复用已有协议引擎

目录新增可选 `capabilities.responses: true`，缺省 false。管理员 `use_responses_api=true` 仅作为启用条件之一；还必须通过供应商类型支持、native adapter 可用及配置校验，才可发布能力。Chat 不因 native 能力自动消失。

新增企业 `POST /api/v1/dsh/responses`，本地 broker 新增受控 Responses 操作。Desktop 按冻结的模型能力选择协议。原生生成一旦开始，错误不自动改走 Chat，避免重复计费及破坏加密历史；旧服务端不声明能力，自然继续 Chat。

客户端复用锁定 `@earendil-works/pi-ai/api/openai-responses` 的公开 stream/转换协议，通过其 fetch/onPayload 接缝接入现有 broker，而不是复制 SSE/工具/reasoning 引擎。Enterprise wrapper 负责 Harness StreamChunk 与 providerMetadata 映射、请求快照和账户代次隔离。现有 PiAiAdapter 的公开构造参数不能直接注入该 transport，因此不通过替换其内部方法接入。

该包目前是传递依赖，实际实现应增加显式依赖声明并同步锁文件及安装闭包，复用同一兼容版本；不得假设开发 node_modules 偶然可达。相比新引擎，此依赖复用已有运行时；体积及安装包资源差异须实际检查。

所有 SDK URL 固定到 broker transport，真实企业和供应商凭据不交给 pi-ai。transport 仅接受固定的 Responses POST；读取、取消、响应体及错误都走 broker 限制。onPayload 将原始 session/prompt_cache_key 归入受控身份映射，禁止保留未验证值。

第一版强制 `store:false`，`include:["reasoning.encrypted_content"]`，全历史 input；拒绝 previous_response_id、conversation、background、远端 URL/file ID、托管工具、任意 metadata/extra headers/extra body。以严格 schema 校验 message、reasoning、function_call、function_call_output；保留允许类型的完整标准字段、顺序、ID、工具参数和 encrypted_content，不经 Chat messages 中转。拒绝未知类型和字段，升级支持集时显式扩展。

使用 transport 对合法终结响应的原始 output 做限额内捕获，在 AssistantProviderMetadata.response 保存版本化 replay 数据及来源：enterprise origin 摘要、账户绑定摘要、provider、公开模型 ID。可见块仅含文本、工具调用及可显示 summary；encrypted_content 不显示、不记日志。pi-ai 的 thinkingSignature/tool ID 继续按其公开格式往返，完整 output 用来检查和补全其转换可能丢掉的字段。

回放前核对来源与输出类型、大小、版本；只在相同 origin/账户/模型下回放加密内容。换模型或账户时不能发送旧密文，允许按现有 provider-neutral 历史降级并记录脱敏原因；若工具关系无法安全重建则明确失败。重启持久化、压缩派生及工具续轮均需覆盖。断流且没有合法终结态时，保留恢复所需历史，不把部分输出标记成功。

否决“设置 use_responses_api 就算完成”：既有 Chat adapter 会重写输出。否决全部重写协议引擎：锁定 pi-ai 已有 store:false、encrypted_content 和工具处理。若公开接缝无法满足完整回放测试，先保持 capability 关闭，补最小公开接缝；不能靠私有方法替换或降低 AC-P2 验收。

### 3.4 后端共享治理生命周期，协议分别编码

模型 service 共享：可信 principal scope → 当前策略/模型快照/READY → 协议与参数 prepare → usage admission → execution → settle。将这一段提取为模块内的受控准备/执行入口，Chat 和 Responses 分别编码响应，不复制准入、计费和异常清理逻辑。

native adapter 使用官方 Python OpenAI SDK Responses 接口，连接参数从现有 LLMService 的供应商配置解析入口获得；不在 endpoint 自行解密/拼接配置，也不通过 LangChain AIMessage 丢失原生结构。第一版只开放已验证的 OpenAI-compatible Responses 节点；Azure 及其他节点通过独立能力测试后再开启。Chat 仍使用原 adapter；双协议模型必须分别验证实际 SDK 请求路径。

native execution 暴露 usage、invoke、stream、close；治理对象只依赖这个窄执行契约。Responses 将 input_tokens、output_tokens、cached_tokens 等映射为既有 DshTokenUsage，保留可审计明细；不能将 reasoning tokens 再加到已包含它的 output_tokens。非流式与流式使用同一计量函数。

流式保留 `event: response.*`、data.type、sequence_number 和类型化载荷；以 response.completed/failed/incomplete 处理终结，不转换成 Chat finish_reason 或 [DONE]。response.failed、error、异常 EOF、取消、提前断连均关闭 upstream；即使尚未读取首帧也必须清理。准入后仅结算一次，遵循已有可靠 settlement/UNKNOWN 语义；缺少可信 usage 不得按 0 成功入账。取消时若已获得完整 usage 则如实结算，否则进入已有未知用量恢复路径。

复用既有 261 模块错误及公开字符串码，供应商错误脱敏。新端点使用相同 desktop_principal 和实时授权，不新增凭据类型、Gateway 登录协议或独立配额表。没有新的 DB schema 或节点本地权威状态。

### 3.5 图片超限交给 Harness 持久卸载后重新派生

先用公开 projectOffloadedImages 生成稳定占位，再读取附件；同一附件只读取一次，每次出现分别计入预算。校验 PNG/JPEG/GIF/WebP 签名，并同时计算 raw、broker 解码估算、data URL 长度及完整 JSON envelope 字节数。

对现代 user/tool 图片计算满足全部限制所需的最小最旧前缀；单图过大时前缀至少延伸到该 occurrence。返回 `LlmError(IMAGE_OFFLOAD_REQUIRED, {offloadImages:n})`；由现有 compaction-image-offload 插件记录事件并重新 deriveMessages 后重试。adapter 不改真实 Session，也不在发送时偷偷删图。读取前后及发网前检查取消。

锁定 Harness 的卸载 walker 不支持旧式嵌套 tool-result 图片；包含此结构的超限请求明确返回不可恢复错误，避免 count 与实际可卸载对象不一致。缺图、坏格式、纯文本过大同样不可恢复，视觉能力缺失沿用既有拒绝。可支持旧格式的后续升级以真实 Session 重试测试为前提。

## 4. 契约、模块与限额

| 模块 | 本轮职责 | 边界 |
| --- | --- | --- |
| Desktop enterprise contract/service | 新能力与 reasoning 元数据校验、冻结快照 | 不推断供应商能力 |
| Desktop Chat adapter / 新 native bridge | Harness 转换、图片预算、回放来源校验 | 不持有企业 token，不决定授权 |
| main broker / enterprise-request | 固定操作、大小与字段白名单、真实凭据发送、取消 | 不允许任意 URL/头 |
| Bisheng schemas / endpoint | 严格协议和重复头检查、principal 获取、响应传输 | 不直接访问 ORM 或供应商配置 |
| DshModelService | 当前授权、协议选择、准入与结算 | 不实现协议字段转换 |
| model_capabilities / adapters | 配置能力、SDK 映射、使用量归一、协议事件 | 不跳过治理直连供应商 |

Responses 请求延用 32 MiB 完整 broker envelope 上限及图片限制；本地和服务器在累计读取时限制，不能先无界 response.text()。原生响应单个 SSE event/非流式 JSON 最大 8 MiB，累计输出最大 32 MiB；UTF-8 按字节计数，拆分 chunk 不绕过限制。达到上限中止，按已有失败/UNKNOWN 路径结算。服务端入口也必须有同等请求体累计限制，不能只信 content-length。

输入最多 4096 项、工具最多 128 项；单项文本、函数参数和加密内容仍受单事件及总大小限制。ID/call_id 最大 256 字符且无控制字符。允许清单覆盖 pi-ai 实际发送的 max_output_tokens、reasoning、text、tool_choice 等字段，逐项定义类型及供应商支持；不接受无约束字典。未知字段拒绝发生在 admission 前。

依赖官方 [OpenAI reasoning guide](https://platform.openai.com/docs/guides/reasoning) 的无状态加密回放约定，以及锁文件对应 pi-ai 的公开接口和 Harness providerMetadata/image-offload 契约。升级这些包须重新检查 replay 格式、terminal usage 补全和 loader 闭包；文档描述不能替代锁定版本行为测试。

## 5. 已知坑

| 事实 | 误判后果 | 处理位置 |
| --- | --- | --- |
| reasoning_content 与 reasoning_effort 独立 | 显示思考却丢失深度 | capabilities/schema/adapter |
| serializer 与主进程存在两次白名单 | 插件测试通过，实际 broker 仍拒绝 | enterprise-chat + broker 组合测试 |
| encrypted_content 可能只出现在终结 response | 工具后下一轮丢失推理状态 | native transport 捕获与 metadata |
| 图片重复引用会重复 base64 编码 | 按附件去重预算导致实际 413 | request-images occurrence 计数 |
| Sub2API 优先用 session_id | 未覆盖配置头会错误合并亲和 | upstream 请求级受控覆盖 |
| 断连可能发生在首帧读取前 | 漏清理或漏 settlement | PreparedStream 等价关闭路径 |
| native SDK 可能自动重试 | 一次授权调用发生重复上游执行 | 禁用 SDK 隐式重试，沿用显式企业策略 |

## 6. 验证与可观测

| AC | 必需证据 |
| --- | --- |
| R1–R3 | 配置矩阵、错误配置隐藏、默认/显式/非法档位；真实 serializer → HTTP broker → schema → SDK 本地接收端，断言参数且非法时无 admission |
| S1–S4 | 多轮、工具、system 变更及压缩后的同 ID；标题/压缩分域；跨用户/租户/模型摘要不同；重复头拒绝；本地 SDK 接收头与 Sub2API GenerateSessionHash 测试 |
| I1–I3 | 真实 Session 和卸载插件错误钩子 → image/offload 事件 → deriveMessages → 第二次实际 serializer/broker 验证；重复图片、后置大图、现代工具图、旧格式、取消、纯文本超限 |
| P1–P3 | 能力缺省/开启/失效；Responses HTTP+SSE；工具 call/result；terminal-only encrypted_content；持久化重启和跨账户/模型回放；未知类型严格拒绝 |
| P4–P5 | 完成/失败/incomplete/错误 EOF/未知用量/取消/首帧前断连；结算幂等与现有 UNKNOWN 机制；真实字节限制；无任意 URL/token/header 转发 |

Desktop 定向运行 `npx vitest run test/enterprise-chat.test.ts test/enterprise-openai-adapter.test.mjs`，实现时增加真实 broker/native/Session 测试；代码交付前按仓库规则执行 typecheck、build、完整 npm test、git diff --check。

Bisheng 从 `src/backend` 用隔离环境运行 `.venv/bin/python -m pytest --confcutdir=test/dsh test/dsh/test_models_api.py test/dsh/test_model_service.py test/dsh/test_vision.py -q`，清除进程代理变量后执行；新增原生及身份测试纳入同一套 isolated fixtures。不得为测试写入真实配置或连接生产资源。DM8、真实上游、Gateway/代理转发和各目标平台安装包单独报告。

联调使用独立开发 Profile/测试租户：管理员设置档位与 Responses 能力 → 登录刷新目录 → 同一对话连续工具调用并切换深度 → 独立标题/压缩调用 → 累计图片触发卸载 → 重启继续。对比 SDK 接收端脱敏的协议、effort、摘要、request_id、usage 和结算记录；浏览器或安装包 UI 需另外验证。日志只记录阶段、协议、公开模型 ID、请求 ID、大小、失败码及用途，不记录正文、密文、原始会话 ID 或凭据。

## 7. 推进顺序与回退

design 确认后再创建执行 tasks：先完成 Chat reasoning 与真实 broker/SDK 组合，再接身份隔离和图片真实恢复，最后增加 native schema/治理、客户端 bridge 和完整回放。每个切片保留可运行旧 Chat。

部署先服务端后客户端。关闭 native 能力只影响新生成选择；已有完整历史保留，不能清空用户会话。新客户端面对旧目录不发送未声明 reasoning、不走 native；目录过期导致服务端拒绝时刷新能力并提示，不能自动重放已开始的生成。新端点尚未满足所有 P 类验收时 capability 必须关闭。

## 8. 设计核查

按仓库 design-checklist 对照 spec 与版本契约完成自查：C1–C8 无新增架构例外；模型配置归属、租户/权限与实际用量治理沿用 F062；本轮不新增 schema 迁移或 Gateway 凭据协议。现有客户端协议版本的 additive 字段、新端点与严格拒绝规则应同步到原契约文档，不能仅留在此设计。

当前没有独立评审代理结果，也未运行所谓自动 Constitution Check。此文档只表示待确认方案；原生 bridge、真实 Session 重试、服务端 SDK 及安装包闭包仍需实现和验证，不能据设计自查宣称已验收。
