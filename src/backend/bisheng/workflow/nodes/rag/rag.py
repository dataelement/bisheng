from typing import List

from bisheng_langchain.rag.bisheng_rag_chain import BishengRetrievalQA
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate, ChatPromptTemplate

from bisheng.api.services.llm import LLMService
from bisheng.database.models.user import UserDao
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class RagNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 判断是知识库还是临时文件列表
        self._knowledge_type = self.node_params["retrieved_result"]["type"]
        self._knowledge_value = [one["key"] for one in self.node_params["retrieved_result"]["value"]]

        self._knowledge_auth = self.node_params["user_auth"]
        self._max_chunk_size = self.node_params["max_chunk_size"]
        self._sort_chunks = False

        # 解析prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params["system_prompt"])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params["user_prompt"])
        self._user_variables = self._user_prompt.extract()

        self._qa_prompt = None

        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params["model_id"],
                                               temperature=self.node_params.get("temperature", 0.3))

        self._user_info = UserDao.get_user(int(self.user_id))

        self._milvus = None
        self._es = None

    def _run(self):

        self.init_user_question()
        self.init_qa_prompt()
        self.init_milvus()
        self.init_es()

        retriever = BishengRetrievalQA.from_llm(
            llm=self._llm,
            vector_store=self._milvus,
            keyword_store=self._es,
            QA_PROMPT=self._qa_prompt,
            max_content=self._max_chunk_size,
            sort_by_source_and_index=self._sort_chunks,
            return_source_documents=True,
        )
        user_questions = self.init_user_question()
        ret = {}
        for index, question in enumerate(user_questions):
            result = retriever._call({"query":question})
            if self.node_params["output_user"]:
                self.callback_manager.on_output_msg(OutputMsgData(node_id=self.id, msg=result["result"]))
            ret[self.node_params["output_user_input"][index]["key"]] = result
        return ret

    def init_user_question(self) -> List[str]:
        ret = []
        for one in self.node_params["user_question"]:
            ret.append(self.graph_state.get_variable_by_str(one))
        return ret

    def init_qa_prompt(self):
        variable_map = {}
        for one in self._user_variables:
            if one == f"{self.id}.user_question":
                variable_map[one] = "{question}"
            elif one == f"{self.id}.retrieved_result":
                variable_map[one] = "{context}"
            else:
                variable_map[one] = self.graph_state.get_variable_by_str(one)
        user_prompt = self._user_prompt.format(variable_map)

        variable_map = {}
        for one in self._system_variables:
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        system_prompt = self._system_prompt.format(variable_map)

        messages_general = [
            SystemMessagePromptTemplate.from_template(system_prompt),
            HumanMessagePromptTemplate.from_template(user_prompt),
        ]
        self._qa_prompt = ChatPromptTemplate.from_messages(messages_general)

    def init_milvus(self):
        if self._milvus:
            return
        if self._knowledge_type == "knowledge":
            node_type = "MilvusWithPermissionCheck"
            params = {
                "user_name": self._user_info.user_name,
                "collection_name": [{"key": one} for one in self._knowledge_value],  # 知识库id列表
                "_is_check_auth": self._knowledge_auth
            }
        else:
            embeddings = LLMService.get_knowledge_default_embedding()
            if not embeddings:
                raise Exception("没有配置默认的embedding模型")
            file_ids = []
            for one in self._knowledge_value:
                file_metadata = self.graph_state.get_variable_by_str(one)
                file_ids.append(file_metadata['file_id'])
            self._sort_chunks = len(file_ids) == 1
            node_type = "Milvus"
            params = {
                "collection_name": self.tmp_collection_name,
                "partition_key": self.workflow_id,
                "embedding": embeddings,
                "metadata_expr": f"file_id in {file_ids}"
            }

        class_obj = import_vectorstore(node_type)
        self._milvus = instantiate_vectorstore(node_type, class_object=class_obj, params=params)

    def init_es(self):
        if self._es:
            return
        if self._knowledge_type == "knowledge":
            node_type = "ElasticsearchWithPermissionCheck"
            params = {
                "user_name": self._user_info.user_name,
                "index_name": [{"key": one} for one in self._knowledge_value],  # 知识库id列表
                "_is_check_auth": self._knowledge_auth
            }
        else:
            file_ids = []
            for one in self._knowledge_value:
                file_metadata = self.graph_state.get_variable_by_str(one)
                file_ids.append(file_metadata['file_id'])
            node_type = "ElasticKeywordsSearch"
            params = {
                "index_name": self.tmp_collection_name,
                "post_filter": {"terms": {"metadata.file_id": file_ids}}
            }
        class_obj = import_vectorstore(node_type)
        self._es = instantiate_vectorstore(node_type, class_object=class_obj, params=params)