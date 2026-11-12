"""T431: native sharing reads use only the already READY permission runtime.

覆盖 AC: AC-68, AC-79, AC-83, AC-89
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.core.context.manager import app_context
from bisheng.permission.application import relation_api as module
from bisheng.permission.application.relation_api import PermissionRelationApplication, PermissionSubject


def test_native_accessor_does_not_initialize_an_unready_runtime(monkeypatch):
    context = SimpleNamespace(is_ready=lambda: False, sync_get_instance=Mock())
    monkeypatch.setattr(app_context, "get_context", lambda name: context)
    with pytest.raises(PermissionServiceUnavailableError) as raised:
        module.get_permission_relation_api_sync()
    assert raised.value.kwargs["reason"] == "permission_runtime_not_ready"
    context.sync_get_instance.assert_not_called()


def test_native_accessor_returns_same_ready_process_relation_application(monkeypatch):
    relations = PermissionRelationApplication(SimpleNamespace())
    process = SimpleNamespace(runtime=SimpleNamespace(components=SimpleNamespace(relations=relations)))
    context = SimpleNamespace(is_ready=lambda: True, sync_get_instance=Mock(return_value=process))
    seen = []

    def get_context(name):
        seen.append(name)
        return context

    monkeypatch.setattr(app_context, "get_context", get_context)
    assert module.get_permission_relation_api_sync() is relations
    assert seen == ["permission_runtime"]
    context.sync_get_instance.assert_called_once_with()


def test_native_application_preserves_backend_errors_and_canonical_objects():
    client = SimpleNamespace(list_objects_sync=Mock(return_value=["llm_server:11", "llm_server:11", "llm_server:12"]))
    api = PermissionRelationApplication(client)
    assert api.list_resource_ids_sync(
        subject=PermissionSubject("tenant", "101"), relation="shared_with", resource_type="llm_server"
    ) == ("11", "12")
    client.list_objects_sync.assert_called_once_with(user="tenant:101", relation="shared_with", type="llm_server")
    client.list_objects_sync.side_effect = RuntimeError("backend unavailable")
    with pytest.raises(PermissionServiceUnavailableError):
        api.list_resource_ids_sync(
            subject=PermissionSubject("tenant", "101"), relation="shared_with", resource_type="llm_server"
        )


@pytest.mark.parametrize(
    "subject,relation,resource",
    [
        (PermissionSubject("user", "7"), "shared_with", "llm_server"),
        (PermissionSubject("tenant", "101"), "visible", "llm_server"),
        (PermissionSubject("tenant", "101"), "shared_with", "workflow"),
    ],
)
def test_native_application_cannot_be_used_for_general_resource_authorization(subject, relation, resource):
    client = SimpleNamespace(list_objects_sync=Mock())
    api = PermissionRelationApplication(client)
    with pytest.raises(ValueError):
        api.list_resource_ids_sync(subject=subject, relation=relation, resource_type=resource)
    client.list_objects_sync.assert_not_called()


def test_native_accessor_distinguishes_missing_runtime_from_broken_ready_components(monkeypatch):
    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(app_context, "get_context", missing)
    with pytest.raises(PermissionServiceUnavailableError) as raised:
        module.get_permission_relation_api_sync()
    assert raised.value.kwargs["reason"] == "permission_runtime_not_ready"
    assert isinstance(raised.value.__cause__, KeyError)
    context = SimpleNamespace(
        is_ready=lambda: True,
        sync_get_instance=lambda: SimpleNamespace(runtime=SimpleNamespace(components=SimpleNamespace())),
    )
    monkeypatch.setattr(app_context, "get_context", lambda name: context)
    with pytest.raises(PermissionServiceUnavailableError) as raised:
        module.get_permission_relation_api_sync()
    assert raised.value.kwargs.get("reason") != "permission_runtime_not_ready"
