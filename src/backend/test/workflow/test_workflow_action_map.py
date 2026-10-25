"""F056 T004 — per-resource-type action legality in ``_application_action_map``.

Why this file exists at all: ``share`` is not a legal action for the ``app``
resource type (``catalog_policy.ACTION_RESOURCE_SCOPES``), and asking for it
does **not** produce a 500. ``_prepare_action_target`` raises
``InvalidCatalogActionError``, which is a ``BaseErrorCode``, so FastAPI answers
HTTP 200 with business code 25001; the SPA's request wrapper rejects, the list
page catches and blanks itself, and the backend log shows no 5xx at all. On top
of that, both administrator short-circuits fire *before* the legality check, so
the bug is invisible to every account a developer normally tests with.

The bucket that has to be filtered is therefore not "the square's bucket" but
"every bucket, everywhere" — ``aenrich_apps_can_share`` alone asks for
``("share",)`` from four call sites that have nothing to do with the square.
"""

from __future__ import annotations

import pytest

from bisheng.api.services.workflow import WorkFlowService
from bisheng.database.models.flow import FlowType

HOSTED = FlowType.HOSTED_APP.value
WORKFLOW = FlowType.WORKFLOW.value
ASSISTANT = FlowType.ASSISTANT.value


@pytest.fixture()
def action_probe(monkeypatch):
    """Record what ``_application_action_map`` asks F048 for, per resource type.

    Returns a namespace whose ``asked`` maps resource_type -> requested actions.
    Everything is granted, so an empty result can only mean the request was
    never made.
    """
    from types import SimpleNamespace

    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", True)

    asked: dict[str, tuple[str, ...]] = {}

    async def _batch_check(user, *, resource_type, resource_ids, actions):
        asked[resource_type] = tuple(actions)
        return {str(resource_id): frozenset(actions) for resource_id in resource_ids}

    monkeypatch.setattr(
        "bisheng.api.services.workflow.batch_check_business_actions",
        _batch_check,
    )
    return SimpleNamespace(asked=asked)


def _rows() -> list[dict]:
    return [
        {"id": "wf-1", "flow_type": WORKFLOW},
        {"id": "asst-1", "flow_type": ASSISTANT},
        {"id": "app-1", "flow_type": HOSTED},
    ]


async def test_app_bucket_drops_share(action_probe):
    """``share`` never reaches the ``app`` bucket — asking for it is the 25001."""
    await WorkFlowService._application_action_map(
        object(),
        _rows(),
        ("use", "edit", "share"),
    )

    assert "share" not in action_probe.asked["app"]
    assert set(action_probe.asked["app"]) == {"use", "edit"}


async def test_other_buckets_unchanged(action_probe):
    """Workflows and assistants keep the exact request they had before F056."""
    await WorkFlowService._application_action_map(
        object(),
        _rows(),
        ("use", "edit", "share"),
    )

    assert action_probe.asked["workflow"] == ("use", "edit", "share")
    assert action_probe.asked["assistant"] == ("use", "edit", "share")


async def test_visible_never_filtered(action_probe):
    """``visible`` is exempt from the legality filter in every bucket.

    It is not a registered action code — ``_normalize_action`` rejects it and
    ``batch_check_visible`` answers it instead — so ``ACTION_RESOURCE_SCOPES``
    has no row for it. Filtering it out would leave the square asking nothing
    and rendering an empty page.
    """
    await WorkFlowService._application_action_map(
        object(),
        _rows(),
        ("visible", "edit"),
    )

    for resource_type in ("workflow", "assistant", "app"):
        assert "visible" in action_probe.asked[resource_type]


async def test_enrich_can_share_no_error(action_probe):
    """``aenrich_apps_can_share`` tolerates hosted rows: no 25001, ``can_share`` false.

    This is the path the workbench recommendation strip, the frequently-used
    list and ``/chat/online?sort_by=update_time`` all take — none of them is the
    square, and none of them is covered by an F056 acceptance criterion.
    """
    data = await WorkFlowService.aenrich_apps_can_share(object(), _rows())

    # The app bucket had nothing legal left to ask, so no check was issued.
    assert "app" not in action_probe.asked
    assert action_probe.asked["workflow"] == ("share",)
    by_id = {row["id"]: row for row in data}
    assert by_id["app-1"]["can_share"] is False
    assert by_id["wf-1"]["can_share"] is True


async def test_actions_by_type_override_is_opt_in(action_probe):
    """The per-bucket override changes only the bucket named; the rest keep ``actions``."""
    await WorkFlowService._application_action_map(
        object(),
        _rows(),
        ("visible", "edit", "share"),
        actions_by_type={"app": ("use", "edit")},
    )

    assert set(action_probe.asked["app"]) == {"use", "edit"}
    assert action_probe.asked["workflow"] == ("visible", "edit", "share")
    assert action_probe.asked["assistant"] == ("visible", "edit", "share")
