from typing import Any, List, Tuple

from langchain.callbacks.manager import Callbacks
from langchain.chains.combine_documents.stuff import StuffDocumentsChain as StuffDocumentsChainOld
from langchain.docstore.document import Document


class StuffDocumentsChain(StuffDocumentsChainOld):

    token_max: int = -1

    def combine_docs(self,
                     docs: List[Document],
                     callbacks: Callbacks = None,
                     **kwargs: Any) -> Tuple[str, dict]:
        """Stuff all documents into one prompt and pass to LLM.

        Args:
            docs: List of documents to join together into one variable
            callbacks: Optional callbacks to pass along
            **kwargs: additional parameters to use to get inputs to LLMChain.

        Returns:
            The first element returned is the single string output. The second
            element returned is a dictionary of other keys to return.
        """
        inputs = self._get_inputs(docs, **kwargs)
        # print('inputs:', len(inputs['context']))
        # print('prompt_length:', self.prompt_length(docs, **kwargs))
        if self.token_max > 0:
            inputs[self.document_variable_name] = inputs[
                self.document_variable_name][:self.token_max]
        # Call predict on the LLM.
        return self.llm_chain.predict(callbacks=callbacks, **inputs), {}

    async def acombine_docs(self,
                            docs: List[Document],
                            callbacks: Callbacks = None,
                            **kwargs: Any) -> Tuple[str, dict]:
        """Stuff all documents into one prompt and pass to LLM.

        Args:
            docs: List of documents to join together into one variable
            callbacks: Optional callbacks to pass along
            **kwargs: additional parameters to use to get inputs to LLMChain.

        Returns:
            The first element returned is the single string output. The second
            element returned is a dictionary of other keys to return.
        """
        inputs = self._get_inputs(docs, **kwargs)
        if self.token_max > 0:
            inputs[self.document_variable_name] = inputs[
                self.document_variable_name][:self.token_max]
        # Call predict on the LLM.
        return await self.llm_chain.apredict(callbacks=callbacks, **inputs), {}
