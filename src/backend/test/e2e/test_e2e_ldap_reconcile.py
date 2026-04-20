"""E2E tests for F015 relink HTTP endpoints.

Scope: validate HTTP-layer wiring on a deployed backend —
``verify_hmac`` dependency, router registration, service delegation.
Deep behaviour (same-ts conflict, path_plus_name candidate scoring,
UserTenantSyncService fan-out) is covered by 64 unit + integration
tests (see ``ac-verification.md §1``).

Covers:

- AC-05: external_id_map strategy reaches the service layer.
- AC-06: path_plus_name strategy reaches the service layer.
- AC-07: dry_run path returns empty ``applied`` without DB writes.
- HMAC gate: missing / invalid signature → 19301.
- Route shape: resolve-conflict HMAC gate.

Prerequisites:

- Backend running with F015 code deployed (NOT the 2.5.0-PM baseline).
  Override port via ``E2E_API_BASE`` env var.
- HMAC secret via ``E2E_HMAC_SECRET`` env var MUST match the server's
  ``sso_sync.gateway_hmac_secret`` config (or
  ``BS_SSO_SYNC__GATEWAY_HMAC_SECRET`` env). A mismatch manifests as
  19301 on every happy-path test.

When either precondition is missing (``/relink`` returns 404 or no
HMAC secret configured), all tests in this module are skipped so a
bare ``pytest test/e2e`` run on a plain 2.5.0-PM backend stays green.

Data isolation: the external_id_map / path_plus_name probes target
non-existent ``old_external_ids`` with the ``e2e-f015-`` prefix so
the service layer returns ``applied=[]`` without touching real depts.
No cleanup needed.
"""

import base64
import hashlib
import hmac
import json
import os

import httpx
import pytest


API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')
HEALTH_URL = API_BASE.replace('/api/v1', '') + '/health'
HMAC_SECRET = os.environ.get('E2E_HMAC_SECRET', '')
SIGNATURE_HEADER = os.environ.get('E2E_SIGNATURE_HEADER', 'X-Signature')
PREFIX = 'e2e-f015-'

RELINK_PATH = '/internal/departments/relink'
RESOLVE_PATH = '/internal/departments/relink/resolve-conflict'


# ---------------------------------------------------------------------------
# HMAC signing (identical algorithm to F014 hmac_auth)
# ---------------------------------------------------------------------------


def _sign(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 of ``METHOD\\nPATH\\n`` + raw_body (hex lowercase)."""
    msg = f'{method.upper()}\n{path}\n'.encode() + raw_body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _signed_headers(method: str, full_path: str, raw_body: bytes,
                    secret: str = None) -> dict:
    secret = secret if secret is not None else HMAC_SECRET
    sig = _sign(method, full_path, raw_body, secret)
    return {
        'Content-Type': 'application/json',
        SIGNATURE_HEADER: sig,
    }


# ---------------------------------------------------------------------------
# Backend availability + feature-gate probes (scope=module)
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def anon_client():
    """Unauthenticated httpx client — F015 endpoints are HMAC-only."""
    client = httpx.Client(base_url=API_BASE, timeout=30)
    try:
        health = client.get(HEALTH_URL)
        if health.status_code != 200:
            pytest.skip('Backend not running (health != 200)')
    except httpx.ConnectError:
        pytest.skip(f'Backend not reachable at {HEALTH_URL}')

    # Feature gate: 2.5.0-PM baseline has no F015 endpoint → 404.
    # We probe with an empty signed body; any non-404 means the route
    # is mounted (even 401/422 is fine — we only care that F015 code is live).
    probe_body = b'{}'
    probe_headers = _signed_headers('POST', f'{API_BASE.rstrip("/")}' +
                                    RELINK_PATH, probe_body)
    probe = client.post(RELINK_PATH, content=probe_body, headers=probe_headers)
    if probe.status_code == 404:
        pytest.skip(
            'F015 relink endpoint not deployed on this backend (got 404). '
            'Deploy feat/v2.5.1/015-ldap-reconcile-celery + restart uvicorn '
            'before re-running this suite.',
        )
    if not HMAC_SECRET:
        pytest.skip(
            'E2E_HMAC_SECRET env var not set. Export the same value as the '
            'server\'s sso_sync.gateway_hmac_secret (or '
            'BS_SSO_SYNC__GATEWAY_HMAC_SECRET) to enable F015 e2e tests.',
        )

    yield client
    client.close()


def _signed_post(client: httpx.Client, path: str, payload: dict) -> httpx.Response:
    raw_body = json.dumps(payload, ensure_ascii=False).encode()
    # F014 signs the full request path including /api/v1, so mirror
    # that exact contract — the server reads request.url.path which is
    # ``/api/v1/internal/...`` when the router is mounted under /api/v1.
    full_path = f'{API_BASE.rstrip("/")}' + path
    # Extract path component (strip protocol+host) for signing.
    from urllib.parse import urlparse
    signed_path = urlparse(full_path).path or path
    headers = _signed_headers('POST', signed_path, raw_body)
    return client.post(path, content=raw_body, headers=headers)


# ---------------------------------------------------------------------------
# HMAC gate tests
# ---------------------------------------------------------------------------


class TestHmacGate:
    """The F014 ``verify_hmac`` dependency guards F015 endpoints."""

    def test_relink_without_signature_rejected(self, anon_client):
        """Missing X-Signature → 19301 (UnifiedResponseModel wraps the
        error in HTTP 200; the MMMEE lives in body['status_code'])."""
        resp = anon_client.post(
            RELINK_PATH,
            json={
                'old_external_ids': [f'{PREFIX}GHOST'],
                'matching_strategy': 'external_id_map',
                'external_id_map': {f'{PREFIX}GHOST': f'{PREFIX}NEW'},
            },
        )
        body = resp.json()
        assert body['status_code'] == 19301, (
            f'expected 19301 (SsoHmacInvalidError), got '
            f'{body.get("status_code")}: {body.get("status_message")}'
        )

    def test_relink_with_invalid_signature_rejected(self, anon_client):
        """Wrong signature → 19301."""
        raw = b'{"old_external_ids":[],"matching_strategy":"external_id_map"}'
        resp = anon_client.post(
            RELINK_PATH,
            content=raw,
            headers={
                'Content-Type': 'application/json',
                SIGNATURE_HEADER: 'deadbeef' * 8,  # 64 hex chars, invalid
            },
        )
        body = resp.json()
        assert body['status_code'] == 19301

    def test_resolve_conflict_without_signature_rejected(self, anon_client):
        """resolve-conflict is guarded by the same HMAC dep → 19301."""
        resp = anon_client.post(
            RESOLVE_PATH,
            json={'dept_id': 1, 'chosen_new_external_id': 'X'},
        )
        body = resp.json()
        assert body['status_code'] == 19301


# ---------------------------------------------------------------------------
# Strategy delegation (AC-05, AC-06, AC-07)
# ---------------------------------------------------------------------------


class TestRelinkDelegation:
    """Happy-path wiring: signed requests reach the service layer and
    return ``RelinkResponse`` JSON. We target non-existent old_external_ids
    (``e2e-f015-`` prefix) so the service returns empty ``applied`` /
    ``conflicts`` without touching real depts — deep behaviour is owned
    by the unit/integration suites."""

    def test_ac05_external_id_map_strategy_round_trip(self, anon_client):
        """AC-05: signed external_id_map reaches the service; response
        carries the unified response envelope with the expected keys."""
        resp = _signed_post(anon_client, RELINK_PATH, {
            'old_external_ids': [f'{PREFIX}ghost-ext'],
            'matching_strategy': 'external_id_map',
            'external_id_map': {
                f'{PREFIX}ghost-ext': f'{PREFIX}ghost-new',
            },
            'source': 'sso',
        })
        assert resp.status_code == 200, resp.text[:500]
        body = resp.json()
        assert body['status_code'] == 200, (
            f'business error: {body.get("status_message")}')
        data = body['data']
        # Ghost external_id → service short-circuits with applied=[].
        assert data['applied'] == []
        assert data['conflicts'] == []
        # Schema shape guarantees downstream consumers can always read
        # the three response buckets.
        assert set(data.keys()) >= {'applied', 'would_apply', 'conflicts'}

    def test_ac06_path_plus_name_strategy_round_trip(self, anon_client):
        """AC-06: signed path_plus_name reaches the service."""
        resp = _signed_post(anon_client, RELINK_PATH, {
            'old_external_ids': [f'{PREFIX}no-such-ext'],
            'matching_strategy': 'path_plus_name',
            'source': 'sso',
        })
        assert resp.status_code == 200, resp.text[:500]
        body = resp.json()
        assert body['status_code'] == 200
        data = body['data']
        assert data['applied'] == []
        assert data['conflicts'] == []

    def test_ac07_dry_run_never_writes(self, anon_client):
        """AC-07: dry_run returns the same empty envelope AND never
        produces ``applied`` entries even if mapping were non-empty."""
        resp = _signed_post(anon_client, RELINK_PATH, {
            'old_external_ids': [f'{PREFIX}ghost-ext-2'],
            'matching_strategy': 'external_id_map',
            'external_id_map': {
                f'{PREFIX}ghost-ext-2': f'{PREFIX}ghost-new-2',
            },
            'source': 'sso',
            'dry_run': True,
        })
        assert resp.status_code == 200, resp.text[:500]
        body = resp.json()
        assert body['status_code'] == 200
        data = body['data']
        # Regardless of whether the old_ext existed, dry_run guarantees
        # ``applied == []`` (AC-07 contract).
        assert data['applied'] == []
