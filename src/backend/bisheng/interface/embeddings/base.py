from typing import Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.custom_lists import embedding_type_to_cls_dict
from bisheng.interface.embeddings.custom import CUSTOM_EMBEDDING
from bisheng.settings import settings
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.frontend_node.embeddings import EmbeddingFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class


class EmbeddingCreator(LangChainTypeCreator):
    type_name: str = 'embeddings'

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = embedding_type_to_cls_dict
            for name, embed in CUSTOM_EMBEDDING.items():
                # TODO: validate AgentType
                self.type_dict[name] = embed  # type: ignore
        return self.type_dict

    @property
    def frontend_node_class(self) -> Type[FrontendNode]:
        return EmbeddingFrontendNode

    def get_signature(self, name: str) -> Optional[Dict]:
        """Get the signature of an embedding."""
        try:
            if name in get_custom_nodes(self.type_name).keys():
                return get_custom_nodes(self.type_name)[name]
            else:
                return build_template_from_class(name, embedding_type_to_cls_dict)
        except ValueError as exc:
            raise ValueError(f'Embedding {name} not found') from exc

        except AttributeError as exc:
            logger.error(f'Embedding {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        names = []
        for _, embed in self.type_to_loader_dict.items():
            embed_name = (embed.function_name() if hasattr(embed, 'function_name') else embed.__name__)
            if embed_name in settings.embeddings or settings.dev:
                names.append(embed_name)
        return names


embedding_creator = EmbeddingCreator()
