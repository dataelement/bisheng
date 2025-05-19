import os
import shutil
import tempfile
from typing import Any

from loguru import logger

from bisheng.api.services.knowledge_imp import decide_vectorstores, read_chunk_text
from bisheng.api.services.llm import LLMService
from bisheng.api.utils import md5_hash
from bisheng.cache.utils import file_download
from bisheng.chat.types import IgnoreException
from bisheng.workflow.nodes.base import BaseNode


class InputNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 节点当前版本
        self._current_v = 2
        # 记录是对话还是表单
        self._tab = self.node_data.tab['value']

        # 记录这个变量是什么类型的
        self._node_params_map = {}
        new_node_params = {}
        # 对话框里输入文件的最大长度，超过这个长度会被截断
        self._dialog_files_length = int(self.node_params.get('dialog_files_content_size', 15000))
        # save image file path
        self._dialog_images_files = []

        if self.is_dialog_input():
            new_node_params['user_input'] = self.node_params['user_input']
            new_node_params['dialog_files_content'] = self.node_params.get('dialog_files_content', [])
        else:
            for value_info in self.node_params['form_input']:
                new_node_params[value_info['key']] = value_info['value']
                self._node_params_map[value_info['key']] = value_info

        self.node_params = new_node_params
        self._image_ext = ['png', 'jpg', 'jpeg', 'bmp']

        self._embedding = None
        self._vector_client = None
        self._es_client = None

    def is_dialog_input(self):
        """ 是否是对话形式的输入 """
        if self.node_data.v < self._current_v:
            raise IgnoreException(f'{self.name} -- workflow node is update')

        if self._tab == 'dialog_input':
            return True
        elif self._tab == 'form_input':
            return False
        raise IgnoreException(f'{self.name} -- workflow node is update')

    def get_input_schema(self) -> Any:
        if self.is_dialog_input():
            user_input_info = self.node_data.get_variable_info('user_input')
            user_input_info.value = [
                self.node_data.get_variable_info('dialog_files_content'),
                self.node_data.get_variable_info('dialog_file_accept')
            ]
            return user_input_info
        form_input_info = self.node_data.get_variable_info('form_input')
        for one in form_input_info.value:
            one['value'], _ = self.parse_msg_with_variables(one['value'])
        return form_input_info

    def _run(self, unique_id: str):
        if self.is_dialog_input():
            # 对话框形式的输入
            dislog_files_content, self._dialog_images_files = self.parse_dialog_files()
            res = {
                'user_input': self.node_params['user_input'],
                'dialog_files_content': dislog_files_content,
                'dialog_image_files': self._dialog_images_files
            }
            self.graph_state.save_context(content=f'{res["dialog_files_content"]}\n{res["user_input"]}',
                                          msg_sender='human')
            return res

        ret = {}
        # 表单形式的需要去处理对应的文件上传
        for key, value in self.node_params.items():
            ret[key] = value
            key_info = self._node_params_map[key]
            if key_info['type'] == 'file':
                new_params = self.parse_upload_file(key, key_info, value)
                ret.update(new_params)

        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        for k, v in result.items():
            if self._node_params_map.get(k) and self._node_params_map[k]['type'] == 'file':
                continue
            ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
        return [ret]

    def parse_dialog_files(self) -> (str, list[str]):
        """ 获取对话框里上传的文件内容 """
        file_length = 0
        dialog_files_content = ""
        image_files_path = []
        if not self.node_params.get('dialog_files_content'):
            return dialog_files_content, image_files_path
        for file_id in self.node_params['dialog_files_content']:
            file_name, file_path, chunks, metadatas = self.get_upload_file_path_content(file_id)
            file_ext = file_name.split('.')[-1].lower()
            if file_ext in self._image_ext:
                image_files_path.append(file_path)

            if file_length >= self._dialog_files_length:
                continue
            file_content = "\n".join(chunks)
            file_content = file_content[:self._dialog_files_length - file_length]
            file_length += len(file_content)

            dialog_files_content += f"[file name]: {file_name}\n[file content begin]\n{file_content}\n[file content end]\n"
        return dialog_files_content, image_files_path

    def get_upload_file_path_content(self, file_url: str) -> (str, str, list, list):
        """
        params:
            file_url: upload to minio share url
        return:
            0: file name
            1: file path in system
            2: chunks list
            3: metadata list
        """
        # 1、获取默认的embedding模型
        if self._embedding is None:
            embedding = LLMService.get_knowledge_default_embedding()
            if not embedding:
                raise Exception('没有配置默认的embedding模型')
            self._embedding = embedding

        if self._vector_client is None:
            # 2、初始化milvus和es实例
            milvus_collection_name = self.get_milvus_collection_name(getattr(self._embedding, 'model_id'))
            self._vector_client = decide_vectorstores(milvus_collection_name, 'Milvus', self._embedding)
            self._es_client = decide_vectorstores(self.tmp_collection_name, 'ElasticKeywordsSearch',
                                                  self._embedding)

        file_id = md5_hash(f'{file_url}')
        filepath, file_name = file_download(file_url)

        # save original file path, because uns will convert file to pdf
        original_file_path = os.path.join(tempfile.gettempdir(), f'{file_id}.{file_name.split(".")[-1]}')
        shutil.copyfile(filepath, original_file_path)
        texts = []
        metadatas = []
        try:
            texts, metadatas, _, _ = read_chunk_text(filepath, file_name,
                                                     ['\n\n', '\n'],
                                                     ['after', 'after'], 1000, 500)
            for metadata in metadatas:
                metadata.update({
                    'file_id': file_id,
                    'knowledge_id': self.workflow_id,
                    'extra': '',
                    'bbox': '',  # 临时文件不能溯源，因为没有持久化存储源文件
                })
        except Exception as e:
            logger.exception('parse input node file error')
            if str(e).find('类型不支持') == -1:
                raise e

        return file_name, original_file_path, texts, metadatas

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
                key_info['file_path']: None,
                key_info['image_file']: None
            }

        # 解析文件
        all_metadata = []
        all_file_content = ''
        original_file_path = []
        file_id = md5_hash(f'{key}:{value[0]}')
        image_files_path = []
        file_content_max_size = int(key_info.get('file_content_size', 15000))
        file_content_length = 0
        for one_file_url in value:
            file_name, file_path, texts, metadatas = self.get_upload_file_path_content(one_file_url)
            original_file_path.append(file_path)
            file_ext = file_name.split('.')[-1].lower()
            if file_ext in self._image_ext:
                image_files_path.append(file_path)

            if file_content_length < file_content_max_size:
                file_content = "\n".join(texts)
                file_content = file_content[:file_content_max_size - file_content_length]
                file_content_length += len(file_content)
                all_file_content += f"[file name]: {file_name}\n[file content begin]\n{file_content}\n[file content end]\n"

            if not texts:
                continue

            # 同一个变量对应的文件，放在一个file_id里
            for one in metadatas:
                one.update({
                    'file_id': file_id,
                    'knowledge_id': self.workflow_id,
                    'extra': '',
                    'bbox': '',  # 临时文件不能溯源，因为没有持久化存储源文件
                })

            # 上传到milvus和es
            logger.debug(f'workflow_add_vectordb file={key} file_name={file_name}')
            # 存入milvus
            self._vector_client.add_texts(texts=texts, metadatas=metadatas)

            logger.debug(f'workflow_add_es file={key} file_name={file_name}')
            # 存入es
            self._es_client.add_texts(texts=texts, metadatas=metadatas)

            logger.debug(f'workflow_record_file_metadata file={key} file_name={file_name}')
            all_metadata.append(metadatas[0])
        # 记录文件metadata，其他节点根据metadata数据去检索对应的文件
        return {
            key_info['key']: all_metadata,
            key_info['file_content']: all_file_content,
            key_info['file_path']: original_file_path,
            key_info['image_file']: image_files_path
        }
