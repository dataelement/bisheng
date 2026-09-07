"""Fresh-install bootstrap for the F048 permission Catalog.

Two deployment paths create the F048 permission tables, and they need different
initialization:

* Upgrade from a pre-F048 release: the environment already carries legacy
  permission data (roles, resource grants, an older OpenFGA model). Its initial
  CURRENT ``permission_catalog_release`` is produced by the forward-only data
  migration (``scripts/migrate_f048_permission_data.py`` ->
  ``F048MigrationCoordinator``). The OpenFGA manager latches
  ``migration_required`` until an operator runs it, so this module never touches
  such an environment.

* Fresh deployment: a brand-new install has no legacy data. The OpenFGA manager
  bootstraps the F048 model directly (``migration_required`` is False), but
  nothing ever runs the data migration, so no CURRENT release is created and the
  permission runtime fails to start with "Permission Catalog must have exactly
  one CURRENT release".

This module closes that gap. It seeds the initial CURRENT release exactly once,
idempotently, reusing the same canonical action/model derivation the migration
writer uses so the fresh-install Catalog is identical to a migrated one minus
legacy grants. It is a no-op once ``f048-initial`` exists (already seeded, or
produced by the upgrade migration).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.authorization_model_f048 import (
    MODEL_VERSION,
    get_authorization_model_f048,
    required_relations_checksum,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    AuthorizationModelReleaseStatus,
    CatalogReleaseStatus,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionModel,
    PermissionModelAction,
)
from bisheng.permission.domain.services.model_policy import (
    PermissionModelRelease,
    derive_permission_models,
)
from bisheng.permission.migration.f048_coordinator import (
    INITIAL_CATALOG_RELEASE_KEY,
)
from bisheng.permission.migration.f048_model_mapper import (
    build_initial_action_release,
)

logger = logging.getLogger(__name__)

# Mirrors OPENFGA_RELEASE_VERSION in f048_runtime_storage. Kept local so the
# hot startup path does not import the whole migration writer stack; the value
# is an audit-only column and is not validated by runtime readiness.
_OPENFGA_RELEASE_VERSION = "1.15.1"

# A stable, unique idempotency key so a concurrent second starter collides on
# the unique constraint instead of inserting a duplicate release.
_BOOTSTRAP_IDEMPOTENCY_KEY = "f048-initial-bootstrap"

# OpenFGA caps a single Write at 100 tuple operations; stay under it.
_FGA_WRITE_BATCH = 90


def _checksum(value: object) -> str:
    """Match the canonical checksum used by the migration writer."""

    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _catalog_tuples(
    release_key: str,
    model_release: PermissionModelRelease,
) -> list[dict[str, str]]:
    """Build the OpenFGA catalog graph for one release.

    Identical to ``catalog_api._expected_tuples`` /
    ``f048_coordinator._compile_target_tuples`` so a fresh install writes the
    same catalog/model markers a publish or migration would.
    """

    catalog = f"permission_catalog_release:{release_key}"
    tuples: dict[tuple[str, str, str], dict[str, str]] = {}

    def add(user: str, relation: str, object_key: str) -> None:
        tuples[(user, relation, object_key)] = {
            "user": user,
            "relation": relation,
            "object": object_key,
        }

    add("user:*", "active", catalog)
    for model in model_release.models:
        release = f"permission_model_release:{release_key}~{model.model_key}"
        add(release, "release", f"permission_model:{model.model_key}")
        add(catalog, "catalog", release)
        add("user:*", "enabled_marker", release)
        for action_code in model.action_codes:
            add("user:*", f"{action_code}_marker", release)
        if "manage_permission" in model.action_codes and model.derived_level is not None:
            upper = model.derived_level if model.allow_same_level else model.derived_level - 1
            for level in range(1, max(upper, 0) + 1):
                add("user:*", f"grant_level_{level}_marker", release)
    return list(tuples.values())


async def _write_catalog_tuples(
    client: FGAClient,
    release_key: str,
    model_release: PermissionModelRelease,
) -> None:
    tuples = _catalog_tuples(release_key, model_release)
    for index in range(0, len(tuples), _FGA_WRITE_BATCH):
        await client.write_tuples(
            writes=tuples[index : index + _FGA_WRITE_BATCH],
            ignore_duplicate_writes=True,
        )


async def _initial_release_exists() -> bool:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            existing = (
                await session.execute(
                    select(PermissionCatalogRelease.id)
                    .where(PermissionCatalogRelease.release_key == INITIAL_CATALOG_RELEASE_KEY)
                    .limit(1)
                )
            ).scalar_one_or_none()
    return existing is not None


async def _seed_control_plane(
    *,
    store_id: str,
    model_id: str,
    model_checksum: str,
    environment: str,
    catalog_checksum: str,
    relations_checksum: str,
    action_release,
    model_release: PermissionModelRelease,
) -> None:
    now = datetime.now(UTC)
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            async with session.begin():
                # Re-check inside the transaction so the common concurrent case
                # is a clean skip rather than an IntegrityError.
                if (
                    await session.execute(
                        select(PermissionCatalogRelease.id)
                        .where(PermissionCatalogRelease.release_key == INITIAL_CATALOG_RELEASE_KEY)
                        .limit(1)
                    )
                ).scalar_one_or_none() is not None:
                    return

                auth_release = (
                    await session.execute(
                        select(AuthorizationModelRelease).where(
                            AuthorizationModelRelease.environment == environment,
                            AuthorizationModelRelease.store_id == store_id,
                            AuthorizationModelRelease.model_id == model_id,
                        )
                    )
                ).scalars().first()
                if auth_release is None:
                    auth_release = AuthorizationModelRelease(
                        environment=environment,
                        store_id=store_id,
                        model_version=MODEL_VERSION,
                        model_id=model_id,
                        predecessor_model_id=None,
                        model_checksum=model_checksum,
                        required_relations_checksum=relations_checksum,
                        openfga_version=_OPENFGA_RELEASE_VERSION,
                        status=AuthorizationModelReleaseStatus.ACTIVE.value,
                        activated_at=now,
                    )
                    session.add(auth_release)
                    await session.flush()
                elif auth_release.status != AuthorizationModelReleaseStatus.ACTIVE.value:
                    auth_release.status = AuthorizationModelReleaseStatus.ACTIVE.value
                    auth_release.activated_at = now
                if auth_release.id is None:
                    raise RuntimeError("Authorization model release was not flushed")

                release = PermissionCatalogRelease(
                    release_key=INITIAL_CATALOG_RELEASE_KEY,
                    version=1,
                    status=CatalogReleaseStatus.CURRENT.value,
                    write_fenced=False,
                    predecessor_id=None,
                    required_authorization_model_release_id=int(auth_release.id),
                    draft_owner_id=0,
                    idempotency_key=_BOOTSTRAP_IDEMPOTENCY_KEY,
                    checksum=catalog_checksum,
                    commit_checksum=catalog_checksum,
                    published_at=now,
                )
                session.add(release)
                await session.flush()
                if release.id is None:
                    raise RuntimeError("Catalog release was not flushed")

                action_ids: dict[str, int] = {}
                for action in action_release.actions:
                    action_row = PermissionAction(
                        catalog_release_id=release.id,
                        code=action.code,
                        name=action.name,
                        level=action.level,
                        active=action.active,
                        sort_order=action.sort_order,
                    )
                    session.add(action_row)
                    await session.flush()
                    if action_row.id is None:
                        raise RuntimeError("Action row was not flushed")
                    action_ids[action.code] = int(action_row.id)
                    for resource_type in sorted(action.resource_types):
                        session.add(
                            PermissionActionResourceScope(
                                action_id=action_row.id,
                                resource_type=resource_type,
                            )
                        )

                for model in model_release.models:
                    model_row = PermissionModel(
                        catalog_release_id=release.id,
                        model_key=model.model_key,
                        normalized_name=model.name.casefold(),
                        name=model.name,
                        kind=model.kind,
                        config_scope=model.config_scope,
                        derived_level=model.derived_level,
                        active=model.active,
                        allow_same_level=model.allow_same_level,
                        legacy_source_key=None,
                    )
                    session.add(model_row)
                    await session.flush()
                    if model_row.id is None:
                        raise RuntimeError("Model row was not flushed")
                    for action_code in model.action_codes:
                        action_id = action_ids.get(action_code)
                        if action_id is None:
                            raise RuntimeError(f"Model references unknown action: {action_code}")
                        session.add(
                            PermissionModelAction(
                                model_id=model_row.id,
                                action_id=action_id,
                            )
                        )


def normalize_environment(value: object) -> str:
    """Mirror scripts.f048_migration_runtime._environment_name."""

    if isinstance(value, dict):
        value = next(
            (value[key] for key in ("name", "environment", "env", "mode") if value.get(key)),
            "dev",
        )
    return str(value or "dev")[:64]


async def seed_initial_permission_catalog(
    client: FGAClient,
    *,
    store_id: str,
    model_id: str,
    model_checksum: str,
    environment: object,
) -> bool:
    """Seed the initial CURRENT Catalog for a fresh install, idempotently.

    Returns True when this call created the release, False when it was already
    present (already seeded, or produced by the upgrade migration). Never raises
    ``PermissionPublishNotReadyError`` / ``AuthorizationModelMismatchError`` so a
    transient failure does not latch the process migration gate; on any error it
    logs and returns False, leaving the caller's own readiness check to surface
    the still-missing Catalog.
    """

    if not store_id or not model_id or not model_checksum:
        return False

    env = normalize_environment(environment)
    action_release = build_initial_action_release()
    model_release = derive_permission_models(action_release)
    catalog_checksum = _checksum(
        {
            "actions": action_release.checksum,
            "models": model_release.checksum,
        }
    )
    relations_checksum = required_relations_checksum(get_authorization_model_f048())

    try:
        if await _initial_release_exists():
            return False

        # Write the OpenFGA catalog graph before the CURRENT release becomes
        # visible so no process can read a CURRENT Catalog without its
        # authorization tuples. Idempotent via ignore_duplicate_writes.
        await _write_catalog_tuples(client, INITIAL_CATALOG_RELEASE_KEY, model_release)

        await _seed_control_plane(
            store_id=store_id,
            model_id=model_id,
            model_checksum=model_checksum,
            environment=env,
            catalog_checksum=catalog_checksum,
            relations_checksum=relations_checksum,
            action_release=action_release,
            model_release=model_release,
        )
    except IntegrityError:
        # Another starting process seeded concurrently; its rows win.
        logger.info("F048 initial permission Catalog already seeded by a concurrent process")
        return False
    except Exception:
        logger.exception("F048 initial permission Catalog bootstrap failed")
        return False

    logger.info(
        "Seeded initial F048 permission Catalog for fresh install: store=%s model=%s",
        store_id,
        model_id,
    )
    return True
