from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode


class AutogenRoleFrontNode(FrontendNode):

    def add_extra_base_classes(self) -> None:
        self.base_classes = ['ConversableAgent']
        self.output_types = ['ConversableAgent']

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

    def add_extra_fields(self) -> None:
        self.template.add_field(
                TemplateField(
                    field_type='int',
                    required=True,
                    show=True,
                    name='temperature',
                    advanced=False,
                    value=0
                ))
        self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='model_name',
                    value='gpt-4-0613',
                    advanced=False,
                ))

        self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=False,
                    show=True,
                    name='openai_api_key',
                    value='',
                    advanced=False,
                ))

        self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=False,
                    show=True,
                    name='openai_proxy',
                    advanced=False,
                ))

        if self.name == 'AutoGenGroupChatManager':
            self.template.add_field(
                TemplateField(
                    field_type='ConversableAgent',
                    is_list=True,
                    required=False,
                    show=True,
                    name='agents',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='int',
                    required=False,
                    show=True,
                    name='max_round',
                    advanced=False,
                    value=50
                ))
        else:
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='name',
                    value='',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=False,
                    show=True,
                    name='system_message',
                    advanced=False,
                ))

        if self.name == 'AutoGenUser':
            self.template.add_field(
                TemplateField(
                    field_type='bool',
                    required=True,
                    show=True,
                    name='code_execution_flag',
                    advanced=False,
                ))
