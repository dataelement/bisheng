# Python 策略实现进度（2026-09-09）

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

## T044/T045：策略与操作 Repository

新增 `domain/repositories/policy.py` 与 `admin_operation.py`。所有方法接受调用方 SQL Session，仅 flush，事务由外部短事务上下文提交。通过现有租户事件和 strict context 做 SELECT 隔离；读后校验实体所属租户，拒绝缺失或 bypass 上下文。没有 Service ORM 查询、方言专用 SQL、进程内锁或额度预占。

已实现用户唯一键占位、不可变操作登记、同 ID 主体/负载幂等优先、单用户 pending owner、FOR UPDATE、lease_generation 领取和过期代次拒绝、旧新审计快照与策略同事务提交、READY/生效完成、提交前拒绝与所有者清理。后续提交不覆盖旧 operation 的 actor、版本或快照。

先运行测试得到缺少 repository 模块的预期红测。当前 7 项 SQLite 文件数据库测试通过，覆盖实际 SQL 回滚/隔离、同操作重试、异载冲突、代次接管、连续历史、权限撤销清理和无上下文拒绝。

`test_external_sql_first_configuration_race` 提供真实 MySQL/DM8 两线程首次配置入口，执行时缺少 `DSH_TEST_DATABASE_URL`，fixture 明确报错。此验证仍待环境，不能用 SQLite 结果声称生产双库并发已经验证。

## T054/T055：策略编排

新增 `domain/services/admin_policy.py`，按设计 §4.5.5 执行：登记 → Redis 独立冻结 → SQL 新策略/审计 → Redis 安装并保留冻结 → SQL READY → 仅移除该操作冻结 → SQL SUCCEEDED。SQL 已提交的恢复不重复加 version；SQL 未提交前重验权限和模型可访问性；提交后的已授权意图继续完成。

稳定接线接口：

- `DshAdminService(repository_scope, quota, authorize, validate_models, now, lease_seconds=30)`。
- `repository_scope()` 是提交/回滚短事务 context manager，yield `DshPolicyRepository`；不得跨 Redis await 保持 SQL 事务。
- `authorize(actor_user_id: int, user_id: int) -> Awaitable[bool]`：当前管理权限、目标租户/状态。
- `validate_models(actor_user_id: int, user_id: int, model_ids: list[int]) -> Awaitable[bool]`：现有模型治理和合法 Root 共享入口。
- `update_policy(user_id, actor_user_id, request: DshUserPolicyInput)` / `resume(operation_id)` 返回内部 operation 字典；API 仍须适配冻结的响应 schema、执行当前调用者鉴权。
- quota 采用 `QuotaRedis.block_policy/install_policy/finish_policy` 同 op/generation/epoch 协议；首次用户 gate 必须经 T053 权威恢复/初始化证明后创建，否则继续 fail closed。

12 项编排测试覆盖远程每阶段响应丢失、SQL COMMITTED/READY/EFFECTIVE 崩溃回滚、旧 Worker 并发、相同操作恢复、不重复审计、提交前后失权边界、异操作竞争及模型不允许。另 4 项 **真实 Redis + SQLite** 集成测试通过，验证无故障及 block/install/finish 回执丢失恢复，UNKNOWN 原因始终保留。

## 已执行验证

```text
DSH_TEST_REDIS_URL=redis://127.0.0.1:16362/15 DSH_TEST_REDIS_ISOLATED=1 \
  <shared-venv>/python -m pytest --confcutdir=test/dsh \
  test/dsh/test_policy_repository.py test/dsh/test_policy_service.py -q -k 'not external'
23 passed, 1 deselected
```

Redis 仅使用隔离测试实例及随机 key prefix，测试结束清理自己的 key；未停止服务。Ruff format/check 已通过这 5 个新文件。

## L1 任务检查

| 项 | 结果 | 证据 |
|---|---|---|
| 分层 | PASS | Service → Repository，Service 无 SQL/ORM 查询 |
| 命名/类型 | PASS_WITH_NOTES | Repository 实例方法符合当前 C1，技能旧 DAO classmethod 条目不适用 |
| 序列化 | PASS | 仅内部操作字典；对外响应由后续 API 适配 |
| 双库/租户 | PASS_WITH_NOTES | 通用 ORM + 自动过滤 + 写主体校验；真实双库竞争待环境 |
| 前端 | N/A | 未修改前端 |
| 泄漏/日志 | PASS | 无凭据，恢复日志带 traceback，持久错误仅固定代码 |
| 设计同步 | PASS_WITH_NOTES | 实现遵设计 4.5.5，主线负责共享 design/tasks 回写 |

T044/T045 的真实 MySQL/DM8 并发条件仍未证明；T054/T055 的真实 Redis CAS 已执行。未提交、未推送。

## 后续验证更新：真实 MySQL8 已补齐

主线启动独立 MySQL8 后，将 `sql_store` fixture 参数化 SQLite 与外部数据库，全部 Repository/策略编排用例分别执行；只重建专属 `dsh_test_policy` 库内两张本模块测试表。加上首次配置两线程竞争与真实 Redis：**47 passed**，先前缺少 MySQL 环境的记录已被本次实际执行补齐。DM8 仍按 Constitution C2 交中央回归，本机没有 DM8 驱动/服务。

## T056–T061：模型强读、协议及执行闭环

- `LLMService.get_dsh_model_snapshot(id)`：strict tenant scope 复用当前 `get_model_for_call`；当前模型/供应商强读，拒绝删除、下线、非 LLM、跨租户及取消共享。合法 Root 共享继续走原模型治理。
- `BishengBase.get_class_instance_from_snapshot(...)`、`LLMService.build_dsh_llm(...)`：使用同一对快照的深拷贝构造外层 BishengLLM，不再访问 60 秒配置缓存；DSH 在复制的 provider user_kwargs 上强制 `max_retries=0`，不改变普通调用和存储配置。
- `schemas/chat.py`：冻结字段的严格请求 schema、工具多轮 call ID 完整性、JSON 字符串参数、唯一函数名、互斥输出限制、stream_options/n/参数边界。
- `infrastructure/chat_adapter.py`：仅通过外层 `bind_tools/ainvoke/astream`，保持既有治理包装；保留 tool argument 增量、验证完成后的 JSON/函数名、受控 reasoning 扩展、可靠 usage 与未知分离。缺失正常 finish 或工具参数不完整不产生成功结果。
- `services/model.py`：当前 policy 与模型交集列表；principal → 强读 policy/model → Redis 准入 → 外层 LLM → 真实用量结算 → JSON/终止 SSE。额度不预占，在途超额照实记账；换模型不清总额，结算回执丢失只查原 request，不重发推理。未知非流 503、流中 error 且无 DONE。

模型接线接口：

```python
DshModelService(
    policy_reader=async_read_current_policy,       # (user_id: int) -> policy | None
    model_loader=LLMService.get_dsh_model_snapshot,
    llm_builder=lambda model, server, principal, request: LLMService.build_dsh_llm(
        model, server, user_id=int(principal.user_id), streaming=request.stream,
    ),
    capabilities_for=verified_adapter_capabilities, # (model, server) -> ChatCapabilities | None
    usage=DshUsageService(quota),
    now=utc_clock,
)
```

`capabilities_for` 必须只声明已通过适配验证的能力，不按模型名字推断 reasoning 支持。未提供实际供应商凭据/模型样本，因此本次 fake provider 测试不能作为所有供应商/模型 PoC 已通过的声明。

`complete(principal, DshChatRequest)` 返回冻结 JSON 或 `PreparedStream`。HTTP 适配必须 `finally: await stream.aclose()`，包括未首次读取即断连：此时没有上游调用，可靠零用量 CANCELLED；已调用后缺 usage 则 UNKNOWN。每次 `__anext__` / `aclose` 内恢复/清理 principal context，避免不同 Task 消费生成器时跨 Context reset token 的真实故障。

### 当前模型验证

- 10 项真实 `LLMService` / `BishengBase` / `BishengLLM` 类测试（DAO 与 SDK 构造依赖替身），使用主线生成的不含业务凭据的测试配置；已用真实类替换早期源方法隔离测试。
- 14 项 Chat schema/协议测试，包括工具分块、不完整参数拒绝、strict bool、未知字段、替代输出参数拒绝、缺 usage 不归零。
- 12 项模型服务测试，包括实时首块、取消关闭上游、未读即取消可靠零、UNKNOWN 无 DONE、结算回执丢失和 **2 项真实 Redis** 超额/换模型总量/回执丢失验证。
- 上述新增文件及两个 LLM 窄入口 Ruff format/check 通过；继承 SDK 的 langchain-community DeprecationWarning 属于现有依赖提示。

尚未声称完成：HTTP/Nginx/SSE 与页面/桌面客户端联调、供应商 PoC、完整端到端、DM8 中央回归。主线负责这些接线与任务总状态。

最终联合复验（本 agent 五个测试文件，同进程，隔离 MySQL8 + Redis + SQLite）：**83 passed, 1 existing deprecation warning**，无 deselect/skip。避免了仅分别通过却共享租户事件互相污染的误判。

## 本轮 T068–T075 / T090–T093 与首次策略补齐

### 实际实现与接线

- `UserDshProfileRepository` 在 User 行锁下合并实际 dirty 字段，避免旧对象覆盖 profile/token version；用户名或禁用状态变更的 User、单调 profile_version、SYNC_PROFILE outbox 同一提交。Repository 不提交，由业务事务持有者提交。
- `UserService.persist_profile_update/apersist_profile_update/record_dsh_profile_change/activate_tenant_with_profile/batch_dsh_profiles/scan_dsh_profiles` 已被实际调用。API 用户禁用/启用继续保留原 JWT 失效逻辑；SSO `LoginSyncService._upsert_user` 三处实际改名路径已替换旧独立提交。
- 任务路径偏差：实际用户名更新在 `sso_sync/domain/services/login_sync_service.py`，不是纯差异计算的 org-sync reconciler。主部门实际提交在 `UserDepartmentService.change_primary_department`，已在原 commit 前写资料意图；后续 `UserTenantSyncService.sync_user` 保留 F012“主部门先提交，再尝试租户迁移”的顺序，DSH 开启时将 UserTenant 主成员切换、JWT token_version 和新租户资料意图合入当次同一事务。没有宣称这两个阶段是一个跨阶段事务。
- 资料按当次已提交快照形成 UUID5 确定性操作 ID；旧租户快照不会自动移动 Gateway 唯一席位 `(installation_id,user_id)`。Gateway 只按原 tenant/user/version 单调更新资料，不改授权。
- `worker/dsh/operations.py` 从严格租户下的持久操作动作派发，header/payload 不匹配拒绝；完整恢复/清除 ContextVar。过期 lease 巡检发现投递丢失，旧代次无法覆盖；操作仍是原 ID。
- `worker/dsh/profiles.py` 投递冻结的 outbox payload，0 accepted 是旧版本/无席位的合法确认；超时保留 PROCESSING。实例级资料巡检通过 UserService 的 ≤100 用户游标强读完整快照，直接低频单调修复，避免已完成 outbox 阻止重新修复。已交 quota agent 接入真实 Celery registry/beat；其回报 7 个任务真实 import 成功，profiles 30 分钟巡检。
- Celery 入口统一使用现有 `run_async_task` 长生命周期 worker loop，避免 `asyncio.run` 让共享 Redis/OpenFGA 跨事件循环。
- 新 `admin_runtime.py` 与 `services/admin.py`/`schemas/admin.py` 提供当前平台权限、用户业务批量补齐、严格 Gateway 响应验证和持久撤销/重分配。Root 实例范围保持既有 `is_global_super && admin_scope is None`，显式 Child/Root scope 均保持限定；租户管理员不能传入其它 tenant。
- Root 全局只在验证实例管理员后通过专属 repository 定位操作所属租户，然后回到 strict scope 读审计；租户用户不获得此定位能力。操作请求 actor 只从平台 JWT 提取；operation_id、原 actor/target/版本/负载不变。超时先读 Gateway 原 operation；UNKNOWN 才按当前权限重试原命令，撤权则 FAILED/permission_denied，不能造新命令或伪成功。
- 八端点在 `api/endpoints/admin.py`，普通管理统一 `status_code/status_message/data` 包装，不能套客户端 DSH error envelope；由主线挂载 `/api/v1`。请求体禁止额外 actor/tenant 字段；历史席位/策略可用受授权的 tenant_id 查询参数定位。
- 用户页只对 Gateway 已分页当前页做一次用户业务批量补齐，不查询模型/用量；不存在过 Seat 的用户通过既有 BiSheng 用户选择器预先配置策略，不伪造跨库全用户分页。设备视图使用 Gateway SQL `target.user_id` 精确查唯一 Seat，之后按 seat_id 查询会话。
- policy 使用实时月账本，先受控新月初始化；失败降级 SQL 历史，不能清零：`usage.source=live|persisted|unavailable`、`quota_state=available|exhausted|unavailable`、`used/limit/remaining/as_of`，新增管理字段 `models: Record<string,number>|null` 与 `unknown_pending: number|null`，未知与统计不可用分开显示。客户端固定 usage 响应未添加这些管理字段。
- UPDATE_POLICY 首次 expected_version=0 时，SQL 持有当次 op/fence 且 policy0、无任何 model_call/monthly_usage 历史才能产生 `new_user_proof`，再由 QuotaRedis.ensure_new_user 在已批准 epoch 且无 Redis 历史上受控创建 gate0。真实 Redis 已验证从完全无 gate 到策略1，正常已用量策略1→2恢复不会借此重建账本。

### 验证证据和边界

- 各新增测试对缺失服务/Worker/API/钩子先记录红灯，然后实现转绿；追加防御性严格 schema 检查随实现收紧。没有将所有原型辅助函数声称为逐行测试先行。
- 同进程联合回归一度 **120 passed**（SQLite + 独立 MySQL8 + 真实 Redis，无 deselect/skip）；随后加入会员/JWT/profile 原子提交/回滚、Root 审计定位、外租户页拒绝和撤权重试测试，最终计数在后续验证记录追加。
- 资料专项后续 **12 passed**，包含两个数据库中的真实会员迁移事务提交/回滚；管理专项后续 **15 passed**（含生产 authorizer callback、八条实际 FastAPI 路由与无 actor 伪造、Gateway 不可用降级），随后再追加撤权恢复用例。
- 新增实现/测试 Ruff check 和 format 通过。所改旧文件与 HEAD 静态问题计数完全相同：user service 23、user API 60、tenant sync 16、SSO sync 1；主部门 service 0，均无新增 lint 问题。架构 guard 对所改旧钩子无新增反馈。
- 本轮真实数据库/Redis 测试不等同整套登录、Nginx、Gateway HTTP、Celery broker/E2E 或供应商 PoC 已全部通过；真实两仓联调、DM8 与供应商适配运行证据仍由主线后续执行/报告。Gateway 行为只使用其固定内部契约，Python 本分工测试使用响应替身；不能宣称完整 Java HTTP E2E。
- 本 agent 未提交、推送或修改共享 tasks/design 勾选；已向主线发出所需文档同步点。

最终本分工十个文件联合回归：**130 passed, 7 个现有依赖 warnings**（37.95s，无跳过）；分页固定 key 收紧后 **11 passed, 6 deselected**（定点排除 external 已在联合执行）。

## 有界两仓接口审查（2026-09-09，独立于 TLS/E2E）

检查范围：Python runtime/API/router/middleware、Gateway 四个公开/七个内部路由、身份双向 HMAC、浏览器 approve/deny、管理分页/操作状态与策略用量降级。此处是实际源码契约核对及定点运行，未将 Mock WebClient/httpx 视作部署后的 Nginx/TLS E2E。

发现并修复：

1. **席位命令 ID 不匹配**：Gateway `DshSeatOperationService.java:21` 与 `DshInternalController` 的 operations/read 要求 UUID；原 Python SeatCommand 只限长度，错误 ID 会先入持久意图，再反复收到 Gateway 400。现 Python `api/endpoints/admin.py:20` 严格 canonical UUID，`services/admin.py` 在意图前再次验证；API 输入 user/tenant/expected_grant_version 也限 int64，搜索/游标与 Java 长度边界对齐。先红后绿回归，合法 UUID 重试仍保持同一 ID。
2. **100 人资料批次可能超过 64 KiB**：双方签名/解析均限制 65536 bytes，合法多字节姓名会导致整页重试失败。`worker/dsh/profiles.py` 的 `profile_batches` 按与 GatewayClient 完全一致的 UTF-8 JSON 编码计算，每请求同时满足 ≤100 与 ≤65536 bytes，不漏/重排任何资料。单条超过界限的 outbox 以 FAILED/invalid_request 保留原 payload 审计，不发远端、不无限重试。
3. **只有 UNKNOWN、没有可靠月汇总时管理不可见未知数量**：总额仍保持 unavailable/null，新增独立 `DshUsageRepository.unknown_pending`（quota agent 实现）和管理 composition 回调，在可靠总额不可读时仍显示已持久化跨月 UNKNOWN 数量。不会把计数转换成 token 或解除阻塞。
4. **HMAC key/instance 字符集宽度不一致**：原 Python 接受点/冒号和 128 位 instance，但 Java 只接受 `[A-Za-z0-9_-]`、instance≤64。已发送主线；当前 source 已见主线将 `ServiceKey` 改为独立 `_INSTALLATION` 与 `_TOKEN` 校验。
5. **平台合法长用户名与 Gateway 128 名字限制不一致**：已发送主线，不截断真实姓名。主线负责将 Gateway 入口保持平台 255 Unicode 码点、搜索投影预留 lowercase 扩张宽度并做真实 MySQL 回归，本分工未自行修改 Gateway DDL。

核对一致的关键链路：

- `GatewayClient.PATHS` 的七个内部 POST 与 `DshInternalController` 路由一一匹配；反向 `DshIdentityClient.java:28–34` 的两个 Python 路径和 JSON 字段与 identity endpoints 一致，返回为裸身份 DTO，不经过管理包装。
- Python `api/router.py:10–12` 挂三类 endpoint；Gateway `DshRoutes.java:9–11` 覆盖实际七个 Python 路径及 admin 前缀，绕过旧收费/回复改写，并未撤除每条 DSH 路由的专属认证。middleware 精确 credential routes 与浏览器 JWT authorize/admin 分离。
- 双方 canonical 顺序均 method/path/SHA256(raw body)/instance/key/timestamp/nonce，用换行分隔，UTF-8 HMAC-SHA256 小写 hex，±60s、签名后原子 nonce claim 120s；两方向独立密钥；HTTPS 固定 origin。这里只核对协议，不宣称验证了线上代理 path 重写、证书或时钟偏差。
- 新 browser deny 使用同一个 JWT+Origin+JSON 受控 authorize 入口，只从 Gateway resolve 的绑定返回 loopback URI/state，并在 tickets.issue 前返回 access_denied；前端 denyDsh/useDshAuthorization 使用同字段，未出现遗漏的第十二条 Gateway 路由。
- Gateway management Page 恰为 items/next_cursor/has_more；Python 原样延续 signed cursor 与 filters，再做当前页一次用户业务批量补齐。sessions 通过精确 target.user_id 查唯一 seat，再带 seat_id 查询；Gateway 再校验 tenant/user。
- Gateway operation status 只有 UNKNOWN/SUCCEEDED/FAILED，Python 将 UNKNOWN/网络未知保留本地 PROCESSING，原 ID 查询后才重试；已确认 Gateway 合法成功总会 grant_version+1，新 op 对已目标状态返回 FAILED，因此 Python 的结果版本严格大于 expected 校验一致。
- 管理 policy source 仅 live/persisted/unavailable，quota_state 仅 available/exhausted/unavailable；历史分量、UNKNOWN 计数不影响准入，也不把 SQL 估计改成实时可用。

审查修复定点复验：**27 passed, 7 existing warnings**（SQLite/MySQL，13.58s），涵盖管理六类、八路由、资料 lease/cursor、超大批次拆分、单条终态审计和 UNKNOWN 无总额降级。未运行 Redis 库15（quota agent 正在使用），没有改动其并行测试数据。新增/改动文件 Ruff 通过；旧钩子 git diff --check 通过。

## 真实 MinIO 证据/审批适配集成验证

新增 `src/backend/test/dsh/test_minio_integration.py`，实际运行 **4 passed in 0.75s，无 skip/deselect/warnings**。

隔离环境：本机 OrbStack 新容器 `f062-minio-32d65bd05e`，仅 `127.0.0.1:32768` 映射 API 端口；固定镜像 `minio/minio:RELEASE.2025-04-22T22-12-26Z`，拉取 digest `sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`。测试随机凭据仅存 `/private/tmp/f062-minio-32d65bd05e.json` 与同名 `.env` 的 0600 文件，没有回显内容，没有复制项目生产配置；Python MinIO SDK 7.2.18。Redis 使用独立 DB11，只执行审批连接/元数据验证，不修改 DB15。

实测覆盖：

- 创建随机隔离 bucket，启用 MinIO versioning，并在同一 key 覆盖写入后使用旧 version ID 读取旧证据，确认未误读 latest；跨 tenant 前缀、缺 version、`@null`、URL、路径穿越被拒绝，真实 metadata 超限对象被拒绝。
- `MinioEvidenceStore` 读真实对象后，真实 `DshReconciliationService._verify` 对 SHA256 与原 provider request/model/start time/真实 token 分量绑定验证；错误 digest 和错误 provider_request_id 都失败。
- `MinioQuotaApprovalStore.publish` 对真实已验证 Redis run_id/epoch 发布版本固定对象，覆盖 key 的新版本后旧 object@version + digest 仍返回旧批准人。`activate_from_approval` 读取真实 MinIO 后激活匹配的 Redis 主实例并通过 topology.check。
- 错误审批 SHA256、其它 instance 路径、未启用 versioning 的发布、publish 时 run_id 不符、激活已签存但 run_id 不匹配的旧主实例证明均拒绝；失败激活保持 topology.ready=False。
- fixture 只清理自己随机创建的 bucket、所有对象版本及 delete marker；清理成功包含于 4 项通过结果。没有访问或清理既有业务 bucket。

验证边界：MinIO 使用隔离 loopback HTTP，不能等同部署 TLS/IAM/对象锁策略已验收。审批 fixture 的 fencing/ledger_proven 标志只针对隔离测试连接，未声称完成生产旧主隔离、真实账本恢复或崩溃重启故障验收。容器和 0600 连接文件暂留给 quota agent 的跨进程故障测试，已告知主线；清理由该协作结束后统一执行，不能中途停掉。

复现环境变量：`DSH_TEST_MINIO_CONFIG=<0600临时配置路径>`、`DSH_TEST_MINIO_ISOLATED=1`、`DSH_TEST_REDIS_URL=redis://127.0.0.1:16362/11`、`DSH_TEST_REDIS_ISOLATED=1`；运行 Python 3.11 venv 的 `pytest --confcutdir=test/dsh test/dsh/test_minio_integration.py -q`。新增测试 Ruff check/format 通过；未改 recovery/operations 实现。

## 管理 Saga 终态与相同 intent 恢复专项

沿 Gateway controller → SeatOperationService → OperationRepository 的真实事务路径核查：旧 grant_version、seat tenant 不匹配、状态不匹配、容量不足原本已在 `gt_dsh_operation` 持久化 FAILED，不会因业务异常回滚。实际遗漏位于事务前：REASSIGN 的 DSH disabled 与 License 无效/过期/instance 不匹配直接抛 403，Python 将其当作未知而一直 PROCESSING。

修复：

- Gateway `DshOperationRepository.recordFailure` 用既有隔离级别/重试事务写入完整 actor/target/action/expected/hash 失败审计；同 ID 同 hash 返回旧终态，不同 hash 拒绝，不写 grant/session。`DshSeatOperationService` 先验原 ID/hash，再对已知前置拒绝写 FAILED；Controller 先完成 HMAC/DTO/actor 目标授权后传递 enabled，返回固定 CommandResult HTTP200。修改范围仅三文件，保留主线姓名/DDL/CLI 工作。
- Python `admin.resume` 对 operations/read 的终态必须重放原持久 payload，让 Gateway 校验相同 actor/target/action/version 的 hash 后才采信，避免只凭 operation_id 接收另一个 intent 的成功结果。
- `GatewayClient` 只有固定 HTTPS revoke/reassign 端点的 HTTP409、严格原生 error envelope、`authorization_conflict/conflict_error` 才产生确定拒绝；本地原 intent 标为 FAILED/authorization_conflict，不覆写 Gateway 的另一条原审计。其他状态、格式错误、网络/SQL/Redis/activation 未知仍保持 PROCESSING，不能推定业务失败。

测试先行记录：新增 Java 四项真实 MySQL 测试初跑 2 pass/2 error，准确复现 dsh_disabled 与 license_invalid。Python 先增加确认重放和拒绝分型断言，SQLite 红灯；当次外部数据库环境未注入导致两项 setup error，此环境错误不算业务复现证据。补齐实现和隔离数据库配置后实跑通过。

最终证据：

- Java17/Maven3.9.9：`DshSeatOperationTerminalTest,DshSeatOperationTest,DshInternalControllerTest` **7 tests, failures=0, errors=0, skipped=0, BUILD SUCCESS**。新增四项采用真实独立 MySQL8，覆盖 stale version/tenant/capacity 的持久失败与重放、License 无效/过期/wrong-instance 恢复后原失败不变、变更 actor 拒绝、disabled 经真实 Controller/HMAC/DTO 路径返回持久 FAILED，以及 activation 未知无虚构审计、原 ID 可恢复执行。
- Python3.11：`test_admin_service.py test_gateway_client.py test_admin_api.py` **49 passed in 5.51s，无 warnings/skip/deselect**，涵盖 SQLite/真实独立 MySQL 下完整原 intent 重试、持久 FAILED 的四种 code、确认超时继续 PROCESSING、终态 lookup 与原 intent 冲突不可假成功、Gateway HTTP错误分型、真实 Redis DB11 HMAC nonce 共享。
- 新 Python 文件 Ruff check/format 通过，所改实现 arch-guard 无输出，两仓定点 diff --check 通过。日志 `/private/tmp/f062-python-saga.log` 与 `/private/tmp/f062-saga-green.log` 不含连接凭据。

验证边界：Java Controller 用 Spring MockServerHttpRequest 和真实 HMAC（该新增用例 nonce 使用内存测试替身），Python HTTP 分型使用 httpx MockTransport；数据库审计/幂等是真实 MySQL。该证据不等于两仓之间的 Nginx/TLS E2E，也未覆盖 DM8。未提交、推送或部署。
