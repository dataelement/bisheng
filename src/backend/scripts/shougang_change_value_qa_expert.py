#!/usr/bin/env python3
"""Update qa_expert job_family/job_category/position/major from dict_value to dict_key.

Usage (from src/backend):

    .venv/bin/python scripts/shougang_change_value_qa_expert.py --dry-run

Logic:
1. Load enabled system_dictionary entries for the four expert types.
2. For each qa_expert row, trim the four fields and look up their dict_key by dict_value.
3. Update qa_expert when a matching dict_key is found and different from the current value.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

FIELD_TO_TYPE: dict[str, str] = {
    "job_family": "expert_job_family",
    "job_category": "expert_job_category",
    "position": "expert_position",
    "major": "expert_major",
}


@dataclass(slots=True)
class UpdateStats:
    """Counters reported by the update script."""

    processed: int = 0
    updated_rows: int = 0
    updated_fields: int = 0
    skipped_empty: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELD_TO_TYPE, 0))
    skipped_no_match: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELD_TO_TYPE, 0))


async def _load_dictionary_maps(session: Any) -> dict[str, dict[str, str]]:
    """Load dict_value -> dict_key maps for the four expert dictionary types."""
    from sqlmodel import select

    from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary

    value_to_key: dict[str, dict[str, str]] = {}
    for col, dict_type in FIELD_TO_TYPE.items():
        result = await session.exec(
            select(SystemDictionary).where(
                SystemDictionary.type == dict_type,
                SystemDictionary.is_enabled == True,  # noqa: E712
            )
        )
        value_to_key[col] = {
            str(item.dict_value).strip(): item.dict_key for item in result.all() if item.dict_value is not None
        }
    return value_to_key


async def _update_qa_expert_values(*, dry_run: bool) -> UpdateStats:
    """Trim and convert qa_expert career fields from dict_value to dict_key."""
    from sqlalchemy import update
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.qa_expert import Expert

    stats = UpdateStats()

    async with get_async_db_session() as session:
        value_to_key = await _load_dictionary_maps(session)

        result = await session.exec(select(Expert))
        experts = result.all()
        stats.processed = len(experts)

        for expert in experts:
            update_values: dict[str, str] = {}
            for col in FIELD_TO_TYPE:
                current_value = getattr(expert, col, None)
                if current_value is None:
                    stats.skipped_empty[col] += 1
                    continue
                trimmed_value = str(current_value).strip()
                if not trimmed_value:
                    stats.skipped_empty[col] += 1
                    continue
                dict_key = value_to_key[col].get(trimmed_value)
                if dict_key is None:
                    stats.skipped_no_match[col] += 1
                    continue
                if trimmed_value != dict_key:
                    update_values[col] = dict_key

            if update_values:
                stats.updated_rows += 1
                stats.updated_fields += len(update_values)
                if not dry_run:
                    await session.exec(update(Expert).where(Expert.id == expert.id).values(**update_values))

        if not dry_run:
            await session.commit()

    return stats


async def _run(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import (
        DEFAULT_TENANT_ID,
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
    )

    tenant_token = None
    await initialize_app_context(config=settings)
    try:
        with bypass_tenant_filter():
            tenant_token = set_current_tenant_id(DEFAULT_TENANT_ID)
            stats = await _update_qa_expert_values(dry_run=args.dry_run)
    finally:
        if tenant_token is not None:
            current_tenant_id.reset(tenant_token)
        await close_app_context()

    print(
        f"[qa_expert_value_update] Summary: processed={stats.processed}, "
        f"updated_rows={stats.updated_rows}, updated_fields={stats.updated_fields}",
        flush=True,
    )
    for col in FIELD_TO_TYPE:
        print(
            f"  {col}: skipped_empty={stats.skipped_empty[col]}, skipped_no_match={stats.skipped_no_match[col]}",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report counts without writing to the database",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
