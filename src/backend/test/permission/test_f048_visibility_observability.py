"""Observability contract for flattened visibility and list strategies."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
)
from bisheng.permission.domain.services.permission_action_service import (
    F048PermissionService,
    PermissionActor,
)
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompiler,
    VisibilityProjectionReconciler,
)


class _ReadyCatalog:
    async def ensure_runtime_ready(self):
        return None

    async def is_action_effective(self, resource_type, action):
        return True


class _Fence:
    async def ensure_readable(self, target):
        return None


class _Marker:
    async def consistency_for(self, **kwargs):
        return "HIGHER_CONSISTENCY"


class _Policy:
    async def allows(self, resource_type, action, max_results):
        return True


@dataclass
class _FGA:
    objects: tuple[str, ...] = ()
    error: Exception | None = None

    async def stream_list_objects(self, **kwargs):
        if self.error:
            raise self.error
        return self.objects


def _service(fga: _FGA) -> F048PermissionService:
    return F048PermissionService(
        catalog=_ReadyCatalog(),
        scope_fence=_Fence(),
        marker=_Marker(),
        fga=fga,
        list_policy=_Policy(),
    )


async def test_visible_list_metric_reports_complete_stream_and_capacity_alert(monkeypatch):
    metrics = []
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.emit_metric",
        lambda domain, **fields: metrics.append((domain, fields)),
    )

    result = await _service(
        _FGA(tuple(f"knowledge_space:{index}" for index in range(8)))
    ).list_visible_objects(
        PermissionActor(user_id=7, current_tenant_id=3),
        resource_type="knowledge_space",
        max_results=10,
    )

    assert len(result.object_ids) == 8
    domain, fields = metrics[-1]
    assert domain == "permission_visible_list"
    assert fields["strategy"] == "visible_ids_first"
    assert fields["visible_count"] == fields["scanned_count"] == 8
    assert fields["stream_completed"] is True
    assert fields["capacity"] == 10
    assert fields["fga_elapsed_ms"] >= 0
    assert fields["total_elapsed_ms"] >= fields["fga_elapsed_ms"]
    assert fields["alert"] == "capacity_80_percent"
    assert not {"user_name", "resource_name", "token", "config"}.intersection(fields)


async def test_visible_list_metric_marks_incomplete_stream(monkeypatch):
    metrics = []
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.emit_metric",
        lambda domain, **fields: metrics.append((domain, fields)),
    )

    with pytest.raises(PermissionEnumerationIncompleteError):
        await _service(_FGA(error=RuntimeError("transport closed"))).list_visible_objects(
            PermissionActor(user_id=7, current_tenant_id=3),
            resource_type="knowledge_space",
            max_results=5000,
        )

    assert metrics[-1][1]["stream_completed"] is False
    assert metrics[-1][1]["alert"] == "stream_incomplete"


def _grant() -> GrantSnapshot:
    return GrantSnapshot(
        grant_id="11",
        tenant_id=3,
        resource_type="knowledge_space",
        resource_id="42",
        model=GrantModelSnapshot(model_key="viewer", active=False, action_codes=()),
        active=True,
        sources=(
            GrantSourceRecord(
                source_id=19,
                subject_type="user",
                subject_id="7",
                userset_relation=None,
                include_children=False,
                source_type="DIRECT",
                source_ref="grant:11",
                source_locator="grant:11:assignee:19",
                source_fingerprint="a" * 64,
                projected_subject="user:7",
                protected=False,
                active=True,
                version=2,
            ),
        ),
    )


def test_projection_metrics_report_sources_checksums_and_orphan_alert(monkeypatch):
    metrics = []
    monkeypatch.setattr(
        "bisheng.permission.domain.services.visibility_projection_service.emit_metric",
        lambda domain, **fields: metrics.append((domain, fields)),
    )
    compiled = VisibilityProjectionCompiler().compile(
        tenant_id=3,
        grants=(_grant(),),
        existing_sources=(),
    )
    plan = VisibilityProjectionReconciler().plan(
        canonical_sources=compiled.active_sources,
        persisted_sources=compiled.active_sources,
        live_tuples=frozenset(
            {
                ("user:7", "visible", "knowledge_space:42"),
                ("user:9", "visible", "knowledge_space:42"),
            }
        ),
    )

    assert plan.deltas[0].action == "DELETE"
    project = next(fields for domain, fields in metrics if fields["operation"] == "project")
    reconcile = next(fields for domain, fields in metrics if fields["operation"] == "reconcile")
    assert project["source_count"] == project["unique_tuple_count"] == 1
    assert len(project["source_checksum"]) == len(project["aggregate_checksum"]) == 64
    assert reconcile["orphan_count"] == 1
    assert reconcile["alert"] == "orphan_visible_tuple"
    assert not {"user_name", "resource_name", "token", "config"}.intersection(reconcile)
