"""T060 — reference validation of a capability declaration at precheck (AC-07 / AC-24).

The rule this suite defends is not "the references are checked" but **where the
check gets its answer**: a model goes through F051's ``resolve_model_name`` and a
knowledge base through F052's facade. A precheck with a SELECT of its own would
eventually pass a declaration the runtime refuses — a green that costs an
approval cycle to discover.

The second half is the approval card's plain-language summary (AC-24): it reads
the same resolution, so the reviewer sees the names the owner wrote next to
whatever is already broken, rather than a JSON blob.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.capability_bus_service import (
    capability_status,
    validate_capability_refs,
)
from bisheng.common.errcode.app_publish import AppCapabilityUnresolvableError
from bisheng.common.errcode.model_face import (
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

TENANT_ID = 1
OWNER_ID = 92001


def _declaration(models=(), knowledge_refs=()):
    return CapabilityDeclaration.model_validate(
        {"models": [{"name": name} for name in models], "knowledge_bases": list(knowledge_refs)}
    )


@pytest.fixture()
def catalog(monkeypatch):
    """Stand in for F051's catalog, raising exactly the codes it raises."""
    import bisheng.llm.domain.services.model_catalog as module

    known = {"qwen-max"}
    offline = {"下线了的模型"}
    ambiguous = {"重名模型"}

    async def _resolve(tenant_id, requested, *, range=None):
        if requested in ambiguous:
            raise ModelFaceModelAmbiguousError(model=requested, candidates=["乙服务商/重名模型", "甲服务商/重名模型"])
        if requested in offline:
            raise ModelFaceModelOfflineError(model=requested)
        if requested not in known:
            raise ModelFaceModelNotFoundError(model=requested)
        return SimpleNamespace(model_name=requested)

    monkeypatch.setattr(module, "resolve_model_name", _resolve)
    return SimpleNamespace(known=known, offline=offline, ambiguous=ambiguous)


@pytest.fixture()
def reachable(monkeypatch):
    """Stand in for the facade's owner-side reachability report."""
    from bisheng.knowledge.domain.schemas.retrieval_facade import ReachabilityReport, RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    state = {"unreachable": [], "revoked": []}

    async def _check(identity, knowledge_ids, *, whitelist=None):
        return ReachabilityReport(
            reachable=[one for one in knowledge_ids if one not in state["unreachable"]],
            unreachable=list(state["unreachable"]),
            revoked=list(state["revoked"]),
        )

    async def _from_user(user_id, tenant_id, **kwargs):
        return SimpleNamespace(actor=SimpleNamespace(subject_id=user_id), login_user=None)

    monkeypatch.setattr(RetrievalFacadeService, "check_reachable", classmethod(lambda cls, *a, **k: _check(*a, **k)))
    monkeypatch.setattr(RetrievalIdentity, "from_user", classmethod(lambda cls, *a, **k: _from_user(*a, **k)))
    return state


# ---------------------------------------------------------------------------
# Models (AC-07)
# ---------------------------------------------------------------------------


async def test_an_empty_declaration_asks_nothing_of_anything(catalog, reachable):
    await validate_capability_refs(_declaration(), tenant_id=TENANT_ID, owner_user_id=OWNER_ID)


async def test_an_enabled_uniquely_resolvable_model_passes(catalog, reachable):
    await validate_capability_refs(_declaration(models=["qwen-max"]), tenant_id=TENANT_ID, owner_user_id=OWNER_ID)


async def test_an_ambiguous_bare_name_is_refused_and_asks_for_the_qualified_one(catalog, reachable):
    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(_declaration(models=["重名模型"]), tenant_id=TENANT_ID, owner_user_id=OWNER_ID)

    error = excinfo.value
    assert error.code == 16224
    assert error.kwargs["details"]["reason"] == "model_ambiguous"
    assert error.kwargs["details"]["candidates"] == ["乙服务商/重名模型", "甲服务商/重名模型"]
    # The hint names a real qualified form, not a made-up placeholder.
    assert "乙服务商/重名模型" in error.kwargs["hints"][0]


@pytest.mark.parametrize("name", ["从未存在", "下线了的模型"])
async def test_a_model_that_is_absent_or_disabled_is_refused(catalog, reachable, name):
    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(_declaration(models=[name]), tenant_id=TENANT_ID, owner_user_id=OWNER_ID)

    assert excinfo.value.kwargs["details"]["reason"] == "model_unavailable"
    assert excinfo.value.kwargs["details"]["value"] == name


async def test_the_verdict_comes_from_f051_not_from_a_second_query(monkeypatch, reachable):
    """The point of T060: one definition of "callable", shared with the face."""
    import bisheng.llm.domain.services.model_catalog as module

    asked = []

    async def _resolve(tenant_id, requested, *, range=None):
        asked.append((tenant_id, requested))
        return SimpleNamespace(model_name=requested)

    monkeypatch.setattr(module, "resolve_model_name", _resolve)

    await validate_capability_refs(
        _declaration(models=["qwen-max", "gpt-4o"]), tenant_id=TENANT_ID, owner_user_id=OWNER_ID
    )

    assert asked == [(TENANT_ID, "qwen-max"), (TENANT_ID, "gpt-4o")]


# ---------------------------------------------------------------------------
# Knowledge bases (AC-07)
# ---------------------------------------------------------------------------


async def test_a_knowledge_base_that_exists_and_is_retrievable_passes(catalog, reachable, knowledge_factory):
    kb = await knowledge_factory(name="产品手册")

    await validate_capability_refs(
        _declaration(knowledge_refs=[{"id": str(kb.id)}]), tenant_id=kb.tenant_id, owner_user_id=OWNER_ID
    )


async def test_a_missing_knowledge_base_is_refused(catalog, reachable, publish_db):
    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(
            _declaration(knowledge_refs=[{"id": "999999"}]), tenant_id=TENANT_ID, owner_user_id=OWNER_ID
        )

    assert excinfo.value.kwargs["details"]["reason"] == "knowledge_revoked"


async def test_a_type_the_facade_cannot_retrieve_from_is_refused(catalog, reachable, knowledge_factory):
    qa = await knowledge_factory(name="问答库", knowledge_type=KnowledgeTypeEnum.QA.value)

    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(
            _declaration(knowledge_refs=[{"id": str(qa.id)}]), tenant_id=qa.tenant_id, owner_user_id=OWNER_ID
        )

    assert "问答库暂不支持检索" in excinfo.value.kwargs["hints"][0]


async def test_a_knowledge_space_is_a_supported_type(catalog, reachable, knowledge_factory):
    space = await knowledge_factory(name="研发知识空间", knowledge_type=KnowledgeTypeEnum.SPACE.value)

    await validate_capability_refs(
        _declaration(knowledge_refs=[{"id": str(space.id)}]),
        tenant_id=space.tenant_id,
        owner_user_id=OWNER_ID,
    )


async def test_an_ambiguous_knowledge_name_asks_for_the_id(catalog, reachable, knowledge_factory):
    first = await knowledge_factory(name="重名库")
    await knowledge_factory(name="重名库")

    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(
            _declaration(knowledge_refs=[{"name": "重名库"}]),
            tenant_id=first.tenant_id,
            owner_user_id=OWNER_ID,
        )

    assert excinfo.value.kwargs["details"]["reason"] == "knowledge_ambiguous"
    assert "id" in excinfo.value.kwargs["hints"][0]


async def test_a_knowledge_base_the_owner_cannot_reach_is_refused(catalog, reachable, knowledge_factory):
    """The declaration's ceiling is the owner's grants (design D13).

    Publishing it anyway would produce an application whose retrieval is empty
    for everyone, with nothing saying why.
    """
    kb = await knowledge_factory(name="财务档案")
    reachable["unreachable"] = [kb.id]

    with pytest.raises(AppCapabilityUnresolvableError) as excinfo:
        await validate_capability_refs(
            _declaration(knowledge_refs=[{"id": str(kb.id)}]), tenant_id=kb.tenant_id, owner_user_id=OWNER_ID
        )

    assert excinfo.value.kwargs["details"]["reason"] == "knowledge_unreachable"
    assert excinfo.value.kwargs["details"]["unreachable"] == [kb.id]


# ---------------------------------------------------------------------------
# The gate on a deployment that cannot issue the scope
# ---------------------------------------------------------------------------


async def test_a_declaration_is_refused_when_its_scope_cannot_be_issued_here(monkeypatch, tier_seed):
    """16231 keeps its meaning: "this environment cannot honour that declaration"."""
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
    from bisheng.common.errcode.app_publish import AppCapabilityBusDisabledError
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    manifest = (
        "manifest_version: 1\nname: demo\nruntime: python3.11\nport: 8080\n"
        "capabilities:\n  models:\n    - name: qwen-max\n"
    )

    with pytest.raises(AppCapabilityBusDisabledError) as excinfo:
        await validate_manifest(manifest)

    assert excinfo.value.code == 16231
    assert excinfo.value.kwargs["details"]["scopes"] == ["model:invoke"]


async def test_a_knowledge_only_declaration_is_accepted_without_the_extension_scope(monkeypatch, tier_seed):
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    manifest = (
        "manifest_version: 1\nname: demo\nruntime: python3.11\nport: 8080\n"
        "capabilities:\n  knowledge_bases:\n    - id: '7'\n"
    )

    validated = await validate_manifest(manifest)

    # The schema stage no longer refuses a declaration outright — reference
    # resolution is the receive leg's job, with the tenant and owner in hand.
    assert [ref.id for ref in validated.manifest.capabilities.knowledge_bases] == ["7"]


async def test_a_secret_reference_is_still_refused_before_anything_else(tier_seed):
    """决议-1: secret references wait for PRD-2, and 16230 says so (AC-56)."""
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
    from bisheng.common.errcode.app_publish import AppSecretReferenceUnsupportedError

    manifest = (
        "manifest_version: 1\nname: demo\nruntime: python3.11\nport: 8080\n"
        "capabilities:\n  models:\n    - name: vault://models/key\n"
    )

    with pytest.raises(AppSecretReferenceUnsupportedError) as excinfo:
        await validate_manifest(manifest)

    assert excinfo.value.code == 16230


# ---------------------------------------------------------------------------
# AC-24 — the approval card's summary reads the same resolution
# ---------------------------------------------------------------------------


async def test_the_approval_summary_shows_real_names_and_real_marks(knowledge_factory):
    kb = await knowledge_factory(name="产品手册")

    rows = await capability_status(
        tenant_id=kb.tenant_id,
        capabilities={
            "models": [{"name": "qwen-max"}],
            "knowledge_bases": [{"id": str(kb.id)}, {"name": "已经没有的库"}],
        },
    )

    # Plain language: the knowledge base's own name, not its id; and the entry
    # that no longer resolves is marked rather than silently listed as healthy.
    assert [(row.kind, row.display_name, row.revoked) for row in rows] == [
        ("model", "qwen-max", False),
        ("knowledge", "产品手册", False),
        ("knowledge", "已经没有的库", True),
    ]
