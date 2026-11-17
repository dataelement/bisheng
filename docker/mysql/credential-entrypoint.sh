#!/usr/bin/env bash
# Keep the vendor lifecycle and mysql user; serialize bootstrap SQL safely.
set +x
set -eo pipefail

if [[ ${BASH_SOURCE[0]} = "$0" ]]; then
  source /usr/local/bin/docker-entrypoint.sh
fi

mysql_sql_literal() {
  local value=${1//\\/\\\\}
  value=${value//\'/\'\'}
  printf "'%s'" "$value"
}

mysql_sql_identifier() {
  local value=${1//\`/\`\`}
  printf '`%s`' "$value"
}

# The pinned vendor helper also writes unescaped passwords into a client CNF.
_mysql_passfile() {
  local value=${MYSQL_ROOT_PASSWORD:-}
  if [[ ${1:-} != --dont-use-mysql-root-password && -n $value ]]; then
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    printf '[client]\npassword="%s"\n' "$value"
  fi
}

# Replace only bootstrap statements; initialization/storage/upgrade remain vendor-owned.
docker_setup_db() {
  [[ -n ${MYSQL_ROOT_PASSWORD:-} && -z ${MYSQL_RANDOM_ROOT_PASSWORD:-} && -z ${MYSQL_ALLOW_EMPTY_PASSWORD:-} ]] \
    || { printf 'MySQL credential initialization requires the supplied password.\n' >&2; return 1; }
  if [[ -z ${MYSQL_INITDB_SKIP_TZINFO:-} ]]; then
    mysql_tzinfo_to_sql /usr/share/zoneinfo \
      | sed 's/Local time zone must be set--see zic manual page/FCTY/' \
      | docker_process_sql --dont-use-mysql-root-password --database=mysql
  fi
  local password root_create='' host database username user_password
  password=$(mysql_sql_literal "$MYSQL_ROOT_PASSWORD")
  if [[ -n ${MYSQL_ROOT_HOST:-} && $MYSQL_ROOT_HOST != localhost ]]; then
    host=$(mysql_sql_literal "$MYSQL_ROOT_HOST")
    root_create="CREATE USER 'root'@${host} IDENTIFIED BY ${password}; GRANT ALL ON *.* TO 'root'@${host} WITH GRANT OPTION;"
  fi
  # Scope escaping mode to this bootstrap session; preserve the server's policy.
  docker_process_sql --dont-use-mysql-root-password --database=mysql <<SQL
SET @@SESSION.sql_mode=REPLACE(@@SESSION.sql_mode, 'NO_BACKSLASH_ESCAPES', '');
SET autocommit=1;
SET @@SESSION.SQL_LOG_BIN=0;
ALTER USER 'root'@'localhost' IDENTIFIED BY ${password};
GRANT ALL ON *.* TO 'root'@'localhost' WITH GRANT OPTION;
FLUSH PRIVILEGES;
${root_create}
DROP DATABASE IF EXISTS test;
SQL
  if [[ -n ${MYSQL_DATABASE:-} ]]; then
    database=$(mysql_sql_identifier "$MYSQL_DATABASE")
    docker_process_sql --database=mysql <<<"CREATE DATABASE IF NOT EXISTS ${database};"
  fi
  if [[ -n ${MYSQL_USER:-} && -n ${MYSQL_PASSWORD:-} ]]; then
    username=$(mysql_sql_literal "$MYSQL_USER")
    user_password=$(mysql_sql_literal "$MYSQL_PASSWORD")
    docker_process_sql --database=mysql <<SQL
SET @@SESSION.sql_mode=REPLACE(@@SESSION.sql_mode, 'NO_BACKSLASH_ESCAPES', '');
CREATE USER ${username}@'%' IDENTIFIED BY ${user_password};
SQL
    if [[ -n ${MYSQL_DATABASE:-} ]]; then
      database=$(mysql_sql_identifier "${MYSQL_DATABASE//_/\\_}")
      docker_process_sql --database=mysql <<<"GRANT ALL ON ${database}.* TO ${username}@'%';"
    fi
  fi
}

credential_mysql_main() {
  if [[ $# = 0 ]]; then set -- mysqld; fi
  if [[ ${1:0:1} = - ]]; then set -- mysqld "$@"; fi
  if [[ ${1:-} = mysqld ]] && ! _mysql_want_help "$@"; then
    mysql_check_config "$@"
    docker_setup_env "$@"
    docker_create_db_directories "$@"
    # Re-enter this wrapper after dropping root so the safe helpers stay in effect.
    if [[ $(id -u) = 0 ]]; then exec gosu mysql bash "$0" "$@"; fi
  fi
  _main "$@"
}

if [[ ${BASH_SOURCE[0]} = "$0" ]]; then credential_mysql_main "$@"; fi
