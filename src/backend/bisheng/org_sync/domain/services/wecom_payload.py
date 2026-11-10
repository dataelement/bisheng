"""Payload builders for the Gateway-compatible WeCom org snapshot.

Both callers push the exact shape ``/api/v1/internal/sso/gateway-wecom-org-sync``
expects:

- ``scripts/wecom_org_sync.py`` — signs the JSON and POSTs it (no-Gateway sync);
- ``bisheng.org_sync.domain.services.pull_sync_service`` — builds the same
  schemas in-process for the admin console's "run now" task.

Keeping the mapping here stops the two paths from drifting apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.sso_sync.domain.schemas.payloads import (
    DepartmentsSyncRequest,
    DepartmentUpsertItem,
    GatewayWecomOrgSyncRequest,
    LoginSyncRequest,
)

ROOT_TENANT_ID = 1


def build_department_items(departments: Iterable[Any]) -> list[dict]:
    """Map ``RemoteDepartmentDTO`` list onto ``DepartmentUpsertItem`` payloads."""
    return [
        {
            "external_id": str(dept.external_id),
            "name": dept.name or "",
            "parent_external_id": (str(dept.parent_external_id) if dept.parent_external_id is not None else None),
            "sort": int(dept.sort_order or 0),
        }
        for dept in departments
    ]


def build_member_items(
    members: Iterable[Any],
    ts: int,
    *,
    source: str = WECOM_SOURCE,
    root_tenant_id: int = ROOT_TENANT_ID,
) -> list[dict]:
    """Map ``RemoteMemberDTO`` list onto ``LoginSyncRequest`` payloads.

    ``secondary_dept_external_ids`` and ``department_admin_external_ids`` are
    always present (including ``[]``): the backend only reconciles stale
    secondary memberships / sso-tracked department-admin grants when the key
    exists. Manual grants written in the console are untouched.
    """
    items: list[dict] = []
    for member in members:
        items.append(
            {
                "source": source,
                "external_user_id": str(member.external_id),
                "primary_dept_external_id": member.primary_dept_external_id or None,
                "secondary_dept_external_ids": list(member.secondary_dept_external_ids or []),
                "department_admin_external_ids": list(member.admin_dept_external_ids or []),
                "user_attrs": {
                    "name": member.name or None,
                    "email": member.email or None,
                    "phone": member.phone or None,
                },
                # WeCom status: active(1) / disabled(2) / not-activated(4) / resigned(5)
                "account_disabled": member.status != "active",
                "root_tenant_id": root_tenant_id,
                "ts": ts,
            }
        )
    return items


def build_payload(
    department_items: Sequence[dict],
    member_items: Sequence[dict],
    ts: int,
    *,
    full_snapshot: bool,
    source: str = WECOM_SOURCE,
    trigger_type: str | None = None,
) -> dict:
    """Assemble the ``gateway-wecom-org-sync`` request body.

    ``trigger_type`` labels the resulting ``org_sync_log`` row; the cron script
    sends ``scheduled`` so it is distinguishable from Gateway pushes
    (``sso_realtime``) on the 组织同步 page.
    """
    payload: dict = {
        "departments": {
            "source": source,
            "upsert": list(department_items),
            "remove": [],
            "source_ts": ts,
            "full_snapshot": full_snapshot,
        },
        "members": list(member_items),
    }
    if trigger_type:
        payload["trigger_type"] = trigger_type
    return payload


def build_request(
    department_items: Sequence[dict],
    member_items: Sequence[dict],
    ts: int,
    *,
    full_snapshot: bool,
    source: str = WECOM_SOURCE,
) -> GatewayWecomOrgSyncRequest:
    """Typed twin of :func:`build_payload` for in-process callers.

    The HTTP script posts the dict; the manual-sync task hands the same mapping
    to ``apply_wecom_org_snapshot`` as Pydantic schemas, so neither side has to
    know the JSON key layout separately.
    """
    return GatewayWecomOrgSyncRequest(
        departments=DepartmentsSyncRequest(
            source=source,
            upsert=[DepartmentUpsertItem(**item) for item in department_items],
            source_ts=ts,
            full_snapshot=full_snapshot,
        ),
        members=[LoginSyncRequest(**item) for item in member_items],
    )
