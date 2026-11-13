"""AC-28..36/42: MySQL/DM native transaction/lock parity in disposable CI DB.

Run separately with each database's explicit live config. This creates only
prefix-scoped organization rows and cleans those IDs; no existing sandbox row
is overwritten. Global sandbox/time/cache fault cases use isolated runtime tests.
"""

import asyncio
import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlmodel import select

from bisheng.core.config.credential_rewrap import plan_records
from bisheng.core.config.secret_crypto import load_keyring


def test_native_database_rewrap_retains_tenant_and_time(live_settings, tmp_path):
    # ConfigService singleton must be bound to this very acceptance deployment.
    config_path = os.getenv("config")
    if not config_path:
        pytest.fail("Set config to the same live deployment YAML")
    from bisheng.common.services.config_service import settings

    assert settings.database_url == live_settings.database_url
    from sqlalchemy.engine import make_url

    from bisheng.common.models.config import Config
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_sync_db_session
    from bisheng.org_sync.domain.models.org_sync import OrgSyncConfig

    assert make_url(settings.database_url).get_backend_name() in ("mysql", "dm")
    path = Path(__file__).resolve().parents[2] / "scripts/rewrap_credentials.py"
    spec = importlib.util.spec_from_file_location("live_rewrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.RuntimeStore(get_sync_db_session, OrgSyncConfig, Config, bypass_tenant_filter)
    old_key = Fernet.generate_key()
    old = Fernet(old_key)
    keyfile = tmp_path / "test-keys.json"
    keyfile.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode(), old_key.decode()]}))
    keyfile.chmod(0o600)
    ring = load_keyring(keyfile)
    ids = []
    before = {}
    prefix = "e2e-credential-" + uuid.uuid4().hex
    try:
        with bypass_tenant_filter(), get_sync_db_session() as s:
            for tenant in (700001, 700002):
                row = OrgSyncConfig(
                    tenant_id=tenant,
                    provider="generic_api",
                    config_name=prefix,
                    auth_type="password",
                    auth_config=old.encrypt(b'{"unknown":42}').decode(),
                )
                s.add(row)
                s.flush()
                s.refresh(row)
                ids.append(row.id)
                before[row.id] = (row.tenant_id, row.update_time)
            s.commit()
        with bypass_tenant_filter(), get_sync_db_session() as s:
            rows = s.exec(select(OrgSyncConfig).where(OrgSyncConfig.id.in_(ids))).all()
            plan = plan_records(
                [{"kind": "org_sync", "id": r.id, "tenant_id": r.tenant_id, "value": r.auth_config} for r in rows], ring
            )
        store.apply_batch(plan)
        store.apply_batch(plan)
        # Real cache maintenance must leave the already-active DB context usable
        # for the migration's final primary-key verification.
        asyncio.run(module.clear_sandbox_cache(settings))
        assert store.records()
        with bypass_tenant_filter(), get_sync_db_session() as s:
            rows = s.exec(select(OrgSyncConfig).where(OrgSyncConfig.id.in_(ids))).all()
            assert len(rows) == 2
            for row in rows:
                assert (row.tenant_id, row.update_time) == before[row.id]
                assert json.loads(ring.decrypt_primary(row.auth_config)) == {"unknown": 42}
    finally:
        with bypass_tenant_filter(), get_sync_db_session() as s:
            rows = s.exec(
                select(OrgSyncConfig).where(OrgSyncConfig.id.in_(ids), OrgSyncConfig.config_name == prefix)
            ).all()
            for row in rows:
                s.delete(row)
            s.commit()
