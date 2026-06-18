# Cursor Configuration

BiSheng 项目的 Cursor Agent 配置，从 `.claude/` 迁移而来。

## 目录结构

```
.cursor/
├── hooks.json          # 文件编辑后自动触发 ruff + arch-guard
├── hooks/
│   ├── ruff-format.sh  # Python 自动格式化（对应 Claude PostToolUse）
│   └── arch-guard.sh   # 架构守卫包装脚本
├── rules/              # Cursor Rules (.mdc)
│   ├── bisheng-core.mdc
│   ├── backend.mdc
│   ├── platform-frontend.mdc
│   └── client-frontend.mdc
└── skills/             # Agent Skills（从 .claude/skills/ 同步）
    ├── code-review/
    ├── sdd-review/
    ├── task-review/
    ├── e2e-test/
    ├── i18n-localizer/
    └── react-component-refactor/
```

## 与 Claude Code 的对应关系

| Claude Code | Cursor |
|-------------|--------|
| `AGENTS.md` | `.cursor/rules/bisheng-core.mdc` (alwaysApply) |
| `.claude/rules/platform-frontend.md` | `.cursor/rules/platform-frontend.mdc` |
| `.claude/rules/client-frontend.md` | `.cursor/rules/client-frontend.mdc` |
| `src/backend/AGENTS.md` | `.cursor/rules/backend.mdc` |
| `.claude/settings.json` PostToolUse hooks | `.cursor/hooks.json` afterFileEdit |
| `.claude/skills/` | `.cursor/skills/` |

## Skills 用法

在 Cursor Agent 对话中使用斜杠命令或直接描述任务：

- `/sdd-review features/v2.5.0/004-rebac-core spec`
- `/task-review features/v2.5.0/004-rebac-core T003`
- `/code-review --base 2.5.0-PM`
- `/e2e-test features/v2.5.0/004-rebac-core`
- `/i18n-localizer` — 国际化模块
- `/react-component-refactor` — 重构大型 React 组件

## 同步维护

更新 `.claude/` 后，需手动同步到 `.cursor/`：

```bash
# 同步 skills
cp -R .claude/skills/* .cursor/skills/

# rules 需按 .claude/rules/*.md 和 AGENTS.md 手动更新 .cursor/rules/*.mdc
```

## Hooks 前置条件

- Python 文件编辑后自动 ruff：需要 `src/backend/.venv` 或系统安装 `uv`
- arch-guard：依赖 `scripts/arch-guard.sh`（项目根目录）
