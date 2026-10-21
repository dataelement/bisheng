"""Global immutable environment catalog; application data stays owner-only."""

from __future__ import annotations

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeProfile, RuntimeProfileDefault
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.permission.application.identity import resolve_permission_actor


def require_natural_owner(app, identity):
    if (
        identity.subject_type != "user"
        or identity.subject_id != app.owner_user_id
        or identity.tenant_id != app.tenant_id
    ):
        raise RuntimeConflict("natural_owner_required")


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
    """Persist resolution aliases so code-only releases never re-resolve an input."""

    def __init__(self, repository):
        self.repo = repository

    async def resolve(self, operation, input_key):
        import re

        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeDependencyPlan, RuntimeOperation

        if not re.fullmatch("[0-9a-f]{64}", input_key):
            raise RuntimeConflict("dependency_input_invalid")
        scope = f"{operation.tenant_id}/{operation.app_id}"
        async with self.repo.transaction():
            rows = await self.repo.find(RuntimeDependencyPlan, scope_key=scope, input_key=input_key, lock=True)
            if rows:
                row = rows[0]
                if row.artifact_id:
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
            return {"state": "claimed", "artifact_id": None}

    async def confirm(self, operation, input_key, artifact_id, *, verified=False):
        from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeDependencyPlan

        async with self.repo.transaction():
            rows = await self.repo.find(
                RuntimeDependencyPlan,
                scope_key=f"{operation.tenant_id}/{operation.app_id}",
                input_key=input_key,
                lock=True,
            )
            artifact = await self.repo.get(RuntimeArtifact, artifact_id)
            if (
                not rows
                or artifact is None
                or artifact.state != "verified"
                or artifact.kind != "dependencies"
                or (artifact.tenant_id, artifact.app_id) != (operation.tenant_id, operation.app_id)
            ):
                raise RuntimeConflict("dependency_materials_not_verified")
            row = rows[0]
            if row.artifact_id and row.artifact_id != artifact_id:
                raise RuntimeConflict("immutable_dependency_resolution")
            if not row.artifact_id and row.operation_id != operation.id:
                raise RuntimeConflict("dependency_owner_mismatch")
            row.artifact_id = artifact_id
            row.state = "verified" if verified else "materials_ready"
            await self.repo.save(row)
            return {"state": row.state, "artifact_id": artifact_id}


async def validate_offline_references(repository, app_id, manifest, principal):
    """Private selection is a human owner action; normal SAK publishing uses owner-bound materials."""
    delivery = manifest.delivery
    if delivery is None or not hasattr(delivery, "dependencies"):
        return
    identifiers = delivery.dependencies.offline_artifacts
    if not identifiers:
        return
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact
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
        if (
            (row.tenant_id, row.app_id) != (app.tenant_id, app.id)
            or getattr(principal, "actor_kind", None) != "natural_person"
            or int(getattr(principal, "actor_id", 0)) != app.owner_user_id
            or int(getattr(principal, "tenant_id", 0)) != app.tenant_id
        ):
            raise AppNotOwnedBySubjectError(details={"reason": "private_material_owner_selection_required"})
