"""BishengLLM must report its wrapped client's provider to langchain.

deepagents' summarization (no model profile -> trigger at 170k tokens) checks two
counts: a chars/4 estimate, which undercounts Chinese about 3x, and the token usage
the provider reported on the last AIMessage. The second is used only when the
message's ``model_provider`` matches the model's ``ls_provider``. BishengLLM used to
report "bishengllm" while the client stamps "openai", so long Chinese task-mode runs
grew past 247k input tokens without a single compaction (cofco).
"""

from deepagents.backends import StateBackend
from deepagents.middleware.summarization import create_summarization_middleware
from langchain_core.messages import AIMessage, HumanMessage

from bisheng.core.ai.llm.chat_openai_reasoning import ChatOpenAIReasoning
from bisheng.llm.domain.llm.llm import BishengLLM


def _bisheng_llm() -> BishengLLM:
    inner = ChatOpenAIReasoning(api_key="sk-test", model="qwen3-235b-a22b", base_url="http://llm.invalid/v1")
    return BishengLLM.model_construct(llm=inner)


def _history(reported_total_tokens: int) -> list:
    return [
        HumanMessage(content="请整理中国信托公司完整名单" * 50),
        AIMessage(
            content="好的",
            response_metadata={"model_provider": "openai"},
            usage_metadata={
                "input_tokens": reported_total_tokens - 10,
                "output_tokens": 10,
                "total_tokens": reported_total_tokens,
            },
        ),
        HumanMessage(content="继续"),
    ]


def test_ls_provider_is_the_wrapped_clients():
    assert _bisheng_llm()._get_ls_params().get("ls_provider") == "openai"


def test_ls_params_without_wrapped_client_does_not_raise():
    assert BishengLLM.model_construct(llm=None)._get_ls_params().get("ls_provider") == "bishengllm"


def test_reported_usage_triggers_summarization():
    mw = create_summarization_middleware(_bisheng_llm(), StateBackend)
    messages = _history(reported_total_tokens=180_000)

    # The estimate alone is far below the 170k trigger ...
    assert mw._count_tokens(messages, None, None) < 170_000
    # ... but the provider-reported usage is above it.
    assert mw._should_summarize(messages, mw._count_tokens(messages, None, None)) is True


def test_reported_usage_below_trigger_does_not_summarize():
    mw = create_summarization_middleware(_bisheng_llm(), StateBackend)
    messages = _history(reported_total_tokens=50_000)

    assert mw._should_summarize(messages, mw._count_tokens(messages, None, None)) is False
