"""Argument surface. Standard-library `argparse`, no click/typer.

The dependency budget (design D12) buys two runtime dependencies and this is not
one of them: a subcommand parser with auto-generated `--help` is exactly what
argparse already does. What we give up is colour and shell completion, neither of
which any acceptance criterion asks for — AC-04 asks for "usable with no TTY and
machine-readable", which is orthogonal to looking nice.

Deferred commands are **not registered**. Registering `dev` so it can answer "not
in this version" would make `--help` advertise five commands, an agent would call
one, and it would get a non-standard failure. Announcing them in the epilogue is
honest; a stub is not.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from bisheng_cli import __version__
from bisheng_cli.errors import EXIT_USAGE, CliError

SUBCOMMANDS = ("login", "deploy", "logs", "skills")
DEFERRED_COMMANDS = ("dev",)

_EPILOG = (
    "本版本提供 login / deploy / logs / skills sync 四条命令。\n"
    "dev 随后续版本提供。\n"
    "机器可读输出: 加 --json，NDJSON 走 stdout、人读文本走 stderr，最后一行恒为 result 事件。"
)


def _add_global_flags(parser: argparse.ArgumentParser, *, mirror: bool) -> None:
    """Global flags, defined on the root parser and mirrored onto each subcommand.

    argparse only accepts a root-level option *before* the subcommand, so a bare
    definition would make `bisheng deploy --json` fail with "unrecognized
    arguments" — and that is the order everyone writes, including this feature's
    own verification script. Mirroring the flags onto every subparser makes both
    orders work.

    The mirrors must use `default=SUPPRESS`. argparse parses a subcommand into a
    fresh namespace and then copies every key of it onto the outer one, so a
    mirror carrying an ordinary default would overwrite the value already parsed
    from `bisheng --json deploy` with `False`. SUPPRESS leaves the key out of the
    sub-namespace entirely when the flag was not given, so whatever the root
    parser decided survives.
    """

    def default(value: object) -> object:
        return argparse.SUPPRESS if mirror else value

    parser.add_argument(
        "--verbose",
        action="store_true",
        default=default(False),
        help="打印请求方法 / 路径 / 状态码 / 耗时（Authorization 头恒掩码）",
    )
    parser.add_argument("--quiet", action="store_true", default=default(False), help="只输出错误")
    parser.add_argument(
        "--json", action="store_true", dest="json_mode", default=default(False), help="机器可读 NDJSON 输出（stdout）"
    )
    parser.add_argument("--timeout", type=float, default=default(None), help="普通请求读超时秒数（默认 60）")
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        default=default(False),
        help="忽略 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 环境变量",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bisheng",
        description="BiSheng 开发者 CLI：登录平台、发布托管应用、查看运行日志。",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"bisheng {__version__}")
    _add_global_flags(parser, mirror=False)

    subparsers = parser.add_subparsers(dest="command", metavar="{login,deploy,logs,skills}")

    login = subparsers.add_parser("login", help="校验服务账号密钥并把凭据写入本地用户目录")
    login.add_argument("base_url", metavar="BASE_URL", help="目标平台地址，例如 http://bisheng.example.com")
    key_source = login.add_mutually_exclusive_group()
    key_source.add_argument(
        "--api-key", dest="api_key", default=None, help="直接传入密钥（会进入 shell 历史，建议改用其它方式）"
    )
    key_source.add_argument("--api-key-stdin", action="store_true", help="从标准输入读取密钥（非交互环境首选）")

    deploy = subparsers.add_parser("deploy", help="打包当前项目并发布到平台")
    deploy.add_argument("path", metavar="PATH", nargs="?", default=".", help="项目根，默认当前目录")
    deploy.add_argument("--app-id", dest="app_id", default=None, help="显式指定目标应用标识（覆盖 .bisheng/app.json）")
    deploy.add_argument("--wait", action="store_true", help="等待审批与上线结果落定")
    deploy.add_argument("--wait-timeout", type=int, default=1800, help="--wait 的最长等待秒数，默认 1800")
    deploy.add_argument("--confirm-schema-change", action="store_true", help="确认本次发布包含应用数据表结构变更")
    deploy.add_argument("--yes", action="store_true", help="跳过目标应用确认（非交互环境必须显式带上）")
    deploy.add_argument("--dry-run", action="store_true", help="只打包与本地校验，打印体量统计，不上传")

    logs = subparsers.add_parser("logs", help="查看自己名下应用的运行日志")
    logs.add_argument("--app-id", dest="app_id", default=None, help="显式指定应用标识（覆盖 .bisheng/app.json）")
    logs.add_argument("--tail", type=int, default=200, help="返回最后 N 行，默认 200")
    logs.add_argument("--since", default=None, help="起始时间：epoch 秒，或 30m / 2h / 7d 相对窗口")
    logs.add_argument("--keyword", default=None, help="只返回含该关键字的行（服务端过滤，行数可能少于 --tail）")
    logs.add_argument("--follow", action="store_true", help="持续拉取（短轮询 3 秒）")

    # `skills` is the first two-token command: a plain subparser whose own
    # subparsers carry the verb. Dispatch (main.py) keys off the top-level
    # `command`, so `commands/skills.py` owns the `sync`-vs-missing branch.
    skills = subparsers.add_parser("skills", help="同步平台的开发者技能包到本地用户目录")
    skills_sub = skills.add_subparsers(dest="skills_command", metavar="{sync}")
    sync = skills_sub.add_parser("sync", help="拉取平台当前版本的技能包到 ~/.bisheng/skills/（幂等，单向覆盖）")

    # Every leaf that can receive a flag needs the mirror, or `--json` after it
    # is "unrecognized arguments". `sync` is where `bisheng skills sync --json`
    # lands; `skills` covers `bisheng skills --json sync`.
    for subparser in (login, deploy, logs, skills, sync):
        _add_global_flags(subparser, mirror=True)

    return parser


def confirm(
    prompt: str,
    *,
    assume_yes: bool,
    is_tty: bool,
    flag_name: str,
    reader: Callable[[str], str] = input,
) -> bool:
    """Ask for confirmation, or refuse when there is nobody to ask.

    "No TTY" must never mean "assume yes". The whole point of the guard is that
    the destructive case (overwriting somebody else's app, applying a schema
    change) is the one that happens unattended.
    """
    if assume_yes:
        return True
    if not is_tty:
        raise CliError(
            f"非交互环境下无法确认：{prompt}",
            exit_code=EXIT_USAGE,
            next_step=f"确认无误后带上 {flag_name} 重新执行。",
        )
    answer = reader(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")
