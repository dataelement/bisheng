from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode


class AutogenRoleFrontNode(FrontendNode):

    def add_extra_base_classes(self) -> None:
        self.base_classes = ['Document']
        self.output_types = ['Document']
    # def add_extra_fields(self) -> None:
    #     name = None
    #     display_name = 'Web Page'

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        if field.name == 'metadata':
            field.show = True
            field.advanced = False
        field.show = True
        if field.name == 'unstructured_api_url':
            field.show = True
            field.advanced = False
