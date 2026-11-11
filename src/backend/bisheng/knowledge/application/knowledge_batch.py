"""Ordinary batches use the existing Plan; external IO never holds target locks."""

from contextlib import asynccontextmanager
from datetime import timedelta
from inspect import isawaitable
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationConfirmationRequiredError,
    KnowledgeOperationPlanChangedError,
)
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.processing_identity import capture_processing_actor, restore_processing_actor
from bisheng.knowledge.domain.repositories.knowledge_batch_repository import KnowledgeBatchRepository, ancestors
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository, _digest, _now
from bisheng.knowledge.domain.schemas.knowledge_batch import BatchCommand
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.knowledge.domain.services.knowledge_batch_classification import classify
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.business_authorization import batch_check_business_actions
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.resource_reference.application.contracts import TransactionIdentity


class KnowledgeBatchApplication:
    def __init__(
        self,
        *,
        session_factory=get_async_db_session,
        repository=None,
        plans=None,
        permission_check=None,
        exporter=None,
        dispatcher=None,
        clock=_now,
    ):
        self.sessions, self.repo, self.clock = session_factory, repository or KnowledgeBatchRepository(), clock
        self.plans = plans or OperationPlanRepository(clock=clock)
        self.permissions = permission_check or batch_check_business_actions
        self.exporter, self.dispatcher = exporter, dispatcher

    @staticmethod
    def _pin():
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed():
            raise KnowledgeOperationPlanChangedError(reason="batch_concrete_tenant_required")
        return tenant, get_admin_scope_tenant_id(), get_current_permission_actor()

    def _check(self, pin, session=None, transaction=None):
        current = self._pin()
        if current[:2] != pin[:2] or current[2] is not pin[2]:
            raise KnowledgeOperationPlanChangedError(reason="batch_identity_or_scope_changed")
        if session is not None:
            transaction.assert_current(session)
            if session.new or session.dirty or session.deleted:
                raise KnowledgeOperationPlanChangedError(reason="batch_pending_business_write")

    @asynccontextmanager
    async def _identity(self, identity, space_id, operation):
        original_pin = self._pin()
        reference = (
            await capture_processing_actor(
                identity,
                space_id=space_id,
                required_action="download" if operation == "download" else "rename",
                entry_kind="open_api" if get_current_open_api_principal() else "web",
            )
        ).reference
        self._check(original_pin)
        async with restore_processing_actor(reference, tenant_id=reference["tenant_id"]) as actual:
            pin = self._pin()
            yield actual, reference, pin
            self._check(pin)

    async def _read(self, space_id, command, pin):
        self._check(pin)
        async with self.sessions() as session, session.begin():
            tx = TransactionIdentity.capture(session)
            value = await self.repo.aread(session, space_id=space_id, command=command)
            self._check(pin, session, tx)
        self._check(pin)
        return value

    async def _classify(self, actual, scope, command, pin):
        allowed = set()
        action = "download" if command.operation == "download" else "rename"
        needed = {ident for unit in scope["units"] for ident in unit}
        selected = {item.id for item in command.items}
        for kind, file_type in (("folder", 0), ("knowledge_file", 1)):
            ids = [
                row["id"]
                for row in scope["files"]
                if row["file_type"] == file_type
                and row["id"] in needed
                and (
                    command.operation == "download"
                    or (command.operation == "tag" and file_type == 1)
                    or (
                        command.operation == "retry"
                        and (row["id"] in selected or row["status"] in (3, 6, 7))
                    )
                )
            ]
            for offset in range(0, len(ids), 200):
                self._check(pin)
                result = await self.permissions(
                    actual, resource_type=kind, resource_ids=ids[offset : offset + 200], actions=(action,)
                )
                self._check(pin)
                allowed.update(int(ident) for ident, codes in result.items() if action in codes)
        if set(command.new_tag_names) - {row["name"] for row in scope["tags"]}:
            result = await self.permissions(
                actual, resource_type="knowledge_space", resource_ids=[scope["root"]["id"]], actions=("edit",)
            )
            self._check(pin)
            if "edit" not in result.get(str(scope["root"]["id"]), ()):
                allowed.clear()
        return classify(scope, command, allowed)

    async def ainspect(self, *, identity, space_id, command):
        command = BatchCommand.model_validate(command.model_dump(mode="json", exclude_defaults=True))
        async with self._identity(identity, space_id, command.operation) as (actual, _, pin):
            scope = await self._read(space_id, command, pin)
            review, _, _ = await self._classify(actual, scope, command, pin)
            return review

    async def aprecheck(self, *, identity, space_id, command):
        command = BatchCommand.model_validate(command.model_dump(mode="json", exclude_defaults=True))
        async with self._identity(identity, space_id, command.operation) as (actual, reference, pin):
            scope = await self._read(space_id, command, pin)
            review, positions, files = await self._classify(actual, scope, command, pin)
            async with self.sessions() as session, session.begin(), session.begin_nested():
                tx = TransactionIdentity.capture(session)
                current = await self.repo.aread(session, space_id=space_id, command=command, lock=True)
                self._check(pin, session, tx)
                if current != scope:
                    raise KnowledgeOperationPlanChangedError()
                result = await self.plans.acreate(
                    session,
                    operation="knowledge_batch_" + command.operation,
                    space_id=space_id,
                    actor_reference=reference,
                    targets=[],
                    target_revisions={"scope": _digest(scope)},
                    source_revisions={},
                    parameters={
                        "command": command.model_dump(mode="json", exclude_defaults=True),
                        "scope": scope,
                        "valid_positions": positions,
                        "files": files,
                        "management_pin": pin[1],
                        "object_key": "download/" + str(uuid4()) + "/batch.zip",
                    },
                    impact=review.impact,
                    expires_at=self.clock() + timedelta(seconds=300),
                )
                self._check(pin, session, tx)
            return result.model_copy(
                update={
                    "can_execute": review.can_execute,
                    "valid_items": review.valid_items,
                    "invalid_items": review.invalid_items,
                    "requires_skip_confirmation": review.requires_skip_confirmation,
                }
            )

    async def _plan(self, space_id, operation, request, reference, pin):
        async with self.sessions() as session, session.begin():
            tx = TransactionIdentity.capture(session)
            row = await self.plans.aget_for_execution(
                session,
                request.confirmation_id,
                space_id=space_id,
                operation="knowledge_batch_" + operation,
                actor_reference=reference,
                plan_digest=request.plan_digest,
            )
            self._check(pin, session, tx)
            if row.parameters["management_pin"] != pin[1] or row.operation_id not in (None, request.idempotency_key):
                raise KnowledgeOperationPlanChangedError()
            return {"parameters": row.parameters, "consumed": row.operation_id is not None}

    async def aconfirm(self, *, identity, space_id, operation, request):
        if operation not in {"download", "tag", "retry"}:
            raise KnowledgeOperationPlanChangedError()
        async with self._identity(identity, space_id, operation) as (actual, reference, pin):
            original = await self._plan(space_id, operation, request, reference, pin)
            params = original["parameters"]
            command = BatchCommand.model_validate(params["command"])
            scope = await self._read(space_id, command, pin)
            if original["consumed"]:
                return await self._replay(actual, scope, command, params, request, pin)
            review, positions, files = await self._classify(actual, scope, command, pin)
            if not review.can_execute or positions != params["valid_positions"] or scope != params["scope"]:
                raise KnowledgeOperationPlanChangedError()
            outcome = await self._export(scope, files, params["object_key"], pin) if operation == "download" else None
            latest, latest_positions, _ = await self._classify(actual, scope, command, pin)
            if not latest.can_execute or latest_positions != positions:
                raise KnowledgeOperationPlanChangedError()
            async with self.sessions() as session, session.begin(), session.begin_nested():
                tx = TransactionIdentity.capture(session)
                current = await self.repo.aread(session, space_id=space_id, command=command, lock=True)
                self._check(pin, session, tx)
                if current != scope:
                    raise KnowledgeOperationPlanChangedError()
                row = await self.plans.aget_for_execution(
                    session,
                    request.confirmation_id,
                    space_id=space_id,
                    operation="knowledge_batch_" + operation,
                    actor_reference=reference,
                    plan_digest=request.plan_digest,
                )
                self._check(pin, session, tx)
                if row.operation_id not in (None, request.idempotency_key):
                    raise KnowledgeOperationPlanChangedError()
                if row.operation_id is None:
                    if operation == "tag":
                        await self.repo.atag(
                            session, scope=scope, files=files, command=command, user_id=reference["actor_user_id"]
                        )
                    elif operation == "retry":
                        await self.repo.await_retry(
                            session, space_id=space_id, files=files, folder_ids=self._folder_timestamps(params)
                        )
                    self._check(pin, session, tx)
                    if not outcome or not outcome["failed_file_ids"]:
                        await self.plans.aconsume(
                            session,
                            request.confirmation_id,
                            operation_id=request.idempotency_key,
                            expected_digest=request.plan_digest,
                        )
                    self._check(pin, session, tx)
            dispatch = await self._dispatch(files, pin) if operation == "retry" else None
            return self._result(command, params, request, False, outcome, dispatch)

    async def _replay(self, actual, scope, command, params, request, pin):
        current = {row["id"]: row for row in scope["files"]}
        originals = params["files"]
        review, positions, _ = await self._classify(actual, params["scope"], command, pin)
        if not review.can_execute or positions != params["valid_positions"]:
            raise KnowledgeOperationPlanChangedError()
        if command.operation == "tag":
            return self._result(command, params, request, True)
        for before in originals:
            after = current.get(before["id"])
            if after is None or any(
                after[key] != before[key] for key in ("id", "tenant_id", "knowledge_id", "file_type", "file_level_path")
            ):
                raise KnowledgeOperationPlanChangedError()
        if command.operation == "download":
            outcome = await self._export(scope, originals, params["object_key"], pin, reuse=True)
            return self._result(command, params, request, True, outcome)
        eligible = [current[row["id"]] for row in originals if current[row["id"]]["status"] == 5]
        async with self.sessions() as session, session.begin(), session.begin_nested():
            tx = TransactionIdentity.capture(session)
            locked = await self.repo.aread(session, space_id=params["scope"]["root"]["id"], command=command, lock=True)
            self._check(pin, session, tx)
            if locked != scope:
                raise KnowledgeOperationPlanChangedError()
        dispatch = await self._dispatch(eligible, pin)
        for row in originals:
            if row["id"] not in dispatch:
                dispatch[row["id"]] = (
                    "running"
                    if current[row["id"]]["status"] == 1
                    else "succeeded"
                    if current[row["id"]]["status"] == 2
                    else "failed"
                )
        return self._result(command, params, request, True, dispatch=dispatch)

    @staticmethod
    def _folder_timestamps(params):
        rows = {row["id"]: row for row in params["scope"]["files"]}
        command = params["command"]
        return {
            ident
            for position in params["valid_positions"]
            for ident in ancestors(rows[command["items"][position]["id"]])
        }

    async def _export(self, scope, files, key, pin, reuse=False):
        exporter = self.exporter
        if exporter is None:
            from bisheng.knowledge.domain.services.knowledge_batch_download import export_batch

            exporter = export_batch
        self._check(pin)
        result = await exporter(scope=scope, files=files, object_key=key, reuse=reuse)
        self._check(pin)
        return result

    async def _dispatch(self, files, pin):
        states = {}
        for file in files:
            self._check(pin)
            try:
                if self.dispatcher is None:
                    from bisheng.worker import retry_knowledge_file_celery

                    retry_knowledge_file_celery.delay(file["id"])
                else:
                    value = self.dispatcher(file)
                    if isawaitable(value):
                        await value
                self._check(pin)
                states[file["id"]] = "accepted"
            except Exception:
                self._check(pin)
                logger.exception("batch retry acknowledgement unknown file_id={}", file["id"])
                states[file["id"]] = "pending_dispatch"
        return states

    @staticmethod
    def _result(command, params, request, reused, outcome=None, dispatch=None):
        failed = set((outcome or {}).get("failed_file_ids", ()))
        positions = set(params["valid_positions"])
        result = []
        file_ids = {row["id"] for row in params["files"]}
        for index, item in enumerate(command.items):
            state = "skipped"
            if index in positions:
                members = set(params["scope"]["units"][index]) & file_ids
                if dispatch is not None:
                    states = {dispatch.get(ident, "failed") for ident in members}
                    state = next(
                        (state for state in ("pending_dispatch", "failed", "accepted", "running") if state in states),
                        "succeeded",
                    )
                else:
                    state = "failed" if members & failed else "succeeded"
            result.append({"id": item.id, "type": item.type, "state": state})
        return {
            "confirmation_id": request.confirmation_id,
            "operation": command.operation,
            "reused": reused,
            "items": result,
            **({"url": outcome["url"]} if outcome and outcome.get("url") else {}),
        }

    async def aordinary(self, *, identity, space_id, command):
        review = await self.ainspect(identity=identity, space_id=space_id, command=command)
        if review.invalid_items:
            raise KnowledgeOperationConfirmationRequiredError(precheck=review.model_dump(mode="json"))
        plan = await self.aprecheck(identity=identity, space_id=space_id, command=command)
        result = await self.aconfirm(
            identity=identity,
            space_id=space_id,
            operation=command.operation,
            request=ProcessingCreateRequest(
                confirmation_id=plan.confirmation_id,
                plan_digest=plan.plan_digest,
                idempotency_key="batch:" + plan.confirmation_id,
            ),
        )

        if any(row["state"] in {"pending_dispatch", "failed"} for row in result["items"]):
            raise KnowledgeOperationConfirmationRequiredError(
                precheck=plan.model_dump(mode="json"), execution=result, idempotency_key="batch:" + plan.confirmation_id
            )
        return result


def get_batch_application():
    return KnowledgeBatchApplication()
