from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode

STRATEGY_TYPES = ['keyword_front', 'vector_front', 'mix']


class RetrieverFrontendNode(FrontendNode):

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        # Define common field attributes
        field.show = True
        if field.name == 'parser_key':
            field.display_name = 'Parser Key'
            field.password = False
            field.advanced = True
            field.show = False
        if field.name == 'combine_strategy' and name == 'MixEsVectorRetriever':
            field.field_type = 'str'
            field.required = True
            field.is_list = True
            field.show = True
            field.multiline = False
            field.options = STRATEGY_TYPES
            field.value = STRATEGY_TYPES[0]
            field.name = 'combine_strategy'
            field.advanced = False
        if field.name in {'metadata', 'tags'} and name == 'MixEsVectorRetriever':
            field.show = True
            field.advanced = True
