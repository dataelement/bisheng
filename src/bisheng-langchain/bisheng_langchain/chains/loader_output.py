"""Chain that runs an arbitrary python function."""
import functools
import logging
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)
from langchain.chains.base import Chain
from langchain.docstore.document import Document

logger = logging.getLogger(__name__)


class LoaderOutputChain(Chain):
    """Chain that print the loader output.
    """
    documents: List[Document]
    input_key: str = "begin"  #: :meta private:
    output_key: str = "text"  #: :meta private:

    @staticmethod
    @functools.lru_cache
    def _log_once(msg: str) -> None:
        """Log a message once.

        :meta private:
        """
        logger.warning(msg)

    @property
    def input_keys(self) -> List[str]:
        """Expect input keys.

        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        """Return output keys.

        :meta private:
        """
        return [self.output_key]

    def _call(
        self,
        inputs: Dict[str, str],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, str]:
        contents = [doc.page_content for doc in self.documents]
        contents = '\n\n'.join(contents)
        # contents = json.dumps(contents, indent=2, ensure_ascii=False)
        output = {self.output_key: contents}
        return output

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        contents = [doc.page_content for doc in self.documents]
        contents = '\n\n'.join(contents)
        # contents = json.dumps(contents, indent=2, ensure_ascii=False)
        output = {self.output_key: contents}
        return output
