"""Safely re-dispatch recoverable approval decision outbox events.

This script repairs terminal approval decisions that were committed to
``approval_decision_outbox`` but were not consumed because an older worker
claimed a different event. It never edits approval or business tables. The
default mode is a read-only dry-run; ``--apply`` publishes one exact
``tenant_id + event_id`` message per eligible row to the normal Celery queue.

Run from ``src/backend/`` with the same config as the deployed services::

    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/recover_approval_decision_events.py \
      --tenant-id 1 --scenario knowledge_space_file_change_request
    PYTHONPATH=./ .venv/bin/python scripts/recover_approval_decision_events.py \
      --tenant-id 1 --event-id 123 124 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import select

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.approval.domain.models.approval_decision_outbox import (  # noqa: E402
    ApprovalDecisionOutbox,
    ApprovalDecisionOutboxStatus,
)
from bisheng.approval.domain.models.approval_instance import ApprovalInstance  # noqa: E402
from bisheng.approval.domain.services.approval_decision_delivery_service import (  # noqa: E402
    ApprovalDecisionDeliveryService,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id  # noqa: E402
from bisheng.core.database import get_async_db_session, get_database_connection  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (  # noqa: E402
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber import (  # noqa: E402
    KnowledgeSpaceFileChangeDecisionSubscriber,
)
from bisheng.permission.domain.models.resource_user_invite_request import (  # noqa: E402
    RESOURCE_USER_INVITE_SCENARIO_CODE,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.services.resource_user_invite_decision_subscriber import (  # noqa: E402
    ResourceUserInviteDecisionSubscriber,
)

SUPPORTED_SCENARIOS = (
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    RESOURCE_USER_INVITE_SCENARIO_CODE,
)
MAX_BATCH_SIZE = 500
EXIT_VALIDATION_SKIPPED = 3
EXIT_DISPATCH_FAILED = 4


@dataclass(frozen=True, slots=True)
class Candidate:
    tenant_id: int
    event_id: int
    instance_id: int
    scenario_code: str
    business_request_id: str
    decision: str
    outbox_status: str
    retry_count: int
    approval_status: str | None = None
    business_execution_state: str | None = None
    recorded_decision_event_id: int | None = None


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate: Candidate
    result: str
    reason: str | None = None
    task_id: str | None = None


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _print_record(record_type: str, payload: dict[str, Any]) -> None:
    print(json.dumps({"type": record_type, **payload}, ensure_ascii=False, default=_json_default))


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _batch_size(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError(f"value must not exceed {MAX_BATCH_SIZE}")
    return parsed


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO-8601 datetime") from error
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _recoverable_condition(now: datetime):
    return or_(
        and_(
            ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PENDING,
            or_(
                ApprovalDecisionOutbox.next_retry_at.is_(None),
                ApprovalDecisionOutbox.next_retry_at <= now,
            ),
        ),
        and_(
            ApprovalDecisionOutbox.status == ApprovalDecisionOutboxStatus.PROCESSING,
            ApprovalDecisionOutbox.claim_deadline <= now,
        ),
    )


def _is_recoverable(row: ApprovalDecisionOutbox, now: datetime) -> tuple[bool, str | None]:
    if row.status == ApprovalDecisionOutboxStatus.PENDING:
        if row.next_retry_at is None or row.next_retry_at <= now:
            return True, None
        return False, "retry_not_due"
    if row.status == ApprovalDecisionOutboxStatus.PROCESSING:
        if row.claim_deadline is not None and row.claim_deadline <= now:
            return True, None
        return False, "active_processing_lease"
    return False, f"outbox_status_{row.status}"


def _candidate(
    row: ApprovalDecisionOutbox,
    instance: ApprovalInstance | None = None,
    business_request: KnowledgeSpaceFileChangeRequest | ResourceUserInviteRequest | None = None,
) -> Candidate:
    return Candidate(
        tenant_id=int(row.tenant_id),
        event_id=int(row.id),
        instance_id=int(row.instance_id),
        scenario_code=str(row.scenario_code),
        business_request_id=str(row.business_request_id),
        decision=str(row.decision),
        outbox_status=str(row.status),
        retry_count=int(row.retry_count),
        approval_status=str(instance.status) if instance is not None else None,
        business_execution_state=(
            str(business_request.execution_state) if business_request is not None else None
        ),
        recorded_decision_event_id=(
            int(business_request.decision_event_id)
            if business_request is not None and business_request.decision_event_id is not None
            else None
        ),
    )


async def _load_business_request(session, row: ApprovalDecisionOutbox):
    try:
        request_id = int(row.business_request_id)
    except (TypeError, ValueError):
        return None
    model = {
        KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE: KnowledgeSpaceFileChangeRequest,
        RESOURCE_USER_INVITE_SCENARIO_CODE: ResourceUserInviteRequest,
    }.get(str(row.scenario_code))
    if model is None:
        return None
    statement = select(model).where(model.id == request_id, model.tenant_id == int(row.tenant_id))
    return (await session.exec(statement)).first()


def _validate_candidate(
    row: ApprovalDecisionOutbox,
    instance: ApprovalInstance | None,
    business_request: KnowledgeSpaceFileChangeRequest | ResourceUserInviteRequest | None,
) -> str | None:
    if instance is None:
        return "approval_instance_missing"
    if int(instance.tenant_id or 0) != int(row.tenant_id or 0):
        return "approval_instance_tenant_mismatch"
    if str(instance.scenario_code) != str(row.scenario_code):
        return "approval_instance_scenario_mismatch"
    if str(instance.business_resource_type) != str(row.business_request_type):
        return "approval_instance_business_type_mismatch"
    if str(instance.business_resource_id) != str(row.business_request_id):
        return "approval_instance_business_id_mismatch"
    if str(instance.business_key) != str(row.business_key):
        return "approval_instance_business_key_mismatch"
    if str(instance.status) != str(row.decision):
        return f"approval_instance_not_terminal_decision:{instance.status}"
    if business_request is None:
        return "business_request_missing"

    event = ApprovalDecisionDeliveryService._build_event(row)
    shadow = type(business_request).model_validate(business_request.model_dump())
    try:
        if row.scenario_code == KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE:
            subscriber = KnowledgeSpaceFileChangeDecisionSubscriber
            subscriber._validate_event_envelope(event)
            subscriber._validate_binding(shadow, event)
            if shadow.decision_event_id is None:
                subscriber._accept_first_event(shadow, event)
            else:
                subscriber._accept_repeated_event(shadow, event)
        elif row.scenario_code == RESOURCE_USER_INVITE_SCENARIO_CODE:
            subscriber = ResourceUserInviteDecisionSubscriber
            subscriber._validate_event_envelope(event)
            subscriber._validate_binding(shadow, event)
            if shadow.decision_event_id is None:
                subscriber._accept_first_event(shadow, event)
            else:
                subscriber._validate_repeated_event(shadow, event)
        else:
            return "unsupported_scenario"
    except Exception as error:
        return f"subscriber_validation_failed:{str(error) or type(error).__name__}"
    return None


async def _scan_tenant(args: argparse.Namespace, tenant_id: int, now: datetime) -> list[CandidateResult]:
    tenant_token = set_current_tenant_id(tenant_id)
    try:
        async with get_async_db_session() as session:
            statement = select(ApprovalDecisionOutbox).where(
                ApprovalDecisionOutbox.tenant_id == tenant_id,
                ApprovalDecisionOutbox.scenario_code.in_(args.scenario),
            )
            if args.event_id:
                statement = statement.where(ApprovalDecisionOutbox.id.in_(args.event_id))
            else:
                statement = statement.where(_recoverable_condition(now))
            if args.decided_after is not None:
                statement = statement.where(ApprovalDecisionOutbox.decided_at >= args.decided_after)
            if args.decided_before is not None:
                statement = statement.where(ApprovalDecisionOutbox.decided_at < args.decided_before)
            statement = statement.order_by(ApprovalDecisionOutbox.id.asc()).limit(args.limit)
            rows = list((await session.exec(statement)).all())

            results: list[CandidateResult] = []
            for row in rows:
                instance_statement = select(ApprovalInstance).where(
                    ApprovalInstance.id == int(row.instance_id),
                    ApprovalInstance.tenant_id == tenant_id,
                )
                instance = (await session.exec(instance_statement)).first()
                business_request = await _load_business_request(session, row)
                candidate = _candidate(row, instance, business_request)
                recoverable, reason = _is_recoverable(row, now)
                if not recoverable:
                    results.append(CandidateResult(candidate=candidate, result="skipped", reason=reason))
                    continue
                reason = _validate_candidate(row, instance, business_request)
                results.append(
                    CandidateResult(
                        candidate=candidate,
                        result="eligible" if reason is None else "skipped",
                        reason=reason,
                    )
                )
            return results
    finally:
        current_tenant_id.reset(tenant_token)


def _load_delivery_task():
    from bisheng.worker.approval.decision_delivery_tasks import deliver_approval_decision

    parameters = inspect.signature(deliver_approval_decision.run).parameters
    if "event_id" not in parameters:
        raise RuntimeError("deployed approval decision task does not support exact event_id delivery")
    return deliver_approval_decision


def _dispatch(result: CandidateResult, task) -> CandidateResult:
    candidate = result.candidate
    published = task.apply_async(
        args=[candidate.event_id],
        headers={"tenant_id": candidate.tenant_id},
    )
    task_id = getattr(published, "id", None)
    return CandidateResult(
        candidate=candidate,
        result="dispatched",
        task_id=str(task_id) if task_id is not None else None,
    )


async def run(args: argparse.Namespace) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    all_results: list[CandidateResult] = []
    for tenant_id in sorted(set(args.tenant_id)):
        all_results.extend(await _scan_tenant(args, tenant_id, now))

    task = _load_delivery_task() if args.apply and any(row.result == "eligible" for row in all_results) else None
    final_results: list[CandidateResult] = []
    dispatch_failed = 0
    for result in all_results:
        final = result
        if result.result == "eligible" and args.apply:
            try:
                final = _dispatch(result, task)
            except Exception as error:
                dispatch_failed += 1
                final = CandidateResult(
                    candidate=result.candidate,
                    result="dispatch_failed",
                    reason=str(error) or type(error).__name__,
                )
        final_results.append(final)
        _print_record("event", {**asdict(final.candidate), "result": final.result, "reason": final.reason, "task_id": final.task_id})

    eligible = sum(result.result == "eligible" for result in final_results)
    dispatched = sum(result.result == "dispatched" for result in final_results)
    skipped = sum(result.result == "skipped" for result in final_results)
    _print_record(
        "summary",
        {
            "mode": "apply" if args.apply else "dry_run",
            "scanned": len(final_results),
            "eligible": eligible,
            "dispatched": dispatched,
            "skipped": skipped,
            "dispatch_failed": dispatch_failed,
        },
    )
    if dispatch_failed:
        return EXIT_DISPATCH_FAILED
    if skipped:
        return EXIT_VALIDATION_SKIPPED
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        type=_positive_int,
        action="append",
        required=True,
        help="tenant to inspect; repeat for more tenants",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=SUPPORTED_SCENARIOS,
        default=None,
        help="scenario to inspect; default: both supported decision-delivery scenarios",
    )
    parser.add_argument(
        "--event-id",
        type=_positive_int,
        nargs="+",
        default=None,
        help="explicit outbox event IDs; non-recoverable rows are reported and skipped",
    )
    parser.add_argument("--decided-after", type=_utc_datetime, help="inclusive ISO-8601 decision time")
    parser.add_argument("--decided-before", type=_utc_datetime, help="exclusive ISO-8601 decision time")
    parser.add_argument("--limit", type=_batch_size, default=100, help=f"maximum rows per tenant (1-{MAX_BATCH_SIZE})")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="publish exact event deliveries to the default Celery queue (default: dry-run)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.scenario is None:
        args.scenario = list(SUPPORTED_SCENARIOS)
    if args.decided_after and args.decided_before and args.decided_after >= args.decided_before:
        parser.error("--decided-after must be earlier than --decided-before")
    async def _main() -> int:
        try:
            return await run(args)
        finally:
            database = await get_database_connection()
            await database.close()

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
