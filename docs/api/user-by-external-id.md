# 按 external_id 查询用户 (User By External ID)

`GET /api/v1/user/by-external-id`

通过 `external_id`（人员 ID）精确查询用户信息。可见范围与 `/api/v1/user/list` 一致；响应中不包含密码等敏感字段。

**实现位置：** `src/backend/bisheng/user/api/user.py` → `get_user_by_external_id`

---

## 1. 适用场景

| 场景 | 是否合适 |
|---|---|
| 外部系统持有人员 ID，需反查 BiSheng 用户详情 | ✅ |
| SSO / 组织同步后按 `external_id` 定位本地用户 | ✅ |
| 按用户名模糊搜索 | ❌ 用 `GET /api/v1/user/list?name=...` |
| 未登录公开查询 | ❌ 需登录 |

---

## 2. 认证

- 需要登录（Bearer Token 或 Cookie）。
- 可见用户范围由当前登录者身份决定（见 §5）。

---

## 3. 请求

### 3.1 Query 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `external_id` | string | **是** | — | 外部人员 ID；首尾空格会被自动 trim |
| `source` | string | 否 | — | 用户来源；传入时精确匹配 `(source, external_id)` |
| `include_deleted` | boolean | 否 | `false` | 是否包含已禁用用户（`delete=1`） |

**`source` 常见取值：** `local`、`feishu`、`wecom`、`dingtalk`、`generic_api`

**匹配规则：**

- 数据库唯一约束为 `(source, external_id)`，同一 `external_id` 在不同 `source` 下可有多条记录。
- 不传 `source`：返回所有匹配该 `external_id` 的用户。
- 传 `source`：仅返回 `(source, external_id)` 唯一组合。

### 3.2 请求示例

```http
GET /api/v1/user/by-external-id?external_id=E001 HTTP/1.1
Host: example.com
Authorization: Bearer <access_token>
```

```http
GET /api/v1/user/by-external-id?external_id=E001&source=feishu HTTP/1.1
Host: example.com
Authorization: Bearer <access_token>
```

```bash
curl -G 'https://<host>/api/v1/user/by-external-id' \
  --data-urlencode 'external_id=E001' \
  --data-urlencode 'source=local' \
  -H 'Authorization: Bearer <access_token>'
```

---

## 4. 响应

### 4.1 统一包装

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": { ... }
}
```

### 4.2 单条匹配

仅匹配到 **1** 条记录时，`data` 直接为用户对象：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "user_id": 7,
    "user_name": "张三",
    "email": "zhangsan@example.com",
    "phone_number": "13800138000",
    "dept_id": "BS@a3f7e",
    "remark": null,
    "avatar": "https://minio.example.com/presigned/avatar/xxx",
    "source": "local",
    "external_id": "E001",
    "external_code": "E001",
    "guid": null,
    "delete": 0,
    "disable_source": null,
    "create_time": "2026-01-15T10:30:00",
    "update_time": "2026-01-20T08:00:00",
    "department_id": 21,
    "department_name": "研发部",
    "roles": [
      {
        "id": 2,
        "group_id": null,
        "name": "默认角色"
      }
    ],
    "groups": [
      {
        "id": 1,
        "name": "默认用户组"
      }
    ]
  }
}
```

### 4.3 多条匹配

同一 `external_id` 在不同 `source` 下有多条记录时：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "user_id": 7,
        "user_name": "张三",
        "source": "local",
        "external_id": "E001"
      },
      {
        "user_id": 42,
        "user_name": "张三",
        "source": "feishu",
        "external_id": "E001"
      }
    ],
    "total": 2
  }
}
```

### 4.4 字段说明

**用户基础字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | int | 用户内部 ID |
| `user_name` | string | 用户名 |
| `email` | string \| null | 邮箱 |
| `phone_number` | string \| null | 手机号 |
| `dept_id` | string \| null | 历史业务侧部门标识 |
| `remark` | string \| null | 备注 |
| `avatar` | string \| null | 头像预签名 URL |
| `source` | string | 用户来源 |
| `external_id` | string \| null | 外部人员 ID |
| `external_code` | string \| null | 外部人员编码 |
| `guid` | string \| null | SSO 账号 GUID |
| `delete` | int | 是否禁用：`0` 启用，`1` 禁用 |
| `disable_source` | string \| null | 禁用来源（组织同步等） |
| `create_time` | string | 创建时间（ISO 8601） |
| `update_time` | string | 更新时间（ISO 8601） |

**扩展字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `department_id` | int \| null | 主部门内部 ID（`department.id`） |
| `department_name` | string \| null | 主部门名称 |
| `roles` | array | 角色列表，元素：`{ id, group_id, name }` |
| `groups` | array | 用户组列表，元素：`{ id, name }` |

**不返回的敏感字段：** `password`、`password_update_time`、`token_version`

> 非超管且为用户组管理员时，`roles` / `groups` 仅返回其管辖用户组范围内的数据。

---

## 5. 权限规则

| 角色 | 可见范围 |
|------|----------|
| 超管 | 全部用户 |
| 部门管理员 | 管辖部门子树内用户 |
| 子租户管理员 | 挂载子树内用户 |
| 用户组管理员 | 所管用户组成员 ∪ 组织管辖范围 |
| 普通用户 | 不可见 |

无权限或用户不存在时，统一返回 **404**，避免泄露用户是否存在。

---

## 6. 错误响应

| 场景 | status_code | status_message |
|------|-------------|----------------|
| `external_id` 为空 | `10600` | Account or password error |
| 用户不存在 | `404` | This resource does not exist |
| 用户存在但无查看权限 | `404` | This resource does not exist |
| 未登录 / Token 无效 | `403` | No permission to operate |

```json
{
  "status_code": 404,
  "status_message": "This resource does not exist",
  "data": null
}
```

---

## 7. 与 `/api/v1/user/list` 对比

| 对比项 | `/user/list` | `/user/by-external-id` |
|--------|--------------|------------------------|
| 查询方式 | `name` 模糊匹配 `user_name` | `external_id` 精确匹配 |
| 是否支持 `external_id` | 否 | 是 |
| 分页 | 支持（`page_num` / `page_size`） | 不支持 |
| 权限模型 | 相同 | 相同 |
| 响应结构 | 始终 `{ data: [], total }` | 单条直接返回对象；多条 `{ data: [], total }` |

---

## 8. 注意事项

1. **`external_id` 与 `user_name` 可能不同**：本地用户创建时 `external_id` 通常默认等于 `user_name`，SSO 同步用户则未必。
2. **多 source 场景**：不传 `source` 可能返回多条，调用方需根据 `source` 字段区分。
3. **禁用用户**：默认过滤 `delete=1`，需显式传 `include_deleted=true`。

---

## 9. 变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1 | 2026-07-31 | 新增接口 |
