from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain.callbacks.manager import AsyncCallbackManagerForChainRun, CallbackManagerForChainRun
from langchain.chains.conversational_retrieval.base import \
    ConversationalRetrievalChain as BaseConversationalRetrievalChain
from langchain_core.messages import BaseMessage

# Depending on the memory type and configuration, the chat history format may differ.
# This needs to be consolidated.
CHAT_TURN_TYPE = Union[Tuple[str, str], BaseMessage]

_ROLE_MAP = {'human': 'Human: ', 'ai': 'Assistant: '}


def _get_chat_history(chat_history: List[CHAT_TURN_TYPE]) -> str:
    buffer = ''
    for dialogue_turn in chat_history:
        if isinstance(dialogue_turn, BaseMessage):
            role_prefix = _ROLE_MAP.get(dialogue_turn.type, f'{dialogue_turn.type}: ')
            buffer += f'\n{role_prefix}{dialogue_turn.content}'
        elif isinstance(dialogue_turn, tuple):
            human = 'Human: ' + dialogue_turn[0]
            ai = 'Assistant: ' + dialogue_turn[1]
            buffer += '\n' + '\n'.join([human, ai])
        else:
            raise ValueError(f'Unsupported chat history format: {type(dialogue_turn)}.'
                             f' Full chat history: {chat_history} ')
    return buffer


class ConversationalRetrievalChain(BaseConversationalRetrievalChain):
    """ConversationalRetrievalChain is a chain you can use to have a conversation with a character from a series."""

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        question = inputs['question']
        get_chat_history = self.get_chat_history or _get_chat_history
        chat_history_str = get_chat_history(inputs['chat_history'])

        if chat_history_str:
            # callbacks = _run_manager.get_child()
            new_question = self.question_generator.run(question=question,
                                                       chat_history=chat_history_str)
        else:
            new_question = question
        accepts_run_manager = ('run_manager' in inspect.signature(self._get_docs).parameters)
        if accepts_run_manager:
            docs = self._get_docs(new_question, inputs, run_manager=_run_manager)
        else:
            docs = self._get_docs(new_question, inputs)  # type: ignore[call-arg]
        output: Dict[str, Any] = {}
        if self.response_if_no_docs_found is not None and len(docs) == 0:
            output[self.output_key] = self.response_if_no_docs_found
        else:
            new_inputs = inputs.copy()
            if self.rephrase_question:
                new_inputs['question'] = new_question
            new_inputs['chat_history'] = chat_history_str
            answer = self.combine_docs_chain.run(input_documents=docs,
                                                 callbacks=_run_manager.get_child(),
                                                 **new_inputs)
            output[self.output_key] = answer

        if self.return_source_documents:
            output['source_documents'] = docs
        if self.return_generated_question:
            output['generated_question'] = new_question
        return output

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or AsyncCallbackManagerForChainRun.get_noop_manager()
        question = inputs['question']
        get_chat_history = self.get_chat_history or _get_chat_history
        chat_history_str = get_chat_history(inputs['chat_history'])
        if chat_history_str:
            # callbacks = _run_manager.get_child()
            new_question = await self.question_generator.arun(question=question,
                                                              chat_history=chat_history_str)
        else:
            new_question = question
        accepts_run_manager = ('run_manager' in inspect.signature(self._aget_docs).parameters)
        if accepts_run_manager:
            docs = await self._aget_docs(new_question, inputs, run_manager=_run_manager)
        else:
            docs = await self._aget_docs(new_question, inputs)  # type: ignore[call-arg]

        output: Dict[str, Any] = {}
        if self.response_if_no_docs_found is not None and len(docs) == 0:
            output[self.output_key] = self.response_if_no_docs_found
        else:
            new_inputs = inputs.copy()
            if self.rephrase_question:
                new_inputs['question'] = new_question
            new_inputs['chat_history'] = chat_history_str
            answer = await self.combine_docs_chain.arun(input_documents=docs,
                                                        callbacks=_run_manager.get_child(),
                                                        **new_inputs)
            output[self.output_key] = answer

        if self.return_source_documents:
            output['source_documents'] = docs
        if self.return_generated_question:
            output['generated_question'] = new_question
        return output
