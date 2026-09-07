# Tasks: 开放 API 鉴权与身份传递（F053）

> 本任务清单以 [design.md](./design.md) 2026-09-04 最终版为唯一技术基准。旧 `tasks.md` 中与最终设计冲突的 P2、share-token、服务账号写入 `user`、独立调用日志表和旧日常会话方案均已删除。

**关联**: [design.md](./design.md) · [spec.md](./spec.md) · [release-contract.md](../release-contract.md) · [openapi-v2-key-auth-api.md](./openapi-v2-key-auth-api.md)
**版本**: v3.0.0-beta1
**工作流**: WS-A 底座与权限主体 · WS-B 管理界面 · WS-C 身份传递与审计 · WS-D 个人访问令牌 · WS-E 日常模式会话 · WS-F v3 免登录发布面

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ⚠️ 历史需求稿 | 其中仍有旧范围描述；执行时以用户确认的最终 `design.md` 为准，不得据此恢复已删除范围 |
| design.md | ✅ 最终设计 | 2026-09-04 用户确认作为最终技术方案 |
| tasks.md | ✅ 已按最终设计重排 | 2026-09-04；共 58 个任务 |
| 实现 | 🔲 未开始 | 0 / 58 |

---

## 1. 执行规则

### 1.1 每个任务固定执行六步

除纯文档或人工验证任务外，每个任务都按以下顺序执行，不允许先写完实现再补测试：

1. 阅读该任务的 `设计依据`、`文件`、`完成条件`，再用 `rg` 重新定位符号；文件路径漂移只允许重定位，不允许改变契约。
2. 先运行相关现有测试，记录基线；现有失败与本任务无关时不得顺手修改。
3. 先增加本任务列出的测试并确认新测试会失败；失败原因必须正好是待实现能力缺失。
4. 只实现本任务范围，直到新增测试和相关回归测试通过。
5. 运行 `scripts/arch-guard.sh`；涉及前端时再从 `src/frontend/` 运行对应应用的 lint、typecheck 和 `lint:prune`。
6. 执行 `/task-review features/v3.0.0-beta1/053-openapi-auth-and-identity <任务ID>`；通过后才勾选任务，并更新“实现”计数。

若实现需要推翻最终设计中的范围、数据结构、路由、鉴权通道或错误码，立即停止并请求用户重新确认；不得在代码或任务里自行发明兼容方案。

### 1.2 永久禁止项

任何任务都不得引入以下内容；每个 Wave 结束都要重新搜索一次：

- 不增加 `user.user_type`，不为服务账号创建 `user` 或 `user_tenant` 行，不用假的 `UserPayload` 代替服务账号授权主体。
- 不新增 `open_api_call_log` 或任何逐调用专用表；逐调用数据只写现有 `audit_log.audit_metadata`（数据库列名 `metadata`）。
- 不实现 IP 白名单、限流、日配额、幂等键，不增加相应字段、Redis key、错误码、请求头或响应头。
- 不修改 `share_link` 表、模型、接口、前端分享参数，不实现 share-token 新通道。
- 不接受 `X-Bisheng-On-Behalf-Of`、`X-Bisheng-End-User` 等旧品牌头；只接受 `X-On-Behalf-Of`、`X-End-User`。
- v2 不回落 `default_operator`，不允许 JWT/cookie 代替 API Key；v3 不校验 API Key 或 JWT。
- v2/v3 API 层不得互相 import，也不得 import v1 API endpoint；只能调用共享 domain service，禁止内部 HTTP 转调。
- 日常模式对外模型不含 `use_knowledge_base`、`task_mode`，但必须保留 `files`；内部固定 `task_mode=False`、`use_knowledge_base=None`。

建议的范围扫描：

```bash
rg -n "user_type|open_api_call_log|share_scope|share_token|Idempotency-Key|ip_allowlist|rate_limit_rpm|quota_daily_calls" \
  src/backend/bisheng/open_api src/backend/bisheng/public_endpoints src/frontend/platform/src src/frontend/client/src
rg -n "X-Bisheng-On-Behalf-Of|X-Bisheng-End-User" src/backend src/frontend
```

扫描命中既有无关代码时只记录；命中新增加的 F053 代码必须删除。

### 1.3 Wave 门禁

- 同一工作流内按编号执行；只有 `依赖` 全部完成的任务才能开始。
- WS-A 与 WS-C 必须同版交付，不能单独发布中间状态。
- v3 后端九个发布接口必须先上线并验证，之后才能切 client、platform 和商业网关。
- 每个 Wave 的集成任务是进入下一 Wave 的门禁；门禁未通过时不得继续堆叠功能。
- MySQL、Redis、OpenFGA 集成测试在 CI 环境执行；DM8 在 105 环境执行。本地缺少中间件不是删除测试或放宽断言的理由。

---

## 2. Wave 0：现状冻结与移植边界

- [ ] **P00：建立实现前基线和目标清单**
  **设计依据**: design §1.2、§2.1、§6.2、§7
  **文件**: 不修改业务代码；输出记录放当前任务 PR 描述
  **执行顺序**:
  1. 从实际 `app.routes` 导出当前 `/api/v2` 的 `(protocol, method, path, endpoint)`，单独列出 HTTP 与 WebSocket。
  2. 标记要从 v2 删除的六个旧 chat HTTP 路由：`history`、`gen_title`、`liked`、`solved`、`comment`、`sync/messages`。
  3. 标记 design §5.E 要新增的五个 v2 路由和 §5.F 要新增的九个 v3 路由。
  4. 用 `git show` 检查参考提交 `a15f06135`、`86e52f90b`、`43e73bfc5`、`c5989ffd6`、`e31c35732`，形成“可复用符号 / 必须重写符号”清单；禁止整体 cherry-pick。
  5. 记录 `user`、`user_tenant`、`share_link`、`audit_log`、`message_session` 当前列，作为迁移后的反向核对基线。
  **完成条件**: 路由、表结构和参考移植清单齐全；确认工作区没有未知的同名迁移或半成品 `open_api/` 目录
  **依赖**: 无

---

## 3. Wave 1：WS-A 凭据底座与独立服务账号

- [ ] **A01：测试基础设施、两张核心表和 ORM 模型**
  **设计依据**: design §5.A2、§6.4、§7.1
  **文件**: `src/backend/test/open_api/conftest.py`、`test/open_api/test_database_contract.py`；`bisheng/core/database/alembic/versions/v3_0_0b1_f053_api_credential_tables.py`；`bisheng/open_api/domain/models/{api_credential,service_account}.py`
  **执行顺序**:
  1. 先写迁移契约测试：仅创建 `api_credential`、`service_account`，明确断言 `user`、`user_tenant` 没有新增列或服务账号外键。
  2. 建立 open_api 测试 fixture；允许参考 vibe fixture，但删除 `user_type` 与影子用户假设。
  3. 实现两张表、唯一键、租户索引和时间字段；`scopes` 使用 `JsonType`，字符串使用 `VARCHAR`。
  4. `service_account` 包含 `resource_owner_user_id`，但不继承、不关联 `User`。
  5. 验证空库和已有 beta1 库的 upgrade/downgrade；downgrade 只回滚本 revision 创建的对象。
  **测试**: 两种数据库方言的 DDL 编译；`subject_kind` 只允许 `service_account|natural_person`；同租户名称/密钥 hash 唯一性
  **完成条件**: 迁移契约测试通过；创建服务账号模型不会产生任何 User/UserTenant 数据
  **依赖**: P00

- [ ] **A02：错误码、配置、scope 注册表和 Principal 契约**
  **设计依据**: design §3.2、§3.4、§6.1、§6.3、§6.4
  **文件**: `src/backend/bisheng/common/errcode/open_api.py`、`core/config/open_platform.py`、`open_api/domain/{scopes,context}.py`、`docs/constitution.md`、三语 `api_errors` 源文件；测试 `test/open_api/test_scopes.py`、`test_open_api_context.py`
  **执行顺序**:
  1. 先写 260 段错误码、scope 标记和不可变 Principal/Snapshot 序列化测试。
  2. 只登记 design §6.3 本期错误码；预留码和 P2 错误码不实现。
  3. 实现 `@open_api_scope(scope, modes, session)`；不保留 `allow_share_token`、`idempotent` 参数。
  4. 实现 `OpenApiPrincipal` 与 `OpenApiExecutionSnapshot`；Snapshot 不含明文密钥，`channel` 只允许 `open_api_v2|public_v3`。
  5. 增加 design §6.4 的 Settings，默认关闭 PAT；不增加 P2 配置。
  6. 更新三语错误文案源并运行生成脚本，不手改生成物。
  **完成条件**: Principal 字段与 design §6.1 完全一致；配置和 scope 注册表中没有永久禁止项
  **依赖**: A01

- [ ] **A03：凭据签发、哈希校验、缓存和失效服务**
  **设计依据**: design §3.2、§5.A1、§6.4
  **文件**: `src/backend/bisheng/open_api/domain/services/{credential_service,credential_validator}.py`；测试 `test/open_api/test_credential_service.py`、`test_credential_validator.py`
  **执行顺序**:
  1. 先覆盖明文仅返回一次、SHA-256 存储、恒时比较、撤销、过期、最后使用时间节流和缓存失效测试。
  2. 实现 `bs-sak-` 与 `bs-pat-` 前缀；前缀与数据库 `subject_kind` 不匹配返回 `26002`。
  3. 认证异常、Redis 异常、数据库异常一律 fail-closed；依赖不可用返回 `26030`。
  4. 缓存 key 只使用 design §6.4 列出的 key；缓存载荷不含明文密钥。
  5. 先只注册服务账号 resolver；自然人 resolver 留给 D02。
  **完成条件**: 不同主体 id 数值碰撞时缓存不串；撤销、过期、停用能在设计时限内生效
  **依赖**: A02

- [ ] **A04：独立服务账号 Domain Service**
  **设计依据**: design §3.3、§5.A2
  **文件**: `src/backend/bisheng/open_api/domain/services/service_account_service.py`、相关 schema；测试 `test/open_api/test_service_account_service.py`
  **执行顺序**:
  1. 先写创建、更新、停用、启用、软删除、同租户归属人校验、跨租户拒绝测试。
  2. 创建服务账号只插入 `service_account`；测试前后 `user`、`user_tenant` 行数不变。
  3. `resource_owner_user_id` 必须指向同租户有效自然人；服务账号不能成为资源 owner、管理员或登录用户。
  4. 停用/删除服务账号后撤销或使其全部凭据失效，并主动清缓存。
  5. 管理操作写现有审计 action：`open_api.service_account.*`、`open_api.api_key.*`。
  **完成条件**: 不存在构造服务账号 `UserPayload`、同步组织或登录守卫的代码
  **依赖**: A01、A03

- [ ] **A05：PermissionActor 扩为通用授权主体**
  **设计依据**: design §3.3、§5.A3、§6.1；constitution C4
  **文件**: `src/backend/bisheng/permission/application/identity.py`、`permission/domain/services/permission_action_service.py` 及所有构造点；测试 `test/permission/test_f048_*actor*.py`、`test/open_api/test_permission_actor.py`
  **执行顺序**:
  1. 先参数化现有 user actor 回归测试，再增加 service_account actor 测试。
  2. 将 actor 表达改为 `subject_type + subject_id + tenant_id + admin facts`；保留现有用户行为。
  3. service_account actor 固定无超级管理员、无租户管理员事实。
  4. 增加 `current_permission_actor` ContextVar 和 token/reset 生命周期工具；v1 未设置时仍从登录用户解析。
  5. 批量修改调用点后运行全部 permission 测试，证明 user actor 零行为变化。
  **完成条件**: 任何权限检查都可区分相同数值的 `user:7` 与 `service_account:7`
  **依赖**: A02

- [ ] **A06：OpenFGA 模型、授权投影和显示名支持 service_account**
  **设计依据**: design §5.A3、§7.2；constitution C4
  **文件**: `src/backend/bisheng/core/openfga/authorization_model_f048.py`、`permission/application/{resource_api,initial_grant}.py`、grant subject/source 相关 service；测试 `test/permission/test_f048_schema_contract.py`、授权投影/反查/显示名测试
  **执行顺序**:
  1. 先增加 schema contract：registry 中所有允许直接授权的资源关系都允许 `service_account`，owner/admin 关系一律不允许。
  2. 增加 OpenFGA `service_account` type，只做向后兼容添加，不改已有 user/department/group tuple。
  3. 扩展 canonical source、显示名、grant mutation 和反向查询。
  4. 通用用户/部门/用户组选择 API 仍不返回服务账号；服务账号授权只能从主体详情入口发起。
  5. 增加 id 碰撞和“SA 无管理员捷径”反向测试。
  **完成条件**: direct grant/revoke/check/list 全链路支持 `service_account:{id}`，旧主体回归通过
  **依赖**: A05

- [ ] **A07：v2 唯一鉴权依赖和异常处理**
  **设计依据**: design §3.1、§3.2、§5.A4
  **文件**: `src/backend/bisheng/open_api/api/{dependencies,exception_handlers}.py`、`open_api/domain/services/identity_service.py` 的接口占位、`src/backend/bisheng/main.py`；测试 `test/open_api/test_dependencies.py`、`test_http_status.py`
  **执行顺序**:
  1. 先写无头、JWT、错误前缀、撤销、过期、租户停用、缺 scope、未标记端点和依赖故障测试。
  2. 实现固定管线前半段：提取凭据 → 校验主体 → 设置 tenant ContextVar → PAT 开关槽位 → scope/mode 标记 → permission actor。
  3. 同时写 `current_open_api_principal`、`conn.scope['open_api_principal']`、`current_permission_actor`；在 finally 中 reset。
  4. v2 错误必须返回真实 400/401/403/500/503，不被全局 handler 压成 200。
  5. 缺标记 fail-closed 为 `26031`，禁止默认 scope 或默认操作员兜底。
  **完成条件**: 已登录但无 API Key 的 v2 请求仍 401；有 SAK 无 JWT 可通过认证阶段
  **依赖**: A03、A05、A06

- [ ] **A08：服务账号管理 API、密钥 API 和 whoami（M1 门禁）**
  **设计依据**: design §4 M1、§5.A2、§5.A4、§6.2
  **文件**: `src/backend/bisheng/open_api/api/{router,dependencies,exception_handlers}.py`、`api/endpoints/{service_account,service_account_keys,auth}.py`、`src/backend/bisheng/api/router.py`；测试 `test/open_api/test_service_account_api.py`、`test_service_account_keys_api.py`、`test_open_api_auth_api.py`
  **执行顺序**:
  1. 先写 v1 管理端点的登录/租户管理员门禁、跨租户、明文一次性返回和 whoami 测试。
  2. 挂载 `/api/v1/service-accounts/**` 管理面和 `GET /api/v2/auth/whoami`。
  3. 管理 API 使用现有 v1 信封；whoami 使用 v2 真 HTTP 状态且显式 `scope=None`。
  4. 签发/编辑模型只含基本信息、权限位和委托配置入口；不得出现网络/P2/share 字段。
  5. whoami 返回密钥主体、资源归属人、租户、权限位、掩码和有效期，不返回明文密钥。
  6. 完成 A06 的 F048 模型契约验证后才允许启用服务账号密钥签发；目标环境尚未部署兼容模型时保持签发入口关闭。
  **完成条件**: M1 通过：JWT 只能访问管理面，不能访问 whoami；SAK 无 JWT 可看到独立服务账号主体；数据库没有对应 User/UserTenant 行
  **依赖**: A04、A06、A07

---

## 4. Wave 2：WS-A 资源归属、存量 v2 接入与异步身份

- [ ] **A09：资源归属人与创建回授**
  **设计依据**: design §3.3、§5.A5
  **文件**: `permission/application/initial_grant.py`、知识库/知识空间/文件的创建 service/adapter；测试 `test/open_api/test_service_account_resource_ownership.py`、相关 F048 创建授权测试
  **执行顺序**:
  1. 先写四组测试：SA-S 创建、SA-D 创建、PAT 创建、INHERIT 子资源创建。
  2. SA-S 业务 creator/owner 写 `resource_owner_user_id`，授权主体仍是 SA，并追加可撤销创建回授。
  3. 模式 D 和 PAT 的 owner 写自然人；模式 D 不回授 SA。
  4. INHERIT 文件/文件夹只继承父资源，不重复写本地回授。
  5. 增加反向测试：资源归属人有权、SA 无权时仍拒绝 SA。
  **完成条件**: 业务归属人与授权主体在代码参数和测试断言中始终分开
  **依赖**: A04、A06

- [ ] **A10：存量 v2 HTTP 路由接入 scope、权限和业务适配器**
  **设计依据**: design §5.A4、§6.2、§9
  **文件**: `src/backend/bisheng/open_endpoints/api/router.py`、`api/endpoints/{knowledge,filelib,citation,llm,flow,assistant,workflow}.py`、`domain/utils.py`；测试 `test/open_api/test_route_completeness.py`、`test_endpoint_auth_matrix.py`
  **执行顺序**:
  1. 先从实际 `app.routes` 生成路由集合测试，不把数量写死为主要断言。
  2. `router_rpc` 全局挂 `verify_open_api_access`；每个 HTTP/WS endpoint 都有 `@open_api_scope`。
  3. `download_statistic`、ASR、TTS 只允许 S；其余业务端点允许 S/D。
  4. 删除 v2 六个旧 chat HTTP 路由；发布需要的 history/gen_title 只在后续 v3 注册。
  5. 所有业务资源操作经 `require_business_action`；v2 endpoint 不直接查 OpenFGA/RBAC。
  6. 移除 v2 的 `get_default_operator*` 回落；需要遗留 `UserPayload` 的业务 service 只可使用资源归属人兼容 payload，权限仍读取 PermissionActor。
  **完成条件**: v2 无 key 全拒绝；六个旧 chat 路由真 404；登录态不能替代 key
  **依赖**: A07、A09

- [ ] **A11：v2 两个 WebSocket 的密钥鉴权和生命周期复查**
  **设计依据**: design §3.2、§5.A4、§9
  **文件**: `open_api/api/dependencies.py`、`open_endpoints/api/endpoints/{workflow,assistant}.py`；测试 `test/open_api/test_websocket_auth.py`
  **执行顺序**:
  1. 先写握手无 key、query key、JWT、有效 header key、撤销/过期/停用后的连接测试。
  2. 只从 `Authorization` header 读取 key，不接受 query 参数密钥。
  3. 握手失败使用 1008；已连接后每 3 秒复查，状态变化后 5 秒内关闭。
  4. 每个连接建立和退出都正确设置/reset tenant、principal、permission actor ContextVar。
  **完成条件**: 两个 WS 与 HTTP 使用同一凭据校验器，且没有 share-token 分支
  **依赖**: A10

- [ ] **A12：工作流 Celery 执行快照**
  **设计依据**: design §3.3、§5.A6、§6.1
  **文件**: `open_endpoints/api/endpoints/workflow.py`、`worker/workflow/tasks.py`、工作流执行入口与 callback；测试 `test/open_api/test_execution_snapshot.py`、worker ContextVar 回归测试
  **执行顺序**:
  1. 先写 SA-S、SA-D、PAT、public_v3 四类快照往返测试和队列载荷无明文 key 测试。
  2. v2 入队前完成凭据和资源准入，把 Snapshot 作为显式任务参数，不能只传资源归属人的 `user_id`。
  3. worker 按 `channel` 恢复 tenant、permission actor 和业务归属人；执行实际动作前再次授权。
  4. worker 在 finally 中 reset；串行处理两个 tenant 的测试不得串上下文。
  5. public_v3 快照不能进入 open_api_v2 分支，反之亦然。
  **完成条件**: 跨进程前后 authorization subject、tenant、owner、mode 不变
  **依赖**: A07、A10

- [ ] **A13：WS-A 综合回归门禁**
  **设计依据**: design §4 关键路径、§9
  **文件**: `src/backend/test/open_api/test_m1_integration.py`
  **执行顺序**:
  1. 运行 A01～A12 的全部测试和 permission 相关回归。
  2. 复核 A08 的 M1：创建 SA 后 User/UserTenant 行数不变；`whoami` 返回独立 SA 主体而不是归属人身份。
  3. 验证同 id 的 user 与 SA 不串授权、缓存、审计主体键。
  4. 运行 Wave 范围扫描，确认无禁止项。
  **完成条件**: WS-A 全绿；仅允许在集成分支继续进入 WS-C，不允许单独发布
  **依赖**: A01～A12

---

## 5. Wave 3：WS-C 身份传递、会话隔离、检索过滤与审计

- [ ] **C01：新身份头解析与错误码**
  **设计依据**: design §5.C1、§6.2、§6.3
  **文件**: `common/errcode/open_api.py`、`open_api/domain/services/identity_service.py`、三语错误文案；测试 `test/open_api/test_identity_headers.py`
  **执行顺序**:
  1. 先写新头、两个头冲突、非法 OBO、超长/不可打印 End-User、旧品牌头测试。
  2. 只读取 `X-On-Behalf-Of` 和 `X-End-User`；两个头同时出现返回 `26010`。
  3. OBO 只接受正整数用户 ID；End-User 最长 128 字节且只允许可打印 ASCII。
  4. 任何旧品牌头即使单独出现也返回 400 `26019`，不作为别名。
  5. 无会话语义的端点可记录合法 End-User，但不改变授权主体。
  **完成条件**: 错误响应只提示新头名称，源码没有旧品牌常量
  **依赖**: A02、A07

- [ ] **C02：委托范围表和 message_session 来源字段迁移**
  **设计依据**: design §5.C2、§5.C6、§6.4、§7.1
  **文件**: `core/database/alembic/versions/v3_0_0b1_f053_delegate_scope_and_session_subject.py`、`open_api/domain/models/credential_delegate_scope.py`、`database/models/session.py`；测试 `test/open_api/test_delegate_session_migration.py`
  **执行顺序**:
  1. 先写 DDL 契约测试。
  2. 创建 `api_credential_delegate_scope`，唯一键覆盖 credential/type/id，带 tenant_id。
  3. `message_session` 只增加 `api_subject_type`、`api_subject_id`、`external_user_id` 和设计指定索引。
  4. 不给 `chat_message` 增列，不增加 share 字段，不创建调用日志表。
  5. upgrade/downgrade 验证 MySQL/DM8 兼容。
  **完成条件**: 迁移后与 design §6.4 字段逐项一致，没有额外 DDL
  **依赖**: A01

- [ ] **C03：委托范围服务和密钥管理契约**
  **设计依据**: design §5.C2、§5.B2
  **文件**: `open_api/domain/services/delegate_scope_service.py`、`open_api/api/endpoints/service_account_keys.py`、credential schema；测试 `test/open_api/test_delegate_scope.py`
  **执行顺序**:
  1. 先写 user/department 范围、跨租户、目标失效、空范围、移除 delegate 清空范围测试。
  2. user 范围只校验 User 存在、`delete=0`、同租户活跃，不读取 `user_type`。
  3. department 在调用期按物化路径展开；保存时校验部门属于同租户。
  4. 有 `delegate` scope 时范围不能为空；去掉 scope 时同事务清空范围。
  5. PAT 不允许 delegate；三项未部署扩展位不展示也不签发。
  **完成条件**: 不存在“有范围但没有 delegate”或“有 delegate 但范围为空”的持久化状态
  **依赖**: A08、C01、C02

- [ ] **C04：五道委托准入和模式 D 主体替换**
  **设计依据**: design §3.2、§5.C3、§6.1
  **文件**: `open_api/domain/services/identity_service.py`、`open_api/api/dependencies.py`、permission actor resolver；测试 `test/open_api/test_identity_modes.py`
  **执行顺序**:
  1. 先对五道检查逐条写失败测试。
  2. 严格按序校验：有 delegate → 目标有效同租户 → 非特权主体 → 命中范围 → endpoint 允许 D。
  3. 前四道错误分别为 `26004/26005/26007/26004`；只有最后“端点不允许 D”返回 `26006`。
  4. 全部通过后把授权主体、有效用户和业务归属人都替换为目标用户；SA 自身授权不参与。
  5. PAT 携带 OBO 在第一道检查之前拒绝；持 delegate 的 SAK 漏传 OBO 返回 `26016`。
  6. 把解析结果同时写 Principal 和 PermissionActor，HTTP/WS 共用同一函数。
  **完成条件**: 模式 D 反向测试证明“SA 有权但目标用户无权”仍拒绝，“目标有权但 SA 无权”可通过
  **依赖**: A07、C03

- [ ] **C05：裸 user_id、默认操作员和旧 chat 路由彻底收口**
  **设计依据**: design §5.C4、§5.A4、§2 K23
  **文件**: `open_endpoints/api/endpoints/{filelib,assistant}.py`、`open_endpoints/domain/{schemas,utils}.py`；测试 `test/open_api/test_removed_inputs.py`
  **执行顺序**:
  1. 先枚举所有 v2 body/query 中的 `user_id`，对每个入口写 400 `26019` 测试。
  2. 从对外 Pydantic schema 和 endpoint 参数移除 `user_id`；`extra='forbid'`，不能静默忽略。
  3. 删除 v2 使用的 `resolve_operator` 和 `get_default_operator*`；静态测试禁止 v2 endpoint import。
  4. 再次断言六个旧 chat 路由未注册。
  **完成条件**: 只能通过 `X-On-Behalf-Of` 表达委托，任何裸参数或旧头都明确拒绝
  **依赖**: C04

- [ ] **C06：会话来源、列表/详情和附件隔离规则**
  **设计依据**: design §3.3、§5.C6
  **文件**: `database/models/session.py`、`chat_session/domain/chat.py`、会话创建/续聊 adapter；测试 `test/open_api/test_session_subject_isolation.py`
  **执行顺序**:
  1. 先按 SA-S（有/无 End-User）、SA-D、PAT、public_v3 建立归属矩阵测试。
  2. SA-S 的兼容 `user_id` 写资源归属人，同时写 `api_subject_type='service_account'` 和 SA id；End-User 写 `external_user_id`。
  3. v1 会话列表排除 SA 来源；v2 会话列表按 tenant + API subject + external user 读取。
  4. 模式 D/PAT 使用自然人 user_id，可继续在 v1 工作台看到。
  5. list、info、续聊、stop、附件引用使用同一 subject matcher；不存在/跨主体/跨租户统一 404。
  6. SA-S 未传 End-User 时按 SA 粒度隔离并记录 WARN，不拒绝请求。
  **完成条件**: 资源归属人无法从 v1 列表读取 SA-S 会话，另一个 SA 或 End-User 也无法越界
  **依赖**: A09、C02、C04

- [ ] **C07：retrieve 两条召回分支的文件级过滤**
  **设计依据**: design §5.C4、§6.5
  **文件**: `knowledge/domain/services/{knowledge_space_chat_service,knowledge_file_visibility_service}.py`、v2 retrieve adapter；测试 `test/knowledge/test_openapi_retrieve_file_visibility.py`
  **执行顺序**:
  1. 先写允许文件、禁止文件、跨租户、过滤服务异常四类反向测试。
  2. 两条召回分支都执行 prefilter 和 post-filter，使用当前 PermissionActor/effective user。
  3. 模式 D 只看到目标用户可见文件；模式 S 使用 SA 的资源授权，不用资源归属人权限兜底。
  4. 过滤服务异常返回 503，响应中不得出现任何 chunk、文件名或正文。
  **完成条件**: 禁止文件在向量查询条件和最终结果中都不存在
  **依赖**: C04、C05

- [ ] **C08：复用 audit_log 的逐调用审计**
  **设计依据**: design §5.C5、§6.4；constitution C2/C3/C6
  **文件**: `open_api/domain/services/call_audit_service.py`、`open_api/api/middleware.py`、`main.py`、现有 `database/models/audit_log.py`；测试 `test/open_api/test_call_audit.py`
  **执行顺序**:
  1. 先写成功、401/403、异常、HTTP、WS 建连/断连、队列满、批量写失败测试。
  2. 中间件只包 v2 密钥面，从 `conn.scope['open_api_principal']` 读取依赖结果。
  3. 使用有界内存队列和 lifespan flusher，调用现有 `AuditLogDao.ainsert_audit_logs`；不增加审计 DDL或清理 Beat。
  4. 公共列按 design §5.C5 映射；调用详情写 `audit_metadata`，action 固定 `open_api.call`。
  5. 不写 Authorization、原始请求体、文件内容或其它请求头；SA 的 operator_id=0，PAT 写持有人 id。
  6. 队列满或落库失败只记 `open_api.audit.write_failed`，不改变业务响应；退出前尽力 flush。
  7. `open_api.call` 不加入旧系统操作页面 action 白名单。
  **完成条件**: MySQL/DM8 都能批量写 JSON metadata；仓库不存在 `open_api_call_log`
  **依赖**: C04

- [ ] **C09：WS-A + WS-C 集成门禁 M2**
  **设计依据**: design §4 M2、§9
  **文件**: `test/open_api/test_identity_e2e.py`、`test_open_api_route_matrix.py`
  **执行顺序**:
  1. 跑 A/C 全部测试、permission 回归、路由完整性和 arch-guard。
  2. 覆盖五道准入、新头、旧头、裸参数、S/D 会话矩阵、文件过滤 fail-closed、审计双归属。
  3. 覆盖 v2 HTTP/WS 均不接受 JWT 回落，且撤销/停用在设计时限内生效。
  4. 运行永久禁止项扫描。
  **完成条件**: M2 全绿；A 与 C 作为一个发布单元，才允许进入后续集成
  **依赖**: A13、C01～C08

---

## 6. Wave 4：WS-F 工作流/知识助手 v3 免登录发布面

- [ ] **F01：抽取工作流、知识助手和发布会话共享 Domain Service**
  **设计依据**: design §3.4、§5.F4；constitution C1
  **文件**: `workflow`、`assistant`、`chat_session` 对应 domain service；现有 v1/v2 endpoints 只保留 adapter；测试各模块 service 单元测试和 v2 回归
  **执行顺序**:
  1. 先录制当前工作流/助手 HTTP 与 WS 的关键响应、事件顺序和副作用回归。
  2. 把 invoke、stop、详情、assistant completion、history、gen_title 的业务编排下沉到所属 domain service。
  3. API 层不互相 import；v2/v3 只做各自鉴权、schema 适配和响应渲染。
  4. 保持 v2 密钥版行为不变，为 v3 adapter 提供相同业务入口。
  **完成条件**: arch-guard RULE-5 通过；共享逻辑没有内部 HTTP 调用
  **依赖**: A10、A12

- [ ] **F02：public_endpoints 模块和 guest policy**
  **设计依据**: design §3.1、§5.F1、§5.F2
  **文件**: `src/backend/bisheng/public_endpoints/api/{router,dependencies,exception_handlers}.py`、domain context/service；测试 `test/public_endpoints/test_guest_policy.py`
  **执行顺序**:
  1. 先写 guest 开关关、默认操作员不存在/停用、资源未发布、跨租户和身份头拒绝测试。
  2. 建立物理独立的 `/api/v3` router，不挂 v2 API Key 依赖，不读取 JWT。
  3. 受控按资源 ID 定位租户后立即设置 tenant ContextVar，再校验发布状态并进入业务 service。
  4. 只允许本模块使用 `default_operator.enable_guest_access`；收到任一身份传递头均拒绝。
  5. 生命周期结束 reset tenant/public principal ContextVar。
  **完成条件**: v3 无 JWT/key 可访问已发布资源；v2 同能力仍要求 key
  **依赖**: F01

- [ ] **F03：注册 v3 七个 HTTP allowlist 路由**
  **设计依据**: design §5.F1
  **文件**: `public_endpoints/api/endpoints/{workflow,assistant,flow,chat}.py`、router；测试 `test/public_endpoints/test_http_allowlist.py`
  **执行顺序**:
  1. 先对 design §5.F1 七个 HTTP method+path 写精确集合测试。
  2. 注册 workflow invoke/stop、assistant chat completions/info、flow detail、chat history/gen_title。
  3. 不注册 assistant/list、知识库、日常会话或管理接口；额外 `/api/v3/**` 必须 404。
  4. 所有端点调用 F01 的共享 service，并经过 F02 guest policy。
  **完成条件**: HTTP 路由集合与 design §5.F1 完全一致
  **依赖**: F02

- [ ] **F04：注册 v3 两个 WebSocket allowlist 路由**
  **设计依据**: design §5.F1、§5.F2
  **文件**: `public_endpoints/api/endpoints/{workflow,assistant}.py`；测试 `test/public_endpoints/test_websocket_allowlist.py`
  **执行顺序**:
  1. 先写工作流和知识助手 WS 的 guest policy、未发布、身份头、跨资源测试。
  2. 注册 `/api/v3/workflow/chat/{workflow_id}` 和 `/api/v3/assistant/chat/{assistant_id}`。
  3. 不要求 JWT/API Key，不接受 query key/share-token，不允许身份传递头。
  4. 使用明确 `channel='public_v3'` 快照进入异步执行，finally reset ContextVar。
  **完成条件**: 两个 v3 WS 可匿名连接已发布资源，两个 v2 WS 仍只能用 API Key
  **依赖**: A11、F02

- [ ] **F05：public_v3 会话绑定与越权防护**
  **设计依据**: design §5.F3、§8 坑 11
  **文件**: `chat_session/domain/chat.py`、workflow/assistant shared service；测试 `test/public_endpoints/test_public_session_ownership.py`
  **执行顺序**:
  1. 先写 history、gen_title、stop、续聊跨资源/跨来源/跨 tenant 的 404 测试。
  2. v3 创建会话写 `api_subject_type='public_v3'`，用现有 flow/resource 字段绑定目标资源，并记录默认操作员兼容 user_id。
  3. 后续操作同时校验 public_v3 来源、资源 id、租户和会话 id，不能只靠 chat_id。
  4. v1/v2 会话不得被 v3 history/title/stop 读取或修改。
  **完成条件**: 猜中其它会话 chat_id 也只能得到统一 404
  **依赖**: C06、F03、F04

- [ ] **F06：client guest 页面完整切换到 v3**
  **设计依据**: design §5.F4、§8 坑 12；前端规范
  **文件**: `src/frontend/client/src/pages/standaloneChat/**`、`pages/appChat/useChatHelpers.ts`、`api/chat/api-endpoints.ts`、三语 locale；测试现有 `StandaloneChatPage.test.ts` 和 API URL 单元测试
  **执行顺序**:
  1. 开始前完整阅读 `src/frontend/packages/ui/docs/index.md` 和本任务涉及组件规范；不改视觉样式。
  2. 先写 guest 调用图测试，覆盖详情、history、gen_title、invoke/stop 和两个 WS。
  3. `apiVersion` 类型扩为 `v1|v2|v3`，guest 固定使用 v3；普通登录/分享链路保持原样。
  4. 删除 guest 分支中的 v2 URL，不增加 share_token 参数或身份头。
  5. 运行 client lint、typecheck、相关测试和 `lint:prune`。
  **完成条件**: 浏览器 Network 中 guest 工作流/助手请求全部为 v3，且无 `/api/v2` 遗留
  **依赖**: F05

- [ ] **F07：platform 发布示例和商业网关切换**
  **设计依据**: design §5.B4、§5.F4、§8 坑 13
  **文件**: `src/frontend/platform/src/components/bs-comp/apiComponent/{ApiAccess,ApiAccessFlow}.tsx`、三语 locale；商业网关对应 route/filter 配置
  **执行顺序**:
  1. 开始前阅读 UI 规范；先写/更新 URL 生成测试。
  2. “无需密钥发布”示例改为 v3；“密钥开放 API”示例继续使用 v2 并携带 Bearer Key。
  3. 不改 `ChatLink` 的分享链接参数和现有 share_link 行为。
  4. 商业网关增加 v3 HTTP 与 WS 代理/拦截规则并验证升级顺序；不得把 v3 送入登录或 API Key 网关。
  5. 若商业网关源码不在本仓，必须在 PR 阻断项中给出对应仓库、负责人、完整路径清单和验证结果；未完成不能宣告 F07 完成。
  **完成条件**: platform 示例语义不混淆，商业版 v3 HTTP/WS 可达
  **依赖**: F03、F04

- [ ] **F08：WS-F 集成门禁 M3**
  **设计依据**: design §4 M3、§9、§10
  **文件**: `test/public_endpoints/test_public_v3_e2e.py`、client/platform 测试
  **执行顺序**:
  1. 精确断言 v3 只有七个 HTTP + 两个 WS allowlist；`/api/v3/assistant/list` 真 404。
  2. 验证开关、发布状态、租户恢复、会话越权和身份头拒绝。
  3. 验证 v2 同路径仍为密钥版，v1/分享链路回归不变。
  4. 验证 client/platform/gateway 全部切换后再允许移除旧 v2 匿名语义。
  **完成条件**: 按“v3 后端先发布 → 调用方后切”完成演练，无发布页中断
  **依赖**: F01～F07、C09

---

## 7. Wave 5A：WS-D 个人访问令牌

- [ ] **D01：PAT 配置、租户设置表和缓存**
  **设计依据**: design §5.D3、§6.4、§7.1
  **文件**: `core/database/alembic/versions/v3_0_0b1_f053_pat_tenant_setting.py`、`open_api/domain/models/open_api_tenant_setting.py`、`core/config/open_platform.py`、`api/v1/endpoints.py`；测试 `test/open_api/test_pat_tenant_setting.py`
  **执行顺序**:
  1. 先写部署级/租户级默认关闭、TTL、缓存失效和迁移测试。
  2. 创建 `open_api_tenant_setting(tenant_id PK, pat_enabled, pat_ttl_days, update_time)`。
  3. 实现部署级 `open_api.pat_enabled` 与租户级开关；任一关闭都不撤销数据库令牌。
  4. 设置缓存 key 仅使用 `oapi:tenant:{tid}:pat`，写时失效。
  5. `GET /env` 只透传前端所需开关，不透出内部密钥配置。
  **完成条件**: 关闭后 5 秒内校验拒绝，重新开启后未过期令牌恢复
  **依赖**: A01、A02

- [ ] **D02：natural_person 凭据 resolver**
  **设计依据**: design §2 K17、§5.D1
  **文件**: `open_api/domain/services/credential_validator.py`、permission user actor resolver；测试 `test/open_api/test_natural_person_resolver.py`
  **执行顺序**:
  1. 先写用户不存在、delete=1、租户关系不活跃、租户不匹配、超管跨租户测试。
  2. `subject_id` 直接解析 User；不读取或增加 `user_type`。
  3. 加载角色和管理员事实，但 visible tenant 始终限制在凭据 tenant。
  4. PAT 开关在 scope 检查前执行；关闭返回 `26040`。
  5. PAT 携 OBO 明确拒绝，不进入委托五道检查。
  **完成条件**: 超管 PAT 也不能读取其它租户资源，失效持有人返回 `26043`
  **依赖**: A03、A05、D01

- [ ] **D03：一人一把、TTL、白名单和 PAT 审计服务**
  **设计依据**: design §5.D2、§5.D3
  **文件**: `open_api/domain/services/personal_token_service.py`；测试 `test/open_api/test_personal_token_service.py`
  **执行顺序**:
  1. 先写首次签发、重签撤销旧 token、手动删除、管理员 TTL 收紧和 scope 拒绝测试。
  2. PAT 固定 `knowledge:read`，不允许 delegate 或其它 scope。
  3. 一人同租户只保留一把未撤销 PAT；重签和删除都记录明确的撤销原因，不自行扩展新的对外字段或错误码。
  4. 管理员有效期取租户 TTL 与部署 `pat_admin_ttl_days` 的较小值，并返回风险提示标记。
  5. 管理操作写现有 `audit_log` action `open_api.pat.*`，不写明文 token。
  **完成条件**: 明文只在签发响应出现一次，查询只能得到掩码
  **依赖**: D02

- [ ] **D04：员工自助和管理员 PAT API**
  **设计依据**: design §5.D4、§6.2
  **文件**: `open_api/api/endpoints/{personal_token_self,personal_token_admin}.py`、router、admin scope；测试 `test/open_api/test_personal_token_self_api.py`、`test_personal_token_admin_api.py`
  **执行顺序**:
  1. 先写员工只能操作自己、管理员台账租户隔离、明文不可查询、按 token/按人吊销测试。
  2. 员工面 `/api/v1/me/api-token/**` 走 JWT；管理员面 `/api/v1/personal-tokens/**` 走租户管理员门禁。
  3. 管理员台账只返回掩码、状态、持有人、有效期、最后使用和风险标记。
  4. settings 更新遵守部署级开关，不能用租户设置绕开部署关闭。
  **完成条件**: v1 管理信封与 v2 真 HTTP 状态不混用
  **依赖**: D03、A08

- [ ] **D05：用户状态变化的级联失效**
  **设计依据**: design §5.D2
  **文件**: 用户禁用/删除入口、`tenant/domain/services/user_tenant_sync_service.py`、credential cache invalidation；测试 `test/open_api/test_pat_cascade.py`
  **执行顺序**:
  1. 先对用户禁用、删除、离开租户和遗漏主动 hook 的校验兜底写测试。
  2. 三个主动触发点撤销该自然人 PAT 并失效缓存。
  3. credential resolver 每次缓存刷新仍校验 User 与 UserTenant，作为漏 hook 的 fail-closed 兜底。
  4. 不增加服务账号登录守卫或 user_type 分支。
  **完成条件**: 主体失效后 5 秒内 PAT 返回 401，不泄漏其它租户资源存在性
  **依赖**: D03

- [ ] **D06：知识检索技能包和匿名分发**
  **设计依据**: design §5.D4；constitution C6/C8
  **文件**: `open_api/skill_packs/bisheng-knowledge-search/**`、`open_api/domain/services/skill_pack_service.py`、`open_api/api/endpoints/skill_pack.py`；测试 `test/open_api/test_skill_pack.py`
  **执行顺序**:
  1. 先写 zip 内容、确定性打包、路径穿越、实例地址渲染和多 API 副本一致测试。
  2. 技能包只调用 v2 knowledge:read 接口，使用新身份头名称。
  3. API Key 从 `BISHENG_API_KEY` 环境变量读取；仓库文件不得写任何真实地址或密钥。
  4. 分发端点沿用匿名 v1 路径，pack 名使用 allowlist；静态模板随应用镜像发布，多节点得到相同内容。
  **完成条件**: zip 可安装、可检索，且仓库 secret scan 无命中
  **依赖**: D04

- [ ] **D07：client 个人中心 API 令牌入口**
  **设计依据**: design §5.D4；client 前端规范
  **文件**: `src/frontend/client/src/layouts/UserPopMenu.tsx`、`components/PersonalTokenDialog.tsx`、`api/personalToken.ts`、三语 locale
  **执行顺序**:
  1. 开始前阅读 UI 规范和 landed 组件清单；先写 API 状态与一次性明文交互测试。
  2. 开关关闭不显示入口；开启后支持查看状态、获取/重签、删除、复制安装提示词。
  3. 明文弹窗必须确认已保存后才能关闭；之后只显示掩码。
  4. HTTP 只经 client `~/api` wrapper，不在 Recoil store 里请求。
  5. 三语同 PR，运行 client lint/typecheck/test/lint:prune。
  **完成条件**: 重签后旧 token 5 秒内失效，页面刷新不能恢复明文
  **依赖**: D04、D06

- [ ] **D08：platform PAT 台账和租户设置**
  **设计依据**: design §5.B1、§5.D4；platform 前端规范
  **文件**: `platform/pages/SystemPage/components/PersonalToken/**`、`controllers/API/personalToken.ts`、types、三语 locale、`locationContext.tsx`
  **执行顺序**:
  1. 开始前阅读 UI 规范；先写 API 封装和权限显隐测试。
  2. 增加与“服务账号”同级的“个人访问令牌”入口。
  3. 台账显示持有人、掩码、时间、权限位、管理员风险标记，支持单个和按人吊销。
  4. 部署开关关闭时租户开关置灰；租户设置支持 enabled 与 TTL。
  5. 使用 platform request wrapper 和 Zustand 既有方式，不引入新状态库。
  **完成条件**: 跨租户台账为空，非管理员无法访问
  **依赖**: D04

- [ ] **D09：WS-D 集成门禁 M4-PAT**
  **设计依据**: design §9 PAT
  **文件**: `test/open_api/test_pat_e2e.py`、PAT 对客文档
  **执行顺序**:
  1. 覆盖一人一把、两层开关、级联失效、knowledge:read 白名单、OBO 拒绝、超管不跨 tenant。
  2. 验证员工/client、管理员/platform、技能包三条链路。
  3. 文档只使用新身份头，不描述 P2 或 share-token。
  4. 运行永久禁止项扫描和 secret scan。
  **完成条件**: D01～D08 后端/前端测试全绿
  **依赖**: D01～D08、C07

---

## 8. Wave 5B：WS-E 日常模式五个 v2 接口

- [ ] **E01：对外请求模型和日常模式错误处理**
  **设计依据**: design §2 K21/K23、§5.E1、§5.E4、§6.3
  **文件**: `open_api/domain/schemas/workstation.py`、`common/errcode/open_api.py`、三语错误文案；测试 `test/open_api/test_daily_chat_schema.py`
  **执行顺序**:
  1. 先从当前 `APIChatCompletion` 自动对比字段，断言 v2 集合只删除 `use_knowledge_base`、`task_mode`，`files` 仍存在，`clientTimestamp` 仍必填。
  2. 新建 `OpenDailyChatCompletionReq(extra='forbid')`，不要增加 run_mode、execution、turn_id 或第二套事件模型。
  3. 传任何 `task_mode` 值都返回 400；值表达任务模式时返回 `26017`。传 `use_knowledge_base` 返回 400；已知异步意图字段返回 `26015`；其它额外字段返回 400。
  4. 实现外部模型到内部 `APIChatCompletion` 的唯一转换函数，无条件补 `task_mode=False`、`use_knowledge_base=None`，原样保留 `files`。
  **完成条件**: OpenAPI schema 中不存在两个删除字段，执行路径无法进入灵思任务分支
  **依赖**: A02、C04

- [ ] **E02：抽取并稳定 v1 日常聊天与配置共享 Service**
  **设计依据**: design §5.E2、§5.E3、§6.5；constitution C1
  **文件**: `workstation/domain/services/{chat_service,workstation_service}.py`、v1 workstation endpoints；测试 `test/workstation/test_daily_chat_service.py`、v1 SSE/配置快照回归
  **执行顺序**:
  1. 先录制 v1 chat/completions 的 SSE 顺序、持久化结果和 `/workstation/config` 返回基线。
  2. 把 endpoint 内编排下沉到 domain service，v1 endpoint 改为薄 adapter。
  3. v1 登录/匿名语义、请求模型和响应逐字节保持不变；`clientTimestamp` 不改可选。
  4. 提供配置投影函数，使 v2 只获取 models/tools，并按 PermissionActor 过滤工具。
  **完成条件**: v1 回归零变化；共享 service 不 import API 层
  **依赖**: A10

- [ ] **E03：抽取来源感知的会话列表与详情 Service**
  **设计依据**: design §5.E1、§5.C6
  **文件**: `chat_session/domain/chat.py`、v1 chat endpoints；测试 `test/chat_session/test_open_api_session_service.py`
  **执行顺序**:
  1. 先冻结 v1 `/chat/list`、`/chat/info` 响应信封和排序分页行为。
  2. 抽取可接收 `SessionSubject` 的 list/info 方法，复用 C06 subject matcher。
  3. v1 adapter 继续传登录用户；v2 adapter 传 OpenApiPrincipal。
  4. 不存在、跨租户、跨主体统一 404；列表按 update_time 倒序并保持 page/limit 契约。
  **完成条件**: v1 自然人列表不出现 SA-S 会话，v2 SA 只能看到自己的会话
  **依赖**: C06

- [ ] **E04：抽取临时文件上传 Service 和主体绑定**
  **设计依据**: design §5.E1、§5.E3
  **文件**: `knowledge/domain/services/knowledge_service.py` 或专用 upload service、v1 knowledge upload endpoint；测试 `test/knowledge/test_open_api_temp_upload.py`
  **执行顺序**:
  1. 先冻结 v1 multipart 限制和 `UploadFileResponse` 形状。
  2. 抽取文件大小/类型校验、对象存储写入和响应组装为共享 service。
  3. v2 上传把文件引用绑定到当前 tenant + API subject + external user；后续聊天只能引用同主体文件。
  4. 文件字节进入对象存储，不能把本地临时路径作为多节点权威状态。
  **完成条件**: v1 上传行为不变；跨主体复用 file_path 返回统一 404
  **依赖**: C06

- [ ] **E05：注册 config、chat/list、chat/info、knowledge/upload 四个 v2 adapter**
  **设计依据**: design §5.E1、§5.E2
  **文件**: `open_endpoints/api/endpoints/{workstation,chat,knowledge}.py`、router/scopes；测试 `test/open_api/test_daily_supporting_apis.py`
  **执行顺序**:
  1. 先对四个精确 method+path、API Key 门禁、无 JWT、scope 和 S/D 写测试。
  2. 注册 `GET /api/v2/workstation/config`，只返回 `models[]`、`tools[]`；不透出 linsight/deployment/invitation 配置。
  3. 注册 `GET /api/v2/chat/list` 和 `GET /api/v2/chat/info?chat_id=`，使用 E03 来源感知 service。
  4. 注册 `POST /api/v2/knowledge/upload`，复用 E04 multipart service，保留 `files` 能力。
  5. 四个 endpoint 只消费 `get_open_api_execution`，不得声明登录依赖。
  **完成条件**: 有 key 无 JWT 正常；有 JWT 无 key 401；跨主体 chat/file 为 404
  **依赖**: E02、E03、E04

- [ ] **E06：注册 v2 workstation/chat/completions**
  **设计依据**: design §5.E1～§5.E5
  **文件**: `open_endpoints/api/endpoints/workstation.py`、daily adapter、scope 注册；测试 `test/open_api/test_daily_chat_completion.py`
  **执行顺序**:
  1. 先写新会话、续聊、模型、工具、files、SA-S、SA-D、PAT、SSE 错误和持久化结果测试。
  2. 注册 `POST /api/v2/workstation/chat/completions`，scope=`chat:invoke`、modes=S/D、session=true。
  3. 用 E01 转换函数和 E02 shared service；内部固定日常模式，不能复制聊天实现。
  4. 模型和工具必须来自当前主体的 config 投影；无权限工具明确拒绝。
  5. SSE 事件顺序、结束事件和数据库消息与 v1 同形；断连时正确清理 ContextVar。
  **完成条件**: `files` 能正常使用；两个删除字段或异步意图不会被静默忽略
  **依赖**: E01、E02、E05

- [ ] **E07：OpenAPI Schema 和接口文档与实现对齐**
  **设计依据**: design §5.E、§6.2、§10
  **文件**: `features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.{json,md}`、应用 OpenAPI schema 定制；测试 `test/open_api/test_openapi_schema_contract.py`
  **执行顺序**:
  1. 从实际 app schema 比对所有 v2 密钥 HTTP 路由、method、security、header、请求体、响应和示例。
  2. WebSocket 以 vendor extension/Markdown 单独校验 URL、header、消息字段和示例。
  3. 断言日常请求无 `use_knowledge_base`/`task_mode`，有 `files`；工作流等待输入字段对外为 `input`。
  4. 断言文档不出现旧品牌头、P2/share-token 或 v1/v3 解释性内容。
  5. 用 Apifox/Postman 实际导入 JSON 做一次人工验证。
  **完成条件**: 所有 `$ref` 可解析，导入后能生成带 Bearer Auth 的 HTTP 集合
  **依赖**: A10、E05、E06

- [ ] **E08：WS-E 集成门禁 M4-日常会话**
  **设计依据**: design §4 M4、§9
  **文件**: `test/open_api/test_daily_chat_e2e.py`
  **执行顺序**:
  1. 覆盖五个 v2 endpoint 的 key-only 调用和 scope/mode 拒绝。
  2. 对比 v1/v2 SSE、配置投影、会话列表/详情和上传响应。
  3. 覆盖 SA/PAT/D 会话归属矩阵、跨主体 chat/file 404、工具权限过滤。
  4. 运行 OpenAPI contract、永久禁止项扫描和 arch-guard。
  **完成条件**: E01～E07 全绿，v1 行为无回归
  **依赖**: E01～E07、C09

---

## 9. Wave 5C：WS-B platform 管理界面

- [ ] **B01：服务账号列表、创建和详情骨架**
  **设计依据**: design §5.B1、§5.A2；platform 前端规范
  **文件**: `platform/pages/SystemPage/components/ServiceAccount/**`、`pages/SystemPage/index.tsx`、`controllers/API/serviceAccount.ts`、types、三语 locale
  **执行顺序**:
  1. 阅读 UI 规范和 landed 组件清单；参考 `c5989ffd6` 时只复用组件结构，不复用 User 影子账号语义。
  2. 先写 API 封装、管理员显隐和明文一次性弹窗测试。
  3. 实现列表、创建、概览、停用/启用/删除；详情显示资源归属人。
  4. 所有 HTTP 经 platform request wrapper；不在 Zustand store 请求。
  5. 三语同 PR，运行 platform lint/typecheck/test/lint:prune。
  **手动验证**: 创建 SA 后进入详情；明文必须确认保存后关闭；数据库没有对应 User
  **完成条件**: 管理员可完成服务账号全生命周期，非管理员和跨租户访问均被拒绝
  **依赖**: A08

- [ ] **B02：API 密钥与委托配置界面**
  **设计依据**: design §5.B2、§5.C2
  **文件**: `ServiceAccount/ApiKeysTab.tsx`、`KeyIssueDialog.tsx`、`DelegateScopeSection.tsx`、API/types/locale
  **执行顺序**:
  1. 先写 scope 选择、空委托范围、移除 delegate 和错误提示测试。
  2. 表单只有基本信息、权限位、委托配置三组；不得出现“网络”组。
  3. delegate 选中后要求至少一个 user/department 范围；列表显示范围摘要。
  4. 界面不显示未部署三扩展位；后端拒绝时展示 260xx 三语文案。
  **手动验证**: 无范围不能保存；保存后摘要正确；去掉 delegate 后范围消失
  **完成条件**: 密钥表单只有三组设计字段，委托配置与后端状态完全一致
  **依赖**: B01、C03

- [ ] **B03：服务账号资源授权页**
  **设计依据**: design §5.B3、§5.A3
  **文件**: `ServiceAccount/ResourceGrantsTab.tsx`、授权 API/types/locale
  **执行顺序**:
  1. 先写 subject 固定为 service_account、跨租户和撤销测试。
  2. 详情页发起授权时固定 `subject_type='service_account'`、`subject_id=sa_id`。
  3. 区分管理员授予与创建回授；“全部撤销”不能误删保障继承访问的回授。
  4. 通用选人器不增加服务账号。
  **手动验证**: grant/check/revoke 生效；来源列正确；id 与用户碰撞不串权
  **完成条件**: 服务账号授权只能从主体详情页发起，授权来源和撤销边界正确
  **依赖**: A06、A09、B01

- [ ] **B04：个人访问令牌台账入口整合**
  **设计依据**: design §5.B1、§5.D4
  **文件**: SystemPage tab、`PersonalToken/**`、API/types/locale
  **执行顺序**:
  1. 将 D08 页面作为“服务账号”的同级入口，不嵌入某个服务账号详情。
  2. 验证管理员权限、部署/租户开关、TTL、吊销和风险提示。
  3. 确认所有列表仅显示掩码。
  **手动验证**: 非管理员不可见；跨租户无数据；关闭租户开关后员工端立即不可用
  **完成条件**: PAT 台账和设置作为独立入口可用，且不泄露明文令牌
  **依赖**: D08

- [ ] **B05：发布示例、管理审计和分享链路回归**
  **设计依据**: design §5.B4、§5.C5、§5.F4
  **文件**: `ApiAccess.tsx`、`ApiAccessFlow.tsx`、`controllers/API/log.ts`、locale；`ChatLink.tsx` 仅回归不修改协议
  **执行顺序**:
  1. 合并 F07 的 v3 发布示例，并验证 v2 密钥示例仍带 Authorization。
  2. 管理操作 action 可按现有审计页规则展示；不要把高频 `open_api.call` 加入系统操作白名单。
  3. 回归现有分享链接生成、打开和撤销流程，确认无新参数、字段或 share-token 通道。
  **手动验证**: 无密钥发布示例全为 v3；密钥示例全为 v2；分享链接行为与改造前一致
  **完成条件**: 发布示例、管理审计和既有分享链路三项回归均通过
  **依赖**: B02、B03、B04、F07、C08

- [ ] **B06：WS-B 前端质量门禁**
  **设计依据**: design §9 前端/网关
  **文件**: platform/client 相关测试与手动清单
  **执行顺序**:
  1. 从 `src/frontend/` 运行 `pnpm lint`、`pnpm typecheck` 和相关 test；修复触碰文件的旧 i18n 违规并 `lint:prune`。
  2. 手动验证 SA 创建/密钥/委托/授权、PAT 台账/开关、v3 发布示例。
  3. 不做视觉决策；发现需改样式时提交设计师确认。
  4. 运行前端范围扫描，确认无品牌身份头、P2、share-token 新逻辑。
  **完成条件**: 两个前端质量门禁全绿，手动清单有截图/Network 证据
  **依赖**: B01～B05、F06、D07

---

## 10. Wave 6：全量验证与发布

- [ ] **R01：三条迁移链、双数据库和数据反向检查**
  **设计依据**: design §7、§10
  **文件**: 三个 F053 Alembic revision、迁移测试
  **执行顺序**:
  1. 串联 `api_credential_tables` → `delegate_scope_and_session_subject` → `pat_tenant_setting` 的 down_revision。
  2. 空库与 beta1 存量库执行 upgrade head；MySQL CI 与 DM8 105 分别验证。
  3. downgrade/upgrade 再跑一次，检查索引、默认值和 tenant filter 注册。
  4. 反向断言没有 `user_type`、`open_api_call_log`、credential P2 列、`share_link.share_scope`。
  **完成条件**: 三个 revision 全通过，数据库对象与 design §6.4/§7.1 完全一致
  **依赖**: A01、C02、D01

- [ ] **R02：后端全量测试、路由和安全门禁**
  **设计依据**: design §9；constitution C1～C8
  **文件**: `test/open_api/`、`test/public_endpoints/`、相关 permission/workstation/chat/knowledge tests
  **执行顺序**:
  1. 运行 ruff、arch-guard 和全部受影响后端测试。
  2. CI 运行 MySQL、Redis、OpenFGA 集成；DM8 105 回归。
  3. 从实际 `app.routes` 验证：v2 统一密钥依赖、五个日常路由存在、六个旧 chat 路由不存在；v3 精确九路由。
  4. 覆盖三面隔离、异步快照、ContextVar reset、审计敏感字段、文件过滤 fail-closed。
  5. 运行永久禁止项扫描和 secret scan。
  **完成条件**: 无失败、无范围漂移、无安全降级
  **依赖**: R01、A13、C09、D09、E08、F08

- [ ] **R03：端到端、前端和商业网关验证**
  **设计依据**: design §9、§10
  **文件**: `/e2e-test` 产物、platform/client 手动验证记录、网关验证记录
  **执行顺序**:
  1. 执行 `/e2e-test features/v3.0.0-beta1/053-openapi-auth-and-identity`。
  2. 验证 v2 SAK/PAT/S/D、五个日常接口和两个密钥 WS。
  3. 无痕浏览器验证 v3 工作流/助手全部 HTTP/WS；Network 不得出现 guest v2 请求。
  4. 验证现有分享链接原样可用。
  5. 商业版验证 v3 HTTP/WS 代理，确认 v3 不被登录/API Key 网关拦截。
  **完成条件**: E2E、两个前端质量门禁、商业网关回归全部有结果
  **依赖**: R01、R02、B06

- [ ] **R04：发布顺序、文档和最终验收**
  **设计依据**: design §10、§11
  **文件**: release notes、部署清单、v2 OpenAPI 文档、v3 发布文档
  **执行顺序**:
  1. 先发布向后兼容的 OpenFGA service_account 模型；模型未就绪时保持 SA 签发入口关闭。
  2. 执行三条迁移并部署含 v3 的后端，先验证九个 v3 路由。
  3. 再切 client、platform 和商业网关；确认后移除旧 v2 匿名语义。
  4. 分开发布 v2 密钥 API 与 v3 免登录发布文档；不能把鉴权说明混在同一示例。
  5. 最终核对 58 个任务、所有测试证据和偏差记录，运行 `/code-review --base feat/3.0.0-beta1`。
  **完成条件**: 发布检查表签字；没有未说明偏差或待办
  **依赖**: R03

---

## 11. 依赖图

```text
P00
 └─ A01 → A02 → A03 → A04
             └─ A05 → A06 → A07 → A08（M1）
                          └─ A09 → A10 → A11
                                      └─ A12 → A13

A/C 同版：
A07 → C01 → C03 → C04 → C05/C06/C07/C08 → C09
A01 → C02 ────────────────┘

v3 发布面：
A10/A12 → F01 → F02 → F03/F04 → F05 → F06/F07 → F08

PAT 与日常模式在 C09 后并行：
D01 → D02 → D03 → D04 → D05/D06/D07/D08 → D09
E01 → E02/E03/E04 → E05 → E06 → E07 → E08

管理界面按后端依赖穿插：
A08 → B01 → B02/B03；D08 → B04；F07/C08 → B05 → B06

最终：R01 → R02 → R03 → R04
```

---

## 12. 每个 Wave 的统一完成检查

```text
[ ] 新测试先红后绿，相关回归全绿
[ ] 任务完成条件逐条有证据
[ ] scripts/arch-guard.sh 无 VIOLATION
[ ] 涉及前端时 lint/typecheck/test/lint:prune 通过
[ ] 所有新文案三语齐全，生成物由脚本产生
[ ] v2/v3 endpoint 未跨 API 层 import，未内部 HTTP 转调
[ ] tenant/permission ContextVar 在 finally reset
[ ] 永久禁止项扫描无新增命中
[ ] /task-review 通过后才勾选任务
```

---

## 13. 实际偏差记录

> 只记录一行指针；原因与新决策写回 `design.md`。若偏差推翻最终设计，必须先暂停并取得用户确认。

- 暂无。

---

## 修订历史

| 日期 | 改动 |
|---|---|
| 2026-08-31 | 初版按旧设计拆为 A～G，包含 P2、share-token 和旧日常会话方案 |
| 2026-09-04 | 按最终 design 全量重排为 58 个顺序任务：删除 R8/P2、share-token、`user_type`、独立调用日志表和三端点日常方案；增加独立服务账号/F048 主体、复用 `audit_log`、五个日常 v2 接口及九个 v3 免登录发布接口 |
