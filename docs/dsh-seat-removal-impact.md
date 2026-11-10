# DSH 去除 Gateway 与席位控制技术评估

> 实施说明：本文保留实施前的影响评估；当前代码职责和实际结果以 [正式设计](../features/v3.0.0/110-dsh-local-access/design.md) 与 [验证记录](../features/v3.0.0/110-dsh-local-access/validation.md) 为准。


DSH 客户端应直接登录 BiSheng 并使用获授权的模型，无需部署 Java Gateway，无需商业 License、人数上限或管理员分配席位。登录授权、专用凭证、设备会话和撤销机制统一由 BiSheng 后端提供。

模型额度保留部门与个人两种配置方式，按用户和模型分别计算：有个人配置时使用个人额度，没有个人配置时继承部门额度。部门额度由每位成员独立使用，部门配置 100 万 Token 即每位成员每月各有 100 万，不设部门共享池。

本次仅修订技术评估文档，未修改业务代码、数据库或部署。以下新增模块、接口与迁移步骤均为待实施方案。

## 已确认的目标与评估基线

### 已确认的业务规则

| 项目 | 目标 |
| --- | --- |
| 部署 | BiSheng 标准服务和现有基础设施即可运行 DSH，不部署 Gateway，不调用其内部接口 |
| 登录 | 通过 BiSheng 的浏览器登录和确认授权完成桌面登录；保留 PKCE 与本机回调 |
| 商业控制 | 取消 DSH License、免费人数、席位购买、分配、释放、重新分配及超额回收 |
| 模型授权 | 部门或个人可分别配置各个模型的月 Token 额度 |
| 优先级 | 个人单独配置优先；未单独配置则继承部门额度，不将两者相加或取较大值 |
| 部门额度 | 每位成员独立获得额度、独立计量，不建立部门公共额度池 |
| 其他约束 | 保留账号与租户有效性、模型访问权限、会话撤销、实际用量及审计 |

去除 Gateway 指 DSH 运行架构不再包含该服务、远程验权或对其共享密钥的依赖。现有 Gateway 还提供部分 SSO 和其他商业能力，停止部署后不能假定这些 Java 自处理接口仍然可用；本次不将这些独立能力全部迁入 Python。DSH 必须能够通过 BiSheng 原生登录独立完成全流程。

### 源码基线

| 项目 | 本次核对的代码基线 | 用途 |
| --- | --- | --- |
| BiSheng | `feat/bisheng-work-110`，`a2b7860d8efed08fdee41e9ecdf46560ed5ef0bb`，创建自 `origin/main` 后已同步模型审计 | Python、管理端、额度策略、计量及模型审计 |
| bisheng-gateway | 本地 `feat/dsh-access`，`faed249a96ea43a4c65b90765dd4054bf6e55722` | 确认需要由 Python 承接的登录和会话能力 |
| bisheng-work | 本地 `feat/3.0.0-dsh-audit`，`73961535622bee347ab4044f2e9ec14d255fbc17` | 确认桌面端固定路径、响应校验和凭证使用方式 |
| gen_license | 本地 `main`，`d7a32207ef2e0fde00d00cbc1c23ab12928f57d7` | 确认退出 DSH 商业授权签发的范围 |

日期：2026 年 10 月 20 日。独立仓库的快照用于评估，不代表它们已与本分支完成联调。桌面仓库的未提交文档未修改。

## 实施前实现与目标之间的差距

### Gateway 目前承担的职责

| 当前职责 | 当前执行位置 | 去除后的处理 |
| --- | --- | --- |
| 创建登录授权请求、保存 PKCE 和回调绑定 | Gateway AuthorizationService 与 Redis | 迁入 BiSheng DSH 模块 |
| 浏览器认证、确认授权、一次性 identity ticket | BiSheng IdentityService；读取授权绑定时请求 Gateway | 保留平台登录与 ticket，绑定读取改为本地服务 |
| 校验 PKCE、换取 access 和 refresh Token | Gateway TokenService | 迁入 BiSheng |
| 设备会话、refresh 轮换、重放检测与撤销 | Gateway SQL SessionRepository | 迁入 BiSheng 自有会话表 |
| 每次访问的在线会话校验 | Python 验 JWT 后调用 Gateway introspection | Python 本地验证签名、身份及数据库会话状态 |
| 保存正额度时分配席位 | Python → Gateway assign-batch | 删除该步骤，策略保存直接处理权限和额度 |
| License、容量和自动回收 | Gateway LicenseState、SeatLimitReconciler | 删除，不迁入 Python |
| 资料和用户名搜索投影 | Python outbox → Gateway profile 存储 | 查询 BiSheng 用户模块，停止远程资料投影 |
| 模型可用性、额度、计量和统计 | BiSheng DSH 模块 | 保留并解除 Gateway 依赖 |

因此，删除 Gateway 配置或隐藏席位页面无法完成目标。Python 当前没有独立的桌面 Token 签发及持久会话能力，必须补齐这些能力。

### 现有额度继承已经具备主要能力

[subject_policy.py](../src/backend/bisheng/dsh/domain/repositories/subject_policy.py) 的 `effective` 与 `user_permissions` 已实现个人优先，没有启用的个人配置时回落到继承来源；当前继承来源还包括部门及角色。个人配置为 30 万时，即使部门额度是 100 万，现有计算也使用个人 30 万。

当前问题主要是授权保存和接入状态仍与商业席位耦合：

```text
个人正额度保存 → allocate_person → allocate_seats → Gateway assign-batch → 提交策略
部门额度保存 → 冻结当前成员 → Gateway assign-batch → 提交部门策略
模型权限页面 → include_seats=true → 远程 License 与逐用户席位查询
```

去除这些步骤后，应保留现有有效策略计算、版本控制与 Redis 一致性，避免另建第二套额度算法。

## 无 Gateway 的登录和会话方案

### 登录流程

```text
DSH 客户端 → BiSheng 创建授权请求，绑定 PKCE、state、本机回调及设备信息
浏览器 → BiSheng 原生登录 → /desktop-login 确认授权
BiSheng → 签发短期一次性 identity ticket → 回调到客户端 127.0.0.1
DSH 客户端 → BiSheng 提交 ticket 和 code_verifier
BiSheng → 校验绑定与当前身份 → 原子消费 ticket → 创建本地会话与 refresh 摘要
BiSheng → 返回 DSH 专用 access Token、refresh Token、用户与租户信息
DSH 客户端 → 直接请求 BiSheng 的模型、用量及插件接口
```

保留现有回调约束：IPv4 loopback、动态端口和固定 `/dsh/callback` 路径；授权请求绑定 client_id、redirect_uri、PKCE challenge 和 state。浏览器确认继续校验平台身份、Origin 和 JSON 请求。桌面端不提交可信 user_id、tenant_id，也不保管平台账号密码。

一次性 ticket 必须在 PKCE 和绑定通过后原子消费，重复换证不能创建多个会话。SQL 创建失败而 ticket 已消费时，客户端重新登录；不能靠重复消费 ticket 补造会话。授权请求和票据过期、拒绝授权、并发重试及回调丢失均需保留明确结果。

主要复用：[IdentityService](../src/backend/bisheng/dsh/domain/services/identity.py)、[TicketRepository](../src/backend/bisheng/dsh/domain/repositories/tickets.py)、[浏览器授权接口](../src/backend/bisheng/dsh/api/endpoints/identity.py) 和现有桌面浏览器流程。

### 新增的后端能力

以下为拟新增职责，按现有 DDD 目录放入 `bisheng/dsh/`，接口只调用服务，不直接操作 ORM。

| 能力 | 技术要求 |
| --- | --- |
| 授权请求服务与 Repository | Redis 保存短期授权请求和绑定；准确读取剩余 TTL；并发实例共享，禁止进程内字典 |
| Token 服务 | ticket 换证、签发 DSH 专用 JWT、refresh 轮换；返回现有桌面端期望的字段 |
| 会话 Repository | SQL 存储用户、租户、设备、版本、绝对到期时间、状态与凭证代次；不再关联席位 |
| refresh Repository | 只存高熵 refresh 的摘要；同一会话内唯一代次；轮换、重放检测和撤销具有事务一致性 |
| 访问校验服务 | 校验签名、typ、issuer、audience、有效期、会话主体和状态，再检查当前账号与租户有效性 |
| 设备管理服务 | 本人查看及撤销自己的设备；租户管理员在授权范围内查询和管理；无席位分配操作 |
| 入口保护和维护 | 分布式登录限流、过期记录清理、敏感字段脱敏；沿用现有错误信封和请求 ID |

会话与 refresh 使用短 SQL 事务、唯一约束和明确锁顺序，覆盖 MySQL 和 DM；不能依赖 Java 服务原有的席位表锁。账号或租户无效时，后续模型请求及刷新仍须拒绝；认证依赖不可用时不能直接放行。

refresh 仅凭摘要定位时尚无可信租户上下文，需由专门 Repository 读取最小会话定位信息，再进入真实租户作用域校验。不能信任客户端传入的租户，也不能把整条 DSH 链路加入全局租户绕过名单。

### 凭证和密钥

新 DSH 身份以 `tenant_id`、`user_id`、`session_id` 为核心；如使用凭证代次，使用会话自己的版本，而非席位 `grant_version`。保留 DSH 专用 Token 类型及用途校验，普通 Web JWT、PAT、SAK 不能冒充桌面凭证。

当前 Python JWT 校验还强制检查原十项 claims 及字段数量。改为本地会话身份时，必须同步调整签发端与校验端的精确契约，不能只从签发结果删除席位字段。

原 `shared_trust.py`（已删除）从 `sso_sync.gateway_hmac_secret` 派生 Token 及双向服务签名密钥，这项依赖已由 [token_keys.py](../src/backend/bisheng/dsh/infrastructure/token_keys.py) 退出。采用 BiSheng 自有的密钥管理方式，为 DSH 提供独立用途的签名密钥，并支持所有 API 副本一致读取和轮换。可参考 [平台密钥持久化模式](../src/backend/bisheng/user/domain/services/jwt_secret.py)，不能每个进程启动时各生成一份，也不能直接把 Web JWT 当作 DSH Token。

生产配置中无需填写 Gateway 地址或 Gateway HMAC 才能启用 DSH。身份 Token 的签名验证继续保留；商业 License 验签整体退出。

### 对外接口兼容

建议新增标准 v1 路径，并保留旧路径为 **FastAPI 内的兼容路由**，二者调用同一套 Python 服务。兼容路由不转发到 Java，也不要求部署额外服务。

| 能力 | 建议的标准路径 | 旧客户端路径与兼容要求 |
| --- | --- | --- |
| 能力发现 | `GET /api/v1/dsh/config` | 保留当前响应语义 |
| 创建授权请求 | `POST /api/v1/dsh/authorizations` | `/api/dsh/authorizations` 由 Python 直接处理 |
| 换证和刷新 | `POST /api/v1/dsh/token` | `/api/dsh/token` 由 Python 直接处理 |
| 退出当前会话 | `POST /api/v1/dsh/logout` | `/api/dsh/logout` 由 Python 直接处理 |
| 浏览器确认授权 | `POST /api/v1/dsh/authorize` | 保留平台身份与防 CSRF 规则 |
| 模型、调用、用量 | `/api/v1/dsh/models`、`chat/completions`、`usage` | 路径保留，鉴权改为 Python 本地会话 |
| 个人设备、资料和用量 | `/api/v1/dsh/me/*` 及已有 profile 接口 | 保留本人权限语义 |
| 管理员设备管理 | `/api/v1/dsh/admin/users/{user_id}/sessions` 及所需会话操作 | 改为直接按用户和租户定位，不再查询席位 |
| 审计会话标题 | `POST /api/v1/dsh/audit/conversations/title` | 保留当前桌面端能力协商和标题更新，改用本地会话鉴权 |

BiSheng 当前统一 v1 router 已带 `/api/v1` 前缀，旧 `/api/dsh/*` 必须在应用层另挂精确别名，不能误注册为 `/api/v1/api/dsh/*`。同时检查 [HTTP 中间件](../src/backend/bisheng/utils/http_middleware.py) 的精确 credential route 清单：公共授权和换证使用各自校验，不能被普通 Web Cookie 身份或错误信封覆盖；管理员及浏览器确认接口仍执行平台鉴权。

桌面端 `contract.js` 固定了旧路径，`parseAuthorization` 还要求返回相同 origin 下的 `/desktop-login`；`parseConfig` 只接受白名单中的协议版本。保留路径、请求响应和 opaque Token 使用方式时，可争取让旧客户端重新登录后继续使用，但必须实测。若更改公开字段或协议版本，需同步更新桌面端的兼容版本清单，不能仅在后端修改版本号。

## 部门与个人额度的精确规则

### 按用户和模型分别决策

```text
存在启用的个人模型配置 → 使用该个人额度
否则存在有效部门模型配置 → 继承部门额度
否则 → 无该模型权限
```

个人配置只覆盖对应模型，不影响该人员的其他模型。继承得到的是个人当月额度；使用量始终按 `tenant_id + user_id + model_id + month` 计量，不按部门共用余额。

| 部门对模型 A 的额度 | 个人对模型 A 的配置 | 最终月额度 | 原因 |
| --- | --- | --- | --- |
| 100 万 | 未配置 | 100 万 | 默认继承 |
| 100 万 | 单独配置 30 万 | 30 万 | 个人优先，允许低于部门 |
| 100 万 | 单独配置 200 万 | 200 万 | 个人优先，允许高于部门 |
| 100 万 | 显式个人额度为 0 | 0，无模型使用权限 | 零额度是明确配置，不能回退部门或解释为不限量 |
| 100 万 | 取消个人配置 | 100 万 | 恢复继承，不清零用量 |
| 无 | 单独配置 30 万 | 30 万 | 不要求先获得部门授权 |
| 无 | 未配置 | 0，无模型权限 | 不默认开放所有模型 |

当前字段可继续表达这三种状态：没有个人行或 `enabled=false` 表示继承；`enabled=true` 且额度大于零表示个人额度；`enabled=true` 且额度为零表示该模型个人额度为零。界面需区分“使用部门额度”和“个人额度为零”，不能只用一个数值 0 同时表达两者。

### 多部门和上下级部门

用户已明确部门独立额度与个人优先。对于未进一步指定的组织细节，建议沿用当前实现：从人员所属有效部门及其祖先部门收集模型额度，同模型取有效部门来源的最大值，不累加、不仅限主部门。这个细节需要在正式 spec 中明确，避免实现时无意改成最近部门覆盖。

例如父部门 100 万、子部门 50 万，按现有规则继承 100 万；若只希望子部门 50 万覆盖父部门，属于另一项继承规则变更。个人 30 万仍覆盖上述全部部门来源。

部门新增成员、转部门、成员移出和部门额度变动，通过实时有效策略反映，不生成个人授权副本，不要求管理员重新保存来分配席位。组织变动不改变用户当月已用量；额度调低到低于已用量时，剩余额度按 0 展示并拒绝新请求，在途请求按现有结算规则完成。

### 角色历史与策略一致性

现有继承还读取 ROLE；目标授权入口聚焦部门和个人。建议新规则只让部门参与默认继承，历史角色授权先盘点、迁移并校验结果，再退出角色来源，不能直接删记录导致权限丢失，也不能在界面隐藏后仍让角色隐式扩权。

现有 [role_migration.py](../src/backend/bisheng/dsh/domain/services/role_migration.py) 不能原样当作无损迁移：它会取个人与角色额度的最大值，可能把当前个人 30 万、角色 100 万的用户抬到 100 万，违背个人优先。迁移必须保留已有显式个人配置；对仅依赖角色的人员规划部门或个人配置，并逐模型比较迁移前后最终额度和来源。

运行时 `effective`、管理展示 `user_permissions`、模型列表、调用准入、usage 及 Redis 投影都必须读取同一套规则。部门策略或成员关系变化后，有效版本和 Redis 限额应随之更新，不能只改页面显示，也不能因切换来源重新初始化用量。

## 保留当前模型审计能力

当前分支已包含模型输入输出采集、会话分组与父子会话、正文读取和标题更新。`audit_runtime.py` 记录真实 tenant_id、user_id、session_id；审计记录本身没有新增席位字段依赖，迁移后继续使用真实 Python session_id。历史会话和请求标识保持不变，不为了更换认证服务重建或清空审计数据。

[会话标题接口](../src/backend/bisheng/dsh/api/endpoints/model_audit_title.py) 复用 `desktop_principal`，应随统一鉴权一起迁移；标题更新不执行模型准入或扣额度。`/dsh/config` 中已有 audit_context、audit_conversation_title 能力字段必须保留，管理端 `model-audit` 页签、管理员读取范围、审计 OFF/METADATA/CONTENT 模式及现有异常标记也保持。

[审计密钥](../src/backend/bisheng/dsh/infrastructure/model_audit_keys.py) 通过 `BS_DSH_MODEL_AUDIT_KEYS` 管理，独立于 License 和 DSH Token 密钥；去除 Gateway 时不能一并删除，也不能通过更换 Token 密钥使历史审计正文无法解密。审计采集和树构建 worker、状态收敛与退出 drain 仍需保留，远程资料同步任务的退出不能影响它们。

## 文件级改动范围

### BiSheng 新增或重构

以下路径以 `src/backend/bisheng/` 为根。

| 文件或模块 | 改动范围 |
| --- | --- |
| `dsh/api/endpoints/`、`dsh/api/router.py`、应用 router 注册 | 新增本地授权请求、Token、logout 和必要的设备操作；挂载标准路由及旧路径别名 |
| `dsh/domain/services/identity.py`、`domain/repositories/tickets.py` | 授权绑定改本地读取，保留浏览器确认及一次性 ticket；换证在同模块完成 |
| 拟新增会话及 refresh 的 models、repositories、services | 建立 BiSheng 自有会话真相，按真实用户和租户定位，无 seat_id 前置条件 |
| `dsh/domain/services/access.py`、`dsh/access_runtime.py`、`api/dependencies.py` | Principal 与本地会话校验重构；删除 GatewayClient、远程 introspection 和双向服务认证的初始化 |
| `dsh/domain/services/self_service.py`、`admin.py` | 个人与管理员设备管理改用本地会话服务；资料直接查询用户模块 |
| `dsh/domain/services/admin_policy.py`、`dsh/admin_runtime.py` | 移除个人 allocate 回调和部门 assign-batch；保留策略版本、管理员和模型校验、SQL/Redis 协调 |
| `dsh/domain/repositories/subject_grant.py`、`domain/models/subject_grant.py` | 退出商业分配成员快照和跨服务意图；策略幂等、历史 PENDING 另行收敛 |
| `dsh/domain/repositories/subject_policy.py`、`policy.py` | 保留个人优先、部门继承；清理席位容量参数和仅用于容量的预留；角色来源按迁移后规则退出 |
| `dsh/domain/services/access_status.py`、`domain/schemas/admin.py` | 去掉 License 与逐用户验席；改为展示有效模型额度及来源 |
| `dsh/domain/services/model.py`、`domain/schemas/usage.py`、`domain/models/model_call.py` | 新调用使用本地 session_id，去掉新数据对 seat_id 和席位 grant_version 的必填要求 |
| `dsh/infrastructure/quota_redis.py`、Lua、用量 Repository 与恢复服务 | 区分历史事件与新事件，调整不可变身份校验，保留幂等结算、UNKNOWN 和累计量 |
| `dsh/audit_runtime.py`、审计 models/services、`api/endpoints/model_audit_title.py` | 审计采集沿用真实本地会话；保留正文、会话层级、标题和管理员数据边界 |
| `dsh/domain/services/profile.py`、`worker/dsh/profiles.py`、`user/domain/services/user.py` | 退出向 Gateway 发送资料的 outbox、全量扫描及用户变更钩子；保留用户模块自身的身份和资料版本 |
| `worker/dsh/operations.py`、`dsh/operations_runtime.py`、`worker/dsh/registry.py` 与 Beat | 去掉席位和资料远程同步任务；保留策略恢复、计量投影、模型审计及必要会话清理 |
| `utils/http_middleware.py`、`dsh/api/responses.py` | 新公共和专用凭证路径精确归属，保留 DSH HTTP 错误格式、日志和租户边界 |
| `core/config/dsh.py`、`dsh/config.py` 与示例配置 | DSH 启用不再要求 gateway_internal_url；退出远程超时、HMAC 和服务签名设置；增加本地会话所需配置及校验 |
| `common/errcode/dsh.py` 及共享三语错误文案 | 商业席位与 License 错误不再用于新请求；保留会话、模型和额度错误，不复用旧错误编号 |

### 应删除的 DSH 远程依赖

主调用退出且历史操作处理完成后，删除 `dsh/infrastructure/gateway_client.py`、双向内部服务签名专用代码、`seat_allocation.py`、`seat_pages.py` 及无其他用途的商业管理适配。`shared_trust.py` 中 Gateway 派生依赖由本地 Token 密钥服务替代。

`/api/v1/internal/dsh/identity/redeem`、`identity/check` 原用于 Gateway 跨服务调用；目标架构中改为内部服务方法，不保留无需使用的 HTTP 接口。所有 `GatewayClient` 注入、runtime.gateway、profiles/upsert、management/read、assign-batch 和远程 operation 查询均应退出，包括后台扫描和用户资料变更这种低频路径。

不要删除整个 DSH worker、共用操作表或用户模块。原本处于同一文件中的额度、用量和资料读取仍有独立用途；例如 `profile_scope` 同时被其他代码用于租户作用域，应按调用点保留或迁移。

### 管理端与客户端

| 范围 | 改动范围 |
| --- | --- |
| Platform `pages/DshPage/sections.ts`、`index.tsx` | 移除授权与席位页签；默认模型与额度；旧 tab 链接落到有效页 |
| `pages/SystemPage/dsh/index.tsx`、`SeatsView.tsx`、`CommercialLicenseDialog.tsx`、`licensePresentation.ts` | 删除商业卡片、容量统计、购买弹窗及后台 License 读取 |
| `pages/ModelPage/manage/dsh/useAccessMembers.tsx`、`DepartmentAccessTree.tsx`、`ReauthorizeSeat.tsx` | 停止 include_seats 和重新分配；展示个人配置、部门来源及最终额度 |
| `ModelAccessDialog.tsx`、`SubjectPolicyControls.tsx`、`useUserPolicyDrafts.ts` | 保留部门和个人保存；明确恢复继承与显式零额度；保存不依赖 Gateway |
| `controllers/API/dsh.ts`、`types/dsh.ts`、`utils/dshRequestError.ts` | 删除席位和 License API/类型/错误特殊逻辑；保留策略保存与会话管理 |
| `pages/SystemPage/dsh/ModelAudit*`、`useModelAudit*` 及审计 API | 保留当前模型审计页签、层级、正文和筛选；回归本地身份下的管理员范围 |
| Platform 与 Web client 的 DSH 个人入口、设备和用量展示 | 指向本地会话和用量服务；保留下载、启动、个人模型用量与退出 |
| bisheng-work `packages/dsh-desktop-enterprise/contract.js`、`contract.d.ts` | 核对路由、协议版本和响应；改标准路径时保留旧服务兼容或明确版本要求 |
| bisheng-work `src/main/enterprise/enterprise-service.ts`、凭证 broker 与 callback server | 验证换证、refresh、退出、重新登录和旧凭证失效；不缓存平台密码，不绕过 PKCE |
| 桌面企业插件 `client.js`、`error-copy.js`、`openai.js` | 移除购买或分配席位提示；保留会话失效、模型未授权和额度耗尽处理 |
| 现行接口、部署、错误与发行文档 | 将 DSH 标记为 BiSheng 内建能力；退出新版本 DSH 付费 License 签发 |

Platform 相对路径以 `src/frontend/platform/src/` 为根。新 UI 不增加第三套组件或额度算法；实施时按当前设计规范和三语 i18n 规则处理。历史操作审计保留，不为删除席位而删除其余操作记录或重新开放隐藏页签。

### 配置与部署

标准部署的 API 流量直接到 BiSheng，`/api/dsh/*` 的兼容路由也必须能到达 FastAPI。检查生产 Nginx/Ingress、开发 Vite 和客户端所填平台 BASE，覆盖 `/desktop-login`、`/api/v1/dsh/*` 以及旧 `/api/dsh/*`，不能只让模型接口直连而登录仍到 Java。

`DshSettings` 目前使用 `extra=forbid`，并在 enabled 时要求 Gateway 地址。需同时调整构造校验和旧配置兼容：过渡期可接收已废弃字段但不使用，之后再按版本移除；直接删字段却沿用旧 YAML 会造成启动失败。新增配置不能引入旧镜像不识别的已启用顶层 key。

无 Gateway 模式必须在 `sso_sync.gateway_hmac_secret` 未配置、Gateway DNS 不存在、没有 Gateway 数据库和 Java 进程的条件下正常启动及完成 DSH 流程。已有模型、用量、MinIO、Redis 等基础设施沿用；取消 Gateway 不意味着取消这些依赖。

其他历史 Gateway 自处理入口需从独立部署的必需链路中排除，特别是商业状态读取及 SSO 登录入口。它们不能因不可达而阻断 BiSheng 原生登录、主页面或 DSH。此项只要求独立部署正确运行，不要求将所有 Java 商业功能重新实现。

## 数据结构与历史兼容

### 新会话表不包含席位

建议在 BiSheng 数据库新增自有 `dsh_session`、`dsh_refresh_token`，名称在正式设计中固定。会话直接存 tenant_id 和 user_id，不从 Gateway 数据库回查席位；refresh 通过 session_id 关联。全新安装不创建或访问 Gateway 的 `gt_dsh_*` 表。

新表按现有 SQLModel 发现和建表约定落地；现有表结构变更通过 Alembic，同时满足 MySQL 和 DM。账号、设备、会话与 Token 的关系使用真实记录，禁止为兼容旧字段给所有用户写固定 seat_id 或伪造 grant_version。

### 调用记录与事件协议

目前 [DshPrincipal](../src/backend/bisheng/dsh/domain/services/access.py)、[UsageEvent](../src/backend/bisheng/dsh/domain/schemas/usage.py)、[DshModelCall](../src/backend/bisheng/dsh/domain/models/model_call.py) 及 [Redis 计量适配](../src/backend/bisheng/dsh/infrastructure/quota_redis.py) 均依赖 seat_id 和 grant_version，SQL 两列非空且有版本约束。完全去除 Gateway 后，不能继续要求新请求拥有旧席位身份。

建议首轮将旧字段保留为可空历史字段，并调整 CHECK：历史值存在时仍满足原约束，新事件使用真实本地 session_id，不填写商业席位字段。同步更新 Pydantic、事件序列化、Redis 身份比较、SQL 投影、重放和自动恢复，使它们能明确区分旧事件与新事件。不可只放宽 SQL 而让旧 Pydantic 继续拒绝新事件。

[月用量表](../src/backend/bisheng/dsh/domain/models/monthly_usage.py) 的主体仍是租户、人员、模型和月份。历史调用、累计用量、UNKNOWN 状态、请求 ID、投影幂等性和在途结算全部保留。会话迁移、部门变动、个人配置改变均不重置月用量。

物理删除历史 seat_id 列、旧回执或 Gateway 数据不属于停用服务的前置步骤；保留历史档案不等于运行时依赖 Gateway。数据转换使用单独带 dry-run 和核对报告的运维程序，不在 Alembic revision 中批量改现有记录。

### 旧会话和旧操作

建议旧 Gateway access/refresh 统一失效，升级后用户重新登录，由 Python 创建新会话；不跨库复制 refresh 摘要和旧授权代次，也不保留远程 introspection 兜底。旧客户端收到失效后必须能回到浏览器登录流程。

旧席位 REVOKED 不再是新登录的准入条件。平台账号和租户有效的人可重新登录，但只能使用当前部门或个人策略允许的模型；旧会话不会复活。需要继续禁止某个账号使用 DSH 时，应明确采用账号、会话或单独的准入规则，不能暗中保留席位分配门槛。

旧 `dsh_admin_operation` 共表仍有策略和用量业务，保留历史数据。对未完成席位、资料远程同步操作做明确退役处理，记录真实终止原因，不能标记为已送达 Gateway；策略已提交或只差 Redis 完成的操作必须按原操作号完成或明确失败。部门授权 PENDING 也不能随表清理丢弃。

## 发布和回退范围

1. 固定 BiSheng、桌面端与旧 Gateway 的版本，盘点当前策略、角色来源、部门关系、旧会话、UNKNOWN 和未完成操作；备份历史档案。
2. 完成本地登录和会话模块、事件双格式兼容、SQL 结构调整、策略去占席及所有远程调用退出。以 Gateway 完全不存在的独立环境验收。
3. 准备切换窗口，暂停旧 DSH 新登录和授权变更；让在途请求结算并收敛旧事件投影，逐类处理未完成操作。不得清空积压或放弃未知用量。
4. 更新 API 与全部 worker，确认新 schema 和事件格式一致；切换 Nginx/Ingress 到 Python 路由，启用本地签发。旧凭证失效，新登录创建本地会话。
5. 更新管理端及需要升级的桌面版本，验证个人覆盖、部门继承、模型调用、设备撤销及插件市场。确认所有必需链路无 Gateway 后再停止其部署。

无需从旧环境迁移会话即可全新部署；已有环境则必须保留历史用量及处理旧事件。上线不能在新旧 API/worker 任意混跑，因为旧代码仍强制校验 seat_id，且旧客户端路由可能指向不同的会话真相。

回退到旧 Gateway 架构不是普通镜像回滚：新 Python 会话不能由旧服务刷新，用户需要再次登录；新产生的无席位事件必须可被回退版本读取或先完成结算，否则旧 worker 无法处理。旧 Gateway 重启还可能按 License 容量回收原席位。优先准备保留本地会话和新事件兼容性的修复版本；确需回旧版，需单独验证路由、凭证、事件和策略兼容，不能恢复旧用量备份覆盖上线后的真实消耗。

## 实施后的验收清单

以下为完整发布验收要求；本地实施结果与真实环境缺口见 [验证记录](../features/v3.0.0/110-dsh-local-access/validation.md)。

| 场景 | 验收结果 |
| --- | --- |
| Gateway 进程、DNS、数据库和 HMAC 均不存在 | 原生登录、DSH 换证、刷新、模型列表、调用、用量、退出及设备管理全部可用 |
| 新部署、未配置 License、第 11 位及更多用户 | 不需要商业签发或人工分配，无人数上限和自动回收 |
| PKCE 错误、state 不符、非法回调、ticket 重放或过期 | 拒绝换证；无重复或串用户会话 |
| 并发首次登录、多 API 副本与重启 | 授权状态共享，签名密钥一致，设备会话和 refresh 事务正确 |
| refresh 并发与重放、本人设备撤销、logout | 旧凭证失效；会话族和其他设备行为符合契约 |
| 账号或租户无效、跨租户访问、JWT/PAT/SAK 冒充 | 持续拒绝，不因去商业化放宽身份或管理边界 |
| 部门 100 万、无个人配置 | 每位成员分别获得 100 万，不共享余额 |
| 部门 100 万、个人 30 万或 200 万 | 对应人员分别使用个人 30 万或 200 万，不取最大、不相加 |
| 个人显式零额度与取消个人配置 | 前者无该模型权限，后者恢复部门额度；已用量不重置 |
| 个人仅配置模型 A | 模型 B 仍按其部门配置继承，不被全用户覆盖开关影响 |
| 多部门、父子部门、成员新增和转部门 | 按确定的部门规则计算，版本和 Redis 同步；不再占席或复制个人策略 |
| 角色历史迁移 | 每用户每模型核对最终额度；低额度个人配置不被角色抬高 |
| 额度降低、当月用尽、UNKNOWN 和 SSE 中断 | 原额度与真实计量规则有效，已接纳请求如实结算 |
| 新旧 UsageEvent、Redis 积压及自动恢复 | 历史数据可读，新事件无需 seat_id，投影不丢失或重复计费 |
| 模型正文审计、父子会话、标题更新与历史正文 | 记录真实本地身份，历史可查可解密，标题更新不扣模型额度 |
| 插件市场和工作台分发 | 复用本地会话鉴权，保留租户、安装策略和管理权限 |
| 旧桌面构建重新登录与标准路径 | 路径和协议版本匹配，同 origin 授权通过，无隐式 Gateway 转发 |
| 用户改名、组织调整、后台任务与长期运行 | 不再产生 profiles/upsert 或验席调用，没有 Gateway 失败重试积压 |
| Gateway 不部署时的 Web 页面 | 商业状态、旧 SSO 等可选入口不会阻断原生登录及 DSH |

后端重点更新 identity、access、Gateway client 退出、个人和部门策略、设备会话、operation worker、资料 outbox 退出、UsageEvent 和恢复测试；新增授权请求、refresh 事务及双数据库并发覆盖。原席位测试替换为无席位准入与无商业化断言，不直接删除相关安全回归。

前端覆盖导航、模型授权弹窗、额度来源和个人零额度，以及去除商业提示；运行 lint、typecheck、check-i18n。最终必须在无 Gateway 环境完成真实桌面端登录、模型请求和用量检查，mock 和静态检查不代替该验收。

## 实施状态（2026-10-20）

已在 `feat/bisheng-work-110` 落实本地授权、会话、Token、原生路由、去席位授权和管理界面；模型审计继续保留。客户端实际开发基线为远端 `origin/V1.1.0`（`5ee11bddf915a29af6d9252ead9b3f8343dba544`），新分支 `codex/dsh-without-gateway`，工作区位于 `bisheng-work/.worktrees/dsh-without-gateway`。

正式 [spec](../features/v3.0.0/110-dsh-local-access/spec.md)、[design](../features/v3.0.0/110-dsh-local-access/design.md)、[tasks](../features/v3.0.0/110-dsh-local-access/tasks.md) 已记录用户确认及实际实现。个人优先、多部门最大值、默认 access 300 秒/会话绝对 30 天、旧路径别名均已固定。真实环境发布、DM 并发与原生客户端联调仍须按 [发布说明](../features/v3.0.0/110-dsh-local-access/deployment.md) 验收。

## 独立仓库源码定位

Gateway 原实现位于 `/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/`，重点为 `service/DshAuthorizationService.java`、`DshTokenService.java`、`DshIntrospectionService.java`、`DshRateLimitService.java` 及 `repository/DshSessionRepository.java`。这些仅作为迁移语义和测试的参考，不作为目标运行组件。

桌面端位于 `/Users/zhangguoqing/works/bisheng-work`，重点为 `packages/dsh-desktop-enterprise/contract.js` 和 `src/main/enterprise/enterprise-service.ts`、`login-callback-server.ts`、`credential-broker.ts`。授权发行工具位于 `/Users/zhangguoqing/works/gen_license/gateway_license.py`，新版本退出 DSH 付费签发；旧部署如仍需发行授权，按版本独立维护。
