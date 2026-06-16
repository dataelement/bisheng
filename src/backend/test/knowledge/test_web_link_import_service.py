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
          <p>这是第二段正文内容，包含足够多的文字以通过正文质量检测，并保留真正的页面信息，确保普通文章不会触发浏览器渲染兜底。</p>
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


def test_rendered_low_value_result_wins_over_static_spa_shell() -> None:
    static = KnowledgeWebLinkImportService._extract_markdown(
        "<html><title>loading...</title><body>loading...</body></html>",
        "http://192.168.106.171:3001/build/apps",
        "text/html",
    )
    rendered = KnowledgeWebLinkImportService._extract_markdown(
        """
        <html>
          <head><title>首钢股份知库工作台</title></head>
          <body>
            <main>
              <p>Convenient, Flexible, Reliable Enterprise-Level Large Model Application Development Platform</p>
              <a href="/register">Don't have an account? Register</a>
              <p>v2.6.0-beta2</p>
            </main>
          </body>
        </html>
        """,
        "http://192.168.106.171:3001/build/apps",
        "text/html",
    )

    assert rendered.low_value_reason
    assert KnowledgeWebLinkImportService._should_use_rendered_extraction(static, rendered)


def test_extract_markdown_absolutizes_links_and_filters_logo_images() -> None:
    html = """
    <html>
      <body>
        <main>
          <img src="/assets/logo.png" alt="logo_picture" />
          <h1>内网文章</h1>
          <p>这是一个内网知识页面，正文内容会保留下来，并且页面中的相对链接应当转换成绝对链接。</p>
          <p>这里继续补充正文信息，避免页面被误判成只有导航入口的低价值页面。</p>
          <a href="/docs/detail">查看详情</a>
        </main>
      </body>
    </html>
    """

    result = KnowledgeWebLinkImportService._extract_markdown(
        html,
        "http://192.168.106.171:3001/build/apps",
        "text/html",
    )

    assert "logo_picture" not in result.markdown
    assert "http://192.168.106.171:3001/docs/detail" in result.markdown
    assert "这是一个内网知识页面" in result.markdown


def test_login_page_is_marked_as_low_value() -> None:
    html = """
    <html>
      <head><title>首钢股份知识库工作台</title></head>
      <body>
        <main>
          <img src="/logo.svg" alt="logo_picture" />
          <p>Convenient, Flexible, Reliable Enterprise-Level Large Model Application Development Platform</p>
          <a href="/register">Don't have an account? Register</a>
          <p>v2.6.0-beta2</p>
        </main>
      </body>
    </html>
    """

    result = KnowledgeWebLinkImportService._extract_markdown(
        html,
        "http://192.168.106.171:3001/build/apps",
        "text/html",
    )

    assert result.low_value_reason
    assert "登录、注册或权限入口页面" in result.markdown
    assert "logo_picture" not in result.markdown


def test_navigation_page_login_urls_do_not_trigger_login_page_detection() -> None:
    html = """
    <html>
      <head><title>百度一下，你就知道</title></head>
      <body>
        <main>
          <a href="https://www.baidu.com/">百度首页</a>
          <a href="https://passport.baidu.com/v2/?login&tpl=mn&register=1">登录</a>
          <a href="https://news.baidu.com">新闻</a>
          <a href="https://map.baidu.com">地图</a>
          <a href="https://wenku.baidu.com">文库</a>
          <section>
            <h1>热搜新闻</h1>
            <p>这里展示搜索门户页面的公开导航内容和热点信息，虽然链接地址里可能带有认证参数，但页面本身不是账号表单。</p>
            <p>继续补充足够多的可见正文，确保这类门户页面不会因为链接地址中的认证参数而被误判。</p>
          </section>
        </main>
      </body>
    </html>
    """

    result = KnowledgeWebLinkImportService._extract_markdown(
        html,
        "https://www.baidu.com/",
        "text/html",
    )

    assert not result.low_value_reason
    assert "登录、注册或权限入口页面" not in result.markdown
    assert "热搜新闻" in result.markdown
