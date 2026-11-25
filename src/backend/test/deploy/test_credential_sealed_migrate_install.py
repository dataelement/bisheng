"""Legacy adoption captures passwords through pipes rather than host files."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from bisheng.core.config.credential_bundle import prepare_bundle
from test.core.test_credential_sealed_bundle import sealed_deployment as _sealed_deployment

# Re-export the fixture without shadowing an imported binding in test parameters.
sealed_deployment = _sealed_deployment

ROOT = Path(__file__).resolve().parents[4]


def test_legacy_capture_encrypts_source_and_runtime_environment(sealed_deployment, tmp_path):
    args, values = sealed_deployment
    base = prepare_bundle(**args)
    store = tmp_path / "store"
    (store / "keys").mkdir(parents=True)
    (store / "revisions").mkdir()
    env = tmp_path / ".env"
    env.write_text("COMPOSE_PROJECT_NAME=legacy-fixture\n")
    env.chmod(0o600)
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(["LEGACY_PASSWORD=legacy-environment-secret-unique"]))
    script = tmp_path / "adopt.sh"
    lines = ["set -euo pipefail", "umask 077"]
    for name in ["install-env.sh", "credential-install.sh", "credential-migrate.sh"]:
        lines.append("source " + shlex.quote(str(ROOT / "docker/lib" / name)))
    for name, value in {
        "SCRIPT_DIR": ROOT / "docker",
        "credential_store": store,
        "ENV_FILE": env,
        "volume": tmp_path,
        "OLD_KEY": args["key_file"],
        "OLD_CONFIG": base / "config.yaml",
        "OLD_ENV": runtime,
    }.items():
        lines.append(name + "=" + shlex.quote(str(value)))
    lines += [
        "credential_deployment_id=legacy-test",
        "BISHENG_ALLOW_CREDENTIAL_MIGRATION=yes",
        'die() { printf "%s\\n" "$*" >&2; exit 2; }',
        "credential_tool() { "
        + shlex.quote(sys.executable)
        + ' -m bisheng.core.config.credential_tool "$@" --deployment-id "$credential_deployment_id"; }',
        'docker() { case "$1" in ps) echo legacy-backend ;; inspect) cat "$OLD_ENV" ;; exec) if [[ "$*" = *"import ast"* ]]; then cat "$OLD_KEY"; else cat "$OLD_CONFIG"; fi ;; *) return 1 ;; esac; }',
        "credential_prepare_legacy",
    ]
    script.write_text("\n".join(lines))
    result = subprocess.run(
        ["bash", str(script)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src/backend")},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    for name in ["source.yaml", "runtime-env.json"]:
        raw = (store / "migration" / name).read_bytes()
        assert json.loads(raw)["format"] == "bisheng.credentials.v2"
        assert b"legacy-environment-secret-unique" not in raw
        assert not any(v.encode() in raw for v in values.values())


@pytest.mark.parametrize(
    "health,binding_ok,cleanup_only,success",
    [
        ("healthy", "yes", "false", True),
        ("unhealthy", "yes", "false", False),
        ("healthy", "no", "false", False),
        ("healthy", "yes", "true", True),
    ],
)
def test_conversion_cleanup_requires_healthy_application_and_no_old_bindings(
    tmp_path, health, binding_ok, cleanup_only, success
):
    script = r"""
set -euo pipefail
source "$1/docker/lib/credential-runtime.sh"
source "$1/docker/lib/credential-sealed-migrate.sh"
credential_store=$2
credential_sealed_migration_session=$2/session
credential_sealed_cleanup_only=$cleanup_only
touch "$2/sealed-migration.active"
die() { exit 2; }
credential_migration_consent() { :; }
credential_stop_legacy_apps() { echo stop >> "$credential_store/events"; }
credential_start_native() { echo native >> "$credential_store/events"; }
credential_check_online() { echo online >> "$credential_store/events"; }
compose() {
  case "$1" in
    up) echo applications >> "$credential_store/events" ;;
    ps) echo fixture-backend ;;
  esac
}
docker() {
  if [[ $* = *'.State.Health'* ]]; then printf '%s\n' "$health";
  else printf '%s\n' "$credential_store/new-ciphertext"; fi
}
credential_sealed_migration_tool() {
  echo "$1" >> "$credential_store/events"
  if [[ $1 = migrate-info ]]; then
    if [[ $cleanup_only = true ]]; then printf COMPLETE; else printf VERIFIED; fi
  fi
  if [[ $1 = migrate-bindings ]]; then cat >/dev/null; [[ $binding_ok = yes ]]; fi
}
credential_sealed_migration_run
"""
    result = subprocess.run(
        ["bash", "-c", script, "migration-test", str(ROOT), str(tmp_path)],
        env={**os.environ, "health": health, "binding_ok": binding_ok, "cleanup_only": cleanup_only},
        capture_output=True,
        timeout=15,
    )
    events = (tmp_path / "events").read_text().splitlines()
    assert (result.returncode == 0) is success
    if success:
        expected = (
            ["online", "migrate-bindings", "migrate-info", "migrate-clean"]
            if cleanup_only == "true"
            else ["stop", "native", "applications", "migrate-bindings", "migrate-info", "migrate-mark", "migrate-clean"]
        )
        assert events == expected
        assert not (tmp_path / "sealed-migration.active").exists()
    else:
        assert "migrate-mark" not in events and "migrate-clean" not in events
        assert (tmp_path / "sealed-migration.active").exists()


def test_pre_activation_service_discovery_does_not_call_compose(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COMPOSE_PROJECT_NAME=bisheng\n")
    env.chmod(0o600)
    script = r"""
set -euo pipefail
SCRIPT_DIR=$1/docker
source "$SCRIPT_DIR/lib/install-env.sh"
source "$SCRIPT_DIR/lib/credential-runtime.sh"
ENV_FILE=$2/.env
WORK=$2
die() { printf '%s\n' "$*" >&2; exit 2; }
compose() { die 'compose must not interpolate before credential activation'; }
docker() {
  printf '%s\n' "$*" > "$WORK/docker-args"
  printf 'redis-container\n'
}
ids=$(credential_compose_service_ids redis)
[[ $ids = redis-container ]]
grep -F 'label=com.docker.compose.project=bisheng' "$WORK/docker-args"
grep -F 'label=com.docker.compose.service=redis' "$WORK/docker-args"
"""
    result = subprocess.run(
        ["bash", "-c", script, "discovery-test", str(ROOT), str(tmp_path)],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_sealed_redis_seed_reads_running_container_without_compose(tmp_path):
    store = tmp_path / "store"
    (store / "revisions").mkdir(parents=True)
    (store / "keys").mkdir()
    env = tmp_path / ".env"
    env.write_text("COMPOSE_PROJECT_NAME=bisheng\nBISHENG_NETWORK_NAME=bisheng-network\n")
    env.chmod(0o600)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}")
    (tmp_path / "keys.json").write_text("{}")
    script = r"""
set -euo pipefail
SCRIPT_DIR=$1/docker
source "$SCRIPT_DIR/lib/install-env.sh"
source "$SCRIPT_DIR/lib/credential-runtime.sh"
ENV_FILE=$2/.env
credential_store=$2/store
BUNDLE=$2/bundle
KEY_FILE=$2/keys.json
image=fixture-backend
credential_sealed_migration_session=$2/session
mkdir -p "$credential_sealed_migration_session"
die() { printf '%s\n' "$*" >&2; exit 2; }
compose() { die 'compose must not interpolate before credential activation'; }
bash() {
  if [[ $1 = "$SCRIPT_DIR/credentials.sh" ]]; then
    [[ $* = *'--role redis --preserve-redis-acl'* ]]
    [[ $* = *'--network bisheng-network'* ]]
    out_dir=
    shift
    while [[ $# -gt 0 ]]; do
      case "$1" in --out-dir) out_dir=$2; shift 2 ;; *) shift ;; esac
    done
    mkdir -p "$out_dir"
    [[ $(cat) = 'bind 0.0.0.0' ]]
    printf seeded > "$out_dir/seed-fixture"
    return 0
  fi
  command bash "$@"
}
docker() {
  case "$1" in
    ps) printf 'running-redis\n' ;;
    exec) [[ $* = 'exec running-redis cat /etc/redis.conf' ]]; printf 'bind 0.0.0.0\n' ;;
    *) return 1 ;;
  esac
}
credential_tool() {
  if [[ $1 = artifact && $2 = info ]]; then printf 'redis\n'; return 0; fi
  if [[ $1 = artifact && $2 = role-keys ]]; then die 'option C does not derive role keys'; fi
  die "unexpected credential_tool $*"
}
seed_capture=$2/published-fixture
credential_runtime_publish_bundle() {
  [[ $(cat "$BUNDLE/seed-fixture") = seeded ]]
  printf '%s' "$BUNDLE" > "$seed_capture"
}
credential_runtime_seed_bundle
[[ $(cat "$seed_capture") = "$BUNDLE" ]]
[[ $BUNDLE = "$credential_store/revisions/seed."*/bundle ]]
[[ $(cat "$BUNDLE/seed-fixture") = seeded ]]
"""
    result = subprocess.run(
        ["bash", "-c", script, "seed-test", str(ROOT), str(tmp_path)],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode() + result.stdout.decode()
