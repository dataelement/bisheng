# 第三方客户端接入 BISHENG MCP 指南

本文面向需要在 IDE、编码助手、智能体平台或自研 MCP Host 中接入 BISHENG 的
管理员和开发者。服务端工具合同、错误格式和上传限制请同时参阅
[Open MCP 接入指南](./open-mcp.md)。

> 文档示例中的地址和密钥均为占位符。不要把真实 API Key 提交到代码仓库、工单、
> 聊天记录或截图中。

## 1. 接入信息

向 BISHENG 管理员获取以下信息：

| 配置项 | 示例 | 说明 |
|---|---|---|
| MCP URL | `https://bisheng.example.com/api/v2/mcp` | 必须是完整地址，不要改成 `/sse` |
| Transport | Streamable HTTP | 本服务不是 stdio，也不是旧版 SSE 双端点 |
| API Key | `bs-sak-<redacted>` | 推荐使用服务账号 API Key |
| Scope | `knowledge:read`、`knowledge:write` | 决定客户端能发现哪些工具 |
| 资源授权 | 指定知识库或知识空间的读写权限 | 决定工具实际能操作哪些资源 |

MCP 客户端必须满足以下条件才能直连：

1. 支持远程 **Streamable HTTP** MCP。
2. 能在 `initialize`、`tools/list` 和每次 `tools/call` 请求中持续发送自定义 HTTP Header。
3. 能发送 `Authorization: Bearer <credential>`。
4. 能处理 MCP `structuredContent`、`TextContent` 和 `isError=true` 工具错误。
5. 能访问 BISHENG 地址并信任其 HTTPS 证书链。

只支持 stdio、只支持旧版 SSE、不能配置请求头，或者只接受 OAuth 登录的客户端，
不能直接连接本版 BISHENG MCP。

## 2. 权限准备

### 2.1 推荐：服务账号 API Key

管理员按以下顺序配置：

1. 在当前租户创建并启用服务账号。
2. 为服务账号授予需要访问的知识库、知识空间及文件权限。
3. 为服务账号签发 `bs-sak-...` API Key。
4. 按用途授予最小 scope：
   - 只读客户端：`knowledge:read`；
   - 需要创建、更新、上传或删除：同时授予 `knowledge:write`；
   - 需要代表平台用户执行：额外授予 `delegate` 并配置允许的委托用户。
5. 在客户端的私有配置或密钥存储中保存签发时返回的明文 Key。

管理接口如下：

| 用途 | 接口 |
|---|---|
| 签发 Key | `POST /api/v1/service-accounts/{service_account_id}/keys` |
| 更新 Key scope | `PATCH /api/v1/service-accounts/{service_account_id}/keys/{key_id}` |
| 撤销 Key | `POST /api/v1/service-accounts/{service_account_id}/keys/{key_id}/revoke` |
| 配置资源授权 | `POST /api/v1/service-accounts/{service_account_id}/resource-grants:mutate` |

Key 的 scope 只控制“哪些 MCP 工具可见”，资源授权控制“具体能访问哪些数据”。
即使 Key 拥有 `knowledge:write`，服务账号没有目标知识库的写权限时，调用仍会被拒绝。

### 2.2 PAT

`bs-pat-...` 个人访问令牌按持有人权限执行，并且本期只允许以下三个只读工具：

- `bisheng_knowledge_list`
- `bisheng_knowledge_retrieve`
- `bisheng_knowledge_file_list`

需要写入能力或服务器到服务器集成时，不要使用 PAT，应使用服务账号 API Key。

### 2.3 委托模式

代表指定 BISHENG 平台用户执行时，在所有 MCP HTTP 请求中增加：

```http
X-On-Behalf-Of: <BISHENG_PLATFORM_USER_ID>
```

该值必须是已加入当前 Key 委托范围的 BISHENG 平台用户 ID。不要直接填第三方系统的
用户 ID；如两边用户 ID 不一致，应由受信任的接入网关先完成身份映射。

只要 Key 包含 `delegate` scope，每个请求就必须携带 `X-On-Behalf-Of`；需要同时支持
服务账号自身身份和委托身份时，应分别签发两把最小权限 Key，不要复用同一把 Key。

`X-On-Behalf-Of` 不能与 `X-End-User` 同时发送。普通客户端优先使用服务账号自身身份，
不要让模型或最终用户动态填写身份 Header。

## 3. 通用配置模板

不同客户端的字段名可能不同，但等价配置都是：

```json
{
  "mcpServers": {
    "bisheng": {
      "type": "streamable-http",
      "url": "https://bisheng.example.com/api/v2/mcp",
      "headers": {
        "Authorization": "Bearer <BISHENG_API_KEY>"
      }
    }
  }
}
```

如果客户端只接受 `type: "http"`，可以使用 `http`；它在这些客户端中表示
Streamable HTTP。不要把 BISHENG MCP 配置成 `stdio` 或 `/sse`。

## 4. 常见客户端配置

以下示例基于对应客户端在 2026-09-18 的官方文档。客户端升级后若字段发生变化，
以客户端当前官方文档为准，但 BISHENG URL、Bearer Header 和权限语义不变。

### 4.1 Claude Code

推荐把地址和 Key 放入环境变量，再在项目根目录 `.mcp.json` 或用户配置中引用：

```bash
export BISHENG_MCP_URL='https://bisheng.example.com/api/v2/mcp'
export BISHENG_API_KEY='bs-sak-<redacted>'
```

```json
{
  "mcpServers": {
    "bisheng": {
      "type": "http",
      "url": "${BISHENG_MCP_URL}",
      "headers": {
        "Authorization": "Bearer ${BISHENG_API_KEY}"
      }
    }
  }
}
```

检查连接：

```bash
claude mcp get bisheng
claude mcp list
```

也可以使用 `claude mcp add --transport http` 和 `--header`，但直接把 Key 写在命令中
可能进入 shell 历史，不建议在生产环境使用。

### 4.2 Cursor

将配置放在用户级 `~/.cursor/mcp.json`。如果写到项目级 `.cursor/mcp.json`，不要提交
包含真实 Key 的文件。

```json
{
  "mcpServers": {
    "bisheng": {
      "url": "https://bisheng.example.com/api/v2/mcp",
      "headers": {
        "Authorization": "Bearer <BISHENG_API_KEY>"
      }
    }
  }
}
```

重载 MCP 后，在 Cursor 的 MCP 设置或 Output 中确认服务已连接，并检查工具列表。
如果全局和项目配置存在同名 `bisheng`，项目配置会覆盖全局配置；排障时应检查是否
连接到了旧配置。

### 4.3 Visual Studio Code / GitHub Copilot

VS Code 可以通过 secret input 避免把 Key 明文写入配置。使用用户级 `mcp.json`，
或在工作区创建 `.vscode/mcp.json`：

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "bisheng-api-key",
      "description": "BISHENG service-account API Key",
      "password": true
    }
  ],
  "servers": {
    "bisheng": {
      "type": "http",
      "url": "https://bisheng.example.com/api/v2/mcp",
      "headers": {
        "Authorization": "Bearer ${input:bisheng-api-key}"
      }
    }
  }
}
```

在命令面板执行 `MCP: List Servers`，启动 `bisheng` 后检查工具列表。工作区配置首次
使用时可能要求用户确认信任。

### 4.4 Codex CLI / Codex 桌面端

在 `~/.codex/config.toml` 中配置 URL，通过环境变量提供 Bearer Token：

```toml
[mcp_servers.bisheng]
url = "https://bisheng.example.com/api/v2/mcp"
bearer_token_env_var = "BISHENG_API_KEY"
```

```bash
export BISHENG_API_KEY='bs-sak-<redacted>'
```

桌面端或 IDE 扩展不一定继承 shell 环境；应按客户端的密钥环境配置方式设置变量并
重启客户端。不要把明文 Key 写入项目级 `config.toml`。

### 4.5 Open WebUI

Open WebUI 的 MCP 连接由管理员统一配置：

1. 进入 `Settings > Admin > Integrations`。
2. 新增 External Tool Server。
3. Type 选择 **MCP (Streamable HTTP)**，不要选择 OpenAPI。
4. Server URL 填写 `https://bisheng.example.com/api/v2/mcp`。
5. 在自定义 Headers 中填写：

   ```json
   {
     "Authorization": "Bearer <BISHENG_API_KEY>"
   }
   ```

6. 保存并执行连接验证，然后通过访问控制限定可以使用该工具连接的用户或用户组。

一个 Open WebUI 连接使用一把服务账号 Key 时，所有获准使用该连接的用户共享这一个
BISHENG 服务账号身份和权限边界。不要把 Open WebUI 的 `{{USER_ID}}` 直接作为
`X-On-Behalf-Of`；它不是天然可信的 BISHENG 平台用户 ID。需要逐用户权限时，应通过
受信任网关完成用户映射，或为不同权限边界配置不同的服务账号连接。

### 4.6 Claude、Claude Desktop 自定义连接器

Claude 和 Claude Desktop 的远程自定义连接器目前面向无认证或 OAuth 认证服务，且
Claude Desktop 不会把远程服务的 `claude_desktop_config.json` 配置作为连接器加载。
BISHENG 本期提供的是静态 Bearer API Key，不提供 MCP OAuth 授权服务器，因此不能按
当前官方“Settings > Connectors”流程直接接入。

如确需接入，应在 BISHENG 前部署经过安全评审的 OAuth-to-Bearer 网关，由网关完成
OAuth 身份校验、用户到 BISHENG 主体的映射和 Key 保管。不要使用把长期 Key 暴露给
公共代理的临时桥接方案。

### 4.7 其他客户端或自研 MCP Host

对于 Cherry Studio、Dify、自动化平台或自研客户端，不按产品名称预设兼容性。先确认
其当前版本满足第 1 节的五项条件，然后使用第 3 节的等价配置。

接入验收至少验证：

1. 初始化成功，客户端没有回退到 SSE。
2. `tools/list` 返回与 Key scope 相符的工具。
3. 只读调用可以获得 `structuredContent` 或等价 `TextContent`。
4. 无权限资源返回明确错误，而不是被客户端显示为连接断开。
5. Key 撤销后，新请求立即或在凭据缓存窗口内失效。
6. 客户端在后续 `tools/call` 中仍持续发送 Authorization Header。

## 5. 连通性验证

在把问题归因于第三方客户端之前，先从可访问 BISHENG 的机器运行服务端随附脚本：

```bash
cd src/backend
export BISHENG_MCP_URL='https://bisheng.example.com/api/v2/mcp'
export BISHENG_API_KEY='bs-sak-<redacted>'
.venv/bin/python scripts/verify_open_mcp.py --expected-profile full
```

只读 Key 使用 `--expected-profile scope-filtered`；PAT 使用
`--expected-profile pat`。完整发布验收仍应使用具有 `knowledge:read` 和
`knowledge:write` 的测试服务账号，确认 10 个工具无缺失也无多出。

可选执行一次只读调用：

```bash
.venv/bin/python scripts/verify_open_mcp.py \
  --expected-profile full \
  --call-tool bisheng_knowledge_list \
  --arguments-json '{"type":0,"page_size":1}'
```

## 6. 常见问题

| 现象 | 常见原因 | 处理方式 |
|---|---|---|
| `401` | 未发送 Bearer、Key 格式错误、Key 已撤销或过期 | 检查客户端是否在每次请求中发送 Header；重新签发 Key |
| `403` | scope 不足、服务账号禁用、委托不允许或资源权限不足 | 区分工具 scope 与具体资源授权，按最小权限补齐 |
| `404` | URL 写错、网关未转发 `/api/v2/mcp` | 使用完整 MCP URL，检查反向代理路由 |
| `413` | MCP 请求体或上传内容超过限制 | 减小请求；检查网关和 BISHENG body 上限是否一致 |
| 能连接但工具数量少 | Key 只有 `knowledge:read`，或使用了 PAT | 对照当前 Key scope 和凭据类型 |
| `tools/list` 成功、调用时认证失败 | 客户端后续请求丢失 Authorization Header | 升级客户端并抓取仅含 Header 名称的日志确认 |
| 客户端尝试连接 `/sse` | 配置成旧版 SSE transport | 改为 Streamable HTTP 和 `/api/v2/mcp` |
| 直连后端成功、经网关失败 | 网关剥离 Header、限制 body 或错误缓冲流式响应 | 检查 `Authorization`、身份 Header、body 上限和流式转发 |
| HTTPS 握手失败 | 客户端不信任企业 CA 或证书域名不匹配 | 安装正确 CA 链，不要关闭 TLS 校验 |

## 7. 安全建议

- 一个客户端或系统使用独立服务账号和独立 Key，避免多人、多系统共享长期密钥。
- 优先只授予 `knowledge:read`；确需写入时再增加 `knowledge:write`。
- 同时收窄 Key scope 和服务账号资源授权，任一层都不要授予全量权限作为排障手段。
- Key 只保存在用户级密钥存储、环境变量、Secret Manager 或受控服务配置中。
- 定期轮换 Key；人员离岗、客户端下线或疑似泄露时立即撤销。
- 不记录 Authorization 值。排障日志只记录 Header 是否存在、credential ID、错误码和 trace ID。
- 对删除、清空、批量删除等 destructive 工具保留客户端确认，不要启用无条件自动批准。
- 多用户智能体平台必须明确“共享服务身份”还是“逐用户委托”，不能用一个管理员 Key
  代替所有用户权限。

## 8. 客户端官方参考

- [Claude Code：连接 MCP 服务](https://code.claude.com/docs/en/mcp)
- [Cursor：MCP integrations](https://prod.cursor.com/help/customization/mcp)
- [VS Code：MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
- [Codex：Model Context Protocol](https://developers.openai.com/codex/mcp/)
- [Open WebUI：Model Context Protocol](https://docs.openwebui.com/features/extensibility/mcp/)
- [Claude 远程自定义连接器说明](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
