"""反向运行的事务、领取和终态。"""

from hashlib import sha256
from time import time
from uuid import uuid4

from loguru import logger
from sqlalchemy import null, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.common.errcode.flow import WorkflowRegistrationConflict, WorkflowRegistrationDenied
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun as Run
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import (
    RUN_EVENT_SECONDS,
    RunControl,
    RunError,
    execution_material,
    read_run_control,
    validate_interaction_input,
)
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest

_PHASE_TIMEOUTS = {
    "QUEUED": "QUEUE_TIMEOUT",
    "RUNNING": "EXECUTION_TIMEOUT",
    "WAITING_INPUT": "INPUT_TIMEOUT",
    "RESUME_QUEUED": "RESUME_QUEUE_TIMEOUT",
    "RESUMING": "RESUME_EXECUTION_TIMEOUT",
}
_ACTIVE_CLAIM = {"RUNNING", "RESUMING"}
_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
_RUN_EVENTS = {
    "RUNNING": "STARTED",
    "WAITING_INPUT": "WAITING_INPUT",
    "RESUME_QUEUED": "RESUME_QUEUED",
    "RESUMING": "RESUMED",
    "CANCEL_REQUESTED": "CANCEL_ACCEPTED",
    "CANCELLED": "CANCELLED",
    "SUCCEEDED": "SUCCEEDED",
    "FAILED": "FAILED",
}


class RunRepository:
    def __init__(
        self,
        registration,
        *,
        clock=time,
        queue_seconds=60,
        run_seconds=60,
        retain_seconds=3600,
        wait_seconds=900,
        max_active_per_user=None,
    ):
        self.registration = registration
        self.clock = clock
        # TODO [F122][EXT-03] 正式执行时限、重试与结果保留窗口待确认。
        self.queue_seconds = queue_seconds
        self.run_seconds = run_seconds
        self.retain_seconds = retain_seconds
        # TODO [F123][EXT-03] 确认等待、恢复排队和执行窗口。
        self.wait_seconds = wait_seconds
        if max_active_per_user is not None and (
            type(max_active_per_user) is not int or not 1 <= max_active_per_user <= 1000
        ):
            raise ValueError("max_active_per_user must be an integer in [1, 1000]")
        self.max_active_per_user = max_active_per_user

    @staticmethod
    def _lock_formal_user(session, scope, user_id):
        # User is global (has no tenant_id). Lock the trusted existing person,
        # then verify the selected active membership, never invent a quota owner.
        from bisheng.database.models.tenant import UserTenant
        from bisheng.user.domain.models.user import User

        user = session.exec(select(User).where(User.user_id == user_id).with_for_update()).first()
        if user is None or user.delete != 0:
            raise RunError("FORBIDDEN")
        memberships = session.exec(select(UserTenant).where(UserTenant.user_id == user_id).with_for_update()).all()
        if not any(row.tenant_id == scope.tenant_id and row.status == "active" for row in memberships):
            raise RunError("FORBIDDEN")

    def _check_formal_quota(self, session, scope, user_id):
        from bisheng.common.errcode.open_api import OpenApiKunlianRateLimitedError

        # A locking/current read avoids an older MySQL REPEATABLE READ snapshot
        # created by replay/version reads. User lock serializes admissions across
        # *all* workflows; Flow lock alone cannot provide this guarantee.
        rows = session.exec(
            select(Run)
            .where(
                build_tenant_filter_clause(Run.tenant_id),
                Run.connection_id == scope.connection_id,
                Run.user_id == user_id,
                Run.status.notin_(_TERMINAL),
            )
            .with_for_update()
        ).all()
        active = sum(
            row.tenant_id == scope.tenant_id
            and isinstance(row.material, dict)
            and row.material.get("runtime_contract") == "published-workflow"
            and isinstance(row.material.get("kunlian_identity"), dict)
            for row in rows
        )
        if active >= self.max_active_per_user:
            raise OpenApiKunlianRateLimitedError()

    @staticmethod
    def _by_key(session, scope, user_id, key):
        stmt = select(Run).where(
            build_tenant_filter_clause(Run.tenant_id),
            Run.connection_id == scope.connection_id,
            Run.user_id == user_id,
            Run.key_digest == key,
        )
        row = session.exec(stmt).first()
        if row is not None and row.connection_id != scope.connection_id:
            raise RunError("FORBIDDEN")
        return row

    def is_expired(self, row):
        return row.expires_at is not None and row.expires_at <= int(self.clock())

    def _replay(self, row, digest):
        if row.request_digest != digest:
            raise RunError("IDEMPOTENCY_CONFLICT")
        if self.is_expired(row):
            raise RunError("IDEMPOTENCY_EXPIRED")
        return Run.model_validate(row), False

    def verify_target(self, tenant_id, workflow_id):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            self.registration.invocation_flow(session, tenant_id, workflow_id)

    def admit(
        self,
        scope,
        user_id,
        key,
        body,
        *,
        run_control=False,
        identity=None,
        allow_platform_agent=False,
        extra_material=None,
    ):
        key_digest = sha256(key.encode()).hexdigest()
        digest = canonical_digest(body.model_dump(exclude={"mode"} if body.mode is None else None))
        from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository

        formal_quota = (
            self.max_active_per_user is not None
            and identity is not None
            and isinstance(self.registration, PublishedRunRegistrationRepository)
        )
        with tenant_execution_scope(scope.tenant_id):
            with self.registration.transaction() as session:
                row = self._by_key(session, scope, user_id, key_digest)
                if row is not None:
                    return self._replay(row, digest)
            try:
                with self.registration.transaction() as session:
                    if formal_quota:
                        self._lock_formal_user(session, scope, user_id)
                    flow = self.registration.invocation_flow(session, scope.tenant_id, body.workflow_id, lock=True)
                    # Formal admission locks User before Flow across workflows.
                    # Candidate idempotency remains protected by the unique key.
                    row = self._by_key(session, scope, user_id, key_digest)
                    if row is not None:
                        return self._replay(row, digest)
                    graph, descriptor = self.registration.invocation_version(
                        session, scope, flow, body.workflow_version_id
                    )
                    material = execution_material(
                        graph,
                        descriptor,
                        body.input,
                        body.mode,
                        allow_platform_agent=allow_platform_agent,
                    )
                    if isinstance(extra_material, dict) and extra_material:
                        material.update(extra_material)
                    if identity is not None:
                        material["kunlian_identity"] = identity
                    if formal_quota:
                        self._check_formal_quota(session, scope, user_id)
                    now = int(self.clock())
                    if run_control:
                        control = RunControl(trace_id=uuid4().hex)
                        control.append(now, "ACCEPTED", "QUEUED")
                        material["run_control"] = control.model_dump()
                    row = Run(
                        session_id=uuid4().hex,
                        tenant_id=scope.tenant_id,
                        connection_id=scope.connection_id,
                        user_id=user_id,
                        workflow_id=body.workflow_id,
                        workflow_version_id=int(descriptor["workflow_version_id"]),
                        key_digest=key_digest,
                        request_digest=digest,
                        status="QUEUED",
                        accepted_at=now,
                        deadline_at=now + self.queue_seconds,
                        material=material,
                    )
                    session.add(row)
                    return Run.model_validate(row), True
            except IntegrityError:
                with self.registration.transaction() as session:
                    row = self._by_key(session, scope, user_id, key_digest)
                    if row is not None:
                        return self._replay(row, digest)
                raise
            except (WorkflowRegistrationConflict, WorkflowRegistrationDenied) as exc:
                raise RunError("VERSION_UNAVAILABLE") from exc

    def load(self, tenant_id, session_id):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = session.exec(select(Run).where(Run.session_id == session_id)).first()
            if row is None or row.tenant_id != tenant_id or self.is_expired(row):
                return None
            return Run.model_validate(row)

    def lookup_by_operation_key(self, scope, user_id, key):
        key_digest = sha256(key.encode()).hexdigest()
        with tenant_execution_scope(scope.tenant_id), self.registration.transaction() as session:
            row = self._by_key(session, scope, user_id, key_digest)
            if row is None or self.is_expired(row):
                return None
            return Run.model_validate(row)

    def _transition_initial(self, tenant_id, session_id, status, values, *, claim_id=None):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            now = int(self.clock())
            if row is None or row.status != status or row.claim_id != claim_id or row.deadline_at <= now:
                return False
            return self._update_current(
                session, row, Run.claim_id == claim_id, Run.deadline_at > now, now=now, **values(now)
            )

    def claim(self, tenant_id, session_id):
        claim_id = uuid4().hex
        won = self._transition_initial(
            tenant_id,
            session_id,
            "QUEUED",
            lambda now: {
                "status": "RUNNING",
                "claim_id": claim_id,
                "started_at": now,
                "deadline_at": now + self.run_seconds,
            },
        )
        return claim_id if won else None

    def _terminal(self, now, *, output=None, error=None, material=None):
        kept = {
            key: material[key]
            for key in ("interaction_id", "receipt", "kunlian_identity", "runtime_contract")
            if isinstance(material, dict) and key in material
        }
        return {
            "status": "FAILED" if error else "SUCCEEDED",
            "output": output if output is not None else null(),
            "error": error,
            "material": kept or null(),
            "finished_at": now,
            "expires_at": now + self.retain_seconds,
        }

    def finish(self, tenant_id, session_id, claim_id, *, output=None, error=None):
        return self._finish_claim(
            tenant_id,
            session_id,
            claim_id,
            ("RUNNING", "WAITING_INPUT"),
            output=output,
            error=error,
        )

    def update_agent_runtime(
        self,
        tenant_id,
        session_id,
        claim_id,
        agent_info: dict,
        *,
        waiting: bool | None = None,
        extend_seconds: int = 125,
    ):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            now = int(self.clock())
            if (
                row is None
                or not claim_id
                or row.claim_id != claim_id
                or row.status not in {"RUNNING", "WAITING_INPUT"}
            ):
                return False
            next_status = row.status
            if waiting is True:
                next_status = "WAITING_INPUT"
            elif waiting is False and row.status == "WAITING_INPUT":
                next_status = "RUNNING"
            material = {
                **(row.material if isinstance(row.material, dict) else {}),
                "agent_runtime": dict(agent_info),
            }
            next_deadline = max(row.deadline_at, now + extend_seconds)
            return self._update_current(
                session,
                row,
                Run.claim_id == claim_id,
                now=now,
                status=next_status,
                deadline_at=next_deadline,
                material=material,
            )

    def is_claim_cancelled(self, tenant_id, session_id, claim_id) -> bool:
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            if row is None or row.claim_id != claim_id:
                return True
            return row.status in {"CANCEL_REQUESTED", "CANCELLED", "FAILED"}

    def fail_before_claim(self, tenant_id, session_id, error):
        return self._transition_initial(tenant_id, session_id, "QUEUED", lambda now: self._terminal(now, error=error))

    @staticmethod
    def _locked_row(session, tenant_id, session_id):
        row = session.exec(
            select(Run).where(build_tenant_filter_clause(Run.tenant_id), Run.session_id == session_id).with_for_update()
        ).first()
        return row if row is not None and row.tenant_id == tenant_id else None

    @staticmethod
    def _update_current(session, row, *conditions, now, **values):
        control = read_run_control(row.material)
        if control is not None:
            status = values["status"]
            if status == "CANCELLED" and row.status != "CANCEL_REQUESTED":
                control.append(now, "CANCEL_ACCEPTED", status)
            control.append(now, _RUN_EVENTS[status], status)
            material = values.get("material", row.material)
            # Keep original non-secret identity reference through every terminal path.
            if isinstance(row.material, dict) and "kunlian_identity" in row.material:
                material = {
                    **(material if isinstance(material, dict) else {}),
                    "kunlian_identity": row.material["kunlian_identity"],
                }
            values["material"] = {
                **(material if isinstance(material, dict) else {}),
                "run_control": control.model_dump(),
            }
        # SQLite Mock 不支持 FOR UPDATE,条件写入仍能阻止读取旧状态的竞争者。
        return (
            session.execute(
                update(Run)
                .where(
                    build_tenant_filter_clause(Run.tenant_id),
                    Run.session_id == row.session_id,
                    Run.status == row.status,
                    *conditions,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ).rowcount
            == 1
        )

    def wait_for_input(self, tenant_id, session_id, claim_id, snapshot):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            now = int(self.clock())
            if (
                row is None
                or row.status != "RUNNING"
                or row.claim_id != claim_id
                or row.deadline_at <= now
                or (row.material or {}).get("mode") != "interactive"
            ):
                return False
            material = {**row.material, "interaction_id": uuid4().hex, "snapshot": snapshot}
            return self._update_current(
                session,
                row,
                Run.claim_id == claim_id,
                Run.deadline_at > now,
                now=now,
                status="WAITING_INPUT",
                claim_id=None,
                deadline_at=now + self.wait_seconds,
                material=material,
            )

    def _owned_row(self, session, subject, session_id):
        row = self._locked_row(session, subject.tenant_id, session_id)
        if row is None or (row.connection_id, row.user_id) != (subject.connection_id, subject.user_id):
            raise RunError("SESSION_NOT_FOUND")
        return row

    def request_cancel(self, subject, session_id):
        while True:
            with tenant_execution_scope(subject.tenant_id), self.registration.transaction() as session:
                row = self._owned_row(session, subject, session_id)
                now = int(self.clock())
                if row.expires_at is not None and row.expires_at <= now:
                    raise RunError("SESSION_NOT_FOUND")
                if read_run_control(row.material) is None:
                    raise RunError("CONTROL_UNAVAILABLE")
                if row.status in _TERMINAL or row.status == "CANCEL_REQUESTED":
                    return Run.model_validate(row)
                timeout = _PHASE_TIMEOUTS.get(row.status)
                if timeout is None:
                    raise RunError("CONTROL_UNAVAILABLE")
                if row.deadline_at <= now:
                    values = self._terminal(now, error=timeout, material=row.material)
                elif row.status in _ACTIVE_CLAIM or row.claim_id is not None:
                    values = {"status": "CANCEL_REQUESTED"}
                else:
                    values = self._cancelled(now, row.material)
                if self._update_current(
                    session, row, Run.claim_id == row.claim_id, Run.deadline_at == row.deadline_at, now=now, **values
                ):
                    session.refresh(row)
                    return Run.model_validate(row)

    def _cancelled(self, now, material):
        return {**self._terminal(now, material=material), "status": "CANCELLED", "claim_id": None}

    def _confirm_cancel(self, session, row, now):
        return self._update_current(
            session, row, Run.claim_id == row.claim_id, now=now, **self._cancelled(now, row.material)
        )

    def confirm_cancel(self, tenant_id, session_id, claim_id):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            return bool(
                row is not None
                and row.status == "CANCEL_REQUESTED"
                and claim_id
                and row.claim_id == claim_id
                and self._confirm_cancel(session, row, int(self.clock()))
            )

    def assert_node_entry(self, tenant_id, connection_id, session_id, claim_id, phase):
        if get_current_tenant_id() != tenant_id:
            raise RunError("CONTROL_STOPPED")
        with self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            if (
                row is None
                or row.connection_id != connection_id
                or row.status != phase
                or row.claim_id != claim_id
                or row.deadline_at <= int(self.clock())
                or read_run_control(row.material) is None
            ):
                raise RunError("CONTROL_STOPPED")

    def _waiting_timeout(self, session, row, now):
        return self._update_current(
            session,
            row,
            Run.deadline_at <= now,
            now=now,
            **self._terminal(now, error="INPUT_TIMEOUT", material=row.material),
        )

    def refresh(self, subject, session_id):
        while True:
            with tenant_execution_scope(subject.tenant_id), self.registration.transaction() as session:
                row = self._owned_row(session, subject, session_id)
                now = int(self.clock())
                if row.expires_at is not None and row.expires_at <= now:
                    raise RunError("SESSION_NOT_FOUND")
                if row.status != "WAITING_INPUT" or row.deadline_at > now:
                    return Run.model_validate(row)
                self._waiting_timeout(session, row, now)
            # 重读已提交的终态或并发请求已受理的状态。

    def _control_snapshot(self, subject, session_id):
        with tenant_execution_scope(subject.tenant_id), self.registration.transaction() as session:
            row = self._owned_row(session, subject, session_id)
            now = int(self.clock())
            if row.expires_at is not None and row.expires_at <= now:
                raise RunError("SESSION_NOT_FOUND")
            control = read_run_control(row.material)
            if control is None:
                raise RunError("CONTROL_UNAVAILABLE")
            return Run.model_validate(row), control, now

    def read_control(self, subject, session_id):
        row, control, _ = self._control_snapshot(subject, session_id)
        return row, control

    def read_events(self, subject, session_id, after, limit):
        row, control, now = self._control_snapshot(subject, session_id)
        if after > control.last_seq:
            raise RunError("INVALID_INPUT")
        lower = control.pruned_through
        for event in control.events:
            if event.occurred_at + RUN_EVENT_SECONDS > now:
                break
            lower = event.seq
        if after < lower:
            raise RunError("EVENT_CURSOR_EXPIRED")
        matching = [event for event in control.events if event.seq > after]
        page = matching[:limit]
        return {
            "session_id": row.session_id,
            "workflow_version_id": str(row.workflow_version_id),
            "events": [event.model_dump() for event in page],
            "next_after": page[-1].seq if page else after,
            "has_more": len(matching) > limit,
        }

    def answer(self, subject, session_id, interaction_id, key, inputs):
        key_digest = sha256(key.encode()).hexdigest()
        answer_digest = canonical_digest(inputs)
        receipt = {"session_id": session_id, "interaction_id": interaction_id, "status": "ACCEPTED"}
        while True:
            with tenant_execution_scope(subject.tenant_id), self.registration.transaction() as session:
                row = self._owned_row(session, subject, session_id)
                now = int(self.clock())
                material = row.material or {}
                if material.get("interaction_id") != interaction_id or (
                    row.expires_at is not None and row.expires_at <= now
                ):
                    raise RunError("SESSION_NOT_FOUND")
                saved = material.get("receipt")
                if saved:
                    if saved["key_digest"] != key_digest:
                        raise RunError("INTERACTION_CONSUMED")
                    if saved["answer_digest"] != answer_digest:
                        raise RunError("IDEMPOTENCY_CONFLICT")
                    return saved["response"], False
                if row.error == "INPUT_TIMEOUT":
                    raise RunError("INPUT_TIMEOUT")
                if row.status != "WAITING_INPUT":
                    raise RunError("INTERACTION_CONSUMED")
                if row.deadline_at <= now:
                    self._waiting_timeout(session, row, now)
                    continue
                validate_interaction_input(material["input_schema"], inputs)
                receipt_material = {"key_digest": key_digest, "answer_digest": answer_digest, "response": receipt}
                if self._update_current(
                    session,
                    row,
                    Run.deadline_at > now,
                    now=now,
                    status="RESUME_QUEUED",
                    deadline_at=now + self.queue_seconds,
                    material={**material, "answer": inputs, "receipt": receipt_material},
                ):
                    return receipt, True

    def claim_resume(self, tenant_id, session_id, interaction_id, *, error=None):
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            now = int(self.clock())
            if (
                row is None
                or row.status != "RESUME_QUEUED"
                or row.deadline_at <= now
                or (row.material or {}).get("interaction_id") != interaction_id
            ):
                return None
            claim_id = uuid4().hex
            values = (
                self._terminal(now, error=error, material=row.material)
                if error
                else {"status": "RESUMING", "claim_id": claim_id, "deadline_at": now + self.run_seconds}
            )
            won = self._update_current(session, row, Run.deadline_at > now, now=now, **values)
            return claim_id if won and not error else None

    def finish_resume(self, tenant_id, session_id, claim_id, *, output=None, error=None):
        return self._finish_claim(tenant_id, session_id, claim_id, "RESUMING", output=output, error=error)

    def _finish_claim(self, tenant_id, session_id, claim_id, phase, *, output, error):
        while True:
            with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
                row = self._locked_row(session, tenant_id, session_id)
                now = int(self.clock())
                if row is None or not claim_id or row.claim_id != claim_id:
                    return False
                allowed_phases = phase if isinstance(phase, tuple) else (phase,)
                if row.status == "CANCEL_REQUESTED":
                    if not self._confirm_cancel(session, row, now):
                        continue
                elif row.status in allowed_phases and row.deadline_at > now:
                    if self._update_current(
                        session,
                        row,
                        Run.claim_id == claim_id,
                        Run.deadline_at > now,
                        now=now,
                        **self._terminal(now, output=output, error=error, material=row.material),
                    ):
                        return True
                    continue
                else:
                    return False
            logger.info("昆联运行确认取消,session_id={} source=worker", session_id)
            return False

    @staticmethod
    def _resume_interaction_id(material):
        value = material.get("interaction_id") if isinstance(material, dict) else None
        if isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value):
            return value
        return None

    def _reject_invalid_resume(self, session, scope, session_id):
        row = self._locked_row(session, scope.tenant_id, session_id)
        if (
            row is not None
            and row.connection_id == scope.connection_id
            and row.status == "RESUME_QUEUED"
            and self._resume_interaction_id(row.material) is None
        ):
            now = int(self.clock())
            error = "RESUME_QUEUE_TIMEOUT" if row.deadline_at <= now else "RESUME_STATE_INVALID"
            self._update_current(session, row, now=now, **self._terminal(now, error=error, material=row.material))

    @staticmethod
    def _formal_cleanup_identity(row):
        """Allow only row-bound, non-secret identity facts into the tombstone."""
        material = row.material
        if not isinstance(material, dict) or material.get("runtime_contract") != "published-workflow":
            return None
        identity = material.get("kunlian_identity")
        if not isinstance(identity, dict):
            return None
        for key in ("tenant_id", "user_id", "credential_id", "policy_revision"):
            if type(identity.get(key)) is not int or identity[key] <= 0:
                return None
        if (identity["tenant_id"], identity.get("connection_id"), identity["user_id"]) != (
            row.tenant_id,
            row.connection_id,
            row.user_id,
        ):
            return None
        for key in ("connection_id", "identity_connection_id", "external_tenant_id", "external_user_id"):
            if not isinstance(identity.get(key), str) or not identity[key]:
                return None
        keys = (
            "tenant_id",
            "connection_id",
            "user_id",
            "credential_id",
            "identity_connection_id",
            "external_tenant_id",
            "external_user_id",
            "policy_revision",
        )
        return {key: identity[key] for key in keys if key in identity}

    def formal_cleanup_page(self, after=None, limit=100):
        """Discover one keyset page of expired terminals; never authorize by discovery.

        No JSON database predicates: MySQL/DM8 use the same relational query.
        Invalid/candidate rows consume page space so scanning remains bounded.
        """
        from bisheng.core.context.tenant import bypass_tenant_filter

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid cleanup limit")
        with bypass_tenant_filter(), self.registration.transaction() as session:
            stmt = select(Run).where(Run.status.in_(tuple(_TERMINAL)), Run.expires_at <= int(self.clock()))
            if after is not None:
                stmt = stmt.where(Run.session_id > after)
            rows = session.exec(stmt.order_by(Run.session_id).limit(limit + 1)).all()
            page = rows[:limit]
            references = [
                (row.tenant_id, row.connection_id, row.session_id)
                for row in page
                if self._formal_cleanup_identity(row) is not None
            ]
            return references, page[-1].session_id if len(rows) > limit else None

    def cleanup_formal_expired(self, tenant_id, connection_id, session_id):
        """Revalidate under the row lock, scrub payloads, retain permanent key facts.

        Never delete the run: its unique key/request digests must reject old keys
        even after outputs and frozen graph/input/answer/snapshot are removed.
        """
        with tenant_execution_scope(tenant_id), self.registration.transaction() as session:
            row = self._locked_row(session, tenant_id, session_id)
            now = int(self.clock())
            if (
                row is None
                or row.connection_id != connection_id
                or row.status not in _TERMINAL
                or row.expires_at is None
                or row.expires_at > now
            ):
                return False
            identity = self._formal_cleanup_identity(row)
            if identity is None:
                return False
            material = {"runtime_contract": "published-workflow", "kunlian_identity": identity}
            if row.output is None and row.material == material:
                return False
            return (
                session.execute(
                    update(Run)
                    .where(
                        build_tenant_filter_clause(Run.tenant_id),
                        Run.tenant_id == tenant_id,
                        Run.connection_id == connection_id,
                        Run.session_id == session_id,
                        Run.user_id == row.user_id,
                        Run.status == row.status,
                        Run.expires_at == row.expires_at,
                        Run.expires_at <= now,
                    )
                    .values(output=null(), material=material)
                    .execution_options(synchronize_session=False)
                ).rowcount
                == 1
            )

    def formal_recovery_page(self, after=None, limit=100):
        """Bounded cross-tenant discovery only; mutations always restore row scope.

        JSON predicates are deliberately avoided for MySQL/DM8 parity. Candidate
        rows may be inspected but are never returned as trusted formal references.
        """
        from bisheng.core.context.tenant import bypass_tenant_filter

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid recovery limit")
        with bypass_tenant_filter(), self.registration.transaction() as session:
            stmt = select(Run).where(Run.status.in_((*_PHASE_TIMEOUTS, "CANCEL_REQUESTED")))
            if after is not None:
                stmt = stmt.where(Run.session_id > after)
            rows = session.exec(stmt.order_by(Run.session_id).limit(limit + 1)).all()
            page = rows[:limit]
            references = []
            for row in page:
                if (row.material or {}).get("runtime_contract") != "published-workflow":
                    continue
                identity = (row.material or {}).get("kunlian_identity")
                if not isinstance(identity, dict) or (
                    identity.get("tenant_id"),
                    identity.get("connection_id"),
                    identity.get("user_id"),
                ) != (row.tenant_id, row.connection_id, row.user_id):
                    continue
                if type(identity.get("credential_id")) is not int or identity["credential_id"] <= 0:
                    continue
                if any(
                    not isinstance(identity.get(key), str) or not identity[key]
                    for key in ("identity_connection_id", "external_tenant_id", "external_user_id")
                ):
                    continue
                references.append((row.tenant_id, row.connection_id, row.session_id))
            return references, page[-1].session_id if len(rows) > limit else None

    def reconcile(self, scope, limit=100, *, include_resumes=False, session_ids=None):
        now = int(self.clock())
        with tenant_execution_scope(scope.tenant_id), self.registration.transaction() as session:
            tenant_filter = build_tenant_filter_clause(Run.tenant_id)
            if session_ids is not None:
                # The formal dispatcher supplies only persisted identity-bound IDs.
                tenant_filter = tenant_filter & Run.session_id.in_(tuple(session_ids))
            cancellations = select(Run).where(
                tenant_filter,
                Run.connection_id == scope.connection_id,
                Run.status == "CANCEL_REQUESTED",
                Run.deadline_at <= now,
            )
            for row in session.exec(
                cancellations.order_by(Run.deadline_at, Run.session_id).limit(limit).with_for_update()
            ).all():
                locked_now = int(self.clock())
                if (
                    row.connection_id == scope.connection_id
                    and row.deadline_at <= locked_now
                    and self._confirm_cancel(session, row, locked_now)
                ):
                    logger.info("昆联运行补偿确认待提交,session_id={} deadline={}", row.session_id, row.deadline_at)
            base = select(Run.session_id, Run.status, Run.connection_id).where(
                tenant_filter, Run.connection_id == scope.connection_id
            )
            overdue = select(Run).where(
                tenant_filter,
                Run.connection_id == scope.connection_id,
                Run.status.in_(tuple(_PHASE_TIMEOUTS)),
                Run.deadline_at <= now,
            )
            for row in session.exec(
                overdue.order_by(Run.deadline_at, Run.session_id).limit(limit).with_for_update()
            ).all():
                if row.connection_id != scope.connection_id:
                    continue
                locked_now = int(self.clock())
                self._update_current(
                    session,
                    row,
                    Run.deadline_at <= locked_now,
                    now=locked_now,
                    **self._terminal(locked_now, error=_PHASE_TIMEOUTS[row.status], material=row.material),
                )
            queued = base.where(Run.status == "QUEUED", Run.deadline_at > now)
            # Mock 保留摘要墓碑以拒绝过期键,按批清除过期业务结果。
            expired = base.where(Run.expires_at <= now, or_(Run.output.is_not(None), Run.material.is_not(None)))
            expired_ids = [
                ident
                for ident, _, connection_id in session.exec(
                    expired.order_by(Run.expires_at, Run.session_id).limit(limit)
                )
                if connection_id == scope.connection_id
            ]
            if expired_ids:
                session.execute(
                    update(Run)
                    .where(tenant_filter, Run.session_id.in_(expired_ids))
                    .values(output=null(), material=null())
                )
            initial = [
                session_id
                for session_id, _, connection_id in session.exec(
                    queued.order_by(Run.deadline_at, Run.session_id).limit(limit)
                )
                if connection_id == scope.connection_id
            ]
            if not include_resumes:
                return initial
            resumes = select(Run.session_id, Run.connection_id, Run.material).where(
                tenant_filter,
                Run.connection_id == scope.connection_id,
                Run.status == "RESUME_QUEUED",
                Run.deadline_at > now,
            )
            pending = [(session_id, None) for session_id in initial]
            for session_id, connection_id, material in session.exec(
                resumes.order_by(Run.deadline_at, Run.session_id).limit(limit)
            ).all():
                if connection_id != scope.connection_id:
                    continue
                interaction_id = self._resume_interaction_id(material)
                if interaction_id is None:
                    # 单条记录损坏不应回滚整批补偿。
                    self._reject_invalid_resume(session, scope, session_id)
                else:
                    pending.append((session_id, interaction_id))
            return pending
