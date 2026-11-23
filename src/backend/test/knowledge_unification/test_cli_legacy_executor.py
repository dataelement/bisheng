"""Public compatibility writers use the same F118 control lock and tokens."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_upgrade_executor import UpgradeExecutor
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.knowledge.domain.repositories.unification_upgrade_repository import UpgradeRunRepository
from test.knowledge_unification import test_migration_cli as original
from test.knowledge_unification.test_permission_publication_application import app

complete, native = original.complete, original.native
raw_resource_native, resource_native = original.raw_resource_native, original.resource_native
transport, published_input, no_real_network = original.transport, original.published_input, original.no_real_network


class Gate:
    def __init__(self):
        self.held, self.acquisitions = False, 0

    @asynccontextmanager
    async def acquire(self):
        if self.held:
            raise KnowledgeOperationPlanConflictError(reason="migration_executor_busy_or_lock_unavailable")
        self.held, self.acquisitions = True, self.acquisitions + 1
        try:
            yield SimpleNamespace(ensure=self.ensure)
        finally:
            self.held = False

    async def ensure(self):
        if not self.held:
            raise KnowledgeOperationPlanConflictError(reason="migration_executor_lock_lost")


def runtime(value, gate):
    @asynccontextmanager
    async def opened(_arguments):
        yield SimpleNamespace(
            store=value.artifacts.store,
            sessions=value.sessions,
            engine=value.database.engine,
            executor_lock=gate.acquire,
            inventory=None,
        )

    return opened


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
@pytest.mark.parametrize("stage", ["--permissions-only", "--register-references-only"])
async def test_second_public_stage_writer_rejects_and_serial_stage_keeps_its_original_scope(published_input, stage):
    value, gate = published_input, Gate()
    if stage == "--register-references-only":
        await app(value).arun_permissions(**value.input, operator_id=7)
    arguments = original.arguments(value, stage, "--apply", "--resume", "--operator-id", "7")
    opened = SimpleNamespace(sessions=value.sessions, engine=value.database.engine, executor_lock=gate.acquire)
    async with UpgradeExecutor.acquire(
        opened, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
    ) as executor:
        await executor.start(value.frozen.tenant_ids)
        writes = value.store.writes
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await original.entry().arun(arguments, runtime_factory=runtime(value, gate))
        assert caught.value.kwargs["reason"] == "migration_executor_busy_or_lock_unavailable"
        assert value.store.writes == writes
        if stage == "--register-references-only":
            preview = await original.entry().arun(
                original.arguments(value, stage, "--operator-id", "7"), runtime_factory=runtime(value, gate)
            )
            assert not preview["ready"] and not preview["registration_complete"]
            assert gate.acquisitions == 1
        await executor.finish_attempt()
    result = await original.entry().arun(arguments, runtime_factory=runtime(value, gate))
    assert not result["ready"]
    assert result["permissions_complete"] if stage == "--permissions-only" else result["registration_complete"]
    async with value.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Run))).scalars().all()
        assert rows and all(row.coverage_epoch is None for row in rows)
        assert all(
            UpgradeExecutor(
                opened,
                run_id=value.frozen.run_id,
                writer_contract_version=value.frozen.writer_contract_version,
                lease=None,
            ).repository._latest(row)[2]["closed"]
            for row in rows
        )


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
async def test_public_legacy_apply_requires_frozen_run_without_bootstrapping_history(published_input):
    value, gate = published_input, Gate()
    async with value.database.engine.begin() as connection:
        await connection.execute(sa.delete(Run.__table__))
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await original.entry().arun(
            original.arguments(value, "--permissions-only", "--apply", "--operator-id", "7"),
            runtime_factory=runtime(value, gate),
        )
    assert caught.value.kwargs["reason"] == "migration_cli_legacy_apply_requires_frozen_run"
    assert gate.acquisitions == 0 and value.store.writes == 0


@pytest.mark.parametrize("published_input", [{"reference_seed": original.seed_cli_operator}], indirect=True)
@pytest.mark.parametrize("cancel", [False, True])
async def test_public_legacy_unknown_effect_keeps_durable_pending_and_releases_owned_lock(published_input, cancel):
    value, gate = published_input, Gate()
    value.store.fail_write, value.store.after, value.store.cancel = 1, True, cancel
    arguments = original.arguments(value, "--permissions-only", "--apply", "--operator-id", "7")
    with pytest.raises(asyncio.CancelledError if cancel else BaseErrorCode):
        await original.entry().arun(arguments, runtime_factory=runtime(value, gate))
    assert not gate.held and gate.acquisitions == 1
    async with value.sessions() as session, session.begin():
        state = await UpgradeRunRepository().aload_state(
            session, run_id=value.frozen.run_id, writer_contract_version=value.frozen.writer_contract_version
        )
        assert state.pending_intents
    value.sessions.assert_closed()
