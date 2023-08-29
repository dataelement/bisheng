from typing import Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.prompts import PromptFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class
from langchain import prompts


class PromptCreator(LangChainTypeCreator):
    type_name: str = 'prompts'

    @property
    def frontend_node_class(self) -> Type[PromptFrontendNode]:
        return PromptFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = {
                prompt_name: import_class(f'langchain.prompts.{prompt_name}')
                # if prompt_name is not lower case it is a class
                for prompt_name in prompts.__all__
            }
            # Merge CUSTOM_PROMPTS into self.type_dict
            from bisheng.interface.prompts.custom import CUSTOM_PROMPTS

            self.type_dict.update(CUSTOM_PROMPTS)
            # Now filter according to settings.prompts
            self.type_dict = {
                name: prompt
                for name, prompt in self.type_dict.items()
                if name in settings.prompts or settings.dev
            }
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        try:
            if name in get_custom_nodes(self.type_name).keys():
                return get_custom_nodes(self.type_name)[name]
            return build_template_from_class(name, self.type_to_loader_dict)
        except ValueError as exc:
            # raise ValueError("Prompt not found") from exc
            logger.error(f'Prompt {name} not found: {exc}')
        except AttributeError as exc:
            logger.error(f'Prompt {name} not loaded: {exc}')
        return None

    def to_list(self) -> List[str]:
        custom_prompts = get_custom_nodes('prompts')
        # library_prompts = [
        #     prompt.__annotations__["return"].__name__
        #     for prompt in self.type_to_loader_dict.values()
        #     if prompt.__annotations__["return"].__name__ in settings.prompts
        #     or settings.dev
        # ]
        return list(self.type_to_loader_dict.keys()) + list(custom_prompts.keys())


prompt_creator = PromptCreator()
