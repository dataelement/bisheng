"""T044 — `bisheng dev`: pre-checks in order, then a wired local run.

The refusal cases are the interesting contract (AC-29 / AC-51 / AC-53): each
one has to stop *before* the next step happens — no request without a
credential, no start without a manifest, no process without a platform that
accepts the key — and say which step failed. The happy path is exercised twice:
with the process and session replaced by fakes (what gets printed, AC-24), and
once for real against a stdlib echo app (what actually reaches the app).
"""

from __future__ import annotations

import http.client
import io
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest

from bisheng_cli import credentials, devdb, project
from bisheng_cli.commands import dev as dev_mod
from bisheng_cli.errors import (
    EXIT_AUTH,
    EXIT_LOCAL_INVALID,
    EXIT_NOT_ENABLED,
    EXIT_NOT_LOGGED_IN,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
)
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import (
    FAKE_KEY,
    FAKE_KEY_MASK,
    PlatformMock,
    env_ok,
    use_mock_transport,
    versions_404,
    versions_ok,
    whoami_err,
    whoami_ok,
)

BASE = "http://platform.test"
WHOAMI = "/api/v2/auth/whoami"
VERSIONS = "/api/v1/dev-toolkit/versions"
FIXTURES = Path(__file__).parent / "fixtures"

# Captured at import, before conftest's `no_network` replaces it: the one test
# that talks to a real child process on loopback puts it back for the proxy's
# upstream hop. The platform side of that test stays mocked.
_REAL_HANDLE_REQUEST = httpx.HTTPTransport.handle_request


@pytest.fixture
def logged_in(home_dir) -> None:
    credentials.save_profile(
        BASE,
        {"api_key": FAKE_KEY, "key_mask": FAKE_KEY_MASK, "actor_kind": "service_account", "actor_name": "旧名字"},
    )


@pytest.fixture
def echo_project(tmp_path: Path) -> Path:
    root = tmp_path / "echo"
    shutil.copytree(FIXTURES / "echo_app", root)
    return root


class _FakeProcess:
    """A Popen stand-in that never exits on its own."""

    def __init__(self) -> None:
        self.signals: list[int] = []
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def kill(self) -> None:
        self.returncode = -9


def _fake_launch(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace the process + the blocking session; capture what `dev` handed them."""
    captured: dict = {}

    def spawn(start, root, env):
        captured["start"], captured["root"], captured["env"] = start, root, env
        captured["process"] = _FakeProcess()
        return captured["process"]

    def session(process, proxy, emitter):
        captured["proxy_url"] = proxy.url
        return EXIT_OK

    monkeypatch.setattr(dev_mod, "spawn_app", spawn)
    monkeypatch.setattr(dev_mod, "run_session", session)
    return captured


def _run(argv: list[str], *, monkeypatch: pytest.MonkeyPatch, mock: PlatformMock) -> tuple[int, str, str]:
    use_mock_transport(monkeypatch, dev_mod, mock)
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _free_port() -> int:
    return devdb.pick_free_port()


# ---- refusals, in pre-check order ---------------------------------------------


def test_not_logged_in_exits_3_with_zero_requests(
    monkeypatch: pytest.MonkeyPatch, home_dir, echo_project: Path
) -> None:
    captured = _fake_launch(monkeypatch)
    mock = PlatformMock()
    code, _, err = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_LOGGED_IN
    assert "bisheng login" in err
    assert mock.paths_called() == [] and "process" not in captured


def test_missing_manifest_field_exits_6_naming_it_before_any_request(
    monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path
) -> None:
    captured = _fake_launch(monkeypatch)
    (echo_project / "bisheng-app.yaml").write_text("name: x\nruntime: python3.11\n", encoding="utf-8")
    mock = PlatformMock()
    code, _, err = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert "port" in err and "缺少必填项" in err
    assert mock.paths_called() == [] and "process" not in captured


def test_missing_manifest_file_exits_6(monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path) -> None:
    _fake_launch(monkeypatch)
    (echo_project / "bisheng-app.yaml").unlink()
    code, _, err = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=PlatformMock())
    assert code == EXIT_LOCAL_INVALID
    assert "bisheng-app.yaml" in err


def test_invalid_key_exits_4_and_starts_nothing(monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path) -> None:
    captured = _fake_launch(monkeypatch)
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_err(26002))
    code, _, err = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_AUTH
    assert "26002" in err
    assert "process" not in captured
    assert not (echo_project / ".bisheng" / "dev").exists()


def test_platform_unreachable_exits_7(monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path) -> None:
    captured = _fake_launch(monkeypatch)
    mock = PlatformMock().get(VERSIONS, httpx.ConnectError("refused"))
    code, _, err = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_UNREACHABLE
    assert "不可达" in err and "process" not in captured


def test_layer_absent_exits_8_before_the_key_is_sent(
    monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path
) -> None:
    _fake_launch(monkeypatch)
    mock = PlatformMock().get(VERSIONS, versions_404()).get("/api/v1/env", env_ok(open_platform_enabled=False))
    code, _, _ = _run(["dev", str(echo_project)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_NOT_ENABLED
    assert WHOAMI not in mock.paths_called()


def test_no_scope_check_at_all(monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path) -> None:
    # AC-29: a key with no permission bit ticked still runs the app locally.
    _fake_launch(monkeypatch)
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok(scopes=[]))
    code, _, _ = _run(["dev", str(echo_project), "--port", str(_free_port())], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK


def test_same_port_for_proxy_and_app_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path
) -> None:
    captured = _fake_launch(monkeypatch)
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok())
    code, _, _ = _run(
        ["dev", str(echo_project), "--port", "9000", "--app-port", "9000"], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_USAGE and "process" not in captured


# ---- happy path: what is printed and what is injected --------------------------


def test_output_names_identity_source_platform_and_local_url_never_the_key(
    monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path
) -> None:
    captured = _fake_launch(monkeypatch)
    project.save_app_ref(echo_project, BASE, app_id="app-42")
    port = _free_port()
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok(actor_name="问卷小队开发号"))
    code, out, err = _run(
        ["dev", str(echo_project), "--port", str(port), "--json", "--verbose"], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_OK
    # AC-24: the *fresh* whoami name, the platform, the local URL.
    assert "问卷小队开发号" in err and "旧名字" not in err
    assert BASE in err and f"http://127.0.0.1:{port}" in err
    assert "服务账号" in err
    assert FAKE_KEY not in err and FAKE_KEY not in out

    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    ready = next(e for e in events if e["event"] == "stage" and e["stage"] == "ready")
    assert ready["data"]["local_url"] == f"http://127.0.0.1:{port}" == captured["proxy_url"]
    assert ready["data"]["app_id"] == "app-42" and ready["data"]["actor_name"] == "问卷小队开发号"
    assert events[-1]["event"] == "result" and events[-1]["ok"] is True

    env = captured["env"]
    assert env["BISHENG_APP_ID"] == "app-42" and env["BISHENG_APP_SLUG"] == "echo"
    assert env["PORT"] == env["BISHENG_APP_PORT"] == str(ready["data"]["app_port"]) != str(port)
    assert env["BISHENG_APP_DB_PATH"] == str(echo_project / ".bisheng" / "dev" / "app.db")
    assert "BISHENG_API_KEY" not in env and FAKE_KEY not in "".join(env.values())
    assert captured["start"].source == "main.py" and captured["root"] == echo_project.resolve()
    # Teardown stopped the process.
    assert captured["process"].signals


def test_no_as_or_identity_override_on_dev() -> None:
    from bisheng_cli.cli import build_parser

    parser = build_parser()
    dev = next(sub for name, sub in _subparsers(parser) if name == "dev")
    options = {s for a in dev._actions for s in a.option_strings}
    assert "--as" not in options
    assert not [o for o in options if "user" in o or "behalf" in o or "impersonat" in o]


def _subparsers(parser):
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            yield from action.choices.items()


def test_platform_flag_selects_the_profile_for_dev(
    monkeypatch: pytest.MonkeyPatch, home_dir, echo_project: Path
) -> None:
    captured = _fake_launch(monkeypatch)
    other = "http://other.test"
    credentials.save_profile(BASE, {"api_key": FAKE_KEY})
    credentials.save_profile(other, {"api_key": FAKE_KEY})  # current
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok())
    code, _, err = _run(
        ["dev", str(echo_project), "--platform", BASE, "--port", str(_free_port())], monkeypatch=monkeypatch, mock=mock
    )
    assert code == EXIT_OK
    assert captured["env"]["BISHENG_PLATFORM_API_BASE"] == BASE
    assert BASE in err


def test_app_that_exits_is_reported_as_exit_6(monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path) -> None:
    class _Crashing(_FakeProcess):
        def poll(self):
            return 1

    monkeypatch.setattr(dev_mod, "spawn_app", lambda start, root, env: _Crashing())
    monkeypatch.setattr(dev_mod.time, "sleep", lambda s: None)
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok())
    code, _, err = _run(["dev", str(echo_project), "--port", str(_free_port())], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_LOCAL_INVALID
    assert "16228" in err


# ---- the real thing: a stdlib app behind the proxy -----------------------------


def test_end_to_end_headers_and_env_reach_a_real_app(
    monkeypatch: pytest.MonkeyPatch, logged_in, echo_project: Path
) -> None:
    """Spawn the echo app for real; the session body makes one request through the proxy."""
    # The proxy's upstream hop is a real loopback connection to the child
    # process; the platform mock stays on the command module's client.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _REAL_HANDLE_REQUEST)
    port = _free_port()
    seen: dict = {}

    def session(process, proxy, emitter):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", proxy.listen_port, timeout=3)
                conn.request("GET", "/echo?q=1", headers={"X_BiSheng_User_Id": "forged", "X-Custom": "kept"})
                response = conn.getresponse()
                if response.status == 200:
                    seen.update(json.loads(response.read()))
                    conn.close()
                    return EXIT_OK
                conn.close()
            except OSError:
                pass
            time.sleep(0.2)
        raise AssertionError("the echo app never answered through the proxy")

    monkeypatch.setattr(dev_mod, "run_session", session)
    mock = PlatformMock().get(VERSIONS, versions_ok()).get(WHOAMI, whoami_ok(actor_id=123, tenant_id=7))
    code, _, _ = _run(["dev", str(echo_project), "--port", str(port)], monkeypatch=monkeypatch, mock=mock)
    assert code == EXIT_OK
    assert seen["path"] == "/echo?q=1"
    headers = seen["headers"]
    assert headers["x-bisheng-user-id"] == "123" and headers["x-bisheng-tenant-id"] == "7"
    assert headers["x-bisheng-subject-kind"] == "service_account"
    assert headers["x-custom"] == "kept"
    assert headers["x-bisheng-access-token"].startswith("bsdev.")
    assert "x-bisheng-dept-id" not in headers
    env = seen["env"]
    assert env["BISHENG_APP_BASE_PATH"] == "" and env["BISHENG_PLATFORM_API_BASE"] == BASE
    assert env["PORT"] == env["BISHENG_APP_PORT"] and env["PORT"] != str(port)
    assert "BISHENG_API_KEY" not in env and FAKE_KEY not in json.dumps(seen)
    assert (echo_project / ".bisheng" / "dev" / "app.db").is_file()
