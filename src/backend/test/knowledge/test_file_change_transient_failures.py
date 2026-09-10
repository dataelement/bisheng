"""An approved change must survive a momentary permission-service wobble.

Preparing an approved change catches every ``BaseErrorCode`` and retires the
request permanently, on the stated assumption that transient failures are not
``BaseErrorCode``. They are: the authorization service reports its own outage
as one, and so does the write fence a catalog publish raises. Clearing a queue
in bulk made the first likely — many changes hit the permission service at
once — and uploads that had already been cleared to run were killed outright
with no retry.

The reader was told nothing either. ``str()`` on one of these errors is the
wrapped exception when there is one, and a transport failure can stringify to
nothing, so the stored reason was a bare "cannot be applied:" with an empty
tail.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.worker.knowledge import file_change_tasks as worker


def _executor(*, prepare_error):
    return SimpleNamespace(
        prepare_execution=AsyncMock(side_effect=prepare_error),
        fail_unstarted_request=AsyncMock(return_value=True),
    )


async def _coordinate(executor):
    with (
        patch.object(worker, "_build_mutation_executor", lambda: executor),
        patch.object(worker, "_build_execution_coordinator", lambda: SimpleNamespace()),
    ):
        return await worker._coordinate_execution_async(
            tenant_id=1,
            request_id=32,
            execution_token=None,
        )


@pytest.mark.parametrize(
    "error",
    [PermissionServiceUnavailableError(), PermissionPublishNotReadyError()],
    ids=["service-unavailable", "write-fenced-by-a-publish"],
)
async def test_a_transient_permission_failure_is_left_for_celery(error) -> None:
    executor = _executor(prepare_error=error)

    with pytest.raises(type(error)):
        await _coordinate(executor)

    # Retiring it here is what destroyed work that was already cleared to run.
    executor.fail_unstarted_request.assert_not_awaited()


async def test_a_real_business_violation_still_retires_the_request() -> None:
    """The guard this branch exists for: retrying would never help."""

    executor = _executor(prepare_error=SpacePermissionDeniedError())

    result = await _coordinate(executor)

    assert result == {"status": "failed", "reason": "business_rule_violation"}
    executor.fail_unstarted_request.assert_awaited_once()


async def test_the_reason_never_ends_at_the_colon() -> None:
    """A wrapped transport error can stringify to nothing; say something anyway."""

    executor = _executor(prepare_error=SpacePermissionDeniedError(exception=RuntimeError()))

    await _coordinate(executor)

    reason = executor.fail_unstarted_request.await_args.kwargs["failure_reason"]
    assert reason.startswith("file change cannot be applied: ")
    assert reason.removeprefix("file change cannot be applied: ").strip()
