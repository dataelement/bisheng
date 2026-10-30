"""Owner environment assets. Save/delete have no orchestration dependency."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from bisheng.app_publish.domain.repositories.app_secret_repository import AppSecretConfigRepository
from bisheng.app_publish.domain.secret_security import (
    AppSecretCipher,
    compare_environment,
    validate_environment,
    validate_name,
    validate_value,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_factory import AppManageForbiddenError
from bisheng.common.errcode.app_publish import (
    AppPublishOwnerOnlyError,
    AppPublishStateConflictError,
    AppSecretEncryptionUnavailableError,
    AppSecretInvalidError,
    AppSecretRevisionConflictError,
)
from bisheng.common.permission_identity import check_tenant_admin


@dataclass(frozen=True)
class AppSecretSnapshot:
    revision: int
    env: dict[str, str] = field(repr=False)
    sensitive_env_names: list[str]
    declaration_digest: str


def secret_names(declaration):
    """Read frozen references only; never interpret arbitrary environment input."""
    return sorted({entry["name"] for entry in (declaration or {}).get("secrets", [])})


class AppSecretService:
    def __init__(self, repository=None, cipher=None, running_snapshot=None):
        self.repo = repository or AppSecretConfigRepository()
        self._cipher = cipher
        if running_snapshot is None:
            from bisheng.app_runtime.application.runtime_secrets import running_environment_snapshot

            running_snapshot = running_environment_snapshot
        self.running_snapshot = running_snapshot

    @property
    def cipher(self):
        return self._cipher or AppSecretCipher.configured()

    @staticmethod
    def _require_owner(app, actor):
        if not isinstance(actor, UserPayload) or actor.tenant_id != app.tenant_id or actor.user_id != app.owner_user_id:
            raise AppPublishOwnerOnlyError()

    @staticmethod
    def _require_live(app):
        if app.state == "deleted":
            raise AppPublishStateConflictError()

    def _entries(self, row, app):
        if row is None:
            return {}
        if row.tenant_id != app.tenant_id:
            raise AppSecretEncryptionUnavailableError()
        return self.cipher.decrypt(row.values_ciphertext, tenant_id=app.tenant_id, app_id=app.id)

    async def save(self, app_id, name, *, value, expected_revision, actor):
        validate_name(name)
        validate_value(value)
        return await self._change(app_id, name, value=value, expected_revision=expected_revision, actor=actor)

    async def delete(self, app_id, name, *, expected_revision, actor, confirm_online_impact=False):
        validate_name(name)
        return await self._change(
            app_id,
            name,
            value=None,
            expected_revision=expected_revision,
            actor=actor,
            confirm_online_impact=confirm_online_impact,
        )

    async def _change(self, app_id, name, *, value, expected_revision, actor, confirm_online_impact=False):
        async with self.repo.transaction() as session:
            app = await self.repo.app(session, app_id, lock=True)
            self._require_owner(app, actor)
            self._require_live(app)
            row = await self.repo.config(session, app_id, lock=True)
            if (row.revision if row else 0) != expected_revision:
                raise AppSecretRevisionConflictError()
            entries = self._entries(row, app)
            now = datetime.utcnow()
            if value is None:
                version = await self.repo.version(session, app.id, app.current_version_id)
                if (
                    app.state == "online"
                    and version
                    and name in secret_names(version.capabilities)
                    and not confirm_online_impact
                ):
                    raise AppSecretInvalidError(reason="confirm_online_impact_required")
                entries.pop(name, None)
            else:
                entries[name] = {"value": value, "updated_by": actor.user_id, "updated_at": now.isoformat()}
            validate_environment({key: item["value"] for key, item in entries.items()})
            ciphertext = self.cipher.encrypt(entries, tenant_id=app.tenant_id, app_id=app.id)
            revision = await self.repo.store(
                session,
                app,
                row,
                ciphertext=ciphertext,
                actor_id=actor.user_id,
                expected_revision=expected_revision,
                now=now,
            )
            await self.repo.append_audit(
                session,
                app,
                actor,
                name=name,
                action="app.secret.delete" if value is None else "app.secret.set",
                revision=revision,
                present=value is not None and value != "",
            )
            return {"revision": revision, "present": value is not None and value != "", "updated_at": now.isoformat()}

    async def get(self, app_id, *, actor):
        async with self.repo.read_transaction(app_id) as (session, app):
            from bisheng.app_runtime.application.tenant_access import require_app_request_tenant

            if not isinstance(actor, UserPayload):
                raise AppManageForbiddenError()
            require_app_request_tenant(app.tenant_id, actor, allow_global_super=True)
            owner = actor.tenant_id == app.tenant_id and actor.user_id == app.owner_user_id
            if not owner and not actor.is_global_super and not await check_tenant_admin(actor.user_id, app.tenant_id):
                from bisheng.permission.application.business_authorization import check_business_action

                if not await check_business_action(actor, resource_type="app", resource_id=app.id, action="edit"):
                    raise AppManageForbiddenError()
            row = await self.repo.config(session, app.id)
            entries = self._entries(row, app)
            current = await self.repo.version(session, app.id, app.current_version_id)
            pending = await self.repo.pending_version(session, app)
            approved = set(secret_names(current.capabilities if current else {}))
            proposed = set(secret_names(pending.capabilities if pending else {}))
            names = approved | proposed | (set(entries) if owner else set())
            items = []
            for name in sorted(names):
                entry = entries.get(name)
                present = bool(entry and entry["value"] != "")
                item = {
                    "name": name,
                    "present": present,
                    "approved_reference": name in approved,
                    "pending_reference": name in proposed,
                }
                if owner:
                    item.update(mask="••••••" if present else None, updated_at=entry["updated_at"] if entry else None)
                items.append(item)
            runtime = {
                "comparison": "not_running" if app.state != "online" else "unknown",
                "saved_revision": row.revision if row else 0,
                "running_operation_id": None,
                "running_version_id": None,
                "route_epoch": None,
                "changed_names": [],
                "rebuild_operation": None,
            }
            if app.state == "online":
                from bisheng.app_runtime.application.runtime_secrets import rebuild_status

                runtime["rebuild_operation"] = await rebuild_status(app.id, session=session)
            # The F054 public adapter supplies the actual route-bound frozen environment.
            if app.state == "online" and self.running_snapshot is not None:
                snapshot = await self.running_snapshot(app.id, session=session)
                if snapshot is not None:
                    comparison, changed = compare_environment(
                        sorted(approved), {key: item["value"] for key, item in entries.items()}, snapshot.env
                    )
                    runtime.update(
                        comparison=comparison,
                        changed_names=changed,
                        running_operation_id=snapshot.operation_id,
                        running_version_id=snapshot.version_id,
                        route_epoch=snapshot.route_epoch,
                    )
            return {
                "revision": row.revision if row else 0,
                "updated_at": row.update_time.isoformat() if row and row.update_time else None,
                "items": items,
                "runtime": runtime,
            }

    async def reference_status(self, app_id, declaration):
        """Trusted declaration summaries only: never return values or owner masks."""
        names = secret_names(declaration)
        if not names:
            return []
        async with self.repo.transaction() as session:
            app = await self.repo.app(session, app_id)
            entries = self._entries(await self.repo.config(session, app.id), app)
            return [
                {
                    "kind": "secret",
                    "name": name,
                    "revoked": False,
                    "reason": "ok" if entries.get(name, {}).get("value", "") != "" else "missing_value",
                }
                for name in names
            ]

    async def formal_snapshot(self, app, approved_version, *, session, expected_revision=None):
        from bisheng.core.context.tenant import get_current_tenant_id

        bound = app
        if bound.tenant_id != get_current_tenant_id():
            raise AppSecretEncryptionUnavailableError()
        if (
            bound.tenant_id != app.tenant_id
            or approved_version.app_id != bound.id
            or approved_version.id not in {bound.current_version_id, bound.pending_version_id}
        ):
            raise AppSecretEncryptionUnavailableError()
        self._require_live(bound)
        row = await self.repo.config(session, app.id, lock=True)
        revision = row.revision if row else 0
        if expected_revision is not None and revision != expected_revision:
            raise AppSecretRevisionConflictError()
        entries = self._entries(row, app)
        names = secret_names(approved_version.capabilities)
        env = {name: entries.get(name, {}).get("value", "") for name in names}
        digest = hashlib.sha256(json.dumps(names, separators=(",", ":")).encode()).hexdigest()
        return AppSecretSnapshot(revision=revision, env=env, sensitive_env_names=names, declaration_digest=digest)

    @staticmethod
    def preview_environment(declaration):
        return dict.fromkeys(secret_names(declaration), "")

    async def delete_for_app(self, app_id):
        async with self.repo.transaction() as session:
            app = await self.repo.app(session, app_id, lock=True)
            if app.state != "deleted":
                raise AppPublishStateConflictError()
            await self.repo.delete_asset(session, app_id)
