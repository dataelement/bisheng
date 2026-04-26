"""F014 shared constants."""

# Generic HMAC Gateway push (``/departments/sync``, ``/internal/sso/login-sync``).
# ``User.source`` / ``Department.source`` for non-WeCom upstreams.
SSO_SOURCE = 'sso'

# WeChat Work (企业微信) data via ``/internal/sso/gateway-wecom-org-sync``.
# Must match org_sync config provider enum (``wecom``).
WECOM_SOURCE = 'wecom'

# Trigger type recorded in ``org_sync_log.trigger_type`` for every row the
# F014 endpoints write. Lets F009 management UI distinguish Gateway-push
# rows from regular Celery-scheduled ones.
SSO_TRIGGER_TYPE = 'sso_realtime'
