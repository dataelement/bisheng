from typing import Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.frontend_node.input_output import InputOutputNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class
from bisheng_langchain import input_output


class IOutputCreator(LangChainTypeCreator):
    type_name: str = 'input_output'

    @property
    def frontend_node_class(self) -> Type[FrontendNode]:
        return InputOutputNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = {}
            # bisheng-langchain
            bisheng = {
                node_name: import_class(f'bisheng_langchain.input_output.{node_name}')
                for node_name in input_output.__all__
            }
            self.type_dict.update(bisheng)
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        """Get the signature of an llm."""
        try:
            if name in get_custom_nodes(self.type_name).keys():
                return get_custom_nodes(self.type_name)[name]
            return build_template_from_class(
                name,
                type_to_cls_dict=self.type_to_loader_dict,
            )
        except ValueError as exc:
            raise ValueError('LLM not found') from exc

        except AttributeError as exc:
            logger.error(f'LLM {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        return self.type_to_loader_dict.keys()


input_output_creator = IOutputCreator()
