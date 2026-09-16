"""T058 — the capability-revoked error state and its 「已失效」 mark (AC-37 / AC-53 / AC-63).

What has to hold at once, and is easy to break one at a time:

* the refusal **names the capability and says 「已收回」**, so it is
  distinguishable from an ordinary failure and actionable without a log;
* it **does not fall back to the old value** — no cached whitelist, no last
  known good id;
* the application **stays usable as a whole**: one dead knowledge base must not
  take the other five, or the models, down with it;
* a new iteration's declaration takes effect **within five seconds** of going
  online, with nothing polling to make that true;
* the publish surface's marks are **computed on demand** — nothing persisted,
  no timer.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.app_publish.domain.services import capability_bus_service
from bisheng.app_publish.domain.services.capability_bus_service import (
    CAPABILITY_KIND_KNOWLEDGE,
    CAPABILITY_KIND_MODEL,
    REASON_AMBIGUOUS,
    REASON_OK,
    REASON_REVOKED,
    capability_status,
    load_effective_declaration,
    model_capability_status,
)
from bisheng.common.errcode.app_publish import AppCapabilityRevokedError
from bisheng.common.errcode.model_face import ModelFaceModelAmbiguousError, ModelFaceModelNotFoundError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum


async def _online_app_declaring(publish_db, app_factory, capabilities):
    from bisheng.database.models.app_version import AppVersionDao

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = capabilities
        session.add(row)
        await session.commit()
    return app_row, version


# ---------------------------------------------------------------------------
# The error itself (AC-53)
# ---------------------------------------------------------------------------


def test_16273_carries_the_capability_name_and_the_reason():
    error = AppCapabilityRevokedError(capability="产品手册", kind=CAPABILITY_KIND_KNOWLEDGE, knowledge_id=7)

    assert error.code == 16273
    assert "产品手册" in error.message
    assert "已被收回" in error.message
    payload = error.return_resp_instance().data
    assert payload["capability"] == "产品手册"
    assert payload["reason"] == REASON_REVOKED
    assert payload["kind"] == CAPABILITY_KIND_KNOWLEDGE


def test_16274_is_a_different_answer_from_16273():
    """ "Declare it and publish again" and "ask why it disappeared" are two fixes."""
    from bisheng.common.errcode.app_publish import AppCapabilityNotDeclaredError

    undeclared = AppCapabilityNotDeclaredError(capability="财务档案", kind=CAPABILITY_KIND_KNOWLEDGE)

    assert undeclared.code == 16274
    assert undeclared.code != AppCapabilityRevokedError(capability="财务档案").code


async def test_one_dead_knowledge_base_leaves_the_rest_of_the_declaration_working(
    publish_db, app_factory, knowledge_factory
):
    alive = await knowledge_factory(name="产品手册")
    dead = await knowledge_factory(name="将被删除")
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {
            "models": [{"name": "qwen-max"}],
            "knowledge_bases": [{"id": str(alive.id)}, {"id": str(dead.id)}],
        },
    )

    async with publish_db() as session:
        await session.delete(await session.get(type(dead), dead.id))
        await session.commit()

    declaration = await load_effective_declaration(app_row.id)

    # The surviving capability is still in the whitelist and the model
    # declaration is untouched — AC-53's "应用整体保持可用".
    assert declaration.knowledge_whitelist == [alive.id]
    assert declaration.model_names == frozenset({"qwen-max"})


async def test_a_revoked_capability_never_falls_back_to_its_old_value(publish_db, app_factory, knowledge_factory):
    dead = await knowledge_factory(name="将被删除")
    app_row, _version = await _online_app_declaring(
        publish_db, app_factory, {"knowledge_bases": [{"id": str(dead.id)}]}
    )

    first = await load_effective_declaration(app_row.id)
    assert first.knowledge_whitelist == [dead.id]

    async with publish_db() as session:
        await session.delete(await session.get(type(dead), dead.id))
        await session.commit()

    second = await load_effective_declaration(app_row.id)

    # Nothing cached the previous resolution; the id is simply gone.
    assert second.knowledge_whitelist == []
    assert second.knowledge[0].reason == REASON_REVOKED


# ---------------------------------------------------------------------------
# AC-37 — the new declaration takes effect when the iteration goes online
# ---------------------------------------------------------------------------


async def test_a_capability_dropped_by_the_new_iteration_stops_working_when_it_goes_online(
    publish_db, app_factory, knowledge_factory
):
    """AC-37's five seconds, with nothing polling to make it true.

    The effective declaration is read off ``app.current_version_id`` per call, so
    the moment the state machine moves that pointer the next call already
    answers with the new declaration. There is no cache to invalidate and
    therefore no window to bound — which is why this test moves the pointer and
    asserts, rather than sleeping.
    """
    from datetime import datetime

    from bisheng.database.models.app import AppDao
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    dropped = await knowledge_factory(name="将被移出声明")
    kept = await knowledge_factory(name="留在声明里")
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {"knowledge_bases": [{"id": str(dropped.id)}, {"id": str(kept.id)}]},
    )
    before = await load_effective_declaration(app_row.id)
    assert set(before.knowledge_whitelist) == {dropped.id, kept.id}

    async with publish_db() as session:
        iteration = AppVersion(
            app_id=app_row.id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            code_object_key="apps/x/versions/v2/code.tar.gz",
            manifest={},
            capabilities={"knowledge_bases": [{"id": str(kept.id)}]},
            injections={},
            tier_id="light",
            runtime="python3.11",
            submitted_at=datetime.now(),
        )
        await AppVersionDao.ainsert(session, iteration)
        stored = await AppDao.aget(session, app_row.id)
        stored.current_version_id = iteration.id
        session.add(stored)
        await session.commit()

    after = await load_effective_declaration(app_row.id)

    assert after.knowledge_whitelist == [kept.id]


def test_the_credential_side_of_the_five_second_bound_is_asserted_not_assumed():
    """The other half of AC-37 — the old key stops working inside the bound.

    Owned by T055; re-asserted from here because AC-37 is what makes the bound a
    product promise rather than an implementation detail of the credential cache.
    """
    from bisheng.app_publish.domain.services.app_credential_service import (
        REVOCATION_BOUND_SECONDS,
        assert_revocation_bound,
    )

    assert assert_revocation_bound() <= REVOCATION_BOUND_SECONDS == 5


# ---------------------------------------------------------------------------
# AC-63 — the publish surface's marks, computed on demand
# ---------------------------------------------------------------------------


async def test_the_capability_list_marks_the_dead_entries_with_a_reason(publish_db, app_factory, knowledge_factory):
    alive = await knowledge_factory(name="产品手册")
    qa = await knowledge_factory(name="问答库", knowledge_type=KnowledgeTypeEnum.QA.value)
    await knowledge_factory(name="重名库")
    await knowledge_factory(name="重名库")
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {
            "models": [{"name": "qwen-max"}],
            "knowledge_bases": [{"id": str(alive.id)}, {"id": str(qa.id)}, {"name": "重名库"}],
        },
    )

    rows = await capability_status(app_id=app_row.id)

    by_label = {row.label: row for row in rows}
    assert by_label[str(alive.id)].display_name == "产品手册"
    assert by_label[str(alive.id)].revoked is False
    assert (by_label[str(qa.id)].revoked, by_label[str(qa.id)].reason) == (True, REASON_REVOKED)
    assert (by_label["重名库"].revoked, by_label["重名库"].reason) == (True, REASON_AMBIGUOUS)
    assert by_label["qwen-max"].kind == CAPABILITY_KIND_MODEL


async def test_nothing_about_the_marks_is_persisted(publish_db, app_factory, knowledge_factory):
    """AC-63 is a read-time computation: no column, no row, no timer.

    Asserted by computing the list twice around a change and requiring the second
    answer to reflect it — a stored mark would still say what it said before.
    """
    kb = await knowledge_factory(name="产品手册")
    app_row, version = await _online_app_declaring(publish_db, app_factory, {"knowledge_bases": [{"id": str(kb.id)}]})

    assert (await capability_status(app_id=app_row.id))[0].revoked is False

    async with publish_db() as session:
        await session.delete(await session.get(type(kb), kb.id))
        await session.commit()

    assert (await capability_status(app_id=app_row.id))[0].revoked is True

    # And the version row that carries the declaration was never written to.
    from bisheng.database.models.app_version import AppVersionDao

    async with publish_db() as session:
        stored = await AppVersionDao.aget(session, app_row.id, version.id)
    assert stored.capabilities == {"knowledge_bases": [{"id": str(kb.id)}]}


async def test_a_version_that_is_not_running_yet_can_still_be_summarised(knowledge_factory):
    """The approval card asks about a version nobody is running (AC-24)."""
    kb = await knowledge_factory(name="产品手册")

    rows = await capability_status(
        tenant_id=kb.tenant_id,
        capabilities={"knowledge_bases": [{"id": str(kb.id)}, {"id": "999999"}]},
    )

    assert [(row.display_name, row.revoked) for row in rows] == [("产品手册", False), ("999999", True)]


async def test_model_marks_use_f051s_resolution_not_a_second_rule(monkeypatch, publish_db, app_factory):
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {"models": [{"name": "qwen-max"}, {"name": "gone"}, {"name": "重名模型"}]},
    )
    declaration = await load_effective_declaration(app_row.id)

    async def _resolve(tenant_id, requested, *, range=None):
        if requested == "gone":
            raise ModelFaceModelNotFoundError(model=requested)
        if requested == "重名模型":
            raise ModelFaceModelAmbiguousError(model=requested, candidates=["a/重名模型", "b/重名模型"])
        return SimpleNamespace(model_name=requested)

    import bisheng.llm.domain.services.model_catalog as catalog

    monkeypatch.setattr(catalog, "resolve_model_name", _resolve)

    rows = await model_capability_status(declaration)

    assert [(row.label, row.revoked, row.reason) for row in rows] == [
        ("qwen-max", False, REASON_OK),
        ("gone", True, REASON_REVOKED),
        # An ambiguous name gets its own reason: the fix is to qualify it, not to
        # ask an administrator why the model vanished.
        ("重名模型", True, REASON_AMBIGUOUS),
    ]


async def test_the_publish_surface_serves_the_marks_it_computed(
    monkeypatch, publish_db, app_factory, knowledge_factory, tier_seed
):
    """AC-61 / AC-63 on the read model the publish page actually calls."""
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    alive = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {"models": [{"name": "qwen-max"}], "knowledge_bases": [{"id": str(alive.id)}, {"id": "999999"}]},
    )

    import bisheng.llm.domain.services.model_catalog as catalog

    async def _resolve(tenant_id, requested, *, range=None):
        raise ModelFaceModelNotFoundError(model=requested)

    monkeypatch.setattr(catalog, "resolve_model_name", _resolve)

    status = await PublishStatusService.get_publish_status(
        app_row.id,
        actor=SimpleNamespace(user_id=app_row.owner_user_id, tenant_id=app_row.tenant_id, is_global_super=False),
    )

    assert status["capabilities"] == [
        # The model was taken away in model management — marked, not hidden.
        {"kind": CAPABILITY_KIND_MODEL, "name": "qwen-max", "revoked": True, "reason": REASON_REVOKED},
        {"kind": CAPABILITY_KIND_KNOWLEDGE, "name": "产品手册", "revoked": False, "reason": REASON_OK},
        {"kind": CAPABILITY_KIND_KNOWLEDGE, "name": "999999", "revoked": True, "reason": REASON_REVOKED},
    ]


async def test_the_publish_surface_still_renders_when_resolution_is_unavailable(
    monkeypatch, publish_db, app_factory, knowledge_factory, tier_seed
):
    """A bad minute in the catalog must not take the whole page down."""
    from bisheng.app_publish.domain.services import capability_bus_service as bus
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    kb = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(publish_db, app_factory, {"knowledge_bases": [{"id": str(kb.id)}]})

    async def _explode(**kwargs):
        raise RuntimeError("knowledge module unavailable")

    monkeypatch.setattr(bus, "capability_status", _explode)

    status = await PublishStatusService.get_publish_status(
        app_row.id,
        actor=SimpleNamespace(user_id=app_row.owner_user_id, tenant_id=app_row.tenant_id, is_global_super=False),
    )

    # Empty reads as "no declaration shown", never as "everything is fine".
    assert status["capabilities"] == []
    assert status["app_id"] == app_row.id


@pytest.mark.parametrize("payload", [None, {}, {"models": "not-a-list"}, {"unknown": 1}])
async def test_an_unreadable_declaration_reads_as_declaring_nothing(payload):
    """A frozen blob this platform cannot parse must fail closed, not guess."""
    declaration = capability_bus_service.parse_declaration(payload)

    assert declaration.is_empty()
