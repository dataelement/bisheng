"""Native ordinary-batch confirmation; isolate only authorization and transport."""
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, update
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.application import processing_identity
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.application.identity import PermissionActor
from test.knowledge_unification.test_direct_delete_scope import deletion_tenant, db

@pytest.fixture
async def batch(db, monkeypatch):
    async with db.engine.begin() as conn:
        await conn.run_sync(lambda sync: Knowledge.metadata.create_all(sync, tables=[row.__table__ for row in (Tag, TagLink, KnowledgeOperationPlan)]))
    user = UserPayload(user_id=7,user_name="operator",tenant_id=101,user_role=[],is_global_super=True)
    user._runtime_credential_reference={"kind":"web_session","user_id":7,"tenant_id":101,"token_version":user.token_version,"expires_at":(datetime.now(UTC)+timedelta(days=1)).isoformat()}
    actor=PermissionActor(user_id=7,current_tenant_id=101,super_admin=True)
    monkeypatch.setattr(processing_identity,"resolve_web_runtime_identity",AsyncMock(return_value=user))
    monkeypatch.setattr(processing_identity,"resolve_permission_actor",AsyncMock(return_value=actor))
    denied,calls,dispatches=set(),[],[]
    async def permissions(identity,*,resource_type,resource_ids,actions):
        calls.append((resource_type,tuple(resource_ids),actions))
        return {str(ident):set(actions) if ident not in denied else set() for ident in resource_ids}
    async def exporter(**kwargs): return {"url":"/download.zip","failed_file_ids":[]}
    def application():
        mod=importlib.import_module("bisheng.knowledge.application.knowledge_batch")
        return mod.KnowledgeBatchApplication(session_factory=db.sessions,permission_check=permissions,dispatcher=lambda file:dispatches.append(file["id"]),exporter=exporter)
    return SimpleNamespace(db=db,user=user,denied=denied,calls=calls,dispatches=dispatches,application=application)

def command(kind,*items,**kwargs):
    mod=importlib.import_module("bisheng.knowledge.domain.schemas.knowledge_batch")
    return mod.BatchCommand(operation=kind,items=[{"id":ident,"type":typ} for typ,ident in items],**kwargs)

def confirmation(plan):
    return ProcessingCreateRequest(confirmation_id=plan.confirmation_id,plan_digest=plan.plan_digest,idempotency_key="same-batch")

async def test_inspection_no_plan_and_rebuilding_download_allowed(batch):
    async with batch.db.sessions() as session,session.begin():
        await session.execute(update(Knowledge).where(Knowledge.id==1).values(state=3))
        await session.execute(update(KnowledgeFile).where(KnowledgeFile.id==30).values(status=4))
    result=await batch.application().ainspect(identity=batch.user,space_id=1,command=command("download",("file",30),("file",999)))
    assert [row.id for row in result.valid_items]==[30]
    assert result.invalid_items[0].reason=="not_found"
    assert all(call[2]==("download",) for call in batch.calls)
    async with batch.db.sessions() as session:
        assert not (await session.execute(select(KnowledgeOperationPlan))).scalars().all()
    assert not batch.dispatches

async def test_mixed_tag_cancel_creates_nothing(batch):
    batch.denied.add(31)
    plan=await batch.application().aprecheck(identity=batch.user,space_id=1,command=command("tag",("file",30),("file",31),("folder",10),new_tag_names=["draft"]))
    assert plan.can_execute and plan.requires_skip_confirmation
    assert {row.reason for row in plan.invalid_items}=={"no_permission","unsupported"}
    async with batch.db.sessions() as session:
        assert not (await session.execute(select(Tag))).scalars().all()
        assert not (await session.execute(select(TagLink))).scalars().all()

async def test_tag_native_atomic_replay_does_not_append_twice(batch):
    app=batch.application()
    plan=await app.aprecheck(identity=batch.user,space_id=1,command=command("tag",("file",30),new_tag_names=["created-on-confirm"]))
    assert (await app.aconfirm(identity=batch.user,space_id=1,operation="tag",request=confirmation(plan)))["items"][0]["state"]=="succeeded"
    assert (await app.aconfirm(identity=batch.user,space_id=1,operation="tag",request=confirmation(plan)))["reused"]
    async with batch.db.sessions() as session:
        assert len((await session.execute(select(Tag))).scalars().all())==1
        assert len((await session.execute(select(TagLink))).scalars().all())==1
    assert all("edit" not in call[2] or call[0]=="knowledge_space" for call in batch.calls)

async def test_final_permission_change_rejects_zero_partial_tag_write(batch):
    app=batch.application()
    plan=await app.aprecheck(identity=batch.user,space_id=1,command=command("tag",("file",30),new_tag_names=["no-write"]))
    batch.denied.add(30)
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await app.aconfirm(identity=batch.user,space_id=1,operation="tag",request=confirmation(plan))
    async with batch.db.sessions() as session:
        assert not (await session.execute(select(Tag))).scalars().all()
        assert (await session.get(KnowledgeOperationPlan,plan.confirmation_id)).operation_id is None

async def test_retry_waiting_and_plan_commit_precede_dispatch_unknown_ack_is_explicit(batch):
    app=batch.application()
    async def dispatch(file):
        async with batch.db.sessions() as session:
            assert (await session.get(KnowledgeFile,file["id"])).status==5
            assert (await session.get(KnowledgeOperationPlan,plan.confirmation_id)).operation_id=="same-batch"
        raise RuntimeError("broker acknowledgement lost")
    app.dispatcher=dispatch
    plan=await app.aprecheck(identity=batch.user,space_id=1,command=command("retry",("file",31),("file",30)))
    assert [row.id for row in plan.valid_items]==[31]
    result=await app.aconfirm(identity=batch.user,space_id=1,operation="retry",request=confirmation(plan))
    assert result["items"][0]["state"]=="pending_dispatch"
    app.dispatcher=lambda file:batch.dispatches.append(file["id"])
    assert (await app.aconfirm(identity=batch.user,space_id=1,operation="retry",request=confirmation(plan)))["items"][0]["state"]=="accepted"
    assert batch.dispatches==[31]

async def test_folder_retry_deduplicates_failed_children(batch):
    app=batch.application()
    plan=await app.aprecheck(identity=batch.user,space_id=1,command=command("retry",("folder",10),("file",31)))
    await app.aconfirm(identity=batch.user,space_id=1,operation="retry",request=confirmation(plan))
    assert sorted(batch.dispatches)==[31,40]

async def test_download_explicit_io_failure_and_stable_server_key(batch):
    app=batch.application();keys=[]
    async def exporter(**kwargs):
        keys.append(kwargs["object_key"]);return {"url":"/partial.zip","failed_file_ids":[31]}
    app.exporter=exporter
    plan=await app.aprecheck(identity=batch.user,space_id=1,command=command("download",("file",30),("file",31)))
    result=await app.aconfirm(identity=batch.user,space_id=1,operation="download",request=confirmation(plan))
    assert [row["state"] for row in result["items"]]==["succeeded","failed"]
    assert result["url"]=="/partial.zip" and keys[0].startswith("download/")
    assert all(call[2]==("download",) for call in batch.calls)

async def test_known_tag_ids_no_root_visible_or_edit(batch):
    async with batch.db.sessions() as session,session.begin():
        session.add(Tag(id=11,tenant_id=101,business_id="1",business_type="knowledge_space",name="existing",user_id=7))
    plan=await batch.application().aprecheck(identity=batch.user,space_id=1,command=command("tag",("file",30),("file",31),("file",61),tag_ids=[11]))
    assert {row.id for row in plan.valid_items}=={30,31,61}
    assert all(call[2]==("rename",) for call in batch.calls)
