# F062：License 与安装标识解绑修订

日期：2026-09-11。状态：三项目代码和本地回归已完成，未部署；环境切换与真实客户端联调待执行。验证结果见 [实施记录](./installation-unbinding-validation.md)。

## 1. 已确认边界

- 保留 License 生成器的指纹输入与外层 `finger` 字段。本期不校验机器指纹，不新增匹配开关；签名仍保护 finger 内容不被篡改。
- 完整移除 `installation_id`，不替换为另一个手填环境 ID；删除数据查询、唯一键、存储路径及内部协议对它的依赖。
- DSH License 使用 schema 2，只接受新格式，不兼容未发布的 schema 1 测试授权。无 DSH 扩展的旧 Gateway/SSO License 兼容要求保持。
- 允许多个独立环境使用同一份 License，各自控制席位总数；不做跨环境累计或在线授权中心。
- 公共客户端协议继续 0.5.0，详见 [客户端兼容说明](./client-installation-unbinding-compatibility.md)。

## 2. 数据和部署边界

一个毕昇环境对应一套相互配对的毕昇/Gateway 数据库及 Redis 存储空间。K8s Pod、节点、域名和 IP 不是数据主键，也不是授权边界。同环境多副本共享存储和既有用户同步 Secret；独立环境通过数据库、Redis 实例/DB 或现有基础设施隔离，不在业务表中增加环境字段。当前 Redis Cluster 尚未实现，不能依赖切换 Redis DB 来声称支持 Cluster。

若两个部署故意连接同一套数据库与 Redis，它们属于同一环境、共用一份席位池；不能在同一存储空间套用两个独立配额。同一 License 可复用不表示认证 Secret 也应跨环境复用，各独立环境应使用各自的用户同步 Secret。

| 对象 | 目标设计 |
|---|---|
| Gateway `gt_dsh_seat` | 删除 installation_id；主键 seat_id 保留，唯一键改为 user_id；tenant_id 保留用于归属及权限校验 |
| Gateway 会话与刷新记录 | 保留 session_id、seat_id 关联；删除 JOIN/查询中的安装 ID 条件，不改变撤销及刷新轮换语义 |
| Gateway `gt_dsh_operation` | 删除 installation_id；operation_id 在当前数据库全局唯一，保留动作、actor、目标、预期版本及 payload 摘要约束 |
| 毕昇模型额度、调用明细、月用量 | 既有表已按租户/用户/模型保存，不重建、不另加明细表 |
| Redis | 授权、票据、Nonce 使用 `{dsh}:...`；额度账本原有 `dsh_quota:{tenant:user}:...` 已无安装标识，保留前缀及用量；不得用 License ID、指纹或安装标识分区 |
| 对象存储恢复证据 | 固定 DSH 业务目录，保留 run_id/epoch、证据摘要和审批约束；移除 installation_id 字段及路径分段，不取消丢账恢复校验 |
| 模型遥测 | app_type 保持 DSH_DESKTOP，app_id 固定为 dsh，不从 License 或安装标识生成 |

全环境 ASSIGNED 席位数由同一数据库事务控制，不能在各 Pod 内独立计数。删除索引前缀后重新验证 MySQL SERIALIZABLE 的并发行为和 DM 表锁路径；DM 不要求本轮实机测试，但建表与业务写法必须兼容。毕昇侧不增加手写业务 SQL。

更换 License 只更新能力、有效期和上限。授权 jti/digest 可保留用于状态展示和审计，不能作为业务数据归属、查询过滤条件或 Redis 主键前缀。降配超限继续按现设计阻断并由管理员处理，不自动释放席位。

## 3. 服务端内部协议：配套切换，不双栈兼容

公开客户端不持有 HMAC Secret；双方仍使用现有用户同步 Secret，原用户同步协议不变。

- HKDF-SHA256：salt=UTF-8("bisheng-dsh-v1")，info=UTF-8(purpose)，输出 32 字节。purpose 保持 bisheng-to-gateway-v1、gateway-to-bisheng-v1、dsh-access-v1；删除原 info 中的安装 ID 和冒号。服务请求使用派生结果的小写 hex UTF-8，access token 使用原始 32 字节结果。
- 内部签名 canonical 为 `method + "\n" + path + "\n" + SHA256(body).hexdigest() + "\n" + key_id + "\n" + timestamp + "\n" + nonce`，末尾无换行；保留现有路径规范化、时间窗及 Nonce 原子防重放。
- 删除 `X-DSH-Installation-Id`，保留 X-DSH-Key-Id、X-DSH-Timestamp、X-DSH-Nonce、X-DSH-Signature；信任仅从固定方向的配置密钥建立。
- access token 固定 HS256、typ=bisheng-dsh-access+jwt、kid=dsh-access-v1、iss=bisheng-dsh、aud=bisheng-dsh-model；声明保留 iss/aud/sub/tenant_id/seat_id/session_id/grant_version/iat/exp/jti，删除 installation_id。
- 保留 PKCE S256、随机短期 ticket、原子一次性消费、用户和租户强校验、在线席位/会话校验；不增加 ticket 签名格式。

| 内部接口/对象 | 变化 |
|---|---|
| `POST /api/v1/internal/dsh/identity/check` | 请求移除 installation_id，保留 tenant_id、user_id |
| identity/redeem、identity/check 的 DshIdentitySnapshot | 响应移除 installation_id，其余主体及显示字段保持 |
| `POST /api/internal/dsh/authorizations/resolve` | 响应删除 `instance`，保留 challenge、redirect_uri、client_id、state、expires_in |
| introspect、席位操作、管理读取、本人会话、资料投影 | 同步公共 HMAC 签名变化，删除内部安装 ID 校验；保留 actor、tenant、user、版本、幂等与会话权限检查 |
| DshEntitlement 内部对象 | 删除 installationId；保留 License 状态、jti、有效期、席位上限和 digest |

Gateway 不再依赖 installation-id 或 replica-id 初始化组件。退出所需的 Mapper、仓储和凭证验证组件可以初始化；新登录、Token 签发、模型验权和本人详情仍检查 DSH 开关。关闭后保留原有会话退出行为，本地路由回归已覆盖。

按用户最新确认，删除 License 激活服务、激活命令、共享激活状态及副本心跳/ACK。每个 Gateway 依据当前加载的有效 License 处理请求，不等待其他副本；席位总数仍在共享数据库事务内统计。滚动更新期间允许上限短暂不一致，例如 10 降至 2 时，尚未更新的副本仍可能按 10 分配，新副本按 2 拒绝新占席；更新全部完成后统一应用新上限，不自动删除已有席位。额度账本恢复审批不属于 License 副本协调，继续保留。

两端内部协议需要配套切换，不能混跑旧 HMAC 格式。
## 4. 测试环境切换

1. 记录代码/镜像和数据库版本，备份 DSH 表、Redis 相关状态、恢复证据及原 License；只操作独立 DSH 环境。
2. 暂停 DSH 新准入，等待在途请求结束、用量 Stream 投影及未完成管理操作收敛。无法完成的记录先核对，不把旧幂等摘要改成新摘要或删除未完成用量。
3. 检查旧安装标识下是否存在重复 user_id、冲突席位/会话或重复幂等动作。若多套测试数据曾混用，先确认归属，不能简单删除字段合并。
4. 删除部署配置中的 installation_id / installation-id 和 replica-id；Gateway 严格拒绝未知 DSH 配置，不能保留旧字段。直接更新建表脚本及目标表结构、索引；保持 seat_id、user_id、模型额度、历史用量及审计。Redis 账本、投影位置、去重/幂等状态迁移并核对数量和金额无关的 Token 合计，不将已有用量归零。
5. 清退旧 access/refresh 对应会话及未完成授权事务，保留会话历史和席位；新登录可使用已分配席位。本次不兼容旧测试凭证、旧 HMAC 或旧 DSH License。
6. 生成 schema 2 测试 License，配套切换 Gateway 与毕昇 API/Worker；验证本地 License 和共享席位计数，核对额度账本及 Redis 恢复证据，再恢复准入。毕昇部署按用户安排执行。

回滚应在暂停 DSH 后恢复匹配的旧代码、表结构、Redis 状态和 License。新环境已有调用后不能直接覆盖旧备份，须先保全并核对新用量和操作记录。

## 5. 验收范围（本地结果见实施记录，部署联调待执行）

- 同一 License、不同指纹环境均可使用；改动已签名 finger 仍验签/内容绑定失败；过期、非法签名、schema 1 仍拒绝 DSH。
- 多副本并发首次登录不超总席位；同用户多设备只占一席；跨租户不可读取他人会话或用量。
- 替换 License、Pod、节点后数据持续可见；同环境 Secret 和共享存储未变时，本次切换之后的新会话可跨副本继续使用。
- Java/Python 新 HMAC 双向向量一致；修改方法、路径、正文、时间戳和重放 Nonce 仍拒绝。
- 旧 SSO trial/pro、用户同步、非 DSH 模型调用不受影响；不新增部门同步、限流功能或 License 管理界面。
- 现有客户端重新登录、刷新、模型目录、JSON/SSE、缓存 Token 明细与登出通过；公共 contract_version 仍为 0.5.0。

本设计不能用文档自检替代上述运行验收；实施、构建、环境修改和客户端联调结果分别记录。
