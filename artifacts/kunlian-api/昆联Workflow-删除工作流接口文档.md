# 昆联 Workflow 删除工作流接口文档

## 1. 接口概述

用于通过昆联开放 API 删除指定工作流（仅限未上线或已下线状态的工作流）。

- **请求方法**：`DELETE`
- **接口路径**：`/api/v2/kunlian/workflows/{workflow_id}`
- **示例基地址**：`http://110.16.193.170:50055`（请按实际交付环境替换）

> **注意**：删除操作不可逆，会删除工作流主记录、将关联版本标记为已删除，并同步清理权限投影、分组关联资源、访客链接及记录审计日志。

---

## 2. 认证与权限要求

调用方须同时满足 **API Key 能力** 与 **账号业务权限** 两层校验：

| 校验维度 | 要求 |
|---|---|
| 认证方式 | `Authorization: Bearer <KUNLIAN_API_KEY>` |
| Key 能力（capability） | `write` |
| 操作账号（Query） | `user_account`（必填，长度 1—128，只能出现一次） |
| 业务权限 | 该 `user_account` 对目标 `workflow_id` 须具备 `delete` 权限 |

**安全与协议约束**：
- 不接受 `Cookie`、`x-on-behalf-of`、`x-end-user`、`x-user-id`、`x-tenant-id` 请求头。
- 不接受 `external_tenant_id`、`external_user_id` Query 参数。

---

## 3. 请求参数

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| Header | `Authorization` | string | 是 | 格式：`Bearer <KUNLIAN_API_KEY>` |
| Path | `workflow_id` | string | 是 | 目标工作流 ID |
| Query | `user_account` | string | 是 | 昆联侧操作账号标识（长度 1—128） |
| Body | — | — | 否 | 无请求体 |

---

## 4. 响应格式与出参

正常返回统一使用平台成功响应包装（HTTP 状态码 `200`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | int | 业务状态码，成功固定为 `200` |
| `status_message` | string | 状态描述，成功为 `"SUCCESS"` |
| `data` | null | 无删除详情对象，固定为 `null` |

---

## 5. 业务规则与限制

1. **上线态拦截**：仅允许删除处于未上线或已下线（非 `ONLINE`）状态的工作流；若工作流当前为 `ONLINE`（已发布上线）状态，接口会拒绝删除并返回 **HTTP 409 / `status_code: 10571`**。请先调用下线接口 `POST /api/v2/kunlian/workflows/{workflow_id}/unpublish` 将其下线，再执行删除。
2. **租户与类型隔离**：仅支持操作当前 Key 所属租户下的工作流（`flow_type = 10`）；工作流不存在、属于其他租户或非工作流类型时统一返回 **HTTP 404**。
3. **删除清理范围**：
   - 删除工作流主表记录，并将关联版本的 `is_delete` 标记为 `1`。
   - 删除对应的 OpenFGA 权限投影记录。
   - 清理分组关联资源、更新关联会话元数据、删除访客链接，并写入工作流删除审计日志。

---

## 6. 错误码与 HTTP 状态对照

| 场景 | HTTP 状态码 | 说明 |
|---|---|---|
| Key 或身份认证失败 | `401` | 返回认证错误业务码与消息 |
| Key 缺少 `write` 能力或账号缺少 `delete` 权限 | `403` | 能力或业务权限校验拒绝 |
| 工作流不存在、非本租户或非工作流类型 | `404` | 资源不可见或不存在 |
| 工作流处于 `ONLINE` 状态（或登记态冲突） | `409` | 业务码 `10571`，`status_message: "Workflow changed or the registration request conflicts"`，`data: null` |
| 携带禁止的身份头或 Query 参数 | `422` | 身份依赖判定 `INVALID_INPUT` |
| 触发接口限流 | `429` | 响应含 `Retry-After` 头 |

---

## 7. 请求与响应示例

### HTTP 请求示例

```http
DELETE http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example?user_account=中数SSO编辑测试
Authorization: Bearer <KUNLIAN_API_KEY>
```

### curl 示例

```bash
curl -X DELETE \
  "http://110.16.193.170:50055/api/v2/kunlian/workflows/workflow-example?user_account=%E4%B8%AD%E6%95%B0SSO%E7%BC%96%E8%BE%91%E6%B5%8B%E8%AF%95" \
  -H "Authorization: Bearer <KUNLIAN_API_KEY>"
```

### 成功响应示例（HTTP 200）

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": null
}
```

### 工作流处于上线状态时响应示例（HTTP 409）

```json
{
  "status_code": 10571,
  "status_message": "Workflow changed or the registration request conflicts",
  "data": null
}
```

---

## 8. 核对依据（静态源代码）

- 路由定义：[kunlian_workflow_api.py](../../src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_api.py#L150-L154)
- 应用服务：[kunlian_workflow_api.py](../../src/backend/bisheng/workflow/application/kunlian_workflow_api.py#L200-L216)
- 权限与清理 Hook：[flow.py](../../src/backend/bisheng/api/services/flow.py#L499-L537)
- 单元测试：[test_kunlian_workflow_delete.py](../../src/backend/test/open_api/test_kunlian_workflow_delete.py)
