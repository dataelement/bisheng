# F008 规格审查

日期：2026-11-06。审查阶段：`sdd-review spec`。初轮新需求覆盖自审为 LGTM；用户要求追加跨 Vibe 合同审查后发现承接缺口，已修订并经三路独立复核 **LGTM**，详见 [vibe-compatibility-review.md](./vibe-compatibility-review.md)。规格已于 2026-11-10 获用户确认。

依据：`spec.md`、已确认的 `discovery.md`、本版本及继承的 release contract、`docs/constitution.md`、后端模块与权限架构，以及 `.claude/skills/sdd-review/references/spec-checklist.md`。跨 Vibe 追加审查涵盖 F054/F055/F056/F086/F059/F115/F119、代码沙箱与端点合同，并使用 `approval-module` 技能核对发布必审边界。

| 检查项 | 结果 | 依据 |
| --- | --- | --- |
| 用户确认需求覆盖 | PASS | AC-01–07 覆盖取消强制诊断/24h及保留实际保护；AC-08–26 覆盖标准交付要求 |
| 边界和失败场景 | PASS | §3，非法配置、外部依赖、历史未知写入者、升级及 RWO 拓扑 |
| 范围排除 | PASS | §1，明确代码交付，不构建镜像/部署线上/迁移122数据 |
| AC 标识与可追溯性 | PASS | AC-01–26 连续且唯一 |
| 可测试性 | PASS | 诊断状态与业务行为分别观察；模板矩阵与真实安装证据分开 |
| EARS 句式 | PASS | 所有 AC 使用 WHEN/WHERE/WHILE/THE SYSTEM SHALL |
| 错误码归属 | PASS | 不新增或复用未经确认的错误码，保留实际错误行为 |
| 领域归属 | PASS | F008 扩展交付与 F059 合同；不接管用户、业务授权或外部 release |
| 架构与版本不变量 | PASS | 保留 C1/C2/C3/C4/C8；release contract 明确 F059 强制诊断前提在本版本的增量替代 |
| 纯 What | PASS | 策略字段、初始化进程和具体代码结构留给设计；规格仅约束外部交付与可观察行为 |

此结论不代表实现或集群验收通过。镜像兼容清单、生产首次授权初始化入口、部署策略可信来源和历史 UID 保护仍须在设计中落地；不能以默认 ready、假报告、dev 环境或伪造管理员替代。

独立复核修正：初稿 AC-06 对“实际隔离”的覆盖不够显式；已补入入口/出站网络隔离、最小 RBAC 和禁止 exec/attach/portforward。该修正落实已确认范围，不恢复环境实测或报告门槛。
