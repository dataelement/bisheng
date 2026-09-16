# MCP Server 工具面

`POST /api/v2/mcp`

平台以标准 **MCP（Model Context Protocol）** 协议对外提供一组工具，供开发者的本地 coding agent（Claude Code、Cursor、Codex、纯 `mcp` python 客户端……）零改造接入：配一个地址和一把服务账号密钥即可列出并调用。

本文是这条接口的对外契约。实现侧的决策与坑见 [`features/v3.0.0/052-mcp-server-face/design.md`](../../features/v3.0.0/052-mcp-server-face/design.md)。

---

## 1. 接入

| 项 | 值 |
|---|---|
| 地址 | `{平台地址}/api/v2/mcp`，**精确路径**，不带尾斜杠、不追加子路径 |
| 传输 | MCP streamable-http，无状态，`Content-Type: application/json` |
| 鉴权 | `Authorization: Bearer bs-sak-…`（服务账号密钥）或 `bs-pat-…`（个人访问令牌） |
| 地址从哪来 | `GET /api/v1/dev-toolkit/versions` 的 `mcp.url` 字段；接入信息区一键复制的就是它。该字段**不含**密钥 |

Claude Code：

```bash
claude mcp add --transport http bisheng https://<平台地址>/api/v2/mcp \
  --header "Authorization: Bearer bs-sak-…"
```

纯 python 客户端：

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

headers = {"Authorization": "Bearer bs-sak-…"}
async with streamable_http_client(url, headers=headers) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        print(await session.list_tools())
```

**未部署开放能力层的环境上这条路径不存在**（404），接入信息区也不展示地址——这是配置的结果，不是一个可以打开的开关。翻 `open_platform.enabled` 需要重启后端。

---

## 2. 身份与边界

- **一律以密钥主体自身的身份执行**。服务账号不继承它的资源归属人，也不继承任何自然人；可见范围 = 密钥权限位 ∧ 该主体被显式授予的资源。
- **不承载委托**。持 `delegate` 位的密钥在连接入口即被拒（`26051`），不会静默降级为「按服务账号身份跑」；委托专用的密钥请让管理员另发一把。
- **任何身份传递请求头一律拒绝**（`26303`）：`X-On-Behalf-Of`、`X-End-User` 及带厂商前缀的同名变体。`/api/v2` 的 REST 面会解析它们，本面不会——收下再忽略会让调用方误以为调用跑在别人的身份下。
- 密钥经请求头传递，**不接受查询参数**（会进访问日志）。
- 撤销 / 到期 / 停用、以及权限位编辑，**下一次调用即生效**（上界 5 秒），无需重连或重签。
- MCP 连接是协议会话，不是平台会话：不创建会话记录，不出现在任何人的会话列表里。

---

## 3. 工具清单

清单**按密钥权限位过滤**——`tools/list` 只返回这把密钥能用的工具。直接调用一个未持位的工具会被拒绝并**指明缺哪一位**，不是「未知工具」。

| 类别 | 工具 | 权限位 | 依赖工场运行时层 |
|---|---|---|---|
| ① 知识库检索 | `bisheng_knowledge_search` | `knowledge:read` | 否 |
| ② 知识库清单 | `bisheng_knowledge_list` | `knowledge:read` | 否 |
| ③ 模型清单 | `bisheng_model_list` | `model:invoke` | 否 |
| ④ 身份 / 组织 | `bisheng_identity_get_user`、`bisheng_org_tree`、`bisheng_dept_members` | `identity:read` | 否 |
| ⑤ 应用数据 | `bisheng_app_db_tables`、`bisheng_app_db_schema`、`bisheng_app_db_rows`、`bisheng_app_db_row_update` | `app:manage` | **是** |
| ⑥ 应用状态 / 日志 | `bisheng_app_status`、`bisheng_app_logs` | `app:manage` | **是** |

几条口径：

- **没勾任何权限位的密钥可以完成连接握手**，但工具清单为空、任何调用被拒。握手不是能力。
- **个人访问令牌**只会看到 ①② 两个工具。
- **未部署工场运行时层**时 ⑤⑥ 不出现在清单里，直接调用得到 `16207`「本环境未启用应用工场」；其余四类不受影响。
- 依赖尚未随本次部署交付的工具（如模型清单依赖模型协议面）**不出现在清单里**，而不是出现后报错。
- 每个工具都带 `outputSchema`，出参结构不需要猜。

### 入参 / 出参

| 工具 | 入参 | 出参 |
|---|---|---|
| `bisheng_knowledge_search` | `query` · `knowledge_ids?`（省略 = 全部授予范围）· `top_k=10`（≤200）· `max_content=15000`（≤60000）· `tags?` | `{chunks:[{knowledge_id, knowledge_type, knowledge_name, document_id, document_name, chunk_index, content, document_update_time}], total, effective_scope, truncated_params}` |
| `bisheng_knowledge_list` | `name?` · `limit=200` | `{items:[{knowledge_id, name, type:"library"\|"space", description}], total}` |
| `bisheng_model_list` | — | `{models:[{name, qualified_name, callable_name, model_type, is_chat, server_name}]}` |
| `bisheng_identity_get_user` | `user_id` | `{user_id, user_name, status, departments:[{dept_id,name,path}], roles}` |
| `bisheng_org_tree` | — | `{departments:[{dept_id, name, parent_id, path, sort_order, source, status, children}]}` |
| `bisheng_dept_members` | `dept_id` · `page=1` · `size=50`（≤200）· `keyword?` | `{members:[{user_id, user_name, status}], total}` |
| `bisheng_app_status` | `app_id` | `{app_id, app_state, instance{…}, publish{…含审批终态与驳回理由全文}}` |
| `bisheng_app_logs` | `app_id` · `tail=200`（≤2000）· `since?` · `keyword?` | `{lines, app_state, pending_reason}` |
| `bisheng_app_db_*` | `app_id` · `table` · `page`/`size`/`order` · `key` · `values` | 数据面服务返回体原样透传 |

几条容易踩的：

- **检索指定的知识库只要有一个不可及，整个请求被拒**，并列出哪些标识不可及——不会静默剔除后返回缩水结果。「不存在」「未授予」「类型不支持」给同一个响应。
- **超出上限的 `top_k` / `max_content` 会被夹到上限**，并在 `truncated_params` 里如实写出来，不会静默截断。
- **`bisheng_model_list` 给出的 `callable_name` 就是模型协议面能直接用的名字**（同名歧义时是带服务商限定的那个）。
- **应用类工具只能操作这把密钥的资源归属人名下的应用**。租户管理员名下服务账号的密钥同样拒——管理员查他人应用请走应用详情页。
- **应用数据工具不含 DDL**：表结构由 `bisheng-app.yaml` 声明、平台建表、变更走发布管线；本面只做表清单 / 表结构读取与行级读写，每次写操作计审计（带 before / after）。
- **`identity:read` 是高危位**：给了就意味着本租户组织架构全量可读，没有把它收窄到部分部门的机制；跨租户一律读不到，且与「不存在」同一响应。结果只含自然人，服务账号不会出现。
- **应用日志的内容范围**与应用详情页运行日志、CLI `logs` 完全一致：应用自己的输出与错误信息，不含平台侧日志。

---

## 4. 错误

调用本面的是 agent——没有界面，也没有人替它看日志。所以**每一次拒绝都带三要素**，并且是可以 `json.loads` 的 JSON，放在 `CallToolResult.content[0].text` 里、`isError=true`：

```json
{
  "code": 26302,
  "category": "scope_missing",
  "reason": "密钥缺少调用该工具所需的权限位",
  "next_step": "找管理员在这把密钥上勾选 data.required 指出的权限位，下次调用即生效。",
  "data": {"required": "identity:read"}
}
```

`next_step` 按请求的 `Accept-Language` 给中 / 英 / 日三语，缺省中文。

`category` 取值：

| category | 含义 |
|---|---|
| `credential_invalid` | 密钥缺失 / 无效 / 已撤销 / 已过期 / 服务账号停用 |
| `scope_missing` | 密钥没有这个工具要的权限位 |
| `delegate_only` | 这把密钥是委托专用的，本面不收 |
| `identity_header_refused` | 请求里带了身份传递头 |
| `unreachable` | 目标不可及（知识库 / 用户 / 部门 / 未建库的应用） |
| `capability_revoked` | 声明接入的知识库已被删除或收回 |
| `not_your_app` | 不是你名下的应用（含不存在、他租户，同一响应） |
| `runtime_disabled` | 本环境未启用应用工场运行时层 |
| `permission_unavailable` | 权限引擎不可用——平台宁可报错也不返回未过滤的结果 |
| `invalid_argument` | 入参不合法 |
| `scope_too_large` | 检索范围过大，请显式指定 |
| `internal` | 其它；`reason` 不回显异常正文 |

**连接 / 握手层**的拒绝不是工具错误，而是真实 HTTP 状态 + 平台信封：

| HTTP | `status_code` | 场景 |
|---|---|---|
| 401 | 26001 / 26002 | 无密钥 / 密钥无效、已撤销、已过期 |
| 403 | 26051 | 持 `delegate` 位 |
| 403 | 26303 | 带了身份传递头 |
| 503 | 26030 | 凭据校验依赖不可用 |
| 404 | — | 本环境未部署开放能力层，路径不存在 |

响应体与错误体**永不回显密钥值**。

---

## 5. 审计

每一次 `tools/call` 都可在审计中归属到密钥（掩码）与其服务账号：事件 `MCP 工具调用`，记录工具名、目标对象摘要（知识库 / 应用 / 部门 / 用户标识）、结果、时延、时间。

**不记录**检索 query 正文、不记录片段内容、不记录入参全文——检索内容属于知识库，把它抄进审计表等于给知识库做了第二份拷贝。被挡在门外的调用（无效密钥、`delegate`、身份头）同样留痕。

---

## 相关

- 知识库纯检索 HTTP 接口：[`filelib-retrieve.md`](./filelib-retrieve.md)（同一条检索门面，同一把密钥得到同一集合）
- 开放 API 鉴权总览：[`开放 API 接口方案.md`](./开放%20API%20接口方案.md)
