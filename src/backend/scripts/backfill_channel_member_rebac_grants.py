#!/usr/bin/env python3
"""Backfill ReBAC viewer/manager grants for already-active channel subscribers.

Why this exists
---------------
The channel "成员管理" / authorization list is rendered from OpenFGA tuples
(``PermissionService.get_resource_permissions('channel', ...)``), not from the
``space_channel_member`` table. Before commit ``c530bf375`` ("频道订阅审批通过后
写入 ReBAC 关系"), activating a channel subscription only set
``space_channel_member.status = ACTIVE`` and did NOT write the matching OpenFGA
viewer grant + relation-model binding. Such members therefore never appear in
the ReBAC-based member list, even though they are active in the DB.

Going forward this is already fixed (every activation path now calls
``ChannelService.sync_direct_channel_user_permissions``). This script repairs the
historical gap: active, non-creator, *direct* (self-subscribed) channel members
that have no FGA grant get one written via the same idempotent sync method.

Scope / safety
--------------
- Only ``status = ACTIVE`` rows are touched. ``PENDING`` / ``REJECTED`` members
  are intentionally left without a grant.
- The creator (``CREATOR`` / owner) is skipped — the owner tuple is managed by
  ``OwnerService``, not mirrored here.
- Only *direct* members (``grant_subject_type`` in ``NULL`` / ``self``) are
  considered. Members authorized through a user / department / user_group grant
  already own their grant path and must not be rewritten here.
- A member is repaired only when no FGA tuple exists for that user on the
  channel; members already present are reported and left untouched.
- ``sync_direct_channel_user_permissions`` is idempotent (grants are idempotent
  writes, bindings are de-duplicated), so re-running is safe.

How to run (from src/backend/)
------------------------------
Dry-run is the default; pass ``--apply`` to persist:

    cd src/backend/
    PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py
    PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py --apply

    # restrict to a single channel
    PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py \
        --channel-id 56019cad26cc486f8a0240826708775b --apply

    bash scripts/backfill_channel_member_rebac_grants.sh
    bash scripts/backfill_channel_member_rebac_grants.sh apply
    bash scripts/backfill_channel_member_rebac_grants.sh --channel-id <id> apply
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.channel.domain.models.channel import Channel  # noqa: E402
from bisheng.channel.domain.services.channel_service import ChannelService  # noqa: E402
from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.permission.domain.services.permission_service import PermissionService  # noqa: E402

# Direct (self-subscribed) members carry no organisation grant subject.
_DIRECT_SUBJECT_TYPES = {None, '', 'self'}


async def _channel_ids(channel_id: str | None) -> list[tuple[str, int | None]]:
    """Return [(channel_id, creator_user_id)] for the requested scope."""
    async with get_async_db_session() as session:
        stmt = select(Channel.id, Channel.user_id)
        if channel_id:
            stmt = stmt.where(Channel.id == channel_id)
        rows = (await session.exec(stmt)).all()
    return [(str(r[0]), r[1]) for r in rows]


async def _active_direct_members(channel_id: str) -> list[SpaceChannelMember]:
    async with get_async_db_session() as session:
        stmt = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            SpaceChannelMember.user_role != UserRoleEnum.CREATOR,
        )
        return list((await session.exec(stmt)).all())


async def _granted_user_ids(channel_id: str) -> set[int]:
    """User ids that already hold a FGA grant on the channel."""
    items = await PermissionService.get_resource_permissions('channel', channel_id)
    return {
        int(item.subject_id)
        for item in items
        if getattr(item, 'subject_type', None) == 'user'
    }


async def backfill(channel_id: str | None, dry_run: bool) -> int:
    # Cross-tenant maintenance: bypass the multi-tenant filter for the whole
    # operation. The ContextVar propagates across awaits in this task, so every
    # nested query (member reads, FGA name enrichment, subject expansion in
    # PermissionService.authorize, binding config writes) inherits the bypass.
    with bypass_tenant_filter():
        return await _run_backfill(channel_id, dry_run)


async def _run_backfill(channel_id: str | None, dry_run: bool) -> int:
    channels = await _channel_ids(channel_id)
    if channel_id and not channels:
        print(f"[error] channel id={channel_id} not found")
        return 2

    scanned_channels = 0
    active_members = 0
    already_granted = 0
    repaired = 0
    failed = 0

    for cid, creator_id in channels:
        members = await _active_direct_members(cid)
        members = [
            m for m in members
            if getattr(m, 'grant_subject_type', None) in _DIRECT_SUBJECT_TYPES
            and (creator_id is None or int(m.user_id) != int(creator_id))
        ]
        if not members:
            continue
        scanned_channels += 1
        active_members += len(members)

        granted_user_ids = await _granted_user_ids(cid)
        for member in members:
            user_id = int(member.user_id)
            role = getattr(member.user_role, 'value', member.user_role)
            if user_id in granted_user_ids:
                already_granted += 1
                print(f"[skip] already granted channel={cid} user_id={user_id} role={role}")
                continue

            action = 'would backfill' if dry_run else 'backfilling'
            print(
                f"[{'dry-run' if dry_run else 'apply'}] {action} channel={cid} "
                f"user_id={user_id} role={role}"
            )
            if dry_run:
                repaired += 1
                continue
            try:
                await ChannelService.sync_direct_channel_user_permissions(
                    cid,
                    user_id,
                    member.user_role,
                    is_active=True,
                )
                repaired += 1
            except Exception as exc:  # report and continue the batch
                failed += 1
                print(f"[error] channel={cid} user_id={user_id} backfill failed: {exc}")

    print(json.dumps({
        'dry_run': dry_run,
        'channel_scope': channel_id or 'all',
        'channels_with_candidates': scanned_channels,
        'active_direct_members': active_members,
        'already_granted': already_granted,
        'backfilled' if not dry_run else 'would_backfill': repaired,
        'failed': failed,
    }, ensure_ascii=False))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--channel-id', default=None, help='Restrict to a single channel id')
    parser.add_argument('--apply', action='store_true', help='Persist changes; default is dry-run')
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    async def _main() -> int:
        # Initialize the full app context (database + OpenFGA, etc.) so FGA
        # writes work. Without this only the lazily-registered database context
        # exists and PermissionService.authorize fails with "FGAClient not available".
        await initialize_app_context(config=settings)
        try:
            return await backfill(channel_id=args.channel_id, dry_run=not args.apply)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_main())


if __name__ == '__main__':
    sys.exit(main())
