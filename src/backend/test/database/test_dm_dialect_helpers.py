"""Unit tests for dialect_helpers — all run without a real DB connection."""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# LargeText
# ---------------------------------------------------------------------------


class TestLargeText:
    def _make_dialect(self, name: str):
        d = MagicMock()
        d.name = name
        d.type_descriptor.side_effect = lambda t: t
        return d

    def test_mysql_returns_longtext(self):
        from sqlalchemy.dialects.mysql import LONGTEXT

        from bisheng.core.database.dialect_helpers import LargeText

        lt = LargeText()
        result = lt.load_dialect_impl(self._make_dialect("mysql"))
        assert isinstance(result, LONGTEXT)

    def test_dm_returns_clob(self):
        from sqlalchemy import CLOB

        from bisheng.core.database.dialect_helpers import LargeText

        lt = LargeText()
        result = lt.load_dialect_impl(self._make_dialect("dm"))
        assert isinstance(result, CLOB)

    def test_sqlite_returns_text(self):
        from sqlalchemy import Text

        from bisheng.core.database.dialect_helpers import LargeText

        lt = LargeText()
        result = lt.load_dialect_impl(self._make_dialect("sqlite"))
        assert isinstance(result, Text)

    def test_cache_ok_is_true(self):
        from bisheng.core.database.dialect_helpers import LargeText

        assert LargeText.cache_ok is True


# ---------------------------------------------------------------------------
# table_exists
# ---------------------------------------------------------------------------


class TestTableExists:
    def _make_conn(self, has_table_return: bool):
        insp = MagicMock()
        insp.has_table.return_value = has_table_return
        conn = MagicMock()
        return conn, insp

    def test_returns_true_when_table_found(self):
        from bisheng.core.database.dialect_helpers import table_exists

        conn, insp = self._make_conn(True)
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert table_exists(conn, "my_table") is True
            insp.has_table.assert_called_once_with("my_table")

    def test_returns_false_when_table_missing(self):
        from bisheng.core.database.dialect_helpers import table_exists

        conn, insp = self._make_conn(False)
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert table_exists(conn, "no_table") is False

    def test_returns_false_on_exception(self):
        from bisheng.core.database.dialect_helpers import table_exists

        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", side_effect=Exception("boom")):
            assert table_exists(conn, "any") is False


# ---------------------------------------------------------------------------
# column_exists
# ---------------------------------------------------------------------------


class TestColumnExists:
    def _make_conn(self, columns: list):
        insp = MagicMock()
        insp.get_columns.return_value = columns
        conn = MagicMock()
        return conn, insp

    def test_returns_true_when_column_found(self):
        from bisheng.core.database.dialect_helpers import column_exists

        conn, insp = self._make_conn([{"name": "id"}, {"name": "tenant_id"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert column_exists(conn, "flow", "tenant_id") is True

    def test_case_insensitive(self):
        from bisheng.core.database.dialect_helpers import column_exists

        conn, insp = self._make_conn([{"name": "TenantId"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert column_exists(conn, "flow", "tenantid") is True

    def test_returns_false_when_column_missing(self):
        from bisheng.core.database.dialect_helpers import column_exists

        conn, insp = self._make_conn([{"name": "id"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert column_exists(conn, "flow", "visibility") is False

    def test_returns_false_on_exception(self):
        from bisheng.core.database.dialect_helpers import column_exists

        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", side_effect=Exception):
            assert column_exists(conn, "flow", "col") is False


# ---------------------------------------------------------------------------
# index_exists
# ---------------------------------------------------------------------------


class TestIndexExists:
    def _make_conn(self, indexes: list):
        insp = MagicMock()
        insp.get_indexes.return_value = indexes
        conn = MagicMock()
        return conn, insp

    def test_returns_true_when_index_found(self):
        from bisheng.core.database.dialect_helpers import index_exists

        conn, insp = self._make_conn([{"name": "ix_flow_tenant"}, {"name": "ix_other"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert index_exists(conn, "flow", "ix_flow_tenant") is True

    def test_case_insensitive(self):
        from bisheng.core.database.dialect_helpers import index_exists

        conn, insp = self._make_conn([{"name": "IX_FLOW_TENANT"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert index_exists(conn, "flow", "ix_flow_tenant") is True

    def test_returns_false_when_index_missing(self):
        from bisheng.core.database.dialect_helpers import index_exists

        conn, insp = self._make_conn([{"name": "ix_other"}])
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert index_exists(conn, "flow", "ix_flow_tenant") is False


# ---------------------------------------------------------------------------
# get_column_type
# ---------------------------------------------------------------------------


class TestGetColumnType:
    def test_returns_lowercased_type_name(self):
        from sqlalchemy.dialects.mysql import LONGTEXT as LT

        from bisheng.core.database.dialect_helpers import get_column_type

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "body", "type": LT()}]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            result = get_column_type(conn, "msg", "body")
        assert result == "longtext"

    def test_returns_none_when_column_missing(self):
        from bisheng.core.database.dialect_helpers import get_column_type

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "id", "type": MagicMock()}]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert get_column_type(conn, "tbl", "missing") is None


# ---------------------------------------------------------------------------
# is_column_nullable
# ---------------------------------------------------------------------------


class TestIsColumnNullable:
    def test_returns_true_when_nullable(self):
        from bisheng.core.database.dialect_helpers import is_column_nullable

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "tenant_id", "nullable": True}]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert is_column_nullable(conn, "auditlog", "tenant_id") is True

    def test_returns_false_when_not_nullable(self):
        from bisheng.core.database.dialect_helpers import is_column_nullable

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "tenant_id", "nullable": False}]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert is_column_nullable(conn, "auditlog", "tenant_id") is False

    def test_returns_false_when_column_not_found(self):
        from bisheng.core.database.dialect_helpers import is_column_nullable

        insp = MagicMock()
        insp.get_columns.return_value = []
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert is_column_nullable(conn, "tbl", "no_col") is False


# ---------------------------------------------------------------------------
# constraint_exists
# ---------------------------------------------------------------------------


class TestConstraintExists:
    def test_returns_true_when_found(self):
        from bisheng.core.database.dialect_helpers import constraint_exists

        insp = MagicMock()
        insp.get_unique_constraints.return_value = [
            {"name": "uk_tenant_roletype_rolename", "column_names": ["tenant_id", "role_type", "role_name"]}
        ]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert constraint_exists(conn, "role", "uk_tenant_roletype_rolename") is True

    def test_returns_false_when_not_found(self):
        from bisheng.core.database.dialect_helpers import constraint_exists

        insp = MagicMock()
        insp.get_unique_constraints.return_value = []
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert constraint_exists(conn, "role", "uk_missing") is False


# ---------------------------------------------------------------------------
# get_indexes_for_column
# ---------------------------------------------------------------------------


class TestGetIndexesForColumn:
    def test_returns_matching_indexes(self):
        from bisheng.core.database.dialect_helpers import get_indexes_for_column

        insp = MagicMock()
        insp.get_indexes.return_value = [
            {"name": "ix_user_name", "unique": True, "column_names": ["user_name"]},
            {"name": "ix_user_email", "unique": False, "column_names": ["email"]},
        ]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            result = get_indexes_for_column(conn, "user", "user_name")
        assert len(result) == 1
        assert result[0]["name"] == "ix_user_name"
        assert result[0]["unique"] is True

    def test_returns_empty_when_no_match(self):
        from bisheng.core.database.dialect_helpers import get_indexes_for_column

        insp = MagicMock()
        insp.get_indexes.return_value = [
            {"name": "ix_other", "unique": False, "column_names": ["other_col"]},
        ]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            result = get_indexes_for_column(conn, "user", "user_name")
        assert result == []


# ---------------------------------------------------------------------------
# get_version_num_length
# ---------------------------------------------------------------------------


class TestGetVersionNumLength:
    def test_returns_length(self):
        from sqlalchemy import String

        from bisheng.core.database.dialect_helpers import get_version_num_length

        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "version_num", "type": String(255)}]
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert get_version_num_length(conn) == 255

    def test_returns_none_when_column_missing(self):
        from bisheng.core.database.dialect_helpers import get_version_num_length

        insp = MagicMock()
        insp.get_columns.return_value = []
        conn = MagicMock()
        with patch("bisheng.core.database.dialect_helpers.inspect", return_value=insp):
            assert get_version_num_length(conn) is None


# ---------------------------------------------------------------------------
# update_time_server_default
# ---------------------------------------------------------------------------


class TestUpdateTimeServerDefault:
    def _make_conn(self, dialect_name: str):
        conn = MagicMock()
        conn.dialect.name = dialect_name
        return conn

    def test_mysql_returns_on_update(self):
        from bisheng.core.database.dialect_helpers import update_time_server_default

        result = update_time_server_default(self._make_conn("mysql"))
        assert "ON UPDATE" in str(result)

    def test_dm_returns_current_timestamp_only(self):
        from bisheng.core.database.dialect_helpers import update_time_server_default

        result = update_time_server_default(self._make_conn("dm"))
        assert "ON UPDATE" not in str(result)
        assert "CURRENT_TIMESTAMP" in str(result)


# ---------------------------------------------------------------------------
# JsonType
# ---------------------------------------------------------------------------


class TestJsonType:
    def _make_dialect(self, name: str):
        d = MagicMock()
        d.name = name
        d.type_descriptor.side_effect = lambda t: t
        return d

    def test_mysql_load_dialect_returns_json(self):
        from sqlalchemy import JSON

        from bisheng.core.database.dialect_helpers import JsonType

        result = JsonType().load_dialect_impl(self._make_dialect("mysql"))
        assert isinstance(result, JSON)

    def test_dm_load_dialect_returns_clob(self):
        from sqlalchemy import CLOB

        from bisheng.core.database.dialect_helpers import JsonType

        result = JsonType().load_dialect_impl(self._make_dialect("dm"))
        assert isinstance(result, CLOB)

    def test_sqlite_load_dialect_returns_text(self):
        from sqlalchemy import Text

        from bisheng.core.database.dialect_helpers import JsonType

        result = JsonType().load_dialect_impl(self._make_dialect("sqlite"))
        assert isinstance(result, Text)

    def test_cache_ok_is_true(self):
        from bisheng.core.database.dialect_helpers import JsonType

        assert JsonType.cache_ok is True

    def test_dm_bind_param_serializes_dict(self):
        import json

        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "dm"
        result = JsonType().process_bind_param({"k": "v"}, dialect)
        assert json.loads(result) == {"k": "v"}

    def test_dm_bind_param_serializes_list(self):
        import json

        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "dm"
        result = JsonType().process_bind_param([1, 2, 3], dialect)
        assert json.loads(result) == [1, 2, 3]

    def test_dm_bind_param_none_returns_none(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "dm"
        assert JsonType().process_bind_param(None, dialect) is None

    def test_dm_result_value_deserializes_dict(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "dm"
        result = JsonType().process_result_value('{"k": "v"}', dialect)
        assert result == {"k": "v"}

    def test_dm_result_value_none_returns_none(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "dm"
        assert JsonType().process_result_value(None, dialect) is None

    def test_mysql_bind_param_passthrough(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "mysql"
        data = {"k": "v"}
        assert JsonType().process_bind_param(data, dialect) is data

    def test_mysql_result_value_passthrough(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "mysql"
        data = {"k": "v"}
        assert JsonType().process_result_value(data, dialect) is data

    def test_sqlite_bind_param_serializes(self):
        import json

        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "sqlite"
        result = JsonType().process_bind_param({"k": "v"}, dialect)
        assert json.loads(result) == {"k": "v"}

    def test_sqlite_result_value_deserializes(self):
        from bisheng.core.database.dialect_helpers import JsonType

        dialect = MagicMock()
        dialect.name = "sqlite"
        result = JsonType().process_result_value('{"k": "v"}', dialect)
        assert result == {"k": "v"}


# ---------------------------------------------------------------------------
# DatabaseConnectionManager — URL conversion
# ---------------------------------------------------------------------------


class TestConnectionManagerUrlConversion:
    def test_pymysql_converts_to_aiomysql(self):
        from bisheng.core.database.connection import DatabaseConnectionManager

        mgr = DatabaseConnectionManager.__new__(DatabaseConnectionManager)
        result = mgr._convert_to_async_url("mysql+pymysql://user:pass@host/db")
        assert result == "mysql+aiomysql://user:pass@host/db"

    def test_dmPython_converts_to_dmAsync(self):
        from bisheng.core.database.connection import DatabaseConnectionManager

        mgr = DatabaseConnectionManager.__new__(DatabaseConnectionManager)
        result = mgr._convert_to_async_url("dm+dmPython://SYSDBA:pass@192.168.107.9:5236/BISHENG")
        assert result == "dm+dmAsync://SYSDBA:pass@192.168.107.9:5236/BISHENG"

    def test_unknown_url_unchanged(self):
        from bisheng.core.database.connection import DatabaseConnectionManager

        mgr = DatabaseConnectionManager.__new__(DatabaseConnectionManager)
        url = "sqlite:///./bisheng.db"
        assert mgr._convert_to_async_url(url) == url

    def test_dm_normalize_moves_path_schema_to_query(self):
        # Path /SCHEMA must become ?schema=SCHEMA: dmPython rejects the
        # `database` kwarg the path maps to, but accepts `schema` from the query.
        from sqlalchemy.engine.url import make_url

        from bisheng.core.database.connection import DatabaseConnectionManager

        url = "dm+dmPython://SYSDBA:pass@192.168.107.9:5236/BISHENG"
        result = make_url(DatabaseConnectionManager._normalize_dm_url(url))
        assert result.database is None
        assert result.query.get("schema") == "BISHENG"

    def test_dm_normalize_no_schema_clears_path_only(self):
        from sqlalchemy.engine.url import make_url

        from bisheng.core.database.connection import DatabaseConnectionManager

        url = "dm+dmPython://SYSDBA:pass@192.168.107.9:5236"
        result = make_url(DatabaseConnectionManager._normalize_dm_url(url))
        assert result.database is None
        assert "schema" not in result.query

    def test_dm_normalize_explicit_query_schema_wins(self):
        # An explicit ?schema= takes precedence over a path-specified schema.
        from sqlalchemy.engine.url import make_url

        from bisheng.core.database.connection import DatabaseConnectionManager

        url = "dm+dmPython://SYSDBA:pass@192.168.107.9:5236/BISHENG?schema=OPENFGA"
        result = make_url(DatabaseConnectionManager._normalize_dm_url(url))
        assert result.database is None
        assert result.query.get("schema") == "OPENFGA"

    def test_dm_normalize_is_idempotent(self):
        from bisheng.core.database.connection import DatabaseConnectionManager

        url = "dm+dmPython://SYSDBA:pass@192.168.107.9:5236/BISHENG"
        once = DatabaseConnectionManager._normalize_dm_url(url)
        twice = DatabaseConnectionManager._normalize_dm_url(once)
        assert once == twice
