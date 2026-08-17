"""T046 — the orchestrator facade contract, plus the zero-orchestration proof.

The last test in this file is not about the client at all: it walks
``src/backend/bisheng/**`` and asserts backend holds no orchestration access
surface. That is AC-14's automated half (arch-guard RULE-10 is the other), and
it lives next to the facade on purpose — the day someone "just imports docker
here for a quick fix", this is the file that explains why they cannot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import tomllib
from pathlib import Path

import httpx
import pytest

from bisheng.common.errcode.app_factory import (
    AppCapacityInsufficientError,
    AppNotFoundError,
    AppOrchestratorUnavailableError,
    AppRuntimeNotSupportedError,
)

SECRET = "f054-test-secret"
BASE_URL = "http://runtime-manager.test"

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"
BACKEND_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _client(handler, *, secret: str = SECRET):
    from bisheng.app_runtime.domain.services.orchestrator_client import OrchestratorClient

    return OrchestratorClient(base_url=BASE_URL, secret=secret, transport=httpx.MockTransport(handler))


def _ok(payload: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(status_code, json=payload)

    handler.request = None
    return handler


def _error(code: str, *, status_code: int, **extra):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.request = request
        return httpx.Response(status_code, json={"detail": {"code": code, "message": f"manager says {code}", **extra}})

    handler.request = None
    return handler


class TestSignature:
    async def test_hmac_signature_matches_manager_contract(self):
        """``METHOD\\nPATH\\nraw_body``, hex, ``X-Signature`` — over the bytes actually sent."""
        handler = _ok({"admitted": True, "reason": "", "snapshot": {}})
        client = _client(handler)

        await client.admission(tier={"cpu": 1.0, "mem": 2048}, purpose="run")

        request = handler.request
        raw = request.content
        expected = hmac.new(
            SECRET.encode(),
            b"POST\n/v1/admission\n" + raw,
            hashlib.sha256,
        ).hexdigest()
        assert request.headers["X-Signature"] == expected
        # The signed bytes are the wire bytes: re-serialising the parsed body
        # would be a different byte string and the manager would reject it.
        assert json.loads(raw) == {"purpose": "run", "tier": {"cpu": 1.0, "mem": 2048}}

    async def test_query_string_is_not_signed(self):
        """The manager signs PATH only; ``logs`` filters ride in the query string."""
        handler = _ok({"lines": []})
        client = _client(handler)

        await client.logs(app_id="app-1", tail=200, keyword="error")

        request = handler.request
        expected = hmac.new(SECRET.encode(), b"GET\n/v1/apps/app-1/logs\n", hashlib.sha256).hexdigest()
        assert request.headers["X-Signature"] == expected
        assert request.url.params["tail"] == "200"
        assert request.url.params["keyword"] == "error"

    async def test_empty_secret_fails_closed(self):
        """No secret is a refusal, never an unsigned request."""
        client = _client(_ok({}), secret="")
        with pytest.raises(AppOrchestratorUnavailableError):
            await client.runtime_status()


class TestFailureTranslation:
    async def test_timeout_and_retry_then_16121(self):
        """An unreachable manager is 16121 — not a 500, and not a silent pass."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(handler)
        with pytest.raises(AppOrchestratorUnavailableError) as excinfo:
            await client.status(app_id="app-1")

        assert excinfo.value.code == 16121
        assert len(attempts) == 2, "a connect failure never reached the peer, so it is replayed once"

    async def test_write_intent_is_not_replayed_on_read_timeout(self):
        """deploy/stop/destroy may already be running; a blind replay would race them."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request)
            raise httpx.ReadTimeout("timed out", request=request)

        client = _client(handler)
        with pytest.raises(AppOrchestratorUnavailableError):
            await client.deploy(app_id="app-1", slug="a", version_id="v1", image_ref="img", tier={"cpu": 1, "mem": 512})

        assert len(attempts) == 1

    @pytest.mark.parametrize(
        ("manager_code", "status_code", "expected"),
        [
            ("backend_unavailable", 503, AppOrchestratorUnavailableError),
            # Contract §3: both mean backend↔manager breakage, never a caller
            # error — answering 401 upwards would look like a logout.
            ("unauthorized", 401, AppOrchestratorUnavailableError),
            ("invalid_request", 400, AppOrchestratorUnavailableError),
            ("unsupported_runtime", 400, AppRuntimeNotSupportedError),
            ("capacity_exhausted", 409, AppCapacityInsufficientError),
            ("not_found", 404, AppNotFoundError),
        ],
    )
    async def test_manager_codes_map_to_161xx(self, manager_code, status_code, expected):
        client = _client(_error(manager_code, status_code=status_code))
        with pytest.raises(expected):
            await client.runtime_status()

    async def test_unknown_manager_code_falls_back_to_16121(self):
        """An unrecognised envelope is an unavailable orchestrator, never a pass."""
        client = _client(_error("something_new", status_code=418))
        with pytest.raises(AppOrchestratorUnavailableError):
            await client.runtime_status()

    async def test_unsupported_runtime_keeps_supported_list(self):
        """AC-15 needs the supported set to tell the developer what to pick instead."""
        client = _client(_error("unsupported_runtime", status_code=400, supported_runtimes=["python3.11"]))
        with pytest.raises(AppRuntimeNotSupportedError) as excinfo:
            await client.build(app_id="a", version_id="v", runtime="node20", code_url="u", code_object_key="k")
        assert excinfo.value.kwargs["supported_runtimes"] == ["python3.11"]

    async def test_failed_build_is_returned_not_raised(self):
        """AC-15's stage / message / tail must survive to the publish pipeline."""
        payload = {"status": "failed", "stage": "docker_build", "message": "pip failed", "tail": ["line"]}
        client = _client(_ok(payload))

        result = await client.build_status(build_id="bld-1")

        assert result == payload

        from bisheng.app_runtime.domain.services.orchestrator_client import build_failure_error

        assert build_failure_error(result).code == 16122


class TestPassthrough:
    async def test_admission_passthrough_snapshot(self):
        """AC-19 / AC-65: the numbers behind "资源不足" come from the manager verbatim."""
        snapshot = {"mem_available_mb": 900, "committed_mb": 20480, "total_mb": 32768, "cpu": 8}
        handler = _ok({"admitted": False, "reason": "mem_available", "snapshot": snapshot})
        client = _client(handler)

        result = await client.admission(tier={"cpu": 2.0, "mem": 4096}, purpose="build")

        assert result["admitted"] is False
        assert result["snapshot"] == snapshot, "a re-derived snapshot would drift from the admission verdict"
        assert json.loads(handler.request.content)["purpose"] == "build"


class TestFormAgnostic:
    async def test_interface_semantics_are_form_agnostic(self):
        """INV-33: no container / compose / pod vocabulary anywhere on the facade.

        F059 swaps the manager's backend for k8s; if a compose word had leaked
        into a method name or a parameter, that swap would reach into backend.
        """
        import inspect

        from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client

        banned = re.compile(r"container|compose|docker|pod|kubelet|namespace|image_pull", re.IGNORECASE)
        methods = [name for name in dir(orchestrator_client) if not name.startswith("_")]
        assert set(methods) == {
            "build",
            "build_status",
            "deploy",
            "stop",
            "destroy",
            "probe",
            "admission",
            "status",
            "logs",
            "runtime_status",
        }
        for name in methods:
            assert not banned.search(name), name
            signature = inspect.signature(getattr(orchestrator_client, name))
            for parameter in signature.parameters:
                assert not banned.search(parameter), f"{name}({parameter})"

    async def test_phase_values_are_the_shape_neutral_set(self):
        from bisheng.database.models import app_instance

        phases = {value for name, value in vars(app_instance).items() if name.startswith("PHASE_")}
        assert phases == {"pending", "building", "starting", "running", "unhealthy", "stopped", "failed"}


class TestZeroOrchestrationDependency:
    """AC-14 — backend's "no orchestration privilege" claim, made checkable."""

    IMPORT_PATTERN = re.compile(r"^[ \t]*(?:from|import)[ \t]+(docker|aiodocker|kubernetes|kubernetes_asyncio)\b", re.M)

    def test_backend_has_zero_orchestration_dependency(self):
        offenders: list[str] = []
        socket_literal = "/var/run/" + "docker.sock"  # split so this file is not its own finding
        host_env = "DOCKER_" + "HOST"
        for path in BACKEND_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if self.IMPORT_PATTERN.search(text):
                offenders.append(f"{path}: imports an orchestration SDK")
            if socket_literal in text:
                offenders.append(f"{path}: contains the docker socket path")
            if re.search(rf"\b{host_env}\b", text):
                offenders.append(f"{path}: reads {host_env}")
        assert not offenders, "\n".join(offenders)

    def test_backend_dependency_tree_has_no_docker_sdk(self):
        """The ban has to hold at *install* time too — an indirect dependency
        would put the SDK inside the backend image regardless of imports."""
        data = tomllib.loads(BACKEND_PYPROJECT.read_text(encoding="utf-8"))
        declared = list(data["project"].get("dependencies") or [])
        for group in (data["project"].get("optional-dependencies") or {}).values():
            declared.extend(group)
        banned = {"docker", "aiodocker", "kubernetes", "kubernetes-asyncio", "kubernetes_asyncio"}
        names = {re.split(r"[<>=!\[~;\s]", item.strip(), maxsplit=1)[0].lower() for item in declared}
        assert not (names & banned)
