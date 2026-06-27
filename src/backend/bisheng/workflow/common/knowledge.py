from datetime import datetime
from typing import Any, Literal

from langchain_core.documents import Document
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, MetadataFieldType
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.rag.version_filter import build_primary_only_filter
from bisheng.llm.domain import LLMService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.user.domain.services.auth import LoginUser
from bisheng.workflow.common.condition import ComparisonType
from bisheng.workflow.common.runtime_knowledge import (
    MAX_RUNTIME_KNOWLEDGE_FILES,
    RUNTIME_STATE_NODE_ID,
    RUNTIME_USER_SELECTED_KNOWLEDGE_KEY,
    RuntimeKnowledgeSelection,
    parse_runtime_knowledge_selection,
)
from bisheng.workflow.nodes.base import BaseNode


def ensure_knowledge_space_login_user(login_user: Any) -> LoginUser:
    """Return a permission-service compatible user for workflow space retrieval."""
    if hasattr(login_user, "get_user_group_ids"):
        return login_user
    if not login_user or not getattr(login_user, "user_id", None):
        raise ValueError("knowledge space retrieval requires a login user")

    return LoginUser(
        user_id=int(login_user.user_id),
        user_name=getattr(login_user, "user_name", "") or "",
        user_role=getattr(login_user, "user_role", None) or [],
        tenant_id=getattr(login_user, "tenant_id", 1) or 1,
        token_version=getattr(login_user, "token_version", 0) or 0,
        is_global_super=getattr(login_user, "is_global_super", False),
    )


def retrieve_knowledge_space_documents_sync(
    *,
    request: Any,
    login_user: Any,
    query: str,
    knowledge_base_ids: list[int],
    kb_filters: dict[int, dict[str, Any]] | None = None,
    top_k: int = 100,
    max_content: int = 15000,
) -> list[tuple[int, Document]]:
    """Synchronously retrieve authorized knowledge-space chunks for workflow nodes."""
    if not knowledge_base_ids:
        return []

    import asyncio

    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.worker._asyncio_utils import run_async_task

    async def _retrieve() -> list[tuple[int, Document]]:
        async with get_async_db_session() as session:
            service = KnowledgeSpaceChatService(request, ensure_knowledge_space_login_user(login_user))
            service.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
            return await service.aretrieve_chunks(
                query=query,
                knowledge_base_ids=knowledge_base_ids,
                kb_filters=kb_filters,
                top_k=top_k,
                max_content=max_content,
            )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_async_task(_retrieve)
    raise RuntimeError("knowledge space retrieval does not support running inside an active event loop")


class ConditionOne(BaseModel):
    id: str = Field(..., description="Unique id for condition")
    knowledge_id: int = Field(..., description="metadata filed belong for knowledge`s id")
    metadata_field: str = Field(..., description="knowledge metadata field")
    comparison_operation: str = Field(..., description="Compare type")
    right_value_type: str = Field(..., description="Right value type")
    right_value: str = Field(..., description="Right value")

    def convert_right_value(self, field_type: str, right_value: Any, is_preset: bool) -> Any:
        # no need to convert right value for is_empty and is_not_empty
        if self.comparison_operation in ["is_empty", "is_not_empty"] or is_preset:
            return right_value

        # only for user metadata field, need to convert right value type
        if field_type in [MetadataFieldType.STRING.value]:
            right_value = str(right_value)
            if not right_value:
                raise ValueError("Right value cannot be empty for the selected comparison operation")
        elif field_type in [MetadataFieldType.NUMBER.value]:
            right_value = int(right_value)
        elif field_type == MetadataFieldType.TIME.value:
            if isinstance(right_value, int):
                # timestamp
                right_value = datetime.fromtimestamp(right_value)
            else:
                # iso format
                right_value = datetime.fromisoformat(right_value)
            right_value = int(right_value.timestamp())
        else:
            raise ValueError(f"Unsupported metadata field type: {field_type}")
        return right_value

    def convert_preset_filed(self) -> (str, str):
        """convert preset field to mysql field in knowledge file table"""
        if self.metadata_field == "document_id":
            return "id"
        elif self.metadata_field == "document_name":
            return "file_name"
        elif self.metadata_field == "upload_time":
            return "create_time"
        elif self.metadata_field == "update_time":
            return "update_time"
        elif self.metadata_field == "uploader":
            return "user_name"
        elif self.metadata_field == "updater":
            return "updater_name"
        else:
            raise ValueError(f"Unsupported preset metadata field: {self.metadata_field}")

    def get_knowledge_file_filter(self, field_info: dict, parent_node: BaseNode, is_preset: bool) -> (str, list[dict]):
        """get knowledge file filter field info for mysql"""
        right_value = self.right_value
        if self.right_value_type == "ref" and self.right_value:
            right_value = parent_node.get_other_node_variable(self.right_value)
        field_type = field_info.get("field_type")
        right_value = self.convert_right_value(field_type, right_value, is_preset)
        if is_preset:
            field_key = self.convert_preset_filed()
            py_field: str | tuple = field_key
        else:
            # MySQL raw SQL path expression
            field_key = f"JSON_UNQUOTE(JSON_EXTRACT(`user_metadata`, '$.{self.metadata_field}.field_value'))"
            # Python-side accessor for DaMeng (used by _filter_python in KnowledgeFileDao)
            py_field = ("user_metadata", self.metadata_field)

        key_info: dict = {"py_field": py_field}
        if self.comparison_operation == ComparisonType.EQUAL:
            key_info["comparison"] = "="
            key_info["value"] = right_value
        elif self.comparison_operation == ComparisonType.NOT_EQUAL:
            key_info["comparison"] = "!="
            key_info["value"] = right_value
        elif self.comparison_operation == ComparisonType.CONTAINS:
            key_info["comparison"] = "like"
            key_info["value"] = f"%{right_value}%"
        elif self.comparison_operation == ComparisonType.NOT_CONTAINS:
            key_info["comparison"] = "not like"
            key_info["value"] = f"%{right_value}%"
        elif self.comparison_operation == ComparisonType.STARTS_WITH:
            key_info["comparison"] = "like"
            key_info["value"] = f"{right_value}%"
        elif self.comparison_operation == ComparisonType.ENDS_WITH:
            key_info["comparison"] = "like"
            key_info["value"] = f"%{right_value}"
        elif self.comparison_operation == ComparisonType.IS_EMPTY:
            key_info["comparison"] = "="
            key_info["value"] = "null"
        elif self.comparison_operation == ComparisonType.IS_NOT_EMPTY:
            key_info["comparison"] = "!="
            key_info["value"] = "null"
        elif self.comparison_operation == ComparisonType.GREATER_THAN:
            key_info["comparison"] = ">"
            key_info["value"] = right_value
        elif self.comparison_operation == ComparisonType.GREATER_THAN_OR_EQUAL:
            key_info["comparison"] = ">="
            key_info["value"] = right_value
        elif self.comparison_operation == ComparisonType.LESS_THAN:
            key_info["comparison"] = "<"
            key_info["value"] = right_value
        elif self.comparison_operation == ComparisonType.LESS_THAN_OR_EQUAL:
            key_info["comparison"] = "<="
            key_info["value"] = right_value
        else:
            raise ValueError(f"Unsupported comparison operation: {self.comparison_operation}")
        if not is_preset and self.comparison_operation in [
            ComparisonType.GREATER_THAN,
            ComparisonType.GREATER_THAN_OR_EQUAL,
            ComparisonType.LESS_THAN,
            ComparisonType.LESS_THAN_OR_EQUAL,
        ]:
            key_info["extra_filter"] = [{"comparison": "!=", "value": "null"}]
        return {field_key: key_info}


class ConditionCases(BaseModel):
    id: str = Field(default=None, description="Unique id for condition case")
    conditions: list[ConditionOne] = Field(default_factory=list, description="List of conditions")
    operator: Literal["and", "or"] = Field(default="and", description="Logical operator to combine conditions")
    enabled: bool = Field(default=False, description="Whether the condition case is enabled")

    def get_knowledge_filter(self, knowledge: Knowledge, parent_node: BaseNode) -> (str, dict):
        """if return is None, filter file is empty, don't need to retrieve from this knowledge"""
        if not self.enabled or not self.conditions:
            return "", {}

        metadata_field_info = {}
        if knowledge.metadata_fields:
            metadata_field_info = {one["field_name"]: one for one in knowledge.metadata_fields}

        # Built-in metadata fields
        preset_field_info = {
            one.field_name: one.model_dump()
            for one in KNOWLEDGE_RAG_METADATA_SCHEMA
            if one.field_name != "user_metadata"
        }
        all_filter_field = []
        for condition in self.conditions:
            if int(condition.knowledge_id) != knowledge.id:
                continue
            if field_info := preset_field_info.get(condition.metadata_field):
                filter_field_info = condition.get_knowledge_file_filter(field_info, parent_node, True)
            elif field_info := metadata_field_info.get(condition.metadata_field):
                filter_field_info = condition.get_knowledge_file_filter(field_info, parent_node, False)
            else:
                logger.warning(f"condition field {condition.metadata_field} not in knowledge metadata fields")
                raise ValueError(f"field {condition.metadata_field} not in knowledge metadata fields")
            all_filter_field.append(filter_field_info)
        if not all_filter_field:
            return "", {}

        file_ids = KnowledgeFileDao.filter_file_by_metadata_fields(knowledge.id, self.operator, all_filter_field)
        if not file_ids:
            # no file match the filter condition
            logger.debug(f"knowledge {knowledge.id} no file match the filter condition")
            return None, None
        milvus_filter = f"document_id in {file_ids}"
        es_filter = {"filter": [{"terms": {"metadata.document_id": file_ids}}]}
        return milvus_filter, es_filter


class RagUtils(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._knowledge_type = self.node_params.get("knowledge", {}).get("type", "knowledge")
        self._knowledge_value = [one["key"] for one in self.node_params.get("knowledge", {}).get("value", [])]

        self._advance_kwargs = self.node_params.get("advanced_retrieval_switch", {})
        metadata_filter = {} if self._knowledge_type == "space" else self.node_params.get("metadata_filter", {})
        self._metadata_filter = ConditionCases(**metadata_filter)
        if self._advance_kwargs:
            self._advance_kwargs = self.node_params.get("advanced_retrieval_switch", {})
            self._knowledge_auth = self._advance_kwargs["user_auth"]
            self._max_chunk_size = int(self._advance_kwargs["max_chunk_size"])
            self._keyword_weight = float(self._advance_kwargs["keyword_weight"])
            self._vector_weight = float(self._advance_kwargs["vector_weight"])
            self._rerank_flag = self._advance_kwargs["rerank_flag"]
            self._rerank_model_id = self._advance_kwargs["rerank_model"]
        else:
            self._knowledge_auth = self.node_params.get("user_auth", False)
            self._max_chunk_size = int(self.node_params.get("max_chunk_size", 15000))
            self._keyword_weight = 0.5
            self._vector_weight = 0.5
            self._rerank_flag = False
            self._rerank_model_id = ""

        self._multi_milvus_retriever = None
        self._multi_es_retriever = None
        self._knowledge_vector_list = []
        self._retriever_kwargs = {"k": 100, "param": {"ef": 110}}
        self._rerank_model = None
        self._knowledge_retriever_tool = None
        self._runtime_selection_required = False
        self._runtime_selected_file_ids_by_knowledge: dict[int, list[int]] | None = None
        self._runtime_selected_file_ids_by_space: dict[int, list[int]] | None = None

    def _run(self, unique_id: str) -> dict[str, Any]:
        raise NotImplementedError()

    @staticmethod
    def format_timestamp(timestamp: int) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return str(timestamp)

    def retrieve_question(self, question: str) -> list[Document]:
        if self._knowledge_type == "space":
            return self.retrieve_space_question(question)
        if self._knowledge_type == "runtime_items":
            return self.retrieve_runtime_items_question(question)

        return self.retrieve_knowledge_question(question)

    def retrieve_knowledge_question(self, question: str) -> list[Document]:
        # 1: retrieve documents from multi retrievers
        knowledge_retriever_tool = KnowledgeRetrieverTool(
            vector_retriever=self._multi_milvus_retriever,
            elastic_retriever=self._multi_es_retriever,
            max_content=self._max_chunk_size,
            rrf_weights=[self._vector_weight, self._keyword_weight],
            rrf_remove_zero_score=True,
            rerank=self._rerank_model,
            sort_by_source_and_index=True,
        )
        finally_docs = knowledge_retriever_tool.invoke(input={"query": question})
        all_file_id = {one.metadata.get("document_id") for one in finally_docs}
        file_map = {}
        if finally_docs:
            if self._knowledge_type == "knowledge":
                file_info = KnowledgeFileDao.get_file_by_ids(list(all_file_id))
                file_map = {one.id: one for one in file_info}
            for one in finally_docs:
                if "upload_time" in one.metadata:
                    one.metadata["upload_time"] = self.format_timestamp(one.metadata["upload_time"])
                if "update_time" in one.metadata:
                    one.metadata["update_time"] = self.format_timestamp(one.metadata["update_time"])
                file_id = one.metadata.get("document_id") or one.metadata.get("file_id")
                if file_id and file_map.get(file_id):
                    for user_key, user_value in one.metadata.get("user_metadata", {}).items():
                        field_info = file_map[file_id].user_metadata.get(user_key)
                        if field_info and field_info.get("field_type") == MetadataFieldType.TIME.value:
                            one.metadata["user_metadata"][user_key] = self.format_timestamp(user_value)
        return finally_docs

    def retrieve_space_question(
        self,
        question: str,
        knowledge_base_ids: list[int] | None = None,
        file_ids_by_space: dict[int, list[int]] | None = None,
    ) -> list[Document]:
        kb_filters = None
        file_filters = file_ids_by_space
        if file_filters is None:
            file_filters = getattr(self, "_runtime_selected_file_ids_by_space", None)
        if file_filters:
            kb_filters = {
                int(knowledge_id): {"file_ids": file_ids}
                for knowledge_id, file_ids in file_filters.items()
            }
        knowledge_base_ids = knowledge_base_ids or [int(one) for one in self._knowledge_value]
        chunks = retrieve_knowledge_space_documents_sync(
            request=getattr(self, "request", None),
            login_user=self.user_info,
            query=question,
            knowledge_base_ids=knowledge_base_ids,
            kb_filters=kb_filters,
            top_k=self._retriever_kwargs["k"],
            max_content=self._max_chunk_size,
        )
        docs = []
        for knowledge_id, doc in chunks:
            doc.metadata["knowledge_space_id"] = knowledge_id
            docs.append(doc)
        return docs

    def retrieve_runtime_items_question(self, question: str) -> list[Document]:
        docs: list[Document] = []
        if self._multi_milvus_retriever or self._multi_es_retriever:
            docs.extend(self.retrieve_knowledge_question(question))
        if self._runtime_selected_file_ids_by_space:
            docs.extend(
                self.retrieve_space_question(
                    question,
                    knowledge_base_ids=sorted(self._runtime_selected_file_ids_by_space.keys()),
                    file_ids_by_space=self._runtime_selected_file_ids_by_space,
                )
            )
        return docs

    def init_user_question(self) -> list[str]:
        # Convert all user questions to strings by default
        ret = []
        for one in self.node_params["user_question"]:
            ret.append(f"{self.get_other_node_variable(one)}")
        return ret

    def init_rerank_model(self):
        if not self._rerank_flag or not self._rerank_model_id:
            return
        if self._rerank_model:
            return
        self._rerank_model = LLMService.get_bisheng_rerank_sync(
            model_id=self._rerank_model_id,
            app_id=self.workflow_id,
            app_name=self.workflow_name,
            app_type=ApplicationTypeEnum.WORKFLOW,
            user_id=self.user_id,
        )

    def init_multi_retriever(self):
        if self._knowledge_type == "knowledge":
            self.init_knowledge_retriever()
        elif self._knowledge_type == "space":
            self.init_space_retriever()
        elif self._knowledge_type == "runtime_items":
            self.init_runtime_items_retriever()
        elif self._knowledge_type == "tmp":
            self.init_file_retriever()
        else:
            raise ValueError(f"Unsupported knowledge retrieval type: {self._knowledge_type}")

    def init_runtime_items_retriever(self):
        self._multi_es_retriever = None
        self._multi_milvus_retriever = None
        if not self._runtime_selected_file_ids_by_knowledge:
            return
        self._knowledge_value = sorted(self._runtime_selected_file_ids_by_knowledge.keys())
        self._knowledge_auth = True
        self.init_knowledge_retriever()

    def init_space_retriever(self):
        """Knowledge-space retrieval is executed per question with permission checks."""
        if not self._knowledge_value:
            raise ValueError("Knowledge space retrieval requires at least one selected space")
        self._multi_es_retriever = None
        self._multi_milvus_retriever = None

    def apply_runtime_knowledge_selection(self):
        raw_selection = self.graph_state.get_variable(
            RUNTIME_STATE_NODE_ID,
            RUNTIME_USER_SELECTED_KNOWLEDGE_KEY,
        )
        selection = parse_runtime_knowledge_selection(raw_selection)
        self._runtime_selection_required = True
        self._metadata_filter = ConditionCases(enabled=False)
        self._runtime_selected_file_ids_by_knowledge = None
        self._runtime_selected_file_ids_by_space = None

        if selection.mode == "source":
            source = selection.whole_source
            if source is None:
                raise ValueError("请选择知识空间。")
            self._knowledge_type = "space"
            self._knowledge_value = [source.source_id]
        elif selection.mode == "items":
            self._knowledge_type = "runtime_items"
            self._knowledge_value = []
            (
                self._runtime_selected_file_ids_by_knowledge,
                self._runtime_selected_file_ids_by_space,
            ) = self._resolve_runtime_item_scope(selection)
            self._knowledge_value = sorted(
                set(self._runtime_selected_file_ids_by_space or {})
            )
        else:
            raise ValueError(f"Unsupported runtime knowledge selection mode: {selection.mode}")

        if self._knowledge_type == "space":
            self._runtime_selected_file_ids_by_space = self._resolve_runtime_space_scope(selection)
        elif self._knowledge_type == "runtime_items":
            if not self._runtime_selected_file_ids_by_space:
                raise ValueError("请选择可用于问答的文件。")
        else:
            raise ValueError(f"Unsupported runtime knowledge type: {self._knowledge_type}")

    def _resolve_runtime_knowledge_scope(
        self,
        selection: RuntimeKnowledgeSelection,
    ) -> dict[int, list[int]] | None:
        if selection.mode == "source":
            return None
        knowledge_groups = selection.item_groups("knowledge")
        if not knowledge_groups:
            return None
        return self._resolve_knowledge_item_groups(knowledge_groups)

    def _resolve_knowledge_item_groups(self, knowledge_groups: dict[int, list[Any]]) -> dict[int, list[int]] | None:
        file_ids_by_knowledge: dict[int, list[int]] = {}
        file_ids = list(
            dict.fromkeys(
                item.id
                for items in knowledge_groups.values()
                for item in items
                if item.ref_type == "file"
            )
        )
        folder_ids = list(
            dict.fromkeys(
                item.id
                for items in knowledge_groups.values()
                for item in items
                if item.ref_type == "folder"
            )
        )

        selected_records = KnowledgeFileDao.get_file_by_ids(file_ids + folder_ids)
        record_map = {int(item.id): item for item in selected_records}
        missing_ids = [item_id for item_id in file_ids + folder_ids if item_id not in record_map]
        if missing_ids:
            raise ValueError(f"所选知识库文件或文件夹不存在或无权限访问: {missing_ids}")

        for knowledge_id, items in knowledge_groups.items():
            for item in items:
                record = record_map.get(int(item.id))
                if not record or int(record.knowledge_id) != int(knowledge_id):
                    raise ValueError(f"所选文件或文件夹不属于当前知识库: {item.id}")
                if item.ref_type == "file":
                    if int(record.file_type) != FileType.FILE.value or int(record.status) != KnowledgeFileStatus.SUCCESS.value:
                        raise ValueError(f"所选文件不属于当前知识库或不可检索: {[item.id]}")
                    file_ids_by_knowledge.setdefault(int(knowledge_id), []).append(int(item.id))
                else:
                    if int(record.file_type) != FileType.DIR.value:
                        raise ValueError(f"所选知识库文件夹无效: {[item.id]}")
                    for file_id in self._resolve_folder_success_file_ids(record):
                        file_ids_by_knowledge.setdefault(int(knowledge_id), []).append(file_id)

        for knowledge_id, ids in list(file_ids_by_knowledge.items()):
            file_ids_by_knowledge[knowledge_id] = list(dict.fromkeys(ids))

        total_files = sum(len(ids) for ids in file_ids_by_knowledge.values())
        if total_files > MAX_RUNTIME_KNOWLEDGE_FILES:
            raise ValueError(f"一次最多可选择{MAX_RUNTIME_KNOWLEDGE_FILES}个文件。")
        return file_ids_by_knowledge or None

    def _resolve_folder_success_file_ids(self, folder: Any) -> list[int]:
        import asyncio

        from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
        from bisheng.worker._asyncio_utils import run_async_task

        prefix = f"{getattr(folder, 'file_level_path', '') or ''}/{folder.id}"

        async def _resolve() -> list[int]:
            children = await SpaceFileDao.get_children_by_prefix(
                int(folder.knowledge_id),
                prefix,
                file_status=KnowledgeFileStatus.SUCCESS,
            )
            return [
                int(item.id)
                for item in children or []
                if int(item.file_type) == FileType.FILE.value
                and int(item.status) == KnowledgeFileStatus.SUCCESS.value
            ]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_async_task(_resolve)
        raise RuntimeError("runtime knowledge folder resolving does not support an active event loop")

    def _resolve_runtime_item_scope(
        self,
        selection: RuntimeKnowledgeSelection,
    ) -> tuple[dict[int, list[int]] | None, dict[int, list[int]] | None]:
        knowledge_groups = selection.item_groups("knowledge")
        if knowledge_groups:
            raise ValueError("自选知识节点仅支持知识空间。")
        space_groups = selection.item_groups("space")
        space_file_ids = self._resolve_runtime_space_scope(selection) if space_groups else None
        total_files = sum(len(ids) for ids in (space_file_ids or {}).values())
        if total_files > MAX_RUNTIME_KNOWLEDGE_FILES:
            raise ValueError(f"一次最多可选择{MAX_RUNTIME_KNOWLEDGE_FILES}个文件。")
        return None, space_file_ids

    def _resolve_legacy_runtime_knowledge_scope(
        self,
        selection: RuntimeKnowledgeSelection,
    ) -> dict[int, list[int]] | None:
        if selection.mode == "source":
            return None
        file_ids = list(dict.fromkeys(selection.file_ids()))
        if not file_ids:
            return None
        if len(file_ids) > MAX_RUNTIME_KNOWLEDGE_FILES:
            raise ValueError(f"一次最多可选择{MAX_RUNTIME_KNOWLEDGE_FILES}个文件。")
        files = KnowledgeFileDao.get_file_by_ids(file_ids)
        file_map = {int(item.id): item for item in files}
        missing_file_ids = [file_id for file_id in file_ids if file_id not in file_map]
        if missing_file_ids:
            raise ValueError(f"所选知识库文件不存在或无权限访问: {missing_file_ids}")
        source_ids = selection.source_ids("knowledge")
        expected_source_id = source_ids[0] if source_ids else 0
        invalid_file_ids = [
            file_id
            for file_id, item in file_map.items()
            if int(item.knowledge_id) != int(expected_source_id)
            or int(item.file_type) != FileType.FILE.value
            or int(item.status) != KnowledgeFileStatus.SUCCESS.value
        ]
        if invalid_file_ids:
            raise ValueError(f"所选文件不属于当前知识库或不可检索: {invalid_file_ids}")
        return {int(expected_source_id): file_ids}

    def _resolve_runtime_space_scope(
        self,
        selection: RuntimeKnowledgeSelection,
    ) -> dict[int, list[int]] | None:
        if selection.mode == "source" or not selection.has_file_or_folder_scope():
            return None

        import asyncio

        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
        from bisheng.worker._asyncio_utils import run_async_task

        file_refs = [
            {"knowledge_space_id": item.source_id, "file_id": item.id}
            for item in selection.items
            if item.source_type == "space" and item.ref_type == "file"
        ]
        folder_refs = [
            {"knowledge_space_id": item.source_id, "folder_id": item.id}
            for item in selection.items
            if item.source_type == "space" and item.ref_type == "folder"
        ]
        if not file_refs and not folder_refs:
            return None

        async def _resolve() -> dict[int, list[int]]:
            service = KnowledgeSpaceService(
                getattr(self, "request", None),
                ensure_knowledge_space_login_user(self.user_info),
            )
            return await service.resolve_qa_scope_file_ids(
                folder_refs=folder_refs,
                file_refs=file_refs,
                max_files=MAX_RUNTIME_KNOWLEDGE_FILES,
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run_async_task(_resolve)
        raise RuntimeError("runtime knowledge space scope resolving does not support an active event loop")

    def _apply_runtime_file_filter(
        self,
        knowledge_id: int,
        milvus_filter_str: str | None,
        es_filter_list: list[dict] | None,
    ) -> tuple[str | None, list[dict] | None]:
        if not self._runtime_selected_file_ids_by_knowledge:
            return milvus_filter_str, es_filter_list
        file_ids = self._runtime_selected_file_ids_by_knowledge.get(int(knowledge_id))
        if file_ids is None:
            return milvus_filter_str, es_filter_list
        if not file_ids:
            return None, None

        file_filter_expr = f"document_id in {file_ids}"
        if milvus_filter_str:
            milvus_filter_str = f"({milvus_filter_str}) and ({file_filter_expr})"
        else:
            milvus_filter_str = file_filter_expr

        es_filter_list = list(es_filter_list or [])
        es_filter_list.append({"terms": {"metadata.document_id": file_ids}})
        return milvus_filter_str, es_filter_list

    def _fetch_non_primary_file_ids(self, knowledge_ids: list[int]) -> list[int]:
        """Best-effort sync fetch of non-primary file ids for the given knowledges."""
        if not knowledge_ids:
            return []
        import asyncio

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
            KnowledgeDocumentVersionRepositoryImpl,
        )
        from bisheng.worker._asyncio_utils import run_async_task

        async def _fetch():
            async with get_async_db_session() as session:
                repo = KnowledgeDocumentVersionRepositoryImpl(session)
                return await repo.find_non_primary_file_ids_by_knowledge_ids(knowledge_ids)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            logger.warning("version filter skipped: already in async context", exc_info=True)
            return []

        try:
            return run_async_task(_fetch)
        except RuntimeError:
            logger.warning("version filter skipped: already in async context", exc_info=True)
            return []
        except Exception:
            logger.warning("version filter fetch failed", exc_info=True)
            return []

    def init_knowledge_retriever(self):
        """retriever from knowledge base"""
        if not self._knowledge_vector_list:
            self._knowledge_vector_list = KnowledgeRag.get_multi_knowledge_vectorstore_sync(
                invoke_user_id=self.user_id,
                knowledge_ids=self._knowledge_value,
                user_name=self.user_info.user_name,
                check_auth=self._knowledge_auth or self._runtime_selection_required,
                include_es=self._keyword_weight > 0,
                include_milvus=self._vector_weight > 0,
            )
            if self._runtime_selection_required:
                requested_knowledge_ids = {int(one) for one in self._knowledge_value}
                authorized_knowledge_ids = {int(one) for one in self._knowledge_vector_list.keys()}
                missing_knowledge_ids = sorted(requested_knowledge_ids - authorized_knowledge_ids)
                if missing_knowledge_ids:
                    raise ValueError(f"所选知识库不存在或无权限访问: {missing_knowledge_ids}")
        all_milvus = []
        all_milvus_filter = []
        all_es = []
        all_es_filter = []
        self._multi_milvus_retriever = None
        self._multi_es_retriever = None

        # Bulk-fetch non-primary file ids once for all knowledges in the retriever.
        # Applying the union to every knowledge's filter is correct — each collection
        # only contains its own files, so cross-knowledge ids are no-ops.
        knowledge_ids = list(self._knowledge_vector_list.keys())
        excluded_file_ids = self._fetch_non_primary_file_ids(knowledge_ids)

        for knowledge_id, knowledge_info in self._knowledge_vector_list.items():
            knowledge = knowledge_info.get("knowledge")
            milvus_vector = knowledge_info.get("milvus")
            es_vector = knowledge_info.get("es")
            milvus_filter_str, es_filter = self._metadata_filter.get_knowledge_filter(
                knowledge=knowledge, parent_node=self
            )
            if milvus_filter_str is None and es_filter is None:
                continue

            # Combine metadata filter with primary-only version filter.
            # build_primary_only_filter expects:
            #   base_milvus_expr: str | None
            #   base_es_filter: List[dict] | None  (the list under the "filter" key)
            base_es_list = es_filter.get("filter") if es_filter else None
            combined_milvus_expr, combined_es_list = build_primary_only_filter(
                excluded_file_ids,
                base_milvus_expr=milvus_filter_str or None,
                base_es_filter=base_es_list,
            )
            combined_milvus_expr, combined_es_list = self._apply_runtime_file_filter(
                int(knowledge_id),
                combined_milvus_expr,
                combined_es_list,
            )
            if combined_milvus_expr is None and combined_es_list is None:
                continue

            if milvus_vector:
                all_milvus.append(milvus_vector)
                milvus_extra = {"expr": combined_milvus_expr} if combined_milvus_expr else {}
                logger.debug(f"retrieve milvus filter: {milvus_extra}")
                all_milvus_filter.append(milvus_extra | self._retriever_kwargs)
            if es_vector:
                all_es.append(es_vector)
                # Reconstruct the ES search_kwargs dict: preserve any base keys from
                # es_filter (e.g. "filter") and override "filter" with combined list.
                combined_es_filter = dict(es_filter) if es_filter else {}
                if combined_es_list:
                    combined_es_filter["filter"] = combined_es_list
                elif "filter" in combined_es_filter:
                    # No exclusions, no base filter list — remove empty entry.
                    del combined_es_filter["filter"]
                logger.debug(f"retrieve es filter: {combined_es_filter}")
                all_es_filter.append(combined_es_filter | self._retriever_kwargs)

        if all_milvus:
            self._multi_milvus_retriever = MultiRetriever(
                vectors=all_milvus, search_kwargs=all_milvus_filter, finally_k=self._retriever_kwargs["k"]
            )
        if all_es:
            self._multi_es_retriever = MultiRetriever(
                vectors=all_es, search_kwargs=all_es_filter, finally_k=self._retriever_kwargs["k"]
            )

    def init_file_retriever(self):
        """retriever from file user upload"""
        file_ids = []
        for one in self._knowledge_value:
            file_metadata = self.get_other_node_variable(one)
            if not file_metadata:
                # No corresponding temporary file data found, User did not upload file
                continue
            file_ids.append(file_metadata[0]["document_id"])
        if not file_ids:
            self._multi_es_retriever = None
            self._multi_milvus_retriever = None
            return
        embeddings = LLMService.get_knowledge_default_embedding(self.user_id, tenant_id=self.tenant_id)
        if not embeddings:
            raise Exception("No knowledge base defaults configuredembeddingModels")

        # vectorstore use different collection_name for different embedding model
        tmp_collection_name = self.get_milvus_collection_name(embeddings.model_id)
        milvus_vector = KnowledgeRag.init_milvus_vectorstore(collection_name=tmp_collection_name, embeddings=embeddings)
        milvus_extra = {"expr": f"document_id in {file_ids}"}
        self._multi_milvus_retriever = milvus_vector.as_retriever(search_kwargs=self._retriever_kwargs | milvus_extra)

        es_extra = {"filter": [{"terms": {"metadata.document_id": file_ids}}]}
        es_vector = KnowledgeRag.init_es_vectorstore_sync(index_name=self.tmp_collection_name)
        self._multi_es_retriever = es_vector.as_retriever(search_kwargs=self._retriever_kwargs | es_extra)
