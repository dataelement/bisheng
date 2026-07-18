from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.base import NormalPipeline
from bisheng.knowledge.rag.pipeline.transformer.content_safety import ContentSafetyTransformer
from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.exceptions import ContentSafetyViolation
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)


def _policy(
    *,
    enabled=True,
    words_types=None,
    custom_words='',
    auto_reply='命中敏感词',
    extra_config=None,
):
    return SimpleNamespace(
        enabled=enabled,
        words_types=words_types or ['custom'],
        custom_words=custom_words,
        auto_reply=auto_reply,
        extra_config=extra_config or {},
    )


def test_normalize_words_dedupes_and_keeps_phrase_spaces():
    assert SensitiveWordPolicyService.normalize_words(' alpha, beta，alpha\nfoo bar ') == [
        'alpha',
        'beta',
        'foo bar',
    ]


def test_check_text_counts_custom_word_hits(monkeypatch):
    monkeypatch.setattr(
        'bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy',
        lambda **kwargs: _policy(custom_words='敏感词\n禁用词'),
    )

    result = SensitiveWordPolicyService.check_text(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        text='敏感词出现一次，禁用词出现两次，禁用词。',
    )

    assert result.enabled is True
    assert {hit.word: hit.count for hit in result.hits} == {
        '敏感词': 1,
        '禁用词': 2,
    }
    assert result.auto_reply == '命中敏感词'


def test_check_text_uses_builtin_and_custom_words(monkeypatch):
    monkeypatch.setattr(
        'bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy',
        lambda **kwargs: _policy(words_types=['builtin', 'custom'], custom_words='自定义词'),
    )
    monkeypatch.setattr(
        SensitiveWordPolicyService,
        'load_builtin_words',
        classmethod(lambda cls: ('内置词',)),
    )

    result = SensitiveWordPolicyService.check_text(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        text='内置词和自定义词都命中',
    )

    assert {hit.word for hit in result.hits} == {'内置词', '自定义词'}


def test_disabled_or_empty_policy_is_not_effective(monkeypatch):
    monkeypatch.setattr(
        'bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy',
        lambda **kwargs: _policy(enabled=True, words_types=['custom'], custom_words=''),
    )

    result = SensitiveWordPolicyService.check_text(
        tenant_id=1,
        business_type=SensitiveWordBusinessType.KNOWLEDGE_SPACE_FILE_PARSE,
        text='任意内容',
    )

    assert result.enabled is False
    assert result.hits == []


def test_content_safety_transformer_raises_on_hits(monkeypatch):
    monkeypatch.setattr(
        'bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy',
        lambda **kwargs: _policy(custom_words='拦截词', auto_reply='不允许上传'),
    )

    transformer = ContentSafetyTransformer(tenant_id=1)

    with pytest.raises(ContentSafetyViolation) as exc:
        transformer.transform_documents([Document(page_content='这里包含拦截词')])

    assert exc.value.to_remark()['reason'] == 'sensitive_check'
    assert exc.value.to_remark()['auto_reply'] == '不允许上传'


def test_pipeline_stops_before_vector_write_when_content_safety_raises(monkeypatch):
    class FakeLoader:
        def load(self):
            return [Document(page_content='这里包含拦截词')]

    class FakeVectorStore:
        def __init__(self):
            self.called = False

        def add_documents(self, docs):
            self.called = True

    monkeypatch.setattr(
        'bisheng.sensitive_word.domain.models.sensitive_word_policy.SensitiveWordPolicyDao.get_policy',
        lambda **kwargs: _policy(custom_words='拦截词'),
    )

    vector_store = FakeVectorStore()
    pipeline = NormalPipeline(
        loader=FakeLoader(),
        transformers=[ContentSafetyTransformer(tenant_id=1)],
        vector_store=[vector_store],
    )

    with pytest.raises(ContentSafetyViolation):
        pipeline.run()

    assert vector_store.called is False
