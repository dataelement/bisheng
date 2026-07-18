"""SSO realtime sync module (F014-sso-org-realtime-sync).

HMAC-authenticated endpoints that let the Gateway push SSO login events and
bulk department changes into bisheng in real time. Separate from
``bisheng.org_sync`` because F014 is the *push* direction (Gateway → bisheng,
HMAC-only, no JWT context) whereas ``org_sync`` is the *pull* direction
(bisheng → provider, admin-gated, Celery-scheduled).

See ``features/v2.5.1/014-sso-org-realtime-sync/spec.md``.
"""
