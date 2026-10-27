"""AC-01, AC-02, AC-03, AC-05, AC-11: real SQL terminal paths, not mock business transitions."""

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.eplus.domain.models.eplus import EPlusInboundMessage, EPlusTurnStatus
from bisheng.eplus.domain.schemas.metric import METRIC_SNAPSHOTS_KEY
from bisheng.eplus.domain.services.conversation_scheduler import EPlusConversationScheduler
from bisheng.eplus.domain.services.message_service import EPlusMessageAdmissionService
from bisheng.eplus.domain.services.metric_observer import terminal_metric_transaction
from test.eplus import test_eplus_message_admission as admission
from test.eplus.test_eplus_conversation_scheduler import (
    BOT_CONFIG_ID,
    TENANT_ID,
    _seed_turn,
)
from test.eplus.test_eplus_conversation_scheduler import (
    engine as engine,
)
from test.eplus.test_eplus_conversation_scheduler import (
    tenant_context as tenant_context,
)


def scheduler(engine, observer):
    return EPlusConversationScheduler(
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        metric_observer=observer,
    )


async def test_rejection_and_duplicate_are_separate_observations(engine):
    observed = []
    service = EPlusMessageAdmissionService(
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        identity_service=admission.FakeIdentityResolver(identity=None),
        media_service=admission.FakeMediaService(),
        metric_observer=observed.append,
    )
    await service.admit(admission._context(), admission._callback("rejected"))
    assert len(observed) == 1 and observed[0].result == "rejected" and not observed[0].admitted
    await service.admit(admission._context(), admission._callback("rejected"))
    assert [s.result for s in observed] == ["rejected", "duplicate"]
    assert observed[0].message_id == observed[1].message_id


async def test_completed_turn_metric_occurs_after_commit_and_is_not_repeated(engine):
    observed = []
    await _seed_turn(engine, conversation_id="c", conversation_key="u", turn_seq=1)
    sched = scheduler(engine, observed.append)
    ready = await sched.next_ready_turn(TENANT_ID, "c")
    async with AsyncSession(engine) as session:
        await session.exec(update(EPlusInboundMessage).values(reply_status="FINISHED"))
        await session.commit()
    await sched.complete_and_wake_next(
        tenant_id=TENANT_ID, turn_id=ready.turn.id, succeeded=True, execution_token=ready.turn.assistant_run_id
    )
    assert len(observed) == 1 and observed[0].result == "success" and observed[0].admitted
    await sched.complete_and_wake_next(
        tenant_id=TENANT_ID, turn_id=ready.turn.id, succeeded=True, execution_token=ready.turn.assistant_run_id
    )
    assert len(observed) == 1


async def test_timeout_and_recovery_emit_failed_terminal_metrics(engine):
    observed = []
    sched = scheduler(engine, observed.append)
    await _seed_turn(engine, conversation_id="queued", conversation_key="u", turn_seq=1)
    assert await sched.expire_waiting_turn(tenant_id=TENANT_ID, turn_id="turn-queued-1")
    await _seed_turn(
        engine, conversation_id="interrupted", conversation_key="v", turn_seq=1, status=EPlusTurnStatus.PREPARING
    )
    await sched.recover_queued(tenant_id=TENANT_ID, bot_config_id=BOT_CONFIG_ID)
    assert len(observed) == 2 and all(s.result == "failed" and s.admitted for s in observed)
    assert {s.reason for s in observed} == {"ASSISTANT_TIMEOUT", "ADMISSION_INTERRUPTED"}


async def test_rollback_drops_observations_and_emitter_failure_is_isolated(engine):
    seen = []
    async with AsyncSession(engine) as session:
        with pytest.raises(RuntimeError):
            async with terminal_metric_transaction(session, seen.append):
                session.info[METRIC_SNAPSHOTS_KEY] = ["not-committed"]
                raise RuntimeError("rollback")
        assert seen == [] and METRIC_SNAPSHOTS_KEY not in session.info

        def broken(value):
            raise RuntimeError("metric sink unavailable")

        async with terminal_metric_transaction(session, broken):
            session.info[METRIC_SNAPSHOTS_KEY] = ["committed"]


async def test_busy_rejection_is_not_an_admitted_qa_or_a_finished_turn(engine):
    observed = []
    service = EPlusMessageAdmissionService(
        session_factory=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        identity_service=admission.FakeIdentityResolver(),
        media_service=admission.FakeMediaService(),
        metric_observer=observed.append,
    )
    for number in range(4):
        await service.admit(admission._context(), admission._callback(f"busy-{number}"))
    assert len(observed) == 1
    assert observed[0].message_id == "busy-3" and observed[0].reason == "BUSY"
    assert observed[0].result == "rejected" and not observed[0].admitted
