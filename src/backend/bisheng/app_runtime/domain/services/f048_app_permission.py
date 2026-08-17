"""Business-owned F048 adapter for hosted applications (design D9, points 6-7).

The adapter answers one question — *is this a real, addressable ``app`` in this
actor's tenant?* — and then hands a ``VerifiedPermissionTarget`` to the sole
permission facade. It decides **no** permissions itself.

Three boundaries worth stating out loud, because each has a plausible-looking
wrong version:

* **It is a fact check, not an owner check.** ``resolve_permission_target``
  deliberately admits a non-owner of the same tenant. Refusing everyone but the
  owner here would silently exclude tenant administrators (allowed one layer
  up by the identity short-circuit) and every subject the owner explicitly
  granted — i.e. the entire point of AC-09. Owner-only rules (delete, the data
  tab) are **business pre-checks in the service layer**, because the permission
  runtime short-circuits administrators to ALLOW and therefore cannot express
  "owner only" at all (constitution C4 note).
* **No OpenFGA import** (arch-guard RULE-9). The only permission-side imports
  are ``permission.domain.schemas`` and ``PermissionActor``, matching every
  sibling adapter.
* **Never system-owned.** Unlike tools and dashboards there is no preset
  variant: a hosted app always has a natural-person owner, so this file has no
  ``authorize_system_owned`` path and an ownerless row is refused outright.

Template: ``tool/domain/services/f048_tool_permission.py`` /
``telemetry_search/domain/services/f048_dashboard_permission.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor

RESOURCE_TYPE = "app"

#: States in which an app is a legitimate permission target. ``deleted`` is
#: excluded: its grants are projected away on delete, and resolving it would
#: resurrect a target for a row that only survives for audit.
PERMISSION_VISIBLE_STATES = frozenset({"draft", "online", "pending_capacity", "stopped"})


@dataclass(frozen=True, slots=True)
class AppPermissionRecord:
    """The business facts a permission decision about one app depends on."""

    tenant_id: int
    resource_id: str
    state: str
    owner_user_id: int | None
    permission_version: int
    context_version: str


class AppPermissionLoader(Protocol):
    async def load_permission_record(self, resource_id: str) -> AppPermissionRecord | None: ...


class AppDaoPermissionLoader:
    """Load one app's tenant / owner / state before any authorization runs."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(self, resource_id: str) -> AppPermissionRecord | None:
        # Imported here rather than at module scope: this module sits in the
        # `app_runtime` domain and is imported by the composition root at
        # process start, while the ORM module pulls in the database stack.
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.app import AppDao

        if not resource_id:
            return None
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, resource_id)
        if row is None or not row.id:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type=RESOURCE_TYPE,
            resource_id=row.id,
        )
        context_version = sha256(
            (f"{permission_context}|{row.update_time.isoformat() if row.update_time else '0'}").encode()
        ).hexdigest()[:64]
        return AppPermissionRecord(
            tenant_id=tenant_id,
            resource_id=row.id,
            state=str(row.state),
            owner_user_id=row.owner_user_id,
            permission_version=version,
            context_version=context_version,
        )


class AppPermissionPort(Protocol):
    async def check_action(
        self,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        action: str,
    ) -> bool: ...

    async def batch_check_actions(
        self,
        actor: PermissionActor,
        targets: tuple[VerifiedPermissionTarget, ...],
        action: str,
    ) -> tuple[bool, ...]: ...

    async def authorize_created(self, **kwargs): ...

    async def project_delete(self, **kwargs): ...


class F048AppPermissionAdapter:
    """Validate hosted-application facts, then invoke the sole permission facade."""

    def __init__(self, *, loader: AppPermissionLoader, permission: AppPermissionPort) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(self, resource_id: str) -> AppPermissionRecord | None:
        return await self._loader.load_permission_record(resource_id)

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        record = await self._loader.load_permission_record(resource_id)
        return self._target(record, resource_id, actor, action=action)

    async def check_action(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> bool:
        target = await self.resolve_permission_target(
            resource_id=resource_id,
            actor=actor,
            action=action,
        )
        return await self._permission.check_action(actor, target, action)

    async def batch_check_loaded(
        self,
        *,
        records: tuple[AppPermissionRecord, ...],
        actor: PermissionActor,
        action: str,
    ) -> tuple[bool, ...]:
        """Check one action across an already-loaded page of apps (list rendering)."""
        targets = tuple(self._record_target(record, actor, action=action) for record in records)
        return await self._permission.batch_check_actions(actor, targets, action)

    async def build_creation_record(self, resource_id: str) -> AppPermissionRecord | None:
        """A record for a just-created app, pinned to ``permission_version = 0``.

        The creation path must NOT go through ``load_permission_record``: that
        asks the runtime for the app's CURRENT projected version, which does not
        exist yet — this projection is what creates it. Querying it first raised
        25008 ("projection is not current") after the app row was already
        written, rolling back every first publish (a chicken-and-egg). The
        runtime requires ``resource_version == 0`` at creation anyway, and
        ``_target`` only validates state / tenant / owner, none of which need the
        version. The row is still read so a vanished app is caught (returns
        ``None``) rather than projected onto nothing.
        """
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.app import AppDao

        if not resource_id:
            return None
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, resource_id)
        if row is None or not row.id:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        return AppPermissionRecord(
            tenant_id=tenant_id,
            resource_id=row.id,
            state=str(row.state),
            owner_user_id=row.owner_user_id,
            permission_version=0,
            context_version="",
        )

    async def authorize_created(
        self,
        *,
        record: AppPermissionRecord,
        actor: PermissionActor,
    ):
        """Project the creator as owner: CUSTOM mode, protected assignment.

        The owner's full action set is a property of the CUSTOM owner
        projection — this adapter never enumerates actions, so adding a seventh
        app action later needs no change here.
        """
        return await self._permission.authorize_created(
            actor=actor,
            target=self._record_target(record, actor),
            owner_user_id=record.owner_user_id,
            mode="CUSTOM",
            protected=True,
        )

    async def project_delete(
        self,
        *,
        record: AppPermissionRecord,
        actor: PermissionActor,
    ):
        return await self._permission.project_delete(
            actor=actor,
            target=self._record_target(record, actor),
        )

    def _record_target(
        self,
        record: AppPermissionRecord,
        actor: PermissionActor,
        *,
        action: str | None = None,
    ) -> VerifiedPermissionTarget:
        return self._target(record, record.resource_id, actor, action=action)

    @staticmethod
    def _target(
        record: AppPermissionRecord | None,
        resource_id: str,
        actor: PermissionActor,
        *,
        action: str | None = None,
    ) -> VerifiedPermissionTarget:
        del action  # every app action is uniform; no preset/system variant exists
        if (
            record is None
            or record.resource_id != resource_id
            or record.state not in PERMISSION_VISIBLE_STATES
            or (record.tenant_id != actor.current_tenant_id and not actor.super_admin)
            or record.owner_user_id is None
            or record.owner_user_id <= 0
        ):
            # One error for "absent", "another tenant's" and "deleted" alike:
            # distinguishing them here would leak the existence of apps the
            # caller may not know about (AC-29's information-disclosure rule
            # applies to the API surface too, not just the entry page).
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=RESOURCE_TYPE,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
