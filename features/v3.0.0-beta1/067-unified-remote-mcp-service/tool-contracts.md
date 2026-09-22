# F067 MCP 工具合同

> **范围真相**：[中粮 SeedMind Apifox 开发者文档](https://s.apifox.cn/a0e36780-865a-4179-b7df-b51a01d5ebcc)，核对日期 2026-09-15。该文档只固定本期能力 allowlist 和业务语义；MCP 的线协议、输入/输出 schema 与错误结果以本文为准，不要求复制 HTTP API 信封。
>
> 本文固定本期 10 个 MCP 工具的名称、顶层入参与顶层出参。Apifox 后续变更不自动改变本文；扩围或破坏性变更必须重新确认 `spec.md` / `design.md`。

## 1. 通用规则

- 所有工具入参均为 JSON object；未声明字段必须拒绝。
- `Authorization`、`X-On-Behalf-Of`、`X-End-User` 是 MCP HTTP 请求头，不属于工具入参。
- `X-On-Behalf-Of` 与 `X-End-User` 互斥；身份、租户、`user_id`、`tenant_id` 和凭据不得由工具参数指定。
- MCP schema 保持 Apifox 对应 API 的业务字段含义、必填语义、默认值、枚举和限制；凡因 path/query/body、顶层数组、文件载体或 MCP schema 约束无法原样复用的字段名称/类型/结构，必须按 §2.4 显式转换。现有 API 的接口逻辑、校验、调用顺序、入参、出参、错误信封和 HTTP 状态均不随 MCP schema 改动。
- 为兼容本期 SDK 协商的 MCP 2025-11-25 协议，所有 `inputSchema` 与成功 `outputSchema` 均以 JSON object 为根；列表放入具名字段，资源变体在 object schema 内使用 `oneOf/$defs`，不返回裸数组或裸 `null`。
- 每个成功输出 property 必须在 `tools/list` 的 `outputSchema` 中提供非空 `description`，明确字段业务含义、枚举值和资源形态适用范围。资源公共 DTO 中不适用于当前 `type` 的字段可能仍返回固定值或 `null`，客户端必须先按 `type` 判断资源形态，不得仅以字段存在与否推断能力。
- 成功调用直接把下表声明的输出对象写入 MCP `structuredContent`，并同时提供内容等价的 JSON `TextContent` 作为兼容回退；不复制 HTTP API 的 `status_code/status_message/data` 信封，也不新增 `ok/http_status` 字段。
- `outputSchema` 只校验成功时的 `structuredContent`。删除、清空等原 API 成功数据为空的操作，在 MCP 中统一返回 `OperationResult`，保证成功结果仍是可校验的 JSON object：

```json
{
  "success": true
}
```

工具执行失败按 MCP 规范返回 `isError=true`，不提供 `structuredContent`；模型可见的 `TextContent` 必须是包含明确 `code` 与 `message` 的 JSON。已有稳定业务错误码时复用该业务码；MCP 专有输入校验使用稳定符号码。不得把 HTTP `status_code`、`http_status` 或 API 错误信封塞进 MCP 工具输出：

```json
{
  "error": {
    "code": 10962,
    "message": "Knowledge resource does not exist"
  }
}
```

未知工具、无效 JSON-RPC 消息、未预期服务端异常等协议级失败使用 MCP/JSON-RPC 标准错误（包括 Internal Error `-32603`）且明确返回协议 `code/message`。HTTP 认证或请求体上限在进入 MCP handler 前失败时，继续使用 transport HTTP 状态，也不伪造成工具结果。

没有既有业务码的工具执行错误只允许使用 `design.md` §4.4 固定的 MCP 符号码；不得临时拼接新错误码，也不得把 HTTP status 数字当成 MCP 业务错误码。

## 2. 工具清单与顶层 schema

| MCP 工具 | source API | 输入字段 | MCP 成功输出 |
|---|---|---|---|
| `bisheng_knowledge_list` | `GET /api/v2/filelib/` | `type?: 0\|1\|3=0`；`name?: string`；`sort_by?: update_time\|create_time\|name=update_time`；`page_size?: integer=10`；`cursor?: string` | `ResourceListData` |
| `bisheng_knowledge_create` | `POST /api/v2/filelib/` | `name: string`；`type?: 0\|1\|3=0`；`description?: string\|null`；`model?: string\|null`（type 0/1 必填，type 3 忽略）；`auth_type?: public\|private\|approval=public`（仅 type 3）；`is_released?: boolean=false`（仅 type 3） | `Resource` |
| `bisheng_knowledge_update` | `PUT /api/v2/filelib/` | `knowledge_id: integer`；`name?: string\|null`；`description?: string\|null`。保持原 API 语义：`name` 不传不修改，`description` 不传则置空 | `Resource` |
| `bisheng_knowledge_delete` | `DELETE /api/v2/filelib/{knowledge_id}` | `knowledge_id: integer` | `OperationResult` |
| `bisheng_knowledge_clear` | `DELETE /api/v2/filelib/clear/{knowledge_id}` | `knowledge_id: integer` | `OperationResult` |
| `bisheng_knowledge_retrieve` | `POST /api/v2/filelib/retrieve` | `query: string(minLength=1)`；`knowledge_base_ids: integer[](minItems=1)`；`filters?: RetrieveFilters\|null`；`top_k?: integer[1,200]=10`；`max_content?: integer(minimum=1)=15000` | `RetrieveData` |
| `bisheng_knowledge_file_upload` | `POST /api/v2/filelib/file/{knowledge_id}` | `knowledge_id: integer`；文件来源二选一：`file_name: string` + `content_base64: string(maxLength=§2.2)`（`mime_type?: string\|null`）或 `file_url: string(uri, §2.2 受控目标)`；`parent_id?: integer\|null`；`split_mode?: auto\|custom\|hierarchical=auto`；`separator?: string[]`；`separator_rule?: string[]`；`chunk_size?: integer`；`chunk_overlap?: integer`；`retain_images?: 0\|1=1`；`force_ocr?: 0\|1=0`；`enable_formula?: 0\|1=1`；`filter_page_header_footer?: 0\|1=0` | `FileRecord` |
| `bisheng_knowledge_file_list` | `GET /api/v2/filelib/file/list` | `knowledge_id: integer`；`parent_id?: integer`；`keyword?: string`；`status?: integer[]`（1 处理中、2 成功、3 失败、4 重建中、5 排队中、6 超时、7 内容安全违规）；`page_size?: integer=10`；`cursor?: string` | `FileListData` |
| `bisheng_knowledge_file_delete` | `DELETE /api/v2/filelib/file/{file_id}` | `file_id: integer` | `OperationResult` |
| `bisheng_knowledge_files_delete` | `POST /api/v2/filelib/delete_file` | `file_ids: integer[]` | `OperationResult` |

### 2.1 两处协议适配

1. Apifox 上传接口的 multipart `file` 在 MCP 中表示为 `file_name`、可选 `mime_type` 和 `content_base64`；不得接受服务器本地 `file_path`。`file_url` 与 base64 文件仍严格二选一，并遵守 §2.2 的入口级限制；解码或下载后的临时文件继续执行原 API 的类型、单文件大小、角色总配额与内容安全校验。
2. Apifox 批量删除接口的请求体是顶层 `integer[]`；MCP arguments 必须是 object，因此固定包装为 `{ "file_ids": [5001, 5002] }`。

### 2.2 上传入口限制

- 新增部署配置 `open_mcp.max_inline_upload_bytes`，默认 `50 * 1024 * 1024`。base64 路径实际允许的解码字节数为 `min(open_mcp.max_inline_upload_bytes, get_max_upload_bytes(file_name))`；大于该值的文件必须改用受控 `file_url`，不得通过调高 JSON body limit 绕过。
- `content_base64` 的 JSON Schema 必须声明 `maxLength = 4 * ceil(open_mcp.max_inline_upload_bytes / 3)`。ASGI 在认证成功后、JSON 解析前以 `maxLength + 1 MiB` 为整个 MCP POST body 上限；商业网关使用相同上限并关闭无限缓冲。超过任一上限返回 HTTP `413`，不进入 MCP handler 或业务 Service。
- base64 必须使用严格校验模式并按块解码到受管临时文件；禁止同时长期保留完整编码串和完整解码字节。无论成功、参数错误、取消或异常，临时文件都必须在 `finally` 中清理。
- 解码或下载前必须先校验目标知识资源、可选父目录的写权限和租户边界；文件准备完成后仍由既有业务 Service 再次鉴权。受管文件只存在于请求私有临时目录，文件名保留既有处理链需要的内容摘要前缀，不得复制到无请求级清理机制的长期 cache。
- `file_url` 只接受 `https`；平台配置的 MinIO share origin 可显式允许 `http`。目标 host 必须是该 MinIO origin 或 `open_mcp.file_url_allowed_hosts` 中的精确项；每次 DNS 解析和每个重定向跳转都重新校验，默认拒绝 loopback、link-local、metadata 地址和私网地址，除非该 origin 是平台明确配置的对象存储地址。
- URL 下载必须流式写临时文件：先检查可信 `Content-Length`，读取时再次按累计字节硬截断，限制为 `get_max_upload_bytes(file_name)`；连接/读取超时和最大重定向次数必须固定。不得调用当前可一次性读取完整响应体、接受任意 URL 的通用 `async_file_download` 路径。
- 本版 MCP schema 不暴露 `callback_url`。现有 HTTP API 的异步 worker 会在稍后重新解析并发送该 URL；在不改变冻结 API 逻辑的前提下，MCP 入口无法保证发送时 DNS 固定和禁止重定向，因此 MCP 明确收窄该可选参数并始终向公共业务能力传 `None`。后续若提供专用持久化 callback relay，需重新评审后再加入 MCP 合同。

### 2.3 工具行为 annotations

annotations 只描述客户端风险与重试提示，不参与服务端授权。`tools/list` 必须返回下表固定值并纳入契约测试：

| MCP 工具 | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---:|---:|---:|---:|
| `bisheng_knowledge_list` | true | false | true | false |
| `bisheng_knowledge_create` | false | false | false | false |
| `bisheng_knowledge_update` | false | false | true | false |
| `bisheng_knowledge_delete` | false | true | true | false |
| `bisheng_knowledge_clear` | false | true | true | false |
| `bisheng_knowledge_retrieve` | true | false | true | false |
| `bisheng_knowledge_file_upload` | false | false | false | true |
| `bisheng_knowledge_file_list` | true | false | true | false |
| `bisheng_knowledge_file_delete` | false | true | true | false |
| `bisheng_knowledge_files_delete` | false | true | true | false |

### 2.4 API → MCP 单向兼容规则

现有 source API 是冻结兼容基线；本文件只定义 MCP 对外合同。实现不得为满足 MCP schema 修改 source API 的 endpoint 接口逻辑、校验与分支、调用顺序、副作用、签名、path/query/body 位置、默认值、响应字段、错误信封或 HTTP 状态。不能原样复用时按下表只在 MCP adapter 内转换：

| 场景 | 现有 API 保持 | MCP 兼容方式 |
|---|---|---|
| path/query/body 参数 | 原参数位置和 FastAPI 校验不变 | 展平为工具 arguments object；adapter 重建业务 command |
| 批量删除 | 顶层 `integer[]` 不变 | MCP 使用 `{ "file_ids": [...] }`，adapter 解包后调用既有能力 |
| 文件上传 | multipart `UploadFile` / `file_url` 不变 | MCP base64 流式落临时文件并构造成上传输入；或使用 §2.2 受控 URL |
| 成功信封 | API 继续返回当前 `status_code/status_message/data` | MCP 去除 HTTP 信封，只把本文件定义的成功 DTO 直接写入 `structuredContent`；空成功映射为 `OperationResult` |
| 异构资源/文件响应 | API 当前 type 0/1/3、知识库/知识空间形态不变 | MCP `outputSchema` 使用明确 `oneOf`/可选字段，复制实际存在字段，不合成不存在字段 |
| 工具执行错误 | API 现有业务校验/异常分支、业务码、消息、data、错误信封和 HTTP 状态不变 | MCP adapter 返回 `isError=true`，不设置 `structuredContent`；JSON `TextContent` 明确给出 `error.code/error.message`，不沿用 HTTP 状态字段 |
| 协议错误 | API 不涉及未知 MCP 工具、畸形 JSON-RPC 或 MCP server crash | 返回标准 JSON-RPC error 的 `code/message`，不伪造成工具业务结果 |

输出映射函数必须按工具显式登记，例如 `map_knowledge_resource_to_mcp`、`map_file_item_to_mcp`；禁止反射式返回任意 ORM 字段。若 source API 后续新增字段，MCP 不自动暴露，须重新确认本合同。`actions` 与 `TagItem[]` 已能被 MCP JSON Schema 原样表达，因此不做 `actions → permission_ids` 或 `TagItem → name` 转换；这两类转换既不是业务需要，也不是协议需要。

## 3. 输出模型

### `OperationResult`

```text
success: true
```

### `Resource`

`Resource` 必须覆盖当前业务能力返回的 `KnowledgeRead`、知识空间列表装饰字段，以及知识空间更新返回的持久化模型。公共字段 `id / name / type` 必须存在；带 `?` 的字段允许缺失，带 `| null` 的字段允许显式 `null`。`additionalProperties=false`；有效动作字段原样使用 `actions`，不引入 `permission_ids` 别名。

```text
id: integer
name: string
type: 0 | 1 | 3
user_id?: integer | null
tenant_id?: integer | null
description?: string | null
model?: string | null
collection_name?: string | null
index_name?: string | null
state?: integer | null
auth_type: public | private | approval
is_released: boolean
is_shared: boolean
auto_tag_enabled: boolean
auto_tag_library_id?: integer | null
metadata_fields?: MetadataField[] | null
create_time?: string(date-time) | null
update_time?: string(date-time) | null

# KnowledgeRead / 列表装饰字段
user_name?: string | null
copiable?: boolean | null
is_pinned?: boolean | null
actions?: string[] | null
is_followed?: boolean
subscription_status?: subscribed | pending | rejected | not_subscribed
user_role?: creator | admin | member | null

# 知识空间 update 当前持久化返回可能携带
creation_request_id?: string | null
creation_payload_hash?: string | null
```

实现使用一个显式的 MCP 专用 `KnowledgeResource` DTO：`id/name/type` 与公共布尔字段固定，知识库视图和知识空间持久化形态的差异字段按上表声明为可选；不得直接把 ORM/SQLModel 当作 MCP 输出模型。这样保持 `outputSchema` 的 object 根节点，也不会因 source API 某一分支缺少装饰字段而伪造值。映射器从现有 API/业务返回对象读取当前字段生成 MCP DTO，但现有 HTTP adapter 继续沿用原响应模型，不切换为 MCP DTO。

关键资源字段语义固定如下；实际字段名为 `is_released`，不是 `is_release`：

| 字段 | 含义与适用范围 |
|---|---|
| `type` | `0` 文档知识库、`1` 问答知识库、`3` 知识空间 |
| `is_released` | 是否发布到知识广场；仅 `type=3` 有业务意义，`type=0/1` 不使用，调用方应忽略 |
| `auth_type` | 知识空间访问方式；仅 `type=3` 有业务意义，`type=0/1` 不使用 |
| `model / collection_name / index_name / state` | 知识库模型、存储索引和处理状态；知识空间不使用 |
| `actions` | 当前身份的有效业务动作代码，不是 `permission_ids` |
| `is_pinned / is_followed / subscription_status / user_role` | 当前身份在知识空间上的个人状态；仅 `type=3` 使用 |

### `ResourceListData`

```text
data: Resource[]
page_size: integer
has_more: boolean
next_cursor: string | null
```

### `RetrieveFilters`

```text
knowledge_base_filters: Array<{
  knowledge_base_id: integer,
  tags: string[],
  tag_match_mode: "ANY" | "ALL" = "ANY"
}>
```

`ALL` 按当前 API 合同保留但尚未投入业务使用；调用结果不得伪装为已支持的匹配语义。

此处 `tags: string[]` 是检索过滤器自身的标签名称入参，不是把文件列表输出中的 `TagItem[]` 扁平化；两份合同分别保持各自类型。

### `RetrieveData`

```text
chunks: Array<{
  content: string,
  knowledge_id: integer,
  document_id: integer,
  document_name: string,
  document_update_time: string,
  chunk_index: integer
}>
total: integer
```

### `FileRecord`

`FileRecord` 是上传返回的公共文件记录。除 `id / knowledge_id / file_name / file_type` 外，以下字段按现有业务模型允许缺失或为 `null`：

```text
id: integer
knowledge_id: integer
file_name: string
file_type: 0 | 1
user_id?: integer | null
user_name?: string | null
tenant_id?: integer | null
thumbnails?: string | null
file_source?: string | null  # 当前已知值：upload/channel/space_upload/audio_transcript/video_transcript/web_link
level?: integer | null
file_level_path?: string | null
abstract?: string | null
file_size?: integer | null
md5?: string | null
parse_type?: string | null
split_rule?: string | null
preview_file_object_name?: string | null
bbox_object_name?: string | null
status?: 1 | 2 | 3 | 4 | 5 | 6 | 7 | null
object_name?: string | null
user_metadata?: object | null
remark?: string | null
file_encoding?: string | null
simhash?: string | null
similar_status?: integer
updater_id?: integer | null
updater_name?: string | null
create_time?: string(date-time) | null
update_time?: string(date-time) | null

# 知识空间上传扩展
old_file_level_path?: string | null
approval_request_id?: integer | null
approval_status?: string | null
approval_reason?: string | null
is_pending_approval?: boolean
version_no?: integer | null
is_multi_version?: boolean
has_similar?: boolean
```

### `FileListData`

```text
data: FileItem[]
page_size: integer
has_more: boolean
next_cursor: string | null
writeable: boolean
```

### `FileItem`

`FileItem` 以 `FileRecord` 为基础，并允许知识库与知识空间列表各自已有的装饰字段：

```text
...FileRecord
title?: string | null
tags?: TagItem[]
has_failed_files?: boolean
has_abnormal_files?: boolean
success_file_num?: integer
processing_file_num?: integer
version_no?: integer | null
is_multi_version?: boolean
has_similar?: boolean
```

`MetadataField` 对齐当前知识资源元数据字段：

```text
field_name: string(maxLength=255, pattern=^[a-z][a-z0-9_]*$)
field_type: string | number | time
updated_at: integer
```

`TagItem` 对齐当前标签响应：

```text
id?: integer | null
name?: string | null
business_type?: string
business_id?: string | null
user_id?: integer
tenant_id?: integer | null
create_time?: string(date-time) | null
update_time?: string(date-time) | null
```

实现必须为 `OperationResult / Resource / MetadataField / FileRecord / FileItem / TagItem` 生成完整 MCP JSON Schema，不能用无约束顶层 `object` 代替。只有现有 API 本身定义为动态键值映射的 `user_metadata` 允许 `additionalProperties`，其值 schema 必须直接复用当前业务模型；知识库与知识空间响应允许通过 `oneOf` 表达。MCP 成功结果必须等于“既有业务结果经过 §2.4 MCP 适配”的结果，不要求 API 原始 JSON 直接通过 MCP `outputSchema`。

## 4. 交付校验

- `tools/list` 恰好注册本文件的 10 个工具，并按 scope/凭据类型过滤可见集合；registry 与本清单双向差集必须为空。
- 每个工具必须同时输出 `inputSchema`、`outputSchema` 与 §2.3 annotations；MCP schema 以本文件为准，并通过 §2.4 映射兼容当前 source API 与 Apifox 合同，不反向改变 API。
- 10 个工具至少各完成一次成功调用，并覆盖参数错误、资源无权限、凭据失效和依赖不可用的拒绝路径；工具执行错误必须断言 `isError=true`、无 `structuredContent`，且模型可见 JSON 中存在非空 `error.code` 与 `error.message`；未知工具、畸形请求和未预期服务端异常必须断言为标准 JSON-RPC error 且存在协议 `code/message`。
- 同一主体、等价业务输入经 API 与 MCP 调用时，数据归属、持久副作用、权限结论和业务结果含义必须一致；线格式差异只允许来自 §2.4 的显式映射。
- 契约测试必须先冻结 source API 的接口逻辑、请求/响应和主要错误快照，再用 type 0、1、3 分别覆盖资源列表/创建/更新，并用知识库与知识空间分别覆盖文件上传/列表；将业务结果经过对应 mapper 后再用 MCP `outputSchema` 校验，同时断言 API 快照未变，MCP 保留 `actions` 与结构化 `TagItem[]`，没有无依据的 `permission_ids` 或标签名称扁平化。
