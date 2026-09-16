"""T045 — platform-capability calls under `bisheng dev` (AC-28 / AC-49).

The decision this pins is 决议-3: the mini proxy injects identity and
environment and **does not proxy** the application's calls to the platform. An
app under `dev` dials `/api/v2` itself, with the credential the developer logged
in with, so the scope check and the visibility filtering are the platform's —
the same code a hosted app meets. The platform-side half of that claim is
`src/backend/test/dev_toolkit/test_dev_capability_parity.py`; this file pins the
CLI half.

Three ways it could quietly stop being true, one test each:

* the proxy grows a rule that forwards `/api/v2/**` to the platform — then a
  local call would carry whatever the proxy decided to attach, and the two
  environments would diverge exactly where nobody looks;
* the proxy attaches the login credential to a forwarded request — the key would
  reach the application through a second door, and `dev` would be granting what
  the environment is supposed to grant;
* `dev` starts checking scopes before it will run — AC-29 says it must not, and
  a CLI-side check is a second, always-stale copy of the platform's answer.
"""

from __future__ import annotations

import inspect
import io
from pathlib import Path

import httpx

from bisheng_cli import devdb, devproxy
from bisheng_cli.commands import dev as dev_command
from bisheng_cli.devproxy import DevIdentity, DevProxy, HandleMinter
from tests.helpers.platform_mock import FAKE_KEY, FAKE_MODEL_BASE_URL

PLATFORM = "http://platform.test"

CAPABILITY_PATHS = (
    "/api/v2/model/v1/chat/completions",
    "/api/v2/model/v1/models",
    "/api/v2/mcp",
    "/api/v2/filelib/retrieve",
    "/api/v2/auth/whoami",
)


def _identity() -> DevIdentity:
    return DevIdentity.from_whoami(
        {"actor_kind": "service_account", "actor_id": 123, "actor_name": "问卷小队开发号", "tenant_id": 1},
        app_id="app-1",
    )


def _proxy(seen: list[httpx.Request]) -> DevProxy:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    identity = _identity()
    return DevProxy(
        identity=identity,
        minter=HandleMinter(identity),
        app_port=51234,
        listen_port=0,
        transport=httpx.MockTransport(handler),
    )


def test_a_capability_path_goes_to_the_app_not_to_the_platform() -> None:
    """Every request the proxy sees is forwarded to the app, whatever its path.

    The proxy has exactly one upstream. A path that *looks* like a platform API
    is just a path the application chose to serve; routing it anywhere else
    would mean the app could never own its own `/api/**` namespace either.
    """
    seen: list[httpx.Request] = []
    proxy = _proxy(seen)
    try:
        for path in CAPABILITY_PATHS:
            proxy.forward("POST", path, [("Content-Type", "application/json")], b"{}")
    finally:
        proxy.stop()

    assert [str(request.url) for request in seen] == [f"http://127.0.0.1:51234{path}" for path in CAPABILITY_PATHS]
    assert not [request for request in seen if PLATFORM in str(request.url)]


def test_the_proxy_never_attaches_the_login_credential() -> None:
    """Not under `Authorization`, not under any other name.

    The application's own `Authorization` header is passed through untouched (it
    is the app's request to make), but the proxy adds none of its own: the
    credential reaches the process through the environment, which is what the
    hosted runtime does too.
    """
    seen: list[httpx.Request] = []
    proxy = _proxy(seen)
    try:
        proxy.forward(
            "GET",
            "/api/v2/model/v1/models",
            [("Authorization", f"Bearer {FAKE_KEY}")],
            b"",
        )
    finally:
        proxy.stop()

    request = seen[0]
    # Passed through exactly once — relayed, not duplicated or replaced.
    assert request.headers.get_list("authorization") == [f"Bearer {FAKE_KEY}"]

    # And with no inbound credential, nothing appears.
    seen.clear()
    proxy = _proxy(seen)
    try:
        proxy.forward("GET", "/api/v2/model/v1/models", [], b"")
    finally:
        proxy.stop()
    assert "authorization" not in seen[0].headers
    assert FAKE_KEY not in str(seen[0].headers)


def test_the_proxy_module_states_that_it_does_not_proxy_capability_calls() -> None:
    """决议-3 written where the next editor will read it, not only in the spec."""
    source = inspect.getsource(devproxy)
    assert "proxy platform-capability calls" in source
    assert "决议-3" in source


def test_dev_never_reads_the_scopes_whoami_reported() -> None:
    """AC-29 / AC-52: a key with nothing ticked still runs the app locally.

    What that key can *do* is answered per call, by the platform. A CLI-side
    scope check would be a second copy of an answer that can change between two
    calls (the platform's cache upper bound is three seconds), and `dev` would
    start refusing to run code that the platform would happily serve.
    """
    source = inspect.getsource(dev_command)
    for read in ('whoami.get("scopes")', 'whoami["scopes"]', '"scopes"]'):
        assert read not in source, f"`dev` reads {read} — it must not judge permissions"


def test_the_model_face_is_wired_from_whoami_not_from_a_composed_url() -> None:
    """AC-27: the CLI never spells `/api/v2/model/v1` itself (F051 AC-30).

    A composed address is right until a deployment sits behind a path prefix or
    a gateway, and then it is wrong in a way only that customer can see.
    """
    for module in (dev_command, devdb):
        assert "/api/v2/model/v1" not in inspect.getsource(module)
    assert "model_base_url" in inspect.getsource(dev_command)


def test_dev_reports_the_model_address_without_ever_printing_the_key(sample_project: Path) -> None:
    """AC-24 / AC-04: the developer is told where model calls go, never the key."""
    from bisheng_cli import credentials
    from bisheng_cli.output import Emitter

    # Human-readable output is on stderr by design (stdout stays parseable).
    out = io.StringIO()
    emitter = Emitter(stdout=io.StringIO(), stderr=out)
    profile = credentials.Profile(base_url=PLATFORM, api_key=FAKE_KEY, actor_name="问卷小队开发号")
    identity = _identity()
    db = devdb.prepare_dev_db(sample_project)
    start = devdb.StartCommand(argv=["python", "main.py"], source="main.py")

    dev_command._report(
        emitter,
        profile,
        {"actor_kind": "service_account", "actor_name": "问卷小队开发号"},
        identity,
        "http://127.0.0.1:8080",
        51234,
        db,
        start,
        FAKE_MODEL_BASE_URL,
    )
    printed = out.getvalue()
    assert FAKE_MODEL_BASE_URL in printed
    assert "OPENAI_BASE_URL" in printed
    assert FAKE_KEY not in printed

    out2 = io.StringIO()
    dev_command._report(
        Emitter(stdout=io.StringIO(), stderr=out2),
        profile,
        {"actor_kind": "service_account", "actor_name": "问卷小队开发号"},
        identity,
        "http://127.0.0.1:8080",
        51234,
        db,
        start,
        "",
    )
    # No model face: say so, rather than leaving the developer to discover it
    # through a 404 from a client library.
    assert "没有部署模型协议面" in out2.getvalue()
    assert FAKE_KEY not in out2.getvalue()
