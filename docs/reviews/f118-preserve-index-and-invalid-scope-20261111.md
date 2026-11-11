# F118 原索引保留及旧跨租户模型引用兼容审查

基线 `ae50f19519`，2026-11-11；范围为 14 个内部生产文件及相关 native 测试、已确认合同增量。用户已明确保留原索引/物理数据，并确认原跨租户模型配置保留为失效、运行/发布拒绝。此审查不代表整个 F118 或 116 升级已完成。

| 维度 | 结论 | 核对证据 |
| --- | --- | --- |
| Boundary Conditions | PASS | 无托管 SQL 文件/目录才允许不兼容旧索引的保留证明；真实 schema/count/绑定保持，缺失或伪造证明、重复资源、跨租户及增添文件/目录拒绝。 |
| Permission & Auth | PASS | 外租户事实来自原可信来源/版本/目标绑定及真实模型/服务商；只签发原项保留/移除资格，详情 invalid_scope、运行/发布 require_source_valid 拒绝；复制、新版本、新槽位及 owner_query 拒绝。外租户服务商不参与 Root sharing。 |
| Concurrency Safety | PASS | 冻结图完整校验后，M3 首次写入前跨所有相关租户检查原索引绑定和实时零文件集，续跑执行相同检查；引用沿用原 native transaction、prelock 证明和来源修订锁协议，不跨事务签发收据。 |
| Information Leakage | PASS | 读取端外租户查询仅投影模型、服务商的 ID/归属；不返回名称、配置或凭据。真实模型存在不伪装为 target_missing；无新 HTTP 字段、接口或权限。 |
| Test Coverage | PASS_WITH_WARNINGS | 组合选集 2,041 passed、1 failed；该频道配额/角色策略加载的 no-network 失败在修改前基线单项复现。最终修改后的关键选集 72 passed，含零文件证明、M3/续跑漂移拒绝、真实 M2/M3/M4 跨租户失效计数闭合及同步/异步读取与原槽位写入。 |
| Code Style | PASS | 19 个变更 Python 文件 Ruff format/check 通过，架构 guard 无输出，git diff --check 通过；通用 SQLAlchemy 查询、无 DDL 或新依赖。 |
| Docs Sync | PASS | spec AC-56/93 与用户确认例外一致；design、release-contract、tasks 和八列 QA TC-KSU-146–150 同步。保留原证书形状兼容，新增 invalid_scope_count 严格计数且参与闭合。 |

实际镜像中 13 个既有文件与发布基线 SHA256 完全相同，新文件原不存在；完整原件及候选哈希保留到现场。M2 原物理盘点标志不改为兼容，不能把物理残留向量伪造为 SQL 文件、授权或索引写入资格。保留旧索引不证明其旧 schema 已支持未来新上传，需按原资源/索引处理流程另行核实。

无新增 HIGH/MEDIUM 实现缺陷。真实 DM8 锁调度及完整 F118 API/UI E2E 未在本机验证；本增量为内部迁移和引用状态，无新增页面/接口，不能以 native M4 测试替代现场完整停服升级。部署、原绑定/物理事实核对及其他完整性阻塞另见 116 运维报告。

Overall: PASS_WITH_WARNINGS
