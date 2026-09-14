"""Classification of what a bare share-link id resolves to.

The distinction that matters to a visitor is "the app was taken offline" versus
"this link does not work". Everything here pins that split, including the two
ways it is easy to get wrong: a type mismatch and a deleted assistant must both
read as a broken link, never as an offline app.
"""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.public_endpoints import (
    PublicApplicationOfflineError,
    PublicLinkInvalidError,
)
from bisheng.database.models.assistant import AssistantStatus
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.public_endpoints.domain.services import guest_policy

ONLINE_FLOW = SimpleNamespace(
    tenant_id=3, flow_type=FlowType.WORKFLOW.value, status=FlowStatus.ONLINE.value
)
OFFLINE_FLOW = SimpleNamespace(
    tenant_id=3, flow_type=FlowType.WORKFLOW.value, status=FlowStatus.OFFLINE.value
)
WRONG_TYPE_FLOW = SimpleNamespace(tenant_id=3, flow_type=5, status=FlowStatus.ONLINE.value)

ONLINE_ASSISTANT = SimpleNamespace(tenant_id=3, is_delete=False, status=AssistantStatus.ONLINE.value)
OFFLINE_ASSISTANT = SimpleNamespace(
    tenant_id=3, is_delete=False, status=AssistantStatus.OFFLINE.value
)
DELETED_ASSISTANT = SimpleNamespace(
    tenant_id=3, is_delete=True, status=AssistantStatus.ONLINE.value
)


@pytest.fixture
def lookups(monkeypatch):
    state = SimpleNamespace(flow=None, assistant=None, flow_calls=0, assistant_calls=0)

    async def aget_flow_by_id(_flow_id):
        state.flow_calls += 1
        return state.flow

    async def aget_one_assistant(_assistant_id):
        state.assistant_calls += 1
        return state.assistant

    monkeypatch.setattr(guest_policy.FlowDao, "aget_flow_by_id", aget_flow_by_id)
    monkeypatch.setattr(guest_policy.AssistantDao, "aget_one_assistant", aget_one_assistant)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param(ONLINE_FLOW, "published", id="online"),
        pytest.param(OFFLINE_FLOW, "offline", id="offline"),
        # A wrong flow_type is a miss, not an offline app: an assistant id
        # probed on the workflow side would otherwise report the whole link
        # as "taken offline".
        pytest.param(WRONG_TYPE_FLOW, "missing", id="wrong_type"),
        pytest.param(None, "missing", id="absent"),
    ],
)
async def test_workflow_probe_classification(lookups, row, expected) -> None:
    lookups.flow = row
    outcome, _ = await guest_policy._probe_published_resource("workflow", "id-1")
    assert outcome == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param(ONLINE_ASSISTANT, "published", id="online"),
        pytest.param(OFFLINE_ASSISTANT, "offline", id="offline"),
        # Deleted means the link is broken, not that the app is paused.
        pytest.param(DELETED_ASSISTANT, "missing", id="deleted"),
        pytest.param(None, "missing", id="absent"),
    ],
)
async def test_assistant_probe_classification(lookups, row, expected) -> None:
    lookups.assistant = row
    outcome, _ = await guest_policy._probe_published_resource("assistant", "id-1")
    assert outcome == expected


@pytest.mark.asyncio
async def test_load_published_resource_raises_the_visitor_facing_error(lookups) -> None:
    lookups.flow = OFFLINE_FLOW
    with pytest.raises(PublicApplicationOfflineError) as offline:
        await guest_policy._load_published_resource("workflow", "id-1")
    assert offline.value.code == 26102
    assert offline.value.http_status == 404

    lookups.flow = None
    with pytest.raises(PublicLinkInvalidError) as missing:
        await guest_policy._load_published_resource("workflow", "id-1")
    assert missing.value.code == 26101
    assert missing.value.http_status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flow", "assistant", "expected"),
    [
        pytest.param(OFFLINE_FLOW, None, PublicApplicationOfflineError, id="workflow_offline"),
        pytest.param(None, OFFLINE_ASSISTANT, PublicApplicationOfflineError, id="assistant_offline"),
        pytest.param(None, None, PublicLinkInvalidError, id="both_missing"),
        pytest.param(
            WRONG_TYPE_FLOW, DELETED_ASSISTANT, PublicLinkInvalidError, id="mismatch_and_deleted"
        ),
    ],
)
async def test_probe_priority_offline_beats_missing(lookups, flow, assistant, expected) -> None:
    lookups.flow = flow
    lookups.assistant = assistant
    with pytest.raises(expected):
        async with guest_policy.public_application_execution("id-1"):
            pytest.fail("should not enter the context")


@pytest.mark.asyncio
async def test_probe_falls_through_to_a_published_assistant(lookups, monkeypatch) -> None:
    lookups.flow = None
    lookups.assistant = ONLINE_ASSISTANT

    async def load_operator(_tenant_id):
        return SimpleNamespace(user_id=41, user_name="guest", tenant_id=3, is_global_super=False)

    async def is_tenant_admin(_user_id, _tenant_id):
        return False

    monkeypatch.setattr(guest_policy, "_load_default_operator", load_operator)
    monkeypatch.setattr(
        "bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin
    )

    async with guest_policy.public_application_execution("id-1") as execution:
        assert execution.principal.resource_type == "assistant"


@pytest.mark.asyncio
async def test_caller_errors_are_not_swallowed_into_a_second_probe(lookups, monkeypatch) -> None:
    """Regression: the body used to sit inside try/except and retry as assistant."""

    lookups.flow = ONLINE_FLOW

    async def load_operator(_tenant_id):
        return SimpleNamespace(user_id=41, user_name="guest", tenant_id=3, is_global_super=False)

    async def is_tenant_admin(_user_id, _tenant_id):
        return False

    monkeypatch.setattr(guest_policy, "_load_default_operator", load_operator)
    monkeypatch.setattr(
        "bisheng.permission.application.relation_api.is_tenant_admin", is_tenant_admin
    )

    with pytest.raises(PublicLinkInvalidError):
        async with guest_policy.public_application_execution("id-1"):
            raise PublicLinkInvalidError()

    assert lookups.assistant_calls == 0
