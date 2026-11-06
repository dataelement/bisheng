"""Knowledge-owned model bindings inside the caller's native transaction.

Targets are verified/locked before the actual Knowledge root. No operation
opens a Session, commits, dispatches a task, or calls a model provider.
"""

import inspect
from copy import deepcopy
from dataclasses import dataclass, field, replace
from uuid import uuid4
from weakref import WeakKeyDictionary, ref

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeNoEmbeddingError,
    KnowledgeNotExistError,
    KnowledgeOperationPlanConflictError,
    KnowledgeRebuildingError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    extract_knowledge_model_references,
)
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.access import (
    get_reference_binding_runtime,
    get_reference_binding_runtime_sync,
)
from bisheng.resource_reference.application.contracts import (
    ReferenceState,
    SourceBindingChange,
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
    canonical_target_id,
    reference_set_digest,
)
from bisheng.resource_reference.application.write_runtime import PreparedSourceBindings
from bisheng.utils.async_utils import run_async_safe


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedKnowledgeModelChange:
    knowledge_id: int
    tenant_id: int
    operation_id: str | None
    model: str | None
    transition: dict | None = field(repr=False)
    expected_revision: int
    expected_generation: str | None
    new_generation: str
    changed: bool
    bindings: PreparedSourceBindings = field(repr=False)
    row: Knowledge = field(repr=False)
    runtime: object = field(repr=False)


_issued: WeakKeyDictionary = WeakKeyDictionary()
_batches: WeakKeyDictionary = WeakKeyDictionary()
_removals: WeakKeyDictionary = WeakKeyDictionary()


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedKnowledgeRemoval:
    knowledge_id: int
    tenant_id: int
    only_clear: bool
    bindings: PreparedSourceBindings | None = field(repr=False)
    row: Knowledge = field(repr=False)
    runtime: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class KnowledgeModelRebuildCommand:
    knowledge_id: int
    type: int
    operation_id: str
    expected_model_config_revision: int
    expected_index_generation: str
    tenant_id: int
    actor_user_id: int


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class KnowledgeModelChangeBatch:
    changes: tuple[SourceBindingChange, ...]
    commands: tuple[KnowledgeModelRebuildCommand, ...]

    async def alock_inventory(self, session):
        state = KnowledgeModelReferenceApplication._batch_state(session, self)
        if state["locked"] is None:
            rows = await KnowledgeModelReferenceApplication.repository.alist_spaces(session, for_update=True)
            if tuple(KnowledgeModelReferenceApplication._facts(row) for row in rows) != state["facts"]:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_space_inventory_changed")
            for row in rows:
                await KnowledgeModelReferenceApplication._authorize(state["user"], row)
            state["locked"] = {row.id: row for row in rows}
        elif (
            tuple(KnowledgeModelReferenceApplication._facts(row) for row in state["locked"].values()) != state["facts"]
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_space_inventory_changed")
        return tuple(state["locked"].values())


class KnowledgeModelReferenceApplication:
    repository = KnowledgeModelReferenceRepository()

    @staticmethod
    def _source(row):
        return SourceKey(row.tenant_id, SourceType.KNOWLEDGE, str(row.id), "current")

    @staticmethod
    def _references(row):
        return extract_knowledge_model_references(model=row.model, model_transition=row.model_transition)

    @classmethod
    def _facts(cls, row):
        return (
            row.id,
            row.tenant_id,
            row.type,
            row.model,
            deepcopy(row.model_transition),
            row.model_config_revision,
            row.index_generation,
            row.state,
        )

    @staticmethod
    def _user(login_user):
        if not isinstance(login_user, UserPayload):
            raise ResourceReferenceInvalidError(reason="knowledge_model_original_identity_required")

    @staticmethod
    async def _authorize(login_user, row, action="edit"):
        await require_business_action(
            login_user,
            resource_type="knowledge_space" if row.type == KnowledgeTypeEnum.SPACE.value else "knowledge_library",
            resource_id=row.id,
            action=action,
        )

    @classmethod
    def _validate_configuration(cls, candidate, bindings, kinds, new_model_id):
        if bindings.verified.context.old_references_digest != reference_set_digest(cls._references(candidate)):
            raise ReferenceCoverageNotReadyError(reason="knowledge_source_configuration_drift")
        selected = TargetKey(TargetType.MODEL, new_model_id)
        targets = {receipt.target.key: receipt.target for receipt in bindings.verified.context.receipts}
        target = targets[selected]
        if target.state != ReferenceState.VALID or not target.new_binding_allowed:
            raise ResourceReferenceInvalidError(reason="knowledge_new_model_invalid")
        if kinds.get(selected) != "embedding":
            raise KnowledgeNoEmbeddingError()
        old = [targets[spec.target] for spec in cls._references(candidate)]
        repair = any(item.state != ReferenceState.VALID or not item.new_binding_allowed for item in old)
        if not repair and (
            candidate.model_transition is not None or candidate.state == KnowledgeState.REBUILDING.value
        ):
            raise KnowledgeRebuildingError()
        return repair

    @classmethod
    def _plan_inputs(cls, row, new_model_id, expected_revision, expected_generation, operation_id):
        if row is None:
            raise KnowledgeNotExistError()
        current = cls._facts(row)
        cls._references(row)  # Unknown business schema is coverage failure, never guessed.
        if (expected_revision is not None and expected_revision != row.model_config_revision) or (
            expected_generation is not None and expected_generation != row.index_generation
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
        try:
            selected = canonical_target_id(new_model_id)
        except ValueError as error:
            raise KnowledgeNoEmbeddingError() from error
        operation = operation_id or str(uuid4())
        transition = {
            "schema_version": 1,
            "operation_id": operation,
            "current_model_id": canonical_target_id(row.model) if row.model else selected,
            "pending_model_id": selected,
        }
        proposed = extract_knowledge_model_references(model=row.model or selected, model_transition=transition)
        return current, selected, transition, proposed

    @classmethod
    def _freeze(cls, session, row, runtime, bindings, selected, transition, repair, *, new_generation=None):
        current = canonical_target_id(row.model) if row.model else None
        changed = current != selected or row.model_transition is not None
        if repair or current is None:
            transition = {**transition, "current_model_id": selected}
        model = selected if repair or current is None else row.model
        transition = transition if changed else None
        actual_refs = extract_knowledge_model_references(model=model, model_transition=transition)
        # The original full target plan/receipts remain intact. Only the final
        # business slots change: explicit repair releases an invalid old slot.
        bindings = replace(bindings, verified=replace(bindings.verified, references=actual_refs))
        plan = PreparedKnowledgeModelChange(
            row.id,
            row.tenant_id,
            transition["operation_id"] if transition else None,
            model,
            transition,
            row.model_config_revision,
            row.index_generation,
            new_generation or str(uuid4()),
            changed,
            bindings,
            row,
            runtime,
        )
        _issued[plan] = (
            ref(plan),
            TransactionIdentity.capture(session),
            cls._facts(row),
            cls._plan_values(plan),
            bindings,
            runtime,
            row,
        )
        return plan

    @staticmethod
    def _binding_values(bindings):
        if bindings is None:
            return None
        verified = bindings.verified
        context = verified.context
        # Frozen DTOs carry values, not authority. Keep a detached manifest of
        # every consumed value, including the original complete receipt plan.
        return deepcopy(
            (
                bindings.source_key,
                bindings.expected_revision,
                bindings.new_revision,
                bindings.effective,
                verified.references,
                verified.extractor_version,
                context.source_key,
                context.expected_root_revision,
                context.locked_root_revision,
                context.locked_targets,
                context.old_references_digest,
                context.receipt_schema_version,
                id(context.transaction),
                tuple(
                    (id(receipt), receipt.source_key, receipt.target, id(receipt.issuer), receipt.schema_version)
                    for receipt in context.receipts
                ),
            )
        )

    @classmethod
    def _plan_values(cls, plan):
        return deepcopy(
            (
                plan.knowledge_id,
                plan.tenant_id,
                plan.operation_id,
                plan.model,
                plan.transition,
                plan.expected_revision,
                plan.expected_generation,
                plan.new_generation,
                plan.changed,
                cls._binding_values(plan.bindings),
            )
        )

    @classmethod
    def _check_plan(cls, session, plan):
        issued = _issued.get(plan) if isinstance(plan, PreparedKnowledgeModelChange) else None
        if issued is None or issued[0]() is not plan:
            raise ResourceReferenceInvalidError(reason="knowledge_model_plan_not_issued")
        try:
            issued[1].assert_current(session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_plan_transaction") from error
        if (
            plan.bindings is not issued[4]
            or plan.runtime is not issued[5]
            or plan.row is not issued[6]
            or cls._plan_values(plan) != issued[3]
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_plan_not_issued")
        if cls._facts(plan.row) != issued[2]:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_plan_changed")
        cls.repository._bound(session, plan.row)

    @classmethod
    def create(cls, session, row, *, login_user, project_created):
        cls._user(login_user)
        cls.repository.insert(session, row)
        runtime = get_reference_binding_runtime_sync()
        bindings = runtime.prepare_source_bindings(
            session,
            cls._source(row),
            cls._references(row),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lambda active: cls.repository.get(active, row.id, for_update=True),
            new_source=True,
        )
        cls._check_create_kinds(
            row,
            bindings,
            cls.repository.model_kinds(session, runtime.verifier, cls._source(row), bindings.verified.context),
        )
        result = project_created(row)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("native Knowledge projection must be synchronous")
        runtime.apply_source_bindings(session, bindings)
        return row

    @staticmethod
    def _check_create_kinds(row, bindings, kinds):
        if not bindings.verified.references:
            raise KnowledgeNoEmbeddingError()
        for receipt in bindings.verified.context.receipts:
            target = receipt.target
            if target.state != ReferenceState.VALID or not target.new_binding_allowed:
                raise ResourceReferenceInvalidError(reason="knowledge_new_model_invalid")
            if kinds.get(target.key) != "embedding":
                raise KnowledgeNoEmbeddingError()

    @classmethod
    async def acreate(cls, session, row, *, login_user, project_created):
        cls._user(login_user)
        await cls.repository.ainsert(session, row)
        runtime = await get_reference_binding_runtime()

        async def lock_root(active):
            return await cls.repository.aget(active, row.id, for_update=True)

        bindings = await runtime.aprepare_source_bindings(
            session,
            cls._source(row),
            cls._references(row),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            new_source=True,
        )
        cls._check_create_kinds(
            row,
            bindings,
            await cls.repository.amodel_kinds(session, runtime.verifier, cls._source(row), bindings.verified.context),
        )
        await project_created(row)
        await runtime.aapply_source_bindings(session, bindings)
        return row

    @classmethod
    def prepare_model_change(
        cls,
        session,
        knowledge_id,
        new_model_id,
        *,
        login_user,
        expected_model_config_revision=None,
        expected_index_generation=None,
        operation_id=None,
    ):
        cls._user(login_user)
        row = cls.repository.get(session, knowledge_id)
        facts, selected, transition, proposed = cls._plan_inputs(
            row, new_model_id, expected_model_config_revision, expected_index_generation, operation_id
        )
        runtime = get_reference_binding_runtime_sync()

        def lock_root(active):
            locked = cls.repository.get(active, knowledge_id, for_update=True)
            if locked is None or cls._facts(locked) != facts:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
            run_async_safe(cls._authorize(login_user, locked))
            return locked

        bindings = runtime.prepare_source_bindings(
            session,
            cls._source(row),
            proposed,
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
        )
        kinds = cls.repository.model_kinds(session, runtime.verifier, cls._source(row), bindings.verified.context)
        repair = cls._validate_configuration(row, bindings, kinds, selected)
        return cls._freeze(session, row, runtime, bindings, selected, transition, repair)

    @classmethod
    async def aprepare_model_change(
        cls,
        session,
        knowledge_id,
        new_model_id,
        *,
        login_user,
        expected_model_config_revision=None,
        expected_index_generation=None,
        operation_id=None,
    ):
        cls._user(login_user)
        row = await cls.repository.aget(session, knowledge_id)
        facts, selected, transition, proposed = cls._plan_inputs(
            row, new_model_id, expected_model_config_revision, expected_index_generation, operation_id
        )
        runtime = await get_reference_binding_runtime()

        async def lock_root(active):
            locked = await cls.repository.aget(active, knowledge_id, for_update=True)
            if locked is None or cls._facts(locked) != facts:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_configuration_changed")
            await cls._authorize(login_user, locked)
            return locked

        bindings = await runtime.aprepare_source_bindings(
            session,
            cls._source(row),
            proposed,
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
        )
        kinds = await cls.repository.amodel_kinds(
            session, runtime.verifier, cls._source(row), bindings.verified.context
        )
        repair = cls._validate_configuration(row, bindings, kinds, selected)
        return cls._freeze(session, row, runtime, bindings, selected, transition, repair)

    @classmethod
    def apply_model_change(cls, session, prepared):
        cls._check_plan(session, prepared)
        if prepared.changed:
            cls.repository.apply_model_configuration(
                session,
                prepared.row,
                model=prepared.model,
                transition=prepared.transition,
                expected_revision=prepared.expected_revision,
                expected_generation=prepared.expected_generation,
                new_generation=prepared.new_generation,
            )
            prepared.row.state = KnowledgeState.REBUILDING.value
            cls.repository.save(session, prepared.row)
            prepared.runtime.apply_source_bindings(session, prepared.bindings)
        return prepared.row

    @classmethod
    async def aapply_model_change(cls, session, prepared):
        cls._check_plan(session, prepared)
        if prepared.changed:
            await cls.repository.aapply_model_configuration(
                session,
                prepared.row,
                model=prepared.model,
                transition=prepared.transition,
                expected_revision=prepared.expected_revision,
                expected_generation=prepared.expected_generation,
                new_generation=prepared.new_generation,
            )
            prepared.row.state = KnowledgeState.REBUILDING.value
            await cls.repository.asave(session, prepared.row)
            await prepared.runtime.aapply_source_bindings(session, prepared.bindings)
        return prepared.row

    @staticmethod
    def _batch_values(batch):
        return deepcopy(
            (
                tuple(
                    (
                        change.source_key,
                        change.references,
                        change.extractor_version,
                        id(change.lock_source_root),
                        change.new_source,
                        change.effective,
                    )
                    for change in batch.changes
                ),
                batch.commands,
            )
        )

    @classmethod
    def _batch_state(cls, session, batch):
        state = _batches.get(batch) if isinstance(batch, KnowledgeModelChangeBatch) else None
        if state is None or state["original"]() is not batch or cls._batch_values(batch) != state["manifest"]:
            raise ResourceReferenceInvalidError(reason="knowledge_model_batch_not_issued")
        try:
            state["transaction"].assert_current(session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_model_batch_transaction") from error
        if cls.repository._tenant_id() != state["tenant"]:
            raise ResourceReferenceInvalidError(reason="knowledge_model_batch_tenant")
        return state

    @classmethod
    async def aplan_workbench_model_changes(cls, session, new_model_id, *, login_user, operation_id=None):
        cls._user(login_user)
        rows = await cls.repository.alist_spaces(session)
        operation = operation_id or str(uuid4())
        candidates, changes, commands = {}, [], []
        batch_ref = None
        for row in rows:
            _, selected, transition, references = cls._plan_inputs(row, new_model_id, None, None, operation)
            generation = str(uuid4())
            key = cls._source(row)
            candidates[key] = (selected, transition, generation)

            async def lock_root(active, knowledge_id=row.id):
                original = batch_ref() if batch_ref is not None else None
                state = cls._batch_state(active, original)
                await original.alock_inventory(active)
                return state["locked"][knowledge_id]

            changes.append(SourceBindingChange(key, references, KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION, lock_root))
            current = canonical_target_id(row.model) if row.model else None
            if current != selected or row.model_transition is not None:
                commands.append(
                    KnowledgeModelRebuildCommand(
                        row.id,
                        row.type,
                        operation,
                        row.model_config_revision + 1,
                        generation,
                        row.tenant_id,
                        login_user.user_id,
                    )
                )
        batch = KnowledgeModelChangeBatch(tuple(changes), tuple(commands))
        batch_ref = ref(batch)
        _batches[batch] = {
            "original": batch_ref,
            "transaction": TransactionIdentity.capture(session),
            "manifest": cls._batch_values(batch),
            "tenant": cls.repository._tenant_id(),
            "facts": tuple(cls._facts(row) for row in rows),
            "candidates": candidates,
            "runtime": await get_reference_binding_runtime(),
            "user": login_user,
            "locked": None,
        }
        return batch

    @classmethod
    async def aapply_workbench_model_changes(cls, session, batch, prepared_sources):
        state = cls._batch_state(session, batch)
        if not isinstance(prepared_sources, tuple):
            raise ResourceReferenceInvalidError(reason="knowledge_model_batch_prepared_required")
        relevant = tuple(item for item in prepared_sources if item.source_key.source_type == SourceType.KNOWLEDGE)
        if len({item.source_key for item in relevant}) != len(relevant) or {
            item.source_key for item in relevant
        } != set(state["candidates"]):
            raise ResourceReferenceInvalidError(reason="knowledge_model_batch_sources_changed")
        await batch.alock_inventory(session)
        changes = {item.source_key: item for item in batch.changes}
        plans = []
        # Validate/freeze every source before the first business write.
        for bindings in relevant:
            key = bindings.source_key
            change = changes[key]
            if (
                bindings.verified.references != change.references
                or bindings.verified.extractor_version != change.extractor_version
                or not bindings.effective
            ):
                raise ResourceReferenceInvalidError(reason="knowledge_model_batch_sources_changed")
            row = state["locked"][int(key.source_id)]
            selected, transition, generation = state["candidates"][key]
            kinds = await cls.repository.amodel_kinds(
                session, state["runtime"].verifier, key, bindings.verified.context
            )
            repair = cls._validate_configuration(row, bindings, kinds, selected)
            plans.append(
                cls._freeze(
                    session,
                    row,
                    state["runtime"],
                    bindings,
                    selected,
                    transition,
                    repair,
                    new_generation=generation,
                )
            )
        for plan in plans:
            await cls.aapply_model_change(session, plan)
        return batch.commands

    @classmethod
    def _removal_plan(cls, session, row, bindings, runtime, only_clear):
        if bindings is not None and bindings.verified.context.old_references_digest != reference_set_digest(
            cls._references(row)
        ):
            raise ReferenceCoverageNotReadyError(reason="knowledge_source_configuration_drift")
        plan = PreparedKnowledgeRemoval(row.id, row.tenant_id, only_clear, bindings, row, runtime)
        _removals[plan] = (
            ref(plan),
            TransactionIdentity.capture(session),
            cls._facts(row),
            cls._removal_values(plan),
            bindings,
            row,
            runtime,
        )
        return plan

    @classmethod
    def _removal_values(cls, plan):
        return deepcopy((plan.knowledge_id, plan.tenant_id, plan.only_clear, cls._binding_values(plan.bindings)))

    @classmethod
    def _check_removal(cls, session, plan):
        original = _removals.get(plan) if isinstance(plan, PreparedKnowledgeRemoval) else None
        if (
            original is None
            or original[0]() is not plan
            or plan.bindings is not original[4]
            or plan.row is not original[5]
            or plan.runtime is not original[6]
            or cls._removal_values(plan) != original[3]
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_removal_plan_not_issued")
        try:
            original[1].assert_current(session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_removal_plan_transaction") from error
        cls.repository._bound(session, plan.row)
        if cls._facts(plan.row) != original[2]:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_removal_plan_changed")

    @classmethod
    def prepare_removal(cls, session, knowledge_id, *, login_user, only_clear=False):
        cls._user(login_user)
        if type(only_clear) is not bool:
            raise ValueError("explicit Knowledge lifecycle is required")
        row = cls.repository.get(session, knowledge_id)
        if row is None:
            raise KnowledgeNotExistError()
        facts = cls._facts(row)

        def lock_root(active):
            locked = cls.repository.get(active, knowledge_id, for_update=True)
            if locked is None or cls._facts(locked) != facts:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_removal_plan_changed")
            run_async_safe(cls._authorize(login_user, locked, action="delete"))
            return locked

        if only_clear:
            # No configuration/source mutation: model invalidity must not turn
            # management cleanup into model execution admission.
            lock_root(session)
            return cls._removal_plan(session, row, None, None, True)
        runtime = get_reference_binding_runtime_sync()
        bindings = runtime.prepare_source_bindings(
            session,
            cls._source(row),
            (),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            effective=False,
        )
        return cls._removal_plan(session, row, bindings, runtime, False)

    @classmethod
    async def aprepare_removal(cls, session, knowledge_id, *, login_user, only_clear=False):
        cls._user(login_user)
        if type(only_clear) is not bool:
            raise ValueError("explicit Knowledge lifecycle is required")
        row = await cls.repository.aget(session, knowledge_id)
        if row is None:
            raise KnowledgeNotExistError()
        facts = cls._facts(row)

        async def lock_root(active):
            locked = await cls.repository.aget(active, knowledge_id, for_update=True)
            if locked is None or cls._facts(locked) != facts:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_removal_plan_changed")
            await cls._authorize(login_user, locked, action="delete")
            return locked

        if only_clear:
            await lock_root(session)
            return cls._removal_plan(session, row, None, None, True)
        runtime = await get_reference_binding_runtime()
        bindings = await runtime.aprepare_source_bindings(
            session,
            cls._source(row),
            (),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
            effective=False,
        )
        return cls._removal_plan(session, row, bindings, runtime, False)

    @classmethod
    def apply_removal(cls, session, prepared):
        cls._check_removal(session, prepared)
        cls.repository.clear_contents(session, prepared.row)
        if not prepared.only_clear:
            prepared.runtime.apply_source_bindings(session, prepared.bindings)
            cls.repository.delete(session, prepared.row)
        return prepared.row

    @classmethod
    async def aapply_removal(cls, session, prepared):
        cls._check_removal(session, prepared)
        await cls.repository.aclear_contents(session, prepared.row)
        if not prepared.only_clear:
            await prepared.runtime.aapply_source_bindings(session, prepared.bindings)
            await cls.repository.adelete(session, prepared.row)
        return prepared.row
