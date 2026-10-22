# MCP 知识空间九工具接入说明

完整使用文档见 [BiSheng MCP 使用文档](../../../docs/api/mcp-usage.md)，包含逐工具参数、调用示例、Python 客户端和错误排查。本页保留特性接入简表。

本地实现已接入 `/mcp`、`/mcp/`。新增截图中的九工具，保留旧 `search_knowledge`，共十个名称。本说明不代表已部署；验证范围见 [verification.md](verification.md)。

## 1. 连接与身份

服务延续默认开启和 MCP 任意来源跨域。客户端使用 Streamable HTTP，配置：

```json
{
  "url": "https://bisheng.example.com/mcp",
  "headers": {"X-Developer-Token": "<完整开发者Token>"}
}
```

Token 不加 `Bearer`，也不放进工具参数。路由白名单未配置、`null` 或 `[]` 时不限制路由，可以调用 MCP；若配置非空规则，必须匹配 `POST /mcp`。如需只允许 MCP，可选配置：

```json
[{"match_type":"METHOD_PATH","method":"POST","path":"/mcp"}]
```

F081 要求十工具顶层必填 external_id，由目标用户决定当前租户及资源读写权限，允许跨 Token 租户。Token 绑定用户/租户有效性检查保留，但不参与业务授权。账号须由可信业务后端验证真实登录用户后固定提供；有效 Token 可以代理管理员，不能交给终端任意选择账号。缺参、账号不可唯一确定、当前关系或租户失效均拒绝，不回退 Token 用户。旧客户端需升级并刷新工具清单。握手、列工具、调用均验证 Token，沿用 IP 和限流规则。非空白名单不匹配时返回 403/19812；空白名单放行不会赋予额外资源权限。浏览器使用请求头鉴权，不设置 Cookie 凭证。

已有 `/mcp` Token 在指定目标用户有上传权时，现在也能调用两个写工具。没有新增逐工具权限配置或必填服务配置；显式关闭 MCP 的原配置仍有效。

## 2. 工具与参数

以下表格只列业务参数，十工具均还必填 external_id（严格字符串、去首尾空白后 1～255 字符，保留前导零）。账号只放顶层，不能放进 filters/folder_scope；多租户仅取唯一当前有效关系，单租户使用默认租户 1。

新工具仅覆盖知识空间，不支持传统文档库、QA 库。`knowledge_id` 是空间 ID，`folder_id=null` 或省略表示根目录。先列空间，再逐层列目录选择位置，不会自动创建空间或目录。

`folder_id` 支持正整数或纯数字的正数字符串，例如 `305`、`"305"`、`"000305"`；业务校验前归一化为整数，响应 ID 仍为整数。嵌套的 `folder_scope.folder_id` 同样支持这两种输入，但必填且非空。空串、空白、非数字、符号/小数、布尔和非正数拒绝；其他资源 ID 仍要求严格整数。

| 工具 | 必填参数 | 可选参数与结果 |
|---|---|---|
| `list_knowledge` | 无 | `name`、`writable_only`；返回空间、层级、根上传权和是否存在可写目录 |
| `list_folders` | `knowledge_id` | `folder_id`；返回直接子目录、ID、安全路径和 `can_upload` |
| `list_files` | `knowledge_id` | `folder_id`、`statuses`、`sort_by`、`order`；返回直接子文件和当前状态 |
| `search_files` | `keyword` | `knowledge_ids`、`folder_scope`、`search_mode`；返回匹配文件及有权路径 |
| `get_file_detail` | `knowledge_id`、`file_id` | `include_content=true`、`content_format=text`、`max_chars=20000`、`cursor`；返回元数据、正文和解析状态 |
| `get_file_source` | `knowledge_id`、`file_id` | `source_type=auto`；返回允许的预览链接、有效期和原件不可用原因 |
| `retrieve_chunks` | `query`、`knowledge_base_ids` | `top_k=5`、`max_content=15000`、`filters`；返回 `{chunks,total}`，片段含内容与出处 |
| `create_document` | `knowledge_id`、`file_name`、`content` | `folder_id`、`content_format=markdown`、分类/标签；创建新 `.md` 或 `.txt` 文件 |
| `upload_file` | `knowledge_id`、`file_name`、`content_base64` | `folder_id`、分类/标签；上传客户端已读取的文件字节 |

前四个工具支持 `page_size`（默认 20，最大 100）和 `cursor`，结果为 `{data,page_size,has_more,next_cursor}`。翻页时保留原查询条件，使用服务返回的游标；不返回未经权限过滤的总数。扫描预算耗尽时可能返回不足一页甚至空页，但 `has_more=true`，应继续使用下一游标。

`list_files.sort_by` 为 `file_name/update_time`，`order` 为 `asc/desc`，默认更新时间倒序。`statuses` 为现有状态：1 处理中、2 成功、3 失败、4 重建中、5 排队、6 超时、7 内容违规；受用户可见状态限制。

`search_files.keyword` 为 1～200 字符，`search_mode=name/content/all`，默认 `all`；最多显式指定 20 个空间，只返回成功文件。`folder_scope={knowledge_id,folder_id}` 限定该目录及子树；若同时传 `knowledge_ids`，其中须包含该空间。结果按更新时间和 ID 倒序排列。

正文页 `max_chars` 为 1～50000 字符；未解析完成时 `content_ready=false`、正文为空。正文版本变化后旧游标被拒绝，需要从首页重新读取。原生 Markdown 不存在时返回实际文本格式。

`retrieve_chunks.query` 为 1～2000 字符，空间数量 1～20，`top_k` 为 1～50，`max_content` 为 1～15000。它与旧 `search_knowledge` 共用检索核心；新名称额外要求目标全部是有权知识空间。旧名称原有范围不变。标签过滤示例：

```json
{"name":"retrieve_chunks","arguments":{"external_id":"00012345","query":"操作规程","knowledge_base_ids":[118],"filters":{"knowledge_base_filters":[{"knowledge_base_id":118,"tags":["规程"],"tag_match_mode":"ANY"}]}}}
```

以下 JSON 为 `tools/call` 的 params；推荐由 MCP 客户端处理握手及协议请求。

```json
{"name":"search_files","arguments":{"external_id":"00012345","keyword":"规程","knowledge_ids":[118],"folder_scope":{"knowledge_id":118,"folder_id":305},"search_mode":"all"}}
```

```json
{"name":"create_document","arguments":{"external_id":"00012345","knowledge_id":118,"folder_id":305,"file_name":"会议纪要.md","content":"# 会议纪要\n\n待办事项。","content_format":"markdown"}}
```

## 3. 上传大小与写入状态

| 限制 | 数值 | 计算方式 |
|---|---|---|
| 文件 | 50 MiB = 52428800 字节 | Base64 解码后的真实字节 |
| 新文档正文 | 10 MiB = 10485760 字节 | UTF-8 编码后的字节，中文不是按字符数计算 |
| HTTP 请求体 | 80 MiB = 83886080 字节 | 包含 JSON、Base64 和元数据，超限 HTTP 413 |

50 MiB 文件转 Base64 约 66.7 MiB。上传还受已有文件类型、系统大小设置及租户/角色配额限制，采用较严格的规则。服务端请求体落盘有界接收后，SDK 仍解析完整 JSON；这不是流式文件上传协议。代理也需允许相应请求大小与处理时间，本次没有改代理配置。

文件名必须是 1～200 字符的基名，不能带路径或控制字符。`create_document` 的 `markdown` 对应 `.md`，`text` 对应 `.txt`。`upload_file` 使用纯 Base64，不接受 `data:` 前缀、URL 或服务器路径。

可选元数据为 `file_category_code`、`file_subcategory_code`、`business_domain_code`（最多各 16 字符），以及 `manual_tag_ids`、`manual_tag_names`（最多各 100 项，每个名称 1～200 字符）。业务校验继续由原上传服务执行，需要业务域的空间应显式提供合法代码。

两个工具均按目标用户上传，创建者、Owner、配额和任务租户使用目标身份，仅新增，不覆盖、不自动改名。根目录与子目录上传权独立；收藏空间不能写入。同名、同内容和配额等冲突返回工具错误，不把已有文件 ID 当作新建成功。

成功结果示例：

```json
{"file_id":901,"knowledge_id":118,"folder_id":305,"file_name":"会议纪要.md","status":5,"accepted":true,"content_ready":false}
```

`accepted=true` 表示创建和解析投递已受理，不能当作解析完成。继续调用 `get_file_detail` 或 `list_files` 查询。投递结果不确定时返回安全工具错误，已知时附 `file_id`；先查询文件状态和列表，不自动重放写请求。网络故障下不承诺恰好写入一次。

## 4. Python 客户端上传示例

使用项目已安装版本的官方 MCP SDK 和 httpx。环境变量提供 URL、Token、目标账号 BISHENG_EXTERNAL_ID、空间 ID、本地文件路径，可选目录 ID。账号环境变量仅用于受控示例；生产从已认证会话导出并覆盖终端参数：

```python
import asyncio
import base64
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    path = Path(os.environ["UPLOAD_PATH"])
    if not 0 < path.stat().st_size <= 50 * 1024 * 1024:
        raise ValueError("File must be nonempty and at most 50 MiB")
    args = {
        "external_id": os.environ["BISHENG_EXTERNAL_ID"],
        "knowledge_id": int(os.environ["BISHENG_KNOWLEDGE_ID"]),
        "file_name": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
    if os.environ.get("BISHENG_FOLDER_ID"):
        args["folder_id"] = int(os.environ["BISHENG_FOLDER_ID"])
    headers = {"X-Developer-Token": os.environ["BISHENG_DEVELOPER_TOKEN"]}
    async with httpx.AsyncClient(headers=headers, timeout=180) as http:
        async with streamable_http_client(
            os.environ["BISHENG_MCP_URL"], http_client=http
        ) as (reader, writer, _):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                result = await client.call_tool("upload_file", args)
                if result.isError:
                    raise RuntimeError("Upload failed; check file state before retrying")
                saved = result.structuredContent
                print({key: saved[key] for key in ("file_id", "status", "accepted")})


asyncio.run(main())
```

## 5. 来源与失败处理

`get_file_source` 的 `auto/preview` 只签发当前有权预览的对象。当前原件下载需要走已有授权水印下载流程，所以 `original_url` 为空，并附 `original_unavailable_reason`；显式请求 `original` 返回工具错误。预览尚未生成时也会报不可用。默认链接有效期为七天，链接不应进入普通日志。

Token 错误为 HTTP 401，路由/IP 拒绝为 403，限流为 429，限流服务不可用为 503。业务参数、权限、内容变化和下游错误使用 MCP 的 `isError=true`，无需解析 REST 响应外壳。user_id/tenant_id、跳过审核、覆盖或外部路径等未知字段会被拒绝。

回退代码会移除新增工具，但不会删除已经创建的文件。本次无表结构变更、依赖安装或部署操作。
