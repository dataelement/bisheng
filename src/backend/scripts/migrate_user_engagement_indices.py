"""Backfill historical user-engagement data into the merged ES index (F058 follow-up).

Background: 用户规模统计 (mid_user_increment) / 活跃用户规模统计 (mid_active_user) /
全员每日参与度 (mid_user_daily_participation_fact) used to be three independent ES
indices. The write paths that produce them (see
bisheng/telemetry/domain/mid_table/{user_increment,derived_events,daily_participation}.py)
have been repointed to write into one shared index (USER_ENGAGEMENT_ES_INDEX,
"mid_user_engagement_stat") going forward, tagging each document with a `metric_source`
discriminator. This script copies the OLD, now-frozen indices' historical documents into
that shared index, so dashboards built on the merged dataset still show history from
before the cutover.

The three old indices are left untouched (read-only) — this script never writes to or
deletes from them. Re-running this script is safe/idempotent: document `_id`s are
deterministic (prefixed per source, matching exactly what the live writers now produce
for the same records), so re-migrating just overwrites the same documents with the same
content.

`_id` scheme (must match the live writers — see user_increment.py / derived_events.py /
daily_participation.py):
  - increment:     "increment_" + the old document's own _id (already "user_{user_id}")
  - active_user:   "active_" + the old document's own _id (already "{user_id}_{date}" or
                    a raw hit id fallback)
  - participation: unchanged — the old scheme ("participation_{tenant}_{date}_{user}")
                    was already source-scoped, no prefix needed

Usage (dry-run by default; add --apply to write):

    cd src/backend
    PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py
    PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply --source increment
    PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply --batch-size 2000
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from elasticsearch import helpers  # noqa: E402
from loguru import logger  # noqa: E402

from bisheng.core.search.elasticsearch.manager import get_es_connection_sync  # noqa: E402
from bisheng.telemetry.domain.mid_table.daily_participation import DailyParticipationFact  # noqa: E402
from bisheng.telemetry.domain.mid_table.derived_events import MidActiveUserJob  # noqa: E402
from bisheng.telemetry.domain.mid_table.user_engagement_shared import (  # noqa: E402
    METRIC_SOURCE_ACTIVE_USER,
    METRIC_SOURCE_INCREMENT,
    METRIC_SOURCE_PARTICIPATION,
    USER_ENGAGEMENT_ES_INDEX,
)
from bisheng.telemetry.domain.mid_table.user_increment import UserIncrement  # noqa: E402

OLD_INDEX_BY_SOURCE = {
    METRIC_SOURCE_INCREMENT: "mid_user_increment",
    METRIC_SOURCE_ACTIVE_USER: "mid_active_user",
    METRIC_SOURCE_PARTICIPATION: "mid_user_daily_participation_fact",
}
_ID_PREFIX_BY_SOURCE = {
    METRIC_SOURCE_INCREMENT: "increment",
    METRIC_SOURCE_ACTIVE_USER: "active",
    # participation already source-scoped — no prefix, see module docstring
}


@dataclass
class MigrationReport:
    source: str
    old_index: str
    scanned: int = 0
    migrated: int = 0
    errors: int = 0

    def __str__(self) -> str:
        return (
            f"source={self.source} old_index={self.old_index} "
            f"scanned={self.scanned} migrated={self.migrated} errors={self.errors}"
        )


def _new_doc_id(metric_source: str, old_id: str) -> str:
    prefix = _ID_PREFIX_BY_SOURCE.get(metric_source)
    return old_id if prefix is None else f"{prefix}_{old_id}"


def _transform_hit(hit: dict, metric_source: str) -> dict:
    source = dict(hit.get("_source") or {})
    source["metric_source"] = metric_source
    return {
        "_index": USER_ENGAGEMENT_ES_INDEX,
        "_id": _new_doc_id(metric_source, hit.get("_id")),
        "_source": source,
    }


def _ensure_target_index(es_client) -> None:
    """Create/extend the shared index's mapping using the exact same code the live
    writers use, so we don't duplicate mapping definitions here and risk drifting."""
    UserIncrement(ensure_sync_index=True)
    DailyParticipationFact(ensure_sync_index=True)
    MidActiveUserJob(es_client=es_client).ensure_index_exists()


def migrate_source(
    es_client,
    metric_source: str,
    *,
    dry_run: bool,
    batch_size: int,
    limit: int | None,
) -> MigrationReport:
    old_index = OLD_INDEX_BY_SOURCE[metric_source]
    report = MigrationReport(source=metric_source, old_index=old_index)

    if not es_client.indices.exists(index=old_index):
        logger.warning(f"Old index '{old_index}' does not exist, skipping {metric_source}.")
        return report

    actions: list[dict] = []
    for hit in helpers.scan(es_client, index=old_index, size=batch_size):
        if limit is not None and report.scanned >= limit:
            break
        report.scanned += 1
        actions.append(_transform_hit(hit, metric_source))
        if len(actions) >= batch_size:
            _flush(es_client, actions, report, dry_run)
            actions = []
    if actions:
        _flush(es_client, actions, report, dry_run)

    return report


def _flush(es_client, actions: list[dict], report: MigrationReport, dry_run: bool) -> None:
    if dry_run:
        report.migrated += len(actions)
        return
    success, errors = helpers.bulk(es_client, actions, raise_on_error=False)
    report.migrated += success
    if errors:
        report.errors += len(errors)
        logger.error(f"{report.source}: {len(errors)} bulk errors, first={errors[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually write (default: dry-run, report only).")
    parser.add_argument(
        "--source",
        choices=sorted(OLD_INDEX_BY_SOURCE),
        default=None,
        help="Restrict to one source (default: migrate all three).",
    )
    parser.add_argument("--batch-size", type=int, default=2000, help="Scan/bulk batch size (default: 2000).")
    parser.add_argument(
        "--limit", type=int, default=None, help="Max documents to scan per source (for a quick trial run)."
    )
    args = parser.parse_args()

    dry_run = not args.apply
    sources = [args.source] if args.source else sorted(OLD_INDEX_BY_SOURCE)

    es_client = get_es_connection_sync()
    if not dry_run:
        _ensure_target_index(es_client)

    reports = [
        migrate_source(es_client, source, dry_run=dry_run, batch_size=args.batch_size, limit=args.limit)
        for source in sources
    ]

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"=== {mode} ===")
    for report in reports:
        print(report)
    total_errors = sum(r.errors for r in reports)
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
