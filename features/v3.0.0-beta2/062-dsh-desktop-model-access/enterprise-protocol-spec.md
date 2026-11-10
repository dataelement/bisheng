# 企业模型协议扩展 Spec

状态：用户已于 2026-10-16 确认 spec 与 design，进入实现；实际验证与交付边界见 `enterprise-protocol-tasks.md`。依据 `enterprise-protocol-discovery.md`，遵循 `docs/SDD-Guide.md` 的分阶段确认。

## 目标

使企业模型的思考深度、对话身份、图片恢复和原生 Responses 在受控链路中保持正确语义；兼容旧 Chat 客户端、旧服务端和未声明相应能力的模型。不提交、推送或部署。

## 验收标准

- AC-R1：管理员明确维护可选档位 `reasoning_efforts` 和默认 `reasoning_effort`；模型目录返回客户端既有 `reasoning.efforts/defaultEffort`，未声明时不推断档位或强加默认值。思考文本输出能力与深度独立。
- AC-R2：普通 Chat 请求的显式/默认 `reasoning_effort` 从客户端真实 serializer 穿过 broker、企业 schema 和供应商适配层；非法/未声明档位在供应商调用和计费 admission 前被拒绝。工具续轮保持同一选择。
- AC-R3：旧客户端和旧服务端保持兼容；配置错误的模型不可静默获得虚假能力；不将非 OpenAI 供应商误标为接受 OpenAI 参数。
- AC-S1：普通对话的 Harness ID 在多轮、历史压缩以及 system/tools 变化后保持稳定；不同对话可区分。
- AC-S2：压缩、标题等辅助用途与普通对话使用不同亲和作用域；没有对话 ID 时不使用登录 session_id 代替。
- AC-S3：Bisheng 使用已认证租户、用户、模型及用途隔离上游身份，不接受客户端伪造的租户或用户，不向供应商泄漏企业登录凭据。
- AC-S4：对话 ID/用途严格校验，拒绝非法、重复、过长输入；旧客户端不携带身份扩展时维持旧行为。当前 Sub2API 能识别最终标识；账号切换或故障不保证缓存命中。
- AC-I1：超限按照实际请求图片大小和 occurrence 计算；重复引用仍按多次预算计入。不得放宽 broker 和 Bisheng 的现有限制。
- AC-I2：可恢复超限返回 Harness `IMAGE_OFFLOAD_REQUIRED` 和最少需卸载的最旧图片数量，Harness 记录卸载决策后重新派生请求并能继续生成；不自行修改真实会话或静默丢图。
- AC-I3：已卸载图片转为稳定占位文本且不重读；缺图、无效格式、不可恢复的文本体积和不支持视觉的既有策略可区分；取消立即退出，不无限重试。
- AC-P1：原生 Responses 为独立协商能力，只有端到端实现的模型才可声明；旧 Chat 路径继续可用。底层使用上游 Responses 不算原生企业协议支持。
- AC-P2：原生请求和 SSE 保留完整类型化输出、工具 call ID、工具结果、reasoning encrypted_content；跨轮持久化及回放不丢失、不当文本显示、不串模型或租户。
- AC-P3：第一版无状态全历史往返；不引入供应商云端存储会话或跨身份引用远端响应 ID。失败时保留客户端可恢复历史。
- AC-P4：原生 Responses 复用现有企业认证、实时授权、租户作用域和配额治理；验证流式/非流式计量、缓存明细、未知用量、取消、断连、错误和终结语义。
- AC-P5：协议边界有严格输入/输出大小限制、错误脱敏和供应商能力校验；客户端不能指定任意 URL、凭据、头或未受控参数。

## 范围边界

不在本轮自动发布正式包或服务；不改变账号亲和为“保证缓存命中”；暂不补 `context.contextWindow`，也不顺带重构模型 UI、配额、授权或其他 WIP。

## 测试层次

组合回归必须穿过真实 Desktop 序列化、本地 broker 校验、Bisheng schema/adapter 和实际 SDK 请求构造；供应商及外部存储可使用隔离测试替身。分别报告离线构造、受控本地 HTTP、真实上游、目标平台安装包和生产验收，不能互相替代。
