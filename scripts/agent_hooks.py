#!/usr/bin/env python3
"""Cursor 与 Claude Code 共用的仓库钩子.

子命令:
    cursor-post-edit: 写文件后把 arch-guard 违规原文注入当前回合.
    claude-post-edit: 同上, 使用 Claude Code 的 hookSpecificOutput.
    cursor-stop: 回合结束时, 工作区仍有违规则追加一条只修违规的跟进.
    cursor-git-safety: 拦截 force push, reset --hard, --no-verify; 新建分支改为询问.
    claude-pre-tool: 对 Bash 工具做同样的 git 拦截.

守卫失败也退出 0. Cursor 只有在 stdout 是合法 JSON 时才会把内容交回模型;
非 0 退出默认放行, 模型看不到违规原文.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

_EDIT_TOOLS = {"Write", "StrReplace", "Edit", "ApplyPatch", "TabWrite"}
_GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_STOP_FILE_LIMIT = 40
_DENY_MESSAGE = (
    "仓库钩子拒绝了这条 git 命令. force push, git reset --hard, 以及 --no-verify "
    "不能由模型执行. 请改用普通 push 或普通 reset. 若必须执行, 请用户在自己的终端里运行."
)
_ASK_MESSAGE = "仓库钩子要求先确认才能新建分支 (git checkout -b/-B 或 git switch -c/-C)."


def main(argv: list[str] | None = None) -> int:
    """按子命令把守卫结果或 git 决定写到 stdout.

    Args:
        argv: 含子命令的参数. 为空时使用 sys.argv.

    Returns:
        进程退出码. 业务拒绝也返回 0, 决定写在 JSON 里.
    """
    args = list(sys.argv if argv is None else argv)
    command = args[1] if len(args) > 1 else ""
    payload = _load_payload()
    if command == "cursor-post-edit":
        _cursor_post_edit(payload)
    elif command == "claude-post-edit":
        _claude_post_edit(payload)
    elif command == "cursor-stop":
        _cursor_stop(payload)
    elif command == "cursor-git-safety":
        _cursor_git_safety(payload)
    elif command == "claude-pre-tool":
        _claude_pre_tool(payload)
    else:
        _print_json({"additional_context": f"unknown agent hook command: {command}"})
        return 2
    return 0


def _load_payload() -> dict[str, object]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _print_json(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return Path(__file__).resolve().parents[1]


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def _tool_file(payload: dict[str, object]) -> str:
    tool_input = _as_dict(payload.get("tool_input"))
    for key in ("file_path", "path", "target_file", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("file_path", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _arch_guard(path: str) -> str:
    """跑架构守卫并返回违规原文.

    Args:
        path: 要检查的文件路径.

    Returns:
        违规原文. 无违规时为空字符串.
    """
    script = _repo_root() / "scripts" / "arch-guard.sh"
    if not script.is_file() or not path:
        return ""
    result = subprocess.run(
        ["bash", str(script), path],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    text = (result.stdout or "").strip()
    if result.returncode == 0:
        return ""
    return text


def _guard_context(text: str) -> str:
    return "arch-guard 发现本次写入的违规, 只修下面这些:\n" + text


def _cursor_post_edit(payload: dict[str, object]) -> None:
    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name and tool_name not in _EDIT_TOOLS:
        return
    text = _arch_guard(_tool_file(payload))
    if text:
        _print_json({"additional_context": _guard_context(text)})


def _claude_post_edit(payload: dict[str, object]) -> None:
    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name and tool_name not in _EDIT_TOOLS:
        return
    text = _arch_guard(_tool_file(payload))
    if not text:
        return
    _print_json(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": _guard_context(text),
            }
        }
    )


def _changed_files(root: Path) -> list[str]:
    """列出相对 HEAD 有改动的源文件, 加上未跟踪文件.

    超过 40 个时只返回前 40 个. 其余交给 pre-commit 和合并流水线,
    避免 stop 钩子在大 diff 上超时.

    Args:
        root: 仓库根目录.

    Returns:
        绝对路径列表, 最多 40 个.
    """
    names: list[str] = []
    for args in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(args, cwd=root, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            continue
        names.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    seen: set[str] = set()
    picked: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        if not name.endswith((".py", ".ts", ".tsx")):
            continue
        path = root / name
        if not path.is_file():
            continue
        picked.append(str(path))
        if len(picked) >= _STOP_FILE_LIMIT:
            break
    return picked


def _cursor_stop(payload: dict[str, object]) -> None:
    status = payload.get("status")
    if status not in (None, "completed"):
        return
    chunks: list[str] = []
    for path in _changed_files(_repo_root()):
        text = _arch_guard(path)
        if text:
            chunks.append(text)
    if not chunks:
        return
    body = "\n".join(chunks)
    if len(body) > 4000:
        body = body[:4000] + "\n...(truncated)"
    _print_json({"followup_message": ("arch-guard 在当前工作区仍有违规. 只修下面这些, 不要改无关文件:\n" + body)})


def _split_commands(command: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buf.append(char)
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        if char in {";", "\n", "|"}:
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def _strip_git_globals(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GIT_GLOBAL_WITH_ARG:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return tokens[index:]
    return []


def _extract_git_args(tokens: list[str]) -> list[str] | None:
    index = 0
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
        index += 1
    if index < len(tokens) and tokens[index] == "sudo":
        index += 1
    if index >= len(tokens):
        return None
    command = tokens[index]
    if command != "git" and not command.endswith("/git"):
        return None
    return _strip_git_globals(tokens[index + 1 :])


def _classify_git_args(args: list[str]) -> str | None:
    if not args:
        return None
    if "--no-verify" in args:
        return "deny"
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "push" and any(item == "-f" or item.startswith("--force") for item in rest):
        return "deny"
    if subcommand == "reset" and "--hard" in rest:
        return "deny"
    if subcommand == "checkout" and any(item in {"-b", "-B"} for item in rest):
        return "ask"
    if subcommand == "switch" and any(item in {"-c", "-C"} for item in rest):
        return "ask"
    return None


def _git_decision(command: str) -> str | None:
    """判断一条 shell 命令该放行, 拒绝, 还是询问.

    Args:
        command: 完整 shell 命令.

    Returns:
        deny, ask, 或 None. None 表示放行.
    """
    decision: str | None = None
    for part in _split_commands(command):
        try:
            tokens = shlex.split(part)
        except ValueError:
            if "git" in part and any(flag in part for flag in ("--no-verify", "--hard", "--force")):
                return "deny"
            continue
        git_args = _extract_git_args(tokens)
        if git_args is None:
            continue
        kind = _classify_git_args(git_args)
        if kind == "deny":
            return "deny"
        if kind == "ask":
            decision = "ask"
    return decision


def _shell_command(payload: dict[str, object]) -> str:
    command = payload.get("command")
    if isinstance(command, str) and command.strip():
        return command
    tool_input = _as_dict(payload.get("tool_input"))
    nested = tool_input.get("command")
    if isinstance(nested, str):
        return nested
    return ""


def _cursor_git_safety(payload: dict[str, object]) -> None:
    decision = _git_decision(_shell_command(payload))
    if decision == "deny":
        _print_json(
            {
                "permission": "deny",
                "user_message": _DENY_MESSAGE,
                "agent_message": _DENY_MESSAGE,
            }
        )
        return
    if decision == "ask":
        _print_json(
            {
                "permission": "ask",
                "user_message": _ASK_MESSAGE,
                "agent_message": _ASK_MESSAGE,
            }
        )
        return
    _print_json({"permission": "allow"})


def _claude_pre_tool(payload: dict[str, object]) -> None:
    tool_name = payload.get("tool_name")
    if tool_name not in (None, "Bash"):
        return
    decision = _git_decision(_shell_command(payload))
    if decision is None:
        return
    _print_json(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": _DENY_MESSAGE if decision == "deny" else _ASK_MESSAGE,
            }
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
