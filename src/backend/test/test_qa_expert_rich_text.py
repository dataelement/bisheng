from bisheng.qa_expert.domain.rich_text import (
    question_description_to_plain_text,
    sanitize_question_description,
)


def test_sanitize_question_description_keeps_allowed_structure():
    value = sanitize_question_description(
        '<p><strong>重点</strong><em>说明</em></p><ul><li>第一项</li></ul>'
        '<blockquote>引用</blockquote><pre><code>const value = 1;</code></pre>'
    )

    assert '<strong>重点</strong>' in value
    assert '<em>说明</em>' in value
    assert '<ul><li>第一项</li></ul>' in value
    assert '<blockquote>引用</blockquote>' in value
    assert '<pre><code>const value = 1;</code></pre>' in value


def test_sanitize_question_description_removes_attributes_and_active_content():
    value = sanitize_question_description(
        '<p onclick="alert(1)"><strong class="danger">安全</strong>'
        '<script>alert(1)</script><iframe src="https://bad.example"></iframe></p>'
    )

    assert value == '<p><strong>安全</strong></p>'
    assert 'onclick' not in value
    assert '<script' not in value
    assert '<iframe' not in value


def test_question_description_plain_text_has_no_html_tags():
    assert question_description_to_plain_text(
        '<p><strong>重点</strong></p><ul><li>第一项</li></ul>'
    ) == '重点 第一项'
