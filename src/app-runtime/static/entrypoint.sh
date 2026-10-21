#!/bin/sh
set -eu
port=${PORT:-8080}
case "$port" in ''|*[!0-9]*) exit 64;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ]
sed "s/__PORT__/$port/g" /opt/bisheng/nginx.conf >/tmp/nginx.conf
if [ "$1" = nginx ]; then exec "$@" -c /tmp/nginx.conf; fi
exec "$@"
