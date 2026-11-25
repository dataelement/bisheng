"""ES security transitions; Docker lifecycle belongs exclusively to the host script."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from bisheng.core.config.credential_artifacts import (
    bundle_native_files,
    read_confidential,
    read_private,
    write_bundle_native,
    write_confidential,
    write_private_atomic,
)
from bisheng.core.config.credential_inputs import read_inputs
from bisheng.core.config.credential_loader import dump_document, load_config, validate_runtime
from bisheng.core.config.credential_rotation import credentials
from bisheng.core.config.credential_rotation_native import _es, _quiet_drivers, classify_failure
from bisheng.core.config.secret_crypto import CredentialConfigurationError, load_keyring


def fail(message):
    raise CredentialConfigurationError("ES migration: " + message + "; preserve state and rerun the original installer")


def settings_for(bundle, env_file=None):
    return validate_runtime(load_config(Path(bundle) / "config.yaml", env_file=env_file).data)


def shared_endpoint(first, second):
    left, right = urlparse(first), urlparse(second)
    if (left.scheme, left.port or 9200, left.path.rstrip("/")) != (
        right.scheme,
        right.port or 9200,
        right.path.rstrip("/"),
    ):
        return False
    if left.hostname == right.hostname:
        return True
    try:

        def addresses(value):
            return {
                row[4][0] for row in socket.getaddrinfo(value.hostname, value.port or 9200, type=socket.SOCK_STREAM)
            }

        first_addresses = addresses(left)
        return bool(first_addresses) and first_addresses == addresses(right)
    except OSError:
        return False  # Unknown aliases are not authorized as the managed instance.


def rewrite_security_config(native, enabled):
    import yaml

    for name in ("es-config/elasticsearch.yml", "es-config/my_elasticsearch.yml"):
        if name not in native:
            continue
        conf = yaml.safe_load(native[name]) or {}
        if not isinstance(conf, dict):
            fail("unsupported ES configuration")
        nested = conf.get("xpack", {}).get("security") if isinstance(conf.get("xpack"), dict) else None
        if isinstance(nested, dict):
            conf.pop("xpack.security.enabled", None)
            nested["enabled"] = enabled
        else:
            conf["xpack.security.enabled"] = enabled
        native[name] = yaml.safe_dump(conf, sort_keys=False).encode()


def security_state(client):
    """Anonymous cluster access alone does not prove that security is disabled."""
    info = client.info()
    features = client.xpack.info(categories=["features"])
    security = features.get("features", {}).get("security", {}).get("enabled")
    if type(security) is not bool:
        fail("server security state is unknown")
    nodes = client.nodes.info()
    if info.get("version", {}).get("number") != "8.12.0" or len(nodes.get("nodes", {})) != 1:
        fail("native version/topology requires a separate validated adapter")
    if not security:
        return "DISABLED"
    identity = client.security.authenticate()
    if identity.get("authentication_type") == "anonymous" or identity.get("username") == "_anonymous":
        fail("anonymous access must not be mistaken for disabled security")
    if not identity.get("username"):
        fail("authenticated identity is unknown")
    return "AUTHENTICATED"


def discover(bundle, env_file=None):
    settings = settings_for(bundle, env_file)
    with _quiet_drivers():
        try:
            with _es(settings, "elasticsearch") as client:
                return security_state(client)
        except CredentialConfigurationError:
            raise
        except Exception as error:
            if classify_failure("elasticsearch", error) == "DENIED":
                return "AUTH_REQUIRED"
            fail("server unavailable or security state cannot be read")


def prepare_es_material(source, settings, key_file, env_file, mode, inputs):
    from bisheng.core.config.credential_bundle import _es as render_es
    from bisheng.core.config.credential_bundle import _object

    data = copy.deepcopy(load_config(Path(source) / "config.yaml", env_file=env_file).data)
    expected = credentials(settings)
    if expected.get("elasticsearch") and mode in (None, "existing"):
        return data, expected, None
    if mode not in {"enable", "retain", "recover"}:
        fail("legacy Elasticsearch has no configured authentication; an explicit in-installer choice is required")
    es = {"mode": mode, "phase": "PREPARED"}
    conf = data["vector_stores"]["elasticsearch"]
    endpoint = conf.get("url") or conf.get("elasticsearch_url")
    telemetry = data.get("telemetry_elasticsearch")
    telemetry_endpoint = (telemetry.get("url") or telemetry.get("elasticsearch_url")) if telemetry else None
    same_statistics = bool(telemetry_endpoint and shared_endpoint(endpoint, telemetry_endpoint))
    es["shared_statistics"] = same_statistics
    if mode == "retain":
        if inputs:
            fail("retain must not contain replacement credentials")
        conf = data["vector_stores"]["elasticsearch"]
        options = _object(conf.get("ssl_verify", {}), "elasticsearch.ssl_verify")
        options.pop("basic_auth", None)
        conf["ssl_verify"] = options
        expected["elasticsearch"] = ""
        if same_statistics:
            options = _object(telemetry.get("ssl_verify", {}), "telemetry_elasticsearch.ssl_verify")
            options.pop("basic_auth", None)
            telemetry["ssl_verify"] = options
            expected["telemetry_elasticsearch"] = ""
        return data, expected, es
    supplied = read_inputs(inputs, allow_plaintext=False)
    if set(supplied) != {"elasticsearch"} or supplied["elasticsearch"].get("username", "elastic") != "elastic":
        fail("only the managed elastic identity is supported for initial activation")
    conf = data["vector_stores"]["elasticsearch"]
    endpoint = conf.get("url") or conf.get("elasticsearch_url")
    if urlparse(endpoint).scheme != "http":
        fail("existing TLS must be preserved by a validated TLS adapter")
    ring = load_keyring(key_file)
    replacement = dict(supplied["elasticsearch"])
    if mode == "enable":
        # With security disabled, an old client username is not a server identity.
        conf = dict(conf)
        options = _object(conf.get("ssl_verify", {}), "elasticsearch.ssl_verify")
        options.pop("basic_auth", None)
        conf["ssl_verify"] = options
        replacement["username"] = "elastic"
    updated, expected["elasticsearch"] = render_es(conf, ring, replacement, False)
    data["vector_stores"]["elasticsearch"] = updated
    # Statistics may be a second consumer of the very same instance.
    telemetry = data.get("telemetry_elasticsearch")
    if telemetry and (telemetry.get("url") or telemetry.get("elasticsearch_url")):
        telemetry_endpoint = telemetry.get("url") or telemetry.get("elasticsearch_url")
        if same_statistics:
            data["telemetry_elasticsearch"], expected["telemetry_elasticsearch"] = render_es(
                telemetry, ring, replacement, False
            )
        elif not expected.get("telemetry_elasticsearch"):
            fail("independent unauthenticated statistics endpoint must not be silently modified")
    return data, expected, es


def _state(session, key_file):
    from bisheng.core.config.credential_sealed_migration import status

    value = status(session, key_file=key_file)
    if not isinstance(value.get("es"), dict):
        fail("no ES transition is bound to this session")
    return value


def _save(session, value, key_file):
    from bisheng.core.config.credential_sealed_migration import _save as save

    save(session, value, key_file)


def _seal_record(session, data, key_file, prefix):
    name = prefix + "-" + uuid.uuid4().hex + ".sealed"
    path = Path(session) / name
    write_confidential(path, json.dumps(data).encode(), key_file=key_file)
    return {"file": name, "sha256": hashlib.sha256(read_private(path)).hexdigest()}


def _record(session, ref, key_file):
    path = Path(session) / ref["file"]
    if path.parent != Path(session) or hashlib.sha256(read_private(path)).hexdigest() != ref["sha256"]:
        fail("encrypted evidence changed")
    return json.loads(read_confidential(path, key_file=key_file))


def index_baseline(client, *, recovery_seconds=0):
    # After changing ES security mode, HTTP may be ready before the existing
    # shards are assigned. Wait only for stats availability; changed counts,
    # UUIDs and aliases still fail the exact frozen-baseline comparison.
    deadline = time.monotonic() + recovery_seconds
    while True:
        indexes = client.indices.get(index="*", expand_wildcards="all")
        stats = client.indices.stats(index="*", metric="docs", expand_wildcards="all").get("indices", {})
        result = {}
        missing = False
        for name, metadata in indexes.items():
            # Skip ES system indexes only. Customer indexes may legitimately start
            # with ".security-" (see tests); enabling auth also creates .ds-* streams.
            if re.fullmatch(r"\.security(?:-\d+|-tokens-\d+|-profile-\d+)?", name):
                continue
            if name.startswith(".ds-"):
                continue
            index = metadata.get("settings", {}).get("index", {})
            if not index.get("uuid"):
                fail("index identity cannot be established")
            if name not in stats:
                missing = True
                continue
            result[name] = {
                "uuid": index["uuid"],
                "count": stats[name]["primaries"]["docs"]["count"],
                "aliases": metadata.get("aliases", {}),
            }
        if not missing:
            cluster_uuid = client.info().get("cluster_uuid")
            if not cluster_uuid or cluster_uuid == "_na_":
                fail("cluster identity cannot be established")
            return {"cluster_uuid": cluster_uuid, "indexes": result}
        if time.monotonic() >= deadline:
            fail("index document baseline cannot be established")
        time.sleep(min(2, max(0, deadline - time.monotonic())))


def freeze(session, key_file, env_file=None):
    value = _state(session, key_file)
    if value["es"]["phase"] != "PREPARED":
        return  # The original frozen baseline is immutable across retries.
    settings = settings_for(value["source"], env_file)
    if value["es"]["mode"] == "recover":
        settings = settings_for(value["bundle"], env_file)
    with _quiet_drivers(), _es(settings, "elasticsearch") as client:
        state = security_state(client)
        expected = "AUTHENTICATED" if value["es"]["mode"] == "recover" else "DISABLED"
        if state != expected:
            fail("source security state changed before maintenance")
        client.indices.refresh(index="*")
        baseline = index_baseline(client)
        if value["es"].get("shared_statistics"):
            with _es(settings, "telemetry_elasticsearch") as statistics:
                if statistics.info().get("cluster_uuid") != baseline["cluster_uuid"]:
                    fail("statistics alias does not identify the same source cluster")
    value["es"]["baseline"] = _seal_record(session, baseline, key_file, "es-baseline")
    value["es"]["phase"] = "FROZEN"
    _save(session, value, key_file)


def observe_target(session, key_file, env_file=None):
    value = _state(session, key_file)
    with _quiet_drivers():
        try:
            with _es(settings_for(value["bundle"], env_file), "elasticsearch") as client:
                state = security_state(client)
                if value["es"]["mode"] == "retain":
                    return "KEEP" if state == "DISABLED" else "UNKNOWN"
                if state == "AUTHENTICATED":
                    identity = client.security.authenticate()
                    expected_user = settings_for(value["bundle"], env_file).vector_stores.elasticsearch.ssl_verify[
                        "basic_auth"
                    ][0]
                    return "READY" if identity.get("username") == expected_user else "UNKNOWN"
                return "UNKNOWN"
        except CredentialConfigurationError:
            raise
        except Exception as error:
            if classify_failure("elasticsearch", error) == "DENIED":
                return "DENIED"
            return "UNKNOWN"


def reset_intent(session, key_file, *, retry=False):
    value = _state(session, key_file)
    if value["es"]["mode"] != "enable" or value["es"]["phase"] not in {"FROZEN", "PASSWORD_INTENT"}:
        fail("password reset is outside the verified transition")
    if value["es"]["phase"] == "PASSWORD_INTENT" and not retry:
        fail("previous password write is uncertain; verify target first or explicitly confirm retry")
    value["es"]["phase"] = "PASSWORD_INTENT"
    _save(session, value, key_file)


def persist_password(session, key_file, env_file=None):
    value = _state(session, key_file)
    if value["es"]["mode"] != "enable" or value["es"]["phase"] != "PASSWORD_INTENT":
        fail("durable password intent required")
    settings = settings_for(value["bundle"], env_file)
    with _quiet_drivers(), _es(settings, "elasticsearch") as client:
        if security_state(client) != "AUTHENTICATED":
            fail("target identity is not authenticated")
        # Bootstrap authentication alone does not establish a native password.
        client.security.change_password(username="elastic", password=credentials(settings)["elasticsearch"])
    value["es"]["phase"] = "PASSWORD_SET"
    _save(session, value, key_file)


def verify(session, key_file, env_file=None):
    value = _state(session, key_file)
    if value["es"]["phase"] not in {"FROZEN", "PASSWORD_SET", "VERIFIED"}:
        fail("frozen baseline required")
    if value["es"]["mode"] == "enable" and value["es"]["phase"] == "FROZEN":
        fail("bootstrap login is insufficient; the native password must be persisted")
    expected = _record(session, value["es"]["baseline"], key_file)
    settings = settings_for(value["bundle"], env_file)
    with _quiet_drivers(), _es(settings, "elasticsearch") as client:
        # A prior run can stop after creating its disposable index.  Only an
        # index carrying our journaled ownership marker may be removed.
        pending = value["es"].get("probe")
        if pending:
            metadata = client.indices.get(index=pending["name"], ignore_unavailable=True)
            if metadata:
                owned = metadata.get(pending["name"], {}).get("mappings", {}).get("_meta", {})
                if owned.get("bisheng_credential_probe") != pending["token"]:
                    fail("interrupted probe ownership cannot be established")
                client.indices.delete(index=pending["name"])
            value["es"].pop("probe")
            _save(session, value, key_file)
        actual_state = security_state(client)
        target_state = "DISABLED" if value["es"]["mode"] == "retain" else "AUTHENTICATED"
        if actual_state != target_state or index_baseline(client, recovery_seconds=60) != expected:
            fail("server authentication or original indexes do not match the frozen baseline")
        if value["es"].get("shared_statistics"):
            with _es(settings, "telemetry_elasticsearch") as statistics:
                if statistics.info().get("cluster_uuid") != expected["cluster_uuid"]:
                    fail("statistics consumer points to a different cluster")
                statistics.search(index=next(iter(expected["indexes"]), "*"), size=0)
        if target_state == "AUTHENTICATED":
            from elasticsearch import ApiError

            anonymous = settings.model_copy(deep=True)
            anonymous.vector_stores.elasticsearch.ssl_verify.pop("basic_auth", None)
            try:
                with _es(anonymous, "elasticsearch") as unauthenticated:
                    unauthenticated.search(index=next(iter(expected["indexes"]), "*"), size=0)
            except ApiError as error:
                if error.status_code not in (401, 403):
                    fail("anonymous-access check is inconclusive")
            else:
                fail("anonymous business-index access is still permitted")
        token = uuid.uuid4().hex
        probe = "bisheng-credential-probe-" + token
        value["es"]["probe"] = {"name": probe, "token": token}
        _save(session, value, key_file)  # Durable intent before index creation.
        client.indices.create(index=probe, mappings={"_meta": {"bisheng_credential_probe": token}})
        client.index(index=probe, id="check", document={"credential_migration_probe": True}, refresh="wait_for")
        if client.get(index=probe, id="check")["_source"] != {"credential_migration_probe": True}:
            fail("read/write probe mismatch")
        client.indices.delete(index=probe)
        value["es"].pop("probe")
    value["es"]["phase"] = "VERIFIED"
    _save(session, value, key_file)


def _compile_current(bundle, inspect_stream, secret_gid, env_file=None):
    from bisheng.core.config.credential_rotation_compose import compile_native

    containers = json.load(inspect_stream)
    if len(containers) != 1:
        fail("ambiguous ES container")
    container = containers[0]
    labels = container["Config"]["Labels"]
    project = labels.get("com.docker.compose.project")
    if labels.get("com.docker.compose.service") != "elasticsearch" or not project:
        fail("ES deployment ownership is unknown")
    mounts = container.get("Mounts", [])
    if not any(
        m.get("Destination") == "/bitnami/elasticsearch/data" and m.get("Type") in {"bind", "volume"} for m in mounts
    ):
        fail("existing ES data mount cannot be identified")
    networks = container["NetworkSettings"]["Networks"]
    if not networks:
        fail("existing ES network is missing")
    host = urlparse(settings_for(bundle, env_file).vector_stores.elasticsearch.elasticsearch_url).hostname
    owned_hosts = {container["Name"].lstrip("/"), container["Config"].get("Hostname")}
    for network in networks.values():
        owned_hosts.update(network.get("Aliases") or [])
        owned_hosts.update(network.get("DNSNames") or [])
        owned_hosts.add(network.get("IPAddress"))
    if host not in owned_hosts:
        fail("configured ES endpoint does not identify the captured container")
    service = {"container_name": container["Name"].lstrip("/"), "networks": {n: {} for n in networks}}
    inventory = {
        "project": project,
        "containers": containers,
        "compose": {"services": {"elasticsearch": service}, "networks": {n: {"name": n} for n in networks}},
    }
    result = compile_native(
        inventory,
        component="elasticsearch",
        bundle=bundle,
        installer_root="/unused",
        secret_gid=secret_gid,
        run_id=json.loads(read_private(Path(bundle) / "manifest.json"))["revision"],
    )
    service = result["compose"]["services"]["elasticsearch"]
    enabled = json.loads(read_private(Path(bundle) / "manifest.json")).get("es_security_enabled", True)
    service["environment"]["ELASTICSEARCH_ENABLE_SECURITY"] = "true" if enabled else "false"
    if urlparse(settings_for(bundle, env_file).vector_stores.elasticsearch.elasticsearch_url).scheme == "http":
        if str(service["environment"].get("ELASTICSEARCH_ENABLE_REST_TLS", "false")).lower() in {"true", "yes"}:
            fail("configured endpoint and existing REST TLS policy conflict")
        service["environment"]["ELASTICSEARCH_ENABLE_REST_TLS"] = "false"
    # Preserve transport TLS whenever the captured configuration enables it.
    import yaml

    native = bundle_native_files(bundle, os.environ["BS_SECRET_KEYS_FILE"])
    transport_tls = False
    for filename in ("es-config/elasticsearch.yml", "es-config/my_elasticsearch.yml"):
        conf = yaml.safe_load(native.get(filename, b"{}")) or {}
        transport_tls = (
            transport_tls
            or conf.get("xpack.security.transport.ssl.enabled") is True
            or conf.get("xpack", {}).get("security", {}).get("transport", {}).get("ssl", {}).get("enabled") is True
        )
    service["environment"]["ELASTICSEARCH_SKIP_TRANSPORT_TLS"] = "no" if transport_tls else "yes"
    service["healthcheck"] = {
        "test": ["CMD", "bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/9200"],
        "start_period": "30s",
        "interval": "5s",
        "timeout": "3s",
        "retries": 60,
    }
    # Mount the exact original image, independent of mutable registry tags.
    service["image"] = container["Image"]
    result["images"] = {}
    return inventory, result


def compile_current(bundle, inspect_stream, secret_gid, env_file=None):
    return _compile_current(bundle, inspect_stream, secret_gid, env_file)[1]["compose"]


def compile_es(session, key_file, inspect_stream, secret_gid, env_file=None):
    value = _state(session, key_file)
    if value["es"]["phase"] != "FROZEN":
        fail("capture must follow a frozen source baseline")
    inventory, result = _compile_current(value["bundle"], inspect_stream, secret_gid, env_file)
    value["es"]["runtime"] = _seal_record(session, {"original": inventory, "compiled": result}, key_file, "es-runtime")
    _save(session, value, key_file)
    return result["compose"]


def export_es(session, key_file):
    value = _state(session, key_file)
    if not value["es"].get("runtime"):
        fail("runtime capture required before export")
    record = _record(session, value["es"]["runtime"], key_file)
    return record["compiled"]["compose"]


def prepare_rollback(session, key_file):
    """Prepare a paired security-mode return without restoring any data files."""
    from bisheng.core.config.credential_runtime_compose import apply_runtime
    from bisheng.core.config.credential_sealed_migration import _inventory

    value = _state(session, key_file)
    es = value["es"]
    if (
        es["mode"] != "enable"
        or es["phase"] not in {"FROZEN", "PASSWORD_INTENT", "PASSWORD_SET", "VERIFIED"}
        or value["phase"] == "COMPLETE"
    ):
        fail("paired return requires an incomplete verified enable plan")
    inventory = _inventory(session, value, key_file)
    runtime = _record(session, es["runtime"], key_file)
    native = bundle_native_files(value["bundle"], key_file)
    native["elasticsearch.password"] = inventory["original_credentials"].get("elasticsearch", "").encode()
    native.pop("telemetry_elasticsearch.password", None)
    rewrite_security_config(native, False)
    target = Path(session) / ("rollback-" + uuid.uuid4().hex)
    target.mkdir(mode=0o700)
    original = inventory["original_document"]
    write_private_atomic(target / "config.yaml", dump_document(original).encode())
    manifest = json.loads(read_private(Path(value["bundle"]) / "manifest.json"))
    manifest.update(revision=uuid.uuid4().hex, es_security_enabled=False)
    manifest.update(write_bundle_native(target, native))
    write_private_atomic(target / "manifest.json", json.dumps(manifest).encode())
    inventory["credentials"] = inventory["original_credentials"]
    inventory_ref = _seal_record(session, inventory, key_file, "rollback-inventory")
    value.update(
        bundle=str(target),
        phase="SEALED",
        inventory_file=inventory_ref["file"],
        inventory_sha256=inventory_ref["sha256"],
    )
    # Reuse verified source mounts, resources, image and TLS policy. No data rollback.
    compiled = runtime["compiled"]
    service = apply_runtime(
        compiled["compose"]["services"]["elasticsearch"],
        "elasticsearch",
        bundle=str(target),
        deployment=manifest["deployment_id"],
        revision=manifest["revision"],
    )
    service["environment"]["ELASTICSEARCH_ENABLE_SECURITY"] = "false"
    compiled["compose"]["services"]["elasticsearch"] = service
    runtime["compiled"] = compiled
    es.update(mode="retain", phase="FROZEN", runtime=_seal_record(session, runtime, key_file, "rollback-runtime"))
    _save(session, value, key_file)
