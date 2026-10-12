"""F073 task view, download and terminate (spec AC-20, AC-22, AC-23, AC-24, AC-25,
AC-26, AC-28, AC-29, AC-30, AC-31)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode import open_api as errors
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.session import MessageSession
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, SessionVersionStatusEnum
from bisheng.open_api.domain.services import task_mode_service
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from test.open_api.task_mode_support import delegated_principal, sa_principal

S = SessionVersionStatusEnum


def _version(status=S.NOT_STARTED, output=None, files=None) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="svid-1",
        session_id="chat-1",
        user_id=12,
        question="q",
        status=status,
        output_result=output,
        files=files,
        tenant_id=9,
    )


def _sa_session(**overrides) -> MessageSession:
    subject = SessionSubject.service_account(
        tenant_id=9, service_account_id=31, resource_owner_user_id=12, external_user_id="emp-1"
    )
    session = subject.stamp(MessageSession(chat_id="chat-1", name="n", flow_type=15, user_id=12))
    session.is_delete = False
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


@pytest.fixture
def store(monkeypatch):
    state = SimpleNamespace(version=_version(), session=_sa_session(), todos=[], sizes={}, terminated=[])

    async def _get_version(task_id):
        return state.version if state.version and task_id == state.version.id else None

    async def _get_session(_chat_id):
        return state.session

    async def _todos(_svid, is_parent_task=False):
        assert is_parent_task is True
        return state.todos

    async def _size(object_name):
        return state.sizes.get(object_name)

    async def _terminate(version):
        state.terminated.append(version.id)
        version.status = S.TERMINATED

    monkeypatch.setattr(task_mode_service.LinsightSessionVersionDao, "get_by_id", _get_version)
    monkeypatch.setattr(task_mode_service.MessageSessionDao, "async_get_one", _get_session)
    monkeypatch.setattr(task_mode_service.LinsightExecuteTaskDao, "get_by_session_version_id", _todos)
    monkeypatch.setattr(OpenTaskModeService, "_object_size", staticmethod(_size))
    monkeypatch.setattr(OpenTaskModeService, "_queue_position", staticmethod(AsyncMock(return_value=None)))
    monkeypatch.setattr("bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.terminate", _terminate)
    return state


async def test_queued_task_reports_its_position(store, monkeypatch):
    monkeypatch.setattr(OpenTaskModeService, "_queue_position", staticmethod(AsyncMock(return_value=4)))
    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert view.status.value == "queued"
    assert view.queue_position == 4
    assert view.result is None


async def test_running_task_counts_todos_without_the_pseudo_task(store):
    store.version = _version(S.IN_PROGRESS)
    store.todos = [
        SimpleNamespace(id="svid-1", status=ExecuteTaskStatusEnum.IN_PROGRESS),  # session pseudo task
        SimpleNamespace(id="t1", status=ExecuteTaskStatusEnum.SUCCESS),
        SimpleNamespace(id="t2", status=ExecuteTaskStatusEnum.IN_PROGRESS),
        SimpleNamespace(id="t3", status=ExecuteTaskStatusEnum.NOT_STARTED),
    ]
    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert view.status.value == "running"
    assert (view.progress.done, view.progress.total) == (1, 3)


async def test_running_task_before_planning_has_empty_progress(store):
    store.version = _version(S.IN_PROGRESS)
    store.todos = [SimpleNamespace(id="svid-1", status=ExecuteTaskStatusEnum.IN_PROGRESS)]
    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert view.progress is None


async def test_completed_result_is_projected_without_internals(store):
    store.version = _version(
        S.COMPLETED,
        output={
            "answer": "Risk found kb_1_2 in clause 3 [S2].",
            "final_files": [
                {
                    "file_id": "f1",
                    "file_name": "Report.DOCX",
                    "file_path": "/root/.cache/x/Report.docx",
                    "file_url": "linsight/final_result/svid-1/f1.docx",
                },
                {
                    "file_id": "f2",
                    "file_name": "notes.md",
                    "file_path": "/root/.cache/x/notes.md",
                    "file_url": "linsight/final_result/svid-1/f2.md",
                },
            ],
            "phantom_deliverables": ["summary.pdf"],
            "invalid_deliverables": [
                {"file_name": "table.xlsx", "rel_path": "output/table.xlsx", "reason": "not a zip"}
            ],
            "partial": True,
        },
        files=[
            {"original_filename": "scan.tiff", "parsing_status": "unsupported", "valid": False},
            {"original_filename": "ok.pdf", "parsing_status": "completed", "valid": True},
        ],
    )
    store.sizes = {"linsight/final_result/svid-1/f1.docx": 2048}

    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")

    assert view.status.value == "completed"
    assert view.partial is True
    result = view.result
    assert "" not in result.answer and "[S2]" not in result.answer
    assert [f.file_id for f in result.files] == ["f1", "f2"]
    assert result.files[0].primary is True and result.files[1].primary is False
    assert result.files[0].file_type == "docx" and result.files[0].size == 2048
    assert result.files[1].size is None
    dumped = view.model_dump_json()
    assert "/root/.cache" not in dumped and "final_result" not in dumped
    assert [(d.file_name, d.reason) for d in result.unavailable_deliverables] == [
        ("summary.pdf", "not_generated"),
        ("table.xlsx", "invalid_format"),
    ]
    assert [(a.file_name, a.reason) for a in result.attachments] == [("scan.tiff", "unsupported")]


@pytest.mark.parametrize(
    "output,category",
    [
        ({"error_message": "quota", "error_type": "quota_exhausted"}, "quota_exhausted"),
        ({"error_message": "Worker node crash detected"}, "unknown"),
    ],
)
async def test_failed_task_reports_a_category(store, output, category):
    store.version = _version(S.FAILED, output=output)
    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert view.status.value == "failed"
    assert view.failure.category == category
    assert view.failure.message == output["error_message"]


async def test_sop_generation_failure_is_failed_and_terminated_has_no_result(store):
    store.version = _version(S.SOP_GENERATION_FAILED, output={})
    assert (await OpenTaskModeService.get_view(sa_principal(), "svid-1")).status.value == "failed"
    store.version = _version(S.TERMINATED, output={"answer": "stopped"})
    view = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert view.status.value == "terminated" and view.result is None


async def test_repeated_queries_on_a_finished_task_are_identical(store):
    store.version = _version(S.COMPLETED, output={"answer": "done", "final_files": []})
    first = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    second = await OpenTaskModeService.get_view(sa_principal(), "svid-1")
    assert first == second


@pytest.mark.parametrize(
    "principal_factory,session_overrides",
    [
        # another service account
        (lambda: sa_principal().model_copy(update={"actor_id": 99, "authorization_subject_id": 99}), {}),
        # same service account, another external user
        (lambda: sa_principal().model_copy(update={"end_user_id": "emp-2"}), {}),
        # a delegated user looking at a service-account run
        (delegated_principal, {}),
        # the service account looking at a session that belongs to a natural person
        (sa_principal, {"api_subject_type": None, "api_subject_id": None, "external_user_id": None}),
    ],
)
async def test_other_callers_get_404_everywhere(store, principal_factory, session_overrides):
    store.version = _version(S.COMPLETED, output={"answer": "a", "final_files": [{"file_id": "f1", "file_url": "k"}]})
    store.session = _sa_session(**session_overrides)
    principal = principal_factory()
    with pytest.raises(NotFoundError):
        await OpenTaskModeService.get_view(principal, "svid-1")
    with pytest.raises(NotFoundError):
        await OpenTaskModeService.download(principal, "svid-1", "f1")
    with pytest.raises(NotFoundError):
        await OpenTaskModeService.terminate(principal, "svid-1")


async def test_unknown_task_is_404(store):
    with pytest.raises(NotFoundError):
        await OpenTaskModeService.get_view(sa_principal(), "nope")


@pytest.mark.parametrize("status", [S.COMPLETED, S.FAILED, S.SOP_GENERATION_FAILED, S.TERMINATED])
async def test_finished_tasks_cannot_be_terminated(store, status):
    store.version = _version(status, output={})
    with pytest.raises(errors.OpenApiTaskAlreadyFinishedError):
        await OpenTaskModeService.terminate(sa_principal(), "svid-1")
    assert store.terminated == []


@pytest.mark.parametrize("status", [S.NOT_STARTED, S.IN_PROGRESS])
async def test_queued_or_running_tasks_are_terminated(store, status):
    store.version = _version(status)
    view = await OpenTaskModeService.terminate(sa_principal(), "svid-1")
    assert store.terminated == ["svid-1"]
    assert view.status.value == "terminated"


async def test_download_only_reaches_this_tasks_own_files(store, monkeypatch):
    store.version = _version(
        S.COMPLETED,
        output={
            "answer": "a",
            "final_files": [
                {"file_id": "f1", "file_name": "报告.md", "file_url": "linsight/final_result/svid-1/f1.md"}
            ],
        },
    )
    fetched = []

    class _Resp:
        def stream(self, _size):
            yield b"# report"

        def close(self):
            pass

        def release_conn(self):
            pass

    def _download(object_name=None, bucket_name=None):
        fetched.append(object_name)
        return _Resp()

    monkeypatch.setattr(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=SimpleNamespace(download_object_sync=_download)),
    )

    response = await OpenTaskModeService.download(sa_principal(), "svid-1", "f1")
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == b"# report"
    assert fetched == ["linsight/final_result/svid-1/f1.md"]
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.md" in response.headers["content-disposition"]

    with pytest.raises(NotFoundError):
        await OpenTaskModeService.download(sa_principal(), "svid-1", "linsight/final_result/other/x.md")
