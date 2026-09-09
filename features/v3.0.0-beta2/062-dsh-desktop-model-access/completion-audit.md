# F062 完成性复核（2026-09-09）

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

> 当前有效修订：用户确认每用户可配多个模型，各模型独立月额度；一期不做限流，配置使用有字段说明的类型对象。DM8 实机本轮暂缓。最新代码、契约变更及实际验证结果见 [逐模型修订验收](./model-quota-revision.md)。下文保留此前检查时点的证据，测试数量不与新版相加。

本轮按 Spec 34 项 AC、冻结客户端 7 接口和 Tasks 原完成条件逐项核对实际源码。此前本地测试通过不足以证明全部需求已实现。本轮列出的 12 类实现遗漏现已修复并完成针对回归；T114 的外部验收汇总仍保持未关闭。没有提交、推送或部署。

## 实现遗漏与修复证据

| 发现 | 影响 | 当前工作与验证 |
|---|---|---|
| AC26 模型与额度视图没有最后调用 | 无法按需求查看最近模型调用结果 | GET policy 新增脱敏 SQL 最新调用、明确 persisted/unavailable；UI 已补，空历史/未知用量不显示成零 |
| 管理候选模型来自通用模型列表，无能力门禁/目标租户交集 | 选择项可能无法保存，全局管理员可能漏见目标租户模型 | GET policy 按 verified capabilities 与目标租户模型业务强读返回 available_models；UI 使用这一受管列表，依赖不可用阻止保存 |
| simple 用户选择器不返回 tenant_id，UI 猜测登录租户 | Root 管理子租户时读写错误目标 | GET policy 省略未确定 tenant，由已授权后端定位；PUT 使用响应 tenant_id，UI 联动回归覆盖 |
| 策略权限/模型校验抛明确拒绝，被兜底 PROCESSING | 未提交策略可能长期冻结 | 捕获明确 403/模型拒绝为持久 FAILED，只清本操作冻结；依赖错误继续原 ID 恢复。管理投影/策略/API 联合 51 项通过（真实 MySQL/Redis） |
| 席位操作成功未回读列表/License | 后续操作可能使用旧 grant_version | 成功 operation_id 仅触发一次 revision，重复终态不反复刷新；独立 UI 回归通过 |
| 管理操作没展示已有 phase，席位前后审计缺 state | 处理中阶段与实际状态变化不够清楚 | UI 展示本地化阶段；成功命令基于 Gateway 已核验的固定状态转换补充 before/after state；管理服务/投影/API 联合 35 项通过（真实 MySQL）；UI 阶段回归通过 |
| Python 失效/重放票据错误统一变成 Gateway 503 | 客户端不能按冻结 invalid_grant 分支重开事务 | 仅可信 redeem 的严格 400 invalid_grant 映射为相同客户端错误；其他不确定仍 503 |
| 过期 refresh 或绝对过期 session 仍可 logout 204 | 与冻结过期凭证 401 不一致 | 两种期限均验证；有效期内已撤销会话仍允许幂等退出 |
| device_name 接受 0/101–128 字符，Unicode 按 UTF-16 限长 | 与冻结 1–100 字符不一致 | 按 Unicode code point 校验；上述 Gateway 三修复针对测试 5 项通过；最终 Gateway 48 项测试及 package 通过 |
| 恢复 Lua 在 SQL epoch CAS 前置 READY | 其他副本可能提前放行或以不一致 epoch 写事件 | 改为 FROZEN receipt→SQL CAS→owner/digest/epoch/version CAS READY；真实跨副本回归已通过 |
| 不确定结算仍留 RUNNING，其他副本可继续新准入 | 未知消费不能及时阻断 | 独立控制连接仅同主精确确认或持久 UNKNOWN/阻断，不能自动恢复准入；不同主不采信终态。首批配额 5 项真实存储回归通过 |
| 配额容量高水位、已投影保留清理、后台续批/扫描范围未完整实现 | 高频调用下持续积压、内存增长和重复全库扫描 | 已补参数化背压、RUNNING 索引、有界续批/租约与严格 ACK/SQL/保留期清理；恢复重算保留事件数以保护旧 PEL。配额联合 62 项通过 |

前端新增目标租户/候选/调用摘要 3 项、成功回读 1 项及原管理 3 项分别执行通过；集合有重叠，不相加为总数。最终范围和结果见下节；不同组有重叠，不合计。

## 外部验收仍缺的证据

- DM8 真库本轮按用户确认暂缓，已完成双侧 SQL 兼容性审查；不再作为本轮开发阻塞，已有 MySQL 8 结果不等价于 DM8。
- 目标旧 Gateway 已发行 artifact、发行工具版本与授权旧/新密文样本。当前项目仅找到本轮生成的 target JAR；git tags 不能确定用户目标旧二进制，不能用新编译 main 代替。
- 实际 HTTPS Nginx、Desktop、SSO、模型供应商与部署故障/负载验收。用户允许环境阻塞的 E2E 暂跳过；脚本与现场清单保留。

已向用户询问现有测试配置/安装包/授权样本的受限文件路径；未请求粘贴凭据或 License 内容。独立实现修复继续进行，不等待该信息。

## 本轮已完成的联合检查

- Gateway：`Dsh*Test,LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest` 排除 scale 执行 package，48 passed，0 failure/error/skip，BUILD SUCCESS。
- Platform：12 个相关文件共 42 passed；lint、typecheck、check-i18n 全部通过。
- Python 管理策略/视图/API 51 passed；管理操作/视图/API 35 passed。两组有重叠，不相加。
- 独占 Redis AOF 重启和关闭旧主后晋升副本的两项真实故障测试通过；这不等于部署环境的主切换验收。配额/对账/Worker/跨进程联合 62 passed（真实 Redis/MySQL/MinIO），配置/基础契约另 12 passed；精确范围见 python-quota-progress.md。

- 最终 Ruff 通过；Architecture Guard 扫描 147 个修改/新增源文件，0 VIOLATION，2 条已核对的既有配置/假密码 fixture WARNING；两仓 diff-check 通过。HTML 锚点/本地链接与契约 JSON 检查通过，客户端仍为七张时序图。

结论：本轮发现的实现缺口已关闭，没有以环境缺失掩盖未实现项；完整发布验收仍受下述外部条件限制。T114 保留未勾选用于汇总这些门禁，不再表示已知源码遗漏仍在修复。
