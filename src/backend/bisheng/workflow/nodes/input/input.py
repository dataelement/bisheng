from typing import Any

from bisheng.api.services.knowledge_imp import decide_vectorstores, read_chunk_text
from bisheng.api.services.llm import LLMService
from bisheng.api.utils import md5_hash
from bisheng.cache.utils import file_download
from bisheng.workflow.nodes.base import BaseNode
from loguru import logger


class InputNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 记录是对话还是表单
        self._tab = self.node_data.tab['value']

        # 记录这个变量是什么类型的
        self._node_params_map = {}
        new_node_params = {}
        if self._tab == 'input':
            new_node_params['user_input'] = self.node_params['user_input']
        else:
            for value_info in self.node_params['form_input']:
                new_node_params[value_info['key']] = value_info['value']
                self._node_params_map[value_info['key']] = value_info
        self.node_params = new_node_params

    def get_input_schema(self) -> Any:
        return self.node_data.group_params

    def _run(self, unique_id: str):
        if self._tab == 'input':
            return {'user_input': self.node_params['user_input']}

        # 表单形式的需要去处理对应的文件上传
        for key, value in self.node_params.items():
            key_info = self._node_params_map[key]
            if key_info['type'] == 'file':
                file_metadata = self.parse_upload_file(key, value)
                self.node_params[key] = file_metadata

        return self.node_params

    def parse_upload_file(self, key: str, value: str) -> dict | None:
        """
         将文件上传到milvus后
         记录文件的metadata数据
        """
        if not value:
            return None

        # 1、获取默认的embedding模型
        embeddings = LLMService.get_knowledge_default_embedding()
        if not embeddings:
            raise Exception('没有配置默认的embedding模型')
        # 2、初始化milvus和es实例
        vector_client = decide_vectorstores(self.tmp_collection_name, 'Milvus', embeddings)
        es_client = decide_vectorstores(self.tmp_collection_name, 'ElasticKeywordsSearch',
                                        embeddings)

        # 3、解析文件
        filepath, file_name = file_download(value)
        file_id = md5_hash(f'{key}:{value}')
        texts, metadatas, parse_type, partitions = read_chunk_text(filepath, file_name,
                                                                   ['\n\n', '\n'],
                                                                   ['after', 'after'], 1000, 500)
        if len(texts) == 0:
            raise ValueError('文件解析为空')

        for metadata in metadatas:
            metadata.update({
                'file_id': file_id,
                'knowledge_id': self.workflow_id,
                'extra': '',
                'bbox': '',  # 临时文件不能溯源，因为没有持久化存储源文件
            })
        # 4、上传到milvus和es
        logger.info(f'workflow_add_vectordb file={key} file_name={file_name}')
        # 存入milvus
        vector_client.add_texts(texts=texts, metadatas=metadatas)

        logger.info(f'workflow_add_es file={key} file_name={file_name}')
        # 存入es
        es_client.add_texts(texts=texts, metadatas=metadatas)

        logger.info(f'workflow_record_file_metadata file={key} file_name={file_name}')
        # 记录文件metadata，其他节点根据metadata数据去检索对应的文件
        return metadatas[0]
