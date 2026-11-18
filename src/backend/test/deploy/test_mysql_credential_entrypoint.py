"""AC-06/11/12/43: native MySQL bootstrap preserves valid password characters."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WRAPPER = ROOT / "docker/mysql/credential-entrypoint.sh"


def shell(script, **variables):
    result = subprocess.run(
        ["bash", "-c", 'source "$WRAPPER"\n' + script],
        env={**os.environ, "WRAPPER": str(WRAPPER), **variables},
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result


def test_sql_literal_escapes_quote_and_backslash_without_evaluating_input(tmp_path):
    marker = tmp_path / "must-not-exist"
    value = "a'\\b\"@:$#%;$(touch " + str(marker) + ")"
    result = shell('mysql_sql_literal "$CASE_VALUE"', CASE_VALUE=value)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
    assert not marker.exists()


def test_client_password_file_preserves_quote_backslash_and_whitespace():
    value = " space'\\double\"@:$#% "
    result = shell("_mysql_passfile", MYSQL_ROOT_PASSWORD=value)
    assert result.returncode == 0, result.stderr
    assert result.stdout == '[client]\npassword="' + value.replace("\\", "\\\\").replace('"', '\\"') + '"\n'
    assert shell("_mysql_passfile --dont-use-mysql-root-password", MYSQL_ROOT_PASSWORD=value).stdout == ""


def test_bootstrap_uses_safe_literals_and_keeps_vendor_client_password():
    password = "quote'and\\slash\""
    script = """
MYSQL_INITDB_SKIP_TZINFO=1
MYSQL_ROOT_HOST="%"
MYSQL_DATABASE='business`name'
docker_process_sql() { cat; }
docker_setup_db
[[ $MYSQL_ROOT_PASSWORD = "$CASE_VALUE" ]]
"""
    result = shell(script, MYSQL_ROOT_PASSWORD=password, CASE_VALUE=password)
    assert result.returncode == 0, result.stderr
    escaped = "'" + password.replace("\\", "\\\\").replace("'", "''") + "'"
    assert "ALTER USER 'root'@'localhost' IDENTIFIED BY " + escaped in result.stdout
    assert "CREATE USER 'root'@'%' IDENTIFIED BY " + escaped in result.stdout
    assert "NO_BACKSLASH_ESCAPES" in result.stdout
    assert "CREATE DATABASE IF NOT EXISTS `business``name`" in result.stdout


def test_bootstrap_never_generates_or_accepts_empty_password():
    result = shell("docker_setup_db", MYSQL_ROOT_PASSWORD="")
    assert result.returncode != 0
    result = shell("docker_setup_db", MYSQL_ROOT_PASSWORD="supplied", MYSQL_RANDOM_ROOT_PASSWORD="yes")
    assert result.returncode != 0
    assert "GENERATED ROOT PASSWORD" not in result.stdout + result.stderr


def test_default_command_still_launches_mysqld_after_entrypoint_override():
    script = """
_mysql_want_help() { return 1; }
mysql_check_config() { :; }
docker_setup_env() { :; }
docker_create_db_directories() { :; }
id() { printf '999\\n'; }
_main() { printf '%s\\n' "$@"; }
credential_mysql_main
"""
    result = shell(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "mysqld\n"
