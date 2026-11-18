"""Host ES transitions persist intent before writes and keep failures paused."""

import os
import pty
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "mode,observation,phase,reset_ok",
    [
        ("enable", "DENIED", "FROZEN", True),
        ("enable", "READY", "FROZEN", True),
        ("enable", "DENIED", "FROZEN", False),
        ("retain", "KEEP", "FROZEN", True),
        ("enable", "READY", "PASSWORD_INTENT", True),
    ],
)
def test_native_reset_order_and_explicit_uncertain_retry(tmp_path, mode, observation, phase, reset_ok):
    script = tmp_path / "host.sh"
    script.write_text(r"""
set -euo pipefail
source "$ROOT/docker/lib/credential-es-migrate.sh"
credential_store=$FIXTURE
credential_sealed_migration_session=$FIXTURE
ENV_FILE=$FIXTURE/.env
KEY_FILE=$FIXTURE/key
COMPOSE=(compose_boundary)
die() { echo stopped >> "$FIXTURE/events"; exit 2; }
env_get() { echo owned-project; }
credential_sealed_migration_tool() {
  if [[ $* = *es-mode* ]]; then printf '%s' "$MODE"; else cat "$FIXTURE/phase"; fi
}
credential_es_tool() {
  case "$1" in
    es-export) echo '{}' ;;
    es-freeze) echo frozen >> "$FIXTURE/events" ;;
    es-observe) echo "$OBSERVATION" ;;
    es-intent) echo intent >> "$FIXTURE/events"; echo PASSWORD_INTENT > "$FIXTURE/phase" ;;
    es-persist) [[ $(cat "$FIXTURE/phase") = PASSWORD_INTENT ]]; echo persisted >> "$FIXTURE/events"; echo PASSWORD_SET > "$FIXTURE/phase" ;;
    es-verify) echo verified >> "$FIXTURE/events" ;;
    seal-stream) cat >/dev/null; echo sealed-log >> "$FIXTURE/events" ;;
    *) exit 3 ;;
  esac
}
compose_boundary() { echo compose >> "$FIXTURE/events"; }
compose() { echo owned-es-container; }
docker() {
  if [[ $* = *'/proc/1/comm'* ]]; then echo java; return; fi
  [[ $(cat "$FIXTURE/phase") = PASSWORD_INTENT ]]
  echo reset >> "$FIXTURE/events"
  [[ $RESET_OK = true ]]
}
credential_es_run
""")
    (tmp_path / "phase").write_text(phase)
    environment = {
        **os.environ,
        "ROOT": str(ROOT),
        "FIXTURE": str(tmp_path),
        "MODE": mode,
        "OBSERVATION": observation,
        "RESET_OK": str(reset_ok).lower(),
    }
    if phase == "PASSWORD_INTENT":
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            ["bash", str(script)], env=environment, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        os.close(slave)
        try:
            os.write(master, b"1\nyes\n")
            output, errors = proc.communicate(timeout=10)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        code = proc.returncode
    else:
        completed = subprocess.run(["bash", str(script)], env=environment, capture_output=True, timeout=10)
        code, errors = completed.returncode, completed.stderr
    events = (tmp_path / "events").read_text().splitlines()
    if reset_ok:
        assert code == 0, errors.decode()
        assert events[-1] == "verified"
        if mode == "enable":
            assert events.index("intent") < events.index("persisted") < events.index("verified")
    else:
        assert code != 0
        assert "verified" not in events and "persisted" not in events
    if observation == "DENIED":
        assert events.index("intent") < events.index("reset")
    else:
        assert "reset" not in events
    if mode == "retain":
        assert "intent" not in events and "persisted" not in events


@pytest.mark.parametrize("mode", ["enable", "retain"])
def test_es_preflight_for_unauthenticated_modes_skips_security_authenticate(tmp_path, mode):
    script = r"""
set -euo pipefail
SCRIPT_DIR=$1/docker
WORK=$2
source "$SCRIPT_DIR/lib/install-env.sh"
source "$SCRIPT_DIR/lib/credential-es-migrate.sh"
ENV_FILE=$WORK/.env
KEY_FILE=$WORK/key
image=fixture-backend
credential_sealed_migration_session=$WORK/session
die() { printf '%s\n' "$*" >&2; exit 2; }
printf 'BISHENG_NETWORK_NAME=bisheng-network\n' > "$ENV_FILE"
printf '{}' > "$KEY_FILE"
mkdir -p "$credential_sealed_migration_session"
credential_sealed_migration_tool() {
  case "$*" in
    *es-mode*) printf '%s' "$MODE" ;;
    *source*) printf '%s' "$WORK/source-bundle" ;;
    *es-phase*) printf PREPARED ;;
    *) exit 3 ;;
  esac
}
bash() {
  if [[ $1 = "$SCRIPT_DIR/credentials.sh" ]]; then
    shift
    local component=""
    while [[ $# -gt 0 ]]; do
      case "$1" in --component) component=$2; shift 2 ;; *) shift ;; esac
    done
    [[ -n $component ]] || { echo 'full online check must not run for enable/retain' >&2; exit 4; }
    printf '%s\n' "$component" >> "$WORK/checked"
    return 0
  fi
  command bash "$@"
}
docker() {
  printf '%s\n' "$*" > "$WORK/docker-args"
  return 0
}
credential_es_preflight
[[ $(tr '\n' ' ' < "$WORK/checked") = 'mysql redis minio milvus ' ]]
grep -F 'elasticsearch:9200' "$WORK/docker-args"
"""
    result = subprocess.run(
        ["bash", "-c", script, "preflight-test", str(ROOT), str(tmp_path)],
        env={**os.environ, "MODE": mode},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode() + result.stdout.decode()
