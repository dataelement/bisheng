# DSH 客户端模型审计：客户端开发接口契约

文档版本：0.3　日期：2026-10-14　状态：客户端首批已实现并通过 mock；服务端已实现字段接收，审计留存及真实联调待完成
关联：[规格 0.19](./spec.md) · [设计 0.8](./design.md) · [任务文档](./tasks.md) · [既有客户端契约 0.5.0](../client-api.md)

本文可直接交给客户端开发者。一期只在现有 Chat Completions 请求上附加两个可选字段：`conversation_id` 和 `request_kind`。服务端保存实际模型输入输出，并按认证租户、用户及客户端会话 ID 归组；客户端无需提交审计正文、源消息 ID、轮次、步骤、任务关系或响应后补报。

本文的 0.3 是文档修订号，不是线协议字段。不增加 `audit_context.version`，不要求仅为此扩展升级 `contract_version`。旧服务端可能不声明扩展；本分支已实现字段接收，但完整留存尚未实现。客户端必须读取实际能力声明后发送，不仅凭 0.5.0 版本号判断。本文替代旧 0.2 高级关联草案，不能据它声称原件已成功持久化或真实联调已通过。

## 1 客户端可以立即开始的工作

本轮正式开发工作树为 `/Users/zhangguoqing/works/bisheng-work/.worktrees/feat-3.0.0-dsh-audit`，同名分支基于最新 origin/main `3f6f010b280e7e095a13f59d8e3faae2c6223ab2` 创建，已由独立 agent 完成 C001 至 C009。114 项企业测试、typecheck/build 通过；C010 的 mock/JSONL 重开自动化已完成，真实 Electron 操作和 T064 未执行。下述 PoC 路径仅是历史调研参考，不是本次开发基线；详见 [阶段验证](./implementation-progress.md)。

沿现有企业插件、模型适配器、Electron 主进程请求链开发，先用 §2 的能力响应作为 mock。最终传给毕昇的模型业务请求保持既有形态，只增加顶层 `audit_context`；只影响毕昇企业 provider，其他第三方 provider 沿原有链路。

2026-10-14 复核的客户端 PoC 位置：

- 仓库：`/Users/zhangguoqing/works/bisheng-work`；PoC 工作树：`.worktrees/codex-dsh-audit-poc`，分支 `codex/dsh-audit-poc`，基线提交 `c452b3bc39d3bcccb1d4baca7661fdae3534d8b3`。
- `packages/dsh-desktop-enterprise/openai.js:EnterpriseLlmAdapter.stream` 已能读取 `GenerateOptions.sessionId` 与 `purpose`。
- `purpose` 的已知值为 `compaction`、`session-title`；普通生成路径未设置 purpose。
- PoC 仅验证了局部代码路径，当前临时钩子还包含 `version` 与消息来源信息，必须按本文精简；跨重启、能力协商和真实服务端上报仍需验收。
- 完整客户端任务见 [tasks.md 的客户端轨道](./tasks.md#client-work)。客户端开发不依赖服务端审计存储完成，可先交付能力解析、两字段组装、主进程透传及 mock 测试。

## 2 服务端能力声明

### 2.1 入口与响应

`GET {BASE}/api/v1/dsh/config`，无请求体、无 Authorization；BASE 仍是现有毕昇 Nginx 公开 origin。

支持一期两字段的新服务端响应：

~~~json
{
  "enabled": true,
  "client_id": "dsh-desktop",
  "contract_version": "0.5.0",
  "audit_context": {
    "fields": ["conversation_id", "request_kind"]
  }
}
~~~

只支持会话 ID 也是合法响应：

~~~json
{
  "enabled": true,
  "client_id": "dsh-desktop",
  "contract_version": "0.5.0",
  "audit_context": {
    "fields": ["conversation_id"]
  }
}
~~~

旧响应 `{"enabled":true,"client_id":"dsh-desktop","contract_version":"0.5.0"}` 保持有效，客户端不发送 `audit_context`。部署未开启时仍返回 `{"enabled":false}`。

能力只说明字段能被服务端接受，不公开租户 OFF/METADATA/CONTENT 模式，也不保证留存成功。客户端不按租户模式决定是否发关联信息；已认证的合法模型调用由服务端决定采集范围。

### 2.2 客户端解析规则

1. 先按既有契约校验根响应的 enabled、client_id、contract_version。
2. 只有 enabled=true 且 audit_context 是对象、fields 是字符串数组时解析审计能力；否则仅省略审计扩展，不把一个无效的可选能力字段当成登录或模型功能失败。
3. fields 去重后与本文已定义字段取交集。未知字段名忽略，不原样转发；交集为空时省略整个 audit_context。
4. 字段子集合法。只公布 conversation_id 时只发它；只公布 request_kind 时可以只发调用种类，该请求仍未关联会话。
5. 不根据 contract_version、客户端版本、提示词或一次未知字段错误猜测支持情况。

根响应、网络、鉴权等整体异常仍遵循既有接口契约；“省略可选扩展”不是把首次 config 请求失败当作已完成登录。

### 2.3 缓存与失效

能力按当前规范化 BASE 保存为进程内快照。登录/重新连接、企业 provider 初始化时读取 config；切换 BASE、账号或企业连接时清除旧能力，重新获取后再使用，客户端重启不沿用未经刷新验证的持久能力副本。服务端升级/降级后可通过重新连接或手动刷新 config 更新快照。

模型请求使用当前快照，不为每次请求或每个 SSE 增量额外查 config。在已有效连接上，仅审计能力刷新失败时清除该扩展快照，后续合法模型请求省略附加字段。已经发出的模型请求不会因能力变化被重发。

## 3 Chat Completions 扩展字段

### 3.1 请求入口和字段表

`POST {BASE}/api/v1/dsh/chat/completions`，Bearer DSH access token。既有 model/messages/tools/流式参数、凭证刷新、错误和取消语义见主客户端契约。

| 字段 | 类型及本期规则 | 来源与作用 | 无效或缺失时 |
|---|---|---|---|
| audit_context | 可选 JSON 对象；规范化紧凑 JSON 的 UTF-8 大小最多 4096 字节 | 与模型业务入参分离的附加信息；只含已公布且本文定义的字段 | 非对象或整体超限：忽略整个扩展，继续合法模型请求 |
| conversation_id | 可选非空字符串，最多 256 个 Unicode 码点；保留原值，不裁剪、不改变大小写，不要求 UUID/前缀/特定字符集合 | 直接取本次 GenerateOptions.sessionId；同一真实客户端会话继续使用现有持久 Session ID | 仅忽略该字段，审计显示未关联；不以登录会话、时间或相似文本推断 |
| request_kind | 可选字符串，只接受 chat、compaction、session-title | 仅作为请求卡片调用种类，不影响归组、身份、模型调用或计费 | 仅忽略该字段，显示调用种类未知，合法 conversation_id 仍可归组 |

256 码点与 4096 字节是附加字段的实现保护上限，不是会话 ID 生成格式或模型正文上限。客户端也应检查，并省略无效字段；不对模型正文做审计专用截断。JSON 大小按紧凑序列化、非 ASCII 不额外转义的 UTF-8 编码计算，两端采用相同规则。

字段独立：request_kind 不依赖 conversation_id。若只有一个有效且被公布的字段，可以只发送该字段；若没有有效字段，省略整个 audit_context，不发送空对象或 null。

### 3.2 调用种类映射

| 客户端观察到的调用路径/purpose | request_kind |
|---|---|
| 已确认的普通生成路径，purpose 未设置 | chat |
| purpose=compaction | compaction |
| purpose=session-title | session-title |
| 其他未定义 purpose 或无法确认路径 | 省略，服务端展示未知 |

取值大小写精确匹配。不能把未知 purpose 默认写为 chat，也不能从提示词或模型返回判断调用种类。压缩后摘要实际进入后续 messages 时随该请求照常发送；无需上报摘要来源。

### 3.3 请求示例

同一会话的第一次流式请求：

~~~json
{
  "model": "bisheng:42",
  "messages": [{"role": "user", "content": "你好"}],
  "stream": true,
  "stream_options": {"include_usage": true},
  "audit_context": {
    "conversation_id": "session-123",
    "request_kind": "chat"
  }
}
~~~

第二次请求继续使用原 Session ID，完整上下文仍由客户端既有算法产生：

~~~json
{
  "model": "bisheng:42",
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好"},
    {"role": "user", "content": "你会什么？"}
  ],
  "stream": true,
  "stream_options": {"include_usage": true},
  "audit_context": {
    "conversation_id": "session-123",
    "request_kind": "chat"
  }
}
~~~

同一会话的压缩调用用原会话 ID 和 request_kind=compaction；标题调用用 request_kind=session-title。Fork 使用客户端已经创建的新 Session ID；一期不传父会话关系。若当前调用拿不到 sessionId，则省略 conversation_id，不临时生成或借用登录会话 ID。

工具定义、调用、结果及图片仍在既有业务字段中发送。未进入模型请求的本地工具结果、文件或消息不额外上报。客户端按既有交互发起的重试是新请求，服务端生成新请求编号；客户端不为审计自动重试或归并请求。

## 4 组装、透传和服务端处理

### 4.1 客户端链路

`config → 企业连接的能力快照 → EnterpriseLlmAdapter.stream → 最终模型请求 + audit_context → brokerChat → Electron parseEnterpriseChatPayload → 企业请求 → 毕昇专用入口`

能力必须从现有可信企业连接状态交给插件；不能让任意模型请求自报“服务端支持”。Electron 只放行 audit_context 及本文两字段，对无效扩展执行省略/逐字段忽略，维持原有模型业务字段、图片限额和请求认证检查。仅扩展字段无效不得让合法模型调用在客户端先失败。

`packages/dsh-desktop-enterprise/contract.js:parseConfig` 当前会丢弃未定义字段，需要保存经过校验的可选能力；`enterprise-service.ts` 等现有连接状态链需将快照传到插件；`index.js` 注册适配器时传入关联组装回调；`openai.js` 只用 sessionId/purpose 组装两个字段。PoC 的 messageSources 观察钩子和 version 参数均不是本期上报前提。

### 4.2 服务端处理和降级矩阵

服务端在严格模型业务 DTO 校验前分离 audit_context，按已公布字段软解析，调用适配器前剥离。该扩展不传给统一模型接口或供应商，也不进入模型消息正文。

| 请求中的情况 | 服务端目标行为 |
|---|---|
| 完全没有 audit_context | 原有调用正常进行；开启模式下留存独立、未关联请求 |
| 有合法 conversation_id，request_kind 无效 | 保留会话归组；调用种类未知 |
| conversation_id 无效，request_kind 合法 | 未关联请求；仍保留合法调用种类 |
| audit_context 为 null、数组、字符串或整体超过 4096 字节 | 忽略整个扩展；合法模型调用继续 |
| 含未知/未公布字段 | 忽略对应字段，其他有效字段继续生效；客户端不应主动发送这些字段 |
| 不同用户传同一 conversation_id | 按认证租户、用户隔离，不能合并或跨用户复用正文 |
| 合法关联信息但租户 OFF 或读取失败降级 OFF | 模型照常调用，不产生模型请求审计；读取失败只尽力产生系统降级诊断 |
| 非法 JSON、业务参数错误、身份/模型权限/额度失败或既有通用安全限制触发 | 沿用既有错误语义；关联软解析不放宽模型业务规则 |

服务端不验证 ID 是否对应真实客户端会话。审计元数据可记录附加信息缺失/无效的诊断，不回显无效字段值或模型原文。tenant_id、user_id、登录 session_id、request_id、审计模式由服务端确定，客户端不能通过附加字段改变它们。

## 5 响应和错误编号

本扩展不新增审计 ACK、回调或补报接口，也不新增“审计失败”客户端模型错误。模型结果、SSE、用量及现有错误码保持既有语义；审计写入失败不会导致模型调用失败或重放。

目标服务端让一次请求的错误体 request_id、完成对象 id（chatcmpl-前缀后的编号）、流式增量 id、用量和审计使用同一编号。客户端应保留服务端返回的编号供排查，不自行生成或通过 X-Request-ID 覆盖。流式正常结束、失败和取消仍按主契约处理，不因有 audit_context 更改 [DONE] 或工具执行判断。

HTTP 200 或正常流式结束并不证明审计已留存。客户端无需等待管理员审计页面可见，也不在响应后补交本地消息。

## 6 客户端改动范围与测试

| 位置 | 本期开发内容 |
|---|---|
| contract.js / contract.d.ts | 解析、保留可选 fields；共享两字段校验与组装规则 |
| enterprise-service.ts / enterprise-desktop.ts | 按当前连接保存及对插件暴露非敏感能力快照；连接变化失效 |
| index.js / openai.js | 注册组装回调，从真实 sessionId/purpose 附加已公布字段 |
| enterprise-chat.ts / index.d.ts | 主进程边界放行、净化两字段，补齐类型；保持凭证注入和来源限制 |
| mock 与测试 | 缺能力、字段子集、非法附加字段、切换连接、两轮、标题、压缩、Fork、取消与错误编号 |

按客户端仓库 AGENTS.md 执行检查。在上述 PoC 工作树，可用 `npx vitest run test/enterprise-contract.test.ts test/enterprise-audit-context-poc.test.mjs test/enterprise-openai-adapter.test.mjs test/enterprise-chat.test.ts` 跑已存在测试；新增能力/集成测试按 [客户端任务](./tasks.md#client-work) 加入。既有 PoC 的高级字段期望须更新，不能以旧测试通过代表本契约实现完成。

## 7 双端联调用例

以下均为待执行，客户端可先用 mock；服务端真实审计可查询后由双方完成。

| ID | 场景 | 客户端/服务端验收 |
|---|---|---|
| C-A01 | 旧客户端 → 新服务端 | 一次合法模型调用；开启模式下有请求审计，未关联 |
| C-A02 | 新客户端 → 无审计能力的旧服务端 | 最终请求没有 audit_context；不触发未知字段失败或能力探测重放 |
| C-A03 | 只声明 conversation_id；未知字段名；fields 格式错误 | 已知字段取交集；错误可选能力只移除扩展，原有连接语义保持 |
| C-A04 | 两轮、重新登录、客户端重启续接现有会话 | 使用现有真实 Session ID；同认证用户同 ID 成一条请求时间线，各请求原件独立 |
| C-A05 | 不同会话及 Fork | 不同 Session ID 分组；不传父会话或消息来源 |
| C-A06 | 普通、压缩、标题和未知 purpose | chat/compaction/session-title 精确映射；未知省略；均按独立模型请求审计 |
| C-A07 | ID 缺失/错误类型/空字符串/256 与 257 码点；扩展 4096 与 4097 字节 | 有效边界接受；无效字段或超限扩展忽略；合法模型调用仍只发生一次 |
| C-A08 | 工具和图片请求 | 附加信息不改变最终模型业务内容；服务端统一接口不接收 audit_context |
| C-A09 | BASE/账号切换与能力刷新失败 | 不把旧能力或旧凭证送往新连接；仅可选能力失败时省略扩展 |
| C-A10 | 两用户同 ID、同用户大小写不同 ID、无会话 ID | 认证作用域隔离，原值精确比较；无 ID 未关联，不按文本推断 |
| C-A11 | 模型错误、SSE 中断、主动取消、客户端交互重试 | 保留返回编号；不为审计自动重试或补报；各次实际调用独立 |
| C-A12 | 租户 OFF/METADATA/CONTENT、审计存储故障及读取失败 | 客户端请求结构不依赖模式；服务端按模式留存/降级，审计故障不改变模型业务结果 |

联调材料记录 BASE（使用测试环境）、服务端/客户端提交与构建版本、能力响应、脱敏请求样本、服务端请求编号和预期/实际结论。测试只用合成正文与测试凭证；此材料用于证明实际线上链路，不以局部适配器单测替代。

## 修订记录

| 日期 | 文档版本 | 变更 |
|---|---|---|
| 2026-10-14 | 0.3 | 按一期请求审计重写为客户端开发契约；精简到会话 ID/调用种类，取消额外版本和高级关系，补齐能力缓存、校验、降级与双端验收 |
