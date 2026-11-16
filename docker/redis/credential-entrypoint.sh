#!/bin/sh
# Preserve explicitly granted secret-file groups when dropping root privileges.
set -eu
vendor=/usr/local/bin/docker-entrypoint.sh
if [ "$#" -gt 0 ] && { [ "${1#-}" != "$1" ] || [ "${1%.conf}" != "$1" ]; }; then
  set -- redis-server "$@"
fi
if [ "${1:-}" = redis-server ] && [ "$(id -u)" = 0 ]; then
  command -v setpriv >/dev/null 2>&1 || { printf 'Redis credential startup requires setpriv.\n' >&2; exit 2; }
  groups=$(id -G | tr ' ' ',')
  # Match the vendor's data ownership setup, then retain Docker group_add.
  find . \! -user redis -exec chown redis '{}' +
  exec setpriv --reuid redis --regid redis --groups "$groups" "$vendor" "$@"
fi
exec "$vendor" "$@"
