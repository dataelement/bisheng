from bisheng.knowledge.domain.services.web_link_import_service import KnowledgeWebLinkImportService


def test_extract_markdown_removes_stylesheet_and_css_noise() -> None:
    html = """
    <html>
      <head>
        <title>测试文章</title>
        <link rel="stylesheet" href="https://example.com/main.css">
      </head>
      <body>
        <style>#app{display:none}.title{color:red}</style>
        <article>
          <h1>测试文章</h1>
          <p>这是第一段正文内容，用来验证网页链接导入时不会把 CSS 样式写进知识库。</p>
          <p>这是第二段正文内容，包含足够多的文字以通过正文质量检测，并保留真正的页面信息。</p>
        </article>
      </body>
    </html>
    """

    result = KnowledgeWebLinkImportService._extract_markdown(
        html,
        "https://example.com/article",
        "text/html",
    )

    assert "rel=\"stylesheet\"" not in result.markdown
    assert "display:none" not in result.markdown
    assert "#app" not in result.markdown
    assert "这是第一段正文内容" in result.markdown
    assert not result.needs_rendered_fallback


def test_spa_shell_triggers_rendered_fallback() -> None:
    html = """
    <html>
      <head><title>loading...</title></head>
      <body>
        <div id="root">loading... You need to enable JavaScript to run this app.</div>
      </body>
    </html>
    """

    result = KnowledgeWebLinkImportService._extract_markdown(
        html,
        "http://192.168.106.171:3002/",
        "text/html",
    )

    assert result.title == "192.168.106.171:3002"
    assert "动态渲染页面" in result.markdown
    assert result.needs_rendered_fallback


def test_rendered_extraction_wins_when_static_is_low_quality() -> None:
    static = KnowledgeWebLinkImportService._extract_markdown(
        "<html><title>loading...</title><body>loading...</body></html>",
        "https://example.com/app",
        "text/html",
    )
    rendered = KnowledgeWebLinkImportService._extract_markdown(
        """
        <html>
          <body>
            <main>
              <h1>渲染后的页面</h1>
              <p>这是浏览器渲染后得到的正文内容，已经不是静态 loading 壳。</p>
              <p>这里继续补充真实页面信息，确保长度足够并且不会被判定为低质量正文。</p>
            </main>
          </body>
        </html>
        """,
        "https://example.com/app",
        "text/html",
    )

    assert KnowledgeWebLinkImportService._should_use_rendered_extraction(static, rendered)
