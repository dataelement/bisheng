#!/usr/bin/env bash
# Record Compose calls; never start the application stack in this test.
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../docker" && pwd)"
source "${SCRIPT_DIR}/lib/install-env.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/bisheng-install-tests.XXXXXX")"
trap 'rm -rf -- "$TEST_ROOT"' EXIT
count=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
die() { fail "$@"; }
pass() { count=$((count + 1)); printf 'PASS: %s\n' "$*"; }
contains() { grep -Fq -- "$2" "$1" || fail "Missing expected text in $1"; }
absent() { ! grep -Fq -- "$2" "$1" || fail "Unexpected text in $1"; }
new_case() {
  CASE_ROOT="$(mktemp -d "${TEST_ROOT}/case.XXXXXX")"
  CASE_DIR="${CASE_ROOT}/docker"
  mkdir -p "$CASE_DIR" "${CASE_ROOT}/bin"
  for item in install.sh credentials.sh .env.example docker-compose.yml lib gateway nginx; do cp -R "${SCRIPT_DIR}/${item}" "$CASE_DIR/"; done
  printf 'fixture-license\n' > "${CASE_ROOT}/license"
  cat > "${CASE_ROOT}/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\t' "$@" >> "$INSTALL_TEST_LOG"; printf '\n' >> "$INSTALL_TEST_LOG"
if [[ "$*" = 'compose version' && "${INSTALL_TEST_LEGACY:-}" = yes ]]; then exit 1; fi
if [[ "${1:-}" = container ]]; then exit 1; fi
if [[ "${1:-}" = inspect ]]; then printf 'healthy\n'; fi
if [[ " $* " = *' ps '* ]]; then printf 'fixture-container\n'; fi
if [[ "${1:-}" = login ]]; then
  IFS= read -r supplied_password
  [[ "$supplied_password" = "${INSTALL_TEST_EXPECTED_PASSWORD:-dataelem}" ]] || exit 18
  [[ "${INSTALL_TEST_FAIL:-}" != login ]] || exit 19
fi
if [[ "${INSTALL_TEST_FAIL:-}" = pull && " $* " = *' pull '* ]]; then exit 17; fi
DOCKER
  cp "${CASE_ROOT}/bin/docker" "${CASE_ROOT}/bin/docker-compose"
  cat > "${CASE_ROOT}/bin/python" <<'BLOCK'
#!/usr/bin/env bash
printf 'Python called\n' > "$INSTALL_TEST_PYTHON"
exit 99
BLOCK
  cp "${CASE_ROOT}/bin/python" "${CASE_ROOT}/bin/python3"
  chmod +x "${CASE_ROOT}/bin/"*
}
# Registry/Gateway contract fixtures start from saved deployment metadata.
# Real no-argument bootstrap and crypto are covered by test_credential_one_command.py.
saved_credentials() {
  [[ -f "${CASE_DIR}/.env" ]] || cp "${CASE_DIR}/.env.example" "${CASE_DIR}/.env"
  mkdir -p "${CASE_ROOT}/bundle"
  printf '{"version": 1, "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n' > "${CASE_ROOT}/bundle/manifest.json"
  printf '{}\n' > "${CASE_ROOT}/keys.json"
  env_set "${CASE_DIR}/.env" BISHENG_CREDENTIALS_DIR "${CASE_ROOT}/bundle"
  env_set "${CASE_DIR}/.env" BISHENG_SECRET_KEYS_FILE "${CASE_ROOT}/keys.json"
  env_set "${CASE_DIR}/.env" BISHENG_CREDENTIAL_REVISION aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
}
run_install() {
  : > "${CASE_ROOT}/calls"
  if PATH="${CASE_ROOT}/bin:$PATH" INSTALL_TEST_LOG="${CASE_ROOT}/calls" \
    INSTALL_TEST_PYTHON="${CASE_ROOT}/python-called" INSTALL_TEST_FAIL="${TEST_FAIL:-}" \
    INSTALL_TEST_LEGACY="${TEST_LEGACY:-}" INSTALL_TEST_EXPECTED_PASSWORD="${TEST_PASSWORD:-dataelem}" \
    /bin/bash "${CASE_DIR}/install.sh" "$@" </dev/null >"${CASE_ROOT}/out" 2>"${CASE_ROOT}/err"; then result=0; else result=$?; fi
}
ok() { [[ $result = 0 ]] || { cat "${CASE_ROOT}/err" >&2; fail 'Installer failed'; }; }
failed() { [[ $result != 0 ]] || fail 'Installer should have failed'; }
gateway() { run_install --gateway --license-file "${CASE_ROOT}/license" --public-url https://example.invalid "$@"; }

new_case
run_install --prepare-only
ok
cmp "${SCRIPT_DIR}/.env.example" "${CASE_DIR}/.env" || fail 'Default configuration was rewritten'
[[ -z "$(env_get "${CASE_DIR}/.env" BISHENG_SECRET_KEYS_FILE)" ]] || fail 'Structural check persisted a key path'
absent "${CASE_DIR}/.env" 'MINIO_ROOT_PASSWORD='
[[ "$(ls -l "${CASE_DIR}/.env" | awk '{print substr($1, 1, 10)}')" = -rw------- ]] || fail 'Unsafe .env permissions'
absent "${CASE_ROOT}/calls" $'login\t'
absent "${CASE_ROOT}/calls" $'pull\t'
absent "${CASE_ROOT}/calls" $'up\t'
pass 'Prepare-only copies the template exactly, persists no secret placeholders, and starts nothing'

env_set "${CASE_DIR}/.env" MINIO_ROOT_PASSWORD existing-password
env_set "${CASE_DIR}/.env" BISHENG_BACKEND_IMAGE custom.example/backend:custom
printf 'CUSTOM_SETTING=preserved\n' >> "${CASE_DIR}/.env"
cp "${CASE_DIR}/.env" "${CASE_ROOT}/before"
run_install --prepare-only
ok
cmp "${CASE_DIR}/.env" "${CASE_ROOT}/before" || fail 'Existing .env changed'
pass 'Existing .env, credentials, image addresses and unknown settings remain byte-identical'

new_case
saved_credentials
run_install
ok
awk '/^login\t/ { login = NR } /pull\t/ { pull = NR } /up\t-d\t$/ { up = NR } END { exit !(login && pull > login && up > pull) }' "${CASE_ROOT}/calls" || fail 'Default deploy is not pull then up -d'
absent "${CASE_ROOT}/calls" $'exec\t'
absent "${CASE_ROOT}/calls" $'--wait\t'
[[ ! -f "${CASE_ROOT}/python-called" ]] || fail 'Host Python called'
contains "${CASE_ROOT}/calls" $'login\tcr.dataelem.com\t--username\tdocker\t--password-stdin\t'
absent "${CASE_ROOT}/calls" $'\tdataelem\t'
absent "${CASE_ROOT}/out" dataelem
absent "${CASE_ROOT}/err" dataelem
pass 'Ordinary deployment logs in via stdin before pull and up -d, without Python'

new_case
run_install --prepare-only
ok
env_set "${CASE_DIR}/.env" CR_REGISTRY_USERNAME custom-user
env_set "${CASE_DIR}/.env" CR_REGISTRY_PASSWORD 'custom-password$literal'
saved_credentials
TEST_PASSWORD='custom-password$literal' run_install
ok
contains "${CASE_ROOT}/calls" $'--username\tcustom-user\t--password-stdin\t'
absent "${CASE_ROOT}/calls" 'custom-password$literal'
absent "${CASE_ROOT}/out" 'custom-password$literal'
absent "${CASE_ROOT}/err" 'custom-password$literal'
pass 'Existing registry credentials override defaults without shell evaluation or argument exposure'

new_case
TEST_FAIL=login run_install
failed
absent "${CASE_ROOT}/calls" $'pull\t'
absent "${CASE_ROOT}/calls" $'up\t'
contains "${CASE_ROOT}/err" 'CR 镜像源登录失败'
pass 'Failed registry login stops before pull or service changes'

new_case
printf 'COMPOSE_PROFILES=\n' > "${CASE_DIR}/.env"
saved_credentials
run_install
ok
contains "${CASE_ROOT}/calls" $'--username\tdocker\t--password-stdin\t'
pass 'Existing env files without registry settings use public defaults'

new_case
saved_credentials
TEST_FAIL=pull run_install
failed
absent "${CASE_ROOT}/calls" $'up\t'
absent "${CASE_ROOT}/calls" $'build\t'
contains "${CASE_ROOT}/err" '镜像'
pass 'Missing images stop before any service changes and never build source'

new_case
run_install --gateway --public-url https://example.invalid --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" != *gateway* ]] || fail 'Gateway enabled without a file'
contains "${CASE_ROOT}/out" '跳过 Gateway'
pass 'Missing license file skips Gateway instead of accepting direct license text'

env_set "${CASE_DIR}/.env" BISHENG_GATEWAY_LICENSE cached-license-text
env_set "${CASE_DIR}/.env" COMPOSE_PROFILES gateway
run_install --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" != *gateway* ]] || fail 'Cached license bypassed file requirement'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_PRO)" = false ]] || fail 'Commercial flag remains enabled'
run_install --gateway --license-file "${CASE_ROOT}/missing-file" --prepare-only
failed
absent "${CASE_ROOT}/calls" $'up\t'
pass 'A cached license does not enable Gateway without a file; an unreadable file fails explicitly'

new_case
saved_credentials
gateway
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = gateway ]] || fail 'Gateway profile missing'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_PRO)" = true ]] || fail 'Commercial flag missing'
for key in BISHENG_GATEWAY_HMAC_SECRET BISHENG_GATEWAY_DB_PASSWORD; do
  secret="$(env_get "${CASE_DIR}/.env" "$key")"
  [[ ${#secret} = 64 ]] || fail 'Gateway secret not independently generated'
  absent "${CASE_ROOT}/out" "$secret"
  absent "${CASE_ROOT}/err" "$secret"
done
awk '/pull\t/ { pull = NR } /up\t-d\t--no-deps\t--force-recreate\tbackend/ { backend = NR } /up\t-d\t$/ { all = NR } END { exit !(pull && backend > pull && all > backend) }' "${CASE_ROOT}/calls" || fail 'Wrong Gateway start order'
absent "${CASE_ROOT}/calls" $'exec\t'
[[ ! -f "${CASE_ROOT}/python-called" ]] || fail 'Host Python called'
pass 'Gateway uses Compose dependencies for initialization and preserves independent generated credentials'

target="$(env_get "${CASE_DIR}/.env" BISHENG_NGINX_CONF_DIR)"
contains "${target}/default.conf" 'proxy_pass http://gateway:8080;'
contains "${target}/websocket.conf" 'proxy_pass http://gateway:8080;'
contains "${target}/default.conf" 'proxy_pass http://minio:9000;'
contains "${target}/default.conf" 'set $bisheng_app_proxy http://app-proxy:8090;'
awk '/location \^~ \/internal\// { internal=1 } internal && /proxy_pass http:\/\/backend_server;/ { direct=1 } END { exit !direct }' "${target}/default.conf" || fail 'Internal routing changed'
cmp "${SCRIPT_DIR}/nginx/conf.d/default.conf" "${CASE_DIR}/nginx/conf.d/default.conf" || fail 'Source Nginx changed'
pass 'Gateway changes browser HTTP/WebSocket targets while preserving internal, app and MinIO routes'

secret="$(env_get "${CASE_DIR}/.env" BISHENG_GATEWAY_HMAC_SECRET)"
run_install --gateway --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_GATEWAY_HMAC_SECRET)" = "$secret" ]] || fail 'Gateway secret changed'
absent "${CASE_ROOT}/calls" $'pull\t'
pass 'Repeated Gateway configuration reuses the supplied license and credentials'

env_set "${CASE_DIR}/.env" COMPOSE_PROFILES gateway,app-runtime
run_install --no-gateway --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime ]] || fail 'Other profiles lost'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_PRO)" = false ]] || fail 'Commercial flag remains enabled'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_NGINX_CONF_DIR)" = ./nginx/conf.d ]] || fail 'Direct routing not restored'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_GATEWAY_HMAC_SECRET)" = "$secret" ]] || fail 'Gateway credentials changed'
absent "${CASE_ROOT}/calls" $'down\t'
pass 'Disabling Gateway restores direct routing without deleting data or other profiles'

new_case
TEST_LEGACY=yes run_install --prepare-only
ok
contains "${CASE_ROOT}/calls" $'config\t--quiet\t'
pass 'Both docker compose and standalone docker-compose command names are supported'

new_case
printf 'CUSTOM_SETTING=$(touch "%s")\n' "${CASE_ROOT}/must-not-exist" > "${CASE_DIR}/.env"
printf 'COMPOSE_PROFILES=\n' >> "${CASE_DIR}/.env"
run_install --prepare-only
ok
[[ ! -f "${CASE_ROOT}/must-not-exist" ]] || fail 'Dotenv executed'
for value in "quote'and\"double" 'trailing\' 'slash\and$literal${VALUE}'; do
  env_set "${CASE_DIR}/.env" ROUNDTRIP "$value"
  [[ "$(env_get "${CASE_DIR}/.env" ROUNDTRIP)" = "$value" ]] || fail 'Dotenv literal changed'
done
pass 'Dotenv content stays data and literal special characters round-trip'

printf '\n%s installer checks passed.\n' "$count"
