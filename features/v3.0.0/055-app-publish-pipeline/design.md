# Design: 应用发布管线与应用密钥管理

> **2026-10-23 增量设计评审稿，待单独确认。** 用户已确认 spec；新增设计未编码。
> 现状基线 `5f2541f4bc483c24624fede9031c88c4ec6f58f4`；规格确认提交 `dda16a6502908ba8d58cff61dc350c0213b86c19`。保留 D1–D16 编号并刷新已失效的 MVP 描述，新增 D17–D20；旧任务的历史测试/行号不是本轮交付证据。
>
> [spec.md](./spec.md)（89 条 AC）· [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md)。本轮覆盖新增 AC-66 至 AC-89，以及已确认修订 AC-54、AC-56；应用密钥归 F055，绝非新的 ApiCredential。

## 1. 目标与非目标

为已有发布/审批/运行管线补齐 owner 私有应用密钥：仅保存名称引用进版本，值加密存平台数据库，已审批正式实例按当前值注入。值变化可靠刷新同版本实例，预检和审批预览只注入声明名与空值。

非目标：第三方 Vault/KMS 托管、第三方凭据有效性探测、密钥 SDK/CLI 管理、商业限额、平台模型供应商密钥编辑、批量应用重启。F054 管生命周期执行，F056 管管理员运行记录查询，不复制这两个领域。

## 2. 关键约束

- 预检、构建、依赖安装、前端编译、扫描、审批预览均不得取得真实值；预览身份和隔离存储原有规则仍有效，不以“无应用业务密钥”取消正常权限检查。
- 值只由同租户应用 natural owner 经平台会话修改；管理员、超管、审批人、SAK、PAT 均不能替 owner 写。权限 shortcut 不代替这个业务前置。
- 声明属于冻结版本并需审批；值属于应用当前配置，改值/删值不创建版本或审批。已有已上线版本与待审批版本可并存，刷新只能运行已批准当前版本。
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

沿用已有终态守卫和持久取消；新密钥刷新也遵守停止/删除围栏。删除应用成功后清除密钥值，审计按既有留存保留；删除未知/清理失败时不抢先把数据与身份当已释放。领域销毁协议改变时重审清理顺序。

### D11：档位为平台资产

资源档位继续独立管理、停用不删；密钥刷新使用已批准版本档位，不按页面可变选择重算代码/资源配置。支持动态扩缩容时另审。

### D12：操作审计与运行记录分层

生命周期/声明/密钥变更进入操作审计；模型、能力、访问记录各有现存专表。密钥事件只能含 app/ref/actor/action/time/result；API key 事件仍可含原有 key_mask，不混用两种掩码。审计模式改变时与 F056 共同审查。

### D13：已有能力总线与运行凭据保持

`runtime_capability_env`、`AppRuntimeCredentialService`、模型面/检索 OBO 已实现，不再“本轮后置”。应用业务密钥无新 SDK API；`os.environ` / `process.env` 原样读取。预检/预览继续没有正式 app credential，但有隔离存储环境。真实密钥不能混进模型供应商平台配置。新增平台能力时才扩 scope。

### D14：审批侧使用当前页面

以现有审批详情/审读页实际入口为准，不恢复过期弹窗设计；仅增名称/缺失提示和差异展示，不新增审批操作。若现有布局没有可用组件，跟随现存审读样式，不改设计系统。

### D15：发布面复用现有 settingsSlot

F055 的 `AppSecretSettings` 加进应用详情的 settingsSlot，与档位/能力并列；查询与持久操作状态由 hook 管理，store 不发 HTTP。natural owner 可编辑，其余有查看资格者仅看名称/缺失；审批人只走审读数据。失败必须 catch 并终止等待，防止新 request 拒绝 Promise 后 UI 卡住。

### D16：当前交付边界

现有发布、预览、结构演进、模型/知识能力与三交付模式已有代码；本轮只补密钥与所需 runtime 刷新，不借此重做 F086/F059。旧任务状态与当前证据分开。未来非本轮能力见 §8。

### D17：加密当前值 + 应用级配置修订（新增）

否决把值写 YAML/版本/镜像、仅哈希（运行需要取回）、复用 ApiCredential（归属/用途不同）、复用源码中固定 Fernet key。选定应用私有 DB 资产，F055 独立 cipher 适配使用部署已有 `app_runtime.runtime_payload_key`，密文封装带 `tenant_id/app_id/name/domain=app-secret-v1` 并在解密后核对防串行替换。明文只在授权写请求和正式执行内存中存在；不做明文读取接口。

使用该部署密钥而非再分发另一套 key，减少离线安装步骤；业务与运行 payload 用不同 envelope domain。值存密文，request 幂等摘要使用部署密钥派生 HMAC，不能存容易枚举的普通值哈希。部署 key 缺失/不可解密时拒绝写/正式启动，不能当作“缺值”注入空。轮换目前是显式维护操作（备份旧 key、暂停写、重加密全部未清理密文及 resumable payload、验证后切换）；直接改 key 会破坏恢复，文档必须说明。未来引入 KMS/在线轮换时重新设计 key id 与轮换协议。

### D18：值刷新复用 deploy，新增明确用途与修订号（新增）

否决直接 Docker restart（env 不变）、修改版本 injections（破坏快照）、再跑发布管线（误触审批/DDL）、复用旧 sealed_env（陈旧值）。选定 `kind=deploy` + 内部 `purpose=config_refresh`，同一 frozen delivery/version/profile/digest，新的 operation ID 与配置 revision；manager 明确声明支持此 purpose/revision，不支持则保存状态中返回能力缺失，不静默按普通升级执行。

上线刷新先持久保存后异步执行；使用既有停止确认、reservation、UID、controller lease、探活和切路由，SQLite 不拷贝、不 restore、不 migrate，空 migration_plan 且禁止恢复快照参数。不能走 `deploy()` 现有“同版本 serving 直接返回”捷径，不能走会计算 DDL 的普通上线分支。旧实例必须按原协议 retire/stop 并持久证明后交接，不能为了同版本替换绕过 `owner_operation_in_progress`。未来支持热加载配置必须有应用协议与独立规格，本轮不做。

### D19：持久 guard 与失败重试（新增）

每应用配置状态行是配置写、正式上线/恢复、维护、停用/删除共同的短事务协调点：先锁 guard，核实 owner/状态/revision，登记操作归属，事务提交后才做网络操作。拒绝 Redis 单锁、进程内锁和持有数据库事务等容器探活。已有应用补建 guard 必须利用唯一约束处理并发首建；所有入口在锁既有操作/assignment 前进入 guard，禁止反向回锁造成死锁。底层 generation/UID 围栏仍保留，guard 不是替代。

既有普通 serving 实例不是冲突；真正冲突是未完成的发布/恢复/维护/刷新/停止/删除或未知 writer。遇冲突在写入前拒绝，内容/审计成功事件不变；活动审批单本身不阻止保存值。已保存但唤醒失败仍有持久操作，重启由 backend 的持久 intent 扫描器（复用既有周期协调入口、各进程以 DB 租约/CAS 竞争）恢复，不能仅注册在某个 API lifespan 或依赖单机路径；未知 writer 不重跑 DDL、不强删。刷新失败不回滚保存值或偷偷部署旧代码；显式重试使用同一失败配置 revision 的新 attempt，原操作未确认清理前不得启动下一次。后续需并发批处理时再评估队列合并。

### D20：输入草稿与固定掩码（新增）

不返回值、不允许“查看明文”。列表只显示固定 `••••••`，不与密码框输入绑定；点击替换打开空的输入草稿，初值绝不放掩码。值控件用已落地 Input/Textarea，换行值不通过单行组件截断；写成功后清空内存草稿，失败保留当前未提交草稿。关闭/换应用/退出清理，不写 URL/localStorage/query cache/埋点。避免使用带请求体自动回显的通用错误日志；secret endpoint 的请求校验异常只返回字段位置/规则，过滤 Pydantic input/ctx/raw body，确保非法值也不会被校验错误回显或写日志。

取 current shared UI docs 的字体/色彩/多端/输入框规范，Button/Input/Textarea/Tabs 使用 status=done 的组件；Select 尚为 draft，筛选跟随当前页面已存在模式，不另造。表单/确认对话框用当前发布页已有实现；不改组件样式、不新增库。未来需要设计师定义新交互时再申请视觉评审。

## 4. 系统现状（接手必读）

### 4.1 数据流与实现状态

**已实现**：接收包 → 源码快照 → 扫描/结构预检 → manager prepare/probe → 版本/审批 → 正式 deploy；SQLite 备份/迁移由 manager 执行、对象数据由 backend 管；F086 RuntimeDeliveryCoordinator 已生成加密 sealed_env；K8s executor 已创建执行专属 Secret。缺口是 schema 拒绝 secret ref、没有值资产/管理 API/刷新用途。

```mermaid
sequenceDiagram
  participant Owner
  participant Backend
  participant DB
  participant Manager
  participant App
  Owner->>Backend: PUT secret, expected_revision, request_id
  Backend->>DB: authorize owner; lock guard; save encrypted value + audit + revision + intent
  DB-->>Backend: committed
  Backend-->>Owner: saved_revision; apply_state=pending; operation_id
  Backend->>Manager: wake durable config_refresh deployment
  Manager->>Backend: claim exact version + revision
  Backend-->>Manager: restricted runtime env from sealed current revision
  Manager->>App: fence/stop old writer; start same delivery; health check
  Manager->>Backend: execution facts with revision and UID
  Backend->>DB: commit route; CAS applied_revision; release guard
  Owner->>Backend: GET metadata and apply status
  Backend-->>Owner: names/missing/state only
```

预检/预览：`capabilities.secrets` → backend 只生成 `{NAME:""}` → probe/preview；不调用解密值函数。正式启动：批准版本声明 → 当前值快照 → seal → 受限 operation → manager → 正式进程环境；构建/preparer/helper 永不接收真实值。

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

| 模块 / 预期文件 | 做什么 | 不做什么 |
|---|---|---|
| `app_publish/domain/models/app_secret.py`、Repository、Service、v1 endpoint（新增） | 加密当前值、owner-only、CAS、审计事务、状态投影 | 不持编排权限、不返回明文 |
| `manifest_validator.py`、`schemas/app_manifest.py` | 名称声明 schema、保留项/大小校验、精确扫描豁免 | 不加载值/远程 secret URI |
| `runtime_delivery_coordinator.py` / `runtime_operation_service.py` | 可信 formal/purpose、revision env、同版本刷新 | 不在版本中存值、不重复迁移 |
| manager `operations.py` / Docker/K8s executor / admission | 检查用途/revision，按现有停止/探活/路由事实执行 | 不直读平台 DB/MinIO/secret 管理 API |
| backend reconciler / publish status adapter | 恢复提交后未唤醒的 intent，展示保存与应用状态 | 不把超时视为已停止 |
| `BuildPage/hostedApp/publish/AppSecretSettings.tsx` 与 hook（新增） | 现有 slot 内的管理区、短时内存草稿 | store 不请求，cache 不存值 |
| F056 操作审计读侧 / credential owner | 查询 secret 事件；凭据签发撤销由其 owner 写可信 app 关联 | 不从查看者参数补写历史关联 |

### 4.4 本轮增量字段与接口合同（拟实现）

**① 持久模型（拟新增，均由 Repository 处理）**

| 模型 | 字段 / 约束 | 生命周期 |
|---|---|---|
| `AppSecretValue` / `app_secret_value` | UUID id；tenant_id 默认 None/NOT NULL/索引；app_id；name（保留原大小写）；name_key（公开名称 UTF-8 的 SHA-256，统一小写 hex）；value_ciphertext LargeText；updated_by/time；唯一 `(tenant_id,app_id,name_key)`；不存明文摘要 | 停用/升级/声明移除保留；owner 显式删值或应用销毁清除 |
| `AppSecretState` / `app_secret_state` | app_id 主键；tenant_id 同上；revision；applied_revision；active_operation_id；apply_state；safe_failure_code；last_request_id / HMAC digest | 与应用同生命周期；新应用创建、旧应用首用唯一约束补建 |
| `AppSecretMutation` / `app_secret_mutation` | UUID、tenant_id 非空/索引、app_id、request_id、request_hmac、action/ref、saved_revision、operation_id、safe_result/time；唯一 `(app_id,request_id)`，无明文值/普通值哈希 | 幂等返回与待执行 intent；不得只记最后一次 request_id，历史重放仍须识别 |
| 现有 `RuntimeOperation.payload` | 非秘密 `purpose,secret_revision,expected_current_version_id,approved_declaration_digest`；秘密只在既有 sealed_env | 操作按原 diagnostic TTL 清理；不得扩散到 delivery/artifact/version |
| 审计 | app.secret.set/delete/apply/retry，app/ref/actor/revision/operation/result/time，无值、无值长度/末位 | 与现有操作审计保留一致 |

所有 tenant 模型加入租户发现导入列表并验证 API/Celery 角色都初始化；无上下文写入拒绝。DM8 保留唯一约束和非空，不用 JSON 条件查密钥。name_key 为公开名称摘要，不是值摘要；用其查重/精确索引，解密绑定后再比较原名，避免 MySQL 默认大小写不敏感 collation 错把 `KEY` 与 `Key` 合并；不引入单库专属 collation。迁移从编码时唯一 Alembic head 接续，新模型/索引名称长度在两库允许范围内。

值写事务还写结构化审计（Repository 使用同一 session），不采用“已保存后审计丢失而无证据”。拒绝请求只写脱敏失败诊断；若审计事务失败，值和 intent 一起回滚。runtime 应用结果以持久执行事实可补记，补记按 operation/action 去重；不因下游页面读取而制造事件。

**② 平台会话 API（拟新增，挂 F055 v1_router）**

| 方法 / 路径 | 请求 | 响应（data 部分） / 权限 |
|---|---|---|
| GET `/api/v1/apps/{id}/secrets` | 无值参数 | `revision,applied_revision,apply_state,operation_id,items:[{name,present,mask,updated_at,approved_reference,pending_reference}]`；natural owner 可见私有存储名，tenant admin 仅获有资格读取的声明名/状态，不暴露未引用私有项；非 owner 不显示 mask/修改者信息 |
| PUT `/api/v1/apps/{id}/secrets/{name}` | `{value,expected_revision,request_id}` | `{saved_revision,apply_state,operation_id}`；仅 owner；不回传 value |
| DELETE 同路径 | `{expected_revision,request_id,confirm_online_impact}` | 同上；仅删值，不改声明；在线引用时须确认 |
| POST `/api/v1/apps/{id}/secrets/apply` | `{expected_revision,request_id}` | 重试当前已保存配置，不能指定旧值/旧版本；owner-only |

同租户先验证业务对象，再验证登录自然人 owner；不把 super shortcut 变 owner。无资格者同一错误，不暴露存在性；跨租户过滤不能变成空成功。request_id 对每应用/动作唯一，由 AppSecretMutation 唯一约束和请求 HMAC 识别；相同参数重复返回原结果，不同参数重用拒绝；revision CAS 失败不写入。不允许客户端提交 ciphertext/runtime_env/sealed_env/tenant_id/actor_id。错误用现有业务响应 envelope 与新增 162 段占用检查后的类型/三语文案；不在设计提前猜未占用编号。

**③ 刷新与并发合同（拟新增）**

1. Guard 短事务核对 App 状态、版本、已冻结交付、活动 mutation/data_operation、节点能力、request_id/revision，再保存值和持久 mutation intent；创建执行失败时 intent 仍可恢复为显式 saved_not_applied，不丢失保存事实。若 online 且该名被当前批准版本引用，配置 revision+1、apply_state=pending，持久创建刷新意图；否则仅保存且 apply_state=not_required，不自动上线。更新未引用项无需重启；online 且有效注入子集不变时可同步确认新 revision 的 applied 状态，不伪造新实例；多个请求冲突直接拒绝，不先写后告知忙。
2. 所有正式启动/恢复从同一受锁状态读取当前 revision，生成 `sealed_env`；恢复一个仍在途的操作使用其冻结 revision。该操作活跃时禁止新值变更，避免旧执行覆盖新配置。只有操作已终结且停止/清理确认后，后续恢复新建操作才读最新值。**不能**把旧 sealed_env 一直带到新 operation。
3. `inject_environment` 增加可信 purpose / revision 参数；probe/preview 不可指定 formal，且即使旧 payload/injections 含同名值也剔除，以空值覆盖。正式校验版本确已批准、声明摘要一致，只解密声明中的名；缺项为空，解密错误为配置失败。平台保留名检查在 backend 和 manager 双侧执行。
4. F054 Coordinator 新增 `refresh_configuration`，复用 deploy 执行器但跳过同版本快速返回和 schema 计算；清晰冻结 `migration_plan=[]`、不允许 snapshot/restore，保留 current/pending 指针、版本终态、档位、代码/依赖/profile。既有普通 deploy 的恢复行为不因此变化。
5. manager 与 backend 在 claim、执行和路由提交核对 secret_revision / operation fencing；commit_runtime_delivery 的刷新分支不重标版本、不清 pending，只更新实例与配置 applied_revision。路由/实例/状态写入与 applied_revision 尽量同事务，通过应用域适配协议完成，不从 F054 跨层操作 F055 ORM。提交响应丢失从持久事实恢复，不能再跑 DDL。
6. Docker 用 Engine 环境数组；K8s 复用已有 operation 专属 Secret + `secretKeyRef`，现有 serve/preview/probe用途校验同步：真实业务值仅 serve，preparer/assembler/data helper 没有这个 Secret。Secret 命名绑定 operation/revision，清理需确认不被活跃/未知 Pod 使用。K8s admission、descriptor 允许新增 env 名但保留保留项/长度/用途边界。
7. refresh failure 区分 `saved_not_applied,failed,unknown`。探活失败不宣称生效；旧 writer 若已停止则保持安全不可用，不以新值自动修改旧实例/恢复旧代码。只有可信成功事实才推进 applied_revision；未知执行不释放 guard、不向 owner 展示“重试可强制覆盖”。停止后下一次正式恢复用最新保存值。
8. 离线旧 manager 能力缺失时不先改线上引用值：write 前准入明确拒绝并提示升级。停止应用或未引用值可保存，不暗中调用旧 manager。无需本轮发布新 tag；后续部署时 backend/manager/Chart 必须匹配支持版本。

**④ 名称、平台变量与输出保护**

保留 `BISHENG_*`、`RTM_*`、`KUBERNETES_*`、`MINIO_*`、`OPENAI_*`、`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY`（含小写），及 `PATH/HOME/LD_*/PYTHONPATH/PYTHONHOME/NODE_OPTIONS/PORT/HOST`、启动器实际保留项，统一 deny policy、两侧测试锁定。禁止别名覆盖平台身份、模型通道、启动/依赖路径或出口；后续新增平台注入名必须同改 policy。

平台不打印写请求体/环境/引擎创建请求，错误只含 ref 与安全原因；runtime status/diagnostic 递归白名单序列化，禁 raw inspect/Secret 内容，日志下载不得拼接 env。应用本身拿到值后可主动输出/外传，平台不能承诺防恶意 owner 应用；平台生成的日志不含值，应用日志走现有授权且对已知值原文做脱敏，不能把“脱敏已知字符串”宣传为防所有编码泄漏。客户端埋点不得读取密钥输入。

**⑤ 前端/CLI/审读**

应用页显示“应用密钥”，列名称、已配置/未配置、更新时间、当前版本引用/待审批版本引用/未引用。编辑用空草稿；删除说明引用仍保留、下次注入为空、线上将刷新；保存与生效分开显示（已保存，正在生效/生效失败/状态未知）。同应用 revision 变化刷新元数据，不用旧页面草稿静默覆盖；成功后查询状态，不以 HTTP 成功当作实例就绪。权限/应用切换清理输入与旧结果；失败保留未提交草稿且不误提示成功。

CLI 不接收值、不提供写密钥命令；manifest 带合法名称可部署，预检/状态提示缺值但不输出任何现存值。审读仅声明名/缺失/差异，由服务端按会话资格构建；不用 owner GET 列表给审批人凑数据。新增文案同时交付 zh-Hans/en/ja（含错误码），不新增中文硬编码。


## 5. 已知坑 / 反直觉事实

| 坑 | 后果 | 处理位置 |
|---|---|---|
| `inject_environment` 已有 sealed_env 就 return | 值变更后旧值仍被复用 | Coordinator 的 revision 校验和新 operation |
| 同版本 deploy 已 serving 直接返回 | UI 显示保存，实际没有刷新 | 新 `refresh_configuration` 分支 |
| 普通 deploy 会重新算 migration_plan | 改个 key 误触数据库维护 | purpose 强约束、空 plan、负向测试 |
| 普通 App 管理员 shortcut 不是 owner 语义 | 管理员越权修改个人第三方 key | F055 business owner 前置 + 平台会话 |
| 能力模型 `is_empty` / scope 推导目前不知道 secrets | 只有 secrets 的包被忽略或错误增加 API 权限 | manifest/schema/derive_scopes 配对测试 |
| 环境值不能通过 shell 插值传递 | 换行/美元/反引号被解释或泄漏 | Docker Env 数组 / K8s Secret；不拼命令 |
| 有了 K8s Secret 不代表集群管理员看不到 | 错误承诺绝对保密 | 原有 RBAC、受限投影、管理员信任边界 |
| 保存成功不等于部署成功 | 假成功、重试覆盖、旧结果污染 | revision/apply_state 与 request_id |
| 预检缺值 warning 不代表应用能无 key 启动 | 为了过预检跳探活 | 原健康 Gate，不伪造成功 |
| 删声明不等于删值；删值不等于撤销第三方 key | 用户误以为外部 key 已吊销 | 明确 UI 说明，外部服务吊销由 owner 负责 |

历史坑编号及早期 MVP 推导见 `dda16a6` 的本文件；当前身份/存储/执行路线以本文为准。

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 消费者 | 风险 |
|---|---|---|
| 原 deploy/deploy-limits/deployment-status、发布状态、diff/审读/preview API | F053 CLI、平台/审批界面 | 旧包无 secrets 字段必须兼容；未知字段不能全放开 |
| `capabilities.secrets:[{name}]` 与缺失 warning | manifest 消费者、审批、F054/F059/F086 | 引用改动需审批，值不入快照 |
| `resolve_formal_secret_env(app, approved_version, revision)` / `preview_secret_env(declaration)`（拟新增应用服务协议） | F054 Coordinator，内部 Python 调用 | 调用方不得自行传 `formal=true` 绕过批准检查；返回值不得进入通用诊断 |
| `configuration guard` / applied-result 回调协议 | 生命周期、维护、自动恢复、删除路径 | 任一漏接会破坏 CAS；不能只保护 UI PUT |
| `app.secret.*` 元数据审计 + mask 类型区分 | F056 | 增 action 需事件枚举、后端白名单、前端映射和三语同步 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险 |
|---|---|---|
| 平台部署拥有的 runtime_payload_key / Fernet；DB | 配置 + Python | 丢 key 不可恢复，不能退回固定源码 key |
| F054/F059/F086 的持久 operation、传输认证、generation/UID/route 提交 | HTTP + Python application protocol | 同版本快速返回、旧 sealed_env、未知 writer 都必须显式适配 |
| K8s 已有 Secret/RBAC/admission 与 Docker Engine Env | 运行基础设施 | API 可 inspect 的管理员仍在信任边界，应用不能读其他 Secret |
| F048 verified target / 自然人会话与租户上下文 | Python protocol | SAK/PAT 的 resource owner 映射不等于当前人类会话 |
| 平台共享 UI 与包裹 request，三语 locales | TS | 不能吞 Promise 拒绝、不能写假成功/空 SelectItem |

## 7. 测试与可观测

- 新增定向单元：schema 合法/非法 ref、精确扫描豁免、保留名/长度/NUL/空值/Unicode 原样；加解密与串 app/tenant 校验、缺 key/坏密文；owner 允许与管理员/超管/审批人/SAK/PAT/跨租户拒绝；CAS/幂等/事务失败无写入。
- 操作集成：formal 真值 vs probe/preview 空值；同版本 shortcut 不生效、migration/restore 不可触发；publish/stop/delete/data maintenance 并发、manager 重启、响应丢失、旧事实与未知 writer；旧 manager 能力缺失。只覆盖本轮改动路径，复用已有 F059 围栏用例，不跑所有 runtime/backend。
- 前端定向：固定 mask 不提交、失败保留草稿/结束等待、saved vs applied、旧请求不覆盖、新 revision 冲突、权限切换清理。沿用共享组件，不做视觉改版。
- E2E 必须走真实业务入口：owner 在 `/build/apps/{id}` 发布设置创建测试密钥；预检/审批预览读取空，批准正式实例收到值；在线替换保持相同版本/delivery/SQLite 数据，记录 revision+新实例；停用更新不自动上线、恢复读最新；失败只标已保存未生效，重试不迁移。测试应用仅返回“值是否匹配”布尔值/摘要测试哨兵，不回显真实秘密。
- 编码后可执行 `cd src/backend && uv run pytest test/app_publish/test_app_secret_service.py test/app_publish/test_app_secret_runtime.py`（拟新增载体）；UI 运行对应文件 Jest。先完成有意义的 red→green 与 L1，再补真实 Docker/K8s 定向 E2E；未执行的不写通过。
- 结构化观测仅 app/ref/revision/operation/purpose/state/reason/duration；拒绝 body/env/raw inspect 日志。DM8 仅 model/迁移静态核查；必要 lint/arch-guard/单 head 只对改动验证。

## 8. 后续改进 / 不打算做的事

不做外部 Vault、key 自动轮换、实时热加载、密钥版本历史恢复、批量更新；当前用同一部署加密 key 的维护成本已说明，后续有合规要求再独立设计。原应用和三交付模式保持兼容；静态应用无服务端进程时不能承诺注入到浏览器或编译产物，明确“该运行形态不支持业务密钥”，保留原静态运行路径。

三份增量设计单独获确认后才拆任务。正式 CI 镜像/tag、ARM 与既有未完成离线验收仍在原清单，不自动完成。

## 修订历史

| 日期 | 变化 | 依据 |
|---|---|---|
| 2026-10-23 | 刷新现有能力/存储/运行协议；新增 D17–D20、四组密钥合同、同版本配置刷新与定向验收设计 | 已确认增量规格与实际代码，未编码 |
| 2026-08-17 起 | 早期发布管线/审批/档位/能力总线设计 | 旧正文见 `dda16a6`；本次不倒改历史验收事实 |
