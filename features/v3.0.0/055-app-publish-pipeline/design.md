# Design: 应用发布管线与应用密钥管理

> **2026-10-23 简化设计已由用户单独确认，进入任务实施。** 用户原文：“确认 F055 简化设计”；批准前SHA-256 `2ef7247c7fcc71d1e2e44b34a9df8dfe865135adc66c249166a29202e29402d6`。 用户已确认 92 条 AC 的手动生效规格；源码基线 `5f2541f4bc483c24624fede9031c88c4ec6f58f4`。D1–D20 与 §1–§8 保持编号；正文覆盖旧三表/自动生效设计，不沿用历史设计的确认状态。
>
> [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md)。主导质量属性：无意外停机、秘密隔离、运行配置与保存配置可辨识。F054 B1、F056 S1 的既有发现仍待修，不由本文宣称关闭。

## 1. 目标与非目标

为已有发布/审批/运行管线补齐 owner 私有应用密钥：仅保存名称引用进版本，值加密存平台数据库，已审批正式实例按当前值注入。保存值不触发重启；页面提示当前实例与最新保存配置的差异，owner 确认后才复用部署流程重建当前版本。预检和审批预览只注入声明名与空值。

非目标：第三方 Vault/KMS 托管、第三方凭据有效性探测、密钥 SDK/CLI 管理、商业限额、平台模型供应商密钥编辑、批量应用重启。F054 管生命周期执行，F056 管管理员运行记录查询，不复制这两个领域。

## 2. 关键约束

- 预检、构建、依赖安装、前端编译、扫描、审批预览均不得取得真实值；预览身份和隔离存储原有规则仍有效，不以“无应用业务密钥”取消正常权限检查。
- 值只由同租户应用 natural owner 经平台会话修改；管理员、超管、审批人、SAK、PAT 均不能替 owner 写。权限 shortcut 不代替这个业务前置。
- 声明属于冻结版本并需审批；值属于应用当前配置，改值/删值不创建版本或审批，也不自动创建运行操作。手动重建只能运行确认时的已批准当前版本，不能借机启动 pending_version。
- 字段边界（拟定实现常量）：每应用最多 64 项；名称 ASCII `[A-Za-z_][A-Za-z0-9_]{0,127}`，区分大小写且精确匹配；值 UTF-8 不超过 16 KiB，整组不超过 128 KiB，禁止 NUL（无法放入进程 env），支持 Unicode/换行/空格/特殊字符且原样传递。空字符串表示缺失；全空格值不自动 trim 成空。
- 遵守 [constitution.md](../../../docs/constitution.md) C1–C8，不复制全局铁律。Constitution Check：新 Model/Repository/Service/Endpoint 分层；tenant_id 默认 None、非空、索引且注册自动注入；通用 LargeText/JsonType 和迁移单 head；仅 162 段新增错误码；平台持久 DB 为权威；不向 backend 引入容器 SDK。无例外。

## 3. 方案对比与选定

### D1：同步接收 + Celery 阶段机

保留同步鉴权/安全解包/manifest 校验，异步扫描、准备交付、探活、审批。拒绝把整条分钟级管线放 HTTP 请求或把失败尝试写成已发布版本。现有 `AppDeployment` 与 worker 已接线；管线可并行分支真正出现时再重议。

### D2：源码快照由平台保存

backend 拥有私有对象存储与代码引用，manager 经受限传输 API 获取。拒绝 manager 直读 MinIO 或通过临时本地文件在 API/worker 间共享；现有 runtime_artifact_service 已提供传输协议。交付物类型改变时重新评估。

### D3：manifest 严格校验，新增引用而非值

`CapabilityDeclaration` 增加 `secrets: list[SecretRef]`，`SecretRef={name: str}` 且 extra=forbid，旧 manifest 不带该字段仍通过。采用与 models/knowledge_bases 同处的声明入口而非任意 `env` 字典；没有平台 issued scope，`derive_scopes` 不因 secrets 新增开放 API 权限。

当前 `_reject_secret_references` 会泛化拒绝 secret/token 等键，必须只豁免合法 `capabilities.secrets[*].name` 子树，其他位置仍禁明文/不支持的引用形状；全源码扫描继续先于构建。`is_empty`、部署适配、预览、摘要/diff、CLI 校验与提示、审批审读都同步识别名称。若未来支持外部 secret provider，另改规格与 schema，不接受 `vault://...` 偷渡。

### D4：fail-fast 阶段结果保留

沿用 `{stage,code,message,details,hints}` 失败形状；缺值是 warning，不单凭缺值拒绝发布。应用自身无法启动则正常探活失败，不跳过 Gate。不得将第三方 key 的值放进 details/hints。若发布阶段拆服务再评估传输合同。

### D5：明文扫描继续阻断

合法声明名不视作密钥明文；实际源文件/打包内容仍扫描、只返回文件/行号/规则，不返回匹配值。密钥不进源码或依赖缓存，不能为“用户确实需要 key”放宽扫描。新检测模式只更新规则与配对用例。

### D6：版本只保存声明快照

版本仍在预检通过后建立；只冻结 secret 名称，不保存值/密文/可还原引用令牌。运行时注入值不写入 `AppVersion.injections`，否则历史版本会变成密钥仓库。未来需要配置历史恢复时需另立规格。

### D7：审批场景保持现有强制入口

仍经统一审批场景/outbox；审读只提供声明名称和按调用时状态计算的缺失提示。审批人不获得 owner 密钥管理能力；声明增删需审批，值修改不触发审批。已有审批规则与申请人过滤保持。改变审批权限时必须读 approval-module skill，不在本次重写中心引擎。

### D8：既有审批基建修复不重做

早期审批解析/seed/通知回退已落地，本轮只核对真实调用点。拒绝把历史设计“阻塞前置”重做成新任务。只有本轮定向用例暴露回归时再改。

### D9：上线前终检与容量准入

冻结交付、当前应用状态、审批结果与容量仍是前置；正式环境在 **执行前**由 backend 生成并封装，不能由调用者透传 runtime_env。manager 不自行判断“审批过”；信任操作的可信用途和版本绑定。执行协议变化时重议。

### D10：撤回 / 删除取消保持幂等

沿用已有终态守卫和持久取消；用户确认的密钥配置重建也遵守停止/删除围栏。删除应用成功后清除密钥值，审计按既有留存保留；删除未知/清理失败时不抢先把数据与身份当已释放。领域销毁协议改变时重审清理顺序。

### D11：档位为平台资产

资源档位继续独立管理、停用不删；用户确认重建使用当前运行操作冻结的资源预算，不因全局档位配置已改变而重算。支持动态扩缩容时另审。

### D12：操作审计与运行记录分层

生命周期/声明/密钥变更进入操作审计；模型、能力、访问记录各有现存专表。密钥事件只能含 app/ref/actor/action/time/result；API key 事件仍可含原有 key_mask，不混用两种掩码。审计模式改变时与 F056 共同审查。

### D13：已有能力总线与运行凭据保持

`runtime_capability_env`、`AppRuntimeCredentialService`、模型面/检索 OBO 已实现，不再“本轮后置”。应用业务密钥无新 SDK API；`os.environ` / `process.env` 原样读取。预检/预览继续没有正式 app credential，但有隔离存储环境。真实密钥不能混进模型供应商平台配置。新增平台能力时才扩 scope。

### D14：审批侧使用当前页面

以现有审批详情/审读页实际入口为准，不恢复过期弹窗设计；仅增名称/缺失提示和差异展示，不新增审批操作。若现有布局没有可用组件，跟随现存审读样式，不改设计系统。

### D15：发布面复用现有 settingsSlot

F055 的 `AppSecretSettings` 加进应用详情的 settingsSlot，与档位/能力并列；查询与持久操作状态由 hook 管理，store 不发 HTTP。natural owner 可编辑，其余有查看资格者仅看名称/缺失；审批人只走审读数据。失败必须 catch 并终止等待，防止新 request 拒绝 Promise 后 UI 卡住。

### D16：当前交付边界

现有发布、预览、结构演进、模型/知识能力与三交付模式已有代码；本轮只补密钥与用户确认的 runtime 重建，不借此重做 F086/F059。旧任务状态与当前证据分开。未来非本轮能力见 §8。

### D17：一张加密配置表，执行状态复用既有账本

否决三张密钥专表及配置独立 applied 状态机：原方案为自动生效维护值、状态和 mutation 意图，但用户已明确保存不重建；现有 RuntimeOperation 已持有幂等、冻结环境、执行事实和失败结果，重复维护会增加双写。选定 `AppSecretConfig` 每应用一行，整组键值映射加密存储；配置 revision 只防旧页面覆盖，不表示运行实例已经采用。

使用既有 `app_runtime.runtime_payload_key`，密文 envelope 校验 `tenant_id/app_id/domain=app-secret-config-v1`。整组映射有大小上限，名称在解密后按原大小写精确比较，无须逐名称摘要/专有 collation。不存业务值普通哈希，不另建 AppSecretState、AppSecretMutation、配置专属扫描器或 ConfigurationApplyPort。平台固定部署 key 要与数据备份；误改或缺失明确失败，不降级为缺值；更换仅作运维说明，不开发轮换工具/UI。将来确有跨应用共享或历史值恢复需求才重新审查，不能在本版预建。

### D18：保存与用户确认重建分离，复用 deploy 执行器

否决保存后自动重启、Docker restart（环境不会更新）、再走发布预检/审批/DDL，以及专用配置执行引擎。保存事务只写加密配置、revision 和既有审计，不调用 manager。用户另行确认后，经 F054 `rebuild_current` 公共应用入口受理 `kind=deploy,purpose=config_restart`，以新的 RuntimeOperation 重建同一冻结 delivery/profile/镜像/档位。

该入口不是原 `deploy()` 原样直调：需要绕过同版本 serving 快速返回、拒绝串接其他 purpose 的 active deploy，并固定空 migration_plan、禁 snapshot/restore。旧 writer 停止确认、预占、探活、切路由、清理和故障续办均用现有机制。失败后不由 recover 自动再创建 config_restart/替代 deploy；只能用户重新核对并确认新 attempt。续办已受理 operation 和 deadline 不算再次用户动作。未来有应用热加载协议时再讨论免重建，不在本版实现。

### D19：以当前路由所绑定的冻结环境判断差异

否决“revision 不同就要重启”、单独持久 dirty 标志、每次改值清空已生效状态和额外值摘要历史库。当前 RuntimeRoute/AppInstance 决定使用哪次正式 operation，backend 受限读取其 sealed_env，仅比较当前批准声明的名和值与最新配置。后保存未引用项不会误报；A→B→A 与实际运行值相同会消除差异。比较结果只含变量名、same/different/unknown 及安全状态，没有新旧值。

保存允许发生在已受理重建期间；本次 operation 的环境一经冻结不变，后续保存仍作为最新配置保留，切路由只提交运行事实、不回写配置。请求丢失复用 RuntimeOperation 的 scope/key/request_digest；不为保存维护历史请求 HMAC。执行上下文缺失、解密失败或路由变化无法取得一致视图时报告 unknown，不能猜已一致。未来若现有执行上下文不再保留而产品要求永久历史配置比较，再另审数据需求。

### D20：输入草稿与固定掩码（新增）

不返回值、不允许“查看明文”。列表只显示固定 `••••••`，不与密码框输入绑定；点击替换打开空的输入草稿，初值绝不放掩码。值控件用已落地 Input/Textarea，换行值不通过单行组件截断；写成功后清空内存草稿，失败保留当前未提交草稿。关闭/换应用/退出清理，不写 URL/localStorage/query cache/埋点。避免使用带请求体自动回显的通用错误日志；secret endpoint 的请求校验异常只返回字段位置/规则，过滤 Pydantic input/ctx/raw body，确保非法值也不会被校验错误回显或写日志。

取 current shared UI docs 的字体/色彩/多端/输入框规范，Button/Input/Textarea/Tabs 使用 status=done 的组件；Select 尚为 draft，筛选跟随当前页面已存在模式，不另造。表单/确认对话框用当前发布页已有实现；不改组件样式、不新增库。未来需要设计师定义新交互时再申请视觉评审。

## 4. 系统现状（接手必读）

### 4.1 数据流与实现状态

**已实现**：接收包 → 代码快照 → 扫描/结构预检 → manager prepare/probe → 版本/审批 → 正式 deploy；backend 持有对象数据，manager 管 SQLite；RuntimeOperation 已持久保存 sealed_env，RuntimeRoute 标记当前运行 operation，K8s 已有执行专属 Secret。**本轮未实现**：合法 secret 声明、加密配置资产、管理 API/差异投影、用户确认的同版本重建分支及敏感输出合同。

```mermaid
sequenceDiagram
  participant Owner
  participant Backend
  participant DB
  participant Manager
  Owner->>Backend: save secret + expected_revision
  Backend->>DB: encrypted config + revision + audit only
  Backend-->>Owner: saved; computed differences; no restart
  Owner->>Backend: confirm rebuild: request_id + expected version/config/route
  Backend->>DB: existing operation + frozen env in one short UoW
  Backend-->>Owner: operation_id
  Backend->>Manager: wake existing durable deployment
  Manager->>Backend: claim operation and receive frozen environment
  Manager->>Manager: stop proof; same delivery; health check
  Manager->>Backend: ready execution fact
  Backend->>DB: existing instance and route commit
  Owner->>Backend: read config and running-operation difference
  Backend-->>Owner: same / different / unknown, names only
```

保存路径没有 manager 调用。预检/预览只生成 `{NAME:""}`，不调用正式解密协议；正式部署/重新上线在当次受理中选最新保存配置，已受理操作和进程原地重启使用其冻结环境，不因新保存值改写。

### 4.2 既有公共合同（保留原编号语义）

**① 管线接收与轮询**：`/api/v2/apps` 由 router_rpc 单一 `verify_open_api_access` 与端点 `open_api_scope("app:manage",modes=("S",))` 保护；本次不把秘密管理挂 v2。

| 路径 | 入参 / 返回 |
|---|---|
| GET `/deploy-limits` | 返回部署实际 `max_package_mb/max_unpacked_mb/max_package_entries`，CLI 不写死上限 |
| POST `/deploy` | multipart package/app_id/confirm_schema_change；返回 deployment_id/app_id/version_id；同步失败不进入轮询阶段 |
| GET `/deployments/{deployment_id}` | stage/status/failure/app_id/version_no/approval/app_state/pending_reason 等当前 service 投影；CLI 只读状态，不自行合成成功入口 |
| GET `/{app_id}/logs` | tail/since/keyword；转同一个日志服务并增加 resource owner/租户限制，不因 key 的管理员身份放大范围 |

**② 发布状态只读接口**：`GET /api/v1/apps/{app_id}/publish-status` 由 PublishStatusService 同时供发布页与工具适配消费；app_state/pending_reason、current/pending version、deployment、approval、tier、capabilities、schema_change、can 是不同维度，缺失 row 不假造成功。手动上线/撤回仍服务端重新检查。

**③ AppManifest**：严格 extra=forbid；manifest_version 1 走兼容 source-image，2 支持 bundle/image/source-image；runtime=python3.11/node20/static，port/tier/capabilities/database/egress 继续当前模型；delivery/dependencies/startup 的准确字段以 `schemas/app_manifest.py` 与 F086/F059 冻结合同为准。本轮仅新增 `capabilities.secrets:[{name}]`，值不在 manifest。模型/知识能力及声明表结构/egress 现已实际消费，不再“非空即拒绝/只给 hints”。

**④ 审批场景**：app_publish_request；business_resource_type=app / business_resource_id=app_id；申请人为自然人 owner；business_key 对应提交尝试。build_detail 为结构化审读快照，有 app/version/tier/capabilities/visibility/schema_change 与兜底展示键；新增 secrets 仅名称/缺失提示。当前单租户审批来源与多租户解析按已合入代码，不能恢复早期固定 seed 示例。

**⑤ 表**：AppDeployment 保存一次发布尝试的 stage/status/code_object_key/manifest/tier_code/failure/scan_result，预检失败不进 AppVersion；ResourceTier 平台级、code 唯一、启用/停用。新密钥资产见 §4.4①，不修改 ResourceTier 所有权。

**⑥ 审计**：app.release.* 事件族保持；app/version/deployment 关联来自业务事实，事件枚举、后端可见白名单/命名空间、前端 actions/i18n 三语同步。新 app.secret.* 是值动作元数据，不带秘密片段。

**⑦ 通知**：发布/审批事件经现有 outbox 与通知适配触达；action_code 与接收者权限由真实场景决定。密钥值不进入通知正文、detail_snapshot 或前端消息 payload。

**⑧ 错误码**：沿用现有 162 模块与 frontend api_errors 唯一文案；16207 运行时关闭、16223 档位无效、16225 审批场景不可用、16226 容量不足、16228 探活失败语义不混用。原 16230 泛拒绝 secret reference 必须收窄为不支持/非法形状，合法 ref 可发布；模型面仍使用 265xx，不翻译成非模型 162xx。

### 4.3 关键模块职责

| 模块 / 拟新增落点 | 做什么 | 不做什么 |
|---|---|---|
| F055 `domain/models/app_secret_config.py`、Repository、AppSecretService、v1 endpoint | 单表加密配置、owner 权限、revision CAS、审计、差异投影 | 不编排、不创建自动重建意图、不返回明文 |
| F055 `application/runtime_secrets.py` 公共协议与组合根 | `formal_snapshot` / `preview_environment`、配置清理；内部环境 DTO | 不暴露 ORM、不自行切路由、不授予管理权限 |
| manifest/schema/CLI/审批摘要 | 合法 secrets 名称、保留名、缺值提示 | 不加载或携带值 |
| F054 AppStateService / RuntimeDeliveryCoordinator | `rebuild_current` 受理、环境冻结、既有 deploy 执行与提交 | 不写 F055 配置表/已生效结果，不迁移数据 |
| manager Docker/K8s executor / admission | 用途/敏感名校验，创建实例、停止证明、探活及事实 | 不读平台 DB/MinIO、不管理最新配置、不因保存而重启 |
| 现有 node-plan/协调入口 | 续办已有操作，读取原期限及冻结环境 | 不扫描配置差异来创建操作，不自动重试失败手动重建 |
| AppSecretSettings 与 hook | 空草稿、固定掩码、保存、差异、确认、既有操作进度 | store 不请求、缓存不存值、不自动确认 |
| F056 / 凭据 Owner | 查询配置事件；S1 的真实 binding 回收事件另待补齐 | 不从查看者参数伪造回收事实 |

### 4.4 本轮增量字段与接口合同（拟实现）

**① 单个持久配置模型**

`AppSecretConfig` / `app_secret_config`：app_id 主键（与 App.id 同型）、tenant_id 默认 None/NOT NULL/索引、revision 非负整数、values_ciphertext 用通用 LargeText、updated_by/updated_at。密文内容为 envelope 与有界 entries 映射：`name -> {value,updated_by,updated_at}`，保留每项最近修改时间而不增加表。最后一项删除后保留空配置行/revision，避免 revision 重置导致旧页面误写；应用真正删除后由既有持久 cleanup 调 F055 公共 `delete_for_app` 幂等清除，失败保留既有 cleanup 待办；历史无值审计不删除。

未建行表示 revision=0、空配置。save Repository 用同一短事务加载受权 App 并锁定，再按 app_id 锁配置/处理唯一约束首建；禁止在该事务调用 manager、锁节点/operation 或持有锁探活。与 App 删除的最终状态写入序列化：已删除不能再保存；先置业务不可写状态再清理配置，不允许清理后重新写入孤儿配置。每个接受的保存/删除使 revision+1；旧 expected_revision 拒绝，不自动覆写。配置与本业务审计由 AppSecretConfigRepository 使用同一个显式 AsyncSession 追加，事务失败一起回滚；复用既有 AuditLog 表及字段约定，不另建表。现有 AuditLogDao.ainsert_v2 自开 session 并 commit，不能调用它宣称同事务，也不为本功能新加 DAO 入口。

新模型登记租户发现与 API/worker 导入，缺上下文写入拒绝；DM8 仅通用类型/约束/迁移静态检查。迁移从唯一 Alembic head 接续。应用停用、版本升级、声明移除不删资产；名称精确比较、Unicode/空白/换行按 §2 处理，空值不标为已录入。

**② 会话 API（拟新增）**

| 方法 / 路径 | 入参 | 返回 / 副作用 |
|---|---|---|
| GET `/api/v1/apps/{id}/secrets` | 无值参数 | `{revision,updated_at,items:[{name,present,mask,updated_at,approved_reference,pending_reference}],runtime:{comparison,saved_revision,running_operation_id,running_version_id,route_epoch,changed_names,rebuild_operation}}`；comparison=same/different/unknown/not_running，失败原因安全枚举 |
| PUT `/api/v1/apps/{id}/secrets/{name}` | `{value,expected_revision}` | `{revision,present,updated_at}`，只保存+审计；没有 operation_id、自动 pending 或后台唤醒 |
| DELETE 同路径 | `{expected_revision,confirm_online_impact}` | 同上；删除保存值，不改声明/当前实例；线上引用先说明当前实例仍可能持旧值 |
| POST `/api/v1/apps/{id}/secrets/rebuild` | `{request_id,expected_version_id,expected_config_revision,expected_route_epoch,confirm_restart:true}` | `{operation_id,status}`，owner 明确确认后转 F054 `rebuild_current`；accepted 不表示已就绪 |

同租户先查业务对象及原可读规则，再验证平台会话的自然人 owner；super shortcut 不变为 owner。tenant admin 只见有资格读取的声明名/状态，不见未引用私有项和 owner mask/修改者；审批人只走批准范围的审读数据，不复用 owner 管理接口。写/重建均拒绝 SAK、PAT、非 owner。无权/不存在按原业务拒绝语义，不泄漏其他租户。公开请求不能传 env、ciphertext、purpose、node、tenant 或任意执行资源。

保存不设独立 request_id 历史表：网络结果不明时刷新安全元数据核对，不自动重复 PUT、不凭一个 revision 推断值内容已成功；显示结果待核对，owner 需要时重新提交。重建才用已有 RuntimeOperation 幂等：先做当前会话/业务归属核验，再按 scope=`tenant/app` 和 `secret-rebuild:request_id` 查原操作，核对原确认字段摘要；同参返回原操作，异参拒绝，不能因当前配置/版本已变化而先拒绝历史同参重放。新 attempt 才检查当前预期条件；新 attempt 需新确认，不复活原失败操作。摘要只含非秘密确认参数，不存业务值摘要。

新增错误按 162 占用检查分配，三语文案同步；不在设计猜编号。Pydantic input/ctx/body、埋点及错误日志不回显值。保存与操作都用既有响应 envelope，前端 catch/finally 结束等待。

**③ 与现有部署的最小衔接**

1. F055 公共 `formal_snapshot(app,approved_version,expected_revision?,session)` 在 caller 的短事务中返回 `{revision,env,sensitive_env_names,declaration_digest}`；F055 Repository 显式使用传入 AsyncSession，只读/flush，不自行 commit，不依赖另一 Repository 的 ContextVar。调用方验证用途、批准版本和租户，provider 再验证输入绑定，只取声明子集；没有值为空，坏密文/缺 key 为失败，不伪装缺值。`preview_environment(declaration)` 只生成空值，不读配置密文。
2. F054 `rebuild_current` 不能把 node→已存在 operation 当作既有统一锁序：claim/fact 实际先锁 operation 再 node，ready commit 还会先锁 App 再进入 node/route。新受理选择先锁 App，再依次锁 node、assignment、route、配置；对已存在的 operation（含 origin 和冲突检查）只作非锁定读取，绝不在持有 App/node 后回锁这些行。只允许锁/更新本事务新插入、尚未发布给任何 manager 的新 operation；幂等重放在这些运行锁前通过只读查找返回，不对旧 operation 再执行 admit。save 只锁 App→配置，不获取运行锁；配置锁拿到后不能回取 App/node/operation。受理事务核验 online/current version/route epoch、当前真实 frozen delivery/profile/tier、没有维护/生命周期冲突或未知 writer（包括已受理尚未 claim 的非终态操作，不只看 assignment 当前指针）；选当前 route 对应执行的 tier 预算，不重新解析可能已被管理员修改的档位数值。冻结参数、容量预占、新 RuntimeOperation 与 sealed_env 在同一个既有 UoW 提交；失败整次回滚。未冻结环境的半操作不对 manager 可领取。网络唤醒在提交后，丢唤醒由原 node plan 发现，不新增配置扫描器。

受理锁集合与现有路径的关系（仅约束本次新分支，不声称底座所有入口已有同一全序）：

| 路径 | 会等待的已有行 | 不允许的新增等待边 |
|---|---|---|
| save | App → AppSecretConfig | 不等待 node/operation |
| 新 rebuild 受理 | App → node → assignment → route → config | 不锁任何已存在 operation；node 后不再取 App；仅本事务私有的新 op 可由 create/admit 自锁 |
| 现有 claim/fact | 自身 operation → node → assignment/route | 本次适配不在持 node 后获取 App；ready fact 的事务先结束，再调用 commit |
| ready commit | 自身 operation → App → node/assignment → route | 本次不在持 App 后回锁 origin operation；旧 writer 状态/事实只读，既有停止/容量协议不改 |

同 app 的受理受 App 行串行，既有 node/assignment 围栏仍控制执行；活动冲突读取以拒绝/后续精确 origin 与代次检查保守处理，不把快照里暂未出现的 queued op 当作唯一安全证明。实现阶段用两个真实 SQL session 覆盖与 claim、maintenance fact、ready commit 的交错，不以单进程锁 mock 代替。若实际 helper 引入表外锁/独立 session，必须先修正此局部调用，不将上表当全仓已验证事实。

3. 现有 create 会拒绝 caller sealed_env，因此由受信 `inject_environment` 在同一 UoW 装配 seal，不把 env 放进公开 OperationInput。持久非秘密字段为 `purpose=config_restart,auto_commit=true,secret_config_revision,sensitive_env_names,approved_declaration_digest,origin_operation_id,origin_exec_ref,origin_route_epoch` 以及既有 expected_app/current/pending 等围栏；秘密只在 sealed_env。普通新部署/恢复也要从其受理快照装配，不留“先创建操作、之后读任意最新值”的窗口。
**同事务环境生产者，不复用独立提交方法冒充原子性**：现有 `inject_environment → AppRuntimeCredentialService.stage → CredentialService.issue` 会通过 CredentialRepository 和 HostedAppSubjectDAO 自开事务提交，签发审计也独立提交。新增受理路径由凭据 Owner 提供显式 `stage_in_transaction(...,session)` 公共服务入口：受信主体解析/首次创建、ApiCredential/委托子项、RuntimeCredentialBinding、签发审计都使用 caller 的同一个 AsyncSession，只 flush、不 commit；原无 session 的签发入口保持原行为。返回 token DTO 从本事务已 flush 的数据构建，不调用另开 session 的 `_to_item`/delegate 查询去读未提交行，不在提交前发 Redis/消息/外部回调。seal、任何 flush 或最终提交失败时，候选主体/凭据/binding/审计/op/预占均回滚；原幂等重放先返回已有操作，不再次签发。该新增协议只补本次受理所需的 producer，不宣称修复历史回收审计 S1，也不重写全部签发流程。

4. `deploy()` 普通同版本快速返回保持原语义；只对显式确认的 config_restart 路径创建新实例。active deploy 的查询/复用必须校验 purpose 和冻结请求，普通发布不得接管 config_restart，反之亦然；冲突复用既有忙/unknown 拒绝。重建固定 `migration_plan=[]`、不允许 snapshot/restore、`preserve_pending_version=true`，不调用 schema_evolution_service；源 version/delivery/profile/digest 和原执行 tier 不变，不重建镜像、不创建代码版本、不触发审批。
5. manager 明确声明支持 config_restart 与敏感输出协议，否则重建拒绝并提示升级；保存仍可独立完成。按既有停止证明→新实例→探活→ready 事实执行。Docker 用 Engine Env，K8s 复用执行专属 Secret/secretKeyRef，Secret 只供 serve，helper/preparer/assembler 无真实值。不能仅 docker restart，也不通过 shell 插值。
6. **本操作自身的 maintenance 路由转换**：原 manager `_deploy` 在停止旧 writer 前会上报 maintenance，backend `fact` 调 `RuntimeProjectionService.block` 会递增 route_epoch；因此不能在 ready 时仍要求原 epoch 原样不变。新增该 purpose 的受围栏投影适配：在同一既有 fact/UoW 中核验 op 的有效归属和冻结 origin route（id/version/operation/exec_ref/epoch），再幂等消费 maintenance 事实、变更路由；在该 RuntimeOperation.payload 记录非秘密 `maintenance_transition={fact_sequence,route_id,before_epoch,after_epoch}`。同一 sequence 重放只返回原事实/转换收据，不再修改当前路由（即使后来已经 serving）；没有重复 block/递增。新的 maintenance 事实若已有转换，只能验证同一尚在途的维护状态，不能追加任意 epoch 或把新路由再封回旧维护态。ready 提交只接受未变的原 route，或本操作这条事实导致的精确 after_epoch、maintenance 状态及原 route 身份，不能用“epoch 更大即可”放行。其他 stop/delete/切流或不同操作造成的改变仍拒绝；不把网络封入口当作 writer 停止证明。该记录只是既有维护事实到路由投影的幂等消费，不是密钥 applied 状态、额外表或新配置成功回执。
7. `commit_runtime_delivery` 为该 purpose 保留 current/pending 指针和原版本终态，只更新原有实例/route/credential/storage 投影；不调用 mark_runtime_online 重标版本，不写 F055 表或 applied receipt。原 expected state/current/pending/UID/代次校验不放宽，origin route 只允许上条证明的自身维护转换；审批或停用等改变关键指针时按既有冲突清理，不能覆盖新指针。保存配置变化不作为拒绝提交的条件：受理后 revision 可以继续增加，本次仍按被冻结环境完成，页面保留真实差异。
8. **明确的异步 ready→commit 消费者**：受理冻结 `auto_commit=true`，由现有 `RuntimeOperationService.fact` 在 ready 事实事务完成后调用 `AppStateService.commit_runtime_delivery` 的 config_restart 分支，不依赖一个已返回的 HTTP handler 等待。manager 仍按原协议等 serving；首次 commit 回滚时，持久 ready 事实保留，ready 上报的同参重放也必须再次尝试同一提交，不能因 fact 已存在而跳过 auto_commit。提交前 backend 进程退出由 manager 的原 operation/node-plan ready 续办触发原事实重报；不创建新操作、延长期限或配置专用调度器。manager/backend 都恢复不了则按原 deadline 显式失败，不挂成永久 pending。该消费者本身先结束 op→node 的 fact 事务，再进入 op→App 的 commit 事务，不跨两段持锁。

route/实例沿既有 UoW 原子提交。DB 回滚则只重试原 ready 提交；响应丢失或 serving/completed 重放，检查既有 op/route/exec_ref 的一致性即可返回原结果，不再增加配置结果双写。未知结果不再创建 operation/执行 DDL，不把已变更的 route 归为旧结果成功。差异仅从实际当前路由计算，不从某个成功回包推导。
9. 用户请求受理后可以继续保存；既有 operation 的 sealed_env 不替换。手动重建失败/取消/超时后，`RuntimeDeliveryCoordinator.recover` 与其他调度入口都读取现有 op.purpose/status，不把它自动转换成 recover deploy 再试；同一在途操作仍可按原期限续办/清理。旧 writer 未确认停止或 cleanup 未完成时，拒绝用户新 attempt；终态不等于已停。stop 可按原协议取消并清理，不授权强删。正常新版本发布、用户重新上线和独立崩溃自愈仍按各自既有生命周期；保存本身不会触发它们。

**④ 差异计算合同**

F055 查询服务消费 F054 公开 `running_environment_snapshot(app_id)` 只读协议，返回经租户/当前正式路由校验的内部 DTO（版本声明、operation/exec_ref/route_epoch、受限运行 env）；不从 F055 跨域查询 runtime ORM、不调用 manager inspect，不把 env 放进响应。生产方为 F054 route/operation Repository，权限在调用前由业务服务确认。

在短时一致读取中选取 current App/version、route 与对应 operation 的 sealed_env；重新确认 route identity 未变化后才报告 same/different。最新配置在本次读的 revision 上比较声明子集，未引用项忽略，缺项归一为空；不作值 trim/编码转换。A→B→A 归为 same；仅配置 revision 增长不能归 different。若无运行实例，not_running；已有执行但快照缺失/无法解密、状态未知或 route 变化不能安全比较，unknown 并给安全原因，不返回空集合冒充 same。读后再发生保存属于下一次查询，响应含所观察 revision/route epoch；前端丢弃旧请求并在保存/操作终态刷新。

运行上下文已由 operation 持有；只读服务不能返回任意历史 operation 的明文环境。日志及比较需要的受限上下文按现有操作留存管理；清理后不额外复制秘密历史，比较可用性退化为 unknown。changed_names 仅包含调用者有资格读取的当前声明名；审批人看版本缺值，不读生产差异。

**⑤ 名称、平台变量与输出保护**



保留 `BISHENG_*`、`RTM_*`、`KUBERNETES_*`、`MINIO_*`、`OPENAI_*`、`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY`（含小写），及 `PATH/HOME/LD_*/PYTHONPATH/PYTHONHOME/NODE_OPTIONS/PORT/HOST`、启动器实际保留项，统一 deny policy、两侧测试锁定。禁止别名覆盖平台身份、模型通道、启动/依赖路径或出口；后续新增平台注入名必须同改 policy。

平台不打印写请求体/环境/引擎创建请求，错误只含 ref 与安全原因；runtime status/diagnostic 递归白名单序列化，禁 raw inspect/Secret 内容，日志下载不得拼接 env。客户端埋点不得读取密钥输入。

**operation 绑定的敏感项合同**：backend 从已批准版本的 `capabilities.secrets` 生成 `sensitive_env_names`（只含名），与 revision/declaration_digest 一起冻结在可信 operation；值仍只在 sealed_env。普通客户端不能提交或修改该集合。manager 从这一 operation 的 runtime_env 取这些名的值构建内存 `SensitiveValues`，不从“当前保存值”代替历史执行值；除原有平台 token/代理凭据规则外，这些业务值不受名称启发式或最短长度限制，空值忽略，短值/普通名一样处理。跨重启从受限 operation 重新取值，不能把敏感值清单写本地状态、日志、材料、query cache 或普通 JSON 诊断。

| 生产 / 消费路径 | 必须处理的点 |
|---|---|
| backend 正式环境装配 → manager | 只为批准 formal operation 产生敏感名与真实值；probe/preview 为名称+空值，build/preparer/helper 无真实值；旧 manager/legacy 路径不能消费此合同则在注入前报缺能力 |
| `container_runner.redact` 与 Docker 正式日志 `api/platform_observe.logs` | 共同接收 SensitiveValues；按原执行绑定值处理，不再只猜 KEY/TOKEN，不允许因值短而跳过 |
| K8s `executors/kubernetes._diagnostic/logs` 与 API 日志出口 | init/serve 日志、waiting/失败信息、正式日志统一使用同一脱敏器，不遗漏 K8s Secret 中注入的普通名称 |
| legacy `api/readonly._redactions` / 日志输出 | 同步消费执行绑定的敏感集合；没有可信集合时不能把新密钥应用降级走旧启发式；无密钥旧应用仍保留原行为 |
| manager `operations.report/_failure` → backend `RuntimeOperationService.fact` | manager 在 diagnostic_tail/错误输出发出前脱敏；backend 按同一 op 的 sealed_env + 敏感名再次处理，再截断/持久化；用户状态/下载只见已处理文本 |

脱敏统一采用最长值优先的一次匹配，覆盖重叠值、Unicode 和整个多行值；**先脱敏，再按长度截断/分行/关键字筛选**。分块读取须保留最长敏感值长度所需的边界上下文，不能先对每块独立 replace；Engine/Pod API 已截断或缺失上下文、无法安全判断的片段整段省略并返回安全说明，不回退原文。敏感材料缺失/不可解密时，受影响日志/诊断不返回 raw tail；运维只得到引用名/原因和安全元数据。日志留存期间必须保留对应执行的受限脱敏上下文；清理后不再提供无法保护的原始历史输出。

这保护平台日志/故障信息出口，不承诺阻止拿到值的应用主动编码、拆分外传或写入自己的业务数据；不增加独立“日志脱敏产品”或新的审计正文采集能力。

**⑥ 前端/CLI/审读**

应用页显示“应用密钥”，列名称、配置状态、每项更新时间与批准/待审批/未引用。保存只提示“已保存”；另一区域根据 comparison 显示“运行配置与最新保存配置不一致”、差异名或“无法确认”。无运行实例显示“下次启动使用最新配置”。提供“重建使配置生效”动作及独立确认，说明重建当前版本可能短暂中断，取消不发执行请求；保存按钮、删除确认和关闭表单都不能触发重建。操作进度消费既有 RuntimeOperation；失败保留配置和真实运行状态，需再次确认才试。删除说明当前实例可能继续持旧值；不显示新旧值。PUT 成功刷新安全元数据，不以旧 revision/HTTP 成功判生效。编辑空草稿、固定 mask 不作输入值，冲突保留未提交草稿；关闭/换应用/退出清理内存，过期异步响应丢弃。

CLI 不接收值、不提供写密钥命令；manifest 带合法名称可部署，预检/状态提示缺值但不输出任何现存值。审读仅声明名/缺失/差异，由服务端按会话资格构建；不用 owner GET 列表给审批人凑数据。新增文案同时交付 zh-Hans/en/ja（含错误码），不新增中文硬编码。


## 5. 已知坑 / 反直觉事实

| 坑 | 后果 | 处理位置 |
|---|---|---|
| 保存值不会改变容器已有环境；docker restart 也不更新 Env | 保存后误报生效 | AppSecretSettings 状态 + F054 rebuild_current |
| 原 deploy 同版本 serving 直接返回 | 用户确认却没有实际重建 | Coordinator 显式 config_restart 分支 |
| 普通 deploy 重新算 schema/tier | 改变量触发 DDL或变档 | 空 migration_plan、原执行 tier/冻结 delivery，负向用例 |
| 配置 revision 不同可能只改了未引用项，A→B→A 也会递增 | 误报重建、制造停机 | F055 compare + F054 running_environment_snapshot |
| 原 stage/issue/subject 和审计会自行 commit | seal失败仍遗留候选凭据，外层回滚是假原子 | 凭据Owner显式session的stage_in_transaction及全部producer同UoW |
| accepted 后没有 HTTP 等待者，普通deploy靠 wait→commit | 实例ready后一直等serving至超时 | auto_commit=true + fact 的持久ready消费/重报 |
| claim/fact 是op→node，commit还要App | 错把node→已有op/先node后App引入互等 | §4.4③局部锁集合，无回锁旧op；两会话交错验证 |
| 原 create 和 inject_environment 是两次调用 | 受理与冻结之间读到后来值 | 同一受理 UoW封装冻结，manager 不领取无环境操作 |
| 原 recover 会自动创建另一 deploy | 手动失败后未经确认再重建 | recover/plan 消费 purpose/status，原操作只续办清理 |
| 原 active deploy 查找不区分用途 | 发布串接手动重建、误改版本状态 | Coordinator active 查找和 commit 分支 |
| 单表只记整组 updated_at 不能表达逐项最近修改 | 违背 AC-67 | 加密 entries 保存逐项元数据，不新增表 |
| maintenance 由本操作自己推进 route_epoch | ready误拒或直接放宽epoch会接受别人的切流 | fact→projection 的受围栏幂等转换及commit精确验证 |
| 当前 route 指向的环境才是运行事实 | 新值保存或旧结果回包误标最新已生效 | 公开只读快照 + 路由绑定核对，缺上下文 unknown |
| 普通管理员 shortcut 不等于 natural owner | 管理员越权改第三方值 | F055 business owner + 平台会话 |
| 日志先截断再脱敏会泄漏短值/跨行值 | 错误输出泄露配置 | §4.4⑤ 全出口操作绑定敏感集合 |
| 删保存值不是第三方凭据撤销，也不是清空现有实例 | owner 误以为旧值已不可用 | 删除提示；显式重建，第三方撤销由 owner 执行 |

历史 MVP 与三表方案只保留在历史评审/提交中；当前接手按本文。F054 B1、F056 S1 独立待办不由本设计覆盖。

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 消费者 | 破坏风险 |
|---|---|---|
| 原 deploy/limits/status、发布/审读/预览 | CLI、平台、审批 | 合法旧包不能因新 secrets 规则失效；预检空值继续真实探活 |
| `capabilities.secrets:[{name}]` + 缺值提示 | F053/F054/F059/F086 | 名称变更审批；值永不写版本/材料 |
| F055 public formal_snapshot / preview_environment / delete_for_app | F054 组合根及生命周期 | 显式 session 与用途校验；秘密 DTO 不可进通用响应或日志 |
| secrets GET/PUT/DELETE/rebuild + runtime comparison | AppSecretSettings/hook | 保存零编排副作用；取消零执行；非 owner 不取得私有值/管理权 |
| app.secret.set/delete 与 app.secret.rebuild 元数据 | F056 操作审计读侧 | action 枚举/后端白名单/前端筛选/三语 lockstep；无值无末位 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险 |
|---|---|---|
| 固定 runtime_payload_key、平台 DB/审计持久表 | 配置/Python | 丢 key 不能恢复；审计事务失败则保存回滚，不回退源码 key |
| F054 rebuild_current、running_environment_snapshot；F086 RuntimeOperation/route | 内部应用协议和受限 DTO | 当前代码需要新增分支/只读导出；不能跨层查 ORM或把公共端点变 env 读取接口 |
| 凭据Owner新增stage_in_transaction及session-aware下游Repository | 显式AsyncSession | 主体/凭据/委托/binding/审计任一仍自行commit就破坏受理原子性；不能跨session读未提交行 |
| 既有 node-plan、stop proof、容量、ready提交、cleanup | 持久执行协议 | 漏用途判断会自动重试或执行DDL；未知 writer 不交接 |
| K8s Secret/RBAC/admission、Docker Engine Env | 执行基础设施 | 旧 manager 缺能力拒绝重建；拥有编排 API 的管理员在信任边界 |
| 平台会话/Permission application/tenant context | 可信身份协议 | SAK/PAT 的资源归属不等于自然人 owner |
| UI 字体/色彩/多端/输入/确认规范、包裹 request/三语 | TS/组件 | Button/Input/Textarea/Confirm 用 done 组件；Modal/Select draft 不自造视觉模式，按已有发布页交互；窄屏遵规范 |

§4.4 的公开协议由各 owner 提供，组合根装配；F054不导入 F055 ORM，F055 不查询 F054 ORM。部署 API 权限与平台数据配置保持进程边界，没有 constitution 例外。

## 7. 测试与可观测

- 单元定向：密文绑定/坏 key/缺上下文/保留名/Unicode与多行；owner允许和管理员/超管/审批人/SAK/PAT/跨租户拒绝；保存无 manager 调用、无 RuntimeOperation；CAS 旧编辑拒绝、事务/审计回滚、最后项删除不重置 revision。声明/预览空值、短值/普通名/重叠/多行/分块日志保护覆盖各输出。
- 差异定向：当前 route 与 frozen env 精确绑定；只改未引用项、A→B→A、缺值与空值、无实例、坏密文、快照丢失、路由变化分别 same/different/not_running/unknown。不得依赖普通值摘要或新增 applied 表。
- 部署定向：取消不建操作；确认过期拒绝；原同参重放在后续改值/换版本后仍返回同一 op、异参拒绝；同版本真的重建、tier/profile/digest 不变、pending 指针不变、无 DDL/restore/构建；本操作maintenance精确转换允许、重复fact不增epoch、其他操作的epoch改变拒绝。受理冻结/凭据签发后seal或flush/最终commit失败，全链候选资产均回滚；已有请求不重复签发。两真实SQL会话覆盖App/node/assignment/op/route交错；ready首次提交失败后同fact重报提交、backend在ready后退出原operation续办；丢唤醒原计划恢复，丢响应不重建第二次；在途继续保存，完成仍显示真实差异。用途不串接、失败不被 recover 自动再试、unknown writer 不覆盖；复用底座围栏用例，不全量跑。
- 前端定向：空草稿/固定mask/失败保留输入；保存只提示已保存；差异提示含名不含值；独立确认及取消；过期响应丢弃、PUT冲突不覆盖、操作状态失败结束等待；采用现有组件和三语，无新视觉设计。
- Docker/K8s 各一次最小 E2E：owner 在 `/build/apps/{id}` 保存哨兵，记录容器/Pod UID 不变；确认前访问仍读旧配置；确认后新UID、原代码/档位/PVC及SQLite数据不变、哨兵匹配。预检/审批预览为空；失败不自动再启，用户再次确认才试；测试应用只返回是否匹配，不回显密钥。
- 编码后命令：`cd src/backend && uv run pytest test/app_publish/test_app_secret_service.py test/app_publish/test_app_secret_runtime.py`（拟新增）；UI只跑 AppSecretSettings 对应测试，runtime只跑修改的用途/日志相关文件。必要 Ruff/arch-guard/单head 定向检查；DM8 仅模型/迁移静态。当前全部为计划，未执行。
- 可观测只含 app/ref/revision/op/purpose/comparison/安全原因/耗时；不采写请求体、env、Secret inspect、普通值摘要。保存与重建分别计动作，GET比较不制造业务事件。

## 8. 后续改进 / 不打算做的事

不做自动配置生效、配置独立状态机、值历史库、外部 Vault、部署 key 轮换工具、热加载、SDK 明文读取或批量重启。只在真实新增产品需求出现时重新审查，不预建表/调度器。当前执行上下文缺失时比较可为 unknown；K8s Secret 不防有权集群管理员，应用自行编码外传不在平台日志脱敏保证内。静态前端不能注入浏览器/编译产物，声明使用却不能安全注入时明确拒绝，不暗中放宽。

设计已确认，本轮按tasks.md增量任务实施；F054 B1、F056 S1 未关闭，ARM、完整离线与正式镜像发行保持原待办，不由本设计审查替代。

## 修订历史

| 日期 | 变化 | 依据 |
|---|---|---|
| 2026-10-23（手动生效简化） | 单表配置；保存零执行；按当前冻结环境比较；显式确认复用原部署；移除自动状态/独立请求/回执与写回协议 | 用户已确认修订规格；新增设计尚未确认/编码 |
| 2026-10-23（二次修订，已由简化方案替代） | 明确固定部署 key 与运维边界、执行敏感项全链路、同一 UoW 生效与响应丢失/部分结果恢复 | 用户要求修订并复审；未新增轮换功能，尚未编码 |
| 2026-10-23 | 刷新现有能力/存储/运行协议；新增 D17–D20、四组密钥合同、同版本配置刷新与定向验收设计 | 已确认增量规格与实际代码，未编码 |
| 2026-08-17 起 | 早期发布管线/审批/档位/能力总线设计 | 旧正文见 `dda16a6`；本次不倒改历史验收事实 |
