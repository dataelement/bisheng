#!/usr/bin/env python3
"""Remove one departed member's orphan visible tuple caused by source-version reset.

Run from src/backend with the live service config. Preview is read-only::

    python scripts/repair_f048_membership_orphan.py --tenant-id 1 \
        --resource-key knowledge_space:14 --user-id 10

After reviewing the JSON plan, stop permission writers and back up SQL/OpenFGA.
Repeat with --apply --confirm-store-id <store> --confirm-plan-checksum <checksum>
--operator-id <operator>. Live runtime heartbeats or pending projections block
apply. Only the exact orphan visible tuple is deleted through the existing
durable projection ledger; historical SQL sources/memberships are preserved.
No model publication, Catalog cutover, or broad reconcile is performed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.permission.application.control_state import SqlPermissionControlState  # noqa: E402
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee  # noqa: E402
from scripts import reconcile_f048_visible_projection as reconcile  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--resource-key", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-store-id")
    parser.add_argument("--confirm-plan-checksum")
    parser.add_argument("--operator-id", type=int, default=0)
    args = parser.parse_args(argv)
    if min(args.tenant_id, args.user_id) <= 0 or args.operator_id < 0:
        parser.error("tenant/user IDs must be positive; operator ID must not be negative")
    if not re.fullmatch(r"knowledge_space:[1-9][0-9]*|channel:[A-Za-z0-9_-]{1,64}", args.resource_key):
        parser.error("--resource-key must be one exact knowledge_space:<id> or channel:<id>")
    if args.apply and (not args.confirm_store_id or not args.confirm_plan_checksum or args.operator_id <= 0):
        parser.error("--apply requires Store ID, plan checksum and a positive operator ID")
    return args


async def load_evidence(args: argparse.Namespace, persisted: tuple) -> tuple[dict, ...]:
    """Require an exited membership and a retired, older version of its source."""
    resource_type, resource_id = args.resource_key.split(":", 1)
    source_type = "SPACE_MEMBERSHIP" if resource_type == "knowledge_space" else "CHANNEL_MEMBERSHIP"
    business_type = BusinessTypeEnum.SPACE if resource_type == "knowledge_space" else BusinessTypeEnum.CHANNEL
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            # Memberships have no tenant column; _load_cleanup_scope has already
            # required this globally unique business resource to belong to the selected tenant.
            members = (
                await session.exec(
                    select(SpaceChannelMember).where(
                        SpaceChannelMember.business_type == business_type,
                        SpaceChannelMember.business_id == resource_id,
                        SpaceChannelMember.user_id == args.user_id,
                        SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                    )
                )
            ).all()
            reconcile._require(not members, "The user is still an ACTIVE business member; no cleanup allowed")
            sources = (
                await session.exec(
                    select(PermissionGrantAssignee)
                    .join(PermissionGrant, PermissionGrant.id == PermissionGrantAssignee.grant_id)
                    .where(
                        PermissionGrant.tenant_id == args.tenant_id,
                        PermissionGrant.resource_type == resource_type,
                        PermissionGrant.resource_id == resource_id,
                        PermissionGrantAssignee.tenant_id == args.tenant_id,
                        PermissionGrantAssignee.subject_type == "user",
                        PermissionGrantAssignee.subject_id == str(args.user_id),
                        PermissionGrantAssignee.source_type == source_type,
                    )
                )
            ).all()
    reconcile._require(bool(sources), "No historical membership authorization source found")
    reconcile._require(
        all(row.state == "INACTIVE" and not row.protected for row in sources),
        "Membership sources must all be INACTIVE and unprotected",
    )
    evidence = []
    for source in sources:
        for row in persisted:
            if (
                row.tenant_id == args.tenant_id
                and f"{row.resource_type}:{row.resource_id}" == args.resource_key
                and row.source_kind == "GRANT_ASSIGNEE"
                and row.source_owner_key == f"grant_assignee:{source.id}"
                and row.source_fingerprint == source.source_fingerprint
                and row.source_locator == source.source_locator
                and row.projected_subject == source.projected_subject == f"user:{args.user_id}"
                and row.state == "RETIRED"
                and row.source_version < source.version
            ):
                evidence.append(
                    {
                        "assignee_id": source.id,
                        "assignee_version": source.version,
                        "projection_id": row.id,
                        "projection_version": row.source_version,
                    }
                )
    reconcile._require(bool(evidence), "No retired membership source with the version-reset signature found")
    return tuple(sorted(evidence, key=lambda row: (row["assignee_id"], row["projection_id"])))


def select_exact_orphan(
    args: argparse.Namespace, audit: reconcile.OrphanTupleAudit
) -> reconcile.OrphanCleanupSelection:
    target = (f"user:{args.user_id}", "visible", args.resource_key)
    selected = tuple(row for row in audit.orphan_tuples if row == target)
    return reconcile.OrphanCleanupSelection(
        object_filters=(args.resource_key,),
        tuple_count=len(selected),
        tuple_checksum=reconcile._checksum(selected),
        tuples=selected,
    )


async def read_visible(client, resource_key: str) -> frozenset[tuple[str, str, str]]:
    rows = await client.read_tuples(relation="visible", object=resource_key, consistency=reconcile.HIGHER_CONSISTENCY)
    return frozenset((row["user"], row["relation"], row["object"]) for row in rows if row["relation"] == "visible")


async def execute(args: argparse.Namespace, *, live_settings=reconcile.settings) -> int:
    client = None
    try:
        await reconcile.initialize_app_context(config=reconcile._offline_settings(live_settings))
        reconcile._require(
            hasattr(SqlPermissionControlState, "resolve_business_source_version"),
            "Deploy the membership reactivation code fix before cleaning data",
        )
        current = await reconcile._load_current_release()
        config = live_settings.openfga
        pin = await reconcile.discover_openfga_runtime(
            config,
            expected_model=None,
            allow_bootstrap=False,
            required_store_id=current.store_id,
            required_model_id=current.model_id,
        )
        reconcile._require(pin.model_checksum == current.model_checksum, "CURRENT model checksum mismatch")
        reconcile._require(not current.write_fenced, "CURRENT Catalog is write fenced")
        if args.apply:
            reconcile._require(args.confirm_store_id == current.store_id, "Store ID confirmation mismatch")
        await reconcile._assert_maintenance_window(apply=args.apply)
        scope = await reconcile._load_cleanup_scope(args.resource_key)
        reconcile._require(scope.tenant_id == args.tenant_id, "Resource belongs to a different tenant")
        grants, _ = await reconcile._load_canonical_grants()
        canonical = reconcile._compile_sources(grants)
        persisted = await reconcile._load_persisted_sources()
        evidence = await load_evidence(args, persisted)
        client = reconcile.FGAClient(
            api_url=config.api_url, store_id=current.store_id, model_id=current.model_id, timeout=config.timeout
        )
        audit = await reconcile._audit_orphan_tuples(
            client,
            canonical_sources=canonical,
            persisted=persisted,
            object_filters=(args.resource_key,),
        )
        selection = select_exact_orphan(args, audit)
        before = await read_visible(client, args.resource_key)
        target = (f"user:{args.user_id}", "visible", args.resource_key)
        reconcile._require(
            target not in before or bool(selection.tuples),
            "The selected visible tuple has a valid SQL source; no cleanup allowed",
        )
        plan = {
            "store_id": current.store_id,
            "model_id": current.model_id,
            "catalog_id": current.catalog_id,
            "tenant_id": args.tenant_id,
            "resource_key": args.resource_key,
            "resource_version": scope.version,
            "user_id": args.user_id,
            "evidence": evidence,
            "selection": asdict(selection),
        }
        checksum = reconcile._checksum(plan)
        print(
            json.dumps(
                {
                    "event": "membership_orphan_plan",
                    "mode": "apply" if args.apply else "dry-run",
                    **plan,
                    "plan_checksum": checksum,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if not args.apply:
            return reconcile.EXIT_OK
        # A successful repeated apply is a no-op; all evidence and safety gates still apply.
        if not selection.tuples:
            print(json.dumps({"event": "already_clean", "deleted_tuple_count": 0}), flush=True)
            return reconcile.EXIT_OK
        reconcile._require(args.confirm_plan_checksum == checksum, "Plan changed; review a new dry-run checksum")
        await reconcile._assert_maintenance_window(apply=True)
        ids = await reconcile._cleanup_orphan_tuples(
            client,
            current=current,
            selection=selection,
            operator_id=args.operator_id,
        )
        after = await read_visible(client, args.resource_key)
        reconcile._require(
            after == before - set(selection.tuples),
            "Post-cleanup visible tuples differ from the reviewed exact deletion",
        )
        print(
            json.dumps(
                {
                    "event": "membership_orphan_cleaned",
                    "deleted_tuple_count": selection.tuple_count,
                    "operation_ids": ids,
                    "other_visible_tuples_preserved": True,
                }
            ),
            flush=True,
        )
        return reconcile.EXIT_OK
    finally:
        try:
            if client is not None:
                await client.close()
        finally:
            await reconcile.close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except reconcile.VisibleReconcileBlockedError as exc:
        print(f"Membership orphan repair blocked: {exc}", file=sys.stderr)
        return reconcile.EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
