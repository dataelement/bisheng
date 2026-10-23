# F055 技术设计与部署合同

## 结构

API endpoint → MarketService → MarketRepository → SQLModel，MinIO 制品由存储适配器读写。校验器只读取 ZIP/JSON/文件摘要，服务端始终将插件作为数据处理。

五张新表：dsh_market_plugin、dsh_market_version、dsh_market_import、dsh_market_audit、dsh_market_device。表模型已加入数据库发现；按项目新表创建机制建表，既有表结构保持原样。

插件 ID 稳定，版本 ID 与 ZIP SHA-256 绑定；插件记录维护 current_version_id、disabled、deleted、revision。删除在 CAS 事务中置 deleted=true、清空当前版本并记录后台操作；普通列表和详情过滤 deleted，策略继续返回曾发布版本以支持已有安装。导入校验成功后，在同一个事务中创建不可变版本、设置当前版本、更新展示元数据、递增 revision、记录前后状态，导入任务置为 completed。版本属性 published_once 记录曾发布资格，映射既有物理列 reviewed；保持现有数据结构与历史资格。导入任务以 tenant_id + digest 幂等，当前可用插件重复导入返回原任务并保留版本；已删除、旧下架或旧禁用记录的明确重导入重新校验并恢复当前版本；失败保持原状态。validating 任务可在服务恢复后继续。旧 pending 任务对应的版本可由管理员重新导入恢复。

制品对象键为 `dsh-market/{tenant_id}/{sha256}.zip`，使用当前 BISHENG 的 MinIO bucket/config。生产环境配置持久化对象存储与数据库备份；全量历史保留。当前没有租户容量配额与自动清理任务。

## 身份和权限

- 桌面与 SPA 传递 BISHENG 签名 JWT（Bearer），也兼容现有 HttpOnly Cookie。验证 JWT、token_version，再构造 LoginUser。
- 员工目录、下载、同步从已验证 JWT 的租户与用户派生范围；管理视图不影响员工范围。
- 管理端使用现有 check_tenant_admin 应用协议；普通及全局管理员均以登录身份的 tenant_id 为当前市场范围。
- `X-DSH-Market-Tenant` 作为登录租户一致性检查，和 actor.tenant_id 不同即拒绝。管理路由移出 AdminScopeMiddleware，market_actor/market_admin 显式关闭管理视图标志并设置仅含登录租户的可见范围。
- 市场属于租户分发设置，采用租户管理员/员工二层权限；对象没有个人所有者、共享关系或继承授权，无需新增 FGA 资源类型及 tuple 投影。
- 所有读写显式添加 tenant_id 谓词，写操作同时校验 revision。JSON 字段使用 JsonType，SQL 避免绑定 MySQL 专属操作。

Desktop 的企业登录基于另外已有的网关登录工作；本次 API 接受 BISHENG JWT。若实际网关使用 opaque token，须在企业统一地址处兑换/转发为已验证 BISHENG 用户 JWT，并对齐 tenant/user 标识。客户端和前端均无法获取对象存储管理凭证。实际网关联调尚未执行。

## API v1

统一前缀 `/api/v1/dsh/market`。标准 JSON 信封为 `status_code/status_message/data`；制品返回 ZIP 二进制。

| 方法/路径 | 身份 | 内容 |
| --- | --- | --- |
| GET /capabilities | 登录员工 | contract_version=1、配置状态、tenant_id、上限与周期 |
| GET /catalog?q=&page=&size= | 登录员工 | 仅本租户当前发布版本，授权过滤后分页 |
| GET /plugins/{id}/versions/{version_id}/artifact | 登录员工 | 复核发布状态和摘要，返回 ZIP；禁止共享缓存 |
| POST /sync | 登录员工 | 设备运行状态报告，返回 Ed25519 签名策略 |
| GET /admin/context | 租户管理员 | 当前登录租户 |
| GET /admin/plugins | 租户管理员 | 本登录租户列表及分页；旧搜索/状态参数保留协议兼容 |
| GET /admin/plugins/{id} | 租户管理员 | 插件状态和全部版本；操作记录保留在后台 |
| DELETE /admin/plugins/{id}?revision= | 租户管理员 | 删除本租户市场记录，保留历史及已有安装授权 |
| POST /admin/plugins/{id}/transition | 租户管理员 | 旧 publish/unpublish/disable 协议保留兼容；当前页面使用导入和删除 |
| POST /admin/imports | 租户管理员 | multipart file，单 ZIP；上传后校验，新版本校验成功即可安装；已有可用版本重复包保持现状，已删除记录重导入恢复 |
| GET /admin/imports | 租户管理员 | 导入任务与失败原因 |
| POST /admin/imports/{id}/resume | 租户管理员 | 恢复 validating 任务 |
| GET /admin/devices | 租户管理员 | 兼容已有设备状态读取；首版管理页面使用插件与版本详情 |

错误码 26101：发布包校验；26102：并发/版本状态冲突；26103：记录或可发布制品缺失；26104：管理权限。多语言错误码遵循 locales SSOT 生成。

## 签名与离线运行

服务端环境变量 `BISHENG_DSH_MARKET_SIGNING_KEY` 载入 PKCS#8 PEM Ed25519 私钥，建议通过部署 secret 注入。Desktop 预置对应 SPKI PEM 公钥。私钥缺失时能力声明 enabled=false；错误密钥使签名失败。

`/sync` 返回 `{payload, signature}`，均为 base64url；签名覆盖原始 JSON 字节。payload 包含 tenant_id、user_id、device_id、issued_at、expires_at，以及各插件 disabled/revision/current_version_id/曾发布版本摘要。

Desktop 用部署公钥验证签名，绑定账号与设备，设置授权到期定时器。已有启用版本在有效缓存授权内可离线恢复；新增安装、更新与新增启用要求在线复核。新安装还需匹配当前发布版本，历史已发布资格只用于已有安装。

部署代理应支持 256 MiB 文件加 multipart 开销，限制整体请求体、并发和临时上传空间。应用在读取文件时再次执行大小限制；框架可能先把 multipart 暂存到磁盘，因此反向代理限制仍需配置。

## 离线发布包

ZIP 根目录 `manifest.json`，平台文件位于 `bundles/{os}-{arch}/node_modules/...`。清单结构：

```json
{
  "schema_version": 1,
  "plugin": {
    "name": "company-report",
    "version": "1.0.0",
    "display_name": "企业报表",
    "description": "生成企业内网业务报表",
    "publisher": "企业研发",
    "license": "Proprietary",
    "desktop_min": "0.1.1",
    "permissions": ["workspace:read", "workspace:write"],
    "services": ["https://reports.company.example"],
    "changelog": "首次企业发布"
  },
  "targets": {
    "darwin-arm64": {"node_modules/company-report/package.json": "64位小写SHA-256"}
  }
}
```

示例 inventory 必须由打包工具生成并列出全部文件。所有平台包的文件按清单校验；每个平台包含完整传递依赖。宿主 React/@deepseek-ai 单例由应用提供，Desktop 安装时验证实际解析位置。插件名保留宿主命名空间；拒绝目录穿越、重复路径、符号链接、特殊文件、未列出文件、缺依赖和摘要冲突。主入口必须位于插件包内。

发布工具和 Desktop 部署步骤见配套 Desktop 分支 `docs/enterprise-plugin-market.md`。

## Constitution Check

C1 分层；C2 使用 JsonType 与通用 SQL；C4 使用现有租户管理员应用协议并校验目标租户；C5 登记 261；C6 私钥通过 secret 注入；C7 前端 API 统一封装；C8 共享数据持久化到数据库及 MinIO。租户模型已登记自动过滤，同时仓库保留显式租户参数与谓词，约束设备身份和管理视图的独立范围；批量写入遵循 backend/AGENTS.md 的显式租户要求。查询范围先确定再分页，管理变更使用 CAS。3006 的 MySQL/MinIO 与签名基础检查已通过；DM8、完整认证中间件及登录用户流程验收单独列为 NOT_RUN。


## 删除字段升级与分支

环境分支通过 `f055_market_deleted` 在实际单头 `f054_merge_beta1_v26_heads` 后添加 deleted Boolean NOT NULL DEFAULT false。迁移只执行 DDL，使用共享 column_exists 守卫；已存在旧记录通过列默认值保持可见。新建表的模型声明与升级一致。

原功能分支的当前单头为 update_time_default_align，对应迁移为 f053_market_deleted。两分支均通过单头检查；后续汇合时保留各自迁移并增加显式 merge revision，DDL 守卫允许同一列已存在。环境回滚版本保留原运行代码和新迁移文件，使原服务可以识别已应用的 f055_market_deleted，同时保留删除记录。
