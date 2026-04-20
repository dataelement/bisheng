from bisheng_langchain.rag import extract_info


class _FakeLLMChain:
    last_prompt = None
    last_context = None

    def __init__(self, llm, prompt):
        _FakeLLMChain.last_prompt = prompt

    def run(self, *, context):
        _FakeLLMChain.last_context = context
        return "ok"


def test_extract_abstract_uses_abstract_prompt_templates(monkeypatch):
    monkeypatch.setattr(extract_info, "LLMChain", _FakeLLMChain)

    result = extract_info.extract_abstract(llm=object(), text="文档正文")

    assert result == "ok"
    messages = _FakeLLMChain.last_prompt.format_messages(context="文档正文")
    assert "文档摘要专家" in messages[0].content
    assert "文档摘要：" in messages[1].content
    assert "生成或提取的标题" not in messages[1].content


def test_extract_abstract_keeps_custom_system_prompt(monkeypatch):
    monkeypatch.setattr(extract_info, "LLMChain", _FakeLLMChain)

    result = extract_info.extract_abstract(
        llm=object(),
        text="文档正文",
        abstract_prompt="自定义摘要系统提示词",
    )

    assert result == "ok"
    messages = _FakeLLMChain.last_prompt.format_messages(context="文档正文")
    assert messages[0].content == "自定义摘要系统提示词"
    assert "文档摘要：" in messages[1].content
