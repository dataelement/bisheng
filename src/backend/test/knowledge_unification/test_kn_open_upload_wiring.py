"""The existing open-protocol constructors preserve the resolved operator."""

import importlib

import pytest
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload


@pytest.mark.parametrize(
    "module_name,builder",
    [
        ("bisheng.open_endpoints.api.endpoints.filelib", "_build_space_service"),
        ("bisheng.open_mcp.application", "_space_service"),
    ],
)
def test_actual_open_factory_preserves_operator_and_uses_fresh_upload_application(module_name, builder):
    module = importlib.import_module(module_name)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    versions, documents = object(), object()
    service = getattr(module, builder)(Request({"type": "http", "headers": []}), user, versions, documents)
    first, second = service.upload_application_factory(), service.upload_application_factory()
    assert first is not second and first.repository is not second.repository
    assert first.user is user and service.login_user is user
    assert first.sessions is module.get_async_db_session
    assert first.admit == service._require_action
    assert first.make_record == service._new_file_permission_record
    assert first.actor_provider == service._permission_actor
    assert service.version_repo is versions and service.doc_repo is documents
