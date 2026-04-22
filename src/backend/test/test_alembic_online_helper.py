from unittest.mock import MagicMock

from bisheng.core.database.alembic_helpers.online import (
    finalize_online_migration_connection,
)


class TestFinalizeOnlineMigrationConnection:

    def test_commits_when_connection_still_has_implicit_transaction(self):
        connection = MagicMock()
        connection.in_transaction.return_value = True

        committed = finalize_online_migration_connection(connection)

        assert committed is True
        connection.commit.assert_called_once_with()

    def test_noop_when_connection_has_no_open_transaction(self):
        connection = MagicMock()
        connection.in_transaction.return_value = False

        committed = finalize_online_migration_connection(connection)

        assert committed is False
        connection.commit.assert_not_called()
