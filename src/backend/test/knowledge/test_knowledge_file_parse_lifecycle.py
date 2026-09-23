from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseAttemptKind,
)


class _DummyFileProcessBase:
    def __init__(self, **_kwargs):
        pass


class _DummyLLMService:
    pass


def _load_file_worker():
    api_module = ModuleType("bisheng.api")
    api_module.__path__ = []
    api_services_module = ModuleType("bisheng.api.services")
    api_services_module.__path__ = []
    knowledge_imp_module = ModuleType("bisheng.api.services.knowledge_imp")
    api_v1_module = ModuleType("bisheng.api.v1")
    api_v1_module.__path__ = []
    api_v1_schemas_module = ModuleType("bisheng.api.v1.schemas")
    llm_domain_module = ModuleType("bisheng.llm.domain")
    lease_module = ModuleType("bisheng.knowledge.domain.services.knowledge_parse_processing_lease")

    knowledge_imp_module.process_file_task = lambda *args, **kwargs: None
    knowledge_imp_module.delete_knowledge_file_vectors = lambda *args, **kwargs: None
    knowledge_imp_module.delete_vector_files = lambda *args, **kwargs: None
    knowledge_imp_module.KnowledgeUtils = object
    api_v1_schemas_module.FileProcessBase = _DummyFileProcessBase
    api_v1_schemas_module.WSModel = object
    llm_domain_module.LLMService = _DummyLLMService
    api_module.services = api_services_module
    api_module.v1 = api_v1_module
    api_services_module.knowledge_imp = knowledge_imp_module
    api_v1_module.schemas = api_v1_schemas_module
    lease_module.track_knowledge_parse_delivery = lambda _kind: lambda function: function
    lease_module.current_knowledge_parse_attempt_kind = lambda: None

    stubs = {
        "bisheng.api": api_module,
        "bisheng.api.services": api_services_module,
        "bisheng.api.services.knowledge_imp": knowledge_imp_module,
        "bisheng.api.v1": api_v1_module,
        "bisheng.api.v1.schemas": api_v1_schemas_module,
        "bisheng.llm.domain": llm_domain_module,
        "bisheng.knowledge.domain.services.knowledge_parse_processing_lease": lease_module,
        "bisheng.worker.main": SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda **_kwargs: lambda function: function),
        ),
    }
    previous_modules = {name: sys.modules.get(name) for name in stubs}
    try:
        sys.modules.update(stubs)
        module_path = Path(__file__).resolve().parents[2] / "bisheng/worker/knowledge/file_worker.py"
        spec = importlib.util.spec_from_file_location(
            "knowledge_file_parse_lifecycle_worker_under_test",
            module_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


file_worker = _load_file_worker()


def test_inline_similarity_waits_for_result_and_preserves_parse_trace() -> None:
    refresh = AsyncMock(return_value=3)
    token = file_worker.trace_id_var.set("parse_file_101")
    try:
        with (
            patch.object(file_worker, "_refresh_file_similarity_candidates", refresh),
            patch.dict(
                sys.modules,
                {"bisheng.worker._asyncio_utils": SimpleNamespace(
                    run_async_task=lambda factory: asyncio.run(factory()),
                )},
            ),
        ):
            assert file_worker.refresh_file_similarity_candidates(101) == 3
            refresh.assert_awaited_once_with(101)
            assert file_worker.trace_id_var.get() == "parse_file_101"

    finally:
        file_worker.trace_id_var.reset(token)


def _title_worker_stub(events: list[str]) -> ModuleType:
    module = ModuleType("bisheng.worker.knowledge.file_title_worker")
    module.extract_and_generate_alias = MagicMock(side_effect=lambda _file_id: events.append("title"))
    return module


def test_initial_lifecycle_marks_processing_before_title_and_parse() -> None:
    events: list[str] = []

    with (
        patch.object(
            file_worker,
            "_prepare_knowledge_file_for_processing",
            side_effect=lambda _file_id: events.append("processing") or True,
            create=True,
        ),
        patch.object(
            file_worker,
            "_run_formal_parse_delivery",
            side_effect=lambda *_args, **_kwargs: events.append("parse"),
            create=True,
        ),
        patch.dict(
            sys.modules,
            {"bisheng.worker.knowledge.file_title_worker": _title_worker_stub(events)},
        ),
    ):
        file_worker.run_initial_knowledge_parse_lifecycle(101, "preview", "callback")

    assert events == ["processing", "title", "parse"]


def test_initial_lifecycle_continues_formal_parse_when_title_step_raises() -> None:
    title_worker = _title_worker_stub([])
    title_worker.extract_and_generate_alias.side_effect = RuntimeError("title failed")
    formal_parse = MagicMock()

    with (
        patch.object(file_worker, "_prepare_knowledge_file_for_processing", return_value=True),
        patch.object(file_worker, "_run_formal_parse_delivery", formal_parse),
        patch.dict(
            sys.modules,
            {"bisheng.worker.knowledge.file_title_worker": title_worker},
        ),
    ):
        file_worker.run_initial_knowledge_parse_lifecycle(103, "preview", "callback")

    formal_parse.assert_called_once_with(
        103,
        "preview",
        "callback",
        complete_filelib_sync=True,
    )


def test_retry_lifecycle_marks_processing_before_cleanup_and_skips_title() -> None:
    events: list[str] = []
    title_worker = _title_worker_stub(events)

    with (
        patch.object(
            file_worker,
            "_prepare_knowledge_file_for_processing",
            side_effect=lambda _file_id: events.append("processing") or True,
            create=True,
        ),
        patch.object(
            file_worker,
            "delete_knowledge_file_vectors",
            side_effect=lambda **_kwargs: events.append("cleanup"),
        ),
        patch.object(
            file_worker,
            "_run_formal_parse_delivery",
            side_effect=lambda *_args, **_kwargs: events.append("parse"),
            create=True,
        ),
        patch.dict(
            sys.modules,
            {"bisheng.worker.knowledge.file_title_worker": title_worker},
        ),
    ):
        file_worker.run_retry_knowledge_parse_lifecycle(102, "preview", "callback")

    assert events == ["processing", "cleanup", "parse"]
    title_worker.extract_and_generate_alias.assert_not_called()


def test_retry_cleanup_failure_marks_file_failed_and_skips_formal_parse() -> None:
    formal_parse = MagicMock()

    with (
        patch.object(file_worker, "_prepare_knowledge_file_for_processing", return_value=True),
        patch.object(
            file_worker,
            "delete_knowledge_file_vectors",
            side_effect=RuntimeError("cleanup failed"),
        ),
        patch.object(file_worker.KnowledgeFileDao, "update_file_status") as update_status,
        patch.object(file_worker.KnowledgeFileDao, "get_file_by_ids", return_value=[]),
        patch.object(file_worker, "_run_formal_parse_delivery", formal_parse),
        patch.object(file_worker, "_enqueue_recommendation_projection_refresh"),
    ):
        file_worker.run_retry_knowledge_parse_lifecycle(104, "preview", "callback")

    assert update_status.call_args.args[:2] == (
        [104],
        KnowledgeFileStatus.FAILED,
    )
    formal_parse.assert_not_called()


def test_new_and_legacy_formal_parse_messages_follow_compatible_paths() -> None:
    initial_lifecycle = MagicMock()
    formal_parse = MagicMock()

    with (
        patch.object(
            file_worker,
            "current_knowledge_parse_attempt_kind",
            return_value=KnowledgeParseAttemptKind.INITIAL,
        ),
        patch.object(file_worker, "run_initial_knowledge_parse_lifecycle", initial_lifecycle),
        patch.object(file_worker, "_run_formal_parse_delivery", formal_parse),
    ):
        file_worker.parse_knowledge_file_celery(105, "preview", "callback")

    initial_lifecycle.assert_called_once_with(105, "preview", "callback")
    formal_parse.assert_not_called()

    initial_lifecycle.reset_mock()
    with (
        patch.object(file_worker, "current_knowledge_parse_attempt_kind", return_value=None),
        patch.object(file_worker, "run_initial_knowledge_parse_lifecycle", initial_lifecycle),
        patch.object(file_worker, "_run_formal_parse_delivery", formal_parse),
    ):
        file_worker.parse_knowledge_file_celery(106, "preview", "callback")

    initial_lifecycle.assert_not_called()
    formal_parse.assert_called_once_with(
        106,
        "preview",
        "callback",
        complete_filelib_sync=True,
    )


@pytest.mark.parametrize(
    ("overrides", "space_level", "should_publish"),
    [
        pytest.param({}, "department", True, id="shared-manager"),
        pytest.param({"entry_type": None, "reference_document_id": None}, "department", True, id="legacy-file"),
        pytest.param({"entry_type": "publish"}, "department", False, id="publish-reference"),
        pytest.param({"entry_type": "share"}, "department", False, id="share-reference"),
        pytest.param({"entry_type": "projection_tombstone"}, "department", False, id="tombstone"),
        pytest.param({"entry_status": "preparing"}, "department", False, id="preparing-manager"),
        pytest.param({"entry_status": "deleting"}, "department", False, id="deleting-manager"),
        pytest.param({"entry_status": "invalid"}, "department", False, id="invalid-manager"),
        pytest.param({"deleted_at": "2026-09-23"}, "department", False, id="recycled-manager"),
        pytest.param({"reference_document_id": None}, "department", False, id="manager-without-document"),
        pytest.param({}, "public", False, id="published-manager-in-public-space"),
        pytest.param({"file_subcategory_code": None}, "department", False, id="missing-subcategory"),
        pytest.param({"file_type": 0}, "department", False, id="directory"),
        pytest.param({"status": KnowledgeFileStatus.FAILED.value}, "department", False, id="failed-parse"),
    ],
)
def test_parse_completion_dispatches_auto_publish_for_eligible_manager(overrides, space_level, should_publish):
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    file = SimpleNamespace(**{
        "id": 101,
        "tenant_id": 7,
        "knowledge_id": 9,
        "file_type": 1,
        "status": KnowledgeFileStatus.SUCCESS.value,
        "entry_type": "manager",
        "entry_status": "active",
        "reference_document_id": 42,
        "deleted_at": None,
        "file_subcategory_code": "POL-A",
        "split_rule": {},
        **overrides,
    })
    scope_lookup = AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum(space_level)))
    dispatch = MagicMock()
    with (
        patch.object(file_worker, "_parse_knowledge_file", return_value=SimpleNamespace(id=9)),
        patch.object(file_worker.KnowledgeFileDao, "get_file_by_ids", return_value=[file]),
        patch.object(file_worker, "_mark_manager_projection_after_parse"),
        patch.object(file_worker, "_complete_filelib_sync_version_link_if_needed"),
        patch.object(file_worker, "_enqueue_recommendation_projection_refresh"),
        patch.object(file_worker, "_enqueue_current_pdf_artifact_sync"),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_by_space_id",
            scope_lookup,
        ),
        patch(
            "bisheng.knowledge.domain.constants.get_file_category_code_from_split_rule",
            return_value="POL",
        ),
        patch.dict(sys.modules, {
            "bisheng.worker._asyncio_utils": SimpleNamespace(run_async_task=lambda factory: asyncio.run(factory())),
            "bisheng.worker.knowledge.auto_publish_worker": SimpleNamespace(
                auto_publish_file_celery=SimpleNamespace(apply_async=dispatch),
            ),
        }),
    ):
        file_worker._run_formal_parse_delivery(101, complete_filelib_sync=True)

    if should_publish:
        dispatch.assert_called_once_with(args=(101, 7), queue="celery")
        scope_lookup.assert_awaited_once_with(9)
    else:
        dispatch.assert_not_called()
