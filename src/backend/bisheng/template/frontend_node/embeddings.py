from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.template.base import Template


class EmbeddingFrontendNode(FrontendNode):

    @staticmethod
    def format_jina_fields(field: TemplateField):
        if 'jina' in field.name:
            field.show = True
            field.advanced = False

        if 'auth' in field.name or 'token' in field.name:
            field.password = True
            field.show = True
            field.advanced = False

        if field.name == 'jina_api_url':
            field.show = True
            field.advanced = True
            field.display_name = 'Jina API URL'
            field.password = False

    @staticmethod
    def format_openai_fields(field: TemplateField):
        if 'openai' in field.name:
            field.show = True
            field.advanced = True
            split_name = field.name.split('_')
            title_name = ' '.join([s.capitalize() for s in split_name])
            field.display_name = title_name.replace('Openai', 'OpenAI').replace('Api', 'API')

        if 'api_key' in field.name:
            field.password = True
            field.show = True
            field.advanced = False

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        field.advanced = not field.required
        field.show = True
        if field.name == 'headers':
            field.show = False
            field.value = ''

        if field.name == 'host_base_url':
            field.show = True
            field.advanced = False

        if field.name == 'model':
            field.show = True
            field.advanced = False
        if name == 'BishengEmbedding':
            if field.name == 'model_id':
                field.show = True
                field.display_name = 'Model Name'
                field.field_type = 'bisheng_embedding'
                field.advanced = False
            elif field.name in ['model', 'llm_node_type']:
                field.show = False

        # Format Jina fields
        EmbeddingFrontendNode.format_jina_fields(field)
        EmbeddingFrontendNode.format_openai_fields(field)


class OpenAIProxyEmbedding(FrontendNode):
    name: str = 'OpenAIProxyEmbedding'
    description: str = """ 使用自建的embedding服务使用openai进行embed """
    base_classes: list[str] = ['Embeddings']
    template: Template = Template(type_name='proxy_embedding',
                                  fields=[
                                      TemplateField(
                                          field_type='str',
                                          required=False,
                                          placeholder='http://43.133.35.137:8080',
                                          is_list=False,
                                          show=True,
                                          multiline=False,
                                          value='',
                                          name='proxy_url',
                                      ),
                                  ])

    def to_dict(self):
        return super().to_dict()
