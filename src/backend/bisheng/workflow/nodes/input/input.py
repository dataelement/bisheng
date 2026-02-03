import copy
import json
import time
from enum import Enum
from typing import Any, List, Dict
from urllib.parse import urlparse, unquote

from json_repair import json_repair
from langchain_core.messages import SystemMessage, HumanMessage
from loguru import logger

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import read_chunk_text
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.chat.types import IgnoreException
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.core.cache.utils import file_download
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.llm.domain.services import LLMService
from bisheng.utils import generate_uuid
from bisheng.workflow.callback.event import GuideQuestionData
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

        self._original_node_params = copy.deepcopy(self.node_params)

        # save user set file key -> file key info
        self._file_key_map = {}

        if self.is_dialog_input():
            new_node_params['user_input'] = self.node_params['user_input']
            new_node_params['dialog_files_content'] = self.node_params.get('dialog_files_content', [])
        else:
            for value_info in self.node_params['form_input']:
                value_key = value_info['key']
                # The file key needs to be re-generated to avoid parse type not ingest to knowledge base
                if value_info["type"] == "file":
                    value_key = f"file_{generate_uuid()[:8]}"
                    self._file_key_map[value_info['key']] = value_info
                new_node_params[value_key] = value_info['value']
                self._node_params_map[value_key] = value_info

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
            try:
                self.handle_recommended_questions()
            except Exception as e:
                logger.exception("handle recommended questions error")
            user_input_info = self.node_data.get_variable_info('user_input')
            user_input_info.value = [
                self.node_data.get_variable_info('dialog_files_content'),
                self.node_data.get_variable_info('dialog_file_accept'),
                self.node_data.get_variable_info('user_input_file'),
            ]
            return user_input_info
        form_input_info = self.node_data.get_variable_info('form_input')
        form_variables = copy.deepcopy(self._node_params_map)
        res = []
        for one_key, one in form_variables.items():
            one['key'] = one_key
            one['value'], _ = self.parse_msg_with_variables(one['value'])
            res.append(one)
        form_input_info.value = res
        return form_input_info

    def handle_recommended_questions(self):
        recommended_questions_flag = self._original_node_params.get('recommended_questions_flag', False)
        if not recommended_questions_flag:
            return
        recommended_llm = self._original_node_params.get('recommended_llm', 0)
        recommended_system_prompt = self._original_node_params.get('recommended_system_prompt', '')
        recommended_history_num = self._original_node_params.get('recommended_history_num', 3)
        if not recommended_llm or not recommended_system_prompt or not recommended_history_num:
            logger.debug(f"{self.name} recommended questions config incomplete")
            return
        chat_history = self.graph_state.get_history_memory(recommended_history_num)
        if not chat_history:
            logger.debug(f"{self.name} recommended questions chat history is empty")
            return
        recommended_system_prompt, _ = self.parse_msg_with_variables(recommended_system_prompt)
        llm_obj = LLMService.get_bisheng_llm_sync(model_id=recommended_llm,
                                                  app_id=self.workflow_id,
                                                  app_name=self.workflow_name,
                                                  app_type=ApplicationTypeEnum.WORKFLOW,
                                                  user_id=self.user_id)
        user_prompt = f"# Current Conversation Context\n{chat_history}"
        result = llm_obj.invoke([SystemMessage(content=recommended_system_prompt), HumanMessage(content=user_prompt)])
        result = result.content
        try:
            result = json.loads(result)
        except json.decoder.JSONDecodeError:
            logger.debug("received non-json response from LLM, try json repair")
            try:
                result = json_repair.loads(result, skip_json_loads=True)
            except Exception as e:
                logger.error(f"json repair failed: {e}")
                return
        logger.debug(f"received response from LLM, result is {result}")
        if not isinstance(result, dict):
            return
        questions = []
        for key, value in result.items():
            if isinstance(value, list):
                questions = value
                break
        if not questions:
            return
        self.callback_manager.on_guide_question(data=GuideQuestionData(node_id=self.id, name=self.name,
                                                                       unique_id=generate_uuid(),
                                                                       guide_question=questions[:3]))

    def _parse_upload_file_variables(self, key_info: Dict, key_value: Dict) -> Dict:
        """
         parse upload_file variables
         Documented metadataData, full-text files, minio file paths, image files path
        """
        # Compatible processing of historical versions of nodes
        if self.node_data.v <= self._current_v:
            return key_value

        file_parse_mode = key_info.get('file_parse_mode', ParseModeEnum.INGEST_TO_KNOWLEDGE_BASE)
        ret = {}
        if file_parse_mode == ParseModeEnum.KEEP_RAW:
            ret[key_info['image_file']] = key_value.get(key_info['image_file'], [])
            ret[key_info['file_path']] = key_value.get(key_info['file_path'], [])
        elif file_parse_mode == ParseModeEnum.EXTRACT_TEXT:
            ret[key_info['file_content']] = key_value.get(key_info['file_content'], "")
        else:
            ret[key_info['key']] = key_value.get(key_info['key'], [])
        return ret

    def _run(self, unique_id: str):
        if self.is_dialog_input():
            key_info = {
                "key": "dialog_files",
                "file_content": "dialog_files_content",
                "file_path": "dialog_file_paths",
                "image_file": "dialog_image_files",
                "file_parse_mode": self._original_node_params.get("file_parse_mode", ParseModeEnum.EXTRACT_TEXT),
                "file_content_size": self._original_node_params.get("dialog_files_content_size", 15000)
            }
            # Input in the form of a dialog
            result = self.parse_upload_file("dialog_files", key_info, self.node_params.get('dialog_files_content', []))
            res = {
                'user_input': self.node_params['user_input'],
            }
            res.update(self._parse_upload_file_variables(key_info, result))

            self.graph_state.save_context(content=f'{res.get("dialog_files_content", "")}\n{res["user_input"]}',
                                          msg_sender='human')
            return res

        ret = {}
        human_input = ""
        # The corresponding file upload needs to be processed in the form
        for key, value in self.node_params.items():
            key_info = self._node_params_map[key]
            label, _ = self.parse_msg_with_variables(key_info.get('value')) if key_info.get('value') else key
            if key_info['type'] == 'file':
                new_params = self.parse_upload_file(key, key_info, value)
                ret.update(self._parse_upload_file_variables(key_info, new_params))

                if new_params[key_info['key']]:
                    content = ""
                    for one in new_params[key_info['key']]:
                        content += f"{one.get('document_name', '')},"
                    human_input += f"{label}: {content.rstrip(',')}\n"
            else:
                ret[key] = value
                human_input += f"{label}: {value}\n"
        self.graph_state.save_context(content=f'{human_input}', msg_sender='human')
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        for k, v in result.items():
            if (self._node_params_map.get(k) and self._node_params_map[k]['type'] == 'file') or (
                    self._file_key_map.get(k) and self._file_key_map[k]['type'] == 'file'):
                continue
            ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
        return [ret]

    def get_upload_file_path_content(self, file_url: str) -> (list, list):
        """
        params:
            file_url: upload to minio share url
        return:
            0: chunks list
            1: metadata list
        """
        filepath, file_name = file_download(file_url)

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

        return texts, metadatas

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
            # get file original name
            file_name = KnowledgeService.get_upload_file_original_name(file_name)
            all_metadata.append({
                "document_id": file_id,
                "document_name": file_name,
                "knowledge_id": self.workflow_id,
                "upload_time": int(time.time()),
                "bbox": '',  # Temporary files cannot be traced because the source files are not persisted
            })

            file_ext = file_name.split('.')[-1].lower()
            logger.debug(f"{self.id}.{key} file_parse_mode is keep_raw")
            original_file_path.append(one_file_url)
            if file_ext in self._image_ext:
                image_files_path.append(one_file_url)

            if file_parse_mode == ParseModeEnum.KEEP_RAW:
                continue

            texts, metadatas = self.get_upload_file_path_content(one_file_url)
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
                metadata.update(all_metadata[-1])
                new_metadata.append(metadata)

            # Uploaded to milvus And es
            logger.debug(f'workflow_add_vectordb file={key} file_name={file_name} file_id={file_id}')
            self._vector_client.add_texts(texts=texts, metadatas=new_metadata)

            logger.debug(f'workflow_add_es file={key} file_name={file_name} file_id={file_id}')
            self._es_client.add_texts(texts=texts, metadatas=new_metadata)

            logger.debug(f'workflow_record_file_metadata file={key} file_name={file_name}')
            all_metadata[-1] = new_metadata[0]
        # Documentation metadata, other nodes according to metadataData to retrieve corresponding files
        return {
            key_info['key']: all_metadata,
            key_info['file_content']: all_file_content,
            key_info['file_path']: original_file_path,
            key_info['image_file']: image_files_path
        }
