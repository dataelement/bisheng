"""T019 — `bisheng login`: probe, whoami, delegate refusal, credential write.

Two things about this file are worth knowing before changing it.

**The delegate cases can only ever be mocked.** F049 deliberately does not
register the `delegate` scope (`open_api/domain/scopes.py` NOTE: "ships with
F050"), so no key that exists today can carry it. Going to 114 to "verify AC-09"
proves nothing and will be read as "the feature does not work".

**`26002` covers three causes with one code.** Unknown, revoked and expired keys
are indistinguishable on the wire — the server sends no signal that separates
them. What is assertable, and what this file asserts, is that `26001` / `26002` /
`26027` read differently, because their next steps differ (fix how you pass the
key / get a new key / have the account re-enabled).
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import httpx
import pytest

from bisheng_cli.commands import login as login_mod
from bisheng_cli.commands import skills as skills_mod
from bisheng_cli.errors import (
    EXIT_AUTH,
    EXIT_FORBIDDEN,
    EXIT_NOT_ENABLED,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    CliError,
)
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import (
    FAKE_KEY,
    PlatformMock,
    env_ok,
    skill_pack,
    skills_path,
    use_mock_transport,
    versions_404,
    versions_ok,
    whoami_err,
    whoami_ok,
)

BASE = "http://platform.test"
WHOAMI = "/api/v2/auth/whoami"
VERSIONS = "/api/v1/dev-toolkit/versions"


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own `BISHENG_API_KEY` must not leak into the suite."""
    monkeypatch.delenv("BISHENG_API_KEY", raising=False)


def _mock(whoami: httpx.Response | None = None) -> PlatformMock:
    mock = PlatformMock().get(VERSIONS, versions_ok())
    if whoami is not None:
        mock.get(WHOAMI, whoami)
        # A successful login now auto-syncs the skill packs (AC-08). Serve the
        # pack so the happy path exercises the real end-to-end shape; failure
        # tests never reach this route because login raises before the sync.
        mock.get(skills_path(), skill_pack())
    return mock


def _run(argv: list[str], *, monkeypatch: pytest.MonkeyPatch, mock: PlatformMock) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, login_mod, mock)
    # login's auto-sync builds its client inside the skills module, so that name
    # needs the mock transport too.
    use_mock_transport(monkeypatch, skills_mod, mock)
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_success_writes_profile_and_prints_platform_account_owner_mask_expiry(
    monkeypatch: pytest.MonkeyPatch, home_dir
) -> None:
    mock = _mock(whoami_ok(resource_owner={"user_id": 7, "user_name": "李开发"}))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    for expected in (BASE, "问卷小队开发号", "李开发", "2026-12-31"):
        assert expected in err

    stored = json.loads((home_dir / ".bisheng" / "credentials.json").read_text(encoding="utf-8"))
    profile = stored["profiles"][BASE]
    assert stored["current"] == BASE
    assert profile["api_key"] == FAKE_KEY
    assert profile["resource_owner"] == {"user_id": 7, "user_name": "李开发"}
    # AC-52: a cached scope set can only ever produce "the admin ticked the box
    # but the CLI still says no".
    assert "scopes" not in profile


def test_success_without_resource_owner_field_degrades_with_explicit_hint(
    monkeypatch: pytest.MonkeyPatch, home_dir
) -> None:
    # F049 sends `resource_owner` as of 2026-08-17, so this covers what is left:
    # an older platform that predates the field, and an owner row that stopped
    # resolving (the server reports null rather than failing the probe).
    # Saying so out loud beats omitting the line: the owner is the account that
    # will end up owning every app this key deploys, and a wrong one is only
    # discovered much later.
    mock = _mock(whoami_ok())
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    assert "资源归属人" in err and "服务账号详情页" in err


def test_no_scope_check_at_all(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # whoami is the one endpoint under /api/v2 that requires no scope at all;
    # login must not add a client-side check the server does not make.
    mock = _mock(whoami_ok(scopes=[]))
    code, _, _ = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK


def test_delegate_scope_refused_before_writing_credentials(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    mock = _mock(whoami_ok(scopes=["delegate", "app:manage"]))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_FORBIDDEN
    assert "委托" in err
    assert not (home_dir / ".bisheng" / "credentials.json").exists()


def test_delegate_refusal_is_not_a_silent_fallback_to_mode_s(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # INV-31: the channel entry point rejects by scope. Degrading to "well, it
    # still works as a plain key" is the failure mode the invariant exists for.
    mock = _mock(whoami_ok(scopes=["delegate"]))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code != EXIT_OK
    assert "登录成功" not in err


def test_delegate_refusal_is_not_a_bare_param_error(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    mock = _mock(whoami_ok(scopes=["delegate"]))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_FORBIDDEN and code != EXIT_USAGE
    assert "本地开发" in err or "另外签发" in err


def test_missing_invalid_and_inactive_account_are_distinguishable(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    messages: dict[int, str] = {}
    for code in (26001, 26002, 26027):
        mock = _mock(whoami_err(code, f"server text {code}"))
        exit_code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
        assert exit_code == EXIT_AUTH
        messages[code] = err

    assert len(set(messages.values())) == 3
    assert "Authorization" in messages[26001]
    assert "重新签发" in messages[26002]
    assert "启用" in messages[26027] and "换一把密钥没有用" in messages[26027]


def test_platform_unreachable_and_layer_absent_are_distinguishable(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    absent = PlatformMock().get(VERSIONS, versions_404()).get("/api/v1/env", env_ok(open_platform_enabled=False))
    code, _, _ = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=absent)
    assert code == EXIT_NOT_ENABLED
    # The probe decides before any credential leaves the machine.
    assert WHOAMI not in absent.paths_called()

    unreachable = PlatformMock().get(VERSIONS, httpx.ConnectError("refused"))
    code, _, _ = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=unreachable)
    assert code == EXIT_UNREACHABLE
    assert WHOAMI not in unreachable.paths_called()


def test_key_from_flag_env_stdin_tty_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin_key = FAKE_KEY + "stdin"
    env_key = FAKE_KEY + "env"

    def args(**kw):
        return SimpleNamespace(**{"api_key": None, "api_key_stdin": False, **kw})

    monkeypatch.setenv("BISHENG_API_KEY", env_key)
    # 1. the flag beats everything
    assert login_mod.resolve_api_key(args(api_key=FAKE_KEY, api_key_stdin=True), stdin=io.StringIO(stdin_key)) == (
        FAKE_KEY
    )
    # 2. the environment beats stdin
    assert login_mod.resolve_api_key(args(api_key_stdin=True), stdin=io.StringIO(stdin_key)) == env_key
    monkeypatch.delenv("BISHENG_API_KEY")
    # 3. stdin beats the prompt
    assert login_mod.resolve_api_key(args(api_key_stdin=True), stdin=io.StringIO(stdin_key)) == stdin_key

    # 4. a TTY with none of the above gets asked
    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert login_mod.resolve_api_key(args(), stdin=_Tty(), prompt=lambda _p: FAKE_KEY) == FAKE_KEY

    # 5. nothing at all, and nobody to ask: a refusal, never a blank key
    with pytest.raises(CliError) as excinfo:
        login_mod.resolve_api_key(args(), stdin=io.StringIO())
    assert excinfo.value.exit_code == EXIT_USAGE


def test_key_never_echoed_in_any_output(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    mock = _mock(whoami_ok(resource_owner={"user_id": 7, "user_name": "李开发"}))
    code, out, err = _run(
        ["--verbose", "--json", "login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_OK
    assert FAKE_KEY not in out and FAKE_KEY not in err
    assert "Bearer" not in out


def test_relogin_overwrites_same_platform_profile(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    second_key = FAKE_KEY + "2"
    _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=_mock(whoami_ok()))
    _run(["login", BASE + "/", "--api-key", second_key], monkeypatch=monkeypatch, mock=_mock(whoami_ok()))

    stored = json.loads((home_dir / ".bisheng" / "credentials.json").read_text(encoding="utf-8"))
    # A trailing slash must not fork the profile — that is how "logged in but the
    # next command says otherwise" happens.
    assert list(stored["profiles"]) == [BASE]
    assert stored["profiles"][BASE]["api_key"] == second_key


def test_login_auto_syncs_skill_packs(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # AC-08 (T039): a successful login pulls the skill packs so a first-time
    # developer never has to know `skills sync` exists.
    mock = _mock(whoami_ok())
    code, _, _ = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert [path for path in mock.paths_called() if "skills" in path] == [skills_path()]
    assert (home_dir / ".bisheng" / "skills" / "deploy-hosting" / "SKILL.md").is_file()


def test_login_still_succeeds_when_auto_sync_fails(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # The sync is best-effort: if the pack endpoint 404s, login still succeeds
    # and points the developer at a manual retry.
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok())
    mock.get(skills_path(), httpx.Response(404, json={"detail": "Not Found"}))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "skills sync" in err
