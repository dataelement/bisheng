"""T823: real Celery/Kombu encoders, without a channel or broker connection."""

import base64
import importlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from functools import lru_cache
from types import SimpleNamespace

import pytest
from kombu.utils.json import dumps as envelope_dumps

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

PREFIX = "bisheng.worker.knowledge."


@pytest.fixture
def codec():
    return importlib.import_module("bisheng.knowledge.application.unification_broker_codec")


@lru_cache(maxsize=64)
def _encoded(spec):
    # Root test infrastructure stubs celery.app. A fresh offline interpreter
    # produces the real encoder output without modifying those shared stubs.
    script = """
import json,sys
from celery.app.amqp import AMQP
from kombu.serialization import dumps
from kombu.transport.virtual.base import Base64
from kombu.utils.json import dumps as encode
spec=json.loads(sys.stdin.read())
builder=object.__new__(AMQP)
builder.utc=False
builder.argsrepr_maxsize=builder.kwargsrepr_maxsize=1024
msg=getattr(builder,'as_task_v'+str(spec['protocol']))('original-task-id',spec['task'],args=spec['args'],kwargs=spec['kwargs'])
headers=msg.headers|({'tenant_id':spec['tenant']} if spec['tenant'] is not None else {})
content,encoding,body=dumps(msg.body,serializer='json')
value={'body':Base64().encode(body),'content-encoding':encoding,'content-type':content,'headers':headers,'properties':msg.properties|{'body_encoding':'base64','delivery_tag':'original-delivery','delivery_info':{'exchange':'','routing_key':'knowledge_celery'}}}
sys.stdout.write(encode(value))
"""
    return subprocess.run([sys.executable, "-c", script], input=spec, text=True, capture_output=True, check=True).stdout


def message(
    task=PREFIX + "file_worker.parse_knowledge_file_celery",
    args=None,
    kwargs=None,
    *,
    protocol=2,
    tenant=101,
    **changes,
):
    spec = json.dumps(
        {"task": task, "args": args or [], "kwargs": kwargs or {}, "protocol": protocol, "tenant": tenant},
        sort_keys=True,
    )
    return envelope_dumps(json.loads(_encoded(spec)) | changes).encode()


def conf(**changes):
    return SimpleNamespace(
        **(
            {
                "broker_url": "redis://worker:private-pass@localhost:6379/3",
                "broker_read_url": None,
                "broker_write_url": None,
                "broker_transport_options": {},
                "task_default_queue": "celery",
                "task_routes": {PREFIX + "*": {"queue": "knowledge_custom"}},
            }
            | changes
        )
    )


@pytest.mark.parametrize("protocol", [1, 2])
async def test_real_protocols_keep_original_target_identity_and_private_digest_only(codec, protocol):
    raw = message(args=[81, "private-cache", "https://private-url/?token=private-secret"], protocol=protocol)
    actual = codec.decode_broker_message(raw)
    assert (actual.task_name, actual.message_id, actual.scope_kind, actual.target_ids, actual.header_tenant_id) == (
        PREFIX + "file_worker.parse_knowledge_file_celery",
        "original-task-id",
        "files",
        (81,),
        101,
    )
    assert len(actual.configuration_digest) == len(actual.raw_digest) == 64
    assert "private-" not in repr(actual) and not hasattr(actual, "__dict__")
    with pytest.raises(FrozenInstanceError):
        actual.message_id = "different"


def test_single_effective_read_write_identity_prefix_and_routes_are_closed(codec):
    actual = codec.BrokerReadConfiguration.from_conf(
        conf(broker_transport_options={"global_keyprefix": "tenant-broker:"})
    )
    assert actual.mode == "redis" and actual.global_keyprefix == "tenant-broker:"
    assert {"celery", "knowledge_celery", "ocr_celery", "knowledge_custom"} <= set(actual.queues)
    assert actual.priority_steps == (0, 3, 6, 9) and actual.sep == "\x06\x16"
    assert "private-pass" not in repr(actual)
    assert actual.connection_options()["url"].endswith("/3")


def test_current_builder_sentinel_and_tls_auth_are_preserved_without_connecting(codec):
    actual = codec.BrokerReadConfiguration.from_conf(
        conf(
            broker_url="sentinel://u:private-pass@a:26379/4;sentinel://u:private-pass@b:26379/4",
            broker_transport_options={
                "master_name": "actual-master",
                "sentinel_kwargs": {"password": "private-sentinel"},
                "global_keyprefix": "p:",
            },
        )
    )
    assert actual.mode == "sentinel"
    options = actual.connection_options()
    assert options["sentinels"] == [["a", 26379], ["b", 26379]]
    assert options["db"] == 4 and options["master_name"] == "actual-master"
    assert options["sentinel_kwargs"]["password"] == "private-sentinel"
    assert "private-" not in repr(actual)
    tls = codec.BrokerReadConfiguration.from_conf(conf(broker_url="rediss://u:private-pass@a:6379/4"))
    assert tls.connection_options()["url"].startswith("rediss:")


@pytest.mark.parametrize(
    "changes",
    [
        {"broker_url": None},
        {"broker_url": "amqp://localhost//"},
        {"broker_url": "redis://a/1;redis://b/1"},
        {"broker_read_url": "redis://localhost/9"},
        {"broker_transport_options": {"unknown_driver_option": True}},
        {"broker_transport_options": {"ack_emulation": False}},
        {"task_routes": lambda: None},
    ],
)
def test_unprovable_broker_configuration_is_not_an_empty_supported_source(codec, changes):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.BrokerReadConfiguration.from_conf(conf(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"content-type": "application/x-python-serialize"},
        {"content-encoding": "latin1"},
        {"body": "%%%notbase64"},
        {"headers": {"task": PREFIX + "file_worker.parse_knowledge_file_celery", "id": "id", "tenant_id": True}},
        {"headers": {"task": PREFIX + "unknown.task", "id": "id"}},
    ],
)
def test_knowledge_message_unsafe_or_unknown_protocol_is_rejected(codec, changes):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.decode_broker_message(message(args=[81], **changes))


def test_foreign_task_is_isolated_without_parsing_its_nonjson_business_body(codec):
    raw = message(task="bisheng.worker.workflow.tasks.run_workflow", body="not-json", **{"content-type": "pickle"})
    assert codec.decode_broker_message(raw) is None
    assert codec.decode_broker_message(b"ordinary chat list", required=False) is None
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.decode_broker_message(b"ordinary chat list", required=True)


@pytest.mark.parametrize(
    "task,args,kwargs,kind,ids",
    [
        ("move_worker.migrate_file_vectors", [81, 40], {}, "move", (81,)),
        (
            "file_worker.file_copy_celery",
            [{"source_knowledge_id": 40, "target_id": 50, "login_user_id": 7}],
            {},
            "spaces",
            (40, 50),
        ),
        ("file_worker.delete_knowledge_file_celery", [[81, 81, 82], 40], {}, "files", (81, 81, 82)),
        ("processing_jobs.execute_processing_job", ["job-id", 2], {}, "jobs", ("job-id",)),
        ("space_delete.purge_space_delete", [], {"job_id": "delete-id"}, "delete_jobs", ("delete-id",)),
        ("qa.insert_qa_celery", [12], {}, "qa", (12,)),
        ("scheduler.trigger_dispatch_task", [], {}, "global", ()),
    ],
)
def test_actual_registered_knowledge_signatures_keep_native_ids_without_fake_file_slots(
    codec, task, args, kwargs, kind, ids
):
    decoded = codec.decode_broker_message(message(task=PREFIX + task, args=args, kwargs=kwargs))
    assert decoded.scope_kind == kind and decoded.target_ids == ids


def test_legacy_model_hint_is_not_rewritten_into_an_operation_or_model_binding(codec):
    raw = message(task=PREFIX + "rebuild_knowledge_worker.rebuild_knowledge_celery", args=[40, 999, 7])
    decoded = codec.decode_broker_message(raw)
    assert decoded.legacy_requires_reissue and decoded.target_ids == (40,)
    assert decoded.operation_id is None and not hasattr(decoded, "model_id")
    current = codec.decode_broker_message(
        message(
            task=PREFIX + "rebuild_knowledge_worker.rebuild_knowledge_celery",
            args=[40, 999, 7],
            kwargs={
                "operation_id": "original-op",
                "expected_model_config_revision": 4,
                "expected_index_generation": "g4",
            },
        )
    )
    assert (
        not current.legacy_requires_reissue and current.expected_revision == 4 and current.expected_generation == "g4"
    )


def test_duplicate_json_nonfinite_signature_and_unfrozen_canvas_are_not_executable(codec):
    for raw in (
        b'{"body":1,"body":2}',
        b'{"number":NaN}',
        message(args=[81], kwargs={"file_id": 82}),
        message(args=[True]),
    ):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            codec.decode_broker_message(raw)
    import json

    value = json.loads(message(args=[81]))
    body = json.loads(base64.b64decode(value["body"]))
    body[2]["chain"] = [{"task": "not-executed"}]
    value["body"] = base64.b64encode(json.dumps(body).encode()).decode()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.decode_broker_message(json.dumps(value).encode())
