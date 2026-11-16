"""Department Owner execution and recovery of an unchanged original intent."""

import json
import time
from contextlib import AsyncExitStack

from loguru import logger
from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import exact_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.database.query_statistics import query_statistics
from bisheng.database.models.department import Department
from bisheng.department.domain.repositories.current_repair_repository import CurrentDepartmentRepairRepository
from bisheng.department.domain.services.current_projection_repair import CurrentDepartmentRepairService
from bisheng.permission.application.department_recovery import (
    KNOWN_EFFECTS,
    archive_owned_key,
    emit_projection_alert,
    owned_key,
    projection_state_expectations,
    reason_from_exception,
    relation_diagnostics,
    target_keys,
)


def validate_original_target(plan, observed, target):
    """Require the full current target and all drift to be original effects."""
    owns = archive_owned_key if plan.operation_type == "DEPARTMENT_ARCHIVE" else owned_key
    if (
        plan.operation_type not in KNOWN_EFFECTS
        or plan.operation_type == "DEPARTMENT_RECONCILE"
        or not plan.deltas
        or any(d.phase != "COMMIT" or not owns(d.key, int(plan.scope_key)) for d in plan.deltas)
    ):
        raise ValueError("UNPROVEN_ORIGINAL_EFFECTS")
    expected = projection_state_expectations(plan.deltas, after=True)
    if any((key in target) != exists for key, exists in expected.items()):
        raise ValueError("ORIGINAL_TARGET_NO_LONGER_CURRENT")
    if (set(observed) ^ set(target)) - expected.keys():
        raise ValueError("DRIFT_OUTSIDE_ORIGINAL_EFFECTS")


class DepartmentProjectionExecutor:
    """One SQL UOW for D, ledger and audit; lease is an additional fence.

    Composition injects permission ports, scoped relation reader, catalog reader
    and lease factory. The domain never constructs Celery or an FGA client.
    """

    def __init__(
        self,
        *,
        ledger,
        scope,
        lease_factory,
        observed,
        environment,
        audit,
        business_environment=None,
        dispatch=None,
        write_gate=None,
        archive_obligations=None,
        session_factory=get_async_db_session,
    ):
        self.ledger, self.scope = ledger, scope
        self.lease_factory, self.observed, self.environment = lease_factory, observed, environment
        self.audit, self.dispatch, self.sessions = audit, dispatch, session_factory
        self.archive_obligations = archive_obligations
        self.business_environment = business_environment or environment
        self.write_gate = write_gate
        self.repository = CurrentDepartmentRepairRepository(session_factory)
        self.business = CurrentDepartmentRepairService(self.repository)

    async def execute(self, operation_id, plan=None):
        started = time.monotonic()
        with query_statistics() as statistics:
            try:
                return await self._execute(operation_id, plan)
            finally:
                logger.info(
                    "PERMISSION_PROJECTION_RUN {}",
                    json.dumps(
                        {
                            "operation_id": operation_id,
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                            **statistics.summary(),
                        },
                        sort_keys=True,
                    ),
                )

    async def _execute(self, operation_id, plan=None):
        original_supplied = plan is not None
        # Identity read is strict in the caller's selected tenant, including SSO.
        if plan is None:
            operation, plan = await self.ledger.department_plan(operation_id)
        with exact_tenant_filter(plan.tenant_id):
            lease_acquired = False
            diagnostics = {
                "expected_version": plan.expected_version,
                "target_version": plan.target_version,
                "store_id": plan.store_id,
                "model_id": plan.model_id,
                "mode": "BUSINESS_PROJECTION" if original_supplied else "AUTO_ORIGINAL",
            }
            try:
                async with self.lease_factory(plan.tenant_id, int(plan.scope_key)) as lease:
                    lease_acquired = True
                    async with self.sessions() as session:
                        async with session.begin():
                            # Consistent lock order: Catalog, D, operation, ancestors.
                            read_environment = self.business_environment if original_supplied else self.environment
                            pin = await read_environment(session)
                            if (plan.store_id, plan.model_id) != pin:
                                raise PermissionPublishNotReadyError(msg="OPERATION_MODEL_PIN_MISMATCH")
                            async with AsyncExitStack() as stack:
                                await stack.enter_async_context(self.scope.bind_session(session, operation_id))
                                await stack.enter_async_context(
                                    self.ledger.department_uow(
                                        session, guard=lease.verify_owned, write_gate=self.write_gate
                                    )
                                )
                                row = (
                                    await session.exec(
                                        select(Department)
                                        .where(
                                            Department.id == int(plan.scope_key),
                                        )
                                        .with_for_update()
                                    )
                                ).first()
                                if row is None or row.permission_projection_operation_id != operation_id:
                                    raise PermissionPublishNotReadyError(msg="Department binding changed")
                                active_ids = await self.ledger.department_active_ids(int(plan.scope_key))
                                if any(identity != operation_id for identity in active_ids):
                                    raise PermissionPublishNotReadyError(msg="OTHER_ACTIVE_DEPARTMENT_OPERATION")
                                operation, durable = await self.ledger.department_plan(operation_id)
                                if durable != plan:
                                    raise PermissionPublishNotReadyError(msg="Original request changed")
                                state, version = row.permission_projection_state, row.permission_projection_version
                                diagnostics.update(
                                    current_state=state,
                                    current_version=version,
                                    operation_status=str(operation.status),
                                    actual_parent_id=row.parent_id,
                                )
                                final = version == plan.target_version and state in {"CURRENT", "FAILED_CLOSED"}
                                if operation.status == "FINALIZED" and (
                                    state != "CURRENT" or version != plan.target_version
                                ):
                                    raise PermissionPublishNotReadyError(msg="FINALIZED_BINDING_INCONSISTENT")
                                if not (
                                    version == plan.expected_version and state in {"PROJECTING", "FAILED_CLOSED"}
                                ) and not (final and operation.status in {"COMMITTED", "FINALIZED"}):
                                    raise PermissionPublishNotReadyError(msg="Department version changed")

                                protected_error = None
                                normal_projection = (
                                    original_supplied and state == "PROJECTING" and operation.status == "PREPARED"
                                )
                                if normal_projection:
                                    # The synchronous business Owner already verified this new
                                    # mutation. Preserve its existing delta/cleanup contract;
                                    # recovery of a failed original intent is more restrictive.
                                    # Recovery throttling must not delay healthy online writes.
                                    # Keep the same borrowed SQL session and lease guard.
                                    async with self.ledger.department_uow(session, guard=lease.verify_owned):
                                        outcome = await self.ledger.execute(plan)
                                    await self.audit(session, plan, operation_id, "finalized", "BUSINESS_PROJECTION")
                                else:

                                    async def verify(p, op):
                                        await lease.verify_owned()
                                        pin = await self.environment(session)
                                        diagnostics.update(current_store_id=pin[0], current_model_id=pin[1])
                                        if (p.store_id, p.model_id) != pin:
                                            raise PermissionPublishNotReadyError(msg="OPERATION_MODEL_PIN_MISMATCH")
                                        dept = await self.repository.get(int(p.scope_key), session=session, lock=True)
                                        if dept["operation_id"] != operation_id or dept["version"] != version:
                                            raise PermissionPublishNotReadyError(
                                                msg="Department binding/version changed"
                                            )
                                        if dept["status"] == "archived" and dept["deleted"] == 1:
                                            # Archive is only resumed when Owner cleanup obligations are empty.
                                            if self.archive_obligations is None:
                                                raise PermissionPublishNotReadyError(
                                                    msg="ARCHIVE_OWNER_CLEANUP_REQUIRED"
                                                )
                                            await self.archive_obligations(session, dept)
                                            members = await self.repository.members(
                                                dept["id"], session=session, lock=True
                                            )
                                            if members or p.operation_type not in {
                                                "DEPARTMENT_ARCHIVE",
                                                "DEPARTMENT_PARENT_REMOVE",
                                            }:
                                                raise PermissionPublishNotReadyError(
                                                    msg="ARCHIVE_OWNER_CLEANUP_REQUIRED"
                                                )
                                            target = frozenset()
                                        else:
                                            proof = await self.business.prove(dept, session=session, lock=True)
                                            ancestors = await self.repository.ancestors(
                                                dept, session=session, lock=True
                                            )
                                            if any(a["state"] != "CURRENT" for a in ancestors):
                                                raise PermissionPublishNotReadyError(msg="ANCESTOR_NOT_CURRENT")
                                            target = target_keys(dept, proof["direct_members"])
                                        present = await self.observed(
                                            dept["id"], include_admin=dept["status"] == "archived"
                                        )
                                        diagnostics.update(relation_diagnostics(present, target))
                                        if op.status in {"COMMITTED", "FINALIZED"} and present != target:
                                            # Still require the old target to agree with business facts.
                                            validate_original_target(p, target, target)
                                            raise PermissionPublishNotReadyError(msg="COMMITTED_AFTER_STATE_MISSING")
                                        validate_original_target(p, present, target)
                                        return present

                                    # Protect a historical CURRENT+COMMITTED hole before returning manual.
                                    try:
                                        await verify(plan, operation)
                                    except PermissionPublishNotReadyError as error:
                                        if (
                                            final
                                            and operation.status == "COMMITTED"
                                            and "COMMITTED_AFTER_STATE_MISSING" in str(error)
                                        ):
                                            row.permission_projection_state = "FAILED_CLOSED"
                                            session.add(row)
                                            await self.audit(
                                                session, plan, operation_id, "failed", "COMMITTED_AFTER_STATE_MISSING"
                                            )
                                            await session.flush()
                                            protected_error = error
                                        else:
                                            raise
                                    else:
                                        protected_error = None
                                    if protected_error is None:
                                        if state == "FAILED_CLOSED" and not final:
                                            row.permission_projection_state = "PROJECTING"
                                            session.add(row)
                                            await session.flush()
                                        outcome = await self.ledger.recover_department_operation(
                                            operation_id, verify_owner=verify
                                        )
                                        await self.audit(session, plan, operation_id, "finalized", None)
                        # SQL commit precedes success evidence and outcome.
                    if protected_error is not None:
                        raise protected_error
                    async with self.sessions() as check:
                        current = await self.repository.get(int(plan.scope_key), session=check)
                        if (
                            current["state"] != "CURRENT"
                            or current["version"] != plan.target_version
                            or current["operation_id"] != operation_id
                        ):
                            raise PermissionPublishNotReadyError(msg="SQL_COMMIT_NOT_VERIFIED")
                    if await self.ledger.department_needs_recovery(operation_id):
                        raise PermissionPublishNotReadyError(msg="SQL_COMMIT_NOT_VERIFIED")
                    emit_projection_alert(
                        "PROJECTED" if normal_projection else "RECOVERED",
                        reason_code="RESTORED_AFTER_VERIFIED",
                        tenant_id=plan.tenant_id,
                        department_id=int(plan.scope_key),
                        operation_id=operation_id,
                        details=diagnostics
                        | {
                            "current_state": "CURRENT",
                            "current_version": plan.target_version,
                            "contained": False,
                            "phase": "sql_readback",
                        },
                    )
                    return outcome
            except Exception as error:
                details = getattr(error, "details", {})
                for ancestor in details.get("chain", []):
                    if (
                        ancestor.get("status") != "active"
                        or ancestor.get("deleted")
                        or ancestor.get("state") != "CURRENT"
                    ):
                        diagnostics.update(
                            ancestor_id=ancestor.get("id"),
                            ancestor_status=ancestor.get("status"),
                            ancestor_deleted=ancestor.get("deleted"),
                            ancestor_projection_state=ancestor.get("state"),
                        )
                        break
                chain = details.get("chain", [])
                if chain and len(chain) <= 100:
                    diagnostics["actual_path"] = chain[0].get("path")
                    diagnostics["expected_path"] = "/" + "/".join(str(item["id"]) for item in reversed(chain)) + "/"
                diagnostics.update(exception_type=type(error).__name__, phase="execution", contained=None)
                emit_projection_alert(
                    "FAILED" if original_supplied else "MANUAL_REQUIRED",
                    reason_code=reason_from_exception(error),
                    tenant_id=plan.tenant_id,
                    department_id=int(plan.scope_key),
                    operation_id=operation_id,
                    details=diagnostics,
                )
                if not lease_acquired:
                    raise
                # The remote FGA may already be AFTER. Keep durable gate on any
                # failed SQL commit; a later run verifies rather than blind replay.
                async with self.sessions() as failure:
                    async with failure.begin():
                        await failure.execute(
                            update(Department)
                            .where(
                                Department.id == int(plan.scope_key),
                                Department.tenant_id == plan.tenant_id,
                                Department.permission_projection_operation_id == operation_id,
                                Department.permission_projection_version == plan.expected_version,
                                Department.permission_projection_state == "PROJECTING",
                            )
                            .values(permission_projection_state="FAILED_CLOSED")
                        )
                if self.dispatch is not None:
                    await self.dispatch(plan.tenant_id, int(plan.scope_key), operation_id)
                raise
