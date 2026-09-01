"""Tests for retrying failed files under a named knowledge-space folder."""

from types import SimpleNamespace

import pytest

import scripts.retry_failed_knowledge_space_folder_files as script_mod
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from scripts.reparse_knowledge_space_files import SelectionReport


def _folder(
    folder_id: int,
    name: str,
    *,
    file_level_path: str = "",
    knowledge_id: int = 10,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=folder_id,
        knowledge_id=knowledge_id,
        file_name=name,
        file_type=FileType.DIR.value,
        file_level_path=file_level_path,
    )


class _Bypass:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_split_folder_path_accepts_slash_and_arrow_separators() -> None:
    assert script_mod.split_folder_path(" 安全生产 / 消防安全 ") == ["安全生产", "消防安全"]
    assert script_mod.split_folder_path("安全生产->消防安全") == ["安全生产", "消防安全"]
    assert script_mod.split_folder_path("安全生产>消防安全") == ["安全生产", "消防安全"]
    assert script_mod.split_folder_path("消防安全") == ["消防安全"]


def test_split_folder_path_rejects_blank() -> None:
    with pytest.raises(script_mod.TargetLookupError, match="empty"):
        script_mod.split_folder_path("   ")


def test_is_space_root_path_accepts_slash() -> None:
    assert script_mod.is_space_root_path("/")
    assert script_mod.is_space_root_path(" / ")
    assert script_mod.is_space_root_path("root")
    assert not script_mod.is_space_root_path("消防安全")
    assert not script_mod.is_space_root_path("安全生产/消防安全")


def test_resolve_folder_walks_nested_name_path() -> None:
    root = _folder(10, "安全生产")
    child = _folder(20, "消防安全", file_level_path="/10")
    nested = _folder(30, "应急预案", file_level_path="/10/20")

    found = script_mod.resolve_folder([root, child, nested], "安全生产/消防安全/应急预案")

    assert found.id == 30


def test_resolve_named_folder_accepts_unique_leaf_name() -> None:
    root = _folder(10, "安全生产")
    child = _folder(20, "消防安全", file_level_path="/10")
    folder, path = script_mod.resolve_named_folder([root, child], "消防安全")

    assert folder.id == 20
    assert path == "安全生产/消防安全"


def test_resolve_named_folder_requires_full_path_when_name_repeats() -> None:
    safety = _folder(10, "安全生产")
    quality = _folder(11, "质量管理")
    nested = _folder(20, "制度", file_level_path="/10")
    other = _folder(21, "制度", file_level_path="/11")
    folders = [safety, quality, nested, other]

    with pytest.raises(script_mod.TargetLookupError, match="not unique"):
        script_mod.resolve_named_folder(folders, "制度")

    found, path = script_mod.resolve_named_folder(folders, "安全生产/制度")
    assert found.id == 20
    assert path == "安全生产/制度"


def test_eligible_statuses_default_to_failed_only() -> None:
    assert script_mod.eligible_statuses(include_timeout=False) == (KnowledgeFileStatus.FAILED.value,)
    assert script_mod.eligible_statuses(include_timeout=True) == (
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.TIMEOUT.value,
    )


def test_parse_args_requires_space_and_folder() -> None:
    with pytest.raises(SystemExit):
        script_mod.parse_args([])
    args = script_mod.parse_args(["--space-name", "库A", "--folder", "目录/子目录"])
    assert args.apply is False
    assert args.space_name == "库A"
    assert args.folder == "目录/子目录"
    assert args.tenant_id is None
    assert args.include_timeout is False


async def test_run_dry_run_prints_failed_files_and_does_not_enqueue(monkeypatch, capsys) -> None:
    space = SimpleNamespace(id=10, tenant_id=1, name="库A")
    folder = _folder(20, "消防安全", file_level_path="/10")
    failed = KnowledgeFile(
        id=101,
        knowledge_id=10,
        file_name="失败文件.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.FAILED.value,
        remark="parse error",
    )
    selection = SelectionReport(selected_files=[failed])
    applied: list[bool] = []

    async def fake_resolve_target(session, **kwargs):
        assert kwargs["space_name"] == "库A"
        return script_mod.ResolvedTarget(space=space, folder=folder, folder_path="安全生产/消防安全")

    async def fake_collect_candidate_files(session, **kwargs):
        assert kwargs["folder_ids"] == [20]
        assert kwargs["eligible_statuses"] == (KnowledgeFileStatus.FAILED.value,)
        return selection

    async def fake_close_app_context():
        return None

    monkeypatch.setattr(script_mod, "bypass_tenant_filter", lambda: _Bypass())
    monkeypatch.setattr(script_mod, "get_async_db_session", lambda: _Session())
    monkeypatch.setattr(script_mod, "resolve_target", fake_resolve_target)
    monkeypatch.setattr(script_mod, "collect_candidate_files", fake_collect_candidate_files)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)
    monkeypatch.setattr(
        script_mod,
        "apply_selection",
        lambda *args, **kwargs: applied.append(kwargs["apply"]) or None,
    )

    code = await script_mod.run(script_mod.parse_args(["--space-name", "库A", "--folder", "消防安全"]))

    assert code == 0
    assert applied == [False]
    output = capsys.readouterr().out
    assert "失败文件.pdf" in output
    assert "file_id=101" in output
    assert "path=安全生产/消防安全" in output


async def test_run_space_root_selects_entire_space(monkeypatch, capsys) -> None:
    space = SimpleNamespace(id=10, tenant_id=1, name="admin的知识库")
    failed = KnowledgeFile(
        id=101,
        knowledge_id=10,
        file_name="根目录失败.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.FAILED.value,
        remark="parse error",
    )
    selection = SelectionReport(selected_files=[failed])
    collect_kwargs: dict = {}

    async def fake_resolve_target(session, **kwargs):
        assert kwargs["folder_path"] == "/"
        return script_mod.ResolvedTarget(space=space, folder=None, folder_path="/")

    async def fake_collect_candidate_files(session, **kwargs):
        collect_kwargs.update(kwargs)
        return selection

    async def fake_close_app_context():
        return None

    monkeypatch.setattr(script_mod, "bypass_tenant_filter", lambda: _Bypass())
    monkeypatch.setattr(script_mod, "get_async_db_session", lambda: _Session())
    monkeypatch.setattr(script_mod, "resolve_target", fake_resolve_target)
    monkeypatch.setattr(script_mod, "collect_candidate_files", fake_collect_candidate_files)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)
    monkeypatch.setattr(script_mod, "apply_selection", lambda *args, **kwargs: None)

    code = await script_mod.run(
        script_mod.parse_args(["--space-name", "admin的知识库", "--folder", "/"]),
    )

    assert code == 0
    assert collect_kwargs["space_ids"] == [10]
    assert "folder_ids" not in collect_kwargs or collect_kwargs.get("folder_ids") in ((), [], None)
    output = capsys.readouterr().out
    assert "entire space" in output
    assert "根目录失败.pdf" in output
