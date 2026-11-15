"""T710: original APP/Port semantics with one linear, pure directory compile."""

import importlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.reference_extractor import AppReferenceRequest, extract_app_reference_requests
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import (
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.knowledge.domain.repositories.unification_inventory_repository import KnowledgeRow
from bisheng.llm.application.model_name_resolution import ModelNameResolutionPort
from bisheng.llm.domain.repositories.model_name_resolution_repository import CatalogModel, CatalogServer, NameCatalog
from bisheng.llm.domain.services.model_catalog import TENANT_RANGE
from bisheng.resource_reference.application.contracts import TargetKey, TargetType


@pytest.fixture
def index_type():
    return importlib.import_module("bisheng.knowledge.application.unification_names").UnificationNameIndex


def catalog():
    return NameCatalog(
        101,
        (),
        (),
        (
            CatalogServer(1, 101, "own", "openai"),
            CatalogServer(2, 1, "root", "openai"),
            CatalogServer(3, 101, "invisible", "openai"),
        ),
        (
            CatalogModel(11, 101, 1, "alpha", "llm", True),
            CatalogModel(12, 101, 1, "same", "llm", True),
            CatalogModel(13, 101, 1, "root/slash", "llm", True),
            CatalogModel(14, 101, 1, "offline", "llm", False),
            CatalogModel(15, 101, 1, "embed", "embedding", True),
            CatalogModel(21, 1, 2, "same", "llm", True),
            CatalogModel(22, 1, 2, "slash", "llm", True),
            CatalogModel(23, 1, 2, "offline", "llm", False),
            CatalogModel(31, 101, 3, "hidden", "llm", True),
        ),
        frozenset({1, 2}),
        frozenset(),
    )


def knowledge(ident=7, name="Docs", kind=0, tenant=101):
    return KnowledgeRow(
        id=ident,
        tenant_id=tenant,
        type=kind,
        name=name,
        user_id=7,
        state=1,
        is_released=False,
        auth_type="private",
        is_shared=False,
        model="11",
        model_transition_json=None,
        model_config_revision=0,
        index_generation="g0",
        index_name=None,
        collection_name=None,
        processing_config_version=0,
        metadata_schema_revision=0,
        migration_origin=None,
        update_time=None,
    )


def request(name, slot="model"):
    return AppReferenceRequest(slot, TargetType.MODEL, requested_name=name)


@pytest.mark.parametrize(
    "name",
    [
        "alpha",
        "same",
        "root/same",
        "own/same",
        "root/slash",
        "own/root/slash",
        "offline",
        "own/offline",
        "missing",
        "hidden",
        "invisible/hidden",
        "embed",
    ],
)
def test_model_results_and_precise_failures_match_original_port(index_type, name):
    original = catalog()
    index = index_type(original, ())
    try:
        expected = ModelNameResolutionPort._resolve(original, name, TENANT_RANGE)
    except (ModelFaceModelAmbiguousError, ModelFaceModelNotFoundError, ModelFaceModelOfflineError) as error:
        with pytest.raises(type(error)) as actual:
            index.resolve((request(name),))
        assert actual.value.kwargs == error.kwargs
    else:
        assert index.resolve((request(name),)) == {"model": TargetKey("model", expected.model_id)}


def test_offline_bare_does_not_shadow_online_qualified_and_visibility_is_consumed_without_expansion(index_type):
    original = catalog()
    original = replace(
        original, models=tuple(replace(row, online=False) if row.id == 13 else row for row in original.models)
    )
    assert ModelNameResolutionPort._resolve(original, "root/slash", TENANT_RANGE).model_id == 22
    assert index_type(original, ()).resolve((request("root/slash"),))["model"] == TargetKey("model", 22)
    restricted = index_type(replace(original, visible_server_ids=frozenset({1})), ())
    with pytest.raises(ModelFaceModelNotFoundError):
        restricted.resolve((request("root/same"),))
    with pytest.raises(ModelFaceModelNotFoundError):
        restricted.resolve((request("hidden"),))


def test_original_extractor_explicit_id_is_kept_for_physical_preflight_without_name_fallback(index_type):
    declaration = CapabilityDeclaration.model_validate(
        {
            "models": [{"name": "alpha"}],
            "knowledge_bases": [
                {"id": "00999", "name": "Docs"},
                {"id": "uuid-old", "name": " Docs "},
            ],
        }
    )
    before = declaration.model_dump(mode="json")
    requests = extract_app_reference_requests(declaration)
    resolved = index_type(catalog(), (knowledge(),)).resolve(requests)
    assert resolved == {
        item.slot_key: TargetKey("model", 11)
        if item.target_type == TargetType.MODEL
        else TargetKey("knowledge_space", item.target_id or "7")
        for item in requests
    }
    assert TargetKey("knowledge_space", 999) in resolved.values()
    assert declaration.model_dump(mode="json") == before
    # Even an internal request carrying both legacy fields cannot fall back
    # from its explicit ID to the known name.
    direct = AppReferenceRequest("explicit", TargetType.KNOWLEDGE_SPACE, requested_name="Docs", target_id="999")
    assert index_type(catalog(), (knowledge(),)).resolve((direct,)) == {"explicit": TargetKey("knowledge_space", 999)}


@pytest.mark.parametrize(
    "name,reason",
    [
        ("duplicate", "app_knowledge_name_ambiguous"),
        ("qa", "app_knowledge_unavailable"),
        ("retired", "app_knowledge_unavailable"),
        ("docs", "app_knowledge_unavailable"),
        (" Docs", "app_knowledge_unavailable"),
        ("unknown", "app_knowledge_unavailable"),
    ],
)
def test_knowledge_name_matching_uses_only_exact_owned_normal_and_space_rows(index_type, name, reason):
    rows = (
        knowledge(),
        knowledge(8, "duplicate", 0),
        knowledge(9, "duplicate", 3),
        knowledge(10, "qa", 1),
        knowledge(11, "retired", 2),
    )
    with pytest.raises(ResourceReferenceInvalidError) as error:
        index_type(catalog(), rows).resolve(
            (AppReferenceRequest("kn", TargetType.KNOWLEDGE_SPACE, requested_name=name),)
        )
    assert error.value.kwargs["reason"] == reason


@pytest.mark.parametrize(
    "broken",
    [
        "catalog_type",
        "catalog_tenant",
        "duplicate_server",
        "duplicate_model",
        "missing_provider",
        "provider_tenant",
        "unknown_visible",
        "duplicate_knowledge",
        "knowledge_tenant",
        "knowledge_container",
    ],
)
def test_malformed_directories_do_not_compile_into_partial_or_broader_candidates(index_type, broken):
    original, rows = catalog(), (knowledge(),)
    if broken == "catalog_type":
        original = {"tenant_id": 101}
    elif broken == "catalog_tenant":
        original = replace(original, tenant_id=True)
    elif broken == "duplicate_server":
        original = replace(original, servers=(*original.servers, original.servers[0]))
    elif broken == "duplicate_model":
        original = replace(original, models=(*original.models, original.models[0]))
    elif broken == "missing_provider":
        original = replace(original, models=(replace(original.models[0], server_id=999),))
    elif broken == "provider_tenant":
        original = replace(original, models=(replace(original.models[0], tenant_id=202),))
    elif broken == "unknown_visible":
        original = replace(original, visible_server_ids=frozenset({1, 999}))
    elif broken == "duplicate_knowledge":
        rows = (*rows, rows[0])
    elif broken == "knowledge_tenant":
        rows = (knowledge(tenant=202),)
    else:
        rows = list(rows)
    with pytest.raises(ResourceReferenceInvalidError):
        index_type(original, rows)


@pytest.mark.parametrize(
    "requests",
    [
        [],
        (object(),),
        (request(""),),
        (request("nul\x00"),),
        (request("alpha", slot=""),),
        (AppReferenceRequest("bad", TargetType.MODEL, target_id="11"),),
        (AppReferenceRequest("bad", TargetType.KNOWLEDGE_FILE, target_id="7"),),
        (AppReferenceRequest("bad", TargetType.KNOWLEDGE_SPACE, target_id=True),),
        (AppReferenceRequest("bad", TargetType.KNOWLEDGE_SPACE, target_id="0", requested_name="Docs"),),
        (AppReferenceRequest("bad", TargetType.KNOWLEDGE_SPACE),),
        (request("alpha", "same"), request("root/same", "same")),
    ],
)
def test_invalid_requests_and_conflicting_duplicate_slots_fail_without_silent_omission(index_type, requests):
    index = index_type(catalog(), (knowledge(),))
    with pytest.raises(ResourceReferenceInvalidError):
        index.resolve(requests)


def test_equal_repeated_slots_and_empty_set_are_deterministic_without_returned_map_aliasing(index_type):
    index = index_type(catalog(), ())
    assert index.resolve(()) == {}
    first = index.resolve((request("alpha"), request("alpha")))
    first["model"] = TargetKey("model", 999)
    assert index.resolve((request("alpha"),)) == {"model": TargetKey("model", 11)}


def test_distinct_slots_compile_once_and_do_not_multiply_model_or_knowledge_directory_reads(index_type):
    total, slots = 500, 300
    original = NameCatalog(
        101,
        (),
        (),
        (CatalogServer(1, 101, "own", "openai"),),
        tuple(CatalogModel(i + 1, 101, 1, f"model-{i}", "llm", True) for i in range(total)),
        frozenset({1}),
        frozenset(),
    )
    rows = tuple(knowledge(i + 1, f"knowledge-{i}", 3) for i in range(total))
    requests = tuple(request(f"model-{i}", f"model:{i}") for i in range(slots)) + tuple(
        AppReferenceRequest(f"knowledge:{i}", TargetType.KNOWLEDGE_SPACE, requested_name=f"knowledge-{i}")
        for i in range(slots)
    )
    counts = {"model": 0, "server": 0, "knowledge": 0}

    def observed(cls, label):
        actual = cls.__getattribute__

        def get(self, name):
            if not name.startswith("_"):
                counts[label] += 1
            return actual(self, name)

        return get

    with (
        patch.object(CatalogModel, "__getattribute__", observed(CatalogModel, "model")),
        patch.object(CatalogServer, "__getattribute__", observed(CatalogServer, "server")),
        patch.object(KnowledgeRow, "__getattribute__", observed(KnowledgeRow, "knowledge")),
    ):
        for i in range(slots):
            ModelNameResolutionPort._resolve(original, f"model-{i}", TENANT_RANGE)
        baseline = dict(counts)
        counts.update(model=0, server=0, knowledge=0)
        index = index_type(original, rows)
        compiled = dict(counts)
        actual = index.resolve(requests)
        index.resolve(tuple(replace(item, slot_key="next:" + item.slot_key) for item in requests))
        lookup = {name: counts[name] - compiled[name] for name in counts}
    print(
        {
            "models": total,
            "knowledge": total,
            "different_model_names": slots,
            "slots": len(requests),
            "original_port_reads": baseline,
            "compiled_reads": compiled,
            "two_lookup_reads": lookup,
        }
    )
    assert baseline["model"] >= total * slots
    assert sum(compiled.values()) <= 20 * (2 * total + 1)
    assert sum(lookup.values()) <= 4 * len(requests)
    assert len(actual) == len(requests)
    assert actual["model:299"] == TargetKey("model", 300)
    assert actual["knowledge:299"] == TargetKey("knowledge_space", 300)
