from typing import Optional

from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.frontend_node.constants import QA_CHAIN_TYPES, SUMMARIZE_CHAIN_TYPES
from bisheng.template.template.base import Template


class ChainFrontendNode(FrontendNode):

    def add_extra_fields(self) -> None:
        if self.template.type_name == 'ConversationalRetrievalChain':
            # add memory
            self.template.add_field(
                TemplateField(
                    field_type='BaseChatMemory',
                    required=True,
                    show=True,
                    name='memory',
                    advanced=False,
                ))
            # add return_source_documents
            self.template.add_field(
                TemplateField(
                    field_type='bool',
                    required=False,
                    show=True,
                    name='return_source_documents',
                    advanced=False,
                    value=True,
                    display_name='Return source documents',
                ))
            self.template.add_field(
                TemplateField(
                    field_type='str',
                    required=True,
                    is_list=True,
                    show=True,
                    multiline=False,
                    options=QA_CHAIN_TYPES,
                    value=QA_CHAIN_TYPES[0],
                    name='chain_type',
                    advanced=False,
                ))
            self.template.add_field(
                TemplateField(
                    field_type='BasePromptTemplate',
                    show=True,
                    name='document_prompt',
                    advanced=False,
                ))
        elif self.template.type_name == 'SequentialChain':
            self.template.add_field(
                TemplateField(field_type='str',
                              required=True,
                              show=True,
                              name='chain_order',
                              advanced=False,
                              value='[]'))
        elif self.template.type_name in {'MultiPromptChain', 'MultiRuleChain'}:
            self.template.add_field(
                TemplateField(field_type='Chain',
                              required=True,
                              show=True,
                              is_list=True,
                              name='LLMChains',
                              advanced=False,
                              value='[]'))
            self.template.add_field(
                TemplateField(field_type='NestedDict',
                              required=True,
                              show=True,
                              is_list=True,
                              name='destination_chain_name',
                              advanced=False,
                              info='{chain_id: name}',
                              value='{}'))

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        FrontendNode.format_field(field, name)
        if name == 'RuleBasedRouter' and field.name == 'rule_function':
            field.field_type = 'function'
        if name == 'RuleBasedRouter' and field.name == 'input_variables':
            field.show = True

        if name == 'LoaderOutputChain' and field.name == 'documents':
            field.is_list = False

        if name == 'RetrievalQA' and field.name == 'memory':
            field.show = False
            field.required = False

        if name == 'APIChain' and field.name == 'limit_to_domains':
            field.show = True
            field.required = True

        field.advanced = False
        if 'key' in field.name:
            field.password = False
            field.show = False
        if field.name in ['input_key', 'output_key']:
            field.required = True
            field.show = True
            field.advanced = True

        # We should think of a way to deal with this later
        # if field.field_type == "PromptTemplate":
        #     field.field_type = "str"
        #     field.multiline = True
        #     field.show = True
        #     field.advanced = False
        #     field.value = field.value.template

        # Separated for possible future changes
        if field.name == 'prompt' and field.value is None:
            field.required = True
            field.show = True
            field.advanced = False
        if field.name == 'condense_question_prompt':
            field.required = False
            field.show = True
        if field.name in {'memory', 'document_prompt'}:
            # field.required = False
            field.show = True
            field.advanced = False
        if field.name == 'verbose':
            field.required = False
            field.show = False
            field.advanced = True
        if field.name == 'llm':
            field.required = True
            field.show = True
            field.advanced = False
            field.field_type = 'BaseLanguageModel'  # temporary fix
            field.is_list = False

        if field.name == 'return_source_documents':
            field.required = False
            field.show = True
            field.advanced = True
            field.value = True
        if field.name == 'combine_docs_chain_kwargs':
            field.show = True
            field.field_type = 'BasePromptTemplate'
            field.display_name = 'prompt'
        if field.name == 'recipient':
            field.display_name = 'AutogenRole'
        if field.name == 'destination_chains':
            field.show = False
        if name == 'TransformChain' and field.name == 'input_variables':
            field.show = True
        if name == 'TransformChain' and field.name == 'transform_cb':
            field.show = True
            field.field_type = 'function'


class SeriesCharacterChainNode(FrontendNode):
    name: str = 'SeriesCharacterChain'
    template: Template = Template(
        type_name='SeriesCharacterChain',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                advanced=False,
                multiline=False,
                name='character',
            ),
            TemplateField(
                field_type='str',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                advanced=False,
                multiline=False,
                name='series',
            ),
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                advanced=False,
                multiline=False,
                name='llm',
                display_name='LLM',
            ),
        ],
    )
    description: str = 'SeriesCharacterChain is a chain you can use to have a conversation with a character from a series.'  # noqa
    base_classes: list[str] = [
        'LLMChain',
        'BaseCustomChain',
        'Chain',
        'ConversationChain',
        'SeriesCharacterChain',
        'function',
    ]


class TimeTravelGuideChainNode(FrontendNode):
    name: str = 'TimeTravelGuideChain'
    template: Template = Template(
        type_name='TimeTravelGuideChain',
        fields=[
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                advanced=False,
                multiline=False,
                name='llm',
                display_name='LLM',
            ),
            TemplateField(
                field_type='BaseChatMemory',
                required=False,
                show=True,
                name='memory',
                advanced=False,
            ),
        ],
    )
    description: str = 'Time travel guide chain.'
    base_classes: list[str] = [
        'LLMChain',
        'BaseCustomChain',
        'TimeTravelGuideChain',
        'Chain',
        'ConversationChain',
    ]


class MidJourneyPromptChainNode(FrontendNode):
    name: str = 'MidJourneyPromptChain'
    template: Template = Template(
        type_name='MidJourneyPromptChain',
        fields=[
            TemplateField(
                field_type='BaseLanguageModel',
                required=True,
                placeholder='',
                is_list=False,
                show=True,
                advanced=False,
                multiline=False,
                name='llm',
                display_name='LLM',
            ),
            TemplateField(
                field_type='BaseChatMemory',
                required=False,
                show=True,
                name='memory',
                advanced=False,
            ),
        ],
    )
    description: str = 'MidJourneyPromptChain is a chain you can use to generate new MidJourney prompts.'
    base_classes: list[str] = [
        'LLMChain',
        'BaseCustomChain',
        'Chain',
        'ConversationChain',
        'MidJourneyPromptChain',
    ]


class CombineDocsChainNode(FrontendNode):
    name: str = 'CombineDocsChain'
    template: Template = Template(
        type_name='load_qa_chain',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                is_list=True,
                show=True,
                multiline=False,
                options=QA_CHAIN_TYPES,
                value=QA_CHAIN_TYPES[0],
                name='chain_type',
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
            TemplateField(
                field_type='int',
                required=False,
                show=True,
                name='token_max',
                display_name='token_max',
                advanced=False,
                info='只对Stuff类型生效',
                value=-1,
            ),
            TemplateField(field_type='BasePromptTemplate',
                          required=False,
                          show=True,
                          name='prompt',
                          display_name='prompt',
                          advanced=False,
                          info='只对Stuff类型生效'),
            TemplateField(
                field_type='BasePromptTemplate',
                required=False,
                show=True,
                name='document_prompt',
                advanced=False,
            )
        ],
    )

    @staticmethod
    def format_field(field: TemplateField, name: Optional[str] = None) -> None:
        pass

    description: str = """Load question answering chain."""
    base_classes: list[str] = ['BaseCombineDocumentsChain', 'function']


class SummarizeDocsChain(FrontendNode):
    name: str = 'SummarizeDocsChain'
    template: Template = Template(
        type_name='load_summarize_chain',
        fields=[
            TemplateField(
                field_type='str',
                required=True,
                is_list=True,
                show=True,
                multiline=False,
                options=SUMMARIZE_CHAIN_TYPES,
                value=SUMMARIZE_CHAIN_TYPES[0],
                name='chain_type',
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
            TemplateField(
                field_type='int',
                required=False,
                show=True,
                name='token_max',
                display_name='token_max',
                advanced=False,
                info='当前只对stuff 生效',
                value=-1,
            ),
            TemplateField(field_type='BasePromptTemplate',
                          required=False,
                          show=True,
                          name='prompt',
                          display_name='prompt',
                          advanced=False,
                          info='只对Stuff类型生效')
        ],
    )
    description: str = """Load summarize chain."""
    base_classes: list[str] = ['BaseCombineDocumentsChain', 'function']
