"""Persistent node-scoped proof; never accept manager readiness as host proof."""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from bisheng.app_runtime.domain.models.runtime_host_isolation import RuntimeHostIsolationReport
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.core.database import get_async_db_session

REQUIRED = frozenset(
    {
        "ipv4_bridge",
        "rules_read_back",
        "egress_allowed",
        "host_gateway_denied",
        "host_published_denied",
        "ingress_reply_allowed",
    }
)


class HostIsolationRepository:
    def __init__(self, factory=get_async_db_session):
        self.factory = factory

    async def accept(self, identity, body, expected):
        if not expected or (body["engine_id"], body["network_id"], body["config_digest"]) != (
            expected.get("engine_id"),
            expected.get("network_id"),
            expected.get("config_digest"),
        ):
            raise RuntimeConflict("host_isolation_binding_mismatch")
        now = datetime.utcnow()
        try:
            checked = datetime.fromisoformat(body["checked_at"].replace("Z", "+00:00"))
            if checked.tzinfo is None:
                raise ValueError("timezone required")
            checked = checked.astimezone(UTC).replace(tzinfo=None)
        except (ValueError, TypeError) as exc:
            raise RuntimeConflict("host_isolation_report_stale") from exc
        if abs((now - checked).total_seconds()) > 30:
            raise RuntimeConflict("host_isolation_report_stale")
        if set(body["checks"]) - REQUIRED:
            raise RuntimeConflict("host_isolation_proof_incomplete")
        if body["status"] == "valid" and (
            set(body["checks"]) != REQUIRED or any(v is not True for v in body["checks"].values())
        ):
            raise RuntimeConflict("host_isolation_proof_incomplete")
        async with self.factory() as session:
            row = (
                await session.exec(
                    select(RuntimeHostIsolationReport)
                    .where(RuntimeHostIsolationReport.id == identity.node_id)
                    .with_for_update()
                )
            ).first()
            if row and body["revision"] <= row.revision:
                raise RuntimeConflict("host_isolation_revision_stale")
            values = {
                k: body[k]
                for k in ("engine_id", "network_id", "config_digest", "rule_digest", "revision", "status", "checks")
            }
            values.update(checked_at=now, valid_until=now + timedelta(seconds=60))
            if row is None:
                row = RuntimeHostIsolationReport(id=identity.node_id, **values)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.add(row)
            await session.commit()
            return {"node_id": row.id, "revision": row.revision, "valid_until": row.valid_until}

    @staticmethod
    async def require(session, node, expected):
        if node is None:
            raise RuntimeConflict("host_isolation_unavailable")
        if node.executor_kind != "docker":
            return None
        row = (
            await session.exec(select(RuntimeHostIsolationReport).where(RuntimeHostIsolationReport.id == node.id))
        ).first()
        now = datetime.utcnow()
        if (
            not expected
            or not row
            or row.status != "valid"
            or row.valid_until <= now
            or row.checked_at > now
            or row.engine_id != node.engine_id
            or row.engine_id != expected.get("engine_id")
            or row.network_id != expected.get("network_id")
            or row.config_digest != expected.get("config_digest")
            or set(row.checks) != REQUIRED
            or not all(v is True for v in row.checks.values())
        ):
            raise RuntimeConflict("host_isolation_unavailable")
        return row
