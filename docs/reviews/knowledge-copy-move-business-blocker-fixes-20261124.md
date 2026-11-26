# 复制/移动任务误阻塞热修复与审查

日期：2026-11-24。目标发行线：`feat/3.1.0-beta2`，实现基线 `50bd1b7eb1`。
范围：修复既有删除保护粒度与旧 QA/文档复制失败释放遗漏；不新增任务取消/回退功能，不改内置工具普通管理者的配置权限。

## 修复结果

| 入口 | 修复前 | 修复后 |
| --- | --- | --- |
| 源空间单文件/文件夹/历史版本删除 | 任一未收尾移动即按整个源空间拒绝 | 按已授权删除闭包的全部物理 ID 校验，仅在完整冻结范围证明不相交时放行 |
| 目标空间单文件/文件夹/历史版本删除 | 任一 move_index 非 succeeded 即拒绝，包括失败/过期旧任务 | 复用同一冻结范围证明，分页检查所有目标任务；无关文件可删除 |
| 旧 QA/文档复制失败 | 目标 FAILED，源仍 COPYING 且保留 copy_target_id，无法正常进入/再次复制 | 原事务释放源，保留失败副本；新复制可建立新配对，旧重复消息 no-op，旧 finish 无权覆盖新配对 |

删除预检与根锁内执行复核都采用服务端展开的资源闭包，不能信任请求中单个文件 ID。目录包含全部子项，文档包含全部关联版本；历史版本专用删除仍只包含被选中物理版本。

移动保护复用既有单文件重解析的证明：原 Plan/Job 配对、租户、scope digest、冻结逻辑范围、target manifest、实际索引 item 身份及计数必须一致。跳过索引的历史版本与文件夹仍在逻辑范围内。任一信息不完整即拒绝，不凭 failed/obsolete 状态清掉真实依赖。目标侧每页 200 个任务，缺失 Plan 的尾页同样拒绝。

整空间删除/清空/重建仍可能破坏未完成移动依赖的旧索引，继续保留原保护。活动复制的目标保护保留，终态复制不阻塞。无数据迁移、DDL、新端点或错误码；未改 FGA 授权规则，也未删除任何副本或工具。

## 116 只读验证

候选类仅在独立诊断进程私有命名空间加载，数据库只读 SELECT；没有替换在线模块、更新任务、提交删除或操作索引。

| 侧别/空间 | 检查文件 | 候选保护结果 |
| --- | --- | --- |
| 源 4145（failed 移动） | 无关 96700 / 关联 97268 | 无关放行 / 关联拒绝 |
| 源 3547（obsolete 移动） | 无关 98313 / 关联 98364 | 无关放行 / 关联拒绝 |
| 目标 4394 | 无关 98168 / 关联 98364 | 无关放行 / 关联拒绝 |
| 目标 4192 | 关联 97268 | 拒绝；未发现可供此探针选择的无关物理文件 |

旧 QA 2698、2712 的 COPYING 行无双向配对，不能据其状态猜测原任务结论，本次不修改历史行。创建阶段的投递结果不确定仍保留原诊断状态。

## 验证

在独立 worktree 的 SQLite 原生事务中执行以下组合，**110 passed**：

```text
test/knowledge/test_managed_tenant_copy.py
test/knowledge/test_managed_copy_worker.py
test/knowledge_unification/test_file_scoped_source_move.py
test/knowledge_unification/test_source_move_input.py
test/knowledge_unification/test_kn_delete_projection.py
test/knowledge_unification/test_kn_delete_plan.py
test/knowledge_unification/test_processing_deletion_fence.py
test/knowledge_unification/test_delete_move_scope.py
test/knowledge_unification/test_move_job_reservation.py
```

覆盖成功/失败/过期等任务状态、跳过版本和目录、批量范围、损坏 manifest/台账/外租户明细、201 条任务分页、预检后新增移动、原生 F048 删除 journal 与 purge、历史版本删除保留主版本、QA worker 失败及旧消息不干扰新复制。仅外部鉴权/物理存储传输在既有 fixture 中隔离；不把 SQLite 回归当作真实双库、ES 或完整页面验收。

变更 Python 文件通过 Ruff format/check、逐文件 arch-guard；`git diff --check` 通过。未部署 116，原删除请求需部署后再验收。

## 七维审查

对照 F118 AC-24/25 与 F009 AC-32/35，按 sdd-code-review 清单审查本次热修复差异。

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

审查要点：保留根锁与执行复核；原消息只有正确租户、源目标关系及操作者才可 no-op，活动消息仍走原权限校验；源恢复和目标失败原子提交，旧 finish 不跨配对。新增查询显式带租户，使用通用 SQLAlchemy，不增加方言专属 SQL。终态历史副本不可重新 claim。两个所属 feature 的 design.md 已同步决策、入参和已知坑。

**Overall: PASS。** 本地与现场只读证据支持当前修复；没有宣称已完成关联移动的物理收尾或在线删除验收。
