"""Outbound whitelist — the policy half of D12-C (AC-16).

AC-16 is two different sentences with two different enforcement points:

* **Build phase** — only the deployment's package index and the platform's own
  distribution endpoint (that is where ``pip install bisheng-sdk`` gets the
  wheel from). Nothing an application declares applies here: a build is
  platform code assembling platform-chosen base images, and a manifest that
  could widen it would be a way to smuggle a dependency past review.
* **Run phase** — deny by default; allow the platform API, this process (the
  attachment handle, contracts §9 — *the outbound whitelist must allow the
  address ``BISHENG_APP_STORAGE_ENDPOINT`` points at, or the handle breaks with
  it*), and the domains the application's own ``bisheng-app.yaml`` declares.
  Direct-IP connections and **all UDP** are refused.

Three layers carry that, and each one exists because the one above it can be
absent on a given host:

1. **L1 ``--internal`` network.** An application container is attached to
   ``bisheng-apps`` and nothing else, so with the network created ``--internal``
   the kernel has no route off the box at all. This is the only layer that is
   free, total and impossible to misconfigure *quietly* — but it is a property
   of a network object created by the deployment, and 114's was created before
   this feature existed.
2. **L2 the egress proxy** (:mod:`runtime_manager.egress_proxy`), the single
   hole in that wall. It is the only layer that can distinguish
   ``api.openai.com`` from ``evil.example.com``, because it is the only one that
   sees a hostname: by the time a packet reaches a firewall there is only an
   address, and one IP serves a hundred names.
3. **L3 host firewall** (``DOCKER-USER`` / an nftables table), which catches the
   case the first layer is not in force — a network recreated without
   ``--internal``, a second network attached by hand — and which is the only
   place UDP can be stopped, since a CONNECT proxy never sees a datagram.

**Why the proxy authenticates the caller.** A whitelist shared by every hosted
application on the host is the union of every manifest, which is not what AC-16
says: the domains an application may reach are *its* declared domains. The
proxy therefore gets an identity per principal, carried in the ordinary
``Proxy-Authorization`` header that every HTTP client already sends when its
``HTTP_PROXY`` variable has credentials in it — no SDK, no code in the
application, no per-container IP bookkeeping that goes stale the moment the
reconciler recreates an instance with a new bridge address.

The policy is a file (``{data_root}/egress/policy.json``) rather than an API
call, so that a restart — or a crash — of the manager cannot take every hosted
application's outbound traffic with it. The proxy re-reads it when its mtime
changes and keeps serving the last good copy if it ever cannot.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from runtime_manager.config import Config

logger = logging.getLogger(__name__)

#: Principal id of the build phase. Not a valid ``app_id`` (those are hex ids),
#: so it can never collide with an application's own policy entry.
PRINCIPAL_BUILD = "_build"

#: Ports an allowlist entry covers when it does not name one. Everything else
#: has to be spelled out as ``host:port`` — an open CONNECT to arbitrary ports
#: is a generic TCP tunnel, which is the thing this whole module exists to
#: prevent.
DEFAULT_PORTS: tuple[int, ...] = (80, 443)

#: Environment variable carrying the per-principal proxy credential. Named so
#: that ``readonly._redactions`` (which matches on the *name*) strips the value
#: out of application logs — including the copy of it inside ``HTTP_PROXY``,
#: because that redaction replaces values wherever they appear in a line.
ENV_EGRESS_TOKEN = "BISHENG_APP_EGRESS_TOKEN"

# Decision vocabulary. These words travel: they are logged by the proxy, and
# the 403 body shows the application developer which rule refused them.
ALLOW = "allowed"
DENY_NOT_DECLARED = "not_declared"
DENY_IP_LITERAL = "ip_literal"
DENY_PORT = "port_not_allowed"
DENY_UDP = "udp_not_allowed"
DENY_UNKNOWN_PRINCIPAL = "unknown_principal"
DENY_PRIVATE_ADDRESS = "private_address"

PROTO_TCP = "tcp"
PROTO_UDP = "udp"


# ---------------------------------------------------------------------------
# destinations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    """One allowlist entry: a host (or a ``.zone`` suffix) and its ports.

    ``trusted`` says **who put it here**, and it is not decoration. An entry the
    *deployment* configured (the platform API, this process, ``RTM_EGRESS_ALLOW``)
    may legitimately live on a private address — on-premise platforms usually do.
    An entry an *application* declared in its own ``bisheng-app.yaml`` may not:
    the proxy is dual-homed by construction (it is the only process with a route
    both onto ``bisheng-apps`` and off the box), so a manifest naming ``mysql``,
    ``minio`` or ``10.0.0.5`` would otherwise turn the one hole in the wall into
    a relay into the deployment's own network — precisely the reachability L1
    exists to remove. See :func:`address_decision`.
    """

    host: str
    ports: tuple[int, ...] = DEFAULT_PORTS
    trusted: bool = False

    @property
    def is_zone(self) -> bool:
        return self.host.startswith(".")

    def host_matches(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        if self.is_zone:
            # ``.example.com`` covers ``a.example.com`` **and** ``example.com``:
            # a developer who writes the zone form means the service, and having
            # the apex silently excluded is a support ticket, not a security
            # property.
            return host == self.host[1:] or host.endswith(self.host)
        return host == self.host

    def matches(self, host: str, port: int) -> bool:
        return port in self.ports and self.host_matches(host)

    def render(self) -> str:
        if tuple(self.ports) == DEFAULT_PORTS:
            return self.host
        return ";".join(f"{self.host}:{port}" for port in self.ports)


def parse_destination(raw: str, trusted: bool = False) -> Destination | None:
    """``https://host:port/path`` / ``host:port`` / ``*.zone`` → :class:`Destination`.

    Returns ``None`` for anything that does not name a host, so a manifest with
    a stray empty string or a bare ``/`` widens nothing. Accepting URLs is
    deliberate: half the values that end up here are configuration URLs
    (``RTM_BUILD_INDEX_URL``, the platform API base) and asking every call site
    to strip them first is how one of them forgets.
    """
    text = (raw or "").strip().lower()
    if not text:
        return None
    if "://" in text:
        split = urlsplit(text)
        host, port = split.hostname or "", split.port
        if not host:
            return None
        if port is None:
            port = 443 if split.scheme == "https" else 80
        return Destination(host=host, ports=(port,), trusted=trusted)

    text = text.split("/", 1)[0]
    host, sep, port_text = text.rpartition(":")
    if sep and port_text.isdigit():
        if not host:
            return None
        return Destination(host=_normalise_host(host), ports=(int(port_text),), trusted=trusted)
    return None if not text else Destination(host=_normalise_host(text), trusted=trusted)


def _normalise_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if host.startswith("*."):
        host = host[1:]
    # ``[::1]`` is how an IPv6 literal is written in a URL and in a CONNECT
    # target, but the host a decision is made about has the brackets stripped
    # (``urlsplit().hostname`` does it too). Storing the bracketed form would
    # make an IPv6 entry silently unmatchable.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def merge_destinations(*groups: object, trusted: bool = False) -> tuple[Destination, ...]:
    """Flatten and de-duplicate, merging the ports of repeated hosts.

    The same host arriving twice with different ports (``platform:7860`` from
    the deploy intent and ``platform`` from ``RTM_EGRESS_ALLOW``) must end up
    with *both*, not with whichever came last.

    ``trusted`` applies to the raw strings in ``groups``; a :class:`Destination`
    that already carries its own answer keeps it. Trust is **unioned** per host
    for the same reason ports are: a host the deployment configured stays
    deployment-configured even if an application happens to name it too.
    """
    ports: dict[str, set[int]] = {}
    trust: dict[str, bool] = {}
    order: list[str] = []
    for group in groups:
        scalar = isinstance(group, (str, Destination))
        items = [group] if scalar else list(group or ())  # type: ignore[arg-type]
        for item in items:
            if isinstance(item, Destination):
                destination, item_trusted = item, item.trusted
            else:
                destination, item_trusted = parse_destination(str(item)), trusted
            if destination is None:
                continue
            if destination.host not in ports:
                ports[destination.host] = set()
                trust[destination.host] = False
                order.append(destination.host)
            ports[destination.host].update(destination.ports)
            trust[destination.host] = trust[destination.host] or item_trusted
    return tuple(Destination(host=host, ports=tuple(sorted(ports[host])), trusted=trust[host]) for host in order)


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    reason: str
    detail: str = ""
    #: Only meaningful when ``allowed``: the matching entry came from the
    #: deployment's own configuration rather than from an application manifest,
    #: so :func:`address_decision` does not apply to it.
    trusted: bool = False


def decide(
    destinations: tuple[Destination, ...],
    host: str,
    port: int,
    protocol: str = PROTO_TCP,
) -> EgressDecision:
    """The whole of AC-16's run-phase sentence, as one function.

    ``protocol`` exists even though the proxy only ever sees TCP: the UDP answer
    is what :func:`firewall_rules` renders, and having both come out of the same
    function is what keeps "no QUIC" from being true in one layer and forgotten
    in the other.
    """
    if protocol == PROTO_UDP:
        return EgressDecision(
            False,
            DENY_UDP,
            "UDP is blocked outright: QUIC / HTTP3 carry the hostname inside an encrypted "
            "packet, so no whitelist can read it. Clients fall back to TCP on their own.",
        )
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return EgressDecision(False, DENY_NOT_DECLARED, "no destination host")

    match = next((d for d in destinations if d.matches(host, port)), None)
    literal = _as_ip(host)
    if literal is not None:
        # An address that is *itself* on the list is fine — on a single-machine
        # deployment the platform API base genuinely is an IP. What is refused
        # is reaching an arbitrary address directly, which is how a name-based
        # whitelist gets walked around.
        if match is not None:
            return _allow(match, host, port)
        return EgressDecision(
            False,
            DENY_IP_LITERAL,
            f"{host}:{port} is a direct IP connection and is not on the whitelist; "
            "declare a hostname in bisheng-app.yaml egress.domains",
        )

    if match is not None:
        return _allow(match, host, port)
    # Match on the host alone — not on the *default* ports — or a destination
    # declared as ``db.example.com:5432`` reached on 5433 reports "not declared"
    # about a host that plainly is.
    if any(d.host_matches(host) for d in destinations):
        return EgressDecision(
            False,
            DENY_PORT,
            f"{host} is declared but port {port} is not; declare it as {host}:{port}",
        )
    return EgressDecision(
        False,
        DENY_NOT_DECLARED,
        f"{host} is not declared; add it to egress.domains in bisheng-app.yaml and publish a new version",
    )


def _allow(match: Destination, host: str, port: int) -> EgressDecision:
    return EgressDecision(True, ALLOW, f"{host}:{port} is declared", trusted=match.trusted)


def address_decision(host: str, addresses: object) -> EgressDecision | None:
    """Second gate for an application-declared name: *where does it resolve*.

    ``None`` means "nothing to object to". A decision means refuse.

    The whitelist is decided on a name, but the proxy then opens a socket, and
    the proxy is the one process in the deployment with a route both onto the
    application network and off the box. Without this, ``egress: {domains:
    [mysql]}`` in a ``bisheng-app.yaml`` — or a public name whose owner points it
    at ``10.0.0.5`` — is a relay straight into the platform's own network, which
    is exactly the reachability the ``--internal`` network was created to remove.

    It applies only to what an *application* declared: an operator who puts a
    private address on ``RTM_EGRESS_ALLOW`` (an on-premise model gateway, an
    internal mirror) has said so deliberately, and that is the escape hatch this
    refusal names.
    """
    resolved = [str(item) for item in (addresses or ())]
    if not resolved:
        return EgressDecision(False, DENY_NOT_DECLARED, f"{host} does not resolve to any address")
    private = sorted({address for address in resolved if not _is_public(address)})
    if not private:
        return None
    return EgressDecision(
        False,
        DENY_PRIVATE_ADDRESS,
        f"{host} resolves to {', '.join(private)}, which is inside the deployment's own network. "
        "An application's egress.domains may only name destinations on the public internet; "
        "an operator who means to open an internal address adds it to RTM_EGRESS_ALLOW",
    )


def _is_public(address: str) -> bool:
    ip = _as_ip(address)
    # An address that does not parse is not one we can vouch for.
    return ip is not None and bool(ip.is_global)


def _as_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# policy for one principal, and the file the proxy reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrincipalPolicy:
    """What one principal (an app, a preview session, the build phase) may reach."""

    principal: str
    token_hash: str
    destinations: tuple[Destination, ...] = ()
    #: The credential **in plaintext**, and yes that is on purpose — see
    #: :func:`hash_token` for why the hash is next to it rather than instead of
    #: it. Never rendered: it is not in any API response, and the injected copy
    #: is redacted out of logs by name (:data:`ENV_EGRESS_TOKEN`).
    token: str = ""

    def authenticates(self, token: str) -> bool:
        return bool(token) and secrets.compare_digest(self.token_hash, hash_token(token))

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "token_hash": self.token_hash,
            "token": self.token,
            "destinations": [{"host": d.host, "ports": list(d.ports), "trusted": d.trusted} for d in self.destinations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrincipalPolicy:
        return cls(
            principal=str(data.get("principal") or ""),
            token_hash=str(data.get("token_hash") or ""),
            token=str(data.get("token") or ""),
            destinations=tuple(
                Destination(
                    host=str(item.get("host") or ""),
                    ports=tuple(int(p) for p in item.get("ports") or ()),
                    # Absent ⇒ untrusted. The file is the proxy's only input, so
                    # a reader that guessed "trusted" here would turn a format
                    # mistake into an open relay into the private network.
                    trusted=bool(item.get("trusted")),
                )
                for item in data.get("destinations") or ()
                if item.get("host")
            ),
        )


def mint_egress_token() -> str:
    """Per-principal proxy credential; 256 bits, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """What the proxy compares against, in constant time.

    The plaintext is stored beside it (``PrincipalPolicy.token``) rather than
    discarded: the manager has to be able to re-inject *the same* credential
    when the reconciler recreates an instance from a record, and when a redeploy
    runs the old and new containers side by side through AC-21's grace window.
    Hashing is therefore not a secrecy measure here — the file already holds the
    secret, and is written ``0600`` into a directory only this deployment's two
    processes can read. It is what keeps the *comparison* constant-time and
    keeps a malformed entry from authenticating anything.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class EgressPolicyStore:
    """``{data_root}/egress/policy.json`` — written by the manager, read by the proxy.

    Written atomically (tmp + ``os.replace``) for the same reason the desired
    state is: the proxy reads this file on a hot path and must never observe a
    half-written one. Reads are cached on ``(mtime, size)``; a file that has
    become unreadable leaves the previous copy in force, because an egress proxy
    that fails *open* on a bad policy would silently undo the feature, and one
    that fails *closed* would take every hosted application offline over a
    corrupted cache file.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._policies: dict[str, PrincipalPolicy] = {}
        self._stamp: tuple[float, int] | None = None
        self._load(force=True)

    @property
    def path(self) -> Path:
        return self._path

    # -- read --------------------------------------------------------------
    def _stat(self) -> tuple[float, int] | None:
        try:
            info = self._path.stat()
        except OSError:
            return None
        return (info.st_mtime, info.st_size)

    def _load(self, force: bool = False) -> None:
        stamp = self._stat()
        if stamp is None:
            if force:
                self._policies = {}
                self._stamp = None
            return
        if not force and stamp == self._stamp:
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            # Valid JSON of the wrong shape is as unreadable as broken JSON, and
            # letting it raise out of here would take down whichever hot path is
            # reading — which for the proxy is every single connection.
            if not isinstance(raw, dict):
                raise TypeError(f"expected an object, got {type(raw).__name__}")
            policies: dict[str, PrincipalPolicy] = {}
            for item in raw.get("principals") or ():
                policy = PrincipalPolicy.from_dict(item)
                if policy.principal:
                    policies[policy.principal] = policy
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("egress policy %s is unreadable, keeping the previous copy: %s", self._path, exc)
            return
        self._policies = policies
        self._stamp = stamp

    def get(self, principal: str) -> PrincipalPolicy | None:
        with self._lock:
            self._load()
            return self._policies.get(principal)

    def list(self) -> list[PrincipalPolicy]:
        with self._lock:
            self._load()
            return list(self._policies.values())

    # -- write -------------------------------------------------------------
    def put(self, policy: PrincipalPolicy) -> PrincipalPolicy:
        with self._lock:
            self._load()
            self._policies[policy.principal] = policy
            self._flush()
            return policy

    def delete(self, principal: str) -> None:
        with self._lock:
            self._load()
            if self._policies.pop(principal, None) is not None:
                self._flush()

    def _flush(self) -> None:
        # 0700 on the directory and 0600 on the file (``mkstemp``'s default,
        # preserved by ``os.replace``): the plaintext credentials live here.
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {"version": 1, "principals": [p.to_dict() for p in self._policies.values()]}
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".egress-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._stamp = self._stat()


_stores: dict[str, EgressPolicyStore] = {}
_stores_lock = threading.Lock()


def get_policy_store(config: Config) -> EgressPolicyStore:
    """Cached per policy path — a fresh ``data_root`` is a fresh store."""
    key = str(config.egress_policy_path)
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = EgressPolicyStore(config.egress_policy_path)
            _stores[key] = store
        return store


# ---------------------------------------------------------------------------
# the two phases
# ---------------------------------------------------------------------------


def platform_destinations(config: Config, platform_api_base: str = "") -> tuple[Destination, ...]:
    """What every hosted application may reach regardless of its manifest.

    ``app_facing_base`` is not optional decoration: it is the address behind
    ``BISHENG_APP_STORAGE_ENDPOINT``, and contracts §9 records that leaving it
    out breaks the attachment handle along with the whitelist. The app-proxy is
    absent on purpose — it dials *in*, never out.

    Every entry here is ``trusted``: it came out of the deployment's own
    configuration, and on an on-premise platform all three of them routinely are
    private addresses.
    """
    return merge_destinations(
        platform_api_base or config.platform_base_url,
        config.app_facing_base,
        config.egress_allow,
        trusted=True,
    )


def runtime_destinations(
    config: Config,
    *,
    platform_api_base: str = "",
    declared: object = (),
) -> tuple[Destination, ...]:
    """Run-phase allowlist for one application: platform + its own declarations.

    ``declared`` stays **untrusted** — it is the one input on this list that the
    application itself authored, and :func:`address_decision` is what keeps it
    from naming a destination inside the deployment.
    """
    return merge_destinations(platform_destinations(config, platform_api_base), declared)


def build_destinations(config: Config) -> tuple[Destination, ...]:
    """Build-phase allowlist: the package sources and the platform's distribution endpoint.

    Note what is *not* here — the application's declared domains. The build runs
    platform-authored Dockerfiles over a platform-chosen base image; letting a
    manifest widen this would put "what my build may download" under the control
    of the thing being built.
    """
    return merge_destinations(
        config.build_index_url,
        config.build_trusted_host,
        config.build_npm_registry,
        config.platform_base_url,
        config.egress_build_allow,
        # All five come from the deployment; a private package mirror is the
        # normal shape of an air-gapped install, not something to refuse.
        trusted=True,
    )


def proxy_url(config: Config, *, principal: str, token: str) -> str:
    """``http://principal:token@host:port`` — the form every HTTP client understands."""
    return f"http://{principal}:{token}@{config.egress_proxy}"


def egress_env(config: Config, *, principal: str, token: str, no_proxy: object = ()) -> dict[str, str]:
    """Proxy variables injected into an instance. Empty dict when the layer is off.

    Both cases matter. Lower-case twins are not redundancy: ``requests`` reads
    both, ``curl`` reads only the lower-case pair, and Java reads neither — an
    application whose HTTP client ignores these still cannot get out, because
    the network has no route and the firewall drops the packet. The variables
    are a convenience for the well-behaved, not the enforcement.
    """
    if not config.egress_enabled:
        return {}
    url = proxy_url(config, principal=principal, token=token)
    skip = ",".join(_no_proxy_hosts(config, no_proxy))
    return {
        ENV_EGRESS_TOKEN: token,
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "NO_PROXY": skip,
        "http_proxy": url,
        "https_proxy": url,
        "no_proxy": skip,
    }


def _no_proxy_hosts(config: Config, extra: object = ()) -> list[str]:
    """Destinations on the application network itself — reachable without a hop.

    This process is the one that matters: the attachment handle is a call from
    the application to ``RTM_APP_FACING_BASE_URL``, both endpoints sit on
    ``bisheng-apps``, and routing it through the proxy would send in-network
    traffic out to a component that would then have to come back in.
    """
    hosts = ["localhost", "127.0.0.1", "::1"]
    own = parse_destination(config.app_facing_base)
    if own is not None:
        hosts.append(own.host)
    for item in [extra] if isinstance(extra, str) else list(extra or ()):  # type: ignore[arg-type]
        destination = parse_destination(str(item))
        if destination is not None:
            hosts.append(destination.host)
    seen: list[str] = []
    for host in hosts:
        if host and host not in seen:
            seen.append(host)
    return seen


def build_proxy_buildargs(config: Config) -> dict[str, str]:
    """Proxy build args for ``docker build``.

    ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY`` are *predefined* build args:
    the daemon accepts them without an ``ARG`` line and does not warn about
    them, which is why they can be added to every runtime template's build
    without producing the "unconsumed build arg" noise that ``build_args_for``
    goes out of its way to avoid. They are not persisted into the image either,
    so a built application does not inherit the build's credential.
    """
    if not config.egress_enabled:
        return {}
    url = proxy_url(config, principal=PRINCIPAL_BUILD, token=_build_token(config))
    return {"HTTP_PROXY": url, "HTTPS_PROXY": url, "NO_PROXY": ",".join(_no_proxy_hosts(config))}


def _build_token(config: Config) -> str:
    """The build principal's credential, minted once and kept in the policy file.

    Stable rather than per-build: a build arg that changed on every build would
    invalidate the daemon's layer cache for every layer after the first, turning
    a 20-second rebuild into a full one.
    """
    store = get_policy_store(config)
    existing = store.get(PRINCIPAL_BUILD)
    # The build principal is the one with no container to inject into: the build
    # args are composed here, on demand, long after the token was minted, so the
    # stored plaintext is the only copy there is.
    token = existing.token if existing is not None and existing.token else mint_egress_token()
    store.put(
        PrincipalPolicy(
            principal=PRINCIPAL_BUILD,
            token_hash=hash_token(token),
            destinations=build_destinations(config),
            token=token,
        )
    )
    return token


def register_principal(
    config: Config,
    *,
    principal: str,
    destinations: tuple[Destination, ...],
    token: str | None = None,
) -> str:
    """Put one principal's policy on file and return the credential to inject.

    Reuses the principal's existing credential when it still has one, for the
    same reason the attachment token is reused across a redeploy: during AC-21's
    grace window the old and the new instance both serve, and both were handed
    the same value.
    """
    if not config.egress_enabled:
        return ""
    store = get_policy_store(config)
    existing = store.get(principal)
    if token is None:
        token = existing.token if existing is not None and existing.token else mint_egress_token()
    store.put(
        PrincipalPolicy(
            principal=principal,
            token_hash=hash_token(token),
            destinations=destinations,
            token=token,
        )
    )
    return token


def forget_principal(config: Config, principal: str) -> None:
    if config.egress_enabled:
        get_policy_store(config).delete(principal)


def decode_proxy_authorization(header: str) -> tuple[str, str]:
    """``Basic base64(principal:token)`` → ``(principal, token)``; ``("", "")`` if unusable."""
    scheme, _, payload = (header or "").strip().partition(" ")
    if scheme.lower() != "basic" or not payload:
        return "", ""
    try:
        decoded = base64.b64decode(payload.strip(), validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return "", ""
    principal, sep, token = decoded.partition(":")
    return (principal, token) if sep else ("", "")


def authorize(store: EgressPolicyStore, header: str, host: str, port: int) -> tuple[EgressDecision, str]:
    """One call answers both "who is this" and "may they". Returns ``(decision, principal)``."""
    principal, token = decode_proxy_authorization(header)
    policy = store.get(principal) if principal else None
    if policy is None or not policy.authenticates(token):
        return (
            EgressDecision(
                False,
                DENY_UNKNOWN_PRINCIPAL,
                "the proxy credential is missing or unknown — the platform injects it as HTTP_PROXY / HTTPS_PROXY; "
                "an application must not replace those variables",
            ),
            principal,
        )
    return decide(policy.destinations, host, port), principal


# ---------------------------------------------------------------------------
# L3 — host firewall fallback
# ---------------------------------------------------------------------------

BACKEND_IPTABLES = "iptables"
BACKEND_NFTABLES = "nftables"
BACKEND_UNKNOWN = "unknown"

#: The nftables table this module owns. Named, and hooked at a priority ahead of
#: docker's own chains, because the nftables backend has no ``DOCKER-USER``
#: equivalent to insert into (design pit 22).
NFT_TABLE = "bisheng_egress"
NFT_PRIORITY = -100


@dataclass(frozen=True)
class FirewallRule:
    """One L3 rule, backend independent. ``verdict`` is ``RETURN`` or ``DROP``."""

    verdict: str
    why: str
    protocol: str = ""
    destination: str = ""
    port: int = 0

    def iptables_spec(self, subnet: str) -> list[str]:
        spec = ["-s", subnet]
        if self.destination:
            spec += ["-d", self.destination]
        if self.protocol:
            spec += ["-p", self.protocol]
        if self.port:
            spec += ["--dport", str(self.port)]
        spec += ["-m", "comment", "--comment", f"bisheng-egress: {self.why}", "-j", self.verdict]
        return spec

    def nft_spec(self, subnet: str) -> str:
        parts = [f"ip saddr {subnet}"]
        if self.destination:
            parts.append(f"ip daddr {self.destination}")
        if self.protocol:
            parts.append(f"meta l4proto {self.protocol}")
        if self.port:
            parts.append(f"{self.protocol} dport {self.port}")
        parts.append("accept" if self.verdict == "RETURN" else "drop")
        parts.append(f'comment "bisheng-egress: {self.why}"')
        return " ".join(parts)


def firewall_rules(config: Config, *, proxy_address: str = "") -> list[FirewallRule]:
    """L3 rules for the application subnet, **in evaluation order**.

    Order is the rule set. ``RETURN`` hands the packet back to the chain that
    called us (docker's own filtering), ``DROP`` ends it; the allowances
    therefore have to come before the two denials or the subnet would be cut off
    from the proxy it is supposed to use.

    Only ``-s <apps subnet>`` is matched, so reply traffic (``-d <subnet>``)
    never meets these rules and no conntrack allowance is needed. Container DNS
    is also untouched: an application resolves through docker's embedded server
    at 127.0.0.11, which is answered inside the container's own namespace and is
    never forwarded — which is what makes a blanket UDP drop survivable.
    """
    subnet = config.apps_subnet
    if not subnet:
        return []
    rules: list[FirewallRule] = []
    exit_point = parse_destination(proxy_address or config.egress_proxy)
    if exit_point is not None and _as_ip(exit_point.host) is not None:
        for port in exit_point.ports:
            rules.append(
                FirewallRule(
                    "RETURN",
                    "the single outbound hole is the egress proxy",
                    protocol="tcp",
                    destination=exit_point.host,
                    port=port,
                )
            )
    rules.append(
        FirewallRule(
            "DROP",
            "UDP carries QUIC / HTTP3, which no hostname whitelist can read",
            protocol="udp",
        )
    )
    rules.append(FirewallRule("DROP", "default deny — everything leaves through the proxy or not at all"))
    return rules


#: Detection result, remembered for the life of the process. ``detect_firewall_backend``
#: shells out twice in the worst case, and it is called from ``GET /v1/runtime/status``,
#: which the platform polls: without this, every poll spawns subprocesses and can
#: block the event loop for as long as their timeouts. The answer only changes when
#: the daemon is reconfigured, which means a restart anyway.
_backend_cache: str = ""


def detect_firewall_backend(runner=None) -> str:
    """Which firewall backend dockerd is driving — ``iptables`` or ``nftables``.

    Probed rather than assumed because getting it wrong is *silent*: on the
    nftables backend (docker 29's default) ``iptables -I DOCKER-USER`` fails
    outright if the legacy tooling is absent, and — worse — succeeds against the
    legacy tables if it is, where nothing ever consults them. The design's other
    option, pinning iptables in the deployment baseline, is expressed here as
    ``RTM_FIREWALL_BACKEND``.
    """
    global _backend_cache
    # An injected runner is a test or a deliberate re-probe; it neither reads nor
    # fills the cache, so one test's answer cannot leak into the next.
    if runner is not None:
        if runner(["iptables", "-S", "DOCKER-USER"])[0] == 0:
            return BACKEND_IPTABLES
        return BACKEND_NFTABLES if runner(["nft", "list", "tables"])[0] == 0 else BACKEND_UNKNOWN
    if _backend_cache:
        return _backend_cache
    if _run(["iptables", "-S", "DOCKER-USER"])[0] == 0:
        _backend_cache = BACKEND_IPTABLES
    elif _run(["nft", "list", "tables"])[0] == 0:
        _backend_cache = BACKEND_NFTABLES
    else:
        _backend_cache = BACKEND_UNKNOWN
    return _backend_cache


def _run(argv: list[str]) -> tuple[int, str]:  # pragma: no cover - exercised on a real host
    import subprocess

    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, ValueError) as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def iptables_commands(config: Config, rules: list[FirewallRule]) -> list[list[str]]:
    """``iptables -I DOCKER-USER <n> …`` for each rule, positions in order.

    Explicit positions rather than repeated ``-I … 1``: inserting at the head N
    times reverses the list, and a reversed rule set here means "deny
    everything" evaluates before "allow the proxy".
    """
    return [
        ["iptables", "-I", "DOCKER-USER", str(index), *rule.iptables_spec(config.apps_subnet)]
        for index, rule in enumerate(rules, start=1)
    ]


def iptables_delete_commands(config: Config, rules: list[FirewallRule]) -> list[list[str]]:
    """The exact inverse, so re-applying is idempotent instead of cumulative."""
    return [["iptables", "-D", "DOCKER-USER", *rule.iptables_spec(config.apps_subnet)] for rule in rules]


def nft_script(config: Config, rules: list[FirewallRule]) -> str:
    """A complete, idempotent nft ruleset for the same rules.

    ``delete table`` first: nft has no "insert if absent", and re-running an
    ``add rule`` script appends duplicates forever. The whole table is ours, so
    dropping it cannot disturb docker's.
    """
    body = "\n".join(f"    add rule inet {NFT_TABLE} forward {rule.nft_spec(config.apps_subnet)}" for rule in rules)
    return (
        f"#!/usr/sbin/nft -f\n"
        f"# BiSheng hosted-app egress (F054 D12 L3). Generated by runtime_manager.egress.\n"
        f"delete table inet {NFT_TABLE}\n"
        f"table inet {NFT_TABLE} {{\n"
        f"    chain forward {{\n"
        f"        type filter hook forward priority {NFT_PRIORITY}; policy accept;\n"
        f"    }}\n"
        f"}}\n"
        f"table inet {NFT_TABLE} {{\n"
        f"{body}\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# pre-flight
# ---------------------------------------------------------------------------


def egress_preflight(config: Config, docker=None, runner=None) -> list[dict[str, Any]]:
    """``runtime/status`` rows for the outbound whitelist (design §7 pre-flight).

    Each row names the fix rather than the symptom, because every failure here
    reaches somebody as something else entirely: a non-``--internal`` network
    looks like nothing at all (apps reach the internet and nobody notices), and
    an unreachable proxy looks like "the application cannot call its API".
    """
    checks: list[dict[str, Any]] = []
    if not config.egress_enabled:
        return [
            {
                "name": "egress_whitelist",
                "ok": False,
                "detail": (
                    "not deployed — hosted applications have unrestricted outbound access (AC-16). "
                    "Set RTM_EGRESS_PROXY to the proxy's address on the application network and run "
                    "`python -m runtime_manager.egress_proxy`"
                ),
            }
        ]

    checks.append(
        {
            "name": "egress_whitelist",
            "ok": True,
            "detail": (
                f"instances dial {config.egress_proxy}; always allowed: "
                f"{', '.join(d.render() for d in platform_destinations(config)) or '(nothing configured)'}"
            ),
        }
    )
    checks.append(_internal_network_check(config, docker))
    checks.append(_firewall_check(config, runner))
    return checks


def _internal_network_check(config: Config, docker) -> dict[str, Any]:
    name = "application_network_internal"
    if docker is None:
        return {"name": name, "ok": False, "detail": "not checked — the orchestration backend is unreachable"}
    try:
        networks = docker.list_networks(name=config.network)
    except Exception as exc:
        return {"name": name, "ok": False, "detail": f"cannot list networks: {exc}"}
    if not networks:
        return {"name": name, "ok": False, "detail": f"{config.network} does not exist"}
    internal = bool(networks[0].get("Internal"))
    if internal:
        return {"name": name, "ok": True, "detail": f"{config.network} is --internal; the proxy is the only way out"}
    return {
        "name": name,
        "ok": False,
        "detail": (
            f"{config.network} is not --internal, so instances can route around the proxy. Recreate it: "
            f"stop the apps, `docker network rm {config.network}`, "
            f"`docker network create --internal {config.network}`, then start them again"
        ),
    }


def _firewall_check(config: Config, runner) -> dict[str, Any]:
    name = "egress_firewall_fallback"
    if not config.apps_subnet:
        return {
            "name": name,
            "ok": False,
            "detail": (
                "RTM_APPS_SUBNET is unset, so the L3 fallback cannot be generated — the whitelist then rests "
                f"entirely on {config.network} being --internal. Read the subnet off "
                f"`docker network inspect {config.network}`"
            ),
        }
    backend = config.firewall_backend or detect_firewall_backend(runner)
    if backend == BACKEND_IPTABLES:
        return {
            "name": name,
            "ok": True,
            "detail": "iptables backend; apply with `python -m runtime_manager.egress firewall --apply`",
        }
    if backend == BACKEND_NFTABLES:
        return {
            "name": name,
            "ok": False,
            "detail": (
                "the docker daemon is on the nftables backend, which has no DOCKER-USER chain (design pit 22): "
                "iptables rules would be accepted and never consulted. Install the generated nft ruleset "
                "(`python -m runtime_manager.egress firewall --print-nft`) or pin the daemon to the iptables backend"
            ),
        }
    return {
        "name": name,
        "ok": False,
        "detail": "cannot tell which firewall backend the daemon drives — set RTM_FIREWALL_BACKEND=iptables|nftables",
    }


# ---------------------------------------------------------------------------
# operator entry point
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    """``python -m runtime_manager.egress firewall [--print|--print-nft|--apply|--delete]``."""
    import argparse

    from runtime_manager.config import get_config

    parser = argparse.ArgumentParser(prog="runtime_manager.egress", description="hosted-app outbound whitelist")
    sub = parser.add_subparsers(dest="command", required=True)
    firewall = sub.add_parser("firewall", help="L3 fallback rules for the application subnet")
    group = firewall.add_mutually_exclusive_group()
    group.add_argument("--print", action="store_true", help="print the iptables commands (default)")
    group.add_argument("--print-nft", action="store_true", help="print an nft ruleset")
    group.add_argument("--apply", action="store_true", help="delete then insert the iptables rules")
    group.add_argument("--delete", action="store_true", help="remove the iptables rules")
    args = parser.parse_args(argv)

    config = get_config()
    rules = firewall_rules(config)
    if not rules:
        print("RTM_APPS_SUBNET is unset — nothing to generate")
        return 1
    if args.print_nft:
        print(nft_script(config, rules), end="")
        return 0
    if args.apply or args.delete:
        for command in iptables_delete_commands(config, rules):
            _run(command)
        if args.delete:
            return 0
        failures = 0
        for command in iptables_commands(config, rules):
            code, output = _run(command)
            if code != 0:
                failures += 1
                print(f"FAILED {' '.join(command)}: {output.strip()}")
        return 1 if failures else 0
    for command in iptables_commands(config, rules):
        print(" ".join(command))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
