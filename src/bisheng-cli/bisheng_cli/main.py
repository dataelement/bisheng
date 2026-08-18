"""Process entry point: stream hardening, dispatch, and the exit-code funnel.

Every path out of this function emits exactly one `result` event — success,
handled failure, and crash alike. An agent that reads only the last stdout line
can then always reach a verdict; without that invariant a crash would leave it
parsing an empty stream and guessing.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from collections.abc import Callable
from typing import Any, TextIO

from bisheng_cli.cli import build_parser
from bisheng_cli.errors import EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, CliError, render_human
from bisheng_cli.output import Emitter, wrap_stream

Handler = Callable[[Any, Emitter], int]

# Resolved lazily so that importing `main` never drags in every command module —
# and so a command that is still being written cannot break `--help`.
_HANDLER_PATHS = {
    "login": "bisheng_cli.commands.login:run",
    "deploy": "bisheng_cli.commands.deploy:run",
    "logs": "bisheng_cli.commands.logs:run",
    "skills": "bisheng_cli.commands.skills:run",
}


def resolve_handler(name: str, overrides: dict[str, Handler] | None = None) -> Handler:
    if overrides and name in overrides:
        return overrides[name]
    module_name, _, attr = _HANDLER_PATHS[name].partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def run(
    argv: list[str] | None = None,
    *,
    handlers: dict[str, Handler] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    emitter = Emitter(
        json_mode=args.json_mode,
        quiet=args.quiet,
        verbose=args.verbose,
        stdout=stdout,
        stderr=stderr,
    )
    command = args.command or ""

    if not command:
        emitter.error(parser.format_usage().strip())
        emitter.error("错误: 缺少子命令。可用: login / deploy / logs / skills sync")
        emitter.result(command, ok=False, exit_code=EXIT_USAGE)
        return EXIT_USAGE

    try:
        handler = resolve_handler(command, handlers)
        exit_code = handler(args, emitter)
        emitter.result(command, ok=exit_code == EXIT_OK, exit_code=exit_code)
        return exit_code
    except CliError as exc:
        emitter.error(render_human(exc))
        emitter.result(command, ok=False, exit_code=exc.exit_code, failure=exc.as_failure())
        return exc.exit_code
    except Exception as exc:
        emitter.error(f"CLI 内部异常: {exc.__class__.__name__}: {exc}")
        emitter.error("下一步: 加 --verbose 重跑并把输出报给支持。")
        if args.verbose:
            emitter.error(traceback.format_exc())
        emitter.result(command, ok=False, exit_code=EXIT_INTERNAL)
        return EXIT_INTERNAL


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point (`[project.scripts] bisheng`)."""
    # First thing, before any Chinese copy can reach a GBK console: a
    # UnicodeEncodeError here would replace the actual error message with a
    # traceback about encoding.
    sys.stdout = wrap_stream(sys.stdout)
    sys.stderr = wrap_stream(sys.stderr)
    raise SystemExit(run(argv))
