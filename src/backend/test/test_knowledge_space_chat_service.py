import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile


def _install_chat_service_stubs() -> None:
    if 'bisheng.api' not in sys.modules:
        api_module = ModuleType('bisheng.api')
        api_module.__path__ = []
        sys.modules['bisheng.api'] = api_module
    if 'bisheng.api.services' not in sys.modules:
        services_module = ModuleType('bisheng.api.services')
        services_module.__path__ = []
        sys.modules['bisheng.api.services'] = services_module
    if 'bisheng.api.services.workstation' not in sys.modules:
        workstation_module = ModuleType('bisheng.api.services.workstation')

        class _DummyWorkStationService:
            @staticmethod
            async def get_knowledge_space_config():
                return SimpleNamespace(system_prompt="", user_prompt="", max_chunk_size=4)

        workstation_module.WorkStationService = _DummyWorkStationService
        sys.modules['bisheng.api.services.workstation'] = workstation_module

    if 'bisheng.api.v1' not in sys.modules:
        v1_module = ModuleType('bisheng.api.v1')
        v1_module.__path__ = []
        sys.modules['bisheng.api.v1'] = v1_module
    if 'bisheng.api.v1.schema' not in sys.modules:
        schema_module = ModuleType('bisheng.api.v1.schema')
        schema_module.__path__ = []
        sys.modules['bisheng.api.v1.schema'] = schema_module
    if 'bisheng.api.v1.schema.chat_schema' not in sys.modules:
        chat_schema_module = ModuleType('bisheng.api.v1.schema.chat_schema')
        chat_schema_module.ChatMessageHistoryResponse = dict
        sys.modules['bisheng.api.v1.schema.chat_schema'] = chat_schema_module

    if 'bisheng.api.v1.schemas' in sys.modules:
        schemas_module = sys.modules['bisheng.api.v1.schemas']
    else:
        schemas_module = ModuleType('bisheng.api.v1.schemas')
        sys.modules['bisheng.api.v1.schemas'] = schemas_module

    class _DummySchema:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def model_dump(self):
            return self.kwargs

    class _DummyChatResponse(dict):
        pass

    class _DummyKnowledgeSpaceConfig(SimpleNamespace):
        system_prompt: str = ""
        user_prompt: str = ""
        max_chunk_size: int = 4

    schemas_module.ChatResponse = _DummyChatResponse
    schemas_module.KnowledgeSpaceConfig = _DummyKnowledgeSpaceConfig
    schemas_module.KnowledgeFileOne = getattr(schemas_module, 'KnowledgeFileOne', _DummySchema)
    schemas_module.FileProcessBase = getattr(schemas_module, 'FileProcessBase', _DummySchema)
    schemas_module.ExcelRule = getattr(schemas_module, 'ExcelRule', _DummySchema)

    if 'bisheng.chat_session.domain.chat' not in sys.modules:
        chat_module = ModuleType('bisheng.chat_session.domain.chat')

        class _DummyChatSessionService:
            @staticmethod
            async def get_chat_history(*args, **kwargs):
                return []

        chat_module.ChatSessionService = _DummyChatSessionService
        sys.modules['bisheng.chat_session.domain.chat'] = chat_module

    if 'bisheng.common.utils.title_generator' not in sys.modules:
        title_module = ModuleType('bisheng.common.utils.title_generator')

        async def _dummy_generate_conversation_title_async(*args, **kwargs):
            return "title"

        title_module.generate_conversation_title_async = _dummy_generate_conversation_title_async
        sys.modules['bisheng.common.utils.title_generator'] = title_module

    if 'bisheng.core.prompts.manager' not in sys.modules:
        prompt_module = ModuleType('bisheng.core.prompts.manager')

        async def _dummy_get_prompt_manager():
            prompt_obj = SimpleNamespace(prompt=SimpleNamespace(system="", user=""))
            return SimpleNamespace(render_prompt=lambda **kwargs: prompt_obj)

        prompt_module.get_prompt_manager = _dummy_get_prompt_manager
        sys.modules['bisheng.core.prompts.manager'] = prompt_module

    if 'bisheng.tool.domain.langchain.knowledge' not in sys.modules:
        tool_module = ModuleType('bisheng.tool.domain.langchain.knowledge')

        class _DummyKnowledgeRetrieverTool:
            def __init__(self, *args, **kwargs):
                pass

            async def ainvoke(self, *args, **kwargs):
                return []

        tool_module.KnowledgeRetrieverTool = _DummyKnowledgeRetrieverTool
        sys.modules['bisheng.tool.domain.langchain.knowledge'] = tool_module


def _load_chat_service_class():
    _install_chat_service_stubs()
    module = importlib.import_module('bisheng.knowledge.domain.services.knowledge_space_chat_service')
    return module.KnowledgeSpaceChatService


def _make_login_user(user_id: int = 7, user_name: str = 'tester') -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        is_admin=lambda: False,
    )


def _make_space(
        *,
        space_id: int = 1,
        user_id: int = 1,
        auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
        state: int = KnowledgeState.PUBLISHED.value,
) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=user_id,
        name='Knowledge Space',
        type=KnowledgeTypeEnum.SPACE.value,
        description='desc',
        model='model-1',
        state=state,
        is_released=False,
        auth_type=auth_type,
    )


def _make_file(
        *,
        file_id: int = 11,
        knowledge_id: int = 1,
        file_type: int = FileType.FILE.value,
        file_name: str = 'doc.txt',
        file_level_path: str = '',
        level: int = 0,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=knowledge_id,
        file_name=file_name,
        file_type=file_type,
        file_level_path=file_level_path,
        level=level,
        object_name='minio/object',
    )


@pytest.fixture
def chat_service():
    return _load_chat_service_class()(MagicMock(), _make_login_user())


class TestKnowledgeSpaceChatPermissions:

    @pytest.mark.asyncio
    async def test_chat_single_file_requires_view_file(self, chat_service):
        file_record = _make_file(file_id=11, knowledge_id=1)
        space = _make_space(space_id=1)

        async def _empty_space_rag(*args, **kwargs):
            if False:
                yield None

        with patch.object(
            chat_service, '_require_file_view_permission', new_callable=AsyncMock,
            return_value=file_record,
        ) as mock_require_view, patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.afilter_session',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(chat_id='chat-1', flow_id='flow-1')],
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(as_retriever=lambda **kwargs: object()),
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(as_retriever=lambda **kwargs: object()),
        ), patch.object(
            chat_service, 'space_rag', _empty_space_rag,
        ):
            result = [item async for item in chat_service.chat_single_file(1, 11, 'hi')]

        assert result == []
        mock_require_view.assert_awaited_once_with(1, 11)

    @pytest.mark.asyncio
    async def test_get_chat_folder_session_requires_view_folder_when_folder_selected(self, chat_service):
        with patch.object(
            chat_service, '_require_folder_view_permission', new_callable=AsyncMock,
        ) as mock_require_folder, patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.afilter_session',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await chat_service.get_chat_folder_session(1, 22)

        assert result == []
        mock_require_folder.assert_awaited_once_with(1, 22)

    @pytest.mark.asyncio
    async def test_get_chat_folder_session_requires_view_space_at_root(self, chat_service):
        with patch.object(
            chat_service, '_require_space_view_permission', new_callable=AsyncMock,
        ) as mock_require_space, patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.afilter_session',
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await chat_service.get_chat_folder_session(1, 0)

        assert result == []
        mock_require_space.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_create_chat_folder_session_requires_view_folder(self, chat_service):
        space = _make_space(space_id=1)
        folder = _make_file(file_id=22, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        session = SimpleNamespace(chat_id='chat-1')

        with patch.object(
            chat_service, '_require_space_view_permission', new_callable=AsyncMock,
        ) as mock_require_space, patch.object(
            chat_service, '_require_folder_view_permission', new_callable=AsyncMock,
            return_value=folder,
        ) as mock_require_folder, patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.async_insert_one',
            new_callable=AsyncMock,
            return_value=session,
        ):
            result = await chat_service.create_chat_folder_session(1, 22)

        assert result == session
        mock_require_space.assert_awaited_once_with(1)
        mock_require_folder.assert_awaited_once_with(1, 22)

    @pytest.mark.asyncio
    async def test_chat_folder_requires_view_folder(self, chat_service):
        space = _make_space(space_id=1)
        folder = _make_file(file_id=22, knowledge_id=1, file_type=FileType.DIR.value, file_name='folder')
        session = [SimpleNamespace(chat_id='chat-1')]

        async def _empty_space_rag(*args, **kwargs):
            if False:
                yield None

        with patch.object(
            chat_service, '_require_space_view_permission', new_callable=AsyncMock,
        ) as mock_require_space, patch.object(
            chat_service, '_require_folder_view_permission', new_callable=AsyncMock,
            return_value=folder,
        ) as mock_require_folder, patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.afilter_session',
            new_callable=AsyncMock,
            return_value=session,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=space,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.SpaceFileDao.get_children_by_prefix',
            new_callable=AsyncMock,
            return_value=[],
        ), patch.object(
            chat_service, 'space_rag', _empty_space_rag,
        ):
            result = [item async for item in chat_service.chat_folder(1, 22, 'chat-1', 'hello')]

        assert result == []
        mock_require_space.assert_awaited_once_with(1)
        mock_require_folder.assert_awaited_once_with(1, 22)

    @pytest.mark.asyncio
    async def test_create_chat_folder_session_rejects_missing_space(self, chat_service):
        class _MissingSpaceError(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__(kwargs.get('msg') or (args[0] if args else 'missing space'))

        with patch.object(
            chat_service, '_require_space_view_permission', new_callable=AsyncMock,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'bisheng.knowledge.domain.services.knowledge_space_chat_service.NotFoundError',
            _MissingSpaceError,
        ):
            with pytest.raises(_MissingSpaceError):
                await chat_service.create_chat_folder_session(1, 0)
