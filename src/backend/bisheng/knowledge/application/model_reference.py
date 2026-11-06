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
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
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
    next_state: int = KnowledgeState.REBUILDING.value
    purpose: str = "change"


_issued: WeakKeyDictionary = WeakKeyDictionary()
_removals: WeakKeyDictionary = WeakKeyDictionary()
_empty_scopes: WeakKeyDictionary = WeakKeyDictionary()


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
    def _freeze(
        cls,
        session,
        row,
        runtime,
        bindings,
        selected,
        transition,
        repair,
        *,
        new_generation=None,
        explicit_rebuild=False,
    ):
        current = canonical_target_id(row.model) if row.model else None
        changed = explicit_rebuild or current != selected or row.model_transition is not None
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
        return cls._register_model_plan(session, plan)

    @classmethod
    def _register_model_plan(cls, session, plan, background=None):
        _issued[plan] = (
            ref(plan),
            TransactionIdentity.capture(session),
            cls._facts(plan.row),
            cls._plan_values(plan),
            plan.bindings,
            plan.runtime,
            plan.row,
            None
            if background is None
            else (background, (background.tenant_id, background.task_id, background.task_name)),
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
                plan.next_state,
                plan.purpose,
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
        if issued[7] is not None:
            background, values = issued[7]
            current = get_current_background_task()
            if current is not background or (current.tenant_id, current.task_id, current.task_name) != values:
                raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_background_changed")
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
        _explicit_rebuild=False,
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
        return cls._freeze(
            session, row, runtime, bindings, selected, transition, repair, explicit_rebuild=_explicit_rebuild
        )

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
        _explicit_rebuild=False,
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
        return cls._freeze(
            session, row, runtime, bindings, selected, transition, repair, explicit_rebuild=_explicit_rebuild
        )

    @classmethod
    def prepare_rebuild(cls, session, knowledge_id, new_model_id, *, login_user, **expected):
        """Explicit work creates an operation even when the embedding is unchanged."""
        return cls.prepare_model_change(
            session, knowledge_id, new_model_id, login_user=login_user, _explicit_rebuild=True, **expected
        )

    @classmethod
    async def aprepare_rebuild(cls, session, knowledge_id, new_model_id, *, login_user, **expected):
        return await cls.aprepare_model_change(
            session, knowledge_id, new_model_id, login_user=login_user, _explicit_rebuild=True, **expected
        )

    @classmethod
    async def aprepare_empty_model_change(
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
        prepared = await cls.aprepare_model_change(
            session,
            knowledge_id,
            new_model_id,
            login_user=login_user,
            expected_model_config_revision=expected_model_config_revision,
            expected_index_generation=expected_index_generation,
            operation_id=operation_id,
        )
        scope = await ProcessingOwnerRepository().aassert_empty_model_change(session, knowledge_id)
        cls._check_plan(session, prepared)
        selected = canonical_target_id(new_model_id)
        references = extract_knowledge_model_references(model=selected, model_transition=None)
        bindings = replace(prepared.bindings, verified=replace(prepared.bindings.verified, references=references))
        plan = replace(
            prepared,
            model=selected,
            transition=None,
            operation_id=None,
            bindings=bindings,
            next_state=KnowledgeState.PUBLISHED.value,
            purpose="empty_change",
        )
        _empty_scopes[plan] = scope
        return cls._register_model_plan(session, plan)

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
            prepared.row.state = prepared.next_state
            cls.repository.save(session, prepared.row)
            prepared.runtime.apply_source_bindings(session, prepared.bindings)
        return prepared.row

    @classmethod
    async def aapply_model_change(cls, session, prepared):
        cls._check_plan(session, prepared)
        if prepared.purpose == "empty_change":
            scope = await ProcessingOwnerRepository().aassert_empty_model_change(session, prepared.knowledge_id)
            cls._check_plan(session, prepared)
            if scope != _empty_scopes.get(prepared):
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_empty_scope_changed")
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
            prepared.row.state = prepared.next_state
            await cls.repository.asave(session, prepared.row)
            await prepared.runtime.aapply_source_bindings(session, prepared.bindings)
        return prepared.row

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

    @classmethod
    def _finalization_inputs(cls, row, operation_id, expected_revision, expected_generation):
        if row is None:
            raise KnowledgeNotExistError()
        background = get_current_background_task()
        if (
            background is None
            or background.tenant_id != row.tenant_id
            or background.tenant_id != cls.repository._tenant_id()
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_background_required")
        cls._references(row)
        transition = row.model_transition
        if (
            transition is None
            or transition["operation_id"] != operation_id
            or type(expected_revision) is not int
            or row.model_config_revision != expected_revision
            or not isinstance(expected_generation, str)
            or not expected_generation
            or row.index_generation != expected_generation
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
        return cls._facts(row), canonical_target_id(transition["pending_model_id"]), background

    @classmethod
    def _freeze_finalization(cls, session, row, runtime, bindings, selected, operation, background, kinds):
        if bindings.verified.context.old_references_digest != reference_set_digest(cls._references(row)):
            raise ReferenceCoverageNotReadyError(reason="knowledge_source_configuration_drift")
        target_key = TargetKey(TargetType.MODEL, selected)
        target = next(item.target for item in bindings.verified.context.receipts if item.target.key == target_key)
        if target.state != ReferenceState.VALID or not target.new_binding_allowed:
            raise ResourceReferenceInvalidError(reason="knowledge_pending_model_invalid")
        if kinds.get(target_key) != "embedding":
            raise KnowledgeNoEmbeddingError()
        plan = PreparedKnowledgeModelChange(
            row.id,
            row.tenant_id,
            operation,
            selected,
            None,
            row.model_config_revision,
            row.index_generation,
            row.index_generation,
            True,
            bindings,
            row,
            runtime,
            KnowledgeState.PUBLISHED.value,
            "finalize",
        )
        return cls._register_model_plan(session, plan, background)

    @classmethod
    def prepare_finalization(
        cls,
        session,
        knowledge_id,
        *,
        operation_id,
        expected_model_config_revision,
        expected_index_generation,
    ):
        if get_current_background_task() is None:
            raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_background_required")
        row = cls.repository.get(session, knowledge_id)
        facts, selected, background = cls._finalization_inputs(
            row, operation_id, expected_model_config_revision, expected_index_generation
        )
        runtime = get_reference_binding_runtime_sync()

        def lock_root(active):
            locked = cls.repository.get(active, knowledge_id, for_update=True)
            current, pending, worker = cls._finalization_inputs(
                locked, operation_id, expected_model_config_revision, expected_index_generation
            )
            if current != facts or pending != selected or worker is not background:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
            return locked

        bindings = runtime.prepare_source_bindings(
            session,
            cls._source(row),
            extract_knowledge_model_references(model=selected),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
        )
        kinds = cls.repository.model_kinds(session, runtime.verifier, cls._source(row), bindings.verified.context)
        return cls._freeze_finalization(session, row, runtime, bindings, selected, operation_id, background, kinds)

    @classmethod
    async def aprepare_finalization(
        cls,
        session,
        knowledge_id,
        *,
        operation_id,
        expected_model_config_revision,
        expected_index_generation,
    ):
        if get_current_background_task() is None:
            raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_background_required")
        row = await cls.repository.aget(session, knowledge_id)
        facts, selected, background = cls._finalization_inputs(
            row, operation_id, expected_model_config_revision, expected_index_generation
        )
        runtime = await get_reference_binding_runtime()

        async def lock_root(active):
            locked = await cls.repository.aget(active, knowledge_id, for_update=True)
            current, pending, worker = cls._finalization_inputs(
                locked, operation_id, expected_model_config_revision, expected_index_generation
            )
            if current != facts or pending != selected or worker is not background:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
            return locked

        bindings = await runtime.aprepare_source_bindings(
            session,
            cls._source(row),
            extract_knowledge_model_references(model=selected),
            extractor_version=KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
            lock_source_root=lock_root,
        )
        kinds = await cls.repository.amodel_kinds(
            session, runtime.verifier, cls._source(row), bindings.verified.context
        )
        return cls._freeze_finalization(session, row, runtime, bindings, selected, operation_id, background, kinds)

    @classmethod
    def apply_finalization(cls, session, prepared):
        if not isinstance(prepared, PreparedKnowledgeModelChange) or prepared.purpose != "finalize":
            raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_plan_required")
        return cls.apply_model_change(session, prepared)

    @classmethod
    async def aapply_finalization(cls, session, prepared):
        if not isinstance(prepared, PreparedKnowledgeModelChange) or prepared.purpose != "finalize":
            raise ResourceReferenceInvalidError(reason="knowledge_model_finalization_plan_required")
        return await cls.aapply_model_change(session, prepared)
