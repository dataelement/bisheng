#!/bin/sh
set -eu
exec mysql --defaults-extra-file=/run/secrets/mysql-client.cnf --host=127.0.0.1 --connect-timeout=5 --batch --skip-column-names --execute='SELECT 1'
