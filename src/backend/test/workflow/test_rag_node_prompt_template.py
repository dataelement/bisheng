from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.messages import SystemMessage

from bisheng.workflow.nodes.prompt_template import PromptTemplateParser
from bisheng.workflow.nodes.rag.rag import RagNode


def test_rag_prompt_treats_system_prompt_braces_as_literal_text():
    """System prompts may contain JSON/ECharts examples with literal braces."""
    node = object.__new__(RagNode)
    node.id = "rag_json"
    node._system_prompt = PromptTemplateParser(
        template=(
            "Please answer with JSON only:\n"
            '{"title": {"text": "example"}, "series": [{"type": "bar"}]}\n'
            "Current date token should remain literal: {cur_date}"
        )
    )
    node._system_variables = node._system_prompt.extract()
    node._user_prompt = PromptTemplateParser(
        template=(
            "Question: {{#rag_json.user_question#}}\n"
            "Context: {{#rag_json.retrieved_result#}}\n"
            "Answer:"
        )
    )
    node._user_variables = node._user_prompt.extract()
    node._log_user_prompt = []
    node._log_system_prompt = []
    node.get_other_node_variable = lambda key: f"value for {key}"

    node.init_qa_prompt()

    assert isinstance(node._qa_prompt.messages[0], SystemMessage)
    assert node._qa_prompt.input_variables == ["context", "question"]
    assert node._log_system_prompt == [node._system_prompt.template]

    messages = node._qa_prompt.format_messages(
        question="summarize",
        context=[Document(page_content='PDF chunk with {"nested": {"value": 1}}')],
    )

    assert '{"title": {"text": "example"}' in messages[0].content
    assert "{cur_date}" in messages[0].content
    assert 'PDF chunk with {"nested": {"value": 1}}' in messages[-1].content
