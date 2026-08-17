"""T028 — the ``app_publish_request`` scenario handler (AC-12 … AC-18 / AC-23 / AC-24).

The handler is the whole of what the approval engine knows about publishing:
who may approve, what the approval card says, and what happens on each terminal
decision. It is duck-typed — the engine calls methods by name, there is no ABC
— so every one of them is asserted here rather than being guaranteed by a type.

The four things most likely to go wrong, and why each has its own test:

* **``resolve_approvers`` is the handler's own job.** The gate calls it and does
  nothing else; a handler that forgets to delegate the generic sources to
  ``resolve_approvers_from_sources`` resolves nobody, and the symptom is
  identical to "the operator configured no approvers" (design 坑 9).
* **The applicant is filtered out at the handler's exit, not in the shared
  resolver.** Auto-skipping the applicant is *this* scenario's product rule;
  pushing it into the resolver would change channel subscription and
  knowledge-space joins, where the owner really should see their own request.
* **Self-approval has no channel back to the caller.** The gate takes a bare
  ``list[int]`` and ``ApprovalGateResult`` has four fixed fields, so the flag
  rides on the handler *instance* — which only works because a fresh handler is
  built per request. The concurrency test is what keeps that true.
* **``detail_snapshot`` is structured, and the client renders unknown keys
  verbatim.** Nested values in a snapshot the front end does not recognise come
  out as ``[object Object]`` in the generic two-column grid, so the three flat
  fallback keys are part of the contract, not decoration (design 坑 7).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .conftest import (
    DEPT_ADMIN_USER_ID,
    OWNER_USER_ID,
    ROOT_TENANT_ID,
    SERVICE_ACCOUNT_USER_ID,
    SUB_TENANT_ID,
    SUPER_ADMIN_USER_ID,
    TENANT_ADMIN_USER_ID,
)

pytestmark = pytest.mark.asyncio

SCENARIO_CODE = "app_publish_request"

_SOURCES = {"sources": [{"type": "department_admin"}, {"type": "tenant_admin"}]}


def _handler():
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

    return AppPublishScenarioHandler()


def _payload(**overrides):
    """A payload snapshot in the shape ``publish_approval_service`` writes."""
    payload = {
        "app_id": "app-1",
        "app_name": "报表工具",
        "app_slug": "report-tool",
        "version_id": "ver-1",
        "version_no": 1,
        "deployment_id": "dep-1",
        "release_kind": "initial",
        "owner_user_id": OWNER_USER_ID,
        "owner_user_name": "f055-owner",
        "source": "cli",
        "submitted_at": "2026-08-17T10:00:00",
        "tier": {"code": "light", "name": "轻量", "cpu_millicores": 1000, "memory_mb": 2048},
        "capabilities": [],
        "approver_note": None,
    }
    payload.update(overrides)
    return payload


def _req(*, tenant_id: int = ROOT_TENANT_ID, applicant_user_id: int = OWNER_USER_ID, department_id=None, **payload):
    return SimpleNamespace(
        tenant_id=tenant_id,
        scenario_code=SCENARIO_CODE,
        business_key="dep-1",
        business_resource_type="app",
        business_resource_id="app-1",
        business_name="报表工具",
        applicant_user_id=applicant_user_id,
        applicant_user_name="f055-owner",
        applicant_department_id=department_id,
        reason=None,
        payload_snapshot=_payload(**payload),
        detail_snapshot={},
    )


# ---------------------------------------------------------------------------
# AC-12 / AC-14 — approver resolution matrix
# ---------------------------------------------------------------------------


async def test_approvers_union_dept_admin_and_tenant_admin_single_or_node(
    publish_db, dept_admin_user, tenant_admin_user
):
    """Both sources contribute to one OR node, department administrator first."""
    resolved = await _handler().resolve_approvers(
        _SOURCES, _req(tenant_id=SUB_TENANT_ID, department_id=dept_admin_user.department_id)
    )

    assert resolved == [DEPT_ADMIN_USER_ID, TENANT_ADMIN_USER_ID]


async def test_owner_without_primary_department_falls_to_tenant_admin(publish_db, tenant_admin_user):
    """No primary department → the ``department_admin`` source contributes nothing (AC-14).

    The owner's *primary* department is the only one consulted — there is no
    walk up the tree — so "no primary department" and "the department has no
    administrator" both land on the tenant administrators.
    """
    resolved = await _handler().resolve_approvers(_SOURCES, _req(tenant_id=SUB_TENANT_ID, department_id=None))

    assert resolved == [TENANT_ADMIN_USER_ID]


async def test_department_without_admin_falls_to_tenant_admin(publish_db, dept_admin_user, tenant_admin_user):
    """A department that exists but has no administrator grant behaves the same way."""
    resolved = await _handler().resolve_approvers(
        _SOURCES, _req(tenant_id=SUB_TENANT_ID, department_id=dept_admin_user.department_id + 999)
    )

    assert resolved == [TENANT_ADMIN_USER_ID]


async def test_root_tenant_resolution_reaches_super_admin(publish_db, super_admin_user):
    """114's single-tenant shape: Root has no tenant admins, so the fallback carries the demo."""
    resolved = await _handler().resolve_approvers(_SOURCES, _req(tenant_id=ROOT_TENANT_ID))

    assert resolved == [SUPER_ADMIN_USER_ID]


async def test_explicit_approver_ids_are_honoured_without_sources(publish_db):
    """A node configured with plain user ids (no ``sources``) still resolves — AC-19's reconfiguration."""
    resolved = await _handler().resolve_approvers({"approver_user_ids": [4242, 4243]}, _req())

    assert resolved == [4242, 4243]


async def test_both_sources_empty_resolves_empty_without_raising(publish_db):
    """Nobody resolvable is a *result*, not an exception — the gate turns it into ``approver_empty``."""
    resolved = await _handler().resolve_approvers(_SOURCES, _req(tenant_id=SUB_TENANT_ID + 5))

    assert resolved == []


# ---------------------------------------------------------------------------
# AC-17 — applicant filtering and the self-approval flag
# ---------------------------------------------------------------------------


async def test_applicant_filtered_out_of_approvers(publish_db, dept_admin_user, tenant_admin_user):
    """The owner never approves their own release while somebody else can."""
    handler = _handler()

    resolved = await handler.resolve_approvers(
        _SOURCES,
        _req(
            tenant_id=SUB_TENANT_ID,
            applicant_user_id=DEPT_ADMIN_USER_ID,
            department_id=dept_admin_user.department_id,
        ),
    )

    assert DEPT_ADMIN_USER_ID not in resolved
    assert resolved == [TENANT_ADMIN_USER_ID]
    assert handler.last_self_approval is False


async def test_self_approval_kept_when_applicant_is_only_candidate(publish_db, super_admin_user):
    """The one case where self-approval is allowed: the applicant is the *only* resolvable approver.

    Filtering them out too would deadlock a single-administrator deployment —
    which is what 114 is.
    """
    handler = _handler()

    resolved = await handler.resolve_approvers(
        _SOURCES, _req(tenant_id=ROOT_TENANT_ID, applicant_user_id=SUPER_ADMIN_USER_ID)
    )

    assert resolved == [SUPER_ADMIN_USER_ID]
    assert handler.last_self_approval is True


async def test_self_approval_flag_carried_via_handler_instance_attr(publish_db, super_admin_user):
    """The flag is an instance attribute because the engine offers no other route.

    ``resolve_approvers`` returns ``list[int]`` and ``ApprovalGateResult`` has
    exactly four fields — neither can carry "this one was self-approved", and
    AC-17 requires it to be audited.
    """
    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateResult

    handler = _handler()
    assert handler.last_self_approval is False, "must default to False before any resolution"

    await handler.resolve_approvers(_SOURCES, _req(tenant_id=ROOT_TENANT_ID, applicant_user_id=SUPER_ADMIN_USER_ID))

    assert handler.last_self_approval is True
    assert "self_approval" not in ApprovalGateResult.model_fields


async def test_self_approval_flag_resets_between_resolutions(publish_db, dept_admin_user, tenant_admin_user):
    """A reused handler must not leak a previous self-approval into the next request."""
    handler = _handler()
    handler.last_self_approval = True

    await handler.resolve_approvers(
        _SOURCES,
        _req(
            tenant_id=SUB_TENANT_ID,
            applicant_user_id=DEPT_ADMIN_USER_ID,
            department_id=dept_admin_user.department_id,
        ),
    )

    assert handler.last_self_approval is False


async def test_concurrent_two_releases_do_not_share_the_self_approval_flag(
    publish_db, super_admin_user, dept_admin_user, tenant_admin_user
):
    """Two in-flight publishes, one self-approved, one not — each handler keeps its own answer.

    This is the test that keeps "build a fresh handler per request" honest. A
    module-level singleton passes every other test in this file and fails only
    here, under exactly the condition production sees.
    """
    import asyncio

    self_handler = _handler()
    other_handler = _handler()

    await asyncio.gather(
        self_handler.resolve_approvers(_SOURCES, _req(tenant_id=ROOT_TENANT_ID, applicant_user_id=SUPER_ADMIN_USER_ID)),
        other_handler.resolve_approvers(
            _SOURCES,
            _req(
                tenant_id=SUB_TENANT_ID,
                applicant_user_id=DEPT_ADMIN_USER_ID,
                department_id=dept_admin_user.department_id,
            ),
        ),
    )

    assert self_handler.last_self_approval is True
    assert other_handler.last_self_approval is False


async def test_approver_resolver_not_modified_by_this_scenario(publish_db, dept_admin_user, tenant_admin_user):
    """The shared resolver still returns the applicant; only the handler's exit filters them.

    Pushing the filter down would change the two shipped scenarios, where the
    person who owns the channel or the space genuinely should see their own
    request.
    """
    from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources

    req = _req(
        tenant_id=SUB_TENANT_ID, applicant_user_id=DEPT_ADMIN_USER_ID, department_id=dept_admin_user.department_id
    )

    raw = await resolve_approvers_from_sources(_SOURCES["sources"], req)

    assert DEPT_ADMIN_USER_ID in raw


# ---------------------------------------------------------------------------
# AC-16 — the applicant is the owner, not the service account
# ---------------------------------------------------------------------------


async def test_applicant_is_owner_natural_person_not_service_account(publish_db):
    """The card names the owner; the service account that ran ``deploy`` appears nowhere.

    Resolving the department from the service account instead would be worse
    than cosmetic: service accounts are swept into the guest department, so the
    ``department_admin`` source would resolve people with no relation to the app.
    """
    detail = await _handler().build_detail(_req())

    assert detail["owner_user_id"] == OWNER_USER_ID
    assert SERVICE_ACCOUNT_USER_ID not in {detail["owner_user_id"]}
    assert detail["owner_user_name"] == "f055-owner"


async def test_approver_note_marks_no_department_admin_source(publish_db):
    """AC-16: the card says *why* it went straight to the tenant administrators."""
    detail = await _handler().build_detail(_req(approver_note="no_department_admin_source"))

    assert detail["approver_note"] == "no_department_admin_source"


# ---------------------------------------------------------------------------
# AC-24 — the approval card's payload
# ---------------------------------------------------------------------------


async def test_detail_snapshot_structured_plus_three_flat_fallback_keys(publish_db):
    """Three flat keys survive a front end that has never heard of this scenario.

    The generic detail grid joins arrays with ", " and renders objects as
    ``[object Object]``; without a flat name / kind / tier an unrecognised
    scenario shows an approver nothing they can read.
    """
    detail = await _handler().build_detail(_req())

    assert detail["app_name"] == "报表工具"
    assert detail["release_kind_text"] == "首发"
    assert detail["tier_name"] == "轻量"
    for key in ("app_name", "release_kind_text", "tier_name"):
        assert isinstance(detail[key], str)


async def test_detail_snapshot_fields_match_contract(publish_db):
    """Field-by-field against design §4.2 ④ — the client panel is written against this."""
    detail = await _handler().build_detail(_req())

    assert set(detail) == {
        "scenario_code",
        "app_name",
        "release_kind_text",
        "tier_name",
        "app_id",
        "app_slug",
        "owner_user_id",
        "owner_user_name",
        "source",
        "release_kind",
        "version_id",
        "version_no",
        "submitted_at",
        "tier",
        "capabilities",
        "visibility_snapshot",
        "schema_change",
        "approver_note",
    }
    assert detail["scenario_code"] == SCENARIO_CODE
    assert detail["tier"] == {"code": "light", "name": "轻量", "cpu_millicores": 1000, "memory_mb": 2048}
    assert detail["capabilities"] == []
    assert detail["visibility_snapshot"] == []
    assert detail["schema_change"] is None


async def test_iteration_release_kind_text(publish_db):
    detail = await _handler().build_detail(_req(release_kind="iteration", version_no=4))

    assert detail["release_kind_text"] == "迭代"
    assert detail["version_no"] == 4


async def test_build_title_names_app_and_release_kind(publish_db):
    assert await _handler().build_title(_req()) == "报表工具 · 首发发布审批"
    assert await _handler().build_title(_req(release_kind="iteration")) == "报表工具 · 迭代发布审批"


async def test_build_business_link_points_at_the_publish_tab(publish_db):
    link = await _handler().build_business_link(_req())

    assert link["app_id"] == "app-1"
    assert link["tab"] == "publish"


# ---------------------------------------------------------------------------
# Registration — the four-part wiring (design K1)
# ---------------------------------------------------------------------------


async def test_preset_is_registered_with_handler_key_and_source_types():
    """``handler_key`` has no default: omitting it raises at import time, not at publish time."""
    from bisheng.approval.domain.services.approval_registry import ApprovalRegistry

    preset = ApprovalRegistry.with_default_presets().get_preset(SCENARIO_CODE)

    assert preset is not None
    assert preset.handler_key == SCENARIO_CODE
    assert preset.scenario_name == "应用发布"
    # ``direct_user`` is what lets a tenant administrator reconfigure the
    # approvers by hand (AC-19); dropping it makes that reconfiguration
    # unreachable from the admin page.
    assert set(preset.approver_source_types) == {"department_admin", "tenant_admin", "direct_user"}


async def test_runtime_handler_factory_builds_this_scenario():
    """Missing this branch means approval passes and the application never goes online.

    The failure is silent: ``build_runtime_handler`` raises ``KeyError``, the
    outbox records a task failure and nothing on the publish face changes.
    """
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler
    from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler

    handler = await build_runtime_handler(SCENARIO_CODE)

    assert isinstance(handler, AppPublishScenarioHandler)


async def test_runtime_handler_factory_returns_a_fresh_instance_each_time():
    """Per-request instances are the precondition of the self-approval flag."""
    from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler

    first = await build_runtime_handler(SCENARIO_CODE)
    second = await build_runtime_handler(SCENARIO_CODE)

    assert first is not second


async def test_handler_implements_the_full_duck_typed_protocol():
    """Every method the engine calls by name exists — there is no ABC to catch a typo."""
    handler = _handler()

    for name in (
        "validate",
        "build_title",
        "build_detail",
        "build_business_link",
        "resolve_approvers",
        "on_approved",
        "on_rejected",
        "on_withdrawn",
        "on_cancelled",
    ):
        assert callable(getattr(handler, name, None)), f"handler is missing {name}"
