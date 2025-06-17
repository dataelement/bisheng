from typing import Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.custom_lists import embedding_type_to_cls_dict
from bisheng.interface.embeddings.custom import CUSTOM_EMBEDDING
from bisheng.interface.stts.custom import CUSTOM_STT
from bisheng.interface.ttss.custom import CUSTOM_TTS
from bisheng.settings import settings
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.frontend_node.embeddings import EmbeddingFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class


class TTSCreator(LangChainTypeCreator):
    type_name: str = 'TTS'

    @property
    def type_to_loader_dict(self) -> Dict:
        return CUSTOM_TTS

    def get_signature(self, name: str) -> Optional[Dict]:
        """Get the signature of an llm."""
        try:
            return build_template_from_class(name, CUSTOM_TTS)
        except ValueError as exc:
            raise ValueError('LLM not found') from exc

        except AttributeError as exc:
            logger.error(f'LLM {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        return [
            tts.__name__
            for tts in self.type_to_loader_dict.values()
            if tts.__name__ in settings.llms or settings.dev
        ]

tts_creator = TTSCreator()
