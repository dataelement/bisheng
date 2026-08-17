"""Route table — the app-proxy's only question to the manager (D5.1).

Answering with an *address* rather than a name is the whole design. On 114 the
app-proxy is a host systemd unit outside every docker network: container names
do not resolve there, and AC-33 forbids publishing a host port. The container's
address on the ``bisheng-apps`` bridge is reachable from the host and from
nowhere else — and it works identically in the compose deployment, so the two
shapes share one mechanism instead of two (坑 30).

``generation`` is the app-proxy's cache-invalidation signal: it increments only
after a new instance passes its readiness gate (AC-21). The platform's
``app_instance.exec_ref`` is *not* consulted here — that column is an audit and
triage reference. Routing has exactly one source of truth, and it is the
manager's desired state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime_manager.config import Config
from runtime_manager.desired_state import ALIVE_PHASES, DESIRED_RUNNING, get_store
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.errors import NotFoundError


@dataclass(frozen=True)
class Route:
    upstream: str
    version_id: str
    generation: int

    def to_response(self) -> dict[str, Any]:
        return {
            "upstream": self.upstream,
            "version_id": self.version_id,
            "generation": self.generation,
        }


class RoutingService:
    def __init__(self, config: Config, docker: DockerBackend | None = None, store=None) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._store = store if store is not None else get_store(config)

    def get_route(self, app_id: str) -> Route:
        record = self._store.get(app_id)
        if record is None:
            raise NotFoundError(f"no instance is declared for app {app_id}")
        if record.desired != DESIRED_RUNNING or record.phase not in ALIVE_PHASES:
            # Stopped is not an error the proxy should retry: it is a state the
            # product renders as the "已停用" page (AC-29).
            raise NotFoundError(f"app {app_id} is not running", phase=record.phase)

        address = self._address(record.container_id or record.container_name)
        if not address:
            raise NotFoundError(f"app {app_id} has no address on the application network")
        return Route(
            upstream=f"http://{address}:{record.port}",
            version_id=record.version_id,
            generation=record.generation,
        )

    def _address(self, container: str) -> str:
        try:
            info = self._docker.inspect_container(container)
        except Exception:
            return ""
        networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
        return (networks.get(self._config.network) or {}).get("IPAddress") or ""
