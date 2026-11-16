# 企业工作台上传与客户端查询设计

> 状态：服务端接口、静态校验和管理页已实现，尚未部署或与 Desktop 联调。交付范围为管理员上传 `.tgz`、管理页查看导入结果，以及 Desktop 按已验证身份查询本租户工作台元数据和下载原始包。安装、离线签名策略和运行验收仍需后续客户端联调，不能由“查询或下载成功”推定。
>
> 压缩包规则见 [工作台压缩包校验规则](workbench-package-validation.md)。外部协议依据：[DSH 工作台开发规范](https://dshdesktop.com/workbench/docs/development/) 与 [工作台市场验收规范](https://dshdesktop.com/workbench/docs/market-acceptance/)；BiSheng 当前插件市场实现见 [F055 设计](design.md)。

## 1. 目标与边界

- 租户管理员在「客户端 → 企业插件」选择工作台 `.tgz`，预览身份、版本、校验结果后上传。上传成功后本租户客户端可查询工作台信息并下载当前版本的原始包；其他租户不可见。
- 保留原始压缩包和 SHA-256，支持相同文件幂等上传、较新版本更新、失败任务查询与恢复。不能用本地 API 节点的磁盘作为持久化来源。
- 新规范包的身份为 `package.json.repository` 规范化的 `owner/repo`。旧包只保存明确的 `legacy_id`，以 `identity_kind` 与新身份区分。
- 查询和下载接口**不指示客户端安装**。两个现有安装开关保持原值和默认关闭语义；`allow_third_party_workbenches` 不影响本租户目录查询或原始包下载。企业分发是否属于“第三方工作台安装”的例外，须在设计真正的客户端安装流程前明确，不在本期偷偷改变策略。
- 不接入公开 `awesome-dsh-workbench` 投稿、npm/GitHub 抓取、服务端执行压缩包、自动构建、自动验证 Desktop UI，也不迁移现有本机工作台安装状态。

## 2. 当前实现与复用点

现有 `/api/v1/dsh/market` 插件市场使用 `market_admin` 校验租户管理员、`market_actor` 校验员工/Desktop 身份；`MarketService` 协调仓库与 MinIO，插件导入任务和版本通过 SQLModel 持久化。平台页已有上传预览、进度、列表与失败任务样式。工作台沿用此调用链、身份边界、统一响应信封与平台请求封装；校验器、表、MinIO key 和路由单独命名，不把 `.tgz` 塞进只支持 ZIP 的插件校验器或插件表。

遵循 [BiSheng 架构约束](../../../docs/constitution.md)：Endpoint → Service → Repository → DB；MySQL/DM8 使用可移植列型与 `JsonType`；多节点共享字节放 MinIO，元数据放数据库；管理员与员工均仅访问登录租户。新表按 SQLModel 模型发现机制创建；若实现时存在依赖这些表的同版本迁移，再按当时 Alembic 单头决定是否补显式建表 revision。

## 3. 数据结构与状态

建议新增三张工作台专用表，名称仅作设计标识，编码时遵守现有命名与索引长度限制：

| 表 | 主要字段与约束 | 职责 |
| --- | --- | --- |
| `dsh_market_workbench` | `id`、`tenant_id`、`identity_key`、`identity_kind`、`workbench_key`、`legacy_id`、`package_name`、`display_name`、`description`、`current_version_id`、`revision`、`updated_at`；租户内 `identity_key` 和 `package_name` 各唯一 | 一个租户的工作台条目。内部 `identity_key` 用 `github:<owner/repo>` 或 `legacy:<旧ID>` 防止空值唯一约束失效；对客户端只展示明确的身份字段。 |
| `dsh_market_workbench_version` | `id`、`tenant_id`、`workbench_id`、`version`、`digest`、`size`、`manifest(JsonType)`、`created_at`；租户/工作台/版本唯一 | 不可变版本与经过白名单归一化的包元数据。`manifest` 仅包含服务端需要的字段，不回传完整 `package.json`。 |
| `dsh_market_workbench_import` | `id`、`tenant_id`、`actor_id`、`digest`、`display_name`、`status`、`error_code`、`error`、`version_id`、`created_at`；租户/摘要唯一 | 可恢复的导入任务与失败原因。可选的展示名称存入任务以便恢复；状态 `validating/completed/failed`；`completed` 只表示静态校验与持久化完成。 |

相同租户与压缩包摘要重复上传返回既有完成任务；失败任务可重新验证。同一 `identity_key + version` 对应不同摘要报版本冲突，较低的 SemVer 不自动覆盖当前版本。新版本通过后，在一次数据库事务中写入不可变版本、切换 `current_version_id`、递增 revision 并完成任务；失败保留旧当前版本。SemVer 比较必须正确处理预发布段，不能复用插件仓库当前只对数字三段 `split(".")` 的比较。

原始字节存入 `dsh-market/workbenches/{tenant_id}/{sha256}.tgz`，与现有插件 `.zip` key 分开。先完成归档安全与元数据校验，再写入对象存储并建任务；恢复任务时从 MinIO 复读并重新校验摘要与内容。上传中断或数据库提交失败时，任务可按摘要恢复校验。对象清理和配额治理留待后续，不能在此阶段删除已有版本的原始包。

## 4. API 契约

前缀 `/api/v1/dsh/market`。JSON 继续使用 `status_code/status_message/data` 信封；业务成功检查 `status_code === 200`。管理员路由仅接受 Web 登录管理员，Desktop DSH access token 只能访问员工路由。租户来自已验证身份；管理端 `X-DSH-Market-Tenant` 仅校验其与登录租户一致，员工/Desktop 不传租户选择参数。

| 方法与路径 | 身份 | 本期作用 |
| --- | --- | --- |
| `POST /admin/workbenches/imports/preview` | 租户管理员 | `multipart/form-data`，字段 `file`；执行 WB 静态规则及版本冲突预览，不写 DB/MinIO。 |
| `POST /admin/workbenches/imports` | 租户管理员 | `multipart/form-data`，字段 `file`、可选 `display_name`；持久化原包与导入任务，返回任务状态。 |
| `GET /admin/workbenches/imports` | 租户管理员 | 最近导入任务、失败规则号与可恢复状态。 |
| `POST /admin/workbenches/imports/{task_id}/resume` | 租户管理员 | 仅恢复 `validating` 或 `failed` 且原包仍在 MinIO 的任务；再次运行同一校验器。 |
| `GET /admin/workbenches?page=&size=` | 租户管理员 | 本租户全部已成功导入的工作台及当前版本，分页。 |
| `GET /workbenches?page=&size=` | 已登录员工/Desktop | 本租户当前工作台的分页元数据目录，`size` 范围 1–100；不返回失败任务。 |
| `GET /workbenches/{id}` | 已登录员工/Desktop | 指定工作台的当前版本元数据；`id` 是服务端不含斜杠的 UUID，不直接将 `owner/repo` 放进 URL。 |
| `GET /workbenches/{id}/versions/{version_id}/artifact` | 已登录员工/Desktop | 下发本租户工作台**当前版本**的原始 `.tgz` 字节；旧版本、其他租户、未完成导入任务不可下载。 |

预览响应的 `data` 建议固定为：

```json
{
  "package_name": "dsh-media-workbench",
  "identity_kind": "repository",
  "workbench_key": "cinderzhan/dsh-media-workbench",
  "legacy_id": null,
  "incoming_version": "0.12.6",
  "current_version": null,
  "suggested_display_name": "dsh-media-workbench",
  "allowed": true,
  "duplicate": false,
  "reason": "",
  "warnings": ["runtime_not_verified"]
}
```

无仓库身份但满足旧包规则时 `identity_kind="legacy"`、`workbench_key=null`、`legacy_id` 为旧 ID，`warnings` 包含 `legacy_identity`。`display_name` 用管理员输入优先，其次旧清单 `title`，最后包名；不能靠解析或执行客户端 JS 获得标题。管理员输入只影响展示，不改变原包摘要或工作台身份。

员工列表返回 `data: {data: WorkbenchSummary[], total: number}`。摘要字段为 `id`、`identity_kind`、`workbench_key`、`legacy_id`、`package_name`、`display_name`、`description`、`current_version: {id, version}`、`verification_level`、`updated_at`；详情返回同一摘要字段和当前版本细节：

```json
{
  "id": "<32-char-server-id>",
  "identity_kind": "repository",
  "workbench_key": "cinderzhan/dsh-media-workbench",
  "legacy_id": null,
  "package_name": "dsh-media-workbench",
  "display_name": "dsh-media-workbench",
  "description": "DSH Desktop 内容运营工作台",
  "current_version": {
    "id": "<32-char-version-id>",
    "version": "0.12.6",
    "sha256": "<64-char-lowercase-hex>",
    "size_bytes": 176881,
    "artifact_url": "/api/v1/dsh/market/workbenches/<id>/versions/<version_id>/artifact"
  },
  "verification_level": "static",
  "updated_at": "<UTC-ISO-8601>"
}
```

查询响应设置 `Cache-Control: no-store`，避免登录、切换租户后混用旧目录。客户端仍须比对登录状态、业务码和字段类型；请求失败或格式错误不推断为“可安装”。`artifact_url` 是同源相对 API 路径，供客户端带现有 DSH access token 发起请求；不返回 MinIO 地址、存储凭证、原始 `package.json`、安装脚本或业务数据。

制品接口成功时直接返回 gzip/tar 原始字节，**不包 JSON 信封**；`Content-Type: application/gzip`、`Content-Disposition: attachment; filename="workbench.tgz"`、`ETag: "<sha256>"`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。客户端从详情取得 `artifact_url`、`sha256` 和 `size_bytes`，用相同身份下载，并在交给安装器前计算实际字节的 SHA-256、核对长度及 `ETag`；任何不一致均丢弃文件。服务端按已验证租户、工作台 ID 和当前版本 ID 读取数据库，以租户及摘要定位 MinIO 原包，复算 SHA-256；返回前复查当前版本未切换。对象缺失、摘要不符或版本状态变化时返回错误，绝不下发未经验证的字节，也不提供直连 MinIO 地址。旧格式包可以按原样下载，但 `identity_kind=legacy` 与 `verification_level=static` 必须随详情呈现，下载不等于客户端支持安装。

详情在上述字段之外返回 `package_metadata` 白名单对象：`repository_url: string|null`、`patch_entry_id: string`、`server_entry: string`、`client_entry: string`、`bundle_patch: string`、`license: string|null`、`node_engine: string|null`、`dependencies: string[]`、`legacy_manifest: boolean`。列表不传完整版本历史；详情亦不暴露或执行包内 JS。`verification_level` 只描述服务端对压缩包做过的检查，不代表 Desktop 兼容性结论。

错误码沿用市场模块 262：`26205` 工作台包校验失败、`26206` 并发导入冲突、`26207` 工作台或当前版本不存在、`26208` 工作台制品缺失或校验失败；已在 `api_errors` 域补齐中、英、日文案。预览返回 `allowed=false` 和 `reason` 表示已有身份/版本冲突；正式导入任务以 `failed/error_code` 保存这类冲突。认证错误沿用当前市场身份边界。制品接口失败仍返回 JSON 错误响应；成功响应是二进制。

## 5. 上传、查询、下载与页面流程

1. 管理员选 `.tgz`。前端仅作扩展名、体积初筛；服务端按 gzip/tar 内容检查。预览返回身份来源、版本、重复/冲突和旧包提示。
2. 管理员确认上传。API 限制请求体与读取量，重新运行完整静态校验（不能相信先前预览）；校验通过后按租户写 MinIO，创建或复用导入任务；Service 从原始字节计算摘要，Repository 在事务内更新当前版本。恢复任务时复读 MinIO 并再次运行同一校验器。反向代理也需限制 multipart 总大小和并发，因为框架可先将文件暂存到磁盘。
3. 页面以「插件 / 工作台」区分两类列表，沿用现有上传、详情、进度和失败任务交互；工作台详情展示身份来源及 `verification_level=static`。新 UI 文案进入三语言 locale，不修改组件库视觉规范。
4. Desktop 使用现有企业登录取得的 DSH access token 请求员工列表与详情，从详情的 `artifact_url` 下载当前版本 `.tgz`，核对响应长度与 SHA-256。平台已上传的包在本期可以下发，但没有签名授权、安装或自动更新接口；客户端不得将 `verification_level=static` 或下载成功当作安装许可。

未来若要实际从企业市场安装，需明确短期签名策略，并在 Desktop 真实版本上验证依赖解析、Harness 重启、provider 注册和工作台 UI。签名 `/sync` 当前只包含插件策略，不能仅凭本期查询/下载接口复用为工作台授权。企业包是否豁免 `allow_third_party_workbenches=false` 的本地第三方安装禁令，需在安装契约中单独确认并写入客户端接入说明。

## 6. 实施位置与验收

- 后端：`bisheng/dsh_market` 增加独立的 tar 校验、工作台 Service/Repository/SQLModel 与路由；复用当前 `market_actor`/`market_admin`、MinIO 连接和统一响应。既有插件 ZIP 导入与 `/catalog` 行为不变。
- 前端：`controllers/API/dshWorkbenches.ts` 提供工作台请求类型与方法；市场页增加工作台内容区，遵守平台 AGENTS 与设计规范。
- 文档：Desktop 并行开发依据[客户端工作台接入说明](desktop-workbench-api.md)；实现后更新本目录的 `spec.md`/`design.md`/`tasks.md` 与客户端说明中的实际交付状态，不得把本设计稿写成已上线能力。
- 后端验收：两个原始样包、结构/身份/版本冲突、危险 tar、资源限制、幂等与任务恢复、租户隔离和管理员权限；单头 Alembic 检查及 MySQL/DM8 SQL 兼容复核。
- 前端验收：预览与正式上传结果一致、失败保留旧列表、租户切换清理状态、旧包提示及分页；`pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`。
- 客户端联调：验收认证后列表/详情读取、当前版本原包下载、SHA-256 复核与租户隔离；安装、重启后加载和 UI 实测单列为后续任务，不能用本期服务端/API 测试代替。

当前分支已完成实现与无外部中间件的接口测试；数据库模型使用 `create_all()` 机制建新表。真实 MinIO、MySQL/DM8、企业登录网关及 Desktop 安装运行尚待环境联调，不能用本地测试替代部署验收。
