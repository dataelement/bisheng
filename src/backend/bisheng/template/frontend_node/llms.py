import json
from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.frontend_node.constants import (CTRANSFORMERS_DEFAULT_CONFIG,
                                                      OPENAI_API_BASE_INFO)


class LLMFrontendNode(FrontendNode):

    def add_extra_fields(self) -> None:
        self.template.add_field(
            TemplateField(field_type='bool',
                          required=False,
                          show=True,
                          advanced=True,
                          name='cache',
                          value=True))
        if 'VertexAI' in self.template.type_name:
            # Add credentials field which should of type file.
            self.template.add_field(
                TemplateField(
                    field_type='file',
                    required=False,
                    show=True,
                    name='credentials',
                    value='',
                    suffixes=['.json'],
                    fileTypes=['json'],
                ))

    @staticmethod
    def format_vertex_field(field: TemplateField, name: str):
        if 'VertexAI' in name:
            advanced_fields = [
                'tuned_model_name',
                'verbose',
                'top_p',
                'top_k',
                'max_output_tokens',
            ]
            if field.name in advanced_fields:
                field.advanced = True
            show_fields = [
                'tuned_model_name',
                'verbose',
                'project',
                'location',
                'credentials',
                'max_output_tokens',
                'model_name',
                'temperature',
                'top_p',
                'top_k',
            ]

            if field.name in show_fields:
                field.show = True

    @staticmethod
    def format_openai_field(field: TemplateField):
        if 'openai' in field.name.lower():
            field.display_name = (field.name.title().replace('Openai',
                                                             'OpenAI').replace('_', ' ')).replace(
                                                                 'Api', 'API')

        if 'key' not in field.name.lower() and 'token' not in field.name.lower():
            field.password = False

        if field.name == 'openai_api_base':
            field.info = OPENAI_API_BASE_INFO

        if field.name == 'openai_proxy':
            field.show = True

    def add_extra_base_classes(self) -> None:
        if 'BaseLLM' not in self.base_classes:
            self.base_classes.append('BaseLLM')

    @staticmethod
    def format_azure_field(field: TemplateField):
        if field.name == 'model_name':
            field.show = False  # Azure uses deployment_name instead of model_name.
        elif field.name == 'openai_api_base':
            # openai < 1.0.0
            field.show = False
        elif field.name == 'openai_api_type':
            field.show = False
        elif field.name == 'openai_api_version':
            field.show = True
            field.password = False
        elif field.name == 'azure_endpoint':
            field.show = True
        elif field.name == 'openai_api_key':
            field.show = True
            field.advanced = False
        elif field.name == 'deployment_name':
            field.show = True
            field.value = 'chatgpt'
        elif field.name == 'azure_ad_token_provider':
            field.show = False
        elif field.name == 'openai_proxy':
            field.advanced = True

    @staticmethod
    def format_contribute_field(field: TemplateField):
        advanced_fields = [
            'top_p',
            'top_k',
            'max_tokens',
        ]
        if field.name in advanced_fields:
            field.advanced = True
        if field.name == 'headers':
            field.show = True
            field.advanced = True
            field.value = ''

        show_fields = [
            'model_name',
            'temperature',
            'top_p',
            'top_k',
            'max_tokens',
        ]
        if field.name in show_fields:
            field.show = True

        if 'api' in field.name.lower() or 'id' in field.name.lower() or 'key' in field.name.lower(
        ) or 'base' in field.name.lower():
            field.show = True
            field.advanced = False
            field.field_type = 'str'

    @staticmethod
    def format_llama_field(field: TemplateField):
        field.show = True
        field.advanced = not field.required

    @staticmethod
    def format_ctransformers_field(field: TemplateField):
        if field.name == 'config':
            field.show = True
            field.advanced = True
            field.value = json.dumps(CTRANSFORMERS_DEFAULT_CONFIG, indent=2)

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        display_names_dict = {
            'huggingfacehub_api_token': 'HuggingFace Hub API Token',
        }
        FrontendNode.format_field(field, name)
        LLMFrontendNode.format_openai_field(field)
        LLMFrontendNode.format_ctransformers_field(field)
        LLMFrontendNode.format_contribute_field(field)

        if name and 'llama' in name.lower() and 'host' not in name.lower():
            LLMFrontendNode.format_llama_field(field)
        if name and 'vertex' in name.lower():
            LLMFrontendNode.format_vertex_field(field, name)
        SHOW_FIELDS = ['repo_id']
        HIDDEN_FIELDS = ['custom_get_token_ids']
        if field.name in SHOW_FIELDS:
            field.show = True
        if field.name in HIDDEN_FIELDS:
            field.show = False

        if 'api' in field.name and ('key' in field.name or
                                    ('token' in field.name and 'tokens' not in field.name)):
            field.password = True
            field.show = True
            # Required should be False to support
            # loading the API key from environment variables
            field.required = False
            field.advanced = False

        if field.name == 'task':
            field.required = True
            field.show = True
            field.is_list = True
            field.options = ['text-generation', 'text2text-generation', 'summarization']
            field.value = field.options[0]
            field.advanced = True

        if display_name := display_names_dict.get(field.name):
            field.display_name = display_name
        if field.name == 'model_kwargs':
            field.field_type = 'code'
            field.advanced = True
            field.show = True
        elif field.name in [
                'model_name',
                'temperature',
                'model_file',
                'model_type',
                'deployment_name',
                'credentials',
                'openai_proxy',
        ]:
            field.advanced = False
            field.show = True
        if field.name == 'credentials':
            field.field_type = 'file'
        if name == 'VertexAI' and field.name not in [
                'callbacks',
                'client',
                'stop',
                'tags',
                'cache',
        ]:
            field.show = True
        if field.name in ['cache']:
            field.show = True

        if name and 'azure' in name.lower():
            LLMFrontendNode.format_azure_field(field)

        # 把组件的流式配置放出来，取消全局的流式控制
        if field.name == 'streaming':
            field.show = True

        if name == 'BishengLLM':
            if field.name in ["temperature", "top_p", "cache"]:
                field.show = True
            if field.name == 'model_id':
                field.field_type = "bisheng_model"
                field.display_name = "Model Name"
            elif field.name == 'model_name':
                field.show = False
