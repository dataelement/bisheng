# Code Review Report

**Feature**: F036-rebac-eval-cost-optim（ReBAC 逐项权限评估优化）
**Review scope**: worktree 相对 `feat/2.6.0-beta4`(base) 的未提交 diff
**Changed files**: 2 源文件改 + 2 新测试 + 3 篇文档（spec/design/loadtest-report）
**Reviewer**: 自审（L2 七维度）

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| 1 边界条件 | 0 | 0 | 0 | PASS |
| 2 权限与认证 | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| 3 并发安全 | 0 | 0 | 0 | PASS |
| 4 信息泄漏 | 0 | 0 | 0 | PASS |
| 5 测试覆盖 | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| 6 代码风格 | 0 | 1 | 1 | PASS_WITH_WARNINGS |
| 7 文档同步(design.md) | 0(已修) | 0 | 0 | PASS |

## Findings

### HIGH（本轮已修复）
- **[Docs] design.md 与实现不同步**：决策 2 / §4.1 数据流 / §4.2 / §4.3 / §6 仍把 ②"整页批量预取"写成已实现，但 ② 经核实不可行（OpenFGA `/read` 无多对象批量原语）、实际只做了 ①③。
  → **本轮评审已修复**：决策 2 改写为"③ + ② 不可行已并入 ①"，数据流改为 `_full`/`_fast` 分发，§4.2 去掉"批量 tuple_cache"行，§5 增坑 7/8（不变量依赖 + owner 短路），§6.2 增不变量依赖，修订历史更正。

### MEDIUM
- **[Permission] ① 的等价性依赖一条未被强制的不变量**：「非 owner 的 file/folder 授权必有 binding」。已用 109 数据验证当前成立（裸非 owner 授权=0），但写路径**无机制强制**。worst-case 为 false-negative（漏显 owner 之外的裸授权项），非越权泄漏（grant-only 模型无"裸限制"）。缓解：① 默认 OFF + 原路径 oracle 兜底。
  → **合入/默认开启前要求**：(a) 在 authorize 写路径加 arch-guard/测试，固化"非 owner 授权 ⟹ 写 binding"；(b) 补"有 binding 空间 + 非 admin 用户"的 109 端到端 diff。
- **[Test] 深层语义等价仅由 109 admin/无 binding 空间的真实 diff 覆盖**：单测为 dispatch 级（mock 评估函数）；`_chain_effective_permission_ids` 对"叶级 owner/parent tuple 不改 view 布尔"的论证未在"有 binding + 非 admin"真实场景端到端验证。同上：补该场景 diff。
- **[Style] fine_grained_permission_service.py 被 ruff format 整文件重排（~96 行单引号→双引号 + `typing.Iterable`→`collections.abc`）混入特性 diff**：原文件本就不符 `[tool.ruff.format]`(double-quote)，PostToolUse/pre-commit 必然重排。建议合入时**拆成独立 `chore: ruff format` 提交**，让特性 diff 只剩 ①③ 逻辑、便于评审与减少冲突。

### LOW
- **[Style] `import os as _os` 置于文件中部（line ~170）带 `# noqa: E402`**：为读开关 env 避免动顶部 import 块。可接受；更干净是提到顶部 import。

## 维度说明（其余为何 PASS）
- **边界**：`build_binding_index` 空 bindings→{}；fast-path 空 items/空祖先链/`user_id` None 均有处理；无新增分页/数值边界。
- **并发**：无新增跨请求共享可变态（`chain_cache`/索引均请求内）；保留 `semaphore`；不改 OpenFGA 双写/事务。
- **信息泄漏**：提交物（源码+文档）无明文密钥；压测报告 curl 用 `$TK` 变量非字面 token。（排查/部署用的临时脚本含口令，仅在 `/tmp`，不在仓库/ diff。）
- **测试**：③ 等价单测、① dispatch 等价单测（owner/叶绑定/索引）齐；109 真实数据 FINGERPRINT 逐位相等；本地全量零新增回归。

## Overall: PASS_WITH_WARNINGS

HIGH 已在本轮修复；3 条 MEDIUM 中 2 条（不变量 arch-guard、非 admin·有绑定空间端到端 diff）为**默认开启 ① 前的硬性前置**，1 条（format 拆 commit）为合入时的整洁项；LOW 可选。①③ 逻辑本身、等价性与压测结论均可接受。
