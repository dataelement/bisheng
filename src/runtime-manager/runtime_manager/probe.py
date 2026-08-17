"""Start-up readiness probe (AC-18).

"Ready" is defined once, here, and reused by three callers that would otherwise
each grow their own slightly different definition: the deploy health gate
(AC-21), F055's hosted pre-flight, and the approval-time preview instance. The
definition is deliberately blunt — the app answers its declared health path on
its declared port with something that is not a 5xx — because anything cleverer
would be a promise about frameworks we do not control.

Two behaviours matter more than the polling itself:

* **A dead container is a verdict, not a wait.** The usual failure is a start
  command that crashes in under a second; waiting out the full 90 s timeout
  would be technically honest and practically useless.
* **The address is the bridge address.** Never a container name (the app-proxy
  on 114 is a host process and cannot resolve one, 坑 30) and never localhost
  (that would be the manager itself).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from runtime_manager.config import LABEL_MANAGED, Config
from runtime_manager.desired_state import get_store
from runtime_manager.docker_backend import DockerBackend, get_docker_backend

logger = logging.getLogger(__name__)

PROBE_NAME_PREFIX = "bisheng-probe-"


@dataclass(frozen=True)
class ProbeOutcome:
    ready: bool
    reason: str = ""
    elapsed: float = 0.0


class HttpProbe(Protocol):
    def get(self, url: str, timeout: float = 2.0) -> int: ...


class HttpxProbe:
    def get(self, url: str, timeout: float = 2.0) -> int:
        import httpx

        response = httpx.get(url, timeout=timeout, follow_redirects=False)
        return response.status_code


class SystemClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


class ProbeService:
    def __init__(
        self,
        config: Config,
        docker: DockerBackend | None = None,
        http: HttpProbe | None = None,
        clock: Any | None = None,
        store=None,
    ) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._http = http or HttpxProbe()
        self._clock = clock or SystemClock()
        self._store = store if store is not None else get_store(config)

    # -- public ------------------------------------------------------------
    def wait_ready(self, container: str, port: int, health_path: str, timeout: float | None = None) -> ProbeOutcome:
        budget = float(timeout if timeout is not None else self._config.probe_timeout_seconds)
        deadline = self._clock.monotonic() + budget
        path = health_path if health_path.startswith("/") else f"/{health_path}"
        last_error = "no attempt completed"

        while True:
            state = self._container_state(container)
            if state is None:
                return ProbeOutcome(False, f"instance {container} disappeared while starting")
            if not state["running"]:
                return ProbeOutcome(
                    False,
                    f"instance exited during start-up (exit code {state['exit_code']}); "
                    "check the run logs for the start command's own error",
                )
            address = state["ip"]
            if address:
                url = f"http://{address}:{port}{path}"
                try:
                    status = self._http.get(url, timeout=2.0)
                    if status < 500:
                        return ProbeOutcome(True, "", elapsed=budget - (deadline - self._clock.monotonic()))
                    last_error = f"{url} answered HTTP {status}"
                except Exception as exc:
                    last_error = f"{url}: {exc}"
            else:
                last_error = "no address on the application network yet"

            if self._clock.monotonic() >= deadline:
                return ProbeOutcome(False, f"not ready within {budget:g}s; last attempt: {last_error}", elapsed=budget)
            self._clock.sleep(self._config.probe_interval_seconds)

    def probe_app(self, app_id: str, timeout: float | None = None) -> ProbeOutcome:
        record = self._store.get(app_id)
        if record is None:
            return ProbeOutcome(False, f"no instance is declared for app {app_id}")
        return self.wait_ready(record.container_id or record.container_name, record.port, record.health_path, timeout)

    def probe_image(
        self,
        *,
        image_ref: str,
        env: dict[str, str],
        port: int,
        health_path: str,
        timeout: float | None = None,
    ) -> ProbeOutcome:
        """Throwaway instance of an image — no app, no volume, no restart policy.

        ``/data`` is a tmpfs rather than a bind: an app that opens its SQLite at
        import time must still be able to start, but a pre-flight must never be
        able to touch a real application's data.
        """
        name = f"{PROBE_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        payload = {
            "Image": image_ref,
            "Env": [f"{k}={v}" for k, v in sorted(env.items())],
            "ExposedPorts": {f"{port}/tcp": {}},
            "Labels": {LABEL_MANAGED: "probe"},
            "HostConfig": {
                "ReadonlyRootfs": True,
                # ``mode=1777`` is required, not cosmetic: the container runs as
                # a non-root app user (uid 10001, builder DEFAULT_APP_UID), and a
                # tmpfs mounts root-owned 0755 by default — so an app that opens
                # its SQLite at /data/app.db on start-up gets "unable to open
                # database file", exits 1, and the probe fails 16228. Sticky
                # world-writable (like /tmp) lets the app user create its file.
                "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m", "/data": "rw,size=64m,mode=1777"},
                "SecurityOpt": ["no-new-privileges:true"],
                "PortBindings": {},
                "PublishAllPorts": False,
                "NetworkMode": self._config.network,
                # A probe that keeps restarting is a probe that never fails.
                "RestartPolicy": {"Name": "no"},
            },
        }
        container_id: str | None = None
        try:
            container_id = self._docker.create_container(name, payload)
            self._docker.start_container(container_id)
            return self.wait_ready(container_id, port, health_path, timeout)
        except Exception as exc:
            return ProbeOutcome(False, f"cannot start a probe instance: {exc}")
        finally:
            if container_id is not None:
                self._cleanup(container_id)

    # -- helpers -----------------------------------------------------------
    def _cleanup(self, ref: str) -> None:
        for action in (
            lambda: self._docker.stop_container(ref, timeout=2),
            lambda: self._docker.remove_container(ref, force=True),
        ):
            try:
                action()
            except Exception as exc:
                logger.debug("probe cleanup %s: %s", ref, exc)

    def _container_state(self, container: str) -> dict[str, Any] | None:
        try:
            info = self._docker.inspect_container(container)
        except Exception:
            return None
        state = info.get("State") or {}
        networks = (info.get("NetworkSettings") or {}).get("Networks") or {}
        network = networks.get(self._config.network) or {}
        return {
            "running": bool(state.get("Running")),
            "exit_code": state.get("ExitCode"),
            "health": (state.get("Health") or {}).get("Status"),
            "ip": network.get("IPAddress") or "",
        }
