# Tasks: F039 ReBAC 读路径性能范式收尾

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0（分支 `feat/v2.6.0/039-rebac-read-path-perf-rollout`，基于 `feat/2.6.0`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-25 用户确认通过（`/sdd-review spec`）。遗留观察：INV-6 豁免论证（B 组全返回）留待 design 给出；详见评审记录。 |
| design.md | ✅ 已评审 | 2026-06-26 用户确认通过（`/sdd-review design`）。Constitution C1–C7 门禁 PASS；两条 medium（E 组版本 key 定主选项、§7 性能阈值落数字）已闭环。INV-6 豁免论证见 design §3 决策 3。 |
| tasks.md | 🔲 草稿 | 拆解完成后改为 ✅ 已拆解（待 design 定稿后再细化下方任务表） |
| 实现 | 🔲 未开始 | 0 / N 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 待办（spec→design 之间）

- [ ] 起草 design.md：落实 5 组（A 频道详情 / B 空间广场 / C 工作台列表 / D 侧边栏懒加载 / E 名册版本派生 key 缓存）的 file:line 锚点与 How。
- [ ] design 中**必须**给出 **INV-6 豁免论证**（B 组 `/space/joined`·`/space/department` 保持全返回，与「所有 ReBAC 列表用 cursor」的张力）或在 release-contract 登记例外。
- [ ] design 中明确 E 组与 F036 design §3/§8 的边界（版本派生 key 解耦缓存 ≠ F036 否决的 TTL/写路径钩子方案）。
- [ ] 在 `feat/2.6.0` 的 `features/v2.6.0/release-contract.md` 登记 F039（表 1 领域归属 / 表 3 依赖 F004·F008·F027·F036·F037 / 新增对外 API `GET /channel/manager/{id}/unread-counts` / 变更历史）。

> 任务级拆解（Wave + TDD）待 design 定稿后填入下表。

## 执行记录（TDD，wave 顺序）

| # | 任务 | 产物 | 覆盖 AC | 状态 |
|---|---|---|---|---|
| — | 待 design 定稿后拆解 | — | — | 🔲 |
