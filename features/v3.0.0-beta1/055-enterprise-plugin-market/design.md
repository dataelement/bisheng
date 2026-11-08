# F055 技术设计与部署合同

## 结构

API endpoint → MarketService → MarketRepository → SQLModel，MinIO 制品由存储适配器读写。校验器只读取 ZIP/JSON/文件摘要，服务端始终将插件作为数据处理。

五张新表：dsh_market_plugin、dsh_market_version、dsh_market_import、dsh_market_audit、dsh_market_device。表模型已加入数据库发现；按项目新表创建机制建表，既有表结构保持原样。

插件 ID 稳定，版本 ID 是稳定记录身份，同版本主动覆盖时 SHA-256、大小和 manifest 可更新；插件记录维护 current_version_id、disabled、deleted、revision。删除在 CAS 事务中置 deleted=true、清空当前版本并记录后台操作；普通列表和详情过滤 deleted，策略继续返回曾发布版本以支持已有安装。导入校验成功后，在同一个事务中创建版本或原位覆盖同版本内容、设置当前版本、更新展示元数据、递增 revision、记录前后状态，导入任务置为 completed。版本属性 published_once 记录曾发布资格，映射既有物理列 reviewed；保持现有数据结构与历史资格。导入任务以 tenant_id + digest 幂等，当前可用插件重复导入仍重新判断当前摘要，同版本不同内容覆盖并推进 revision；历史 completed digest 任务不得阻止 A→B→A；已删除、旧下架或旧禁用记录的明确重导入重新校验并恢复当前版本；失败保持原状态。validating 任务可在服务恢复后继续。旧 pending 任务对应的版本可由管理员重新导入恢复。

制品对象键为 `dsh-market/{tenant_id}/{sha256}.zip`，使用当前 BISHENG 的 MinIO bucket/config。生产环境配置持久化对象存储与数据库备份；全量历史保留。当前没有租户容量配额与自动清理任务。

## 身份和权限

- 桌面与 SPA 传递 BISHENG 签名 JWT（Bearer），也兼容现有 HttpOnly Cookie。验证 JWT、token_version，再构造 LoginUser。
- 员工目录、下载、同步从已验证 JWT 的租户与用户派生范围；管理视图不影响员工范围。
- 管理端使用现有 check_tenant_admin 应用协议；普通及全局管理员均以登录身份的 tenant_id 为当前市场范围。
- `X-DSH-Market-Tenant` 作为登录租户一致性检查，和 actor.tenant_id 不同即拒绝。管理路由移出 AdminScopeMiddleware，market_actor/market_admin 显式关闭管理视图标志并设置仅含登录租户的可见范围。
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
| GET /admin/plugins | 租户管理员 | 本登录租户列表及分页；旧搜索/状态参数保留协议兼容 |
| GET /admin/plugins/{id} | 租户管理员 | 插件状态和全部版本；操作记录保留在后台 |
| DELETE /admin/plugins/{id}?revision= | 租户管理员 | 删除本租户市场记录，保留历史及已有安装授权 |
| POST /admin/plugins/{id}/transition | 租户管理员 | 旧 publish/unpublish/disable 协议保留兼容；当前页面使用导入和删除 |
| POST /admin/imports | 租户管理员 | multipart file，manifest ZIP 或含 package.json 的 ZIP / npm tgz；上传后校验，新版本校验成功即可安装；已有可用版本重复包保持现状，已删除记录重导入恢复 |
| GET /admin/imports | 租户管理员 | 导入任务与失败原因 |
| POST /admin/imports/{id}/resume | 租户管理员 | 恢复 validating 任务 |
| GET /admin/devices | 租户管理员 | 兼容已有设备状态读取；首版管理页面使用插件与版本详情 |

错误码 26101：发布包校验；26102：并发/版本状态冲突；26103：记录或可发布制品缺失；26104：管理权限。多语言错误码遵循 locales SSOT 生成。

## 在线会话与发布快照

分发不使用独立签名密钥。`BISHENG_DSH_MARKET_SIGNING_KEY` 不再读取；能力声明不返回 `public_key` 或 `lease_seconds`。员工目录、制品和同步沿用本分支的原生桌面会话或平台登录身份校验；不新增席位校验。管理员身份和工作台接口保持原边界。

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

## 配置静态校验修复（2026-11-07）

用户明确授权支持受约束 config、细分错误并以原包回归；WB-08 现接受 name/id 加可选 mapping config，边界与配额以[校验规则](workbench-package-validation.md)为准。先以 YAML 事件检查资源，再 compose 语法树并检查标签、引用和表达式位置；后端绝不实例化配置节点或执行 JavaScript。仅支持开发协议 §3.3 的 config.root + dshHomePath 单层目录子集；不开放通用 !!js。未来支持新函数、路径语法或标签时，重新评估宿主执行协议并补拒绝用例。

预览、正式导入和恢复仍共用校验器，原始 TGZ 的摘要、对象存储、下载链路不变；未改数据库与权限。错误响应只在现有 26205 信封 data 中追加明细，字段及前端分类见[错误契约](workbench-upload-query-design.md)。已知坑：BaseErrorCode 的 code 参数是外层数值业务码，校验原因 code 必须存入 data，不能直接解包传参；MarketWorkbenchBundleError 接收 validation_error 明细解决冲突，API 回归同时断言两者。

修订记录：2026-11-07，修复带 config 原包误报缺少 ID 与前端丢弃原因；原包 API 回归、拒绝测试和待完成 alpha3 验收见[修复验收记录](workbench-config-fix-validation.md)。

## 工作台 TGZ 多选（2026-11-07）

按用户确认只支持直接多选 TGZ，暂不支持 ZIP。平台逐包串行预览和导入，复用已有单包 API；不增加后端路由、批次表或存储格式。允许升级和已存在包幂等处理，格式/版本冲突仅拒绝对应文件，其他通过项继续。正式导入以当时后端重检为准，批次不是跨包事务；保留各文件结果，避免把业务任务 failed 当作 HTTP 成功。具体 AC、队列隔离和验证见[多选导入规格](workbench-multiselect-spec.md)。

## 后续用户确认：覆盖、100 MiB 与工作台删除

最新完整验收见 workbench-overwrite-delete-spec.md。本次保持 dsh_market 现有架构与表结构；插件与工作台均允许完全相同版本号重导入新内容，原位更新版本 digest/size/manifest、当前展示元数据及 revision。插件仍写入包含旧/新摘要的审计；内容寻址对象不变更旧字节。低版本与身份校验保留。预览 overwrite 仅在允许覆盖且内容变化时为 true。

主动再次上传必须按当前状态重新执行，不能直接复用历史 completed 摘要任务；重复任务插入唯一键竞争恢复也走相同检查，覆盖 A→B→A。下载在存储读取之后重新检查当前版本 ID 与摘要，防止原位替换期间返回陈旧内容。客户端按详情最新摘要而非仅版本号缓存制品。

工作台压缩包上限统一 100 MiB，API 读取最多上限+1，前端同值；保留展开 256 MiB、10,000 条目、元数据 1 MiB 与静态配置安全限制。每批仍 50 个、串行预览/上传，去掉独立 64 MiB 批次总量门槛。部署代理必须容纳 100 MiB 与 multipart 开销；插件既有 512 MiB 合同保留。

工作台列表/详情暴露 revision；DELETE /api/v1/dsh/market/admin/workbenches/{id}?revision=n 使用真实 market_admin 依赖，repository 用 tenant+revision CAS 将 current_version_id 置空并推进 revision，返回 {id,deleted:true}。无数据库 schema 迁移、无历史回填、无共享内容对象删除。删后管理员/员工列表、详情及旧下载链接不可见；主动重导入可恢复，不卸载客户端已安装内容。

管理页使用既有确认组件：确认取消、Escape、关闭与 AbortSignal 生命周期统一触发 exactly-once cleanup，异步关闭和 finally 绑定各自确认身份。删除锁定重复请求，失败保留行/对话框供重试，成功清除详情并刷新列表、回退空末页；组件销毁或租户变化后忽略旧回调。
