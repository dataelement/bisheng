"""F048 preview, download, and RAG action separation."""

from __future__ import annotations

import pytest

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionFGAUnavailableError,
)
from bisheng.knowledge.api.endpoints.knowledge import (
    FILE_DOWNLOAD_PERMISSION_ACTION,
    FILE_PREVIEW_PERMISSION_ACTION,
)
from bisheng.knowledge.api.endpoints.knowledge_space import (
    SPACE_FILE_DOWNLOAD_PERMISSION_ACTION,
    SPACE_FILE_PREVIEW_PERMISSION_ACTION,
)
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    KnowledgeFileDeliveryAuthorizationPort,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _Adapter:
    def __init__(self) -> None:
        self.calls = []
        self.allowed = True
        self.error: Exception | None = None

    async def check_action(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.allowed


def _actor() -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=5)


def test_preview_routes_have_no_permission_action() -> None:
    assert FILE_PREVIEW_PERMISSION_ACTION is None
    assert SPACE_FILE_PREVIEW_PERMISSION_ACTION is None
    assert FILE_DOWNLOAD_PERMISSION_ACTION == "download"
    assert SPACE_FILE_DOWNLOAD_PERMISSION_ACTION == "download"


@pytest.mark.asyncio
async def test_preview_does_not_call_permission_action() -> None:
    files = _Adapter()
    libraries = _Adapter()
    port = KnowledgeFileDeliveryAuthorizationPort(
        file_permissions=files,
        library_permissions=libraries,
    )

    await port.preview(resource_id="101", actor=_actor())

    assert files.calls == []
    assert libraries.calls == []


@pytest.mark.asyncio
async def test_original_and_batch_download_require_exact_download_action() -> None:
    files = _Adapter()
    port = KnowledgeFileDeliveryAuthorizationPort(
        file_permissions=files,
        library_permissions=_Adapter(),
    )

    await port.require_download(
        resource_type="knowledge_file",
        resource_id="101",
        actor=_actor(),
    )
    await port.require_batch_download(
        resources=(
            ("folder", "20"),
            ("knowledge_file", "102"),
        ),
        actor=_actor(),
    )

    assert [(call["resource_type"], call["resource_id"], call["action"]) for call in files.calls] == [
        ("knowledge_file", "101", "download"),
        ("folder", "20", "download"),
        ("knowledge_file", "102", "download"),
    ]


@pytest.mark.asyncio
async def test_visible_or_preview_never_substitutes_for_download() -> None:
    files = _Adapter()
    files.allowed = False
    port = KnowledgeFileDeliveryAuthorizationPort(
        file_permissions=files,
        library_permissions=_Adapter(),
    )

    await port.preview(resource_id="101", actor=_actor())
    with pytest.raises(PermissionDeniedError):
        await port.require_download(
            resource_type="knowledge_file",
            resource_id="101",
            actor=_actor(),
        )

    assert len(files.calls) == 1
    assert files.calls[0]["action"] == "download"


@pytest.mark.asyncio
async def test_rag_uses_library_use_and_fga_failures_propagate() -> None:
    files = _Adapter()
    libraries = _Adapter()
    port = KnowledgeFileDeliveryAuthorizationPort(
        file_permissions=files,
        library_permissions=libraries,
    )

    await port.require_rag_use(library_id="71", actor=_actor())
    assert libraries.calls[0]["action"] == "use"

    files.error = PermissionFGAUnavailableError()
    with pytest.raises(PermissionFGAUnavailableError):
        await port.require_download(
            resource_type="knowledge_file",
            resource_id="101",
            actor=_actor(),
        )
