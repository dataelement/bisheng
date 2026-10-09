# MCP 知识检索接入说明

实现入口为 `/mcp`，工具为 `search_knowledge`。服务默认开启，不需要配置 Host/Origin 或跨域白名单；本文不代表已部署。

## 1. 默认行为与可选关闭

没有 `mcp.server` 配置或未设置 enabled 时，MCP 默认开启。
`/mcp`、`/mcp/` 允许任意跨域来源、请求方法和请求头，任意 Host/Origin 可进入鉴权与协议处理。
预检可直接完成；实际请求仍要求开发者 Token 和权限，非 POST 在鉴权后返回 405。
跨域使用 `X-Developer-Token` 请求头，不使用 Cookie 凭证；浏览器请求不要设置 `credentials: include`。
其他 REST 路径的 CORS 策略不变，不需要修改 `BISHENG_CORS_ORIGINS`。

保留可选关闭开关。若已有 DB 系统配置显式设置 enabled=false，仍保持关闭；需要开启时去掉或修改该值。
旧 allowed_hosts/allowed_origins 配置已忽略。配置读取路径为 `settings.get_mcp_conf()`；显式开关修改需等缓存更新并重启。

```yaml
mcp:
  enable_stdio: true
  server:
    enabled: false  # 仅需要关闭 MCP 时配置
```

用户于 2026-10-09 确认取消 SDK Host/Origin 白名单与 DNS 重绑定防护；来源限制放宽，不改变 Token 和知识权限。
对外使用 HTTPS，代理保留 Token、协议、Accept 和 Content-Type 请求头；JSON 无状态传输不要求独立 GET SSE 流。

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
| HTTP 404 | MCP 被显式关闭，检查已有 enabled=false 配置与重启状态。 |
| HTTP 401 / 19801～19803 | 缺失、无效、禁用 Token，或绑定用户/租户失效。 |
| HTTP 403 / 19804、19812 | IP 或显式路由规则不允许。 |
| HTTP 429 / 19805 | Token 请求限流。 |
| HTTP 503 / 19806 | Token 限流基础设施不可用；主应用既有过载保护也可能提前拒绝请求。 |
| HTTP 405 | 完成鉴权后请求了非 POST 方法；POST-only Token 对 GET 可能先收到 403。 |
| MCP `isError=true` | 参数/未知工具、资源无权、检索超时或下游失败。 |

正式启用前用实际 Token 与知识库验证一次有权/无权检索和来源链接；当前自动化测试没有操作真实业务数据。

## 5. 关闭与回退

把 DB 系统配置 `mcp.server.enabled` 改为 `false`，确认缓存更新后重启，`/mcp` 返回 404。
旧 REST 保持可用。本期无数据库结构迁移，不需要数据回滚。
本次代码默认开启；没有修改实际部署的 DB 配置、创建/编辑真实 Token、提交、推送或部署。
