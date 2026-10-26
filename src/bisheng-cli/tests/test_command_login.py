"""T019 — `bisheng login`: probe, whoami, delegate refusal, credential write.

Two things about this file are worth knowing before changing it.

**The delegate cases can only ever be mocked.** F049 deliberately does not
register the `delegate` scope (`open_api/domain/scopes.py` NOTE: "ships with
F050"), so no key that exists today can carry it. Going to 114 to "verify AC-09"
proves nothing and will be read as "the feature does not work".

**`26002` covers four causes with one code.** Unknown, revoked and expired keys
are indistinguishable on the wire — and so is a disabled or deleted service
account, which the beta2 server folds into the same code
(`credential_validator.resolve_service_account`) instead of the separate `26027`
F049 used to raise here. The server sends no signal that separates them, so the
CLI must not pretend to: what this file asserts is that `26001` and `26002` read
differently, and that `26002` names the disabled-account case rather than
telling the developer to go get yet another key.
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
    DEFAULT_PACKS,
    FAKE_KEY,
    FAKE_PAT,
    PlatformMock,
    env_ok,
    serve_default_packs,
    skills_path,
    use_mock_transport,
    versions_404,
    versions_ok,
    whoami_err,
    whoami_ok,
    whoami_without_resource_owner,
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
        # packs so the happy path exercises the real end-to-end shape; failure
        # tests never reach these routes because login raises before the sync.
        serve_default_packs(mock)
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
    mock = _mock(whoami_ok(resource_owner={"user_id": 7}))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    # AC-06: platform address, the account name and its resource owner. The
    # owner reaches the CLI as an id and nothing else (`WhoamiResourceOwner` has
    # exactly one field), so an id is what gets printed — inventing a name here
    # would be inventing it about the person who ends up owning every app.
    for expected in (BASE, "问卷小队开发号", "用户 #7", "2026-12-31"):
        assert expected in err

    stored = json.loads((home_dir / ".bisheng" / "credentials.json").read_text(encoding="utf-8"))
    profile = stored["profiles"][BASE]
    assert stored["current"] == BASE
    assert profile["api_key"] == FAKE_KEY
    assert profile["resource_owner"] == {"user_id": 7}
    assert (profile["actor_kind"], profile["actor_id"], profile["actor_name"]) == (
        "service_account",
        123,
        "问卷小队开发号",
    )
    # AC-52: a cached scope set can only ever produce "the admin ticked the box
    # but the CLI still says no".
    assert "scopes" not in profile


def test_personal_token_is_not_reported_as_a_service_account(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    """A `bs-pat-` token authenticates on the same endpoint and answers `natural_person`.

    The CLI asks for a service-account key but cannot stop anyone pasting the
    other kind, and beta2 accepts it (`credential_validator._TOKEN_RE`). Printing
    its holder under "服务账号" would name the wrong subject entirely.
    """
    mock = _mock(whoami_ok(actor_kind="natural_person", actor_id=7, actor_name="李开发", scopes=[]))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_PAT], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    assert "个人访问令牌" in err and "李开发" in err
    assert "服务账号: 李开发" not in err


def test_login_says_so_when_the_key_has_no_resource_owner(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # `resource_owner` is nullable on the wire, and a credential in that state
    # cannot publish anything: `resource_owner_of()` refuses the first deploy
    # with 16205 rather than creating an application owned by nobody. Login is
    # where that is cheap to say — ten minutes before the deploy that fails.
    mock = _mock(whoami_without_resource_owner())
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_OK
    assert "资源归属人" in err and "服务账号详情页" in err
    assert "deploy" in err


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


def test_delegate_key_is_refused_at_whoami_not_dropped_as_an_unknown_code(
    monkeypatch: pytest.MonkeyPatch, home_dir
) -> None:
    """The path a real delegate key takes, which the scope check never sees.

    `whoami` requires no scope, so the platform's entrance gate lets the call
    through and the delegation resolver answers `26016` — `login` never gets a
    scope list to check. Unregistered, that code fell through to exit 19
    ("平台返回未登记的错误码 26016"), which is neither the right verdict nor a
    diagnosis anyone can act on.
    """
    mock = _mock(whoami_err(26016, "X-On-Behalf-Of is required for a delegated credential"))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)

    assert code == EXIT_FORBIDDEN
    assert "委托" in err and "另外签发" in err
    # The platform's own sentence still gets printed verbatim ("三部分，缺一不可"),
    # but it must not be what the CLI tells the caller to act on: the CLI sends
    # no identity headers, on any command, so adding one is not available.
    assert "下一步: 请平台管理员另外签发" in err
    assert not (home_dir / ".bisheng" / "credentials.json").exists()


def test_malformed_header_and_rejected_key_are_distinguishable(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    """26001 and 26002 are the two the runtime path can actually produce.

    A disabled service account used to arrive as its own code (26027). On the
    beta2 server `resolve_service_account` raises `OpenApiCredentialInvalidError`
    for it — 26002 — so that is the code whose copy has to carry the case; 26027
    survives only on the management face, which no CLI command calls.
    """
    messages: dict[int, str] = {}
    for code in (26001, 26002):
        mock = _mock(whoami_err(code, f"server text {code}"))
        exit_code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
        assert exit_code == EXIT_AUTH
        messages[code] = err

    assert messages[26001] != messages[26002]
    assert "Authorization" in messages[26001]
    # Re-issuing a key is no longer the whole answer: for a disabled account the
    # new key is exactly as dead as the old one.
    assert "停用" in messages[26002] and "重新签发" in messages[26002]


def test_personal_token_rejections_are_not_generic_permission_errors(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # Unregistered, 26040 fell through to "ask your admin about the permission
    # bits" (HTTP 403) and 26043 to "check whether the key expired" (401) —
    # both point away from the cause, which is the credential *kind*.
    for code, expected_exit in ((26040, EXIT_FORBIDDEN), (26043, EXIT_AUTH)):
        mock = _mock(whoami_err(code, f"server text {code}"))
        exit_code, _, err = _run(["login", BASE, "--api-key", FAKE_PAT], monkeypatch=monkeypatch, mock=mock)
        assert exit_code == expected_exit
        assert "个人" in err and "bs-sak-" in err


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
    mock = _mock(whoami_ok())
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
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert [path for path in mock.paths_called() if "skills" in path] == [skills_path(p) for p in DEFAULT_PACKS]
    slug = skills_mod.profile_slug(BASE)
    for pack in DEFAULT_PACKS:
        assert (home_dir / ".bisheng" / "skills" / slug / pack / "SKILL.md").is_file()
    # Where it landed must be on screen. Login used to sync in silence, which is
    # how "5 个文件已同步" could be true while nothing could read them.
    assert "技能包落点" in err


def test_login_refuses_platform_flag(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # `login` names its platform positionally; accepting `--platform` as well
    # would leave two addresses in one command and no way to tell which one the
    # key was verified against.
    mock = PlatformMock()
    code, _, err = _run(
        ["--platform", "http://other.test", "login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_USAGE
    assert "--platform" in err
    assert mock.paths_called() == []


def test_login_still_succeeds_when_auto_sync_fails(monkeypatch: pytest.MonkeyPatch, home_dir) -> None:
    # The sync is best-effort: if the pack endpoint 404s, login still succeeds
    # and points the developer at a manual retry.
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok())
    mock.get(skills_path(), httpx.Response(404, json={"detail": "Not Found"}))
    code, _, err = _run(["login", BASE, "--api-key", FAKE_KEY], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert "skills sync" in err
