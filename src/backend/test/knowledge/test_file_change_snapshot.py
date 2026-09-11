from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_file_change_snapshot_keeps_technical_path_and_adds_readable_location(monkeypatch):
    resource = SimpleNamespace(
        id=30,
        file_name="report.pdf",
        file_level_path="/10/20",
        level=2,
    )

    class _Repository:
        def __init__(self, _session) -> None:
            pass

        async def get_space(self, **_kwargs):
            return SimpleNamespace(name="Finance Space")

        async def get_formal_file(self, **_kwargs):
            return resource

        async def resolve_folder_display_path(self, *, folder_ids, **_kwargs):
            assert folder_ids == [10, 20]
            return "/Budget/Reports"

    @asynccontextmanager
    async def _session_factory():
        yield SimpleNamespace()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        _session_factory,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository.KnowledgeSpaceMutationRepository",
        _Repository,
    )
    service = KnowledgeSpaceService(
        request=SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1")),
        login_user=SimpleNamespace(user_id=7, user_name="reviewer"),
    )
    token = current_tenant_id.set(11)
    try:
        command = await service.build_file_change_command(
            action="rename",
            space_id=1,
            resource_id=30,
            resource_type="file",
            name="renamed.pdf",
        )
    finally:
        current_tenant_id.reset(token)

    assert command.action_snapshot["space_name"] == "Finance Space"
    assert command.action_snapshot["source_path"] == "/10/20"
    assert command.action_snapshot["source_display_path"] == "/Budget/Reports"
