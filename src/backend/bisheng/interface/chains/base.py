from typing import Any, ClassVar, Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.chains import ChainFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class, build_template_from_method
from bisheng_langchain import chains as bisheng_chains
from langchain import chains

# Assuming necessary imports for Field, Template, and FrontendNode classes


class ChainCreator(LangChainTypeCreator):
    type_name: str = 'chains'

    @property
    def frontend_node_class(self) -> Type[ChainFrontendNode]:
        return ChainFrontendNode

    # We need to find a better solution for this
    from_method_nodes: ClassVar[Dict] = {
        'APIChain': 'from_llm_and_api_docs',
        'ConversationalRetrievalChain': 'from_llm',
        'LLMCheckerChain': 'from_llm',
        'SQLDatabaseChain': 'from_llm',
        'LLMRouterChain': 'from_llm',
    }

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            # langchain
            self.type_dict: dict[str, Any] = {
                chain_name: import_class(f'langchain.chains.{chain_name}')
                for chain_name in chains.__all__
            }
            # bisheng-langchain
            bisheng = {
                chain_name: import_class(f'bisheng_langchain.chains.{chain_name}')
                for chain_name in bisheng_chains.__all__
            }
            self.type_dict.update(bisheng)

            from bisheng.interface.chains.custom import CUSTOM_CHAINS

            self.type_dict.update(CUSTOM_CHAINS)
            # Filter according to settings.chains
            self.type_dict = {
                name: chain
                for name, chain in self.type_dict.items()
                if name in settings.chains or settings.dev
            }
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        try:
            if name in get_custom_nodes(self.type_name).keys():
                return get_custom_nodes(self.type_name)[name]
            elif name in self.from_method_nodes.keys():
                return build_template_from_method(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                    method_name=self.from_method_nodes[name],
                    add_function=True,
                )
            return build_template_from_class(name, self.type_to_loader_dict, add_function=True)
        except ValueError as exc:
            raise ValueError(f'Chain {name} not found: {exc}') from exc
        except AttributeError as exc:
            logger.error(f'Chain {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        names = []
        for _, chain in self.type_to_loader_dict.items():
            chain_name = (chain.function_name()
                          if hasattr(chain, 'function_name') else chain.__name__)
            names.append(chain_name)
        return names


chain_creator = ChainCreator()
