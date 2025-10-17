"""
Typora 风格的 Markdown 转 PDF 转换器

使用 Playwright (Chromium) 将 HTML 渲染为 PDF 的专业 Markdown 转 PDF 导出器，
支持 Typora 风格样式和数学表达式的 MathJax 渲染。

功能特性:
- 通过无头 Chromium 将 Markdown 文件或字符串转换为样式化的 PDF
- 包含默认的 Typora 风格 CSS 样式
- 支持自定义 CSS 覆盖
- MathJax 集成用于 LaTeX 数学渲染
- 可配置的页面格式和边距
- 健壮的错误处理和资源管理

依赖项:
    pip install playwright markdown
    playwright install chromium

使用示例:
    from to_pdf import MarkdownToPdfConverter
    converter = MarkdownToPdfConverter()
    converter.convert_file("README.md", "output.pdf")
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

from bisheng.common.utils.markdown_cmpnt.md_to_docx.parser.ext_md_syntax import ExtMdSyntax

logger = logging.getLogger(__name__)

# 依赖导入及错误处理
try:
    import markdown
except ImportError as e:
    logger.error("缺少必需的依赖项: %s", e)
    raise ImportError("请安装 'markdown' 包: pip install markdown") from e

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 不可用。请安装: pip install playwright && playwright install chromium")

DEFAULT_CSS = r"""
top: 6px;
font-size: 9px;
color: var(--muted-color);
background: transparent;
}


/* Tables */
table {
width: 100%;
border-collapse: collapse;
margin: 0 0 0.9em 0;
font-size: 11pt;
}
th, td {
border: 1px solid #e6ecf0;
padding: 8px 10px;
text-align: left;
}
th { background: #fafbfc; font-weight: 600; }


/* Images */
img { max-width: 100%; height: auto; display: block; margin: 0.5em 0; }


/* Caption support (if markdown-to-html generator provides figure/figcaption) */
figure { margin: 0 0 0.9em 0; }
figcaption { font-size: 10pt; color: var(--muted-color); text-align: center; margin-top: 0.35em; }


/* Table of contents (toc) */
.toc {
margin: 0 0 1em 0;
padding-left: 0;
list-style: none;
}
.toc li { margin: 0.25em 0; }
.toc a { color: var(--accent-color); }


/* Footnotes */
.footnotes { font-size: 10pt; border-top: 1px dashed var(--hr-color); margin-top: 1em; padding-top: 0.6em; }
.footnotes li { margin: 0.4em 0; }


/* Page break helpers */
.page-break { page-break-after: always; }
.page-break-before { page-break-before: always; }


/* Fixed header/footer for printing — Chromium will include them in the page content when using print() */
.header, .footer {
display: block;
position: fixed;
left: 0; right: 0;
color: var(--muted-color);
font-size: 9pt;
padding: 6px 12mm;
}
.header { top: 0; }
.footer { bottom: 0; }
.footer .page-number::after { content: counter(page); }


/* Print-specific rules */
@media print {
body { background: white; }
/* Hide interactive elements if present */
a[href]:after { content: ""; }
/* Avoid background colors bleeding if printer doesn't support it */
* { -webkit-print-color-adjust: exact; }
}


/* Small-screen fallback (not usually needed for print) */
@media screen and (max-width: 800px) {
#content { padding: 16px; }
}


/* MathJax tweaks */
.mjx-svg-href { vertical-align: middle; }


/* Accessibility tweaks */
:focus { outline: 2px dashed rgba(3,102,214,0.35); outline-offset: 2px; }


/* Utility classes */
.center { text-align: center; }
.right { text-align: right; }
.small { font-size: 10pt; color: var(--muted-color); }


/* End of CSS */
"""

MATHJAX_SNIPPET = r"""
<script>
window.MathJax = {
  tex: {inlineMath: [['$','$'], ['\\(','\\)']]},
  svg: {fontCache: 'global'}
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
"""

HTML_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
{css}
</style>
{mathjax}
</head>
<body>
{body}
</body>
</html>
"""


class MarkdownToPdfError(Exception):
    """Markdown 转 PDF 转换错误的自定义异常。"""
    pass


class MarkdownToPdfConverter:
    """
    具有 Typora 风格渲染的强大 Markdown 转 PDF 转换器。

    此类提供将 Markdown 文件或字符串转换为 PDF 的方法，
    使用 Playwright 进行渲染，并包含全面的错误处理。
    """

    SUPPORTED_PAGE_FORMATS = {'A4', 'A3', 'A5', 'Letter', 'Legal', 'Tabloid'}
    DEFAULT_MARKDOWN_EXTENSIONS = [ExtMdSyntax(), 'extra', 'codehilite', 'toc', 'tables', 'sane_lists', 'fenced_code']
    DEFAULT_TIMEOUT = 60000  # 毫秒

    def __init__(self,
                 default_css: Optional[str] = None,
                 enable_math: bool = False,
                 page_format: str = 'A4',
                 margin_mm: int = 20):
        """
        使用默认设置初始化转换器。

        Args:
            default_css: 用于替代内置 Typora 样式的自定义默认 CSS
            enable_math: 是否启用 MathJax 数学表达式支持
            page_format: 默认页面格式 (A4, A3, A5, Letter, Legal, Tabloid)
            margin_mm: 默认边距（毫米）

        Raises:
            MarkdownToPdfError: 如果 Playwright 不可用或参数无效
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise MarkdownToPdfError(
                'Playwright 未安装。请安装: pip install playwright && playwright install chromium'
            )

        if page_format not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(
                f'不支持的页面格式: {page_format}。支持的格式: {self.SUPPORTED_PAGE_FORMATS}'
            )

        if not isinstance(margin_mm, (int, float)) or margin_mm < 0:
            raise MarkdownToPdfError('边距必须是非负数')

        self.default_css = default_css or DEFAULT_CSS
        self.enable_math = enable_math
        self.page_format = page_format
        self.margin_mm = margin_mm

        logger.info("MarkdownToPdfConverter 已初始化，格式=%s，边距=%dmm",
                    page_format, margin_mm)

    def _validate_input_path(self, file_path: Union[str, Path]) -> Path:
        """验证输入文件路径并返回 Path 对象。"""
        path = Path(file_path)

        if not path.exists():
            raise MarkdownToPdfError(f'输入文件不存在: {path}')

        if not path.is_file():
            raise MarkdownToPdfError(f'输入路径不是文件: {path}')

        if not path.suffix.lower() in {'.md', '.markdown', '.txt'}:
            logger.warning("输入文件没有 markdown 扩展名: %s", path.suffix)

        return path

    def _validate_output_path(self, file_path: Union[str, Path]) -> Path:
        """验证输出文件路径并确保目录存在。"""
        path = Path(file_path)

        # 确保父目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.suffix.lower() != '.pdf':
            logger.warning("输出文件没有 .pdf 扩展名: %s", path.suffix)

        return path

    def _load_css_file(self, css_path: Union[str, Path]) -> str:
        """从文件加载 CSS 内容，带有错误处理。"""
        try:
            css_file = Path(css_path)
            if not css_file.exists():
                raise MarkdownToPdfError(f'CSS 文件不存在: {css_file}')

            with open(css_file, 'r', encoding='utf-8') as f:
                css_content = f.read().strip()

            if not css_content:
                logger.warning("CSS 文件为空: %s", css_file)

            return css_content

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'读取 CSS 文件 {css_path} 失败: {e}') from e

    def render_markdown_to_html(self,
                                markdown_text: str,
                                custom_css: Optional[str] = None,
                                enable_math: Optional[bool] = None) -> str:
        """
        将 Markdown 文本转换为带有样式和 MathJax 支持的 HTML。

        Args:
            markdown_text: 要转换的 Markdown 内容
            custom_css: 可选的自定义 CSS，用于覆盖默认样式
            enable_math: 覆盖实例设置的数学支持

        Returns:
            适用于 PDF 转换的完整 HTML 文档

        Raises:
            MarkdownToPdfError: 如果 Markdown 处理失败
        """
        if not isinstance(markdown_text, str):
            raise MarkdownToPdfError('Markdown 文本必须是字符串')

        if not markdown_text.strip():
            logger.warning("提供的 Markdown 内容为空")

        try:
            # 使用扩展将 Markdown 转换为 HTML
            html_body = markdown.markdown(
                markdown_text,
                extensions=self.DEFAULT_MARKDOWN_EXTENSIONS
            )

            # 确定 CSS 和 MathJax 设置
            css_content = custom_css or self.default_css
            use_math = enable_math if enable_math is not None else self.enable_math
            math_snippet = MATHJAX_SNIPPET if use_math else '\n'

            # 生成完整的 HTML 文档
            html_document = HTML_TEMPLATE.format(
                css=css_content,
                mathjax=math_snippet,
                body=html_body
            )

            logger.debug("成功将 %d 个字符的 Markdown 转换为 HTML", len(markdown_text))
            return html_document

        except Exception as e:
            raise MarkdownToPdfError(f'将 Markdown 渲染为 HTML 失败: {e}') from e

    def convert_html_to_pdf(self,
                            html_content: str,
                            output_path: Union[str, Path],
                            page_format: Optional[str] = None,
                            margin_mm: Optional[int] = None) -> None:
        """
        使用 Playwright 将 HTML 内容转换为 PDF。

        Args:
            html_content: 要转换的 HTML 内容
            output_path: PDF 保存路径
            page_format: 覆盖默认页面格式
            margin_mm: 覆盖默认边距

        Raises:
            MarkdownToPdfError: 如果 PDF 转换失败
        """
        if not isinstance(html_content, str) or not html_content.strip():
            raise MarkdownToPdfError('HTML 内容不能为空')

        output_file = self._validate_output_path(output_path)
        format_to_use = page_format or self.page_format
        margin_to_use = margin_mm if margin_mm is not None else self.margin_mm

        if format_to_use not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(f'不支持的页面格式: {format_to_use}')

        # 创建临时 HTML 文件
        temp_html_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.html',
                    delete=False,
                    encoding='utf-8'
            ) as temp_file:
                temp_html_path = temp_file.name
                temp_file.write(html_content)

            logger.debug("已创建临时 HTML 文件: %s", temp_html_path)

            # 使用 Playwright 转换为 PDF
            self._render_pdf_with_playwright(temp_html_path, output_file, format_to_use, margin_to_use)

            logger.info("成功创建 PDF: %s", output_file)

        except Exception as e:
            raise MarkdownToPdfError(f'将 HTML 转换为 PDF 失败: {e}') from e
        finally:
            # 清理临时文件
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                    logger.debug("已清理临时文件: %s", temp_html_path)
                except OSError as e:
                    logger.warning("清理临时文件 %s 失败: %s", temp_html_path, e)

    def convert_html_to_pdf_bytes(self,
                                  html_content: str,
                                  page_format: Optional[str] = None,
                                  margin_mm: Optional[int] = None) -> bytes:
        """
        使用 Playwright 将 HTML 内容转换为 PDF 字节数据。

        Args:
            html_content: 要转换的 HTML 内容
            page_format: 覆盖默认页面格式
            margin_mm: 覆盖默认边距

        Returns:
            PDF 文件的字节数据

        Raises:
            MarkdownToPdfError: 如果 PDF 转换失败
        """
        if not isinstance(html_content, str) or not html_content.strip():
            raise MarkdownToPdfError('HTML 内容不能为空')

        format_to_use = page_format or self.page_format
        margin_to_use = margin_mm if margin_mm is not None else self.margin_mm

        if format_to_use not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(f'不支持的页面格式: {format_to_use}')

        # 创建临时 HTML 文件
        temp_html_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.html',
                    delete=False,
                    encoding='utf-8'
            ) as temp_file:
                temp_html_path = temp_file.name
                temp_file.write(html_content)

            logger.debug("已创建临时 HTML 文件: %s", temp_html_path)

            # 使用 Playwright 转换为 PDF 字节数据
            pdf_bytes = self._render_pdf_bytes_with_playwright(temp_html_path, format_to_use, margin_to_use)

            logger.debug("成功生成 PDF 字节数据，大小: %d bytes", len(pdf_bytes))
            return pdf_bytes

        except Exception as e:
            raise MarkdownToPdfError(f'将 HTML 转换为 PDF 字节数据失败: {e}') from e
        finally:
            # 清理临时文件
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                    logger.debug("已清理临时文件: %s", temp_html_path)
                except OSError as e:
                    logger.warning("清理临时文件 %s 失败: %s", temp_html_path, e)

    def _render_pdf_with_playwright(self,
                                    html_file_path: str,
                                    output_path: Path,
                                    page_format: str,
                                    margin_mm: int) -> None:
        """处理 Playwright PDF 生成的内部方法。"""
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    file_url = f'file:///{html_file_path.replace(os.sep, "/")}'

                    logger.debug("在浏览器中加载 HTML: %s", file_url)
                    page.goto(file_url, timeout=self.DEFAULT_TIMEOUT)

                    # 如果启用了 MathJax，等待排版完成
                    if self.enable_math:
                        self._wait_for_mathjax(page)

                    # 使用指定设置生成 PDF
                    margin_config = {
                        'top': f'{margin_mm}mm',
                        'bottom': f'{margin_mm}mm',
                        'left': f'{margin_mm}mm',
                        'right': f'{margin_mm}mm'
                    }

                    page.pdf(
                        path=str(output_path),
                        format=page_format,
                        margin=margin_config,
                        print_background=True
                    )

                finally:
                    browser.close()

        except Exception as e:
            raise MarkdownToPdfError(f'Playwright PDF 生成失败: {e}') from e

    def _render_pdf_bytes_with_playwright(self,
                                          html_file_path: str,
                                          page_format: str,
                                          margin_mm: int) -> bytes:
        """处理 Playwright PDF 字节数据生成的内部方法。"""
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    file_url = f'file:///{html_file_path.replace(os.sep, "/")}'

                    logger.debug("在浏览器中加载 HTML: %s", file_url)
                    page.goto(file_url, timeout=self.DEFAULT_TIMEOUT)

                    # 如果启用了 MathJax，等待排版完成
                    if self.enable_math:
                        self._wait_for_mathjax(page)

                    # 使用指定设置生成 PDF 字节数据
                    margin_config = {
                        'top': f'{margin_mm}mm',
                        'bottom': f'{margin_mm}mm',
                        'left': f'{margin_mm}mm',
                        'right': f'{margin_mm}mm'
                    }

                    pdf_bytes = page.pdf(
                        format=page_format,
                        margin=margin_config,
                        print_background=True
                    )

                    return pdf_bytes

                finally:
                    browser.close()

        except Exception as e:
            raise MarkdownToPdfError(f'Playwright PDF 字节数据生成失败: {e}') from e

    def _wait_for_mathjax(self, page) -> None:
        """等待 MathJax 完成排版，带有超时处理。"""
        try:
            logger.debug("等待 MathJax 排版...")
            page.wait_for_function(
                "() => window.MathJax && window.MathJax.typesetPromise",
                timeout=self.DEFAULT_TIMEOUT
            )
            page.evaluate("() => window.MathJax && window.MathJax.typesetPromise()")
            logger.debug("MathJax 排版完成")
        except Exception as e:
            logger.debug("MathJax 超时或不存在（这是正常的）: %s", e)

    def convert_file(self,
                     input_path: Union[str, Path],
                     output_path: Union[str, Path],
                     css_file: Optional[Union[str, Path]] = None,
                     **kwargs) -> None:
        """
        将 Markdown 文件转换为 PDF。

        Args:
            input_path: 输入 Markdown 文件路径
            output_path: 输出 PDF 文件路径
            css_file: 可选的自定义 CSS 文件路径
            **kwargs: 附加选项 (page_format, margin_mm, enable_math)

        Raises:
            MarkdownToPdfError: 如果转换失败
        """
        input_file = self._validate_input_path(input_path)

        try:
            # 读取 Markdown 内容
            with open(input_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            logger.info("从 %s 读取了 %d 个字符", input_file, len(markdown_content))

            # 如果提供了自定义 CSS，则加载
            custom_css = None
            if css_file:
                custom_css = self._load_css_file(css_file)
                logger.info("从 %s 加载了自定义 CSS", css_file)

            # 转换为 PDF
            self.convert_string(markdown_content, output_path, custom_css, **kwargs)

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'读取输入文件 {input_file} 失败: {e}') from e

    def convert_string(self,
                       markdown_text: str,
                       output_path: Union[str, Path],
                       custom_css: Optional[str] = None,
                       **kwargs) -> None:
        """
        将 Markdown 字符串转换为 PDF。

        Args:
            markdown_text: Markdown 字符串内容
            output_path: 输出 PDF 文件路径
            custom_css: 可选的自定义 CSS 内容
            **kwargs: 附加选项 (page_format, margin_mm, enable_math)

        Raises:
            MarkdownToPdfError: 如果转换失败
        """
        try:
            # 将 Markdown 渲染为 HTML
            html_content = self.render_markdown_to_html(
                markdown_text,
                custom_css=custom_css,
                enable_math=kwargs.get('enable_math')
            )

            # 将 HTML 转换为 PDF
            self.convert_html_to_pdf(
                html_content,
                output_path,
                page_format=kwargs.get('page_format'),
                margin_mm=kwargs.get('margin_mm')
            )

        except MarkdownToPdfError:
            raise
        except Exception as e:
            raise MarkdownToPdfError(f'转换失败: {e}') from e

    def convert_file_to_bytes(self,
                              input_path: Union[str, Path],
                              css_file: Optional[Union[str, Path]] = None,
                              **kwargs) -> bytes:
        """
        将 Markdown 文件转换为 PDF 字节数据。

        Args:
            input_path: 输入 Markdown 文件路径
            css_file: 可选的自定义 CSS 文件路径
            **kwargs: 附加选项 (page_format, margin_mm, enable_math)

        Returns:
            PDF 文件的字节数据

        Raises:
            MarkdownToPdfError: 如果转换失败
        """
        input_file = self._validate_input_path(input_path)

        try:
            # 读取 Markdown 内容
            with open(input_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            logger.info("从 %s 读取了 %d 个字符", input_file, len(markdown_content))

            # 如果提供了自定义 CSS，则加载
            custom_css = None
            if css_file:
                custom_css = self._load_css_file(css_file)
                logger.info("从 %s 加载了自定义 CSS", css_file)

            # 转换为 PDF 字节数据
            return self.convert_string_to_bytes(markdown_content, custom_css, **kwargs)

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'读取输入文件 {input_file} 失败: {e}') from e

    def convert_string_to_bytes(self,
                                markdown_text: str,
                                custom_css: Optional[str] = None,
                                **kwargs) -> bytes:
        """
        将 Markdown 字符串转换为 PDF 字节数据。

        Args:
            markdown_text: Markdown 字符串内容
            custom_css: 可选的自定义 CSS 内容
            **kwargs: 附加选项 (page_format, margin_mm, enable_math)

        Returns:
            PDF 文件的字节数据

        Raises:
            MarkdownToPdfError: 如果转换失败
        """
        try:
            # 将 Markdown 渲染为 HTML
            html_content = self.render_markdown_to_html(
                markdown_text,
                custom_css=custom_css,
                enable_math=kwargs.get('enable_math')
            )

            # 将 HTML 转换为 PDF 字节数据
            return self.convert_html_to_pdf_bytes(
                html_content,
                page_format=kwargs.get('page_format'),
                margin_mm=kwargs.get('margin_mm')
            )

        except MarkdownToPdfError:
            raise
        except Exception as e:
            raise MarkdownToPdfError(f'转换失败: {e}') from e


# 向后兼容函数
def render_markdown_to_html(md_text: str, css: str = None, enable_math: bool = False) -> str:
    """用于向后兼容的遗留函数。"""
    converter = MarkdownToPdfConverter(enable_math=enable_math)
    return converter.render_markdown_to_html(md_text, custom_css=css, enable_math=enable_math)


def html_to_pdf_with_playwright(html: str, output_path: str, format: str = 'A4', margin_mm: int = 20):
    """用于向后兼容的遗留函数。"""
    converter = MarkdownToPdfConverter(page_format=format, margin_mm=margin_mm)
    converter.convert_html_to_pdf(html, output_path, page_format=format, margin_mm=margin_mm)


def md_to_pdf(input_md: str, output_pdf: str, css_file: str = None, is_path: bool = False,
              enable_math: bool = False, page_format: str = 'A4', margin_mm: int = 20):
    """用于向后兼容的遗留函数。"""
    converter = MarkdownToPdfConverter(
        enable_math=enable_math,
        page_format=page_format,
        margin_mm=margin_mm
    )

    if is_path:
        converter.convert_file(input_md, output_pdf, css_file=css_file)
    else:
        custom_css = None
        if css_file:
            custom_css = converter._load_css_file(css_file)
        converter.convert_string(input_md, output_pdf, custom_css=custom_css)


def md_to_pdf_bytes(input_md: str, css_file: str = None, is_path: bool = False,
                    enable_math: bool = False, page_format: str = 'A4', margin_mm: int = 20) -> bytes:
    """
    将 Markdown 转换为 PDF 字节数据的便捷函数。

    Args:
        input_md: Markdown 文件路径（如果 is_path=True）或 Markdown 字符串
        css_file: 可选的自定义 CSS 文件路径
        is_path: input_md 是否为文件路径
        enable_math: 是否启用 MathJax 数学表达式支持
        page_format: 页面格式 (A4, A3, A5, Letter, Legal, Tabloid)
        margin_mm: 边距（毫米）

    Returns:
        PDF 文件的字节数据

    Raises:
        MarkdownToPdfError: 如果转换失败
    """
    converter = MarkdownToPdfConverter(
        enable_math=enable_math,
        page_format=page_format,
        margin_mm=margin_mm
    )

    if is_path:
        return converter.convert_file_to_bytes(input_md, css_file=css_file)
    else:
        custom_css = None
        if css_file:
            custom_css = converter._load_css_file(css_file)
        return converter.convert_string_to_bytes(input_md, custom_css=custom_css)
