from __future__ import annotations

import re
import json
import logging
import typing as t
import warnings
from typing import Any, Dict, List, Optional
from collections import defaultdict, namedtuple
from dataclasses import dataclass
from langchain_core.callbacks import CallbackManagerForChainRun
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import HumanMessagePromptTemplate, PromptTemplate

try:
    from llama_index.node_parser import SimpleNodeParser
    from llama_index.readers.schema import Document as LlamaindexDocument
    from llama_index.schema import BaseNode
except ImportError:
    raise ImportError(
        "llama_index must be installed to use this function. "
        "Please, install it with `pip install llama_index`."
    )
import numpy as np
import numpy.testing as npt
import pandas as pd
from langchain.prompts import ChatPromptTemplate
from langchain.docstore.document import Document
# from langchain.schema.document import Document as LangchainDocument
from langchain.chains.base import Chain
from numpy.random import default_rng
from tqdm import tqdm
from .prompt_v2 import (
    SEED_QUESTION_CHAT_PROMPT,
    SCORE_CONTEXT_CHAT_PROMPT,
    FILTER_QUESTION_CHAT_PROMPT,
    ANSWER_FORMULATE,
)
from .base import parse_json

logger = logging.getLogger(__name__)


def load_as_score(text):
    """
    validate and returns given text as score
    """
    pattern = r"^[\d.]+$"
    if not re.match(pattern, text):
        warnings.warn("Invalid score")
        score = 0.0
    else:
        score = eval(text)
    return score


def load_as_json(text):
    """
    validate and return given text as json
    """

    try:
        return json.loads(parse_json(text))
    except ValueError as e:
        warnings.warn(f"Invalid json: {e}")

    return {}


DEFAULT_TRAIN_DISTRIBUTION = {
    "simple": 1.0,
    "reasoning": 0.0,
    "multi_context": 0.0,
    "conditional": 0.0,
}

DataRow = namedtuple(
    "DataRow",
    [
        "question",
        "ground_truth_context",
        "ground_truth",
        "question_type",
        "episode_done",
    ],
)


@dataclass
class TrainDataset:
    """
    TrainDataset class
    """

    train_data: t.List[DataRow]

    def to_pandas(self) -> pd.DataFrame:
        data_samples = []
        for data in self.train_data:
            data = {
                "question": data.question,
                "ground_truth_context": data.ground_truth_context,
                "ground_truth": data.ground_truth,
                "question_type": data.question_type,
                "episode_done": data.episode_done,
            }
            data_samples.append(data)
        return pd.DataFrame.from_records(data_samples)


class TrainsetGenerator:
    """
    Ragas Train Set Generator

    Attributes
    ----------
    generator_llm: LangchainLLM
        LLM used for all the generator operations in the TrainGeneration paradigm.
    critique_llm: LangchainLLM
        LLM used for all the filtering and scoring operations in TrainGeneration
        paradigm.
    chunk_size: int
        The chunk size of nodes created from data.
    train_distribution : dict
        Distribution of different types of questions to be generated from given
        set of documents. Defaults to {"easy":0.1, "reasoning":0.4, "conversation":0.5}
    """

    def __init__(
            self,
            generator_llm: BaseLanguageModel,
            critic_llm: BaseLanguageModel,
            trainset_distribution: t.Optional[t.Dict[str, float]] = None,
            chunk_size: int = 1024,
            seed: int = 42,
            prompt: Optional[ChatPromptTemplate] = SEED_QUESTION_CHAT_PROMPT,
            filter_lowquality_context: bool = False,
            filter_lowquality_question: bool = False,
            answer_prompt: Optional[HumanMessagePromptTemplate] = ANSWER_FORMULATE,
    ) -> None:
        self.generator_llm = generator_llm
        self.critic_llm = critic_llm
        trainset_distribution = trainset_distribution or DEFAULT_TRAIN_DISTRIBUTION
        npt.assert_almost_equal(
            1,
            sum(trainset_distribution.values()),
            err_msg="Sum of distribution should be 1",
        )

        probs = np.cumsum(list(trainset_distribution.values()))
        types = trainset_distribution.keys()
        self.trainset_distribution = dict(zip(types, probs))
        self.chunk_size = chunk_size
        self.threshold = 5.0
        self.rng = default_rng(seed)
        self.prompt = prompt
        self.filter_lowquality_context = filter_lowquality_context
        self.filter_lowquality_question = filter_lowquality_question
        if answer_prompt is None:
            answer_prompt = ANSWER_FORMULATE
        self.answer_prompt = answer_prompt

    @classmethod
    def from_default(
            cls,
            llm: BaseLanguageModel,
            chunk_size: int = 512,
            trainset_distribution: dict = DEFAULT_TRAIN_DISTRIBUTION,
            prompt: Optional[ChatPromptTemplate] = SEED_QUESTION_CHAT_PROMPT,
            filter_lowquality_context: bool = False,
            filter_lowquality_question: bool = False,
            answer_prompt: Optional[PromptTemplate] = ANSWER_FORMULATE,
    ):
        generator_llm = llm
        critic_llm = llm
        return cls(
            generator_llm=generator_llm,
            critic_llm=critic_llm,
            chunk_size=chunk_size,
            trainset_distribution=trainset_distribution,
            prompt=prompt,
            filter_lowquality_context=filter_lowquality_context,
            filter_lowquality_question=filter_lowquality_question,
            answer_prompt=answer_prompt,
        )

    def _get_evolve_type(self) -> str:
        """
        Decides question evolution type based on probability
        """
        prob = self.rng.uniform(0, 1)
        return next(
            (
                key
                for key in self.trainset_distribution.keys()
                if prob <= self.trainset_distribution[key]
            ),
            "simple",
        )

    def _filter_context(self, context: str) -> bool:
        """
        context: str
            The input context

        Checks if the context is has information worthy of framing a question
        """
        prompt = SCORE_CONTEXT_CHAT_PROMPT.format_prompt(context=context)
        results = self.critic_llm(prompt.to_messages())
        output = results.content
        score = load_as_score(output)
        print('context score:', score)
        return score >= self.threshold

    def _seed_question(self, context: str) -> str:
        if self.prompt is None:
            prompt = SEED_QUESTION_CHAT_PROMPT.format_prompt(context=context)
        else:
            prompt = self.prompt.format_prompt(context=context)
        results = self.generator_llm(prompt.to_messages())
        return results.content

    def _filter_question(self, question: str) -> bool:
        prompt = FILTER_QUESTION_CHAT_PROMPT.format_prompt(question=question)
        results = self.critic_llm(prompt.to_messages())
        results = results.content
        json_results = load_as_json(results)
        print('filter question:', question, json_results)
        return json_results.get("verdict") != "No"

    def _qc_template(self, prompt, question, context) -> str:
        human_prompt = prompt.format(question=question, context=context)
        prompt = ChatPromptTemplate.from_messages([human_prompt])
        results = self.generator_llm(prompt.messages)
        return results.content

    def _generate_answer(self, question: str, context: t.List[str]) -> t.List[str]:
        return [
            self._qc_template(self.answer_prompt, qstn, context[i])
            for i, qstn in enumerate(question.split("\n"))
        ]

    def _remove_nodes(
            self, available_indices: t.List[BaseNode], node_idx: t.List
    ) -> t.List[BaseNode]:
        for idx in node_idx:
            available_indices.remove(idx)
        return available_indices

    def _generate_doc_nodes_map(
            self, document_nodes: t.List[BaseNode]
    ) -> t.Dict[str, t.List[BaseNode]]:
        doc_nodes_map: t.Dict[str, t.List[BaseNode]] = defaultdict(list)
        for node in document_nodes:
            if node.ref_doc_id:
                doc_nodes_map[node.ref_doc_id].append(node)

        return doc_nodes_map  # type: ignore

    def _get_neighbour_node(
            self, node: BaseNode, related_nodes: t.List[BaseNode]
    ) -> t.List[BaseNode]:
        if len(related_nodes) < 2:
            warnings.warn("No neighbors exists")
            return [node]
        idx = related_nodes.index(node)
        ids = [idx - 1, idx] if idx == (len(related_nodes) - 1) else [idx, idx + 1]
        return [related_nodes[idx] for idx in ids]

    def generate(
            self,
            documents: t.List[LlamaindexDocument] | t.List[Document],
            train_size: int,
    ) -> TrainDataset:
        if not isinstance(documents[0], (LlamaindexDocument, Document)):
            raise ValueError(
                "Trainset Generatation only supports LlamaindexDocuments or Documents"  # noqa
            )

        if isinstance(documents[0], Document):
            # cast to LangchainDocument since its the only case here
            documents = t.cast(t.List[Document], documents)
            documents = [
                LlamaindexDocument.from_langchain_format(doc) for doc in documents
            ]
        # Convert documents into nodes
        node_parser = SimpleNodeParser.from_defaults(
            chunk_size=self.chunk_size, chunk_overlap=0, include_metadata=True
        )
        documents = t.cast(t.List[LlamaindexDocument], documents)
        document_nodes: t.List[BaseNode] = node_parser.get_nodes_from_documents(
            documents=documents
        )
        # # maximum 1 seed question per node
        # if train_size > len(document_nodes):
        #     raise ValueError(
        #         """Maximum possible number of samples exceeded, 
        #                      reduce train_size or add more documents"""
        #     )

        available_nodes = document_nodes
        doc_nodes_map = self._generate_doc_nodes_map(document_nodes)
        count_neighbours = sum(len(val) > 1 for _, val in doc_nodes_map.items())
        if count_neighbours < len(documents) // 2:
            warnings.warn("Most documents are too short")

        count = 0
        samples = []
        pbar = tqdm(total=train_size)
        while count < train_size and available_nodes != []:
            print(count, train_size, len(available_nodes))
            evolve_type = self._get_evolve_type()
            curr_node = self.rng.choice(np.array(available_nodes), size=1)[0]
            available_nodes = self._remove_nodes(available_nodes, [curr_node])

            neighbor_nodes = doc_nodes_map[curr_node.source_node.node_id]

            # Append multiple nodes randomly to remove chunking bias
            size = self.rng.integers(1, 3)
            nodes = (
                self._get_neighbour_node(curr_node, neighbor_nodes)
                if size > 1 and evolve_type != "multi_context"
                else [curr_node]
            )

            text_chunk = " ".join([node.get_content() for node in nodes])
            if self.filter_lowquality_context:
                score = self._filter_context(text_chunk)
                if not score:
                    continue
            seed_question = self._seed_question(text_chunk)

            question = seed_question
            if self.filter_lowquality_question:
                is_valid_question = self._filter_question(question)
            else:
                is_valid_question = True
            if is_valid_question:
                context = [text_chunk] * len(question.split("\n"))
                is_conv = len(context) > 1
                answer = self._generate_answer(question, context)
                for i, (qstn, ctx, ans) in enumerate(
                        zip(question.split("\n"), context, answer)
                ):
                    episode_done = False if is_conv and i == 0 else True
                    samples.append(
                        DataRow(qstn, [ctx], [ans], evolve_type, episode_done)
                    )
                count += 1
                pbar.update(1)

        return TrainDataset(train_data=samples)


class QAGenerationChainV2(Chain):
    """Base class for question-answer generation chains."""

    documents: List[Document]
    generator: TrainsetGenerator
    """LLM Chain that generates responses from user input and context."""
    k: Optional[int] = None
    """Number of questions to generate."""
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
            filter_lowquality_context: bool = False,
            filter_lowquality_question: bool = False,
            question_prompt: Optional[ChatPromptTemplate] = SEED_QUESTION_CHAT_PROMPT,
            answer_prompt: Optional[HumanMessagePromptTemplate] = ANSWER_FORMULATE,
            **kwargs: Any,
    ) -> QAGenerationChainV2:
        """
        Create a QAGenerationChain from a language model.

        Args:
            llm: a language model
            question_prompt: a prompt template for generate question
            answer_prompt: a prompt template for generate answer
            **kwargs: additional arguments

        Returns:
            a QAGenerationChain class
        """
        generator = TrainsetGenerator.from_default(
            llm, 
            chunk_size=chunk_size, 
            prompt=question_prompt, 
            answer_prompt=answer_prompt,
            filter_lowquality_context=filter_lowquality_context, 
            filter_lowquality_question=filter_lowquality_question
        )
        return cls(documents=documents, generator=generator, k=k, **kwargs)

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
        for doc in self.documents:
            doc.metadata = {}
        if self.k is None:
            self.k = 1000
        dataset = self.generator.generate(documents=self.documents, train_size=self.k)
        df = dataset.to_pandas()
        qa_pairs = df.to_dict("records")
        qa = []
        for pair in qa_pairs:
            qa.append({
                "question": pair["question"],
                "answer": pair["ground_truth"][0],
                "context": pair["ground_truth_context"][0],
            })
        qa = f'```json\n{json.dumps(qa, ensure_ascii=False, indent=4)}\n```'
        return {self.output_key: qa}

    async def _acall(
            self,
            inputs: Dict[str, Any],
            run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, List]:
        output = self._call(inputs, run_manager)
        return output
