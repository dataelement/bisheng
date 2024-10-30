from bisheng_langchain.rag.bisheng_rag_chain import BishengRetrievalQA

from bisheng.api.services.llm import LLMService
from bisheng.database.models.user import UserDao
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
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

        # 解析prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params["system_prompt"])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params["user_prompt"])
        self._user_variables = self._user_prompt.extract()

        self.llm = LLMService.get_bisheng_llm(model_id=self.node_params["model_id"],
                                              temperature=self.node_params.get("temperature", 0.3))

        self._user_info = UserDao.get_user(int(self.user_id))

        self._milvus = None
        self._es = None

    def _run(self):

        # 判断是知识库还是临时文件列表，初始化对应的milvus和es
        pass

    def init_milvus(self):
        if self._milvus:
            return
        if self._knowledge_type == "knowledge":
            node_type = "MilvusWithPermissionCheck"
            params = {
                "user_name": self._user_info.user_name,
                "collection_name": self._knowledge_value,  # 知识库id列表
                "_is_check_auth": self._knowledge_auth
            }
        else:
            embeddings = LLMService.get_knowledge_default_embedding()
            if not embeddings:
                raise Exception("没有配置默认的embedding模型")
            file_ids = []
            for one in self._knowledge_value:
                file_metadata = self.graph_state.get_variable_by_str(one)
                file_ids.append(f"file_id == \"{file_metadata['file_id']}\"")

            node_type = "Milvus"
            params = {
                "collection_name": self.tmp_collection_name,
                "partition_key": self.workflow_id,
                "embedding": embeddings,
                "metadata_expr": " or ".join(file_ids)
            }

        class_obj = import_vectorstore(node_type)
        milvus_obj = instantiate_vectorstore(node_type, class_object=class_obj, params=params)
