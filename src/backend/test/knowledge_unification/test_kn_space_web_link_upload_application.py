"""Real web initial chains and two owned objects; isolate only IO transports."""

import asyncio
import importlib
import json
from dataclasses import replace

import pytest
import sqlalchemy as sa

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.context import tenant as context
from bisheng.knowledge.application.file_processing_adapter import legacy_rule_from_snapshot
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from test.knowledge_unification import test_kn_space_upload_application as original

native = original.native
database = original.database
case = original.case


@pytest.fixture
def web(case, monkeypatch):
    application = original.app(case, monkeypatch)
    materials = importlib.import_module("bisheng.knowledge.application.web_link_upload")
    monkeypatch.setattr(
        materials, "KnowledgeUtils", case.utils
    )  # Real source_module Utils, never the test placeholder.
    snapshot = case.utils.processing_snapshot_for_legacy_request(
        FileProcessBase(knowledge_id=9700), knowledge=case.knowledge, file_name="原网页.html", file_source="web_link"
    )
    rule = legacy_rule_from_snapshot(snapshot, space_id=9700).model_dump(mode="json")
    rule["_effective_processing"] = snapshot.model_dump(mode="json")
    prepared = materials.PreparedWebLink(
        file_name="原网页.html",
        content_hash="b" * 64,
        markdown_bytes="# 原正文\n".encode(),
        html_snapshot_bytes=b"<html>original</html>",
        split_rule=json.dumps(rule, ensure_ascii=False),
        user_metadata={
            "source_type": "web_link",
            "source_url": "https://private.invalid/source",
            "final_url": "https://private.invalid/final",
            "web_title": "原网页.html",
            "imported_at": "original-time",
            "html_snapshot_object_name": "foreign/input-key",
        },
    )
    case.web_calls, case.web_fail, case.web_hook, case.web_removes = [], None, None, []

    def put(**kwargs):
        case.io("put")
        case.web_calls.append(kwargs)
        hit = case.web_fail and len(case.web_calls) == case.web_fail[0]
        if hit and case.web_fail[1] == "before":
            raise case.web_fail[2]
        case.blobs[kwargs["object_name"]] = kwargs["file"]
        if case.web_hook:
            case.web_hook()
        if hit:
            raise case.web_fail[2]

    def remove(**kwargs):
        case.io("remove")
        # No attempted object may be removed before all three SQL rows are gone.
        assert case.commit_count >= 2
        case.web_removes.append(kwargs["object_name"])
        case.blobs.pop(kwargs["object_name"], None)

    case.storage.put_object_sync, case.storage.remove_object_sync = put, remove
    return application, prepared


async def create(web, case, *, parent=None, prepared=None):
    application, original_prepared = web
    return await application.acreate_web_link(
        knowledge=case.knowledge, parent_id=parent, prepared=prepared or original_prepared
    )


@pytest.mark.parametrize("parent", [None, 11])
async def test_web_uses_actual_native_v1_materialized_metadata_and_original_container_gate(web, case, parent):
    result = await create(web, case, parent=parent)
    prepared = web[1]
    after = await original.original.snapshot(case.database)
    file, doc, version = original.new_rows(after, result.id)
    assert (file["file_name"], file["file_size"], file["md5"], file["split_rule"], file["file_source"]) == (
        prepared.file_name,
        len(prepared.markdown_bytes),
        prepared.content_hash,
        prepared.split_rule,
        "web_link",
    )
    assert file["object_name"] == f"original/{result.id}.md"
    assert file["user_metadata"] == {**prepared.user_metadata, "html_snapshot_object_name": f"preview/{result.id}.html"}
    assert (file["file_level_path"], doc["file_level_path"]) == (("/10/11", "/10/11") if parent else ("", ""))
    assert version["is_primary"] and version["version_no"] == 1
    assert [(call["object_name"], call["content_type"], call["file"]) for call in case.web_calls] == [
        (file["object_name"], "text/markdown; charset=utf-8", prepared.markdown_bytes),
        (f"preview/{result.id}.html", "text/html; charset=utf-8", prepared.html_snapshot_bytes),
    ]
    assert case.events == [
        ("folder" if parent else "knowledge_space", parent or 9700, "upload_file"),
        "put",
        "put",
        "project",
    ]
    assert not case.active and all(not session.in_transaction() for session in case.sessions)


async def test_empty_html_keeps_metadata_key_but_only_attempts_and_cleans_markdown(web, case):
    application, prepared = web
    result = await create(web, case, prepared=replace(prepared, html_snapshot_bytes=b""))
    assert result.user_metadata["html_snapshot_object_name"] == f"preview/{result.id}.html"
    case.blobs[f"preview/{result.id}.html"] = b"not owned or attempted"
    await application.arollback_created()
    assert case.web_removes == [f"original/{result.id}.md"]
    assert case.blobs == {f"preview/{result.id}.html": b"not owned or attempted"}


@pytest.mark.parametrize("position", [1, 2])
@pytest.mark.parametrize("when", ["before", "after"])
async def test_each_put_failure_unwinds_only_attempted_keys_after_sql_delete_ack(web, case, position, when):
    application = web[0]
    before = await original.original.snapshot(case.database)
    failure = OSError("controlled web PUT failure")
    case.web_fail = (position, when, failure)
    with pytest.raises(OSError) as caught:
        await create(web, case)
    assert caught.value is failure and len(case.web_calls) == position
    await application.arollback_created()
    assert await original.original.snapshot(case.database) == before
    assert case.web_removes == list(reversed([call["object_name"] for call in case.web_calls]))
    assert not case.blobs


async def test_projection_failure_and_cancel_preserve_original_failure_and_own_two_objects(web, case):
    application = web[0]
    before = await original.original.snapshot(case.database)
    case.fail = "cancel:project"
    with pytest.raises(asyncio.CancelledError):
        await create(web, case)
    case.fail = None
    await application.arollback_created()
    assert len(case.web_calls) == len(case.web_removes) == 2
    assert await original.original.snapshot(case.database) == before and not case.blobs


async def test_cancel_during_html_put_keeps_both_attempted_keys_for_bounded_cleanup(web, case):
    application = web[0]
    failure = asyncio.CancelledError("cancelled HTML PUT")
    case.web_fail = (2, "after", failure)
    with pytest.raises(asyncio.CancelledError) as caught:
        await create(web, case)
    assert caught.value is failure
    await application.arollback_created()
    assert len(case.web_removes) == 2 and not case.blobs


@pytest.mark.parametrize("position", ["before", "after"])
async def test_native_commit_unknown_never_puts_projects_or_authorizes_cleanup(web, case, position):
    case.fail_commit = (1, position)
    with pytest.raises(OSError) as caught:
        await create(web, case)
    assert not case.web_calls and not case.blobs
    case.adapter._permission.authorize_created.assert_not_awaited()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await web[0].arollback_created()
    assert "private.invalid" not in repr(caught.value.space_upload_progress)
    assert web[1].split_rule not in repr(caught.value.space_upload_progress)


async def test_delete_commit_unknown_preserves_both_objects_even_when_sql_delete_ran(web, case):
    result = await create(web, case)
    case.fail_commit = (2, "after")
    with pytest.raises(OSError):
        await web[0].arollback_created()
    assert not case.web_removes and len(case.blobs) == 2
    after = await original.original.snapshot(case.database)
    assert not any(row["id"] == result.id for row in after["knowledgefile"])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await web[0].arollback_created()
    assert not case.web_removes


@pytest.mark.parametrize("field", ["object_name", "metadata"])
async def test_mutable_returned_file_cannot_redirect_owned_cleanup(web, case, field):
    result = await create(web, case)
    case.blobs["foreign/key"] = b"must remain"
    if field == "object_name":
        result.object_name = "foreign/key"
    else:
        result.user_metadata["html_snapshot_object_name"] = "foreign/key"
    before = await original.original.snapshot(case.database)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await web[0].arollback_created()
    assert not case.web_removes and case.blobs["foreign/key"] == b"must remain"
    assert await original.original.snapshot(case.database) == before


async def test_prepared_metadata_mutation_cannot_change_frozen_actual_attempted_keys(web, case):
    result = await create(web, case)
    web[1].user_metadata["html_snapshot_object_name"] = "foreign/key"
    await web[0].arollback_created()
    assert case.web_removes == [f"preview/{result.id}.html", f"original/{result.id}.md"]


async def test_identity_is_rechecked_between_the_two_puts(web, case):
    token = context.set_current_tenant_id(101)
    case.web_hook = lambda: context.set_current_tenant_id(202)
    try:
        with pytest.raises(ResourceReferenceInvalidError):
            await create(web, case)
        assert len(case.web_calls) == 1
    finally:
        context.current_tenant_id.reset(token)
    await web[0].arollback_created()
    assert len(case.web_removes) == 1


async def test_visible_only_cannot_register_a_web_chain(web, case):
    case.allowed = {"visible"}
    case.database.queries.clear()
    with pytest.raises(SpacePermissionDeniedError):
        await create(web, case)
    assert not case.sessions and not case.database.queries and not case.web_calls


async def test_same_transaction_materialization_failure_leaves_no_half_web_chain(web, case):
    before = await original.original.snapshot(case.database)

    def fail(_conn, _cursor, sql, _params, _context, _many):
        if sql.startswith("UPDATE knowledgefile"):
            raise RuntimeError("native materialization failure")

    sa.event.listen(case.database.engine.sync_engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="native materialization failure"):
            await create(web, case)
    finally:
        sa.event.remove(case.database.engine.sync_engine, "after_cursor_execute", fail)
    assert await original.original.snapshot(case.database) == before and not case.web_calls


async def test_selected_super_web_creation_preserves_original_home_and_current_pin(web, case):
    case.user.tenant_id, case.user.is_global_super = 1, True
    case.actor = PermissionActor(user_id=7, tenant_id=1, super_admin=True)
    actor_token = set_current_permission_actor(case.actor)
    flag, pin = context.set_is_management_api(True), context.set_admin_scope_tenant_id(101)
    try:
        result = await create(web, case)
        assert result.tenant_id == 101 and case.user.tenant_id == case.actor.current_tenant_id == 1
        await web[0].arollback_created()
    finally:
        context._admin_scope_tenant_id.reset(pin)
        context._is_management_api.reset(flag)
        reset_current_permission_actor(actor_token)
