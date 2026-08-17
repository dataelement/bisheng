"""Programmable doubles for the orchestration backend and the host.

Why a hand-written fake instead of ``unittest.mock``: every lifecycle test in
this suite asserts on the *exact create payload* that would hit the daemon
(``HostConfig.NanoCpus`` / ``ReadonlyRootfs`` / ``SecurityOpt`` / the absence of
``PortBindings``). A mock records calls but cannot answer "and then what does
``inspect`` return", which is precisely what probe / routing / reconcile need.
The fake keeps a tiny container state machine so those flows are testable end
to end without a daemon.

What the fake deliberately does **not** simulate — and therefore what
``@pytest.mark.docker`` covers on real infrastructure:

* whether the kernel actually enforces ``Memory`` / ``NanoCpus`` (AC-63),
* whether ``restart: unless-stopped`` actually restarts a killed process,
* whether a real ``HEALTHCHECK`` flips ``State.Health`` on its own,
* whether ``docker build`` produces a runnable image.

The fake's job is the layer we own: did we ask for the right thing.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_ID_SEQ = itertools.count(1)


class FakeDockerError(RuntimeError):
    """Stand-in for ``docker.errors.APIError``."""


@dataclass
class FakeContainer:
    name: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: f"fakecid{next(_ID_SEQ):08d}")
    running: bool = False
    health: str | None = None  # None | starting | healthy | unhealthy
    ip: str = "172.31.0.2"
    exit_code: int = 0
    restart_count: int = 0
    started_at: str = ""
    logs: str = ""

    @property
    def labels(self) -> dict[str, str]:
        return self.payload.get("Labels") or {}

    def inspect(self, network: str) -> dict[str, Any]:
        return {
            "Id": self.id,
            "Name": f"/{self.name}",
            "Created": self.started_at,
            "RestartCount": self.restart_count,
            "State": {
                "Running": self.running,
                "Status": "running" if self.running else "exited",
                "ExitCode": self.exit_code,
                "StartedAt": self.started_at,
                **({"Health": {"Status": self.health}} if self.health else {}),
            },
            "Config": {
                "Image": self.payload.get("Image"),
                "Env": list(self.payload.get("Env") or []),
                "Labels": dict(self.labels),
                "Healthcheck": self.payload.get("Healthcheck"),
                "ExposedPorts": self.payload.get("ExposedPorts"),
            },
            "HostConfig": dict(self.payload.get("HostConfig") or {}),
            "NetworkSettings": {
                "Networks": {network: {"IPAddress": self.ip if self.running else ""}}
            },
        }


class FakeDockerBackend:
    """In-memory :class:`runtime_manager.docker_backend.DockerBackend`."""

    def __init__(self, network: str = "bisheng-apps") -> None:
        self.network = network
        self.containers: dict[str, FakeContainer] = {}
        self.images: list[str] = []
        #: Networks the daemon knows about. Starts with the application network
        #: present; emptying it reproduces the "nobody ran ``docker network
        #: create bisheng-apps``" state a fresh host is actually in.
        self.networks: list[str] = [network]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reachable = True
        #: Stream the next ``build_image`` call replays. A dict with a ``error``
        #: key makes the build fail at that line, exactly like the daemon does.
        self.build_stream: list[dict[str, Any]] = [{"stream": "Successfully built abc123\n"}]
        self.build_raises: Exception | None = None

    # -- helpers used by tests --------------------------------------------
    def get(self, name_or_id: str) -> FakeContainer:
        for c in self.containers.values():
            if name_or_id in (c.name, c.id):
                return c
        raise FakeDockerError(f"no such container: {name_or_id}")

    def created_payload(self, name: str) -> dict[str, Any]:
        return self.get(name).payload

    def set_health(self, name_or_id: str, health: str) -> None:
        self.get(name_or_id).health = health

    def last_call(self, method: str) -> dict[str, Any]:
        for name, kwargs in reversed(self.calls):
            if name == method:
                return kwargs
        raise AssertionError(f"{method} was never called")

    def call_count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    # -- DockerBackend protocol -------------------------------------------
    def ping(self) -> bool:
        self.calls.append(("ping", {}))
        return self.reachable

    def _require_reachable(self) -> None:
        if not self.reachable:
            raise FakeDockerError("orchestration backend unreachable")

    def create_container(self, name: str, payload: dict[str, Any]) -> str:
        self.calls.append(("create_container", {"name": name, "payload": payload}))
        self._require_reachable()
        if any(c.name == name for c in self.containers.values()):
            raise FakeDockerError(f"conflict: container name {name} already in use")
        container = FakeContainer(name=name, payload=payload)
        self.containers[container.id] = container
        return container.id

    def start_container(self, container: str) -> None:
        self.calls.append(("start_container", {"container": container}))
        self._require_reachable()
        c = self.get(container)
        c.running = True
        c.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if c.payload.get("Healthcheck") and c.health is None:
            c.health = "starting"

    def stop_container(self, container: str, timeout: int = 10) -> None:
        self.calls.append(("stop_container", {"container": container, "timeout": timeout}))
        self._require_reachable()
        c = self.get(container)
        c.running = False
        c.health = None

    def remove_container(self, container: str, force: bool = False) -> None:
        self.calls.append(("remove_container", {"container": container, "force": force}))
        self._require_reachable()
        c = self.get(container)
        if c.running and not force:
            raise FakeDockerError("cannot remove a running container")
        self.containers.pop(c.id, None)

    def inspect_container(self, container: str) -> dict[str, Any]:
        self.calls.append(("inspect_container", {"container": container}))
        self._require_reachable()
        return self.get(container).inspect(self.network)

    def list_containers(
        self, all_states: bool = True, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("list_containers", {"all_states": all_states, "filters": filters}))
        self._require_reachable()
        wanted_labels = [] if not filters else list(filters.get("label") or [])
        out: list[dict[str, Any]] = []
        for c in self.containers.values():
            if not all_states and not c.running:
                continue
            if not _labels_match(c.labels, wanted_labels):
                continue
            out.append(
                {
                    "Id": c.id,
                    "Names": [f"/{c.name}"],
                    "Labels": dict(c.labels),
                    "State": "running" if c.running else "exited",
                    "Status": "Up 1 second" if c.running else "Exited (0) 1 second ago",
                    "Image": c.payload.get("Image"),
                }
            )
        return out

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
        self.calls.append(
            (
                "build_image",
                {
                    "context_dir": context_dir,
                    "dockerfile": dockerfile,
                    "tag": tag,
                    "buildargs": dict(buildargs),
                    "memory_bytes": memory_bytes,
                    "network_mode": network_mode,
                },
            )
        )
        self._require_reachable()
        if self.build_raises is not None:
            raise self.build_raises
        stream = list(self.build_stream)
        if not any("error" in line for line in stream):
            self.images.append(tag)
        return iter(stream)

    def list_images(self, name: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("list_images", {"name": name}))
        self._require_reachable()
        return [
            {"Id": f"sha256:{i}", "RepoTags": [tag]}
            for i, tag in enumerate(self.images)
            if name is None or tag.startswith(name)
        ]

    def remove_image(self, image: str, force: bool = False) -> None:
        self.calls.append(("remove_image", {"image": image, "force": force}))
        self._require_reachable()
        if image in self.images:
            self.images.remove(image)

    def list_networks(self, name: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("list_networks", {"name": name}))
        self._require_reachable()
        return [
            {"Name": item, "Id": f"fakenet{index}"}
            for index, item in enumerate(self.networks)
            if name is None or item == name
        ]

    def container_logs(
        self, container: str, tail: int | str = "all", since: int | None = None
    ) -> str:
        self.calls.append(("container_logs", {"container": container, "tail": tail, "since": since}))
        self._require_reachable()
        return self.get(container).logs


def _labels_match(labels: dict[str, str], wanted: list[str]) -> bool:
    for item in wanted:
        if "=" in item:
            key, value = item.split("=", 1)
            if labels.get(key) != value:
                return False
        elif item not in labels:
            return False
    return True


@dataclass
class FakeHostSnapshot:
    """Duck-typed stand-in for ``runtime_manager.admission.HostSnapshot``.

    Structural rather than nominal on purpose: ``tests/fakes.py`` importing the
    module under test would make the fake unusable for the very first red test.
    """

    mem_total_mb: int
    mem_available_mb: int
    cpu_count: float


class FakeHostProbe:
    """Injectable ``/proc/meminfo`` + ``nproc``.

    114 is the reference machine: 32 GiB total, and ``MemAvailable`` has been
    observed as low as ~0.9 GiB with the two JVMs, uvicorn, three celery
    workers and four linsight workers resident (K2). Both numbers are settable
    so a test can reproduce that exact shape.
    """

    def __init__(
        self,
        mem_total_mb: int = 32768,
        mem_available_mb: int = 20480,
        cpu_count: float = 8,
    ) -> None:
        self.mem_total_mb = mem_total_mb
        self.mem_available_mb = mem_available_mb
        self.cpu_count = cpu_count

    def snapshot(self) -> FakeHostSnapshot:
        return FakeHostSnapshot(
            mem_total_mb=self.mem_total_mb,
            mem_available_mb=self.mem_available_mb,
            cpu_count=self.cpu_count,
        )


class ImmediateScheduler:
    """Retirement scheduler double — runs the callback now, records the delay.

    The grace period (30 s) is a *number under test* (AC-21: it must stay well
    clear of the app-proxy's 3 s route cache), so the tests assert the delay
    that was requested rather than waiting for it.
    """

    def __init__(self) -> None:
        self.scheduled: list[float] = []

    def schedule(self, delay: float, fn, *args, **kwargs) -> None:
        self.scheduled.append(delay)
        fn(*args, **kwargs)


class RecordingScheduler:
    """Retirement scheduler double that records but never runs the callback."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[float, Any]] = []

    def schedule(self, delay: float, fn, *args, **kwargs) -> None:
        self.scheduled.append((delay, (fn, args, kwargs)))

    def run_all(self) -> None:
        pending, self.scheduled = self.scheduled, []
        for _delay, (fn, args, kwargs) in pending:
            fn(*args, **kwargs)


class FakeClock:
    """Monotonic clock with an explicit ``advance`` — no ``time.sleep`` in tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeHttpProbe:
    """Programmable HTTP readiness probe.

    ``responses`` is consumed one entry per attempt; each entry is either an int
    status code or an exception instance to raise (connection refused while the
    app is still booting). Once exhausted, the last entry repeats.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses: list[Any] = responses or [200]
        self.requests: list[str] = []
        self._index = 0

    def get(self, url: str, timeout: float = 2.0) -> int:
        self.requests.append(url)
        item = self.responses[min(self._index, len(self.responses) - 1)]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return int(item)
