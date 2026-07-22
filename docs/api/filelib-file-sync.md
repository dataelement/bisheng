# Filelib 统一文件同步接口

本文档是 Filelib 第三方文件同步接口的唯一现行契约。文件分类、业务域和目标知识空间由本次请求使用的开发者 Token 上的 `file_sync_rule` 决定，调用方不能通过 URL 或请求参数覆盖这些业务规则。

## 1. 接口概览

```http
POST /api/v2/filelib/file/sync
Content-Type: multipart/form-data
X-Developer-Token: {plaintext-token}
```

示例 Base URL：

```text
https://{bisheng-host}/api/v2
```

调用成功表示文件记录已经创建并进入异步处理队列，不表示解析已经完成。

### 1.1 上线前置条件

每个调用 Token 必须同时满足：

1. Token 存在、已启用，且请求 IP 和限流规则允许本次请求。
2. Token 路由白名单允许 `POST /api/v2/filelib/file/sync`；若白名单拒绝，先返回 `19812`，不会读取文件同步业务配置。
3. Token 已保存一份完整的 `file_sync_rule`。未配置时统一接口返回 HTTP 403、业务码 `19906`，同一 Token 的其他已授权接口不受影响。
4. Token 绑定用户在最终目标知识空间根目录具有上传权限。配置固定目标空间或查询 options 都不会自动授予此权限。

## 2. Token 文件同步业务配置

管理员在管理后台的“开发者 Token”创建或编辑页面配置。每个 Token 最多一份配置，不支持草稿或多规则。

### 2.1 JSON 结构

```json
{
  "category": {
    "code": "POLICY",
    "subcategory_code": "MGMT_POLICY"
  },
  "business_domain": {
    "mode": "fixed",
    "code": "SAFETY"
  },
  "target_space": {
    "mode": "dynamic",
    "knowledge_id": null
  },
  "dynamic_source": "responsible_person_id"
}
```

| 字段 | 约束 |
|---|---|
| `category.code` | 必填；固定一级分类编码；保存时去除首尾空格并转大写；`[A-Z0-9_]{1,16}`。 |
| `category.subcategory_code` | 必填；必须属于上述一级分类；保存时转大写；`[A-Z0-9_-]{1,16}`。 |
| `business_domain.mode` | `fixed` 或 `dynamic`。 |
| `business_domain.code` | 业务域为 `fixed` 时必填，为 `dynamic` 时必须为 `null`。 |
| `target_space.mode` | `fixed` 或 `dynamic`。 |
| `target_space.knowledge_id` | 目标空间为 `fixed` 时必填正整数，为 `dynamic` 时必须为 `null`。 |
| `dynamic_source` | 任一维度为 `dynamic` 时必填；可选 `department_id` 或 `responsible_person_id`。两个维度均为 `fixed` 时必须为 `null`。 |

分类始终固定。业务域和目标空间可独立选择固定或动态，因此共有四种组合：

| 业务域 | 目标空间 | 固定值 | `dynamic_source` | 请求中动态必填 ID |
|---|---|---|---|---|
| fixed | fixed | 域 code、空间 ID | 必须为空 | 无 |
| fixed | dynamic | 域 code | 必填 | 配置指定的一个 ID |
| dynamic | fixed | 空间 ID | 必填 | 配置指定的一个 ID |
| dynamic | dynamic | 无域/空间固定值 | 必填 | 配置指定的一个 ID；两个动态维度共用解析结果 |

### 2.2 动态来源语义

- `department_id`：请求必须显式提供 `params.department_id`。系统在 Token 当前租户内按部门 ID 解析动态业务。
- `responsible_person_id`：请求必须显式提供 `params.responsible_person_id`。系统在 Token 当前租户内解析人员，并要求该人员恰好有一个有效主部门。

系统不会在缺少配置指定 ID 时回退到调用人、另一个 ID 或名称字段。名称与 ID 同时提供时，名称必须与 ID 对应对象一致。

### 2.3 固定引用与运行时复核

保存配置时，系统按 Token 目标租户校验分类父子关系、启用业务域、有效知识空间和固定域/空间双向绑定。调用统一接口时会再次校验，以发现配置保存后发生的删除、停用、跨租户或解绑变化。

最终域与空间必须同时满足：

```text
space.id in domain.space_ids
AND
domain.code in space.business_domain_codes
```

动态目标空间按选中部门从近到远使用既有部门知识空间解析规则；同层出现多个候选时返回冲突，不随机取第一项。

### 2.4 管理 API

配置候选项：

```http
GET /api/v1/admin/developer-tokens/config/file-sync-options
  ?tenant_id=2
  &space_page=1
  &space_limit=50
  &space_keyword=safety
```

示例成功数据：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "tenant_id": 2,
    "categories": [
      {
        "code": "POLICY",
        "label": "政策制度",
        "children": [{"code": "MGMT_POLICY", "label": "管理政策"}]
      }
    ],
    "business_domains": [{"code": "SAFETY", "name": "安全"}],
    "knowledge_spaces": {
      "data": [{"id": 118, "name": "安全环保部-部门库"}],
      "total": 1
    }
  }
}
```

- `POST /api/v1/admin/developer-tokens`：创建 Token 时可提交 `file_sync_rule`；`null` 表示不开通。
- `PUT /api/v1/admin/developer-tokens/{token_id}`：省略 `file_sync_rule` 表示保持原值；显式提交 `null` 表示关闭并清空。
- `GET /api/v1/admin/developer-tokens` 与详情接口返回非秘密的结构化配置，供管理页展示和编辑。
- 配置校验失败返回 HTTP 400、业务码 `19813`。options 只提供候选项，不授予 Token 绑定用户上传权限。

## 3. 请求参数

请求体包含两个 `multipart/form-data` 字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `file` | file | 是 | 非空文件二进制。文件格式、容量、敏感词等继续遵循知识空间现有上传策略。 |
| `params` | string | 是 | JSON 对象序列化后的字符串。 |

不要手工设置 multipart `boundary`；由 HTTP 客户端生成。

### 3.1 `params` 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `external_file_id` | string | 是 | 第三方文件标识，1～255 字符；用于回传和审计，不提供幂等保证。 |
| `file_name` | string | 是 | 最终文件名，1～200 字符；必须是 base name，不能包含 `/` 或 `\`。 |
| `department` | string | 否 | 主责单位名称；与 `department_id` 同传时必须一致。 |
| `department_id` | positive integer | 条件必填 | 当 Token 的 `dynamic_source=department_id` 时必须显式提供；否则可用于文件元数据。 |
| `responsible_person` | string | 否 | 责任人名称；与 `responsible_person_id` 同传时必须一致。 |
| `responsible_person_id` | positive integer | 条件必填 | 当 Token 的 `dynamic_source=responsible_person_id` 时必须显式提供；否则可用于文件元数据。 |

未知 `params` 字段按既有行为忽略，但任何分类、业务域或目标知识空间覆盖字段都不会参与业务解析。

两个维度均为固定时，责任人默认 Token 绑定用户，主责单位默认该用户的唯一主部门；调用人或责任人的主部门不存在/不唯一时仍会失败。

## 4. 调用示例

### 4.1 固定业务域、固定目标空间

Token 配置：

```json
{
  "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
  "business_domain": {"mode": "fixed", "code": "SAFETY"},
  "target_space": {"mode": "fixed", "knowledge_id": 118},
  "dynamic_source": null
}
```

调用：

```bash
curl -X POST 'https://{bisheng-host}/api/v2/filelib/file/sync' \
  -H 'X-Developer-Token: bst_REDACTED' \
  -F 'file=@./安全管理制度.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0001","file_name":"安全管理制度.pdf"}'
```

### 4.2 动态业务域、动态目标空间，共用责任人主部门

Token 配置：

```json
{
  "category": {"code": "REPORT", "subcategory_code": "LEAN_PROJECT"},
  "business_domain": {"mode": "dynamic", "code": null},
  "target_space": {"mode": "dynamic", "knowledge_id": null},
  "dynamic_source": "responsible_person_id"
}
```

调用：

```bash
curl -X POST 'https://{bisheng-host}/api/v2/filelib/file/sync' \
  -H 'X-Developer-Token: bst_REDACTED' \
  -F 'file=@./精益项目报告.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0002","file_name":"精益项目报告.pdf","responsible_person_id":12}'
```

## 5. 成功响应与处理状态

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0001",
    "file_id": 345,
    "file_encoding": "SGGF-POLICY-SAFETY-20260700000001",
    "knowledge_id": 118,
    "knowledge_name": "安全环保部-部门库",
    "status": 5
  }
}
```

| `status` | 含义 |
|---:|---|
| 1 | 处理中 |
| 2 | 处理成功 |
| 3 | 处理失败 |
| 4 | 重建中 |
| 5 | 排队中 |
| 6 | 解析超时 |
| 7 | 内容安全违规 |

文件编码保持 `SGGF-{一级分类编码}-{业务域编码}-{YYYYMM}{8位序号}`。同步响应通常为状态 `5`，调用方应使用现有文件查询能力继续观察解析结果。

## 6. 错误契约

文件同步业务错误使用实际 HTTP 状态，业务码位于 `data.error_code`：

```json
{
  "status_code": 404,
  "status_message": "configured target knowledge space does not exist",
  "data": {"error_code": 19903}
}
```

| HTTP | 业务码 | 场景 |
|---:|---:|---|
| 400 | `19901` | `params` JSON/字段非法；文件为空；文件名不是 base name；配置指定的动态 ID 缺失；名称与 ID 不一致。 |
| 403 | `19902` | Token 绑定用户无最终目标空间根目录上传权限。 |
| 404 | `19903` | 分类、域、空间、人员、部门、主部门或双向绑定不存在、失效或跨租户不可见。 |
| 409 | `19904` | 业务域、主部门或目标空间解析不唯一；现有上传规则判定文件内容或名称重复。 |
| 422 | `19905` | multipart 缺少 `file` 或 `params`。 |
| 403 | `19906` | Token 未配置文件同步规则，或数据库中的规则结构已损坏。 |

Developer Token 认证与访问控制错误沿用通用契约，业务码位于顶层 `status_code`；调用方不能只根据 HTTP 200 判断成功：

| 业务码 | 场景 |
|---:|---|
| `19801` | 缺少 `X-Developer-Token`。 |
| `19802` | Token、绑定租户或绑定用户无效。 |
| `19803` | Token 已禁用。 |
| `19804` | 请求 IP 不在允许范围。 |
| `19812` | 路由白名单不允许统一同步路径；优先于 `19906`。 |
| `19805` | 超过 Token 限流。 |
| `19806` | 限流存储不可用。 |

跨租户资源按不存在处理，错误消息不会确认其他租户的资源是否存在。

## 7. 幂等性、权限与审计

- 本接口不是幂等接口。`external_file_id` 只用于回传、元数据和审计，不执行唯一约束；重复提交会分别进入正常上传流程。
- 现有知识上传重复内容/名称校验仍可能返回 `19904`，但不能把它当成基于 `external_file_id` 的幂等机制。
- 文件写入目标空间根目录，保持跳过审批、先持久化后异步入队的既有同步行为。
- Token ID 仅用于服务端受控日志和 Token 审计；Header、Token 明文/密文/哈希、完整规则 JSON 都不得写入文件元数据或业务日志。
- 文件元数据记录 `external_file_id`、最终主责单位、责任人以及固定来源 `filelib_sync_endpoint=sync`。

## 8. 发布切换清单

本次切换没有兼容路由、重定向或自动迁移。

### 8.1 发布前

- [ ] 确认 Alembic 迁移仅增加 nullable `file_sync_rule`，不回填业务数据；所有既有 Token 保持 `NULL`。
- [ ] 按调用方逐个确定分类、业务域模式、目标空间模式和动态来源，不根据 Token 名称、旧白名单或历史请求自动推断。
- [ ] 在管理页为每个需要同步的 Token 人工保存完整配置，并验证绑定用户对最终空间有上传权限。
- [ ] 人工将 Token 路由白名单调整为允许统一路径；配置与白名单是两项独立操作。
- [ ] 调用方改造请求地址并完成固定/动态组合、动态 ID 缺失和异步解析状态测试。
- [ ] 安排服务端与调用方在同一发布窗口切换；旧分拆调用在新版本中会直接得到 404。

### 8.2 发布后监控

- [ ] 观察 `19812`、`19901`～`19906`、HTTP 404 和 409 的数量与 Token ID 分布，不记录 Token secret。
- [ ] 抽查成功响应的分类、业务域、`knowledge_id`、文件编码及最终解析状态。
- [ ] 确认没有调用方继续请求已移除的分拆接口。
- [ ] 确认配置缺失或失败请求仍受现有限流约束。

### 8.3 回退

1. 优先回退应用版本并保留新增 nullable 列和已保存配置；旧应用会忽略该列。
2. 应用回退若恢复旧调用契约，必须同步回退调用方和路由白名单，避免两端契约不一致。
3. 不要把 Alembic downgrade 作为首选回退。downgrade 会删除 `file_sync_rule` 列及其中配置，数据不可逆；确需执行时必须先导出配置并取得发布负责人授权。
4. 回退后记录未完成的 Token 配置、白名单和调用方切换项，重新发布时逐项核对。
