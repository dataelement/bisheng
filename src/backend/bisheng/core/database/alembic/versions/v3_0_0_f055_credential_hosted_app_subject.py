"""F055 T055: widen ``api_credential.subject_kind`` to admit hosted applications.

``v3_0_0b1_f053_api_credential_tables`` created the CHECK with two values, and
``create_all`` never alters an existing table — so the model listing three
values only takes effect on a **fresh** database. On every upgraded one the
constraint still reads two, and the first hosted application to be brought
online dies inside ``AppRuntimeCredentialService.issue()`` with

    (pymysql.err.OperationalError) (3819, "Check constraint
    'ck_api_credential_subject_kind' is violated.")

surfaced to the operator as a 500 on 「重新上线」 (observed on 114, 2026-09-16).

Only the DDL lives here. A downgrade needs every ``subject_kind='hosted_app'``
row deleted first; that is an operational prerequisite, not something a
migration may do (the constitution forbids data changes in a revision), so the
downgrade fails loudly rather than silently dropping credentials.
"""

from alembic import op
from sqlalchemy import inspect

revision = "f055_credential_hosted_app_subject"
down_revision = "merge_app_factory_beta2_heads"
branch_labels = None
depends_on = None

_TABLE = "api_credential"
_NAME = "ck_api_credential_subject_kind"
_OLD = "subject_kind IN ('service_account', 'natural_person')"
_NEW = "subject_kind IN ('service_account', 'natural_person', 'hosted_app')"


def _skip() -> bool:
    """SQLite has no ALTER for constraints, and does not need one.

    Test databases are built by ``create_all`` from the model, which already
    carries the three-value form. ``batch_alter_table`` would rebuild the whole
    table to change nothing.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return True
    return _TABLE not in set(inspect(bind).get_table_names())


def upgrade() -> None:
    if _skip():
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _NEW)


def downgrade() -> None:
    if _skip():
        return
    bind = op.get_bind()
    remaining = bind.exec_driver_sql(f"SELECT COUNT(*) FROM {_TABLE} WHERE subject_kind = 'hosted_app'").scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} hosted-application credential(s) still exist; revoke them before downgrading "
            "(a migration must not delete credentials on its own)"
        )
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _OLD)
