# F114 Vibe 应用操作与 F048 权限动作统一 — 需求发现与映射评审

> 状态：2026-10-30 用户已确认 36 项映射并要求进入正式规格；同日追加具体租户单选，并按用户同意的复审建议补充代发布自审、预览用途和取消资格。正式规格见 spec.md，规格与修订设计均已确认；本地实现已接线，真实E2E与最终L2待完成，证据见verification。
> 日期：2026-10-30（Asia/Taipei）。基线：`origin/feat/3.0.0@cfcefd6577744c7807f30ce77de4e1b4050074ff`。
> 分支：`codex/114-vibe-permission-actions`；独立工作树：`/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng`。

## 1. 需求变更

用户最新要求：“修改下需求，统一下所有的 vibeapp 相关操作 → 映射到现有的权限操作”。这取代上一轮“本轮只统一删除权限”的范围。

目标是以已有 `app` 资源及 F048 具体动作作为同一应用在界面、API、CLI/MCP 的资源授权依据，移除动作校验之后额外叠加的“必须是原创建人”“创建人停用后才能由管理员处理”等资格分支；前端根据同一授权结果显示入口。

本轮需求映射已由用户确认，正式 spec 已由用户确认，已完成设计确认并进入实施；本轮替代合同及代码按tasks逐项接线，未完成部分不视为已交付。

## 2. 已核对的现状

- `app` 已注册六个动作：`use`、`edit`、`manage_permission`、`delete`、`publish`、`unpublish`。`read`、`view_log`、`export`、`secret` 等不是该资源当前有效动作，本次不另造这些动作，也不扩展其它资源的动作范围。
- 已有 F048 `viewer/editor/manager/owner` 等权限模型；最终是否允许以模型当前生效的具体动作集合为准，不能在业务层硬编码某模型名字等于某权限。
- 构建列表和部分详情已经使用 `edit`；状态服务、数据、日志、密钥、部署和部分运行时管理仍各自有 owner/管理员分支，形成列表、详情、按钮、接口不一致。
- 最新已交付删除逻辑是原创建人或超管可删、租户管理员仅清理失效 owner。该逻辑也属于本次待替换对象。
- CLI 的 `app:manage` 是开放通道权限位，当前不向个人令牌签发；发布管线额外按 `resource_owner_user_id` 比较 app.owner。CLI 日志还会构造归属人的兼容 UserPayload。统一时需要保留真实凭据主体，不能靠替换为 owner 身份获得 app 授权。
- 运行时 profile/公共依赖、宿主隔离/K8s 能力报告属于平台运维；SDK 附件和内部 manager 回调另有应用运行期凭据、访问者身份或内部签名。这些并非可以全部替换成一个用户 app:edit 的同类调用。

## 3. 拟采用的六类动作语义

| 动作 | Vibe 操作范围 | 不由该动作单独授予的能力 |
| --- | --- | --- |
| `use` | 在应用广场发现并进入允许访问的应用，HTTP/WebSocket 业务访问 | 管理源码、生产表、日志、环境变量或部署实例 |
| `edit` | 查看和维护应用管理内容：元信息、源码/版本内容、日志、生产数据、环境变量、应用私有依赖与数据快照 | 发布上线、下线、删除整个应用、修改授权 |
| `publish` | 提交发布审批、撤回应用发布、手动上线、恢复上线及启动新的正式运行配置 | 跳过发布审批、代替审批人同意/拒绝、直接改授权 |
| `unpublish` | 下线正式应用并停止其对外服务 | 删除代码/数据库/附件等资产 |
| `delete` | 显式删除整个应用及其资产 | 删除在线应用、绕过确认或删除其他应用的资产 |
| `manage_permission` | 查看和维护该应用的授权、可见范围 | 隐式取得其它管理动作；实际权限仍查 F048 |

**有意采用的权限粒度**：由于不新增 read/log/export/secret 等动作，`edit` 同时承载管理内容的读写。被授予 edit 的用户将能查看、编辑和导出应用生产数据、查看日志，以及新增/替换/删除环境变量；不再因为不是原创建人被拒绝。只持 use 的业务用户没有这些管理能力。

环境变量仍不提供已保存明文的读取/回显接口，不因权限统一增加密钥明文返回。预检/管理预览/审批预览不注入真实值，保存不自动重建，生效仍需二次确认。

## 4. 全入口映射清单（建议）

表中“任一管理动作”是 `edit OR publish OR unpublish OR delete OR manage_permission`；“且”表示必须同时满足。所有条件都针对同一个 app，不得把应用 A 的动作用于应用 B。

| 编号 | 操作/入口 | 拟要求的动作 | 业务状态与数据范围 |
| --- | --- | --- | --- |
| M01 | client 广场、统一应用入口、HTTP/WebSocket 访问 | `use`；列表按 F048 可见投影 | 仍验证登录、租户、应用态、访问者身份；撤权/停用断开连接 |
| M02 | 构建管理列表、基础详情、实例/运行状态 | 任一管理动作 | 显示获授权的应用；只持 delete/unpublish 的用户也能确认操作对象；只读基础信息不夹带源码/数据/环境值 |
| M03 | 发布进度、版本号、发布说明、审批结果等管理摘要 | 任一管理动作 | 目标应用/版本/发布尝试必须匹配，不暴露未授权的源码正文 |
| M04 | 编辑名称、描述、图标等元信息 | `edit` | 保留并发保护、审计，不变更 app.owner 或 tenant |
| M05 | 源码快照、源码文件、完整 manifest、版本内容与差异 | `edit` | 版本及路径隔离；审批人审读走 M26 的临时业务授权 |
| M06 | 运行日志、构建/预检的详细诊断 | `edit` | 仍脱敏、保留时间/数量限制；CLI/MCP 同动作 |
| M07 | 数据表清单、结构、行查询、整表/选中数据导出 | `edit` | 只读应用自建表；保留行数、文件、导出数据范围限制 |
| M08 | 编辑生产数据行 | `edit` | 二次确认、审计、主键/字段白名单；不开放任意 SQL 或 DDL |
| M09 | 环境变量名称、配置状态、配置差异读取 | `edit` | 可管理完整配置项，历史密文不回显明文 |
| M10 | 新增、替换、删除某个环境变量值 | `edit` | 保存加密、审计、CAS；删除配置项不等于 delete 整个应用 |
| M11 | 确认用最新环境配置重建正式实例 | `edit AND publish` | 同版本重建、用户确认、在线版本/配置指纹/租约一致性；保存配置仍不触发重建 |
| M12 | 查看/维护应用私有离线依赖及其可用状态 | `edit` | 不修改公共镜像/profile；保留 digest、架构及缓存隔离 |
| M13 | 读取应用数据库快照列表与内容（现有管理能力） | `edit` | 下载/恢复票据绑定 app、tenant、快照；不新增不存在的下载入口 |
| M14 | 数据快照恢复 | `edit`；若包含正式实例启动还需 `publish` | 仍确认破坏性影响、停旧 writer、独占维护、恢复验证；不得借 edit 绕过启动资格 |
| M15 | CLI 迭代 deploy：代码包/镜像/依赖与发布声明上传后提交发布 | `edit AND publish` | 保留包校验、扫描、预检、冻结快照与必审；实际执行主体查 F048 |
| M16 | 首次创建应用并首次提交发布 | 现有创建资格 + 创建后按本次所需动作初始化/校验 F048 | 无目标 app 时不伪造一个可授权对象；保留单命令首发体验。初始授权须可追溯、限定该 app，不授全租户权限；见 §6 |
| M17 | 更改资源档位、运行 profile、启动配置、能力声明后重新发布 | `edit AND publish` | 改声明须经现有发布管线，不直接编辑冻结版本或 manager 状态 |
| M18 | 上线/手动上线/重新上线已有已批准版本 | `publish` | 审批和容量准入、探活、路由切换继续有效；未批准不能上线 |
| M19 | 下线正式应用 | `unpublish` | 二次确认、停止执行体、保留资产、审计 |
| M20 | 应用发布的主动撤回 | `publish` | 允许有 publish 的非原创建人操作；限本 app 的可撤回在途发布，审计实际操作者；不能更改审批终态 |
| M21 | 取消运行时管理操作 | 当前取消者具备原业务操作所需全部动作 | 已批准版本上线取消需 publish；环境变量配置确认重建/新版本发布取消需 edit AND publish；恢复不启动需 edit，包含启动还需 publish。仍受原可取消阶段和安全清理约束 |
| M22 | 旧运行绑定导入、升级与重绑（退役） | 不提供；持有 edit/publish 也不能执行 | AC-57、AC-71；同版本环境变量确认重建复用 M11，代码/镜像/运行环境变更复用 M15、M17；本次不新增独立通用重建 |
| M23 | 删除整个应用 | `delete` | 创建人、管理员、普通授权用户一律同动作；保留先下线、二次确认、资产清理、审批取消及审计 |
| M24 | 查看授权清单/可见范围的管理信息 | `manage_permission` | 基础发布摘要可仅返回是否配置的无主体概览；完整主体列表与授权详情受动作控制 |
| M25 | 增删授权、修改授权模型、设置可见范围 | `manage_permission` | 使用既有 F048 Grant/投影流程；不改变服务账号主体侧授权入口 |
| M26 | 审批任务的详情、冻结源码审读、临时预览 | 审批引擎任务资格签发的临时业务授权 | 绑定实例/版本/任务/期限；审批预览注入审批人本人，平台能力限该版本声明及应用归属人权限；不转换为通用管理授权 |
| M27 | 有编辑权限的管理者查看提交版本的管理预览 | `edit` | 注入实际预览者本人，平台能力限版本声明与本人权限；不能继承审批例外；与审批预览隔离，均不注入真实密钥 |
| M28 | 审批通过/驳回、异常审批重试/指定审批人/取消 | 既有审批任务或审批管理权限 | 不映射成 app.publish 后绕过审批引擎；应用相关的业务提交/主动撤回分别按 M15/M20 |
| M29 | 应用维度的模型/能力/访问运行记录与受权导出 | `edit` | 仍执行 app/tenant 过滤、时间范围和导出限制；不附带模型密钥或请求正文 |
| M30 | 平台审计页跨应用查询 | 既有审计入口资格 + 可管理应用/租户范围 | 有 app:edit 不自动获得整个平台审计权限；单应用记录读按 M29 |
| M31 | CLI/MCP 的应用列表、详情、状态、数据、日志及发布 | 与上述同语义操作相同的动作 | 开放通道 scope/模式检查仍是额外入口条件；不再按资源归属人只列“我的应用” |
| M32 | 应用 SDK 的模型/检索/附件调用 | 已授权的 `use` 会话/运行期身份 + 能力声明及底层资源授权 | 不能按调用方自带 appId 或伪造用户身份放行；SDK 业务附件的删除不是删除整个应用 |
| M33 | 应用管理操作导致的 SQLite 快照/迁移、manager 下载源码/上传快照等 | 继承所属操作经校验后签发的内部授权 | app、tenant、version、operation、用途绑定；HMAC/票据/幂等/租约继续核验，不能暴露成匿名接口 |
| M34 | profile/基础镜像/公共依赖导入、默认 profile、宿主隔离和 K8s 能力管理 | 既有平台运维/超管权限 | 这些资源不属于某一个 app；不得因有一个 app.edit 就获得全局编排权限 |
| M35 | 发布审批 outbox、Celery 续办及在途操作重试 | 经过验证并冻结的原始操作授权 + 阶段性重校验 | 记录实际主体及凭据引用；扩权/启动/提交新路由前验证权限仍有效；失败进入已有可解释终态/等待态，旧资源清理不因此被卡住 |
| M36 | 既有正式实例自愈、清理旧执行体与停止确认 | 既有运行期意图和内部执行资格 | 管理者个人撤权不等于停用应用；自愈不得凭空获得新能力或改版本，不用伪造 owner 会话 |

## 5. 对现有边界的修订与保留

### 5.1 将明确替换的 owner 规则

| 已有合同/落点 | 本次建议 |
| --- | --- |
| F054 AC-44、AC-53：删除资格；最新超管例外 | 全部归到 app.delete，不再判断创建人账号有效性 |
| F054 AC-55、AC-56：日志和数据的 owner/管理员前置限制 | 统一 app.edit，所有通道同口径 |
| F055 AC-04：CLI 迭代发布/日志按 resource_owner_user_id 限定目标 | 通道资格与 F048 动作同时校验，使用真实服务账号/PAT 主体 |
| F055 的撤回、手动上线、发布面动作 owner 开关 | 根据 publish 等具体动作和发布状态决定 |
| F055 AC-66 等环境变量保存/读取/重建 owner 限制 | 维护为 edit，确认重建为 edit AND publish；不回显明文 |
| F056 运行记录查询、导出及前端 owner/管理员分支 | 应用维度按 edit，平台审计入口保持既有菜单和租户范围 |
| F086/F059 运行时管理的 natural_owner_required | 按 M12–M22 的实际操作映射，两个执行后端相同 |
| release-contract INV-35 的“除 owner 显式删除流程外”措辞 | 应修订为“除具有 app.delete 资格的显式删除流程外”；资产保护、在线不可删除不变 |

以上是拟修订项索引，不是宣称原合同已经变更。正式 spec 经确认后，设计阶段做完整引用扫描并同步现行合同；不把早期版本线已归档文档当作本次交付目标。

### 5.2 继续保留的条件

1. 租户归属、超管管理视角与 F066 数据范围约束继续执行；用户迁租户后不迁移存量应用和权限。
2. `owner_user_id` 仍是资源归属事实和审批路由/通知/资产归档的依据，不是额外动作通行证；本期不实现移交、改 owner 或改 tenant。
3. F048 权限模型和动作启停仍是真相；不写业务层角色名到动作的静态映射，不扩大其它资源的 Catalog。
4. 发布必审、包安全校验、密钥扫描、声明白名单、预览隔离、容量准入、探活、路由切换、数据维护围栏及删除范围不变。
5. 仅持 use 的用户仍不能查看管理数据；应用自己的个人会话/业务数据行隔离规则不因平台权限统一而被删除。
6. env 保持加密保存、无明文回显；保存不重启，生效需确认；日志/记录继续脱敏。
7. 审计记录真实自然人/服务账号、凭据引用、目标 tenant/app/version、动作及结果，资源 owner 与实际操作者分开。
8. 内部调用仍需 HMAC/受限凭据和用途绑定，manager 不直接相信前端权限参数；平台运维权限不降为单应用 edit。

## 6. 需要确认的产品口径

**用户已确认本矩阵并进入正式规格**。以下三项实质性的行为变化由正式 spec 继续明确，具体租户单选增量见 §9：

- **edit 的信息范围**：覆盖生产数据查看/修改/导出、日志及环境变量维护，不再单独保留 owner 限制。系统没有 app.read/app.export/app.secret 动作，若要继续分开这些能力，就需要另一项 Catalog 扩展需求，不能用看似统一的额外 owner 判断代替。
- **发布代行**：具备 publish 的管理者可以为他人的应用提交、撤回应用发布及手动上线；改包并提交同时要求 edit。审批引擎的通过/驳回仍不随 app 权限开放。资源 owner、审批申请人与路由依据保持现状，实际提交/撤回者另记；自审同时排除资源归属人与实际提交关联自然人，仅保留原单管理员例外，无合格候选进入异常处理。
- **CLI/MCP 与首次创建**：按已准入通道的真实主体检查 F048：服务账号查自身授权；支持自然人/PAT 的入口查其真实自然人授权。保留 app:manage 等通道条件，当前不支持 PAT 的 CLI 发布入口不会因本次映射而开放；不能继承资源归属人的全部权限。已有 app 需明确授权；首次创建保留单命令体验，通过受控创建生命周期登记本次所需的 app 初始化授权及审计。初始化授权的具体模型/Grant 与原服务账号主体侧约束如何衔接，列为设计必须解决的合同，不以“创建成功”掩盖后续无法查询/发布的问题。

上述初始化只限新建 app，不给历史资源批量补授权，不改历史 owner/tenant，不通过管理员身份代签调用者。具体实现待设计评审；如果无法在已有授权能力内满足，需要回到规格评审说明差异，不静默添加权限动作或放宽 scope。

## 7. 代码证据索引

以下链接固定到本轮静态核查基线；本轮未执行生产环境删除、发布或数据查询。

| 文件 | 已核对事实 |
| --- | --- |
| [catalog_policy.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/permission/domain/services/catalog_policy.py#L52) | app 已有六个动作，share/download 等不在 app 范围 |
| [test_app_permission_registration.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/test/app_runtime/test_app_permission_registration.py#L67) | app 类型及六动作注册断言 |
| [app_state_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/domain/services/app_state_service.py#L782) | 删除、上下线等独立业务资格分支 |
| [app_query_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/domain/services/app_query_service.py#L266) | 平台详情 edit、CLI/MCP 额外 owner 入口及日志判断 |
| [app_data_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/domain/services/app_data_service.py) | 生产数据 owner 校验；运行时数据会话/票据复用该判断 |
| [app_secret_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_publish/domain/services/app_secret_service.py#L55) | 变量维护 owner 校验、只读响应按 owner 裁剪 |
| [secret_rebuild_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py) | 重建 owner 判断和确认指纹/幂等围栏 |
| [publish_pipeline_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py#L228) | 发布主体重校验、自然人归属校验、迭代仅原归属人 |
| [deploy.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_publish/api/endpoints/deploy.py#L198) | CLI logs 构造资源归属人兼容身份 |
| [publish_status_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_publish/domain/services/publish_status_service.py#L91) | withdraw/preview/manual_publish 按 owner 设置 |
| [runtime_management_service.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/domain/services/runtime_management_service.py#L35) | 私有物料、运行状态、快照恢复等 natural_owner_required |
| [runtime_management.py](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/backend/bisheng/app_runtime/api/endpoints/runtime_management.py) | 应用级管理与平台公共 profile/物料入口 |
| [HostedAppCard.tsx](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/frontend/platform/src/pages/BuildPage/HostedAppCard.tsx#L188) | F048 canDelete 后又叠加创建人/管理员条件 |
| [DangerZoneCard.tsx](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/src/frontend/platform/src/pages/BuildPage/hostedApp/publish/DangerZoneCard.tsx) | 详情删除区只按 owner/super 显示 |
| [approval-module](https://github.com/dataelement/bisheng/blob/cfcefd6577744c7807f30ce77de4e1b4050074ff/.claude/skills/approval-module/SKILL.md) | 任务决策、业务取消、必审及 outbox 的既有边界 |

## 8. 验证与交付边界

- 本阶段只做静态入口盘点、既有合同对照和文档一致性检查。没有运行测试、部署 116/189、改授权、改服务账号或迁移存量数据。
- 后续只做本功能必要定向验证：六动作的允许/拒绝与组合、只持 use 的拒绝、所有者被撤权不绕过、同租户与跨租户、超管选定视角、SA/PAT 主体、不复用 owner 身份、前端与 API 一致、异步撤权/重试、确认取消不发请求和审计实际操作者。
- 按相同产品合同验证 Docker/K8s，权限集中在 backend，不重跑所有编排/故障用例；真实 E2E 使用专用临时对象，范围在设计明确。DM8 按既定要求仅静态检查。
- 不新增公开推送、tag、镜像发行或环境更新。当前已完成需求分支本地实现，未合入 feat/3.0.0。

| SDD 阶段 | 状态 |
| --- | --- |
| 需求目标 | 用户已要求扩大为所有 Vibe 相关操作 |
| Discovery 操作映射 | 用户已确认；具体租户单选作为已确认增量目标并入正式规格 |
| 正式 spec / spec-review | 原 70 条已确认；用户明确 v2 及 R3 收窄决定；共 71 条，M22 标为退役，规格原文未变；设计 R4/R5/R6 已修订，24 项静态复审 LGTM、独立复审 PROCEED，整份设计已单独确认，实施证据见verification.md |
| design | ✅ 用户已单独确认；R1–R6关闭，静态LGTM/独立PROCEED |
| tasks / 编码 / E2E / L2 | 本地102/104；真实E2E、最终L2/门禁仍待完成 |


## 9. 2026-10-30 具体租户视角增量

用户明确要求去掉“整个平台”，必须限定某一个租户；同日确认本映射并进入正式规格。此前出现的全平台管理视角不再作为目标行为。Root 仅代表 Root 本身；无选择、过期或无效选择回到所属租户，不能回到全平台。完整验收以 spec.md AC-09 至 AC-18 为准。

## 10. 2026-10-30 复审建议修订

用户在查看三项评审问题与推荐口径后回复“按照建议修改”。以下三项口径已写入正式规格，随后整体确认及归属澄清见 §11：

1. 代发布时，应用归属人仍是审批申请人及路由依据；自审同时排除应用归属人与实际提交关联自然人。服务账号以提交时固定的账号归属人参与排除，审计仍保留真实服务账号主体；仅保留原全租户单管理员自审例外，无合格审批人则进入异常处理。见 AC-39、AC-67、AC-68。
2. 管理预览按实际预览者身份及本人底层权限执行；有效审批任务预览保留原归属人能力例外。同一人双重资格时按本次用途分别校验，不能混用；所有预览不注入真实密钥。见 AC-38、AC-50、AC-51、AC-69。
3. 取消由当前取消者满足原业务用途的全部动作，可与发起者不同；环境变量配置确认重建/新版本发布取消需 edit AND publish，恢复按是否包含启动区分。已生效或不可取消阶段仍拒绝，必要失败清理继续。见 AC-56、AC-70 及 spec §3.1。

正式规格新增 AC-67 至 AC-70，原 AC-ID 不重排；该轮共 70 条并已获确认（后续收敛见 §12）；设计待单独确认，任务与业务编码尚未开始。

## 11. 规格确认与归属澄清

用户已明确“确认规格，进入设计”，随后重申“创建资源还是属于归属人，这个逻辑不变”。应用和服务账号后续创建资源的自然人归属与租户规则保持；真实服务账号作为鉴权和审计主体，按现有 F048 创建生命周期取得可撤销初始授权，不改成资源 owner。70 条 AC 正文未因这一澄清修改。当前设计见 design.md，仍需单独确认后拆任务和编码。后续协议收敛决定见 §12；本段的 70 条为当时确认记录。

## 12. 唯一 v2 运行控制协议与共用接口边界

用户明确共用读取/调用按原最小权限维持，并在说明“功能尚未正式对外发布”后要求“收敛统一一下”。本稿据此统一：Vibe 只保留运行控制协议 v2；不再补 v1 阶段授权、不保留长期双协议或旧绑定导入。源码构建公共函数、SQLite/附件/日志/SDK 及现有平台 API/应用包格式保留；测试资产不自动删除或迁租户。

该轮新增 AC-71，原其它 69 条 AC 正文保持。后续实质复审发现 R3：旧 rebind 对正常在线同版本返回既有实例，不能当作现有通用 v2 重建；用户已采纳进一步收窄建议，现行条款以 AC-57 及下节为准。原 R1/R2 关闭结论保持，设计仍须单独确认。

## 13. 旧绑定重绑与现有发布链路收敛

用户对 R3 建议回复“按照建议修改”。旧绑定导入、升级和 rebind 一并退役，M22 保留盘点编号但不再对应可授权执行动作。同版本环境变量确认重建仍按 M11/AC-26；代码、镜像、运行环境或启动声明变更仍按 M15、M17/AC-35、AC-36 走新版本发布，两类操作均要求 edit AND publish。取消按这两种真实业务用途判定，本次不新增 runtime_upgrade 或独立通用实例重建。创建资源归属人、租户及受保护自然人 owner 授权保持原规则。

本轮只修订文档；设计仍需用户单独确认，未创建 tasks、修改业务代码、运行测试、提交、推送或更新 116/189。

## 14. R4/R5/R6 设计修订范围

用户再次“按照建议修改”：补系统自愈授权来源、维护首次副作用前的阶段准入、预览会话/凭据/operation 的原子登记及失败回收；只细化 How，71 条 spec AC 原文保持。无需新增权限动作、引擎、移交迁移或恢复框架。该轮设计24项静态复审LGTM、同一独立代理复审PROCEED，三项原发现均关闭；随后用户确认与开发进度见§15。独立原文见 architecture-critique-r4-r6.md，原 REVISE 快照保留。

## 15. 用户设计确认与开发

2026-10-30用户确认整份设计，进入任务拆解和开发；71条AC不变。当前102/104项本地任务完成；逐阶段定向结果及未通过的工作区门禁见verification，真实E2E与最终L2未完成。详见tasks.md与verification.md。
