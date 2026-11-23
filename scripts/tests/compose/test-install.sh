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
# Direct `docker ps` means no running stack. Compose `ps` is the readiness probe,
# which must see one container or the installer waits until timeout.
if [[ "${1:-}" = compose && " $* " = *' ps '* ]]; then printf 'fixture-container\n'; fi
if [[ "${1:-}" = exec ]]; then printf 'java\n'; fi
if [[ "$*" = *'artifact publish'* ]]; then
  bundle=''; destination=''; previous=''
  for arg in "$@"; do
    [[ $previous = --bundle ]] && bundle=$arg
    [[ $previous = --destination ]] && destination=$arg
    previous=$arg
  done
  if [[ -n $bundle && -n $destination && -d $bundle ]]; then
    mkdir -p "$destination"
    cp -R "$bundle"/. "$destination"/
  fi
fi
if [[ "$*" = *'artifact capabilities'* ]]; then
  printf 'plaintext-native-v1\n'
elif [[ "$*" = *'--field version'* ]]; then
  printf '2\n'
elif [[ "$*" = *'es-info'* ]]; then
  printf 'configured\n'
fi
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
  # The copied installer still defines the fixed credential root. Command-boundary
  # cases must not create or lock that directory on the machine running the test.
  cat >> "${CASE_DIR}/lib/install-env.sh" <<EOF
credential_store_path() { printf '%s\n' '${CASE_ROOT}/credential-store'; }
EOF
  # Real verify needs Linux root, iptables, and a reviewed host CIDR list.
  # Record the mandatory call, then let the command-boundary checks continue.
  cat > "${CASE_DIR}/lib/runner-egress.sh" <<'EOF'
#!/usr/bin/env bash
printf 'egress\t%s\n' "${1:-}" >> "${INSTALL_TEST_LOG:-/dev/null}"
[[ "${1:-}" == verify ]]
EOF
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
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime ]] || fail 'Runtime is not enabled by default'
seen_secrets='|'
for key in BISHENG_RUNTIME_MANAGER_SECRET BISHENG_RUNTIME_CONTROL_SECRET BISHENG_RUNTIME_ENTRY_SECRET BISHENG_RUNTIME_EGRESS_SECRET BISHENG_APP_PROXY_HMAC_SECRET BISHENG_APP_OBO_SECRET BISHENG_RUNTIME_HOST_ISOLATION_SECRET SANDBOX_TOKEN; do
  value="$(env_get "${CASE_DIR}/.env" "$key")"
  [[ ${#value} = 64 ]] || fail 'Runtime secret missing'
  [[ "$seen_secrets" != *"|$value|"* ]] || fail 'Runtime identities share a secret'
  seen_secrets="${seen_secrets}${value}|"
  absent "${CASE_ROOT}/out" "$value"
done
[[ ${#seen_secrets} -gt 1 ]] || fail 'No runtime identities'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_RUNTIME_PAYLOAD_KEY)" =~ ^[A-Za-z0-9_-]{43}=$ ]] || fail 'Invalid Fernet key'
# Only the generated runtime identities and sandbox token may differ from the template.
runtime_keys='^(BISHENG_RUNTIME_MANAGER_SECRET|BISHENG_RUNTIME_CONTROL_SECRET|BISHENG_RUNTIME_ENTRY_SECRET|BISHENG_RUNTIME_EGRESS_SECRET|BISHENG_APP_PROXY_HMAC_SECRET|BISHENG_APP_OBO_SECRET|BISHENG_RUNTIME_HOST_ISOLATION_SECRET|BISHENG_RUNTIME_PAYLOAD_KEY|SANDBOX_TOKEN)='
cmp <(grep -Ev "$runtime_keys" "${SCRIPT_DIR}/.env.example") <(grep -Ev "$runtime_keys" "${CASE_DIR}/.env") || fail 'Default configuration was rewritten'
[[ -z "$(env_get "${CASE_DIR}/.env" BISHENG_SECRET_KEYS_FILE)" ]] || fail 'Structural check persisted a key path'
absent "${CASE_DIR}/.env" 'MINIO_ROOT_PASSWORD='
[[ "$(ls -l "${CASE_DIR}/.env" | awk '{print substr($1, 1, 10)}')" = -rw------- ]] || fail 'Unsafe .env permissions'
absent "${CASE_ROOT}/calls" $'login\t'
absent "${CASE_ROOT}/calls" $'pull\t'
absent "${CASE_ROOT}/calls" $'up\t'
absent "${CASE_ROOT}/calls" $'egress\tverify'
pass 'Prepare-only enables runtime with independent secrets, otherwise keeps the template, persists no credential placeholders, and starts nothing'

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
awk '/^egress\tverify$/ { egress = NR } /^login\t/ { login = NR } /pull\t/ { pull = NR } /up\t-d\t$/ { up = NR } END { exit !(egress && login > egress && pull > login && up > pull) }' "${CASE_ROOT}/calls" || fail 'Default deploy is not verified egress, then pull, then up -d'
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
contains "${CASE_ROOT}/err" 'CR镜像源登录失败'
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
failed
contains "${CASE_ROOT}/err" '尚未完成Gateway'
absent "${CASE_ROOT}/calls" $'up\t'
pass 'Gateway is refused before license handling until credential acceptance is finished'

new_case
saved_credentials
gateway
failed
contains "${CASE_ROOT}/err" '尚未完成Gateway'
absent "${CASE_ROOT}/calls" $'up\t'
[[ ! -f "${CASE_ROOT}/python-called" ]] || fail 'Host Python called'
pass 'Gateway deployment stops before account changes'

new_case
printf 'COMPOSE_PROFILES=gateway,app-runtime\nBISHENG_PRO=true\nBISHENG_GATEWAY_HMAC_SECRET=kept-secret\n' > "${CASE_DIR}/.env"
run_install --no-gateway --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime ]] || fail 'Other profiles lost'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_PRO)" = false ]] || fail 'Commercial flag remains enabled'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_NGINX_CONF_DIR)" = ./nginx/conf.d ]] || fail 'Direct routing not restored'
[[ "$(env_get "${CASE_DIR}/.env" BISHENG_GATEWAY_HMAC_SECRET)" = kept-secret ]] || fail 'Gateway credentials changed'
absent "${CASE_ROOT}/calls" $'down\t'
pass 'Disabling Gateway restores direct routing without deleting data or other profiles'

new_case
run_install --ft --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime,ft ]] || fail 'FT profile missing'
absent "${CASE_ROOT}/calls" $'pull\t'
absent "${CASE_ROOT}/calls" $'up\t'
env_set "${CASE_DIR}/.env" BISHENG_FT_IMAGE custom.example/ft:custom
cp "${CASE_DIR}/.env" "${CASE_ROOT}/before"
run_install --prepare-only
ok
cmp "${CASE_DIR}/.env" "${CASE_ROOT}/before" || fail 'FT settings changed on rerun'
pass 'FT opt-in persists without deploying in prepare-only or replacing custom images'

env_set "${CASE_DIR}/.env" COMPOSE_PROFILES app-runtime,ft,ft
run_install --ft --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime,ft ]] || fail 'Combined profiles lost or duplicated'
run_install --no-ft --prepare-only
ok
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = app-runtime ]] || fail 'Disabling FT lost other profiles'
absent "${CASE_ROOT}/calls" $'stop\t'
absent "${CASE_ROOT}/calls" $'down\t'
pass 'FT switches preserve app-runtime without stopping services'

new_case
printf 'COMPOSE_PROFILES=\nCUSTOM_SETTING=preserved\n' > "${CASE_DIR}/.env"
run_install --ft
failed
[[ "$(env_get "${CASE_DIR}/.env" COMPOSE_PROFILES)" = ft ]] || fail 'Legacy env cannot opt in'
contains "${CASE_DIR}/.env" 'CUSTOM_SETTING=preserved'
absent "${CASE_ROOT}/calls" $'up\t'
pass 'Existing env files can record FT, and deployment still stops without the base config'

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
