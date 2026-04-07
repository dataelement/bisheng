# Bisheng Workflow MCP 接入说明

## 概述

Bisheng 提供一个面向外部 Agent 的 Workflow MCP 服务，支持：

- 创建 workflow draft
- 读取 workflow 节点
- 读取节点可编辑参数
- 编辑节点参数
- 校验 workflow
- 发布 workflow

服务地址：

- MCP: `/mcp/`
- MCP token 申请接口: `POST /api/v1/user/mcp_token`

注意：

- `/mcp/` 只接受 **Bisheng MCP token**
- 不接受普通 Bisheng 登录 token 直接调用

---

## 服务端配置

建议至少配置这些项：

- `BISHENG_MCP_ALLOWED_ORIGINS`
  - 用逗号分隔的 origin 白名单
  - 例如：`https://clawith.example.com,https://clawith-dev.example.com`
- `JWT_SECRET`
  - 用于签发和校验 Bisheng token / MCP token
- `redis_url`
  - 用于校验 Bisheng 主 session 是否仍然有效

说明：

- 如果未配置 `BISHENG_MCP_ALLOWED_ORIGINS`，本地默认只做 `localhost/127.0.0.1/同 host` 的基础放行
- 生产环境应显式配置 `BISHENG_MCP_ALLOWED_ORIGINS`

---

## 认证模型

### 1. 先有 Bisheng 登录态

你需要先在 Bisheng 完成正常登录，拿到普通 Bisheng access token。

这个 token 仍然是 Bisheng 主站登录态，不建议直接交给 MCP client 长期使用。

### 2. 再换取 MCP token

使用普通 Bisheng access token 调：

```http
POST /api/v1/user/mcp_token
Authorization: Bearer <bisheng_access_token>
Content-Type: application/json
```

请求体：

```json
{
  "expires_in": 1800
}
```

返回示例：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "access_token": "<mcp_access_token>",
    "token_type": "Bearer",
    "expires_in": 1800,
    "scopes": [
      "workflow.read",
      "workflow.write",
      "workflow.publish"
    ],
    "audience": "bisheng-workflow-mcp"
  }
}
```

### 3. 用 MCP token 调 `/mcp/`

```http
Authorization: Bearer <mcp_access_token>
```

MCP token 特性：

- audience 固定为 `bisheng-workflow-mcp`
- token type 固定为 `mcp_access_token`
- 绑定当前 Bisheng 登录 session
- 如果 Bisheng 主 session 失效或被替换，MCP token 也会失效
- 默认有效期 30 分钟，可通过 `expires_in` 调整，范围 `60-3600` 秒

---

## Scope

当前 MCP token 默认带 3 个 scope：

- `workflow.read`
- `workflow.write`
- `workflow.publish`

tool 权限要求：

- `ping`: 任意已认证 MCP token
- `whoami`: 任意已认证 MCP token
- `list_workflow_nodes`: `workflow.read`
- `get_workflow_node_params`: `workflow.read`
- `create_workflow_draft`: `workflow.write`
- `update_workflow_draft`: `workflow.write`
- `update_workflow_node_params`: `workflow.write`
- `validate_workflow`: `workflow.write`
- `publish_workflow`: `workflow.publish`

---

## Tool 列表

### `ping`

用于测试 MCP 连通性和当前认证状态。

返回：

```json
{
  "ok": true,
  "service": "bisheng-workflow-mcp",
  "authenticated": true,
  "user_id": 1,
  "user_name": "admin",
  "scopes": [
    "workflow.read",
    "workflow.write",
    "workflow.publish"
  ]
}
```

### `whoami`

返回当前 MCP token 对应的 Bisheng 用户。

### `create_workflow_draft`

创建一个新的 workflow draft。

输入：

```json
{
  "name": "demo-workflow",
  "description": "created by agent",
  "guide_word": "",
  "graph_data": {
    "nodes": [],
    "edges": []
  }
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "status": "draft",
  "draft_revision": 1
}
```

### `list_workflow_nodes`

列出当前 workflow 可编辑版本中的节点摘要。

输入：

```json
{
  "flow_id": "<flow_id>"
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "draft_revision": 3,
  "nodes": [
    {
      "id": "node-1",
      "type": "llm",
      "name": "LLM",
      "param_keys": [
        "system_prompt",
        "user_prompt",
        "model_id",
        "temperature"
      ]
    }
  ]
}
```

### `get_workflow_node_params`

读取单个节点当前可编辑参数。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_id": "<node_id>"
}
```

返回会带：

- `draft_revision`
- `node_type`
- `node_name`
- `params`

每个 param 字段会包含：

- `display_name`
- `group_name`
- `type`
- `required`
- `show`
- `options`
- `scope`
- `placeholder`
- `refresh`
- `value`

### `update_workflow_node_params`

编辑单个节点参数。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_id": "<node_id>",
  "updates": {
    "temperature": 0.3,
    "system_prompt": "new prompt"
  },
  "expected_revision": 3
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "status": "draft",
  "draft_revision": 4
}
```

### `update_workflow_draft`

整体替换当前 draft graph。

输入：

```json
{
  "flow_id": "<flow_id>",
  "graph_data": {
    "nodes": [],
    "edges": []
  },
  "expected_revision": 4
}
```

### `validate_workflow`

校验 workflow 当前版本。

### `publish_workflow`

发布指定 workflow 版本。

---

## Draft Revision

Workflow draft 使用乐观并发控制。

关键字段：

- 读接口返回 `draft_revision`
- 写接口要求传 `expected_revision`
- 成功写入后会返回新的 `draft_revision`

推荐调用顺序：

1. `list_workflow_nodes` 或 `get_workflow_node_params`
2. 取返回里的 `draft_revision`
3. 调 `update_workflow_node_params` / `update_workflow_draft`
4. 把 `draft_revision` 作为 `expected_revision` 传回去

如果 revision 不匹配，会拒绝写入。

拒绝示例：

```json
{
  "ok": false,
  "message": "Workflow draft revision mismatch, expected 2, got 3",
  "error_code": 10532
}
```

这用于防止：

- 多个 Agent 同时编辑同一个 draft
- UI 和 Agent 同时改同一个 workflow

---

## 节点参数暴露规则

MCP 不会把节点里所有字段都暴露出去。

当前只允许读取和编辑：

- `show != false`
- 非敏感字段
- 非 password/file 类型字段

默认会屏蔽这些字段：

- `password`
- `token`
- `secret`
- `api_key`
- `apikey`
- `credential`
- `auth`
- `cookie`

也就是说：

- 隐藏字段不会出现在 `param_keys`
- 敏感字段不会出现在 `get_workflow_node_params`
- 敏感字段也不能通过 `update_workflow_node_params` 修改

---

## 错误语义

### HTTP 层

- `401`
  - 缺少 Bearer token
  - MCP token 非法
  - MCP token 过期
  - Bisheng 主 session 失效
- `403`
  - Origin 不允许

### Tool 层

tool 调用失败时，返回结构化 JSON：

```json
{
  "ok": false,
  "message": "xxx",
  "error_code": 10532
}
```

典型错误：

- `10526`: workflow graph / 节点参数校验失败
- `10529`: workflow 重名
- `10532`: draft revision 冲突

---

## Clawith 配置建议

Clawith 里建议这样接：

- `server_url`: `https://<bisheng-host>/mcp/`
- `transport`: `streamable_http`
- `auth_type`: `bearer`
- `token_source`: 用户级 credential
- `credential_value`: `POST /api/v1/user/mcp_token` 返回的 `access_token`

不要让模型自己持有普通 Bisheng 登录 token。

更合理的流程是：

1. 用户先在 Clawith 里完成 Bisheng 登录/绑定
2. Clawith 后端持有普通 Bisheng 登录态
3. Clawith 后端按需调用 `/api/v1/user/mcp_token`
4. Clawith 用返回的 MCP token 调 `/mcp/`

---

## 已验证的本地链路

本地已验证：

1. 普通 Bisheng access token 可成功换取 MCP token
2. MCP token 可成功调用 `ping`
3. MCP token 可成功调用 `list_workflow_nodes`
4. workflow tool 返回 `draft_revision`
5. 节点参数读取正常
6. `update_workflow_node_params` 成功写入后会推进 `draft_revision`
7. 旧 `expected_revision` 的重复写入会被 `10532` 拒绝

本地测试地址：

- `http://127.0.0.1:7860/api/v1/user/mcp_token`
- `http://127.0.0.1:7860/mcp/`

---

## 注意事项

- `/mcp/` 必须带尾斜杠
- 生产环境建议显式配置 `BISHENG_MCP_ALLOWED_ORIGINS`
- 不建议长期缓存 MCP token，建议按需刷新
- 普通 Bisheng access token 和 MCP token 不要混用
