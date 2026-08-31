import importlib.util
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import bisheng.worker as worker_package
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.services.model_rate_limit import ResolvedModelConfig
from bisheng.llm.domain.services.model_rate_limit_state import ProbeRateLimitResult

# Several legacy worker tests replace ``bisheng.worker`` in ``sys.modules`` at
# collection time. Keep this test order-independent by restoring the real
# package search path before importing the F051 task module.
worker_path = str(Path(__file__).resolve().parents[2] / "bisheng" / "worker")
package_paths = list(getattr(worker_package, "__path__", []))
if worker_path not in package_paths:
    package_paths.append(worker_path)
    worker_package.__path__ = package_paths

probe_path = Path(worker_path) / "model_rate_limit.py"
probe_spec = importlib.util.spec_from_file_location("bisheng.worker.model_rate_limit", probe_path)
assert probe_spec is not None and probe_spec.loader is not None
probe_module = importlib.util.module_from_spec(probe_spec)
sys.modules[probe_spec.name] = probe_module
probe_spec.loader.exec_module(probe_module)
worker_package.model_rate_limit = probe_module
ProbeOutcome = probe_module.ProbeOutcome
_run_in_task_tenant = probe_module._run_in_task_tenant
enqueue_model_rate_limit_probe = probe_module.enqueue_model_rate_limit_probe
invoke_minimal_model_probe = probe_module.invoke_minimal_model_probe
probe_aliyun_model_rate_limit = probe_module.probe_aliyun_model_rate_limit
run_model_rate_limit_probe = probe_module.run_model_rate_limit_probe


class ProviderError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class FakeStateService:
    def __init__(self, *, claimed_version: int | None = 4) -> None:
        self.claimed_version = claimed_version
        self.begun = []
        self.cleared = []
        self.recorded = []

    async def begin_probe(self, **kwargs):
        self.begun.append(kwargs)
        return self.claimed_version

    async def clear_if_version(self, **kwargs):
        self.cleared.append(kwargs)
        return True

    async def record_probe_rate_limited(self, **kwargs):
        self.recorded.append(kwargs)
        return ProbeRateLimitResult(changed=True, next_probe_token="probe-next")


def resolved() -> ResolvedModelConfig:
    return ResolvedModelConfig(
        model=SimpleNamespace(id=17, server_id=6, online=True),
        server=SimpleNamespace(id=6, type="qwen", config={}),
    )


async def test_probe_success_clears_only_the_claimed_version() -> None:
    state = FakeStateService(claimed_version=7)
    calls = []
    recovered = []

    async def resolver(model_id: int):
        return resolved()

    async def invoke(model_id: int):
        calls.append(model_id)

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=1,
        state_service=state,
        model_resolver=resolver,
        probe_call=invoke,
        diagnostics=SimpleNamespace(rate_limit_recovered=lambda **fields: recovered.append(fields)),
    )

    assert result == ProbeOutcome.RECOVERED
    assert calls == [17]
    assert state.cleared == [{"tenant_id": 2, "model_id": 17, "observed_version": 7}]
    assert recovered == [{"tenant_id": 2, "model_id": 17, "probe_attempt": 1, "status_version": 7}]


async def test_first_and_second_limits_schedule_only_the_next_bounded_attempt() -> None:
    state = FakeStateService()
    scheduled = []

    async def resolver(model_id: int):
        return resolved()

    async def invoke(model_id: int):
        raise ProviderError("rate limit", status_code=429, code="Throttling.RateQuota")

    async def schedule(**payload):
        scheduled.append(payload)

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=2,
        state_service=state,
        model_resolver=resolver,
        probe_call=invoke,
        schedule_probe=schedule,
    )

    assert result == ProbeOutcome.STILL_RATE_LIMITED
    assert state.recorded == [
        {
            "tenant_id": 2,
            "model_id": 17,
            "observed_version": 4,
            "probe_attempt": 2,
            "exhausted": False,
        }
    ]
    assert scheduled == [{"tenant_id": 2, "model_id": 17, "probe_token": "probe-next", "probe_attempt": 3}]


async def test_third_limit_exhausts_without_unbounded_retry() -> None:
    state = FakeStateService()
    scheduled = []

    async def resolver(model_id: int):
        return resolved()

    async def invoke(model_id: int):
        raise ProviderError("rate limit", status_code=429, code="Throttling.BurstRate")

    async def schedule(**payload):
        scheduled.append(payload)

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=3,
        state_service=state,
        model_resolver=resolver,
        probe_call=invoke,
        schedule_probe=schedule,
    )

    assert result == ProbeOutcome.EXHAUSTED
    assert state.recorded[0]["exhausted"] is True
    assert scheduled == []


async def test_non_rate_limit_error_does_not_claim_recovery_or_schedule() -> None:
    state = FakeStateService()
    scheduled = []

    async def resolver(model_id: int):
        return resolved()

    async def invoke(model_id: int):
        raise TimeoutError("provider timeout")

    async def schedule(**payload):
        scheduled.append(payload)

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=1,
        state_service=state,
        model_resolver=resolver,
        probe_call=invoke,
        schedule_probe=schedule,
    )

    assert result == ProbeOutcome.NON_RATE_LIMIT_ERROR
    assert state.cleared == []
    assert state.recorded == []
    assert scheduled == []


async def test_expired_or_unowned_state_is_a_noop_before_model_resolution() -> None:
    state = FakeStateService(claimed_version=None)
    resolved_models = []

    async def resolver(model_id: int):
        resolved_models.append(model_id)
        return resolved()

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=1,
        state_service=state,
        model_resolver=resolver,
    )

    assert result == ProbeOutcome.STALE
    assert resolved_models == []


async def test_deleted_or_disabled_model_stops_without_clearing_busy() -> None:
    state = FakeStateService()

    async def resolver(model_id: int):
        raise LookupError("model deleted")

    result = await run_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=1,
        state_service=state,
        model_resolver=resolver,
    )

    assert result == ProbeOutcome.MODEL_UNAVAILABLE
    assert state.cleared == []
    assert state.recorded == []


async def test_minimal_probe_is_non_streaming_one_token_without_user_context() -> None:
    factory_kwargs = {}
    invoked = []

    class FakeLlm:
        async def ainvoke(self, messages):
            invoked.append(messages)

    async def factory(**kwargs):
        factory_kwargs.update(kwargs)
        return FakeLlm()

    await invoke_minimal_model_probe(17, llm_factory=factory)

    assert factory_kwargs["model_id"] == 17
    assert factory_kwargs["streaming"] is False
    assert factory_kwargs["max_tokens"] == 1
    assert factory_kwargs["temperature"] == 0
    assert factory_kwargs["user_id"] == 0
    assert set(factory_kwargs) == {
        "model_id",
        "streaming",
        "max_tokens",
        "temperature",
        "app_id",
        "app_name",
        "app_type",
        "user_id",
    }
    assert len(invoked) == 1
    assert len(invoked[0]) == 1
    assert invoked[0][0].type == "system"


async def test_enqueue_uses_tenant_header_and_attempt_delay_without_tenant_in_body(monkeypatch) -> None:
    dispatched = []
    monkeypatch.setattr(probe_aliyun_model_rate_limit, "apply_async", lambda **options: dispatched.append(options))

    await enqueue_model_rate_limit_probe(
        tenant_id=2,
        model_id=17,
        probe_token="probe-1",
        probe_attempt=2,
    )

    assert dispatched == [
        {
            "kwargs": {"model_id": 17, "probe_token": "probe-1", "probe_attempt": 2},
            "headers": {"tenant_id": 2},
            "countdown": 30,
        }
    ]


def test_worker_entry_restores_and_resets_leaf_tenant(monkeypatch) -> None:
    observed = []

    def fake_run_async_task(coroutine_factory):
        coroutine = coroutine_factory()
        coroutine.close()
        observed.append(get_current_tenant_id())
        return ProbeOutcome.STALE

    monkeypatch.setattr("bisheng.worker.model_rate_limit.run_async_task", fake_run_async_task)
    request = SimpleNamespace(headers={"tenant_id": "12"})

    result = _run_in_task_tenant(request=request, coroutine_factory=lambda: _unused_coroutine())

    assert result == ProbeOutcome.STALE
    assert observed == [12]
    assert get_current_tenant_id() is None


async def _unused_coroutine() -> None:
    return None


def test_celery_task_signature_and_module_have_no_user_execution_dependencies() -> None:
    parameters = set(inspect.signature(probe_aliyun_model_rate_limit.run).parameters)
    source = inspect.getsource(inspect.getmodule(probe_aliyun_model_rate_limit))

    assert parameters == {"self", "model_id", "probe_token", "probe_attempt"}
    for forbidden in ("execution_id", "session_id", "chat_id", "prompt", "ModelCallExecution"):
        assert forbidden not in source
