"""Empty root initialization preserves original denial through native recovery."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import (
    PermissionGrant,
)
from bisheng.permission.domain.models import (
    PermissionProjectionOperation as Op,
)
from bisheng.permission.domain.models import (
    ResourcePermissionMode as Mode,
)
from scripts import f118_empty_root as helper
from scripts import prepare_f118_history as script
from test.knowledge_unification import test_history_delete_closure as original

resource_native, native, history = original.resource_native, original.native, original.history


async def setup(history, count=1):
    from test.knowledge_unification import test_history_upgrade_defaults as defaults

    await defaults.seed(history)
    async with script.global_session(history.sessions) as session:
        pin = await script.read_pin(session)
    await history.db.insert(
        Knowledge, [original.original.resources.resource(15000 + i, model=None) for i in range(count)]
    )
    oldwrite = history.fga.write_atomic

    async def strict(*, writes, deletes):
        assert not writes
        assert all(delta.key in history.fga.present for delta in deletes), (
            "absent DELETE must use native forward recovery"
        )
        return await oldwrite(writes=writes, deletes=deletes)

    history.fga.write_atomic = strict
    return pin


@pytest.mark.parametrize("count", [2, 4])
async def test_empty_denial_preview_apply_verify_and_resume(history, count, record_property, tmp_path):
    from sqlalchemy import event

    pin = await setup(history, count)
    counts = {"sql": 0, "commits": 0}

    def query(*args):
        counts["sql"] += 1

    def commit(*args):
        counts["commits"] += 1

    event.listen(history.db.engine.sync_engine, "before_cursor_execute", query)
    event.listen(history.db.engine.sync_engine, "commit", commit)
    scans = history.fga.scans
    items = await helper.capture(history.sessions, history.fga, pin)
    assert len(items) == count
    plan = {"schema": 4, "pin": pin, "empty_root_initializations": items}
    filename = tmp_path / "plan.json"
    script.save_plan(filename, plan)
    assert script.load_plan(filename) == plan
    for _ in range(2):
        assert (
            len(
                await helper.apply(
                    script.load_plan(filename),
                    sessions=history.sessions,
                    client=history.fga,
                    runtime=history.runtime,
                    operator_id=7,
                )
            )
            == count
        )
    assert not await helper.capture(history.sessions, history.fga, pin)
    assert not history.fga.writes and history.fga.scans - scans == 5
    async with script.global_session(history.sessions) as session:
        for item in items:
            ident = item["business"]["id"]
            assert script.canonical((await session.get(Knowledge, ident)).model_dump()) == item["business"]
            mode = (
                await session.exec(
                    select(Mode).where(Mode.resource_id == str(ident), Mode.resource_type == "knowledge_library")
                )
            ).one()
            assert (mode.mode, mode.version, mode.projection_state) == ("CUSTOM", 1, "CURRENT")
            assert (await session.get(Op, mode.operation_id)).status == "FINALIZED"
            assert not (
                await session.exec(select(PermissionGrant).where(PermissionGrant.resource_id == str(ident)))
            ).all()
    record_property(
        "scale", str({"count": count, **counts, "scans": history.fga.scans - scans, "writes": history.fga.writes})
    )
    assert counts["sql"] < 130 * count + 10


@pytest.mark.parametrize("drift", ["payload", "graph", "incoming", "root", "foreign_mode", "pin"])
async def test_changed_empty_facts_reject_before_any_native_write(history, drift):
    pin = await setup(history)
    items = await helper.capture(history.sessions, history.fga, pin)
    if drift == "payload":
        await history.db.insert(KnowledgeFile, [original.original.resources.file(15100, knowledge_id=15000)])
    elif drift == "graph":
        history.fga.present.add(("user:7", "owner", "knowledge_library:15000"))
    elif drift == "incoming":
        history.fga.present.add(("knowledge_library:15000", "parent", "knowledge_file:99"))
    elif drift == "pin":
        pin = pin | {"model_id": "different"}
    else:
        async with script.global_session(history.sessions) as session:
            if drift == "root":
                root = await session.get(Knowledge, 15000)
                root.description = "changed"
                session.add(root)
            else:
                session.add(
                    Mode(
                        tenant_id=202,
                        resource_type="knowledge_space",
                        resource_id="15000",
                        mode="CUSTOM",
                        version=1,
                        projection_state="CURRENT",
                    )
                )
    with pytest.raises(BaseErrorCode):
        await helper.apply(
            {"pin": pin, "empty_root_initializations": items},
            sessions=history.sessions,
            client=history.fga,
            runtime=history.runtime,
            operator_id=7,
        )
    async with script.global_session(history.sessions) as session:
        assert not (await session.exec(select(Op).where(Op.scope_key == "knowledge_library:15000"))).all()


@pytest.mark.parametrize("boundary", ["prepared", "claimed", "finalized"])
async def test_native_receipt_survives_unknown_reply_without_enabling_root(history, monkeypatch, boundary):
    pin = await setup(history)
    items = await helper.capture(history.sessions, history.fga, pin)
    owner = history.runtime._state if boundary == "claimed" else history.runtime._projection
    method = "prepare_owner" if boundary == "claimed" else ("prepare" if boundary == "prepared" else "execute")
    original_call = getattr(owner, method)
    fired = False

    async def fail(*args, **kwargs):
        nonlocal fired
        value = await original_call(*args, **kwargs)
        if not fired:
            fired = True
            raise RuntimeError("lost native acknowledgement")
        return value

    monkeypatch.setattr(owner, method, fail)
    plan = {"pin": pin, "empty_root_initializations": items}
    with pytest.raises(RuntimeError):
        await helper.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    monkeypatch.setattr(owner, method, original_call)
    assert (
        len(
            await helper.apply(
                plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
            )
        )
        == 1
    )
    assert not history.fga.writes
