#!/usr/bin/env bash
# Runs inside the MySQL image; no host MySQL client is needed.
set -euo pipefail
: "${GATEWAY_DATABASE_PASSWORD:?Set BISHENG_GATEWAY_DB_PASSWORD before enabling Gateway}"
mysql -h mysql -u root < /schema.sql
password=${GATEWAY_DATABASE_PASSWORD//\\/\\\\}
password=${password//\'/\'\'}
{
  printf "CREATE USER IF NOT EXISTS 'bisheng_gateway'@'%%' IDENTIFIED BY '%s';\n" "$password"
  printf "GRANT ALL PRIVILEGES ON bisheng_gateway.* TO 'bisheng_gateway'@'%%';\n"
} | mysql -h mysql -u root
