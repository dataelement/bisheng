# Open MCP 接入指南

F067 在每个 BISHENG 部署上提供一个统一的远程 MCP 服务，本期仅暴露
10 个知识资源和知识文件工具。MCP 的 JSON 合同由 MCP 层适配，不会修改
对应的 `/api/v2/filelib/` HTTP API 入参、出参、错误信封或业务逻辑。

## Endpoint 与协议

- Endpoint：`https://<BISHENG_HOST>/api/v2/mcp`
- Transport：MCP Streamable HTTP，无状态模式
- 请求认证：每个 HTTP 请求都必须带 `Authorization: Bearer <credential>`
- 工具发现：客户端先完成 `initialize`，再调用 `tools/list`
- 工具调用：使用 `tools/call`，工具参数始终是 JSON object

客户端应使用支持 Streamable HTTP 的 MCP SDK，由 SDK 处理
`MCP-Protocol-Version` 和 `Accept` 等协议头；不应把 MCP session id 当作身份凭据。

## 认证与身份

`Bearer` 值可以是已有开放 API 的服务账号 API Key，也可以是租户允许的
PAT（个人访问令牌）。MCP 与开放 API 复用同一套凭据过期、撤销、主体状态、
scope、租户、数据范围和资源权限判定。`tools/list` 只返回当前凭据可使用的工具，
具体资源仍会在调用时逐次鉴权。

| 凭据模式 | HTTP headers | 可用范围 |
|---|---|---|
| 服务账号自身身份（S） | `Authorization: Bearer <API_KEY>` | 由 API Key 的 `knowledge:read` / `knowledge:write` scope 决定 |
| 服务账号委托身份（D） | 上述 header + `X-On-Behalf-Of: <BISHENG_PLATFORM_USER_ID>` | 另需凭据允许委托，按被代表用户执行 |
| PAT | `Authorization: Bearer <PAT>` | 仅可发现和调用 3 个 `knowledge:read` 工具 |

`X-End-User: <external_user_partition>` 只用于已有 F053 终端用户分区语义，不能与
`X-On-Behalf-Of` 同时使用。`Authorization`、`X-On-Behalf-Of`、`X-End-User`、
`user_id` 和 `tenant_id` 都不属于工具 arguments，不得由模型在工具参数中指定。

## 10 个工具

| 工具 | scope | PAT | 主要输入 | 成功输出 |
|---|---|---:|---|---|
| `bisheng_knowledge_list` | `knowledge:read` | 是 | `type?`, `name?`, `sort_by?`, `page_size?`, `cursor?` | `ResourceListData` |
| `bisheng_knowledge_create` | `knowledge:write` | 否 | `name`, `type?`, `description?`, `model?`, `auth_type?`, `is_released?` | `KnowledgeResource` |
| `bisheng_knowledge_update` | `knowledge:write` | 否 | `knowledge_id`, `name?`, `description?` | `KnowledgeResource` |
| `bisheng_knowledge_delete` | `knowledge:write` | 否 | `knowledge_id` | `{"success":true}` |
| `bisheng_knowledge_clear` | `knowledge:write` | 否 | `knowledge_id` | `{"success":true}` |
| `bisheng_knowledge_retrieve` | `knowledge:read` | 是 | `query`, `knowledge_base_ids`, `filters?`, `top_k?`, `max_content?` | `RetrieveData` |
| `bisheng_knowledge_file_upload` | `knowledge:write` | 否 | `knowledge_id` + base64 或受控 URL，以及解析参数 | `FileRecord` |
| `bisheng_knowledge_file_list` | `knowledge:read` | 是 | `knowledge_id`, `parent_id?`, `keyword?`, `status?`, `page_size?`, `cursor?` | `FileListData` |
| `bisheng_knowledge_file_delete` | `knowledge:write` | 否 | `file_id` | `{"success":true}` |
| `bisheng_knowledge_files_delete` | `knowledge:write` | 否 | `file_ids` | `{"success":true}` |

完整的字段类型、枚举、默认值、上限和 `inputSchema` / `outputSchema` 由
`tools/list` 返回。每个成功输出字段都在 `outputSchema` 中带有 `description`，说明其
业务含义、枚举值以及只适用于知识库、知识空间、文件或文件夹的条件。下列约束容易被
客户端忽略：

- `type` 为 `0` 或 `1` 时，创建工具的 `model` 必填。
- 批量删除在 MCP 中为 object：`{"file_ids":[5001,5002]}`，不是顶层数组。
- 上传不接受服务器本地 `file_path`；`content_base64` 和 `file_url` 必须二选一。
- 成功返回的知识资源动作字段保留为 `actions`，文件标签保留为结构化
  `TagItem[]`，不转成 `permission_ids` 或标签名数组。

### 关键输出字段语义

实际字段名是 `is_released` (不是 `is_release`)。资源类型不同但复用同一个
`KnowledgeResource` 输出模型时，不适用的字段会返回固定值或 `null`；客户端应先根据
`type` 判断资源形态，不应仅凭某个公共字段是否存在来推断能力。

| 字段 | 含义与适用范围 |
|---|---|
| `type` | `0`=文档知识库，`1`=问答知识库，`3`=知识空间 |
| `is_released` | 知识空间是否发布到知识广场；仅 `type=3` 有业务意义，`type=0/1` 不使用，调用方应忽略 |
| `auth_type` | 知识空间访问方式：`public/private/approval`；仅 `type=3` 有业务意义，`type=0/1` 不使用 |
| `model` | 文档/问答知识库使用的模型标识；知识空间不使用，通常为 `null` |
| `state` | 知识库状态：`0` 未发布、`1` 可用、`2` 复制中、`3` 重建中、`4` 重建失败；知识空间不使用 |
| `actions` | 当前身份对资源拥有的有效业务动作代码，不是角色 ID 或 `permission_ids` |
| `is_pinned/is_followed/subscription_status/user_role` | 当前身份在知识空间上的个人状态；仅 `type=3` 使用 |
| `file_type` | `0`=文件夹，`1`=文件 |
| `status` | 文件处理状态：`1` 处理中、`2` 成功、`3` 失败、`4` 重建中、`5` 排队中、`6` 超时、`7` 内容安全违规 |
| `writeable` | 当前身份是否可向本次文件列表所查询的目录上传文件 |
| `tags` | 文件关联的结构化标签列表 `TagItem[]`；不是标签名称数组 |
| `has_failed_files/has_abnormal_files` | 文件夹后代异常汇总；后者是知识空间创建者可见的提示，文件条目不适用 |
| `approval_* / is_pending_approval` | 部门知识空间上传审批信息；无需审批的资源不适用 |
| `version_no/is_multi_version/has_similar` | 文件多版本和相似文件状态；文件夹不适用 |

其余存储对象名、目录路径、元数据、分页游标和检索分段字段的含义，以客户端实际收到的
`outputSchema.properties.<field>.description` 为准。

## 成功与错误输出

成功时，业务结果直接放入 MCP `structuredContent`，并同时返回内容等价的 JSON
`TextContent`。不会复制 HTTP API 的 `status_code/status_message/data` 信封。例如列表结果：

```json
{
  "data": [],
  "page_size": 10,
  "has_more": false,
  "next_cursor": null
}
```

参数错误、权限拒绝或业务失败是 MCP tool error：`isError=true`，不返回
`structuredContent`，模型可见的 `TextContent` 至少包含稳定错误码和安全错误信息：

```json
{
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "knowledge_id: Input should be greater than 0"
  }
}
```

已有业务错误码会优先保留。无已有业务码时，可能返回
`INVALID_ARGUMENT`、`UNAUTHENTICATED`、`PERMISSION_DENIED`、`NOT_FOUND`、
`CONFLICT`、`RATE_LIMITED`、`DEPENDENCY_UNAVAILABLE` 或 `TOOL_EXECUTION_FAILED`。
错误输出不包含 HTTP status 字段、请求头、堆栈或服务器路径。

还未进入 MCP handler 的凭据错误和请求体超限分别使用 transport HTTP
`401/403/503` 和 `413`。无效 JSON-RPC、未知方法和协议内部错误使用标准
JSON-RPC `error.code/error.message`，不伪装成 HTTP API 错误信封。

## 文件上传安全限制

base64 路径的默认上限为 50 MiB（解码后），实际上限是
`min(open_mcp.max_inline_upload_bytes, 该文件类型的业务上传上限)`。服务端在
JSON 解析前限制整个 MCP body，严格校验 base64，并流式写入临时文件。

`file_url` 默认仅允许 HTTPS，host 必须精确命中平台 MinIO share origin 或
`open_mcp.file_url_allowed_hosts`。初始 URL、DNS 结果和每次重定向都会重新校验，
禁止 userinfo、loopback、link-local、metadata 和未明确允许的私网地址。下载同时
检查 `Content-Length` 和实际流式读取字节数，并有固定连接/读取超时和
重定向次数。

本版 MCP 上传不暴露 `callback_url`。现有 HTTP API 的异步回调行为保持不变；MCP
为了在不改旧 API 逻辑的前提下避免延迟发送时的 DNS 重绑定和重定向风险，明确收窄
这一可选参数。无论成功、失败或取消，MCP 受管临时文件都会清理。

可在服务配置中设置：

```yaml
open_mcp:
  max_inline_upload_bytes: 52428800
  file_url_allowed_hosts:
    - files.example.com
  enable_dns_rebinding_protection: false
  transport_allowed_hosts:
    - bisheng.example.com
  transport_allowed_origins:
    - https://bisheng.example.com
  connect_timeout_seconds: 5
  read_timeout_seconds: 60
  max_redirects: 3
```

`enable_dns_rebinding_protection` 默认为 `false`，避免默认部署在多级反向代理改写
`Host` 时拒绝 MCP 请求。若后端直接对客户端开放，或前置代理未校验 `Host` / `Origin`，
应显式设为 `true` 并配置精确白名单。关闭时 `transport_allowed_hosts` 与
`transport_allowed_origins` 保留配置但不参与 SDK 传输校验。

allowlist 只写 host，不带 scheme、路径、userinfo 或主机名通配符；仅支持
`example.com:*` 形式的端口通配。反向代理/商业网关的 body 上限应与后端保持一致，
并禁止无限请求缓冲。

## 客户端配置

常见 IDE、编码助手和智能体平台的逐项配置、支持边界及排障方法见
[第三方客户端接入 BISHENG MCP 指南](./open-mcp-third-party-clients.md)。

Streamable HTTP 客户端可使用如下配置：

```json
{
  "mcpServers": {
    "bisheng": {
      "type": "streamable-http",
      "url": "https://bisheng.example.com/api/v2/mcp",
      "headers": {
        "Authorization": "Bearer <BISHENG_API_KEY>"
      }
    }
  }
}
```

D 模式只在受信任的客户端配置中增加
`"X-On-Behalf-Of":"<BISHENG_PLATFORM_USER_ID>"`。该值必须是已配置到 Key 委托范围的
BISHENG 平台用户 ID；不要直接填第三方系统用户 ID。不要把真实凭据写进仓库、讨论区、
命令行参数或验证输出。

## 连通性验证

从 `src/backend/` 运行官方 MCP Python client 验证脚本：

```bash
export BISHENG_MCP_URL=https://bisheng.example.com/api/v2/mcp
export BISHENG_API_KEY='<full-scope-api-key>'
.venv/bin/python scripts/verify_open_mcp.py --expected-profile full
```

脚本会完成 `initialize` 和 `tools/list`，输出服务端信息、协议版本和当前可见工具，
并按 `--expected-profile full` 对 10 个工具做双向差集；任一工具缺失或多出都会失败。
脚本不会输出凭据。

可选执行只读 smoke call：

```bash
.venv/bin/python scripts/verify_open_mcp.py \
  --expected-profile full \
  --call-tool bisheng_knowledge_list \
  --arguments-json '{"type":0,"page_size":1}'
```

PAT 预期只看到 `bisheng_knowledge_list`、`bisheng_knowledge_retrieve` 和
`bisheng_knowledge_file_list`，验证时显式传 `--expected-profile pat`。对于有意收窄 scope
的 API Key，可使用 `--expected-profile scope-filtered` 仅做诊断；该模式不构成 10 工具
发布验收证据。验收写入工具时必须使用专用测试租户和可清理数据，不要用本脚本扩展写操作。
