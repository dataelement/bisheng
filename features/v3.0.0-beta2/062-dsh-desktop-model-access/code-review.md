> 2026-09-11 修订：本文保留历史实施记录。安装 ID、License 激活与副本 ACK 相关段落已被 [解绑修订](./installation-unbinding-revision.md) 和 [验证记录](./installation-unbinding-validation.md) 替代；不再执行旧激活命令。

# F062 两仓代码与交付审查

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

> 当前有效修订：用户确认每用户可配多个模型，各模型独立月额度；一期不做限流，配置使用有字段说明的类型对象。DM8 实机本轮暂缓。最新代码、契约变更及实际验证结果见 [逐模型修订验收](./model-quota-revision.md)。下文保留此前检查时点的证据，测试数量不与新版相加。

日期：2026-09-09。按仓库 `code-review` 七维度及 `task-review` 清单审查。范围包括工作区修改和全部新增未跟踪源码，不能仅用 `base...HEAD`（本轮未提交）冒充完整差异。

- BiSheng：`feat/3.0.0-beta2-pre`，基线 `v3.0.0-beta1-fix@02592397a3706252c201a05ce68b0640a47fd1ef`。
- Gateway：`feat/dsh-access`，基线 `main@75a74ff28ea95cba0938ff4912317cade2353337`。
- 审查结论（完成性复核更新）：**本地实现复核通过，完整发布验收未关闭**。逐项比对发现的 12 类实现遗漏已修复，见 completion-audit.md；DM8 实机本轮暂缓；目标旧二进制和实际部署验收仍缺证据。T114 保留为外部验收汇总门禁。本报告不授权提交、推送、合并或部署。

## 七维度核对

| 维度 | 核对对象与结论 |
|---|---|
| 边界条件 | 专用 DTO 严格类型、十进制 ID、UUID、PKCE S256/IPv4 loopback、可信剩余 TTL、JSON/SSE 终态、未知 usage 为 NULL、Unicode 原名及资料精确字节拆批均有针对测试。分页签名绑定实例/租户/筛选；恢复清单已消除一万条总数上限，保留明确分片/索引容量限制。 |
| 权限与认证 | 7 个 Desktop 接口使用独立凭证与真实 HTTP 错误；浏览器和管理使用普通 JWT/既有 PermissionService。Middleware 只分派精确 method/path，初始化无租户且不启用 bypass；验证后设定可信上下文并恢复。Root 共享模型通过原模型业务授权后与 DSH 范围取交集，普通 JWT/PAT/SAK 不作 DSH 回退。 |
| 并发与恢复 | MySQL 空实例 11 人抢 10 席、并发刷新、撤销版本、同 ID 不同 intent、实际用量 Lua 幂等、SQL 提交后 ACK 丢失、策略所有者/CAS、UNKNOWN 分原因冻结、多进程重试均有实际存储证据。MinIO 不可变版本与摘要承载审批；Redis 断连/主身份变化拒绝旧审批复用。DM8 和部署旧主隔离尚待真环境。 |
| 信息暴露 | DSH 日志不记录 Authorization、票据、refresh secret 或完整模型消息；HMAC 双向独立且绑定精确 body/path/instance/nonce；对外不返回内部地址。新 fixture 仅使用测试签名材料，临时存储凭据保持在仓库外受限文件。旧源码既有 License 密钥和配置告警不在本轮复制或扩大使用。 |
| 测试覆盖 | Python HTTP/领域/Runtime、真实 MySQL/Redis/MinIO、Java Spring/Mapper、Platform 交互与安全 live harness 均有执行证据。34 项 AC 追溯及实际 Desktop/Nginx/provider 缺口见 e2e-report；不将 mock、skip 或 SQL 编译当作真实联调/双库通过。 |
| 代码规范 | 新业务位于各自领域 Service/Repository，HTTP 薄接线；用户资料变更由原事务记录 outbox，Worker 恢复 tenant headers 后复原。Platform 复用请求封装与现有组件，三语言齐全，无新增库；旧 i18n suppression 由 prune 缩减。Ruff、前端质量检查及两仓 diff-check 已执行。 |
| 文档同步 | Design/HTML 从设计阶段更新为当前实现；26 端点、7 个冻结 Desktop 接口与 7 张时序图一致。补充配置、生产 CLI、首次审批初始化、完整恢复分片、管理错误与意图核验、外部 Desktop 交接及四类验收报告。 |

## 已修复问题

| 问题 | 修复与回归 |
|---|---|
| HTTP 200 管理业务错误在旧请求封装中丢失结构，无法识别确定版本冲突 | opt-in `preserveError` 在保留全局提示后附带 response；仅明确验证/冲突认定拒绝，不把超时认定失败。兼容测试覆盖旧调用行为和 HTTP 200/非 2xx 两支。 |
| REASSIGN 在 License 或开关前置拒绝时没有 Gateway 操作终态 | 受信且语义有效的拒绝写入原 intent 的 FAILED；以后 License 恢复也不改写原终态。激活/数据库/网络不确定仍 PROCESSING。 |
| 仅根据 operations/read 的同 ID 终态可能误认另一意图 | 使用原 actor/target/action/version 重放，由 Gateway 持久 payload_hash 确认；确认超时不假成功，严格命令 409 冲突结束本地原意图。 |
| 255 字符合法用户被 Java UTF-16 长度或窄检索列拒绝 | 按码点校验，容纳 lowercase 扩展；MySQL 510 字符、DM8 2040 字节。真实 MySQL 覆盖长汉字、emoji 和 dotted-I。 |
| 资料只按 100 条分批仍可超过 64 KiB | 同时按确切 UTF-8 JSON 字节上限拆批；单项过大持久化失败并保留审计。 |
| 配额恢复存在 10,000 请求总上限 | 增加连续恢复分片与摘要校验，SQL/Redis 每批 500 条；10,001 请求真实恢复和缺片拒绝通过。 |
| 流在首个读取前断线可能不结算 | 响应生命周期 finally 关闭 PreparedStream；每个流读取/关闭独立恢复 trace/tenant；未知计量冻结且不发送 DONE。 |
| 初始账本无审批与初始策略互相等待 | 初次策略先持久化 version=0 意图，再由空历史证明生成审批；同 operation_id 续跑 0→1，不手写 SQL/READY。 |

## 验证证据

- Gateway 最终命令选择 `Dsh*Test,LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest`、排除 `scale` 后执行 `package`：**48 tests，0 failure/error/skip，BUILD SUCCESS**；此前真实 50,000 席位 scale 用例另有 1 次通过。未运行加载旧默认环境的无关 demo/application-context 测试。
- Platform 最终 12 个测试文件 **42 tests passed**；仓库前端 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n` 均 exit 0。当前 bs-ui Input 的既有 React `jsx` 属性告警未修改共享样式。
- Python 联合初跑 **232 passed，14 setup errors**；错误是安全 fixture 拒绝错误测试库/已有表，没有放宽为清空已有表。对应 5 文件改用显式隔离空库补跑 **22 passed in 17.20s**，覆盖上述 14 个 setup 阻塞；MySQL 8.0.46，测试库前后均为空。22 项与初跑已有通过项存在重叠，不简单相加。详见 database-acceptance。新增 Saga 专项 **49 passed**；它与联合套件有重叠，不相加为总数。
- 真实 MinIO **4 passed**；七个独立 Python 进程故障验收 **1 passed**。E2E harness 安全门 **3 passed**，真实部署用例 **7 skipped**，详见 e2e-report。
- Python DSH/Worker/测试/资料 Repository/迁移/错误码的 `ruff check` 通过；Architecture Guard 无新增 VIOLATION，既有配置与显式假密码 fixture 的 WARNING 单独核对，不作为生产凭据泄漏结论。两仓 `git diff --check` 通过。
- 实际全局 Python Router 导入核对 15 条 DSH 端点，实际 Celery 注册 7 个任务。此检查不等于已经运行部署队列或完成 Nginx 传输验证。

## 完成性复核的最终增量

12 类遗漏均有源码修复与针对回归：最后调用和模型候选/目标租户、明确策略拒绝、成功操作回读和前后状态审计、Gateway invalid_grant/退出期限/Unicode 长度，以及配额恢复顺序/不确定结算/容量与清理/后台处理。七个 Desktop 接口的既定字段、状态和时序不变；管理响应补充已写回 Design/HTML。

- 管理策略/视图/API：51 passed；管理操作/视图/API：35 passed。两个真实 MySQL/Redis 分组存在重叠，不相加。
- 配额/对账/Worker/运行时/跨进程联合：62 passed in 49.47s，真实 Redis/MySQL/MinIO，无 skip；配置/基础契约：12 passed in 5.00s。
- 独占 Redis 实际 AOF 重启和关闭旧主后晋升：另 2 passed in 8.93s。新主拒绝旧审批，完整 MinIO 证据和 SQL epoch CAS 后新审批才可开放；不替代部署网络隔离和负载验收。
- Ruff、前端三项质量门禁及两仓 diff-check 通过。Architecture Guard 147 个修改/新增源文件、0 VIOLATION、2 条已核对 WARNING。上节早期 Python 232/22/49 等分组为历史证据，不累计为当前全套总数。

## 尚未关闭的发布门禁

1. 实际 HTTPS Nginx→Gateway→Python、DSH Desktop 版本/负责人、可计量供应商及 Agent tools/SSE 联调。按用户允许跳过环境阻塞的 E2E，保留可运行 harness 和现场清单。
2. DM8 Linux 真库迁移、事务/锁、分页与数值/Unicode 边界。MySQL 通过不证明 DM8 通过。
3. 厂商发行工具、目标旧 Gateway 二进制与授权密文样本的双向兼容，包括 RSA 分块长度。解码输入回归不代替此证据。
4. 部署 Redis 主切换、旧主隔离/AOF 完整性及两副本 50 并发/1000 RPS 目标。已记录本地延迟样本，未称达到生产 SLA。

上述事项分别对应 T007/T010/T028/T029/T110/T111/T112/T113 的原完成条件；代码已落地的任务也不因此勾成完整发布验收通过。无需为等待外部环境继续重复本地绿测。部署步骤和保留席位/审计/用量的回退流程见 rollout.md。
