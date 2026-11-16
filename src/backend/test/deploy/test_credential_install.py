"""Exercise the host wrapper with a Docker boundary double, without host Python."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("output_first", [False, True])
def test_wrapper_shared_input_output_parent_has_one_writable_mount(tmp_path, output_first):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    inputs = tmp_path / "inputs.yaml"
    inputs.write_text("version: 1\n")
    groups = [["--inputs", str(inputs)], ["--out-dir", str(tmp_path / "bundle")]]
    if output_first:
        groups.reverse()
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "docker/credentials.sh"),
            "--image",
            "local:test",
            "prepare",
            *[arg for group in groups for arg in group],
        ],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    specs = [line for line in log.read_text().splitlines() if line.startswith("type=bind,")]
    assert specs == [f"type=bind,source={tmp_path},target={tmp_path}"]


def test_wrapper_has_no_host_python_or_secret_environment(tmp_path):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    key = tmp_path / "keys.json"
    key.write_text("{}")
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "docker/credentials.sh"),
            "--image",
            "local:test",
            "check",
            "--bundle",
            str(tmp_path),
            "--key-file",
            str(key),
        ],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    args = log.read_text()
    assert "--pull=never" in args and "--network\nnone" in args
    assert "--read-only" in args and "readonly" in args
    assert "bisheng.core.config.credential_tool" in args
    assert "--env-file" not in args and "MYSQL_PWD" not in args


def test_online_requires_explicit_network():
    result = subprocess.run(
        ["bash", str(ROOT / "docker/credentials.sh"), "--image", "local:test", "check", "--online"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "network" in result.stderr


def test_installer_preparation_precedes_service_start():
    text = (ROOT / "docker/install.sh").read_text()
    assert "credentials.sh" in (ROOT / "docker/lib/credential-install.sh").read_text()
    assert text.index("credential_setup\n") < text.index("compose up -d")
    helper = (ROOT / "docker/lib/credential-install.sh").read_text()
    assert "check --bundle" in helper and "--enforce" in helper
    assert "credential_retire_unusable_policy_bundle" in helper
    assert "MINIO_ROOT_PASSWORD" not in text


def test_deployment_env_template_is_unambiguous():
    from bisheng.core.config.credential_loader import read_env_file

    values = read_env_file(ROOT / "docker/.env.example")
    assert values["BISHENG_CREDENTIALS_DIR"] == ""
    assert values["BISHENG_SECRET_KEYS_FILE"] == ""
    assert "MINIO_ROOT_PASSWORD" not in values
    assert "BISHENG_GATEWAY_HMAC_SECRET" in values
    text = (ROOT / "docker/install.sh").read_text()
    assert "--no-deps --force-recreate backend backend_worker" in text


def test_prepare_only_does_not_pull_login_or_start_services(tmp_path):
    import shutil

    deployment = tmp_path / "docker"
    deployment.mkdir()
    for name in ("install.sh", "credentials.sh", ".env.example"):
        shutil.copyfile(ROOT / "docker" / name, deployment / name)
    shutil.copytree(ROOT / "docker/lib", deployment / "lib")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "docker-commands"
    fake = binaries / "docker"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CAPTURE"\nexit 0\n')
    fake.chmod(0o700)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text('{"version": 1, "revision": "' + "a" * 32 + '"}')
    key = tmp_path / "keys.json"
    key.write_text("{}")
    key.chmod(0o600)
    result = subprocess.run(
        [
            "bash",
            str(deployment / "install.sh"),
            "--prepare-only",
            "--bundle",
            str(bundle),
            "--key-file",
            str(key),
            "--revision",
            "a" * 32,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{binaries}:/usr/bin:/bin", "CAPTURE": str(log)},
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert any("credential_tool check" in line for line in calls)
    assert not any(line.startswith(("login ", "pull ")) or " up " in line for line in calls)
    assert key.stat().st_mode & 0o777 == 0o600  # installer never relaxes the external key


def test_only_migration_policy_verification_grants_bundle_write_access(tmp_path):
    import json

    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = binaries / "docker"
    capture = tmp_path / "mounts.json"
    fake.write_text(
        '#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\nif sys.argv[1]=="run":Path(os.environ["CAPTURE"]).write_text(json.dumps(sys.argv[2:]))\n'
    )
    fake.chmod(0o700)
    bundle, session = tmp_path / "bundle", tmp_path / "session"
    bundle.mkdir()
    session.mkdir()
    key = tmp_path / "key.json"
    key.write_text("fixture")
    key.chmod(0o600)
    environment = {**os.environ, "PATH": f"{binaries}:/usr/bin:/bin", "CAPTURE": str(capture)}
    # The Docker boundary records mounts; real crypto/state behavior has separate tests.
    for action, readonly in [("info", True), ("migrate-verify", False)]:
        command = [
            "bash",
            str(ROOT / "docker/credentials.sh"),
            "--image",
            "fixture",
            "artifact",
            action,
            "--bundle",
            str(bundle),
            "--session-dir",
            str(session),
            "--key-file",
            str(key),
            "--deployment-id",
            "d" * 32,
        ]
        result = subprocess.run(command, env=environment, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr.decode()
        arguments = json.loads(capture.read_text())
        mounts = [arguments[i + 1] for i, item in enumerate(arguments) if item == "--mount"]
        assert f"type=bind,source={bundle},target={bundle}" + (",readonly" if readonly else "") in mounts
        assert f"type=bind,source={key},target={key},readonly" in mounts
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    (store / "deployment.id").write_text("d" * 32)
    command = [
        "bash",
        str(ROOT / "docker/credentials.sh"),
        "--image",
        "fixture",
        "artifact",
        "migrate-clean",
        "--policy-root",
        str(store),
        "--session-dir",
        str(session),
        "--key-file",
        str(key),
        "--deployment-id",
        "d" * 32,
    ]
    result = subprocess.run(command, env=environment, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    arguments = json.loads(capture.read_text())
    mounts = [arguments[i + 1] for i, item in enumerate(arguments) if item == "--mount"]
    assert f"type=bind,source={store},target={store}" in mounts


def test_wrapper_mounts_journal_source_outside_cli_paths(tmp_path):
    """Adopt/resume sessions may point source at another tree; the CLI never lists it."""
    import json

    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = binaries / "docker"
    capture = tmp_path / "mounts.json"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        'if sys.argv[1] == "run":\n'
        '    Path(os.environ["CAPTURE"]).write_text(json.dumps(sys.argv[2:]))\n'
        'elif sys.argv[1] == "ps":\n'
        "    sys.exit(0)\n"
    )
    fake.chmod(0o700)
    foreign = tmp_path / "other-project" / "adopt-bundle"
    foreign.mkdir(parents=True)
    (foreign / "config.yaml").write_text("database_url: mysql://x\n")
    session = tmp_path / "session"
    session.mkdir()
    (session / "journal.json").write_text(
        json.dumps(
            {
                "source": str(foreign),
                "bundle": str(tmp_path / "missing-on-purpose"),
                "store": str(tmp_path / "store"),
            }
        )
    )
    key = tmp_path / "key.json"
    key.write_text("fixture")
    key.chmod(0o600)
    environment = {**os.environ, "PATH": f"{binaries}:/usr/bin:/bin", "CAPTURE": str(capture)}
    command = [
        "bash",
        str(ROOT / "docker/credentials.sh"),
        "--image",
        "fixture",
        "--network",
        "bisheng-network",
        "artifact",
        "es-freeze",
        "--session-dir",
        str(session),
        "--env-file",
        str(tmp_path / "env"),
        "--key-file",
        str(key),
        "--deployment-id",
        "d" * 32,
    ]
    (tmp_path / "env").write_text("COMPOSE_PROJECT_NAME=bisheng\n")
    # Missing journal bundle must fail on the host before docker run.
    result = subprocess.run(command, env=environment, capture_output=True, timeout=10, text=True)
    assert result.returncode == 2
    assert "session journal references missing path" in result.stderr
    assert not capture.exists()
    # With all journal paths present, foreign source is bind-mounted readonly.
    bundle = tmp_path / "current-bundle"
    store = tmp_path / "store"
    bundle.mkdir()
    store.mkdir()
    (session / "journal.json").write_text(
        json.dumps({"source": str(foreign), "bundle": str(bundle), "store": str(store)})
    )
    result = subprocess.run(command, env=environment, capture_output=True, timeout=10, text=True)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(capture.read_text())
    mounts = [arguments[i + 1] for i, item in enumerate(arguments) if item == "--mount"]
    assert f"type=bind,source={foreign},target={foreign},readonly" in mounts
    assert f"type=bind,source={bundle},target={bundle},readonly" in mounts
    assert f"type=bind,source={session},target={session}" in mounts


def test_wrapper_help_with_no_mounts_works_on_system_bash(tmp_path):
    fake = tmp_path / "docker"
    log = tmp_path / "args"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAPTURE"\n')
    fake.chmod(0o700)
    response = subprocess.run(
        ["bash", str(ROOT / "docker/credentials.sh"), "--image", "local:test", "--help"],
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CAPTURE": str(log)},
        capture_output=True,
        text=True,
    )
    assert response.returncode == 0, response.stderr
    assert "--help" in log.read_text()


def test_retire_unusable_policy_bundle_archives_missing_baseline(tmp_path):
    """Abandoning a migration must not leave a reusable prepared pair with a dead baseline."""
    import json
    import textwrap

    store = tmp_path / "credential-security"
    revisions = store / "revisions"
    revisions.mkdir(parents=True)
    bundle = revisions / "deadbeefdeadbeefdeadbeefdeadbeef"
    bundle.mkdir()
    missing_baseline = store / "migrations" / "gone" / "backups"
    (bundle / "deployment-policy.json").write_text(
        json.dumps({"payload": {"baseline": str(missing_baseline)}, "mac": "x"})
    )
    prepared = store / "prepared.env"
    prepared.write_text(f"BISHENG_CREDENTIALS_DIR={bundle}\nBISHENG_SECRET_KEYS_FILE=/tmp/keys.json\n")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"BISHENG_CREDENTIALS_DIR={bundle}\n"
        "BISHENG_SECRET_KEYS_FILE=/tmp/keys.json\n"
        "BISHENG_CREDENTIAL_REVISION=deadbeefdeadbeefdeadbeefdeadbeef\n"
        "KEEP=1\n"
    )
    script = tmp_path / "retire.sh"
    docker_dir = ROOT / "docker"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            SCRIPT_DIR={docker_dir!s}
            source "$SCRIPT_DIR/lib/install-env.sh"
            source "$SCRIPT_DIR/lib/credential-install.sh"
            die() {{ printf '%s\\n' "$*" >&2; exit 2; }}
            credential_store={store!s}
            ENV_FILE={env_file!s}
            BUNDLE={bundle!s}
            KEY_FILE=/tmp/keys.json
            credential_key_explicit=false
            credential_retire_unusable_policy_bundle
            [[ -z ${{BUNDLE:-}} ]]
            [[ ! -e {bundle!s} ]]
            [[ ! -e {prepared!s} ]]
            [[ -d {store!s}/abandoned ]]
            abandoned=$(find {store!s}/abandoned -maxdepth 1 -type d -name 'abandoned-*-missing-baseline' | head -n1)
            [[ -n $abandoned && -d $abandoned/bundle && -f $abandoned/prepared.env ]]
            [[ $(env_get "$ENV_FILE" BISHENG_CREDENTIALS_DIR) = '' ]]
            [[ $(env_get "$ENV_FILE" BISHENG_SECRET_KEYS_FILE) = '' ]]
            [[ $(env_get "$ENV_FILE" KEEP) = 1 ]]
            printf 'retired\\n'
            """
        )
    )
    script.chmod(0o700)
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "部署策略基线目录已缺失" in result.stdout
    assert "retired" in result.stdout


def test_credential_store_is_created_at_the_fixed_path(tmp_path):
    import textwrap

    script_dir = tmp_path / "docker"
    legacy = script_dir / ".generated/credential-security/marker"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("keep\n")
    fixed = tmp_path / "fixed-store"
    env_file = script_dir / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=bisheng\n")
    script = tmp_path / "init-store.sh"
    docker_dir = ROOT / "docker"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            SCRIPT_DIR={docker_dir!s}
            source "$SCRIPT_DIR/lib/install-env.sh"
            source "$SCRIPT_DIR/lib/credential-install.sh"
            die() {{ printf '%s\\n' "$*" >&2; exit 2; }}
            credential_store_path() {{ printf '%s\\n' {fixed!s}; }}
            ENV_FILE={env_file!s}
            credential_initialize_store
            [[ -d {fixed!s}/keys && -d {fixed!s}/revisions ]]
            [[ -f {legacy!s} ]]
            perm=$(python3 -c 'import os,sys; print(format(os.stat(sys.argv[1]).st_mode & 0o777, "o"))' {fixed!s})
            [[ $perm = 700 ]]
            printf 'created\\n'
            """
        )
    )
    script.chmod(0o700)
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "created" in result.stdout
