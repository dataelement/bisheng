"""Making ``app`` effective on an environment that already ran the F048 migration.

Adding ``app`` to the code constants is enough for a **fresh** install and not
nearly enough for an existing one, because two independent gates disagree with
the code the moment it changes:

* the authorization model checksum moves, so every process boots into
  ``migration_required`` and answers 503 for *all* permission checks — not just
  hosted apps (design K9);
* ``permission_action_resource_scope`` is written in exactly two places (first
  migration, catalog draft publish) and **no** ``CatalogChangeType`` can alter
  ``resource_types`` — so no running code path will ever insert the ``app``
  rows, and the SQL-join predicate behind ``is_action_effective`` keeps
  answering "not effective" forever.

Hence a four-step upgrade: publish the model (an HTTP write, outside any SQL
transaction), then re-point the release, retire the old one and backfill the
scope rows — those three atomically. This file pins the awkward parts: that a
dry run really writes nothing, that a re-run does not stack duplicate models in
the store, that a mid-flight failure leaves no half-upgraded control plane, and
that ``rollback`` means "re-point SQL", not "un-publish the model".

Runs anywhere: an aiosqlite database carrying the four F048 control-plane
tables plus a programmable fake OpenFGA client. The steps under test are pure
SQL and one HTTP call, so nothing here is weakened to avoid the middleware.

覆盖 AC: AC-13
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles
from sqlmodel import select

from bisheng.core.openfga.authorization_model_f048 import (
    MODEL_VERSION,
    authorization_model_checksum,
    build_authorization_model_f048,
    canonicalize_authorization_model,
    required_relations_checksum,
)
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
)

ENVIRONMENT = "test"
STORE_ID = "store-f054"
M1_MODEL_ID = "model-m1"
APP_ACTIONS = ("use", "edit", "manage_permission", "delete", "publish", "unpublish")

_CONTROL_PLANE_TABLES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
)


# SQLite only auto-assigns a rowid to a column declared exactly ``INTEGER
# PRIMARY KEY``; the F048 control-plane tables use BIGINT, so inserts without an
# explicit id fail with a NOT NULL violation. Rendering BIGINT as INTEGER for
# the SQLite dialect restores autoincrement and loses nothing — SQLite's INTEGER
# is already 64-bit. DDL for MySQL / DM8 is untouched.
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(type_, compiler, **kw):
    return "INTEGER"


def _upgrade_module():
    """Import the T017 script lazily so this file collects before it exists."""
    try:
        return importlib.import_module("scripts.upgrade_f048_authorization_model")
    except ImportError:  # pragma: no cover - Test-First window
        pytest.skip("upgrade_f048_authorization_model (T017) not implemented yet")


# ---------------------------------------------------------------------------
# Fake OpenFGA control plane
# ---------------------------------------------------------------------------


class _FakeFGAClient:
    """Remembers every published model, exactly like a real store does."""

    def __init__(self, models: list[dict] | None = None) -> None:
        self.store_id = STORE_ID
        self._models: list[dict] = list(models or [])
        self.writes = 0

    async def list_authorization_models(self) -> list[dict]:
        # A real response carries protobuf defaults the canonicalizer strips;
        # keep them so the checksum path is exercised, not bypassed.
        return [dict(model, condition="", module="") for model in self._models]

    async def write_authorization_model(self, model: dict) -> str:
        self.writes += 1
        model_id = f"model-published-{self.writes}"
        self._models.append({"id": model_id, **canonicalize_authorization_model(model)})
        return model_id

    @property
    def published_ids(self) -> list[str]:
        return [model["id"] for model in self._models]


def _m1_model() -> dict:
    """The pre-F054 model: the current builder minus the ``app`` resource type.

    Rebuilt from the live builder rather than pasted, so this fixture does not
    rot when unrelated type definitions change; only ``app`` is removed.
    """
    model = build_authorization_model_f048()
    model["type_definitions"] = [definition for definition in model["type_definitions"] if definition["type"] != "app"]
    return model


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.fixture()
async def control_plane_db():
    """aiosqlite holding the four control-plane tables; yields a session factory."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    importlib.import_module("bisheng.permission.domain.models.catalog")
    importlib.import_module("bisheng.permission.domain.models.migration")

    tables = [SQLModel.metadata.tables[name] for name in _CONTROL_PLANE_TABLES]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    yield _session
    await engine.dispose()


async def _seed_m1_world(session_factory, *, include_app_scopes: bool = False) -> SimpleNamespace:
    """One ACTIVE M1 release, one CURRENT catalog release, the twelve actions.

    ``include_app_scopes=False`` is the real starting state of a 114-style host:
    the actions exist with their pre-F054 resource scopes and nothing mentions
    ``app``.
    """
    from bisheng.permission.domain.models.catalog import (
        PermissionAction,
        PermissionActionResourceScope,
        PermissionCatalogRelease,
    )
    from bisheng.permission.domain.models.migration import AuthorizationModelRelease

    m1 = _m1_model()
    async with session_factory() as session:
        release = AuthorizationModelRelease(
            environment=ENVIRONMENT,
            store_id=STORE_ID,
            model_version="f048-v1",
            model_id=M1_MODEL_ID,
            predecessor_model_id=None,
            model_checksum=authorization_model_checksum(m1),
            required_relations_checksum=required_relations_checksum(m1),
            openfga_version="1.8.0",
            status="ACTIVE",
        )
        session.add(release)
        await session.flush()

        catalog = PermissionCatalogRelease(
            release_key="f048-initial",
            version=1,
            status="CURRENT",
            write_fenced=False,
            required_authorization_model_release_id=release.id,
            draft_owner_id=0,
            idempotency_key="f048-initial",
            checksum="0" * 64,
        )
        session.add(catalog)
        await session.flush()

        for order, code in enumerate(REGISTERED_ACTION_CODES):
            action = PermissionAction(
                catalog_release_id=catalog.id,
                code=code,
                name=code.replace("_", " ").title(),
                level=((order % 4) + 1),
                active=True,
                sort_order=order,
            )
            session.add(action)
            await session.flush()
            scopes = ACTION_RESOURCE_SCOPES[code]
            for resource_type in sorted(scopes):
                if resource_type == "app" and not include_app_scopes:
                    continue
                session.add(PermissionActionResourceScope(action_id=action.id, resource_type=resource_type))
        await session.commit()
        return SimpleNamespace(model_release_id=release.id, catalog_release_id=catalog.id)


async def _scope_rows(session_factory, resource_type: str) -> set[str]:
    from bisheng.permission.domain.models.catalog import (
        PermissionAction,
        PermissionActionResourceScope,
    )

    async with session_factory() as session:
        rows = await session.exec(
            select(PermissionAction.code)
            .join(PermissionActionResourceScope, PermissionActionResourceScope.action_id == PermissionAction.id)
            .where(PermissionActionResourceScope.resource_type == resource_type)
        )
        return set(rows.all())


async def _releases(session_factory) -> list:
    from bisheng.permission.domain.models.migration import AuthorizationModelRelease

    async with session_factory() as session:
        rows = await session.exec(select(AuthorizationModelRelease).order_by(AuthorizationModelRelease.id))
        return list(rows.all())


async def _catalog(session_factory):
    from bisheng.permission.domain.models.catalog import PermissionCatalogRelease

    async with session_factory() as session:
        rows = await session.exec(select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT"))
        return rows.first()


def _context(control_plane_db, client, *, heartbeats: tuple = ()):
    module = _upgrade_module()

    async def _heartbeats():
        return heartbeats

    return module.UpgradeContext(
        client=client,
        environment=ENVIRONMENT,
        session_factory=control_plane_db,
        heartbeat_reader=_heartbeats,
    )


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


async def test_dry_run_reports_plan_and_writes_nothing(control_plane_db) -> None:
    """The default is a plan. Neither the store nor a single SQL row moves."""
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    plan = await module.build_plan(ctx)

    assert plan.noop is False
    assert plan.current_model_id == M1_MODEL_ID
    assert plan.target_checksum == authorization_model_checksum(build_authorization_model_f048())
    assert set(plan.missing_scopes) == {(action, "app") for action in APP_ACTIONS}

    assert client.writes == 0
    assert len(await _releases(control_plane_db)) == 1
    assert await _scope_rows(control_plane_db, "app") == set()


async def test_noop_when_checksum_matches(control_plane_db) -> None:
    """Already upgraded → nothing to do, and ``apply`` refuses to redo it."""
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db, include_app_scopes=True)
    target = build_authorization_model_f048()
    async with control_plane_db() as session:
        from bisheng.permission.domain.models.migration import AuthorizationModelRelease

        rows = await session.exec(select(AuthorizationModelRelease))
        row = rows.first()
        row.model_checksum = authorization_model_checksum(target)
        row.required_relations_checksum = required_relations_checksum(target)
        row.model_version = MODEL_VERSION
        session.add(row)
        await session.commit()

    client = _FakeFGAClient([{"id": M1_MODEL_ID, **target}])
    ctx = _context(control_plane_db, client)

    plan = await module.build_plan(ctx)
    assert plan.noop is True
    assert plan.missing_scopes == ()

    result = await module.apply_upgrade(ctx)
    assert result["event"] == "noop"
    assert client.writes == 0
    assert len(await _releases(control_plane_db)) == 1


async def test_preflight_blocks_on_live_heartbeats(control_plane_db) -> None:
    """Live processes pin the old model; upgrading under them is a silent outage.

    Every running process fails closed within ~15 s of the SQL pin moving, so
    the script refuses unless the operator says explicitly that it is fine.
    """
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client, heartbeats=(SimpleNamespace(process="api-1"),))

    with pytest.raises(module.UpgradeBlockedError):
        await module.apply_upgrade(ctx)

    assert client.writes == 0
    assert await _scope_rows(control_plane_db, "app") == set()

    # ...and the escape hatch is explicit, not a retry.
    result = await module.apply_upgrade(ctx, allow_live=True)
    assert result["event"] == "applied"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


async def test_apply_publishes_model_idempotently(control_plane_db) -> None:
    """Re-running does not stack a second identical model in the store.

    The lookup is by **canonical checksum**, never "take the newest": that is
    the difference between this script and ``force_write_model``, which grows
    the store by one duplicate model per restart (design pit 3).
    """
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    first = await module.apply_upgrade(ctx)
    assert first["event"] == "applied"
    assert client.writes == 1
    published = client.published_ids

    second = await module.apply_upgrade(ctx)
    assert second["event"] == "noop"
    assert client.writes == 1
    assert client.published_ids == published


async def test_apply_reuses_a_model_already_in_the_store(control_plane_db) -> None:
    """An M2 published by an earlier aborted run is adopted, not duplicated."""
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    target = build_authorization_model_f048()
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}, {"id": "model-orphan-m2", **target}])
    ctx = _context(control_plane_db, client)

    result = await module.apply_upgrade(ctx)

    assert client.writes == 0
    assert result["model_id"] == "model-orphan-m2"


async def test_apply_writes_release_rows_in_one_sql_txn(control_plane_db) -> None:
    """All four SQL effects land together: new ACTIVE row, M1 retired, pointer moved, scopes filled."""
    module = _upgrade_module()
    seeded = await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    await module.apply_upgrade(ctx)

    releases = await _releases(control_plane_db)
    assert len(releases) == 2
    old = next(row for row in releases if row.model_id == M1_MODEL_ID)
    new = next(row for row in releases if row.model_id != M1_MODEL_ID)
    assert old.status == "RETIRED" and old.retired_at is not None
    assert new.status == "ACTIVE"
    assert new.model_version == MODEL_VERSION
    assert new.predecessor_model_id == M1_MODEL_ID
    target = build_authorization_model_f048()
    assert new.model_checksum == authorization_model_checksum(target)
    assert new.required_relations_checksum == required_relations_checksum(target)

    catalog = await _catalog(control_plane_db)
    assert catalog.id == seeded.catalog_release_id
    assert catalog.required_authorization_model_release_id == new.id

    assert await _scope_rows(control_plane_db, "app") == set(APP_ACTIONS)


async def test_a_failure_in_the_last_step_rolls_back_the_first_three(control_plane_db, monkeypatch) -> None:
    """A half-upgraded control plane is the one outcome nothing can recover from.

    If the pointer moved but the scope rows are missing, every process reloads
    a Catalog in which no action is effective for ``app`` — and the pointer
    change is invisible in any log. Steps 2-4 therefore share one transaction.
    """
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    async def _boom(*args, **kwargs):
        raise RuntimeError("scope insert exploded")

    monkeypatch.setattr(module, "_insert_missing_scopes", _boom)

    with pytest.raises(RuntimeError, match="scope insert exploded"):
        await module.apply_upgrade(ctx)

    releases = await _releases(control_plane_db)
    assert len(releases) == 1, "the new release row must not survive a failed transaction"
    assert releases[0].status == "ACTIVE", "M1 must not be left retired"
    catalog = await _catalog(control_plane_db)
    assert catalog.required_authorization_model_release_id == releases[0].id
    assert await _scope_rows(control_plane_db, "app") == set()


# ---------------------------------------------------------------------------
# verify / rollback
# ---------------------------------------------------------------------------


async def test_verify_asserts_read_side(control_plane_db) -> None:
    """``verify`` re-derives the runtime read predicate rather than trusting ``apply``."""
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    with pytest.raises(module.UpgradeBlockedError):
        await module.verify_upgrade(ctx)

    await module.apply_upgrade(ctx)
    report = await module.verify_upgrade(ctx)

    assert report["event"] == "verified"
    assert report["effective_actions"] == sorted(APP_ACTIONS)


async def test_step1_not_rollbackable_documented(control_plane_db) -> None:
    """``rollback`` re-points SQL. The published model stays in the store, harmlessly.

    An authorization model cannot be deleted from OpenFGA, so "roll back" can
    only mean: make the SQL pin name M1 again and drop the ``app`` scope rows.
    M2 is then an orphan nobody pins — which is exactly why the next ``apply``
    must find it by checksum instead of publishing a third one.
    """
    module = _upgrade_module()
    await _seed_m1_world(control_plane_db)
    client = _FakeFGAClient([{"id": M1_MODEL_ID, **_m1_model()}])
    ctx = _context(control_plane_db, client)

    applied = await module.apply_upgrade(ctx)
    published_after_apply = list(client.published_ids)

    result = await module.rollback_upgrade(ctx)
    assert result["event"] == "rolled_back"

    releases = await _releases(control_plane_db)
    active = [row for row in releases if row.status == "ACTIVE"]
    assert len(active) == 1 and active[0].model_id == M1_MODEL_ID
    catalog = await _catalog(control_plane_db)
    assert catalog.required_authorization_model_release_id == active[0].id
    assert await _scope_rows(control_plane_db, "app") == set()

    # The store is untouched: the M2 model is still there and still findable.
    assert client.published_ids == published_after_apply
    assert applied["model_id"] in client.published_ids

    # Re-applying adopts the orphan rather than publishing a third model.
    again = await module.apply_upgrade(ctx)
    assert client.writes == 1
    assert again["model_id"] == applied["model_id"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_subcommands_and_dry_run_default() -> None:
    """``plan`` is the default posture; ``apply`` must be typed out."""
    module = _upgrade_module()

    assert module.parse_args(["plan"]).command == "plan"
    assert module.parse_args([]).command == "plan"
    for command in ("apply", "verify", "rollback"):
        assert module.parse_args([command]).command == command
    assert module.parse_args(["apply"]).allow_live is False
    assert module.parse_args(["apply", "--allow-live"]).allow_live is True
