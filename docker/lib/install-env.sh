#!/usr/bin/env bash
# Shared deployment helpers. Only this checked-in file is sourced, never .env.

env_get() { awk -v MODE=get -v KEY="$2" -f "${SCRIPT_DIR}/lib/env.awk" "$1"; }

env_set() {
  local file="$1" key="$2" value="$3" temporary
  case "$value" in
    *$'\n'*|*$'\r'*) die "配置项不能包含换行：${key}" ;;
  esac
  temporary="$(mktemp "${file}.XXXXXX")"
  if BISHENG_ENV_VALUE="$value" awk -v MODE=set -v KEY="$key" \
      -f "${SCRIPT_DIR}/lib/env.awk" "$file" > "$temporary"; then
    chmod 600 "$temporary"
    mv "$temporary" "$file"
  else
    rm -f "$temporary"
    die "无法更新配置项：${key}"
  fi
}

set_gateway_profile() {
  local profiles="$1" enabled="$2"
  awk -v profiles="$profiles" -v enabled="$enabled" 'BEGIN {
    count = split(profiles, items, /[[:space:],]+/)
    for (i = 1; i <= count; i++) {
      item = items[i]
      if (item != "" && item != "gateway" && !seen[item]++) result = result (result ? "," : "") item
    }
    if (enabled == "true") result = result (result ? "," : "") "gateway"
    printf "%s", result
  }'
}
