---
name: task-review
description: L1 任务级代码审查。在每个任务完成后执行轻量级约定合规检查，
  确保架构红线和编码约定在任务级别被守住，不让违规累积到特性级审查（L2）才发现。
  用法：/task-review <feature_dir> <task_id>
  TRIGGER when: 用户完成了一个 SDD 任务（实现或测试），或者用户使用 /task-review 命令。
---

# Task Review Skill（L1 任务级审查）

## 调用方式

```
/task-review <feature_dir> <task_id>
```

例：
```
/task-review features/v2.5.0/004-rebac-core T003
/task-review features/v2.5.0/007-resource-permission-ui T007
```

## 审查流程

### Step 1: 解析参数 + 收集变更范围

1. 验证参数：
   - `feature_dir` 必须存在且包含 `tasks.md`
   - `task_id` 必须匹配 tasks.md 中的某个任务（格式：`T001`、`T003` 等）
   - 若参数缺失或无效，报告错误后停止

2. 从 `<feature_dir>/tasks.md` 中读取指定任务的元数据：
   - 任务类型（测试 / 实现 / 基础设施 / Worker）
   - 目标文件列表
   - 前置依赖
   - 配对任务（测试↔实现）
   - 覆盖 AC 标注（测试任务）

3. 读取任务声明的所有目标文件内容（直接读取文件，不依赖 git diff）

### Step 2: 判断任务类型，选择检查子集

根据任务类型确定适用的检查项（参见 `references/task-checklist.md`）：

| 任务类型 | 适用检查项 | 额外检查 |
|---------|-----------|---------|
| **测试任务** | #2 命名 + #5 前端约定 | AC 标注格式（`覆盖 AC: AC-NN`） |
| **实现任务** | 完整 #1~#6 | 配对测试任务已完成（tasks.md 中已打勾） |
| **基础设施任务** | #1 架构分层 + #4 数据库约定 + #6 信息泄漏 | 无 |
| **Worker 任务** | #1 架构 + #4 数据库 + #6 信息泄漏 | tenant_id 通过 Celery headers 传递 |

任务类型判断规则：
- 文件路径包含 `test/` 或 `__tests__/` → 测试任务
- 文件路径包含 `domain/models/` 或 `common/errcode/` 或任务描述含"ORM""迁移""错误码""配置" → 基础设施任务
- 文件路径包含 `worker/` 或任务描述含"Celery""异步任务" → Worker 任务
- 其他 → 实现任务
- 若任务同时包含测试和实现文件，按实现任务处理

### Step 3: 按检查清单执行检查

逐项执行 `references/task-checklist.md` 中适用的检查项。

### Step 4: 元数据交叉验证

- **文件范围**：任务声明的目标文件是否实际存在，是否存在范围蔓延（修改了任务未声明的文件）
- **配对测试**：若为实现任务，检查 tasks.md 中配对的测试任务是否已打勾 ✅
- **前置依赖**：检查任务声明的依赖项是否已完成（tasks.md 中已打勾）

### Step 5: 输出报告

按以下格式输出：

```markdown
## Task Review: <task_id>

**任务**: <任务标题>
**类型**: 测试 / 实现 / 基础设施 / Worker
**文件**: <文件列表>

| # | 检查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | 架构分层 | PASS / FAIL / N/A | <若 FAIL，具体描述> |
| 2 | 命名规范 | PASS / FAIL / N/A | |
| 3 | 序列化约定 | PASS / FAIL / N/A | |
| 4 | 数据库约定 | PASS / FAIL / N/A | |
| 5 | 前端约定 | PASS / FAIL / N/A | |
| 6 | 信息泄漏 | PASS / FAIL / N/A | |

**元数据验证**: 文件范围 PASS/FAIL | 配对测试 PASS/FAIL/N/A | 依赖 PASS/FAIL

**结果**: PASS / PASS_WITH_NOTES / NEEDS_FIX
```

### Step 6: 处理结果

| 结果 | 条件 | 动作 |
|------|------|------|
| **PASS** | 全部通过 | 告知用户可以打勾 |
| **PASS_WITH_NOTES** | 仅 MEDIUM 级提醒，无 HIGH | 告知用户可以打勾，列出提醒供参考 |
| **NEEDS_FIX** | 任何 HIGH 违规 | 列出需要修复的具体问题，修复后可再次调用 `/task-review` 重审（最多 1 轮重审） |

## 错误处理

- `feature_dir` 不存在 → 报告路径错误，停止
- `tasks.md` 不存在 → 报告"找不到 tasks.md"，停止
- `task_id` 不匹配 → 报告"未找到任务 <task_id>"，停止
- 目标文件不存在 → 标记为 WARNING（文件可能尚未创建），继续检查其他文件
