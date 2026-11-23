#!/usr/bin/env bash
# Installer-only control-plane token generation. Never print the token.
sandbox_initialize_token() {
  local value
  value="$(env_get "$ENV_FILE" SANDBOX_TOKEN)"
  if [[ -z "$value" || "$value" = bisheng-sandbox-local || ${#value} -lt 48 ]]; then
    value="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
    [[ ${#value} -eq 64 && "$value" =~ ^[0-9a-f]+$ ]] || die '无法生成隔离执行器认证密钥'
    env_set "$ENV_FILE" SANDBOX_TOKEN "$value"
  fi
}
