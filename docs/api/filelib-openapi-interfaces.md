# Filelib OpenAPI 接口文档

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

### 1.3 通用成功响应

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

### 1.4 通用认证错误

| 业务码 | message | 说明 |
|---:|---|---|
| `19801` | `developer_token_missing` | 缺少 `X-Developer-Token`。 |
| `19802` | `developer_token_invalid` | Token 无效。 |
| `19803` | `developer_token_disabled` | Token 已禁用。 |
| `19804` | `developer_token_ip_forbidden` | 请求 IP 不允许。 |
| `19805` | `developer_token_rate_limited` | 超过限流。 |
| `19806` | `developer_token_limiter_unavailable` | 限流存储不可用。 |

---

## 2. 查询知识资源列表

### 2.1 接口

```http
GET /api/v2/filelib/
```

### 2.2 Query 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `type` | integer | 否 | `0` | 知识资源类型。 |
| `name` | string | 否 | `null` | 知识资源名称，模糊匹配。 |
| `page_size` | integer | 否 | `10` | 每页数量。 |
| `page_num` | integer | 否 | `1` | 页码，从 `1` 开始。 |

`type` 枚举：

| 值 | 说明 |
|---:|---|
| `0` | 文档知识库 |
| `1` | QA 知识库 |
| `2` | 个人知识库 |
| `3` | 知识空间 |

### 2.3 请求示例

```bash
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/?type=3&page_size=10&page_num=1' \
  -H 'X-Developer-Token: bst_xxx'
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
    "total": 1
  }
}
```

### 2.5 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.data` | array | 知识资源列表。 |
| `data.total` | integer | 知识资源总数。 |

`data.data[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 知识资源 ID。 |
| `user_id` | integer / null | 创建用户 ID。 |
| `user_name` | string / null | 创建用户名。 |
| `name` | string | 知识资源名称。 |
| `type` | integer | 知识资源类型。 |
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
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/file/list?knowledge_id=118&page_size=10&page_num=1' \
  -H 'X-Developer-Token: bst_xxx'
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
| `403` | 无知识资源读取权限。 |
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

### 4.3 请求示例

```bash
curl -X GET 'http://127.0.0.1:7860/api/v2/filelib/file/detail?file_encoding=SGGF-RPT-QM-20260400000007&knowledge_id=118&content_format=text' \
  -H 'X-Developer-Token: bst_xxx'
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
| `data.chunk_count` | integer | 正文拼接使用的分段数量。 |

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
| `403` | - | 无知识资源读取权限。 |
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
  -H 'X-Developer-Token: bst_xxx' \
  -d '{
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
        "source_url": "/knowledge-spaces?spaceId=118&fileId=345",
        "source_full_url": "http://localhost:5173/knowledge-spaces?spaceId=118&fileId=345"
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
| `source_url` | string | 原文预览相对地址。 |
| `source_full_url` | string | 原文预览完整地址。 |

### 5.6 错误响应

| HTTP 状态 | detail | 场景 |
|---:|---|---|
| `400` | `filter references kb_id ... not present in knowledge_base_ids` | 过滤条件引用了未在 `knowledge_base_ids` 中的知识资源。 |
| `400` | `tag_match_mode=ALL is not yet supported` | `tag_match_mode` 传入 `ALL`。 |
| `403` | - | 无知识资源读取权限。 |
| `422` | - | Body 参数校验失败。 |
