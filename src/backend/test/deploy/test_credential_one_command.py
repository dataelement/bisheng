"""AC-43..47: original entry points drive real offline crypto through a Docker double."""

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "project"
    docker = root / "docker"
    docker.mkdir(parents=True)
    for name in ("install.sh", "credentials.sh", ".env.example", "docker-compose.yml"):
        shutil.copyfile(ROOT / "docker" / name, docker / name)
    for name in ("lib", "bisheng/config", "gateway", "nginx"):
        shutil.copytree(ROOT / "docker" / name, docker / name)
    (root / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/deploy.sh", root / "scripts/deploy.sh")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "docker"
    fake.write_text("""#!/usr/bin/env python3
import json,os,sys,subprocess
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[:2]==['image','inspect']:sys.exit(0)
if args[:2]==['container','inspect']:sys.exit(0 if os.getenv('OLD_DEPLOYMENT') else 1)
if args and args[0]=='login':sys.stdin.read();sys.exit(0)
if args and args[0]=='inspect':print('healthy');sys.exit(0)
if args and args[0]=='run' and 'bisheng.core.config.credential_tool' in args:
    tool=args[args.index('bisheng.core.config.credential_tool')+1:]
    if tool==['--help'] and 'old-without-credentials:test' in args:sys.exit(2)
    if '--online' in tool:sys.exit(3 if Path(os.environ['FAIL_ONLINE']).exists() else 0)
    env=dict(os.environ);env['PYTHONPATH']=os.environ['BACKEND_SOURCE']
    env.pop('config',None);env.pop('BS_SECRET_KEYS_FILE',None)
    sys.exit(subprocess.call([os.environ['REAL_PYTHON'],'-m','bisheng.core.config.credential_tool',*tool],env=env))
if 'ps' in args:print('fixture-container');sys.exit(0)
sys.exit(0)
""")
    fake.chmod(0o700)
    # python3 is the Docker boundary double's interpreter, never an installer dependency.
    (binary / "python3").symlink_to(sys.executable)
    env = {
        **os.environ,
        "PATH": f"{binary}:/usr/bin:/bin",
        "CALLS": str(tmp_path / "calls"),
        "REAL_PYTHON": sys.executable,
        "BACKEND_SOURCE": str(ROOT / "src/backend"),
        "FAIL_ONLINE": str(tmp_path / "fail-online"),
    }
    values = {}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("mysql", "redis", "minio", "elasticsearch", "milvus"):
        path = inputs / (name + ".password")
        path.write_text(secrets.token_urlsafe(24))
        path.chmod(0o600)
        values[name] = {"secret_key_file" if name == "minio" else "password_file": str(path)}
    user = inputs / "minio.user"
    user.write_text("minioadmin")
    values["minio"]["access_key_file"] = str(user)
    manifest = inputs / "inputs.yaml"
    manifest.write_text(yaml.safe_dump({"version": 1, **values}))
    manifest.chmod(0o600)
    text = (
        (docker / ".env.example")
        .read_text()
        .replace("BISHENG_CREDENTIAL_INPUTS_FILE=", f"BISHENG_CREDENTIAL_INPUTS_FILE={manifest}")
    )
    (docker / ".env").write_text(text)
    (docker / ".env").chmod(0o600)

    def run(*args, wrapper=False):
        command = (
            ["bash", str(root / "scripts/deploy.sh"), "install"] if wrapper else ["bash", str(docker / "install.sh")]
        )
        return subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=60)

    def calls():
        return [json.loads(line) for line in Path(env["CALLS"]).read_text().splitlines()]

    return root, env, run, calls, values


def saved_env(root):
    from bisheng.core.config.credential_loader import read_env_file

    return read_env_file(root / "docker/.env")


def test_original_command_bootstraps_and_repeat_preserves_credentials(install):
    root, _env, run, calls, values = install
    first = run()
    assert first.returncode == 0, first.stderr
    config = saved_env(root)
    key = Path(config["BISHENG_SECRET_KEYS_FILE"])
    bundle = Path(config["BISHENG_CREDENTIALS_DIR"])
    assert key.is_file() and (bundle / "config.yaml").is_file()
    snapshot = (key.read_bytes(), (bundle / "config.yaml").read_bytes(), config["BISHENG_CREDENTIAL_REVISION"])
    second = run(wrapper=True)
    assert second.returncode == 0, second.stderr
    after = saved_env(root)
    assert (key.read_bytes(), (bundle / "config.yaml").read_bytes(), after["BISHENG_CREDENTIAL_REVISION"]) == snapshot
    commands = calls()
    assert sum("keygen" in c for c in commands) == 1
    assert sum("prepare" in c for c in commands) == 1
    assert all(
        Path(values[name]["secret_key_file" if name == "minio" else "password_file"]).read_text()
        not in json.dumps(commands) + first.stdout + first.stderr
        for name in values
    )


def test_prepare_only_needs_neither_passwords_nor_images(install):
    root, _env, run, calls, _ = install
    (root / "docker/.env").unlink()
    result = run("--prepare-only")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in ("login", "pull", "run", "image") or "up" in c for c in calls())
    assert saved_env(root)["BISHENG_SECRET_KEYS_FILE"] == ""


def test_failed_online_check_reuses_prepared_identity_on_retry(install):
    root, env, run, calls, _ = install
    Path(env["FAIL_ONLINE"]).touch()
    result = run()
    assert result.returncode != 0
    config = saved_env(root)
    key = Path(config["BISHENG_SECRET_KEYS_FILE"])
    before = key.read_bytes()
    assert not any("--force-recreate" in c and "backend" in c for c in calls())
    Path(env["FAIL_ONLINE"]).unlink()
    assert run().returncode == 0
    assert key.read_bytes() == before and sum("keygen" in c for c in calls()) == 1


def test_missing_saved_key_is_never_regenerated(install):
    root, _env, run, calls, _ = install
    assert run().returncode == 0
    config = saved_env(root)
    Path(config["BISHENG_SECRET_KEYS_FILE"]).unlink()
    count = sum("keygen" in c for c in calls())
    result = run()
    assert result.returncode != 0
    assert sum("keygen" in c for c in calls()) == count
    assert "密钥" in result.stderr


def test_existing_data_is_not_treated_as_fresh_install(install):
    root, _env, run, calls, _ = install
    data = root / "docker/mysql/data"
    data.mkdir(parents=True)
    (data / "ibdata1").write_text("existing")
    result = run()
    assert result.returncode != 0
    assert not any("keygen" in c or "prepare" in c or "up" in c for c in calls())
    assert (data / "ibdata1").read_text() == "existing"


def test_missing_customer_input_explains_same_command_without_starting(install):
    root, _env, run, calls, _ = install
    text = (root / "docker/.env").read_text()
    text = (
        "\n".join(line for line in text.splitlines() if not line.startswith("BISHENG_CREDENTIAL_INPUTS_FILE=")) + "\n"
    )
    (root / "docker/.env").write_text(text)
    result = run()
    assert result.returncode != 0
    assert "MySQL" in result.stderr and "交互" in result.stderr
    assert not any("up" in c for c in calls())


def test_confirmed_legacy_adoption_stays_in_same_entry_and_never_recreates_native(install, tmp_path):
    from cryptography.fernet import Fernet

    root, env, run, calls, _ = install
    old_key = Fernet.generate_key()
    fernet = Fernet(old_key)
    source = yaml.safe_load(
        (root / "docker/bisheng/config/config.yaml").read_text().replace("!env ${BISHENG_GATEWAY_HMAC_SECRET}", '""')
    )
    source["database_url"] = (
        "mysql+pymysql://root:" + fernet.encrypt(b"actual-old-password").decode() + "@mysql:3306/bisheng"
    )
    source["object_storage"]["minio"]["access_key"] = "existing-account"
    source["object_storage"]["minio"]["secret_key"] = "actual-old-minio-password"
    source["vector_stores"]["elasticsearch"]["ssl_verify"] = {}
    legacy_config = tmp_path / "legacy-config.yaml"
    legacy_config.write_text(yaml.safe_dump(source))
    legacy_key = tmp_path / "legacy-key.json"
    legacy_key.write_text(json.dumps({"version": 1, "keys": [old_key.decode()]}))
    legacy_key.chmod(0o600)
    fake = root.parent / "bin/docker"
    text = fake.read_text()
    text = text.replace(
        "if args and args[0]=='inspect':print('healthy');sys.exit(0)",
        """if args and args[0]=='inspect' and '.Config.Env' in ' '.join(args):print(json.dumps(['BISHENG_GATEWAY_HMAC_SECRET=']));sys.exit(0)
if args and args[0]=='cp':
    import shutil
    shutil.copyfile(os.environ['LEGACY_CONFIG'],args[-1]);sys.exit(0)
if args and args[0]=='exec':print(Path(os.environ['LEGACY_KEYS']).read_text());sys.exit(0)
if args and args[0]=='inspect':print('healthy');sys.exit(0)
if 'scripts/rewrap_credentials.py' in args:
    if '--apply' in args:
        mount=args[args.index('-v')+1].split(':/maintenance')[0]
        backup=Path(mount)/'run';backup.mkdir(exist_ok=True);(backup/'plan.json').write_text('{}')
        if Path(os.environ['FAIL_ONLINE']).exists():sys.exit(3)
    print('rewrap boundary passed');sys.exit(0)""",
    )
    fake.write_text(text)
    env.update(
        {
            "OLD_DEPLOYMENT": "yes",
            "BISHENG_ALLOW_CREDENTIAL_MIGRATION": "yes",
            "LEGACY_CONFIG": str(legacy_config),
            "LEGACY_KEYS": str(legacy_key),
        }
    )
    Path(env["FAIL_ONLINE"]).touch()
    first = run()
    assert first.returncode != 0
    assert not any("--force-recreate" in c and "backend" in c for c in calls())
    Path(env["FAIL_ONLINE"]).unlink()
    second = run(wrapper=True)
    assert second.returncode == 0, second.stderr
    after = saved_env(root)
    newring = json.loads(Path(after["BISHENG_SECRET_KEYS_FILE"]).read_text())
    assert newring["keys"][0] != old_key.decode() and old_key.decode() in newring["keys"]
    from sqlalchemy.engine import make_url

    data = yaml.safe_load((Path(after["BISHENG_CREDENTIALS_DIR"]) / "config.yaml").read_text())
    assert (
        Fernet(newring["keys"][0].encode()).decrypt(make_url(data["database_url"]).password.encode())
        == b"actual-old-password"
    )
    native = {"mysql", "redis", "minio", "milvus", "elasticsearch", "openfga"}
    assert not any("up" in c and native.intersection(c) for c in calls())
    assert any("--resume" in c for c in calls())
    assert not any("--online" in c for c in calls())  # auth state may intentionally remain unchanged
    assert not any("actual-old-password" in json.dumps(c) or old_key.decode() in json.dumps(c) for c in calls())


def test_interactive_original_command_hides_passwords_and_reprompts_mismatch(install):
    import pty
    import select
    import time

    root, env, _run, calls, _ = install
    file = root / "docker/.env"
    file.write_text(
        file.read_text().replace(
            next(line for line in file.read_text().splitlines() if line.startswith("BISHENG_CREDENTIAL_INPUTS_FILE=")),
            "BISHENG_CREDENTIAL_INPUTS_FILE=",
        )
    )
    master, slave = pty.openpty()
    proc = subprocess.Popen(["bash", str(root / "docker/install.sh")], env=env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    received = bytearray()
    pending = bytearray()

    def expect(text):
        marker = text.encode()
        deadline = time.monotonic() + 30
        while marker not in pending:
            assert time.monotonic() < deadline, "installer prompt timeout"
            if select.select([master], [], [], 1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                assert chunk, received.decode(errors="replace")
                received.extend(chunk)
                pending.extend(chunk)
        end = pending.index(marker) + len(marker)
        del pending[:end]

    passwords = []
    try:
        for index, label in enumerate(("MySQL", "Redis", "MinIO", "Elasticsearch", "Milvus")):
            expect("请输入" + label + "密码（输入隐藏）：")  # noqa: RUF001 -- exact localized terminal prompt
            value = secrets.token_urlsafe(20) + "@:$"
            passwords.append(value)
            os.write(master, (value + "\n").encode())
            expect("请再次输入确认：")  # noqa: RUF001 -- exact localized terminal prompt
            if index == 0:
                os.write(master, b"mismatch\n")
                expect("两次输入不一致")
                expect("请输入MySQL密码（输入隐藏）：")  # noqa: RUF001 -- exact localized terminal prompt
                os.write(master, (value + "\n").encode())
                expect("请再次输入确认：")  # noqa: RUF001 -- exact localized terminal prompt
            os.write(master, (value + "\n").encode())
        deadline = time.monotonic() + 30
        while proc.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    received.extend(os.read(master, 65536))
                except OSError:
                    break
        assert proc.wait(timeout=5) == 0
        output = received.decode(errors="replace")
        assert all(value not in output for value in passwords)
        assert all(value not in json.dumps(calls()) for value in passwords)
        assert saved_env(root)["BISHENG_SECRET_KEYS_FILE"]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


def test_prepared_identity_recovers_when_env_write_was_lost(install):
    root, _env, run, calls, _ = install
    assert run().returncode == 0
    initial = saved_env(root)
    key = Path(initial["BISHENG_SECRET_KEYS_FILE"]).read_bytes()
    # Simulate losing activation metadata after successful private preparation.
    (root / "docker/.env").write_bytes((root / "docker/.env.example").read_bytes())
    result = run(wrapper=True)
    assert result.returncode == 0, result.stderr
    after = saved_env(root)
    assert after["BISHENG_CREDENTIAL_REVISION"] == initial["BISHENG_CREDENTIAL_REVISION"]
    assert Path(after["BISHENG_SECRET_KEYS_FILE"]).read_bytes() == key
    assert sum("keygen" in c for c in calls()) == 1


def test_missing_saved_bundle_never_falls_back_to_fresh(install):
    root, _env, run, calls, _ = install
    assert run().returncode == 0
    current = saved_env(root)
    bundle = Path(current["BISHENG_CREDENTIALS_DIR"])
    bundle.rename(bundle.with_name("backup"))
    result = run()
    assert result.returncode != 0 and "备份" in result.stderr
    assert sum("prepare" in c for c in calls()) == 1


def test_active_install_lock_blocks_parallel_preparation(install):
    root, _env, run, calls, _ = install
    lock = root / "docker/.generated/credential-security/.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))
    result = run()
    assert result.returncode != 0 and "另一个部署进程" in result.stderr
    assert not any("keygen" in c or "up" in c for c in calls())
    assert (lock / "pid").read_text() == str(os.getpid())


def test_interrupted_process_lock_is_recovered_by_original_command(install):
    root, _env, run, calls, _ = install
    lock = root / "docker/.generated/credential-security/.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("99999999")
    result = run()
    assert result.returncode == 0, result.stderr
    assert not lock.exists()
    assert sum("keygen" in c for c in calls()) == 1


def test_incompatible_image_stops_before_passwords_or_data_changes(install):
    root, _env, run, calls, _ = install
    file = root / "docker/.env"
    original = saved_env(root)["BISHENG_BACKEND_IMAGE"]
    file.write_text(file.read_text().replace(original, "old-without-credentials:test"))
    result = run()
    assert result.returncode != 0 and "配套镜像" in result.stderr
    assert not any("keygen" in c or "prepare" in c or "up" in c for c in calls())


def test_existing_remote_redis_without_mysql_is_not_fresh(install):
    root, _env, run, calls, _ = install
    fake = root.parent / "bin/docker"
    source = fake.read_text().replace(
        "sys.exit(0 if os.getenv('OLD_DEPLOYMENT') else 1)", "sys.exit(0 if args[-1]=='bisheng-redis' else 1)"
    )
    fake.write_text(source)
    response = run()
    assert response.returncode != 0 and "已有中间件数据" in response.stderr
    assert not any("keygen" in c or "prepare" in c or "up" in c for c in calls())
