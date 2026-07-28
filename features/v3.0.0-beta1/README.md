# v3.0.0-beta1 Feature 索引

**版本目标**：交付 3.0.0-beta1 功能体验优化、灵思引用溯源，以及 ReBAC 权限模型、
授权关系、权限继承和历史数据升级。

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
| F048 | [rebac-permission-model-grants](./048-rebac-permission-model-grants/) | P0 | 🔲 Spec 草案待确认 | F004, F006, F007, F008, F027, F036, F040 |

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
| 2026-07-28 | 补充 OpenFGA A/B 模型升级、旧四档/标准/自定义模型迁移、Config 大 JSON 表化合同及产品可读说明。 |
