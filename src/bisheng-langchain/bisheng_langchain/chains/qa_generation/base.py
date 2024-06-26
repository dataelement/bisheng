from __future__ import annotations

import json
import re
import logging
from langchain.docstore.document import Document
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForChainRun
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate
from langchain_core.pydantic_v1 import Field
from langchain_text_splitters import RecursiveCharacterTextSplitter, TextSplitter

from langchain.chains.base import Chain
from langchain.chains.llm import LLMChain
from langchain.chains.qa_generation.prompt import PROMPT_SELECTOR, CHAT_PROMPT, PROMPT

logger = logging.getLogger(__name__)


def parse_json(input_str: str) -> str:
    match = re.search(r'```(json)?(.*)```', input_str, re.DOTALL)
    if match is None:
        out_str = input_str
    else:
        out_str = match.group(2)

    out_str = out_str.strip()
    out_str = out_str.replace('```', '')
    return out_str


class QAGenerationChain(Chain):
    """Base class for question-answer generation chains."""

    documents: List[Document]
    llm_chain: LLMChain
    """LLM Chain that generates responses from user input and context."""
    k: Optional[int] = None
    """Number of questions to generate."""
    text_splitter: TextSplitter = Field(
        default=RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", " ", ""],
            chunk_size=1000,
            chunk_overlap=100,
        )
    )
    """Text splitter that splits the input into chunks."""
    input_key: str = "begin"
    """Key of the input to the chain."""
    output_key: str = "questions"
    """Key of the output of the chain."""

    @classmethod
    def from_llm(
        cls,
        documents: List[Document],
        llm: BaseLanguageModel,
        k: Optional[int] = None,
        chunk_size: int = 512,
        prompt: Optional[ChatPromptTemplate] = CHAT_PROMPT,
        **kwargs: Any,
    ) -> QAGenerationChain:
        """
        Create a QAGenerationChain from a language model.

        Args:
            llm: a language model
            prompt: a prompt template
            **kwargs: additional arguments

        Returns:
            a QAGenerationChain class
        """
        _prompt = PROMPT_SELECTOR.get_prompt(llm) if prompt is None else prompt
        chain = LLMChain(llm=llm, prompt=_prompt)
        text_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", " ", ""],
            chunk_size=chunk_size,
            chunk_overlap=50,
        )
        return cls(documents=documents, llm_chain=chain, k=k, text_splitter=text_splitter, **kwargs)

    @property
    def _chain_type(self) -> str:
        raise NotImplementedError

    @property
    def input_keys(self) -> List[str]:
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        return [self.output_key]

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, List]:
        contents = [doc.page_content for doc in self.documents]
        contents = '\n\n'.join(contents)
        docs = self.text_splitter.create_documents([contents])
        # len(qa) = min(len(docs), self.k)
        logger.info(f"Split {len(docs)} documents. Gen qa num: min({len(docs)}, {self.k}).")
        qa = ''
        qa_i = 0
        for doc in docs:
            try:
                results = self.llm_chain.generate([{"text": doc.page_content}], run_manager=run_manager)
                res = results.generations[0]
                qa += res[0].text
                qa_i += 1
            except Exception as e:
                logger.error(f"Failed to parse response Error: {e}")
                continue
            if self.k is not None and qa_i >= self.k:
                break
        return {self.output_key: qa}

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, List]:
        output = self._call(inputs, run_manager)
        return output
