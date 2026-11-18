"""AC-43..47: original entry points drive real offline crypto through a Docker double."""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet

from bisheng.core.config.credential_artifacts import write_confidential

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "project"
    docker = root / "docker"
    docker.mkdir(parents=True)
    for name in ("install.sh", "credentials.sh", ".env.example", "docker-compose.yml"):
        shutil.copyfile(ROOT / "docker" / name, docker / name)
    for name in ("lib", "bisheng/config", "gateway", "nginx", "redis", "mysql", "milvus"):
        shutil.copytree(ROOT / "docker" / name, docker / name)
    fixed_store = root.parent / "credential-security"
    env_lib = docker / "lib/install-env.sh"
    env_lib.write_text(env_lib.read_text().replace("/opt/bisheng/.credential-security", str(fixed_store)))
    (root / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/deploy.sh", root / "scripts/deploy.sh")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "docker"
    fake.write_text("""#!/usr/bin/env python3
import hashlib,io,json,os,sys,subprocess,tarfile
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[:1]==['info'] and '.SecurityOptions' in ' '.join(args):
    if os.getenv('ROOTLESS_FIXTURE'):print('rootless')
    sys.exit(0)
if args[:2]==['image','inspect']:
    if os.getenv('MISSING_IMAGE'):sys.exit(1)
    if '--format' in args:print('sha256:'+'a'*63+os.getenv('IMAGE_VERSION','a'))
    sys.exit(0)
if args and args[0]=='create':print('fixture-template-container');sys.exit(0)
if args and args[0]=='cp':
    source,target=args[-2:]
    if target=='-':
        body=b'log:\\n  level: info\\n'
        name='config/es_config.sample' if 'elasticsearch' in source else 'configs/milvus.yaml'
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
            item=tarfile.TarInfo(name);item.size=len(body);archive.addfile(item,io.BytesIO(body))
        sys.exit(0)
if args[:2]==['container','inspect']:sys.exit(0 if os.getenv('OLD_DEPLOYMENT') else 1)
if args and args[0]=='login':sys.stdin.read();sys.exit(0)
if 'config' in args and '--images' in args:
    print('cr.dataelem.com/mysql:8.0');print('cr.dataelem.com/dataelement/bisheng-backend:v3.1.0-beta2');sys.exit(0)
if args and args[0]=='inspect':
    if '--format' in args:print('healthy');sys.exit(0)
    print(json.dumps([{'Name':'/bisheng-es','Image':'sha256:'+'c'*64,
      'Config':{'Labels':{'com.docker.compose.project':'bisheng','com.docker.compose.service':'elasticsearch'},
        'Env':[],'Cmd':['/opt/bitnami/scripts/elasticsearch/run.sh'],'User':'1001','Hostname':'bisheng-es'},
      'HostConfig':{},'Mounts':[{'Type':'bind','Source':'/existing/es-data','Destination':'/bitnami/elasticsearch/data','RW':True}],
      'NetworkSettings':{'Networks':{'bisheng-network':{'Aliases':['bisheng-es','elasticsearch']}}}}]))
    sys.exit(0)
if args and args[0]=='exec' and '/proc/1/comm' in args:
    marker=os.getenv('ES_SETUP_MARKER')
    if marker and not Path(marker).exists():Path(marker).write_text('seen');print('bash');sys.exit(0)
    print('java');sys.exit(0)
if args and args[0]=='run' and 'bisheng.core.config.credential_tool' in args:
    tool=args[args.index('bisheng.core.config.credential_tool')+1:]
    if tool[0]=='--help' and 'old-without-credentials:test' in args:sys.exit(2)
    if '--online' in tool:sys.exit(3 if Path(os.environ['FAIL_ONLINE']).exists() else 0)
    env=dict(os.environ);env['PYTHONPATH']=os.environ['BACKEND_SOURCE']
    env.pop('config',None);env.pop('BS_SECRET_KEYS_FILE',None)
    sys.exit(subprocess.call([os.environ['REAL_PYTHON'],'-m','bisheng.core.config.credential_tool',*tool],env=env))
if 'up' in args:Path(os.environ['SERVICES_STARTED']).touch();sys.exit(0)
if 'ps' in args:
    if any('com.bisheng.credential.session=' in arg for arg in args):sys.exit(0)
    if os.getenv('OLD_DEPLOYMENT') or Path(os.environ['SERVICES_STARTED']).exists():print('fixture-container')
    sys.exit(0)
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
        "SERVICES_STARTED": str(tmp_path / "services-started"),
    }
    values = {}
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    key = tmp_path / "provided-keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    identity = "b" * 32
    store = fixed_store
    store.mkdir(parents=True)
    (store / "deployment.id").write_text(identity)
    (store / "deployment.id").chmod(0o600)
    expected = {}
    for name in ("mysql", "redis", "minio", "elasticsearch", "milvus"):
        path = inputs / (name + ".password")
        expected[name] = secrets.token_urlsafe(24)
        write_confidential(path, expected[name].encode(), key_file=key, deployment=identity)
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
        .replace("BISHENG_SECRET_KEYS_FILE=", f"BISHENG_SECRET_KEYS_FILE={key}")
    )
    (docker / ".env").write_text(text)
    (docker / ".env").chmod(0o600)
    for name in values:
        values[name]["_expected"] = expected[name]

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


def test_cached_image_policy_uses_original_command_without_registry_login(install):
    root, _env, run, calls, _values = install
    file = root / "docker/.env"
    file.write_text(file.read_text().replace("BISHENG_IMAGE_PULL_POLICY=always", "BISHENG_IMAGE_PULL_POLICY=missing"))
    result = run()
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in {"pull", "login"} or c[-1:] == ["pull"] for c in calls())


def test_never_pull_policy_rejects_missing_backend_before_preparing_passwords(install):
    root, env, run, calls, _values = install
    file = root / "docker/.env"
    file.write_text(file.read_text().replace("BISHENG_IMAGE_PULL_POLICY=always", "BISHENG_IMAGE_PULL_POLICY=never"))
    env["MISSING_IMAGE"] = "yes"
    result = run()
    assert result.returncode != 0 and "后端工具镜像不可用" in result.stderr
    assert not any(c[0] in {"pull", "login"} for c in calls())
    assert not any("keygen" in c or "seal-input" in c or "up" in c for c in calls())


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
    assert sum("keygen" in c for c in commands) == 0
    assert sum("prepare" in c for c in commands) == 1
    assert all(values[name]["_expected"] not in json.dumps(commands) + first.stdout + first.stderr for name in values)


def test_legacy_env_without_runtime_bindings_still_installs(install):
    """An .env from before the runtime layer lacks the keys the shipped config reads with !env.

    Without app-runtime nothing generates them, so the installer adds them empty,
    the same as .env.example, instead of failing credential preparation.
    """
    root, _env, run, _calls, _values = install
    runtime_keys = ("BISHENG_RUNTIME_CONTROL_SECRET", "BISHENG_APP_PROXY_HMAC_SECRET", "BISHENG_APP_OBO_SECRET")
    file = root / "docker/.env"
    lines = [
        "COMPOSE_PROFILES=" if line.startswith("COMPOSE_PROFILES=") else line
        for line in file.read_text().splitlines()
        if not line.startswith(tuple(key + "=" for key in runtime_keys))
    ]
    file.write_text("\n".join(lines) + "\n")
    result = run()
    assert result.returncode == 0, result.stderr
    config = saved_env(root)
    assert all(config[key] == "" for key in runtime_keys)
    assert config["COMPOSE_PROFILES"] == ""


def test_prepare_only_needs_neither_passwords_nor_images(install):
    root, _env, run, calls, _ = install
    (root / "docker/.env").unlink()
    result = run("--prepare-only")
    assert result.returncode == 0, result.stderr
    assert not any(c[0] in ("login", "pull", "run", "image") or "up" in c for c in calls())
    assert saved_env(root)["BISHENG_SECRET_KEYS_FILE"] == ""


def test_denied_daemon_stops_before_registry_and_preparation(install):
    root, _env, run, calls, _ = install
    fake = root.parent / "bin/docker"
    source = fake.read_text().replace(
        "if args[:2]==['image','inspect']:", "if args[:1]==['info']:sys.exit(1)\nif args[:2]==['image','inspect']:"
    )
    fake.write_text(source)
    before = (root / "docker/.env").read_bytes()
    result = run()
    assert result.returncode != 0 and "当前账号无法访问Docker服务" in result.stderr
    assert not any(c[0] in {"login", "pull", "run"} for c in calls())
    assert (root / "docker/.env").read_bytes() == before
    assert not (root / "docker/.generated/credential-security/revisions").exists()


def test_unvalidated_rootless_stops_before_password_and_registry_steps(install):
    root, env, run, calls, _ = install
    env["ROOTLESS_FIXTURE"] = "yes"
    before = (root / "docker/.env").read_bytes()
    result = run()
    assert result.returncode != 0 and "rootless Docker" in result.stderr
    assert not any(c[0] in {"login", "pull", "run"} for c in calls())
    assert (root / "docker/.env").read_bytes() == before


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
    assert key.read_bytes() == before and sum("keygen" in c for c in calls()) == 0


def test_backend_image_change_reuses_identical_credentials(install):
    root, env, run, _calls, _ = install
    assert run().returncode == 0
    before = saved_env(root)
    env["IMAGE_VERSION"] = "b"
    result = run()
    assert result.returncode == 0, result.stderr
    after = saved_env(root)
    # Option C: no Go runtime binary in .env; credential package and keys stay stable.
    assert "BISHENG_CREDENTIAL_RUNTIME_BINARY" not in after
    assert after["BISHENG_CREDENTIALS_DIR"] == before["BISHENG_CREDENTIALS_DIR"]
    assert after["BISHENG_SECRET_KEYS_FILE"] == before["BISHENG_SECRET_KEYS_FILE"]
    assert (
        json.loads(Path(after["BISHENG_CREDENTIALS_DIR"], "manifest.json").read_text())["native_storage"] == "plaintext"
    )


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


def test_unverified_es_source_stops_before_any_native_change(install, tmp_path):
    from cryptography.fernet import Fernet

    root, env, run, calls, _ = install
    old_key = Fernet.generate_key()
    fernet = Fernet(old_key)
    # The legacy container's config holds plain values; blank every shipped !env binding.
    source = yaml.safe_load(re.sub(r"!env \$\{\w+\}", '""', (root / "docker/bisheng/config/config.yaml").read_text()))
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
        "if args and args[0]=='inspect':\n",
        """if args and args[0]=='inspect' and '.Config.Env' in ' '.join(args):print(json.dumps(['BISHENG_GATEWAY_HMAC_SECRET=']));sys.exit(0)
if args and args[0]=='exec':
    source='LEGACY_KEYS' if 'import ast' in ' '.join(args) else 'LEGACY_CONFIG'
    sys.stdout.write(Path(os.environ[source]).read_text());sys.exit(0)
if args and args[0]=='inspect':
""",
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
    first = run()
    assert first.returncode != 0 and "ES服务端安全状态未知" in first.stderr
    assert not any("--force-recreate" in c and "backend" in c for c in calls())
    second = run(wrapper=True)
    assert second.returncode != 0 and "ES服务端安全状态未知" in second.stderr
    assert saved_env(root)["BISHENG_CREDENTIALS_DIR"] == ""
    from bisheng.core.config.credential_loader import read_env_file

    after = read_env_file(root.parent / "credential-security/prepared.env")
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
    assert not any("--resume" in c or "--apply" in c for c in calls())
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
            minimum = 8 if label == "MinIO" else 6
            expect("请输入" + label + f"密码（至少{minimum}位，输入隐藏）：")  # noqa: RUF001 -- exact localized terminal prompt
            value = secrets.token_urlsafe(20) + "@:$"
            passwords.append(value)
            os.write(master, (value + "\n").encode())
            expect("请再次输入确认：")  # noqa: RUF001 -- exact localized terminal prompt
            if index == 0:
                os.write(master, b"mismatch\n")
                expect("两次输入不一致")
                expect("请输入MySQL密码（至少6位，输入隐藏）：")  # noqa: RUF001 -- exact localized terminal prompt
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
    assert sum("keygen" in c for c in calls()) == 0


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
    lock = root.parent / "credential-security/.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))
    result = run()
    assert result.returncode != 0 and "另一个部署进程" in result.stderr
    assert not any("keygen" in c or "up" in c for c in calls())
    assert (lock / "pid").read_text() == str(os.getpid())


def test_interrupted_process_lock_is_recovered_by_original_command(install):
    root, _env, run, calls, _ = install
    lock = root.parent / "credential-security/.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("99999999")
    result = run()
    assert result.returncode == 0, result.stderr
    assert not lock.exists()
    assert sum("keygen" in c for c in calls()) == 0


def test_incompatible_image_stops_before_passwords_or_data_changes(install):
    root, _env, run, calls, _ = install
    file = root / "docker/.env"
    original = saved_env(root)["BISHENG_BACKEND_IMAGE"]
    file.write_text(file.read_text().replace(original, "old-without-credentials:test"))
    result = run()
    assert result.returncode != 0 and "配套镜像" in result.stderr
    assert not any("keygen" in c or "prepare" in c or "up" in c for c in calls())


def test_existing_remote_redis_without_mysql_is_not_fresh(install):
    _root, env, run, calls, _ = install
    env["OLD_DEPLOYMENT"] = "redis-only"
    response = run()
    assert response.returncode != 0 and "已有部署" in response.stderr
    assert not any("keygen" in c or "prepare" in c or "up" in c for c in calls())


def test_original_install_waits_for_final_es_process(install):
    root, env, run, calls, _ = install
    env["ES_SETUP_MARKER"] = str(root / "es-temporary-process")
    result = run()
    assert result.returncode == 0, "installer did not wait for final native process"
    probes = [call for call in calls() if call[:1] == ["exec"] and "/proc/1/comm" in call]
    assert len(probes) >= 2
