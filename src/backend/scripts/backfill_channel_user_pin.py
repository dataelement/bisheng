#!/usr/bin/env python3
"""F051 — backfill legacy channel pins into the decoupled per-user pin table.

Channel pin state used to live on ``space_channel_member.is_pinned``. F051 moved it
to a dedicated ``channel_user_pin`` table (decoupled from membership). This one-off
script copies existing pins so users keep their pinned channels after upgrade.

Source rows: ``space_channel_member`` where ``business_type='channel'`` AND
``is_pinned`` is true AND ``status='ACTIVE'``. Each becomes a
``channel_user_pin(user_id, channel_id=business_id)`` row. Idempotent: a
(user_id, channel_id) already present is skipped, so re-running is safe.

Run from ``src/backend/`` (dry-run prints what would change; ``--apply`` writes):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/backfill_channel_user_pin.py            # dry-run
    python scripts/backfill_channel_user_pin.py --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.channel.domain.models.channel_user_pin import ChannelUserPin  # noqa: E402
from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402


@dataclass
class BackfillReport:
    candidates: int = 0
    created: int = 0
    skipped_existing: int = 0


async def backfill(session, *, apply: bool = True) -> BackfillReport:
    """Copy legacy active channel pins into channel_user_pin.

    When ``apply`` is False, counts what would change without writing.
    """
    report = BackfillReport()

    pinned_members = (
        await session.exec(
            select(SpaceChannelMember).where(
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.is_pinned == True,  # noqa: E712 — SQL boolean, not Python identity
            )
        )
    ).all()
    report.candidates = len(pinned_members)
    if not pinned_members:
        return report

    existing = set((await session.exec(select(ChannelUserPin.user_id, ChannelUserPin.channel_id))).all())

    seen_in_run: set[tuple[int, str]] = set()
    for member in pinned_members:
        channel_id = member.business_id
        if not channel_id:
            continue
        key = (member.user_id, channel_id)
        if key in existing or key in seen_in_run:
            report.skipped_existing += 1
            continue
        seen_in_run.add(key)
        report.created += 1
        if apply:
            session.add(ChannelUserPin(user_id=member.user_id, channel_id=channel_id))

    if apply and report.created:
        await session.commit()

    return report


async def _run(apply: bool) -> int:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            report = await backfill(session, apply=apply)
    mode = "APPLIED" if apply else "DRY-RUN"
    print(
        f"[{mode}] candidates={report.candidates} created={report.created} skipped_existing={report.skipped_existing}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    sys.exit(main())
