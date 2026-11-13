#!/bin/sh
set -eu
# redis-cli receives auth only in this short-lived process, never argv/Compose.
REDISCLI_AUTH=$(cat /run/secrets/redis.password)
export REDISCLI_AUTH
[ "$(redis-cli --no-auth-warning ping 2>/dev/null)" = PONG ]
