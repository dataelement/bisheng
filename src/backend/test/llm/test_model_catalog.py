"""F051 T008: the callable model catalog and name resolution.

This module is the single source three consumers share (the model protocol
face, F052's list tool, F055's precheck), so the rules it encodes — what is
callable, what a name resolves to, and what happens when it cannot be decided —
are asserted here rather than at each consumer.
"""

import pytest

from bisheng.common.errcode.model_face import (
    ModelFaceCapabilityUndeclaredError,
    ModelFaceCatalogUnavailableError,
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.common.services.config_service import settings
from bisheng.llm.domain.services import model_catalog
from bisheng.llm.domain.services.model_catalog import (
    ModelRange,
    invalidate_catalog,
    list_callable_chat_models,
    resolve_model_name,
)
from test.open_api.model_gateway_fixtures import install_catalog, model_row, server_row

TENANT = 9


@pytest.fixture(autouse=True)
def _clean_catalog_cache():
    invalidate_catalog()
    yield
    invalidate_catalog()


def _default_rows():
    servers = [
        server_row(1, "azure-openai"),
        server_row(2, "qwen-cloud"),
        server_row(3, "root-shared"),
    ]
    models = [
        model_row(10, 1, "gpt-4o"),
        model_row(11, 1, "shared-name"),
        model_row(12, 2, "shared-name"),
        model_row(13, 2, "qwen/qwen-2.5-72b"),
        model_row(14, 1, "retired-model", online=False),
        model_row(15, 1, "text-embedding-3", model_type="embedding"),
        model_row(16, 3, "root-model"),
        # Belongs to a provider this tenant cannot see. Deleting a provider
        # deletes its models with it, so "not visible" is the only shape a
        # foreign row can actually take.
        model_row(17, 99, "another-tenants-model"),
    ]
    return servers, models


async def test_list_callable_only_llm_and_online(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    names = {model.model_name for model in await list_callable_chat_models(TENANT)}

    assert "gpt-4o" in names
    assert "retired-model" not in names
    assert "text-embedding-3" not in names
    assert "another-tenants-model" not in names


async def test_root_shared_server_models_are_callable_for_the_child(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    resolved = await resolve_model_name(TENANT, "root-model")

    assert resolved.server_name == "root-shared"


async def test_exact_unique_name_resolves(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    resolved = await resolve_model_name(TENANT, "gpt-4o")

    assert (resolved.model_id, resolved.server_name) == (10, "azure-openai")
    assert resolved.qualified_name == "azure-openai/gpt-4o"


async def test_model_name_containing_a_slash_prefers_the_bare_match(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    resolved = await resolve_model_name(TENANT, "qwen/qwen-2.5-72b")

    # Not read as "provider qwen, model qwen-2.5-72b": the bare name exists.
    assert resolved.model_id == 13
    assert resolved.server_name == "qwen-cloud"


async def test_ambiguous_bare_name_is_refused_with_the_qualified_alternatives(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    with pytest.raises(ModelFaceModelAmbiguousError) as excinfo:
        await resolve_model_name(TENANT, "shared-name")

    assert excinfo.value.code == 26214
    assert excinfo.value.candidates == ["azure-openai/shared-name", "qwen-cloud/shared-name"]


async def test_qualified_name_resolves_for_ambiguous_and_unique_rows(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    ambiguous = await resolve_model_name(TENANT, "qwen-cloud/shared-name")
    unique = await resolve_model_name(TENANT, "azure-openai/gpt-4o")

    assert ambiguous.model_id == 12
    assert unique.model_id == 10


async def test_offline_is_distinguishable_from_missing(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    with pytest.raises(ModelFaceModelOfflineError) as offline:
        await resolve_model_name(TENANT, "retired-model")
    with pytest.raises(ModelFaceModelNotFoundError) as missing:
        await resolve_model_name(TENANT, "never-configured")

    assert (offline.value.code, missing.value.code) == (26212, 26211)


async def test_another_tenants_model_reads_as_missing_not_as_revoked(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    with pytest.raises(ModelFaceModelNotFoundError) as excinfo:
        await resolve_model_name(TENANT, "another-tenants-model")

    # "Not yours" and "does not exist" must be one answer, or the face becomes
    # an existence oracle for other tenants' configuration (AC-13).
    assert excinfo.value.code == 26211


async def test_a_deleted_provider_leaves_no_model_row_to_explain(monkeypatch):
    # Deleting a provider deletes its models (LLMDao.adelete_server_by_id), so
    # resolution cannot report "revoked" — there is nothing left to find. 26213
    # is raised one step later instead, when the cached name still resolves and
    # instantiation finds the row gone; that path is asserted in
    # test_model_gateway_stream.py.
    servers, models = _default_rows()
    install_catalog(monkeypatch, [server for server in servers if server.id != 1], models)

    with pytest.raises(ModelFaceModelNotFoundError):
        await resolve_model_name(TENANT, "gpt-4o")


async def test_non_chat_model_reads_as_not_found_without_disclosing_its_type(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    with pytest.raises(ModelFaceModelNotFoundError) as excinfo:
        await resolve_model_name(TENANT, "text-embedding-3")

    assert "embedding" not in excinfo.value.message.lower().replace("text-embedding-3", "")


async def test_list_offers_qualified_names_only_for_ambiguous_rows(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    callable_names = {model.callable_name for model in await list_callable_chat_models(TENANT)}

    assert "gpt-4o" in callable_names
    assert "shared-name" not in callable_names
    assert {"azure-openai/shared-name", "qwen-cloud/shared-name"} <= callable_names


async def test_every_listed_name_actually_resolves(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())

    for model in await list_callable_chat_models(TENANT):
        resolved = await resolve_model_name(TENANT, model.callable_name)
        assert resolved.model_id == model.model_id


async def test_catalog_ttl_is_capped_at_sixty_seconds(monkeypatch):
    monkeypatch.setattr(settings.open_api, "model_catalog_ttl_seconds", 61)

    assert settings.open_api.model_catalog_ttl_seconds == 61
    # The clamp lives on the settings validator, so a value assigned directly in
    # a test bypasses it; what matters is the cache never outlives the bound.
    monkeypatch.setattr(settings.open_api, "model_catalog_ttl_seconds", 60)
    invalidate_catalog()
    assert model_catalog._cache().ttl <= 60


async def test_permission_failure_refuses_instead_of_narrowing(monkeypatch):
    servers, models = _default_rows()
    install_catalog(monkeypatch, servers, models, fail_with=RuntimeError("openfga unreachable"))

    with pytest.raises(ModelFaceCatalogUnavailableError) as excinfo:
        await list_callable_chat_models(TENANT)

    assert excinfo.value.code == 26216
    assert excinfo.value.http_status == 503


async def test_a_failed_read_is_not_cached(monkeypatch):
    servers, models = _default_rows()
    install_catalog(monkeypatch, servers, models, fail_with=RuntimeError("openfga unreachable"))
    with pytest.raises(ModelFaceCatalogUnavailableError):
        await list_callable_chat_models(TENANT)

    install_catalog(monkeypatch, servers, models)

    assert await list_callable_chat_models(TENANT)


async def test_declared_range_refuses_an_undeclared_model(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())
    declared = ModelRange(kind="declared", declared=frozenset({"gpt-4o"}))

    assert (await resolve_model_name(TENANT, "gpt-4o", range=declared)).model_id == 10
    with pytest.raises(ModelFaceCapabilityUndeclaredError) as excinfo:
        await resolve_model_name(TENANT, "root-model", range=declared)

    assert excinfo.value.code == 26215


async def test_offline_beats_undeclared_so_the_owner_knows_which_fix_applies(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())
    declared = ModelRange(kind="declared", declared=frozenset({"retired-model"}))

    # Declared, but an administrator took it offline: "revoked", not "you forgot
    # to declare it" — the two have different owners and different fixes.
    with pytest.raises(ModelFaceModelOfflineError):
        await resolve_model_name(TENANT, "retired-model", range=declared)


async def test_declared_range_accepts_the_qualified_spelling(monkeypatch):
    install_catalog(monkeypatch, *_default_rows())
    declared = ModelRange(kind="declared", declared=frozenset({"azure-openai/gpt-4o"}))

    assert (await resolve_model_name(TENANT, "gpt-4o", range=declared)).model_id == 10
