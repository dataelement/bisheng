"""Plan explicitly selected provider files; confirmation accepts a durable intent, never a native write."""

from datetime import timedelta

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.knowledge.application.knowledge_batch import KnowledgeBatchApplication
from bisheng.knowledge.application.provider_resolver import BindingUnavailable, CapabilityUnavailable
from bisheng.knowledge.domain.repositories.provider_batch_repository import snapshot
from bisheng.knowledge.domain.schemas.knowledge_batch import BatchCommand, BatchInspection


class ProviderBatchApplication(KnowledgeBatchApplication):
    def __init__(self, *, resolver=None, facts=snapshot, **kwargs):
        super().__init__(**kwargs)
        self.resolver, self.facts = resolver, facts

    def _writer(self, scope, operation):
        b = scope["binding"]
        if self.resolver and operation in {"retry", "tag", "delete"}:
            try:
                port = self.resolver.resolve(
                    tenant_id=b["tenant_id"],
                    space_id=b["space_id"],
                    provider_key=b["provider_key"],
                    binding=b,
                    operation="batch_" + operation,
                )
            except (BindingUnavailable, CapabilityUnavailable) as exc:
                raise KnowledgeOperationPlanChangedError(reason="provider_batch_unsupported") from exc
            if callable(getattr(port, "accept_batch", None)):
                return port
        raise KnowledgeOperationPlanChangedError(reason="provider_batch_unsupported")

    async def _inspect(self, actual, space, command, pin):
        space_allowed = await self.permissions(
            actual, resource_type="knowledge_space", resource_ids=[space], actions=("visible",)
        )
        if "visible" not in space_allowed.get(str(space), ()):
            raise KnowledgeOperationPlanChangedError(reason="provider_batch_unavailable")
        async with self.sessions() as db, db.begin():
            scope = await self.facts(db, space, command, lock=False)
        self._writer(scope, command.operation)
        rows = {f["file_id"]: f for f in scope["files"]}
        action = "delete" if command.operation == "delete" else "rename"
        grants = (
            await self.permissions(
                actual, resource_type="knowledge_file", resource_ids=list(rows), actions=("visible", action)
            )
            if rows
            else {}
        )
        eligible, invalid = [], []
        for s in command.items:
            f = rows.get(s.id) if s.type == "file" else None
            if (
                f
                and {"visible", action}.issubset(grants.get(str(s.id), ()))
                and (
                    (
                        command.operation == "retry"
                        and f["status"] in (3, 6, 7)
                        and f["lifecycle"] in ("pending", "active", "failed")
                    )
                    or (command.operation != "retry" and f["status"] == 2 and f["lifecycle"] == "active")
                )
            ):
                eligible.append(f)
            else:
                invalid.append({"id": s.id, "type": s.type, "reason": "unavailable"})
        self._check(pin)
        review = BatchInspection(
            can_execute=bool(eligible),
            valid_items=[{"id": f["file_id"], "type": "file"} for f in eligible],
            invalid_items=invalid,
            requires_skip_confirmation=bool(invalid and eligible),
            impact={"files": len(eligible)},
        )
        return scope, eligible, review

    async def ainspect(self, *, identity, space_id, command):
        async with self._identity(identity, space_id, command.operation) as (actual, _, pin):
            return (await self._inspect(actual, space_id, command, pin))[2]

    async def aprecheck(self, *, identity, space_id, command):
        async with self._identity(identity, space_id, command.operation) as (actual, reference, pin):
            scope, files, review = await self._inspect(actual, space_id, command, pin)
            async with self.sessions() as db, db.begin():
                if await self.facts(db, space_id, command, lock=True) != scope:
                    raise KnowledgeOperationPlanChangedError()
                plan = await self.plans.acreate(
                    db,
                    operation="provider_batch_" + command.operation,
                    space_id=space_id,
                    actor_reference=reference,
                    targets=[{k: f[k] for k in ("file_id", "document_id", "version_id")} for f in files],
                    target_revisions={},
                    source_revisions={},
                    parameters={
                        "scope": scope,
                        "files": files,
                        "command": command.model_dump(mode="json", exclude_defaults=True),
                        "management_pin": pin[1],
                    },
                    impact=review.impact,
                    expires_at=self.clock() + timedelta(minutes=5),
                )
                self._check(pin)
            return plan.model_copy(
                update={
                    k: getattr(review, k)
                    for k in ("can_execute", "valid_items", "invalid_items", "requires_skip_confirmation")
                }
            )

    async def aconfirm(self, *, identity, space_id, operation, request):
        async with self._identity(identity, space_id, operation) as (actual, reference, pin):

            async def fetch(db):
                row = await self.plans.aget_for_execution(
                    db,
                    request.confirmation_id,
                    space_id=space_id,
                    operation="provider_batch_" + operation,
                    actor_reference=reference,
                    plan_digest=request.plan_digest,
                )
                if (
                    row.operation_id not in (None, request.idempotency_key)
                    or row.parameters["management_pin"] != pin[1]
                ):
                    raise KnowledgeOperationPlanChangedError()
                return row

            async with self.sessions() as db, db.begin():
                previous = await fetch(db)
                params, consumed = previous.parameters, previous.operation_id is not None
            if consumed:
                # Jobs may already have changed status or deleted targets. A receipt
                # for this authenticated actor is not authorization to re-run a job.
                grants = await self.permissions(
                    actual, resource_type="knowledge_space", resource_ids=[space_id], actions=("visible",)
                )
                if "visible" not in grants.get(str(space_id), ()):
                    raise KnowledgeOperationPlanChangedError()
                self._check(pin)
                return {"operation_id": request.confirmation_id, "state": "accepted", "reused": True}
            command = BatchCommand.model_validate(params["command"])
            scope, files, _ = await self._inspect(actual, space_id, command, pin)
            if not files or files != params["files"] or scope != params["scope"]:
                raise KnowledgeOperationPlanChangedError()
            async with self.sessions() as db, db.begin():
                if await self.facts(db, space_id, command, lock=True) != scope:
                    raise KnowledgeOperationPlanChangedError()
                row = await fetch(db)
                reused = row.operation_id is not None
                if not reused:
                    # Only a registered durable, same-transaction acceptance port is eligible.
                    # It must not send HTTP or dispatch while this transaction is open.
                    await self._writer(scope, operation).accept_batch(
                        db,
                        operation_id=row.id,
                        actor_reference=reference,
                        operation=operation,
                        binding=scope["binding"],
                        revision=scope["revision"],
                        targets=files,
                        tags=scope["tags"],
                    )
                    await self.plans.aconsume(
                        db, row.id, operation_id=request.idempotency_key, expected_digest=request.plan_digest
                    )
                self._check(pin)
            return {
                "operation_id": request.confirmation_id,
                "state": "accepted",
                "reused": reused,
                "items": [{"id": f["file_id"], "state": "accepted"} for f in files],
            }
