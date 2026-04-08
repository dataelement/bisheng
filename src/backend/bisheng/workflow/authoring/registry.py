import copy
from typing import Optional

from bisheng.workflow.authoring.contract import (
    NodeTemplateDescriptor,
    NodeTypeDescriptor,
    WorkflowParamGroupDescriptor,
    WorkflowParamMetadata,
    WorkflowTabDescriptor,
    WorkflowTabOption,
)


_NODE_DISPLAY_NAMES = {
    'start': 'Start',
    'input': 'Input',
    'output': 'Output',
    'llm': 'LLM',
    'agent': 'Agent',
    'qa_retriever': 'QA Retriever',
    'rag': 'RAG',
    'knowledge_retriever': 'Knowledge Retriever',
    'report': 'Report',
    'code': 'Code',
    'condition': 'Condition',
    'end': 'End',
    'tool': 'Tool',
}

_NODE_DESCRIPTIONS = {
    'tool': 'Dynamic tool node. Param schema depends on the selected tool.',
}

_WORKFLOW_NODE_TEMPLATES = [
    {
        'id': 'start_xxx',
        'name': '',
        'description': '',
        'type': 'start',
        'v': '3',
        'group_params': [
            {
                'name': '开场引导',
                'params': [
                    {
                        'key': 'guide_word',
                        'label': 'Guide Word',
                        'value': '',
                        'type': 'textarea',
                        'placeholder': '',
                    },
                    {
                        'key': 'guide_question',
                        'label': 'Guide Questions',
                        'value': [],
                        'type': 'input_list',
                        'placeholder': '',
                        'help': '',
                    },
                ],
            },
            {
                'name': '全局变量',
                'params': [
                    {
                        'key': 'user_info',
                        'global': 'key',
                        'label': 'User Info',
                        'type': 'var',
                        'value': '',
                    },
                    {
                        'key': 'current_time',
                        'global': 'key',
                        'label': 'Current Time',
                        'type': 'var',
                        'value': '',
                    },
                    {
                        'key': 'chat_history',
                        'global': 'key',
                        'label': 'Chat History',
                        'type': 'chat_history_num',
                        'value': 10,
                    },
                    {
                        'key': 'preset_question',
                        'label': 'Preset Questions',
                        'global': 'item:input_list',
                        'type': 'input_list',
                        'value': [],
                        'placeholder': '',
                        'help': '',
                    },
                    {
                        'key': 'custom_variables',
                        'label': 'Custom Variables',
                        'global': 'item:input_list',
                        'type': 'global_var',
                        'value': [],
                        'help': '',
                    },
                ],
            },
        ],
    },
    {
        'id': 'input_xxx',
        'name': '',
        'description': '',
        'type': 'input',
        'v': '3',
        'tab': {
            'value': 'dialog_input',
            'options': [
                {
                    'label': 'Dialog Input',
                    'key': 'dialog_input',
                    'help': '',
                },
                {
                    'label': 'Form Input',
                    'key': 'form_input',
                    'help': '',
                },
            ],
        },
        'group_params': [
            {
                'name': '接收文本',
                'params': [
                    {
                        'key': 'user_input',
                        'global': 'key',
                        'label': 'User Input',
                        'type': 'var',
                        'tab': 'dialog_input',
                    },
                ],
            },
            {
                'name': '',
                'groupKey': 'inputfile',
                'params': [
                    {
                        'groupTitle': True,
                        'key': 'user_input_file',
                        'tab': 'dialog_input',
                        'value': True,
                    },
                    {
                        'key': 'file_parse_mode',
                        'type': 'select_parsemode',
                        'tab': 'dialog_input',
                        'value': 'extract_text',
                    },
                    {
                        'key': 'dialog_files_content',
                        'global': 'key',
                        'label': 'Dialog Files Content',
                        'type': 'var',
                        'tab': 'dialog_input',
                    },
                    {
                        'key': 'dialog_files_content_size',
                        'label': 'Dialog Files Content Size',
                        'type': 'char_number',
                        'min': 0,
                        'value': 15000,
                        'tab': 'dialog_input',
                    },
                    {
                        'key': 'dialog_file_accept',
                        'label': 'Dialog File Accept',
                        'type': 'select_fileaccept',
                        'value': 'all',
                        'tab': 'dialog_input',
                    },
                    {
                        'key': 'dialog_image_files',
                        'global': 'key',
                        'label': 'Dialog Image Files',
                        'type': 'var',
                        'tab': 'dialog_input',
                        'help': '',
                    },
                    {
                        'key': 'dialog_file_paths',
                        'global': 'key',
                        'label': 'Dialog File Paths',
                        'type': 'var',
                        'tab': 'dialog_input',
                        'help': '',
                    },
                ],
            },
            {
                'name': '',
                'groupKey': 'custom',
                'params': [
                    {
                        'groupTitle': True,
                        'key': 'recommended_questions_flag',
                        'label': 'Recommended Questions Flag',
                        'hidden': True,
                        'tab': 'dialog_input',
                        'help': '',
                        'value': False,
                    },
                    {
                        'key': 'recommended_llm',
                        'label': 'Recommended LLM',
                        'type': 'bisheng_model',
                        'tab': 'dialog_input',
                        'value': '',
                        'placeholder': '',
                        'required': True,
                    },
                    {
                        'key': 'recommended_system_prompt',
                        'label': 'Recommended System Prompt',
                        'tab': 'dialog_input',
                        'type': 'var_textarea',
                        'value': '',
                        'required': True,
                    },
                    {
                        'key': 'recommended_history_num',
                        'label': 'Recommended History Num',
                        'type': 'slide',
                        'tab': 'dialog_input',
                        'help': '',
                        'scope': [1, 10],
                        'step': 1,
                        'value': 2,
                    },
                ],
            },
            {
                'name': '',
                'params': [
                    {
                        'key': 'form_input',
                        'global': 'item:form_input',
                        'label': 'Form Input',
                        'type': 'form',
                        'tab': 'form_input',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'output_xxx',
        'name': '',
        'description': '',
        'type': 'output',
        'v': '2',
        'group_params': [
            {
                'params': [
                    {
                        'key': 'message',
                        'label': 'Message',
                        'global': 'key',
                        'type': 'var_textarea_file',
                        'required': True,
                        'placeholder': '',
                        'value': {
                            'msg': '',
                            'files': [],
                        },
                    },
                    {
                        'key': 'output_result',
                        'label': 'Output Result',
                        'global': 'value.type=input',
                        'type': 'output_form',
                        'required': True,
                        'value': {
                            'type': '',
                            'value': '',
                        },
                        'options': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'llm_xxx',
        'name': '',
        'description': '',
        'type': 'llm',
        'v': '2',
        'tab': {
            'value': 'single',
            'options': [
                {'label': 'Single', 'key': 'single'},
                {'label': 'Batch', 'key': 'batch'},
            ],
        },
        'group_params': [
            {
                'params': [
                    {
                        'key': 'batch_variable',
                        'label': 'Batch Variable',
                        'global': 'self',
                        'type': 'user_question',
                        'test': 'var',
                        'value': [],
                        'required': True,
                        'linkage': 'output',
                        'placeholder': '',
                        'help': '',
                        'tab': 'batch',
                    },
                ],
            },
            {
                'name': '模型设置',
                'params': [
                    {
                        'key': 'model_id',
                        'label': 'Model ID',
                        'type': 'bisheng_model',
                        'value': '',
                        'required': True,
                        'placeholder': '',
                    },
                    {
                        'key': 'temperature',
                        'label': 'Temperature',
                        'type': 'slide',
                        'scope': [0, 2],
                        'step': 0.1,
                        'value': 0.7,
                    },
                ],
            },
            {
                'name': '提示词',
                'params': [
                    {
                        'key': 'system_prompt',
                        'label': 'System Prompt',
                        'type': 'var_textarea',
                        'test': 'var',
                        'value': '',
                    },
                    {
                        'key': 'user_prompt',
                        'label': 'User Prompt',
                        'type': 'var_textarea',
                        'test': 'var',
                        'value': '',
                        'required': True,
                    },
                    {
                        'key': 'image_prompt',
                        'label': 'Image Prompt',
                        'type': 'image_prompt',
                        'value': [],
                        'help': '',
                    },
                ],
            },
            {
                'name': '输出',
                'params': [
                    {
                        'key': 'output_user',
                        'label': 'Output To User',
                        'type': 'switch',
                        'help': '',
                        'value': True,
                    },
                    {
                        'key': 'output',
                        'global': 'code:value.map(el => ({ label: el.label, value: el.key }))',
                        'label': 'Output Variable',
                        'help': '',
                        'type': 'var',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'agent_xxx',
        'name': '',
        'description': '',
        'type': 'agent',
        'v': '2',
        'tab': {
            'value': 'single',
            'options': [
                {'label': 'Single', 'key': 'single'},
                {'label': 'Batch', 'key': 'batch'},
            ],
        },
        'group_params': [
            {
                'params': [
                    {
                        'key': 'batch_variable',
                        'label': 'Batch Variable',
                        'required': True,
                        'type': 'user_question',
                        'test': 'var',
                        'global': 'self',
                        'value': [],
                        'linkage': 'output',
                        'placeholder': '',
                        'tab': 'batch',
                        'help': '',
                    },
                ],
            },
            {
                'name': '模型设置',
                'params': [
                    {
                        'key': 'model_id',
                        'label': 'Model ID',
                        'type': 'agent_model',
                        'required': True,
                        'value': '',
                        'placeholder': '',
                    },
                    {
                        'key': 'temperature',
                        'label': 'Temperature',
                        'type': 'slide',
                        'scope': [0, 2],
                        'step': 0.1,
                        'value': 0.7,
                    },
                ],
            },
            {
                'name': '提示词',
                'params': [
                    {
                        'key': 'system_prompt',
                        'label': 'System Prompt',
                        'type': 'var_textarea',
                        'test': 'var',
                        'value': '',
                        'placeholder': '',
                        'required': True,
                    },
                    {
                        'key': 'user_prompt',
                        'label': 'User Prompt',
                        'type': 'var_textarea',
                        'test': 'var',
                        'value': '',
                        'placeholder': '',
                        'required': True,
                    },
                    {
                        'key': 'chat_history_flag',
                        'label': 'Chat History',
                        'type': 'slide_switch',
                        'scope': [0, 100],
                        'step': 1,
                        'value': {
                            'flag': True,
                            'value': 50,
                        },
                        'help': '',
                    },
                    {
                        'key': 'image_prompt',
                        'label': 'Image Prompt',
                        'type': 'image_prompt',
                        'value': '',
                        'help': '',
                    },
                ],
            },
            {
                'name': '知识库',
                'params': [
                    {
                        'key': 'knowledge_id',
                        'label': 'Knowledge ID',
                        'type': 'knowledge_select_multi',
                        'placeholder': '',
                        'value': {
                            'type': 'knowledge',
                            'value': [],
                        },
                    },
                ],
            },
            {
                'name': '数据库',
                'params': [
                    {
                        'key': 'sql_agent',
                        'type': 'sql_config',
                        'value': {
                            'open': False,
                            'db_address': '',
                            'db_name': '',
                            'db_username': '',
                            'db_password': '',
                        },
                    },
                ],
            },
            {
                'name': '工具',
                'params': [
                    {
                        'key': 'tool_list',
                        'label': 'Tool List',
                        'type': 'add_tool',
                        'value': [],
                    },
                ],
            },
            {
                'name': '输出',
                'params': [
                    {
                        'key': 'output_user',
                        'label': 'Output To User',
                        'type': 'switch',
                        'help': '',
                        'value': True,
                    },
                    {
                        'key': 'output',
                        'global': 'code:value.map(el => ({ label: el.label, value: el.key }))',
                        'label': 'Output Variable',
                        'type': 'var',
                        'help': '',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'qa_retriever_xxx',
        'name': '',
        'description': '',
        'type': 'qa_retriever',
        'v': '1',
        'group_params': [
            {
                'name': '检索设置',
                'params': [
                    {
                        'key': 'user_question',
                        'label': 'User Question',
                        'type': 'var_select',
                        'test': 'var',
                        'value': '',
                        'required': True,
                        'placeholder': '',
                    },
                    {
                        'key': 'qa_knowledge_id',
                        'label': 'QA Knowledge ID',
                        'type': 'qa_select_multi',
                        'value': [],
                        'required': True,
                        'placeholder': '',
                    },
                    {
                        'key': 'score',
                        'label': 'Score',
                        'type': 'slide',
                        'value': 0.8,
                        'scope': [0.01, 0.99],
                        'step': 0.01,
                        'help': '',
                    },
                ],
            },
            {
                'name': '输出',
                'params': [
                    {
                        'key': 'retrieved_result',
                        'label': 'Retrieved Result',
                        'type': 'var',
                        'global': 'key',
                        'value': '',
                    },
                ],
            },
        ],
    },
    {
        'id': 'rag_xxx',
        'name': '',
        'description': '',
        'type': 'rag',
        'v': '2',
        'group_params': [
            {
                'name': '知识库检索设置',
                'params': [
                    {
                        'key': 'user_question',
                        'label': 'User Question',
                        'global': 'self=user_prompt',
                        'type': 'user_question',
                        'test': 'var',
                        'help': '',
                        'linkage': 'output_user_input',
                        'value': [],
                        'placeholder': '',
                        'required': True,
                    },
                    {
                        'key': 'knowledge',
                        'label': 'Knowledge',
                        'type': 'knowledge_select_multi',
                        'placeholder': '',
                        'value': {
                            'type': 'knowledge',
                            'value': [],
                        },
                        'required': True,
                    },
                    {
                        'key': 'metadata_filter',
                        'label': 'Metadata Filter',
                        'type': 'metadata_filter',
                        'value': {},
                    },
                    {
                        'key': 'advanced_retrieval_switch',
                        'label': 'Advanced Retrieval Switch',
                        'type': 'search_switch',
                        'value': {},
                    },
                    {
                        'key': 'retrieved_result',
                        'label': 'Retrieved Result',
                        'type': 'var',
                        'global': 'self=user_prompt',
                    },
                ],
            },
            {
                'name': 'AI回复生成设置',
                'params': [
                    {
                        'key': 'system_prompt',
                        'label': 'System Prompt',
                        'type': 'var_textarea',
                        'value': '',
                        'required': True,
                    },
                    {
                        'key': 'user_prompt',
                        'label': 'User Prompt',
                        'type': 'var_textarea',
                        'value': '',
                        'test': 'var',
                        'required': True,
                    },
                    {
                        'key': 'model_id',
                        'label': 'Model ID',
                        'type': 'bisheng_model',
                        'value': '',
                        'required': True,
                        'placeholder': '',
                    },
                    {
                        'key': 'temperature',
                        'label': 'Temperature',
                        'type': 'slide',
                        'scope': [0, 2],
                        'step': 0.1,
                        'value': 0.7,
                    },
                ],
            },
            {
                'name': '输出',
                'params': [
                    {
                        'key': 'output_user',
                        'label': 'Output To User',
                        'type': 'switch',
                        'value': True,
                        'help': '',
                    },
                    {
                        'key': 'output_user_input',
                        'label': 'Output User Input',
                        'type': 'var',
                        'help': '',
                        'global': 'code:value.map(el => ({ label: el.label, value: el.key }))',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'knowledge_retriever_xxx',
        'name': '',
        'description': '',
        'type': 'knowledge_retriever',
        'v': '1',
        'group_params': [
            {
                'name': '知识库检索设置',
                'params': [
                    {
                        'key': 'user_question',
                        'label': 'User Question',
                        'global': 'self=user_prompt',
                        'type': 'user_question',
                        'test': 'var',
                        'help': '',
                        'linkage': 'retrieved_result',
                        'value': [],
                        'placeholder': '',
                        'required': True,
                    },
                    {
                        'key': 'knowledge',
                        'label': 'Knowledge',
                        'type': 'knowledge_select_multi',
                        'placeholder': '',
                        'value': {
                            'type': 'knowledge',
                            'value': [],
                        },
                        'required': True,
                    },
                    {
                        'key': 'metadata_filter',
                        'label': 'Metadata Filter',
                        'type': 'metadata_filter',
                        'value': {},
                    },
                    {
                        'key': 'advanced_retrieval_switch',
                        'label': 'Advanced Retrieval Switch',
                        'type': 'search_switch',
                        'value': {},
                    },
                ],
            },
            {
                'name': '输出',
                'params': [
                    {
                        'key': 'retrieved_result',
                        'label': 'Retrieved Result',
                        'type': 'var',
                        'global': 'code:value.map(el => ({ label: el.label, value: el.key }))',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'report_xxx',
        'name': '',
        'description': '',
        'type': 'report',
        'v': '1',
        'group_params': [
            {
                'params': [
                    {
                        'key': 'report_info',
                        'label': 'Report Info',
                        'placeholder': '',
                        'required': True,
                        'type': 'report',
                        'value': {},
                    },
                ],
            },
        ],
    },
    {
        'id': 'code_xxx',
        'name': '',
        'description': '',
        'type': 'code',
        'v': '1',
        'group_params': [
            {
                'name': '入参',
                'params': [
                    {
                        'key': 'code_input',
                        'type': 'code_input',
                        'test': 'input',
                        'required': True,
                        'value': [
                            {'key': 'arg1', 'type': 'input', 'label': '', 'value': ''},
                            {'key': 'arg2', 'type': 'input', 'label': '', 'value': ''},
                        ],
                    },
                ],
            },
            {
                'name': '执行代码',
                'params': [
                    {
                        'key': 'code',
                        'type': 'code',
                        'required': True,
                        'value': "def main(arg1: str, arg2: str) -> dict: \n    return {'result1': arg1, 'result2': arg2}",
                    },
                ],
            },
            {
                'name': '出参',
                'params': [
                    {
                        'key': 'code_output',
                        'type': 'code_output',
                        'global': 'code:value.map(el => ({ label: el.key, value: el.key }))',
                        'required': True,
                        'value': [
                            {'key': 'result1', 'type': 'str'},
                            {'key': 'result2', 'type': 'str'},
                        ],
                    },
                ],
            },
        ],
    },
    {
        'id': 'condition_xxx',
        'name': '',
        'description': '',
        'type': 'condition',
        'v': '1',
        'group_params': [
            {
                'params': [
                    {
                        'key': 'condition',
                        'label': '',
                        'type': 'condition',
                        'value': [],
                    },
                ],
            },
        ],
    },
    {
        'id': 'end_xxx',
        'name': '',
        'description': '',
        'type': 'end',
        'v': '1',
        'group_params': [],
    },
    {
        'id': 'tool_xxx',
        'name': '',
        'description': '',
        'type': 'tool',
        'v': '1',
        'group_params': [],
        'dynamic_template': True,
    },
]

_TEMPLATE_MAP = {item['type']: item for item in _WORKFLOW_NODE_TEMPLATES}


def _normalize_tab(tab: Optional[dict]) -> Optional[WorkflowTabDescriptor]:
    if not isinstance(tab, dict):
        return None
    options = []
    for option in tab.get('options', []) or []:
        if not isinstance(option, dict):
            continue
        options.append(
            WorkflowTabOption(
                key=str(option.get('key', '')),
                label=str(option.get('label', '')),
                help=option.get('help'),
            )
        )
    return WorkflowTabDescriptor(value=tab.get('value'), options=options)


def normalize_tab_descriptor(tab: Optional[dict]) -> Optional[WorkflowTabDescriptor]:
    return _normalize_tab(tab)


def _normalize_param(field: dict, group_name: str) -> WorkflowParamMetadata:
    key = field.get('key', '')
    return WorkflowParamMetadata(
        display_name=field.get('display_name') or field.get('label') or field.get('name') or key,
        group_name=group_name,
        type=field.get('type'),
        required=field.get('required', False),
        show=field.get('show', True) and not field.get('hidden', False),
        options=field.get('options'),
        scope=field.get('scope'),
        placeholder=field.get('placeholder'),
        refresh=field.get('refresh', False),
        value=field.get('value'),
    )


def _iter_group_fields(node_template: dict):
    for group in node_template.get('group_params', []) or []:
        if not isinstance(group, dict):
            continue
        group_name = group.get('name', '')
        group_key = group.get('groupKey')
        param_keys = []
        fields = {}
        for field in group.get('params', []) or []:
            if not isinstance(field, dict):
                continue
            key = field.get('key')
            if not key or field.get('groupTitle') is True:
                continue
            metadata = _normalize_param(field, group_name)
            if not metadata.show:
                continue
            param_keys.append(key)
            fields[key] = metadata
        yield WorkflowParamGroupDescriptor(name=group_name, group_key=group_key, param_keys=param_keys), fields


def _display_name_for(node_type: str) -> str:
    return _NODE_DISPLAY_NAMES.get(node_type, node_type.replace('_', ' ').title())


def _description_for(node_type: str) -> str:
    return _NODE_DESCRIPTIONS.get(node_type, '')


def get_node_template_descriptor(node_type: str) -> Optional[NodeTemplateDescriptor]:
    template = _TEMPLATE_MAP.get(node_type)
    if template is None:
        return None
    groups = []
    params = {}
    for group, fields in _iter_group_fields(copy.deepcopy(template)):
        groups.append(group)
        params.update(fields)
    return NodeTemplateDescriptor(
        node_type=node_type,
        display_name=_display_name_for(node_type),
        description=_description_for(node_type),
        tab=_normalize_tab(template.get('tab')),
        groups=groups,
        params=params,
        dynamic_template=template.get('dynamic_template', False),
    )


def list_node_type_descriptors() -> list[NodeTypeDescriptor]:
    descriptors = []
    for node_type in _TEMPLATE_MAP:
        template = get_node_template_descriptor(node_type)
        if template is None:
            continue
        descriptors.append(
            NodeTypeDescriptor(
                type=node_type,
                display_name=template.display_name,
                description=template.description,
                param_keys=list(template.params.keys()),
                dynamic_template=template.dynamic_template,
            )
        )
    return descriptors


def get_node_template_payload(node_type: str) -> Optional[dict]:
    template = _TEMPLATE_MAP.get(node_type)
    if template is None:
        return None
    return copy.deepcopy(template)


def create_graph_node_payload(node_type: str,
                              *,
                              node_id: str,
                              name: str = '',
                              position_x: float = 0,
                              position_y: float = 0) -> Optional[dict]:
    template = get_node_template_payload(node_type)
    if template is None:
        return None

    template['id'] = node_id
    template['name'] = name or template.get('name') or _display_name_for(node_type)
    template.setdefault('description', '')
    template.setdefault('v', '1')

    return {
        'id': node_id,
        'type': 'noteNode' if node_type == 'note' else 'flowNode',
        'position': {
            'x': position_x,
            'y': position_y,
        },
        'data': template,
    }
