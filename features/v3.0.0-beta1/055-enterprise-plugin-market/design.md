# F055 技术设计与部署合同

## 结构

API endpoint → MarketService → MarketRepository → SQLModel，MinIO 制品由存储适配器读写。校验器只读取 ZIP/JSON/文件摘要，服务端始终将插件作为数据处理。

五张新表：dsh_market_plugin、dsh_market_version、dsh_market_import、dsh_market_audit、dsh_market_device。表模型已加入数据库发现；按项目新表创建机制建表，既有表结构保持原样。

插件 ID 稳定，版本 ID 与 ZIP SHA-256 绑定；插件记录维护 current_version_id、disabled、deleted、revision。删除在 CAS 事务中置 deleted=true、清空当前版本并记录后台操作；普通列表和详情过滤 deleted，策略继续返回曾发布版本以支持已有安装。导入校验成功后，在同一个事务中创建不可变版本、设置当前版本、更新展示元数据、递增 revision、记录前后状态，导入任务置为 completed。版本属性 published_once 记录曾发布资格，映射既有物理列 reviewed；保持现有数据结构与历史资格。导入任务以 tenant_id + digest 幂等，当前可用插件重复导入返回原任务并保留版本；已删除、旧下架或旧禁用记录的明确重导入重新校验并恢复当前版本；失败保持原状态。validating 任务可在服务恢复后继续。旧 pending 任务对应的版本可由管理员重新导入恢复。

制品对象键为 `dsh-market/{tenant_id}/{sha256}.zip`，使用当前 BISHENG 的 MinIO bucket/config。生产环境配置持久化对象存储与数据库备份；全量历史保留。当前没有租户容量配额与自动清理任务。

## 身份和权限

- 桌面与 SPA 传递 BISHENG 签名 JWT（Bearer），也兼容现有 HttpOnly Cookie。验证 JWT、token_version，再构造 LoginUser。
- 员工目录、下载、同步从已验证 JWT 的租户与用户派生范围；管理视图不影响员工范围。
- 既有市场管理接口使用现有租户管理员协议，以登录身份的租户执行业务。两张管理列表由平台请求准入提供显示范围，见下节。
- `X-DSH-Market-Tenant` 作为登录租户一致性检查，和 actor.tenant_id 不同即拒绝。既有市场管理路由继续由 market_actor/market_admin 绑定登录租户。两个管理列表 GET 是例外，走平台管理请求准入。
- 市场属于租户分发设置，采用租户管理员/员工二层权限；对象没有个人所有者、共享关系或继承授权，无需新增 FGA 资源类型及 tuple 投影。
- 所有读写显式添加 tenant_id 谓词，写操作同时校验 revision。JSON 字段使用 JsonType，SQL 避免绑定 MySQL 专属操作。

在 `feat/bisheng-work-110` 上，Desktop 使用毕昇原生桌面会话；市场通过已有在线会话校验用户和租户，也保留平台登录 JWT / HttpOnly Cookie 的既有入口。不依赖 Gateway、席位或独立市场签名私钥。客户端和前端均无法获取对象存储管理凭证。

## API v1

统一前缀 `/api/v1/dsh/market`。标准 JSON 信封为 `status_code/status_message/data`；制品返回 ZIP 二进制。

| 方法/路径 | 身份 | 内容 |
| --- | --- | --- |
| GET /capabilities | 已登录员工 | contract_version=2、tenant_id、上限与同步周期；响应 `Cache-Control: no-store` |
| GET /catalog?q=&page=&size= | 已登录员工 | 仅本租户当前发布版本，授权过滤后分页 |
| GET /plugins/{id}/versions/{version_id}/artifact | 已登录员工 | 复核发布状态和摘要，返回制品；禁止共享缓存 |
| POST /sync | 已登录员工 | 设备运行状态报告，返回未签名发布快照；响应 `Cache-Control: no-store` |
| GET /admin/context | 租户管理员 | 当前登录租户 |
| GET /admin/plugins | 全局超管或租户管理员 | 查询管理视图下的插件列表及分页；旧搜索和状态参数继续使用 |
| GET /admin/workbenches | 全局超管或租户管理员 | 查询管理视图下的工作台列表及分页 |
| GET /admin/plugins/{id} | 租户管理员 | 插件状态和全部版本；操作记录保留在后台 |
| DELETE /admin/plugins/{id}?revision= | 租户管理员 | 删除本租户市场记录，保留历史及已有安装授权 |
| POST /admin/plugins/{id}/transition | 租户管理员 | 旧 publish/unpublish/disable 协议保留兼容；当前页面使用导入和删除 |
| POST /admin/imports | 租户管理员 | multipart file，manifest ZIP 或含 package.json 的 ZIP / npm tgz；上传后校验，新版本校验成功即可安装；已有可用版本重复包保持现状，已删除记录重导入恢复 |
| GET /admin/imports | 租户管理员 | 导入任务与失败原因 |
| POST /admin/imports/{id}/resume | 租户管理员 | 恢复 validating 任务 |
| GET /admin/devices | 租户管理员 | 兼容已有设备状态读取；首版管理页面使用插件与版本详情 |

错误码 26101：发布包校验；26102：并发/版本状态冲突；26103：记录或可发布制品缺失；26104：管理权限。多语言错误码遵循 locales SSOT 生成。

## 两张列表跟随平台管理视图

代码已实现，现场验收待执行。目标版本为 3.1.0-beta1，验收对应 [AC-MS-01～03](spec.md#管理视图验收)。

### 实现方案

1. 复用现有 `GET /api/v1/dsh/market/admin/plugins` 与 `GET /api/v1/dsh/market/admin/workbenches`。只将这两个 GET 注册为平台租户范围请求，并在现有浏览器请求规则中为它们附带选中租户。已有准入先验证身份和选中值，再把这个值交给原列表查询。全局超管使用所选租户，租户管理员只查询登录租户。桌面凭据和普通员工不能访问管理列表。
2. 两张表继续使用现有分页、排序和查询服务。筛选在数据库分页前完成，列表和总数使用同一租户。响应继续使用 `{data, total}`，查看其他租户时增加 `read_only: true`，并仅保留现有表格展示所需的字段，剔除完整版本清单、截图与下载链接、操作版本号。其他市场入口继续使用登录租户，原有操作鉴权保持有效。
3. 现有右上角切换继续重载页面；市场页同时监听既有 `bisheng:management-scope-changed` 确认事件，以本地刷新序号重建当前列表面板。在宿主保留页面挂载时也立即清空分页、详情、导入状态和旧请求；当前插件/工作台页签保持不变，列表从第 1 页重查。刷新序号不是租户授权来源，租户仍由现有请求层的服务端确认上下文决定。不新增全局租户状态、事件或页面。收到只读列表时隐藏操作入口，切回本租户恢复原界面。

### 取舍与验证

前端已有正确的切换状态，但当前后端列表会强制使用登录租户，仅在前端筛选会漏掉目标租户的记录。改动范围因此限定在两个现有 GET 的租户来源及两张表的只读展示。放弃新增专用列表接口，避免同一列表有两套契约。未来若这些列表成为外部集成的公开接口，再考虑独立版本。

回归验证覆盖全局超管切换两个租户后记录和总数正确，分页重置、旧响应不会覆盖新列表，以及租户管理员无法借请求头跨租户查询。查看其他租户时页面只读，直接调用详情、导入或删除仍受原权限限制。桌面目录同登录租户的对照行为保持一致。

2026-11-19 补充：市场页原先只用 `user_id:tenant_id` 作为重建标识；切管理视图不改变登录租户，整页重载之外的已挂载面板不会重新查询。`PluginMarketPage` 现按上述确认事件重建活动面板；组件回归覆盖登录租户不变、第二页重置、旧确认失效和迟到响应。真实请求适配器同时验证 `X-Management-Tenant` 随确认视图变更，而 `X-DSH-Market-Tenant` 继续保留登录租户，避免把显示范围误当作操作权限。

发布时前后端一起更新。两个列表变更为平台租户请求后，旧前端没有发送全局超管所需的管理租户证明。

设计沿用 [架构宪法 C1～C8](../../../docs/constitution.md)。不改表结构、存储、错误码、桌面协议或管理状态模型。

## 在线会话与发布快照

分发不使用独立签名密钥。`BISHENG_DSH_MARKET_SIGNING_KEY` 不再读取；能力声明不返回 `public_key` 或 `lease_seconds`。员工目录、制品和同步沿用本分支的原生桌面会话或平台登录身份校验；不新增席位校验。既有管理操作和 Desktop 工作台接口保持原来的身份范围。

`/sync` 直接返回 `{tenant_id, user_id, device_id, synced_at, policies}`。`policies` 含各插件 disabled、revision、current_version_id 及曾发布版本摘要。`synced_at` 为服务端秒级时间。响应禁止缓存。

会话撤销或到期后停止使用；短暂断网只停止进程并保留安装记录，恢复连接后按用户开关重新启用。服务端确认下架、禁用或摘要变化时关闭用户开关。制品仍按 SHA-256、路径和平台校验。新安装还需匹配当前发布版本，历史已发布资格只用于已有安装。

部署代理应支持 512 MiB 文件加 multipart 开销，限制整体请求体、并发和临时上传空间。应用在读取文件时再次执行大小限制；框架可能先把 multipart 暂存到磁盘，因此反向代理限制仍需配置。

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

## 社区 npm 包导入

插件上传接受 manifest ZIP，以及以 package.json 声明身份的 ZIP / npm `.tgz`（含 `.tar.gz` 后缀）。社区包采用 schema_version=2、format=npm；名称、版本、入口和平台兼容性来自 package.json，支持预发布版本的比较。包校验不执行代码，继续限制大小、展开量、文件数、安全路径、重复路径和特殊文件。下载保持原始制品与 SHA-256，gzip 制品返回 `application/gzip`。

本轮沿用 PR #2502 的社区包解析和版本比较实现。原 manifest ZIP 的完整依赖检查保持原语义；npm 包的真实依赖解析、安装及宿主运行由客户端负责，服务端静态校验不等于安装验收。工作台 `.tgz` 保持独立验证和独立路由。

## Constitution Check

C1 分层；C2 使用 JsonType 与通用 SQL；C4 使用现有租户管理员应用协议并校验目标租户；C5 登记 261；C6 分发依赖已有在线会话，不另存市场签名私钥；C7 前端 API 统一封装；C8 共享数据持久化到数据库及 MinIO。租户模型已登记自动过滤，同时仓库保留显式租户参数与谓词，约束设备身份和管理视图的独立范围；批量写入遵循 backend/AGENTS.md 的显式租户要求。查询范围先确定再分页，管理变更使用 CAS。DM8、完整认证中间件及登录用户流程验收单独列为 NOT_RUN。


## 删除字段升级与分支

环境分支通过 `f055_market_deleted` 在实际单头 `f054_merge_beta1_v26_heads` 后添加 deleted Boolean NOT NULL DEFAULT false。迁移只执行 DDL，使用共享 column_exists 守卫；已存在旧记录通过列默认值保持可见。新建表的模型声明与升级一致。

原功能分支的当前单头为 update_time_default_align，对应迁移为 f053_market_deleted。两分支均通过单头检查；后续汇合时保留各自迁移并增加显式 merge revision，DDL 守卫允许同一列已存在。环境回滚版本保留原运行代码和新迁移文件，使原服务可以识别已应用的 f055_market_deleted，同时保留删除记录。

## 工作台扩展（2026-10-15）

工作台使用独立的 `.tgz` 静态校验器、三张租户表和 MinIO 对象前缀，与原有插件 ZIP、设备报告和 `/sync` 发布快照分开。管理员预览与导入、Desktop 目录/详情/制品下载复用市场身份边界；管理页面沿用现有市场交互与组件。新表由 SQLModel 模型发现和 `create_all(checkfirst=True)` 创建，不改动已有市场表。完整数据结构、API 与边界见[工作台上传与查询设计](workbench-upload-query-design.md)，归档规则见[工作台压缩包校验规则](workbench-package-validation.md)。

独立存储与路由用于区分工作台包与插件包；即使后缀同为 `.tgz`，也按各自协议验证。本轮不新增工作台安装或运行授权协议。已知边界：压缩包静态检查无法证明宿主服务、依赖解析与 UI 运行，真实 MinIO、MySQL/DM8 和 Desktop 联调需在部署环境验收。
