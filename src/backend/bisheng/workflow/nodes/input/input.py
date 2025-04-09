import json
import os
import shutil
import tempfile
from typing import Any

from bisheng.api.services.knowledge_imp import decide_vectorstores, read_chunk_text
from bisheng.api.services.llm import LLMService
from bisheng.api.utils import md5_hash
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import file_download
from bisheng.chat.types import IgnoreException
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
        # 对话框里输入文件的最大长度，超过这个长度会被截断
        self._dialog_files_length = int(self.node_params.get('dialog_files_content_size', 15000))
        if self.is_dialog_input():
            new_node_params['user_input'] = self.node_params['user_input']
            new_node_params['dialog_files_content'] = self.node_params.get('dialog_files_content', [])
        else:
            for value_info in self.node_params['form_input']:
                new_node_params[value_info['key']] = value_info['value']
                self._node_params_map[value_info['key']] = value_info

        # 初始化redis客户端，获取通过对话框上传的文件内容
        self._redis_client = redis_client
        self.node_params = new_node_params

    def is_dialog_input(self):
        """ 是否是对话形式的输入 """
        if self._tab == 'dialog_input':
            return True
        elif self._tab == 'form_input':
            return False
        raise IgnoreException(f'{self.name} -- workflow node is update')

    def get_input_schema(self) -> Any:
        if self.is_dialog_input():
            return self.node_data.get_variable_info('user_input')
        return self.node_data.get_variable_info('form_input')

    def _run(self, unique_id: str):
        if self.is_dialog_input():
            res = {'user_input': self.node_params['user_input'], "dialog_files_content": self.parse_dialog_files()}
            self.graph_state.save_context(content=f'{res["dialog_files_content"]}\n{res["user_input"]}', msg_sender='human')
            return res

        ret = {}
        # 存到聊天历史记录内
        human_input = ""
        # 表单形式的需要去处理对应的文件上传
        for key, value in self.node_params.items():
            ret[key] = value
            human_input += f'{key}:{value}\n'
            key_info = self._node_params_map[key]
            if key_info['type'] == 'file':
                new_params = self.parse_upload_file(key,key_info, value)
                if key_info['multiple']:
                    new_params = {key_info['key']: new_params[key_info['key']]}
                ret.update(new_params)

        self.graph_state.save_context(content=human_input, msg_sender='human')
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        for k,v in result.items():
            if self._node_params_map.get(k) and self._node_params_map[k]['type'] == 'file':
                continue
            ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
        return [ret]

    def parse_dialog_files(self) -> str:
        """ 获取对话框里上传的文件内容 """
        file_length = 0
        dialog_files_content = ""
        if not self.node_params.get('dialog_files_content'):
            return dialog_files_content
        for file_id in self.node_params['dialog_files_content']:
            file_info = self._redis_client.get(f'workflow:dialog_file:{file_id}')
            if not file_info:
                continue
            if file_length >= self._dialog_files_length:
                break
            file_info = json.loads(file_info)
            file_info['content'] = file_info['content'][:self._dialog_files_length - file_length]
            file_length += len(file_info['content'])

            dialog_files_content += f"[file name]: {file_info['name']}\n[file content begin]\n{file_info['content']}\n[file content end]\n"
        return dialog_files_content

    def parse_upload_file(self, key: str, key_info: dict, value: str) -> dict | None:
        """
         将文件上传到milvus后
         记录文件的metadata数据、文件全文、文件本地路径
        """
        if 'file_content' not in key_info:
            raise IgnoreException(f'{self.name} -- workflow node is update')
        if not value:
            logger.warning(f"{self.id}.{key} value is None")
            return {
                key_info['key']: None,
                key_info['file_content']: None,
                key_info['file_path']: None
            }


        # 1、获取默认的embedding模型
        embeddings = LLMService.get_knowledge_default_embedding()
        if not embeddings:
            raise Exception('没有配置默认的embedding模型')

        # 2、初始化milvus和es实例
        milvus_collection_name = self.get_milvus_collection_name(getattr(embeddings, 'model_id'))
        vector_client = decide_vectorstores(milvus_collection_name, 'Milvus', embeddings)
        es_client = decide_vectorstores(self.tmp_collection_name, 'ElasticKeywordsSearch',
                                        embeddings)

        # 3、解析文件
        metadatas = []
        texts = []
        original_file_path = ''
        file_id = md5_hash(f'{key}:{value[0]}')
        for one_file_url in value:
            filepath, file_name = file_download(one_file_url)
            if not original_file_path:
                original_file_path = os.path.join(tempfile.gettempdir(), f'{file_id}.{file_name.split(".")[-1]}')
                shutil.copyfile(filepath, original_file_path)
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
        return {
            key_info['key']: metadatas[0],
            key_info['file_content']: "\n".join(texts),
            key_info['file_path']: original_file_path
        }
