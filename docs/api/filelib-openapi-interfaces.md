# Filelib OpenAPI 接口文档

新增按文件 ID 获取原文件地址：`GET /api/v2/filelib/file/source_url?file_id=123`，支持 `external_id`，返回 `{file_id, source_full_url}`。详见 [按文件 ID 获取原文件地址](filelib-file-source-url.md)。

## 1. 通用约定

### 1.1 Base URL

```text
http://{bisheng-host}:7860/api/v2
```

### 1.2 通用 Header

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Developer-Token` | 是 | 开发者 Token。 |

`POST` JSON 请求额外需要：

| Header | 必填 | 说明 |
|---|---:|---|
| `Content-Type` | 是 | 固定为 `application/json`。 |

### 1.3 调用资格、业务用户与数据作用域

Filelib 查询接口（包括按 ID 获取原文件地址）使用双重身份：

- `X-Developer-Token` 始终必填，只用于验证调用方是否具备调用资格，包括 Token 状态、绑定关系、IP、路由白名单和限流。
- `external_id` 可选，用于确定本次请求的业务用户、资源权限和数据作用域。
- 未传 `external_id` 时，业务用户回退为 Token 绑定用户，保持原有行为。
- 传入 `external_id` 时，系统按去除首尾空白后的值全局精确匹配唯一有效用户，并完整继承该用户权限；目标用户为全局超级管理员时同样继承其完整权限。
- 找不到有效用户、用户已禁用或存在多个有效匹配时统一返回 HTTP `403`，不会披露具体原因，也不会回退到 Token 绑定用户。
- 空字符串、纯空白或超过 255 个字符的 `external_id` 返回 HTTP `422`。

Token 校验优先于外部用户解析。Token 校验失败时返回既有 Developer Token 错误，不查询 `external_id` 对应用户，也不进入 Filelib 业务。

> 安全与部署限制：传入 `external_id` 会在本次请求内使用目标用户的完整权限和全局数据作用域。该能力仅适用于当前未启用租户功能的部署；若启用多租户，必须先重新设计和评审作用域边界，不能直接沿用本接口语义。

### 1.4 通用成功响应

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | integer | 业务状态码。成功固定为 `200`。 |
| `status_message` | string | 业务状态说明。成功通常为 `SUCCESS`。 |
| `data` | any | 接口返回数据。 |

### 1.5 通用认证与用户上下文错误

| 业务码 | message | 说明 |
|---:|---|---|
| `19801` | `developer_token_missing` | 缺少 `X-Developer-Token`。 |
| `19802` | `developer_token_invalid` | Token 无效。 |
| `19803` | `developer_token_disabled` | Token 已禁用。 |
| `19804` | `developer_token_ip_forbidden` | 请求 IP 不允许。 |
| `19805` | `developer_token_rate_limited` | 超过限流。 |
| `19806` | `developer_token_limiter_unavailable` | 限流存储不可用。 |

除上述业务码外：

| HTTP 状态 | 场景 |
|---:|---|
| `403` | `external_id` 未匹配到唯一有效用户。响应不区分不存在、禁用或重复。 |
| `422` | `external_id` 为空、纯空白、超过 255 个字符或其他参数校验失败。 |

### 1.6 SPACE 共享存储约定（F112）

文件业务统一接受知识空间 `SPACE(type=3)`，不再读取或写入逐库旧 ES/Milvus。
显式非 SPACE 的文件请求、非 SPACE/SPACE 混合检索、类型别名冲突在业务副作用前拒绝。
资源列表及创建的默认类型从 `0` 改为 `3`；这属于调用兼容性变化，调用方需同步调整。
6 个 QA 接口（`add_qa`、`add_relative_qa`、`qa/{qa_id}`、`update_qa`、`detail_qa`、`query_qa`）
和 `download_statistic` 保持原行为，其他入口的 NORMAL/PRIVATE/QA 存储不受影响。

| 接口 | 共享存储行为 |
|---|---|
| `POST /filelib/` | 默认创建操作者拥有的团队库；可指定现有公共/部门/科室空间类型，资格校验沿用知识空间服务 |
| `PUT /filelib/` | 修改 SPACE 名称、描述，保持已有发布状态 |
| `DELETE /filelib/{knowledge_id}` | 走空间退役与分发规则，不删除租户共享索引/collection |
| `DELETE /filelib/clear/{knowledge_id}` | 清空当前空间入口并保留空间及授权；有效引用使用的正文、原对象保留 |
| `POST /filelib/file/{knowledge_id}`、`POST /filelib/chunks` | 分别异步/同步解析，直接写共享存储；配额、解析参数、回调保持 |
| `POST /filelib/chunks_string` | 文档切片直接写共享存储；空 documents 返回参数错误，不修改输入 metadata |
| `DELETE /filelib/file/{file_id}`、`POST /filelib/delete_file` | 沿用入口生命周期；批量文件须属于同一个 SPACE，跨空间批次返回业务码 10950 |
| `GET /filelib/`、`GET /filelib/file/list` | 保留既有分页；文件摘要从共享文档及版本读取 |
| `GET /filelib/file/detail` | 先解析实际内容文件，再读文本产物或完整共享分块；不回退旧存储 |
| `GET /filelib/file/source_url`、`POST /filelib/retrieve` | 仅接受已授权 SPACE；签名仍遵守现有 view_file 与原文件地址规则 |

写接口沿用配置的 `default_operator`，查询接口沿用 Token 绑定用户或 `external_id`；
本次不把业务用户切换扩展到写接口。共享路由须提前初始化，接口不会自动建库或迁移旧数据。

创建最小请求：

```json
{"name":"政研资料","type":3,"space_level":"team"}
```

`space_level` 缺省为 `team`；`department_id`、`is_clinic` 按已有空间规则使用；不能主动创建个人库。
`model`、`index_name`、`collection_name` 可以省略；显式提供时必须与租户共享目标一致，否则返回参数错误。
全局 KnowledgeCreate 的默认值保持不变，仅此 Filelib 创建接口使用新默认值。

| HTTP / 业务码 | 场景 |
|---|---|
| HTTP 503，`status_code=10973` | 共享目标未初始化、初始化字段不完整或共享后端不可用 |
| HTTP 409，`status_code=10974` | 已解析成功文件的共享投影未就绪或共享正文缺失 |
| 沿用业务错误包装，`status_code=18098` | 读取期间版本/代次变化、历史非主版本正文请求或写冻结等状态冲突 |

共享错误不会伪装为空正文成功。写冻结阻止写入，不阻止合法读取；资源和文件权限仍由服务端领域规则检查。

---

## 2. 查询知识资源列表

### 2.1 接口

```http
GET /api/v2/filelib/
```

### 2.2 Query 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `type` | integer | 否 | `3` | 仅支持知识空间 SPACE。 |
| `knowledge_type` | integer | 否 | `null` | `type` 的兼容参数；两者同时传入时值必须一致，否则返回 HTTP `422`。 |
| `name` | string | 否 | `null` | 知识资源名称，模糊匹配。 |
| `page_size` | integer | 否 | `10` | 每页数量。 |
| `cursor` | string | 否 | `null` | 游标分页令牌。首次请求不传；下一页传上次响应的 `next_cursor`。 |
| `external_id` | string | 否 | `null` | 业务用户外部标识。最大 255 个字符；未传时使用 Token 绑定用户。 |

`type` 枚举：

| 值 | 说明 |
|---:|---|
| `0` / `1` / `2` | 本文件接口不再支持，返回参数错误；不影响独立 QA 接口及其他业务入口 |
| `3` | 知识空间，默认值 |

当类型为 `3` 时，接口返回指定业务用户在门户知识库侧栏可见的知识空间并集：

- 全部公共库；
- 用户具有查看、管理权限或有效成员关系的部门库；
- 用户具有查看、管理权限或有效成员关系的团队库和科室库；
- 当前用户已经存在的“我的收藏”和默认个人知识库。

该查询不会自动创建缺失的个人库。对于尚未访问过门户、固定个人库尚未生成的用户，个人库可能为空。

### 2.3 请求示例

```bash
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/?type=3&page_size=10&external_id=EMP001' \
  -H 'X-Developer-Token: bst_{REDACTED}'
```

### 2.4 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": 118,
        "user_id": 12,
        "user_name": "zhangsan",
        "name": "GR00011",
        "type": 3,
        "space_level": "department",
        "description": "知识资源描述",
        "model": null,
        "collection_name": null,
        "index_name": "col_118",
        "state": 1,
        "is_released": false,
        "auth_type": "public",
        "is_shared": false,
        "auto_tag_enabled": false,
        "auto_tag_library_id": null,
        "metadata_fields": null,
        "create_time": "2026-06-07T15:32:00",
        "update_time": "2026-06-07T15:32:00"
      }
    ],
    "page_size": 10,
    "has_more": false,
    "next_cursor": null
  }
}
```

### 2.5 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 知识资源列表。 |
| `data.page_size` | integer | 每页数量。 |
| `data.has_more` | boolean | 是否还有下一页。 |
| `data.next_cursor` | string / null | 下一页游标。`has_more=false` 时为 `null`。 |

`data.data[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 知识资源 ID。 |
| `user_id` | integer / null | 创建用户 ID。 |
| `user_name` | string / null | 创建用户名。 |
| `name` | string | 知识资源名称。 |
| `type` | integer | 知识资源类型。 |
| `space_level` | string / null | `type=3` 时返回知识空间层级：`public`、`department`、`team`、`team_ks` 或 `personal`；其他类型不返回该扩展值。 |
| `description` | string / null | 描述。 |
| `model` | string / null | 模型配置。 |
| `collection_name` | string / null | 向量集合名称。 |
| `index_name` | string / null | 索引名称。 |
| `state` | integer / null | 知识资源状态。 |
| `is_released` | boolean | 是否发布。 |
| `auth_type` | string | 权限类型。 |
| `is_shared` | boolean | 是否共享。 |
| `auto_tag_enabled` | boolean | 是否启用自动标签。 |
| `auto_tag_library_id` | integer / null | 自动标签库 ID。 |
| `metadata_fields` | array / null | 元数据字段配置。 |
| `create_time` | string / null | 创建时间。 |
| `update_time` | string / null | 更新时间。 |

### 2.6 错误响应

| HTTP 状态 | 场景 |
|---:|---|
| `403` | `external_id` 未匹配到唯一有效用户，或目标用户无知识资源读取权限。 |
| `422` | Query 参数校验失败。 |

---

## 3. 查询文件列表

### 3.1 接口

```http
GET /api/v2/filelib/file/list
```

### 3.2 Query 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | integer | 是 | - | 知识资源 ID。 |
| `keyword` | string | 否 | `null` | 文件名关键字，模糊匹配。 |
| `status` | integer[] | 否 | `null` | 文件状态。多值传参格式：`status=2&status=3`。 |
| `page_size` | integer | 否 | `10` | 每页数量。 |
| `page_num` | integer | 否 | `1` | 页码，从 `1` 开始。 |
| `external_id` | string | 否 | `null` | 业务用户外部标识。最大 255 个字符；未传时使用 Token 绑定用户。 |

`status` 枚举：

| 值 | 说明 |
|---:|---|
| `1` | 处理中 |
| `2` | 处理成功 |
| `3` | 处理失败 |
| `4` | 重建中 |
| `5` | 排队中 |
| `6` | 解析超时 |
| `7` | 内容安全违规 |

### 3.3 请求示例

```bash
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/file/list?knowledge_id=118&page_size=10&page_num=1&external_id=EMP001' \
  -H 'X-Developer-Token: bst_{REDACTED}'
```

### 3.4 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": 345,
        "user_id": 12,
        "user_name": "zhangsan",
        "knowledge_id": 118,
        "file_name": "example.pdf",
        "file_type": 1,
        "file_source": "upload",
        "file_size": 215270,
        "status": 2,
        "file_encoding": "SGGF-RPT-QM-20260400000007",
        "is_primary": true,
        "document_type": "RPT",
        "categoryID": "入库分类测试",
        "categoryGroupClassCode": "分类编码测试",
        "docTypeCode": "分类赋码测试",
        "create_time": "2026-06-07T15:32:00",
        "update_time": "2026-06-07T15:32:00"
      }
    ],
    "total": 1,
    "writeable": false
  }
}
```

### 3.5 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 文件列表。 |
| `data.total` | integer | 文件总数。 |
| `data.writeable` | boolean | 是否可写。 |

`data.data[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 文件 ID。 |
| `user_id` | integer / null | 上传用户 ID。 |
| `user_name` | string / null | 上传用户名。 |
| `knowledge_id` | integer | 知识资源 ID。 |
| `file_name` | string | 文件名称。 |
| `file_type` | integer | 文件类型。文件为 `1`。 |
| `file_source` | string / null | 文件来源。 |
| `file_size` | integer / null | 文件大小，单位 byte。 |
| `status` | integer / null | 文件状态。 |
| `file_encoding` | string | 文件编码。 |
| `is_primary` | boolean | 是否主版本。 |
| `document_type` | string | 文档类型编码。 |
| `categoryID` | string | 固定返回 `入库分类测试`。 |
| `categoryGroupClassCode` | string | 固定返回 `分类编码测试`。 |
| `docTypeCode` | string | 固定返回 `分类赋码测试`。 |
| `create_time` | string / null | 创建时间。 |
| `update_time` | string / null | 更新时间。 |

### 3.6 错误响应

| HTTP 状态 | 场景 |
|---:|---|
| `403` | `external_id` 未匹配到唯一有效用户，或目标用户无知识资源读取权限。 |
| `422` | Query 参数校验失败。 |

---

## 4. 查询文件详情

### 4.1 接口

```http
GET /api/v2/filelib/file/detail
```

### 4.2 Query 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `file_encoding` | string | 是 | - | 文件编码。 |
| `knowledge_id` | integer | 否 | `null` | 知识资源 ID。 |
| `content_format` | string | 否 | `text` | 正文格式。可选值：`text`、`markdown`。 |
| `external_id` | string | 否 | `null` | 业务用户外部标识。最大 255 个字符；未传时使用 Token 绑定用户。 |

### 4.3 请求示例

```bash
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/file/detail?file_encoding=SGGF-RPT-QM-20260400000007&knowledge_id=118&content_format=text&external_id=EMP001' \
  -H 'X-Developer-Token: bst_{REDACTED}'
```

### 4.4 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file": {
      "id": 345,
      "knowledge_id": 118,
      "file_encoding": "SGGF-RPT-QM-20260400000007",
      "file_name": "example.pdf",
      "file_size": 215270,
      "status": 2,
      "update_time": "2026-06-10 08:30:00",
      "is_primary": true,
      "document_type": "RPT",
      "categoryID": "入库分类测试",
      "categoryGroupClassCode": "分类编码测试",
      "docTypeCode": "分类赋码测试"
    },
    "content": "文件解析后的完整正文...",
    "chunk_count": 12
  }
}
```

文件未处理成功时：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file": null,
    "content": "",
    "chunk_count": 0
  }
}
```

### 4.5 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.file` | object / null | 文件信息。 |
| `data.content` | string | 文件完整正文。 |
| `data.chunk_count` | integer | 共享分块路径为实际分块数；文本产物路径保持既有语义，非空为 1、空为 0。 |

正文始终完整返回，不套用 MCP 的单页字符上限。发布/分享文件返回访问入口的元数据，
正文来自解析后的实际内容文件。历史非主版本请求返回状态冲突，避免旧元数据配上新版本正文。
读取前后检查版本、代次和路由，并通过独立只读会话再次复核，避免数据库快照掩盖并发变化。

`data.file`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 文件 ID。 |
| `knowledge_id` | integer | 知识资源 ID。 |
| `file_encoding` | string | 文件编码。 |
| `file_name` | string | 文件名称。 |
| `file_size` | integer / null | 文件大小，单位 byte。 |
| `status` | integer / null | 文件状态。 |
| `update_time` | string | 更新时间。 |
| `is_primary` | boolean | 是否主版本。 |
| `document_type` | string | 文档类型编码。 |
| `categoryID` | string | 固定返回 `入库分类测试`。 |
| `categoryGroupClassCode` | string | 固定返回 `分类编码测试`。 |
| `docTypeCode` | string | 固定返回 `分类赋码测试`。 |

### 4.6 错误响应

| HTTP 状态 | detail | 场景 |
|---:|---|---|
| `400` | `file_encoding must not be empty` | `file_encoding` 为空字符串。 |
| `403` | - | `external_id` 未匹配到唯一有效用户，或目标用户无知识资源读取权限。 |
| `404` | `file not found` | 文件不存在。 |
| `404` | `knowledge not found` | 知识资源不存在。 |
| `409` | `duplicate file_encoding found` | 文件编码匹配到多个文件。 |
| `422` | - | 参数校验失败。 |

---

## 5. 检索知识库 Chunk

### 5.1 接口

```http
POST /api/v2/filelib/retrieve
```

### 5.2 请求 Body

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `external_id` | string | 否 | `null` | 业务用户外部标识。最大 255 个字符；未传时使用 Token 绑定用户。 |
| `query` | string | 是 | - | 检索问题。最小长度 `1`。 |
| `knowledge_base_ids` | integer[] | 是 | - | 知识资源 ID 列表。至少 1 个。 |
| `filters` | object | 否 | `null` | 过滤条件。 |
| `filters.knowledge_base_filters` | object[] | 否 | `[]` | 知识资源过滤条件列表。 |
| `filters.knowledge_base_filters[].knowledge_base_id` | integer | 是 | - | 知识资源 ID。 |
| `filters.knowledge_base_filters[].tags` | string[] | 否 | `[]` | 标签名称列表。 |
| `filters.knowledge_base_filters[].tag_match_mode` | string | 否 | `ANY` | 标签匹配方式。可选值：`ANY`、`ALL`。当前仅支持 `ANY`。 |
| `top_k` | integer | 否 | `10` | 返回 chunk 数量上限。范围：`1` 到 `200`。 |
| `max_content` | integer | 否 | `15000` | 单个知识资源内容长度上限。最小值 `1`。 |

### 5.3 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/retrieve' \
  -H 'Content-Type: application/json' \
  -H 'X-Developer-Token: bst_{REDACTED}' \
  -d '{
    "external_id": "EMP001",
    "query": "安全管理要求",
    "knowledge_base_ids": [118],
    "filters": {
      "knowledge_base_filters": [
        {
          "knowledge_base_id": 118,
          "tags": ["技术文档"],
          "tag_match_mode": "ANY"
        }
      ]
    },
    "top_k": 10,
    "max_content": 15000
  }'
```

### 5.4 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "chunks": [
      {
        "content": "相关 chunk 文本...",
        "knowledge_id": 118,
        "document_id": 345,
        "document_name": "example.pdf",
        "chunk_index": 3,
        "source_url": "/bisheng/original/345.pdf?X-Amz-Expires=604800&X-Amz-Signature=REDACTED",
        "source_full_url": "https://files.example.com/bisheng/original/345.pdf?X-Amz-Expires=604800&X-Amz-Signature=REDACTED"
      }
    ],
    "total": 1
  }
}
```

### 5.5 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.chunks` | array | Chunk 列表。 |
| `data.total` | integer | 返回 chunk 数量。 |

`data.chunks[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string | Chunk 文本。 |
| `knowledge_id` | integer | 知识资源 ID。 |
| `document_id` | integer | 文件 ID。 |
| `document_name` | string | 文件名称。 |
| `chunk_index` | integer | Chunk 序号。 |
| `source_url` | string | 原文件 GET 预签名 URL 的相对路径和查询串；调用方需拼接部署提供的文件访问 Origin。原对象缺失时为空字符串。 |
| `source_full_url` | string | 同一原文件的绝对 GET 预签名 URL，可直接访问且无需再次提交 Developer Token。原对象缺失时为空字符串。 |

两个 URL 来自同一次签名，对象路径、签名参数和过期时间一致，有效期固定为签发后 7 天。同一响应内，同一 `document_id` 的多个 Chunk 复用相同 URL；不同请求可能重新签发并返回不同值。

链接只会为最终通过业务用户 `view_file` 可见性过滤并进入响应的文件签发。按当前接口契约，不额外要求 `download_file`，也不进入门户下载额度、审计、水印、审批或分发限制链路。文件记录、对象名或原对象不存在时，Chunk 仍然返回，两个 URL 均为空字符串；其他 MinIO 连接、认证或签名异常会使请求失败。

> 安全提示：预签名 URL 是签发后 7 天内有效的 Bearer 凭证。任何持有者都能读取原文件，后续撤销用户权限、禁用 Developer Token 或退出登录不会使已签发 URL 提前失效。调用方不得把完整 URL 写入日志、监控标签、前端埋点或第三方分析系统。

### 5.6 错误响应

| HTTP 状态 | detail | 场景 |
|---:|---|---|
| `400` | `filter references kb_id ... not present in knowledge_base_ids` | 过滤条件引用了未在 `knowledge_base_ids` 中的知识资源。 |
| `400` | `tag_match_mode=ALL is not yet supported` | `tag_match_mode` 传入 `ALL`。 |
| `403` | - | `external_id` 未匹配到唯一有效用户，或目标用户无知识资源读取权限。 |
| `422` | - | Body 参数校验失败。 |
| `500` | - | MinIO 连接、认证、服务端或签名失败等非“对象不存在”异常。 |
