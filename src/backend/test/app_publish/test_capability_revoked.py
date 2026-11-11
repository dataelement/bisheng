"""T058 — the capability-revoked error state and its 「已失效」 mark (AC-37 / AC-53 / AC-63).

What has to hold at once, and is easy to break one at a time:

* the refusal **names the capability and says 「已收回」**, so it is
  distinguishable from an ordinary failure and actionable without a log;
* it **does not fall back to the old value** — no cached whitelist, no last
  known good id;
* one invalid saved reference **blocks the whole version**, while inspection
  retains every declaration and its frozen ID for repair;
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
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import ModelFaceModelAmbiguousError, ModelFaceModelNotFoundError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.open_api.application.runtime_authorization import without_open_api_identity

from .reference_fixtures import bind_saved_source as bind_saved_source
from .reference_fixtures import delete_knowledge_target


async def _online_app_declaring(publish_db, app_factory, capabilities, *, binding=None):
    from bisheng.database.models.app_version import AppVersionDao

    app_row, version = await app_factory(state="online")
    async with publish_db() as session:
        row = await AppVersionDao.aget(session, app_row.id, version.id)
        row.capabilities = capabilities
        session.add(row)
        await session.commit()
    if binding is not None:
        await binding(app_row, version)
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


async def test_one_dead_knowledge_base_blocks_the_whole_saved_version_but_preserves_its_declaration(
    publish_db, app_factory, knowledge_factory, bind_saved_source
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
        binding=bind_saved_source,
    )

    async with publish_db() as session:
        await delete_knowledge_target(session, dead)
        await session.commit()

    with pytest.raises(ResourceReferenceInvalidError):
        await load_effective_declaration(app_row.id)
    declaration = await load_effective_declaration(app_row.id, purpose="inspect")
    assert {one.knowledge_id for one in declaration.knowledge} == {alive.id, dead.id}
    with pytest.raises(ResourceReferenceInvalidError):
        _ = declaration.knowledge_whitelist
    assert declaration.model_names == frozenset({"qwen-max"})


async def test_a_revoked_capability_never_falls_back_to_its_old_value(
    publish_db, app_factory, knowledge_factory, bind_saved_source
):
    dead = await knowledge_factory(name="将被删除")
    app_row, _version = await _online_app_declaring(
        publish_db, app_factory, {"knowledge_bases": [{"id": str(dead.id)}]}, binding=bind_saved_source
    )

    first = await load_effective_declaration(app_row.id)
    assert first.knowledge_whitelist == [dead.id]

    async with publish_db() as session:
        await delete_knowledge_target(session, dead)
        await session.commit()

    with pytest.raises(ResourceReferenceInvalidError):
        await load_effective_declaration(app_row.id)
    second = await load_effective_declaration(app_row.id, purpose="inspect")
    assert second.knowledge[0].knowledge_id == dead.id
    with pytest.raises(ResourceReferenceInvalidError):
        _ = second.knowledge_whitelist
    assert second.knowledge[0].reason == REASON_REVOKED


# ---------------------------------------------------------------------------
# AC-37 — the new declaration takes effect when the iteration goes online
# ---------------------------------------------------------------------------


async def test_a_capability_dropped_by_the_new_iteration_stops_working_when_it_goes_online(
    publish_db, app_factory, knowledge_factory, bind_saved_source
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
        binding=bind_saved_source,
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

    await bind_saved_source(app_row, iteration)
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

    # Draft precheck can show unresolved declarations without inventing an indexed source.
    rows = await capability_status(
        tenant_id=app_row.tenant_id,
        capabilities={
            "models": [{"name": "qwen-max"}],
            "knowledge_bases": [{"id": str(alive.id)}, {"id": str(qa.id)}, {"name": "重名库"}],
        },
    )

    by_label = {row.label: row for row in rows}
    assert by_label[str(alive.id)].display_name == "产品手册"
    assert by_label[str(alive.id)].revoked is False
    assert (by_label[str(qa.id)].revoked, by_label[str(qa.id)].reason) == (True, REASON_REVOKED)
    assert (by_label["重名库"].revoked, by_label["重名库"].reason) == (True, REASON_AMBIGUOUS)
    assert by_label["qwen-max"].kind == CAPABILITY_KIND_MODEL


async def test_nothing_about_the_marks_is_persisted(
    publish_db, app_factory, knowledge_factory, bind_saved_source, owner_user
):
    """AC-63 is a read-time computation: no column, no row, no timer.

    Asserted by computing the list twice around a change and requiring the second
    answer to reflect it — a stored mark would still say what it said before.
    """
    kb = await knowledge_factory(name="产品手册")
    app_row, version = await _online_app_declaring(
        publish_db, app_factory, {"knowledge_bases": [{"id": str(kb.id)}]}, binding=bind_saved_source
    )

    with without_open_api_identity():
        assert (await capability_bus_service.inspect_saved_capabilities(app_row.id, version.id, owner_user.payload))[
            0
        ].revoked is False

    async with publish_db() as session:
        await delete_knowledge_target(session, kb)
        await session.commit()

    with without_open_api_identity():
        assert (await capability_bus_service.inspect_saved_capabilities(app_row.id, version.id, owner_user.payload))[
            0
        ].revoked is True

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
    declaration = capability_bus_service.EffectiveDeclaration(
        app_row.id, app_row.tenant_id, "", models=("qwen-max", "gone", "重名模型")
    )

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
    monkeypatch, publish_db, app_factory, knowledge_factory, tier_seed, bind_saved_source, owner_user
):
    """AC-61 / AC-63 on the read model the publish page actually calls."""
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    alive = await knowledge_factory(name="产品手册")
    deleted = await knowledge_factory(name="将被删除")
    app_row, _version = await _online_app_declaring(
        publish_db,
        app_factory,
        {"models": [{"name": "qwen-max"}], "knowledge_bases": [{"id": str(alive.id)}, {"id": str(deleted.id)}]},
        binding=bind_saved_source,
    )

    import sqlalchemy as sa

    import bisheng.llm.domain.services.model_catalog as catalog
    from bisheng.llm.domain.models.llm_server import LLMModel

    async def _resolve(*args, **kwargs):
        raise AssertionError("saved inspection must not use the cached catalog")

    monkeypatch.setattr(catalog, "resolve_model_name", _resolve)
    async with publish_db() as session, session.begin():
        model = (await session.execute(sa.select(LLMModel).where(LLMModel.model_name == "qwen-max"))).scalars().one()
        model.online = False
        model_id = str(model.id)
        await delete_knowledge_target(session, deleted)
    with without_open_api_identity():
        status = await PublishStatusService.get_publish_status(app_row.id, actor=owner_user.payload)

    assert status["capabilities"] == [
        # The model was taken away in model management — marked, not hidden.
        {
            "kind": CAPABILITY_KIND_MODEL,
            "name": "qwen-max",
            "label": "qwen-max",
            "revoked": True,
            "reason": "offline",
            "target_id": model_id,
            "target_type": "model",
            "state": "valid",
        },
        {
            "kind": CAPABILITY_KIND_KNOWLEDGE,
            "name": "产品手册",
            "label": str(alive.id),
            "revoked": False,
            "reason": REASON_OK,
            "target_id": str(alive.id),
            "target_type": "knowledge_space",
            "state": "valid",
        },
        {
            "kind": CAPABILITY_KIND_KNOWLEDGE,
            "name": str(deleted.id),
            "label": str(deleted.id),
            "revoked": True,
            "reason": "invalid_deleted",
            "target_id": str(deleted.id),
            "target_type": "knowledge_space",
            "state": "invalid_deleted",
        },
    ]


async def test_the_publish_surface_still_renders_when_resolution_is_unavailable(
    monkeypatch, publish_db, app_factory, knowledge_factory, tier_seed, bind_saved_source, owner_user
):
    """A bad minute in the catalog must not take the whole page down."""
    from bisheng.app_publish.domain.services import capability_bus_service as bus
    from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService

    kb = await knowledge_factory(name="产品手册")
    app_row, _version = await _online_app_declaring(
        publish_db, app_factory, {"knowledge_bases": [{"id": str(kb.id)}]}, binding=bind_saved_source
    )

    async def _explode(*args, **kwargs):
        raise RuntimeError("knowledge module unavailable")

    monkeypatch.setattr(bus, "inspect_saved_capabilities", _explode)

    with without_open_api_identity():
        status = await PublishStatusService.get_publish_status(app_row.id, actor=owner_user.payload)

    assert status["capabilities"] == [
        {
            "kind": "knowledge",
            "name": str(kb.id),
            "label": str(kb.id),
            "revoked": True,
            "reason": "not_ready",
            "target_id": str(kb.id),
            "target_type": "knowledge_space",
            "state": "not_ready",
        }
    ]
    assert status["app_id"] == app_row.id


@pytest.mark.parametrize("payload", [None, {}, {"models": "not-a-list"}, {"unknown": 1}])
async def test_an_unreadable_declaration_reads_as_declaring_nothing(payload):
    """A frozen blob this platform cannot parse must fail closed, not guess."""
    declaration = capability_bus_service.parse_declaration(payload)

    assert declaration.is_empty()
