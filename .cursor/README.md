# Cursor 配置（与 `.claude/` 对应）

本目录为 [Cursor](https://cursor.com) 的项目级配置，与 `.claude/`（Claude Code）保持功能对齐。

## 目录映射

| Claude Code | Cursor | 说明 |
|-------------|--------|------|
| `.claude/settings.json` | `.cursor/hooks.json` | Agent 钩子配置 |
| `.claude/hooks/` | `.cursor/hooks/` | 钩子脚本 |
| `.claude/skills/` | `.cursor/skills/` | 项目级 Agent Skills |

## Hooks

| 事件 | 脚本 | 行为 |
|------|------|------|
| `afterFileEdit` | `hooks/ruff-format-hook.sh` | 编辑 `.py` 后自动 `ruff format` + `ruff check --fix` |
| `postToolUse` (Write\|StrReplace\|Edit) | `hooks/arch-guard-hook.sh` | 运行 `scripts/arch-guard.sh`，违规通过 `additional_context` 回传 Agent |

与 Claude 的差异：

- Cursor 使用 `hooks.json`（`version: 1`），事件名为 camelCase（如 `postToolUse`）
- Ruff 挂在 `afterFileEdit`（专用于文件编辑后处理）
- Arch-guard 挂在 `postToolUse`，输出 `{ "additional_context": "..." }`（Claude 为 `hookSpecificOutput.additionalContext`）
- 文件路径兼容 `file_path` / `tool_input.path` / `tool_input.filePath`

## Skills

从 `.claude/skills/` 同步，命令用法不变：

| Skill | 触发 |
|-------|------|
| `sdd-review` | `/sdd-review <feature_dir> <spec\|design\|tasks>` |
| `task-review` | `/task-review <feature_dir> <task_id>` |
| `code-review` | `/code-review --base <branch>` |
| `e2e-test` | `/e2e-test [feature_dir]` |
| `approval-module` | 审批相关改动前自动加载 |
| `i18n-localizer` | 模块国际化 |
| `react-component-refactor` | 大组件拆分重构 |

## 维护

更新 Skill 或 Hook 时，建议同时维护 `.claude/` 与 `.cursor/` 两份，或从 `.claude/` 复制后做格式适配。

```bash
cp -R .claude/skills/* .cursor/skills/
# 然后检查 hooks 脚本是否需要同步
```
