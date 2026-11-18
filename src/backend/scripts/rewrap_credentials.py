"""Rewrap existing organization/sandbox ciphertext without changing credentials.

From src/backend, export the SAME config and BS_SECRET_KEYS_FILE as the service.
Default is read-only preflight. Use --all-tenants --backup-dir /secure/run;
--apply writes in batches only after durable backup. Resume with --resume DIR.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlmodel import select, update  # noqa: E402

from bisheng.core.config.credential_rewrap import (  # noqa: E402
    backup_plan,
    current_state,
    load_plan,
    plan_records,
    record_token,
    replace_record,
    write_journal,
)
from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring  # noqa: E402


class RuntimeStore:
    def __init__(self, sessions, org_model, config_model, bypass):
        self.sessions, self.org, self.config, self.bypass = sessions, org_model, config_model, bypass

    def records(self):
        with self.bypass(), self.sessions() as session:
            # Read all targets before writes: a corrupt later row must stop the
            # operation before any batch commits.
            orgs = session.exec(select(self.org).order_by(self.org.id)).all()
            configs = session.exec(select(self.config).where(self.config.key == "sandbox_endpoint")).all()
            return [
                {"kind": "org_sync", "id": r.id, "tenant_id": r.tenant_id, "value": r.auth_config} for r in orgs
            ] + [{"kind": "sandbox", "id": r.id, "tenant_id": None, "value": r.value} for r in configs]

    def apply_batch(self, entries):
        if len(entries) > 100:
            raise CredentialConfigurationError("rewrap: batch limit exceeded")
        with self.bypass(), self.sessions() as session:
            try:
                for entry in entries:
                    model = self.org if entry["kind"] == "org_sync" else self.config
                    statement = select(model).where(model.id == entry["id"])
                    if entry["kind"] == "org_sync":
                        statement = statement.where(model.tenant_id == entry["tenant_id"])
                    else:
                        statement = statement.where(model.key == "sandbox_endpoint")
                    row = session.exec(statement.with_for_update()).first()
                    if row is None:
                        raise CredentialConfigurationError("rewrap: target disappeared or tenant changed")
                    field = "auth_config" if entry["kind"] == "org_sync" else "value"
                    value = getattr(row, field)
                    if current_state(entry, record_token(entry["kind"], value)) == "NEW":
                        continue
                    replacement = replace_record(entry["kind"], value, entry["new"])
                    # Locked ORM identity + explicit tenant/key predicate, never
                    # a CLOB equality/JSON SQL condition. Explicit timestamp
                    # suppresses onupdate without changing business edit time.
                    query = update(model).where(model.id == entry["id"])
                    if entry["kind"] == "org_sync":
                        query = query.where(model.tenant_id == entry["tenant_id"])
                    else:
                        query = query.where(model.key == "sandbox_endpoint")
                    session.exec(
                        query.values(**{field: replacement, "update_time": row.update_time}).execution_options(
                            synchronize_session=False
                        )
                    )
                session.commit()
            except Exception:
                session.rollback()
                raise


async def clear_sandbox_cache(settings):
    from bisheng.core.cache.redis_conn import RedisClient

    # Maintenance already owns a live database context. A private Redis client
    # avoids closing that context before the post-commit primary-key recheck.
    client = RedisClient(settings.redis_url)
    try:
        await client.adelete("config:sandbox_endpoint")
    finally:
        await client.aclose()


def verify_static(ring):
    from urllib.parse import urlparse

    from sqlalchemy.engine import make_url

    from bisheng.core.config.credential_bundle import _object
    from bisheng.core.config.credential_loader import config_path, load_config

    data = load_config(config_path(os.getenv("config", "config.yaml"))).data
    values = []
    db = make_url(data["database_url"])
    values.append(db.password)

    def redis_tokens(value):
        if isinstance(value, str):
            return [urlparse(value).password]
        return (
            redis_tokens(value["url"]) if value.get("url") else [value.get("password"), value.get("sentinel_password")]
        )

    for name in ("redis_url", "celery_redis_url"):
        values.extend(redis_tokens(data[name]))
    values.append(data.get("object_storage", {}).get("minio", {}).get("secret_key"))
    vector = data.get("vector_stores", {})
    args = _object(vector.get("milvus", {}).get("connection_args"), "milvus")
    values.extend([args.get("password"), args.get("token")])
    for es in (vector.get("elasticsearch", {}), data.get("telemetry_elasticsearch", {})):
        auth = _object(es.get("ssl_verify", {}), "elasticsearch").get("basic_auth")
        if auth:
            values.append(auth[1])
    for value in values:
        if value:
            ring.decrypt_primary(value[8:-1] if value.startswith("encrypt(") and value.endswith(")") else value)


def execute(args, store, ring, cache_clear, static_check):
    records = store.records()
    if args.verify_primary_only:
        static_check(ring)
        plan_records(records, ring, primary_only=True)
        print("rewrap: primary-only verification passed")
        return 0
    # Full preflight even on resume; unknown concurrent ciphertext cannot be
    # hidden by a completed count from an old journal.
    planned = plan_records(records, ring)
    plan = load_plan(args.resume) if args.resume else planned
    if args.resume:
        current = {(r["kind"], r["id"]): r for r in records}
        for entry in plan:
            row = current.get((entry["kind"], entry["id"]))
            if row is None or row.get("tenant_id") != entry["tenant_id"]:
                raise CredentialConfigurationError("rewrap: recovery identity changed")
            current_state(entry, record_token(entry["kind"], row["value"]))
            if ring.decrypt_primary(entry["new"]) != ring.decrypt(entry["old"]):
                raise CredentialConfigurationError("rewrap: recovery ciphertext pair does not match")
        identities = {(e["kind"], e["id"]) for e in plan}
        if any((e["kind"], e["id"]) not in identities for e in planned):
            raise CredentialConfigurationError(
                "rewrap: additional old-key rows appeared; stop writers and prepare a new maintenance run"
            )
    if not args.apply:
        print(f"rewrap: dry-run target_count={len(plan)}; database/cache unchanged")
        return 0
    directory = Path(args.resume or args.backup_dir)
    if not args.resume:
        backup_plan(directory, plan)
    for start in range(0, len(plan), 100):
        store.apply_batch(plan[start : start + 100])
        write_journal(directory, "DB_IN_PROGRESS", min(start + 100, len(plan)))
    write_journal(directory, "DB_COMPLETE_CACHE_PENDING", len(plan))
    try:
        cache_clear()
        static_check(ring)
        plan_records(store.records(), ring, primary_only=True)
    except Exception:
        # DB commits remain durable. Do not claim rollback or COMPLETE.
        raise CredentialConfigurationError(
            "rewrap: DB committed; CACHE_PENDING or primary verification pending; resume required"
        ) from None
    write_journal(directory, "COMPLETE", len(plan))
    print(f"rewrap: COMPLETE target_count={len(plan)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-tenants", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backup-dir", type=Path)
    group.add_argument("--resume", type=Path)
    group.add_argument("--verify-primary-only", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and (args.verify_primary_only or not (args.backup_dir or args.resume)):
        parser.error("--apply requires backup-dir or resume")
    try:
        from bisheng.common.models.config import Config
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_sync_db_session
        from bisheng.org_sync.domain.models.org_sync import OrgSyncConfig

        store = RuntimeStore(get_sync_db_session, OrgSyncConfig, Config, bypass_tenant_filter)
        return execute(args, store, get_keyring(), lambda: asyncio.run(clear_sandbox_cache(settings)), verify_static)
    except CredentialConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        print(
            "rewrap: maintenance failed; inspect durable journal before retry; no secret details emitted",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
