from bisheng.common.utils.markdown_cmpnt.md_to_pdf import sanitize_html_for_pdf


def test_sanitize_html_for_pdf_blocks_local_file_and_relative_resources() -> None:
    html = """
    <p><img src="file:///etc/passwd" /></p>
    <p><img src="../../etc/passwd" /></p>
    <p><img src="https://example.com/a.png" /></p>
    <p><img src="data:image/png;base64,AAAA" /></p>
    <p><a href="#section-1">section</a></p>
    <p><a href="/etc/passwd">local</a></p>
    """

    sanitized = sanitize_html_for_pdf(html)

    assert "file:///etc/passwd" not in sanitized
    assert "../../etc/passwd" not in sanitized
    assert 'href="/etc/passwd"' not in sanitized
    assert 'src="https://example.com/a.png"' in sanitized
    assert 'src="data:image/png;base64,AAAA"' in sanitized
    assert 'href="#section-1"' in sanitized


def test_sanitize_html_for_pdf_removes_dangerous_tags_and_event_handlers() -> None:
    html = """
    <script>alert(1)</script>
    <iframe src="file:///etc/passwd"></iframe>
    <img src="https://example.com/a.png" onerror="alert(1)" style="background:url(file:///etc/passwd)" />
    <source srcset="file:///etc/passwd 1x, https://example.com/img.png 2x" />
    """

    sanitized = sanitize_html_for_pdf(html)

    assert "<script" not in sanitized
    assert "<iframe" not in sanitized
    assert "onerror=" not in sanitized
    assert "style=" not in sanitized
    assert "file:///etc/passwd" not in sanitized
    assert "https://example.com/img.png 2x" in sanitized


def test_sanitize_html_for_pdf_void_meta_does_not_swallow_body() -> None:
    """A disallowed VOID tag (``<meta>``, emitted un-closed by the docx md2html as
    ``<head><meta charset="utf-8">``) must not open a block that swallows the rest
    of the document. Regression for blank .docx/.pdf deliverables (the meta block
    never closed, so the whole <body> was dropped)."""
    html = '<head><meta charset="utf-8"></head>\n<body>\n<h1>标题</h1>\n<p>正文内容</p>\n</body>'

    sanitized = sanitize_html_for_pdf(html)

    assert "<meta" not in sanitized  # meta itself is still stripped
    assert "<h1>标题</h1>" in sanitized  # body survives the void meta
    assert "正文内容" in sanitized


def test_sanitize_html_for_pdf_block_tags_still_drop_inner_content() -> None:
    """The void-tag fix must NOT weaken real block tags: non-void disallowed tags
    (script/style) keep swallowing their inner content, surrounding text survives."""
    html = "<p>before</p><style>.x{color:red}</style><p>mid</p><script>evil()</script><p>end</p>"

    sanitized = sanitize_html_for_pdf(html)

    assert "color:red" not in sanitized
    assert "evil()" not in sanitized
    assert "before" in sanitized and "mid" in sanitized and "end" in sanitized
