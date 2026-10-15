"""Missing observations become UNKNOWN, never fabricated business failure."""

from datetime import UTC


def derive_audit_states(row, *, now, window, activity, has_fragments):
    changes = {}
    last = row.last_write_at or row.started_at
    last = last.replace(tzinfo=UTC) if last.tzinfo is None else last
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    if activity is True or (now - last).total_seconds() < window:
        return changes
    if row.model_result == "RUNNING":
        changes["model_result"] = "UNKNOWN"
    if row.response_result == "RUNNING":
        changes["response_result"] = "UNKNOWN"
    if row.usage_settlement == "PENDING":
        changes["usage_settlement"] = "UNCERTAIN"
    if row.content_status == "PENDING":
        changes["content_status"] = "PARTIAL" if has_fragments else "NOT_CAPTURED"
    return changes


class DshModelAuditStateService:
    def __init__(self, queries, activity, *, window, now):
        self.queries, self.activity, self.window, self.now = queries, activity, window, now

    async def inspect(self, tenant, cursor=None):
        rows = await self.queries.execute(tenant, lambda repository: repository.stalled(cursor=cursor))
        changed = 0
        for row in rows:
            active = await self.activity.confirmed(row.request_id)

            def apply(repository, row=row, active=active):
                current = repository.request(row.request_id, lock=True)
                if current is None or current.state_version != row.state_version:
                    return 0
                _, occurrences, _ = repository.facts(row.request_id)
                changes = derive_audit_states(
                    current, now=self.now(), window=self.window, activity=active, has_fragments=bool(occurrences)
                )
                for key, value in changes.items():
                    setattr(current, key, value)
                if changes:
                    current.state_version += 1
                    repository.session.add(current)
                return bool(changes)

            changed += await self.queries.execute(tenant, apply)
        return rows[-1].request_id if len(rows) == 100 else None, changed
