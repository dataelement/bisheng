# Design: DSH 本地登录与部门额度

关联：[spec.md](./spec.md) · [tasks.md](./tasks.md) · [已确认评估](../../../docs/dsh-seat-removal-impact.md)。版本 v3.0.0，更新于 2026-10-20。

## 1. 目标与边界

DSH 直接使用 Python BiSheng 完成登录、会话和模型调用，退出商业席位控制；保留额度治理、租户隔离及完整模型审计。其他 Java SSO 等独立商业功能不迁入本模块。按用户后续授权提交并推送功能分支；部署与真实环境验收另行执行。

## 2. 关键约束

遵守 constitution C1–C8。保留桌面协议 0.5.0、PKCE S256、127.0.0.1 本机回调、自然人身份和当前租户检查。已有用量不可归零；新旧事件必须同时可读；数据库 DDL 与运营数据迁移分开。

## 3. 方案与选定

### 决策 1：认证状态本地化

备选是保留远程验席或将全部认证状态置于 Redis；选定 Redis 保存五分钟授权绑定和一次性 ticket，SQL 保存设备会话与 refresh 摘要。这样沿用现有基础设施，refresh 通过会话行锁串行轮换，重放提交整族撤销后返回错误。若会话 QPS 使 SQL 验证成为瓶颈，再评估有撤销一致性保证的缓存。

### 决策 2：独立用途签名

备选是复用 Web JWT 或 Gateway Secret；选定从平台持久化 JWT 主密钥派生独立用途的 HS256 密钥，固定新 kid `dsh-local-v1`。不读取 Gateway HMAC，也不接受旧 Gateway Token。今后需要跨独立服务验证或无中断密钥轮换时，再评估非对称 key ring。

### 决策 3：额度来源与历史

选定个人 enabled=true 优先，包括显式零；enabled=false 表示取消个人配置、恢复部门继承。多部门及祖先部门按同模型最大额度，成员按 tenant/user/model/month 独立累计。取消 ROLE 运行时来源，但离线运维迁移可显式读取退休 ROLE 来源，写入个人策略后停用 ROLE；已有个人额度保持原值。若产品引入部门共享池，需要另立计量契约。

### 决策 4：协议兼容和审计

标准路径和旧路径使用同一 handler，避免双会话真相。历史事件的 seat_id/grant_version 保留可空，不生成虚拟席位。正文采集、树结构、标题、审计密钥和后台归并任务继续运行。改变协议版本或缩小旧客户端范围时再移除别名。

## 4. 系统现状

### 4.1 数据流

`Desktop → /api/v1/dsh/authorizations → /desktop-login 浏览器确认 → ticket → /api/v1/dsh/token → 本地 SQL 会话 → /models、/chat/completions、/usage、/profile`。

刷新先用随机 refresh 的 SHA256 摘要定位最小租户/人员信息，再进入对应租户校验身份和锁定会话。退出与本人设备撤销只操作所属会话。浏览器管理接口继续使用平台 JWT 及原管理权限检查。

### 4.2 字段与 API

| 契约 | 约定 |
| --- | --- |
| POST authorizations | client_id=dsh-desktop、S256 challenge、state、loopback redirect；可选 device_name/client_version；有效期 300 秒 |
| POST token | identity_ticket + auth_id + code_verifier，或 refresh_token；两种请求不能混用 |
| POST logout | Bearer access 或 JSON refresh_token 二选一，成功 204；功能关闭后仍可撤销已有凭证 |
| 标准 / 旧路径 | 上述三接口分别位于 /api/v1/dsh 和 /api/dsh；旧别名由应用根路由注册 |
| 响应 | token_type、access_token、expires_in、refresh_token、refresh_expires_in、session_id、session_expires_at、user、tenant；无席位 |
| access JWT | iss/aud/sub/tenant_id/session_id/session_version/iat/exp/jti；默认 300 秒，最大 600 秒 |
| 设备会话 | dsh_session；默认绝对 30 天；dsh_refresh_token 仅保存摘要、代际、状态及过期时间 |
| UsageEvent / dsh_model_call | 席位和 grant_version 可空；历史正版本保持可读；其他用量、版本、epoch 字段维持原契约 |
| 个人策略 | enabled=true + monthly_token_limit=0 为显式拒绝；enabled=false 为恢复继承 |

### 4.3 模块职责

| 模块 | 职责 |
| --- | --- |
| local_auth.py / identity.py | 原生登录 HTTP、浏览器确认及已有能力协商 |
| authorization.py service / repository | PKCE、回调校验、授权绑定及原子 Redis 限流 |
| local_session.py service / repository / model | Token 签发、会话所有权、事务轮换和撤销；SQL 位于 Repository |
| token_keys.py / access.py | 用途派生、严格 Token 结构、当前身份和 SQL 状态验证 |
| admin_runtime / admin_policy / subject_policy | 本地授权、部门与个人额度；无占席回调 |
| worker/dsh | 保留计量和模型审计，退出 profile 同步与远程席位恢复 |
| Platform DshPage / DepartmentAccessTree | 删除商业入口和重授权操作，保留额度配置、用量和模型审计 |
| Desktop contract.js | 登录、换证和退出改用标准原生路径，审计协商保持原样 |

### 4.4 数据库基线与建表职责

数据库差异以 main `4218ba7c1` 为准，不以 109 曾部署的 feat/3.0.0 审计环境为准。main 的 83 个 Alembic 文件不变，新 revision `work110_dsh_local_sessions` 直接接在 main 的 `f065_dsh_install_policy_default_off` 后面，只修改已有调用表的两列可空性和版本约束。13 张审计表及 2 张原生会话表均为相对 main 新增的整表，由模型发现/建表流程创建完整定义。

不能将不同版本线的测试环境 head 作为导入旧迁移链的理由；这会重复携带审计 DDL，甚至带入无关的知识空间字段。109 采用归档原库、新库建立真实 main 基线后再升级的测试恢复流程，业务数据处理不进入 Alembic revision。

## 5. 已知坑

| 事实 | 忽略后的影响 | 处理 |
| --- | --- | --- |
| 重放撤销后立即在事务内抛错会回滚撤销 | 攻击者凭证仍可用 | Repository 返回错误，Service 在提交后抛错 |
| SQLModelSerializable.model_dump 将 datetime 转为字符串 | 会话过期判断类型错误 | Repository snapshot 保留原生 datetime |
| 模型可见范围包含 Root | 直接复用会话分页可能泄漏 Root 会话 | 会话 Repository 使用 strict_tenant_filter 由事件精确注入当前租户，另有所有权校验 |
| 旧别名挂到 v1 router 会叠加前缀 | 老客户端换证 404 | 应用层 compatibility_router |
| max(personal, role) 会抬高低个人额度 | 迁移改变业务授权 | role_migration 保留已配置个人值，含零额度 |
| 新事件没有商业身份 | 旧 worker 校验失败 | 全组件同批切换，保留可空历史列，禁止直接混跑或盲回滚 |

## 6. 对外契约与依赖

### 6.1 Outgoing

标准及旧认证接口供 Desktop 使用；/api/v1/dsh/profile、模型、审计、市场和工作台接口沿用既有路径。本地 Token 不能作为 Web JWT/PAT/SAK 使用。管理端不再调用 License/席位接口；旧商业命令返回 404。

### 6.2 Incoming

平台 JWT 主密钥持久化解析器提供跨副本一致主密钥；身份服务提供当前自然人、租户和账号有效性；Redis 提供授权 ticket/Lua 和既有额度；MySQL/DM 提供事务和会话行锁；既有模型与完整审计服务保持权限、密钥和存储契约。没有 Gateway 服务、数据库或 HMAC 依赖。

## 7. 验证与运维

实际结果和未完成的真实环境验收见 [validation.md](./validation.md)。发布步骤见 [deployment.md](./deployment.md)。单测、HTTP 进程内测试、客户端 mock 服务、真实数据库并发和实际 Electron 登录分别记录证据，不相互替代。

## 8. 后续边界

不删除历史审计和旧操作记录，不迁移 Gateway SSO，不重置已用量。过期本地会话和 refresh 摘要的运营清理应在绝对过期后执行；USED 摘要不能在有效期内提前清理，否则失去重放检测证据。

## 修订历史

- 2026-10-20：按用户确认的方案实施本地认证、去席位、个人优先及部门独立额度；记录序列化和精确租户范围两个实际发现，保持模型审计协议。
