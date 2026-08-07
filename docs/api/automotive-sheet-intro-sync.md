# 汽车板介绍定时同步（Automotive Sheet Intro Sync）

Feature **F049** — 租户管理员在 Platform「开发者 Token」页配置上游 PDF 接口与入库目标；系统按固定策略拉取 PDF 并通过 `filelib_sync` 核心路径覆盖入库。

---

## 1. 通用约定

### 1.1 Base URL

```text
http://{bisheng-host}:7860/api/v1
```

### 1.2 认证与权限

| 项 | 说明 |
|----|------|
| 认证 | Platform 登录 JWT（Cookie `access_token_cookie`） |
| 权限 | 当前租户管理员（与 Developer Token 管理 API 一致）；全局超管可跨租户管理 |
| 租户上下文 | 读写均作用于**当前登录租户**；Celery 子任务通过 `tenant_id` header 恢复 ContextVar |

### 1.3 成功响应

与 Platform 其他 Admin API 一致：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {}
}
```

### 1.4 业务错误码（199xx 段）

| 业务码 | HTTP | message | 场景 |
|--------|------|---------|------|
| `19907` | 403 | `automotive_sheet_intro_sync_disabled` | `enabled=false` 时调用 `POST /test` |
| `19908` | 422 | `automotive_sheet_intro_sync_invalid_config` | 配置 JSON 校验失败 |
| `19909` | 502 | `automotive_sheet_intro_upstream_error` | 上游 PDF 拉取失败（非 200 / 非 PDF / 空 body / 超限） |

入库阶段继续抛既有 `FilelibSync*`（198/199 段），由编排 Service 捕获写入 `filelib_scheduled_sync_run_log`，不向外暴露给 Beat。

---

## 2. 管理 API

Base path：

```text
/api/v1/admin/developer-tokens/automotive-sheet-intro-sync
```

与 [Developer Token 管理 API](./filelib-openapi-interfaces.md) 同命名空间；路由注册在 `/{token_id}` 之前，避免路径冲突。

### 2.1 获取配置 — `GET /`

**Response `data`**：`AutomotiveSheetIntroSyncConfig`（见 §3）。无存储记录时返回默认值（`enabled=false`，`file_name=汽车板介绍.pdf` 等）。

### 2.2 保存配置 — `PUT /`

**Request Body**：与 §3 同构。

**Response `data`**：校验并持久化后的配置。

**校验规则**：

- `enabled=false`：仅校验 JSON 结构。
- `enabled=true`：校验 `api_url`、Token、分类、固定业务域、固定目标空间/目录；复用 `DeveloperTokenService._validate_file_sync_rule` + `_validate_file_sync_target`；**不允许** dynamic 模式与个人库兜底。

### 2.3 测试同步 — `POST /test`

无 Request Body；对**当前租户**派发 Celery 手动任务。

**前置**：`enabled=true`，否则返回 `19907`。

**Response `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | Celery 任务 ID |
| `task_name` | string | `bisheng.open_endpoints.worker.filelib_sync_worker.run_automotive_sheet_intro_sync` |
| `scope` | string | 固定 `"tenant"` |
| `tenant_id` | int | 当前租户 ID |
| `message` | string | 提示文案 |

行为与定时任务一致，仅 `trigger_type=manual`，metadata 写入 `filelib_sync_trigger=manual`。

### 2.4 查询执行记录 — `GET /runs`

**Query**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | ≥1 |
| `limit` | int | 20 | 1–200 |

**Response `data`**：分页结构 `{ "data": [...], "total": N }`。

单条记录字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 记录 ID |
| `job_code` | string | 固定 `automotive_sheet_intro` |
| `trigger_type` | string | `manual` \| `scheduled` |
| `status` | string | `running` \| `success` \| `failed` \| `skipped` |
| `file_id` | int \| null | 成功时知识库文件 ID |
| `knowledge_id` | int \| null | 目标空间 ID |
| `file_name` | string \| null | 固定文件名快照 |
| `error_message` | string \| null | 失败/跳过原因，≤500 字符 |
| `start_time` | datetime | 开始时间 |
| `end_time` | datetime \| null | 结束时间 |
| `duration_ms` | int \| null | 耗时（毫秒） |

---

## 3. 配置 JSON（`AutomotiveSheetIntroSyncConfig`）

存储：`config` 表，物理 key `automotive_sheet_intro_sync`（根租户）或 `automotive_sheet_intro_sync:t:{tenant_id}`。

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `enabled` | boolean | 是 | `false` | 总开关 |
| `api_url` | string | enabled 时 | — | 上游 PDF 完整 URL（`http(s)://`，≤2048） |
| `api_method` | string | 否 | `GET` | `GET` \| `POST` |
| `api_timeout_seconds` | int | 否 | `120` | 10–600 |
| `developer_token_id` | int | enabled 时 | — | 当前租户且已启用的 Token |
| `file_name` | string | 是 | `汽车板介绍.pdf` | basename，`.pdf` 结尾，≤200 |
| `external_file_id` | string | 否 | `automotive_sheet_intro` | 写入 metadata，页面不展示 |
| `category` | object | enabled 时 | — | `{ code, subcategory_code }` |
| `business_domain` | object | enabled 时 | — | `{ mode: "fixed", code }` |
| `target_space` | object | enabled 时 | — | `{ mode: "fixed", knowledge_id, folder_mode, folder_id? \| folder_path? }` |

`folder_mode`：`none`（空间根目录）或 `fixed`（指定目录）。

---

## 4. 上游 PDF 接口契约

| 项 | 要求 |
|----|------|
| URL | 配置 `api_url` |
| 方法 | `GET`（默认）或 `POST` |
| 成功状态 | `200` |
| Content-Type | 含 `application/pdf` |
| Body | 非空；校验 magic `%PDF-`；默认上限 50MB |
| 失败 | 记 `run_log.status=failed`；**不删除**库内已有文件 |

V1 不在页面配置鉴权 Header；如需 Header 鉴权，部署侧或二期扩展。

本地联调可用 mock 服务，见 `features/v2.6.0/049-automotive-sheet-intro-sync/scripts/mock_upstream_pdf.sh`。

---

## 5. Celery 与定时任务

| Beat Key | Task | Cron | 时区 |
|----------|------|------|------|
| `automotive_sheet_intro_sync_daily` | `bisheng.open_endpoints.worker.filelib_sync_worker.fanout_automotive_sheet_intro_sync` | `0 0 * * *` | Asia/Shanghai |

Fan-out 范围：根租户 + 所有 active 子租户；每个租户派发 `run_automotive_sheet_intro_sync`，header `tenant_id`。

单租户 Redis 锁：`bisheng:lock:automotive_sheet_intro_sync:{tenant_id}`，TTL 1800s；拿不到锁 → `skipped`。

---

## 6. 与 `filelib_sync` 的关系

| 维度 | 开放 API `POST /api/v2/filelib/file/sync` | 汽车板介绍同步 |
|------|-------------------------------------------|----------------|
| 触发 | 第三方实时上传 multipart | 定时 / 管理端测试 |
| 身份 | `X-Developer-Token` | 配置中的 `developer_token_id` + 绑定用户 |
| 文件来源 | 请求体 | HTTP 拉取上游 PDF |
| 入库 | `FilelibSyncService.sync()` | `FilelibSyncService.sync_from_staged_file()` |
| metadata | 标准 filelib 字段 | 额外 `filelib_sync_endpoint=automotive_sheet_intro_sync`、`filelib_sync_trigger` |
| 覆盖策略 | 同名覆盖 | 固定 `file_name` 同名覆盖 |

详见 [filelib 同步接口文档](./filelib-file-sync.md)。

---

## 7. Platform UI

路径：**系统管理 → 开发者 Token → 汽车板介绍同步**

字段与 §3 一致；不展示 `external_file_id` 与 cron。保存 / 测试同步 / 最近执行表格见 Feature spec §14。
