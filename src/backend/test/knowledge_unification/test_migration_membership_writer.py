"""T1011: actual producer -> original SQL service/App -> atomic Root+Member."""

import asyncio
import importlib
from dataclasses import asdict, replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.models.space_channel_member import SpaceChannelMember as Member
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    MEMBER_COLUMNS,
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.schemas.unification_conversion import ResourceConversionCommand
from bisheng.knowledge.domain.services.unification_conversion import UnificationConversionService
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from test.knowledge_unification import test_migration_conversion_application as app_native
from test.knowledge_unification import test_migration_conversion_repository as original
from test.knowledge_unification.test_migration_space_membership_inventory import member

resource_native, database = original.resource_native, original.database
native, complete, transport, produced, module = (
    app_native.native,
    app_native.complete,
    app_native.transport,
    app_native.produced,
    app_native.module,
)


async def commands(database):
    facts = await original.producer.acquire(database, planned_at=original.NOW)
    builder = importlib.import_module(
        "bisheng.knowledge.application.unification_conversion_plan"
    ).ConversionPlanBuilder(
        run_id=original.IDENTITY["run_id"],
        writer_contract_version=original.IDENTITY["writer_contract_version"],
        planned_at=original.NOW,
    )
    memberships = {row.knowledge_id: row for row in facts["creator_memberships"]}
    resources = facts["resources"]
    for start in range(0, len(resources), 200):
        rows = resources[start : start + 200]
        builder.add_resources(rows, creator_memberships=tuple(memberships[row.id] for row in rows if row.type == 0))
    return tuple(builder.finish())


async def issue(service, session, values, **kwargs):
    return await service._issue_verified_batch(session, **original.IDENTITY, commands=values, **kwargs)


async def rows(session, knowledge_id=9000):
    result, cursor = [], None
    while True:
        page = await UnificationSpaceMembershipRepository().apage_members(
            session, knowledge_ids=(knowledge_id,), after_id=cursor
        )
        result.extend(page.items)
        if page.next_after is None:
            return tuple(result)
        cursor = page.next_after


async def snapshot(database):
    result = await original.snapshot(database)
    async with database.engine.connect() as connection:
        result["members"] = tuple(
            dict(row) for row in (await connection.execute(sa.select(Member.__table__).order_by(Member.id))).mappings()
        )
    return result


async def verify(service, session, values, goal):
    batch = await issue(service, session, values, expected_checkpoint=goal, mode="verify", eof=True)
    return await service.averify_committed_page(session, batch=batch)


async def test_other_four_kinds_keep_the_actual_pre_writer_outcome_bytes(database):
    values = tuple(row for row in database.commands if type(row) is not ResourceConversionCommand)
    repo = UnificationConversionService().repository
    async with AsyncSession(database.engine) as session, session.begin():
        result = await original.apply(repo, session, values)
    # Native fixed e2d0d23bff, before the Member Writer; no new Outcome fields.
    assert (
        digest(tuple(asdict(row) for row in result))
        == "47dc19e965c9dbfb003fefb9937091400696885af93d29442b331bca6b7b0292"
    )


@pytest.mark.parametrize("keep", [False, True])
async def test_real_producer_service_binds_actual_creator_pk_full_set_and_preserves_every_original_source(
    database, keep
):
    other = member(31, "9000", user_id=8, user_role="MEMBER", status="REJECTED", grant_binding_key="other-source")
    initial = [other, member(41, "9001", user_id=9, status="PENDING")]
    if keep:
        initial.append(
            member(
                51,
                "9000",
                membership_source="department_admin",
                department_admin_promoted_from_role="member",
                relation="editor",
                grant_subject_type="department",
                grant_subject_id=19,
                grant_relation="viewer",
                grant_include_children=True,
                grant_model_id="retired-source",
                grant_binding_key="original-source",
                is_pinned=True,
                update_time=None,
            )
        )
    await database.insert(Member, initial)
    values = await commands(database)
    command = values[0]
    assert command.membership_action == ("keep" if keep else "insert")
    before = await snapshot(database)
    service = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        result = await service.aapply_batch(session, batch=await issue(service, session, values, eof=True))
        actual = await rows(session)
        creator = next(row for row in actual if row.user_id == 7)
        assert creator.id == (51 if keep else max(row.id for row in actual))
        template = {name: getattr(creator, name) for name in MEMBER_COLUMNS if name != "id"}
        assert digest(template) == command.creator_template_digest
        assert result.outcomes[0].actual_after_digest == digest(
            (
                command.after_business_digest,
                command.after_neutral_digest,
                creator.id,
                digest(tuple(asdict(row) for row in actual)),
            )
        )
        assert (await session.get(original.raw.Knowledge, 9000)).type == 3
    after = await snapshot(database)
    assert tuple(row for row in after["members"] if row["id"] in {31, 41, 51}) == before["members"]
    assert after["knowledgefile"] == before["knowledgefile"]
    fresh = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await fresh.aget_progress(session, **original.IDENTITY)
        assert (await verify(fresh, session, values, goal)).verification_complete
    assert await snapshot(database) == after


@pytest.mark.parametrize(
    "failure", ["late-sql", "cancel", "member-trigger", "member-pk-trigger", "root-trigger", "checkpoint"]
)
async def test_caught_late_failure_cannot_commit_half_converted_root_member_or_run_checkpoint(
    database, monkeypatch, failure
):
    values = tuple(row for row in database.commands if type(row) is ResourceConversionCommand)
    service = UnificationConversionService()
    if failure.endswith("trigger"):
        table, event, assignment = (
            ("space_channel_member", "INSERT", "grant_binding_key='unexpected'")
            if failure.startswith("member")
            else ("knowledge", "UPDATE", "update_time='2099-01-01 00:00:00.000000'")
        )
        if failure == "member-pk-trigger":
            assignment = "id=NEW.id+1000"
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql(
                f"CREATE TRIGGER unexpected AFTER {event} ON {table} BEGIN UPDATE {table} SET {assignment} WHERE id=NEW.id; END"
            )
    before = await snapshot(database)
    async with AsyncSession(database.engine) as session, session.begin():
        if failure in {"late-sql", "cancel"}:
            flush, hit = session.flush, []

            async def interrupted(*args, **kwargs):
                await flush(*args, **kwargs)
                if not hit and any(type(row) is Member for row in session.identity_map.values()):
                    hit.append(True)
                    raise (
                        asyncio.CancelledError() if failure == "cancel" else RuntimeError("after actual Member insert")
                    )

            monkeypatch.setattr(session, "flush", interrupted)
        if failure == "checkpoint":
            checkpoint = service.runs.acheckpoint

            async def broken(*args, **kwargs):
                await checkpoint(*args, **kwargs)
                raise RuntimeError("after actual Run checkpoint")

            monkeypatch.setattr(service.runs, "acheckpoint", broken)
        error = (
            asyncio.CancelledError
            if failure == "cancel"
            else KnowledgeOperationPlanConflictError
            if failure.endswith("trigger")
            else RuntimeError
        )
        with pytest.raises(error):
            await service.aapply_batch(session, batch=await issue(service, session, values, eof=True))
    assert await snapshot(database) == before


@pytest.mark.parametrize("drift", ["pk", "source", "insert", "delete", "original-source", "original-delete"])
@pytest.mark.parametrize("keep", [False, True])
async def test_committed_prefix_verification_rejects_member_pk_or_complete_source_set_drift(database, drift, keep):
    await database.insert(
        Member,
        [
            member(
                10,
                "9000",
                user_id=7 if keep else 8,
                user_role="CREATOR" if keep else "MEMBER",
                grant_binding_key="frozen-source",
            )
        ],
    )
    values = await commands(database)
    service = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        await service.aapply_batch(session, batch=await issue(service, session, values, eof=True))
        actual_id = next(row.id for row in await rows(session) if row.user_id == 7)
    target_id = 10 if drift.startswith("original-") else actual_id
    async with database.engine.begin() as connection:
        if drift == "insert":
            await connection.execute(sa.insert(Member.__table__), member(20, "9000", user_id=8, user_role="MEMBER"))
        elif drift.endswith("delete"):
            await connection.execute(sa.delete(Member.__table__).where(Member.id == target_id))
        else:
            await connection.execute(
                sa.update(Member.__table__)
                .where(Member.id == target_id)
                .values(**({"id": 99} if drift == "pk" else {"grant_binding_key": "changed-source"}))
            )
    restarted = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        goal = await restarted.aget_progress(session, **original.IDENTITY)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await verify(restarted, session, values, goal)


async def test_after_without_a_durable_checkpoint_is_never_adopted_or_inserted_again(database):
    values = tuple(row for row in database.commands if type(row) is ResourceConversionCommand)
    service = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        scope = await service.repository.alock_scope(session, **original.IDENTITY, commands=values)
        await service.repository.aapply_and_read_after(session, scope=scope)
    before = await snapshot(database)
    assert len(before["members"]) == 1 and before["knowledge"][0]["type"] == 3
    async with AsyncSession(database.engine) as session, session.begin():
        assert (await service.aget_progress(session, **original.IDENTITY)).processed_count == 0
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(session, batch=await issue(service, session, values, eof=True))
    assert await snapshot(database) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"creator_user_id": True},
        {"creator_user_id": 7.0},
        {"before_member_count": True},
        {"before_member_digest": "f" * 64},
        {"creator_template_digest": "f" * 64},
        {"existing_creator_member_id": True},
        {"creator_planned_at": None},
        {"membership_action": "promote"},
    ],
)
async def test_native_command_fields_and_original_creator_evidence_are_not_coerced_or_guessed(database, changes):
    value = next(row for row in database.commands if type(row) is ResourceConversionCommand)
    before = await snapshot(database)
    service = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(
                session, batch=await issue(service, session, (replace(value, **changes),), eof=True)
            )
    assert await snapshot(database) == before


@pytest.mark.parametrize("drift", ["extra", "foreign", "missing", "owner"])
async def test_live_before_scope_and_full_member_set_are_rechecked_without_adoption(database, drift):
    value = next(row for row in database.commands if type(row) is ResourceConversionCommand)
    async with database.engine.begin() as connection:
        if drift == "extra":
            await connection.execute(sa.insert(Member.__table__), member(10, "9000", user_id=8, user_role="MEMBER"))
        elif drift == "missing":
            await connection.execute(
                sa.delete(original.raw.Knowledge.__table__).where(original.raw.Knowledge.id == 9000)
            )
        else:
            await connection.execute(
                sa.update(original.raw.Knowledge.__table__)
                .where(original.raw.Knowledge.id == 9000)
                .values(**({"tenant_id": 202} if drift == "foreign" else {"user_id": 8}))
            )
    before = await snapshot(database)
    service = UnificationConversionService()
    async with AsyncSession(database.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aapply_batch(session, batch=await issue(service, session, (value,), eof=True))
    assert await snapshot(database) == before


@pytest.mark.parametrize("drift", ["tenant", "transaction"])
async def test_original_scope_is_captured_before_the_first_native_await(database, monkeypatch, drift):
    repo = UnificationConversionService().repository
    value = next(row for row in database.commands if type(row) is ResourceConversionCommand)
    async with AsyncSession(database.engine) as session, session.begin():
        execute, tokens, nested, hit = session.execute, [], [], []

        async def changed(*args, **kwargs):
            result = await execute(*args, **kwargs)
            if not hit:
                hit.append(True)
                if drift == "tenant":
                    tokens.append(set_current_tenant_id(202))
                else:
                    nested.append(await session.begin_nested())
            return result

        monkeypatch.setattr(session, "execute", changed)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.alock_scope(session, **original.IDENTITY, commands=(value,))
        finally:
            for token in reversed(tokens):
                current_tenant_id.reset(token)
            for active in reversed(nested):
                await active.rollback()


@pytest.mark.parametrize("after", [False, True])
async def test_actual_frozen_app_unknown_commit_recovers_once_with_the_same_creator_pk(module, produced, after):
    database, _, _, _ = produced
    app, _ = app_native.application(module, produced, app_native.Sessions(database.engine, fail_at=1, after=after))
    with pytest.raises(ReferenceCoverageNotReadyError) as caught:
        await app.arun(**app_native.arguments(produced))
    assert caught.value.kwargs["sql_conversion_report"]["commit_outcome"] == "unknown"
    async with AsyncSession(database.engine) as session, session.begin():
        interrupted = await rows(session)
    assert len(interrupted) == int(after)
    restarted, _ = app_native.application(module, produced)
    assert (await restarted.arun(**app_native.arguments(produced))).sql_complete
    async with AsyncSession(database.engine) as session, session.begin():
        final = await rows(session)
    assert len(final) == 1 and (not after or final == interrupted)
    assert await restarted.arun(**app_native.arguments(produced))
    async with AsyncSession(database.engine) as session, session.begin():
        assert await rows(session) == final
