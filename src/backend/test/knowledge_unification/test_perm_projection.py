"""F118 permission projection/model shape. 覆盖 AC: AC-30, AC-31, AC-59, AC-79, AC-80, AC-81, AC-83."""

from dataclasses import replace

import pytest

from bisheng.core.openfga.authorization_model_f048 import (
    DEFAULT_ACTION_CODES,
    build_authorization_model_f048,
    get_authorization_model_f048,
)
from bisheng.permission.domain.services.catalog_policy import ACTION_RESOURCE_SCOPES, REGISTERED_ACTION_CODES
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from test.knowledge_unification.test_perm_source_snapshot import scoped


def test_current_openfga_and_catalog_retire_use_together():
    assert set(DEFAULT_ACTION_CODES) == set(REGISTERED_ACTION_CODES)
    for definition in get_authorization_model_f048()["type_definitions"]:
        assert not {"use", "can_use", "system_can_use", "ordinary_can_use"} & set(definition.get("relations", {}))
    with pytest.raises(ValueError, match="retired"):
        build_authorization_model_f048(("download", "use"))
    assert ACTION_RESOURCE_SCOPES["rename"] == {"folder", "knowledge_file"}
    assert not {"folder", "knowledge_file"} & ACTION_RESOURCE_SCOPES["edit"]


def test_child_visibility_inheritance_remains_compositional():
    definitions = {item["type"]: item for item in get_authorization_model_f048()["type_definitions"]}
    child = definitions["knowledge_file"]["relations"]
    assert child["inherited_visible"]["intersection"]["child"] == [
        {"tupleToUserset": {"tupleset": {"relation": "parent"}, "computedUserset": {"relation": "visible"}}},
        {"computedUserset": {"relation": "inherit_mode"}},
    ]
    assert "visible" in child and "can_download" in child and "can_rename" in child


def test_pure_visible_projection_keeps_shared_sources_until_last_revoke():
    service = GrantSourceService()
    compiler = VisibilityProjectionCompiler()
    first = service.canonicalize_source(source_id=1, subject_type="user", subject_id="42", source_type="DIRECT")
    second = service.canonicalize_source(
        source_id=2, subject_type="user", subject_id="42", source_type="OTHER", source_ref="business"
    )
    grant = GrantSnapshot("g1", 101, "tool", "t1", scoped(), True, (first, second))
    initial = compiler.compile(tenant_id=101, grants=(grant,), existing_sources=())
    assert len(initial.active_sources) == 2
    assert len(initial.deltas) == 1 and initial.deltas[0].relation == "visible"
    remaining = service.remove_source(grant, source_id=1).grant
    partial = compiler.compile(tenant_id=101, grants=(remaining,), existing_sources=initial.active_sources)
    assert partial.deltas == () and len(partial.active_sources) == 1
    ended = service.remove_source(remaining, source_id=2).grant
    final = compiler.compile(tenant_id=101, grants=(ended,), existing_sources=partial.active_sources)
    assert len(final.deltas) == 1 and final.deltas[0].action == "DELETE"
    assert final.deltas[0].relation == "visible"


def test_invalid_unmarked_empty_grant_cannot_compile_visible_contribution():
    source = GrantSourceService().canonicalize_source(
        source_id=1, subject_type="user", subject_id="42", source_type="DIRECT"
    )
    grant = GrantSnapshot("g1", 101, "tool", "t1", GrantModelSnapshot("empty", True, (), 1), True, (source,))
    with pytest.raises(ValueError, match="model"):
        VisibilityProjectionCompiler().compile(tenant_id=101, grants=(grant,), existing_sources=())
    valid = replace(grant, model=scoped(active=False))
    assert VisibilityProjectionCompiler().compile(tenant_id=101, grants=(valid,), existing_sources=()).active_sources
