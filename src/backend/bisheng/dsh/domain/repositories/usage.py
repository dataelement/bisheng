"""Transactional, versioned projection of complete DSH request events."""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlmodel import Session

from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.schemas.model_policy import model_configs_payload
from bisheng.dsh.domain.schemas.usage import UsageEvent


class DshUsageRepository:
    """Caller owns transaction and only acknowledges Stream events after commit."""

    def __init__(self, session: Session):
        self.session = session

    def project_batch(self, events: list[UsageEvent]) -> int:
        if not self.session.in_transaction():
            raise RuntimeError("Projection requires an explicit transaction")
        if len(events) > 500:
            raise ValueError("Projection batches are bounded to 500 events")
        tenant = get_current_tenant_id()
        merged = {}
        for raw in events:
            event = UsageEvent.model_validate(raw.model_dump())
            if event.tenant_id != tenant:
                raise ValueError("Event tenant does not match trusted worker context")
            previous = merged.get(event.request_id)
            if previous and previous.event_version == event.event_version and previous != event:
                raise ValueError("Conflicting event payload for one version")
            if previous is None or previous.event_version < event.event_version:
                merged[event.request_id] = event
        changed = 0
        deltas = defaultdict(int)
        timezones = {}
        with strict_tenant_filter():
            # Existing policy rows serialize first request/month inserts across consumers.
            for user_id in sorted({e.user_id for e in merged.values()}):
                policies = list(
                    self.session.scalars(
                        select(DshUserPolicy)
                        .where(DshUserPolicy.user_id == user_id)
                        .order_by(DshUserPolicy.model_id)
                        .with_for_update()
                    )
                )
                policy = next((p for p in policies if p.tenant_id == tenant), None)
                if policy is None:
                    raise ValueError("Projection requires an existing tenant user policy")
            for request_id, event in sorted(merged.items()):
                current = self.session.scalar(
                    select(DshModelCall).where(DshModelCall.request_id == request_id).with_for_update()
                )
                if current is not None:
                    immutable = (
                        "tenant_id",
                        "user_id",
                        "model_id",
                        "usage_month",
                        "seat_id",
                        "session_id",
                        "quota_epoch",
                        "policy_version",
                        "grant_version",
                    )
                    if any(getattr(current, k) != getattr(event, k) for k in immutable):
                        raise ValueError("Request identity and admission ownership are immutable")
                    if event.event_version == current.event_version:
                        fields = (
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "status",
                            "usage_source",
                            "provider_request_id",
                            "error_code",
                            "latency_ms",
                        )
                        if any(getattr(current, key) != getattr(event, key) for key in fields):
                            raise ValueError("Conflicting persisted payload for the same event version")
                    if event.event_version <= current.event_version:
                        continue
                    if current.total_tokens is not None:
                        raise ValueError("Reliable settlement is immutable")
                    if current.status == "USAGE_UNKNOWN" and event.status == "RUNNING":
                        raise ValueError("Request state cannot regress")
                payload = event.model_dump(
                    exclude={"billing_timezone", "operation_id", "payload_hash", "operation_generation"}
                )
                if current is None:
                    current = DshModelCall(**payload)
                    self.session.add(current)
                else:
                    for key, value in payload.items():
                        setattr(current, key, value)
                if event.total_tokens is not None:
                    key = (event.user_id, event.usage_month, event.model_id)
                    deltas[key] += event.total_tokens
                    timezones[key] = event.billing_timezone
                changed += 1
            for (user_id, month, model_id), delta in sorted(deltas.items()):
                rows = list(
                    self.session.scalars(
                        select(DshMonthlyUsage)
                        .where(
                            DshMonthlyUsage.user_id == user_id,
                            DshMonthlyUsage.usage_month == month,
                            DshMonthlyUsage.model_id == model_id,
                        )
                        .with_for_update()
                    )
                )
                row = next((r for r in rows if r.tenant_id == tenant), None)
                if row is None:
                    row = DshMonthlyUsage(
                        tenant_id=tenant,
                        user_id=user_id,
                        usage_month=month,
                        model_id=model_id,
                        billing_timezone=timezones[(user_id, month, model_id)],
                    )
                    self.session.add(row)
                row.used_tokens += delta
                row.version += 1
                row.projected_at = datetime.now(UTC).replace(tzinfo=None)
            self.session.flush()
        return changed

    def unresolved(self, user_id: int) -> list[DshModelCall]:
        with strict_tenant_filter():
            rows = self.session.scalars(
                select(DshModelCall).where(
                    DshModelCall.user_id == user_id, DshModelCall.status.in_(["RUNNING", "USAGE_UNKNOWN"])
                )
            )
            return [row for row in rows if row.tenant_id == get_current_tenant_id()]

    def recovery_snapshot(self, user_id: int, *, billing_timezone: str) -> tuple[list[UsageEvent], dict]:
        """Read all retained state; refuse partial inventories and summaries without supporting calls."""
        import json

        tenant = get_current_tenant_id()
        with strict_tenant_filter():
            policy = DshPolicyRepository(self.session).get(user_id)
            if policy is None:
                raise ValueError("Recovery requires a current SQL user policy")
            calls = []
            after_id = ""
            while True:
                page = list(
                    self.session.scalars(
                        select(DshModelCall)
                        .where(
                            DshModelCall.tenant_id == tenant,
                            DshModelCall.user_id == user_id,
                            DshModelCall.request_id > after_id,
                        )
                        .order_by(DshModelCall.request_id)
                        .limit(500)
                    )
                )
                if not page:
                    break
                calls.extend(page)
                after_id = page[-1].request_id
            totals = [
                row
                for row in self.session.scalars(select(DshMonthlyUsage).where(DshMonthlyUsage.user_id == user_id))
                if row.tenant_id == tenant
            ]
        sql_totals = {(row.usage_month, row.model_id): row.used_tokens for row in totals}
        calculated = {}
        events = []
        for row in calls:
            if row.total_tokens is not None:
                key = (row.usage_month, row.model_id)
                calculated[key] = calculated.get(key, 0) + row.total_tokens
            data = {key: value for key, value in row.model_dump().items() if key in UsageEvent.model_fields}
            data["billing_timezone"] = next(
                (item.billing_timezone for item in totals if item.usage_month == row.usage_month), billing_timezone
            )
            data["operation_id"] = row.reconciliation_operation_id if row.usage_source == "RECONCILED" else None
            events.append(UsageEvent.model_validate_json(json.dumps(data)))
        if calculated != sql_totals:
            raise ValueError("SQL summary cannot be reconstructed from retained request evidence")
        return events, policy.recovery_payload()

    def complete_recovery(self, user_id: int, *, expected_policy: dict, epoch: int):
        """Publish the recovered epoch only if policy authority has not changed during IO."""
        repository = DshPolicyRepository(self.session)
        current = repository.get(user_id, lock=True)
        if current is None or current.recovery_payload() != expected_policy:
            raise ValueError("SQL policy changed during controlled recovery")
        if epoch < current.quota_epoch:
            raise ValueError("Recovery cannot move the policy epoch backwards")
        for row in repository.rows(user_id):
            row.quota_epoch = epoch
            row.quota_sync_state = "PENDING" if row.pending_operation_id else "READY"
        self.session.flush()

    def unknown_pending(self, user_id: int) -> int:
        with strict_tenant_filter():
            return self.session.scalar(
                select(func.count())
                .select_from(DshModelCall)
                .where(
                    DshModelCall.tenant_id == get_current_tenant_id(),
                    DshModelCall.user_id == user_id,
                    DshModelCall.status == "USAGE_UNKNOWN",
                )
            )

    def persisted_usage(self, user_id: int, usage_month: str) -> dict:
        tenant = get_current_tenant_id()
        with strict_tenant_filter():
            rows = [
                row
                for row in self.session.scalars(
                    select(DshMonthlyUsage).where(
                        DshMonthlyUsage.user_id == user_id, DshMonthlyUsage.usage_month == usage_month
                    )
                )
                if row.tenant_id == tenant
            ]
            policies = [
                row
                for row in self.session.scalars(select(DshUserPolicy).where(DshUserPolicy.user_id == user_id))
                if row.tenant_id == tenant
            ]
            unknown_pending = self.unknown_pending(user_id)
        if not rows or not policies or any(row.projected_at is None for row in rows):
            raise ValueError("No trustworthy persisted usage snapshot exists")
        used = sum(row.used_tokens for row in rows)
        model_limits = {str(row.model_id): row.monthly_token_limit for row in policies if row.enabled}
        models = {str(row.model_id): row.used_tokens for row in rows}
        limit = sum(model_limits.values())
        return {
            "used": used,
            "limit": limit,
            "remaining": sum(max(allowed - models.get(model, 0), 0) for model, allowed in model_limits.items()),
            "model_limits": model_limits,
            "source": "sql_estimate",
            "unknown_pending": unknown_pending,
            "as_of": max(row.projected_at for row in rows),
            "quota_state": "unavailable",
            "models": {str(row.model_id): row.used_tokens for row in rows},
        }

    def new_month_proof(self, user_id: int, usage_month: str) -> dict:
        tenant = get_current_tenant_id()
        with strict_tenant_filter():
            calls = [
                row
                for row in self.session.scalars(
                    select(DshModelCall)
                    .where(DshModelCall.user_id == user_id, DshModelCall.usage_month == usage_month)
                    .limit(1)
                )
                if row.tenant_id == tenant
            ]
            totals = [
                row
                for row in self.session.scalars(
                    select(DshMonthlyUsage)
                    .where(DshMonthlyUsage.user_id == user_id, DshMonthlyUsage.usage_month == usage_month)
                    .limit(1)
                )
                if row.tenant_id == tenant
            ]
            policies = [
                row
                for row in self.session.scalars(select(DshUserPolicy).where(DshUserPolicy.user_id == user_id))
                if row.tenant_id == tenant
            ]
        if calls or totals or not policies:
            raise ValueError("Month history is not proven empty")
        policy = DshPolicyRepository(self.session).get(user_id)
        return {
            "tenant_id": tenant,
            "user_id": user_id,
            "usage_month": usage_month,
            "history_empty": True,
            "policy_version": policy.version,
            "model_configs": model_configs_payload(policy.model_configs),
        }
