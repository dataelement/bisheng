"""T863: native SQL + Run checkpoint batches, without an App artifact bypass."""

import asyncio
import importlib
from dataclasses import asdict, replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from test.knowledge_unification import test_migration_conversion_repository as native

resource_native = native.resource_native
database = native.database


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.domain.services.unification_conversion")


@pytest.fixture
def service(module):
    return module.UnificationConversionService()


async def issue(service, session, commands, **kwargs):
    # The actual App must validate frozen artifact membership before this private
    # issuer. These fixtures certify only the Domain component, never that wiring.
    return await service._issue_verified_batch(session, **native.IDENTITY, commands=tuple(commands), **kwargs)


async def progress(service, session):
    return await service.aget_progress(session, **native.IDENTITY)


async def test_all_five_native_kinds_checkpoint_and_business_share_the_parent_transaction(service, database):
    before = await native.snapshot(database)
    async with AsyncSession(database.engine) as session:
        async with session.begin():
            batch = await issue(service, session, database.commands, eof=True)
            result = await service.aapply_batch(session, batch=batch)
            assert len(result.outcomes) == len(database.commands)
            assert result.progress.processed_count == len(database.commands)
            assert result.progress.complete
            assert result.progress.cursor == f"sql-v1:{len(database.commands)}:{database.commands[-1].command_key}"
            assert await progress(service, session) == result.progress
            await session.rollback()
    assert await native.snapshot(database) == before
    async with AsyncSession(database.engine) as session, session.begin():
        result = await service.aapply_batch(session, batch=await issue(service, session, database.commands, eof=True))
    after = await native.snapshot(database)
    row = after[Run.__tablename__][0]
    assert row["phase"] == "converting"
    assert row["checkpoints"]["converting"]["sql_conversion"] == asdict(result.progress)
    assert set(asdict(result.progress)) == {"cursor", "processed_count", "digest", "complete"}
    assert after["knowledgefile"] == before["knowledgefile"]
    assert len(after["knowledge_document"]) == len(after["knowledge_document_version"]) == 3


@pytest.mark.parametrize("kind", ["forged", "copied", "tampered", "replayed", "cross_transaction"])
async def test_only_the_original_same_transaction_batch_can_write(service, database, kind):
    async with AsyncSession(database.engine) as session:
        await session.begin()
        batch = await issue(service, session, database.commands, eof=True)
        if kind == "forged":
            attempted = asdict(batch)
        elif kind == "copied":
            attempted = replace(batch)
        elif kind == "tampered":
            object.__setattr__(batch, "eof", False)
            attempted = batch
        elif kind == "replayed":
            await service.aapply_batch(session, batch=batch)
            attempted = batch
        elif kind == "cross_transaction":
            await session.rollback()
            await session.begin()
            attempted = batch
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(session, batch=attempted)
        await session.rollback()


@pytest.mark.parametrize("drift", ["phase", "baseline", "plan", "cursor"])
async def test_actual_run_is_rechecked_after_issuance(service, database, drift):
    async with AsyncSession(database.engine) as session, session.begin():
        batch = await issue(service, session, database.commands, eof=True)
        values = {"phase": "backfilling"} if drift == "phase" else {drift + "_hash": "f" * 64}
        if drift == "cursor":
            values = {
                "checkpoints": {
                    "converting": {
                        "sql_conversion": {
                            "cursor": "sql-v1:1:" + "a" * 64,
                            "processed_count": 1,
                            "digest": "c" * 64,
                            "complete": False,
                        }
                    }
                }
            }
        await session.execute(sa.update(Run.__table__).where(Run.tenant_id == 101).values(**values))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(session, batch=batch)
    after = await native.snapshot(database)
    assert after["knowledge"][0]["type"] == 0
    assert after["knowledge_document"] == ()


@pytest.mark.parametrize("failure", ["checkpoint", "cancel", "after_hash"])
async def test_caught_failure_cannot_commit_business_without_checkpoint(service, database, monkeypatch, failure):
    before = await native.snapshot(database)
    if failure == "after_hash":
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql(
                "CREATE TRIGGER dirty_time AFTER UPDATE ON knowledge BEGIN "
                "UPDATE knowledge SET update_time='2099-01-01 00:00:00.000000' WHERE id=NEW.id; END"
            )
    else:
        original = service.runs.acheckpoint

        async def interrupted(*args, **kwargs):
            await original(*args, **kwargs)  # Prove rollback after real checkpoint SQL.
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("checkpoint acknowledgement lost")

        monkeypatch.setattr(service.runs, "acheckpoint", interrupted)
    async with AsyncSession(database.engine) as session, session.begin():
        batch = await issue(service, session, database.commands, eof=True)
        error = {
            "cancel": asyncio.CancelledError,
            "checkpoint": RuntimeError,
            "after_hash": KnowledgeOperationPlanConflictError,
        }[failure]
        with pytest.raises(error):
            await service.aapply_batch(session, batch=batch)
        # Intentionally catch and COMMIT the parent transaction.
    assert await native.snapshot(database) == before


async def test_pending_caller_writes_are_preserved_without_begin_nested_autoflush(service, database):
    async with AsyncSession(database.engine) as session, session.begin():
        batch = await issue(service, session, database.commands, eof=True)
        file = await session.get(native.raw.KnowledgeFile, 1)
        file.remark = "caller-owned change"
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(session, batch=batch)
        assert file.remark == "caller-owned change" and file in session.dirty
        # Getter is native/no_autoflush and cannot discard or flush caller state.
        assert (await progress(service, session)).processed_count == 0
        assert file in session.dirty
        await session.rollback()


async def test_empty_frozen_eof_has_real_zero_progress_without_fake_documents(service, database):
    async with AsyncSession(database.engine) as session, session.begin():
        result = await service.aapply_batch(session, batch=await issue(service, session, (), eof=True))
        assert result.outcomes == ()
        assert result.progress.cursor is None and result.progress.processed_count == 0
        assert result.progress.complete and len(result.progress.digest) == 64
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await issue(service, session, database.commands, expected_checkpoint=result.progress, continuation=result)
    after = await native.snapshot(database)
    assert after["knowledge"][0]["type"] == 0 and after["knowledge_document"] == ()


async def test_new_batches_need_the_real_committed_continuation_not_a_bare_cursor(service, database, module):
    async with AsyncSession(database.engine) as session, session.begin():
        first = await service.aapply_batch(session, batch=await issue(service, session, database.commands[:1]))
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await issue(
                service, session, database.commands[1:], ordinal=1, expected_checkpoint=first.progress, eof=True
            )
        batch = await issue(
            service,
            session,
            database.commands[1:],
            ordinal=1,
            expected_checkpoint=first.progress,
            continuation=first,
            eof=True,
        )
        last = await service.aapply_batch(session, batch=batch)
        assert last.progress.processed_count == len(database.commands) and last.progress.complete
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await module.UnificationConversionService()._issue_verified_batch(
                session,
                **native.IDENTITY,
                commands=(),
                ordinal=len(database.commands),
                expected_checkpoint=last.progress,
                continuation=last,
                eof=True,
            )


async def test_recovery_reads_real_allocated_ids_and_is_independent_of_page_boundaries(service, database, module):
    split = 3
    async with AsyncSession(database.engine) as session, session.begin():
        first = await service.aapply_batch(session, batch=await issue(service, session, database.commands[:split]))
    restarted = module.UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await progress(restarted, session)
        partial = await restarted.averify_committed_page(
            session,
            batch=await issue(restarted, session, database.commands[:1], expected_checkpoint=goal, mode="verify"),
        )
        assert not partial.verification_complete
        verified = await restarted.averify_committed_page(
            session,
            batch=await issue(
                restarted,
                session,
                database.commands[1:split],
                ordinal=1,
                expected_checkpoint=goal,
                continuation=partial,
                mode="verify",
                eof=True,
            ),
        )
        assert verified.verification_complete and verified.progress == first.progress
        result = await restarted.aapply_batch(
            session,
            batch=await issue(
                restarted,
                session,
                database.commands[split:],
                ordinal=split,
                expected_checkpoint=goal,
                continuation=verified,
                eof=True,
            ),
        )
        assert result.progress.complete
    # A new reader checks the complete prefix with a different batch boundary.
    checker = module.UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await progress(checker, session)
        checked = await checker.averify_committed_page(
            session,
            batch=await issue(checker, session, database.commands, expected_checkpoint=goal, mode="verify", eof=True),
        )
        assert checked.progress == goal and checked.verification_complete


async def test_recovery_rejects_real_after_drift_without_repairing_it(service, database, module):
    async with AsyncSession(database.engine) as session, session.begin():
        await service.aapply_batch(session, batch=await issue(service, session, database.commands, eof=True))
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(native.raw.KnowledgeDocument.__table__).values(level=999))
    before = await native.snapshot(database)
    checker = module.UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await progress(checker, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checker.averify_committed_page(
                session,
                batch=await issue(
                    checker, session, database.commands, expected_checkpoint=goal, mode="verify", eof=True
                ),
            )
    assert await native.snapshot(database) == before


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_large_conversion_and_fresh_session_recovery_are_linear_and_bounded(
    service, database, module, count
):
    from bisheng.knowledge.domain.services.unification_fingerprints import digest

    await database.insert(native.raw.KnowledgeFile, [native.raw.file(i) for i in range(10, count + 7)])
    facts = await native.producer.acquire(database, planned_at=native.NOW)
    builder = importlib.import_module(
        "bisheng.knowledge.application.unification_conversion_plan"
    ).ConversionPlanBuilder(
        run_id=native.IDENTITY["run_id"],
        writer_contract_version=native.IDENTITY["writer_contract_version"],
        planned_at=native.NOW,
    )
    for kind in native.producer.KINDS:
        rows = facts[kind]
        for offset in range(0, max(len(rows), 1), 200):
            values = rows[offset : offset + 200]
            kwargs = (
                {
                    "creator_memberships": tuple(
                        plan for plan in facts["creator_memberships"] if plan.knowledge_id in {row.id for row in values}
                    )
                }
                if kind == "resources"
                else {}
            )
            getattr(builder, "add_" + kind)(values, **kwargs)
    builder.add_defaults(())
    commands = tuple(cmd for cmd in builder.finish() if cmd.operation == "initialize_v1")
    assert len(commands) == count

    async def files_digest():
        async with database.engine.connect() as connection:
            return digest(
                [
                    dict(row)
                    for row in (
                        await connection.execute(
                            sa.select(native.raw.KnowledgeFile.__table__).order_by(native.raw.KnowledgeFile.id)
                        )
                    ).mappings()
                ]
            )

    original_files = await files_digest()
    database.queries.clear()
    current, continuation = None, None
    for offset in range(0, count, 200):
        async with AsyncSession(database.engine) as session, session.begin():
            continuation = await service.aapply_batch(
                session,
                batch=await issue(
                    service,
                    session,
                    commands[offset : offset + 200],
                    ordinal=offset,
                    expected_checkpoint=current,
                    continuation=continuation,
                    eof=offset + 200 >= count,
                ),
            )
            current = continuation.progress
    application_queries = len(database.queries)
    assert current.processed_count == count and current.complete
    assert application_queries <= ((count + 199) // 200) * 65
    assert await files_digest() == original_files
    async with database.engine.connect() as connection:
        for model in (native.raw.KnowledgeDocument, native.raw.KnowledgeDocumentVersion):
            assert await connection.scalar(sa.select(sa.func.count()).select_from(model)) == count
    checker = module.UnificationConversionService()
    database.queries.clear()
    continuation = None
    for offset in range(0, count, 137):
        async with AsyncSession(database.engine) as session, session.begin():
            continuation = await checker.averify_committed_page(
                session,
                batch=await issue(
                    checker,
                    session,
                    commands[offset : offset + 137],
                    ordinal=offset,
                    expected_checkpoint=current,
                    continuation=continuation,
                    mode="verify",
                    eof=offset + 137 >= count,
                ),
            )
    assert continuation.verification_complete and continuation.progress == current
    assert len(database.queries) <= ((count + 136) // 137) * 25
    # Actual native SQL, including union primary/survivor candidates, never has
    # an unbounded ID parameter list. Recovery never selects whole File history.
    import re

    for sql, _ in database.queries:
        assert all(section.count("?") <= 200 for section in re.findall(r"\bIN \(([^)]+)\)", sql))
    print(
        f"native conversion count={count} apply_SELECT={application_queries} "
        f"recovery_SELECT={len(database.queries)} apply_pages={(count + 199) // 200} recovery_pages={(count + 136) // 137}"
    )


async def test_rollback_result_is_not_a_committed_continuation_and_prefix_mode_cannot_write(service, database):
    async with AsyncSession(database.engine) as session, session.begin():
        first = await service.aapply_batch(session, batch=await issue(service, session, database.commands[:1]))
        await session.rollback()
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await issue(
                service,
                session,
                database.commands[1:],
                expected_checkpoint=first.progress,
                ordinal=1,
                continuation=first,
                eof=True,
            )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await issue(service, session, database.commands, mode="verify", eof=True)


async def test_getter_preserves_pending_run_changes_and_never_initializes_sql_progress(service, database):
    before = await native.snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        run = (await session.execute(sa.select(Run))).scalar_one()
        run.verification_report = {"caller": "pending"}
        run.checkpoints = {
            "converting": {"caller": {"cursor": None, "processed_count": 0, "digest": None, "complete": False}}
        }
        assert (await progress(service, session)).digest is None
        assert run in session.dirty and run.verification_report == {"caller": "pending"}
        assert "caller" in run.checkpoints["converting"]
        await session.rollback()
    assert await native.snapshot(database) == before


@pytest.mark.parametrize("retag_first", [False, True])
async def test_real_tag_link_retag_and_duplicate_drop_survivors_remain_valid_across_commits(
    service, database, module, retag_first
):
    commands = tuple(
        sorted(
            (cmd for cmd in database.commands if cmd.operation == "tag_link_conversion"),
            key=lambda cmd: cmd.action == "retag",
            reverse=retag_first,
        )
    )
    assert {cmd.action for cmd in commands} == {"retag", "drop_duplicate"}
    before = await native.snapshot(database)
    current, receipt = None, None
    for offset, command in enumerate(commands):
        async with AsyncSession(database.engine) as session, session.begin():
            receipt = await service.aapply_batch(
                session,
                batch=await issue(
                    service,
                    session,
                    (command,),
                    ordinal=offset,
                    expected_checkpoint=current,
                    continuation=receipt,
                    eof=offset == len(commands) - 1,
                ),
            )
            current = receipt.progress
    after = await native.snapshot(database)
    assert [row["id"] for row in after["taglink"]] == [2, 3]
    assert next(row for row in after["taglink"] if row["id"] == 2) == next(
        row for row in before["taglink"] if row["id"] == 2
    )
    assert next(row for row in after["taglink"] if row["id"] == 3)["resource_type"] == 8
    checker = module.UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        verified = await checker.averify_committed_page(
            session, batch=await issue(checker, session, commands, expected_checkpoint=current, mode="verify", eof=True)
        )
        assert verified.verification_complete and verified.progress == current


async def test_recovery_detects_allocated_primary_key_drift_even_when_templates_still_match(service, database, module):
    async with AsyncSession(database.engine) as session, session.begin():
        await service.aapply_batch(session, batch=await issue(service, session, database.commands, eof=True))
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.update(native.raw.KnowledgeDocument.__table__).where(native.raw.KnowledgeDocument.id == 1).values(id=999)
        )
        await connection.execute(
            sa.update(native.raw.KnowledgeDocumentVersion.__table__)
            .where(native.raw.KnowledgeDocumentVersion.document_id == 1)
            .values(document_id=999)
        )
    before = await native.snapshot(database)
    checker = module.UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await progress(checker, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checker.averify_committed_page(
                session,
                batch=await issue(
                    checker, session, database.commands, expected_checkpoint=goal, mode="verify", eof=True
                ),
            )
    assert await native.snapshot(database) == before


def test_conversion_service_does_not_execute_sql_outside_the_repository(module):
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    direct_sql = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "exec", "scalar", "scalars"}
    ]
    assert direct_sql == [], f"C1: SQL belongs to the Repository, found Service calls at {direct_sql}"
