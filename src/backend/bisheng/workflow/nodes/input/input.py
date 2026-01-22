import os
import shutil
import tempfile
import time
from enum import Enum
from typing import Any, List
from urllib.parse import urlparse, unquote

from loguru import logger

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import read_chunk_text
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.chat.types import IgnoreException
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.core.cache.utils import file_download
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.llm.domain.services import LLMService
from bisheng.utils import generate_uuid
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.input.const import InputFileMetadata


class ParseModeEnum(str, Enum):
    KEEP_RAW = 'keep_raw'
    EXTRACT_TEXT = 'extract_text'
    INGEST_TO_KNOWLEDGE_BASE = 'ingest_to_temp_kb'


class InputNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Node Current Version
        self._current_v = 2
        # Whether the record is a conversation or a form
        self._tab = self.node_data.tab['value']

        # Record what type of variable this is
        self._node_params_map = {}
        new_node_params = {}
        # The maximum length of the input file in the dialog box, more than this length will be truncated

        if self.node_data.v < self._current_v:
            raise IgnoreException(f'{self.name} -- workflow node is update')

        if self.is_dialog_input():
            new_node_params['user_input'] = self.node_params['user_input']
            new_node_params['dialog_files_content'] = self.node_params.get('dialog_files_content', [])
        else:
            for value_info in self.node_params['form_input']:
                new_node_params[value_info['key']] = value_info['value']
                self._node_params_map[value_info['key']] = value_info

        self.node_params = new_node_params
        self._image_ext = ['png', 'jpg', 'jpeg', 'bmp']

        self._vector_client = None
        self._es_client = None

    def is_dialog_input(self):
        """ Whether the input is in the form of a conversation """
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
            # Input in the form of a dialog
            result = self.parse_upload_file("dialog_files", {
                "key": "dialog_files",
                "file_content": "dialog_files_content",
                "file_path": "dialog_files_path",
                "image_file": "dialog_image_files",
                "file_parse_mode": self.node_params.get("file_parse_mode", ParseModeEnum.EXTRACT_TEXT),
                "file_content_size": self.node_params.get("dialog_files_content_size", 15000)
            }, self.node_params.get('dialog_files_content', []))
            res = {
                'user_input': self.node_params['user_input'],
                'dialog_files_content': result.get("dialog_files_content", ""),
                'dialog_files_path': result.get("dialog_files_path", []),
                'dialog_image_files': result.get("dialog_image_files", []),
            }
            self.graph_state.save_context(content=f'{res["dialog_files_content"]}\n{res["user_input"]}',
                                          msg_sender='human')
            return res

        ret = {}
        human_input = ""
        # The corresponding file upload needs to be processed in the form
        for key, value in self.node_params.items():
            ret[key] = value
            key_info = self._node_params_map[key]
            label, _ = self.parse_msg_with_variables(key_info.get('value')) if key_info.get('value') else key
            if key_info['type'] == 'file':
                new_params = self.parse_upload_file(key, key_info, value)
                ret.update(new_params)
                if new_params[key_info['key']]:
                    content = ""
                    for one in new_params[key_info['key']]:
                        content += f"{one.get('source')},"
                    human_input += f"{label}: {content.rstrip(',')}\n"
            else:
                human_input += f"{label}: {value}\n"
        self.graph_state.save_context(content=f'{human_input}', msg_sender='human')
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        for k, v in result.items():
            if self._node_params_map.get(k) and self._node_params_map[k]['type'] == 'file':
                continue
            ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
        return [ret]

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
        file_id = generate_uuid()
        filepath, file_name = file_download(file_url)
        file_name = KnowledgeService.get_upload_file_original_name(file_name)

        # save original file path, because uns will convert file to pdf
        original_file_path = os.path.join(tempfile.gettempdir(), f'{file_id}.{file_name.split(".")[-1]}')
        shutil.copyfile(filepath, original_file_path)
        texts = []
        metadatas = []
        try:
            file_rule = FileProcessBase(knowledge_id=0)
            texts, metadatas, _, _ = read_chunk_text(self.user_id, filepath, file_name, file_rule.separator,
                                                     file_rule.separator_rule,
                                                     file_rule.chunk_size, 0, None,
                                                     file_rule.retain_images, file_rule.enable_formula,
                                                     file_rule.force_ocr,
                                                     file_rule.filter_page_header_footer, file_rule.excel_rule)
        except KnowledgeFileNotSupportedError as e:
            logger.exception('parse input node file error')
            if str(e).find('Type not supported') == -1:
                raise e

        return file_name, original_file_path, texts, metadatas

    def init_vector_clients(self):
        if self._vector_client is None:
            embedding = LLMService.get_knowledge_default_embedding(self.user_id)
            if not embedding:
                raise Exception('No default configured embedding Models')
            milvus_collection_name = self.get_milvus_collection_name(getattr(embedding, 'model_id'))
            self._vector_client = KnowledgeRag.init_milvus_vectorstore(milvus_collection_name, embedding,
                                                                       metadata_schemas=InputFileMetadata)
            self._es_client = KnowledgeRag.init_es_vectorstore_sync(self.tmp_collection_name,
                                                                    metadata_schemas=InputFileMetadata)

    def parse_upload_file(self, key: str, key_info: dict, value: List[str]) -> dict | None:
        """
         parse upload_file
         Documented metadataData, full-text files, minio file paths, image files path
        """
        # Parsing the file. need return values
        all_metadata = []
        all_file_content = ''
        original_file_path = []
        image_files_path = []
        if not value:
            logger.warning(f"{self.id}.{key} value is None")
            return {
                key_info['key']: all_metadata,
                key_info['file_content']: all_file_content,
                key_info['file_path']: original_file_path,
                key_info['image_file']: image_files_path
            }

        file_parse_mode = key_info.get('file_parse_mode', ParseModeEnum.INGEST_TO_KNOWLEDGE_BASE)
        file_content_max_size = int(key_info.get('file_content_size', 15000))

        file_id = generate_uuid()

        file_content_length = 0
        for one_file_url in value:
            url_obj = urlparse(one_file_url)
            file_name = unquote(url_obj.path.split('/')[-1])

            file_ext = file_name.split('.')[-1].lower()
            logger.debug(f"{self.id}.{key} file_parse_mode is keep_raw")
            original_file_path.append(one_file_url)
            if file_ext in self._image_ext:
                image_files_path.append(one_file_url)

            if file_parse_mode == ParseModeEnum.KEEP_RAW:
                continue

            file_name, file_path, texts, metadatas = self.get_upload_file_path_content(one_file_url)
            if file_content_length < file_content_max_size:
                file_content = "\n".join(texts)
                file_content = file_content[:file_content_max_size - file_content_length]
                file_content_length += len(file_content)
                all_file_content += f"[file name]: {file_name}\n[file content begin]\n{file_content}\n[file content end]\n"
            if not texts:
                logger.debug(f"{self.id}.{key} extract file text is empty")
                continue
            if file_parse_mode == ParseModeEnum.EXTRACT_TEXT:
                continue

            self.init_vector_clients()
            new_metadata = []
            # A file corresponding to the same variable, placed in a file_id mile
            for one in metadatas:
                metadata = one.model_dump()
                metadata.update({
                    'document_id': file_id,
                    'document_name': file_name,
                    'knowledge_id': self.workflow_id,
                    'upload_time': int(time.time()),
                    'bbox': '',  # Temporary files cannot be traced because the source files are not persisted
                })
                new_metadata.append(metadata)

            # Uploaded to milvus And es
            logger.debug(f'workflow_add_vectordb file={key} file_name={file_name} file_id={file_id}')
            self._vector_client.add_texts(texts=texts, metadatas=new_metadata)

            logger.debug(f'workflow_add_es file={key} file_name={file_name} file_id={file_id}')
            self._es_client.add_texts(texts=texts, metadatas=new_metadata)

            logger.debug(f'workflow_record_file_metadata file={key} file_name={file_name}')
            all_metadata.append(new_metadata[0])
        # Documentation metadata, other nodes according to metadataData to retrieve corresponding files
        return {
            key_info['key']: all_metadata,
            key_info['file_content']: all_file_content,
            key_info['file_path']: original_file_path,
            key_info['image_file']: image_files_path
        }
