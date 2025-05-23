from typing import Any, Dict, List, Optional, Type, Union

from bisheng.interface.base import CustomChain
from bisheng.interface.utils import extract_input_variables_from_prompt
from bisheng_langchain.chains.question_answering import load_qa_chain
from langchain.base_language import BaseLanguageModel
from langchain.callbacks.manager import CallbackManagerForChainRun
from langchain.chains import ConversationChain, LLMChain
from langchain.chains.summarize import load_summarize_chain
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from langchain.schema import BaseMemory
from langchain.schema.prompt_template import BasePromptTemplate
from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from pydantic import Field, model_validator

DEFAULT_SUFFIX = """"
Current conversation:
{history}
Human: {input}
{ai_prefix}"""


class BaseCustomConversationChain(ConversationChain):
    """BaseCustomChain is a chain you can use to have a conversation with a custom character."""

    template: Optional[str]

    ai_prefix_value: Optional[str]
    """Field to use as the ai_prefix. It needs to be set and has to be in the template"""

    @model_validator(mode='before')
    @classmethod
    def build_template(cls, values):
        format_dict = {}
        input_variables = extract_input_variables_from_prompt(values['template'])

        if values.get('ai_prefix_value', None) is None:
            values['ai_prefix_value'] = values['memory'].ai_prefix

        for key in input_variables:
            new_value = values.get(key, f'{{{key}}}')
            format_dict[key] = new_value
            if key == values.get('ai_prefix_value', None):
                values['memory'].ai_prefix = new_value

        values['template'] = values['template'].format(**format_dict)

        values['template'] = values['template']
        values['input_variables'] = extract_input_variables_from_prompt(values['template'])
        values['prompt'].template = values['template']
        values['prompt'].input_variables = values['input_variables']
        return values


class SeriesCharacterChain(BaseCustomConversationChain):
    """SeriesCharacterChain is a chain you can use to have a conversation with a character from a series."""

    character: str
    series: str
    template: Optional[str] = """I want you to act like {character} from {series}.
I want you to respond and answer like {character}. do not write any explanations. only answer like {character}.
You must know all of the knowledge of {character}.
Current conversation:
{history}
Human: {input}
{character}:"""
    memory: BaseMemory = Field(default_factory=ConversationBufferMemory)
    ai_prefix_value: Optional[str] = 'character'
    """Default memory store."""


class MidJourneyPromptChain(BaseCustomConversationChain):
    """MidJourneyPromptChain is a chain you can use to generate new MidJourney prompts."""

    template: Optional[
        str
    ] = """I want you to act as a prompt generator for Midjourney's artificial intelligence program.
    Your job is to provide detailed and creative descriptions that will inspire unique and interesting images from the AI.
    Keep in mind that the AI is capable of understanding a wide range of language and can interpret abstract concepts, so feel free to be as imaginative and descriptive as possible.
    For example, you could describe a scene from a futuristic city, or a surreal landscape filled with strange creatures.
    The more detailed and imaginative your description, the more interesting the resulting image will be. Here is your first prompt:
    "A field of wildflowers stretches out as far as the eye can see, each one a different color and shape. In the distance, a massive tree towers over the landscape, its branches reaching up to the sky like tentacles.\"

    Current conversation:
    {history}
    Human: {input}
    AI:"""  # noqa: E501


class TimeTravelGuideChain(BaseCustomConversationChain):
    template: Optional[
        str
    ] = """I want you to act as my time travel guide. You are helpful and creative. I will provide you with the historical period or future time I want to visit and you will suggest the best events, sights, or people to experience. Provide the suggestions and any necessary information.
    Current conversation:
    {history}
    Human: {input}
    AI:"""  # noqa: E501


class CombineDocsChain(CustomChain):
    """Implementation of load_qa_chain function"""

    @staticmethod
    def function_name():
        return 'load_qa_chain'

    @classmethod
    def initialize(cls,
                   llm: BaseLanguageModel,
                   chain_type: str,
                   prompt: BasePromptTemplate = None,
                   document_prompt: BasePromptTemplate = None,
                   token_max: str = -1):
        if chain_type == 'stuff':
            if document_prompt:
                return load_qa_chain(llm=llm,
                                     chain_type=chain_type,
                                     prompt=prompt,
                                     token_max=token_max,
                                     document_prompt=document_prompt)
            else:
                return load_qa_chain(llm=llm,
                                     chain_type=chain_type,
                                     prompt=prompt,
                                     token_max=token_max)
        else:
            return load_qa_chain(llm=llm, chain_type=chain_type)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class SummarizeDocsChain(CustomChain):
    """Implementation of load_sumarize_chain function"""

    @staticmethod
    def function_name():
        return 'load_summarize_chain'

    @classmethod
    def initialize(cls,
                   llm: BaseLanguageModel,
                   chain_type: str,
                   prompt: str = None,
                   token_max: str = -1):
        if chain_type == 'stuff':
            return load_summarize_chain(llm=llm,
                                        chain_type=chain_type,
                                        prompt=prompt,
                                        token_max=token_max)
        else:
            return load_summarize_chain(llm=llm, chain_type=chain_type)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


prompt_default = PromptTemplate(
    input_variables=['image_desc'],
    template="""Generate a detailed prompt to generate an image based on the following description:
    {image_desc}""")


class DalleGeneratorChain(CustomChain):
    """Implementation of dall-e generate images"""
    dalle: DallEAPIWrapper
    llm: Optional[BaseLanguageModel]
    prompt: Optional[PromptTemplate]
    input_key: str = 'image_desc'
    output_key: str = 'response'  #: :meta private:

    @property
    def input_keys(self) -> List[str]:
        """Use this since so some prompt vars come from history."""
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    @staticmethod
    def function_name():
        return 'DalleGeneratorChain'

    @classmethod
    def initialize(cls, dalle: DallEAPIWrapper, **kwargs):
        return DalleGeneratorChain(dalle=dalle, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)

    def _call(self,
              inputs: Dict[str, Any],
              run_manager: Optional[CallbackManagerForChainRun] = None) -> Dict[str, Any]:
        if self.llm:
            prompt = self.prompt or prompt_default
            llm_chain = LLMChain(llm=self.llm, prompt=prompt)
            pic_url = self.dalle.run(llm_chain.run(inputs)).split('\n')
        else:
            pic_url = self.dalle.run(inputs.get(self.input_key)).split('\n')
        if len(pic_url) > 0:
            pic_style = []
            for url in pic_url:
                pic_style.append(f'![{url}]({url})')
            pic_url = ' \n'.join(pic_style)
            return {self.output_key: pic_url, 'type': 'image'}
        else:
            return {self.output_key: f'![{pic_url}]({pic_url})', 'type': 'image'}


CUSTOM_CHAINS: Dict[str, Type[Union[ConversationChain, CustomChain]]] = {
    'CombineDocsChain': CombineDocsChain,
    'SummarizeDocsChain': SummarizeDocsChain,
    'SeriesCharacterChain': SeriesCharacterChain,
    'MidJourneyPromptChain': MidJourneyPromptChain,
    'TimeTravelGuideChain': TimeTravelGuideChain,
    'DalleGeneratorChain': DalleGeneratorChain,
}
