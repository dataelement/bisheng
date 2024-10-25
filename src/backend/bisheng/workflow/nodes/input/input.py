from bisheng.api.services.knowledge_imp import decide_vectorstores, read_chunk_text
from bisheng.api.utils import md5_hash
from bisheng.cache.utils import file_download
from bisheng.workflow.nodes.base import BaseNode
from bisheng.api.services.llm import LLMService


class InputNode(BaseNode):

    def init_data(self):
        # 对话框形式只有一个输出变量
        if self.node_data.tab.value == "input":
            self.node_params["user_input"] = ""
            return

        # 表单形式
        # 记录这个变量是什么类型的
        self.node_params_map = {}
        for one in self.node_data.group_params:
            if one.key != "form_input":
                continue
            for value_info in one.value:
                self.node_params[value_info.key] = value_info.value
                self.node_params_map[value_info.key] = value_info

    def _run(self):
        if self.node_data.tab.value == "input":
            return {"user_input": self.node_params["user_input"]}

        ret = {}
        # 表单形式的需要去处理对应的文件上传
        for key, value in self.node_param.items():
            key_info = self.node_params_map[key]
            if key_info.type == "file":
                self.parse_upload_file(key, value)

        return self.node_params

    def parse_upload_file(self, key: str, value: str):
        """ 将文件上传到milvus后 """
        if not value:
            return

        # 将文件上传到milvus和es

        # 1、获取默认的embedding模型
        embeddings = LLMService.get_knowledge_default_embedding()
        if not embeddings:
            raise Exception("没有配置默认的embedding模型")
        # 2、初始化milvus和es实例
        vector_client = decide_vectorstores(self.tmp_collection_name, 'Milvus', embeddings)
        es_client = decide_vectorstores(self.tmp_collection_name, 'ElasticKeywordsSearch', embeddings)

        # 3、解析文件
        filepath, file_name = file_download(value)
        # file_name = md5_hash(f"{key}:{value}")
        texts, metadatas, parse_type, partitions = read_chunk_text(filepath, file_name,
                                                                   ["\n\n", "\n"], ["after", "after"],
                                                                   1000, 500)


