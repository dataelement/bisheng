import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus


class _DummyKnowledgeUtils:
    @staticmethod
    def get_knowledge_file_object_name(file_id, file_name):
        return f'target/{file_id}/{file_name}'

    @staticmethod
    def get_knowledge_bbox_file_object_name(file_id):
        return f'target/{file_id}/bbox'

    @staticmethod
    def get_knowledge_preview_file_object_name(file_id, file_name):
        return f'target/{file_id}/{file_name}.preview'


class _DummyFileProcessBase:
    pass


class _DummyLLMService:
    @staticmethod
    def get_bisheng_knowledge_embedding_sync(*_args, **_kwargs):
        return None


_MISSING = object()


def _load_file_worker():
    api_module = ModuleType('bisheng.api')
    api_module.__path__ = []
    api_services_module = ModuleType('bisheng.api.services')
    api_services_module.__path__ = []
    knowledge_imp_module = ModuleType('bisheng.api.services.knowledge_imp')
    api_v1_module = ModuleType('bisheng.api.v1')
    api_v1_module.__path__ = []
    api_v1_schemas_module = ModuleType('bisheng.api.v1.schemas')
    llm_domain_module = ModuleType('bisheng.llm.domain')

    knowledge_imp_module.process_file_task = lambda *args, **kwargs: None
    knowledge_imp_module.delete_knowledge_file_vectors = lambda *args, **kwargs: None
    knowledge_imp_module.delete_vector_files = lambda *args, **kwargs: None
    knowledge_imp_module.KnowledgeUtils = _DummyKnowledgeUtils
    api_v1_schemas_module.FileProcessBase = _DummyFileProcessBase
    api_v1_schemas_module.KnowledgeFileOne = _DummyFileProcessBase
    api_v1_schemas_module.ExcelRule = _DummyFileProcessBase
    api_v1_schemas_module.WSModel = object
    llm_domain_module.LLMService = _DummyLLMService
    api_module.services = api_services_module
    api_module.v1 = api_v1_module
    api_services_module.knowledge_imp = knowledge_imp_module
    api_v1_module.schemas = api_v1_schemas_module

    stubs = {
        'bisheng.api': api_module,
        'bisheng.api.services': api_services_module,
        'bisheng.api.services.knowledge_imp': knowledge_imp_module,
        'bisheng.api.v1': api_v1_module,
        'bisheng.api.v1.schemas': api_v1_schemas_module,
        'bisheng.llm.domain': llm_domain_module,
        'bisheng.worker.main': SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn)),
        ),
    }
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in stubs}
    try:
        sys.modules.update(stubs)
        file_worker_path = Path(__file__).parents[1] / 'bisheng' / 'worker' / 'knowledge' / 'file_worker.py'
        spec = importlib.util.spec_from_file_location('test_file_worker_under_test', file_worker_path)
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


file_worker = _load_file_worker()


def _make_space(space_id: int) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=7,
        name=f'space-{space_id}',
        type=KnowledgeTypeEnum.SPACE.value,
        model='model-1',
        state=KnowledgeState.PUBLISHED.value,
    )


def _make_file() -> KnowledgeFile:
    return KnowledgeFile(
        id=1580,
        user_id=7,
        knowledge_id=12,
        file_name='迁移指南.pdf',
        file_type=FileType.FILE.value,
        object_name='source/迁移指南.pdf',
        bbox_object_name='',
        status=KnowledgeFileStatus.WAITING.value,
    )


def test_copy_normal_skips_empty_bbox_object_name(monkeypatch):
    object_exists_calls = []

    class FakeMinio:
        bucket = 'bucket'

        def object_exists_sync(self, *args, **kwargs):
            object_name = kwargs.get('object_name')
            if object_name is None and len(args) >= 2:
                object_name = args[1]
            assert object_name, 'empty object_name should not be checked'
            object_exists_calls.append(object_name)
            return False

        def copy_object_sync(self, **_kwargs):
            raise AssertionError('copy should not run when source objects are absent')

    def _add_file(record):
        record.id = 9301
        return record

    updated = []
    monkeypatch.setattr(file_worker, 'get_minio_storage_sync', lambda: FakeMinio())
    monkeypatch.setattr(
        file_worker.KnowledgeUtils,
        'get_knowledge_file_object_name',
        staticmethod(lambda file_id, file_name: f'target/{file_id}/{file_name}'),
    )
    monkeypatch.setattr(file_worker.KnowledgeFileDao, 'add_file', staticmethod(_add_file))
    monkeypatch.setattr(file_worker.KnowledgeFileDao, 'update', staticmethod(lambda record: updated.append(record)))

    result = file_worker.copy_normal(
        _make_file(),
        _make_space(12),
        _make_space(7),
        7,
    )

    assert result.id == 9301
    assert object_exists_calls == ['source/迁移指南.pdf', '1580']
    assert updated[-1].status == KnowledgeFileStatus.WAITING.value


def test_copy_normal_enqueues_success_file_stat_sync(monkeypatch):
    class FakeMinio:
        bucket = 'bucket'

        def object_exists_sync(self, *args, **kwargs):
            object_name = kwargs.get('object_name')
            if object_name is None and len(args) >= 2:
                object_name = args[1]
            return object_name == 'source/迁移指南.pdf'

        def copy_object_sync(self, **_kwargs):
            return None

    source_file = _make_file()
    source_file.status = KnowledgeFileStatus.SUCCESS.value
    enqueued = []

    def _add_file(record):
        record.id = 9302
        return record

    monkeypatch.setattr(file_worker, 'get_minio_storage_sync', lambda: FakeMinio())
    monkeypatch.setattr(file_worker.KnowledgeFileDao, 'add_file', staticmethod(_add_file))
    monkeypatch.setattr(file_worker.KnowledgeFileDao, 'update', staticmethod(lambda record: None))
    monkeypatch.setattr(file_worker, 'copy_vector', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        file_worker.KnowledgeSpaceContentStat,
        'enqueue_file_stat_sync',
        staticmethod(lambda file_ids: enqueued.extend(file_ids)),
    )

    result = file_worker.copy_normal(
        source_file,
        _make_space(12),
        _make_space(7),
        7,
    )

    assert result.status == KnowledgeFileStatus.SUCCESS.value
    assert enqueued == [9302]
