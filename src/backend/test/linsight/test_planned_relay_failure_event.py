"""F004: the ``run_failed`` event of a planned relay run that could not be created.

The event is rendered in the browser's error card. It must carry the redacted
detail every other ``run_failed`` carries, never the exception text itself.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from bisheng.linsight.worker import ScheduleCenterProcess
from bisheng.linsight.domain.services.run_event_stream import RunEventStream

CID = "conv-relay-fail"
RUN = "run-relay-fail"
SECRET = "INSERT INTO linsight_session_version (id) VALUES ('x') -- host=10.1.2.3"


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


async def test_relay_failure_event_does_not_carry_the_exception_text(redis):
    unread = [{"message_id": "m1", "text": "还要加一节"}]

    await ScheduleCenterProcess._report_planned_relay_failure(
        redis, CID, RUN, RuntimeError(f"(pymysql.err.OperationalError) [SQL: {SECRET}]"), unread
    )

    events = [ev async for ev in RunEventStream(redis).read(CID)]
    assert [ev["type"] for ev in events] == ["run_started", "run_failed"]
    failed = events[-1]["data"]
    assert SECRET not in str(failed)
    assert "10.1.2.3" not in str(failed) and "INSERT INTO" not in str(failed)
    assert failed["code"] and failed["reason"] and failed["detail"]
    assert failed["reference_id"]
    assert failed["unread_messages"] == unread
