"""部门目录迁移的归属、范围和写入边界回归。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.move_department_files_to_personal as m
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope


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


def snapshot():
    return m.Snapshot(
        tenant_id=1,
        spaces=[space()],
        scopes=[scope()],
        files=[folder(11, "待整理"), folder(12, "制度", "/11"), file()],
        users=[SimpleNamespace(user_id=7, user_name="张三", delete=0)],
        member_ids={7},
    )


def test_routes_by_current_user_and_preserves_root_and_subfolders():
    plan = m.build_plan(snapshot(), "待整理")
    assert not plan.skipped
    c = plan.candidates[0]
    assert c.owner.user_id == 7
    assert c.folder_names == ("待整理", "制度")
    assert c.target_space is None
    assert c.preview()["target_space_name"] == "张三的知识库"


@pytest.mark.parametrize("level", ["public", "team", "team_ks", "personal"])
def test_only_department_spaces(level):
    s = snapshot()
    s.scopes[0].level = level
    assert not m.build_plan(s, "待整理").candidates


def test_exact_root_and_path_segment_boundaries():
    s = snapshot()
    s.files += [folder(111, "别的"), file(102, "/111"), file(103, "")]
    assert [c.files[0].id for c in m.build_plan(s, "待整理").candidates] == [101]
    s.files[0].file_level_path = "/88"
    assert not m.build_plan(s, "待整理").candidates


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("deleted_user", "owner_unavailable"),
        ("membership", "owner_unavailable"),
        ("processing", "file_ineligible"),
        ("reference", "shared_relationship"),
        ("duplicate_root", "ambiguous_source_root"),
        ("broken_path", "invalid_source_path"),
    ],
)
def test_skip_unsafe_sources(mutation, reason):
    s = snapshot()
    if mutation == "deleted_user":
        s.users[0].delete = 1
    if mutation == "membership":
        s.member_ids.clear()
    if mutation == "processing":
        s.files[-1].status = 1
    if mutation == "reference":
        s.files[-1].reference_document_id = 500
    if mutation == "duplicate_root":
        s.files.append(folder(13, "待整理"))
    if mutation == "broken_path":
        s.files[1].file_level_path = ""
    p = m.build_plan(s, "待整理")
    assert not p.candidates
    assert reason in {r["reason"] for r in p.skipped}


def add_chain(s):
    s.files.append(file(102))
    s.documents = [
        KnowledgeDocument(id=50, tenant_id=1, knowledge_id=10, primary_version_id=502, file_level_path="/11/12")
    ]
    s.versions = [
        KnowledgeDocumentVersion(
            id=501, tenant_id=1, document_id=50, knowledge_file_id=101, version_no=1, is_primary=False
        ),
        KnowledgeDocumentVersion(
            id=502, tenant_id=1, document_id=50, knowledge_file_id=102, version_no=2, is_primary=True
        ),
    ]


def test_complete_version_chain_stays_together():
    s = snapshot()
    add_chain(s)
    c = m.build_plan(s, "待整理").candidates[0]
    assert [f.id for f in c.files] == [101, 102]
    assert c.document.id == 50
    assert [v.version_no for v in c.versions] == [1, 2]


@pytest.mark.parametrize("mutation", ["owner", "missing", "primary", "outside", "external", "approval"])
def test_version_chain_refuses_partial_or_shared_migration(mutation):
    s = snapshot()
    add_chain(s)
    if mutation == "owner":
        s.files[-1].user_id = 8
    if mutation == "missing":
        s.files.pop()
    if mutation == "primary":
        s.versions[0].is_primary = True
    if mutation == "outside":
        s.files[-1].file_level_path = ""
    if mutation == "external":
        s.files.append(file(999, "", reference_document_id=50))
    if mutation == "approval":
        s.locked_document_ids.add(50)
    p = m.build_plan(s, "待整理")
    assert not p.candidates
    assert p.skipped


def personal(s):
    s.spaces.append(space(20, name="张三的知识库"))
    s.scopes.append(scope(20, "personal"))
    s.files += [folder(21, "待整理", sid=20), folder(22, "制度", "/21", sid=20)]


def test_target_and_batch_names_are_planned_for_overwrite_without_md5_filter():
    s = snapshot()
    s.files.append(file(102))
    batch = m.build_plan(s, "待整理")
    assert len(batch.candidates) == 2
    assert batch.candidates[1].preview()["replaces_planned_unit_ids"] == ["file:101"]
    personal(s)
    target = file(201, "/21/22")
    target.knowledge_id = 20
    s.files.append(target)
    plan = m.build_plan(s, "待整理")
    assert len(plan.candidates) == 2
    assert plan.candidates[0].preview()["overwrite_targets"][0]["file_ids"] == [201]
    target.file_name = "different.pdf"
    target.md5 = "same"
    s.files[2].md5 = "same"
    plan = m.build_plan(s, "待整理")
    assert len(plan.candidates) == 2
    assert not plan.candidates[0].overwrites


@pytest.mark.parametrize("mutation", ["duplicate", "file_blocks_folder", "wrong_owner"])
def test_target_safety(mutation):
    s = snapshot()
    personal(s)
    if mutation == "duplicate":
        s.files.append(folder(23, "制度", "/21", sid=20))
    if mutation == "file_blocks_folder":
        s.files[-1].file_type = 1
    if mutation == "model":
        s.spaces[-1].model = "other"
    if mutation == "wrong_owner":
        s.spaces[-1].user_id = 99
    assert not m.build_plan(s, "待整理").candidates


async def test_dry_run_does_not_initialize_writing_services(tmp_path):
    backend = SimpleNamespace(
        load=AsyncMock(return_value=snapshot()),
        initialize_apply=AsyncMock(side_effect=AssertionError("write")),
        execute=AsyncMock(side_effect=AssertionError("write")),
    )
    args = m.parse_args(["--folder-name", "待整理", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=backend) == 0
    backend.initialize_apply.assert_not_awaited()
    backend.execute.assert_not_awaited()
    assert list(tmp_path.glob("*.json"))


def test_multitenant_requires_explicit_tenant_and_single_tenant_rejects_other_id():
    args = m.parse_args(["--folder-name", "待整理"])
    with pytest.raises(m.PreflightError):
        m.resolve_tenant(args, True)
    args.tenant_id = 2
    with pytest.raises(m.PreflightError):
        m.resolve_tenant(args, False)
    assert m.resolve_tenant(args, True) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_personal_spaces_select_lowest_id_and_report_candidates(reverse):
    s = snapshot()
    personal(s)
    s.spaces.append(space(30, name="张三的知识库"))
    s.scopes.append(scope(30, "personal"))
    if reverse:
        s.spaces.reverse()
    p = m.build_plan(s, "待整理")
    assert not p.skipped
    assert p.candidates[0].target_space.id == 20
    assert p.candidates[0].preview()["personal_space_candidate_ids"] == [20, 30]


def test_duplicate_personal_spaces_do_not_fallback_when_first_model_is_incompatible():
    s = snapshot()
    personal(s)
    s.spaces[-1].model = "incompatible"
    s.spaces.append(space(30, name="张三的知识库"))
    s.scopes.append(scope(30, "personal"))
    plan = m.build_plan(s, "待整理")
    assert len(plan.candidates) == 1
    assert plan.candidates[0].target_space.id == 20


@pytest.mark.parametrize("existing", [False, True])
async def test_personal_space_uses_existing_creator_only_when_missing(monkeypatch, tmp_path, existing):
    s = snapshot()
    if existing:
        personal(s)
    candidate = m.build_plan(s, "待整理").candidates[0]
    target = space(20, name="张三的知识库")
    service = SimpleNamespace(
        login_user=SimpleNamespace(user_id=7), ensure_personal_default_space=AsyncMock(return_value=target)
    )
    latest = snapshot()
    personal(latest)
    backend = m.Backend()
    backend.service_for = AsyncMock(return_value=service)
    backend.load = AsyncMock(return_value=latest)
    monkeypatch.setattr(
        m,
        "_read_resource_permission_tuples",
        AsyncMock(return_value=[{"user": "user:7", "relation": "owner", "object": "knowledge_space:20"}]),
    )
    journal = m.RollbackJournal(path=tmp_path / "events.jsonl", run_id="test")
    journal.open()
    try:
        _, actual = await backend.ensure_space(candidate, journal)
    finally:
        journal.close()
    assert actual.id == 20
    if existing:
        service.ensure_personal_default_space.assert_not_awaited()
    else:
        service.ensure_personal_default_space.assert_awaited_once_with()


async def test_folder_creation_preserves_root_and_only_reuses_exact_parent(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    s = snapshot()
    personal(s)
    candidate = m.build_plan(s, "待整理").candidates[0]
    existing = folder(21, "待整理", sid=20)
    unrelated = folder(25, "制度", "/99", sid=20)
    rows = [existing, unrelated]

    class Session:
        async def exec(self, statement):
            return SimpleNamespace(all=lambda: rows)

    @asynccontextmanager
    async def session():
        yield Session()

    async def add(sid, name, parent_id):
        new = folder(30, name, f"/{parent_id}", sid=sid)
        rows.append(new)
        return new

    monkeypatch.setattr(m, "get_async_db_session", session)
    service = SimpleNamespace(add_folder=AsyncMock(side_effect=add))
    created, mappings = [], []
    journal = m.RollbackJournal(path=tmp_path / "folders.jsonl", run_id="test")
    journal.open()
    try:
        target = await m.Backend().prepare_folders(candidate, service, journal, created, mappings)
    finally:
        journal.close()
    assert target.file_level_path == "/21/30"
    service.add_folder.assert_awaited_once_with(20, "制度", 21)
    assert [f.id for f in created] == [30]
    assert [r["action"] for r in mappings] == ["reused", "created"]


def test_overwrite_target_preserves_complete_version_boundary():
    state = snapshot()
    personal(state)
    first = add_existing_target(state)
    second = first.model_copy(update={"id": 202, "file_name": "previous.pdf"})
    state.files.append(second)
    state.documents = [
        KnowledgeDocument(id=80, tenant_id=1, knowledge_id=20, primary_version_id=802, file_level_path="/21/22")
    ]
    state.versions = [
        KnowledgeDocumentVersion(id=801, document_id=80, knowledge_file_id=202, version_no=1, is_primary=False),
        KnowledgeDocumentVersion(id=802, document_id=80, knowledge_file_id=201, version_no=2, is_primary=True),
    ]
    candidate = m.build_plan(state, "待整理").candidates[0]
    assert set(candidate.preview()["overwrite_targets"][0]["file_ids"]) == {201, 202}
    assert candidate.overwrites[0].document.id == 80
    state.files.remove(second)
    assert not m.build_plan(state, "待整理").candidates


@pytest.mark.parametrize("kind", ["reference", "external", "locked", "folder", "processing"])
def test_overwrite_does_not_delete_protected_targets(kind):
    state = snapshot()
    personal(state)
    old = add_existing_target(state)
    if kind == "reference":
        old.reference_document_id = 80
    elif kind == "external":
        state.files.append(file(999, "", share_source_file_id=201))
    elif kind == "locked":
        state.locked_file_ids.add(201)
    elif kind == "folder":
        old.file_type = 0
    else:
        old.status = 1
    assert not m.build_plan(state, "待整理").candidates


def add_existing_target(state):
    target = file(201, "/21/22")
    target.knowledge_id = 20
    state.files.append(target)
    return target
