# MCP 知识检索接入说明

实现入口为 `/mcp`，工具为 `search_knowledge`。服务默认关闭；本文是启用和接入步骤，不代表已部署或已开启。

## 1. 开启服务

在后台系统配置的 `mcp` 部分增加 `server` 子块，保留原 `enable_stdio` 值：

```yaml
mcp:
  enable_stdio: true
  server:
    enabled: true
    allowed_hosts:
      - "bisheng.example.com:*"
    allowed_origins:
      - "https://bisheng.example.com:*"
```

把示例域名替换为实际 MCP 服务域名。允许列表只接受明确主机，端口可以使用 `:*`；不接受无约束 `*`。
`:*` 同时覆盖未显式指定端口的 Host/Origin。服务端客户端一般没有 Origin；有 Origin 时必须在允许列表中。
若代理保留浏览器客户端的其他 Origin，应显式添加该来源；浏览器还需通过主应用既有 CORS 设置。

配置来源是已有 DB 系统配置，读取路径为 `settings.get_mcp_conf()`，不是仅修改本地 `config.yaml`。
已有部署的 `mcp` 块不会因模板增加子块就自动开启；缺少 `server` 时使用关闭默认值。
确认既有配置缓存已经更新或最多 100 秒 TTL 到期后，重启后端。开关和传输安全列表是启动快照。

对外使用 HTTPS，代理保留 `X-Developer-Token`、`MCP-Protocol-Version`、`Accept`、`Content-Type` 等请求头和实际 Host。
第一版使用 JSON 响应、无状态传输，不要求客户端建立独立 GET SSE 流。

## 2. 配置 Token 与资源权限

管理员在现有开发者 Token 管理页面创建或编辑 Token，选择绑定用户和部门；绑定用户需要具备目标知识资源权限。

添加路由白名单：

```json
[
  {
    "match_type": "METHOD_PATH",
    "method": "POST",
    "path": "/mcp"
  }
]
```

也支持现有 PATH/PREFIX 规则。MCP 必须有非空且命中的规则；旧 Token 空白名单不能调用 MCP。
不会自动扩大其他 Token 的白名单，旧 REST 的空白名单处理保持不变。
配置 IP 与限流后，复制完整 Token，调用头为 `X-Developer-Token: <完整Token>`，不加 Bearer。
握手、通知、工具列表和每次调用都是 HTTP 请求，都会验证 Token 并计入既有 Token 请求限流。

Token 验证成功不等于资源可读。MCP 固定使用绑定用户，不接收 `external_id`、`user_id` 或 `tenant_id`。
签发的来源链接沿用既有检索接口语义和有效期；链接本身应按凭证处理，不放入普通日志。

## 3. 客户端接入

连接参数示意，实际配置格式按客户端要求填写：

```json
{
  "url": "https://bisheng.example.com/mcp",
  "headers": {
    "X-Developer-Token": "<完整Token>"
  }
}
```

Token 保存在接入方配置或密钥环境变量中，不作为工具参数交给模型。
该方式适用于能配置自定义请求头的 MCP 客户端；本期没有实现 OAuth 登录与授权发现。

使用已安装官方 SDK 的最小 Python 调用：

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    headers = {"X-Developer-Token": os.environ["BISHENG_DEVELOPER_TOKEN"]}
    url = os.environ["BISHENG_MCP_URL"]
    knowledge_id = int(os.environ["BISHENG_KNOWLEDGE_ID"])
    async with httpx.AsyncClient(headers=headers, timeout=60) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print([tool.name for tool in tools.tools])
                result = await session.call_tool("search_knowledge", {
                    "query": "安全管理要求有哪些",
                    "knowledge_base_ids": [knowledge_id],
                    "top_k": 5,
                })
                print(result.isError, result.structuredContent)


asyncio.run(main())
```

知识库 ID 由接入方配置；首期没有知识库发现工具。响应是片段与来源，不包含模型生成答案。
输入限制：query 去空白后 1～2000 字符、1～20 个正整数知识库 ID、top_k 1～50、max_content 1～15000。
`max_content` 保留按知识库合并内容的限制语义；可使用已有 filters/ANY 标签筛选，ALL 仍不支持。
空结果为 `chunks=[], total=0`，业务失败为 `isError=true`，不能把两者混为一谈。

## 4. 常见失败

| 状态 | 意义 |
|------|------|
| HTTP 404 | MCP 默认关闭或已关闭，检查生效配置和重启状态。 |
| HTTP 401 / 19801～19803 | 缺失、无效、禁用 Token，或绑定用户/租户失效。 |
| HTTP 403 / 19804、19812 | IP 或显式路由规则不允许。 |
| HTTP 429 / 19805 | Token 请求限流。 |
| HTTP 503 / 19806 | Token 限流基础设施不可用；主应用既有过载保护也可能提前拒绝请求。 |
| HTTP 421 / 403 | Host 或 Origin 未在配置中允许。 |
| HTTP 405 | 完成鉴权后请求了非 POST 方法；POST-only Token 对 GET 可能先收到 403。 |
| MCP `isError=true` | 参数/未知工具、资源无权、检索超时或下游失败。 |

正式启用前用实际 Token 与知识库验证一次有权/无权检索和来源链接；当前自动化测试没有操作真实业务数据。

## 5. 关闭与回退

把 DB 系统配置 `mcp.server.enabled` 改为 `false`，确认缓存更新后重启，`/mcp` 返回 404。
旧 REST 保持可用。本期无数据库结构迁移，不需要数据回滚。
本次交付未自动启用服务、创建/编辑真实 Token、提交、推送或部署。
