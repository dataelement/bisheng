"""The one and only place that knows what an orchestration backend is.

Everything above this module (admission / builder / lifecycle / probe / routing
/ reconciler) speaks the :class:`DockerBackend` protocol, never ``import
docker``. Three things fall out of that, and all three are the point:

1. **D2-A → D2-B costs a base URL.** Putting ``tecnativa/docker-socket-proxy``
   in front of dockerd is ``RTM_DOCKER_HOST=tcp://127.0.0.1:2375`` and nothing
   else — no call site changes.
2. **F059 (k8s) replaces one file.** The protocol is written in terms of
   "create / start / stop / inspect / build / logs", which a k8s backend can
   satisfy; the intent RPC above it is already form agnostic (INV-33).
3. **The unit suite needs neither a daemon nor the SDK.** The docker SDK is
   imported *inside* :meth:`_RealDockerBackend._client`, so
   ``tests/fakes.py::FakeDockerBackend`` is a complete substitute. Container
   behaviour that a fake cannot honestly simulate (real limits, real restart,
   real health) is marked ``@pytest.mark.docker`` and verified in the CI
   middleware stage and on 114.

The payload passed to :meth:`create_container` is the raw Docker Engine
``POST /containers/create`` body (``{"Image", "Env", "Labels", "Healthcheck",
"ExposedPorts", "HostConfig", "NetworkingConfig"}``). Using the engine's own
shape — rather than the SDK's high-level keyword soup — is what makes the
lifecycle tests able to assert ``HostConfig.NanoCpus`` / ``ReadonlyRootfs`` /
``SecurityOpt`` / the *absence* of ``PortBindings`` directly against the value
that will hit the daemon.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

from runtime_manager.config import get_config
from runtime_manager.errors import BackendUnavailableError


@runtime_checkable
class DockerBackend(Protocol):
    """Form-specific operations the manager needs. Keep this list minimal."""

    def ping(self) -> bool: ...

    def create_container(self, name: str, payload: dict[str, Any]) -> str: ...

    def start_container(self, container: str) -> None: ...

    def stop_container(self, container: str, timeout: int = 10) -> None: ...

    def remove_container(self, container: str, force: bool = False) -> None: ...

    def inspect_container(self, container: str) -> dict[str, Any]: ...

    def list_containers(
        self, all_states: bool = True, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

    def build_image(
        self,
        *,
        context_dir: str,
        dockerfile: str,
        tag: str,
        buildargs: dict[str, str],
        memory_bytes: int,
        network_mode: str | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def list_images(self, name: str | None = None) -> list[dict[str, Any]]: ...

    def remove_image(self, image: str, force: bool = False) -> None: ...

    def list_networks(self, name: str | None = None) -> list[dict[str, Any]]: ...

    def container_logs(self, container: str, tail: int | str = "all", since: int | None = None) -> str: ...


class _RealDockerBackend:
    """Docker Engine API implementation (lazy SDK import — see module docstring)."""

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url or None
        self._api = None

    def _client(self):
        if self._api is None:
            try:
                import docker
            except ImportError as exc:  # pragma: no cover - deployment error
                raise BackendUnavailableError(f"docker SDK is not installed: {exc}")
            try:
                self._api = docker.APIClient(base_url=self._base_url) if self._base_url else docker.APIClient()
            except Exception as exc:  # pragma: no cover - daemon down
                raise BackendUnavailableError(f"cannot reach the orchestration backend: {exc}")
        return self._api

    def ping(self) -> bool:
        try:
            return bool(self._client().ping())
        except Exception:
            return False

    def create_container(self, name: str, payload: dict[str, Any]) -> str:
        return self._client().create_container_from_config(payload, name=name)["Id"]

    def start_container(self, container: str) -> None:
        self._client().start(container)

    def stop_container(self, container: str, timeout: int = 10) -> None:
        self._client().stop(container, timeout=timeout)

    def remove_container(self, container: str, force: bool = False) -> None:
        # v=False on purpose: named/bind volumes are the application's data and
        # are only ever removed by an explicit destroy(purge_volume=True) —
        # AC-40 ("no path other than the owner's explicit delete destroys data").
        self._client().remove_container(container, force=force, v=False)

    def inspect_container(self, container: str) -> dict[str, Any]:
        return self._client().inspect_container(container)

    def list_containers(self, all_states: bool = True, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._client().containers(all=all_states, filters=filters or {})

    def build_image(
        self,
        *,
        context_dir: str,
        dockerfile: str,
        tag: str,
        buildargs: dict[str, str],
        memory_bytes: int,
        network_mode: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        return self._client().build(
            path=context_dir,
            dockerfile=dockerfile,
            tag=tag,
            buildargs=buildargs,
            container_limits={"memory": memory_bytes},
            network_mode=network_mode,
            rm=True,
            forcerm=True,
            pull=False,
            decode=True,
        )

    def list_images(self, name: str | None = None) -> list[dict[str, Any]]:
        return self._client().images(name=name)

    def remove_image(self, image: str, force: bool = False) -> None:
        self._client().remove_image(image, force=force)

    def list_networks(self, name: str | None = None) -> list[dict[str, Any]]:
        # Only ever read. The application network is created by the deployment
        # (a documented pre-flight, contracts §7), never by this process: a
        # manager that silently creates its own network hides the one mistake
        # that makes every publish fail on a fresh host.
        return self._client().networks(names=[name] if name else None)

    def container_logs(self, container: str, tail: int | str = "all", since: int | None = None) -> str:
        raw = self._client().logs(container, stdout=True, stderr=True, tail=tail, since=since, timestamps=True)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)


#: D2-B — ``tecnativa/docker-socket-proxy`` permission flag → the protocol
#: methods that need it. This is the endpoint whitelist itself, in the one place
#: that knows which Docker API endpoints this process actually calls, so that
#: adding a method to :class:`DockerBackend` without widening the proxy fails a
#: test here rather than failing a deploy on a customer's host.
#:
#: The proxy's permissions are coarse (a flag per endpoint family, plus ``POST``
#: as a global write gate), so this is the *smallest* set that makes the
#: protocol above work — not a list of everything the manager might like.
SOCKET_PROXY_PERMISSIONS: dict[str, tuple[str, ...]] = {
    # ``GET /_ping`` — the reachability answer ``runtime/status`` reports.
    "PING": ("ping",),
    # ``/containers/*`` — create, inspect, list, remove, logs.
    "CONTAINERS": (
        "create_container",
        "inspect_container",
        "list_containers",
        "remove_container",
        "container_logs",
    ),
    # ``/containers/{id}/start`` and ``/stop`` are gated separately from
    # ``CONTAINERS`` by the proxy, and separately from each other.
    "ALLOW_START": ("start_container",),
    "ALLOW_STOP": ("stop_container",),
    # ``POST /build``.
    "BUILD": ("build_image",),
    # ``/images/*`` — the retention sweep and its ``list`` half.
    "IMAGES": ("list_images", "remove_image"),
    # ``GET /networks`` — read only; the application network is created by the
    # deployment, never by this process.
    "NETWORKS": ("list_networks",),
    # The global write gate. Without it the proxy is read-only and every create
    # / build / remove answers 403 — which surfaces to a user as "编排器不可用"
    # with a perfectly healthy daemon behind it.
    "POST": (
        "create_container",
        "start_container",
        "stop_container",
        "remove_container",
        "build_image",
        "remove_image",
    ),
}

#: Flags the proxy understands that must stay **off**, listed rather than merely
#: omitted: the image defaults them to 0, but writing them down is what makes a
#: reviewer able to read this table as a decision instead of an oversight.
#: ``EXEC`` is the one that matters — it is arbitrary code in any container on
#: the host, and nothing in :class:`DockerBackend` asks for it. ``VOLUMES`` is
#: off because instances use bind mounts the manager creates on the filesystem,
#: not named volumes. ``ALLOW_RESTARTS`` is off because a restart is precisely
#: what the reconciler must own (contracts §8: exited ⇒ ``start``, never a
#: restart that loses the daemon's backoff).
#:
#: ``VERSION`` is off and that is a real decision, not an omission: ``docker-py``
#: only calls ``GET /version`` when it is constructed with ``version="auto"``,
#: and :class:`_RealDockerBackend` deliberately does not. If anyone ever adds
#: that argument, every call will start failing 403 at construction — the flag,
#: not the argument, is where the fix belongs.
SOCKET_PROXY_DENIED: tuple[str, ...] = (
    "ALLOW_RESTARTS",
    "AUTH",
    "COMMIT",
    "CONFIGS",
    "DISTRIBUTION",
    "EVENTS",
    "EXEC",
    "GRPC",
    "INFO",
    "NODES",
    "PLUGINS",
    "SECRETS",
    "SERVICES",
    "SESSION",
    "SWARM",
    "SYSTEM",
    "TASKS",
    "VERSION",
    "VOLUMES",
)


def socket_proxy_env() -> dict[str, str]:
    """The proxy container's full environment — every flag, on or off.

    Every flag is emitted explicitly, including the zeros. Relying on the
    image's defaults would mean a future version of the image that flips one of
    them silently widens this deployment's blast radius, and nothing in our
    repository would have changed.
    """
    env = dict.fromkeys(SOCKET_PROXY_PERMISSIONS, "1")
    env.update(dict.fromkeys(SOCKET_PROXY_DENIED, "0"))
    return dict(sorted(env.items()))


def protocol_methods() -> tuple[str, ...]:
    """Method names of the :class:`DockerBackend` protocol, for the lockstep test."""
    return tuple(sorted(name for name in vars(DockerBackend) if not name.startswith("_")))


_backend: DockerBackend | None = None


def get_docker_backend() -> DockerBackend:
    global _backend
    if _backend is None:
        _backend = _RealDockerBackend(get_config().docker_host)
    return _backend


def set_docker_backend(backend: DockerBackend | None) -> None:
    """Injection seam used by tests and by the composition root in ``main``."""
    global _backend
    _backend = backend
