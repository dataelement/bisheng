"""重复个人库的规划和执行回归。"""

import copy
import json
from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from scripts import merge_personal_knowledge_spaces as m

base = m


def space(sid=10, uid=7, name="部门库"):
    return Knowledge(id=sid, tenant_id=1, user_id=uid, name=name, type=3, model="embed")


def scope(sid=10, level="department", uid=7):
    return KnowledgeSpaceScope(space_id=sid, tenant_id=1, level=level, owner_type="user", owner_id=uid)


def file(fid=101, path="/11/12", **kwargs):
    return KnowledgeFile(
        id=fid,
        tenant_id=1,
        knowledge_id=10,
        user_id=7,
        file_name="a.pdf",
        file_level_path=path,
        status=2,
        original_uploader_id=99,
        **kwargs,
    )


def folder(fid, name, path="", sid=10):
    return KnowledgeFile(
        id=fid,
        tenant_id=1,
        knowledge_id=sid,
        file_type=0,
        file_name=name,
        file_level_path=path,
        status=2,
        level=len([p for p in path.split("/") if p]),
    )


class MemoryOperations(m.GuardedOperations):
    def __init__(self, tenant_id, spaces, state, fail_at=None):
        super().__init__(tenant_id, spaces)
        self.state = state
        self.fail_at = fail_at
        self.calls = []

    async def snapshot_unit(self, unit):
        for f in unit.source_files:
            self.snapshots[f.id] = base.SourceSnapshot(
                base.TagSnapshot(), (), base.IndexSnapshot(0, 0), {"original": True}
            )

    async def copy_file(self, source, target):
        self.calls.append("copy")
        if self.fail_at == "copy":
            raise RuntimeError("copy failed")
        new = source.model_copy(
            update={
                "id": source.id + 1000,
                "knowledge_id": target.space.id,
                "user_id": target.owner.user_id,
                "file_level_path": target.file_level_path,
            }
        )
        self.state.files.append(new)
        self.target_files_by_source_id[source.id] = new
        return new

    async def copy_tags(self, source, target, context):
        self.calls.append("tags")

    async def write_permissions(self, target, context):
        self.calls.append("permissions")
        if self.fail_at == "permissions":
            raise RuntimeError("permission write failed")

    async def verify_target(self, source, target, context):
        self.calls.append("verify")
        if self.fail_at == "verify":
            raise RuntimeError("target invalid")

    async def delete_source(self, source, target, context):
        self.calls.append("delete")
        self.state.files = [f for f in self.state.files if f.id != source.id]
        if self.fail_at == "delete":
            await self.restore_source(source, target, context)
            raise RuntimeError("source deletion failed")

    async def restore_source(self, source, target, context):
        self.calls.append("restore")
        if all(f.id != source.id for f in self.state.files):
            self.state.files.append(source)
        return []

    async def cleanup_target(self, target, context):
        self.calls.append("cleanup")
        if self.preserve_targets:
            return ["preserved after overwrite started"]
        self.state.files = [f for f in self.state.files if f.id != target.id]
        return []

    async def revalidate_overwrite_target(self, overwrite, target):
        assert {f.id for f in overwrite.files} <= {f.id for f in self.state.files}

    async def snapshot_overwrite_target(self, overwrite, target):
        return [{"file_id": f.id} for f in overwrite.files]

    async def delete_overwrite_target(self, overwrite, target):
        self.calls.append("overwrite")
        if self.fail_at == "overwrite":
            return [base.OverwriteDeletionStep("objects", "failed", error="delete failed")]
        ids = {f.id for f in overwrite.files}
        self.state.files = [f for f in self.state.files if f.id not in ids]
        if overwrite.document:
            self.state.documents = [d for d in self.state.documents if d.id != overwrite.document.id]
            self.state.versions = [v for v in self.state.versions if v.document_id != overwrite.document.id]
        return [base.OverwriteDeletionStep("objects", "success")]


def snapshot():
    return m.Snapshot(
        tenant_id=1,
        spaces=[space(20, name="张三的知识库"), space(10, name="张三的知识库")],
        scopes=[scope(20, "personal"), scope(10, "personal")],
        users=[SimpleNamespace(user_id=7, user_name="张三", delete=0)],
        member_ids={7},
        files=[file(201, "").model_copy(update={"knowledge_id": 20})],
    )


def test_single_file_import_and_plan_without_any_scripts_package(monkeypatch):
    import builtins
    import runpy

    original_import = builtins.__import__

    def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts" or name.startswith("scripts."):
            raise ImportError("business script is not deployed")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", isolated_import)
    isolated = runpy.run_path(m.__file__)
    plan = isolated["build_plan"](snapshot())
    assert plan.groups[0].target.id == 10
    assert plan.candidates[0].unit_id == "file:201"


def test_root_target_permissions_and_result_use_real_space():
    s = snapshot()
    target = base.TargetContext(1, s.spaces[1], None, s.users[0], "", 0)
    rows = base._target_permission_rows(s.files[0], target)
    assert {"user": "knowledge_space:10", "relation": "parent", "object": "knowledge_file:201"} in rows
    assert target.key == (10, 0)
    assert base._result_for_source(s.files[0], target, status="ready").target_folder_id is None


def test_plan_groups_real_personal_spaces_and_includes_root():
    s = snapshot()
    plan = m.build_plan(s)
    assert plan.groups[0].target.id == 10
    assert [s.id for s in plan.groups[0].sources] == [20]
    candidate = plan.candidates[0]
    assert candidate.folder_names == ()
    assert candidate.target_space.id == 10


def test_plan_keeps_empty_folders():
    s = snapshot()
    s.files = [folder(21, "空目录", sid=20)]
    plan = m.build_plan(s)
    assert len(plan.candidates) == 1
    assert plan.candidates[0].unit_id == "folder:21"
    assert plan.candidates[0].folder_names == ("空目录",)


@pytest.mark.parametrize("change", ["favorite", "custom", "department", "tenant", "deleted", "nonmember", "filter"])
def test_excludes_non_default_or_unavailable_owner(change):
    s = snapshot()
    if change == "favorite":
        s.spaces[0].is_favorite = True
    elif change == "custom":
        s.spaces[0].name = "自建库"
    elif change == "department":
        s.scopes[0].level = "department"
    elif change == "tenant":
        s.spaces[0].tenant_id = 2
    elif change == "deleted":
        s.users[0].delete = 1
    elif change == "nonmember":
        s.member_ids.clear()
    assert not m.build_plan(s, 8 if change == "filter" else None).groups


def test_merge_uses_library_owner_not_file_uploader():
    s = snapshot()
    s.files[0].user_id = 999
    assert m.build_plan(s).candidates[0].owner.user_id == 7


@pytest.mark.parametrize("blocker", ["channel_sync_binding", "active_space_approval"])
def test_bound_spaces_cannot_migrate_or_be_deleted(blocker):
    s = m.MergeSnapshot(**vars(snapshot()), space_blockers={20: [blocker]})
    plan = m.build_plan(s)
    assert not plan.candidates
    assert plan.skipped[0]["reason"] == blocker
    assert m.cleanup_reason(s, plan.groups[0], s.spaces[0], []) == "space_has_active_binding_or_approval"


class MemoryBackend(m.Backend):
    async def execute(self, candidate, journal, folder_name=""):
        # 旧复制/补偿路径的回归继续使用其专用适配器; 原记录迁移另有真实数据库测试。
        if candidate.files:
            result = await m.MigrationBackend.execute(self, candidate, journal, folder_name)
            self.annotate_mappings(candidate, result)
            return result
        return await super().execute(candidate, journal, folder_name)

    def __init__(self, state, fail_at=None):
        self.state = state
        self.fail_at = fail_at
        self.deleted = []
        self.initialized = 0

    async def load(self, tenant_id, **kwargs):
        return copy.deepcopy(self.state)

    async def read_files(self, file_ids):
        return {f.id: f for f in self.state.files if f.id in file_ids}

    async def initialize_apply(self):
        self.initialized += 1

    async def ensure_space(self, candidate, journal):
        return None, candidate.target_space

    async def prepare_folders(self, candidate, service, journal, created, mappings):
        path, parent = "", None
        for source in candidate.folders:
            matches = [
                f
                for f in self.state.files
                if f.knowledge_id == candidate.target_space.id
                and (f.file_level_path or "") == path
                and f.file_name == source.file_name
            ]
            if matches:
                parent = matches[0]
            else:
                parent = folder(source.id + 5000, source.file_name, path, candidate.target_space.id)
                self.state.files.append(parent)
            mappings.append(
                {
                    "source_folder_id": source.id,
                    "target_folder_id": parent.id,
                    "name": parent.file_name,
                    "parent_path": path,
                }
            )
            path = f"{path}/{parent.id}"
        return base.TargetContext(1, candidate.target_space, parent, candidate.owner, path, len(candidate.folders))

    async def verify_completed(self, unit, operations, results):
        assert not {f.id for f in unit.source_files} & {f.id for f in self.state.files}

    async def delete_empty_source(self, group, source, mappings, journal, expected_files=None):
        assert m.cleanup_reason(self.state, group, source, mappings, expected_files) is None
        if self.fail_at == "space_delete":
            raise RuntimeError("delete failed")
        m.record_event(journal, "source_space_delete_started", {"source_space_id": source.id})
        self.deleted.append(source.id)
        self.state.files = [f for f in self.state.files if f.knowledge_id != source.id]
        self.state.scopes = [s for s in self.state.scopes if s.space_id != source.id]
        self.state.spaces = [s for s in self.state.spaces if s.id != source.id]


def runtime(monkeypatch, tmp_path, *, fail_at=None):
    s = snapshot()
    backend = MemoryBackend(s, fail_at)
    calls = []

    def operations(tenant_id, spaces):
        op = MemoryOperations(tenant_id, spaces, s, fail_at)
        op.calls = calls
        return op

    monkeypatch.setattr(m, "GuardedOperations", operations)
    args = m.parse_args(["--all-users", "--apply", "--report-dir", str(tmp_path)])
    return s, backend, calls, args


async def test_preview_never_initializes_writes(tmp_path):
    backend = MemoryBackend(snapshot())
    args = m.parse_args(["--all-users", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=backend) == 0
    assert backend.initialized == 0 and not backend.deleted
    assert not list(tmp_path.glob("*.jsonl"))
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["status"] == "preview"


async def test_sequential_root_overwrite_preserves_last_file_and_removes_old_spaces(monkeypatch, tmp_path):
    s, backend, calls, args = runtime(monkeypatch, tmp_path)
    s.spaces.insert(0, space(30, name="张三的知识库"))
    s.scopes.append(scope(30, "personal"))
    s.files.extend(
        [
            file(101, ""),
            file(301, "").model_copy(update={"knowledge_id": 30}),
            file(202, "").model_copy(update={"knowledge_id": 20}),
        ]
    )
    assert await m.run(args, backend=backend) == 0
    assert backend.deleted == [20, 30]
    assert [f.id for f in s.files] == [1301]
    assert s.files[0].file_level_path == ""
    assert calls.count("overwrite") == 3
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "completed" and report["pending_sources"] == 0
    assert report["results"][1]["overwrite_targets"][0]["file_ids"] == [1201]
    assert not m.build_plan(s).groups
    events = [json.loads(line)["event_type"] for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert events.index("unit_succeeded") < events.index("source_space_delete_started")


async def test_nested_and_empty_folders_survive_merge(monkeypatch, tmp_path):
    s, backend, _calls, args = runtime(monkeypatch, tmp_path)
    s.files = [
        folder(21, "待整理", sid=20),
        folder(22, "制度", "/21", 20),
        folder(23, "空目录", "/21", 20),
        file(201, "/21/22").model_copy(update={"knowledge_id": 20}),
    ]
    assert await m.run(args, backend=backend) == 0
    assert backend.deleted == [20]
    assert {f.file_name for f in s.files if f.file_type == 0} == {"待整理", "制度", "空目录"}
    assert next(f for f in s.files if f.file_type == 1).file_level_path == "/5021/5022"


async def test_empty_library_is_merged_without_file_units(monkeypatch, tmp_path):
    s, backend, calls, args = runtime(monkeypatch, tmp_path)
    s.files.clear()
    assert await m.run(args, backend=backend) == 0
    assert backend.deleted == [20] and not calls


async def test_skipped_file_keeps_old_space_while_other_file_moves(monkeypatch, tmp_path):
    s, backend, _calls, args = runtime(monkeypatch, tmp_path)
    s.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "status": 1, "file_name": "b.pdf"}))
    assert await m.run(args, backend=backend) == 0
    assert not backend.deleted
    assert {f.id for f in s.files} == {202, 1201}
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "completed_with_skips"


@pytest.mark.parametrize("fail_at", ["copy", "permissions", "verify", "delete", "overwrite", "space_delete"])
async def test_failure_stops_without_deleting_source_space(monkeypatch, tmp_path, fail_at):
    s, backend, calls, args = runtime(monkeypatch, tmp_path, fail_at=fail_at)
    args.stop_on_error = True
    s.files.extend([file(101, ""), file(202, "").model_copy(update={"knowledge_id": 20})])
    assert await m.run(args, backend=backend) == 3
    assert not backend.deleted
    if fail_at != "space_delete":
        assert calls.count("copy") == 1
    if fail_at == "overwrite":
        assert {101, 201, 1201} <= {f.id for f in s.files}
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "failed"
    if fail_at == "space_delete":
        assert report["source_results"][0]["status"] == "failed"


async def test_journal_failure_prevents_source_deletion(monkeypatch, tmp_path):
    s, backend, calls, args = runtime(monkeypatch, tmp_path)
    record = m.record_event

    def fail(journal, event, payload):
        if event == "before_source_delete":
            raise OSError("disk full")
        record(journal, event, payload)

    monkeypatch.setattr(m, "record_event", fail)
    assert await m.run(args, backend=backend) == 3
    assert not backend.deleted and "delete" not in calls
    assert {f.id for f in s.files} == {201}


async def test_interrupt_keeps_old_space_and_next_unit_pending(monkeypatch, tmp_path):
    from contextlib import contextmanager

    s, backend, _calls, args = runtime(monkeypatch, tmp_path)
    s.files.append(file(202, "").model_copy(update={"knowledge_id": 20, "file_name": "b.pdf"}))
    active = []

    @contextmanager
    def signal_scope(controller, enabled):
        active.append(controller)
        yield

    execute = backend.execute

    async def execute_and_stop(*args):
        result = await execute(*args)
        active[0].request_stop()
        return result

    monkeypatch.setattr(base, "_sigint_stop_scope", signal_scope)
    monkeypatch.setattr(backend, "execute", execute_and_stop)
    assert await m.run(args, backend=backend) == 130
    assert {f.id for f in s.files} == {202, 1201}
    assert not backend.deleted
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "interrupted" and report["pending"] == 1 and report["pending_sources"] == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ("new_file", "source_not_empty"),
        ("orphan_document", "source_documents_remain"),
        ("lost_folder", "source_folder_not_preserved"),
        ("moved_folder", "source_folder_not_preserved"),
        ("lost_target", "migrated_target_changed"),
        ("storage", "storage_used_by_another_space"),
        ("new_canonical", "personal_group_changed"),
    ],
)
def test_cleanup_rechecks_preserved_content(change, reason):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument

    s = snapshot()
    group = m.build_plan(s).groups[0]
    target_file = file(1001, "")
    s.files = [folder(21, "空目录", sid=20), folder(501, "空目录", sid=10), target_file]
    mappings = [
        {"source_folder_id": 21, "target_folder_id": 501, "name": "空目录", "parent_path": "", "source_parent_path": ""}
    ]
    expected = {1001: m.file_identity(target_file)}
    if change == "new_file":
        s.files.append(file(202, "").model_copy(update={"knowledge_id": 20}))
    elif change == "orphan_document":
        s.documents.append(KnowledgeDocument(id=99, tenant_id=1, knowledge_id=20))
    elif change == "lost_folder":
        s.files = [f for f in s.files if f.id != 501]
    elif change == "moved_folder":
        s.files[0].file_level_path = "/999"
    elif change == "lost_target":
        s.files.remove(target_file)
    elif change == "storage":
        for obj in [*s.spaces, group.sources[0]]:
            obj.collection_name = "reused"
    elif change == "new_canonical":
        s.spaces.append(space(5, name="张三的知识库"))
        s.scopes.append(scope(5, "personal"))
    assert m.cleanup_reason(s, group, group.sources[0], mappings, expected) == reason


def add_root_chain(s):
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion

    s.files.append(file(202, "").model_copy(update={"knowledge_id": 20}))
    s.documents = [KnowledgeDocument(id=50, tenant_id=1, knowledge_id=20, primary_version_id=502, file_level_path="")]
    s.versions = [
        KnowledgeDocumentVersion(
            id=501 + index, document_id=50, knowledge_file_id=201 + index, version_no=index + 1, is_primary=bool(index)
        )
        for index in range(2)
    ]


@pytest.mark.parametrize("change", ["missing_version", "folder_version", "locked", "external_reference"])
def test_invalid_or_protected_chains_remain_in_source(change):
    s = snapshot()
    add_root_chain(s)
    if change == "missing_version":
        s.files.pop()
    elif change == "folder_version":
        s.files[1].file_type = 0
    elif change == "locked":
        s.locked_document_ids.add(50)
    elif change == "external_reference":
        s.files.append(file(301, "").model_copy(update={"reference_document_id": 50}))
    assert not m.build_plan(s).candidates
    assert m.build_plan(s).skipped


async def test_complete_root_chain_is_migrated_then_overwritten_as_a_whole(monkeypatch, tmp_path):
    s, backend, _calls, args = runtime(monkeypatch, tmp_path)
    add_root_chain(s)
    s.files.append(file(203, "").model_copy(update={"knowledge_id": 20}))
    plan = m.build_plan(s)
    assert [f.id for f in plan.candidates[0].files] == [201, 202]

    class Graph(m.GuardedGraphStore):
        async def create_target_graph(self, unit, files):
            doc = unit.source_document.model_copy(
                update={"id": 1050, "knowledge_id": 10, "primary_version_id": 1502, "file_level_path": ""}
            )
            versions = [
                v.model_copy(update={"id": v.id + 1000, "document_id": doc.id, "knowledge_file_id": f.id})
                for v, f in zip(unit.source_versions, files, strict=True)
            ]
            s.documents.append(doc)
            s.versions.extend(versions)
            self.target_graphs[doc.id] = {"document": doc.model_dump(), "versions": [v.model_dump() for v in versions]}
            return doc.id

        async def verify_target_graph(self, unit, target_id, files):
            doc = next(d for d in s.documents if d.id == target_id)
            versions = [v for v in s.versions if v.document_id == target_id]
            assert base.TargetConflictIndex._valid_version_graph(doc, versions)
            assert {v.knowledge_file_id for v in versions} == {f.id for f in files}

        async def delete_source_graph(self, unit):
            s.documents = [d for d in s.documents if d.id != unit.source_document.id]
            s.versions = [v for v in s.versions if v.document_id != unit.source_document.id]

    monkeypatch.setattr(m, "GuardedGraphStore", Graph)
    assert await m.run(args, backend=backend) == 0
    assert [f.id for f in s.files] == [1203]
    assert not s.documents and not s.versions
    assert backend.deleted == [20]
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["results"][1]["overwrite_targets"][0]["file_ids"] == [1201, 1202]


@pytest.mark.parametrize("module_present", [True, False])
async def test_loader_finds_empty_library_owner_and_bindings(monkeypatch, module_present):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from sqlalchemy import Column, Integer
    from sqlalchemy.orm import declarative_base

    from bisheng.knowledge.rag import shared_space_storage

    s = snapshot()
    s.files.clear()
    owners, s.users = s.users, []
    s.member_ids.clear()
    monkeypatch.setattr(m.MigrationBackend, "load", AsyncMock(return_value=s))
    # 全局测试夹具替换了 User 模块, 这里用最小映射表验证真实 SQL 构造。
    loader_user = type(
        "LoaderUser",
        (declarative_base(),),
        {
            "__tablename__": "merge_loader_user",
            "user_id": Column(Integer, primary_key=True),
        },
    )
    monkeypatch.setattr(m, "User", loader_user)
    monkeypatch.setattr(base.settings.multi_tenant, "enabled", False)
    replies = iter([owners, ["20"], []])
    session = SimpleNamespace(exec=AsyncMock(side_effect=lambda query: SimpleNamespace(all=lambda: next(replies))))

    @asynccontextmanager
    async def connection():
        yield session

    monkeypatch.setattr(m, "get_async_db_session", connection)
    monkeypatch.setattr(shared_space_storage, "aresolve_space_shared_routing", AsyncMock(return_value=None))
    if not module_present:
        import sys

        monkeypatch.setitem(sys.modules, "bisheng.knowledge.rag.shared_space_storage", None)
    loaded = await m.Backend().load(1)
    assert loaded.member_ids == {7} and loaded.users[0].user_id == 7
    assert loaded.space_blockers == {20: ["channel_sync_binding"]}
    assert len(m.find_groups(loaded)[0]) == 1
    assert loaded.shared_storage is False


@pytest.mark.parametrize("shared", [True, False])
async def test_shared_storage_detection_uses_installed_resolver(monkeypatch, shared):
    from unittest.mock import AsyncMock

    resolver = AsyncMock(return_value=object() if shared else None)
    monkeypatch.setattr(m, "import_module", lambda name: SimpleNamespace(aresolve_space_shared_routing=resolver))
    assert await m.uses_shared_storage(2) is shared
    resolver.assert_awaited_once_with(2, 3)


async def test_missing_optional_module_keeps_conservative_storage_guard(monkeypatch):
    def absent(name):
        raise ModuleNotFoundError("old deployment", name=name)

    monkeypatch.setattr(m, "import_module", absent)
    s = m.MergeSnapshot(**vars(snapshot()))
    s.shared_storage = await m.uses_shared_storage(1)
    assert s.shared_storage is False
    s.files.clear()
    for record in s.spaces:
        record.collection_name = "same_collection"
    group = m.build_plan(s).groups[0]
    assert m.cleanup_reason(s, group, group.sources[0], []) == "storage_used_by_another_space"
    s.spaces[0].collection_name = "separate_collection"
    group = m.build_plan(s).groups[0]
    assert m.cleanup_reason(s, group, group.sources[0], []) is None


@pytest.mark.parametrize("failure", ["nested_dependency", "resolver_error"])
async def test_shared_storage_detection_does_not_hide_broken_installation(monkeypatch, failure):
    from unittest.mock import AsyncMock

    error = ModuleNotFoundError("missing internal dependency", name="broken_storage_dependency")

    def broken(name):
        if failure == "nested_dependency":
            raise error
        return SimpleNamespace(aresolve_space_shared_routing=AsyncMock(side_effect=error))

    monkeypatch.setattr(m, "import_module", broken)
    with pytest.raises(ModuleNotFoundError, match="internal dependency"):
        await m.uses_shared_storage(1)


@pytest.mark.parametrize("residual", [False, True])
async def test_source_cleanup_calls_business_delete_and_checks_residuals(monkeypatch, tmp_path, residual):
    from unittest.mock import AsyncMock

    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao

    s = snapshot()
    s.files.clear()
    group = m.build_plan(s).groups[0]
    after = copy.deepcopy(s)
    after.spaces = [space for space in after.spaces if space.id != 20]
    if not residual:
        after.scopes = [scope for scope in after.scopes if scope.space_id != 20]
    backend = m.Backend()
    monkeypatch.setattr(backend, "load", AsyncMock(side_effect=[s, after]))
    monkeypatch.setattr(backend, "source_has_rows", AsyncMock(return_value=residual))
    service = SimpleNamespace(delete_space=AsyncMock())
    monkeypatch.setattr(backend, "service_for", AsyncMock(return_value=service))
    monkeypatch.setattr(base, "_read_resource_permission_tuples", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "_delete_empty_space_records", AsyncMock())
    monkeypatch.setattr(m, "_replace_resource_permission_tuples", AsyncMock())
    monkeypatch.setattr(SpaceChannelMemberDao, "clean_space_member", AsyncMock())
    monkeypatch.setattr(SpaceChannelMemberDao, "async_get_members_by_space", AsyncMock(return_value=[]))
    journal = base.RollbackJournal(path=tmp_path / "delete.jsonl", run_id="test")
    journal.open()
    try:
        if residual:
            with pytest.raises(RuntimeError, match="残留"):
                await backend.delete_empty_source(group, group.sources[0], [], journal)
        else:
            await backend.delete_empty_source(group, group.sources[0], [], journal)
        service.delete_space.assert_awaited_once_with(20, force=True)
        assert service.request.client.host == "127.0.0.1"
    finally:
        journal.close()
