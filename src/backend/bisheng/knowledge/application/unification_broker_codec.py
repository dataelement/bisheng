"""Closed broker configuration and JSON protocols; no transport or execution."""

import base64
import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from uuid import UUID

from kombu.utils.url import parse_url

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.repositories.unification_task_repository import task_digest

MAX_BYTES = 16 * 1024 * 1024
PREFIX = "bisheng.worker.knowledge."
_CONTROLS = {
    "scheduler.trigger_dispatch_task",
    "scheduler.reconcile_file_scheduler_task",
    "processing_jobs.dispatch_pending_processing_jobs",
    "space_delete.dispatch_pending_deletes",
    "stale_projection_reconciler.reconcile_stale_parent_projections",
    "knowledge_chat_history_retention.rehome_knowledge_chat_sessions",
}
_FILE_TASKS = {
    "file_worker.parse_knowledge_file_celery",
    "file_worker.retry_knowledge_file_celery",
    "rebuild_knowledge_worker.rebuild_knowledge_file_chunk",
}
_REBUILDS = {"rebuild_knowledge_worker.rebuild_knowledge_celery", "qa.rebuild_qa_knowledge_celery"}
TASKS = frozenset(
    PREFIX + name
    for name in _CONTROLS
    | _FILE_TASKS
    | _REBUILDS
    | {
        "file_worker.file_copy_celery",
        "file_worker.delete_knowledge_file_celery",
        "move_worker.migrate_file_vectors",
        "qa.insert_qa_celery",
        "qa.copy_qa_knowledge_celery",
        "processing_jobs.execute_processing_job",
        "space_delete.purge_space_delete",
    }
)
_CONNECTION_OPTIONS = {
    "socket_timeout",
    "socket_connect_timeout",
    "socket_keepalive",
    "socket_keepalive_options",
    "health_check_interval",
    "retry_on_timeout",
    "max_connections",
}
_ALLOWED_OPTIONS = _CONNECTION_OPTIONS | {
    "global_keyprefix",
    "sep",
    "priority_steps",
    "unacked_key",
    "unacked_index_key",
    "unacked_mutex_key",
    "master_name",
    "sentinel_kwargs",
    "min_other_sentinels",
    "visibility_timeout",
    "unacked_mutex_expire",
    "unacked_restore_limit",
    "queue_order_strategy",
    "body_encoding",
    "ack_emulation",
}
_SSL_OPTIONS = {
    "ssl_cert_reqs",
    "ssl_ca_certs",
    "ssl_ca_data",
    "ssl_certfile",
    "ssl_keyfile",
    "ssl_check_hostname",
    "ssl_password",
}


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_broker_{reason}")


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _blocked("unsupported_configuration")


def _url(value):
    if type(value) is not str or not value:
        _blocked("redis_transport_required")
    parts = value.split(";")
    parsed = [urlsplit(part) for part in parts]
    if any(part.scheme not in {"redis", "rediss", "sentinel"} or not part.hostname for part in parsed):
        _blocked("redis_transport_required")
    mode = parsed[0].scheme
    if any(part.scheme != mode for part in parsed) or (len(parsed) > 1 and mode != "sentinel"):
        _blocked("multiple_brokers_unsupported")
    identities, databases = [], []
    for part in parsed:
        query = parse_qs(part.query, strict_parsing=True)
        database = query.get("db", [part.path.lstrip("/") or "0"])
        if len(database) != 1 or not database[0].isascii() or not database[0].isdecimal():
            _blocked("invalid_database")
        databases.append(int(database[0]))
        identities.append(
            (part.scheme, part.hostname, part.port or (26379 if mode == "sentinel" else 6379), int(database[0]))
        )
    if len(set(databases)) != 1:
        _blocked("multiple_brokers_unsupported")
    return mode, tuple(sorted(identities)), parsed, databases[0]


@dataclass(frozen=True, slots=True)
class BrokerReadConfiguration:
    mode: str
    _connection_json: str = field(repr=False)
    queues: tuple[str, ...] = field(repr=False)
    global_keyprefix: str = field(repr=False)
    sep: str = field(repr=False)
    priority_steps: tuple[int, ...]
    unacked_key: str = field(repr=False)
    unacked_index_key: str = field(repr=False)
    unacked_mutex_key: str = field(repr=False)
    fingerprint: str

    def connection_options(self):
        return json.loads(self._connection_json)

    @classmethod
    def from_conf(cls, conf, *, ocr_queue="ocr_celery"):
        try:
            original = getattr(conf, "broker_url", None)
            read = getattr(conf, "broker_read_url", None) or original
            write = getattr(conf, "broker_write_url", None) or original
            mode, identity, parsed, database = _url(read)
            driver = getattr(conf, "broker_transport", None)
            if driver is not None and driver != mode:
                _blocked("unsupported_transport_driver")
            if _url(write)[:2] != (mode, identity):
                _blocked("read_write_broker_mismatch")
            options = getattr(conf, "broker_transport_options", None) or {}
            if type(options) is not dict or set(options) - _ALLOWED_OPTIONS:
                _blocked("unsupported_transport_options")
            options = json.loads(_canonical(options))
            if options.get("ack_emulation", True) is not True or options.get("body_encoding", "base64") != "base64":
                _blocked("unsupported_transport_options")
            prefix, sep = options.get("global_keyprefix", ""), options.get("sep", "\x06\x16")
            steps = options.get("priority_steps", [0, 3, 6, 9])
            if (
                type(prefix) is not str
                or "\x00" in prefix
                or type(sep) is not str
                or not sep
                or type(steps) is not list
                or not steps
                or steps[0] != 0
                or any(type(step) is not int or not 0 <= step <= 9 for step in steps)
                or sorted(set(steps)) != steps
            ):
                _blocked("invalid_key_configuration")
            keys = tuple(
                options.get(name, default)
                for name, default in (
                    ("unacked_key", "unacked"),
                    ("unacked_index_key", "unacked_index"),
                    ("unacked_mutex_key", "unacked_mutex"),
                )
            )
            if any(type(key) is not str or not key or "\x00" in key for key in keys):
                _blocked("invalid_key_configuration")
            connection = {key: options[key] for key in _CONNECTION_OPTIONS if key in options}
            if mode == "sentinel":
                master = options.get("master_name")
                if type(master) is not str or not master:
                    _blocked("sentinel_master_required")
                credentials = {(part.username, part.password) for part in parsed}
                if len(credentials) != 1:
                    _blocked("sentinel_credentials_mismatch")
                user, password = next(iter(credentials))
                connection.update(
                    sentinels=[[part.hostname, part.port or 26379] for part in parsed],
                    master_name=master,
                    db=database,
                    username=unquote(user) if user is not None else None,
                    password=unquote(password) if password is not None else None,
                    sentinel_kwargs=options.get("sentinel_kwargs", {}),
                    min_other_sentinels=options.get("min_other_sentinels", 0),
                )
            else:
                if {"master_name", "sentinel_kwargs", "min_other_sentinels"} & set(options):
                    _blocked("unsupported_transport_options")
                connection["url"] = read
            # Kombu's pure URL parser supplies the actual SSL query coercions.
            # No Connection/Channel is constructed and no decoder is invoked.
            tls = parse_url(read.split(";")[0]).get("ssl", getattr(conf, "broker_use_ssl", None))
            if tls is True or (tls is not None and tls is not False and type(tls) is not dict):
                _blocked("ambiguous_ssl_configuration")
            if not tls and mode == "rediss":
                tls = {"ssl_cert_reqs": 0}  # Original Kombu rediss default.
            if tls:
                if set(tls) - _SSL_OPTIONS:
                    _blocked("unsupported_ssl_options")
                connection.update(json.loads(_canonical(tls)))
                if mode == "sentinel":
                    connection["ssl"] = True
                else:
                    uri = urlsplit(read)
                    query = urlencode(
                        [(key, value) for key, value in parse_qsl(uri.query) if not key.startswith("ssl_")]
                    )
                    connection["url"] = urlunsplit(("rediss", uri.netloc, uri.path, query, uri.fragment))
            routes = getattr(conf, "task_routes", None) or {}
            if type(routes) is not dict:
                _blocked("static_routes_required")
            queues = {"knowledge_celery", getattr(conf, "task_default_queue", None) or "celery", ocr_queue}
            for pattern, route in routes.items():
                if type(pattern) is not str:
                    _blocked("static_routes_required")
                if any(fnmatch.fnmatchcase(name, pattern) for name in TASKS):
                    route = {"queue": route} if type(route) is str else route
                    if type(route) is not dict or route.get("exchange_type", "direct") not in {"direct", "topic"}:
                        _blocked("static_routes_required")
                    if route.get("queue"):
                        queues.add(route["queue"])
            if any(type(queue) is not str or not queue or "\x00" in queue for queue in queues):
                _blocked("invalid_queue_name")
            return cls(
                mode,
                _canonical(connection),
                tuple(sorted(queues)),
                prefix,
                sep,
                tuple(steps),
                *keys,
                task_digest(
                    {
                        "read": read,
                        "write": write,
                        "options": options,
                        "driver": driver,
                        "ssl": tls,
                        "queues": sorted(queues),
                    }
                ),
            )
        except KnowledgeOperationPlanConflictError:
            raise
        except (ValueError, TypeError, AttributeError, UnicodeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_broker_unsupported_configuration") from error


@dataclass(frozen=True, slots=True)
class DecodedKnowledgeMessage:
    task_name: str
    message_id: str
    header_tenant_id: int | None
    scope_kind: str
    target_ids: tuple[int | str, ...] = field(repr=False)
    space_id: int | None
    source_space_id: int | None
    operation_id: str | None
    expected_revision: int | None
    expected_generation: str | None
    legacy_requires_reissue: bool
    configuration_digest: str
    raw_digest: str


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _blocked("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value: _blocked("nonfinite_json"))


def _positive(value):
    if type(value) is not int or value <= 0:
        _blocked("invalid_target_id")
    return value


def _string_id(value):
    if type(value) is not str or not value or len(value) > 128 or "\x00" in value:
        _blocked("invalid_message_identity")
    return value


def _bind(args, kwargs, names, defaults=None, *, keyword_only=()):
    defaults = defaults or {}
    if len(args) > len(names) or set(kwargs) - (set(names) | set(keyword_only)):
        _blocked("unknown_task_signature")
    values = dict(zip(names, args, strict=False))
    if values.keys() & kwargs.keys():
        _blocked("duplicate_task_argument")
    values.update(kwargs)
    for name in (*names, *keyword_only):
        if name not in values:
            if name not in defaults:
                _blocked("missing_task_argument")
            values[name] = defaults[name]
    return values


def _scope(name, args, kwargs):
    short = name[len(PREFIX) :]
    kind, targets, space, source, operation, revision, generation, legacy = (
        "global",
        (),
        None,
        None,
        None,
        None,
        None,
        False,
    )
    if short in _FILE_TASKS:
        names = (
            ("file_id",)
            if short.endswith("rebuild_knowledge_file_chunk")
            else ("file_id", "preview_cache_key", "callback_url")
        )
        values = _bind(args, kwargs, names, {"preview_cache_key": None, "callback_url": None})
        kind, targets = "files", (_positive(values["file_id"]),)
    elif short == "file_worker.delete_knowledge_file_celery":
        values = _bind(args, kwargs, ("file_ids", "knowledge_id", "clear_minio"), {"clear_minio": True})
        if type(values["file_ids"]) is not list:
            _blocked("invalid_target_ids")
        kind, targets, space = (
            "files",
            tuple(_positive(ident) for ident in values["file_ids"]),
            _positive(values["knowledge_id"]),
        )
    elif short == "move_worker.migrate_file_vectors":
        values = _bind(args, kwargs, ("file_id", "source_space_id"))
        kind, targets, source = "move", (_positive(values["file_id"]),), _positive(values["source_space_id"])
    elif short in {"file_worker.file_copy_celery", "qa.copy_qa_knowledge_celery"}:
        if short.startswith("file_worker"):
            values = _bind(args, kwargs, ("param",))["param"]
            if type(values) is not dict or not {"source_knowledge_id", "target_id", "login_user_id"} <= values.keys():
                _blocked("unknown_copy_signature")
            source, space = _positive(values["source_knowledge_id"]), _positive(values["target_id"])
        else:
            values = _bind(args, kwargs, ("source_knowledge_id", "target_knowledge_id", "login_user_id"))
            source, space = _positive(values["source_knowledge_id"]), _positive(values["target_knowledge_id"])
        kind, targets = "spaces", (source, space)
    elif short in _REBUILDS:
        hint = "embedding_model_id" if short.startswith("qa.") else "new_model_id"
        proof = ("operation_id", "expected_model_config_revision", "expected_index_generation")
        values = _bind(args, kwargs, ("knowledge_id", hint, "invoke_user_id"), dict.fromkeys(proof), keyword_only=proof)
        kind, space = "spaces", _positive(values["knowledge_id"])
        targets = (space,)
        operation, revision, generation = (values[key] for key in proof)
        legacy = not (
            type(operation) is str
            and bool(operation)
            and type(revision) is int
            and revision >= 0
            and "expected_index_generation" in kwargs
            and (generation is None or (type(generation) is str and bool(generation)))
        )
        if legacy:
            operation, revision, generation = None, None, None
    elif short == "processing_jobs.execute_processing_job":
        values = _bind(args, kwargs, ("job_id", "expected_dispatch_revision"))
        kind, targets, revision = "jobs", (_string_id(values["job_id"]),), values["expected_dispatch_revision"]
        if type(revision) is not int or revision < 0:
            _blocked("invalid_dispatch_revision")
    elif short == "space_delete.purge_space_delete":
        values = _bind(args, kwargs, (), keyword_only=("job_id",))
        kind, targets = "delete_jobs", (_string_id(values["job_id"]),)
    elif short == "qa.insert_qa_celery":
        values = _bind(args, kwargs, ("qa_id",))
        kind, targets = "qa", (_positive(values["qa_id"]),)
    elif short == "knowledge_chat_history_retention.rehome_knowledge_chat_sessions":
        _bind(args, kwargs, (), keyword_only=("source_space_id", "source_flow_ids", "reason", "dispatched_at_ms"))
    elif short in _CONTROLS:
        _bind(args, kwargs, ())
    else:
        _blocked("unknown_knowledge_task")
    return kind, targets, space, source, operation, revision, generation, legacy


def decode_broker_message(raw, *, required=True):
    if type(raw) is str:
        raw = raw.encode("utf-8")
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        _blocked("message_size_or_type")
    try:
        value = _parse(raw.decode("utf-8"))
    except (ValueError, UnicodeError, KnowledgeOperationPlanConflictError) as error:
        if not required:
            return None
        raise KnowledgeOperationPlanConflictError(reason="migration_broker_invalid_envelope") from error
    return _decode_envelope(value, hashlib.sha256(raw).hexdigest(), required=required)


def _pidbox_reply(headers, properties, body):
    """Recognize Kombu's control reply protocol, without treating it as a task."""
    delivery = properties.get("delivery_info")
    if (
        set(headers) != {"ticket", "clock"}
        or type(headers["clock"]) is not int
        or headers["clock"] < 0
        or type(delivery) is not dict
        or set(delivery) != {"exchange", "routing_key"}
        or delivery["exchange"] != "reply.celery.pidbox"
        or not body
        or any(type(key) is not str or not key for key in body)
        or {"task", "id", "args", "kwargs", "callbacks", "errbacks", "chord"} & body.keys()
    ):
        return False
    for value in (headers["ticket"], delivery["routing_key"]):
        if type(value) is not str:
            return False
        try:
            if str(UUID(value)) != value:
                return False
        except ValueError:
            return False
    return True


def _decode_envelope(value, raw_digest, *, required=True):
    envelope = {"body", "headers", "properties", "content-type", "content-encoding"}
    if (
        type(value) is not dict
        or not envelope <= value.keys()
        or type(value["headers"]) is not dict
        or type(value["properties"]) is not dict
    ):
        if not required:
            return None
        _blocked("invalid_envelope")
    headers, properties = value["headers"], value["properties"]
    name = headers.get("task")
    if type(name) is str and not name.startswith(PREFIX):
        return None  # Proven non-knowledge task; its business body is not ours.
    if (
        value["content-type"] != "application/json"
        or value["content-encoding"] != "utf-8"
        or headers.get("compression") is not None
    ):
        _blocked("unsupported_message_encoding")
    if properties.get("body_encoding") != "base64" or type(value["body"]) is not str:
        _blocked("unsupported_body_encoding")
    try:
        body_bytes = base64.b64decode(value["body"], validate=True)
        if len(body_bytes) > MAX_BYTES:
            _blocked("message_size_or_type")
        body = _parse(body_bytes.decode("utf-8"))
        if type(body) is dict and name is None:
            if _pidbox_reply(headers, properties, body):
                return None
            name, ident, args, kwargs = body.get("task"), body.get("id"), body.get("args"), body.get("kwargs")
            canvas = [body.get(key) for key in ("callbacks", "errbacks", "chord")]
        elif type(body) is list and len(body) == 3:
            ident, args, kwargs = headers.get("id"), body[0], body[1]
            if type(body[2]) is not dict:
                _blocked("invalid_canvas")
            canvas = list(body[2].values())
        else:
            _blocked("invalid_task_protocol")
        if type(name) is not str:
            _blocked("unknown_task_identity")
        if not name.startswith(PREFIX):
            return None
        if (
            name not in TASKS
            or type(args) is not list
            or type(kwargs) is not dict
            or any(item is not None and not (type(item) in (list, dict) and not item) for item in canvas)
        ):
            _blocked("unsupported_knowledge_signature")
        tenant = headers.get("tenant_id")
        if tenant is not None:
            if type(tenant) is str and tenant.isascii() and tenant.isdecimal():
                tenant = int(tenant)
            _positive(tenant)
        scope = _scope(name, args, kwargs)
        return DecodedKnowledgeMessage(
            name,
            _string_id(ident),
            tenant,
            *scope,
            task_digest({"headers": headers, "properties": properties, "body": body}),
            raw_digest,
        )
    except KnowledgeOperationPlanConflictError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_broker_invalid_message") from error


def decode_unacked_message(raw):
    if type(raw) is str:
        raw = raw.encode("utf-8")
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        _blocked("message_size_or_type")
    try:
        value = _parse(raw.decode("utf-8"))
        if (
            type(value) is not list
            or len(value) != 3
            or type(value[0]) is not dict
            or type(value[1]) is not str
            or type(value[2]) is not str
        ):
            _blocked("invalid_unacked_tuple")
        fingerprint = hashlib.sha256(raw).hexdigest()
        return _decode_envelope(value[0], fingerprint), value[1], value[2], fingerprint
    except KnowledgeOperationPlanConflictError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_broker_invalid_unacked_tuple") from error
