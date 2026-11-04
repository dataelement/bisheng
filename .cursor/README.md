# Cursor 配置（与 `.claude/` 对应）

本目录为 [Cursor](https://cursor.com) 的项目级配置，与 `.claude/`（Claude Code）保持功能对齐。

## 目录映射

| Claude Code | Cursor | 说明 |
|-------------|--------|------|
| `.claude/settings.json` | `.cursor/hooks.json` | Agent 钩子配置 |
| `.claude/hooks/` | `.cursor/hooks/` | 钩子脚本 |
| `.claude/skills/` | `.cursor/skills/`（软链接） | 项目级 Agent Skills，唯一原件在 `.claude/skills/` |

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

`.cursor/skills` 是指向 `../.claude/skills` 的软链接（`.agents/skills` 同理），三处读到的是同一份文件，命令用法不变：

| Skill | 触发 |
|-------|------|
| `sdd-review` | `/sdd-review <feature_dir> <spec\|design\|tasks>` |
| `task-review` | `/task-review <feature_dir> <task_id>` |
| `sdd-code-review` | `/sdd-code-review --base <branch>` |
| `e2e-test` | `/e2e-test [feature_dir]` |
| `approval-module` | 审批相关改动前自动加载 |
| `i18n-localizer` | 模块国际化 |
| `react-component-refactor` | 大组件拆分重构 |

## 维护

Skill 只改 `.claude/skills/` 下的原件，不要在 `.cursor/skills` 或 `.agents/skills` 里另建副本；新增 Skill 放进 `.claude/skills/` 后三处自动可见。

Hooks 仍是两份（事件名与输出格式不同），改 `.claude/hooks/` 时检查 `.cursor/hooks/` 是否需要同步。

Windows 检出需要 `git config core.symlinks true`（并具备创建符号链接的权限），否则软链接会变成一个只含路径文本的普通文件。
