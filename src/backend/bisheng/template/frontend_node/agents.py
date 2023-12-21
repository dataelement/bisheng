from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.template.base import Template
from langchain.agents import types

NON_CHAT_AGENTS = {
    agent_type: agent_class
    for agent_type, agent_class in types.AGENT_TO_CLASS.items() if 'chat' not in agent_type.value
}


class AgentFrontendNode(FrontendNode):

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        if field.name in ['suffix', 'prefix', 'format_instructions', 'input_variables']:
            field.show = False if name == 'ChatglmFunctionsAgent' else True
        if field.name == 'Tools' and name == 'ZeroShotAgent':
            field.field_type = 'BaseTool'
            field.is_list = True
        if 'path' == field.name and name == 'CSVAgent':
            field.field_type = 'file'
            field.required = True
            field.show = True
            field.value = ''
            field.suffixes = ['.csv']
            field.fileTypes = ['csv']


class SQLAgentNode(FrontendNode):
    name: str = 'SQLAgent'
    template: Template = Template(
        type_name='sql_agent',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                multiline=False,
                value='',
                name='database_uri',
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                show=True,
                name='llm',
                display_name='LLM',
            ),
        ],
    )
    description: str = """Construct an SQL agent from an LLM and tools."""
    base_classes: list[str] = ['AgentExecutor', 'function']

    def to_dict(self):
        return super().to_dict()


class VectorStoreRouterAgentNode(FrontendNode):
    name: str = 'VectorStoreRouterAgent'
    template: Template = Template(
        type_name='vectorstorerouter_agent',
        fields=[
            TemplateField(
                field_type='VectorStoreRouterToolkit',
                required=True,
                show=True,
                name='vectorstoreroutertoolkit',
                display_name='Vector Store Router Toolkit',
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                show=True,
                name='llm',
                display_name='LLM',
            ),
        ],
    )
    description: str = """Construct an agent from a Vector Store Router."""
    base_classes: list[str] = ['AgentExecutor', 'function']

    def to_dict(self):
        return super().to_dict()


class VectorStoreAgentNode(FrontendNode):
    name: str = 'VectorStoreAgent'
    template: Template = Template(
        type_name='vectorstore_agent',
        fields=[
            TemplateField(
                field_type='VectorStoreInfo',
                required=True,
                show=True,
                name='vectorstoreinfo',
                display_name='Vector Store Info',
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                show=True,
                name='llm',
                display_name='LLM',
            ),
        ],
    )
    description: str = """Construct an agent from a Vector Store."""
    base_classes: list[str] = ['AgentExecutor', 'function']

    def to_dict(self):
        return super().to_dict()


class SQLDatabaseNode(FrontendNode):
    name: str = 'SQLDatabase'
    template: Template = Template(
        type_name='sql_database',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                is_list=False,
                show=True,
                multiline=False,
                value='',
                name='uri',
            ),
        ],
    )
    description: str = """SQLAlchemy wrapper around a database."""
    base_classes: list[str] = ['SQLDatabase']

    def to_dict(self):
        return super().to_dict()


class InitializeAgentNode(FrontendNode):
    name: str = 'AgentInitializer'
    display_name: str = 'AgentInitializer'
    template: Template = Template(
        type_name='initialize_agent',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                is_list=True,
                show=True,
                multiline=False,
                options=list(NON_CHAT_AGENTS.keys()),
                value=list(NON_CHAT_AGENTS.keys())[0],
                name='agent',
                advanced=False,
            ),
            TemplateField(
                field_type='BaseChatMemory',
                required=False,
                show=True,
                name='memory',
                advanced=False,
            ),
            TemplateField(
                field_type='Tool',
                required=False,
                show=True,
                name='tools',
                is_list=True,
                advanced=False,
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                show=True,
                name='llm',
                display_name='LLM',
                advanced=False,
            ),
        ],
    )
    description: str = """Construct a zero shot agent from an LLM and tools."""
    base_classes: list[str] = ['AgentExecutor', 'function']

    def to_dict(self):
        return super().to_dict()

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        # do nothing and don't return anything
        pass


class JsonAgentNode(FrontendNode):
    name: str = 'JsonAgent'
    template: Template = Template(
        type_name='json_agent',
        fields=[
            TemplateField(
                field_type='BaseToolkit',
                required=True,
                show=True,
                name='toolkit',
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                show=True,
                name='llm',
                display_name='LLM',
            ),
        ],
    )
    description: str = """Construct a json agent from an LLM and tools."""
    base_classes: list[str] = ['AgentExecutor', 'function']

    def to_dict(self):
        return super().to_dict()
