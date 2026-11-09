"""T995: one Catalog rebuild and actual Grant+Source work for namespace batches."""

from dataclasses import asdict, replace

import pytest

from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog
from test.knowledge_unification.test_permission_namespace_catalog import MAPPING, build


def resource_rows(catalog, count):
    models = {row.model_key: row for row in catalog.models}
    scopes = {row.code: row.resource_types for row in catalog.actions}
    for index in range(count):
        ident = str(10000 + index)
        grants, assignees, buckets = [], [], {}
        for number in range(20):
            grant_id = index * 20 + number + 1
            grants.append(
                plans.PermissionGrantBaseline(grant_id, 101, "knowledge_library", ident, f"custom-{number}", "ACTIVE")
            )
            group = []
            for offset in range(5):
                source_id = (grant_id - 1) * 5 + offset + 1
                record = GrantSourceService().canonicalize_source(
                    source_id=source_id,
                    subject_type="user",
                    subject_id="7",
                    source_type="OTHER",
                    source_ref=f"original:{source_id}",
                )
                facts = asdict(record)
                del facts["active"]
                source = plans.PermissionAssigneeBaseline(
                    id=facts.pop("source_id"),
                    grant_id=grant_id,
                    tenant_id=101,
                    state="INACTIVE" if offset == 4 else "ACTIVE",
                    **facts,
                )
                assignees.append(source)
                group.append(source.to_source_record())
            buckets[grant_id] = tuple(group)
        before = plans.PermissionResourceBaseline(
            101,
            "knowledge_library",
            ident,
            plans.ResourceModeBaseline(index + 1, 101, "knowledge_library", ident, "CUSTOM"),
            tuple(grants),
            tuple(assignees),
            (),
        )
        snapshots = plans._grants(before, models, scopes, buckets)
        visible = (
            VisibilityProjectionCompiler().compile(tenant_id=101, grants=snapshots, existing_sources=()).active_sources
        )
        retired = tuple(
            VisibilityProjectionCompiler._compile_source(101, grant, grant.sources[-1]).model_copy(
                update={"state": "RETIRED"}
            )
            for grant in snapshots
        )
        before = replace(
            before,
            visible_sources=tuple(
                plans.PermissionVisibleSourceBaseline(index * 100 + n, row)
                for n, row in enumerate((*visible, *retired), 1)
            ),
        )
        yield before


def measure(monkeypatch, action):
    counts = {"catalog": 0, "derive": 0, "model_candidates": 0, "source_reads": 0, "compiled_sources": 0}
    catalog, derive = plans.build_catalog_retirement_plan, plans.derive_permission_models
    init = plans.ModelApplicabilityChange.__init__
    getattribute = plans.PermissionAssigneeBaseline.__getattribute__
    compile_source = VisibilityProjectionCompiler._compile_source

    def catalog_once(*args, **kwargs):
        counts["catalog"] += 1
        return catalog(*args, **kwargs)

    def derive_once(*args, **kwargs):
        counts["derive"] += 1
        return derive(*args, **kwargs)

    def candidate(self, *args, **kwargs):
        counts["model_candidates"] += 1
        init(self, *args, **kwargs)

    def read(self, name):
        if name == "grant_id":
            counts["source_reads"] += 1
        return getattribute(self, name)

    def compile(*args, **kwargs):
        counts["compiled_sources"] += 1
        return compile_source(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(plans, "build_catalog_retirement_plan", catalog_once)
        patch.setattr(plans, "derive_permission_models", derive_once)
        patch.setattr(plans.ModelApplicabilityChange, "__init__", candidate)
        patch.setattr(plans.PermissionAssigneeBaseline, "__getattribute__", read)
        patch.setattr(VisibilityProjectionCompiler, "_compile_source", staticmethod(compile))
        result = action()
    return result, counts


@pytest.mark.parametrize(("resource_count", "model_count"), [(401, 27), (1001, 27), (3, 401), (3, 1001)])
def test_explicit_resource_batches_and_verifier_use_one_context_and_linear_real_sources(
    monkeypatch, resource_count, model_count
):
    baseline = legacy_catalog(
        customs=tuple(
            CustomModelSelection(f"custom-{i}", f"Custom {i}", ("download", "use")) for i in range(model_count - 4)
        )
    )
    catalog = build(baseline, namespace_type_mappings=MAPPING)
    before = tuple(resource_rows(baseline, resource_count))
    modes = tuple(replace(row.mode, resource_type="knowledge_space") for row in before)
    result, built = measure(
        monkeypatch,
        lambda: tuple(
            plans.build_resource_retirement_plans(
                catalog_plan=catalog,
                before=iter(before),
                target_modes=iter(modes),
            )
        ),
    )
    reports, checked = measure(
        monkeypatch,
        lambda: tuple(
            verify.verify_resource_retirements(
                catalog_plan=catalog,
                plans=iter(result),
                actual=(row.after for row in result),
            )
        ),
    )
    assert len(result) == len(reports) == resource_count and all(row.complete for row in reports)
    for values in (built, checked):
        assert values["catalog"] == values["derive"] == 1
        assert values["model_candidates"] == model_count
        assert values["source_reads"] <= 8 * resource_count * 100
        assert values["compiled_sources"] <= 4 * resource_count * 100
    print(
        {
            "resources": resource_count,
            "models": model_count,
            "grants": resource_count * 20,
            "sources": resource_count * 100,
            "build": built,
            "verify": checked,
        }
    )
