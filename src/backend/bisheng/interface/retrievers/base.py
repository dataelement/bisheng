from typing import Any, ClassVar, Dict, List, Optional, Type

from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.retrievers import RetrieverFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class, build_template_from_method
from bisheng_langchain import retrievers as bisheng_retrievers
from langchain import retrievers


class RetrieverCreator(LangChainTypeCreator):
    type_name: str = 'retrievers'

    from_method_nodes: ClassVar[Dict] = {
        'MultiQueryRetriever': 'from_llm',
        'ZepRetriever': '__init__'
    }

    @property
    def frontend_node_class(self) -> Type[RetrieverFrontendNode]:
        return RetrieverFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict: dict[str, Any] = {
                retriever_name: import_class(f'langchain.retrievers.{retriever_name}')
                for retriever_name in retrievers.__all__
            }

            self.type_dict.update({
                retriever_name:
                import_class(f'bisheng_langchain.retrievers.{retriever_name}')
                for retriever_name in bisheng_retrievers.__all__
            })
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        """Get the signature of an embedding."""
        try:
            if name in self.from_method_nodes:
                return build_template_from_method(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                    method_name=self.from_method_nodes[name],
                )
            else:
                return build_template_from_class(name, type_to_cls_dict=self.type_to_loader_dict)
        except ValueError as exc:
            raise ValueError(f'Retriever {name} not found') from exc
        except AttributeError as exc:
            logger.error(f'Retriever {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        return [
            retriever for retriever in self.type_to_loader_dict.keys()
            if retriever in settings.retrievers or settings.dev
        ]


retriever_creator = RetrieverCreator()
