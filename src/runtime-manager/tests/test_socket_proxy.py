"""T078 — the docker-socket-proxy endpoint whitelist (D2-B).

D2 chose "直连 dockerd 作 MVP，socket-proxy 紧随其后" on the strength of one
claim: the switch costs *a base URL and nothing else*. That claim is only true
while the whitelist and the backend protocol agree, and they agree in exactly
one place — :data:`runtime_manager.docker_backend.SOCKET_PROXY_PERMISSIONS`.

So this file asserts the two directions of that agreement:

* every method the manager can call is covered by a flag that is **on**, so
  adding one without widening the proxy fails here rather than on a customer's
  host with an opaque 403 folded into 16121「编排器不可用」;
* every flag that is **off** is off on purpose, and the ones that would hand
  back the root-equivalence D2-B exists to remove (``EXEC`` above all) can never
  drift on silently.

The proxy container itself — that it answers, that it really refuses ``/exec`` —
needs a daemon and carries ``@pytest.mark.docker``.
"""

from __future__ import annotations

import subprocess

import pytest

from runtime_manager.docker_backend import (
    SOCKET_PROXY_DENIED,
    SOCKET_PROXY_PERMISSIONS,
    protocol_methods,
    socket_proxy_env,
)


def test_every_backend_method_is_covered_by_an_enabled_permission():
    """The lockstep that makes "D2-A → D2-B is a base URL" stay true."""
    covered = {method for methods in SOCKET_PROXY_PERMISSIONS.values() for method in methods}
    missing = sorted(set(protocol_methods()) - covered)
    assert not missing, (
        f"{missing} would be called through the socket proxy with no endpoint permission — "
        f"the call answers 403 and the platform reports 编排器不可用 with a healthy daemon behind it"
    )


def test_the_whitelist_names_no_method_that_does_not_exist():
    """A stale entry is a widened proxy nobody notices, so it fails here too."""
    stray = sorted({m for methods in SOCKET_PROXY_PERMISSIONS.values() for m in methods} - set(protocol_methods()))
    assert not stray


def test_every_write_method_is_also_under_the_global_post_gate():
    """The proxy is read-only unless ``POST=1``; a write not listed there 403s."""
    writes = {
        "create_container",
        "start_container",
        "stop_container",
        "remove_container",
        "build_image",
        "remove_image",
    }
    assert writes <= set(SOCKET_PROXY_PERMISSIONS["POST"])


def test_exec_is_denied_because_it_is_the_whole_point():
    """``/exec`` is arbitrary code in any container on the host."""
    assert "EXEC" in SOCKET_PROXY_DENIED
    assert socket_proxy_env()["EXEC"] == "0"


def test_the_denied_and_allowed_sets_do_not_overlap():
    assert not set(SOCKET_PROXY_DENIED) & set(SOCKET_PROXY_PERMISSIONS)


def test_restarts_stay_with_the_reconciler_not_with_the_proxy():
    """contracts §8: an exited instance is ``start``ed, never ``restart``ed —
    a restart loses the daemon's own exponential backoff."""
    assert socket_proxy_env()["ALLOW_RESTARTS"] == "0"


def test_volumes_are_denied_because_instances_use_binds():
    assert socket_proxy_env()["VOLUMES"] == "0"


def test_the_environment_spells_out_every_flag_including_the_zeros():
    """Relying on the image's defaults would let a new image version widen us."""
    env = socket_proxy_env()
    assert set(env) == set(SOCKET_PROXY_PERMISSIONS) | set(SOCKET_PROXY_DENIED)
    assert set(env.values()) == {"0", "1"}


def test_the_compose_file_gives_the_proxy_exactly_this_environment():
    """The one gate that would catch the flags being edited in only one place."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    compose = repo_root / "docker" / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")
    declared = {}
    inside = False
    for line in text.splitlines():
        if line.startswith("  docker-socket-proxy:"):
            inside = True
            continue
        if inside and line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            break
        if inside and ": " in line:
            key, _, value = line.strip().partition(": ")
            if key.isupper():
                declared[key] = json.loads(value) if value.startswith('"') else value.strip("'")
    assert declared == socket_proxy_env(), (
        "docker/docker-compose.yml and SOCKET_PROXY_PERMISSIONS disagree — "
        'regenerate the block from `python -c "from runtime_manager.docker_backend import socket_proxy_env; '
        'print(socket_proxy_env())"`'
    )


#: How to reach the proxy *as the manager does*, which is the only vantage point
#: that exists: the compose form publishes no port for it at all (that is the
#: point), so a ``curl`` from the host would answer "connection refused" and read
#: as a pass on a deployment that is wide open. Asking from inside the manager
#: container answers the real question. In the systemd form the proxy binds
#: ``127.0.0.1:2375`` and ``RTM_DOCKER_HOST`` says so — read it off the unit
#: rather than assuming either shape.
_PROXY_BASE = "http://docker-socket-proxy:2375"
_ASK = (
    "import sys,urllib.request,urllib.error\n"
    "req=urllib.request.Request(sys.argv[1], method=sys.argv[2])\n"
    "try: print(urllib.request.urlopen(req, timeout=5).status)\n"
    "except urllib.error.HTTPError as exc: print(exc.code)\n"
)


def _ask_proxy(path: str, method: str = "GET") -> str:
    out = subprocess.run(
        ["docker", "exec", "bisheng-runtime-manager", "python", "-c", _ASK, f"{_PROXY_BASE}{path}", method],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.docker
def test_the_socket_proxy_refuses_exec_on_this_host():
    """D2-B end to end. Run on 114 with the app-runtime profile up."""
    assert _ask_proxy("/v1.44/exec", "POST") == "403"


@pytest.mark.docker
def test_the_socket_proxy_allows_the_endpoints_the_manager_needs():
    assert _ask_proxy("/v1.44/containers/json") == "200"
