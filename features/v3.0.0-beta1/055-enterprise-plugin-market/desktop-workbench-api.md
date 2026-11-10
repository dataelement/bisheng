# Desktop 企业工作台接口接入说明（联调契约草案）

> 状态：**供客户端并行开发；工作台接口已实现，尚未部署或与 Desktop 联调**。路径和字段按 [工作台上传与查询设计](workbench-upload-query-design.md)实现，接入具体环境前须确认该环境已部署相关代码。本文件只覆盖工作台目录、详情和原始 `.tgz` 下载；不表示包已通过 Desktop 运行验证，也不定义安装、启用、自动更新或离线授权协议。

## 1. 接口与身份

使用现有企业登录流程取得的 **DSH access token**，向同一个 BiSheng 公开地址发送请求：

```http
Authorization: Bearer <DSH access token>
```

| 方法与完整路径 | 用途 | 状态 |
| --- | --- | --- |
| `GET /api/v1/dsh/market/workbenches?page=1&size=20` | 本租户工作台目录 | 当前分支已实现 |
| `GET /api/v1/dsh/market/workbenches/{id}` | 工作台当前版本详情 | 当前分支已实现 |
| `GET /api/v1/dsh/market/workbenches/{id}/versions/{version_id}/artifact` | 下载当前版本原始 `.tgz` | 当前分支已实现 |
| `GET /api/v1/dsh/market/capabilities` | 现有安装开关与市场能力 | 已实现，见[安装开关接入说明](desktop-install-policy-api.md) |

前三个接口从已验证身份确定租户，不接收 `tenant_id`、`user_id` 或 `X-DSH-Market-Tenant` 来选择租户。不要使用管理员 Web 凭证、refresh token 或 MinIO 地址；Desktop 凭证不能调用 `/admin/*`。登录、账号、租户或 BiSheng 地址切换后，丢弃旧列表、详情和已下载的文件，并重新请求。

列表与详情成功时使用 BiSheng JSON 信封 `{status_code,status_message,data}`；须同时检查 HTTP 成功、`status_code === 200` 和字段类型。列表分页从 `page=1` 开始，`size` 范围为 1–100，默认建议 20。响应头为 `Cache-Control: no-store`；不要跨用户或租户复用缓存。

## 2. 查询列表

```http
GET {BiSheng公开地址}/api/v1/dsh/market/workbenches?page=1&size=20
Authorization: Bearer <DSH access token>
```

响应示例；ID、时间及文件信息均为示意值：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "id": "0123456789abcdef0123456789abcdef",
        "identity_kind": "repository",
        "workbench_key": "cinderzhan/dsh-media-workbench",
        "legacy_id": null,
        "package_name": "dsh-media-workbench",
        "display_name": "dsh-media-workbench",
        "description": "内容运营工作台",
        "current_version": {
          "id": "fedcba9876543210fedcba9876543210",
          "version": "0.12.6"
        },
        "verification_level": "static",
        "updated_at": "2026-10-15T00:00:00Z"
      }
    ],
    "total": 1
  }
}
```

`data.data` 是当前有可用版本的工作台数组，`data.total` 是本租户符合条件的总数；空目录返回 `[]` 和 `0`。列表只给当前版本摘要，不给原始包地址或历史版本。展示名称使用 `display_name`；`package_name` 是 npm 包名，`id` 是服务端生成的 32 位十六进制标识。不要把 `workbench_key` 中的斜杠直接拼进 URL。

## 3. 查询详情

```http
GET {BiSheng公开地址}/api/v1/dsh/market/workbenches/0123456789abcdef0123456789abcdef
Authorization: Bearer <DSH access token>
```

详情保留列表字段，并把 `current_version` 扩展为：

```json
{
  "id": "fedcba9876543210fedcba9876543210",
  "version": "0.12.6",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "size_bytes": 176881,
  "artifact_url": "/api/v1/dsh/market/workbenches/0123456789abcdef0123456789abcdef/versions/fedcba9876543210fedcba9876543210/artifact"
}
```

完整详情还包含 `package_metadata`：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `repository_url` | `string \| null` | 包声明的规范化 GitHub 仓库地址；旧包可为空 |
| `patch_entry_id` | `string` | `cordis.patch.yml` 中本包的插件树 ID |
| `server_entry`、`client_entry`、`bundle_patch` | `string` | 包内入口与 patch 的相对路径，仅供展示或诊断 |
| `license`、`node_engine` | `string \| null` | 包声明的许可证与 Node 版本约束 |
| `dependencies` | `string[]` | 声明的依赖名称，不代表包内已包含依赖 |
| `legacy_manifest` | `boolean` | 是否携带旧版 `workbench.json` |

客户端当前只需使用版本 `id`、`version`、`sha256`、`size_bytes` 和 `artifact_url` 完成下载与完整性核对。`package_metadata`、`verification_level="static"` 都不代表宿主依赖可解析或工作台可运行。

工作台身份规则：

| `identity_kind` | `workbench_key` | `legacy_id` | 客户端处理 |
| --- | --- | --- | --- |
| `repository` | 非空 `owner/repo` | `null` | 按仓库身份展示；这是新规范身份 |
| `legacy` | `null` | 非空旧 ID | 可展示与下载原包；提示旧格式，不能伪造成仓库身份或推断支持安装 |

`id` 与 `current_version.id` 用于 API 定位；工作台版本字符串遵循完整 SemVer，可含预发布段，例如 `0.3.0-desktop.1`。不要用版本号代替版本 ID，也不要用 `legacy_id` 作为新协议身份。

## 4. 下载原始包

使用详情中的 `artifact_url`，只向当前 BiSheng 地址的同源 API 路径发请求，并携带相同的 DSH access token。不得把 token 发送到响应提供的其他域名；不得根据 `package_name`、`workbench_key` 或版本号自行猜测文件地址。

```http
GET {BiSheng公开地址}/api/v1/dsh/market/workbenches/{id}/versions/{version_id}/artifact
Authorization: Bearer <DSH access token>
```

成功响应是**原始 `.tgz` 二进制**，没有 JSON 信封；`Content-Type: application/gzip`、`Content-Disposition: attachment; filename="workbench.tgz"`、`ETag: "<sha256>"`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。服务端只下发本租户的当前版本，旧版本及已切换版本的地址会失效；不会返回直连 MinIO 地址。

客户端按以下顺序处理：

1. 从详情读取 `artifact_url`、`sha256` 和 `size_bytes`；校验 URL 为本服务同源的 `/api/v1/dsh/market/workbenches/…/artifact` 路径。
2. 带 Bearer token 下载完整响应。HTTP 非成功时按 JSON 错误处理，不把错误页当压缩包；不允许认证头随跨域重定向转发。
3. 核对实际收到的字节数等于 `size_bytes`，计算原始字节的 SHA-256（64 位小写十六进制），并与详情 `sha256` 及去掉双引号后的 `ETag` 一致。`Content-Type` 或文件名不能替代摘要校验。
4. 任何核对失败都丢弃文件；版本已变化时重新获取详情再下载。通过完整性校验也只表示取得了管理员上传的原包，不表示允许安装。

## 5. 失败处理与范围

| 情况 | 客户端处理 |
| --- | --- |
| 身份过期、无权限、网络失败 | 清理当前下载结果，按现有登录流程重试；不要回退到其他租户的缓存 |
| JSON 业务码非 `200` 或字段缺失/类型错误 | 视为失败；不展示为可下载或可安装 |
| 工作台不存在、当前版本切换 | 重新查列表/详情；不要继续使用旧 `artifact_url` |
| 原包缺失、摘要/长度不符 | 丢弃文件，提示下载失败并保留诊断信息 |

业务码：`26207` 表示工作台或当前版本不存在，`26208` 表示制品缺失或校验失败，`26206` 表示并发状态冲突。客户端按 HTTP 状态、统一信封和通用失败路径实现，不以错误码作为唯一判定。二进制成功响应不解析 `status_code`，错误响应才按 JSON 处理。

现有 `/capabilities` 的 `allow_third_party_workbenches` 默认 `false`，约束第三方来源的**新增安装**；它不阻止本租户工作台目录查询和原包下载。企业工作台是否可直接安装、是否需要签名租约以及与该开关的关系，尚未确定。现有 `/sync` 签名策略只覆盖插件；客户端在本期可完成列表、详情、下载和校验，不应把工作台装入插件 `/sync` 报告，也不应仅凭这三个接口启动安装。

## 6. 联调验收

- 用两个样包分别看到仓库身份与旧身份；旧包 `workbench_key=null`，下载仍保持原始字节。
- 分页、空列表、无效 ID、切换当前版本、跨租户访问均按上述契约处理。
- 下载的字节数与 SHA-256 同详情一致；损坏、缺失和中途切换版本时不保留文件。
- 切换 BiSheng 地址、账号或租户后重新请求，不复用旧目录、详情或下载文件。

样包结构及校验结论见[工作台压缩包校验规则](workbench-package-validation.md)。目标环境部署后，应以实际 API 响应补充联调证据。
