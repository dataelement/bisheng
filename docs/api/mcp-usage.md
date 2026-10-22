# BiSheng MCP 使用文档

外部 MCP 客户端可通过以下连接信息，浏览有权访问的知识空间、读取和检索文件，并将文本或本地文件保存到指定目录：

```json
{
  "url": "https://bisheng.example.com/mcp",
  "headers": {
    "X-Developer-Token": "<填写完整的开发者Token>"
  }
}
```

本文面向接入开发者和客户端使用者，适用于当前知识空间 MCP 实现。九个新工具仅覆盖知识空间，包括公共、部门、团队、科室和已有个人空间；另保留兼容工具 `search_knowledge`，共十个工具。

示例域名和资源 ID 均需替换：`118` 为知识空间 ID，`305` 为目录 ID，`901` 为文件 ID。实际以发现工具返回的 ID 为准。部署后的工具清单可通过客户端的 `tools/list` 查看。

## 1. 快速接入

按以下顺序完成首次调用：

1. 管理员创建开发者 Token，绑定有权访问目标空间的用户；路由白名单可留空，若已配置规则则须覆盖 `POST /mcp`。
2. 客户端选择 **Streamable HTTP**，填写后端实际地址及 `X-Developer-Token` 请求头。
3. 客户端连接并完成 MCP 初始化，刷新工具列表。
4. 调用 `list_knowledge` 取得空间 ID，再用 `list_folders`、`list_files` 浏览内容。
5. 读取用 `get_file_detail`，问答取片段用 `retrieve_chunks`；保存内容用 `create_document` 或 `upload_file`。

典型操作顺序：

```text
浏览读取：list_knowledge → list_folders → list_files / search_files
         → get_file_detail / get_file_source / retrieve_chunks

保存文件：list_knowledge(writable_only=true) → 选择可写位置
         → create_document / upload_file → get_file_detail 查询解析结果
```

### 1.1 连接地址

| 项目 | 使用方式 |
|---|---|
| 协议 | MCP Streamable HTTP |
| 路径 | `/mcp`，也支持 `/mcp/` |
| 本地直连示例 | `http://127.0.0.1:7860/mcp`，以实际启动端口为准 |
| 外部访问示例 | `https://bisheng.example.com/mcp`，代理需将该路径转发到后端 |
| 身份请求头 | `X-Developer-Token: <完整Token>` |
| 工具请求 | MCP `tools/list`、`tools/call`，由客户端或 SDK 处理初始化与 HTTP 请求 |

MCP 默认开启，无需新增必填配置；已有配置显式关闭时仍保持关闭。MCP 允许任意来源跨域，浏览器通过请求头鉴权，不能设置 `credentials: include`。普通 REST 接口的跨域策略保持原状。

上述连接 JSON 只表示 URL 和请求头。各客户端配置文件的外层结构可能不同，请填入该客户端对应的服务器地址、传输类型和自定义请求头字段。当前接入使用开发者 Token，不提供 OAuth 登录流程，也不需要配置本地 stdio 启动命令。

### 1.2 Token 如何使用

在管理后台的“开发者 Token”功能中创建或编辑 Token，设置绑定用户、IP 白名单和限流规则。路由白名单遵循统一规则：未配置、`null` 或 `[]` 时不启用路由过滤，默认允许所有支持开发者 Token 的路由；配置非空规则后，只允许匹配的路由。

如果需要将 Token 的路由范围限制为 MCP，可配置以下规则（可选）：

```json
[
  {
    "match_type": "METHOD_PATH",
    "method": "POST",
    "path": "/mcp"
  }
]
```

客户端发送完整 Token 值，不加 `Bearer` 前缀：

```text
X-Developer-Token: <完整Token>
```

空路由白名单可以调用 MCP，仍需提供有效 Token，并通过 IP、限流及其他身份检查。路由放行不代表获得资源权限：读取、上传、租户范围仍按绑定用户的实际权限判断；不支持通过工具参数切换身份。非空白名单未覆盖 MCP 或当前方法时返回 HTTP `403` / `19812`。

握手、通知、工具列表和工具调用都会验证 Token，并计入请求限流。刷新列表或轮询解析状态也会消耗请求额度。已有 `/mcp` Token 的绑定用户如果有上传权，可以调用两个写工具；当前没有逐工具的 Token 白名单。

## 2. 工具总览

| 工具 | 用途 | 是否写入 |
|---|---|---|
| `list_knowledge` | 发现有权空间，按名称或可写能力筛选 | 否 |
| `list_folders` | 逐层列目录及路径、上传能力 | 否 |
| `list_files` | 列当前目录的文件，支持排序、状态和分页 | 否 |
| `search_files` | 按文件名或正文关键词查找文件 | 否 |
| `get_file_detail` | 读取文件元数据、解析状态和正文页 | 否 |
| `get_file_source` | 获取允许的预览来源链接 | 否 |
| `retrieve_chunks` | 根据问题返回相关片段及出处 | 否 |
| `create_document` | 将文本或 Markdown 保存成新文件 | 是 |
| `upload_file` | 将客户端文件字节以 Base64 上传 | 是 |
| `search_knowledge` | 兼容已有知识检索调用 | 否 |

`search_files` 返回“哪些文件匹配”，`retrieve_chunks` 返回“哪些正文片段相关”。两者均不生成模型答案。工具不提供创建目录、删除、覆盖、替换版本、发布或分享操作。

## 3. 公共约定

### 3.1 资源 ID 与参数

`knowledge_id`、`file_id` 等其他资源 ID 使用严格正整数，不能传字符串或布尔值。`folder_id` 同时接受正整数和纯 ASCII 数字的正数字符串，例如 `305`、`"305"`、`"000305"` 均表示目录 305；服务端统一转为整数后进行目录归属和权限校验，响应中的 ID 仍为整数。

顶层 `folder_id` 省略或为 `null` 表示根目录。`folder_scope.folder_id` 同样兼容数字字符串，但必填且不能为 `null`。空字符串、空白、非数字、带符号/小数、布尔值及非正数均拒绝，不会自动落入根目录。

新工具拒绝未声明字段，包括 `external_id`、`user_id`、`tenant_id`、`skip_approval`、`file_path` 等。Token 只放在请求头，不能作为工具参数传入。

检索工具使用复数参数 `knowledge_base_ids`；文件搜索使用 `knowledge_ids`。它们的名称不同，不能互换。

### 3.2 调用和返回格式

后续工具示例均为 `tools/call` 的 **params**。完整的 MCP 请求结构如下，不能将工具名直接拼成 HTTP 路径：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_knowledge",
    "arguments": {"page_size": 20}
  }
}
```

推荐使用 MCP 客户端或本文 SDK 示例处理握手、协议头和请求 ID。Python SDK 调用成功后，业务数据位于 `result.structuredContent`，工具失败时 `result.isError=true`。不使用 REST 的 `status_code/data` 外壳判断工具成功。

### 3.3 列表分页

前四个工具统一支持：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `page_size` | integer | `20` | 每页 1～100 项 |
| `cursor` | string / null | `null` | 首次省略，后续原样传入 `next_cursor`；最大 8192 字符 |

统一返回：

```json
{
  "data": [],
  "page_size": 20,
  "has_more": false,
  "next_cursor": null
}
```

判断是否继续翻页，应看 `has_more`。不足一页甚至空页仍可能有下一页；如果 `has_more=true`，继续传下一游标。不能仅凭 `data` 长度结束遍历。

翻页时保留原工具、空间/目录、筛选和排序条件。游标绑定身份及查询条件，不能跨用户或跨工具复用，也不要自行解码或修改。列表不返回未经权限过滤的总数。

### 3.4 文件状态

| `status` | 含义 | 使用建议 |
|---|---|---|
| `1` | 处理中 | 稍后查询 |
| `2` | 解析成功 | 结合 `content_ready` 判断正文是否可读 |
| `3` | 解析失败 | 检查源文件，必要时由管理端处理 |
| `4` | 重建中 | 稍后查询 |
| `5` | 排队 | 已受理，等待处理 |
| `6` | 超时 | 由管理端检查解析任务 |
| `7` | 内容违规 | 按现有内容管理流程处理 |

可见状态受权限限制，传入状态筛选不会扩大文件权限。读取未完成文件的详情时，正文为空且 `content_ready=false`，不等同于文件本身没有内容。

## 4. 九个工具的参数与示例

### 4.1 list_knowledge 列出知识空间

在公共分页参数外支持：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | string / null | `null` | 空间名称包含匹配；去除首尾空白后为 1～200 字符 |
| `writable_only` | boolean | `false` | 只返回根目录可上传，或至少有一个可访问目录可上传的空间 |

```json
{"name":"list_knowledge","arguments":{"name":"规程","writable_only":true,"page_size":20}}
```

`data` 中每项包含 `id`、`name`、`space_level`、`description`、`can_upload_to_root`、`has_writable_folders`。层级值为 `public`、`department`、`team`、`team_ks`（科室）、`personal`。

`can_upload_to_root=false`、`has_writable_folders=true` 时，应继续列目录选择可写位置，不能直接写根目录。空间可见也不代表空间内所有文件均可读。列表不会自动创建个人空间，收藏空间不提供上传能力。

### 4.2 list_folders 列出当前层目录

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 是 | 空间 ID |
| `folder_id` | integer / string / null | 否 | 父目录 ID；数字字符串可用；省略表示空间根目录 |

另支持公共分页参数。列根目录示例：

```json
{"name":"list_folders","arguments":{"knowledge_id":118,"page_size":20}}
```

返回目录项示例：

```json
{
  "id": 305,
  "knowledge_id": 118,
  "name": "操作规程",
  "size": 0,
  "status": 2,
  "update_time": "2026-10-16T10:00:00",
  "parent_id": null,
  "path_ids": [305],
  "path_names": ["操作规程"],
  "can_upload": true
}
```

只列直接子目录。继续向下浏览时，将返回目录的 `id` 作为下一次 `folder_id`。路径只包含有权展示的层级。

### 4.3 list_files 列出当前层文件

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 必填 | 空间 ID |
| `folder_id` | integer / string / null | `null` | 目录 ID，兼容纯数字的正数字符串 |
| `statuses` | integer[] / null | `null` | 最多 7 项，每项为 1～7；不传表示不额外筛选状态 |
| `sort_by` | string | `update_time` | `file_name` 或 `update_time` |
| `order` | string | `desc` | `asc` 或 `desc` |

另支持公共分页参数。

```json
{"name":"list_files","arguments":{"knowledge_id":118,"folder_id":"305","statuses":[2],"sort_by":"update_time","order":"desc","page_size":20}}
```

每项包含 `id`、`knowledge_id`、`name`、`size`（字节）、`status`、`update_time`、`parent_id`。只返回当前目录的直接子文件，不混入文件夹或递归子目录文件，默认排除回收、失效入口及历史非主版本。该操作不修正文件解析状态。

### 4.4 search_files 搜索文件

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `keyword` | string | 必填 | 去除首尾空白后为 1～200 字符 |
| `knowledge_ids` | integer[] / null | `null` | 指定 1～20 个空间；不传则使用当前可读空间范围 |
| `folder_scope` | object / null | `null` | `{knowledge_id,folder_id}`；目录 ID 为正整数或数字字符串，限定该目录及子目录 |
| `search_mode` | string | `all` | `name` 文件名、`content` 正文、`all` 两者并集 |

另支持公共分页参数。

```json
{"name":"search_files","arguments":{"keyword":"安全操作","knowledge_ids":[118],"folder_scope":{"knowledge_id":118,"folder_id":305},"search_mode":"all","page_size":20}}
```

如果同时指定 `knowledge_ids` 和 `folder_scope`，目录所属空间必须在该集合内，实际只搜索该目录所在空间的子树。无权空间或跨空间目录会失败，不会自动扩大范围。

返回文件列表，除文件基本字段外带有权路径 `path_ids/path_names`。仅搜索成功文件，按 `update_time desc, id desc` 排序；不支持 `statuses`、`sort_by`、`order` 参数。正文检索不可用时，`content/all` 会报错，不会悄悄改成只搜文件名。

### 4.5 get_file_detail 获取文件详情与正文

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 必填 | 文件入口所在空间 ID |
| `file_id` | integer | 必填 | 文件 ID |
| `include_content` | boolean | `true` | `false` 时只返回元数据及解析状态 |
| `content_format` | string | `text` | `text` 或 `markdown` |
| `max_chars` | integer | `20000` | 每页 1～50000 字符 |
| `cursor` | string / null | `null` | 本工具专属正文游标 |

```json
{"name":"get_file_detail","arguments":{"knowledge_id":118,"file_id":901,"content_format":"text","max_chars":20000}}
```

返回结构示例：

```json
{
  "file": {
    "id": 901,
    "knowledge_id": 118,
    "name": "操作规程.txt",
    "size": 1024,
    "status": 2,
    "update_time": "2026-10-16T10:00:00",
    "parent_id": 305
  },
  "content": "操作前应完成设备检查。",
  "content_ready": true,
  "content_format": "text",
  "content_version": "example-content-version",
  "has_more": false,
  "next_cursor": null
}
```

长正文按 `next_cursor` 续读；始终保留原空间、文件和 `content_format`。正文版本变化时，旧游标失效，需从首页重新读取；不能将旧版前半段与新版后半段拼接。`include_content=false` 或文件尚未解析时，不传正文游标。

正文属于当前授权入口对应的有效内容版本。请求 `markdown` 并不保证能还原原文件排版，实际格式以返回的 `content_format` 为准。

### 4.6 get_file_source 获取预览来源

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 必填 | 空间 ID |
| `file_id` | integer | 必填 | 文件 ID |
| `source_type` | string | `auto` | `auto`、`preview`、`original` |

```json
{"name":"get_file_source","arguments":{"knowledge_id":118,"file_id":901,"source_type":"auto"}}
```

返回包含 `file_id`、`knowledge_id`、`preview_url`、`original_url`、`expires_at`、`original_unavailable_reason`。

当前实现中，`auto/preview` 复用系统现有的预览权限和来源解析，优先返回已生成的 PDF、HTML 或普通预览链接，默认有效期七天。Markdown、文本、PDF 和常见图片可沿用页面的原生文件预览地址，无需额外生成预览对象；相对签名链接会补齐现有对象存储分享域名。

`original_url` 保持为空，并返回不可用原因；显式请求 `original` 会返回工具错误。Office 预览缺失时不会回退原件，原件下载仍需通过系统已有的授权水印下载流程。原生预览地址可能与页面读取原生文件的地址相同，获取预览不代表获得额外下载授权。

文件未生成预览、预览不可用或用户无权限时会报错。链接失效后重新调用本工具获取，不能把签名链接当作永久文件地址。

### 4.7 retrieve_chunks 检索正文片段

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | string | 必填 | 去除首尾空白后为 1～2000 字符 |
| `knowledge_base_ids` | integer[] | 必填 | 1～20 个有权知识空间 ID |
| `top_k` | integer | `5` | 最终返回片段数量上限，1～50 |
| `max_content` | integer | `15000` | 每空间检索合并文本的字符预算，1～15000 |
| `filters` | object / null | `null` | 按空间配置标签名过滤 |

```json
{
  "name": "retrieve_chunks",
  "arguments": {
    "query": "设备检修前需要完成哪些检查？",
    "knowledge_base_ids": [118],
    "top_k": 5,
    "max_content": 15000,
    "filters": {
      "knowledge_base_filters": [
        {"knowledge_base_id":118,"tags":["操作规程"],"tag_match_mode":"ANY"}
      ]
    }
  }
}
```

过滤器使用标签**名称**，不是标签 ID。`knowledge_base_filters` 最多 20 项，每项空间 ID 必须出现在本次 `knowledge_base_ids` 中，同一空间只配置一项。`tag_match_mode` 默认且目前只支持 `ANY`；虽然 schema 保留 `ALL` 枚举，当前传入 `ALL` 会失败。

返回示例：

```json
{
  "chunks": [
    {
      "content": "检修前应确认设备停机，并完成能源隔离。",
      "knowledge_id": 118,
      "document_id": 901,
      "document_name": "操作规程.txt",
      "chunk_index": 0,
      "source_url": "",
      "source_full_url": ""
    }
  ],
  "total": 1
}
```

`document_id` 对应调用者空间内的文件入口，可用于后续 `get_file_detail`。`total` 是本次返回的片段数，不是全库命中总数。无命中返回 `chunks=[]、total=0`，属于成功。来源链接沿用既有检索返回语义，链接生成不可用时可能为空，不影响已经返回的片段内容。

### 4.8 create_document 保存文本或 Markdown

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 必填 | 目标空间 ID |
| `file_name` | string | 必填 | 1～200 字符的文件基名 |
| `content` | string | 必填 | 非空正文，UTF-8 编码后不超过 10 MiB |
| `content_format` | string | `markdown` | `markdown` 对应 `.md`，`text` 对应 `.txt` |
| `folder_id` | integer / string / null | `null` | 指定已有目录，兼容数字字符串；省略表示根目录 |

另支持 §5 的分类与标签参数。

```json
{"name":"create_document","arguments":{"knowledge_id":118,"folder_id":305,"file_name":"会议纪要.md","content_format":"markdown","content":"# 会议纪要\n\n1. 完成设备检查。\n2. 更新操作规程。"}}
```

保存纯文本时须显式传 `content_format="text"` 并使用 `.txt` 后缀。成功返回写入受理结果，格式见 §6。

### 4.9 upload_file 上传现有文件

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `knowledge_id` | integer | 必填 | 目标空间 ID |
| `file_name` | string | 必填 | 1～200 字符的文件基名，保留真实扩展名 |
| `content_base64` | string | 必填 | 严格 Base64，解码后非空且不超过 50 MiB |
| `folder_id` | integer / string / null | `null` | 指定已有目录，兼容数字字符串；省略表示根目录 |

另支持 §5 的分类与标签参数。

```json
{"name":"upload_file","arguments":{"knowledge_id":118,"folder_id":"305","file_name":"hello.txt","content_base64":"aGVsbG8="}}
```

示例上传的是五字节的 `hello` 文本。真实文件需由客户端读取原始字节后做标准 Base64 编码，传入不带换行和 `data:` 前缀的字符串。不能传文件 URL、客户端路径或服务器路径代替 Base64。

当前允许的扩展名为 `pdf`、`txt`、`docx`、`ppt`、`pptx`、`md`、`xls`、`xlsx`、`doc`、`html`、`htm`。是否能完成解析还取决于文件内容和现有解析服务。

## 5. 分类、标签和大小限制

两个写工具共用以下可选元数据：

| 参数 | 类型 | 限制与含义 |
|---|---|---|
| `file_category_code` | string / null | 一级分类代码，最多 16 字符 |
| `file_subcategory_code` | string / null | 二级分类代码，最多 16 字符 |
| `business_domain_code` | string / null | 业务域代码，最多 16 字符 |
| `manual_tag_ids` | integer[] | 最多 100 个正整数标签 ID |
| `manual_tag_names` | string[] | 最多 100 个名称，每个为 1～200 字符 |

按当前系统字典和审核规则填写。目标空间要求业务域时，应提供相应合法代码；省略参数不会跳过原上传规则。根目录上传权与指定目录上传权分别判断，收藏空间不能写入。

| 限制对象 | 上限 | 计算方式 |
|---|---|---|
| `upload_file` 文件 | 50 MiB，52428800 字节 | Base64 解码后的真实文件字节 |
| `create_document` 正文 | 10 MiB，10485760 字节 | UTF-8 编码后的真实字节 |
| MCP HTTP 请求体 | 80 MiB，83886080 字节 | 整个 JSON 请求，包含 Base64 和元数据 |
| 文件名 | 200 字符 | 只允许基名，禁止路径分隔符和控制字符 |

1 MiB 为 1024×1024 字节。中文正文按 UTF-8 字节计算，不能以字符数代替字节数。50 MiB 文件转 Base64 约为 66.7 MiB，HTTP 请求体上限为其保留了传输空间。

实际可上传大小取 MCP 上限与既有系统大小设置、文件类型规则、租户/角色配额中的较严格限制。若系统配置更小，MCP 不会自动提高它。外部代理也需允许相应请求体与处理时间；代理先拒绝的请求不会进入 MCP。

## 6. 写入结果和状态回查

创建和上传成功后的 `structuredContent` 示例：

```json
{
  "file_id": 901,
  "knowledge_id": 118,
  "folder_id": 305,
  "file_name": "会议纪要.md",
  "status": 5,
  "accepted": true,
  "content_ready": false
}
```

`accepted=true` 表示文件创建及解析投递已经受理，不代表正文已经可读。以返回状态为准，不应假定每次都为 `5`。

随后查询：

```json
{"name":"get_file_detail","arguments":{"knowledge_id":118,"file_id":901,"include_content":false}}
```

需要确认正文可读时，再将 `include_content` 设为 `true`。可间隔数秒查询，并结合 Token 限流调整频率；成功且内容就绪后可使用 `retrieve_chunks` 检索。

同名或同内容冲突按既有上传去重规则拒绝，不自动覆盖、替换版本、改名或重新选择空间。写入超时、断连或出现 `Write outcome uncertain` 时，先按已知 `file_id` 查询，或通过目录列表核对文件，再决定是否重试；不要自动重放写请求。

## 7. Python 客户端完整示例

示例使用与当前项目一致的 `mcp==1.27.1` SDK 和 `httpx`，要求 Python 3.10 或以上。已有项目环境可直接使用 `src/backend/.venv/bin/python`；独立客户端环境可安装：

```bash
python -m pip install 'mcp==1.27.1' httpx
```

设置环境变量。Token 占位值需替换；`UPLOAD_PATH` 是客户端本机文件路径，仅由下面的 Python 脚本读取：

```bash
export BISHENG_MCP_URL='https://bisheng.example.com/mcp'
export BISHENG_DEVELOPER_TOKEN='<填写完整Token>'
export BISHENG_KNOWLEDGE_ID='118'
export BISHENG_FOLDER_ID='305'
export UPLOAD_PATH='/absolute/path/hello.txt'
```

以下脚本默认列工具和空间。设置 `UPLOAD_PATH` 时还会上传该文件并查询一次状态；不设置时只执行读取操作。保存为 `bisheng_mcp_demo.py` 后运行 `python bisheng_mcp_demo.py`：

```python
import asyncio
import base64
import os
from datetime import timedelta
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call(client, name, arguments):
    result = await client.call_tool(name, arguments)
    if result.isError:
        details = " ".join(
            block.text for block in result.content if block.type == "text"
        )
        raise RuntimeError(f"{name}: {details}")
    return result.structuredContent


async def main():
    headers = {"X-Developer-Token": os.environ["BISHENG_DEVELOPER_TOKEN"]}
    async with httpx.AsyncClient(headers=headers, timeout=180) as http:
        async with streamable_http_client(
            os.environ["BISHENG_MCP_URL"],
            http_client=http,
            terminate_on_close=False,
        ) as (reader, writer, _):
            async with ClientSession(
                reader, writer, read_timeout_seconds=timedelta(seconds=180)
            ) as client:
                await client.initialize()
                tools = await client.list_tools()
                print("tools:", [tool.name for tool in tools.tools])

                arguments = {"page_size": 20}
                while True:
                    page = await call(client, "list_knowledge", arguments)
                    for space in page["data"]:
                        print(space["id"], space["name"], space["can_upload_to_root"])
                    if not page["has_more"]:
                        break
                    arguments["cursor"] = page["next_cursor"]

                if not os.environ.get("UPLOAD_PATH"):
                    return
                path = Path(os.environ["UPLOAD_PATH"])
                if not 0 < path.stat().st_size <= 50 * 1024 * 1024:
                    raise ValueError("File must be nonempty and at most 50 MiB")
                knowledge_id = int(os.environ["BISHENG_KNOWLEDGE_ID"])
                upload = {
                    "knowledge_id": knowledge_id,
                    "file_name": path.name,
                    "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
                if os.environ.get("BISHENG_FOLDER_ID"):
                    upload["folder_id"] = int(os.environ["BISHENG_FOLDER_ID"])
                saved = await call(client, "upload_file", upload)
                print("saved:", saved["file_id"], saved["status"], saved["accepted"])
                detail = await call(client, "get_file_detail", {
                    "knowledge_id": knowledge_id,
                    "file_id": saved["file_id"],
                    "include_content": False,
                })
                print("state:", detail["file"]["status"], detail["content_ready"])


asyncio.run(main())
```

目标空间要求分类、业务域或标签时，在 `upload` 中按 §5 加入相应参数。示例不会自动重试写入，也不会等待解析直至完成；后续按 §6 查询即可。

## 8. 常见错误与排查

先区分 HTTP 接入错误和 MCP 工具错误。HTTP 错误会由客户端表现为连接或请求失败；业务操作失败则检查 `isError` 和工具错误文本，即使 HTTP 请求成功也不能视为业务成功。

| 表现 | 可能原因与处理 |
|---|---|
| HTTP `401` | Token 缺失、无效或禁用；检查是否传完整值、是否误加 `Bearer` |
| HTTP `403` | Token IP 不符，或已配置的非空路由白名单未命中 `POST /mcp`；空白名单不启用路由过滤 |
| HTTP `404` | 后端版本尚未包含入口、服务显式关闭，或代理未转发 `/mcp` |
| HTTP `405` | 直接用浏览器 GET 探测了 MCP；改用 Streamable HTTP 客户端和 POST 请求 |
| HTTP `413` | 请求体超过 80 MiB，或代理设置更小；同时计算 Base64 膨胀与元数据 |
| HTTP `429` | Token 限流；降低并发、列表刷新或轮询频率 |
| HTTP `503` | 鉴权或限流依赖不可用；由管理员检查相关服务 |
| 工具列表只有旧 `search_knowledge` | 实际连接的后端可能仍为旧版本；核对地址和发布版本后刷新列表 |
| `Resource denied or unavailable` | 资源无权、状态不可用、目标错误或原上传业务规则不满足；检查空间/目录/文件归属与绑定用户权限 |
| `Invalid MCP input or pagination cursor` 或参数校验错误 | 检查参数名、ID 类型、Base64、文件名、大小及游标条件；无效游标从首页重新获取 |
| `MCP operation timed out` | 操作超时；读取可缩小范围，写入先查询已有结果再决定是否重试 |
| `Write outcome uncertain` | 创建/投递结果不确定；按返回的 `file_id` 或目录列表核对，不能当作已经回滚 |
| `MCP operation failed` | 下游操作异常或不支持的过滤条件，例如 `tag_match_mode=ALL`；核对参数，必要时结合 `X-Trace-ID` 排查 |
| 列表为空 | 可能无匹配或无权；有 `next_cursor` 时仍需继续翻页 |
| 正文为空且 `content_ready=false` | 解析或当前内容投影尚未就绪，结合文件状态回查 |
| `original_url` 为空 | 当前原件走已有水印下载流程；使用授权预览或已有下载功能 |

工具错误文本可能带 SDK 包装前缀，不建议把完整英文错误字符串作为程序分支依据。签名 URL 失效后重新获取；不要把 Token、Base64 正文或签名链接写入普通业务日志。

## 9. 旧工具与相关资料

`search_knowledge` 保留原名称、参数和知识资源范围，用于兼容已有客户端。其必填参数同样为 `query`、`knowledge_base_ids`，默认 `top_k=5`、`max_content=15000`，返回 `{chunks,total}`。新接入知识空间检索可使用 `retrieve_chunks`；前者的旧资源范围不因新工具限定知识空间而收窄。

```json
{"name":"search_knowledge","arguments":{"query":"设备检修前需要完成哪些检查？","knowledge_base_ids":[118],"top_k":5}}
```
