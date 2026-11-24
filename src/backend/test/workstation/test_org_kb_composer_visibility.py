"""F005 revision: configured knowledge bases are all preselected; ``show_in_composer`` decides the tag.

Covers the read-time upgrade of configs saved before the revision (design decision 9),
the save round trip, and that the child-tenant projection and the visible-permission
filter keep the new field.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from bisheng.api.v1.schemas import OrgKbConfig, WorkstationConfig
from bisheng.workstation.domain.services import workstation_service as ws_module
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _parse(payload: dict) -> WorkstationConfig:
    # `tools: []` keeps parse_config off the GptsToolsDao seeding path (no DB).
    return WorkStationService.parse_config(SimpleNamespace(value=json.dumps({"tools": [], **payload})))


def _kbs(config: WorkstationConfig) -> list[tuple[int, bool]]:
    return [(kb.id, kb.show_in_composer) for kb in config.orgKbs]


def test_a_legacy_config_keeps_only_default_checked_kbs_and_shows_them():
    config = _parse(
        {
            "orgKbs": [
                {"id": 1, "name": "checked", "default_checked": True, "sort_order": 0},
                {"id": 2, "name": "unchecked", "default_checked": False, "sort_order": 1},
                {"id": 3, "name": "no flag", "sort_order": 2},
            ]
        }
    )

    assert _kbs(config) == [(1, True)]


def test_a_new_config_reads_as_saved():
    config = _parse(
        {
            "orgKbs": [
                {"id": 1, "name": "shown", "show_in_composer": True},
                {"id": 2, "name": "hidden", "show_in_composer": False},
            ]
        }
    )

    assert _kbs(config) == [(1, True), (2, False)]


def test_kbs_added_after_the_upgrade_are_kept_without_default_checked():
    # AC-28: a saved item never carries default_checked, so the legacy rule must not drop it.
    config = _parse({"orgKbs": [{"id": 5, "name": "new", "show_in_composer": False}]})

    assert _kbs(config) == [(5, False)]


def test_empty_and_missing_lists_read_as_empty():
    assert _parse({"orgKbs": []}).orgKbs == []
    assert _parse({"orgKbs": None}).orgKbs == []
    assert _parse({}).orgKbs == []


def test_a_saved_config_round_trips_the_field():
    saved = WorkstationConfig(
        orgKbs=[
            OrgKbConfig(id=1, name="shown"),
            OrgKbConfig(id=2, name="hidden", show_in_composer=False),
        ]
    ).model_dump(mode="json")

    assert all("show_in_composer" in item for item in saved["orgKbs"])
    assert _kbs(_parse(saved)) == [(1, True), (2, False)]


def test_the_old_default_checked_field_is_not_emitted():
    item = OrgKbConfig.model_validate({"id": 1, "name": "kb", "default_checked": True, "show_in_composer": False})

    assert "default_checked" not in item.model_dump()


async def test_the_child_tenant_projection_keeps_the_field(monkeypatch):
    async def rows_for(ids):
        return [SimpleNamespace(id=i) for i in ids]

    monkeypatch.setattr(ws_module.KnowledgeDao, "aget_list_by_ids", rows_for)
    config = WorkstationConfig(orgKbs=[OrgKbConfig(id=7, name="hidden", show_in_composer=False)])

    kept = await WorkStationService._afilter_org_kbs_for_current_tenant(config.orgKbs)

    assert [(item["id"], item["show_in_composer"]) for item in kept] == [(7, False)]


async def test_the_visible_filter_keeps_the_field(monkeypatch):
    async def fake_batch(user, *, resource_type, resource_ids, actions):
        return {str(i): frozenset({"visible"}) for i in resource_ids}

    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions",
        fake_batch,
    )
    items = [{"id": 8, "name": "hidden", "show_in_composer": False}]

    kept = await WorkStationService.afilter_org_kbs_by_visible_permission(items, SimpleNamespace(user_id=1))

    assert kept == items
