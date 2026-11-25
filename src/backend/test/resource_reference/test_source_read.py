"""Auxiliary indexes never grant or prevent business admission. 覆盖 AC: AC-07, AC-12."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime


def reader():
    payload = canonical_payload_json({"assistant": {"id": "a"}})
    snapshot = AuthorizedSourceSnapshot(
        SourceKey(101, SourceType.ASSISTANT, "a", "current"), (), "assistant-v1", payload_digest(payload), payload
    )
    runtime = object.__new__(ReferenceSourceReadRuntime)
    runtime.repository = SimpleNamespace(
        aread_source=AsyncMock(side_effect=AssertionError("business must not read reference index")),
        read_source=Mock(side_effect=AssertionError("business must not read reference index")),
    )
    runtime.verifier = SimpleNamespace(
        aget_source_snapshot=AsyncMock(return_value=snapshot),
        get_source_snapshot=Mock(return_value=snapshot),
        _ainspect_targets=AsyncMock(return_value=()),
        _inspect_targets=Mock(return_value=()),
        arevalidate_scope=AsyncMock(),
        revalidate_scope=Mock(),
    )
    return runtime, snapshot


@pytest.mark.parametrize("purpose", ["execute", "inspect"])
async def test_async_business_reads_without_reference_index(purpose):
    runtime, snapshot = reader()
    result = await runtime._source(object(), SimpleNamespace(purpose=purpose), object(), purpose=purpose)
    assert result.snapshot == snapshot
    assert result.target_states == ()
    runtime.verifier.arevalidate_scope.assert_awaited_once()
    runtime.repository.aread_source.assert_not_awaited()


@pytest.mark.parametrize("purpose", ["execute", "inspect"])
def test_sync_business_reads_without_reference_index(purpose):
    runtime, snapshot = reader()
    result = runtime._source_sync(object(), SimpleNamespace(purpose=purpose), object(), purpose=purpose)
    assert result.snapshot == snapshot
    runtime.verifier.revalidate_scope.assert_called_once()
    runtime.repository.read_source.assert_not_called()


async def test_original_identity_failure_never_becomes_an_index_fallback():
    runtime, _ = reader()
    runtime.verifier.aget_source_snapshot.side_effect = ResourceReferenceInvalidError(reason="identity_changed")
    with pytest.raises(ResourceReferenceInvalidError):
        await runtime.arequire_source_valid(object(), SimpleNamespace(purpose="execute"), object())
    runtime.verifier._ainspect_targets.assert_not_awaited()


def test_missing_target_state_survives_the_public_assistant_response_schema():
    from bisheng.api.v1.schemas import AssistantReferenceView
    from bisheng.resource_reference.application.contracts import TargetKey
    from bisheng.resource_reference.application.source_contracts import ReferenceTargetReadFact

    fact = ReferenceTargetReadFact(TargetKey("model", "99"), "invalid_missing", False)
    row = AssistantReferenceView(
        slot_key="model_name", target_type="model", target_id="99", state=fact.state.value, is_valid=False
    )
    assert row.state == "invalid_missing"
