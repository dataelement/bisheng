"""T009 — the command surface and the exit-code funnel.

Module-level imports on purpose: this file doubles as the import smoke test for
the production entry point. A dependency that resolved to an incompatible
version breaks here, at collection, instead of on a developer's machine after a
`pip install`.
"""

from __future__ import annotations

import io
import json

import pytest

from bisheng_cli import __version__
from bisheng_cli.cli import DEFERRED_COMMANDS, SUBCOMMANDS, build_parser, confirm
from bisheng_cli.errors import EXIT_INTERNAL, EXIT_USAGE, CliError
from bisheng_cli.main import main, run


def _subparser_actions(parser):
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            yield from action.choices.items()


def _all_option_strings(parser) -> set[str]:
    strings = {s for a in parser._actions for s in a.option_strings}
    for _, sub in _subparser_actions(parser):
        strings |= {s for a in sub._actions for s in a.option_strings}
    return strings


def test_help_lists_exactly_login_deploy_logs() -> None:
    parser = build_parser()
    names = {name for name, _ in _subparser_actions(parser)}
    assert names == {"login", "deploy", "logs"} == set(SUBCOMMANDS)


def test_help_footer_declares_deferred_commands() -> None:
    # Deferred commands are announced, not hidden: an agent that reads --help
    # should learn that `dev` exists later rather than infer it never will.
    text = build_parser().format_help()
    for name in DEFERRED_COMMANDS:
        assert name in text


def test_deferred_commands_are_not_registered() -> None:
    names = {name for name, _ in _subparser_actions(build_parser())}
    assert "dev" not in names and "skills" not in names


def test_no_as_flag_anywhere() -> None:
    options = _all_option_strings(build_parser())
    assert "--as" not in options
    assert not [o for o in options if "on-behalf" in o or "end-user" in o or "impersonat" in o]


def test_no_platform_flag_this_round() -> None:
    assert "--platform" not in _all_option_strings(build_parser())


def test_no_init_subcommand() -> None:
    assert "init" not in {name for name, _ in _subparser_actions(build_parser())}


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_every_interactive_confirm_has_a_flag_equivalent() -> None:
    subs = dict(_subparser_actions(build_parser()))
    deploy_options = {s for a in subs["deploy"]._actions for s in a.option_strings}
    login_options = {s for a in subs["login"]._actions for s in a.option_strings}
    assert {"--confirm-schema-change", "--yes"} <= deploy_options
    assert "--api-key-stdin" in login_options


def test_non_interactive_missing_flag_is_refusal_not_default_yes() -> None:
    with pytest.raises(CliError) as excinfo:
        confirm("覆盖既有应用?", assume_yes=False, is_tty=False, flag_name="--yes")
    assert excinfo.value.exit_code == EXIT_USAGE
    assert "--yes" in excinfo.value.next_step


def test_confirm_flag_equivalent_short_circuits_without_prompting() -> None:
    def _explode(_prompt: str) -> str:  # pragma: no cover - must never run
        raise AssertionError("prompted despite the flag")

    assert confirm("覆盖?", assume_yes=True, is_tty=True, flag_name="--yes", reader=_explode) is True


def test_confirm_interactive_reads_answer() -> None:
    assert confirm("覆盖?", assume_yes=False, is_tty=True, flag_name="--yes", reader=lambda _p: "y") is True
    assert confirm("覆盖?", assume_yes=False, is_tty=True, flag_name="--yes", reader=lambda _p: "n") is False


def _boom(_args, _emitter) -> int:
    raise RuntimeError("kaboom")


def test_unexpected_exception_exits_1_with_traceback_only_in_verbose() -> None:
    err = io.StringIO()
    code = run(["login", "http://p.test"], handlers={"login": _boom}, stdout=io.StringIO(), stderr=err)
    assert code == EXIT_INTERNAL
    assert "Traceback" not in err.getvalue()

    verbose_err = io.StringIO()
    run(
        ["--verbose", "login", "http://p.test"],
        handlers={"login": _boom},
        stdout=io.StringIO(),
        stderr=verbose_err,
    )
    assert "Traceback" in verbose_err.getvalue()


def test_result_event_emitted_even_on_exception() -> None:
    out = io.StringIO()
    run(["--json", "login", "http://p.test"], handlers={"login": _boom}, stdout=out, stderr=io.StringIO())
    events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert events[-1]["event"] == "result"
    assert events[-1]["ok"] is False and events[-1]["exit_code"] == EXIT_INTERNAL


def test_cli_error_from_handler_is_rendered_with_code_and_next_step() -> None:
    def _fail(_args, _emitter) -> int:
        raise CliError("坏了", exit_code=6, code=16203, next_step="检查包根")

    err = io.StringIO()
    code = run(["login", "http://p.test"], handlers={"login": _fail}, stdout=io.StringIO(), stderr=err)
    assert code == 6
    text = err.getvalue()
    assert "16203" in text and "检查包根" in text


def test_successful_handler_emits_single_result_and_returns_its_code() -> None:
    out = io.StringIO()
    code = run(
        ["--json", "logs"],
        handlers={"logs": lambda _a, _e: 0},
        stdout=out,
        stderr=io.StringIO(),
    )
    assert code == 0
    events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert [e["event"] for e in events].count("result") == 1


def test_no_subcommand_is_usage_error() -> None:
    assert run([], stdout=io.StringIO(), stderr=io.StringIO()) == EXIT_USAGE


def test_main_is_the_console_script_entry_point() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == EXIT_USAGE
