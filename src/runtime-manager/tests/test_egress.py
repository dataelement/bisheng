"""T076 — the outbound whitelist, both phases and all three layers (AC-16).

The shape of this file follows where the enforcement actually lives:

* **decisions** — the pure policy function, one test per sentence of AC-16;
* **the proxy** — driven over real loopback sockets against a real upstream,
  because "it refuses an undeclared host" is a claim about bytes on a wire and a
  mocked socket would only prove that the mock was configured;
* **rules** — what the L3 fallback renders, including the order, which *is* the
  rule set;
* **wiring** — that a deploy / build / preview actually reaches those decisions.

What is deliberately **not** here: whether the kernel drops the packet. That
needs a daemon and a real bridge, carries ``@pytest.mark.docker``, and is
verified in the CI middleware stage and on 114 — the same split every other
container-shaped claim in this package uses.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime_manager.api.schemas import DeployRequest, HealthIn, TierIn
from runtime_manager.builder import BuildService
from runtime_manager.config import LABEL_EGRESS_DOMAINS, Config
from runtime_manager.desired_state import InstanceRecord
from runtime_manager.egress import (
    BACKEND_IPTABLES,
    BACKEND_NFTABLES,
    BACKEND_UNKNOWN,
    DENY_IP_LITERAL,
    DENY_NOT_DECLARED,
    DENY_PORT,
    DENY_PRIVATE_ADDRESS,
    DENY_UDP,
    DENY_UNKNOWN_PRINCIPAL,
    ENV_EGRESS_TOKEN,
    PRINCIPAL_BUILD,
    PROTO_UDP,
    Destination,
    EgressPolicyStore,
    build_destinations,
    build_proxy_buildargs,
    decide,
    detect_firewall_backend,
    egress_env,
    egress_preflight,
    firewall_rules,
    forget_principal,
    get_policy_store,
    iptables_commands,
    iptables_delete_commands,
    merge_destinations,
    nft_script,
    parse_destination,
    register_principal,
    runtime_destinations,
)
from runtime_manager.egress_proxy import EgressProxy
from runtime_manager.lifecycle import LifecycleService
from tests.fakes import FakeDockerBackend, FakeHostProbe, ImmediateScheduler

PROXY_ADDRESS = "egress-proxy:3128"
PLATFORM = "http://platform.example.com:7860"


@pytest.fixture
def egress_config(rtm_config: Config) -> Config:
    """``rtm_config`` with the egress layer deployed — the post-T077 shape."""
    config = rtm_config.with_overrides(
        egress_proxy=PROXY_ADDRESS,
        app_facing_base_url="http://runtime-manager:8091",
        platform_base_url=PLATFORM,
        apps_subnet="172.31.0.0/16",
        firewall_backend=BACKEND_IPTABLES,
    )
    from runtime_manager.config import set_config

    set_config(config)
    return config


# ---------------------------------------------------------------------------
# destinations
# ---------------------------------------------------------------------------


def test_parse_destination_accepts_the_three_forms_it_is_actually_given():
    assert parse_destination("https://pypi.example.com/simple") == Destination("pypi.example.com", (443,))
    assert parse_destination("http://platform:7860") == Destination("platform", (7860,))
    assert parse_destination("api.openai.com") == Destination("api.openai.com", (80, 443))
    assert parse_destination("db.example.com:5432") == Destination("db.example.com", (5432,))
    assert parse_destination("*.example.com") == Destination(".example.com", (80, 443))


def test_parse_destination_refuses_what_names_no_host():
    assert parse_destination("") is None
    assert parse_destination("   ") is None
    assert parse_destination("/") is None


def test_merge_destinations_unions_the_ports_of_a_repeated_host():
    merged = merge_destinations(["platform:7860"], ["platform:443"], ["platform:7860"])
    assert merged == (Destination("platform", (443, 7860)),)


# ---------------------------------------------------------------------------
# decisions — AC-16, sentence by sentence
# ---------------------------------------------------------------------------


def test_declared_domain_is_allowed_on_both_default_ports():
    destinations = merge_destinations(["api.openai.com"])
    assert decide(destinations, "api.openai.com", 443).allowed
    assert decide(destinations, "api.openai.com", 80).allowed


def test_undeclared_domain_is_refused_and_the_message_names_the_fix():
    decision = decide(merge_destinations(["api.openai.com"]), "evil.example.com", 443)
    assert not decision.allowed
    assert decision.reason == DENY_NOT_DECLARED
    assert "egress.domains" in decision.detail


def test_a_zone_entry_covers_subdomains_and_the_apex_but_not_a_lookalike():
    destinations = merge_destinations(["*.example.com"])
    assert decide(destinations, "a.example.com", 443).allowed
    assert decide(destinations, "example.com", 443).allowed
    # The suffix trap: ``notexample.com`` ends with ``example.com`` as a string
    # and must not end with it as a zone.
    assert not decide(destinations, "notexample.com", 443).allowed


def test_a_declared_host_on_an_undeclared_port_says_so_rather_than_not_declared():
    decision = decide(merge_destinations(["api.openai.com"]), "api.openai.com", 8443)
    assert decision.reason == DENY_PORT
    assert "api.openai.com:8443" in decision.detail


def test_direct_ip_is_refused_even_when_the_domain_next_to_it_is_allowed():
    decision = decide(merge_destinations(["api.openai.com"]), "1.2.3.4", 443)
    assert not decision.allowed
    assert decision.reason == DENY_IP_LITERAL


def test_an_ip_that_is_itself_declared_is_allowed():
    """A single-machine deployment's platform API base genuinely is an address."""
    destinations = merge_destinations(["192.168.106.114:7860"])
    assert decide(destinations, "192.168.106.114", 7860).allowed
    assert not decide(destinations, "192.168.106.115", 7860).allowed


def test_udp_is_refused_no_matter_what_is_declared():
    decision = decide(merge_destinations(["api.openai.com"]), "api.openai.com", 443, protocol=PROTO_UDP)
    assert not decision.allowed
    assert decision.reason == DENY_UDP
    assert "QUIC" in decision.detail


# ---------------------------------------------------------------------------
# the two phases
# ---------------------------------------------------------------------------


def test_build_phase_allows_the_package_index_and_the_platform_and_nothing_else(egress_config: Config):
    destinations = build_destinations(egress_config)
    assert decide(destinations, "pypi.example.com", 443).allowed
    assert decide(destinations, "platform.example.com", 7860).allowed
    # A manifest cannot widen a build: the whole point of AC-16's build sentence.
    assert not decide(destinations, "api.openai.com", 443).allowed


def test_run_phase_allows_the_platform_the_manager_and_the_declared_domains(egress_config: Config):
    destinations = runtime_destinations(
        egress_config, platform_api_base="http://entry.example.com", declared=["api.openai.com"]
    )
    assert decide(destinations, "entry.example.com", 80).allowed
    assert decide(destinations, "api.openai.com", 443).allowed
    # The package index is *not* reachable at run time (D12: "运行期零包源").
    assert not decide(destinations, "pypi.example.com", 443).allowed


def test_the_model_face_address_is_on_the_list_even_though_it_is_not_platform_api_base(egress_config: Config):
    """F051's ``OPENAI_BASE_URL`` is the *browser-visible* origin, not this one.

    It is built from ``open_api.public_base_url`` and only falls back to
    ``app_runtime.entry_base_url`` (= ``platform_api_base``) when that is unset,
    so on any deployment where the two differ — the documented normal case — an
    allowlist derived from ``platform_api_base`` alone refuses every hosted
    application's model call the moment this layer is switched on. Deriving the
    platform half from the names the platform injects is what keeps the next
    platform URL somebody adds from repeating this.
    """
    destinations = runtime_destinations(
        egress_config,
        platform_api_base="http://entry.example.com",
        declared=[],
        injected_env={
            "OPENAI_BASE_URL": "https://bisheng.customer.com/api/v2/model/v1",
            "BISHENG_MODEL_BASE_URL": "https://bisheng.customer.com/api/v2/model/v1",
        },
    )
    decision = decide(destinations, "bisheng.customer.com", 443)
    assert decision.allowed
    assert decision.trusted, "the platform's own address may be private on an on-premise install"


def test_an_applications_own_env_cannot_forge_a_platform_address(egress_config: Config):
    """Only the reserved names are read, and the backend writes those last."""
    destinations = runtime_destinations(egress_config, declared=[], injected_env={"MY_API": "https://evil.example.com"})
    assert not decide(destinations, "evil.example.com", 443).allowed


def test_the_deploy_path_puts_the_model_face_on_the_policy(egress_config: Config, fake_docker):
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request(env={"OPENAI_BASE_URL": "https://bisheng.customer.com/api/v2/model/v1"}))
    hosts = {d.host for d in get_policy_store(egress_config).get("app-1").destinations}
    assert "bisheng.customer.com" in hosts


def test_the_attachment_handle_host_is_always_on_the_run_phase_list(egress_config: Config):
    """contracts §9: the whitelist must allow ``BISHENG_APP_STORAGE_ENDPOINT``.

    The value is derived from ``RTM_APP_FACING_BASE_URL``, which is also what
    the injected endpoint is built from — so this test fails the moment someone
    narrows one of the two without the other.
    """
    destinations = runtime_destinations(egress_config, declared=[])
    assert decide(destinations, "runtime-manager", 8091).allowed


# ---------------------------------------------------------------------------
# injected environment
# ---------------------------------------------------------------------------


def test_no_proxy_variables_are_injected_when_the_layer_is_not_deployed(rtm_config: Config):
    assert egress_env(rtm_config, principal="app-1", token="t") == {}


def test_injected_variables_cover_both_cases_and_skip_the_in_network_hops(egress_config: Config):
    env = egress_env(egress_config, principal="app-1", token="secret-token")
    assert env["HTTP_PROXY"] == env["HTTPS_PROXY"] == f"http://app-1:secret-token@{PROXY_ADDRESS}"
    assert env["http_proxy"] == env["HTTP_PROXY"], "curl reads only the lower-case pair"
    assert env[ENV_EGRESS_TOKEN] == "secret-token"
    # The attachment handle is an in-network call; sending it through the proxy
    # would push it out of the network and back in.
    assert "runtime-manager" in env["NO_PROXY"].split(",")
    assert "127.0.0.1" in env["NO_PROXY"].split(",")


def test_the_credential_env_name_is_one_the_log_redactor_recognises():
    """Otherwise the token shows up in plain text in the app's own log tail."""
    from runtime_manager.api.readonly import SENSITIVE_ENV_NAME

    assert SENSITIVE_ENV_NAME.search(ENV_EGRESS_TOKEN)


def test_build_args_use_the_build_principal_and_do_not_change_between_builds(egress_config: Config):
    first = build_proxy_buildargs(egress_config)
    second = build_proxy_buildargs(egress_config)
    assert first["HTTP_PROXY"].startswith(f"http://{PRINCIPAL_BUILD}:")
    # A build arg that changed per build would invalidate the layer cache below
    # the first RUN, every time.
    assert first == second


def test_build_args_are_empty_when_the_layer_is_not_deployed(rtm_config: Config):
    assert build_proxy_buildargs(rtm_config) == {}


# ---------------------------------------------------------------------------
# the policy file
# ---------------------------------------------------------------------------


def test_register_then_authorise_round_trip(egress_config: Config):
    token = register_principal(egress_config, principal="app-1", destinations=merge_destinations(["api.openai.com"]))
    store = get_policy_store(egress_config)
    policy = store.get("app-1")
    assert policy is not None
    assert policy.authenticates(token)
    assert not policy.authenticates("wrong")
    # The plaintext never leaves the file as a hash only — the manager has to be
    # able to re-inject it on a redeploy — but the *hash* is what authenticates.
    assert policy.token_hash != token


def test_re_registering_keeps_the_credential_so_the_grace_window_holds(egress_config: Config):
    first = register_principal(egress_config, principal="app-1", destinations=merge_destinations(["a.example.com"]))
    second = register_principal(egress_config, principal="app-1", destinations=merge_destinations(["b.example.com"]))
    assert first == second
    policy = get_policy_store(egress_config).get("app-1")
    assert [d.host for d in policy.destinations] == ["b.example.com"]


def test_forget_removes_the_entry(egress_config: Config):
    register_principal(egress_config, principal="app-1", destinations=())
    forget_principal(egress_config, "app-1")
    assert get_policy_store(egress_config).get("app-1") is None


def test_a_second_reader_sees_a_write_through_the_file(tmp_path: Path):
    writer = EgressPolicyStore(tmp_path / "policy.json")
    reader = EgressPolicyStore(tmp_path / "policy.json")
    assert reader.get("app-1") is None
    from runtime_manager.egress import PrincipalPolicy, hash_token

    writer.put(PrincipalPolicy(principal="app-1", token_hash=hash_token("t"), destinations=()))
    assert reader.get("app-1") is not None


def test_a_corrupt_policy_file_leaves_the_previous_copy_in_force(tmp_path: Path):
    """Fail-open on a bad *cache* beats taking every hosted app offline."""
    from runtime_manager.egress import PrincipalPolicy, hash_token

    path = tmp_path / "policy.json"
    store = EgressPolicyStore(path)
    store.put(PrincipalPolicy(principal="app-1", token_hash=hash_token("t"), destinations=()))
    path.write_text("{ not json", encoding="utf-8")
    assert store.get("app-1") is not None


# ---------------------------------------------------------------------------
# the proxy, over real sockets
# ---------------------------------------------------------------------------


class _Upstream:
    """A loopback TCP server that echoes what it is sent, prefixed."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.connections = 0

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.connections += 1
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    writer.write(b"echo:" + data)
                    await writer.drain()
            except OSError:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


def _auth(principal: str, token: str) -> str:
    raw = base64.b64encode(f"{principal}:{token}".encode()).decode()
    return f"Proxy-Authorization: Basic {raw}\r\n"


async def _talk(port: int, request: bytes) -> bytes:
    """Send one proxy request and read the whole answer — head *and* body.

    The body is where the refusal reason is, and the reason is the part the
    application developer will actually read.
    """
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    answer = await reader.read(8192)
    writer.close()
    return answer


@pytest.fixture
async def running_proxy(egress_config: Config):
    proxy = EgressProxy(egress_config, store=get_policy_store(egress_config))
    server = await proxy.start("127.0.0.1", 0)
    yield proxy, server.sockets[0].getsockname()[1]
    await proxy.stop()


async def test_connect_to_a_declared_host_tunnels_bytes(egress_config: Config, running_proxy):
    _proxy, port = running_proxy
    upstream = _Upstream()
    upstream_port = await upstream.start()
    # ``trusted`` = "the deployment configured this", which is what a loopback
    # stand-in for a public upstream has to be: an *application*-declared name
    # resolving to loopback is refused on purpose, and has its own test below.
    token = register_principal(
        egress_config, principal="app-1", destinations=(Destination("127.0.0.1", (upstream_port,), trusted=True),)
    )
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\n{_auth('app-1', token)}\r\n".encode())
        await writer.drain()
        status = await reader.readuntil(b"\r\n\r\n")
        assert b"200 Connection Established" in status
        writer.write(b"hello")
        await writer.drain()
        assert await reader.read(64) == b"echo:hello"
        writer.close()
    finally:
        await upstream.stop()


async def test_connect_to_an_undeclared_host_is_403_and_never_dials_upstream(egress_config: Config, running_proxy):
    _proxy, port = running_proxy
    upstream = _Upstream()
    upstream_port = await upstream.start()
    token = register_principal(egress_config, principal="app-1", destinations=merge_destinations(["api.openai.com"]))
    try:
        head = await _talk(port, f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\n{_auth('app-1', token)}\r\n".encode())
        assert b"403 Forbidden" in head
        assert upstream.connections == 0, "a refused destination must not be contacted at all"
    finally:
        await upstream.stop()


async def test_a_request_without_a_credential_is_407_with_a_challenge(running_proxy):
    _proxy, port = running_proxy
    head = await _talk(port, b"CONNECT api.openai.com:443 HTTP/1.1\r\n\r\n")
    assert b"407 Proxy Authentication Required" in head
    assert b"Proxy-Authenticate: Basic" in head
    assert DENY_UNKNOWN_PRINCIPAL.encode() in head


async def test_a_wrong_credential_is_407_not_403(egress_config: Config, running_proxy):
    _proxy, port = running_proxy
    register_principal(egress_config, principal="app-1", destinations=merge_destinations(["api.openai.com"]))
    head = await _talk(port, f"CONNECT api.openai.com:443 HTTP/1.1\r\n{_auth('app-1', 'wrong')}\r\n".encode())
    assert b"407" in head


async def test_one_app_cannot_use_another_apps_whitelist(egress_config: Config, running_proxy):
    """The whole reason the proxy authenticates: per-application declarations."""
    _proxy, port = running_proxy
    register_principal(egress_config, principal="app-1", destinations=merge_destinations(["a.example.com"]))
    token_2 = register_principal(egress_config, principal="app-2", destinations=merge_destinations(["b.example.com"]))
    head = await _talk(port, f"CONNECT a.example.com:443 HTTP/1.1\r\n{_auth('app-2', token_2)}\r\n".encode())
    assert b"403 Forbidden" in head
    assert DENY_NOT_DECLARED.encode() in head


async def test_absolute_form_http_is_forwarded_without_the_proxy_credential(egress_config: Config, running_proxy):
    _proxy, port = running_proxy
    seen: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(handle, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    token = register_principal(
        egress_config, principal="app-1", destinations=(Destination("127.0.0.1", (upstream_port,), trusted=True),)
    )
    try:
        head = await _talk(
            port,
            f"GET http://127.0.0.1:{upstream_port}/a?b=1 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{upstream_port}\r\n"
            f"X-Keep: yes\r\n"
            f"{_auth('app-1', token)}\r\n".encode(),
        )
        assert b"200 OK" in head
        forwarded = seen[0]
        assert forwarded.startswith(b"GET /a?b=1 HTTP/1.1")
        assert b"X-Keep: yes" in forwarded
        assert b"Proxy-Authorization" not in forwarded, "the proxy consumes its own credential"
    finally:
        upstream.close()
        await upstream.wait_closed()


async def test_an_origin_form_request_is_not_a_proxy_request(running_proxy):
    _proxy, port = running_proxy
    head = await _talk(port, b"GET /status HTTP/1.1\r\nHost: x\r\n\r\n")
    assert b"400 Bad Request" in head
    assert b"HTTP_PROXY" in head


async def test_an_allowed_but_dead_upstream_is_502_not_403(egress_config: Config, running_proxy):
    """Otherwise a developer goes hunting in their manifest for a network fault."""
    _proxy, port = running_proxy
    dead = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    dead_port = dead.sockets[0].getsockname()[1]
    dead.close()
    await dead.wait_closed()
    token = register_principal(
        egress_config, principal="app-1", destinations=(Destination("127.0.0.1", (dead_port,), trusted=True),)
    )
    head = await _talk(port, f"CONNECT 127.0.0.1:{dead_port} HTTP/1.1\r\n{_auth('app-1', token)}\r\n".encode())
    assert b"502 Bad Gateway" in head


async def test_an_application_declared_name_pointing_inside_the_deployment_is_refused(
    egress_config: Config, running_proxy
):
    """The hole in the wall must not double as a relay into the platform's network.

    The proxy is the one process with a route both onto ``bisheng-apps`` and off
    the box, and in the compose form it sits on the platform's own network next
    to mysql / redis / minio. Without this gate a single line of
    ``egress: {domains: [mysql]}`` in somebody's ``bisheng-app.yaml`` reaches all
    of them — the exact reachability the ``--internal`` network removed.
    """
    _proxy, port = running_proxy
    upstream = _Upstream()
    upstream_port = await upstream.start()
    # Declared by the application (untrusted), and it resolves to loopback.
    token = register_principal(
        egress_config, principal="app-1", destinations=(Destination("127.0.0.1", (upstream_port,)),)
    )
    try:
        head = await _talk(port, f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\n{_auth('app-1', token)}\r\n".encode())
        assert b"403 Forbidden" in head
        assert DENY_PRIVATE_ADDRESS.encode() in head
        assert b"RTM_EGRESS_ALLOW" in head, "the refusal has to name the operator's escape hatch"
        assert upstream.connections == 0
    finally:
        await upstream.stop()


async def test_the_same_address_is_reachable_once_the_operator_declares_it(egress_config: Config, running_proxy):
    """``RTM_EGRESS_ALLOW`` is the deployment saying so deliberately — on-premise
    model gateways and internal mirrors are the normal case, not an attack."""
    _proxy, port = running_proxy
    upstream = _Upstream()
    upstream_port = await upstream.start()
    config = egress_config.with_overrides(egress_allow=(f"127.0.0.1:{upstream_port}",))
    token = register_principal(config, principal="app-1", destinations=runtime_destinations(config, declared=[]))
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{upstream_port} HTTP/1.1\r\n{_auth('app-1', token)}\r\n".encode())
        await writer.drain()
        assert b"200 Connection Established" in await reader.readuntil(b"\r\n\r\n")
        writer.close()
    finally:
        await upstream.stop()


def test_the_address_gate_applies_to_the_manifest_and_not_to_the_platform(egress_config: Config):
    """The two halves of the run-phase list carry different answers."""
    destinations = runtime_destinations(
        egress_config, platform_api_base="http://10.0.0.5:7860", declared=["api.openai.com"]
    )
    assert decide(destinations, "10.0.0.5", 7860).trusted, "the platform may live on a private address"
    assert not decide(destinations, "api.openai.com", 443).trusted


def test_a_host_the_deployment_also_configures_stays_trusted_if_a_manifest_names_it(egress_config: Config):
    config = egress_config.with_overrides(egress_allow=("internal.example.com",))
    destinations = runtime_destinations(config, declared=["internal.example.com"])
    assert decide(destinations, "internal.example.com", 443).trusted


def test_address_decision_refuses_a_name_that_answers_with_any_private_address():
    """Any, not all: a rebinding answer carries one of each."""
    from runtime_manager.egress import address_decision

    assert address_decision("x.example.com", ["93.184.216.34"]) is None
    refused = address_decision("x.example.com", ["93.184.216.34", "10.0.0.5"])
    assert refused is not None and refused.reason == DENY_PRIVATE_ADDRESS
    assert "10.0.0.5" in refused.detail
    for private in ("127.0.0.1", "169.254.169.254", "::1", "fd00::1", "192.168.1.1", "172.17.0.2"):
        assert address_decision("x.example.com", [private]) is not None, private


def test_address_decision_refuses_a_name_that_resolves_to_nothing():
    from runtime_manager.egress import address_decision

    assert address_decision("x.example.com", []) is not None


def test_the_trust_flag_survives_the_policy_file(egress_config: Config):
    """The file is the proxy's only input; a flag that did not round-trip would
    make every platform destination look application-declared and be refused."""
    register_principal(
        egress_config,
        principal="app-1",
        destinations=runtime_destinations(
            egress_config, platform_api_base="http://10.0.0.5:7860", declared=["api.openai.com"]
        ),
    )
    reloaded = EgressPolicyStore(egress_config.egress_policy_path).get("app-1")
    by_host = {d.host: d.trusted for d in reloaded.destinations}
    assert by_host["10.0.0.5"] is True
    assert by_host["api.openai.com"] is False


def test_a_declared_port_that_is_not_a_default_still_reports_the_port_rather_than_the_host(egress_config: Config):
    """``db.example.com:5432`` reached on 5433 is a port mistake, not an undeclared host."""
    decision = decide(merge_destinations(["db.example.com:5432"]), "db.example.com", 5433)
    assert decision.reason == DENY_PORT


# ---------------------------------------------------------------------------
# L3 — the firewall fallback
# ---------------------------------------------------------------------------


def test_no_subnet_means_no_rules_rather_than_rules_that_match_everything(egress_config: Config):
    assert firewall_rules(egress_config.with_overrides(apps_subnet="")) == []


def test_rule_order_allows_the_proxy_before_it_denies_everything(egress_config: Config):
    rules = firewall_rules(egress_config.with_overrides(egress_proxy="172.31.0.9:3128"))
    assert [(r.verdict, r.protocol) for r in rules] == [
        ("RETURN", "tcp"),
        ("DROP", "udp"),
        ("DROP", ""),
    ]
    assert rules[0].destination == "172.31.0.9"
    assert rules[0].port == 3128


def test_a_proxy_named_by_hostname_yields_no_allowance_so_the_default_deny_is_visible(egress_config: Config):
    """A firewall matches addresses. Silently "allowing" a name would be a lie."""
    rules = firewall_rules(egress_config)
    assert [r.verdict for r in rules] == ["DROP", "DROP"]


def test_udp_is_dropped_by_the_rule_set_not_merely_by_the_proxys_absence(egress_config: Config):
    udp = [r for r in firewall_rules(egress_config) if r.protocol == "udp"]
    assert len(udp) == 1
    assert udp[0].verdict == "DROP"


def test_iptables_commands_number_their_positions_in_evaluation_order(egress_config: Config):
    config = egress_config.with_overrides(egress_proxy="172.31.0.9:3128")
    commands = iptables_commands(config, firewall_rules(config))
    assert [c[3] for c in commands] == ["1", "2", "3"]
    assert commands[0][:3] == ["iptables", "-I", "DOCKER-USER"]
    assert "-s" in commands[0] and "172.31.0.0/16" in commands[0]
    assert commands[-1][-1] == "DROP"


def test_delete_commands_are_the_exact_inverse_so_re_applying_is_idempotent(egress_config: Config):
    rules = firewall_rules(egress_config)
    inserts = iptables_commands(egress_config, rules)
    deletes = iptables_delete_commands(egress_config, rules)
    for insert, delete in zip(inserts, deletes, strict=True):
        # ``-I CHAIN <position> <spec>`` vs ``-D CHAIN <spec>``.
        assert insert[4:] == delete[3:]
        assert delete[1] == "-D"


def test_the_nft_ruleset_drops_its_own_table_first_and_hooks_ahead_of_docker(egress_config: Config):
    script = nft_script(egress_config, firewall_rules(egress_config))
    assert "delete table inet bisheng_egress" in script
    assert "priority -100" in script
    assert "meta l4proto udp" in script and "drop" in script


def test_firewall_backend_detection_reads_the_host_rather_than_guessing():
    assert detect_firewall_backend(lambda argv: (0, "")) == BACKEND_IPTABLES
    assert detect_firewall_backend(lambda argv: (0, "") if argv[0] == "nft" else (1, "no chain")) == BACKEND_NFTABLES
    assert detect_firewall_backend(lambda argv: (127, "not found")) == BACKEND_UNKNOWN


# ---------------------------------------------------------------------------
# pre-flight
# ---------------------------------------------------------------------------


def test_preflight_says_out_loud_that_an_undeployed_whitelist_means_open_egress(rtm_config: Config):
    rows = egress_preflight(rtm_config, docker=None)
    assert [r["name"] for r in rows] == ["egress_whitelist"]
    assert rows[0]["ok"] is False
    assert "RTM_EGRESS_PROXY" in rows[0]["detail"]


def test_preflight_flags_an_application_network_that_is_not_internal(egress_config: Config, fake_docker):
    row = next(r for r in egress_preflight(egress_config, fake_docker) if r["name"] == "application_network_internal")
    assert row["ok"] is False
    assert "docker network create --internal bisheng-apps" in row["detail"]


def test_preflight_is_clean_once_the_network_is_internal_and_iptables_is_pinned(egress_config: Config, fake_docker):
    fake_docker.internal_networks.add(egress_config.network)
    rows = egress_preflight(egress_config, fake_docker)
    assert all(row["ok"] for row in rows), rows


def test_preflight_refuses_to_call_the_nftables_backend_fine(egress_config: Config, fake_docker):
    """Design pit 22: iptables rules on the nftables backend filter nothing."""
    fake_docker.internal_networks.add(egress_config.network)
    config = egress_config.with_overrides(firewall_backend=BACKEND_NFTABLES)
    row = next(r for r in egress_preflight(config, fake_docker) if r["name"] == "egress_firewall_fallback")
    assert row["ok"] is False
    assert "DOCKER-USER" in row["detail"]


def test_preflight_names_the_missing_subnet_rather_than_silently_skipping_l3(egress_config: Config, fake_docker):
    fake_docker.internal_networks.add(egress_config.network)
    config = egress_config.with_overrides(apps_subnet="")
    row = next(r for r in egress_preflight(config, fake_docker) if r["name"] == "egress_firewall_fallback")
    assert row["ok"] is False
    assert "RTM_APPS_SUBNET" in row["detail"]


def test_runtime_status_carries_the_egress_rows(rtm_client, fake_docker):
    """The pre-flight is the thing operators read before publishing (contracts §7)."""
    body = rtm_client.get("/v1/runtime/status").json()
    assert "egress_whitelist" in {row["name"] for row in body["preflight"]}


# ---------------------------------------------------------------------------
# wiring — a deploy, a build and a preview really do reach the policy
# ---------------------------------------------------------------------------


def _deploy_request(**overrides) -> DeployRequest:
    payload = {
        "app_id": "app-1",
        "slug": "demo",
        "version_id": "v" * 32,
        "version_no": 1,
        "image_ref": "bisheng-app/demo:1-vvvvvvvv",
        "tier": TierIn(cpu=0.5, mem=512),
        "port": 8080,
        "health": HealthIn(),
        "platform_api_base": PLATFORM,
        "egress_domains": ["api.openai.com"],
    }
    payload.update(overrides)
    return DeployRequest(**payload)


class _ReadyProber:
    """Readiness gate double — the gate itself is tested in test_probe_and_route."""

    def wait_ready(self, container, port, health_path, timeout=None):
        return SimpleNamespace(ready=True, reason="")


def _service(config: Config, docker: FakeDockerBackend) -> LifecycleService:
    from runtime_manager.admission import AdmissionService

    return LifecycleService(
        config,
        docker=docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        prober=_ReadyProber(),
        scheduler=ImmediateScheduler(),
    )


def test_deploy_injects_the_proxy_and_registers_the_declared_domains(egress_config: Config, fake_docker):
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request())

    payload = fake_docker.last_call("create_container")["payload"]
    env = dict(item.split("=", 1) for item in payload["Env"])
    assert env["HTTP_PROXY"].endswith(f"@{PROXY_ADDRESS}")
    assert env["HTTP_PROXY"].startswith("http://app-1:")
    assert payload["Labels"][LABEL_EGRESS_DOMAINS] == "api.openai.com"

    policy = get_policy_store(egress_config).get("app-1")
    hosts = {d.host for d in policy.destinations}
    assert {"api.openai.com", "platform.example.com", "runtime-manager"} <= hosts


def test_an_application_cannot_replace_the_injected_proxy_with_its_own(egress_config: Config, fake_docker):
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request(env={"HTTP_PROXY": "http://attacker:1234"}))
    env = dict(item.split("=", 1) for item in fake_docker.last_call("create_container")["payload"]["Env"])
    assert "attacker" not in env["HTTP_PROXY"]


def test_a_redeploy_carries_the_same_credential_through_the_grace_window(egress_config: Config, fake_docker):
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request())
    first = dict(item.split("=", 1) for item in fake_docker.last_call("create_container")["payload"]["Env"])
    service.deploy(_deploy_request(version_id="w" * 32, version_no=2, image_ref="bisheng-app/demo:2-wwwwwwww"))
    second = dict(item.split("=", 1) for item in fake_docker.last_call("create_container")["payload"]["Env"])
    assert first[ENV_EGRESS_TOKEN] == second[ENV_EGRESS_TOKEN]


def test_destroy_takes_the_credential_with_it(egress_config: Config, fake_docker):
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request())
    service.destroy("app-1")
    assert get_policy_store(egress_config).get("app-1") is None


def test_declared_domains_survive_a_lost_state_file(egress_config: Config, fake_docker):
    """Labels are the disaster-recovery truth; a narrower whitelist is a silent outage."""
    service = _service(egress_config, fake_docker)
    service.deploy(_deploy_request())
    name = fake_docker.last_call("create_container")["name"]
    recovered = InstanceRecord.from_container(fake_docker.get(name).inspect(egress_config.network))
    assert recovered.egress_domains == ["api.openai.com"]


def test_the_build_runs_on_the_build_network_with_the_build_principals_proxy(egress_config: Config, fake_docker):
    from runtime_manager.api.schemas import BuildRequest

    config = egress_config.with_overrides(build_network="bisheng-build")
    from runtime_manager.admission import AdmissionService

    service = BuildService(
        config,
        docker=fake_docker,
        admission=AdmissionService(config, host_probe=FakeHostProbe()),
        fetcher=lambda url, dest: dest.mkdir(parents=True, exist_ok=True),
    )
    service.run(
        BuildRequest(
            app_id="app-1",
            version_id="v" * 32,
            runtime="python3.11",
            code_object_key="k",
            code_url="https://example/k",
            slug="demo",
            build_args={"HTTP_PROXY": "http://attacker:1234"},
        )
    )
    call = fake_docker.last_call("build_image")
    assert call["network_mode"] == "bisheng-build"
    assert call["buildargs"]["HTTP_PROXY"].startswith(f"http://{PRINCIPAL_BUILD}:")


def test_a_preview_gets_its_own_principal_not_the_applications(egress_config: Config, fake_docker):
    from runtime_manager.admission import AdmissionService, Tier
    from runtime_manager.preview import PreviewService, preview_principal

    service = PreviewService(
        egress_config,
        docker=fake_docker,
        admission=AdmissionService(egress_config, host_probe=FakeHostProbe()),
        prober=_ReadyProber(),
    )
    service.start(
        session_id="session-0001",
        app_id="app-1",
        version_id="v" * 32,
        image_ref="bisheng-app/demo:1-vvvvvvvv",
        tier=Tier(cpu=0.5, mem_mb=512),
        egress_domains=["api.openai.com"],
    )
    store = get_policy_store(egress_config)
    assert store.get(preview_principal("session-0001")) is not None
    assert store.get("app-1") is None

    env = dict(item.split("=", 1) for item in fake_docker.last_call("create_container")["payload"]["Env"])
    assert env["HTTP_PROXY"].startswith(f"http://{preview_principal('session-0001')}:")


def test_stopping_a_preview_takes_its_credential_with_it(egress_config: Config, fake_docker):
    from runtime_manager.admission import AdmissionService, Tier
    from runtime_manager.preview import PreviewService, preview_principal

    service = PreviewService(
        egress_config,
        docker=fake_docker,
        admission=AdmissionService(egress_config, host_probe=FakeHostProbe()),
        prober=_ReadyProber(),
    )
    service.start(
        session_id="session-0001",
        app_id="app-1",
        version_id="v" * 32,
        image_ref="bisheng-app/demo:1-vvvvvvvv",
        tier=Tier(cpu=0.5, mem_mb=512),
    )
    service.stop("session-0001")
    assert get_policy_store(egress_config).get(preview_principal("session-0001")) is None


# ---------------------------------------------------------------------------
# what only a real daemon can answer
# ---------------------------------------------------------------------------


@pytest.mark.docker
def test_the_application_network_is_internal_on_this_host():
    """AC-16 L1. Verified on 114 / in the CI middleware stage.

    ``docker network inspect bisheng-apps -f '{{.Internal}}'`` must print
    ``true``; anything else means instances have a route around the proxy no
    unit test can see.
    """
    import subprocess

    out = subprocess.run(
        ["docker", "network", "inspect", "bisheng-apps", "-f", "{{.Internal}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "true"


@pytest.mark.docker
def test_an_instance_cannot_reach_an_undeclared_host():
    """AC-16 L2 + L3 end to end, on a real container with a real kernel.

    The unit suite proves the manager *decides* correctly; only this proves the
    packet does not leave. Run it on 114 with the app-runtime layer up.
    """
    import subprocess

    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "bisheng-apps",
            "curlimages/curl:8.8.0",
            "-sS",
            "--max-time",
            "8",
            "https://example.com",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0, "an undeclared destination answered — the whitelist is not in force"


@pytest.mark.docker
def test_udp_out_of_the_application_network_is_dropped():
    """AC-16's UDP clause. DNS through docker's embedded resolver must still work."""
    import subprocess

    blocked = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "bisheng-apps",
            "busybox:1.36",
            "sh",
            "-c",
            "nc -u -w 3 8.8.8.8 53 </dev/null; echo $?",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.stdout.strip().splitlines()[-1] != "0"


def test_json_policy_file_is_readable_by_a_separate_process(egress_config: Config):
    """The proxy runs as its own unit; the file is the whole contract between them."""
    register_principal(egress_config, principal="app-1", destinations=merge_destinations(["api.openai.com"]))
    raw = json.loads(egress_config.egress_policy_path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["principals"][0]["principal"] == "app-1"
