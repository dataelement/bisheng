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
    Prompt类型枚举
    """
    PROMPT = "prompt"
    CHATPROMPT = "chat_prompt"


class ChatPromptSchema(BaseModel):
    system: str = Field(default='', description='系统Prompt内容')
    user: str = Field(default='', description='用户Prompt内容')


# 标准Prompt Schema
class PromptSchema(BaseModel):
    """
    标准Prompt Schema
    """
    description: str = Field(default='', description='Prompt描述')
    type: PromptTypeEnum = Field(default=PromptTypeEnum.PROMPT, description='Prompt类型')
    prompt: Union[str, ChatPromptSchema] = Field(..., description='Prompt内容')


# 内置Prompt加载器
class PromptLoader(object):
    def __init__(self):
        """
        初始化Prompt加载器
        """
        self.prompt_yaml_dir = os.path.join(os.path.dirname(__file__), 'yaml')
        self.prompts_storage = {}
        self._load_all()

    # 解析prompts
    @staticmethod
    def _parse_prompt(prompts_data: dict) -> Dict[str, PromptSchema]:
        """
        解析Prompt数据
        :param prompts_data: Prompt数据
        :return: 解析后的Prompt对象
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

    # 获取指定的Prompt
    def get_prompt(self, namespace: str, prompt_name: str) -> PromptSchema:
        """
        获取指定的Prompt
        :param namespace: 命名空间
        :param prompt_name: Prompt名称
        :return: Prompt对象
        """
        if namespace in self.prompts_storage:
            return copy.deepcopy(self.prompts_storage[namespace].get(prompt_name, None))
        else:
            raise KeyError(f"Namespace '{namespace}' not found in prompts storage.")

    def render_prompt(self, namespace: str, prompt_name: str, **kwargs) -> PromptSchema:
        """
        渲染指定的Prompt
        :param namespace: 命名空间
        :param prompt_name: Prompt名称
        :param kwargs: 渲染参数
        :return: 渲染后的Prompt字符串
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
