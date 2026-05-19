# v2.6.0 Feature 索引

**版本目标**：承载审批中心统一化等跨模块产品能力，作为 v2.5.x 之后的新一轮功能版本。

**版本契约**：[release-contract.md](./release-contract.md)

**开发主线分支**：`2.6.0-PM`

---

## Feature 列表

| # | Feature | 优先级 | 状态 | 依赖 |
|---|---------|--------|------|------|
| F025 | [approval-center-unification](./025-approval-center-unification/) | P0 | 🔲 规格已生成，待评审 | F005, F011, F012, F013 |

---

## SDD 工作流

1. Spec Discovery → 对齐 PRD 不确定性
2. 编写 spec.md → `/sdd-review spec`
3. 编写 tasks.md → `/sdd-review tasks`
4. 创建 Feature 分支 `feat/v2.6.0/{NNN}-{name}`，基于 `2.6.0-PM`
5. 逐任务执行 → `/task-review` → 打勾
6. `/e2e-test`（强制）
7. `/code-review --base 2.6.0-PM`
8. 合并回 `2.6.0-PM`

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-05-18 | 初始化 v2.6.0 版本目录，并迁入 **F025-approval-center-unification** 规格与任务。 |
