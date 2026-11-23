"""Original ZIP output has explicit failures and releases SQL before storage IO."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.services import knowledge_batch_download as module
from test.knowledge_unification import test_kn_batch as native

deletion_tenant, db, batch = native.deletion_tenant, native.db, native.batch


class Storage:
    tmp_bucket = "temporary"

    def __init__(self, active, broken=()):
        self.active, self.broken, self.reads, self.archives, self.links = active, set(broken), [], [], []

    def download_object_sync(self, *, object_name):
        assert self.active[0] == 0
        self.reads.append(object_name)
        if object_name in self.broken:
            raise RuntimeError("object unavailable")
        return SimpleNamespace(stream=lambda size: [b"original"], close=lambda: None, release_conn=lambda: None)

    async def put_object_tmp(self, key, source, **kwargs):
        assert self.active[0] == 0
        with ZipFile(source) as archive:
            self.archives.append((key, archive.namelist()))

    async def get_share_link(self, key, **kwargs):
        assert self.active[0] == 0
        self.links.append((key, kwargs))
        return "/temporary.zip"


async def test_actual_exporter_reports_per_file_failure_and_keeps_seven_day_url(batch, monkeypatch):
    active = [0]

    @asynccontextmanager
    async def sessions():
        active[0] += 1
        try:
            async with batch.db.sessions() as session:
                yield session
        finally:
            active[0] -= 1

    storage = Storage(active, broken=["obj/31"])
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    app = batch.application()
    app.sessions = sessions
    app.exporter = None
    plan = await app.aprecheck(
        identity=batch.user, space_id=1, command=native.command("download", ("file", 30), ("file", 31))
    )
    result = await app.aconfirm(
        identity=batch.user, space_id=1, operation="download", request=native.confirmation(plan)
    )
    assert [row["state"] for row in result["items"]] == ["succeeded", "failed"]
    assert storage.links[0][1]["expire_days"] == 7 and len(storage.archives) == 1
    assert any("f-30" in name for name in storage.archives[0][1])
    async with batch.db.sessions() as session:
        assert (await session.get(KnowledgeOperationPlan, plan.confirmation_id)).operation_id is None


async def test_download_replay_reuses_completed_archive_without_reading_source_again(batch, monkeypatch):
    storage = Storage([0])
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    app = batch.application()
    app.exporter = None
    plan = await app.aprecheck(identity=batch.user, space_id=1, command=native.command("download", ("file", 30)))
    await app.aconfirm(identity=batch.user, space_id=1, operation="download", request=native.confirmation(plan))
    reads = list(storage.reads)
    assert (
        await app.aconfirm(identity=batch.user, space_id=1, operation="download", request=native.confirmation(plan))
    )["reused"]
    assert storage.reads == reads and storage.links[0][0] == storage.links[1][0]


async def test_permission_change_during_export_refuses_final_consumption(batch):
    app = batch.application()

    async def exporter(**kwargs):
        batch.denied.add(30)
        return {"url": "/not-issued.zip", "failed_file_ids": []}

    app.exporter = exporter
    plan = await app.aprecheck(identity=batch.user, space_id=1, command=native.command("download", ("file", 30)))
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await app.aconfirm(identity=batch.user, space_id=1, operation="download", request=native.confirmation(plan))
    async with batch.db.sessions() as session:
        assert (await session.get(KnowledgeOperationPlan, plan.confirmation_id)).operation_id is None


async def test_unknown_archive_upload_returns_explicit_failed_items_without_consumption(batch, monkeypatch):
    storage = Storage([0])

    async def fail(*args, **kwargs):
        raise RuntimeError("storage upload ACK lost")

    storage.put_object_tmp = fail
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    app = batch.application()
    app.exporter = None
    plan = await app.aprecheck(identity=batch.user, space_id=1, command=native.command("download", ("file", 30)))
    result = await app.aconfirm(
        identity=batch.user, space_id=1, operation="download", request=native.confirmation(plan)
    )
    assert result["items"][0]["state"] == "failed" and "url" not in result
    async with batch.db.sessions() as session:
        assert (await session.get(KnowledgeOperationPlan, plan.confirmation_id)).operation_id is None
