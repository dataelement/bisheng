# DSH 客户端模型审计：客户端接口契约

文档版本：0.4　日期：2026-10-16　状态：规格和设计已确认，两端已实现并通过本机实际客户端 HTTP 链路；真实三存储/正式 Electron 等待验收，未提交或发布

关联：[规格](./spec.md) · [技术设计](./design.md) · [任务记录](./tasks.md) · [既有客户端契约](../client-api.md)

现有两端代码已支持本版五字段，旧文档 0.3 的 `conversation_id`、`request_kind` 继续兼容。本版在能力协商基础上补充会话来源、直接父会话和最终输入消息的来源类型，不新增源消息 ID、轮次、任务树或响应后补报，不修改模型正文、凭证、用量、SSE 或取消语义。新扩展已验证真实适配器/主进程校验器到本机 HTTP 及独立 SQLite/内存存储；真实 MinIO、正式 Electron、真实供应商等门禁以最新验证记录为准。

0.4 是文档修订号，不是线协议字段；不增加 `audit_context.version`，`contract_version` 保持 0.5.0。客户端仅在实际 config 公布某字段时发送它，不能凭版本号推断支持，更不能遇到未知字段错误后自动重放模型请求。

## 1 开发范围与事实来源

桌面客户端为 bisheng-work 的 `feat/3.0.0-dsh-audit` 工作树，不是本仓库的 Web client。现有代码锚点如下，依赖升级时须重新核验：

| 位置 | 读取或修改内容 | 不做什么 |
|---|---|---|
| 企业插件 `index.js` | 经公开 `ctx.get('sessions')?.get(sessionId)` 读取已加载会话的 header，将同步只读 resolver 注入适配器 | 不强制注入 sessions 服务，不扫描/加载磁盘历史，不监听全部消息事件 |
| 企业模型适配器 `openai.js` | `sessionId`、`purpose` 与序列化前消息的 `source.kind/form`；在最终 messages.push 时同步记录来源 | 不复制完整 source，不按原始数组与最终数组直接 zip |
| `contract.js/.d.ts` | 能力白名单、规范化及限额，两端传递过程使用同一客户端实现 | 不放宽原有模型业务校验 |
| Electron `enterprise-chat.ts`、`enterprise-service.ts` 及类型 | 使用可信连接能力重新规范化，按最终消息数量检查对应关系 | 不信任请求自报能力，不把凭证交给插件 |
| Harness 公开类型和内置插件 | SessionHeader 的 origin/parentSession；GenerateOptions 的 purpose；内部 Message.source | 不修改 Harness 核心或 node_modules，不增加 patch |

当前依赖中子 Agent header 有 `origin='subagent'` 与 `parentSession`；普通 Fork 也可能有 parentSession，但没有子 Agent origin。内置压缩与标题分别设置 `purpose='compaction'/'session-title'`，仍带发起会话 sessionId。消息 role=user 可能来自技能目录或运行时上下文；source 缺失时不能推断为用户手输。

## 2 能力声明与缓存

`GET {BASE}/api/v1/dsh/config`，无请求体和 Authorization；BASE 为既有 Nginx 公开 origin。实现本版后 enabled 响应示例：

~~~json
{
  "enabled": true,
  "client_id": "dsh-desktop",
  "contract_version": "0.5.0",
  "audit_context": {
    "fields": [
      "conversation_id", "request_kind", "session_origin",
      "parent_conversation_id", "message_sources"
    ]
  }
}
~~~

字段子集合法，旧部署可能只公布两字段或完全没有 audit_context；部署未开启时仍返回 `{"enabled":false}`。能力仅表示可接收，不公开租户模式，不保证审计已经持久化。

1. 根响应先按主契约校验。仅 enabled=true、audit_context 为对象且 fields 为字符串数组时解析可选能力；坏的可选能力只移除扩展，不改变登录结果。
2. fields 去重并与本文五字段白名单取交集；未知字段忽略，空交集不发送扩展。只支持消息来源或用途、不支持会话 ID 也是合法子集。
3. 快照取自可信企业连接，按规范化 BASE 保存于进程内；登录、重连、企业 provider 初始化时刷新。切换 BASE、账号、连接时清除旧能力，重启不沿用未刷新的持久快照。
4. 已连接时仅可选能力刷新失败则清除该扩展快照；首次 config 的整体失败仍按原连接错误处理。请求使用当前快照，不为每次模型调用额外查 config；已发送请求不因能力变化重发。

## 3 请求字段与规范化

`POST {BASE}/api/v1/dsh/chat/completions`，Bearer DSH access token；顶层可选 `audit_context`，不是 OpenAI 模型参数。

### 3.1 请求级字段

| 字段 | 类型/限制 | 来源及行为 |
|---|---|---|
| conversation_id | 非空字符串，最多 256 Unicode 码点，UTF-8 可编码；原值精确保留 | 当前 GenerateOptions.sessionId；无值不临时造 ID 或借用登录会话编号 |
| request_kind | chat / compaction / session-title | purpose 未设置的已知普通路径为 chat；已知辅助用途原值；其他 purpose 省略 |
| session_origin | main / subagent | 已加载且 header.id 与 sessionId 精确相同时，origin=subagent 则 subagent；origin 未设置则 main（包括普通 Fork）；无法读取或未知 origin 则省略 |
| parent_conversation_id | 与 conversation_id 同样的字符串限制 | 只在有效子会话 ID、session_origin=subagent 且公开 parentSession 有效时发送；与自身 ID 相同则忽略。普通 Fork 不发送，不能代替子会话 ID |

四字段规范化后组成请求级 section，紧凑 JSON UTF-8 不超过 4096 字节。未知字段不参与序列化或预算检查；无效值逐字段忽略。`parent_conversation_id` 依赖有效子会话和 subagent 来源，但父字段无效不能使子会话或来源失效。其他字段相互独立，未提供的来源/用途显示未知。

### 3.2 message_sources：最终输入的来源标注

仅协商支持时发送可选对象：

~~~json
{
  "items": [
    {"message_index": 1, "sources": [{"kind": "runtime-context", "form": "snapshot"}]},
    {"message_index": 2, "sources": [{"kind": "skill-catalog", "form": "catalog"}]}
  ],
  "truncated": false
}
~~~

| 项 | 固定约定 |
|---|---|
| message_index | 最终 HTTP `messages[]` 的 0 基整数索引，不是内部源消息编号或显示气泡序号；禁止布尔值、小数、负数及越界值 |
| sources | 1–4 个来源描述，按首次出现顺序去重；仅 kind 与可选 form，不传 entries/sections/text/id/replayState 等完整 source 对象 |
| kind / form | 非空 ASCII 标识；kind 最多 64 字符，form 最多 32 字符，均匹配 `[A-Za-z0-9][A-Za-z0-9._:/-]*`；大小写原样保留。kind 无效则该来源无效，form 无效则只忽略 form |
| items | 按 message_index 严格递增，最多 128 项；没有已知来源的输入不填条目，不补造 generated/user 等标签 |
| truncated | 必填布尔值；表示客户端曾因数量、来源数或字节预算省略可取得的来源标注，不表示模型正文被截断 |
| 字节预算 | 整个规范化 message_sources 对象紧凑 JSON UTF-8 最多 12288 字节，独立于请求级 4096 字节；两端非 ASCII 不额外转义，无 lone surrogate、NaN 或 Infinity |

客户端在追加最终消息时同步生成映射：直接消息沿用该消息已知 source；一条内部消息拆成多个请求消息时分别沿用来源；多个工具图片合成一条请求消息时合并所有已知来源。合成消息包含无来源成分时不能宣称已覆盖全部来源；本版使用 truncated=true 表示映射信息不全，已知来源仍可保留，UI 显示“来源部分提供”。`options.system` 和临时压缩指令若没有 source，不伪造来源。

一个合成消息有超过 4 种来源时保留前 4 种并设 truncated=true；超过 128 项或 12288 字节时按最终索引保留可容纳的完整前缀，设 truncated=true。大小检查必须预留 truncated 字段，不截断字符串或模型正文。没有任何可取得的来源时省略整个 message_sources；确实发生删减但没有可容纳项时可发送 items=[]、truncated=true。

服务端与 Electron 对畸形输入：只扫描前 128 项，每项最多检查前 4 个来源，不无界遍历；超出的部分标部分提供。重复索引不采用 first/last-wins，已扫描重复索引的所有条目均忽略；越界/非法条目及无效来源忽略，其余有效条目可保留并标部分提供。section 非对象、items 非数组或 truncated 非布尔时仅丢弃该 section；其他层级的未知字段也忽略，不序列化或深遍历未知值。预算按提取的合法字段增量计算，超过 12288 字节时同样保留可容纳的完整前缀并标部分提供；不得先对整个原始扩展 JSON.stringify。拒绝后没有合法信息则标注无效；不回显无效值。依赖最终 messages 数量的校验在业务 DTO 合法之后执行，业务错误仍沿原规则拒绝。

有效标注不证明客户端来源真实，也不保证所有消息都有来源。不允许根据内容补全旧日志；source_kind 不是 role，也不是内容风险判定。

### 3.3 统一软降级与旧版兼容

| 情况 | 行为 |
|---|---|
| 无扩展、非对象扩展、无已公布合法字段 | 省略/忽略扩展，保留原合法模型请求；按生效模式产生请求级审计 |
| 请求级某字段无效 | 只忽略该字段及其依赖；消息标注仍可独立有效 |
| 消息标注超限、坏类型或索引无效 | 只降级标注；有效会话、用途、来源及父编号继续有效 |
| 未知/未公布字段 | 不读取其深层对象，不计算其序列化大小；忽略，不替它占用已知字段预算 |
| 旧服务端只公布两字段 | 新客户端裁剪为两字段，仍符合旧版 4096 字节规则；不发送新 section |
| 非法 JSON、原有通用请求大小上限、模型业务/认证/额度错误 | 保持既有拒绝语义，不能用审计软降级放宽业务限制 |

无合法字段时不发送空对象/null。不为审计拒绝、存储失败、缺能力或未知字段错误自动重试模型。

## 4 请求示例与服务端关系

子 Agent 发起一次压缩，最终请求包含系统消息、运行时上下文和无来源的临时指令：

~~~json
{
  "model": "bisheng:42",
  "messages": [
    {"role": "system", "content": "你是编程助手。"},
    {"role": "user", "content": "Current runtime context: ..."},
    {"role": "user", "content": "请压缩当前上下文。"}
  ],
  "stream": true,
  "stream_options": {"include_usage": true},
  "audit_context": {
    "conversation_id": "child-session-9",
    "request_kind": "compaction",
    "session_origin": "subagent",
    "parent_conversation_id": "parent-session-1",
    "message_sources": {
      "items": [
        {"message_index": 1, "sources": [{"kind": "runtime-context", "form": "snapshot"}]}
      ],
      "truncated": false
    }
  }
}
~~~

服务端取认证 tenant/user，与 child-session-9 归组；卡片显示子 Agent / 压缩。父编号仅是同一认证租户和该历史用户范围的可选导航，不替换自身会话，不影响正文去重作用域。父会话无可见记录时显示暂无可查看记录，不能查询其他用户或租户来补齐。

正文授权后，输入 NDJSON 的 unit_index=0 仍为模型参数，message_index=1 对应 input/unit_index=2；UI 展示该条真实 user 角色与“运行时上下文”来源。无来源的另外两条仍显示来源未提供。模型仅收到原有 model/messages/stream 等业务字段，绝不收到 audit_context。

普通会话使用自身 ID、session_origin=main 与实际用途；子 Agent 普通聊天仅将 request_kind 改为 chat。压缩和标题不新建会话，未知 purpose 省略用途。Fork 使用客户端已创建的新 Session ID，不因 parentSession 就标为子 Agent。未发送给模型的本地工具结果、事件或文件不额外上报。

## 5 链路、存储与管理读取

`可信 config 快照 → 企业插件解析已加载会话 → 适配器序列化并同步标注 → Electron 按可信能力净化 → 毕昇剥离扩展/严格业务校验 → 异步审计`

1. 两端共享各自规范化函数，不能出现插件允许而主进程静默丢弃所有新字段。Electron 不信任请求自报能力；会话 resolver 失败只省略会话来源，不加载历史或阻断生成。
2. 服务端字段与模型 DTO 分离，租户、用户、登录会话、request_id 和模式永远来自服务端；解析后仅用于审计，不加入统一模型入参或供应商 SDK 参数。
3. OFF 不产生本功能审计；METADATA 保留请求级字段，不存逐消息来源；CONTENT 才在独立加密对象中保存规范化来源标注。原模型输入输出及正文完整性不因标注缺失被改判。
4. 管理列表/详情只新增 session_origin 与 parent_conversation_id 等请求级字段，不返回逐消息数组、密钥或私有对象引用。标注仅随逐次授权留痕后的 body-access 返回，详见设计 §6.2；导航父会话不预读正文。
5. 来源记录使用客户端断言，不做真实性验证、完整任务图或历史回填；完整来源对象、认证凭证不进入标注、普通日志或错误。

## 6 响应和失败语义

不新增审计 ACK、回调或补报接口。错误体 request_id、完成对象 id（chatcmpl-前缀后编号）、流式增量 id、用量和审计继续复用同次服务端编号；客户端不自行覆盖它。审计存储或标注写入失败不令模型调用失败、重放或改变结算。

HTTP 200、SSE 正常结束和能力存在均不保证审计已持久化。客户端不等待审计页面可见，不因扩展改变 [DONE]、工具执行或取消处理。

## 7 测试与联调

以下是本版验收矩阵，执行/未执行证据见 validation-results.md 的 2026-10-16 增量记录，不沿用历史测试通过结论：

| ID | 场景 | 必验结果 |
|---|---|---|
| C-A01 | 旧客户端 → 新服务端 | 原合法请求仅调用一次；缺字段按未知/未关联，不造来源 |
| C-A02 | 新客户端 → 无能力旧服务端 | 不发送扩展，不探测重放 |
| C-A03 | 两字段能力、五字段能力、字段子集及畸形 config | 只发已知且获准字段；可选能力失败不改变根连接校验 |
| C-A04 | 两轮、重启或重新登录续接会话 | 复用现有 Session ID，保留各次独立请求 |
| C-A05 | 主会话、普通 Fork、子 Agent 及缺失会话服务 | 只 origin=subagent 标子 Agent；缺信息继续调用，Fork 不误标 |
| C-A06 | 主/子会话各自聊天、压缩、标题及未知 purpose | 用途与会话来源独立，不新建压缩会话、不合并父子 |
| C-A07 | 256/257 码点、12288/12289 字节、128/129 项、4/5 来源 | 边界确定；超限只影响相应 section，不丢有效会话，不改正文 |
| C-A08 | 插入 system、拆工具结果、合并多工具图片 | 标注对应最终索引，混合/缺失来源不冒充单来源 |
| C-A09 | BASE/账号切换与能力刷新失败 | 无旧能力或旧凭证串用，不重复调用 |
| C-A10 | 跨用户/租户同名父 ID、自指/环状/冲突关系、父记录缺失 | 只定位同历史租户/用户；无递归、无正文预取、无范围外存在性泄露 |
| C-A11 | 错误、SSE 中断、取消、客户端主动重试 | 原错误编号/响应/用量不变，审计不触发重试或补报 |
| C-A12 | 三档模式、存储/密钥失败、模式读取失败 | 按既定留存/降级规则；正文完整性与标注状态独立 |
| C-A13 | 同角色不同来源、未知/缺来源、来源对象带 entries 等 | 仅留受限 kind/form，不复制载荷，不从正文猜测 |
| C-A14 | 重复/负数/小数/布尔/越界索引，未知巨型字段 | 无效标注局部忽略，合法基础字段保留，校验有界 |
| C-A15 | 新旧 body-access、标注对象缺失/损坏、日志持久化失败 | 授权前无标注；失败不阻止已授权正文读取，日志失败则两者均拒绝；正文状态不受标注错误污染 |

客户端现有定向入口：`./node_modules/.bin/vitest run test/enterprise-audit-context.test.ts test/enterprise-chat.test.ts test/enterprise-contract-import.test.ts test/enterprise-audit-integration.test.ts`；适配器新增映射用例按实际测试文件扩展。完整检查沿客户端 AGENTS.md 的 npm test、typecheck、build；不使用旧 PoC 工作树作为开发或验收基线。

真实联调记录两端提交/构建、能力响应、合成请求、服务端编号、落库/正文读取及实际上游入参。只用隔离环境与合成正文；正式 Electron、供应商、DM8 未执行时单独注明，不能用 mock 或源码断言替代。

## 修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-14 | 0.3 | 请求级两字段契约及能力协商、缓存、软降级；现有代码基线 |
| 2026-10-16 | 0.4 候选 | 规格 0.20 确认后增加会话来源/父会话与最终消息来源；明确独立预算、映射、范围隔离及新版验收，等待设计确认 |
| 2026-10-16 | 0.4 确认及实现 | 用户确认后完成两端规范化与上报、独立加密标注、管理页读取与直接父会话导航；受控 HTTP 链路通过，真实三存储和正式 Electron 等待验收，尚未提交发布 |
