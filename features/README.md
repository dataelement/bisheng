# SDD (Spec-Driven Development) — BiSheng 适配版

> **完整方法论指南**: [`docs/SDD-Guide.md`](../docs/SDD-Guide.md)
>
> 本目录存放 SDD 产物——版本契约、Feature 规格和任务清单。

---

## 工作流（9 步）

```
0. release-contract.md          版本开始时，一次性
   ↓
1. Spec Discovery               架构师提问，识别 PRD 不确定性
   ↓ ★ 手动暂停点：用户确认
2. 编写 spec.md                 合并需求规范 + 技术设计
   ↓
3. /sdd-review <dir> spec       审查 spec（11 项检查）
   ↓ ★ 手动暂停点：用户确认
4. 编写 tasks.md                拆解为原子任务
   ↓
5. /sdd-review <dir> tasks      审查 tasks（17 项，自动推进）
   ↓
6. 创建 Feature 分支            feat/v2.5.0/{NNN}-{name}，基于 2.5.0-PM
   ↓
7. 逐任务执行                   实现 → 测试 → /task-review → 打勾
   ↓
7.5. /e2e-test <dir>            E2E 测试（强制）
   ↓
8. /code-review --base 2.5.0-PM 多维度代码审查（自动）
   ↓
9. 合并回 2.5.0-PM
```

**核心约束**:
- 每步只产出该步骤的文件，不提前执行后续步骤
- 两个 ★ 手动暂停点必须等待用户确认
- 实现偏差必须记录在 tasks.md §实际偏差记录

---

## 目录结构

```
features/
├── README.md                    # 本文件
├── _templates/                  # 可复用模板
│   ├── release-contract.md      # 版本契约模板
│   ├── spec.md                  # 规格文档模板（BiSheng 适配版）
│   └── tasks.md                 # 任务清单模板（BiSheng 适配版）
└── v2.5.0/                      # v2.5.0 版本产物
    ├── release-contract.md      # 版本契约（预填）
    ├── README.md                # Feature 索引
    ├── 001-feature-name/
    │   ├── spec.md
    │   └── tasks.md
    └── ...
```

---

## 命名规范

### Feature 目录

```
{NNN}-{kebab-case-name}
```

- `NNN` — 零补齐三位数字（000, 001, 002, ...）
- Name — 小写、连字符分隔、描述性名称
- 示例：`000-test-infrastructure`、`001-multi-tenant`、`004-rebac-core`

### Feature 分支

```
feat/v2.5.0/{NNN}-{short-name}
```

- 基于 `2.5.0-PM` 拉出
- 合并回 `2.5.0-PM`（`git merge --no-ff`）
- 示例：`feat/v2.5.0/004-rebac-core`

---

## 审查命令

| 命令 | 时机 | 说明 |
|------|------|------|
| `/sdd-review <dir> spec` | spec.md 编写后 | 11 项需求+架构检查 |
| `/sdd-review <dir> tasks` | tasks.md 编写后 | 17 项拆解质量检查（自动） |
| `/task-review <dir> <task_id>` | 每个任务完成后 | L1 约定合规（6 项） |
| `/code-review --base 2.5.0-PM` | Feature 全部完成后 | L2 多维度深度审查 |
| `/e2e-test <dir>` | 全部任务完成后 | 生成并运行 E2E 测试 |

---

## 快速开始

### 新建 Feature

```bash
# 1. 复制模板
cp features/_templates/spec.md features/v2.5.0/NNN-feature-name/spec.md
cp features/_templates/tasks.md features/v2.5.0/NNN-feature-name/tasks.md

# 2. 按工作流执行：Discovery → spec → review → tasks → review → 实现
```

### 新建版本

```bash
# 1. 创建版本目录
mkdir features/vX.Y.Z

# 2. 复制版本契约模板
cp features/_templates/release-contract.md features/vX.Y.Z/release-contract.md

# 3. 填写领域对象归属、不变量、依赖图
```
