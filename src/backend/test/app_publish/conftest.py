"""Shared fixtures for the app_publish (F055) test package.

Runs anywhere by default: an in-memory aiosqlite database holding the tables
F055 touches, bound into the app_publish modules by monkeypatching
``get_async_db_session`` (repo precedent: ``test/app_runtime/conftest.py``,
``test/open_api/conftest.py``). Nothing here weakens an assertion to make it
pass locally — tests that genuinely need MinIO / OpenFGA / MySQL say so
themselves and skip when the middleware is absent.

Seven things this file exists to prevent:

* **A tenant-admin false green.** ``tenant_admin_user`` is a *real* tenant
  administrator of a **child** tenant, not a platform super admin. The Root
  tenant has no tenant administrators at all (``TenantAdminService.
  list_tenant_admins`` returns ``[]`` for it by construction), which is exactly
  why AC-21's approver resolution needs a Root fallback — and why proving it
  with a super admin proves nothing.
* **A half-stubbed orchestrator.** ``fake_orchestrator`` replaces **all ten**
  ``orchestrator_client`` methods and asserts its stub set still equals the
  facade's public surface. Miss one and it silently falls through to real HTTP
  against 127.0.0.1:8091, which surfaces as a connection error far from the
  test that caused it.
* **Two copies of the tier seed.** ``tier_seed`` runs the real
  ``seed_resource_tiers()`` (T015). Manifest tests and tier tests share it, so
  "what light means" can never drift between the two suites.
* **Tar entry kinds nobody thinks of.** ``tarball_factory`` can emit symlinks,
  hardlinks, device nodes and FIFOs — none of which need root, because
  ``TarInfo`` objects are written directly rather than created on disk. A zip
  only has absolute paths and ``..`` to worry about; a tar has four more
  (design pit 15), and a factory that cannot produce them lets the gate ship
  half-built.
* **Real MinIO in a unit test.** ``fake_minio`` backs the storage facade with a
  temp directory and records every call, so the "never read the package into
  memory" and "the bucket is created idempotently" assertions have something to
  observe.
* **Proxy-induced mass ERRORs.** A stray ``ALL_PROXY=socks://`` makes every
  httpx client fail on the missing ``socksio`` extra and turns the whole
  package into ERRORs. The autouse fixture strips the six variables.
* **A green suite over an absent module.** ``fake_orchestrator`` /
  ``fake_f054_services`` / ``fake_publish_approval`` all ``import_module`` their
  target and let an ``ImportError`` through. While F054's service layer was
  landing they stood same-named placeholders into ``sys.modules`` instead, which
  meant the pipeline suite asserted against stubs of its own making.

Import discipline: nothing from ``bisheng.app_publish.domain.services`` is
imported at module level — fixtures import lazily inside their body, which is
what lets a test file that is written before its service still be collected.
What they do **not** do is stand a placeholder into ``sys.modules`` when the
module is missing: an earlier revision did that while F054's service layer was
in flight, and a suite that goes green against a module which does not exist is
worse than a red one. Everything now binds the real module and fails loudly.
"""

from __future__ import annotations

import gzip
import importlib
import io
import os
import tarfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_PROXY_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")

# Fixed ids keep assertions readable and never collide with real seed data.
ROOT_TENANT_ID = 1
SUB_TENANT_ID = 2
OWNER_USER_ID = 92001
DEPT_ADMIN_USER_ID = 92002
TENANT_ADMIN_USER_ID = 92003
SUPER_ADMIN_USER_ID = 92004
SERVICE_ACCOUNT_USER_ID = 92010

DEPT_BUSINESS_KEY = "BS@f055dept"
DEPT_NAME = "研发中心"

# ``user.password`` is NOT NULL; seeded rows never authenticate.
SEED_PASSWORD_PLACEHOLDER = "x"

#: Directory holding the baseline package contents (``bisheng-app.yaml`` +
#: ``main.py`` + ``requirements.txt``). ``tarball_factory`` packs it by default.
MINIMAL_APP_DIR = Path(__file__).parent / "fixtures" / "minimal_app"

#: Bucket the pipeline stores code snapshots in. Deliberately **not** the
#: shared public bucket: ``src/frontend/nginx.conf`` proxies the public bucket's
#: keys anonymously (design K5 / pit 13).
APPS_BUCKET = "bisheng-apps"

# Modules that bind ``get_async_db_session`` by name at import time. Absent
# ones (not implemented yet) are skipped silently — the tuple is the union of
# what exists today and what waves 2-3 will add.
_SESSION_PATCH_TARGETS = (
    "bisheng.core.database",
    "bisheng.core.database.manager",
    "bisheng.database.models.app",
    "bisheng.database.models.app_version",
    "bisheng.database.models.app_instance",
    "bisheng.database.models.audit_log",
    "bisheng.database.models.department",
    "bisheng.database.models.department_admin_grant",
    "bisheng.database.models.resource_tier",
    "bisheng.database.models.tenant",
    "bisheng.user.domain.models.user",
    "bisheng.user.domain.models.user_role",
    "bisheng.app_publish.domain.models.app_deployment",
    "bisheng.app_publish.domain.services.package_service",
    "bisheng.app_publish.domain.services.manifest_validator",
    "bisheng.app_publish.domain.services.secret_scanner",
    "bisheng.app_publish.domain.services.resource_tier_service",
    "bisheng.app_publish.domain.services.version_service",
    "bisheng.app_publish.domain.services.precheck_service",
    "bisheng.app_publish.domain.services.publish_pipeline_service",
    "bisheng.app_publish.domain.services.publish_approval_service",
    "bisheng.app_publish.domain.services.publish_status_service",
    "bisheng.app_publish.domain.services.publish_notification_service",
    "bisheng.app_publish.domain.services.publish_online_service",
    "bisheng.app_publish.domain.services.publish_terminal_service",
    "bisheng.app_publish.domain.services.app_publish_scenario_handler",
    "bisheng.app_runtime.domain.services.app_state_service",
    "bisheng.app_runtime.domain.services.app_meta_service",
    "bisheng.app_publish.composition",
    "bisheng.approval.domain.services.approval_gate",
    "bisheng.approval.domain.services.approver_resolver",
    "bisheng.approval.domain.services.approval_center_service",
    "bisheng.approval.domain.services.approval_notification_service",
    # The gate reads scenarios / routes / nodes and writes instances through
    # these; each does ``from bisheng.core.database import get_async_db_session``
    # at import time, so patching the source module alone would leave them
    # pointed at the real engine.
    "bisheng.approval.domain.repositories.approval_instance_repository",
    "bisheng.approval.domain.repositories.approval_scenario_repository",
    "bisheng.approval.domain.repositories.approval_query_repository",
)

_TABLES = (
    "tenant",
    "user",
    "user_tenant",
    "role",
    "userrole",
    "department",
    "user_department",
    "department_admin_grant",
    "auditlog",
    "app",
    "app_version",
    "app_instance",
    "app_deployment",
    "resource_tier",
    "approval_scenario",
    "approval_route_rule",
    "approval_flow_definition",
    "approval_flow_version",
    "approval_node_definition",
    "approval_instance",
    "approval_task",
    "approval_exception",
    "approval_outbox",
    "approval_action_log",
)

_METADATA_MODULES = (
    "bisheng.database.models.tenant",
    "bisheng.database.models.audit_log",
    "bisheng.database.models.department",
    "bisheng.database.models.department_admin_grant",
    "bisheng.database.models.resource_tier",
    "bisheng.database.models.app",
    "bisheng.database.models.app_version",
    "bisheng.database.models.app_instance",
    "bisheng.user.domain.models.user",
    "bisheng.user.domain.models.user_role",
    "bisheng.database.models.role",
    "bisheng.app_publish.domain.models",
    "bisheng.approval.domain.models.approval_scenario",
    "bisheng.approval.domain.models.approval_instance",
)

#: Every method ``orchestrator_client`` exposes (F054 design §4.2 ①). The
#: ``fake_orchestrator`` fixture stubs exactly this set — see the module
#: docstring for why "exactly" matters.
ORCHESTRATOR_METHODS = (
    "build",
    "build_status",
    "deploy",
    "stop",
    "destroy",
    "probe",
    "admission",
    "status",
    "logs",
    "runtime_status",
)


def _optional_module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


@contextmanager
def _sqlite_ddl_quirks(tables):
    """Make MySQL/DM8-shaped tables emittable on SQLite, for DDL only.

    ``userrole`` has a composite primary key (``user_id`` + ``role_id`` + a
    surrogate ``id``) with ``autoincrement`` on the surrogate. SQLite rejects
    that outright ("SQLite does not support autoincrement for composite primary
    keys"), which would otherwise take down every fixture that seeds a role.
    The flag is cleared for the ``create_all`` call and restored immediately —
    it is consulted only when DDL is compiled, so nothing else in the process
    sees the change, and the production DDL is untouched (Alembic owns it).

    Rows written through this engine therefore need an explicit ``id``; the
    fixtures that seed ``userrole`` pass one.
    """
    touched = []
    for table in tables:
        for column in table.columns:
            if column.primary_key and column.autoincrement is True and len(table.primary_key.columns) > 1:
                touched.append(column)
                column.autoincrement = False
    try:
        yield
    finally:
        for column in touched:
            column.autoincrement = True


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    """Strip proxy variables — see the module docstring."""
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Database (aiosqlite) + session binding
# ---------------------------------------------------------------------------


@pytest.fixture()
async def publish_engine():
    """Fresh in-memory aiosqlite engine carrying the F055-relevant tables."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel

    for module in _METADATA_MODULES:
        importlib.import_module(module)

    tables = [SQLModel.metadata.tables[name] for name in _TABLES if name in SQLModel.metadata.tables]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with _sqlite_ddl_quirks(tables):
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture()
async def publish_db(publish_engine, monkeypatch):
    """Bind ``get_async_db_session`` in every app_publish-facing module to ``publish_engine``.

    Returns the session factory (an ``asynccontextmanager``) so a test can seed
    or inspect rows directly: ``async with publish_db() as session: ...``.
    """
    from sqlmodel.ext.asyncio.session import AsyncSession

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=publish_engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for target in _SESSION_PATCH_TARGETS:
        module = _optional_module(target)
        if module is not None and hasattr(module, "get_async_db_session"):
            monkeypatch.setattr(module, "get_async_db_session", _session)
    return _session


# ---------------------------------------------------------------------------
# Identities — the approver-resolution matrix (AC-15 / AC-17 / AC-21)
# ---------------------------------------------------------------------------


def _payload(user_id: int, user_name: str, tenant_id: int, *, is_global_super: bool = False):
    from bisheng.common.dependencies.user_deps import UserPayload

    # ``user_role=[]`` skips the UserRoleDao lookup in LoginUser.__init__.
    return UserPayload(
        user_id=user_id,
        user_name=user_name,
        user_role=[],
        tenant_id=tenant_id,
        is_global_super=is_global_super,
    )


async def _seed_user(publish_db, user_id: int, user_name: str, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import USER_TYPE_HUMAN, User

    async with publish_db() as session:
        user = User(
            user_id=user_id,
            user_name=user_name,
            password=SEED_PASSWORD_PLACEHOLDER,
            user_type=USER_TYPE_HUMAN,
            delete=0,
        )
        session.add(user)
        await session.flush()
        session.add(UserTenant(user_id=user.user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.commit()
        return user


def _identity(user, tenant_id: int = ROOT_TENANT_ID, **extra):
    return SimpleNamespace(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id,
        payload=_payload(user.user_id, user.user_name, tenant_id, is_global_super=extra.pop("is_global_super", False)),
        **extra,
    )


@pytest.fixture()
async def owner_user(publish_db):
    """The natural person who owns published apps — the approval applicant (INV-29)."""
    user = await _seed_user(publish_db, OWNER_USER_ID, "f055-owner")
    return _identity(user)


@pytest.fixture()
async def dept_admin_user(publish_db, owner_user):
    """A department administrator of the owner's primary department.

    Seeds the department, makes ``owner_user`` its primary member and grants
    this user ``department_admin_grant`` — i.e. exactly what
    ``approver_resolver``'s ``department_admin`` source reads. The department
    name is Chinese on purpose: it travels through notification copy and
    ``detail_snapshot``.
    """
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.database.models.department_admin_grant import (
        DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
        DepartmentAdminGrant,
    )

    user = await _seed_user(publish_db, DEPT_ADMIN_USER_ID, "f055-dept-admin")
    async with publish_db() as session:
        department = Department(dept_id=DEPT_BUSINESS_KEY, name=DEPT_NAME, parent_id=None, tenant_id=ROOT_TENANT_ID)
        session.add(department)
        await session.flush()
        # Explicit ids: ``user_department.id`` is BIGINT and SQLite only
        # autoincrements a column declared exactly ``INTEGER PRIMARY KEY``.
        session.add(UserDepartment(id=1, user_id=owner_user.user_id, department_id=department.id, is_primary=1))
        session.add(UserDepartment(id=2, user_id=user.user_id, department_id=department.id, is_primary=1))
        # Explicit id for the same reason as ``user_department``: the column is
        # BIGINT and SQLite only autoincrements a plain ``INTEGER PRIMARY KEY``.
        session.add(
            DepartmentAdminGrant(
                id=1,
                user_id=user.user_id,
                department_id=department.id,
                grant_source=DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
            )
        )
        await session.commit()
        department_id = department.id
    return _identity(user, department_id=department_id, department_name=DEPT_NAME)


@pytest.fixture()
async def tenant_admin_user(publish_db, monkeypatch):
    """A **real** tenant administrator of a child tenant — never a super admin.

    Tenant-admin membership lives in OpenFGA (``user:X admin tenant:Y``), so the
    fixture seeds the child tenant and its user and stubs
    ``TenantAdminService.list_tenant_admins`` instead of standing up a
    permission backend. The Root tenant is left with **no** administrators,
    which is not an omission: ``list_tenant_admins`` short-circuits Root to
    ``[]`` in production too, and that is the whole reason AC-21 needs a
    Root → platform-super-admin fallback.
    """
    from bisheng.database.models.tenant import Tenant
    from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService

    async with publish_db() as session:
        session.add(
            Tenant(
                id=SUB_TENANT_ID,
                tenant_code="f055-sub",
                tenant_name="F055 sub tenant",
                status="active",
                parent_tenant_id=ROOT_TENANT_ID,
            )
        )
        await session.commit()
    user = await _seed_user(publish_db, TENANT_ADMIN_USER_ID, "f055-tenant-admin", tenant_id=SUB_TENANT_ID)

    async def _list_tenant_admins(cls, tenant_id: int) -> list[int]:
        return [TENANT_ADMIN_USER_ID] if int(tenant_id) == SUB_TENANT_ID else []

    monkeypatch.setattr(TenantAdminService, "list_tenant_admins", classmethod(_list_tenant_admins))
    return _identity(user, SUB_TENANT_ID)


@pytest.fixture()
async def super_admin_user(publish_db):
    """A platform super admin (``AdminRole`` = role_id 1) — the Root-tenant fallback approver.

    ``is_global_super=True`` on the payload matters: the permission runtime
    short-circuits this identity to ALLOW before ReBAC is consulted, so any
    "owner only" rule must be a business pre-check rather than a permission
    check (C4) — this fixture is what proves the difference.
    """
    from bisheng.database.constants import AdminRole
    from bisheng.user.domain.models.user_role import UserRole

    user = await _seed_user(publish_db, SUPER_ADMIN_USER_ID, "f055-super-admin")
    async with publish_db() as session:
        # Explicit ``id``: ``userrole`` has a composite primary key, so the
        # surrogate key cannot autoincrement on SQLite (see _sqlite_ddl_quirks).
        session.add(UserRole(id=1, user_id=user.user_id, role_id=AdminRole, tenant_id=ROOT_TENANT_ID))
        await session.commit()
    return _identity(user, is_global_super=True)


@pytest.fixture()
def service_account_principal(owner_user):
    """``service_account_principal(scopes=[...], resource_owner_user_id=...)`` → ``OpenApiPrincipal``.

    The shape ``open_api_subject("app:manage")`` puts into the request context
    (F049 T005). ``resource_owner_user_id`` defaults to ``owner_user`` — the
    natural person the CLI's key creates resources on behalf of — because
    "whose apps may this key publish" is the whole of AC-04's ownership rule and
    a principal without it silently makes every app look unowned.
    """
    from bisheng.open_api.domain.context import PRINCIPAL_KIND_SERVICE_ACCOUNT, OpenApiPrincipal

    def _make(
        *,
        scopes: list[str] | tuple[str, ...] = ("app:manage",),
        resource_owner_user_id: int | None = None,
        subject_user_id: int = SERVICE_ACCOUNT_USER_ID,
        credential_id: int | None = 1,
        subject_kind: str = PRINCIPAL_KIND_SERVICE_ACCOUNT,
    ) -> OpenApiPrincipal:
        return OpenApiPrincipal(
            credential_id=credential_id,
            subject_kind=subject_kind,
            subject_user_id=subject_user_id,
            resource_owner_user_id=(owner_user.user_id if resource_owner_user_id is None else resource_owner_user_id),
            scopes=tuple(scopes),
        )

    return _make


# ---------------------------------------------------------------------------
# Domain factories
# ---------------------------------------------------------------------------


@pytest.fixture()
async def app_factory(publish_db, owner_user):
    """``await app_factory(state=..., owner_user_id=..., ...)`` → ``(App, AppVersion)``.

    Straight through the DAOs rather than a service: the pipeline tests need an
    app in a given state without asserting anything about how it got there, and
    ``AppStateService`` cannot manufacture an ``online`` app without a live
    orchestrator. Same shape as ``test/app_runtime/conftest.py`` so a test moved
    between the two packages keeps working.
    """
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.database.models.app import App, AppDao
    from bisheng.database.models.app_version import VERSION_KIND_INITIAL, AppVersion, AppVersionDao

    counter = {"n": 0}

    async def _create(
        *,
        state: str = "draft",
        owner_user_id: int | None = None,
        tenant_id: int = ROOT_TENANT_ID,
        slug: str | None = None,
        name: str | None = None,
        runtime: str = "python3.11",
        tier_id: str = "light",
        with_version: bool = True,
        terminal_state: str | None = None,
    ):
        counter["n"] += 1
        suffix = counter["n"]
        set_current_tenant_id(tenant_id)
        async with publish_db() as session:
            app_row = App(
                slug=slug or f"f055-app-{suffix}",
                name=name or f"F055 app {suffix}",
                description="seeded by app_factory",
                owner_user_id=owner_user_id if owner_user_id is not None else owner_user.user_id,
                tenant_id=tenant_id,
                state=state,
            )
            await AppDao.acreate(session, app_row)
            version_row = None
            if with_version:
                version_row = AppVersion(
                    app_id=app_row.id,
                    version_no=1,
                    kind=VERSION_KIND_INITIAL,
                    terminal_state=terminal_state,
                    code_object_key=f"apps/{app_row.id}/versions/v1/code.tar.gz",
                    manifest={"name": app_row.name, "runtime": runtime, "port": 8080},
                    capabilities={},
                    injections={},
                    tier_id=tier_id,
                    runtime=runtime,
                    submitted_at=datetime.now(),
                )
                await AppVersionDao.ainsert(session, version_row)
                app_row.current_version_id = version_row.id
                session.add(app_row)
            await session.commit()
        return app_row, version_row

    return _create


@pytest.fixture()
async def deployment_factory(publish_db, owner_user):
    """``await deployment_factory(app_id=..., stage=..., status=...)`` → ``AppDeployment``.

    Goes through ``AppDeploymentDao`` so the row is shaped exactly as the
    pipeline would leave it at that stage.
    """
    from bisheng.app_publish.domain.models.app_deployment import (
        STAGE_RECEIVED,
        STATUS_RUNNING,
        AppDeployment,
        AppDeploymentDao,
    )
    from bisheng.core.context.tenant import set_current_tenant_id

    async def _create(
        *,
        app_id: str | None = None,
        tenant_id: int = ROOT_TENANT_ID,
        owner_user_id: int | None = None,
        submitted_by_user_id: int = SERVICE_ACCOUNT_USER_ID,
        stage: str = STAGE_RECEIVED,
        status: str = STATUS_RUNNING,
        version_id: str | None = None,
        approval_instance_id: int | None = None,
        code_object_key: str | None = None,
        manifest: dict | None = None,
        tier_code: str | None = None,
        failure: dict | None = None,
        scan_result: dict | None = None,
    ) -> AppDeployment:
        set_current_tenant_id(tenant_id)
        async with publish_db() as session:
            row = AppDeployment(
                tenant_id=tenant_id,
                app_id=app_id,
                owner_user_id=owner_user_id if owner_user_id is not None else owner_user.user_id,
                submitted_by_user_id=submitted_by_user_id,
                stage=stage,
                status=status,
                version_id=version_id,
                approval_instance_id=approval_instance_id,
                code_object_key=code_object_key,
                manifest=manifest,
                tier_code=tier_code,
                failure=failure,
                scan_result=scan_result,
            )
            await AppDeploymentDao.acreate(session, row)
            await session.commit()
        return row

    return _create


@pytest.fixture()
async def tier_seed(publish_db):
    """Run the real ``seed_resource_tiers()`` once and return the seeded rows.

    Shared by the tier suite and the manifest suite on purpose: "what ``light``
    resolves to" must have exactly one definition in the tests, the same way it
    has exactly one in the code (T015).
    """
    from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService
    from bisheng.database.models.resource_tier import ResourceTierDao

    await ResourceTierService.seed_resource_tiers()
    async with publish_db() as session:
        return await ResourceTierDao.alist(session)


# ---------------------------------------------------------------------------
# Package tarballs
# ---------------------------------------------------------------------------


def _tar_bytes_from_members(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    """Write ``TarInfo`` objects straight into a gzip stream.

    Going through ``TarInfo`` rather than the filesystem is what lets this
    produce symlinks, hardlinks, character devices and FIFOs **without root and
    without a real device node** — the four entry kinds a tar has and a zip does
    not (design pit 15).
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for info, payload in members:
            tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return gzip.compress(raw.getvalue())


def _file_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mode = 0o644
    return info, payload


def _special_member(name: str, kind: bytes, *, linkname: str = "") -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name=name)
    info.type = kind
    info.linkname = linkname
    info.size = 0
    if kind in (tarfile.CHRTYPE, tarfile.BLKTYPE):
        info.devmajor, info.devminor = 1, 3
    return info, None


@pytest.fixture()
def tarball_factory(tmp_path):
    """``tarball_factory(**kwargs)`` → ``Path`` of a ``.tar.gz`` on disk.

    Keyword arguments compose, so one call can build "a valid package that also
    contains a symlink". Defaults pack ``fixtures/minimal_app/``.

    * ``include_manifest=False`` — drop ``bisheng-app.yaml`` (16203)
    * ``manifest`` — replace the manifest body (str or bytes)
    * ``extra_files={name: content}`` — arbitrary additional members
    * ``symlink`` / ``hardlink`` / ``device`` / ``fifo`` — the four tar-only
      entry kinds (16202)
    * ``absolute_path`` / ``traversal`` — the two entry kinds a zip also has
    * ``entries=N`` — pad to N members (the entry-count gate)
    * ``payload_mb=N`` — add one compressible N MB member (the tar-bomb gate;
      gzip keeps the *upload* small, which is precisely what makes the unpacked
      gate a separate gate)
    """

    def _make(
        *,
        include_manifest: bool = True,
        manifest: str | bytes | None = None,
        extra_files: dict[str, str | bytes] | None = None,
        symlink: bool = False,
        hardlink: bool = False,
        device: bool = False,
        fifo: bool = False,
        absolute_path: bool = False,
        traversal: bool = False,
        entries: int = 0,
        payload_mb: int = 0,
        name: str = "package.tar.gz",
    ) -> Path:
        members: list[tuple[tarfile.TarInfo, bytes | None]] = []
        for source in sorted(MINIMAL_APP_DIR.iterdir()):
            if source.name == "bisheng-app.yaml" and not include_manifest:
                continue
            payload = source.read_bytes()
            if source.name == "bisheng-app.yaml" and manifest is not None:
                payload = manifest.encode("utf-8") if isinstance(manifest, str) else manifest
            members.append(_file_member(source.name, payload))
        if include_manifest and manifest is not None and not any(i.name == "bisheng-app.yaml" for i, _ in members):
            body = manifest.encode("utf-8") if isinstance(manifest, str) else manifest
            members.append(_file_member("bisheng-app.yaml", body))

        for member_name, content in (extra_files or {}).items():
            body = content.encode("utf-8") if isinstance(content, str) else content
            members.append(_file_member(member_name, body))

        if symlink:
            members.append(_special_member("link-to-etc-passwd", tarfile.SYMTYPE, linkname="/etc/passwd"))
        if hardlink:
            members.append(_special_member("hardlink-to-main", tarfile.LNKTYPE, linkname="main.py"))
        if device:
            members.append(_special_member("dev-null", tarfile.CHRTYPE))
        if fifo:
            members.append(_special_member("a-fifo", tarfile.FIFOTYPE))
        if absolute_path:
            members.append(_file_member("/etc/cron.d/pwn", b"* * * * * root id\n"))
        if traversal:
            members.append(_file_member("../../escaped.txt", b"escaped\n"))

        for index in range(max(0, entries - len(members))):
            members.append(_file_member(f"pad/{index}.txt", b"x"))

        if payload_mb:
            # Zeros: gzip squeezes them to almost nothing, so the upload passes
            # the size gate and only the unpacked gate can catch it.
            members.append(_file_member("big.bin", b"\0" * (payload_mb * 1024 * 1024)))

        target = tmp_path / name
        target.write_bytes(_tar_bytes_from_members(members))
        return target

    return _make


# ---------------------------------------------------------------------------
# Object storage stub
# ---------------------------------------------------------------------------


class _FakeMinioStorage:
    """Filesystem-backed stand-in for ``MinioStorage``, with call recording.

    Only the surface the publish pipeline uses. Two behaviours are load-bearing
    rather than convenience:

    * ``put_object`` records whether it was handed a ``Path`` or bytes, so
      "the upload is never read into memory" is an observable fact rather than
      a code-review promise.
    * ``create_bucket_sync`` counts calls, so "the bucket is ensured
      idempotently on first use" (design pit 14) can be asserted without
      touching ``_init_bucket_conf`` — which must keep creating only the public
      and tmp buckets.
    """

    def __init__(self, root: Path, default_bucket: str = "bisheng"):
        self._root = root
        self.bucket = default_bucket
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.created_buckets: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _path(self, bucket_name: str | None, object_name: str) -> Path:
        return self._root / (bucket_name or self.bucket) / object_name

    def _bucket_dir(self, bucket_name: str | None) -> Path:
        return self._root / (bucket_name or self.bucket)

    # -- buckets ---------------------------------------------------------
    def create_bucket_sync(self, bucket_name: str) -> None:
        self.calls.append(("create_bucket_sync", {"bucket_name": bucket_name}))
        self.created_buckets.append(bucket_name)
        self._bucket_dir(bucket_name).mkdir(parents=True, exist_ok=True)

    async def create_bucket(self, bucket_name: str) -> None:
        self.create_bucket_sync(bucket_name)

    def check_bucket_exists_sync(self, bucket_name: str) -> bool:
        self.calls.append(("check_bucket_exists_sync", {"bucket_name": bucket_name}))
        return self._bucket_dir(bucket_name).is_dir()

    async def check_bucket_exists(self, bucket_name: str) -> bool:
        return self.check_bucket_exists_sync(bucket_name)

    # -- objects ---------------------------------------------------------
    def put_object_sync(self, *, bucket_name: str | None = None, object_name: str, file: Any, **kwargs: Any) -> None:
        self.calls.append(
            (
                "put_object",
                {"bucket_name": bucket_name, "object_name": object_name, "from_path": isinstance(file, (str, Path))},
            )
        )
        target = self._path(bucket_name, object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(file, (str, Path)):
            target.write_bytes(Path(file).read_bytes())
        elif isinstance(file, bytes):
            target.write_bytes(file)
        else:
            file.seek(0)
            target.write_bytes(file.read())

    async def put_object(self, *, bucket_name: str | None = None, object_name: str, file: Any, **kwargs: Any) -> None:
        self.put_object_sync(bucket_name=bucket_name, object_name=object_name, file=file, **kwargs)

    def get_share_link_sync(self, object_name, bucket=None, clear_host: bool = True, expire_days: int = 7) -> str:
        """Presigned download URL. The build intent carries one (``code_url``), so the
        orchestrator can fetch the snapshot without a MinIO credential of its own."""
        self.calls.append(
            ("get_share_link", {"bucket": bucket, "object_name": object_name, "expire_days": expire_days})
        )
        return f"http://minio.test/{bucket or self.bucket}/{object_name}?X-Amz-Expires={expire_days * 86400}"

    async def get_share_link(self, object_name, bucket=None, clear_host: bool = True, expire_days: int = 7) -> str:
        return self.get_share_link_sync(object_name, bucket=bucket, clear_host=clear_host, expire_days=expire_days)

    def get_object_sync(self, bucket_name: str | None = None, object_name: str | None = None) -> bytes | None:
        self.calls.append(("get_object", {"bucket_name": bucket_name, "object_name": object_name}))
        target = self._path(bucket_name, object_name or "")
        return target.read_bytes() if target.is_file() else None

    async def get_object(self, bucket_name: str | None = None, object_name: str | None = None) -> bytes | None:
        return self.get_object_sync(bucket_name=bucket_name, object_name=object_name)

    def object_exists_sync(self, bucket_name: str | None = None, object_name: str | None = None) -> bool:
        return self._path(bucket_name, object_name or "").is_file()

    async def object_exists(self, bucket_name: str | None = None, object_name: str | None = None) -> bool:
        return self.object_exists_sync(bucket_name=bucket_name, object_name=object_name)

    def remove_object_sync(self, bucket_name: str | None = None, object_name: str | None = None) -> None:
        self.calls.append(("remove_object", {"bucket_name": bucket_name, "object_name": object_name}))
        target = self._path(bucket_name, object_name or "")
        if target.is_file():
            target.unlink()

    async def remove_object(self, bucket_name: str | None = None, object_name: str | None = None) -> None:
        self.remove_object_sync(bucket_name=bucket_name, object_name=object_name)

    def list_object_names(self, bucket_name: str | None = None, prefix: str = "") -> list[str]:
        """Object keys under ``prefix`` — what an orphan sweep walks."""
        base = self._bucket_dir(bucket_name)
        if not base.is_dir():
            return []
        keys = [str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()]
        return sorted(key for key in keys if key.startswith(prefix))


@pytest.fixture()
def fake_minio(tmp_path, monkeypatch):
    """Back the MinIO facade with a temp directory; return the stub.

    Patches ``get_minio_storage`` / ``get_minio_storage_sync`` at their source
    module **and** in every consumer that imported them by name, so a service
    written either way is covered.
    """
    storage = _FakeMinioStorage(tmp_path / "minio")

    async def _get_async():
        return storage

    def _get_sync():
        return storage

    from bisheng.core.storage.minio import minio_manager

    monkeypatch.setattr(minio_manager, "get_minio_storage", _get_async)
    monkeypatch.setattr(minio_manager, "get_minio_storage_sync", _get_sync)
    for target in _SESSION_PATCH_TARGETS:
        module = _optional_module(target)
        if module is None:
            continue
        if hasattr(module, "get_minio_storage"):
            monkeypatch.setattr(module, "get_minio_storage", _get_async)
        if hasattr(module, "get_minio_storage_sync"):
            monkeypatch.setattr(module, "get_minio_storage_sync", _get_sync)
    return storage


# ---------------------------------------------------------------------------
# Orchestrator stub
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_orchestrator(monkeypatch):
    """Replace **all ten** ``orchestrator_client`` methods with programmable stubs.

    Returns a namespace with ``calls`` (an ordered list of ``(method, kwargs)``)
    and ``responses`` (a per-method dict a test may overwrite before acting —
    assign an ``Exception`` instance to make the call raise). Default responses
    follow the shapes in F054 design §4.2 ①.

    The fixture asserts its stub set equals the facade's public method set, so a
    newly added facade method fails loudly here rather than silently escaping to
    real HTTP against runtime-manager. It binds the **real** facade — an earlier
    revision stood a placeholder module into ``sys.modules`` while F054 was in
    flight, which is exactly the shape that lets a suite go green against an
    implementation that does not exist.
    """
    module = importlib.import_module("bisheng.app_runtime.domain.services.orchestrator_client")
    client = module.orchestrator_client
    public = {
        name
        for name in dir(client)
        if not name.startswith("_")
        and callable(getattr(client, name, None))
        and not isinstance(getattr(client, name), type)
    }
    unstubbed = public - set(ORCHESTRATOR_METHODS)
    assert not unstubbed, (
        f"orchestrator_client gained method(s) {sorted(unstubbed)} that fake_orchestrator does not stub; "
        "an unstubbed method falls through to real HTTP against runtime-manager"
    )

    responses: dict[str, Any] = {
        "build": {"build_id": "bld-1", "status": "building"},
        "build_status": {
            "status": "succeeded",
            "stage": "docker_build",
            "message": "",
            "tail": "",
            "image_ref": "bisheng-app/f055-app-1:1-abcdef12",
        },
        "deploy": {"instance_id": "inst-1", "phase": "starting"},
        "stop": {"phase": "stopped"},
        "destroy": {},
        "probe": {"ready": True, "reason": ""},
        "admission": {
            "admitted": True,
            "reason": "",
            "snapshot": {"mem_available_mb": 8192, "committed_mb": 1024, "total_mb": 32768, "cpu": 8},
        },
        "status": {
            "instance_id": "inst-1",
            "phase": "running",
            "health": "healthy",
            "current_version_id": None,
            "started_at": None,
            "restart_count": 0,
            "last_probe_at": None,
        },
        "logs": {"lines": []},
        "runtime_status": {
            "backend_available": True,
            "supported_runtimes": ["python3.11"],
            "capacity": {"mem_available_mb": 8192, "committed_mb": 1024, "total_mb": 32768, "cpu": 8},
            "preflight": [],
        },
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    def _make(name: str):
        async def _stub(*args: Any, **kwargs: Any):
            calls.append((name, kwargs))
            value = responses[name]
            if isinstance(value, Exception):
                raise value
            return value

        return _stub

    for name in ORCHESTRATOR_METHODS:
        monkeypatch.setattr(client, name, _make(name), raising=False)

    return SimpleNamespace(calls=calls, responses=responses)


#: The F054 domain services F055's pipeline calls, and the methods stubbed on
#: each. Programmable stand-ins for the *real* modules — F055 must never write
#: the ``app`` table itself, so these two calls are the only way a first publish
#: can create an application.
F054_SERVICE_METHODS = {
    "bisheng.app_runtime.domain.services.app_provision_service": ("create_draft",),
    "bisheng.app_runtime.domain.services.app_meta_service": ("update_meta",),
}


@pytest.fixture()
def fake_f054_services(monkeypatch):
    """Programmable stand-ins for ``AppProvisionService.create_draft`` / ``AppMetaService.update_meta``.

    Returns a namespace with ``calls`` and ``responses``, same contract as
    ``fake_orchestrator``. F055 must never write the ``app`` table itself
    (决议-8: F054 owns application state), so these two calls are the *only*
    way a first publish can create an application — which is exactly why they
    are asserted on rather than bypassed.
    """
    calls: list[tuple[str, dict[str, Any]]] = []
    responses: dict[str, Any] = {"create_draft": None, "update_meta": None}

    def _bind(dotted: str, container: str, methods: tuple[str, ...]):
        module = importlib.import_module(dotted)
        target = getattr(module, container)
        for name in methods:

            async def _stub(*_args, __name=name, **kwargs):
                calls.append((__name, kwargs))
                value = responses[__name]
                if isinstance(value, Exception):
                    raise value
                return value

            monkeypatch.setattr(target, name, _stub, raising=False)

    _bind("bisheng.app_runtime.domain.services.app_provision_service", "AppProvisionService", ("create_draft",))
    _bind("bisheng.app_runtime.domain.services.app_meta_service", "AppMetaService", ("update_meta",))
    return SimpleNamespace(calls=calls, responses=responses)


@pytest.fixture()
def fake_publish_approval(monkeypatch):
    """Programmable stand-in for ``publish_approval_service``'s three module-level coroutines.

    The pipeline needs three things from it: the two pre-submission gates
    (in-flight request → 16251, pending-online → 16252) and ``submit`` /
    ``cancel``. Patching them keeps a pipeline test about *ordering* — did the
    gates run before the gate, did the version INSERT follow the request — free
    of the approval engine's own state. Tests that are about the approval side
    use the real module.
    """
    methods = ("assert_submittable", "submit", "cancel")
    module = importlib.import_module("bisheng.app_publish.domain.services.publish_approval_service")

    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateResult

    calls: list[tuple[str, dict[str, Any]]] = []
    responses: dict[str, Any] = {
        "assert_submittable": None,
        "submit": ApprovalGateResult(decision=ApprovalGateDecision.PENDING, instance_id=9001),
        "cancel": None,
    }

    for name in methods:

        async def _stub(*args: Any, __name=name, **kwargs: Any):
            calls.append((__name, {"args": args, **kwargs}))
            value = responses[__name]
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(module, name, _stub, raising=False)
    return SimpleNamespace(calls=calls, responses=responses, module=module)


# ---------------------------------------------------------------------------
# Approval environment + audit capture
# ---------------------------------------------------------------------------


@pytest.fixture()
async def approval_env(publish_db):
    """Seed the preset approval scenarios so ``ApprovalGate`` does not fail closed.

    Without the seed the gate raises ``ApprovalScenarioDisabledError`` on the
    very first ``deploy`` (design K1 ④). That is a real production failure mode,
    so the tests that want it ask for it explicitly rather than getting it by
    accident from a missing fixture — which is why this returns the seed list
    and never skips.
    """
    from bisheng.approval.domain.services.approval_seed_service import (
        DEFAULT_APPROVAL_SCENARIO_SEEDS,
        seed_approval_scenarios_in_session,
    )

    assert any(seed["scenario_code"] == "app_publish_request" for seed in DEFAULT_APPROVAL_SCENARIO_SEEDS), (
        "the app_publish_request scenario is missing from the seed list; every publish test below would "
        "be asserting against a gate that can never open"
    )
    async with publish_db() as session:
        await seed_approval_scenarios_in_session(session, ROOT_TENANT_ID)
        await seed_approval_scenarios_in_session(session, SUB_TENANT_ID)
        await session.commit()
    return DEFAULT_APPROVAL_SCENARIO_SEEDS


@pytest.fixture()
def audit_sink(monkeypatch):
    """Capture ``AuditLogDao.ainsert_v2`` calls instead of writing rows.

    Returns the list of keyword dicts in call order — assert on
    ``[call["action"] for call in audit_sink]`` for the ``app.release.*``
    coverage (AC-01).
    """
    from bisheng.database.models.audit_log import AuditLogDao

    captured: list[dict[str, Any]] = []

    async def _capture(*args: Any, **kwargs: Any):
        captured.append(dict(kwargs))
        return None

    monkeypatch.setattr(AuditLogDao, "ainsert_v2", classmethod(lambda cls, *a, **kw: _capture(*a, **kw)))
    return captured


@pytest.fixture()
def approval_notifications(monkeypatch):
    """Capture every station message the approval side sends.

    Returns the list of keyword dicts passed to
    ``ApprovalNotificationService.notify_users`` / ``notify_admins``, tagged
    with which one was called. Patched rather than allowed through because the
    real path opens a session against the message service and swallows its own
    failures — an assertion on "the approvers were notified" would pass either
    way (design 坑 5 is precisely a notification that silently never happens).
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    sent: list[dict[str, Any]] = []

    async def _notify_users(**kwargs: Any) -> None:
        sent.append({"kind": "users", **kwargs})

    async def _notify_user(**kwargs: Any) -> None:
        sent.append({"kind": "users", "receiver_user_ids": [kwargs.pop("receiver_user_id")], **kwargs})

    async def _notify_admins(**kwargs: Any) -> None:
        sent.append({"kind": "admins", **kwargs})

    monkeypatch.setattr(ApprovalNotificationService, "notify_users", staticmethod(_notify_users))
    monkeypatch.setattr(ApprovalNotificationService, "notify_user", staticmethod(_notify_user))
    monkeypatch.setattr(ApprovalNotificationService, "notify_admins", staticmethod(_notify_admins))
    return sent


@pytest.fixture(autouse=True)
def no_celery_dispatch(monkeypatch):
    """Never hand an outbox row to a broker from a unit test.

    ``ApprovalCenterService._dispatch_outbox`` has **no** try/except (design
    坑 11), so an unreachable broker would surface as a failure inside
    ``decide_task`` rather than as the "approved but never executed" it is in
    production. Autouse because forgetting it turns into a connection timeout
    in whichever test happens to approve something.

    Returns the list of dispatched outbox ids so a test can assert the handover
    happened.
    """
    dispatched: list[int] = []

    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
    from bisheng.approval.domain.services.approval_gate import ApprovalGate

    monkeypatch.setattr(ApprovalCenterService, "_dispatch_outbox", staticmethod(dispatched.append))
    monkeypatch.setattr(ApprovalGate, "_dispatch_outbox_task", staticmethod(dispatched.append))
    return dispatched


@pytest.fixture()
def api_app(monkeypatch):
    """``api_app(principal=..., payload=...)`` → an ``httpx.AsyncClient`` bound to F055's routers.

    Two deliberate choices, both inherited from ``test/app_runtime/conftest.py``:

    * **ASGITransport, not ``TestClient``.** ``TestClient`` drives the app on
      its own event loop while the in-memory aiosqlite engine and every
      ContextVar these tests set live on the test's loop — the first DB call
      would fail with "attached to a different loop".
    * **The routers alone, not ``bisheng.main.create_app``.** The full app
      brings a middleware chain that re-resolves tenants against a database
      these tests replaced; a failure here should point at F055.

    ``principal`` replaces the ``app:manage`` credential dependency and seeds
    the open-API principal ContextVar, which is what the ownership rule reads.
    Passing ``None`` leaves the real dependency in place, which is how the
    "a session cookie cannot call /api/v2" and "missing scope" cases are
    exercised.
    """
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode

    def _handle(_request, exc: BaseErrorCode) -> JSONResponse:
        # Mirrors bisheng.main.handle_http_exception: business errors ride in a
        # 200 envelope, because the platform SPA turns a real 403/404 on a GET
        # into a full-page navigation to /403 (design 坑 22).
        return JSONResponse(status_code=200, content=exc.to_dict())

    def _build(principal=None, payload=None, app_runtime_enabled: bool = True):
        from bisheng.app_publish.api.endpoints import deploy as deploy_endpoints
        from bisheng.app_publish.api.router import v1_router, v2_router
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import set_current_tenant_id
        from bisheng.open_api.domain.context import set_current_open_api_principal

        monkeypatch.setattr(settings.app_runtime, "enabled", app_runtime_enabled)

        app = FastAPI(exception_handlers={BaseErrorCode: _handle})
        app.include_router(v1_router, prefix="/api/v1")
        app.include_router(v2_router, prefix="/api/v2")
        if principal is not None:
            set_current_open_api_principal(principal)
            # The real credential dependency seeds this too. Without it the
            # receive leg writes ``app_deployment.tenant_id = NULL`` and fails
            # on the NOT NULL constraint — which is the same guard that stops a
            # child tenant's row landing in Root.
            set_current_tenant_id(ROOT_TENANT_ID)
            resolved = _payload(principal.subject_user_id, "service-account", ROOT_TENANT_ID)
            app.dependency_overrides[deploy_endpoints.app_manage_subject] = lambda: resolved
        if payload is not None:
            app.dependency_overrides[UserPayload.get_login_user] = lambda: payload
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    return _build


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_runtime_settings(monkeypatch):
    """``app_runtime_settings(max_package_mb=1, ...)`` → patch ``settings.app_runtime`` fields.

    The package gates read their thresholds from deployment configuration
    (T005), so a size-gate test sets a 1 MB ceiling rather than building a
    50 MB tarball.
    """
    from bisheng.common.services.config_service import settings

    def _apply(**overrides: Any):
        conf = settings.app_runtime
        for key, value in overrides.items():
            assert hasattr(conf, key), f"settings.app_runtime has no field {key!r}"
            monkeypatch.setattr(conf, key, value)
        return conf

    return _apply


# ---------------------------------------------------------------------------
# Sanity: the environment this package assumes
# ---------------------------------------------------------------------------


def pytest_report_header(config) -> str:  # pragma: no cover - diagnostic only
    proxies = [key for key in _PROXY_KEYS if os.environ.get(key)]
    return f"app_publish: proxy env stripped per-test ({', '.join(proxies) or 'none set'})"
