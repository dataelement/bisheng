from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from sqlmodel import true


class WrappersFrontendNode(FrontendNode):
    name: str = 'WrappersFrontendNode'

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        if name == 'DallEAPIWrapper':
            if field.name == 'model_name':
                field.show = True
                field.name = 'model'
                field.value = 'dall-e-3'
            elif field.name == 'openai_api_key':
                field.show = true
                field.name = 'api_key'
                field.display_name = 'openai_api_key'
                field.password = true
            elif field.name == 'openai_api_base':
                field.show = True
                field.name = 'api_base'
                field.display_name = 'openai_api_base'
            elif field.name == 'openai_proxy':
                field.show = True
            elif field.name == 'n':
                field.show = True
                field.field_type = 'int'
                field.value = 1
                field.info = '生成图片数量，使用dalle3 只能填1'
                field.advanced = True
            elif field.name == 'size':
                field.show = True
                field.is_list = True
                field.field_type = 'str'
                field.options = ['256x256', '512x512', '1024x1024', '1024x1792', '1792x1024']
                field.value = field.options[2]
                field.advanced = True
            elif field.name == 'quality':
                field.show = True
                field.field_type = 'str'
                field.advanced = True
                field.value = 'standard'
            elif field.name == 'request_timeout':
                field.show = True
                field.name = 'timeout'
                field.value = 30
