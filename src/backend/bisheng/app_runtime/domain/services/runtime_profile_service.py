"""Global immutable catalog and application materials authorized by F048."""

from __future__ import annotations

from datetime import datetime

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeProfile, RuntimeProfileDefault
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.permission.application.identity import resolve_permission_actor


async def require_platform_super(actor):
    identity = await resolve_permission_actor(actor)
    if identity.subject_type != "user" or not identity.super_admin:
        raise RuntimeConflict("platform_super_admin_required")
    return identity


class RuntimeProfileService:
    def __init__(self, repository=None):
        self.repo = repository or RuntimeDeliveryRepository()

    async def import_revision(self, document, *, actor):
        identity = await require_platform_super(actor)
        definition = RuntimeProfileDefinition.model_validate(document)
        body = definition.model_dump(mode="json")
        digest = content_digest(body)
        async with self.repo.transaction():
            existing = await self.repo.find(
                RuntimeProfile, code=definition.code, revision=definition.revision, lock=True
            )
            if existing:
                if existing[0].content_digest != digest:
                    raise RuntimeConflict("immutable_profile_conflict")
                return existing[0]
            return await self.repo.save(
                RuntimeProfile(
                    id=digest[:32],
                    code=definition.code,
                    revision=definition.revision,
                    language=definition.language,
                    contract_version=definition.contract_version,
                    created_by=identity.subject_id,
                    definition=body,
                    content_digest=digest,
                )
            )

    async def set_default(self, language, profile_id, *, expected_generation, actor):
        await require_platform_super(actor)
        async with self.repo.transaction():
            profile = await self.repo.get(RuntimeProfile, profile_id)
            if profile is None or profile.language != language or profile.status != "active":
                raise RuntimeConflict("profile_unavailable")
            rows = await self.repo.find(RuntimeProfileDefault, language=language, lock=True)
            if rows:
                row = rows[0]
                if row.generation != expected_generation:
                    raise RuntimeConflict("default_generation_conflict")
                row.profile_id = profile.id
                row.generation += 1
            else:
                if expected_generation != 0:
                    raise RuntimeConflict("default_generation_conflict")
                row = RuntimeProfileDefault(language=language, profile_id=profile.id)
            return await self.repo.save(row)

    async def resolve(self, language, reference, platform):
        if reference:
            code, sep, revision = reference.rpartition("@")
            if not sep or not revision.isdigit():
                raise RuntimeConflict("profile_revision_required")
            rows = await self.repo.find(RuntimeProfile, code=code, revision=int(revision))
            profile = rows[0] if rows else None
        else:
            defaults = await self.repo.find(RuntimeProfileDefault, language=language)
            profile = await self.repo.get(RuntimeProfile, defaults[0].profile_id) if defaults else None
        if profile is None or profile.status != "active" or profile.language != language:
            raise RuntimeConflict("profile_unavailable")
        entry = profile.definition.get("platforms", {}).get(platform)
        if not entry:
            raise RuntimeConflict("profile_platform_incompatible")
        return {
            "profile_id": profile.id,
            "profile_digest": profile.content_digest,
            "profile_revision": f"{profile.code}@{profile.revision}",
            "platform": platform,
            "language": profile.language,
            **entry,
        }

    async def list_defaults(self):
        return [
            {"language": row.language, "profile_id": row.profile_id, "generation": row.generation}
            for row in await self.repo.find(RuntimeProfileDefault)
        ]

    async def list_public(self):
        return [
            {
                "id": row.id,
                "code": row.code,
                "revision": row.revision,
                "language": row.language,
                "status": row.status,
                "platforms": list(row.definition.get("platforms", {})),
            }
            for row in await self.repo.find(RuntimeProfile)
        ]


class RuntimeDependencyService:
    """Persist immutable cache aliases and the selection made by each prepare."""

    def __init__(self, repository, *, clock=datetime.utcnow):
        self.repo = repository
        self.clock = clock

    async def _operation(self, operation):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation

        current = await self.repo.get(RuntimeOperation, operation.id, lock=True)
        if (
            current is None
            or (current.tenant_id, current.app_id, current.node_id)
            != (
                operation.tenant_id,
                operation.app_id,
                operation.node_id,
            )
            or current.kind != "prepare"
            or current.status in {"completed", "failed", "cancelled", "timed_out"}
            or current.deadline <= self.clock()
            or current.payload.get("cancel_requested")
        ):
            raise RuntimeConflict("dependency_operation_expired")
        return current

    async def validated_artifact(self, operation, input_key, artifact_id, *, producer_operation_id=None):
        from bisheng.app_runtime.domain.models.runtime_delivery import (
            RuntimeArtifact,
            RuntimeOperation,
            RuntimeTransfer,
        )

        artifact = await self.repo.get(RuntimeArtifact, artifact_id)
        profile = operation.payload.get("profile") or {}
        if (
            artifact is None
            or artifact.state != "verified"
            or artifact.kind != "dependencies"
            or (
                artifact.tenant_id,
                artifact.app_id,
            )
            != (operation.tenant_id, operation.app_id)
            or (profile.get("platform") and artifact.platform != profile["platform"])
        ):
            raise RuntimeConflict("dependency_materials_not_verified")
        original = artifact.metadata_.get("input_key") == input_key and (
            not profile.get("profile_id") or artifact.metadata_.get("profile_id") == profile["profile_id"]
        )
        if original:
            return artifact
        # Identical bytes can have several resolutions. Validate the durable
        # producing operation/confirmed transfer rather than rewriting provenance.
        producer_id = producer_operation_id or operation.id
        producer = await self.repo.get(RuntimeOperation, producer_id)
        transfers = await self.repo.find(
            RuntimeTransfer,
            operation_id=producer_id,
            artifact_id=artifact_id,
            action="upload",
            state="confirmed",
        )
        produced_profile = producer.payload.get("profile", {}) if producer else {}
        selected = producer.payload.get("dependency_resolution", {}) if producer else {}
        if (
            producer is None
            or (producer.tenant_id, producer.app_id) != (operation.tenant_id, operation.app_id)
            or not transfers
            or selected.get("input_key") != input_key
            or selected.get("artifact_id") not in {None, artifact_id}
            or any(
                produced_profile.get(field) != profile.get(field)
                for field in ("profile_id", "profile_digest", "platform", "abi", "runtime_image_id")
            )
        ):
            raise RuntimeConflict("dependency_materials_not_verified")
        return artifact

    async def _remember(self, operation, row):
        selected = operation.payload.get("dependency_resolution")
        if selected and (
            selected.get("input_key") != row.input_key
            or (selected.get("artifact_id") and selected["artifact_id"] != (row.artifact_id or None))
        ):
            raise RuntimeConflict("immutable_dependency_selection")
        operation.payload = {
            **operation.payload,
            "dependency_resolution": {
                "input_key": row.input_key,
                "artifact_id": row.artifact_id or None,
                "state": row.state,
            },
        }
        await self.repo.save(operation)

    async def resolve(self, operation, input_key):
        import re

        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeDependencyPlan, RuntimeOperation

        if not isinstance(input_key, str) or not re.fullmatch("[0-9a-f]{64}", input_key):
            raise RuntimeConflict("dependency_input_invalid")
        scope = f"{operation.tenant_id}/{operation.app_id}"
        async with self.repo.transaction():
            operation = await self._operation(operation)
            rows = await self.repo.find(RuntimeDependencyPlan, scope_key=scope, input_key=input_key, lock=True)
            if rows:
                row = rows[0]
                if row.artifact_id:
                    await self.validated_artifact(
                        operation, input_key, row.artifact_id, producer_operation_id=row.operation_id
                    )
                    if row.state not in {"materials_ready", "verified"}:
                        raise RuntimeConflict("dependency_materials_not_verified")
                    await self._remember(operation, row)
                    return {"state": row.state, "artifact_id": row.artifact_id}
                previous = await self.repo.get(RuntimeOperation, row.operation_id)
                if (
                    row.operation_id != operation.id
                    and previous is not None
                    and previous.status not in {"failed", "cancelled", "timed_out", "completed"}
                ):
                    raise RuntimeConflict("dependency_preparing")
                row.operation_id = operation.id
            else:
                row = RuntimeDependencyPlan(
                    tenant_id=operation.tenant_id,
                    app_id=operation.app_id,
                    scope_key=scope,
                    input_key=input_key,
                    operation_id=operation.id,
                )
            await self.repo.save(row)
            await self._remember(operation, row)
            return {"state": "claimed", "artifact_id": None}

    async def confirm(self, operation, input_key, artifact_id, *, verified=False):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeDependencyPlan

        async with self.repo.transaction():
            operation = await self._operation(operation)
            rows = await self.repo.find(
                RuntimeDependencyPlan,
                scope_key=f"{operation.tenant_id}/{operation.app_id}",
                input_key=input_key,
                lock=True,
            )
            await self.validated_artifact(operation, input_key, artifact_id)
            if not rows:
                raise RuntimeConflict("dependency_materials_not_verified")
            row = rows[0]
            if row.artifact_id and row.artifact_id != artifact_id:
                raise RuntimeConflict("immutable_dependency_resolution")
            if not row.artifact_id and row.operation_id != operation.id:
                raise RuntimeConflict("dependency_owner_mismatch")
            row.artifact_id = artifact_id
            row.state = "verified" if verified or row.state == "verified" else "materials_ready"
            await self.repo.save(row)
            await self._remember(operation, row)
            return {"state": row.state, "artifact_id": artifact_id}


async def validate_offline_references(repository, app_id, manifest, principal):
    """Keep material ownership fixed while authorizing the actual app editor."""
    delivery = manifest.delivery
    if delivery is None or not hasattr(delivery, "dependencies"):
        return
    identifiers = delivery.dependencies.offline_artifacts
    if not identifiers:
        return
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact
    from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService
    from bisheng.common.errcode.app_publish import AppNotOwnedBySubjectError
    from bisheng.core.context.tenant import bypass_tenant_filter

    app = await repository.get_application(app_id)
    for ident in identifiers:
        with bypass_tenant_filter():
            row = await repository.get(RuntimeArtifact, ident)
        if row is None or row.kind != "offline" or row.state != "verified":
            raise AppNotOwnedBySubjectError(details={"reason": "offline_material_unavailable"})
        if row.visibility == "public":
            continue
        if app is None or (row.tenant_id, row.app_id) != (app.tenant_id, app.id):
            raise AppNotOwnedBySubjectError(details={"reason": "private_material_scope_mismatch"})
        await AppAuthorizationService.authorize_loaded_app(principal, app, "content_read")
