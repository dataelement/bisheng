"""F029: backfill resource-level shared_with tuples for existing Root LLM.

Revision ID: f029_llm_shared_backfill
Revises: f028_workbench_menu_keys_backfill
Create Date: 2026-04-25

Why:
  v2.4 → v2.5 upgrade adds ``llm_server.tenant_id`` (default Root=1) but
  does not write OpenFGA ``tenant:{child}#shared_with → llm_server:{id}``
  tuples for pre-existing Root rows. The LLM list query in
  ``LLMDao.aget_shared_server_ids_for_leaf`` therefore returns empty for
  Children, hiding all Root LLMs from upgraded customers (an upgraded site
  with one default LLM and several Children effectively loses LLM access
  in every Child after the upgrade).

  Note: Root → Child sharing for LLM uses **resource-level** shared_with —
  different from the **tenant-level** shared_to used by knowledge_space /
  workflow / assistant. See ResourceShareService docstring for the two
  parallel mechanisms.

What:
  For each (active Child, Root llm_server) pair, write the shared_with
  tuple via direct OpenFGA HTTP. Sync writes from the alembic context
  because FGAClient is initialized lazily on first app request and is not
  available in the migration runner.

Failure tolerance:
  If OpenFGA isn't reachable from the alembic process (DB upgrade
  sometimes runs before the FGA container is healthy), log a warning and
  let the migration succeed. Tuples are written one-by-one with
  per-tuple try/except so an existing duplicate row doesn't poison the
  remaining writes (FGA returns 400 on duplicate within a batch and
  rolls back the whole batch).
"""

import json
import urllib.error
import urllib.request
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.database.models.tenant import ROOT_TENANT_ID

revision: str = 'f029_llm_shared_backfill'
down_revision: Union[str, Sequence[str], None] = 'f028_workbench_menu_keys_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# OpenFGA's /write endpoint accepts multiple tuple_keys per request; chunking
# guards against payload-size limits on huge sites (e.g. 1000 servers × 100
# children = 100k tuples) without giving up the per-batch fallback that lets
# us tolerate already-existing tuples on rerun.
_BATCH_SIZE = 500


def _fga_post(url: str, body: dict, timeout: float) -> None:
    """POST a JSON body to OpenFGA. Raises urllib.error.HTTPError on non-2xx."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()  # drain to free the socket


def _fga_get(url: str, timeout: float) -> dict:
    """GET a JSON response from OpenFGA. Raises on non-2xx."""
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
        return json.loads(resp.read())


def _resolve_store_and_model(api_url: str, store_name: str, timeout: float) -> tuple:
    """Look up store id by name and the latest authorization model id.

    Settings hold ``store_id`` / ``model_id`` only after OpenFGAManager
    bootstraps at app startup; the alembic process runs before that, so we
    discover both via the FGA HTTP API. Returns (None, None) on lookup
    failure so the migration can skip cleanly.
    """
    try:
        stores = _fga_get(f'{api_url}/stores', timeout=timeout).get('stores', [])
    except Exception as exc:  # noqa: BLE001 — FGA unreachable, skip
        print(f'[F029]  store lookup failed: {exc}')
        return None, None

    sid = next((s['id'] for s in stores if s.get('name') == store_name), None)
    if not sid:
        return None, None

    try:
        models = _fga_get(
            f'{api_url}/stores/{sid}/authorization-models?page_size=1',
            timeout=timeout,
        ).get('authorization_models', [])
    except Exception as exc:  # noqa: BLE001
        print(f'[F029]  model lookup failed: {exc}')
        return sid, None

    mid = models[0]['id'] if models else None
    return sid, mid


def upgrade() -> None:
    try:
        from bisheng.common.services.config_service import settings
        cfg = settings.openfga
    except Exception as exc:  # noqa: BLE001 — settings unavailable in some test fixtures
        print(f'[F029] settings.openfga unavailable, skip backfill: {exc}')
        return

    if not getattr(cfg, 'enabled', False):
        print('[F029] OpenFGA disabled, skip backfill')
        return

    api_url = cfg.api_url.rstrip('/')
    timeout = float(getattr(cfg, 'timeout', 5))
    store_id = cfg.store_id
    model_id = cfg.model_id
    if not store_id or not model_id:
        # Settings only carry these after OpenFGAManager.bootstrap, which the
        # alembic process never runs. Discover via the FGA HTTP API instead.
        store_id, model_id = _resolve_store_and_model(
            api_url, getattr(cfg, 'store_name', 'bisheng'), timeout,
        )
    if not store_id or not model_id:
        print('[F029] OpenFGA store/model not found, skip backfill '
              '(start the app once to bootstrap, then rerun)')
        return

    conn = op.get_bind()

    # Honour the "Root-only" intent: if the operator turned off
    # share_default_to_children on the Root tenant, do not auto-fan out.
    # Default True (matches PRD §7.1.6 + tenant table DEFAULT 1).
    share_row = conn.execute(sa.text(
        'SELECT share_default_to_children FROM tenant WHERE id = :t'
    ), {'t': ROOT_TENANT_ID}).fetchone()
    if share_row is not None and not bool(share_row[0]):
        print('[F029] Root tenant.share_default_to_children=0; skip backfill '
              '(operators can re-enable per-resource via the share dialog)')
        return

    server_ids = [
        r[0] for r in conn.execute(sa.text(
            'SELECT id FROM llm_server WHERE tenant_id = :t'
        ), {'t': ROOT_TENANT_ID}).fetchall()
    ]
    if not server_ids:
        print('[F029] no Root llm_server rows; nothing to backfill')
        return

    child_ids = [
        r[0] for r in conn.execute(sa.text(
            "SELECT id FROM tenant WHERE parent_tenant_id = :t AND status = 'active'"
        ), {'t': ROOT_TENANT_ID}).fetchall()
    ]
    if not child_ids:
        print(f'[F029] {len(server_ids)} Root llm_server but no active Children; '
              'tuples will be written by mount_child when the first Child is mounted')
        return

    write_url = f'{api_url}/stores/{store_id}/write'
    all_tuples = [
        {
            'user': f'tenant:{cid}',
            'relation': 'shared_with',
            'object': f'llm_server:{sid}',
        }
        for cid in child_ids for sid in server_ids
    ]

    ok = 0
    skipped = 0
    failed = 0
    for i in range(0, len(all_tuples), _BATCH_SIZE):
        batch = all_tuples[i:i + _BATCH_SIZE]
        body = {
            'writes': {'tuple_keys': batch},
            'authorization_model_id': model_id,
        }
        try:
            _fga_post(write_url, body, timeout=timeout)
            ok += len(batch)
            continue
        except urllib.error.HTTPError as http_err:
            # OpenFGA rolls back the whole batch on duplicate tuples (400).
            # Fall back to per-tuple writes so already-existing rows don't
            # poison the new ones — only on the failing batch, not all.
            if http_err.code != 400:
                failed += len(batch)
                print(f'[F029]  HTTP {http_err.code} on batch {i // _BATCH_SIZE}: {http_err.reason}')
                continue
        except Exception as exc:  # noqa: BLE001 — best-effort, never abort upgrade
            failed += len(batch)
            print(f'[F029]  unreachable on batch {i // _BATCH_SIZE}: {exc}')
            continue

        for tuple_key in batch:
            try:
                _fga_post(
                    write_url,
                    {'writes': {'tuple_keys': [tuple_key]}, 'authorization_model_id': model_id},
                    timeout=timeout,
                )
                ok += 1
            except urllib.error.HTTPError as http_err:
                if http_err.code == 400:
                    skipped += 1
                else:
                    failed += 1
                    print(f'[F029]  HTTP {http_err.code} for {tuple_key}: {http_err.reason}')
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f'[F029]  unreachable for {tuple_key}: {exc}')

    print(f'[F029] backfill done: ok={ok} skipped(existing)={skipped} failed={failed} '
          f'(servers={len(server_ids)} × children={len(child_ids)} = {len(all_tuples)} tuples)')


def downgrade() -> None:
    """Idempotent forward migration; no-op rollback.

    A real rollback would have to know which shared_with tuples were
    pre-existing vs written here, which the migration does not track.
    Leaving them in place is harmless on downgrade — the LLM service
    still queries them but the schema downgrade only flips column
    defaults and the tuples become inert.
    """
    pass
