import json
import time
from typing import List, Any

import loguru

from bisheng.api.services.llm import LLMService
from bisheng.chat.types import IgnoreException
from bisheng.database.models.user import UserDao
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.utils.minio_client import MinioClient
from bisheng.workflow.callback.event import OutputMsgData, StreamMsgOverData
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser
from bisheng_langchain.rag.bisheng_rag_chain import BishengRetrievalQA
from langchain_core.prompts import (ChatPromptTemplate, HumanMessagePromptTemplate,
                                    SystemMessagePromptTemplate)


class RagNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 判断是知识库还是临时文件列表
        if 'knowledge' not in self.node_params:
            raise IgnoreException(f'{self.name} -- node params is error')
        self._knowledge_type = self.node_params['knowledge']['type']
        self._knowledge_value = [
            one['key'] for one in self.node_params['knowledge']['value']
        ]

        self._minio_client = MinioClient()

        self._knowledge_auth = self.node_params['user_auth']
        self._max_chunk_size = int(self.node_params['max_chunk_size'])
        self._sort_chunks = False

        # 解析prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()

        self._qa_prompt = None

        self._enable_web_search = self.node_params.get('enable_web_search', False)

        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params['model_id'], enable_web_search=self._enable_web_search,
                                               temperature=self.node_params.get(
                                                   'temperature', 0.3),
                                               cache=False)

        self._user_info = UserDao.get_user(int(self.user_id))

        # 是否输出结果给用户
        self._output_user = self.node_params.get('output_user', False)
        self._show_source = self.node_params.get('show_source', True)
        # self._show_source = True

        # 运行日志数据
        self._log_source_documents = {}
        self._log_system_prompt = []
        self._log_user_prompt = []
        self._log_reasoning_content = {}

        self._milvus = None
        self._es = None

    def _run(self, unique_id: str):
        self._log_source_documents = {}
        self._log_system_prompt = []
        self._log_user_prompt = []
        self._log_reasoning_content = {}

        self.init_qa_prompt()
        self.init_milvus()
        self.init_es()

        loguru.logger.debug(f'jjxx flag1')

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
            output_key = self.node_params['output_user_input'][index]['key']
            if question is None:
                question = ''
            # 因为rag需要溯源所以不能用通用llm callback来返回消息。需要拿到source_document之后在返回消息内容
            llm_callback = LLMNodeCallbackHandler(callback=self.callback_manager,
                                                  unique_id=unique_id,
                                                  node_id=self.id,
                                                  output=self._output_user,
                                                  output_key=output_key,
                                                  cancel_llm_end=True)

            result = retriever._call({'query': question}, run_manager=llm_callback)

            if not self._show_source:
                # 不溯源
                result['source_documents'] = []

            if self._output_user:
                self.graph_state.save_context(content=result['result'], msg_sender='AI')
                if llm_callback.output_len == 0:
                    self.callback_manager.on_output_msg(
                        OutputMsgData(node_id=self.id,
                                      msg=result['result'],
                                      unique_id=unique_id,
                                      output_key=output_key,
                                      source_documents=result.get('source_documents', [])))
                else:
                    # 说明有流式输出，则触发流式结束事件, 因为需要source_document所以在此执行流式结束事件
                    self.callback_manager.on_stream_over(StreamMsgOverData(
                        node_id=self.id,
                        msg=result['result'],
                        reasoning_content=llm_callback.reasoning_content,
                        unique_id=unique_id,
                        source_documents=result.get('source_documents', []),
                        output_key=output_key,
                    ))
            ret[output_key] = result[retriever.output_key]
            self._log_reasoning_content[output_key] = llm_callback.reasoning_content
            self._log_source_documents[output_key] = result.get('source_documents', [])
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        index = 0
        user_question_list = self.init_user_question()
        # 判断检索结果是否超出一定的长度, 原因是ws发送的消息超过一定的长度会报错
        source_documents = [[d.page_content for d in one] for one in self._log_source_documents.values()]
        tmp_retrieved_type = 'variable'
        tmp_retrieved_result = json.dumps(source_documents, indent=2, ensure_ascii=False)
        if len(tmp_retrieved_result.encode('utf-8')) >= 50 * 1024:  # 大于50kb的日志数据存文件
            tmp_retrieved_type = 'file'
            tmp_object_name = f'/workflow/source_document/{time.time()}.txt'
            self._minio_client.upload_tmp(tmp_object_name, tmp_retrieved_result.encode('utf-8'))
            share_url = self._minio_client.get_share_link(tmp_object_name, self._minio_client.tmp_bucket)
            tmp_retrieved_result = self._minio_client.clear_minio_share_host(share_url)

        for key, val in result.items():
            if tmp_retrieved_type != 'file':
                tmp_retrieved_result = json.dumps([one.page_content for one in self._log_source_documents[key]],
                                                  indent=2, ensure_ascii=False)
            one_ret = [
                {'key': f'{self.id}.user_question', 'value': user_question_list[index], "type": "variable"},
                {'key': f'{self.id}.retrieved_result', 'value': tmp_retrieved_result, "type": tmp_retrieved_type},
                {'key': 'system_prompt', 'value': self._log_system_prompt[0], "type": "params"},
                {'key': 'user_prompt', 'value': self._log_user_prompt[0], "type": "params"},
            ]
            if self._log_reasoning_content[key]:
                one_ret.append({'key': '思考内容', 'value': self._log_reasoning_content[key], "type": "params"})
            one_ret.append({'key': f'{self.id}.{key}', 'value': val, 'type': 'variable'})

            index += 1
            ret.append(one_ret)
        return ret

    def init_user_question(self) -> List[str]:
        ret = []
        for one in self.node_params['user_question']:
            ret.append(self.get_other_node_variable(one))
        return ret

    def init_qa_prompt(self):
        variable_map = {}
        for one in self._user_variables:
            if one == f'{self.id}.user_question':
                variable_map[one] = '$$question$$'
            elif one == f'{self.id}.retrieved_result':
                variable_map[one] = '$$context$$'
            else:
                variable_map[one] = self.get_other_node_variable(one)
        if variable_map.get(f'{self.id}.retrieved_result') is None:
            raise IgnoreException('用户提示词必须包含 retrieved_result 变量')
        user_prompt = self._user_prompt.format(variable_map)
        log_user_prompt = user_prompt.replace('$$question$$', '{user_question}').replace('$$context$$',
                                                                                         '{retrieved_result}')
        user_prompt = (user_prompt.replace('{', '{{').replace('}', '}}')
                       .replace('$$question$$', '{question}').replace('$$context$$', '{context}'))
        self._log_user_prompt.append(log_user_prompt)

        variable_map = {}
        for one in self._system_variables:
            variable_map[one] = self.get_other_node_variable(one)
        system_prompt = self._system_prompt.format(variable_map)
        system_prompt.replace('{', '{{').replace('}', '}}')
        self._log_system_prompt.append(system_prompt)

        messages_general = [
            SystemMessagePromptTemplate.from_template(system_prompt),
            HumanMessagePromptTemplate.from_template(user_prompt),
        ]
        self._qa_prompt = ChatPromptTemplate.from_messages(messages_general)

    def init_milvus(self):
        if self._knowledge_type == 'knowledge':
            node_type = 'MilvusWithPermissionCheck'
            params = {
                'user_name': self._user_info.user_name,
                'collection_name': [{
                    'key': one
                } for one in self._knowledge_value],  # 知识库id列表
                '_is_check_auth': self._knowledge_auth
            }
        else:
            embeddings = LLMService.get_knowledge_default_embedding()
            if not embeddings:
                raise Exception('没有配置默认的embedding模型')
            file_ids = ["0"]
            for one in self._knowledge_value:
#------
                file_metadata = self.get_other_node_variable(one)
                if not file_metadata:
                    # 未找到对应的临时文件数据, 用户未上传文件
                    continue
                file_ids.append(file_metadata[0]['file_id'])
                # DONE merge_check 1
# =======
#                 file_metadata = self.graph_state.get_variable_by_str(f'{one}')
#                 if not file_metadata:
#                     continue
#                 file_ids.append(file_metadata['file_id'])
# >>>>>>> feat/zyrs_0527
            self._sort_chunks = len(file_ids) == 1
            node_type = 'Milvus'
            params = {
                'collection_name': self.get_milvus_collection_name(getattr(embeddings, 'model_id')),
                'partition_key': self.workflow_id,
                'embedding': embeddings,
                'metadata_expr': f'file_id in {file_ids}'
            }

        class_obj = import_vectorstore(node_type)
        self._milvus = instantiate_vectorstore(node_type, class_object=class_obj, params=params)

    def init_es(self):
        if self._knowledge_type == 'knowledge':
            node_type = 'ElasticsearchWithPermissionCheck'
            params = {
                'user_name': self._user_info.user_name,
                'index_name': [{
                    'key': one
                } for one in self._knowledge_value],  # 知识库id列表
                '_is_check_auth': self._knowledge_auth
            }
        else:
            file_ids = ["0"]
            for one in self._knowledge_value:
# ------
                file_metadata = self.get_other_node_variable(one)
                if not file_metadata:
                    continue
                file_ids.append(file_metadata[0]['file_id'])
                # DONE merge_check 1
# =======
#                 file_metadata = self.graph_state.get_variable_by_str(f'{one}')
#                 if not file_metadata:
#                     continue
#                 file_ids.append(file_metadata['file_id'])
# >>>>>>> feat/zyrs_0527
            node_type = 'ElasticKeywordsSearch'
            params = {
                'index_name': self.tmp_collection_name,
                'post_filter': {
                    'terms': {
                        'metadata.file_id': file_ids
                    }
                }
            }
        class_obj = import_vectorstore(node_type)
        self._es = instantiate_vectorstore(node_type, class_object=class_obj, params=params)
