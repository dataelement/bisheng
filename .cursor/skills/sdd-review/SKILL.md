---
name: sdd-review
description: 对 BiSheng 项目的 SDD 文档执行审查。
  - spec：写完 spec.md 后调用，同时检查 PRD gap 和架构合规性，生成报告供用户参考
  - tasks：写完 tasks.md 后自动调用，检查 AC 追溯、任务拆解质量和技术债预防
  用法：/sdd-review <feature_dir> <doc_type>，doc_type 为 spec / tasks。
  TRIGGER when: 用户完成了 SDD 的 spec.md / tasks.md 编写，或者用户使用 /sdd-review 命令，或者 Claude 完成了这些文件的编写后需要审查。
---

# SDD Review Skill

## 调用方式

```
/sdd-review <feature_dir> <doc_type>
```

例：
```
/sdd-review features/v2.5.0/004-rebac-core spec
/sdd-review features/v2.5.0/001-multi-tenant tasks
```

## 审查流程

### 第一步：解析参数

从用户输入或调用上下文中提取：
- `feature_dir`：特性目录路径（如 `features/v2.5.0/004-rebac-core`）
- `doc_type`：文档类型，必须是 `spec` 或 `tasks`

若参数缺失或无效，向用户报告错误后停止。

---

### spec 模式（辅助审查，不自动推进）

spec.md 合并了需求规范和技术设计，因此 spec 审查同时覆盖需求覆盖和架构合规检查。

**第二步（spec）：执行合并审查**

读取文件：
- `<feature_dir>/spec.md`（已写的规格文档）
- spec.md 中"关联 PRD"字段指向的文件（若未标注，读取 `docs/PRD/` 下与特性名最相关的文件）
- `features/v2.5.0/release-contract.md`（不变量约束，确认 spec 未越界）
- `docs/architecture/02-backend-modules.md`（后端模块架构）
- `docs/architecture/10-permission-rbac.md`（权限体系）

按 `references/spec-checklist.md` 中的检查清单执行 14 项检查。

**第三步（spec）：展示报告，等待用户确认**

向用户展示分析结果：
- 无 gap / 无问题：告知"审查通过，可继续确认"
- 有 gap / 有问题：展示每个问题（MISSING / FORMAT / CONFLICT / ISSUE），供用户决定是否修改

**等待用户确认**（唯一手动暂停点）。用户确认后，将 `<feature_dir>/tasks.md` 状态表中 spec.md 行更新为 `✅ 已评审`。

---

### tasks 模式（自动审查）

**第二步（tasks）：执行审查**

读取文件：
- `<feature_dir>/tasks.md`
- `<feature_dir>/spec.md`（验收标准 + 技术方案）
- `features/v2.5.0/release-contract.md`（领域归属 + 不变量）

按 `references/tasks-checklist.md` 中的检查清单执行 21 项检查。

**第三步（tasks）：处理审查结果**

**输出格式**：
- 有问题：`ISSUE: <描述> | SEVERITY: high/medium/low | TASK: <T-NN 若适用>`
- 无问题：`LGTM`

**处理逻辑**：
- `LGTM` → 更新 `<feature_dir>/tasks.md` 状态表，将 `tasks.md` 行改为 `✅ 已拆解`
- 有 `high`/`medium` ISSUE → 修复后重新审查（最多 2 轮）
- `low` ISSUE → 记录但跳过
- 2 轮后仍有 `high`/`medium` → 停止，向用户报告剩余问题

## 错误处理

- feature_dir 不存在 → 报告路径错误，停止
- doc_type 不是 spec / tasks → 报告参数错误，停止
- spec.md 不存在 → 报告"找不到 spec.md，请先完成 spec"，停止
- tasks.md 不存在（tasks 模式）→ 报告"找不到 tasks.md，请先完成 tasks"，停止
