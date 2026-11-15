"""Whole SPACE copy admission on the existing confirmation and task ledger."""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid5

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.repositories.space_copy_job_repository import SpaceCopyJobRepository
from bisheng.knowledge.domain.repositories.space_copy_repository import SpaceCopyRepository, SpaceCopyScope, root_facts
from bisheng.knowledge.domain.schemas.move_processing import move_path_ids
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted, OperationItem, ResourceVersionTarget
from bisheng.knowledge.domain.schemas.processing_job_acceptance import NewProcessingItem, ProcessingConfiguration
from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.permission.application.business_authorization import VerifiedPermissionTarget, require_business_action
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.knowledge_copy_projection import KnowledgeCopyProjectionApplication
from bisheng.utils import generate_knowledge_index_name


def target(kind, ident, *, context, parent_type=None, parent_id=None, version=0):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=admission.tenant(),
        resource_type=kind,
        resource_id=str(ident),
        resource_version=version,
        context_version=context,
        parent_type=parent_type,
        parent_id=str(parent_id) if parent_id is not None else None,
    )


def authority_context():
    return admission.tenant(), get_current_permission_actor(), get_current_open_api_principal()


def assert_authority(context):
    current = authority_context()
    if current[0] != context[0] or current[1] is not context[1] or current[2] is not context[2]:
        raise KnowledgeOperationPlanChangedError()


def clean(session, context=None):
    if context is not None:
        assert_authority(context)
    if session.new or session.dirty or session.deleted:
        raise KnowledgeOperationPlanChangedError()


class SpaceCopyApplication:
    def __init__(
        self,
        *,
        session_factory=get_async_db_session,
        projection=None,
        creation_policy=KnowledgeCreationPolicy,
        quota=None,
    ):
        self.sessions = session_factory
        self.projection = projection or KnowledgeCopyProjectionApplication(session_factory=session_factory)
        self.creation_policy, self.quota = creation_policy, quota or self._quota
        self.rows, self.jobs, self.plans = SpaceCopyRepository(), SpaceCopyJobRepository(), OperationPlanRepository()

    @staticmethod
    async def _quota(identity):
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        await KnowledgeSpaceService(None, identity)._assert_space_creation_quota()

    async def authorize(self, identity, source):
        tenant = admission.tenant()
        async with self.sessions() as session:
            context = authority_context()
            actual = await self.rows.aroot(session, source["id"])
            clean(session, context)
        actor = get_current_permission_actor()
        if (
            actual.tenant_id != tenant
            or actual.user_id != source["user_id"]
            or actor is None
            or (actor.subject_type, actor.subject_id) != ("user", source["user_id"])
        ):
            raise PermissionDeniedError(reason="space_copy_actual_creator_required")
        if (
            actual.state != 1
            or actual.model_transition is not None
            or any(
                getattr(actual, name) != source[name]
                for name in ("model", "model_config_revision", "index_generation", "metadata_schema_revision")
            )
        ):
            raise KnowledgeOperationPlanChangedError()
        await require_business_action(
            identity, resource_type="knowledge_space", resource_id=source["id"], action="upload_file"
        )
        if get_current_permission_actor() is not actor or admission.tenant() != source["tenant_id"]:
            raise PermissionDeniedError(reason="space_copy_context_changed")

    async def _permissions(self, scope):
        components = await self.projection.composition._composition()
        nodes = [("knowledge_space", scope.source["id"], None, None)]
        for row in scope.files:
            path = move_path_ids(row["file_level_path"])
            nodes.append(
                (
                    "folder" if row["file_type"] == 0 else "knowledge_file",
                    row["id"],
                    "folder" if path else "knowledge_space",
                    path[-1] if path else scope.source["id"],
                )
            )
        result = []
        context = scope.digest
        for kind, ident, parent_type, parent_id in nodes:
            before = target(kind, ident, context=context, parent_type=parent_type, parent_id=parent_id)
            state = await components.state.mode_for_target(before)
            if (
                state.projection_state != "CURRENT"
                or state.mode not in {"CUSTOM", "INHERIT"}
                or (state.parent_type, state.parent_id)
                != (parent_type, str(parent_id) if parent_id is not None else None)
            ):
                raise KnowledgeOperationPlanChangedError()
            result.append(
                {
                    "kind": kind,
                    "id": ident,
                    "parent_type": parent_type,
                    "parent_id": parent_id,
                    "mode": state.mode,
                    "version": state.version,
                }
            )
        return result

    async def aprecheck(self, source_space_id, *, name, identity, entry_kind="web"):
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError("copy name must contain 1..200 characters")
        captured = await capture_processing_actor(
            identity, space_id=source_space_id, required_action="upload_file", entry_kind=entry_kind
        )
        async with admission.identity(
            captured.reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
        ) as (actual, _):
            authority = authority_context()
            async with self.sessions() as session:
                context = authority_context()
                scope = await self.rows.aload_scope(session, source_space_id)
                clean(session, context)
            await self.authorize(actual, scope.source)
            creation = await self.creation_policy.prepare(actual) if entry_kind == "web" else None
            await self.quota(actual)
            permissions = await self._permissions(scope)
            await self.authorize(actual, scope.source)
            if creation is not None:
                await self.creation_policy.revalidate(creation)
            assert_authority(authority)
            async with self.sessions() as session:
                context = authority_context()
                current = await self.rows.aload_scope(session, source_space_id, lock=True)
                if current != scope:
                    raise KnowledgeOperationPlanChangedError()
                physical = any(row["file_type"] == 1 for row in scope.files)
                result = await self.plans.acreate(
                    session,
                    operation="space_copy" if physical else "space_copy_empty",
                    space_id=source_space_id,
                    actor_reference=captured.reference,
                    targets=[],
                    target_revisions={"scope_digest": scope.digest},
                    source_revisions={
                        "model_config_revision": scope.source["model_config_revision"],
                        "index_generation": scope.source["index_generation"],
                    },
                    parameters={"name": name, "scope": scope.payload(), "permissions": permissions},
                    impact={
                        "file_count": sum(row["file_type"] == 1 for row in scope.files),
                        "directory_count": sum(row["file_type"] == 0 for row in scope.files),
                        "independent_copy": True,
                    },
                    expires_at=self.plans.clock() + timedelta(minutes=5),
                )
                clean(session, context)
                await session.commit()
            return result.model_copy(
                update={"can_execute": True, "valid_items": [OperationItem(id=source_space_id, type="space")]}
            )

    async def _read_plan(self, session, source_id, request):
        plan = await self.plans._locked(session, request.confirmation_id)
        self.plans._validate(plan)
        if (
            plan.space_id != source_id
            or plan.operation not in {"space_copy", "space_copy_empty"}
            or plan.plan_digest != request.plan_digest
        ):
            raise KnowledgeOperationPlanChangedError()
        return plan

    async def aconfirm(self, source_space_id, request, *, identity, entry_kind="web"):
        async with self.sessions() as session:
            context = authority_context()
            plan = await self._read_plan(session, source_space_id, request)
            reference, payload = deepcopy(plan.actor_reference), deepcopy(plan.parameters)
            unconsumed = plan.operation_id is None
            clean(session, context)
        scope = SpaceCopyScope(**payload["scope"])
        async with admission.identity(
            reference, current=identity, entry_kind=entry_kind, required_action="upload_file"
        ) as (actual, _):
            authority = authority_context()
            await self.authorize(actual, scope.source)
            creation = await self.creation_policy.prepare(actual) if entry_kind == "web" else None
            async with self.sessions() as session:
                context = authority_context()
                current = await self.rows.aload_scope(session, source_space_id)
                if (
                    (current.digest != scope.digest)
                    if unconsumed
                    else (current.execution_digest != scope.execution_digest)
                ):
                    raise KnowledgeOperationPlanChangedError()
            if await self._permissions(scope) != payload["permissions"]:
                raise KnowledgeOperationPlanChangedError()
            if creation is not None:
                await self.creation_policy.revalidate(creation)
            if unconsumed:
                await self.quota(actual)
            assert_authority(authority)
            result = await self._accept(source_space_id, request, scope, actual)
            from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner

            await SpaceCopyOwner(self).aensure_logical(
                result["knowledge"].id,
                result["processing_job"].job_id if result["processing_job"] else None,
                identity=actual,
                entry_kind=entry_kind,
            )
            async with self.sessions() as session:
                context = authority_context()
                row = await self.rows.aroot(session, result["knowledge"].id)
                clean(session, context)
                result["knowledge"] = row.model_copy(deep=True)
                if result["processing_job"] is None:
                    result["completed"] = row.state == 1
            return result

    async def _accept(self, source_id, request, scope, identity):
        creation_key = str(uuid5(UUID(request.confirmation_id), request.idempotency_key))
        scope_digest = scope.digest
        async with self.sessions() as session:
            context = authority_context()
            current = await self.rows.aload_scope(session, source_id, lock=True)
            plan = await self._read_plan(session, source_id, request)
            if (
                (current.execution_digest != scope.execution_digest)
                if plan.operation_id
                else (current.digest != scope_digest)
            ):
                raise KnowledgeOperationPlanChangedError()
            if plan.operation_id:
                if plan.operation == "space_copy":
                    job = await self.jobs.aget(session, plan.operation_id)
                    if job.idempotency_key != request.idempotency_key or job.parameters["confirmation_id"] != plan.id:
                        raise KnowledgeOperationPlanChangedError()
                    root = await self.rows.aroot(session, job.space_id)
                    accepted = JobAccepted(job_id=job.id, state=job.state, reused=True)
                else:
                    root = await self.rows.aroot(session, int(plan.operation_id))
                    accepted = None
                if root.creation_request_id != creation_key or root.creation_payload_hash != plan.request_hash:
                    raise KnowledgeOperationPlanChangedError()
                clean(session, context)
                return {
                    "knowledge": root.model_copy(deep=True),
                    "processing_job": accepted,
                    "completed": accepted is None and root.state == 1,
                }
            values = {
                name: deepcopy(scope.source[name])
                for name in ("description", "model", "metadata_fields", "processing_defaults", "auto_tag_enabled")
            }
            index = generate_knowledge_index_name()
            root = Knowledge(
                **values,
                name=plan.parameters["name"],
                type=3,
                state=0,
                user_id=scope.source["user_id"],
                tenant_id=admission.tenant(),
                index_name=index,
                collection_name=index,
                creation_request_id=creation_key,
                creation_payload_hash=plan.request_hash,
                is_released=False,
                is_shared=False,
            )

            async def created(actual):
                await Models.repository.aadd_space_creator(session, actual, user_id=scope.source["user_id"])

            await Models.acreate(session, root, login_user=identity, project_created=created)
            mapping = await self.rows.aallocate(session, scope=scope, target=root, creator_id=scope.source["user_id"])
            accepted = None
            if plan.operation == "space_copy":
                source_versions = {row["knowledge_file_id"]: row for row in scope.versions}
                permissions = {(value["kind"], value["id"]): value for value in plan.parameters["permissions"]}
                items = []
                for row in scope.files:
                    if row["file_type"] != 1:
                        continue
                    old = source_versions[row["id"]]
                    new = mapping["versions"][str(old["id"])]
                    copied = mapping["files"][str(row["id"])]
                    item_target = ResourceVersionTarget(
                        file_id=copied["id"], document_id=new["document_id"], version_id=new["id"]
                    )
                    path = move_path_ids(copied["file_level_path"])
                    permission = permissions[("knowledge_file", row["id"])]
                    items.append(
                        NewProcessingItem(
                            item_target,
                            root.id,
                            path[-1] if path else None,
                            {
                                "source_file": row,
                                "target_file": copied,
                                "source_version": old,
                                "target_version": {
                                    key: new[key]
                                    for key in ("id", "document_id", "knowledge_file_id", "version_no", "is_primary")
                                },
                                "permission": permission,
                                "source": scope.source,
                                "destination": root_facts(root),
                                "scope_digest": scope_digest,
                            },
                        )
                    )
                params = {
                    "operation_id": plan.id,
                    "confirmation_id": plan.id,
                    "plan_digest": plan.plan_digest,
                    "source_space_id": source_id,
                    "scope_digest": scope_digest,
                    "mapping": {
                        key: {ident: value["id"] for ident, value in rows.items()} for key, rows in mapping.items()
                    },
                    "permissions": plan.parameters["permissions"],
                }
                result = await self.jobs.acreate(
                    session,
                    space_id=root.id,
                    kind="space_copy",
                    idempotency_key=request.idempotency_key,
                    actor_user_id=plan.actor_user_id,
                    actor_reference=plan.actor_reference,
                    parameters=params,
                    configuration=ProcessingConfiguration(root.model_config_revision, root.index_generation),
                    items=items,
                )
                accepted = JobAccepted(job_id=result.job.id, state=result.job.state, reused=False)
                operation_id = result.job.id
            else:
                if any(row["file_type"] == 1 for row in scope.files):
                    raise KnowledgeOperationPlanChangedError()
                operation_id = str(root.id)
            await self.plans.aconsume(session, plan.id, operation_id=operation_id, expected_digest=plan.plan_digest)
            clean(session, context)
            await session.commit()
            return {"knowledge": root.model_copy(deep=True), "processing_job": accepted, "completed": False}
