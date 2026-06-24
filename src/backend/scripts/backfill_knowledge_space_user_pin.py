#!/usr/bin/env python3
"""F037 — backfill legacy space pins into the decoupled per-user pin table.

Pin state used to live on ``space_channel_member.is_pinned``. Feature 037 moved it
to a dedicated ``knowledge_space_user_pin`` table (decoupled from membership). This
one-off script copies existing pins so users keep their pinned spaces after upgrade.

Source rows: ``space_channel_member`` where ``business_type='space'`` AND
``is_pinned`` is true AND ``status='ACTIVE'``. Each becomes a
``knowledge_space_user_pin(user_id, space_id=business_id)`` row. Idempotent: a
(user_id, space_id) already present is skipped, so re-running is safe.

Run from ``src/backend/`` (dry-run prints what would change; ``--apply`` writes):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/backfill_knowledge_space_user_pin.py            # dry-run
    python scripts/backfill_knowledge_space_user_pin.py --apply    # write
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

from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_user_pin import (  # noqa: E402
    KnowledgeSpaceUserPin,
)


@dataclass
class BackfillReport:
    candidates: int = 0
    created: int = 0
    skipped_existing: int = 0


async def backfill(session, *, apply: bool = True) -> BackfillReport:
    """Copy legacy active space pins into knowledge_space_user_pin.

    When ``apply`` is False, counts what would change without writing.
    """
    report = BackfillReport()

    pinned_members = (
        await session.exec(
            select(SpaceChannelMember).where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.is_pinned == True,  # noqa: E712 — SQL boolean, not Python identity
            )
        )
    ).all()
    report.candidates = len(pinned_members)
    if not pinned_members:
        return report

    existing = set((await session.exec(select(KnowledgeSpaceUserPin.user_id, KnowledgeSpaceUserPin.space_id))).all())

    seen_in_run: set[tuple[int, int]] = set()
    for member in pinned_members:
        try:
            space_id = int(member.business_id)
        except (TypeError, ValueError):
            continue
        key = (member.user_id, space_id)
        if key in existing or key in seen_in_run:
            report.skipped_existing += 1
            continue
        seen_in_run.add(key)
        report.created += 1
        if apply:
            session.add(KnowledgeSpaceUserPin(user_id=member.user_id, space_id=space_id))

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
