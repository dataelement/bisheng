"""Tests for the space-aware free-space -> department-space migration task.

``bisheng.worker.__init__`` eagerly imports the full Celery task universe
(config_service reads config.yaml from disk, etc.), which breaks in the
unit-test environment. On top of that, ``test/fixtures/mock_services.py``
premocks ``bisheng.worker`` / ``bisheng.worker.main`` /
``bisheng.worker.knowledge`` / ``bisheng.worker.knowledge.file_worker`` as
bare ``MagicMock()`` objects inserted directly into ``sys.modules`` --
bypassing the parent-package attribute link that a normal import sets up.
That means ``unittest.mock.patch("bisheng.worker...")`` string targets can
never resolve for the rest of the test session (``mock._importer`` does
``getattr(bisheng_module, "worker")``, which stays unset forever once the
premock's fast cached-import path is hit).

The established workaround in this suite (see test_tenant_reconcile_task.py,
test_admin_scope_cleanup_task.py, test_file_worker_copy_normal.py) is to
side-load the target module directly from its file via ``importlib``, with
a stubbed passthrough ``bisheng_celery.task`` decorator, and then patch
attributes directly on the loaded module object (or the real DAO classes it
imported) via ``monkeypatch`` instead of string-based ``patch()``.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

_MISSING = object()


def _load_space_migrate_worker() -> ModuleType:
    stubs = {
        "bisheng.worker.main": SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn)),
        ),
    }
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in stubs}
    try:
        sys.modules.update(stubs)
        path = (
            Path(__file__).parents[1]
            / "bisheng" / "worker" / "knowledge" / "space_migrate_worker.py"
        )
        spec = importlib.util.spec_from_file_location(
            "test_space_migrate_worker_under_test", path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


m = _load_space_migrate_worker()

from bisheng.knowledge.domain.models.knowledge import KnowledgeState  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFileStatus,
)


def _kfile(id, md5, status=2, file_type=FileType.FILE.value):
    return SimpleNamespace(id=id, md5=md5, status=status, file_type=file_type)


def test_migrate_skips_duplicate_md5_and_copies_rest(monkeypatch):
    source = SimpleNamespace(id=1, name="自由库", state=1, update_time=None, model="e")
    target = SimpleNamespace(id=2, state=1, update_time=None, model="e")
    a_dir = SimpleNamespace(id=12, md5="z", status=KnowledgeFileStatus.SUCCESS.value,
                            file_type=FileType.DIR.value)
    target_folder = SimpleNamespace(
        id=99,
        file_name="自由库",
        file_type=FileType.DIR.value,
        file_level_path="",
        level=0,
        md5=None,
    )
    pages = [[_kfile(10, "a"), _kfile(11, "b"), a_dir], []]

    monkeypatch.setattr(
        m.KnowledgeDao,
        "query_by_id",
        staticmethod(lambda i: source if i == 1 else target),
    )
    update_state = MagicMock()
    monkeypatch.setattr(m.KnowledgeDao, "update_state", update_state)
    monkeypatch.setattr(
        m.KnowledgeFileDao,
        "get_file_by_condition",
        staticmethod(lambda kid: [_kfile(98, "a"), target_folder]),
    )
    monkeypatch.setattr(
        m.KnowledgeFileDao,
        "get_file_by_filters",
        staticmethod(lambda kid, status=None, page=1, page_size=20: pages[page - 1]),
    )
    copy_normal = MagicMock(
        return_value=SimpleNamespace(status=KnowledgeFileStatus.SUCCESS.value),
    )
    monkeypatch.setattr(m, "copy_normal", copy_normal)
    del_src = AsyncMock()
    monkeypatch.setattr(m, "_delete_source_space", del_src)

    result = m.space_migrate_celery({"source_id": 1, "target_id": 2, "op_user_id": 5})

    copied_ids = [c.args[0].id for c in copy_normal.call_args_list]
    assert copied_ids == [11]          # md5 "a" 已存在于目标，跳过 id=10；目录 id=12 被跳过
    assert copy_normal.call_args.kwargs == {
        "target_level": 1,
        "target_file_level_path": "/99",
    }
    del_src.assert_called_once()        # 成功后删源库
    assert result == "space migrate done"
    update_state.assert_not_called()    # 成功路径不应触发回滚


def test_migrate_failure_rolls_back_state_and_keeps_source(monkeypatch):
    source = SimpleNamespace(id=1, name="自由库", state=1, update_time=None, model="e")
    target = SimpleNamespace(id=2, state=1, update_time=None, model="e")

    monkeypatch.setattr(
        m.KnowledgeDao,
        "query_by_id",
        staticmethod(lambda i: source if i == 1 else target),
    )
    update_state = MagicMock()
    monkeypatch.setattr(m.KnowledgeDao, "update_state", update_state)
    monkeypatch.setattr(
        m.KnowledgeFileDao,
        "get_file_by_condition",
        staticmethod(lambda kid: []),
    )
    monkeypatch.setattr(
        m,
        "_get_or_create_migration_folder",
        lambda **_kwargs: SimpleNamespace(id=99, file_level_path="", level=0),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(m.KnowledgeFileDao, "get_file_by_filters", staticmethod(_boom))
    del_src = AsyncMock()
    monkeypatch.setattr(m, "_delete_source_space", del_src)

    result = m.space_migrate_celery({"source_id": 1, "target_id": 2, "op_user_id": 5})

    del_src.assert_not_called()         # 失败不删源库
    assert result == "space migrate failed"
    # 最后一次 update_state 把源库恢复为 PUBLISHED（回滚迁移中）
    last = update_state.call_args_list[-1]
    assert last.kwargs.get("state") == KnowledgeState.PUBLISHED or (
        last.args[1:] and last.args[1] == KnowledgeState.PUBLISHED
    )


def test_migrate_aborts_and_keeps_source_when_copy_fails(monkeypatch):
    """copy_normal 对某个源文件复制失败（返回 None 或 status==FAILED）时，
    迁移必须整体中止：不删源库、状态回滚为 PUBLISHED、返回失败文案。
    这防止「复制失败仍删源库」导致的丢文件（Imp-1）。
    """
    source = SimpleNamespace(id=1, name="自由库", state=1, update_time=None, model="e")
    target = SimpleNamespace(id=2, state=1, update_time=None, model="e")
    pages = [[_kfile(10, "a"), _kfile(11, "b")], []]

    monkeypatch.setattr(
        m.KnowledgeDao,
        "query_by_id",
        staticmethod(lambda i: source if i == 1 else target),
    )
    update_state = MagicMock()
    monkeypatch.setattr(m.KnowledgeDao, "update_state", update_state)
    monkeypatch.setattr(
        m.KnowledgeFileDao,
        "get_file_by_condition",
        staticmethod(lambda kid: []),
    )
    monkeypatch.setattr(
        m,
        "_get_or_create_migration_folder",
        lambda **_kwargs: SimpleNamespace(id=99, file_level_path="", level=0),
    )
    monkeypatch.setattr(
        m.KnowledgeFileDao,
        "get_file_by_filters",
        staticmethod(lambda kid, status=None, page=1, page_size=20: pages[page - 1]),
    )
    copy_normal = MagicMock(
        return_value=SimpleNamespace(status=KnowledgeFileStatus.FAILED.value),
    )
    monkeypatch.setattr(m, "copy_normal", copy_normal)
    del_src = AsyncMock()
    monkeypatch.setattr(m, "_delete_source_space", del_src)

    result = m.space_migrate_celery({"source_id": 1, "target_id": 2, "op_user_id": 5})

    del_src.assert_not_called()         # 复制失败必须保留源库，绝不能删
    assert result == "space migrate failed"
    last = update_state.call_args_list[-1]
    assert last.kwargs.get("state") == KnowledgeState.PUBLISHED or (
        last.args[1:] and last.args[1] == KnowledgeState.PUBLISHED
    )


def test_migrate_reuses_same_named_root_folder(monkeypatch):
    folder = SimpleNamespace(
        id=99,
        file_name="自由库",
        file_type=FileType.DIR.value,
        file_level_path=None,
        level=0,
    )
    create = MagicMock()
    monkeypatch.setattr(m, "run_async_safe", create)

    result = m._get_or_create_migration_folder(
        target_id=2,
        source_name="自由库",
        target_files=[folder],
        op_user_id=5,
    )

    assert result is folder
    create.assert_not_called()


def test_migrate_creates_root_folder_when_name_is_absent(monkeypatch):
    created_folder = SimpleNamespace(id=100, file_name="自由库", file_level_path="", level=0)

    async def create_folder(*_args):
        return created_folder

    monkeypatch.setattr(m, "_create_migration_folder", create_folder)
    monkeypatch.setattr(m, "run_async_safe", lambda coro, *, timeout: asyncio.run(coro))

    result = m._get_or_create_migration_folder(
        target_id=2,
        source_name="自由库",
        target_files=[],
        op_user_id=5,
    )

    assert result is created_folder


def test_worker_request_supports_get_request_ip():
    """删源库会走 delete_space 的审计日志 get_request_ip(request)，它读 request.headers，
    并在无代理头时读 request.client.host。worker 造的 Request 必须带 headers+client，
    否则 starlette 在 list(scope["headers"]) 抛 KeyError: 'headers'，迁移在删源库处崩溃
    （真实环境 source=167/177 已复现）。"""
    from bisheng.utils import get_request_ip

    assert get_request_ip(m._worker_request()) == "127.0.0.1"
