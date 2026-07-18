"""Guard: org_sync JSON columns must use the DM-safe ``JsonType`` decorator.

Regression test for the production DaMeng (DM8) crash where
``OrgSyncLogRead.model_validate(log)`` received ``error_details`` as a raw JSON
*string* and Pydantic raised ``list_type`` (``Input should be a valid list``).

Root cause: the ORM models declared these columns with SQLAlchemy's native
``JSON`` type. On DM8 the physical column is CLOB and the native ``JSON`` type
does **not** deserialize the text back to a Python object on read — it returns
the raw string. The codebase-wide ``JsonType`` ``TypeDecorator`` (and the F009
migration that actually created these columns) round-trip correctly on
MySQL/DM8/SQLite. MySQL and SQLite deserialize native JSON on read, which is why
the bug only ever surfaced on DM in production.

These guards pin both columns back to ``JsonType`` so any future drift fails in
CI — fully offline, no DB connection required.
"""

from bisheng.core.database.dialect_helpers import JsonType
from bisheng.org_sync.domain.models.org_sync import OrgSyncConfig, OrgSyncLog


def test_org_sync_log_error_details_uses_json_type():
    col_type = OrgSyncLog.__table__.c.error_details.type
    assert isinstance(col_type, JsonType), (
        "OrgSyncLog.error_details must use JsonType (DM-safe): raw JSON returns "
        "an un-deserialized string on DaMeng and crashes OrgSyncLogRead with "
        f"list_type. Got {type(col_type).__name__}."
    )


def test_org_sync_config_sync_scope_uses_json_type():
    col_type = OrgSyncConfig.__table__.c.sync_scope.type
    assert isinstance(col_type, JsonType), (
        "OrgSyncConfig.sync_scope must use JsonType (DM-safe): same DaMeng "
        f"deserialization gap as error_details. Got {type(col_type).__name__}."
    )
