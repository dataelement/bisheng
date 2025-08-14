import inspect
from typing import Any, Dict, List, Optional

from langchain.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)
from langchain.chains.base import Chain
from langchain.schema import BaseRetriever, Document
from pydantic import Field


class RetrievalChain(Chain):
    """Chain to use to combine the documents."""

    input_key: str = 'query'  #: :meta private:
    output_key: str = 'result'  #: :meta private:
    retriever: BaseRetriever = Field(exclude=True)
    return_source_documents: bool = False

    def _get_docs(
        self,
        question: str,
        *,
        run_manager: CallbackManagerForChainRun,
    ) -> List[Document]:
        """Get docs."""
        return self.retriever.get_relevant_documents(question, callbacks=run_manager.get_child())

    async def _aget_docs(
        self,
        question: str,
        *,
        run_manager: AsyncCallbackManagerForChainRun,
    ) -> List[Document]:
        """Get docs."""
        return await self.retriever.aget_relevant_documents(question, callbacks=run_manager.get_child())

    @property
    def input_keys(self) -> List[str]:
        """Return the input keys.

        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        """Return the output keys.

        :meta private:
        """
        _output_keys = [self.output_key]
        if self.return_source_documents:
            _output_keys = _output_keys + ["source_documents"]
        return _output_keys

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        question = inputs[self.input_key]
        accepts_run_manager = "run_manager" in inspect.signature(self._get_docs).parameters
        if accepts_run_manager:
            docs = self._get_docs(question, run_manager=_run_manager)
        else:
            docs = self._get_docs(question)  # type: ignore[call-arg]

        if self.return_source_documents:
            return {self.output_key: docs, "source_documents": docs}
        else:
            return {self.output_key: docs}

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or AsyncCallbackManagerForChainRun.get_noop_manager()
        question = inputs[self.input_key]
        accepts_run_manager = "run_manager" in inspect.signature(self._aget_docs).parameters
        if accepts_run_manager:
            docs = await self._aget_docs(question, run_manager=_run_manager)
        else:
            docs = await self._aget_docs(question)  # type: ignore[call-arg]

        if self.return_source_documents:
            return {self.output_key: docs, "source_documents": docs}
        else:
            return {self.output_key: docs}
