import copy
import logging
import os
from enum import Enum
from string import Template
from typing import Union, Dict

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PromptTypeEnum(str, Enum):
    """
    PromptType Enumeration
    """
    PROMPT = "prompt"
    CHATPROMPT = "chat_prompt"


class ChatPromptSchema(BaseModel):
    system: str = Field(default='', description='SystemPromptContents')
    user: str = Field(default='', description='UsersPromptContents')


# StandardPrompt Schema
class PromptSchema(BaseModel):
    """
    StandardPrompt Schema
    """
    description: str = Field(default='', description='PromptDescription')
    type: PromptTypeEnum = Field(default=PromptTypeEnum.PROMPT, description='PromptType')
    prompt: Union[str, ChatPromptSchema] = Field(..., description='PromptContents')


# embeddedPromptLoader..
class PromptLoader(object):
    def __init__(self):
        """
        InisialisasiPromptLoader..
        """
        self.prompt_yaml_dir = os.path.join(os.path.dirname(__file__), 'yaml')
        self.prompts_storage = {}
        self._load_all()

    # analyzingprompts
    @staticmethod
    def _parse_prompt(prompts_data: dict) -> Dict[str, PromptSchema]:
        """
        analyzingPromptDATA
        :param prompts_data: PromptDATA
        :return: After parsingPromptObjects
        """
        parsed_prompts = {}
        for prompt_name, prompt_data in prompts_data.items():
            if not isinstance(prompt_data, dict):
                raise ValueError(f"Invalid prompt format for {prompt_name}: Expected a dictionary.")
            prompt_schema = PromptSchema(**prompt_data)
            parsed_prompts[prompt_name] = prompt_schema

        return parsed_prompts

    def _load_all(self):
        for root, _, files in os.walk(self.prompt_yaml_dir):
            for file in files:
                if not file.endswith('.yaml') and not file.endswith('.yml'):
                    continue
                file_path = os.path.join(root, file)
                namespace = os.path.splitext(file)[0]
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        prompt_data = yaml.safe_load(f)
                        if isinstance(prompt_data, dict):
                            self.prompts_storage[namespace] = self._parse_prompt(prompt_data.get('prompts', {}))
                        else:
                            raise ValueError(f"Invalid YAML format in {file_path}: Expected a dictionary.")
                    except yaml.YAMLError as e:
                        logger.error(f"Error parsing YAML file {file_path}: {e}")
                        continue

    # Get the specifiedPrompt
    def get_prompt(self, namespace: str, prompt_name: str) -> PromptSchema:
        """
        Get the specifiedPrompt
        :param namespace: namespace
        :param prompt_name: PromptPart Name
        :return: PromptObjects
        """
        if namespace in self.prompts_storage:
            return copy.deepcopy(self.prompts_storage[namespace].get(prompt_name, None))
        else:
            raise KeyError(f"Namespace '{namespace}' not found in prompts storage.")

    def render_prompt(self, namespace: str, prompt_name: str, **kwargs) -> PromptSchema:
        """
        Render specifiedPrompt
        :param namespace: namespace
        :param prompt_name: PromptPart Name
        :param kwargs: Rendering parameters
        :return: RenderedPromptString
        """
        prompt_obj = self.get_prompt(namespace, prompt_name)
        if prompt_obj.type == PromptTypeEnum.PROMPT:
            prompt_obj.prompt = Template(prompt_obj.prompt).safe_substitute(**kwargs)
        elif prompt_obj.type == PromptTypeEnum.CHATPROMPT:
            prompt_obj.prompt.system = Template(prompt_obj.prompt.system).safe_substitute(**kwargs)
            prompt_obj.prompt.user = Template(prompt_obj.prompt.user).safe_substitute(**kwargs)
        else:
            raise ValueError(f"Unsupported prompt type: {prompt_obj.type}")

        return prompt_obj
