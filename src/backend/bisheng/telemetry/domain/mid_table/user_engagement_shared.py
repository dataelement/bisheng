"""Shared constants for the merged user-engagement ES index.

F058 follow-up: `用户规模统计` (mid_user_increment), `活跃用户规模统计`
(mid_active_user), and `全员每日参与度` (mid_user_daily_participation_fact) were
originally three independent ES indices. They now share one physical index so the
dashboard can present/query them as a single dataset. Each source's records carry a
`metric_source` discriminator (this module's constants) so:

- queries can filter down to one source's fields/metrics without cross-source noise,
- each source's own `_id` scheme can be prefixed to avoid collisions between sources,
- each source's incremental-sync watermark query (see BaseMidTable._watermark_filter)
  only looks at its own records, not the more-frequent siblings sharing the index.

The three original index names (mid_user_increment, mid_active_user,
mid_user_daily_participation_fact) are kept around read-only as a historical/rollback
copy — nothing writes to them anymore after this change; see
scripts/migrate_user_engagement_indices.py for the one-time historical backfill into
the merged index.
"""

USER_ENGAGEMENT_ES_INDEX = "mid_user_engagement_stat"

METRIC_SOURCE_INCREMENT = "increment"
METRIC_SOURCE_ACTIVE_USER = "active_user"
METRIC_SOURCE_PARTICIPATION = "participation"

METRIC_SOURCE_FIELD_MAPPING = {
    "metric_source": {"type": "keyword"},
}
