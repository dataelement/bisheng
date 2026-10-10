# v2 密钥鉴权 API 接口文档（四大分类）

> 可导入文件：[`openapi-v2-key-auth-api-by-category.json`](./openapi-v2-key-auth-api-by-category.json)  
> OpenAPI：3.1.0  
> 本文档收录：**41 个 HTTP 接口 + 2 个 WebSocket 接口，共 43 个接口**。  
> 分类顺序：知识库 → 日常模式会话 → 工作流 → 助手。

按“请求方法 + 路径”计数，同一路径的 GET、POST、PUT 分别计数；SSE 属于对应的 HTTP 接口。

**分类总览**

| 分类 | HTTP | WebSocket | 合计 | 主要权限位 |
|---|---:|---:|---:|---|
| [知识库](#knowledge) | 28 | 0 | **28** | knowledge:read、knowledge:write |
| [日常模式会话](#daily-chat) | 5 | 0 | **5** | chat:invoke |
| [工作流](#workflow) | 3 | 1 | **4** | workflow:read、workflow:invoke |
| [助手](#assistant) | 5 | 1 | **6** | assistant:read、assistant:invoke |
| **合计** | **41** | **2** | **43** | |

**使用方式**

将配套 JSON 导入 Apifox 或 Postman，设置实际服务地址并在集合鉴权中填写 Bearer Token。接口按上述四类组织。WebSocket 不属于 OpenAPI 3.1 的 HTTP operation，导入工具通常不会自动创建 WS 连接；其连接方式和初始化消息分别列在“工作流”和“助手”章节。

运行本文的 HTTP 请求示例前，先设置：

```bash
export BISHENG_API_BASE='http://localhost:7860'
export BISHENG_API_KEY='<API_KEY>'
```

将示例中的知识库 ID、文件 ID、助手 ID、工作流 ID、模型 ID 和文件路径替换成实际值。

**通用请求头**

| 请求头 | 必填 | 说明 |
|---|---:|---|
| `Authorization: Bearer <API_KEY>` | 是 | 所有接口均须有效密钥，且密钥具有接口要求的权限位 |
| `X-On-Behalf-Of` | 条件必填 | 代表平台用户执行；密钥配置了 delegate 时必须传入，只能用于支持 D 模式的接口 |
| `X-End-User` | 否 | S 模式下区分外部使用者，不改变授权主体；不能与 X-On-Behalf-Of 同时传入 |

S 表示“自身身份”，D 表示“代表他人”。每个接口的基本信息保留 S/D 标记；仅标 S 的接口不支持代表他人。

**请求示例说明**

- 使用 `application/json` 的请求提供独立的 JSON 示例及对应 curl 示例。
- 四个上传类 POST 使用 `multipart/form-data`，同时提供表单字段的 JSON 示意和实际上传示例。JSON 示意不作为这四个接口的 HTTP 请求体。
- 成功响应、返回字段和返回示例沿用原文档结构；流式接口分别说明 SSE 内容。

**通用错误响应**

所有 HTTP 接口均声明 400、401、403、404、422、500、503。错误 JSON 示例：

```json
{
  "status_code": 26003,
  "status_message": "缺少接口所需权限",
  "data": {
    "required": "knowledge:read"
  }
}
```

<a id="knowledge"></a>

## 知识库

共 **28 个接口**（HTTP 28 个，WebSocket 0 个）。包括知识库、问答库和知识空间相关接口，以及文件、问答、元数据与引用查询。

读取权限接口 7 个，写入权限接口 21 个。元数据的两个查询接口沿用 `knowledge:write`；日常会话附件上传归入“日常模式会话”。

| 功能组 | 接口用途 | 方法 | 路径 | 权限位 |
|---|---|---|---|---|
| 资源管理 | [查询知识资源列表](#knowledge-01) | GET | `/api/v2/filelib/` | `knowledge:read` |
| 资源管理 | [创建知识资源](#knowledge-02) | POST | `/api/v2/filelib/` | `knowledge:write` |
| 资源管理 | [修改知识资源](#knowledge-03) | PUT | `/api/v2/filelib/` | `knowledge:write` |
| 资源管理 | [删除知识资源](#knowledge-04) | DELETE | `/api/v2/filelib/{knowledge_id}` | `knowledge:write` |
| 资源管理 | [清空知识资源内容](#knowledge-05) | DELETE | `/api/v2/filelib/clear/{knowledge_id}` | `knowledge:write` |
| 文件与内容 | [查询文件或目录列表](#knowledge-06) | GET | `/api/v2/filelib/file/list` | `knowledge:read` |
| 文件与内容 | [上传知识文件](#knowledge-07) | POST | `/api/v2/filelib/file/{knowledge_id}` | `knowledge:write` |
| 文件与内容 | [上传文件并同步切分](#knowledge-08) | POST | `/api/v2/filelib/chunks` | `knowledge:write` |
| 文件与内容 | [写入文本块](#knowledge-09) | POST | `/api/v2/filelib/chunks_string` | `knowledge:write` |
| 文件与内容 | [删除单个文件](#knowledge-10) | DELETE | `/api/v2/filelib/file/{file_id}` | `knowledge:write` |
| 文件与内容 | [批量删除文件](#knowledge-11) | POST | `/api/v2/filelib/delete_file` | `knowledge:write` |
| 检索与引用 | [检索知识片段](#knowledge-12) | POST | `/api/v2/filelib/retrieve` | `knowledge:read` |
| 检索与引用 | [查询引用详情](#knowledge-13) | GET | `/api/v2/citation/{citation_id}` | `knowledge:read` |
| 处理日志 | [下载处理统计日志](#knowledge-14) | GET | `/api/v2/filelib/download_statistic` | `knowledge:read` |
| 问答管理 | [按时间查询问答](#knowledge-15) | POST | `/api/v2/filelib/query_qa` | `knowledge:read` |
| 问答管理 | [查询问答详情](#knowledge-16) | GET | `/api/v2/filelib/detail_qa` | `knowledge:read` |
| 问答管理 | [批量新增问答](#knowledge-17) | POST | `/api/v2/filelib/add_qa` | `knowledge:write` |
| 问答管理 | [追加相似问题](#knowledge-18) | POST | `/api/v2/filelib/add_relative_qa` | `knowledge:write` |
| 问答管理 | [修改问答](#knowledge-19) | POST | `/api/v2/filelib/update_qa` | `knowledge:write` |
| 问答管理 | [删除问答或相似问题](#knowledge-20) | DELETE | `/api/v2/filelib/qa/{qa_id}` | `knowledge:write` |
| 元数据字段 | [查询知识库元数据字段](#knowledge-21) | GET | `/api/v2/knowledge/get_metadata_fields/{knowledge_id}` | `knowledge:write` |
| 元数据字段 | [新增知识库元数据字段](#knowledge-22) | POST | `/api/v2/knowledge/add_metadata_fields` | `knowledge:write` |
| 元数据字段 | [修改知识库元数据字段](#knowledge-23) | PUT | `/api/v2/knowledge/modify_metadata_fields` | `knowledge:write` |
| 元数据字段 | [删除知识库元数据字段](#knowledge-24) | DELETE | `/api/v2/knowledge/delete_metadata_fields` | `knowledge:write` |
| 文件元数据 | [查询文件元数据](#knowledge-25) | POST | `/api/v2/knowledge/file/list_user_metadata` | `knowledge:write` |
| 文件元数据 | [新增文件元数据](#knowledge-26) | POST | `/api/v2/knowledge/file/add_user_metadata` | `knowledge:write` |
| 文件元数据 | [修改文件元数据](#knowledge-27) | PUT | `/api/v2/knowledge/file/modify_user_metadata` | `knowledge:write` |
| 文件元数据 | [删除文件元数据](#knowledge-28) | DELETE | `/api/v2/knowledge/file/delete_user_metadata` | `knowledge:write` |

<a id="knowledge-01"></a>

### `GET /api/v2/filelib/`

**接口用途：查询知识资源列表。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `type` | `integer` | 否 | `0` | 类型 |
| query | `name` | `string / null` | 否 | `—` | 名称 |
| query | `sort_by` | `string` | 否 | `update_time` | 排序字段 |
| query | `page_size` | `integer / null` | 否 | `10` | 每页数量 |
| query | `cursor` | `string / null` | 否 | `—` | 下一页游标 |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/filelib/" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeCursorPage` | 知识资源游标分页结果 |
| `data.data` | `array<KnowledgeDetail>` | 本页数据 |
| `data.data[].id` | `integer` | 知识资源 ID |
| `data.data[].name` | `string` | 知识资源名称 |
| `data.data[].type` | `integer` | 0 文档知识库、1 问答知识库、3 知识空间 |
| `data.data[].description` | `string / null` | 说明 |
| `data.data[].model` | `string / null` | 向量模型 ID |
| `data.data[].state` | `integer / null` | 状态 |
| `data.data[].auth_type` | `string / null` | 知识空间访问方式 |
| `data.data[].user_id` | `integer / null` | 业务归属人用户 ID |
| `data.data[].tenant_id` | `integer / null` | 租户 ID |
| `data.data[].user_name` | `string / null` | 业务归属人名称 |
| `data.data[].actions` | `array<string> / null` | 当前主体可执行的操作 |
| `data.data[].create_time` | `string(date-time) / null` | 创建时间 |
| `data.data[].update_time` | `string(date-time) / null` | 更新时间 |
| `data.page_size` | `integer` | 本页条数 |
| `data.has_more` | `boolean` | 是否还有下一页 |
| `data.next_cursor` | `string / null` | 下一页游标；没有下一页时为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": 123,
        "name": "产品知识库",
        "type": 0
      }
    ],
    "page_size": 10,
    "has_more": false,
    "next_cursor": null
  }
}
```

<a id="knowledge-02"></a>

### `POST /api/v2/filelib/`

**接口用途：创建知识资源。**

创建知识库、问答库或知识空间。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `name` | `string` | 是 | `—` | 名称 |
| `type` | `integer` | 否 | `0` | 类型 |
| `description` | `string / null` | 否 | `—` | 说明 |
| `model` | `string / null` | 否 | `—` | 知识助手 ID 或模型 ID，具体含义见接口说明 |
| `collection_name` | `string / null` | 否 | `—` | 向量数据库中的集合名称 |
| `index_name` | `string / null` | 否 | `—` | 检索引擎中的索引名称 |
| `state` | `integer / null` | 否 | `1` | 知识资源状态 |
| `is_released` | `boolean` | 否 | `False` | 是否发布到知识广场 |
| `auth_type` | `AuthTypeEnum` | 否 | `public` | 访问权限类型 |
| `is_shared` | `boolean` | 否 | `False` | 知识资源是否共享 |
| `auto_tag_enabled` | `boolean` | 否 | `False` | 是否开启自动标签 |
| `auto_tag_library_id` | `integer / null` | 否 | `—` | 自动标签所使用的标签库 ID |
| `metadata_fields` | `array<object> / null` | 否 | `—` | 元数据字段定义列表 |
| `is_partition` | `boolean / null` | 否 | `—` | 是否使用向量数据库分区 |

#### 请求 JSON 示例

```json
{
  "name": "产品知识库",
  "type": 0,
  "description": "产品资料",
  "model": "embedding-model-id"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"name":"产品知识库","type":0,"description":"产品资料","model":"embedding-model-id"}'
```

#### 成功响应

HTTP 状态：`201`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeDetail` | 创建或更新后的知识资源 |
| `data.id` | `integer` | 知识资源 ID |
| `data.name` | `string` | 知识资源名称 |
| `data.type` | `integer` | 0 文档知识库、1 问答知识库、3 知识空间 |
| `data.description` | `string / null` | 说明 |
| `data.model` | `string / null` | 向量模型 ID |
| `data.state` | `integer / null` | 状态 |
| `data.auth_type` | `string / null` | 知识空间访问方式 |
| `data.user_id` | `integer / null` | 业务归属人用户 ID |
| `data.tenant_id` | `integer / null` | 租户 ID |
| `data.user_name` | `string / null` | 业务归属人名称 |
| `data.actions` | `array<string> / null` | 当前主体可执行的操作 |
| `data.create_time` | `string(date-time) / null` | 创建时间 |
| `data.update_time` | `string(date-time) / null` | 更新时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 123,
    "name": "产品知识库",
    "type": 0,
    "actions": [
      "view",
      "edit"
    ]
  }
}
```

<a id="knowledge-03"></a>

### `PUT /api/v2/filelib/`

**接口用途：修改知识资源。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/` |
| 请求方式 | `PUT` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `name` | `string / null` | 否 | `—` | 名称 |
| `description` | `string / null` | 否 | `—` | 说明 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "name": "新名称",
  "description": "新说明"
}
```

#### 请求示例

```bash
curl -X PUT "$BISHENG_API_BASE/api/v2/filelib/" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"name":"新名称","description":"新说明"}'
```

#### 成功响应

HTTP 状态：`201`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeDetail` | 创建或更新后的知识资源 |
| `data.id` | `integer` | 知识资源 ID |
| `data.name` | `string` | 知识资源名称 |
| `data.type` | `integer` | 0 文档知识库、1 问答知识库、3 知识空间 |
| `data.description` | `string / null` | 说明 |
| `data.model` | `string / null` | 向量模型 ID |
| `data.state` | `integer / null` | 状态 |
| `data.auth_type` | `string / null` | 知识空间访问方式 |
| `data.user_id` | `integer / null` | 业务归属人用户 ID |
| `data.tenant_id` | `integer / null` | 租户 ID |
| `data.user_name` | `string / null` | 业务归属人名称 |
| `data.actions` | `array<string> / null` | 当前主体可执行的操作 |
| `data.create_time` | `string(date-time) / null` | 创建时间 |
| `data.update_time` | `string(date-time) / null` | 更新时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 123,
    "name": "产品知识库",
    "type": 0,
    "actions": [
      "view",
      "edit"
    ]
  }
}
```

<a id="knowledge-04"></a>

### `DELETE /api/v2/filelib/{knowledge_id}`

**接口用途：删除知识资源。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/{knowledge_id}` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/filelib/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-05"></a>

### `DELETE /api/v2/filelib/clear/{knowledge_id}`

**接口用途：清空知识资源内容。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/clear/{knowledge_id}` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/filelib/clear/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-06"></a>

### `GET /api/v2/filelib/file/list`

**接口用途：查询文件或目录列表。**

查询知识文件或目录。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/file/list` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| query | `parent_id` | `integer / null` | 否 | `—` | 父目录 ID |
| query | `keyword` | `string` | 否 | `—` | 名称关键字 |
| query | `status` | `array<integer>` | 否 | `—` | 状态筛选 |
| query | `page_size` | `integer` | 否 | `10` | 每页数量 |
| query | `cursor` | `string / null` | 否 | `—` | 下一页游标 |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/filelib/file/list?knowledge_id=123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `FileCursorPage` | 文件或目录游标分页结果 |
| `data.data` | `array<KnowledgeFileItem>` | 本页文件或目录 |
| `data.data[].id` | `integer` | 文件或目录 ID |
| `data.data[].knowledge_id` | `integer` | 所属知识资源 ID |
| `data.data[].file_name` | `string` | 文件或目录名称 |
| `data.data[].status` | `integer / null` | 解析状态 |
| `data.data[].parent_id` | `integer / null` | 父目录 ID |
| `data.data[].type` | `integer / null` | 资源类型 |
| `data.data[].create_time` | `string(date-time) / null` | 创建时间 |
| `data.data[].update_time` | `string(date-time) / null` | 更新时间 |
| `data.page_size` | `integer` | 本页条数 |
| `data.has_more` | `boolean` | 是否还有下一页 |
| `data.next_cursor` | `string / null` | 下一页游标 |
| `data.writeable` | `boolean` | 当前主体是否可向此位置写入 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": 789,
        "knowledge_id": 123,
        "file_name": "合同.pdf"
      }
    ],
    "page_size": 10,
    "has_more": false,
    "next_cursor": null,
    "writeable": true
  }
}
```

<a id="knowledge-07"></a>

### `POST /api/v2/filelib/file/{knowledge_id}`

**接口用途：上传知识文件。**

上传文件到知识资源。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/file/{knowledge_id}` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`multipart/form-data`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `split_mode` | `string / null` | 否 | `auto` | 切分模式：auto、custom 或 hierarchical |
| `separator` | `array<string> / null` | 否 | `—` | 自定义分隔符列表 |
| `separator_rule` | `array<string> / null` | 否 | `—` | 分隔符切分规则列表 |
| `chunk_size` | `integer / null` | 否 | `—` | 文本块长度 |
| `chunk_overlap` | `integer / null` | 否 | `—` | 文本块重叠长度 |
| `hierarchy_level` | `integer / null` | 否 | `3` | 层级切分深度 |
| `append_title` | `boolean / null` | 否 | `False` | 是否给文本块附加标题 |
| `max_chunk_size` | `integer / null` | 否 | `1000` | 最大文本块长度 |
| `callback_url` | `string / null` | 否 | `—` | 知识文件处理完成后的回调地址 |
| `file_url` | `string / null` | 否 | `—` | 服务端要下载的文件 URL |
| `file` | `string(binary) / null` | 否 | `—` | 上传文件 |
| `retain_images` | `integer / null` | 否 | `1` | 是否保留文档图片；1 是、0 否 |
| `force_ocr` | `integer / null` | 否 | `0` | 是否强制 OCR；1 是、0 否 |
| `enable_formula` | `integer / null` | 否 | `1` | 是否识别公式；1 是、0 否 |
| `filter_page_header_footer` | `integer / null` | 否 | `0` | 是否过滤页眉页脚；1 是、0 否 |
| `excel_rule` | `ExcelRule / null` | 否 | `{}` | Excel 切分规则 |
| `excel_rule.slice_length` | `integer / null` | 否 | `10` | 每个分片包含的数据行数 |
| `excel_rule.header_start_row` | `integer / null` | 否 | `1` | 表头起始行 |
| `excel_rule.header_end_row` | `integer / null` | 否 | `1` | 表头结束行 |
| `excel_rule.append_header` | `integer / null` | 否 | `1` | 是否给每个分片附加表头 |
| `parent_id` | `integer / null` | 否 | `—` | 父目录 ID |

#### 表单字段 JSON 示例

下面的 JSON 用于说明表单字段及其填写值。实际请求使用 `multipart/form-data`；`file` 的示例值是本地文件路径，发送时需上传该文件的二进制内容。请使用下方的 `curl -F` 示例。

```json
{
  "file": "/path/to/合同.pdf",
  "split_mode": "auto",
  "hierarchy_level": 3,
  "append_title": false,
  "max_chunk_size": 1000,
  "retain_images": 1,
  "force_ocr": 0,
  "enable_formula": 1,
  "filter_page_header_footer": 0
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/file/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -F 'file=@/path/to/合同.pdf' \
  -F 'split_mode=auto' \
  -F 'hierarchy_level=3' \
  -F 'append_title=false' \
  -F 'max_chunk_size=1000' \
  -F 'retain_images=1' \
  -F 'force_ocr=0' \
  -F 'enable_formula=1' \
  -F 'filter_page_header_footer=0'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeFileResult` | 文件处理结果 |
| `data.id` | `integer / null` | 知识文件 ID |
| `data.knowledge_id` | `integer / null` | 知识资源 ID |
| `data.file_name` | `string / null` | 文件名 |
| `data.file_path` | `string / null` | 文件路径或对象存储引用 |
| `data.status` | `integer / null` | 处理状态 |
| `data.error` | `string / null` | 处理失败原因 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 789,
    "knowledge_id": 123,
    "file_name": "合同.pdf",
    "status": 1
  }
}
```

<a id="knowledge-08"></a>

### `POST /api/v2/filelib/chunks`

**接口用途：上传文件并同步切分。**

上传并同步切分文件。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/chunks` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`multipart/form-data`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `metadata` | `string` | 是 | `—` | 文件元数据 JSON 字符串 |
| `split_mode` | `string / null` | 否 | `auto` | 切分模式：auto、custom 或 hierarchical |
| `separator` | `array<string> / null` | 否 | `—` | 自定义分隔符列表 |
| `separator_rule` | `array<string> / null` | 否 | `—` | 分隔符切分规则列表 |
| `chunk_size` | `integer / null` | 否 | `—` | 文本块长度 |
| `chunk_overlap` | `integer / null` | 否 | `—` | 文本块重叠长度 |
| `hierarchy_level` | `integer / null` | 否 | `3` | 层级切分深度 |
| `append_title` | `boolean / null` | 否 | `False` | 是否给文本块附加标题 |
| `max_chunk_size` | `integer / null` | 否 | `1000` | 最大文本块长度 |
| `file` | `string(binary)` | 是 | `—` | 上传文件 |

#### 表单字段 JSON 示例

下面的 JSON 用于说明表单字段及其填写值。实际请求使用 `multipart/form-data`；`file` 的示例值是本地文件路径，发送时需上传该文件的二进制内容。请使用下方的 `curl -F` 示例。

```json
{
  "knowledge_id": 123,
  "metadata": "{}",
  "split_mode": "auto",
  "file": "/path/to/合同.pdf"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/chunks" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -F 'knowledge_id=123' \
  -F 'metadata={}' \
  -F 'split_mode=auto' \
  -F 'file=@/path/to/合同.pdf'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeFileResult` | 文件处理结果 |
| `data.id` | `integer / null` | 知识文件 ID |
| `data.knowledge_id` | `integer / null` | 知识资源 ID |
| `data.file_name` | `string / null` | 文件名 |
| `data.file_path` | `string / null` | 文件路径或对象存储引用 |
| `data.status` | `integer / null` | 处理状态 |
| `data.error` | `string / null` | 处理失败原因 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 789,
    "knowledge_id": 123,
    "file_name": "合同.pdf",
    "status": 1
  }
}
```

<a id="knowledge-09"></a>

### `POST /api/v2/filelib/chunks_string`

**接口用途：写入文本块。**

写入调用方提供的文本块。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/chunks_string` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `documents` | `array<Document>` | 是 | `—` | 要写入的文本块 |
| `documents[].id` | `string / null` | 否 | `—` | 记录 ID |
| `documents[].metadata` | `object` | 否 | `—` | 文件元数据 JSON 字符串 |
| `documents[].page_content` | `string` | 是 | `—` | 文本块正文 |
| `documents[].type` | `string` | 否 | `Document` | 类型 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "documents": [
    {
      "page_content": "要写入的文本",
      "metadata": {
        "source": "example.txt"
      }
    }
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/chunks_string" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"documents":[{"page_content":"要写入的文本","metadata":{"source":"example.txt"}}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `KnowledgeFileResult` | 文件处理结果 |
| `data.id` | `integer / null` | 知识文件 ID |
| `data.knowledge_id` | `integer / null` | 知识资源 ID |
| `data.file_name` | `string / null` | 文件名 |
| `data.file_path` | `string / null` | 文件路径或对象存储引用 |
| `data.status` | `integer / null` | 处理状态 |
| `data.error` | `string / null` | 处理失败原因 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 789,
    "knowledge_id": 123,
    "file_name": "合同.pdf",
    "status": 1
  }
}
```

<a id="knowledge-10"></a>

### `DELETE /api/v2/filelib/file/{file_id}`

**接口用途：删除单个文件。**

删除单个知识文件。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/file/{file_id}` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `file_id` | `integer` | 是 | `—` | 知识文件 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/filelib/file/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-11"></a>

### `POST /api/v2/filelib/delete_file`

**接口用途：批量删除文件。**

批量删除知识文件。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/delete_file` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

请求体类型为 `array<integer>`，没有可展开的固定字段。

#### 请求 JSON 示例

```json
[
  789,
  790
]
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/delete_file" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '[789,790]'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-12"></a>

### `POST /api/v2/filelib/retrieve`

**接口用途：检索知识片段。**

只召回知识片段，不调用大模型。D 模式按被代表用户的文件可见范围过滤。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/retrieve` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `query` | `string` | 是 | `—` | 检索问题 |
| `knowledge_base_ids` | `array<integer>` | 是 | `—` | 要检索的知识库 ID 列表 |
| `filters` | `RetrieveFilters / null` | 否 | `—` | 按知识库设置的标签过滤条件 |
| `filters.knowledge_base_filters` | `array<KnowledgeBaseFilter>` | 否 | `—` | 各知识库的标签过滤条件 |
| `filters.knowledge_base_filters[].knowledge_base_id` | `integer` | 是 | `—` | 知识库 ID，必须同时出现在 knowledge_base_ids 中 |
| `filters.knowledge_base_filters[].tags` | `array<string>` | 否 | `—` | 用于缩小文件范围的标签名称 |
| `filters.knowledge_base_filters[].tag_match_mode` | `string` | 否 | `ANY` | 标签匹配方式：ANY 表示命中任意标签；ALL 暂不支持 |
| `top_k` | `integer` | 否 | `10` | 最多返回的文本片段数量 |
| `max_content` | `integer` | 否 | `15000` | 每个知识库合并内容的最大长度 |

#### 请求 JSON 示例

```json
{
  "query": "合同有效期多久？",
  "knowledge_base_ids": [
    123
  ],
  "filters": {
    "knowledge_base_filters": [
      {
        "knowledge_base_id": 123,
        "tags": [
          "合同"
        ],
        "tag_match_mode": "ANY"
      }
    ]
  },
  "top_k": 10,
  "max_content": 15000
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/retrieve" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"query":"合同有效期多久？","knowledge_base_ids":[123],"filters":{"knowledge_base_filters":[{"knowledge_base_id":123,"tags":["合同"],"tag_match_mode":"ANY"}]},"top_k":10,"max_content":15000}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `RetrieveResp` | 知识片段召回结果 |
| `data.chunks` | `array<RetrieveChunk>` | 召回片段列表 |
| `data.chunks[].content` | `string` | 召回的正文片段 |
| `data.chunks[].knowledge_id` | `integer` | 知识库 ID |
| `data.chunks[].document_id` | `integer` | 来源文件 ID |
| `data.chunks[].document_name` | `string` | 来源文件名 |
| `data.chunks[].chunk_index` | `integer` | 片段在文件中的序号 |
| `data.chunks[].document_update_time` | `string` | 来源文件最后更新时间，格式为 YYYY-MM-DD HH:mm:ss |
| `data.total` | `integer` | 返回的片段数量 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "chunks": [
      {
        "content": "命中的正文片段",
        "knowledge_id": 123,
        "document_id": 789,
        "document_name": "合同.pdf",
        "chunk_index": 3,
        "document_update_time": "2026-09-04 10:00:00"
      }
    ],
    "total": 1
  }
}
```

<a id="knowledge-13"></a>

### `GET /api/v2/citation/{citation_id}`

**接口用途：查询引用详情。**

查询引用溯源详情。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/citation/{citation_id}` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `citation_id` | `string` | 是 | `—` | 引用溯源 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/citation/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `OpenCitationResponse` | 引用溯源详情 |
| `data.file_id` | `integer / null` | 知识文件 ID |
| `data.file_name` | `string / null` | 知识文件名称 |
| `data.file_type` | `string / null` | 知识文件类型 |
| `data.knowledge_name` | `string / null` | 知识库名称 |
| `data.download_url` | `string / null` | 文件下载地址 |
| `data.preview_url` | `string / null` | 文件预览地址 |
| `data.bbox` | `string / null` | 引用内容在原文件中的位置 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file_id": 789,
    "file_name": "合同.pdf",
    "file_type": "pdf",
    "knowledge_name": "合同知识库",
    "download_url": "https://api.example.com/files/789/download",
    "preview_url": "https://api.example.com/files/789/preview",
    "bbox": "1,100,100,300,180"
  }
}
```

<a id="knowledge-14"></a>

### `GET /api/v2/filelib/download_statistic`

**接口用途：下载处理统计日志。**

只允许 S 模式。使用 file_path 指定服务器上已有的 .log 文件；当前实现要求路径以 /app/data 开头，且去掉 .log 后不能含有点号。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/download_statistic` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `file_path` | `string` | 是 | `—` | 服务器上的 .log 文件路径；使用实际处理日志路径，例如 /app/data/statistic.log |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/filelib/download_statistic?file_path=%2Fapp%2Fdata%2Fstatistic.log" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/octet-stream`。

#### 返回字段

响应体为文件二进制数据，没有 JSON 字段。

#### 返回示例

```text
<binary file content>
```

<a id="knowledge-15"></a>

### `POST /api/v2/filelib/query_qa`

**接口用途：按时间查询问答。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/query_qa` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `timeRange` | `array<string>` | 是 | `—` | 查询时间范围：[开始时间, 结束时间] |

#### 请求 JSON 示例

```json
{
  "timeRange": [
    "2026-09-01 00:00:00",
    "2026-09-04 23:59:59"
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/query_qa" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"timeRange":["2026-09-01 00:00:00","2026-09-04 23:59:59"]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `array<QAItem>` | 问答记录列表 |
| `data[].id` | `integer` | 问答记录 ID |
| `data[].knowledge_id` | `integer` | 所属问答知识库 ID |
| `data[].questions` | `array<string>` | 问题及相似问法 |
| `data[].answers` | `array<string>` | 答案列表 |
| `data[].source` | `integer / null` | 数据来源 |
| `data[].extra_meta` | `string / null` | 扩展元数据 JSON 字符串 |
| `data[].create_time` | `string(date-time) / null` | 创建时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "id": 456,
      "knowledge_id": 123,
      "questions": [
        "什么是毕昇？"
      ],
      "answers": [
        "企业级大模型应用平台"
      ]
    }
  ]
}
```

<a id="knowledge-16"></a>

### `GET /api/v2/filelib/detail_qa`

**接口用途：查询问答详情。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/detail_qa` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `id` | `integer` | 是 | `—` | 记录 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/filelib/detail_qa?id=123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `QAItem / null` | 问答记录 |
| `data.id` | `integer` | 问答记录 ID |
| `data.knowledge_id` | `integer` | 所属问答知识库 ID |
| `data.questions` | `array<string>` | 问题及相似问法 |
| `data.answers` | `array<string>` | 答案列表 |
| `data.source` | `integer / null` | 数据来源 |
| `data.extra_meta` | `string / null` | 扩展元数据 JSON 字符串 |
| `data.create_time` | `string(date-time) / null` | 创建时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 456,
    "knowledge_id": 123,
    "questions": [
      "什么是毕昇？"
    ],
    "answers": [
      "企业级大模型应用平台"
    ]
  }
}
```

<a id="knowledge-17"></a>

### `POST /api/v2/filelib/add_qa`

**接口用途：批量新增问答。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/add_qa` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `data` | `array<APIAddQAParam>` | 是 | `—` | 要新增的问答列表 |
| `data[].question` | `string` | 是 | `—` | 问题 |
| `data[].answer` | `array<string>` | 是 | `—` | 答案列表 |
| `data[].extra` | `object / null` | 否 | `{}` | 问答扩展信息 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "data": [
    {
      "question": "什么是毕昇？",
      "answer": [
        "企业级大模型应用平台"
      ],
      "extra": {}
    }
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/add_qa" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"data":[{"question":"什么是毕昇？","answer":["企业级大模型应用平台"],"extra":{}}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `array<QAItem>` | 问答记录列表 |
| `data[].id` | `integer` | 问答记录 ID |
| `data[].knowledge_id` | `integer` | 所属问答知识库 ID |
| `data[].questions` | `array<string>` | 问题及相似问法 |
| `data[].answers` | `array<string>` | 答案列表 |
| `data[].source` | `integer / null` | 数据来源 |
| `data[].extra_meta` | `string / null` | 扩展元数据 JSON 字符串 |
| `data[].create_time` | `string(date-time) / null` | 创建时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "id": 456,
      "knowledge_id": 123,
      "questions": [
        "什么是毕昇？"
      ],
      "answers": [
        "企业级大模型应用平台"
      ]
    }
  ]
}
```

<a id="knowledge-18"></a>

### `POST /api/v2/filelib/add_relative_qa`

**接口用途：追加相似问题。**

补充问答相似问题。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/add_relative_qa` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `data` | `APIAppendQAParam` | 是 | `—` | 要追加的相似问题 |
| `data.relative_questions` | `array<string>` | 否 | `[]` | 相似问题列表 |
| `data.id` | `string` | 否 | `—` | 记录 ID |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "data": {
    "id": "456",
    "relative_questions": [
      "毕昇是什么？"
    ]
  }
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/add_relative_qa" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"data":{"id":"456","relative_questions":["毕昇是什么？"]}}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `QAItem / null` | 问答记录 |
| `data.id` | `integer` | 问答记录 ID |
| `data.knowledge_id` | `integer` | 所属问答知识库 ID |
| `data.questions` | `array<string>` | 问题及相似问法 |
| `data.answers` | `array<string>` | 答案列表 |
| `data.source` | `integer / null` | 数据来源 |
| `data.extra_meta` | `string / null` | 扩展元数据 JSON 字符串 |
| `data.create_time` | `string(date-time) / null` | 创建时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 456,
    "knowledge_id": 123,
    "questions": [
      "什么是毕昇？"
    ],
    "answers": [
      "企业级大模型应用平台"
    ]
  }
}
```

<a id="knowledge-19"></a>

### `POST /api/v2/filelib/update_qa`

**接口用途：修改问答。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/update_qa` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `id` | `integer` | 是 | `—` | 记录 ID |
| `question` | `string / null` | 否 | `—` | 问题 |
| `original_question` | `string / null` | 否 | `—` | 修改前的问题 |
| `answer` | `array<string> / null` | 否 | `—` | 答案列表 |

#### 请求 JSON 示例

```json
{
  "id": 456,
  "question": "什么是毕昇平台？",
  "answer": [
    "企业级大模型应用平台"
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/filelib/update_qa" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"id":456,"question":"什么是毕昇平台？","answer":["企业级大模型应用平台"]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-20"></a>

### `DELETE /api/v2/filelib/qa/{qa_id}`

**接口用途：删除问答或相似问题。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/filelib/qa/{qa_id}` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `qa_id` | `integer` | 是 | `—` | 问答记录 ID |
| query | `question` | `string / null` | 否 | `—` | 问题 |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/filelib/qa/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="knowledge-21"></a>

### `GET /api/v2/knowledge/get_metadata_fields/{knowledge_id}`

**接口用途：查询知识库元数据字段。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/get_metadata_fields/{knowledge_id}` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/knowledge/get_metadata_fields/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `array<MetadataField>` | 知识库元数据字段定义 |
| `data[].field_name` | `string` | 元数据字段名 |
| `data[].field_type` | `MetadataFieldType` | 元数据字段类型 |
| `data[].updated_at` | `integer` | 元数据字段更新时间戳 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "field_name": "contract_no",
      "field_type": "string",
      "updated_at": 1788480000
    }
  ]
}
```

<a id="knowledge-22"></a>

### `POST /api/v2/knowledge/add_metadata_fields`

**接口用途：新增知识库元数据字段。**

增加知识库元数据字段。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/add_metadata_fields` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `metadata_fields` | `array<MetadataField>` | 是 | `—` | 元数据字段定义列表 |
| `metadata_fields[].field_name` | `string` | 是 | `—` | 元数据字段名 |
| `metadata_fields[].field_type` | `MetadataFieldType` | 是 | `—` | 元数据字段类型 |
| `metadata_fields[].updated_at` | `integer` | 否 | `—` | 元数据字段更新时间戳 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "metadata_fields": [
    {
      "field_name": "contract_no",
      "field_type": "string"
    }
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/knowledge/add_metadata_fields" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"metadata_fields":[{"field_name":"contract_no","field_type":"string"}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="knowledge-23"></a>

### `PUT /api/v2/knowledge/modify_metadata_fields`

**接口用途：修改知识库元数据字段。**

修改知识库元数据字段名。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/modify_metadata_fields` |
| 请求方式 | `PUT` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `metadata_fields` | `array<UpdateMetadataFieldName>` | 是 | `—` | 元数据字段定义列表 |
| `metadata_fields[].old_field_name` | `string` | 是 | `—` | 修改前的元数据字段名 |
| `metadata_fields[].new_field_name` | `string` | 是 | `—` | 修改后的元数据字段名 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "metadata_fields": [
    {
      "old_field_name": "contract_no",
      "new_field_name": "contract_code"
    }
  ]
}
```

#### 请求示例

```bash
curl -X PUT "$BISHENG_API_BASE/api/v2/knowledge/modify_metadata_fields" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"metadata_fields":[{"old_field_name":"contract_no","new_field_name":"contract_code"}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="knowledge-24"></a>

### `DELETE /api/v2/knowledge/delete_metadata_fields`

**接口用途：删除知识库元数据字段。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/delete_metadata_fields` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `field_names` | `array<string>` | 是 | `—` | 元数据字段名列表 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "field_names": [
    "contract_code"
  ]
}
```

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/knowledge/delete_metadata_fields" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"field_names":["contract_code"]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="knowledge-25"></a>

### `POST /api/v2/knowledge/file/list_user_metadata`

**接口用途：查询文件元数据。**

查询文件用户元数据。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/file/list_user_metadata` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `knowledge_file_ids` | `array<integer>` | 是 | `—` | 知识文件 ID 列表 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "knowledge_file_ids": [
    789
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/knowledge/file/list_user_metadata" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"knowledge_file_ids":[789]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `array<object>` | 文件用户元数据列表 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "knowledge_file_id": 789,
      "user_metadata": {
        "contract_no": "HT-001"
      }
    }
  ]
}
```

<a id="knowledge-26"></a>

### `POST /api/v2/knowledge/file/add_user_metadata`

**接口用途：新增文件元数据。**

增加文件用户元数据。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/file/add_user_metadata` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `add_metadata_list` | `array<ModifyKnowledgeFileMetaDataReq>` | 是 | `—` | 要新增的文件元数据 |
| `add_metadata_list[].knowledge_file_id` | `integer` | 是 | `—` | 知识文件 ID |
| `add_metadata_list[].user_metadata_list` | `array<FileUserMetaDataInfo>` | 是 | `—` | 文件元数据列表 |
| `add_metadata_list[].user_metadata_list[].field_name` | `string` | 是 | `—` | 元数据字段名 |
| `add_metadata_list[].user_metadata_list[].field_value` | `object / null` | 否 | `—` | 元数据字段值 |
| `add_metadata_list[].user_metadata_list[].updated_at` | `integer` | 否 | `—` | 元数据字段更新时间戳 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "add_metadata_list": [
    {
      "knowledge_file_id": 789,
      "user_metadata_list": [
        {
          "field_name": "contract_no",
          "field_value": "HT-001"
        }
      ]
    }
  ]
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/knowledge/file/add_user_metadata" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"add_metadata_list":[{"knowledge_file_id":789,"user_metadata_list":[{"field_name":"contract_no","field_value":"HT-001"}]}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="knowledge-27"></a>

### `PUT /api/v2/knowledge/file/modify_user_metadata`

**接口用途：修改文件元数据。**

修改文件用户元数据。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/file/modify_user_metadata` |
| 请求方式 | `PUT` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `modify_metadata_list` | `array<ModifyKnowledgeFileMetaDataReq>` | 是 | `—` | 要修改的文件元数据 |
| `modify_metadata_list[].knowledge_file_id` | `integer` | 是 | `—` | 知识文件 ID |
| `modify_metadata_list[].user_metadata_list` | `array<FileUserMetaDataInfo>` | 是 | `—` | 文件元数据列表 |
| `modify_metadata_list[].user_metadata_list[].field_name` | `string` | 是 | `—` | 元数据字段名 |
| `modify_metadata_list[].user_metadata_list[].field_value` | `object / null` | 否 | `—` | 元数据字段值 |
| `modify_metadata_list[].user_metadata_list[].updated_at` | `integer` | 否 | `—` | 元数据字段更新时间戳 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "modify_metadata_list": [
    {
      "knowledge_file_id": 789,
      "user_metadata_list": [
        {
          "field_name": "contract_no",
          "field_value": "HT-002"
        }
      ]
    }
  ]
}
```

#### 请求示例

```bash
curl -X PUT "$BISHENG_API_BASE/api/v2/knowledge/file/modify_user_metadata" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"modify_metadata_list":[{"knowledge_file_id":789,"user_metadata_list":[{"field_name":"contract_no","field_value":"HT-002"}]}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="knowledge-28"></a>

### `DELETE /api/v2/knowledge/file/delete_user_metadata`

**接口用途：删除文件元数据。**

删除文件用户元数据。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/file/delete_user_metadata` |
| 请求方式 | `DELETE` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `knowledge:write` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `knowledge_id` | `integer` | 是 | `—` | 知识资源 ID |
| `delete_user_metadatas` | `array<DeleteUserMetadataReq>` | 是 | `—` | 要删除的文件元数据 |
| `delete_user_metadatas[].knowledge_file_id` | `integer` | 是 | `—` | 知识文件 ID |
| `delete_user_metadatas[].field_names` | `array<string>` | 是 | `—` | 元数据字段名列表 |

#### 请求 JSON 示例

```json
{
  "knowledge_id": 123,
  "delete_user_metadatas": [
    {
      "knowledge_file_id": 789,
      "field_names": [
        "contract_no"
      ]
    }
  ]
}
```

#### 请求示例

```bash
curl -X DELETE "$BISHENG_API_BASE/api/v2/knowledge/file/delete_user_metadata" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"knowledge_id":123,"delete_user_metadatas":[{"knowledge_file_id":789,"field_names":["contract_no"]}]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `boolean` | 操作是否成功 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": true
}
```

<a id="daily-chat"></a>

## 日常模式会话

共 **5 个接口**（HTTP 5 个，WebSocket 0 个）。按配置查询、附件上传、发起对话、会话查询的顺序排列。当前对话入口固定返回 SSE；会话详情返回会话信息。

| 功能组 | 接口用途 | 方法 | 路径 | 权限位 |
|---|---|---|---|---|
| 调用准备 | [查询可用模型和工具](#daily-chat-01) | GET | `/api/v2/workstation/config` | `chat:invoke` |
| 调用准备 | [上传会话附件](#daily-chat-02) | POST | `/api/v2/knowledge/upload` | `chat:invoke` |
| 对话 | [发起日常对话](#daily-chat-03) | POST | `/api/v2/workstation/chat/completions` | `chat:invoke` |
| 会话查询 | [查询会话列表](#daily-chat-04) | GET | `/api/v2/chat/list` | `chat:invoke` |
| 会话查询 | [查询会话详情](#daily-chat-05) | GET | `/api/v2/chat/info` | `chat:invoke` |

<a id="daily-chat-01"></a>

### `GET /api/v2/workstation/config`

**接口用途：查询可用模型和工具。**

响应只返回 models 和 tools。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/workstation/config` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `chat:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/workstation/config" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `OpenWorkstationConfig` | 模型和工具列表 |
| `data.models` | `array<WorkstationModel>` | 当前主体可使用的模型 |
| `data.models[].key` | `string / null` | 模型用途标识 |
| `data.models[].id` | `string` | 模型 ID |
| `data.models[].name` | `string / null` | 模型名称 |
| `data.models[].displayName` | `string / null` | 展示名称 |
| `data.models[].description` | `string / null` | 模型说明，最长 50 个字符 |
| `data.models[].visual` | `boolean / null` | 是否支持视觉输入 |
| `data.tools` | `array<WorkstationToolGroup>` | 当前主体可使用的工具 |
| `data.tools[].id` | `integer` | 工具组 ID |
| `data.tools[].name` | `string` | 工具组名称 |
| `data.tools[].is_preset` | `integer / null` | 0 自定义、1 内置、2 MCP |
| `data.tools[].description` | `string / null` | 工具组说明 |
| `data.tools[].default_checked` | `boolean` | 新会话是否默认选中 |
| `data.tools[].children` | `array<WorkstationToolLeaf>` | 工具组内的具体工具 |
| `data.tools[].children[].id` | `integer` | 工具 ID |
| `data.tools[].children[].name` | `string` | 工具名称 |
| `data.tools[].children[].tool_key` | `string` | 工具唯一标识 |
| `data.tools[].children[].desc` | `string / null` | 工具说明 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "models": [
      {
        "id": "model-id",
        "name": "通用对话模型",
        "visual": false
      }
    ],
    "tools": [
      {
        "id": 1,
        "name": "常用工具",
        "is_preset": 1,
        "default_checked": false,
        "children": [
          {
            "id": 11,
            "name": "联网搜索",
            "tool_key": "web_search"
          }
        ]
      }
    ]
  }
}
```

<a id="daily-chat-02"></a>

### `POST /api/v2/knowledge/upload`

**接口用途：上传会话附件。**

上传临时附件，返回的 file_path 用于日常对话请求 files。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/knowledge/upload` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `chat:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`multipart/form-data`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `file` | `string(binary)` | 是 | `—` | 要上传的附件文件 |

#### 表单字段 JSON 示例

下面的 JSON 用于说明表单字段及其填写值。实际请求使用 `multipart/form-data`；`file` 的示例值是本地文件路径，发送时需上传该文件的二进制内容。请使用下方的 `curl -F` 示例。

```json
{
  "file": "/path/to/example.pdf"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/knowledge/upload" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -F 'file=@/path/to/example.pdf'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `UploadFileData` | 上传后的临时文件引用 |
| `data.flowId` | `string / null` | 关联应用 ID；未关联时为 null |
| `data.file_path` | `string` | 临时文件引用，后续放入日常对话请求 files[] |
| `data.relative_path` | `string / null` | 对象存储相对路径 |
| `data.file_name` | `string / null` | 文件名 |
| `data.repeat` | `boolean` | 是否检测到重复文件 |
| `data.repeat_file_name` | `string / null` | 重复文件名 |
| `data.repeat_update_time` | `string(date-time) / null` | 重复文件更新时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "flowId": null,
    "file_path": "bisheng/tmp/example.pdf",
    "relative_path": null,
    "file_name": "example.pdf",
    "repeat": false,
    "repeat_file_name": null,
    "repeat_update_time": null
  }
}
```

<a id="daily-chat-03"></a>

### `POST /api/v2/workstation/chat/completions`

**接口用途：发起日常对话。**

固定执行日常模式并返回 SSE，支持 files 附件。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/workstation/chat/completions` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `chat:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `clientTimestamp` | `string` | 是 | `—` | 客户端时间；沿用现有会话协议的必填字段 |
| `conversationId` | `string / null` | 否 | `—` | 会话 ID；不传表示新建会话 |
| `error` | `boolean / null` | 否 | `False` | 历史兼容字段 |
| `generation` | `string / null` | 否 | `` | 历史兼容字段 |
| `isCreatedByUser` | `boolean / null` | 否 | `False` | 历史兼容字段 |
| `isContinued` | `boolean / null` | 否 | `False` | 历史兼容字段 |
| `model` | `string` | 是 | `—` | 模型 ID；从工作台配置接口的 models[].id 取得 |
| `text` | `string / null` | 否 | `` | 本轮用户输入 |
| `tools` | `array<DailyToolPayload> / null` | 否 | `—` | 本轮启用的工具；必须来自工作台配置接口 |
| `tools[].id` | `integer` | 否 | `0` | 工具 ID；从工作台配置接口取得 |
| `tools[].tool_key` | `string / null` | 否 | `—` | 工具唯一标识 |
| `tools[].type` | `string` | 否 | `tool` | 当前固定为 tool |
| `skills` | `array<string> / null` | 否 | `—` | 技能名称列表；当前日常模式不使用 |
| `files` | `array<DailyChatFile> / null` | 否 | `—` | 本轮附件；文件引用由 /api/v2/knowledge/upload 返回 |
| `files[].file_id` | `string / null` | 否 | `—` | 附件 ID；如上传响应未返回则可以不传 |
| `files[].filepath` | `string` | 是 | `—` | 上传接口返回的 file_path |
| `files[].filename` | `string` | 是 | `—` | 展示文件名 |
| `files[].type` | `string / null` | 否 | `—` | 文件类型或扩展名 |
| `search_enabled` | `boolean / null` | 否 | `False` | 旧联网搜索字段；新调用应使用 tools |
| `parentMessageId` | `string / null` | 否 | `—` | 历史兼容字段 |
| `overrideParentMessageId` | `string / null` | 否 | `—` | 历史兼容字段 |
| `responseMessageId` | `string / null` | 否 | `—` | 历史兼容字段 |

#### 请求 JSON 示例

```json
{
  "clientTimestamp": "2026-09-04T00:00:00Z",
  "conversationId": null,
  "model": "model-id",
  "text": "请总结这个问题",
  "tools": [],
  "files": []
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/workstation/chat/completions" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"clientTimestamp":"2026-09-04T00:00:00Z","conversationId":null,"model":"model-id","text":"请总结这个问题","tools":[],"files":[]}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`text/event-stream`。

#### 返回字段

每个 SSE `data:` 后面都是一段 JSON：

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | `string` | 消息类别，例如 agent_answer |
| `type` | `string` | 消息阶段，例如 start、stream、end、error |
| `message` | `object / string` | 本次返回的消息内容 |
| `is_bot` | `boolean` | 是否为机器人消息 |
| `chat_id` | `string` | 会话 ID |
| `flow_id` | `string` | 应用 ID；日常会话为空字符串 |
| `final` | `boolean` | 是否为最后一个事件 |
| `conversation.conversationId` | `string` | 最终事件返回的会话 ID |

#### 返回示例

```text
event: message
data: {"category":"agent_answer","type":"stream","message":{"msg":"部分回答"},"is_bot":true,"chat_id":"chat-001","flow_id":""}

data: {"final":true,"conversation":{"conversationId":"chat-001"}}


```

<a id="daily-chat-04"></a>

### `GET /api/v2/chat/list`

**接口用途：查询会话列表。**

仅返回属于当前 API 主体的日常会话。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/chat/list` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `chat:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `page` | `integer` | 否 | `1` | 页码 |
| query | `limit` | `integer` | 否 | `10` | 每页数量 |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/chat/list" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `array<ChatListItem>` | 当前主体的会话列表 |
| `data[].name` | `string / null` | 会话名称 |
| `data[].flow_name` | `string / null` | 应用名称 |
| `data[].flow_description` | `string / null` | 应用说明 |
| `data[].flow_id` | `string / null` | 应用 ID |
| `data[].chat_id` | `string / null` | 会话 ID |
| `data[].create_time` | `string(date-time) / null` | 创建时间 |
| `data[].update_time` | `string(date-time) / null` | 更新时间 |
| `data[].flow_type` | `integer / null` | 会话所属应用类型 |
| `data[].latest_message` | `ChatMessageSummary / null` | 最近一条消息 |
| `data[].latest_message.id` | `integer / null` | 消息 ID |
| `data[].latest_message.is_bot` | `boolean` | 是否为机器人消息 |
| `data[].latest_message.message` | `string / null` | 消息正文或序列化后的消息数据 |
| `data[].latest_message.type` | `string` | 消息类型 |
| `data[].latest_message.category` | `string` | 消息分类 |
| `data[].latest_message.chat_id` | `string / null` | 会话 ID |
| `data[].latest_message.create_time` | `string(date-time) / null` | 创建时间 |
| `data[].logo` | `string / null` | 应用图标地址 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": [
    {
      "name": "合同总结",
      "flow_name": "日常对话",
      "flow_id": "",
      "chat_id": "chat-001",
      "flow_type": 20,
      "latest_message": {
        "id": 9001,
        "is_bot": true,
        "message": "最近一条回答"
      }
    }
  ]
}
```

<a id="daily-chat-05"></a>

### `GET /api/v2/chat/info`

**接口用途：查询会话详情。**

资源不存在或不属于当前 API 主体时均返回 404。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/chat/info` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `chat:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `chat_id` | `string` | 是 | `—` | 会话 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/chat/info?chat_id=chat-001" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `ChatInfo / null` | 会话详情 |
| `data.chat_id` | `string` | 会话 ID |
| `data.name` | `string / null` | 会话名称 |
| `data.flow_id` | `string` | 应用 ID |
| `data.flow_type` | `integer` | 应用类型 |
| `data.flow_name` | `string / null` | 应用名称 |
| `data.flow_description` | `string / null` | 应用说明 |
| `data.flow_logo` | `string / null` | 应用图标地址 |
| `data.user_id` | `integer` | 兼容存储的自然人用户 ID |
| `data.tenant_id` | `integer / null` | 租户 ID |
| `data.is_delete` | `boolean / null` | 会话是否已删除 |
| `data.create_time` | `string(date-time) / null` | 创建时间 |
| `data.update_time` | `string(date-time) / null` | 更新时间 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "chat_id": "chat-001",
    "name": "合同总结",
    "flow_id": "",
    "flow_type": 20,
    "user_id": 1001
  }
}
```

<a id="workflow"></a>

## 工作流

共 **4 个接口**（HTTP 3 个，WebSocket 1 个）。包括工作流详情、执行、停止和 WebSocket 对话。WebSocket 已纳入本类数量。

| 功能组 | 接口用途 | 方法 | 路径 | 权限位 |
|---|---|---|---|---|
| 详情 | [查询工作流详情](#workflow-01) | GET | `/api/v2/flows/{flow_id}` | `workflow:read` |
| 调用 | [执行工作流](#workflow-02) | POST | `/api/v2/workflow/invoke` | `workflow:invoke` |
| 调用 | [停止工作流](#workflow-03) | POST | `/api/v2/workflow/stop` | `workflow:invoke` |
| WebSocket | [工作流交互连接](#workflow-04) | WS | `/api/v2/workflow/chat/{workflow_id}` | `workflow:invoke` |

<a id="workflow-01"></a>

### `GET /api/v2/flows/{flow_id}`

**接口用途：查询工作流详情。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/flows/{flow_id}` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `workflow:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `flow_id` | `string(uuid)` | 是 | `—` | 工作流 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/flows/22222222-2222-2222-2222-222222222222" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `FlowDetail` | 工作流详情 |
| `data.id` | `string(uuid)` | 工作流 ID |
| `data.name` | `string` | 工作流名称 |
| `data.description` | `string / null` | 工作流说明 |
| `data.logo` | `string / null` | 图标地址 |
| `data.status` | `integer / null` | 上线状态 |
| `data.flow_type` | `integer / null` | 应用类型 |
| `data.data` | `object` | 工作流节点与连线配置 |
| `data.can_share` | `boolean` | 当前主体是否可分享 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "合同审查",
    "data": {
      "nodes": [],
      "edges": []
    },
    "can_share": false
  }
}
```

<a id="workflow-02"></a>

### `POST /api/v2/workflow/invoke`

**接口用途：执行工作流。**

首次调用时不传 session_id；工作流等待输入时，使用原 session_id 并同时提交 input 和 message_id。stream=true 返回 SSE。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/workflow/invoke` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `workflow:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `workflow_id` | `string(uuid)` | 是 | `—` | 工作流 ID |
| `override` | `object / null` | 否 | `—` | 要覆盖的工作流节点参数 |
| `stream` | `boolean / null` | 否 | `True` | 是否返回流式响应 |
| `message_id` | `integer / null` | 否 | `—` | 消息 ID |
| `session_id` | `string / null` | 否 | `—` | 工作流会话 ID |
| `input` | `object / null` | 否 | `—` | 工作流等待输入时提交的数据 |

#### 请求 JSON 示例

```json
{
  "workflow_id": "22222222-2222-2222-2222-222222222222",
  "override": null,
  "stream": false,
  "input": null,
  "message_id": null,
  "session_id": null
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/workflow/invoke" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"workflow_id":"22222222-2222-2222-2222-222222222222","override":null,"stream":false,"input":null,"message_id":null,"session_id":null}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `WorkflowInvokeData` | 非流式工作流执行结果 |
| `data.session_id` | `string` | 本次工作流执行的会话标识 |
| `data.events` | `array<WorkflowEvent>` | 非流式调用累计得到的事件 |
| `data.events[].event` | `string` | 事件类型 |
| `data.events[].message_id` | `string / null` | 消息 ID |
| `data.events[].status` | `string / null` | 事件状态 |
| `data.events[].node_id` | `string / null` | 节点 ID |
| `data.events[].node_name` | `string / null` | 节点名称 |
| `data.events[].node_execution_id` | `string / null` | 节点执行 ID |
| `data.events[].output_schema` | `object / null` | 节点输出 |
| `data.events[].input_schema` | `object / null` | 等待用户输入时的输入定义 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "session_id": "chat001_async_task_id",
    "events": [
      {
        "event": "output_msg",
        "status": "end",
        "output_schema": {
          "message": "执行完成"
        }
      }
    ]
  }
}
```

响应类型：`text/event-stream`。

#### 返回字段

每个 SSE `data:` 后面都是一段 JSON：

| 字段 | 类型 | 说明 |
|---|---|---|
| `event` | `string` | 工作流事件类型 |
| `status` | `string` | 事件状态，例如 start、stream、end、error |
| `message_id` | `string / null` | 消息 ID |
| `node_id` | `string / null` | 工作流节点 ID |
| `node_name` | `string / null` | 工作流节点名称 |
| `node_execution_id` | `string / null` | 节点本次执行 ID |
| `output_schema` | `object` | 节点输出内容 |
| `result` | `object / null` | 事件附带的其他结果 |
| `session_id` | `string` | 本次工作流会话 ID |

#### 返回示例

```text
data: {"session_id":"chat001_async_task_id","data":{"event":"output_msg","status":"end","output_schema":{"message":"执行完成"}}}


```

<a id="workflow-03"></a>

### `POST /api/v2/workflow/stop`

**接口用途：停止工作流。**

只允许停止属于当前执行主体的工作流会话。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/workflow/stop` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `workflow:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `workflow_id` | `string(uuid)` | 是 | `—` | 工作流 ID |
| `session_id` | `string` | 是 | `—` | 工作流会话 ID |

#### 请求 JSON 示例

```json
{
  "workflow_id": "22222222-2222-2222-2222-222222222222",
  "session_id": "chat001_async_task_id"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/workflow/stop" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"workflow_id":"22222222-2222-2222-2222-222222222222","session_id":"chat001_async_task_id"}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `null` | 成功时固定为 null |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

<a id="workflow-04"></a>

### `WS /api/v2/workflow/chat/{workflow_id}`

**接口用途：工作流交互连接。**

| 项目 | 说明 |
|---|---|
| URL | `ws://<host>/api/v2/workflow/chat/{workflow_id}?chat_id=<chat_id>` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 可选身份头 | `X-On-Behalf-Of` 或 `X-End-User`，二选一 |
| 权限位 | `workflow:invoke` |
| path 参数 | `workflow_id`：工作流 UUID |
| query 参数 | `chat_id`：会话 ID，可选 |

连接示例：

```bash
websocat -H='Authorization: Bearer <API_KEY>' \
  'ws://localhost:7860/api/v2/workflow/chat/22222222-2222-2222-2222-222222222222?chat_id=chat-001'
```

初始化消息：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `action` | string | 是 | 初始化动作，固定为 `init_data` |
| `chat_id` | string | 否 | 会话 ID；新会话可以不传 |
| `flow_id` | string | 是 | 工作流 ID，应与 URL 中的 `workflow_id` 一致 |
| `data` | object | 是 | 工作流节点和连线配置 |

```json
{
  "action": "init_data",
  "chat_id": "chat-001",
  "flow_id": "22222222-2222-2222-2222-222222222222",
  "data": {
    "nodes": [],
    "edges": []
  }
}
```

返回字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | string | 消息类别 |
| `type` | string | 消息阶段，常见值为 `start`、`stream`、`end`、`over`、`close`、`error` |
| `message` | object / string | 消息内容 |
| `is_bot` | boolean | 是否为机器人消息 |
| `chat_id` | string | 会话 ID |
| `flow_id` | string | 工作流 ID |
| `message_id` | string / null | 消息 ID |

返回示例：

```json
{
  "category": "answer",
  "type": "stream",
  "message": "部分输出",
  "is_bot": true,
  "chat_id": "chat-001",
  "flow_id": "22222222-2222-2222-2222-222222222222"
}
```

<a id="assistant"></a>

## 助手

共 **6 个接口**（HTTP 5 个，WebSocket 1 个）。包括知识助手列表、详情、对话、WebSocket 连接和语音能力。ASR/TTS 均使用 assistant:invoke 权限位。

| 功能组 | 接口用途 | 方法 | 路径 | 权限位 |
|---|---|---|---|---|
| 查询 | [查询助手列表](#assistant-01) | GET | `/api/v2/assistant/list` | `assistant:read` |
| 查询 | [查询助手详情](#assistant-02) | GET | `/api/v2/assistant/info/{assistant_id}` | `assistant:read` |
| 对话 | [调用助手对话](#assistant-03) | POST | `/api/v2/assistant/chat/completions` | `assistant:invoke` |
| WebSocket | [助手交互连接](#assistant-04) | WS | `/api/v2/assistant/chat/{assistant_id}` | `assistant:invoke` |
| 语音 | [语音转文字](#assistant-05) | POST | `/api/v2/llm/workbench/asr` | `assistant:invoke` |
| 语音 | [文字转语音](#assistant-06) | POST | `/api/v2/llm/workbench/tts` | `assistant:invoke` |

<a id="assistant-01"></a>

### `GET /api/v2/assistant/list`

**接口用途：查询助手列表。**

查询知识助手列表。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/assistant/list` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `assistant:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| query | `name` | `string` | 否 | `—` | 名称 |
| query | `tag_id` | `integer` | 否 | `—` | 标签 ID |
| query | `page` | `integer / null` | 否 | `1` | 页码 |
| query | `limit` | `integer / null` | 否 | `10` | 每页数量 |
| query | `status` | `integer / null` | 否 | `—` | 状态筛选 |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/assistant/list" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `AssistantPageData` | 知识助手分页结果 |
| `data.data` | `array<AssistantSummary>` | 本页知识助手 |
| `data.data[].id` | `string(uuid)` | 知识助手 ID |
| `data.data[].name` | `string` | 知识助手名称 |
| `data.data[].desc` | `string / null` | 知识助手说明 |
| `data.data[].logo` | `string / null` | 图标地址 |
| `data.data[].status` | `integer / null` | 上线状态 |
| `data.data[].write` | `boolean / null` | 当前主体是否可编辑 |
| `data.data[].tags` | `array<object> / null` | 标签 |
| `data.total` | `integer` | 符合条件的总数 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "制度助手"
      }
    ],
    "total": 1
  }
}
```

<a id="assistant-02"></a>

### `GET /api/v2/assistant/info/{assistant_id}`

**接口用途：查询助手详情。**

查询知识助手详情。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/assistant/info/{assistant_id}` |
| 请求方式 | `GET` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `assistant:read` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| path | `assistant_id` | `string(uuid)` | 是 | `—` | 知识助手 ID |
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

#### 请求示例

```bash
curl -X GET "$BISHENG_API_BASE/api/v2/assistant/info/123" \
  -H "Authorization: Bearer $BISHENG_API_KEY"
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `AssistantInfo` | 知识助手详情 |
| `data.id` | `string(uuid)` | 知识助手 ID |
| `data.name` | `string` | 知识助手名称 |
| `data.desc` | `string / null` | 知识助手说明 |
| `data.logo` | `string / null` | 图标地址 |
| `data.status` | `integer / null` | 上线状态 |
| `data.temperature` | `number / null` | 模型温度 |
| `data.tool_list` | `array<object>` | 助手关联工具 |
| `data.flow_list` | `array<object>` | 助手关联工作流 |
| `data.knowledge_list` | `array<object>` | 助手关联知识库 |
| `data.can_share` | `boolean` | 当前主体是否可分享 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "制度助手",
    "tool_list": [],
    "flow_list": [],
    "knowledge_list": [],
    "can_share": false
  }
}
```

<a id="assistant-03"></a>

### `POST /api/v2/assistant/chat/completions`

**接口用途：调用助手对话。**

model 字段填写知识助手 ID。stream=false 返回 JSON，stream=true 返回 SSE 并以 data: [DONE] 结束。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/assistant/chat/completions` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `assistant:invoke` |
| 身份模式 | `S/D` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `messages` | `array<object>` | 是 | `—` | 对话消息列表 |
| `model` | `string` | 是 | `—` | 知识助手 ID 或模型 ID，具体含义见接口说明 |
| `n` | `integer` | 否 | `1` | 候选答案数量；当前只支持 1 |
| `stream` | `boolean` | 否 | `False` | 是否返回流式响应 |
| `temperature` | `number` | 否 | `0.0` | 模型温度；0 表示使用原配置 |
| `tools` | `array<object>` | 否 | `—` | 工具列表 |

#### 请求 JSON 示例

```json
{
  "model": "11111111-1111-1111-1111-111111111111",
  "messages": [
    {
      "role": "user",
      "content": "请介绍一下报销制度"
    }
  ],
  "stream": false,
  "temperature": 0
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/assistant/chat/completions" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"model":"11111111-1111-1111-1111-111111111111","messages":[{"role":"user","content":"请介绍一下报销制度"}],"stream":false,"temperature":0}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `string` | 请求 ID |
| `object` | `string` | 响应对象类型 |
| `created` | `integer` | Unix 时间戳 |
| `model` | `string` | 知识助手 ID |
| `choices` | `array<OpenAIChoiceResponse>` | 候选答案 |
| `choices[].index` | `integer` | 候选答案序号 |
| `choices[].message` | `object / null` | 非流式回答 |
| `choices[].finish_reason` | `string / null` | 结束原因 |
| `choices[].delta` | `object / null` | 流式增量 |
| `usage` | `object / null` | Token 用量；当前可能为 null |
| `system_fingerprint` | `string / null` | 系统指纹；当前可能为 null |

#### 返回示例

```json
{
  "id": "chatcmpl-001",
  "object": "chat.completion",
  "created": 1788480000,
  "model": "11111111-1111-1111-1111-111111111111",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "回答内容"
      },
      "finish_reason": "stop",
      "delta": null
    }
  ],
  "usage": null,
  "system_fingerprint": null
}
```

响应类型：`text/event-stream`。

#### 返回字段

每个 SSE `data:` 后面都是一段 JSON：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `string` | 本次生成 ID |
| `object` | `string` | 事件类型，流式响应通常为 chat.completion.chunk |
| `created` | `integer` | 事件创建时间戳 |
| `model` | `string` | 实际使用的知识助手 ID |
| `choices` | `array` | 本次返回的候选结果 |
| `choices[].index` | `integer` | 候选结果序号 |
| `choices[].delta.content` | `string` | 本次增量输出的文字 |
| `choices[].finish_reason` | `string / null` | 结束原因；生成中为 null |

#### 返回示例

```text
data: {"id":"chatcmpl-001","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"回答"}}]}

data: [DONE]


```

<a id="assistant-04"></a>

### `WS /api/v2/assistant/chat/{assistant_id}`

**接口用途：助手交互连接。**

| 项目 | 说明 |
|---|---|
| URL | `ws://<host>/api/v2/assistant/chat/{assistant_id}?chat_id=<chat_id>` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 可选身份头 | `X-On-Behalf-Of` 或 `X-End-User`，二选一 |
| 权限位 | `assistant:invoke` |
| path 参数 | `assistant_id`：知识助手 UUID |
| query 参数 | `chat_id`：会话 ID，可选 |

连接示例：

```bash
websocat -H='Authorization: Bearer <API_KEY>' \
  'ws://localhost:7860/api/v2/assistant/chat/11111111-1111-1111-1111-111111111111?chat_id=chat-001'
```

初始化消息：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `chatHistory` | array | 是 | 对话历史；新会话传空数组 |
| `chat_id` | string | 否 | 会话 ID；新会话可以不传 |
| `flow_id` | string | 是 | 知识助手 ID，应与 URL 中的 `assistant_id` 一致 |
| `inputs` | object | 是 | 知识助手运行参数 |
| `inputs.data.id` | string | 是 | 知识助手 ID |
| `inputs.data.chatId` | string | 否 | 会话 ID |
| `inputs.data.type` | integer | 是 | 应用类型，知识助手为 5 |
| `name` | string | 否 | 知识助手名称 |
| `description` | string | 否 | 知识助手说明 |

```json
{
  "chatHistory": [],
  "chat_id": "chat-001",
  "flow_id": "11111111-1111-1111-1111-111111111111",
  "inputs": {
    "data": {
      "id": "11111111-1111-1111-1111-111111111111",
      "chatId": "chat-001",
      "type": 5
    }
  },
  "name": "制度助手",
  "description": "制度问答"
}
```

返回字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | string | 消息类别 |
| `type` | string | 消息阶段，常见值为 `start`、`stream`、`end`、`over`、`close`、`error` |
| `message` | object / string | 消息内容 |
| `is_bot` | boolean | 是否为机器人消息 |
| `chat_id` | string | 会话 ID |
| `flow_id` | string | 知识助手 ID |
| `message_id` | string / null | 消息 ID |

返回示例：

```json
{
  "category": "answer",
  "type": "end",
  "message": "完整回答",
  "is_bot": true,
  "chat_id": "chat-001",
  "flow_id": "11111111-1111-1111-1111-111111111111"
}
```

<a id="assistant-05"></a>

### `POST /api/v2/llm/workbench/asr`

**接口用途：语音转文字。**

音频转文字。

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/llm/workbench/asr` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `assistant:invoke` |
| 身份模式 | `S` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`multipart/form-data`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `file` | `string(binary)` | 否 | `—` | 上传文件 |

#### 表单字段 JSON 示例

下面的 JSON 用于说明表单字段及其填写值。实际请求使用 `multipart/form-data`；`file` 的示例值是本地文件路径，发送时需上传该文件的二进制内容。请使用下方的 `curl -F` 示例。

```json
{
  "file": "/path/to/audio.wav"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/llm/workbench/asr" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -F 'file=@/path/to/audio.wav'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `string` | 接口返回的字符串结果 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": "示例结果"
}
```

<a id="assistant-06"></a>

### `POST /api/v2/llm/workbench/tts`

**接口用途：文字转语音。**

#### 基本信息

| 项目 | 值 |
|---|---|
| URL | `/api/v2/llm/workbench/tts` |
| 请求方式 | `POST` |
| 鉴权头 | `Authorization: Bearer <API_KEY>`，必填 |
| 权限位 | `assistant:invoke` |
| 身份模式 | `S` |

#### 请求参数

| 位置 | 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| header | `X-On-Behalf-Of` | `string` | 否 | `—` | 可选。代表指定平台用户执行。不能与 X-End-User 同时传；使用前必须给密钥配置委托权限和委托范围。 |
| header | `X-End-User` | `string` | 否 | `—` | 可选。S 模式下区分外部使用者，不改变权限主体。不能与 X-On-Behalf-Of 同时传。 |

请求体类型：`application/json`。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `text` | `string` | 是 | `—` | 要合成的文字 |

#### 请求 JSON 示例

```json
{
  "text": "需要合成的文字"
}
```

#### 请求示例

```bash
curl -X POST "$BISHENG_API_BASE/api/v2/llm/workbench/tts" \
  -H "Authorization: Bearer $BISHENG_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"text":"需要合成的文字"}'
```

#### 成功响应

HTTP 状态：`200`。

响应类型：`application/json`。

#### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | `integer` | 业务状态码；成功固定为 200 |
| `status_message` | `string` | 状态说明 |
| `data` | `string` | 接口返回的字符串结果 |

#### 返回示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": "示例结果"
}
```
