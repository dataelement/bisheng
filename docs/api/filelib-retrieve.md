# 知识库纯检索接口 (Filelib Retrieve)

`POST /api/v2/filelib/retrieve`

跨一个或多个知识库返回 top-k chunks，**不**调用 LLM 生成回答。面向外部检索集成场景（自带 LLM 的 agent、Deep Research 工作流、第三方 RAG 编排器），是 BiSheng 工作台「日常模式 + 知识库检索」中检索阶段的 HTTP 化暴露。

---

## 1. 适用场景

| 场景 | 是否合适 |
|---|---|
| 外部 agent 用自己的 LLM 生成答案，需要 BiSheng 的检索能力 | ✅ |
| Deep Research / DeepAgents 类多源检索拼接 | ✅ |
| 自建 RAG 流水线接 BiSheng 知识库当 retriever | ✅ |
| 普通用户聊天问答 | ❌ 用 `POST /api/v1/knowledge/space/{space_id}/chat/folder`（SSE 流式 RAG） |

---

## 2. 认证与业务用户

接口要求 `X-Developer-Token`。Developer Token 先验证调用资格，包括 Token 状态、绑定关系、IP、路由白名单和限流；Token 失败时不会解析业务用户或执行检索。

- Body 未传 `external_id`：使用 Token 绑定用户的权限和作用域。
- Body 传入 `external_id`：全局精确解析唯一有效用户，并使用该用户的完整权限执行检索。
- `external_id` 不存在、禁用或重复时统一返回 HTTP `403`；空白或超过 255 个字符返回 HTTP `422`。
- 知识空间和文件仍经过现有 `view_file` 可见性过滤。

本契约仅适用于当前未启用租户功能的部署。启用多租户前必须重新评审 Token、目标用户、数据作用域和原文件对象路径。

---

## 3. 请求

### 3.1 Header

```
Content-Type: application/json
X-Developer-Token: bst_{REDACTED}
```

### 3.2 Body

```json
{
  "external_id": "EMP001",
  "query": "string",
  "knowledge_base_ids": [1, 2],
  "filters": {
    "knowledge_base_filters": [
      {
        "knowledge_base_id": 1,
        "tags": ["tag-name-1", "tag-name-2"],
        "tag_match_mode": "ANY"
      }
    ]
  },
  "top_k": 10,
  "max_content": 15000
}
```

### 3.3 字段说明

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `external_id` | string | ❌ | null | 业务用户外部标识；未传时使用 Token 绑定用户，最大 255 个字符。 |
| `query` | string | ✅ | — | 用户问题。最小长度 1。 |
| `knowledge_base_ids` | int[] | ✅ | — | 要检索的知识库 ID 列表（即 BiSheng 内部的 knowledge space id），至少 1 个。 |
| `filters` | object | ❌ | null | 检索过滤器，目前仅支持按知识库分别配置 tag 过滤。 |
| `filters.knowledge_base_filters` | array | ❌ | `[]` | 每个 entry 配置一个 KB 的过滤条件。 |
| `filters.knowledge_base_filters[].knowledge_base_id` | int | ✅ | — | 必须出现在 `knowledge_base_ids` 中，否则 400。 |
| `filters.knowledge_base_filters[].tags` | string[] | ✅ | — | 标签名（**不是** tag id）。标签作用域是单个 KB（business_type=knowledge_space, business_id=该 KB 的 id）。 |
| `filters.knowledge_base_filters[].tag_match_mode` | enum | ❌ | `"ANY"` | 枚举：`"ANY"` 或 `"ALL"`。**目前只支持 ANY**，传 `"ALL"` 返回 400。 |
| `top_k` | int | ❌ | 10 | 最终返回的 chunk 数量上限，跨所有 KB 合并后再截断。范围 `[1, 200]`。 |
| `max_content` | int | ❌ | 15000 | 单个 KB 内合并文本的字符上限（影响检索阶段返回的最大 chunk 数），传递给底层 retriever。范围 `>=1`。 |

### 3.4 字段语义补充

#### `knowledge_base_ids` vs `filters.knowledge_base_filters`

- `knowledge_base_ids` 定义检索范围（哪些 KB 参与）。
- `filters.knowledge_base_filters` 定义筛选条件（参与的 KB 各自怎么筛）。
- **没在 `knowledge_base_filters` 中出现的 KB，按整库检索**（不施加 tag 过滤）。
- 在 `knowledge_base_filters` 中出现但 `tags` 解析后无匹配文件，该 KB 直接返回 0 chunks，不影响其他 KB。

#### `tag_match_mode`

- `"ANY"`（默认）：文件命中**任意一个**标签即纳入。
- `"ALL"`：文件必须**同时**带上全部标签——**暂未实现，传此值返回 400**。后续版本会补齐。

#### `max_content` 的工作机制

由底层 `KnowledgeRetrieverTool` 在 RRF 合并后按字符总长度截断。这是**单 KB 内**的限制，多 KB 调用每个库独立应用此上限。最终再用 `top_k` 全局截断。

---

## 4. 响应

### 4.1 成功响应（HTTP 200）

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "chunks": [
      {
        "content": "...chunk 文本内容...",
        "knowledge_id": 1,
        "document_id": 123,
        "document_name": "产品手册.pdf",
        "chunk_index": 5,
        "source_url": "/bisheng/original/123.pdf?X-Amz-Expires=604800&X-Amz-Signature=REDACTED",
        "source_full_url": "https://files.example.com/bisheng/original/123.pdf?X-Amz-Expires=604800&X-Amz-Signature=REDACTED"
      },
      {
        "content": "...",
        "knowledge_id": 2,
        "document_id": 456,
        "document_name": "API 说明.md",
        "chunk_index": 0,
        "source_url": "",
        "source_full_url": ""
      }
    ],
    "total": 2
  }
}
```

### 4.2 chunk 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string | chunk 原文。可能含 markdown 图片标记（`![](path/IMAGE_X.png)`），渲染时建议保留。 |
| `knowledge_id` | int | 该 chunk 来源的知识库 ID。多 KB 调用下用于区分来源。 |
| `document_id` | int | 文档（文件）ID，在 BiSheng 内对应 `KnowledgeFile.id`。 |
| `document_name` | string | 文档名称（含扩展名）。 |
| `chunk_index` | int | chunk 在文档内的顺序号，从 0 开始。 |
| `source_url` | string | 原文件预签名 URL 的相对路径和查询串。调用方需拼接正确的文件访问 Origin；原对象缺失时为空。 |
| `source_full_url` | string | 同一原文件的绝对 GET 预签名 URL，可直接访问且无需 Developer Token；原对象缺失时为空。 |

两个 URL 来自同一次签名，有效期固定为签发后 7 天。同一响应内，同一 `document_id` 的多个 Chunk 复用同一对 URL；不同请求可能获得不同签名。

链接签发只依赖检索阶段已经通过的 `view_file` 可见性结果，不额外检查 `download_file`，也不进入门户下载额度、审计、水印、审批或分发限制链路。文件记录或原对象缺失不会删除 Chunk，只会返回两个空字符串；MinIO 的其他异常会使整个请求失败。

> 预签名 URL 是 7 天内有效的 Bearer 凭证，不能通过撤销用户权限或禁用 Developer Token 提前失效。不得把完整 URL 写入日志、监控、埋点或第三方分析系统。

### 4.3 顶层包装字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.chunks` | array | 检索到的 chunks，按 KB 顺序拼接后取 `top_k` 截断。**单库内**按 RRF 相关度排序；**跨库间**按 `knowledge_base_ids` 入参的顺序串接。 |
| `data.total` | int | 实际返回的 chunks 数量（≤ `top_k`）。 |
| `status_code` | int | 200 表示成功；非 200 见错误码表。 |
| `status_message` | string | 状态描述。 |

> 注意：当前版本不返回相关度 `score`。如下游需要重排/二次过滤，建议依赖返回顺序（同一 KB 内已按 RRF 排序）。

---

## 5. 错误响应

### 5.1 HTTP 400 Bad Request

请求语义错误，常见原因：

| 触发条件 | `detail` 字段示例 |
|---|---|
| `knowledge_base_ids` 为空 | `"knowledge_base_ids must not be empty"` |
| 过滤器引用了不在 `knowledge_base_ids` 中的 KB | `"filter references kb_id 99 not present in knowledge_base_ids"` |
| `tag_match_mode` 传了 `"ALL"` | `"tag_match_mode=ALL is not yet supported"` |
| 字段类型校验失败（FastAPI 自动校验） | `"validation error"` 嵌套结构 |

```json
{
  "detail": "tag_match_mode=ALL is not yet supported"
}
```

### 5.2 业务错误（HTTP 200 + 错误 status_code）

BiSheng 沿用了「HTTP 200 + body 内 status_code」的统一响应模型用于业务错误：

| `status_code` | 含义 | 何时触发 |
|---|---|---|
| 404 | 知识库不存在 | `knowledge_base_ids` 中某个 ID 在数据库中查不到 |
| 403 | 业务用户无权或 `external_id` 解析失败 | 知识空间/文件权限检查不通过，或外部用户不存在、禁用、重复 |
| 500 | 服务器内部错误 | 向量库、ES、embedding 或 MinIO 连接/认证/签名异常等 |

```json
{
  "status_code": 404,
  "status_message": "Knowledge base 99 not found",
  "data": {
    "exception": "..."
  }
}
```

> ⚠️ 调用方应同时检查 HTTP status 和 body 内的 `status_code` 字段。

---

## 6. 调用示例

### 6.1 单 KB，整库检索

```bash
curl -X POST 'http://bisheng-host:7860/api/v2/filelib/retrieve' \
  -H 'Content-Type: application/json' \
  -H 'X-Developer-Token: bst_{REDACTED}' \
  -d '{
    "external_id": "EMP001",
    "query": "如何配置 SSO 登录?",
    "knowledge_base_ids": [1],
    "top_k": 5
  }'
```

### 6.2 多 KB，部分库带 tag 过滤

```bash
curl -X POST 'http://bisheng-host:7860/api/v2/filelib/retrieve' \
  -H 'Content-Type: application/json' \
  -H 'X-Developer-Token: bst_{REDACTED}' \
  -d '{
    "external_id": "EMP001",
    "query": "审批流程的常见问题",
    "knowledge_base_ids": [1, 2, 3],
    "filters": {
      "knowledge_base_filters": [
        {
          "knowledge_base_id": 1,
          "tags": ["approval", "faq"],
          "tag_match_mode": "ANY"
        }
      ]
    },
    "top_k": 20,
    "max_content": 12000
  }'
```

上例语义：
- KB 1 限定带 `approval` 或 `faq` 标签的文件。
- KB 2、KB 3 整库检索（未在 filters 中出现）。
- 三库各自检索后合并，取前 20 个 chunks。

### 6.3 Python (httpx)

```python
import httpx

resp = httpx.post(
    "http://bisheng-host:7860/api/v2/filelib/retrieve",
    headers={"X-Developer-Token": "bst_{REDACTED}"},
    json={
        "external_id": "EMP001",
        "query": "How do I configure tenant isolation?",
        "knowledge_base_ids": [1, 2],
        "top_k": 8,
    },
    timeout=30.0,
)
body = resp.json()
assert body["status_code"] == 200
for chunk in body["data"]["chunks"]:
    print(f"[KB={chunk['knowledge_id']} doc={chunk['document_name']}] {chunk['content'][:80]}")
```

### 6.4 LangChain Tool 包装（参考）

```python
from langchain_core.tools import tool
import httpx

@tool
def bisheng_retrieve(query: str, knowledge_base_ids: list[int], top_k: int = 10) -> list[dict]:
    """Retrieve top-k chunks from BiSheng knowledge bases without LLM generation."""
    resp = httpx.post(
        "http://bisheng-host:7860/api/v2/filelib/retrieve",
        headers={"X-Developer-Token": "bst_{REDACTED}"},
        json={"query": query, "knowledge_base_ids": knowledge_base_ids, "top_k": top_k},
        timeout=30.0,
    )
    body = resp.json()
    if body.get("status_code") != 200:
        raise RuntimeError(f"BiSheng retrieve failed: {body.get('status_message')}")
    return body["data"]["chunks"]
```

---

## 7. 行为细节与边界

### 7.1 检索流程（内部实现）

每个 KB 独立执行以下流程，最终结果合并：

1. 身份解析：Developer Token 校验成功后，按可选 `external_id` 确定 F069 业务用户。
2. 权限校验：业务用户是否对该 KB 和候选文件具有 `view_file` 权限。
3. 解析过滤：tag 名（如有）→ tag id → file id 列表。无对应文件时该 KB 返回空。
4. 构建过滤器：file id 列表 + 主版本过滤（排除已废弃的文档版本）→ Milvus expr + ES filter。
5. 双路召回：Milvus 向量检索 + Elasticsearch 全文检索，各取 top 100。
6. RRF 合并：两路结果按 Reciprocal Rank Fusion 融合排序。
7. `max_content` 截断：从前往后累加 chunk 文本长度，超过阈值截断。
8. 多库合并、跨库去重并执行 `top_k` 截断。
9. 对最终 Chunk 的唯一文件批量读取原对象，每个文件签发一次 7 天绝对 URL 并派生相对 URL。

多 KB 间：使用 `asyncio.gather` 并发执行，按 `knowledge_base_ids` 顺序合并，最后 `top_k` 截断。

### 7.2 性能注意

- 单 KB 检索延迟约等于一次 Milvus query + 一次 ES query 的串行最大值。
- 多 KB 是并发的，所以延迟不显著叠加。
- `max_content` 不影响检索阶段的 candidate 数量（始终是 top 100），只决定最终保留的 chunk 数。
- `top_k` 大时建议同步调大 `max_content`，否则可能在 `max_content` 截断后就已经少于 `top_k` 个 chunk。

### 7.3 多租户

- 当前 `external_id` 全局业务用户上下文和原文件签名契约只允许在未启用租户功能的部署使用。
- 若启用多租户，必须先更新 F069/F084 规格并重新验证资源过滤和 MinIO 对象前缀，不能直接沿用当前全局作用域。

### 7.4 文档版本

- 自动只检索「主版本」(`is_primary=true`) 的文档；废弃版本不会出现在结果里。
- 这与 `/api/v1/.../chat/folder` 行为一致。

### 7.5 标签作用域

- BiSheng 的标签按 `(business_type, business_id)` 划分作用域。
- 本接口的 tag 在 `business_type=knowledge_space, business_id=<knowledge_base_id>` 的空间下查找。
- 同名标签在不同 KB 下是不同记录——传 tag 名时不会跨 KB 混淆。

### 7.6 空结果

下列情况都返回 HTTP 200 + 空 `chunks` 数组（不算错误）：

- 知识库为空、检索词无任何召回。
- tag 过滤后命中 0 个文件。
- 所有候选文件都是非主版本（被版本过滤剔除）。

### 7.7 原文件链接安全边界

- 只有最终进入响应的可见 Chunk 才会触发原文件链接解析；被权限过滤或 Top-K 截断的文件不会签发。
- 只有 `view_file`、没有 `download_file` 的业务用户也能通过本接口读取原文件，这是已确认的接口特例。
- 链接不应用门户下载额度、审计、水印、审批或分发限制。
- 原对象缺失返回空链接；网络、认证、服务端或签名异常不降级为成功。
- 已签发 URL 无单链接提前撤销能力，紧急处置只能移走/删除对象、轮换 MinIO 签名密钥或等待过期，并可能影响其他调用方。

---

## 8. 与现有接口的关系

| 接口 | 路径 | 区别 |
|---|---|---|
| 本接口 | `POST /api/v2/filelib/retrieve` | 纯检索，JSON 同步响应，Developer Token 验证调用资格，可选 `external_id` 决定业务用户 |
| 工作台 RAG | `POST /api/v1/knowledge/space/{id}/chat/folder` | 检索 + LLM 生成 + 会话落库，SSE 流式，用户 JWT |
| 知识库管理 | `POST /api/v2/filelib/...` 其他端点 | 同 namespace 下的上传/QA 管理 |

---

## 9. 版本与兼容性

- **当前状态**：v2.6.0 引入。后续版本会补齐 `tag_match_mode=ALL`、可选的 `score` 字段、`metadata` 透传开关。
- **向后兼容承诺**：现有字段（`query`、`knowledge_base_ids`、`filters`、`top_k`、`max_content`）的语义保持稳定；新增字段会以可选项加入。
- **响应包装**沿用 BiSheng 全局响应模型，`data` 结构在 minor 版本内保持兼容。

---

## 10. FAQ

**Q：能跨多个知识库返回结果时按全局相关度排序吗?**
A：当前实现按 KB 顺序串接，未做跨库 score 归一化。如下游对全局排序有强需求，可在调用前把同一类知识库分组、或在自己侧再做一次重排。

**Q：top_k 设置成 50 但只返回了 10 条，是 bug 吗?**
A：很可能是 `max_content` 提前截断了。调大 `max_content`，或检查知识库实际命中量。

**Q：能传 user_id 让接口以某个特定用户身份检索吗?**
A：当前不支持。如需多用户身份语义，需在调用层做。后续版本可能加 `as_user_id` 可选参数。

**Q：如何拿到 chunk 的 page、bbox、source 等元信息?**
A：当前响应不透传 metadata。后续版本会加可选的 `include_metadata` 开关。
