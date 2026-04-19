"""F014 shared constants."""

# Canonical ``source`` identifier for rows written/queried by the F014 SSO
# sync flows. Matches the enumerated value documented on
# ``User.source`` / ``Department.source`` columns.
SSO_SOURCE = 'sso'

# Trigger type recorded in ``org_sync_log.trigger_type`` for every row the
# F014 endpoints write. Lets F009 management UI distinguish Gateway-push
# rows from regular Celery-scheduled ones.
SSO_TRIGGER_TYPE = 'sso_realtime'
