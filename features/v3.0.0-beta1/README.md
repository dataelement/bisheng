# v3.0.0-beta1 Feature 索引

**版本目标**：交付 3.0.0-beta1 功能体验优化、灵思引用溯源、ReBAC 权限模型、
授权关系、权限继承和历史数据升级，以及平台级信息源订阅与新增文章同步可靠性改造。

**版本契约**：[release-contract.md](./release-contract.md)

---

## Feature 列表

| # | Feature | 优先级 | 状态 | 依赖 |
|---|---------|--------|------|------|
| F043 | [report-node-optimization](./043-report-node-optimization/) | P1 | Spec 已存在 | 无 |
| F044 | [model-status-manual-verify](./044-model-status-manual-verify/) | P1 | Spec 已存在 | 无 |
| F045 | [chat-image-preview](./045-chat-image-preview/) | P1 | Spec 已存在 | 无 |
| F046 | [channel-source-link-failure-ux](./046-channel-source-link-failure-ux/) | P1 | Spec 已存在 | 无 |
| F047 | [linsight-citation-traceability](./047-linsight-citation-traceability/) | P2 | Spec、Design 已存在 | F035, F029 |
| F048 | [rebac-permission-model-grants](./048-rebac-permission-model-grants/) | P0 | ✅ 功能与迁移脚本开发完成；本地 E2E 经用户确认不执行 | F004, F006, F007, F008, F018, F027, F036, F040 |
| F049 | [knowledge-space-children-read-optimization](./049-knowledge-space-children-read-optimization/) | P1 | Spec 已存在 | F027, F040, F048 |
| F050 | [unified-permission-settings](./050-unified-permission-settings/) | P0 | Spec、Design 已确认，Tasks 已拆解，实现中 | v2.6.0 F044, F048 |
| F060 | [information-source-subscription-reconciliation](./060-information-source-subscription-reconciliation/) | P1 | ✅ 本地开发与评审完成；真实依赖 E2E、DM8 待执行 | v2.6.0 F031、Information 协议 v1.1 |

---

## 配套说明

- [产品可读：Authorization Model 接管与数据迁移说明](./048-rebac-permission-model-grants/product-authorization-model-and-migration-guide.md)

---

## SDD 工作流

1. Spec Discovery → 对齐 PRD 与 P0 决策
2. 编写 spec.md → `/sdd-review <feature-dir> spec`
3. 用户确认 Spec
4. 编写 design.md → `/sdd-review <feature-dir> design`
5. 用户确认 Design（含 Constitution Check）
6. 编写 tasks.md → `/sdd-review <feature-dir> tasks`
7. 创建 Feature 分支 `feat/v3.0.0-beta1/048-rebac-permission-model-grants`
8. 逐波实现、E2E、代码评审和发布验收

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-07-24 | 登记 F043～F046。 |
| 2026-07-27 | 登记 F047 灵思任务模式引用溯源。 |
| 2026-07-28 | 将 ReBAC Spec 并入本版本并重编号为 F048。 |
| 2026-07-28 | 补充 OpenFGA Authorization Model 升级、旧四档/标准/自定义模型迁移、Config 大 JSON 表化合同及产品可读说明。 |
| 2026-07-28 | 用户确认进入 Design；形成 Catalog 原子发布、Grant 投影、权限模式与 M0–M6 设计草案。 |
| 2026-07-28 | `/sdd-review design` 自审通过（LGTM）；等待用户 SDD ★ 确认。 |
| 2026-07-29 | 按评审反馈纳入 dashboard、预览/下载边界、业务/权限职责与全模型重算，并梳理 F018 owner 现状。 |
| 2026-07-29 | OQ-07 选择 A，F048 启服时退役 F018；迁移改为停服直迁、校验后启服，不提供独立预演或应用级回滚。 |
| 2026-07-29 | 用户纠正迁移边界：沿用现有 OpenFGA Store，只发布并运行新 model；旧 model 仅保留为不可变历史记录，不维护两套 Store/model 运行链。 |
| 2026-07-29 | 纠正后的同 Store、单运行 model 方案通过 `/sdd-review design` 24 项复审；停在 Design ★ 门禁，尚未生成 tasks.md。 |
| 2026-07-29 | 用户进一步纠正执行职责：Alembic migration 仅处理数据库结构 DDL；旧权限数据、Config 和 OpenFGA tuple 迁移由 `src/backend/scripts/` 专用脚本完成，服务启动不自动迁移。 |
| 2026-07-29 | Alembic/scripts 职责纠正后的方案通过 `/sdd-review design` 24 项复审；停在 Design ★ 门禁，尚未生成 tasks.md。 |
| 2026-07-29 | 用户明确确认 Design ★，进入 tasks.md 编写与评审阶段；编码尚未开始。 |
| 2026-07-29 | F048 tasks.md 完成 140 项原子拆解并通过 `/sdd-review tasks` 21 项评审；等待用户明确确认 Tasks。 |
| 2026-07-30 | 用户明确确认 Tasks ★；完成 T001～T139 的实现、逐波回归和代码审查；随后明确本地不执行真实环境 E2E，T140 以范围决策和未执行证据报告收口，功能与迁移脚本开发完成。 |
| 2026-08-14 | 登记 F049 知识空间目录与搜索读取优化，以及 F050 统一权限设置入口的 F048 适配。 |
| 2026-08-17 | F050 Design 经用户确认；以 feat/2.6.0 实际 UI 为基线、F048 为唯一权限运行时，进入 Tasks 拆解。 |
| 2026-08-21 | 登记 F060 信息源订阅对账、公共文章同步与知识空间一次投递；F051～F059 已在当前代码或并行 Feature 历史中使用，故从 F060 起号。 |
| 2026-08-21 | 用户确认 F060 Spec，进入 Design 与 Constitution Check。 |
| 2026-08-21 | F060 Design 完成并按 design checklist 24 项自审通过（LGTM）；等待用户 SDD ★ 确认。 |
| 2026-08-25 | 用户确认 F060 Design；tasks.md 完成 43 项拆解并按 tasks checklist 21 项自审通过（LGTM），等待用户确认。 |
