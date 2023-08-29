from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.template.base import Template


class InputNode(FrontendNode):
    name: str = 'InputNode'
    template: Template = Template(
        type_name='input',
        fields=[
            TemplateField(
                field_type='str',
                is_list=True,
                multiline=True,
                required=True,
                show=True,
                name='input',
                display_name='输入内容',
            ),
        ],
    )
    description: str = """输入节点，用来自动对接输入"""
    base_classes: list[str] = ['input']

    def to_dict(self):
        return super().to_dict()

class InputFileNode(FrontendNode):
    name: str = 'InputFileNode'
    template: Template = Template(
        type_name='InputFileNode',
        fields=[
            TemplateField(
                field_type='file',
                show=True,
                name='file_path',
                value='',
                display_name='输入内容',
                suffixes=['.pdf'],
                fileTypes=['pdf'],
            ),
        ],
    )
    description: str = """输入节点，用来自动对接输入"""
    base_classes: list[str] = ['fileNode']


    def to_dict(self):
        return super().to_dict()


class OutputNode(FrontendNode):
    name: str = 'OutputNode'
    template: Template = Template(
        type_name='output',
        fields=[
            TemplateField(
                field_type='str',
                list=False,
                multiline=True,
                required=True,
                show=True,
                name='output',
                display_name='展示输出内容',
            ),
        ],
    )
    description: str = """输出节点，用来表示输出"""
    base_classes: list[str] = ['output']

    def to_dict(self):
        return super().to_dict()
