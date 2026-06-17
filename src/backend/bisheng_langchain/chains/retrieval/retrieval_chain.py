import inspect
from typing import Any

from langchain_classic.callbacks.manager import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
)
from langchain_classic.chains.base import Chain
from langchain_classic.schema import BaseRetriever, Document
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
    ) -> list[Document]:
        """Get docs."""
        child_manager = run_manager.get_child()
        if hasattr(self.retriever, "invoke"):
            return self.retriever.invoke(question, config={"callbacks": child_manager})
        return self.retriever.get_relevant_documents(question, callbacks=child_manager)

    async def _aget_docs(
        self,
        question: str,
        *,
        run_manager: AsyncCallbackManagerForChainRun,
    ) -> list[Document]:
        """Get docs."""
        child_manager = run_manager.get_child()
        if hasattr(self.retriever, "ainvoke"):
            return await self.retriever.ainvoke(question, config={"callbacks": child_manager})
        return await self.retriever.aget_relevant_documents(question, callbacks=child_manager)

    @property
    def input_keys(self) -> list[str]:
        """Return the input keys.

        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> list[str]:
        """Return the output keys.

        :meta private:
        """
        _output_keys = [self.output_key]
        if self.return_source_documents:
            _output_keys = [*_output_keys, "source_documents"]
        return _output_keys

    def _call(
        self,
        inputs: dict[str, Any],
        run_manager: CallbackManagerForChainRun | None = None,
    ) -> dict[str, Any]:
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
        inputs: dict[str, Any],
        run_manager: AsyncCallbackManagerForChainRun | None = None,
    ) -> dict[str, Any]:
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
