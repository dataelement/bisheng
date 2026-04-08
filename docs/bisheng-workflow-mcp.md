# Bisheng Workflow MCP 接入说明

## 概述

Bisheng 提供一个面向外部 Agent 的 Workflow Authoring MCP 服务，支持：

- 发现可编辑 workflow
- 读取 workflow manifest / version / graph
- 发现可用 node type
- 读取 node template
- 创建 workflow draft
- 读取 workflow 节点
- 读取节点可编辑参数
- 原子编辑 workflow graph
- 编辑节点参数
- 校验 workflow
- 发布 workflow

服务地址：

- MCP: `/mcp`
- MCP token 申请接口: `POST /api/v1/user/mcp_token`

注意：

- `/mcp` 只接受 **Bisheng MCP token**
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

### 3. 用 MCP token 调 `/mcp`

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
- `list_workflows`: `workflow.read`
- `get_workflow`: `workflow.read`
- `get_workflow_versions`: `workflow.read`
- `get_workflow_graph`: `workflow.read`
- `list_node_types`: `workflow.read`
- `get_node_template`: `workflow.read`
- `list_workflow_nodes`: `workflow.read`
- `get_workflow_node_params`: `workflow.read`
- `create_workflow_draft`: `workflow.write`
- `update_workflow_draft`: `workflow.write`
- `update_workflow_node_params`: `workflow.write`
- `add_node`: `workflow.write`
- `remove_node`: `workflow.write`
- `connect_nodes`: `workflow.write`
- `disconnect_edge`: `workflow.write`
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

### `list_workflows`

列出当前用户有 authoring 权限的 workflow。

返回会带：

- `flow_id`
- `name`
- `description`
- `status`
- `current_version_id`
- `editable_version_id`
- `draft_revision`
- `schema_version`

### `get_workflow`

读取单个 workflow 的 manifest 信息。

### `get_workflow_versions`

列出 workflow 全部版本摘要。

返回会带：

- `version_id`
- `name`
- `description`
- `is_current`
- `is_editable`
- `is_external_draft`
- `original_version_id`
- `draft_revision`
- `schema_version`

### `get_workflow_graph`

读取 workflow 当前可编辑版本的标准化 graph。

输入：

```json
{
  "flow_id": "<flow_id>"
}
```

可选传 `version_id` 指定版本。

返回会带：

- `flow_id`
- `version_id`
- `draft_revision`
- `schema_version`
- `nodes`
- `edges`

每个 `node` 会包含：

- `id`
- `type`
- `name`
- `tab`
- `param_keys`
- `params`

### `list_node_types`

列出当前 Workflow Authoring MCP 支持发现的 node type。

返回会带：

- `type`
- `display_name`
- `description`
- `param_keys`
- `dynamic_template`
- `schema_version`

### `get_node_template`

读取单个 node type 的标准化 template。

输入：

```json
{
  "node_type": "llm"
}
```

返回会带：

- `node_type`
- `display_name`
- `description`
- `tab`
- `groups`
- `params`
- `dynamic_template`
- `schema_version`

### `create_workflow_draft`

创建一个新的 workflow draft。

行为说明：

- `graph_data` 允许为空图
- 如果初始图缺 `start`，MCP 会自动补一个 `start` 节点并连到入口节点
- 如果初始图缺 `end`，MCP 会自动补一个 `end` 节点并连到终点节点
- 对空图，MCP 会直接生成最小合法 scaffold：`start -> end`

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

### `get_condition_node`

读取条件节点的结构化分支配置。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_id": "condition_1234"
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "draft_revision": 4,
  "node_id": "condition_1234",
  "node_name": "Condition Node",
  "condition_cases": [
    {
      "id": "case_a",
      "operator": "and",
      "conditions": [
        {
          "id": "rule_1",
          "left_var": "score",
          "comparison_operation": "greater_than",
          "right_value_type": "const",
          "right_value": "80",
          "variable_key_value": {}
        }
      ],
      "variable_key_value": {}
    }
  ],
  "route_handles": [
    "case_a",
    "right_handle"
  ],
  "outgoing_edges": {
    "case_a": [
      {
        "edge_id": "edge_1",
        "target_node_id": "node-2",
        "target_handle": "input"
      }
    ]
  }
}
```

说明：

- `condition_cases[].id` 就是该分支在 graph 里的 `source_handle`
- 默认兜底分支固定是 `right_handle`
- 分支连线仍然通过 `connect_nodes` / `disconnect_edge` 操作
- 每个 `condition_cases[].id` 都必须有对应的出边，且 `right_handle` 也必须有兜底出边

### `update_condition_node`

更新一个已有条件节点的结构化条件分支配置。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_id": "condition_1234",
  "condition_cases": [
    {
      "id": "case_a",
      "operator": "and",
      "conditions": [
        {
          "id": "rule_1",
          "left_var": "score",
          "comparison_operation": "greater_than_or_equal",
          "right_value_type": "const",
          "right_value": "90",
          "variable_key_value": {}
        }
      ],
      "variable_key_value": {}
    }
  ],
  "expected_revision": 4
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "status": "draft",
  "draft_revision": 5,
  "node_id": "condition_1234"
}
```

注意：

- 如果你修改了 `condition_cases[].id`，必须同步调整对应边的 `source_handle`
- 如果 case id 和出边 handle 不一致，服务端会拒绝保存

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

### `add_node`

向当前可编辑 graph 添加一个节点。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_type": "code",
  "name": "Code Node",
  "position_x": 120,
  "position_y": 260,
  "initial_params": {
    "code": "print('hello')"
  },
  "expected_revision": 4
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "status": "draft",
  "draft_revision": 5,
  "node_id": "code_ab12cd34"
}
```

说明：

- `node_type` 必须来自 `list_node_types`
- `initial_params` 可选，仅能覆盖该 node type 已暴露的可编辑参数

### `remove_node`

从当前可编辑 graph 删除一个节点。

输入：

```json
{
  "flow_id": "<flow_id>",
  "node_id": "code_ab12cd34",
  "cascade": true,
  "expected_revision": 5
}
```

说明：

- `cascade=true` 时会一并删除与该节点关联的边
- `cascade=false` 且节点仍有边时会拒绝删除

### `connect_nodes`

在两个现有节点之间新增一条边。

输入：

```json
{
  "flow_id": "<flow_id>",
  "source_node_id": "node-1",
  "target_node_id": "node-2",
  "source_handle": "output",
  "target_handle": "input",
  "expected_revision": 5
}
```

返回：

```json
{
  "ok": true,
  "flow_id": "<flow_id>",
  "version_id": 12,
  "status": "draft",
  "draft_revision": 6,
  "edge_id": "edge_ef56gh78"
}
```

说明：

- 当前会拒绝重复同构边
- 当前要求显式传 `source_handle` / `target_handle`

### `disconnect_edge`

从当前可编辑 graph 删除一条边。

优先推荐按 `edge_id` 删除。

输入：

```json
{
  "flow_id": "<flow_id>",
  "edge_id": "edge_ef56gh78",
  "expected_revision": 6
}
```

也支持按 `(source_node_id, target_node_id, source_handle, target_handle)` 精确匹配删除。

### `update_workflow_draft`

整体替换当前 draft graph。

输入：

```json
{
  "flow_id": "<flow_id>",
  "graph_data": {
    "nodes": [
      {
        "id": "start_1",
        "data": {
          "id": "start_1",
          "type": "start",
          "name": "Start",
          "group_params": []
        }
      }
    ],
    "edges": []
  },
  "expected_revision": 4
}
```

### `validate_workflow`

校验 workflow 当前版本。

返回新增 `diagnostics` 字段，每个诊断项包含：

- `code`
- `severity`
- `message`
- `node_id`
- `field_path`
- `suggested_fix`

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

graph 原子编辑接口也遵守同样规则：

- `add_node`
- `remove_node`
- `connect_nodes`
- `disconnect_edge`

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

- `server_url`: `https://<bisheng-host>/mcp`
- `transport`: `streamable_http`
- `auth_type`: `bearer`
- `token_source`: 用户级 credential
- `credential_value`: `POST /api/v1/user/mcp_token` 返回的 `access_token`

不要让模型自己持有普通 Bisheng 登录 token。

更合理的流程是：

1. 用户先在 Clawith 里完成 Bisheng 登录/绑定
2. Clawith 后端持有普通 Bisheng 登录态
3. Clawith 后端按需调用 `/api/v1/user/mcp_token`
4. Clawith 用返回的 MCP token 调 `/mcp`

---

## 已验证的本地链路

本地已验证：

1. 普通 Bisheng access token 可成功换取 MCP token
2. MCP token 可成功调用 `ping`
3. MCP token 可成功调用 discovery / authoring tool
4. workflow tool 返回 `draft_revision`
5. 节点参数读取正常
6. `update_workflow_node_params` 成功写入后会推进 `draft_revision`
7. 旧 `expected_revision` 的重复写入会被 `10532` 拒绝

本地测试地址：

- `http://127.0.0.1:7860/api/v1/user/mcp_token`
- `http://127.0.0.1:7860/mcp`

---

## 注意事项

- `/mcp` 和 `/mcp/` 都可访问，但文档统一使用 `/mcp`
- 生产环境建议显式配置 `BISHENG_MCP_ALLOWED_ORIGINS`
- 不建议长期缓存 MCP token，建议按需刷新
- 普通 Bisheng access token 和 MCP token 不要混用
