from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode


class AutogenRoleFrontNode(FrontendNode):

    def add_extra_base_classes(self) -> None:
        self.base_classes.append('ConversableAgent')

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        field.show = True

    def add_extra_fields(self) -> None:
        if self.name in {
                'AutoGenAssistant',
                'AutoGenGroupChatManager',
        }:
            self.template.add_field(
                TemplateField(field_type='BaseLanguageModel',
                              required=True,
                              show=True,
                              name='llm',
                              advanced=False))

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
                TemplateField(field_type='int',
                              required=False,
                              show=True,
                              name='max_round',
                              advanced=False,
                              value=50))
            self.template.add_field(
                TemplateField(field_type='str',
                              required=False,
                              show=True,
                              name='system_message',
                              advanced=False,
                              value='Group chat manager.'))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    show=True,
                    name='name',
                    value='chat_manage',
                    advanced=False,
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
                    required=True,
                    show=True,
                    name='system_message',
                    advanced=False,
                ))

        if self.name == 'AutoGenUser':
            self.template.add_field(
                TemplateField(field_type='int',
                              required=False,
                              show=True,
                              name='max_consecutive_auto_reply',
                              advanced=False,
                              value=10))
            self.template.add_field(
                TemplateField(field_type='str',
                              required=True,
                              show=True,
                              name='human_input_mode',
                              advanced=False,
                              value='ALWAYS'))
        if self.name == 'AutoGenCustomRole':
            self.template.add_field(
                TemplateField(
                    field_type='function',
                    required=True,
                    show=True,
                    name='func',
                    advanced=False,
                ))
