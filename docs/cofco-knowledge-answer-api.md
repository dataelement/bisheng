# 中粮知识空间检索问答接口文档

更新日期：2026-10-09 · 适用版本：中粮 909 定制线

## 1. 接口说明

根据问题检索指定知识空间中的相关内容，调用大模型总结，一次性返回文字答案与参考文件。

- 方法：`POST`
- 路径：`/api/v2/filelib/answer`
- 105 测试地址：`http://192.168.106.105:3001/api/v2/filelib/answer`
- 格式：JSON，非流式；不创建会话，不读取或保存对话历史。
- 仅支持知识空间（`type=3`），不支持文档知识库、QA 知识库。
- 是“相关片段检索后回答”，不是完整阅读空间内全部文件，也不是完整文件列表接口。

## 2. 鉴权与权限

| 请求头 | 必填 | 说明 |
|---|---|---|
| Authorization | 是 | `Bearer <OPEN_API_KEY>`，后台生成的开放 APIKey / 个人访问令牌 |
| Content-Type | 是 | `application/json` |

凭据必须具有 `knowledge:read` 权限。空间和文件权限、租户隔离、个人令牌数据范围与现有开放接口一致，不绕过权限。请求中的任一空间不可访问时，整体拒绝，不返回部分结果。

个人令牌以令牌持有人身份调用，无需委托请求头。服务账号如需身份委托，沿用平台已有 `X-On-Behalf-Of` 规则；不在请求体传 `user_id` 或 `tenant_id`。

密钥仅放在请求头，不放 URL、请求体、日志或本文档。生产环境建议使用 HTTPS。

## 3. 请求参数

| 字段 | 类型 | 必填 | 默认值 / 限制 |
|---|---|---|---|
| query | string | 是 | 问题；去除首尾空白后 1～4096 字符 |
| knowledge_base_ids | integer[] | 是 | 空间 ID；原始数组 1～20 项，ID 为正整数；重复 ID 自动去重 |
| model_id | integer | 是 | 正整数；当前租户工作台可选的已上线文本大模型 ID |
| top_k | integer | 否 | 默认 10，范围 1～50；最终参考片段数，不是文件数 |
| max_content | integer | 否 | 默认 15000，范围 1～60000；所有空间参考正文合计字符上限，不是 token 数 |
| filters | object | 否 | 各空间的标签筛选，见下文 |

`model_id` 没有默认值，也不会自动换模型。模型须在后台工作台可选清单中，且模型及供应商配置有效；启用了内置联网或工具能力的模型不支持本接口。

不支持 `stream`、`messages`、`conversation_id`、`system_prompt` 等参数；未知字段会被拒绝。

### 基本请求示例

以下空间 137、模型 20 已在 105 联测通过；其他环境需替换为实际可用 ID。

```json
{
  "query": "AWS Well-Architected Framework 包含哪些支柱？请根据知识空间资料简要列出。",
  "knowledge_base_ids": [137],
  "model_id": 20,
  "top_k": 5,
  "max_content": 10000
}
```

### 可选标签筛选

```json
{
  "query": "报销申请需要哪些材料？",
  "knowledge_base_ids": [137, 172],
  "model_id": 20,
  "filters": {
    "knowledge_base_filters": [
      {
        "knowledge_base_id": 137,
        "tags": ["财务", "制度"],
        "tag_match_mode": "ANY"
      }
    ]
  }
}
```

筛选项的空间必须包含在 `knowledge_base_ids` 中，每个空间最多配置一次。未配置筛选的空间不加标签限制。每个空间最多 20 个标签，每个标签去空白后 1～128 字符；重复标签自动去重。仅支持 `ANY`，即匹配所列标签中的任意一个；不支持 `ALL`。

多空间分别检索后，按空间轮流选取片段，并应用全局条数和字符预算；不是跨空间全局相关性重排。

## 4. 返回格式

### 有召回结果：HTTP 200

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "answer": "根据提供的文档，AWS Well-Architected Framework 包含以下六大支柱：\n\n- 卓越运营\n- 安全性\n- 可靠性\n- 性能效率\n- 成本优化\n- 可持续性",
    "has_context": true,
    "model_id": 20,
    "references": [
      {
        "knowledge_id": 137,
        "document_id": 975,
        "document_name": "1ae9a74119b4cbbd__wellarchitected-framework.pdf",
        "document_update_time": "2026-09-15 10:19:08"
      }
    ]
  }
}
```

| 返回字段 | 类型 | 说明 |
|---|---|---|
| status_code | integer | 业务状态码，200 表示成功；与 HTTP 状态码不是同一字段 |
| status_message | string | 状态说明 |
| data.answer | string | 总结后的文字答案，可能含 Markdown 文本；不返回图片、附件或推理过程 |
| data.has_context | boolean | 是否召回并保留了参考内容；true 不代表资料一定足够回答问题 |
| data.model_id | integer | 本次请求通过校验的模型 ID |
| data.references | object[] | 参与本次生成上下文的参考文件列表，按文件去重；不是空间的完整文件清单 |
| references[].knowledge_id | integer | 来源空间 ID |
| references[].document_id | integer | 来源文件 ID |
| references[].document_name | string | 文件名 |
| references[].document_update_time | string | 来源更新时间，缺失时为空字符串 |

来源列表由后端根据实际保留的检索内容生成，不由模型编造。不返回原始分块、文件下载地址或内部引用 ID。

### 无召回结果：HTTP 200

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "answer": "未找到相关内容",
    "has_context": false,
    "model_id": 20,
    "references": []
  }
}
```

无参考内容时不调用大模型生成，但仍校验空间权限和模型配置。有参考内容但依据不足时，模型应说明资料不足。

## 5. 错误处理

| HTTP 状态 | 业务码 | 说明 / 处理建议 |
|---|---|---|
| 400 | 400 | 参数错误，或模型不在工作台允许范围、启用了联网/工具；按错误说明修改请求或配置 |
| 400 | 26019 | 不允许在请求体覆盖调用身份 |
| 400 | 10962 | 传入非知识空间类型的资源 |
| 400 | 10009 / 10010 | 模型或供应商配置已删除，后台重新配置 |
| 400 | 10011 / 10012 | 模型类型不支持或模型已下线，选择有效文本大模型 |
| 401 | 26001 / 26002 | 凭据缺失、格式错误、撤销或过期，检查或重新生成开放 Key |
| 403 | 26003 | 凭据缺少所需权限位 |
| 403 | 26040 / 26043 / 26044 | 开放能力关闭、持有人状态异常或个人令牌数据范围受限；联系管理员 |
| 403 / 404 | 沿用平台原业务码 | 无空间/文件访问权限，或资源不存在、不可见；不通过更换猜测 ID 绕过 |
| 503 | 26030 | 权限/鉴权依赖暂不可用 |
| 502 | 10963 | 检索失败，检查索引、检索服务及嵌入模型 |
| 502 | 10964 | 模型初始化或生成失败，检查模型端点、Key、配额、上下文长度等 |
| 504 | 10965 | 问答编排或阶段超时 |
| 502 | 10966 | 模型返回空答案、工具调用或非文字结果 |

表列常见错误，不涵盖既有鉴权、限流和配额的全部错误。客户端应同时判断 HTTP 状态和响应中的业务码。

本接口新增错误示例（HTTP 502）：

```json
{
  "status_code": 10964,
  "status_message": "Knowledge answer generation failed",
  "data": null
}
```

既有平台错误的 `data` 可能包含错误详情对象，客户端不要假设所有错误都是 `data=null`。模型供应商认证失败会作为 10964 返回，不等于调用方开放 APIKey 失效。

## 6. 调用示例

把 `<OPEN_API_KEY>` 替换为后台生成的有效凭据；不要将替换后的命令或请求头写入共享日志。

```bash
curl --request POST \
  'http://192.168.106.105:3001/api/v2/filelib/answer' \
  --header 'Authorization: Bearer <OPEN_API_KEY>' \
  --header 'Content-Type: application/json' \
  --data '{"query":"AWS Well-Architected Framework 包含哪些支柱？","knowledge_base_ids":[137],"model_id":20,"top_k":5,"max_content":10000}'
```

空间 ID 可先调用 `GET /api/v2/filelib/?type=3&page_size=50` 获取；有更多页时按返回的 `next_cursor` 继续。列表为凭据可见的空间范围；部门空间沿用现有接口规则，可能不在此列表中。模型 ID 从后台工作台配置中的可用模型获取。

## 7. 超时与联测结果

服务编排总预算 120 秒，检索阶段最多 30 秒、生成阶段最多 90 秒，且共享总预算；鉴权时间另计。建议客户端、网关和反向代理读取超时至少设置 150 秒，并按环境鉴权耗时适当增加。

重复调用可能产生重复模型费用，超时后不要无条件重试。本接口不会持久化历史供下一次调用使用。

2026-10-09 在 105 实测：

- 开放个人令牌鉴权、空间列表、原召回接口正常。
- 空间 137 + 模型 20：新接口约 7.3 秒返回上述六大支柱答案、`has_context=true` 及文件 975 的来源信息。
- 空空间 179 + 模型 20：约 0.4 秒返回“未找到相关内容”、`has_context=false`、空来源列表。

以上为已验证样例，不代表所有空间、模型和异常分支已完成现场验收。
