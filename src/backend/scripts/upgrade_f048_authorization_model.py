#!/usr/bin/env python3
"""Make a new F048 resource type effective on an environment that already migrated.

Adding a resource type to the code constants is enough for a fresh install and
useless on an existing one. Two gates disagree with the new code the moment it
ships (F054 design D9 / K9):

1. **The authorization-model checksum moves.** Every process compares the model
   its code builds against the one the SQL control plane pins. On a mismatch it
   refuses to publish a ready heartbeat and answers 503 for **all** permission
   checks — not just the new type. So the SQL pin has to be moved deliberately.
2. **Nothing writes ``permission_action_resource_scope`` at runtime.** That
   table is populated in exactly two places (the first F048 migration and a
   Catalog draft publish), and no ``CatalogChangeType`` can alter an action's
   ``resource_types``. Without a backfill the join behind ``is_action_effective``
   keeps answering "not effective" forever, and every check on the new type
   raises ``InvalidCatalogActionError``.

Four steps, in this order:

  1. publish (or adopt) the new model in the store — an HTTP write, therefore
     **outside** any SQL transaction;
  2. insert the new ACTIVE ``authorization_model_release`` row and retire the
     old one;
  3. re-point the CURRENT ``permission_catalog_release`` at it;
  4. backfill the missing ``permission_action_resource_scope`` rows and
     recompute the release checksum.

Steps 2-4 share one transaction. A half-applied control plane — pointer moved,
scope rows missing — is the one state nothing can recover from automatically,
because it reads as "successfully upgraded" everywhere.

**Not** ``force_write_model``: that flag writes OpenFGA without writing SQL,
skips the checksum lookup (so every restart adds a duplicate model), and is
disabled in production. Three separate reasons it cannot be the upgrade path.

Run from ``src/backend/`` with the same ``config`` value as the live service:

    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/upgrade_f048_authorization_model.py plan
    PYTHONPATH=./ .venv/bin/python scripts/upgrade_f048_authorization_model.py apply
    PYTHONPATH=./ .venv/bin/python scripts/upgrade_f048_authorization_model.py verify

The default is ``plan`` (dry run). Three operational facts that are not
negotiable:

* **Restart every process afterwards** — API, the three Celery workers, Beat and
  the Linsight worker. Heartbeats are re-checked every 15 s with a 45 s TTL, so
  a process left running does not keep working: it fails closed.
* **Ship the code before adding the config key.** ``load_settings_from_yaml``
  raises ``KeyError`` on an unknown top-level key, so a config.yaml carrying
  ``app_runtime:`` in front of code that knows it stops the backend from
  starting at all.
* **Dry-run first on any environment with data.** ``plan`` prints exactly what
  ``apply`` would touch and writes nothing.

arch-guard note: importing ``bisheng.core.openfga`` here reports a RULE-9
violation. Constitution C4 exempts "explicit operational migration tools" from
that rule but the guard's allowlist only covers ``core/openfga`` and
``permission/``, so every F048 script in this directory reports it — see
``f048_migration_runtime.py`` and ``benchmark_f048_permission_paths.py``.

Rollback (``rollback``) re-points SQL at the previous model and removes the
scope rows. The published model itself stays in the store — OpenFGA models are
immutable and undeletable. It becomes an orphan nobody pins, which is harmless
precisely because step 1 finds models by checksum rather than by recency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import func, update  # noqa: E402
from sqlmodel import select  # noqa: E402

from bisheng.core.openfga.authorization_model_f048 import (  # noqa: E402
    MODEL_VERSION,
    authorization_model_checksum,
    build_authorization_model_f048,
    canonicalize_authorization_model,
    required_relations_checksum,
)
from bisheng.permission.domain.models.catalog import (  # noqa: E402
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
)
from bisheng.permission.domain.models.migration import AuthorizationModelRelease  # noqa: E402
from bisheng.permission.domain.services.catalog_policy import (  # noqa: E402
    ACTION_RESOURCE_SCOPES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.migration.f048_runtime_storage import OPENFGA_RELEASE_VERSION  # noqa: E402

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4

#: The resource type this run makes effective. One value on purpose: a script
#: that upgrades "whatever the constants say" cannot be reviewed against a plan.
TARGET_RESOURCE_TYPE = "app"


class UpgradeBlockedError(RuntimeError):
    """A preflight or post-apply safety invariant was not satisfied."""


@dataclass(frozen=True, slots=True)
class UpgradeContext:
    """Everything the steps touch, injected so they can be driven in a test.

    ``session_factory`` is an async context manager yielding a session, and
    ``heartbeat_reader`` returns the live F048 runtime heartbeats.
    """

    client: Any
    environment: str
    session_factory: Callable[[], Any]
    heartbeat_reader: Callable[[], Awaitable[tuple]]


@dataclass(frozen=True, slots=True)
class UpgradePlan:
    """What ``apply`` would do. Printed verbatim by ``plan``."""

    noop: bool
    reason: str
    target_checksum: str
    current_model_release_id: int | None = None
    current_model_id: str | None = None
    catalog_release_id: int | None = None
    missing_scopes: tuple[tuple[str, str], ...] = ()
    live_heartbeats: int = 0
    existing_target_release_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": "noop" if self.noop else "plan",
            "reason": self.reason,
            "target_checksum": self.target_checksum,
            "current_model_id": self.current_model_id,
            "catalog_release_id": self.catalog_release_id,
            "missing_scopes": [list(pair) for pair in self.missing_scopes],
            "live_heartbeats": self.live_heartbeats,
        }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def _active_release(session, environment: str) -> AuthorizationModelRelease:
    rows = (
        (
            await session.execute(
                select(AuthorizationModelRelease)
                .where(
                    AuthorizationModelRelease.environment == environment,
                    AuthorizationModelRelease.status == "ACTIVE",
                )
                .order_by(AuthorizationModelRelease.id)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) != 1:
        raise UpgradeBlockedError(f"expected exactly one ACTIVE authorization model release, found {len(rows)}")
    return rows[0]


async def _current_catalog(session) -> PermissionCatalogRelease:
    rows = (
        (await session.execute(select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")))
        .scalars()
        .all()
    )
    if len(rows) != 1:
        raise UpgradeBlockedError(f"expected exactly one CURRENT Catalog release, found {len(rows)}")
    if rows[0].write_fenced:
        raise UpgradeBlockedError("CURRENT Catalog release is write fenced; a publish is in flight")
    return rows[0]


async def _catalog_actions(session, catalog_release_id: int) -> list[PermissionAction]:
    return list(
        (
            await session.execute(
                select(PermissionAction)
                .where(PermissionAction.catalog_release_id == catalog_release_id)
                .order_by(PermissionAction.sort_order, PermissionAction.code)
            )
        )
        .scalars()
        .all()
    )


async def _action_scopes(session, action_ids: list[int]) -> dict[int, set[str]]:
    if not action_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(PermissionActionResourceScope).where(PermissionActionResourceScope.action_id.in_(action_ids))
            )
        )
        .scalars()
        .all()
    )
    scopes: dict[int, set[str]] = {action_id: set() for action_id in action_ids}
    for row in rows:
        scopes[int(row.action_id)].add(row.resource_type)
    return scopes


def _target_action_codes() -> tuple[str, ...]:
    """Action codes the target resource type is scoped to, per the code constants."""
    return tuple(sorted(code for code, types in ACTION_RESOURCE_SCOPES.items() if TARGET_RESOURCE_TYPE in types))


async def build_plan(ctx: UpgradeContext) -> UpgradePlan:
    """Compare code against the live control plane. Writes nothing."""
    target_model = build_authorization_model_f048()
    target_checksum = authorization_model_checksum(target_model)
    heartbeats = await ctx.heartbeat_reader()

    async with ctx.session_factory() as session:
        active = await _active_release(session, ctx.environment)
        catalog = await _current_catalog(session)
        actions = await _catalog_actions(session, int(catalog.id))
        scopes = await _action_scopes(session, [int(action.id) for action in actions])

        wanted = set(_target_action_codes())
        missing = tuple(
            sorted(
                (action.code, TARGET_RESOURCE_TYPE)
                for action in actions
                if action.code in wanted and TARGET_RESOURCE_TYPE not in scopes.get(int(action.id), set())
            )
        )
        existing_target = (
            (
                await session.execute(
                    select(AuthorizationModelRelease).where(
                        AuthorizationModelRelease.environment == ctx.environment,
                        AuthorizationModelRelease.store_id == ctx.client.store_id,
                        AuthorizationModelRelease.model_checksum == target_checksum,
                    )
                )
            )
            .scalars()
            .first()
        )

    checksum_matches = active.model_checksum == target_checksum
    if checksum_matches and not missing:
        return UpgradePlan(
            noop=True,
            reason="the ACTIVE release already pins the target model and every scope row exists",
            target_checksum=target_checksum,
            current_model_release_id=int(active.id),
            current_model_id=active.model_id,
            catalog_release_id=int(catalog.id),
            live_heartbeats=len(heartbeats),
        )

    return UpgradePlan(
        noop=False,
        reason=(
            f"publish model {MODEL_VERSION}, re-point the CURRENT Catalog release and "
            f"add {len(missing)} {TARGET_RESOURCE_TYPE} scope row(s)"
        ),
        target_checksum=target_checksum,
        current_model_release_id=int(active.id),
        current_model_id=active.model_id,
        catalog_release_id=int(catalog.id),
        missing_scopes=missing,
        live_heartbeats=len(heartbeats),
        existing_target_release_id=int(existing_target.id) if existing_target is not None else None,
    )


# ---------------------------------------------------------------------------
# Step 1 — the control-plane write (outside SQL)
# ---------------------------------------------------------------------------


async def _find_remote_model(ctx: UpgradeContext, checksum: str) -> str | None:
    """Locate an already-published model by canonical checksum.

    Mirrors ``permission/migration/f048_runtime_storage.py::_find_remote_model``
    — the same normalization, because a model read back from OpenFGA carries
    empty protobuf defaults that would otherwise change the digest. This is
    what makes ``apply`` idempotent and what stops the store from filling up
    with identical models.
    """
    for raw in await ctx.client.list_authorization_models():
        normalized = {
            "schema_version": raw.get("schema_version"),
            "type_definitions": raw.get("type_definitions"),
        }
        if raw.get("conditions"):
            normalized["conditions"] = raw["conditions"]
        if (
            normalized["schema_version"]
            and normalized["type_definitions"]
            and authorization_model_checksum(canonicalize_authorization_model(normalized)) == checksum
        ):
            model_id = raw.get("id") or raw.get("authorization_model_id")
            if model_id:
                return str(model_id)
    return None


async def _publish_model(ctx: UpgradeContext, model: dict, checksum: str) -> tuple[str, bool]:
    """Return ``(model_id, published_now)``; adopts an existing model when possible."""
    model_id = await _find_remote_model(ctx, checksum)
    if model_id is not None:
        return model_id, False
    return await ctx.client.write_authorization_model(model), True


# ---------------------------------------------------------------------------
# Steps 2-4 — one SQL transaction
# ---------------------------------------------------------------------------


async def _insert_missing_scopes(session, *, catalog_release_id: int, missing: tuple[tuple[str, str], ...]) -> None:
    """Backfill ``permission_action_resource_scope`` for the target type."""
    if not missing:
        return
    by_code = {action.code: action for action in await _catalog_actions(session, catalog_release_id)}
    for code, resource_type in missing:
        action = by_code.get(code)
        if action is None:
            raise UpgradeBlockedError(f"CURRENT Catalog has no action row for {code!r}")
        session.add(PermissionActionResourceScope(action_id=int(action.id), resource_type=resource_type))
    await session.flush()


async def _recompute_catalog_checksum(session, catalog: PermissionCatalogRelease) -> str:
    """Re-derive the release checksum from the rows as they now stand.

    ``derive_action_release`` also re-validates them, so a scope row naming a
    type absent from ``MIGRATED_RESOURCE_TYPES`` fails here rather than at the
    next snapshot load in a live process.
    """
    actions = await _catalog_actions(session, int(catalog.id))
    scopes = await _action_scopes(session, [int(action.id) for action in actions])
    release = derive_action_release(
        CatalogAction(
            code=action.code,
            name=action.name,
            level=action.level,
            active=bool(action.active),
            resource_types=frozenset(scopes.get(int(action.id), set())),
            sort_order=int(action.sort_order),
        )
        for action in actions
    )
    catalog.checksum = release.checksum
    session.add(catalog)
    await session.flush()
    return release.checksum


async def apply_upgrade(ctx: UpgradeContext, *, allow_live: bool = False) -> dict[str, Any]:
    """Run the four steps. Idempotent: a second run reports ``noop``."""
    plan = await build_plan(ctx)
    if plan.noop:
        return plan.to_dict()
    if plan.live_heartbeats and not allow_live:
        raise UpgradeBlockedError(
            f"{plan.live_heartbeats} permission runtime heartbeat(s) are live; stop the processes "
            "or pass --allow-live (they fail closed within ~15s of the pin moving)"
        )

    target_model = build_authorization_model_f048()
    model_id, published_now = await _publish_model(ctx, target_model, plan.target_checksum)

    async with ctx.session_factory() as session:
        async with session.begin():
            active = await _active_release(session, ctx.environment)
            catalog = await _current_catalog(session)

            new_release = (
                (
                    await session.execute(
                        select(AuthorizationModelRelease).where(
                            AuthorizationModelRelease.environment == ctx.environment,
                            AuthorizationModelRelease.store_id == ctx.client.store_id,
                            AuthorizationModelRelease.model_id == model_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if new_release is None:
                new_release = AuthorizationModelRelease(
                    environment=ctx.environment,
                    store_id=ctx.client.store_id,
                    model_version=MODEL_VERSION,
                    model_id=model_id,
                    predecessor_model_id=active.model_id,
                    model_checksum=plan.target_checksum,
                    required_relations_checksum=required_relations_checksum(target_model),
                    openfga_version=OPENFGA_RELEASE_VERSION,
                    status="ACTIVE",
                )
                session.add(new_release)
                await session.flush()
            new_release.status = "ACTIVE"
            new_release.activated_at = func.now()
            new_release.retired_at = None
            session.add(new_release)

            if int(active.id) != int(new_release.id):
                await session.execute(
                    update(AuthorizationModelRelease)
                    .where(AuthorizationModelRelease.id == active.id)
                    .values(status="RETIRED", retired_at=func.now(), update_time=func.now())
                )

            catalog.required_authorization_model_release_id = int(new_release.id)
            session.add(catalog)
            await session.flush()

            await _insert_missing_scopes(
                session,
                catalog_release_id=int(catalog.id),
                missing=plan.missing_scopes,
            )
            checksum = await _recompute_catalog_checksum(session, catalog)
            new_release_id = int(new_release.id)

    return {
        "event": "applied",
        "model_id": model_id,
        "published_now": published_now,
        "model_release_id": new_release_id,
        "retired_model_id": plan.current_model_id,
        "catalog_release_id": plan.catalog_release_id,
        "catalog_checksum": checksum,
        "added_scopes": [list(pair) for pair in plan.missing_scopes],
        "restart_required": True,
    }


# ---------------------------------------------------------------------------
# verify / rollback
# ---------------------------------------------------------------------------


async def _is_action_effective(session, catalog_release_id: int, resource_type: str, action: str) -> bool:
    """The read-side predicate, re-derived rather than trusted.

    Same joins and same three conditions as
    ``permission/application/sql_runtime.py::is_action_effective`` — verifying
    with a different query than production uses would prove the wrong thing.
    """
    statement = (
        select(PermissionAction.id)
        .join(PermissionActionResourceScope, PermissionActionResourceScope.action_id == PermissionAction.id)
        .where(
            PermissionAction.catalog_release_id == catalog_release_id,
            PermissionAction.code == action,
            PermissionAction.active == 1,
            PermissionAction.level.is_not(None),
            PermissionActionResourceScope.resource_type == resource_type,
        )
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def verify_upgrade(ctx: UpgradeContext) -> dict[str, Any]:
    """Assert the read side agrees. Raises ``UpgradeBlockedError`` when it does not."""
    target_checksum = authorization_model_checksum(build_authorization_model_f048())
    async with ctx.session_factory() as session:
        active = await _active_release(session, ctx.environment)
        catalog = await _current_catalog(session)
        if active.model_checksum != target_checksum:
            raise UpgradeBlockedError("the ACTIVE authorization model release does not pin the target model")
        if int(catalog.required_authorization_model_release_id) != int(active.id):
            raise UpgradeBlockedError("the CURRENT Catalog release does not point at the ACTIVE model release")

        effective = []
        for action in _target_action_codes():
            if not await _is_action_effective(session, int(catalog.id), TARGET_RESOURCE_TYPE, action):
                raise UpgradeBlockedError(f"action {action!r} is still not effective for {TARGET_RESOURCE_TYPE!r}")
            effective.append(action)

    return {
        "event": "verified",
        "resource_type": TARGET_RESOURCE_TYPE,
        "model_id": active.model_id,
        "catalog_release_id": int(catalog.id),
        "effective_actions": sorted(effective),
    }


async def rollback_upgrade(ctx: UpgradeContext) -> dict[str, Any]:
    """Re-point SQL at the predecessor model and drop the target scope rows.

    Not a true inverse: the published model stays in the store forever
    (OpenFGA models are immutable). It becomes an orphan nobody pins, which is
    why a later ``apply`` adopts it by checksum instead of publishing again.
    """
    async with ctx.session_factory() as session:
        async with session.begin():
            active = await _active_release(session, ctx.environment)
            if not active.predecessor_model_id:
                raise UpgradeBlockedError("the ACTIVE release has no predecessor to roll back to")
            predecessor = (
                (
                    await session.execute(
                        select(AuthorizationModelRelease).where(
                            AuthorizationModelRelease.environment == ctx.environment,
                            AuthorizationModelRelease.store_id == ctx.client.store_id,
                            AuthorizationModelRelease.model_id == active.predecessor_model_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if predecessor is None:
                raise UpgradeBlockedError(
                    f"predecessor model release {active.predecessor_model_id} is not recorded in SQL"
                )

            catalog = await _current_catalog(session)
            actions = await _catalog_actions(session, int(catalog.id))
            action_ids = [int(action.id) for action in actions]
            removed = 0
            if action_ids:
                rows = (
                    (
                        await session.execute(
                            select(PermissionActionResourceScope).where(
                                PermissionActionResourceScope.action_id.in_(action_ids),
                                PermissionActionResourceScope.resource_type == TARGET_RESOURCE_TYPE,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    await session.delete(row)
                    removed += 1
                await session.flush()

            catalog.required_authorization_model_release_id = int(predecessor.id)
            session.add(catalog)
            predecessor.status = "ACTIVE"
            predecessor.activated_at = func.now()
            predecessor.retired_at = None
            session.add(predecessor)
            active.status = "RETIRED"
            active.retired_at = func.now()
            session.add(active)
            await session.flush()
            checksum = await _recompute_catalog_checksum(session, catalog)
            orphan_model_id = active.model_id
            predecessor_model_id = predecessor.model_id

    return {
        "event": "rolled_back",
        "model_id": predecessor_model_id,
        "orphan_model_id": orphan_model_id,
        "removed_scopes": removed,
        "catalog_checksum": checksum,
        "restart_required": True,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="plan",
        choices=("plan", "apply", "verify", "rollback"),
        help="plan (default, writes nothing) | apply | verify | rollback",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="apply even though permission runtime heartbeats are live (they will fail closed)",
    )
    return parser.parse_args(argv)


async def _build_context() -> UpgradeContext:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import app_context
    from bisheng.core.database import get_async_db_session
    from bisheng.core.openfga.runtime_heartbeat import list_runtime_heartbeats
    from scripts.reconcile_f048_visible_projection import _environment_name

    client = await app_context.async_get_instance("openfga")
    return UpgradeContext(
        client=client,
        # The environment name is the FILTER KEY that selects which
        # authorization_model_release row this script reads and writes. It must
        # match how the reconcile script and the runtime derive it, or the
        # upgrade lands on a row nobody else looks at. `settings.openfga` never
        # had this field (the read was `settings.openfga.environment`, which
        # AttributeErrors post-merge); the value lives on the top-level
        # `settings.environment` and can be a str or a dict, exactly what the
        # reconcile script's `_environment_name` already normalises. Reuse it
        # rather than re-deriving, so the two scripts cannot drift.
        environment=_environment_name(settings.environment),
        session_factory=get_async_db_session,
        heartbeat_reader=list_runtime_heartbeats,
    )


async def execute(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import bypass_tenant_filter

    # ``initialize_app_context`` grew a required ``config`` argument when
    # feat/3.0.0-beta1 merged in; the sibling backfill scripts already pass it.
    # This script was on the other branch and did not get updated in the merge —
    # a no-arg call raised TypeError before it could even print the plan.
    await initialize_app_context(config=settings)
    try:
        ctx = await _build_context()
        # The control-plane tables carry no tenant_id, but the listener still
        # needs a context to skip; bypass keeps the script runnable outside a
        # request scope.
        with bypass_tenant_filter():
            if args.command == "plan":
                result = (await build_plan(ctx)).to_dict()
            elif args.command == "apply":
                result = await apply_upgrade(ctx, allow_live=args.allow_live)
            elif args.command == "verify":
                result = await verify_upgrade(ctx)
            else:
                result = await rollback_upgrade(ctx)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result.get("restart_required"):
            print(
                "RESTART EVERY PROCESS NOW: API, celery x3, beat, linsight worker. "
                "Heartbeats re-check every 15s (TTL 45s); a process left running fails closed.",
                file=sys.stderr,
            )
        return EXIT_OK
    finally:
        await close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except UpgradeBlockedError as exc:
        print(f"F048 authorization model upgrade blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
