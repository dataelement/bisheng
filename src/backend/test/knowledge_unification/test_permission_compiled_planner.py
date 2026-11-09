"""T1020: compiled pure plans retain acquired native C4/C5 facts and old bytes."""

import json
from dataclasses import FrozenInstanceError, fields, replace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from test.knowledge_unification.test_permission_namespace_catalog import build
from test.knowledge_unification.test_permission_namespace_resource import (
    mapped,
    original_resource,
    target,
)
from test.knowledge_unification.test_permission_namespace_resource import (
    original as original,
)
from test.knowledge_unification.test_permission_namespace_resource import (
    storage as storage,
)


def payload(value):
    return json.dumps(
        plans._json(plans._resource_payload(value)),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


@pytest.mark.parametrize("mapped_catalog", [False, True])
@pytest.mark.parametrize("kind", ["root", "qa", "space", "folder", "knowledge_file"])
async def test_native_compiled_point_and_repeated_batches_equal_original_complete_plans(original, mapped_catalog, kind):
    engine, before_catalog, before = original
    if kind == "space":
        before = original_resource(before_catalog, resource_type="knowledge_space", model_key="owner")
    elif kind in {"folder", "knowledge_file"}:
        before = original_resource(before_catalog, resource_type=kind)
        before = replace(before, mode=target(before, parent_type="knowledge_library", parent_id="40"))
    catalog = mapped(before_catalog) if mapped_catalog else build(before_catalog)
    mode = before.mode if mapped_catalog else None
    if mapped_catalog and kind == "root":
        mode = target(before, resource_type="knowledge_space")
    elif mapped_catalog and kind in {"folder", "knowledge_file"}:
        mode = target(before, parent_type="knowledge_space")
    expected = plans.build_resource_retirement_plan(catalog_plan=catalog, before=before, namespace_target=mode)
    original_bytes = payload(expected)
    sql = []

    def capture(_c, _cu, statement, _p, _ctx, _many):
        sql.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        compiler = plans.ResourceRetirementPlanner(catalog_plan=catalog)
        actual = compiler.build(before=before, namespace_target=mode)
        assert actual == expected and payload(actual) == original_bytes
        for _ in range(3):
            result = tuple(
                compiler.build_many(before=iter((before,)), target_modes=None if mode is None else iter((mode,)))
            )
            assert result == (expected,) and payload(result[0]) == original_bytes
        assert verify.verify_resource_retirement(plan=actual, actual=actual.after).complete
        assert actual.after.assignees is before.assignees
        for old, new in zip(before.visible_sources, actual.after.visible_sources, strict=True):
            assert old.id == new.id
            assert old.source.source_version == new.source.source_version
            assert old.source.operation_id == new.source.operation_id
            assert old.source.migration_item_id == new.source.migration_item_id
            assert old.source.contribution_fingerprint == new.source.contribution_fingerprint
        if not mapped_catalog and kind == "root":
            assert actual.checksum == "918cb725064907eb35182d2ac84d0d7fc2477b58efa33a55d1f7f0185498126a"
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not sql


@pytest.mark.parametrize("bad", ["none", "checksum", "matrix", "mapping", "models", "scope"])
async def test_bad_catalog_is_rebuilt_and_rejected_before_even_empty_batches(original, bad):
    _, before_catalog, _ = original
    catalog = mapped(before_catalog)
    changed = {
        "none": None,
        "checksum": replace(catalog, checksum="0" * 64),
        "matrix": replace(catalog, namespace_applicability_changes=catalog.namespace_applicability_changes[:-1]),
        "mapping": replace(catalog, namespace_type_mappings=()),
        "models": replace(catalog, after_models=catalog.after_models[::-1]),
        "scope": replace(
            catalog,
            after_actions=(
                replace(catalog.after_actions[0], resource_types=set(catalog.after_actions[0].resource_types)),
                *catalog.after_actions[1:],
            ),
        )
        if bad == "scope"
        else catalog,
    }[bad]
    with pytest.raises((PermissionMigrationBlockedError, TypeError)):
        compiler = plans.ResourceRetirementPlanner(catalog_plan=changed)
        tuple(compiler.build_many(before=(), target_modes=()))


async def test_compiled_value_and_every_index_are_ordinary_immutable_values(original):
    _, before_catalog, before = original
    compiler = plans.ResourceRetirementPlanner(catalog_plan=mapped(before_catalog))
    assert not hasattr(compiler, "__dict__")
    for item in fields(compiler):
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(compiler, item.name, None)
    context = compiler._context
    for name in ("before_models", "after_models", "before_scopes", "after_scopes"):
        index = getattr(context, name)
        key = next(iter(index))
        with pytest.raises(TypeError):
            index[key] = None
        with pytest.raises(TypeError):
            del index[key]
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(context, name, {})
    mode = target(before, resource_type="knowledge_space")
    assert compiler.build(before=before, namespace_target=mode).after.mode == mode


@pytest.mark.parametrize("mapped_catalog", [False, True])
@pytest.mark.parametrize("bad", ["none", "dict", "list", "mutable_field", "changed_id", "subclass"])
async def test_point_and_batch_keep_original_target_errors(original, mapped_catalog, bad):
    _, before_catalog, before = original
    catalog = mapped(before_catalog) if mapped_catalog else build(before_catalog)

    class DerivedMode(plans.ResourceModeBaseline):
        pass

    mode = {
        "none": None,
        "dict": {"resource_type": "knowledge_space"},
        "list": [before.mode],
        "mutable_field": target(before, resource_id=["40"]),
        "changed_id": target(before, id=True),
        "subclass": DerivedMode(**{item.name: getattr(before.mode, item.name) for item in fields(before.mode)}),
    }[bad]
    compiler = plans.ResourceRetirementPlanner(catalog_plan=catalog)
    if not mapped_catalog and bad == "none":
        assert compiler.build(before=before) == plans.build_resource_retirement_plan(
            catalog_plan=catalog, before=before
        )
        return
    with pytest.raises(PermissionMigrationBlockedError) as old:
        plans.build_resource_retirement_plan(catalog_plan=catalog, before=before, namespace_target=mode)
    with pytest.raises(PermissionMigrationBlockedError) as current:
        compiler.build(before=before, namespace_target=mode)
    assert current.value.kwargs == old.value.kwargs
    with pytest.raises(PermissionMigrationBlockedError) as batch:
        tuple(compiler.build_many(before=(before,), target_modes=None if mode is None else (mode,)))
    assert batch.value.kwargs == old.value.kwargs


@pytest.mark.parametrize("bad", ["short", "long", "missing", "wrong_late"])
async def test_exact_pairing_does_not_report_a_partial_batch_as_complete(original, bad):
    _, before_catalog, before = original
    compiler = plans.ResourceRetirementPlanner(catalog_plan=mapped(before_catalog))
    mode = target(before, resource_type="knowledge_space")
    targets = {"short": (mode,), "long": (mode, mode, mode), "missing": None, "wrong_late": (mode, {})}[bad]
    stream = compiler.build_many(before=iter((before, before)), target_modes=None if targets is None else iter(targets))
    with pytest.raises(PermissionMigrationBlockedError):
        if bad != "missing":
            assert next(stream) == compiler.build(before=before, namespace_target=mode)
        tuple(stream)
    assert tuple(compiler.build_many(before=(), target_modes=())) == ()
    assert compiler.build(before=before, namespace_target=mode).after.mode == mode


@pytest.mark.parametrize("bad", ["source", "mode", "retired"])
async def test_compilation_never_weakens_original_canonical_evidence_checks(original, bad):
    _, before_catalog, before = original
    compiler = plans.ResourceRetirementPlanner(catalog_plan=mapped(before_catalog))
    if bad == "source":
        before = replace(
            before, assignees=(replace(before.assignees[0], source_fingerprint="0" * 64), *before.assignees[1:])
        )
    elif bad == "mode":
        before = replace(before, mode=replace(before.mode, resource_id=["40"]))
    else:
        rows = list(before.visible_sources)
        rows[-1] = replace(rows[-1], source=rows[-1].source.model_copy(update={"source_fingerprint": "0" * 64}))
        before = replace(before, visible_sources=tuple(rows))
    with pytest.raises(PermissionMigrationBlockedError):
        compiler.build(before=before, namespace_target=target(before, resource_type="knowledge_space"))
