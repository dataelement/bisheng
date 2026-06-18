"""F014 shared constants."""

# Generic HMAC Gateway push (``/departments/sync``, ``/internal/sso/login-sync``).
# ``User.source`` / ``Department.source`` for non-WeCom upstreams.
SSO_SOURCE = 'sso'

# WeChat Work (企业微信) data via ``/internal/sso/gateway-wecom-org-sync``.
# Must match org_sync config provider enum (``wecom``).
WECOM_SOURCE = 'wecom'

# Shougang (首钢) org sync source for dedicated SG callback payloads.
SG_SOURCE = 'sg'

# Default source used by single-user login-sync and plain departments/sync
# when the caller does not explicitly specify one. Keep this aligned across
# endpoints so department upsert and subsequent login bind against the same
# rows by default.
DEFAULT_SSO_SYNC_SOURCE = WECOM_SOURCE

# Trigger type recorded in ``org_sync_log.trigger_type`` for every row the
# F014 endpoints write. Lets F009 management UI distinguish Gateway-push
# rows from regular Celery-scheduled ones.
SSO_TRIGGER_TYPE = 'sso_realtime'
