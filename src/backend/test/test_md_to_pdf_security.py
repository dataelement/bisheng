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

    assert 'file:///etc/passwd' not in sanitized
    assert '../../etc/passwd' not in sanitized
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

    assert '<script' not in sanitized
    assert '<iframe' not in sanitized
    assert 'onerror=' not in sanitized
    assert 'style=' not in sanitized
    assert 'file:///etc/passwd' not in sanitized
    assert 'https://example.com/img.png 2x' in sanitized
