# Feature: F067 通用开放能力的统一远程 MCP 服务

> **本文档定位 — 纯 What（需求口径，不随代码漂移）**
>
> 本文只定义业务范围与验收标准；实现方案、协议适配、部署形态、接口与文件清单在设计确认后记录于
> [design.md](./design.md)。

**关联 PRD**: [《0923 中粮需求响应》§3「提供通用 API 与 MCP 接口」](https://dataelem.feishu.cn/wiki/YPnUwk9ZjiNYPdkmh1DcmiRnnac#doxcnWFZOYA02TvKHbI3ksU9Tvh)
**范围基线**: [中粮 SeedMind Apifox 开发者文档](https://s.apifox.cn/a0e36780-865a-4179-b7df-b51a01d5ebcc)
**优先级**: P1
**所属版本**: v3.0.0-beta1
**依赖**: F053 开放 API 鉴权与身份传递、F066 PAT 数据范围
**状态**: ✅ 能力范围已于 2026-09-15 按中粮 SeedMind Apifox 文档重新确认；Design 已于 2026-09-18 确认并生成 `tasks.md`

> **范围边界**
> - **本次纳入**：
>   - 每个 BISHENG 部署提供一个供外部客户端接入的统一远程 MCP 服务。
>   - 仅覆盖中粮 SeedMind Apifox 文档当前列出的 10 个知识资源/文件 API，每个 API 对应一个 MCP 工具。
>   - 沿用开放 API 的服务账号自身身份、服务账号代表他人、个人访问令牌知识只读，以及租户、资源权限、数据范围、业务状态和审计规则。
>   - 交付服务地址、客户端配置示例、工具说明和可核验的能力覆盖清单。
> - **本次明确排除**：
>   - 不开放上述 10 个 API 之外的任何能力，包括工作流、应用/知识助手、日常对话、语音、引用、问答对、元数据、分段上传与下载统计。
>   - Apifox 后续新增的 API 不自动进入本 Feature；扩围必须重新更新并确认 Spec/Design。
>   - 不新增凭据类型、身份模式、授权服务器或特定第三方平台的专用接入。
>   - 不替换、下线或改变现有开放 API 的调用合同。

---

## 1. 用户故事

作为 **需要把 BISHENG 能力接入智能体或自动化平台的集成方**，
我希望 **只配置一个远程 MCP 服务地址和一份既有凭据，即可发现并调用获准的 BISHENG 业务工具**，
以便 **用统一方式接入本期指定的知识资源和文件能力，而不必为每项能力单独集成**。

作为 **租户管理员与安全负责人**，
我希望 **MCP 与开放 API 使用完全一致的身份、权限、数据范围、失效和审计规则**，
以便 **增加接入方式时不产生第二套授权边界或越权通道**。

作为 **平台维护者**，
我希望 **正式开放能力与 MCP 覆盖关系能够被明确验收**，
以便 **开放能力演进时不会出现 MCP 静默漏能力或额外暴露能力**。

---

## 2. 验收标准

### 2.1 服务接入与能力覆盖

- **AC-01** — THE SYSTEM SHALL 为每个 BISHENG 部署提供一个统一远程 MCP 服务，使调用方通过同一服务完成工具发现和工具调用。
- **AC-02** — WHEN 调用方取得部署方提供的服务地址和有效的既有开放凭据, THE SYSTEM SHALL 允许其按交付说明完成接入，无需为不同业务组配置不同服务地址或签发新类型凭据。
- **AC-03** — THE SYSTEM SHALL 随服务交付可执行的客户端配置示例、工具用途与参数说明、认证说明及能力覆盖清单，且所有示例凭据均为不可用占位符。
- **AC-04** — THE SYSTEM SHALL 为中粮 SeedMind Apifox 范围基线中当前列出的 10 个 API 各提供一个 MCP 工具，包括知识资源查询、创建、更新、删除、清空、检索，以及文件上传、查询、删除、批量删除。
- **AC-05** — THE SYSTEM SHALL 保证上述 10 个工具全部可实际调用，且 `tools/list` 不得返回本期 allowlist 之外的 BISHENG 业务工具。
- **AC-06** — WHEN Apifox 文档后续新增、删除或修改 API, THE SYSTEM SHALL 保持本 Feature 的 10 项已确认 allowlist 不自动扩张；只有在 Spec/Design 重新确认后才能增删 MCP 工具。
- **AC-07** — THE SYSTEM SHALL 把现有开放 API 的全部接口逻辑视为冻结兼容基线，包括校验与分支、调用顺序、副作用、路由、请求字段/位置、默认值、响应字段、错误信封与 HTTP 状态；调用方可独立选择开放 API 或 MCP，F067 不得为适配 MCP 改变任何既有 API 接口逻辑。

### 2.2 工具发现与身份

- **AC-08** — WHEN 已认证调用方请求工具清单, THE SYSTEM SHALL 只返回该凭据类型、权限位和身份模式允许使用的工具。
- **AC-09** — IF 凭据缺失、无效、过期、已撤销或其主体已失效, THEN THE SYSTEM SHALL 拒绝工具发现与工具执行，不返回可供继续调用的业务能力。
- **AC-10** — WHEN 服务账号以自身身份调用工具, THE SYSTEM SHALL 以该服务账号作为业务执行主体和数据归属主体。
- **AC-11** — WHEN 服务账号以代表他人模式调用工具, THE SYSTEM SHALL 仅在被代表用户满足既有全部委托准入条件时，以该用户作为业务执行主体和数据归属主体。
- **AC-12** — IF 代表他人模式缺少有效被代表用户、目标不满足准入条件或委托范围不允许, THEN THE SYSTEM SHALL 拒绝调用，不得回退为服务账号自身身份。
- **AC-13** — THE SYSTEM SHALL 仅从受信任的认证上下文确定租户和执行主体；任何业务工具参数均不得选择、替换或提升执行主体。
- **AC-14** — WHEN 调用方使用个人访问令牌, THE SYSTEM SHALL 只允许其发现和调用本期 allowlist 中标记为 `knowledge:read` 的查询列表、检索分段和查询文件列表工具，不得提供知识或文件写入、删除、清空或委托能力。

### 2.3 调用期授权与失效

- **AC-15** — WHEN 调用方执行任一工具, THE SYSTEM SHALL 在该次调用时重新校验凭据、身份模式、租户、权限位、资源权限、数据范围和业务状态，不得把此前的工具发现结果当作永久授权。
- **AC-16** — WHEN 凭据撤销、过期、主体停用、权限变更或数据范围变更已经按开放 API 合同生效, THE SYSTEM SHALL 对后续 MCP 调用同步生效，包括通过既有连接发起的调用。
- **AC-17** — IF 调用所需的身份、权限、租户或数据范围无法确定，或授权依赖不可用, THEN THE SYSTEM SHALL 失败关闭，且不得执行部分业务、返回未过滤结果或降级为其他主体。
- **AC-18** — WHEN 调用涉及具体资源, THE SYSTEM SHALL 应用与对应开放 API 相同的资源动作、租户隔离、数据所有权和业务状态限制，即使该工具已出现在发现结果中也必须重新判定。

### 2.4 业务语义、安全与审计

- **AC-19** — WHEN 同一主体以等价业务输入分别通过开放 API 和 MCP 发起同一操作, THE SYSTEM SHALL 产生相同的业务结果含义、数据归属、持久副作用和权限边界；MCP 因 JSON object、base64、structuredContent 或 `oneOf` 需要采用不同线格式时，由 MCP adapter 按工具合同转换，不反向修改开放 API。
- **AC-20** — THE SYSTEM SHALL 在 MCP 中保持对应开放 API 的成功、空结果、分页、业务拒绝和失败语义，使调用方能够区分成功、无数据、参数错误、权限拒绝与服务失败；成功结果按逐工具 `outputSchema` 返回 MCP `structuredContent`，工具执行失败按 MCP 规范返回 `isError=true`、不设置 `structuredContent`，并在模型可见内容中返回明确、稳定的错误 `code` 与 `message`；未知工具、畸形请求和未预期服务端异常使用标准 JSON-RPC error 并返回协议 `code/message`。两类错误均不得要求沿用 HTTP `status_code/http_status` 或 API 错误信封。
- **AC-21** — WHEN 调用文件上传工具, THE SYSTEM SHALL 保持对应 API 的文件类型、大小、配额、解析参数、异步处理和错误语义；同时在 JSON 解析前限制 MCP 请求体，在解码/下载前后限制文件字节数，并约束 URL 协议、目标、重定向、超时和临时文件清理，不得因 base64 或 `file_url` 适配而弱化资源与网络安全边界。
- **AC-22** — WHEN MCP 工具调用被接受或拒绝, THE SYSTEM SHALL 形成与开放 API 同等级别、可关联实际凭据与执行主体的调用审计，同时不得记录明文凭据、认证头、请求文件内容或其它受保护输入。
- **AC-23** — IF MCP 调用在完成业务操作前失败, THEN THE SYSTEM SHALL 返回明确失败，不得把未执行、部分执行或结果未知报告为成功；业务操作自身的既有幂等与恢复语义保持不变。
- **AC-24** — THE SYSTEM SHALL 保持所有未进入本期 10 项 allowlist 的能力在 F067 MCP 中不可发现、不可调用，即使它们已经是其他开放 API 的正式能力。
- **AC-25** — THE SYSTEM SHALL 为每个工具提供可校验的 MCP `outputSchema`，其中每个成功输出字段都必须通过 `description` 明确业务含义、枚举值和资源类型适用范围，并为不能原样表达的业务结果提供逐工具兼容映射；schema 只校验成功时的 MCP `structuredContent`，不得要求或修改现有 API 输出。MCP 输出直接保留业务能力提供的 `actions` 与结构化 `TagItem[]`；不得无依据地转换为 `permission_ids` 或标签名称数组。
- **AC-26** — THE SYSTEM SHALL 为每个工具声明与实际副作用一致的只读、破坏性、幂等和开放世界 annotations；这些提示不得作为跳过服务端鉴权、资源动作检查或人工确认的依据。

---

## 3. 边界情况

- 工具曾在发现结果中出现，但凭据、权限或主体随后失效时，执行必须以调用时状态为准并拒绝。
- 凭据可发现某类工具但无权访问某个具体资源时，只拒绝该次资源调用，不得由工具可见性推导资源授权。
- 个人访问令牌持有人具有管理员身份时，仍须遵守 F066 的 PAT 数据范围；数据范围收窄不得被管理员能力绕过。
- Apifox 文档中用于代用户查询的身份信息不进入 MCP tool arguments；代表他人仍只能通过受信任的 `X-On-Behalf-Of` 认证上下文生效。
- 多租户环境中，任何身份、资源或数据结果都不得跨越凭据所属租户的既有边界。
- 本期覆盖采用一对一规则：10 个 allowlist API 必须恰好对应 10 个 MCP 工具。
- 现有 API 是只读业务基线：接口逻辑和请求/响应合同保持不变；任何 path/query/body 展平、顶层数组包装、文件转换、字段联合、结构化成功结果或 MCP 错误包装都只发生在 MCP adapter 内。
- 可以让 API 与 MCP 复用既有 application/domain Service；只有在出现真实重复时才允许抽取最小、传输无关的公共业务 capability。HTTP 与 MCP 的参数、响应及错误协议适配不得进入公共 capability，也不得借公共抽取改变既有 API 行为。

---

## 4. 设计与实现（指针，不复制）

| 你想知道 | 去哪看 |
|---|---|
| 服务形态、工具拆分、协议与能力映射 | design.md（Spec 确认后创建） |
| 10 个工具的稳定名称、顶层入参与出参 | [tool-contracts.md](./tool-contracts.md) |
| 任务拆解与验证记录 | tasks.md（Design 确认后创建） |
| 版本级归属、依赖与不变量 | [release-contract.md](../release-contract.md) |
| 架构与安全约束 | [docs/constitution.md](../../../docs/constitution.md) |

---

## 相关文档

- [Discovery 记录](./discovery.md)
- [F053 spec](../053-openapi-auth-and-identity/spec.md)
- [F053 v2 API 合同](../053-openapi-auth-and-identity/openapi-v2-key-auth-api.md)
- [中粮 SeedMind Apifox 范围基线](https://s.apifox.cn/a0e36780-865a-4179-b7df-b51a01d5ebcc)
- [MCP 工具合同](./tool-contracts.md)
- [F066 spec](../066-pat-data-scope-and-ai-access/spec.md)
- [版本契约](../release-contract.md)
