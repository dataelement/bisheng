from datetime import UTC, datetime, timedelta

from bisheng.llm.domain.services.model_rate_limit_state import (
    ModelRateLimitState,
    ModelRateLimitView,
)
from bisheng.workstation.api.endpoints.config import project_workstation_model_states


class FakeRateLimitService:
    def __init__(self, states: dict[int, ModelRateLimitView], *, fail: bool = False) -> None:
        self.states = states
        self.fail = fail
        self.calls = []

    async def list_model_states(self, tenant_id: int, model_ids: list[int]):
        self.calls.append((tenant_id, model_ids))
        if self.fail:
            raise ConnectionError("redis unavailable")
        return {
            model_id: self.states.get(
                model_id,
                ModelRateLimitView(
                    model_id=model_id,
                    rate_limit_state=ModelRateLimitState.NORMAL,
                    busy_until=None,
                    status_version=0,
                ),
            )
            for model_id in model_ids
        }


def state(model_id: int, rate_limit_state: ModelRateLimitState, version: int) -> ModelRateLimitView:
    return ModelRateLimitView(
        model_id=model_id,
        rate_limit_state=rate_limit_state,
        busy_until=datetime(2026, 8, 27, 12, 0, tzinfo=UTC) + timedelta(seconds=model_id),
        status_version=version,
    )


async def test_projection_batches_authorized_model_ids_once_and_preserves_order() -> None:
    service = FakeRateLimitService(
        {
            17: state(17, ModelRateLimitState.RECOVERING, 3),
            18: state(18, ModelRateLimitState.BUSY, 4),
        }
    )
    models = [
        {"id": "18", "name": "model-b", "displayName": "B"},
        {"id": "17", "name": "model-a", "displayName": "A"},
        {"id": "19", "name": "model-c", "displayName": "C"},
    ]

    projected = await project_workstation_model_states(models, tenant_id=2, rate_limit_service=service)

    assert service.calls == [(2, [18, 17, 19])]
    assert [model["id"] for model in projected] == ["18", "17", "19"]
    assert [model["rateLimitState"] for model in projected] == ["busy", "recovering", "normal"]
    assert all("availability" not in model for model in projected)
    assert projected[0]["statusVersion"] == 4
    assert projected[0]["busyUntil"].endswith("Z")


async def test_busy_decoration_does_not_remove_or_reselect_default_model() -> None:
    service = FakeRateLimitService({17: state(17, ModelRateLimitState.BUSY, 2)})
    models = [
        {"id": "17", "name": "same-name", "displayName": "First", "default": True},
        {"id": "18", "name": "same-name", "displayName": "Second"},
    ]

    projected = await project_workstation_model_states(models, tenant_id=2, rate_limit_service=service)

    assert len(projected) == 2
    assert projected[0]["default"] is True
    assert projected[0]["rateLimitState"] == "busy"
    assert projected[1]["rateLimitState"] == "normal"


async def test_same_model_id_uses_one_state_without_expanding_candidate_scope() -> None:
    service = FakeRateLimitService({17: state(17, ModelRateLimitState.RECOVERING, 8)})
    models = [
        {"id": "17", "name": "alias-a"},
        {"id": "17", "name": "alias-b"},
    ]

    projected = await project_workstation_model_states(models, tenant_id=3, rate_limit_service=service)

    assert service.calls == [(3, [17])]
    assert [model["name"] for model in projected] == ["alias-a", "alias-b"]
    assert [model["statusVersion"] for model in projected] == [8, 8]


async def test_redis_read_failure_fails_soft_to_normal_decoration() -> None:
    service = FakeRateLimitService({}, fail=True)
    models = [{"id": "17", "name": "model-a"}]

    projected = await project_workstation_model_states(models, tenant_id=2, rate_limit_service=service)

    assert projected == [
        {
            "id": "17",
            "name": "model-a",
            "rateLimitState": "normal",
            "busyUntil": None,
            "statusVersion": 0,
        }
    ]


async def test_empty_model_list_does_not_read_redis() -> None:
    service = FakeRateLimitService({})

    projected = await project_workstation_model_states([], tenant_id=2, rate_limit_service=service)

    assert projected == []
    assert service.calls == []
