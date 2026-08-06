# v3.0.0 Feature 索引（应用工场）

**版本目标**：交付《3.0 应用工场 PRD-1》——专业开发者通道（DEV）、应用运行时与发布（RT）、治理与管理面（GOV），及伴生《3.0 开放 API 鉴权与身份传递 PRD》的 v2 开放 API 鉴权改造。

**版本契约**：[release-contract.md](./release-contract.md)
**Spec Discovery**：[000-prd1-discovery/discovery.md](./000-prd1-discovery/discovery.md)（含 11 维代码调研锚点 research/）

> ⚠️ **推送前必读**：本分支 `3.0-vibe` 汇集了应用工场与开放 API 鉴权的全部产品文档与调研记录，其中 `000-prd1-discovery/research/` 与 `docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` **含未修复安全缺口的行级定位**。origin 是公开仓，**未经确认不得推送本分支**。

> 编号说明：F043–F048 已被 `features/v3.0.0-beta1/` 占用（该目录仅存在于 origin/feat/3.0.0-beta1 分支、未合入主线），本版本从 F049 起。

---

## Feature 列表（规划态，Discovery ★ 确认后逐个进 spec）

| # | Feature | 批次 | 状态 | 依赖 |
|---|---------|------|------|------|
| F049 | openapi-auth | A | 🔲 待 Spec（Discovery 待用户确认） | — |
| F050 | personal-api-key | A | 🔲 规划 | F049 |
| F051 | model-protocol-gateway | A | 🔲 规划 | F050 |
| F052 | mcp-server-face | A | 🔲 规划 | F050 |
| F053 | dev-cli-skills | A尾/B | 🔲 规划 | F050–F052 |
| F054 | app-domain-runtime | B | 🔲 规划 | F049 |
| F055 | app-publish-pipeline | B | 🔲 规划 | F054, F049 |
| F056 | app-square-governance | B | 🔲 规划 | F054, F055 |
| F057 | bisheng-sdk | B | 🔲 规划 | F049/F051/F052/F054 |

批次 A = 开放能力层（可独立于工场运行时交付，GOV-07）；批次 B = 工场运行时层。

---

## SDD 工作流

1. Spec Discovery → ★ 用户确认（当前所在步骤）
2. 编写 spec.md → `/sdd-review <dir> spec` → ★ 用户确认
3. 编写 design.md → `/sdd-review <dir> design`（Constitution Check）→ ★ 用户确认
4. 编写 tasks.md → `/sdd-review <dir> tasks`
5. 创建 Feature 分支 `feat/v3.0.0/{NNN}-{name}`（尽早建，文档与代码都在分支上）
6. 逐任务执行 → `/task-review` → 打勾
7. `/e2e-test`（强制）
8. `/code-review`
9. 合并

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-08-06 | 初始化 v3.0.0 版本目录：PRD-1 Spec Discovery 产出（000-prd1-discovery/）+ 契约初版 + 九 Feature 规划索引。 |
