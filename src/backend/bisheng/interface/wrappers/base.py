from typing import ClassVar, Dict, List, Optional, Type

from bisheng.interface.base import LangChainTypeCreator
from bisheng.template.frontend_node.wrappers import WrappersFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class, build_template_from_method
from bisheng_langchain.utils.azure_dalle_image_generator import AzureDallEWrapper as DallEAPIWrapper
from langchain_community.utilities import requests, sql_database
from sqlmodel import true


class WrapperCreator(LangChainTypeCreator):
    type_name: str = 'wrappers'

    from_method_nodes: ClassVar[Dict] = {'SQLDatabase': 'from_uri'}

    @property
    def frontend_node_class(self) -> Type[WrappersFrontendNode]:
        """The class type of the FrontendNode created in frontend_node."""
        return WrappersFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = {
                wrapper.__name__: wrapper
                for wrapper in
                [requests.TextRequestsWrapper, sql_database.SQLDatabase, DallEAPIWrapper]
            }
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        try:
            if name in self.from_method_nodes:
                return build_template_from_method(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                    add_function=True,
                    method_name=self.from_method_nodes[name],
                )

            return build_template_from_class(name, self.type_to_loader_dict, true)
        except ValueError as exc:
            raise ValueError('Wrapper not found') from exc
        except AttributeError as exc:
            logger.error(f'Wrapper {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        return list(self.type_to_loader_dict.keys())


wrapper_creator = WrapperCreator()
