from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.template.base import Template


def build_file_field(suffixes: list,
                     fileTypes: list,
                     name: str = 'file_path',
                     fieldType='fileNode') -> TemplateField:
    """Build a template field for a document loader."""
    return TemplateField(
        field_type=fieldType,
        required=True,
        show=True,
        name=name,
        value='',
        suffixes=suffixes,
        fileTypes=fileTypes,
    )


class InputOutputNode(FrontendNode):
    name: str = 'InputOutputNode'
    base_classes: list[str] = ['input', 'output']

    def add_extra_base_classes(self) -> None:
        if self.name in {'AudioInputNode', 'FileInputNode'}:
            self.base_classes.append('input')

    def add_extra_fields(self) -> None:
        pass

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        if name == 'Report':
            if field.name == 'memory':
                field.show = False
            elif field.name == 'input_node':
                field.show = False
            elif field.name == 'chains':
                field.show = True
                field.field_type = 'function'
                field.display_name = 'functions'
            elif field.name == 'report_name':
                field.show = True
                field.display_name = 'Report Name'
                field.info = 'the file name we generate'
            elif field.name == 'variables':
                field.show = True
                field.field_type = 'VariableNode'
        if name == 'VariableNode':
            if field.name == 'variables':
                field.show = True
                field.field_type = 'variable'
                field.required = True
        if name == 'AudioInputNode':
            if field.name == 'file_path':
                field.show = True
                field.field_type = 'fileNode'
                field.required = True
                field.suffixes = ['.mp3']
                field.fileTypes = ['mp3']
            elif field.name == 'openai_proxy':
                field.show = True

        if name == 'FileInputNode':
            if field.name == 'file_path':
                field.show = True
                field.field_type = 'fileNode'
                field.required = True
                field.suffixes = ['.jpg', '.png', '.jpeg']
                field.fileTypes = ['jpg', 'png', 'jpeg']
            elif field.name == 'openai_proxy':
                field.show = True


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
            ),
            TemplateField(field_type='str',
                          show=True,
                          name='file_type',
                          placeholder='提示上传文件类型',
                          display_name='Name',
                          info='Tips for which file should upload'),
        ],
    )
    description: str = """输入节点，用来自动对接输入"""
    base_classes: list[str] = ['fileNode']

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        field.show = True

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
