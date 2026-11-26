"""V1 contracts at the existing client routes; no Native fallback."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceCreateReq


def test_unknown_provider_is_not_ignored():
    with pytest.raises(ValidationError):
        KnowledgeSpaceCreateReq(name="test", provider_key="unknown")
    assert KnowledgeSpaceCreateReq(name="test").provider_key == "native"


def test_real_router_registers_controlled_reads_and_settings():
    paths = {r.path for r in api.router.routes}
    for suffix in ("capabilities", "settings", "files/{file_id}/content/{operation}"):
        assert "/knowledge/space/{space_id}/" + suffix in paths


async def test_external_preview_never_issues_native_original(monkeypatch):
    from bisheng.knowledge.application import provider_v1_runtime as runtime

    monkeypatch.setattr(runtime, "resolve_space_route", AsyncMock(return_value=SimpleNamespace(provider_key="weknora")))
    service = SimpleNamespace(get_file_preview=AsyncMock(), _permission_actor=AsyncMock())
    from bisheng.knowledge.application.provider_reads import ReadHandle

    reads = SimpleNamespace(issue=AsyncMock(return_value=ReadHandle(5, 6, 7, 8, 9, "preview")))
    monkeypatch.setattr(runtime, "build_provider_reads", AsyncMock(return_value=reads))
    result = await api.get_file_preview(space_id=5, file_id=6, svc=service)
    assert result.data["original_url"] == ""
    assert "/content/preview?" in result.data["preview_url"]
    assert result.data["media_kind"] == "text_excerpt"
    service.get_file_preview.assert_not_awaited()


@pytest.mark.parametrize("owner", ["kb", "other"])
async def test_preview_stream_uses_scoped_parsed_text_only(monkeypatch, owner):
    from contextlib import asynccontextmanager

    import httpx

    from bisheng.knowledge.application import provider_v1_runtime as runtime

    def upstream(req):
        assert req.url.path == "/chunks/doc" and req.url.params["chunk_type"] == "text"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "knowledge_id": "doc",
                        "knowledge_base_id": owner,
                        "tenant_id": 4,
                        "chunk_type": "text",
                        "content": "excerpt",
                    }
                ],
            },
        )

    @asynccontextmanager
    async def client(_):
        async with httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(upstream)) as c:
            yield c

    monkeypatch.setattr(runtime, "instance_client", client)
    port = runtime._PreviewExcerpt(SimpleNamespace(remote_kb_id="kb", remote_scope_id="4"))
    if owner != "kb":
        with pytest.raises(runtime.ProviderFeatureUnavailable):
            async with port.open_stream("doc"):
                pytest.fail("mismatched library")
        return
    async with port.open_stream("doc") as result:
        assert result.headers["content-type"].startswith("text/plain") and "excerpt" in result.text


async def test_provision_create_submits_managed_policy(monkeypatch):
    """A successful native WeKnora library must never be mistaken for managed."""
    from contextlib import asynccontextmanager

    from bisheng.knowledge.application import provider_provision_runtime as pr
    from bisheng.knowledge.application.provider_provisioning import Preset

    p = Preset(
        tenant_id=1,
        instance_id=2,
        scope="1",
        revision=1,
        summary="a",
        embedding="b",
        vision="v",
        chunk_size=64,
        overlap=0,
    )
    config = {
        "summary_model_id": "a",
        "embedding_model_id": "b",
        "vision_model_id": "v",
        "chunk_size": 64,
        "overlap": 0,
    }
    monkeypatch.setattr(pr, "_target", lambda op: p)

    @asynccontextmanager
    async def client(_preset):
        yield object()

    monkeypatch.setattr(pr, "_client", client)
    monkeypatch.setattr(pr, "_resolve_extract", AsyncMock(return_value=(object(), {})))
    monkeypatch.setattr(pr, "preflight", lambda *args: config)
    post = AsyncMock(return_value={})
    monkeypatch.setattr(pr, "_data", post)
    op = SimpleNamespace(
        remote_kb_id="kb",
        tenant_id=1,
        target_manifest=[{"extract_template_kb_id": "tpl", "extract_config": None}],
    )
    await pr.ProvisionRemote().create_library(op, "dept", config)
    assert post.await_args.kwargs["json"].get("model_policy") == "bisheng-v1"


async def test_native_preview_keeps_original_response(monkeypatch):
    from bisheng.knowledge.application import provider_v1_runtime as runtime

    urls = {"preview_url": "/original-native-preview"}
    monkeypatch.setattr(runtime, "resolve_space_route", AsyncMock(return_value=None))
    svc = SimpleNamespace(get_file_preview=AsyncMock(return_value=urls))
    result = await api.get_file_preview(space_id=5, file_id=6, svc=svc)
    assert result.data == urls
    svc.get_file_preview.assert_awaited_once_with(6, space_id=5)


SELECTION = {
    "summary_model_id": "s",
    "embedding_model_id": "e",
    "vision_model_id": "v",
    "chunk_size": 512,
    "overlap": 64,
    "extract_template_kb_id": "tpl",
}


async def test_weknora_create_requires_the_creators_selection(monkeypatch):
    monkeypatch.setattr(api, "_expected_provider_tenant", AsyncMock(return_value=1))
    req = KnowledgeSpaceCreateReq(name="x", provider_key="weknora", creation_request_id="k", preset_summary={})
    with pytest.raises(api.provider.ProviderFeatureUnavailable):
        await api.create_space(req, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(user_id=7))


@pytest.mark.parametrize(
    "change",
    [
        {"overlap": 512},
        {"vision_model_id": "s"},
        {"chunk_size": "512"},
        {"summary_model_id": "a/b"},
        {"extract_template_kb_id": None},
        {
            "extract_template_kb_id": "tpl",
            "extract_config": {
                "text": "t",
                "tags": ["x"],
                "nodes": [{"name": "a"}],
                "relations": [{"node1": "a", "type": "r", "node2": "a"}],
            },
        },
    ],
)
def test_provider_selection_rejects_unusable_choices(change):
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ProviderSelection

    with pytest.raises(ValidationError):
        ProviderSelection(**{**SELECTION, **change})


async def test_unavailable_model_cannot_provision_or_fall_back(monkeypatch):
    from bisheng.knowledge.application import provider_provision_runtime as pr

    monkeypatch.setattr(api, "_expected_provider_tenant", AsyncMock(return_value=1))
    provisioning = SimpleNamespace(create=AsyncMock())
    monkeypatch.setattr(pr, "build_provisioning", AsyncMock(return_value=provisioning))
    monkeypatch.setattr(pr, "load_preset", AsyncMock(side_effect=ValueError("model unavailable")))
    native = SimpleNamespace(create_knowledge_space=AsyncMock())
    req = KnowledgeSpaceCreateReq(
        name="external",
        provider_key="weknora",
        creation_request_id="contract-key",
        preset_summary={},
        provider_selection=SELECTION,
    )
    with pytest.raises(ValueError, match="model unavailable"):
        await api.create_space(req, SimpleNamespace(), native, SimpleNamespace(user_id=7))
    native.create_knowledge_space.assert_not_awaited()
    provisioning.create.assert_not_awaited()


async def test_department_request_with_provider_never_calls_native_creator(monkeypatch):
    from bisheng.knowledge.application import provider_provision_runtime as pr
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import DepartmentKnowledgeSpaceBatchCreateReq

    dept = api.DepartmentKnowledgeSpaceService
    accept, native = AsyncMock(return_value=[{"state": "pending"}]), AsyncMock()
    monkeypatch.setattr(dept, "_ensure_tenant_admin", AsyncMock())
    monkeypatch.setattr(dept, "accept_external_spaces", accept)
    monkeypatch.setattr(dept, "batch_create_spaces", native)
    monkeypatch.setattr(api, "_expected_provider_tenant", AsyncMock(return_value=1))
    monkeypatch.setattr(pr, "load_preset", AsyncMock())
    monkeypatch.setattr(pr, "build_provisioning", AsyncMock())
    result = await api.batch_create_department_spaces(
        DepartmentKnowledgeSpaceBatchCreateReq(
            provider_key="weknora",
            request_key="K",
            preset_summary={},
            provider_selection=SELECTION,
            items=[{"department_id": 12, "name": "工程"}],
        ),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    assert result.data == {"items": [{"state": "pending"}]}
    assert accept.await_args.kwargs["items"][0][0].department_id == 12
    native.assert_not_awaited()


def test_handle_contains_only_local_version_coordinates():
    from bisheng.knowledge.application.provider_reads import ReadHandle
    from bisheng.knowledge.application.provider_v1_runtime import handle_url

    assert (
        handle_url(ReadHandle(1, 2, 3, 4, 5, "download"))
        == "/api/v1/knowledge/space/1/files/2/content/download?version_id=3&generation=4&epoch=5"
    )
