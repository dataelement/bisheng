"""Missing observations become UNKNOWN, never fabricated business failure."""

import json
from datetime import UTC, datetime

from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


def derive_audit_states(row, *, now, window, activity, has_fragments):
    if getattr(row, "record_origin", "MODEL") == "EXTERNAL_SAFETY":
        return {}
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
    if getattr(row, "message_sources_status", None) == "PENDING":
        changes["message_sources_status"] = "UNAVAILABLE"
    return changes


class DshModelAuditStateService:
    def __init__(self, queries, activity, *, window, now):
        self.queries, self.activity, self.window, self.now = queries, activity, window, now

    async def inspect(self, tenant, cursor=None):
        annotation_cursor = None
        annotation_phase = isinstance(cursor, str) and cursor.startswith("annotations:")
        if annotation_phase:
            position = json.loads(cursor[len("annotations:") :])
            annotation_cursor = (datetime.fromisoformat(position[0]), position[1])
        rows = (
            []
            if annotation_phase
            else await self.queries.execute(tenant, lambda repository: repository.stalled(cursor=cursor))
        )
        annotations = (
            []
            if len(rows) == 100
            else await self.queries.execute(
                tenant, lambda repository: repository.pending_annotations(cursor=annotation_cursor)
            )
        )
        existing_ids = {row.request_id for row in rows}
        inspect_rows = [*rows, *(row for row in annotations if row.request_id not in existing_ids)]
        changed = 0
        for row in inspect_rows:
            # Keep the original batch for cursor advancement, but do not inspect
            # external rows through activity, manifest or original-body storage.
            if getattr(row, "record_origin", "MODEL") == "EXTERNAL_SAFETY":
                continue
            active = await self.activity.confirmed(row.request_id)

            def apply(repository, row=row, active=active):
                current = repository.request(row.request_id, lock=True)
                if (
                    current is None
                    or current.state_version != row.state_version
                    or getattr(current, "record_origin", "MODEL") == "EXTERNAL_SAFETY"
                ):
                    return 0
                _, occurrences, _ = repository.facts(row.request_id)
                changes = derive_audit_states(
                    current, now=self.now(), window=self.window, activity=active, has_fragments=bool(occurrences)
                )
                for key, value in changes.items():
                    setattr(current, key, value)
                if changes:
                    refresh_audit_status(current)
                    if changes.get("message_sources_status") == "UNAVAILABLE":
                        record_audit_metric("annotation_pending_timeout", tenant_id=tenant)
                    current.state_version += 1
                    repository.session.add(current)
                return bool(changes)

            changed += await self.queries.execute(tenant, apply)
        if len(rows) == 100:
            return rows[-1].request_id, changed
        if len(annotations) == 100:
            last = annotations[-1]
            return "annotations:" + json.dumps([last.started_at.isoformat(), last.request_id]), changed
        return None, changed
