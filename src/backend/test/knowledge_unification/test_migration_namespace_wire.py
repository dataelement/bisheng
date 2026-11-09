"""T1024: exact namespace plan wire over actual native before/after facts.

覆盖 AC: AC-01, AC-02, AC-80, AC-89
The wire carries existing plans; it does not issue or execute a migration.
"""

import json
from dataclasses import asdict, replace
from itertools import islice
from math import ceil

import pytest
from sqlalchemy import event

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.application.unification_conversion_codec import decode_sql_conversion_page
from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_permission_namespace_resource as native

storage = native.storage
original = native.original
RUN = "namespace-wire"
WRITER = "f118-v1"
HASH = "a" * 64
NAMESPACE = {
    "namespace_catalog",
    "namespace_applicability",
    "namespace_target_mode",
    "namespace_after_grant",
    "namespace_after_assignee",
    "namespace_after_visible_source",
}
ADDITIONAL = {
    "mode_id",
    "catalog_plan_checksum",
    "target_mode_digest",
    "after_digest",
    "grant_count",
    "assignee_count",
    "visible_source_count",
}


def normalized(value):
    return json.loads(codec.canonical(value))


def header(catalog):
    return codec.record_from_values(
        "namespace_catalog",
        run_id=catalog.run_id,
        writer_contract_version=catalog.writer_contract_version,
        before_catalog_checksum=catalog.before.release.checksum,
        target_model_checksum=catalog.target_model_checksum,
        catalog_plan_checksum=catalog.checksum,
        action_checksum=catalog.action_checksum,
        model_checksum=catalog.model_checksum,
        from_resource_type="knowledge_library",
        to_resource_type="knowledge_space",
        model_count=len(catalog.after_models),
    )


def matrix(catalog):
    return tuple(
        codec.record_from_values(
            "namespace_applicability", catalog_plan_checksum=catalog.checksum, **normalized(asdict(change))
        )
        for change in catalog.namespace_applicability_changes
    )


def after_rows(plan):
    mode_id = plan.before.mode.id
    for name, values in (
        ("namespace_target_mode", (plan.namespace_target,)),
        ("namespace_after_grant", plan.after.grants),
        ("namespace_after_assignee", plan.after.assignees),
        ("namespace_after_visible_source", plan.after.visible_sources),
    ):
        for value in values:
            yield codec.record_from_values(name, mode_id=mode_id, **codec.record_from_row(value).data)


def summary(plan):
    return codec.record_from_values(
        "permission_plan",
        tenant_id=plan.before.tenant_id,
        resource_type=plan.before.resource_type,
        resource_id=plan.before.resource_id,
        target_resource_type=plan.namespace_target.resource_type,
        plan_checksum=plan.checksum,
        before_digest=plans._checksum(plan.before),
        after_grants_digest=plans._checksum(plan.after_grants),
        visibility_deltas_digest=plans._checksum(plan.visibility_deltas),
        expected_use_changes_digest=plans._checksum(plan.expected_use_changes),
        mode_id=plan.before.mode.id,
        catalog_plan_checksum=plan.catalog_plan.checksum,
        target_mode_digest=plans._checksum(plan.namespace_target),
        after_digest=plans._checksum(plan.after),
        grant_count=len(plan.after.grants),
        assignee_count=len(plan.after.assignees),
        visible_source_count=len(plan.after.visible_sources),
    )


def encode(records, **changes):
    args = {
        "run_id": RUN,
        "section": "permission_namespace",
        "kind": "plan",
        "scope": "tenant",
        "tenant_id": 101,
        "page_index": 0,
        "records": tuple(records),
    }
    return codec.encode_inventory_page(**(args | changes))


def decode(content, **changes):
    args = {
        "run_id": RUN,
        "section": "permission_namespace",
        "kind": "plan",
        "scope": "tenant",
        "tenant_id": 101,
        "page_index": 0,
    }
    return codec.decode_inventory_page(content, **(args | changes))


@pytest.fixture
def compiled(original):
    engine, before_catalog, before = original
    catalog = plans.build_catalog_retirement_plan(
        run_id=RUN,
        writer_contract_version=WRITER,
        before=before_catalog,
        target_model_checksum=HASH,
        namespace_type_mappings=(("knowledge_library", "knowledge_space"),),
    )
    plan = plans.ResourceRetirementPlanner(catalog_plan=catalog).build(
        before=before, namespace_target=replace(before.mode, resource_type="knowledge_space")
    )
    return engine, catalog, plan


async def test_original_native_permission_rows_keep_their_existing_typed_wire(compiled):
    before = compiled[2].before
    rows = (before.mode, *before.grants, *before.assignees, *before.visible_sources)
    records = tuple(codec.record_from_row(row) for row in rows)
    raw = encode(records, section="permission", kind="baseline")
    assert decode(raw, section="permission", kind="baseline").records == records


async def test_native_catalog_matrix_and_full_typed_after_preserve_original_ids_and_order(compiled):
    engine, catalog, plan = compiled
    queries = []

    def capture(_c, _cu, sql, _params, _ctx, _many):
        queries.append(sql)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        declaration = (header(catalog), *matrix(catalog))
        raw = encode(declaration, scope="global", tenant_id=None)
        assert decode(raw, scope="global", tenant_id=None).records == declaration
        records = tuple(after_rows(plan))
        assert decode(encode(records)).records == records
        assert [row.record_type for row in records] == (
            ["namespace_target_mode"]
            + ["namespace_after_grant"] * len(plan.after.grants)
            + ["namespace_after_assignee"] * len(plan.after.assignees)
            + ["namespace_after_visible_source"] * len(plan.after.visible_sources)
        )
        assert [row.data["id"] for row in records[2 : 2 + len(plan.after.assignees)]] == [
            row.id for row in plan.after.assignees
        ]
        assert {row.data["mode_id"] for row in records} == {plan.before.mode.id}
        source = next(row.data["source"] for row in records if row.record_type == "namespace_after_visible_source")
        assert source["source_version"] == 0 and source["operation_id"] == 19 and source["migration_item_id"] == 23
        assert not queries
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)


async def test_permission_summary_binds_whole_after_with_permission_hash_and_stays_sql_deferred(compiled):
    _, catalog, plan = compiled
    record = summary(plan)
    assert record.data["catalog_plan_checksum"] == catalog.checksum
    assert record.data["after_digest"] == plans._checksum(plan.after)
    assert record.data["after_grants_digest"] != plans._checksum(plan.after.grants)
    chinese = replace(plan.after.mode, resource_id="知识空间")
    assert plans._checksum(chinese) != codec.digest(chinese)
    raw = encode((record,), section="conversion")
    result = decode_sql_conversion_page(raw, run_id=RUN, writer_contract_version=WRITER, tenant_id=101, page_index=0)
    assert result.commands == () and result.deferred == (record,)


@pytest.mark.parametrize("field", sorted(ADDITIONAL))
async def test_old_hint_only_summary_cannot_omit_any_new_frozen_field(compiled, field):
    data = summary(compiled[2]).data
    del data[field]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values("permission_plan", **data)


@pytest.mark.parametrize("tag", sorted(NAMESPACE))
async def test_namespace_records_are_closed_and_cannot_reuse_other_section_or_kind(compiled, tag):
    _, catalog, plan = compiled
    candidates = (header(catalog), *matrix(catalog), *after_rows(plan))
    record = next(row for row in candidates if row.record_type == tag)
    global_row = tag in {"namespace_catalog", "namespace_applicability"}
    scope = {"scope": "global", "tenant_id": None} if global_row else {}
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(tag, **(record.data | {"private_payload": "forbidden"}))
    for changes in ({"section": "permission"}, {"kind": "baseline"}, {"kind": "conversion"}):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            encode((record,), **(scope | changes))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode((record,), **({} if global_row else {"scope": "global", "tenant_id": None}))


@pytest.mark.parametrize("tag", ["namespace_catalog", "namespace_applicability"])
@pytest.mark.parametrize(
    "pair",
    [
        ("knowledge_space", "knowledge_library"),
        ("folder", "knowledge_space"),
        ("knowledge_library", "folder"),
        ("", "knowledge_space"),
    ],
)
async def test_wire_mapping_is_the_unique_frozen_pair(compiled, tag, pair):
    _, catalog, _ = compiled
    record = header(catalog) if tag == "namespace_catalog" else matrix(catalog)[0]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(tag, **(record.data | {"from_resource_type": pair[0], "to_resource_type": pair[1]}))


@pytest.mark.parametrize("value", [True, 0, -1, "1", 1.0])
async def test_mode_id_is_positive_native_integer_and_target_id_must_match(compiled, value):
    record = next(after_rows(compiled[2]))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(record.record_type, **(record.data | {"mode_id": value}))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(record.record_type, **(record.data | {"mode_id": record.data["id"] + 1}))


async def test_nested_visible_tenant_cannot_borrow_a_page_even_after_canonical_reencoding(compiled):
    record = next(row for row in after_rows(compiled[2]) if row.record_type == "namespace_after_visible_source")
    source = record.data["source"] | {"tenant_id": 202}
    wrong = codec.record_from_values(record.record_type, **(record.data | {"source": source}))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode((wrong,))
    value = json.loads(encode((record,)))
    value["records"][1]["source"]["tenant_id"] = 202
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(codec.canonical(value))


async def test_action_order_is_wire_data_and_unknown_fields_or_old_tag_are_not_silently_coerced(compiled):
    record = matrix(compiled[1])[0]
    data = record.data | {"before_action_codes": ["rename", "download", "share"]}
    ordered = codec.record_from_values(record.record_type, **data)
    assert decode(encode((ordered,), scope="global", tenant_id=None), scope="global", tenant_id=None).records == (
        ordered,
    )
    reversed_row = codec.record_from_values(
        record.record_type, **(data | {"before_action_codes": list(reversed(data["before_action_codes"]))})
    )
    assert encode((ordered,), scope="global", tenant_id=None) != encode((reversed_row,), scope="global", tenant_id=None)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(
            record.record_type, **(data | {"before_action_codes": tuple(data["before_action_codes"])})
        )
    baseline = codec.record_from_row(compiled[2].after.mode)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode((baseline,))


async def test_catalog_run_and_permission_summary_location_are_not_hints(compiled):
    record = header(compiled[1])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode((record,), run_id="other-run", scope="global", tenant_id=None)
    declaration = summary(compiled[2])
    for changes in ({"section": "permission"}, {"section": "conversion", "kind": "baseline"}):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            encode((declaration,), **changes)


@pytest.mark.parametrize("count", [401, 10001])
async def test_typed_target_mode_pages_have_no_total_limit_and_retain_native_order(compiled, count):
    mode = compiled[2].namespace_target
    rows = (
        codec.record_from_values(
            "namespace_target_mode",
            mode_id=index,
            **codec.record_from_row(replace(mode, id=index, resource_id=str(index))).data,
        )
        for index in range(1, count + 1)
    )
    consumed, pages = 0, 0
    while batch := tuple(islice(rows, 199)):
        raw = encode(batch, page_index=pages)
        actual = decode(raw, page_index=pages).records
        assert actual == batch and len(actual) <= 199
        assert [row.data["mode_id"] for row in actual] == list(range(consumed + 1, consumed + len(batch) + 1))
        consumed += len(actual)
        pages += 1
    assert consumed == count and pages == ceil(count / 199)
