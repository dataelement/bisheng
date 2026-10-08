# Release Contract — v3.0.0-beta2

> 本文件登记 beta2 新增 Feature 的领域归属与跨功能约束。既有能力沿用
> [beta1 契约](../v3.0.0-beta1/release-contract.md)；全局架构规则以
> [constitution.md](../../docs/constitution.md) 为准。
> F062 两仓实现已落地；用户确认的逐模型修订对应客户端契约 0.2.0，完整发布验收另记。

## 表 1：领域对象归属

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| DSH License entitlement / activation | F062-dsh-desktop-model-access | Gateway 项目内授权能力扩展，复用当前 License 验签解析结果，不新增配置副本表；管理 DSH capability、实例绑定与席位容量；不改变现有其他商业能力的授权语义 |
| DSH SeatAssignment / Session | F062-dsh-desktop-model-access | Gateway DSH 模块持有固定席位、授权代次、登录会话与刷新凭证真相；BiSheng 只引用 |
| DSH UserPolicy | F062-dsh-desktop-model-access | BiSheng 一条用户策略保存强类型逐模型配置，每个用户/模型独立月 token 上限，不拥有或复制既有模型供应商配置 |
| DSH MonthlyUsage / ModelCall / AdminOperation | F062-dsh-desktop-model-access | BiSheng 持有已累计用量准入与实际用量入账、调用记录、策略变更不可变审计、可靠用量补记和跨服务管理操作进度；月汇总按用户、模型、月份分行，明细保留 model_id，Redis 实时执行当前用户与所选模型的独立月额度，SQL 为批量投影 |

User、Tenant、LLMServer、LLMModel、PermissionActor 和 F053 ApiCredential 继续由原模块持有；F062 通过原模块业务入口读取、鉴权或调用。User 拟增 dsh_profile_version，由原用户/主部门业务事务递增并在同事务通过 DSH 服务登记 SYNC_PROFILE；不迁移用户领域所有权，不改变 F012/F048 权限及回滚语义。

## 表 2：跨 Feature 不变量

本版增量使用 `B2-INV-N` 标识，避免与 beta1 既有 INV 编号冲突。

| ID | 不变量 | 来源 |
|----|--------|------|
| B2-INV-1 | 席位按安装实例与稳定自然人标识计数；相同用户多设备不重复占席。只有管理员明确撤销才释放，已撤销用户不得通过登录自动重新占席 | F062 AC-05～12 |
| B2-INV-2 | DSH 凭证由 Gateway DSH 模块签发、管理；不能与常规 JWT、PAT、SAK 互换。DSH 席位撤销不修改常规 JWT 版本或 F053 凭证 | F062 AC-13～17 |
| B2-INV-3 | DSH 只调用既有模型业务确认可访问且管理员开放的模型；根租户共享仍遵守既有模型共享契约 | F062 AC-18～21 |
| B2-INV-4 | 启用 DSH 依赖 Gateway 内的授权模块；缺失、失效只拒绝 DSH 能力，不给常规 BiSheng 业务增加启动或逐请求依赖 | F062 AC-31～32 |
| B2-INV-5 | 月用量按租户、用户、模型、月份分行，逐用户/模型独立执行月额度，用户汇总仅用于展示、额度不可互借；席位释放、重分配、模型移除或设备登录不重置用量；Redis 按已累计实际用量检查，达限拒绝新请求，在途允许超额并如实入账，不预占；实际累计与 SQL 批量投影幂等，无法确认配额时失败关闭；UNKNOWN 按用户跨月阻断，可靠逐请求补记幂等且只移除对应原因，证据不足不强制解冻 | F062 AC-22～24、34 |
| B2-INV-6 | DSH 客户端只配置 Nginx 公开 origin；全部 API 经 Gateway，版本 API 转发到 BiSheng、其余由 Gateway 自有接口承载，不要求第二公开地址 | F062 client-api.md §2；2026-09-09 用户确认 |
| B2-INV-7 | 客户端当前 0.2.0 接口与时序冻结为开发基线（原 0.1.0 的逐模型修订已记录）；任何线协议变更须更新设计及客户端文档、记录版本差异并同步客户端确认和联调，不能仅修改服务端 | F062 design.md §6.0；2026-09-09 用户要求 |
| B2-INV-8 | 新 Gateway 保留旧 License 解码和既有商业授权语义；可选 DSH 签名扩展独立验权，缺失/失效不能把旧能力连带置为过期，旧 pro 不代表 DSH 无限席位；旧商业期满与 DSH 到期独立判断，外层无法解析则 DSH 拒绝 | F062 design.md §4.5.4；2026-09-09 用户要求 |

## 表 3：Feature 依赖

| Feature | 依赖 | 边界 |
|---------|------|------|
| F062 | BiSheng 既有用户登录、租户、模型管理与 LLMService | 身份确认和模型调用使用原业务入口 |
| F062 | Gateway 项目内 License / DSH 授权模块 | 模块开发随 Gateway 部署；新增双向服务端信任配置 |
| F062 | F048 权限应用层、现有管理端鉴权 | 复用统一业务授权入口，不新增第二权限判定系统 |
| F062 | F053 作为凭证隔离回归对象 | 不依赖其 PAT/SAK 校验器或数据表；具体鉴权生命周期独立 |

## 已分配模块编码

2026-09-09 按当前源码扫描分配 F062 模块 **261**，已实现 `26101–26130`，见 `src/backend/bisheng/common/errcode/dsh.py`。覆盖冻结客户端错误与内部管理 operation_in_progress/operation_conflict；既有 **260** 仍保留给 F053。客户端字符串码及 HTTP 不变，不将 MMMEE 当 HTTP 状态。

## 本轮内部契约补充

2026-09-09：identity/redeem 与 identity/check 共用可信 DshIdentitySnapshot；BiSheng 管理 policy 保存使用 operation_id，操作查询返回审计与 phase；UPDATE_POLICY / RECONCILE_USAGE 在 BiSheng 分派。以上由两仓开发者按 Design §4.5.5、§4.7.4、§6.1 同步实现，26 个 HTTP 接口及 8 张表数量不变；客户端 0.1.0 不新增调用。未来线协议变化仍执行 B2-INV-7，不表示已经联系客户端。

## 变更历史

| 日期 | 内容 | 影响范围 |
|------|------|----------|
| 2026-09-09 | 修复 SDD 审计、共享、双授权、身份 DTO 和 UNKNOWN 恢复问题；客户端 0.1.0 保持冻结 | F062 |
| 2026-09-09 | 冻结客户端 0.1.0 契约并要求后续同步客户端；Gateway 开发分支 feat/dsh-access 基于 main，新增旧 License 兼容约束 | F062 |
| 2026-09-09 | 确认官方 DSH 链路商业控制边界及单 Nginx 入口，补充客户端开发与联调契约 | F062 |
| 2026-09-08 | 取消额度预占；按实际已用量达限拦截新请求，在途并发允许超额，实际入账与批量投影保留 | F062 |
| 2026-09-08 | 万级席位查询、身份检索投影及独立登录视图；Redis 原子额度与 Stream 批量 SQL 投影，故障关闭 | F062 |
| 2026-09-08 | F062 表结构精简至 8 张，License 复用既有解析，用户模型范围与月总限额合表；保留用量汇总和请求明细 | F062 |
| 2026-09-07 | 建立 beta2 契约，迁入 F062 并登记设计草案的领域归属、部署边界与依赖 | F062 |
| 2026-09-09 | 用户确认逐用户/模型独立月额度，一期不支持限流；主配置对象化；DM8 真库本轮暂缓，以无手写业务 SQL 和兼容性审查替代本轮实测门禁 | F062 |

当前客户端版本升级 0.1.0 → 0.2.0：逐模型 usage 查询与额度汇总语义变化已写入契约和时序图，客户端接收/适配确认仍待完成。原 0.1.0 JSON 留作历史差异，不提供旧共享池运行时。

## F062 部署简化（2026-09-09，当前有效）

以 [deployment-simplification.md](./062-dsh-desktop-model-access/deployment-simplification.md) 为准：复用用户同步 HMAC 和毕昇 Redis；DSH token 固定 HS256，ticket 保持一次性兑换；取消模型部署白名单，用户模型及额度由界面授权；月度默认 Asia/Shanghai。客户端契约 0.4.0 保留现有 HTTP 路径与时序，旧 Token 需重新登录。License 发行机制独立不变。
