"""
Typora Style Markdown Transfer PDF Converter

Use Playwright (Chromium) will be HTML Render As PDF Professional Markdown Transfer PDF Exporter
Support Typora of style styles and mathematical expressions MathJax rendered

Feature:
- Pass Headless Chromium will be Markdown Convert file or string to stylized PDF
- Contains the default Typora Style CSS Styles
- Supports customization CSS Override
- MathJax Integration for LaTeX Mathematical rendering
- Configurable page formatting and margins
- Robust error handling and resource management

dependent:
    pip install playwright markdown
    playwright install chromium

Usage Sample:
    from to_pdf import MarkdownToPdfConverter
    converter = MarkdownToPdfConverter()
    converter.convert_file("README.md.md", "output.pdf")
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

from bisheng.common.utils.markdown_cmpnt.md_to_docx.parser.ext_md_syntax import ExtMdSyntax

logger = logging.getLogger(__name__)

# Dependent Import and Error Handling
try:
    import markdown
except ImportError as e:
    logger.error("Required dependency is missing: %s", e)
    raise ImportError("Please Install 'markdown' Package: pip install markdown") from e

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright Not available. Please install: pip install playwright && playwright install chromium")

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
    """Markdown Transfer PDF Conversion error custom exception."""
    pass


class MarkdownToPdfConverter:
    """
    Has Typora The power of style rendering Markdown Transfer PDF Converter

    Such provision will Markdown Convert file or string to PDF short circuit exist. 
    Use Playwright Render and include comprehensive error handling.
    """

    SUPPORTED_PAGE_FORMATS = {'A4', 'A3', 'A5', 'Letter', 'Legal', 'Tabloid'}
    DEFAULT_MARKDOWN_EXTENSIONS = [ExtMdSyntax(), 'extra', 'codehilite', 'toc', 'tables', 'sane_lists', 'fenced_code']
    DEFAULT_TIMEOUT = 60000  # ms

    def __init__(self,
                 default_css: Optional[str] = None,
                 enable_math: bool = False,
                 page_format: str = 'A4',
                 margin_mm: int = 20):
        """
        Initializes the converter with default settings.

        Args:
            default_css: Used instead of built-in Typora Custom Default for Styles CSS
            enable_math: enabled MathJax Math expression support
            page_format: Default page format (A4, A3, A5, Letter, Legal, Tabloid)
            margin_mm: Default margin (mm)

        Raises:
            MarkdownToPdfError: Automatically close purchase order after Playwright Unavailable or invalid parameters
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise MarkdownToPdfError(
                'Playwright Not installed. Please install: pip install playwright && playwright install chromium'
            )

        if page_format not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(
                f'Unsupported page format: {page_format}Supported Formats: {self.SUPPORTED_PAGE_FORMATS}'
            )

        if not isinstance(margin_mm, (int, float)) or margin_mm < 0:
            raise MarkdownToPdfError('Margins must be non-negative')

        self.default_css = default_css or DEFAULT_CSS
        self.enable_math = enable_math
        self.page_format = page_format
        self.margin_mm = margin_mm

        logger.info("MarkdownToPdfConverter Initialized, Format=%s Margin=%dmm",
                    page_format, margin_mm)

    def _validate_input_path(self, file_path: Union[str, Path]) -> Path:
        """Validate input file path and go back Path of research."""
        path = Path(file_path)

        if not path.exists():
            raise MarkdownToPdfError(f'This input file does not exist.: {path}')

        if not path.is_file():
            raise MarkdownToPdfError(f'Input path is not a file: {path}')

        if not path.suffix.lower() in {'.md', '.markdown', '.txt'}:
            logger.warning("Input file not available markdown extension: %s", path.suffix)

        return path

    def _validate_output_path(self, file_path: Union[str, Path]) -> Path:
        """Verify the output file path and make sure the directory exists."""
        path = Path(file_path)

        # Make sure the parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.suffix.lower() != '.pdf':
            logger.warning("Output file not available .pdf extension: %s", path.suffix)

        return path

    def _load_css_file(self, css_path: Union[str, Path]) -> str:
        """Load from file CSS Content with error handling."""
        try:
            css_file = Path(css_path)
            if not css_file.exists():
                raise MarkdownToPdfError(f'CSS File don\'t exists: {css_file}')

            with open(css_file, 'r', encoding='utf-8') as f:
                css_content = f.read().strip()

            if not css_content:
                logger.warning("CSS File is empty: %s", css_file)

            return css_content

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'read out CSS Doc. {css_path} Kalah: {e}') from e

    def render_markdown_to_html(self,
                                markdown_text: str,
                                custom_css: Optional[str] = None,
                                enable_math: Optional[bool] = None) -> str:
        """
        will be Markdown Convert text to with style and MathJax Supportive HTML。

        Args:
            markdown_text: To be converted Markdown Contents
            custom_css: Optional customizations CSSfor overriding default styles
            enable_math: Mathematical support for overriding instance settings

        Returns:
            Available for PDF Conversion Complete HTML Documentation

        Raises:
            MarkdownToPdfError: Automatically close purchase order after Markdown Failed to Process
        """
        if not isinstance(markdown_text, str):
            raise MarkdownToPdfError('Markdown Text must be a string')

        if not markdown_text.strip():
            logger.warning("SERVICES  Markdown Konten kosong")

        try:
            # Using the extension will Markdown Convert To HTML
            html_body = markdown.markdown(
                markdown_text,
                extensions=self.DEFAULT_MARKDOWN_EXTENSIONS
            )

            # OK CSS And MathJax Pengaturan
            css_content = custom_css or self.default_css
            use_math = enable_math if enable_math is not None else self.enable_math
            math_snippet = MATHJAX_SNIPPET if use_math else '\n'

            # Generate full HTML Documentation
            html_document = HTML_TEMPLATE.format(
                css=css_content,
                mathjax=math_snippet,
                body=html_body
            )

            logger.debug("Success will %d character (s) of Markdown Convert To HTML", len(markdown_text))
            return html_document

        except Exception as e:
            raise MarkdownToPdfError(f'will be Markdown Render As HTML Kalah: {e}') from e

    def convert_html_to_pdf(self,
                            html_content: str,
                            output_path: Union[str, Path],
                            page_format: Optional[str] = None,
                            margin_mm: Optional[int] = None) -> None:
        """
        Use Playwright will be HTML Convert content to PDF。

        Args:
            html_content: To be converted HTML Contents
            output_path: PDF SAVE PATH
            page_format: Override default page formatting
            margin_mm: Override default margin

        Raises:
            MarkdownToPdfError: Automatically close purchase order after PDF failed to transform
        """
        if not isinstance(html_content, str) or not html_content.strip():
            raise MarkdownToPdfError('HTML Content cannot be empty')

        output_file = self._validate_output_path(output_path)
        format_to_use = page_format or self.page_format
        margin_to_use = margin_mm if margin_mm is not None else self.margin_mm

        if format_to_use not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(f'Unsupported page format: {format_to_use}')

        # Create Temporary HTML Doc.
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

            logger.debug("Temporary Created HTML Doc.: %s", temp_html_path)

            # Use Playwright Convert To PDF
            self._render_pdf_with_playwright(temp_html_path, output_file, format_to_use, margin_to_use)

            logger.info("Slider Created Successfully. PDF: %s", output_file)

        except Exception as e:
            raise MarkdownToPdfError(f'will be HTML Convert To PDF Kalah: {e}') from e
        finally:
            # Clean Up Temp Files
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                    logger.debug("Temporary files cleaned: %s", temp_html_path)
                except OSError as e:
                    logger.warning("Clean Up Temp Files %s Kalah: %s", temp_html_path, e)

    def convert_html_to_pdf_bytes(self,
                                  html_content: str,
                                  page_format: Optional[str] = None,
                                  margin_mm: Optional[int] = None) -> bytes:
        """
        Use Playwright will be HTML Convert content to PDF Bytes of data.

        Args:
            html_content: To be converted HTML Contents
            page_format: Override default page formatting
            margin_mm: Override default margin

        Returns:
            PDF Bytes data of the file

        Raises:
            MarkdownToPdfError: Automatically close purchase order after PDF failed to transform
        """
        if not isinstance(html_content, str) or not html_content.strip():
            raise MarkdownToPdfError('HTML Content cannot be empty')

        format_to_use = page_format or self.page_format
        margin_to_use = margin_mm if margin_mm is not None else self.margin_mm

        if format_to_use not in self.SUPPORTED_PAGE_FORMATS:
            raise MarkdownToPdfError(f'Unsupported page format: {format_to_use}')

        # Create Temporary HTML Doc.
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

            logger.debug("Temporary Created HTML Doc.: %s", temp_html_path)

            # Use Playwright Convert To PDF Bytes of data
            pdf_bytes = self._render_pdf_bytes_with_playwright(temp_html_path, format_to_use, margin_to_use)

            logger.debug("Successfully Generated! PDF bytes data, size: %d bytes", len(pdf_bytes))
            return pdf_bytes

        except Exception as e:
            raise MarkdownToPdfError(f'will be HTML Convert To PDF Byte Data Failure: {e}') from e
        finally:
            # Clean Up Temp Files
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                    logger.debug("Temporary files cleaned: %s", temp_html_path)
                except OSError as e:
                    logger.warning("Clean Up Temp Files %s Kalah: %s", temp_html_path, e)

    def _render_pdf_with_playwright(self,
                                    html_file_path: str,
                                    output_path: Path,
                                    page_format: str,
                                    margin_mm: int) -> None:
        """<g id="Bold">Medical Treatment:</g> Playwright PDF The internal method of the build."""
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    file_url = f'file:///{html_file_path.replace(os.sep, "/")}'

                    logger.debug("Load in browser HTML: %s", file_url)
                    page.goto(file_url, timeout=self.DEFAULT_TIMEOUT)

                    # If enabled MathJax, waiting for typesetting to complete
                    if self.enable_math:
                        self._wait_for_mathjax(page)

                    # Build with specified settings PDF
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
            raise MarkdownToPdfError(f'Playwright PDF Generation Failed: {e}') from e

    def _render_pdf_bytes_with_playwright(self,
                                          html_file_path: str,
                                          page_format: str,
                                          margin_mm: int) -> bytes:
        """<g id="Bold">Medical Treatment:</g> Playwright PDF Internal method for byte data generation."""
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    file_url = f'file:///{html_file_path.replace(os.sep, "/")}'

                    logger.debug("Load in browser HTML: %s", file_url)
                    page.goto(file_url, timeout=self.DEFAULT_TIMEOUT)

                    # If enabled MathJax, waiting for typesetting to complete
                    if self.enable_math:
                        self._wait_for_mathjax(page)

                    # Build with specified settings PDF Bytes of data
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
            raise MarkdownToPdfError(f'Playwright PDF Byte data generation failed: {e}') from e

    def _wait_for_mathjax(self, page) -> None:
        """Menunggu MathJax Finish typography with timeout."""
        try:
            logger.debug("Menunggu MathJax Format...")
            page.wait_for_function(
                "() => window.MathJax && window.MathJax.typesetPromise",
                timeout=self.DEFAULT_TIMEOUT
            )
            page.evaluate("() => window.MathJax && window.MathJax.typesetPromise()")
            logger.debug("MathJax Typography complete")
        except Exception as e:
            logger.debug("MathJax Timeout or non-existent (this is normal): %s", e)

    def convert_file(self,
                     input_path: Union[str, Path],
                     output_path: Union[str, Path],
                     css_file: Optional[Union[str, Path]] = None,
                     **kwargs) -> None:
        """
        will be Markdown Convert file to PDF。

        Args:
            input_path: Masukkan Markdown FilePath
            output_path: Output PDF FilePath
            css_file: Optional customizations CSS FilePath
            **kwargs: Add Ons (page_format, margin_mm, enable_math)

        Raises:
            MarkdownToPdfError: If the conversion fails
        """
        input_file = self._validate_input_path(input_path)

        try:
            # read out Markdown Contents
            with open(input_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            logger.info("FROM %s read %d characters", input_file, len(markdown_content))

            # If customization is provided CSS, then load
            custom_css = None
            if css_file:
                custom_css = self._load_css_file(css_file)
                logger.info("FROM %s Customization loaded CSS", css_file)

            # Convert To PDF
            self.convert_string(markdown_content, output_path, custom_css, **kwargs)

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'Read input file {input_file} Kalah: {e}') from e

    def convert_string(self,
                       markdown_text: str,
                       output_path: Union[str, Path],
                       custom_css: Optional[str] = None,
                       **kwargs) -> None:
        """
        will be Markdown Convert string to PDF。

        Args:
            markdown_text: Markdown String content
            output_path: Output PDF FilePath
            custom_css: Optional customizations CSS Contents
            **kwargs: Add Ons (page_format, margin_mm, enable_math)

        Raises:
            MarkdownToPdfError: If the conversion fails
        """
        try:
            # will be Markdown Render As HTML
            html_content = self.render_markdown_to_html(
                markdown_text,
                custom_css=custom_css,
                enable_math=kwargs.get('enable_math')
            )

            # will be HTML Convert To PDF
            self.convert_html_to_pdf(
                html_content,
                output_path,
                page_format=kwargs.get('page_format'),
                margin_mm=kwargs.get('margin_mm')
            )

        except MarkdownToPdfError:
            raise
        except Exception as e:
            raise MarkdownToPdfError(f'failed to transform: {e}') from e

    def convert_file_to_bytes(self,
                              input_path: Union[str, Path],
                              css_file: Optional[Union[str, Path]] = None,
                              **kwargs) -> bytes:
        """
        will be Markdown Convert file to PDF Bytes of data.

        Args:
            input_path: Masukkan Markdown FilePath
            css_file: Optional customizations CSS FilePath
            **kwargs: Add Ons (page_format, margin_mm, enable_math)

        Returns:
            PDF Bytes data of the file

        Raises:
            MarkdownToPdfError: If the conversion fails
        """
        input_file = self._validate_input_path(input_path)

        try:
            # read out Markdown Contents
            with open(input_file, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            logger.info("FROM %s read %d characters", input_file, len(markdown_content))

            # If customization is provided CSS, then load
            custom_css = None
            if css_file:
                custom_css = self._load_css_file(css_file)
                logger.info("FROM %s Customization loaded CSS", css_file)

            # Convert To PDF Bytes of data
            return self.convert_string_to_bytes(markdown_content, custom_css, **kwargs)

        except (OSError, UnicodeDecodeError) as e:
            raise MarkdownToPdfError(f'Read input file {input_file} Kalah: {e}') from e

    def convert_string_to_bytes(self,
                                markdown_text: str,
                                custom_css: Optional[str] = None,
                                **kwargs) -> bytes:
        """
        will be Markdown Convert string to PDF Bytes of data.

        Args:
            markdown_text: Markdown String content
            custom_css: Optional customizations CSS Contents
            **kwargs: Add Ons (page_format, margin_mm, enable_math)

        Returns:
            PDF Bytes data of the file

        Raises:
            MarkdownToPdfError: If the conversion fails
        """
        try:
            # will be Markdown Render As HTML
            html_content = self.render_markdown_to_html(
                markdown_text,
                custom_css=custom_css,
                enable_math=kwargs.get('enable_math')
            )

            # will be HTML Convert To PDF Bytes of data
            return self.convert_html_to_pdf_bytes(
                html_content,
                page_format=kwargs.get('page_format'),
                margin_mm=kwargs.get('margin_mm')
            )

        except MarkdownToPdfError:
            raise
        except Exception as e:
            raise MarkdownToPdfError(f'failed to transform: {e}') from e


# Backward compatibility function
def render_markdown_to_html(md_text: str, css: str = None, enable_math: bool = False) -> str:
    """Legacy functions for backward compatibility."""
    converter = MarkdownToPdfConverter(enable_math=enable_math)
    return converter.render_markdown_to_html(md_text, custom_css=css, enable_math=enable_math)


def html_to_pdf_with_playwright(html: str, output_path: str, format: str = 'A4', margin_mm: int = 20):
    """Legacy functions for backward compatibility."""
    converter = MarkdownToPdfConverter(page_format=format, margin_mm=margin_mm)
    converter.convert_html_to_pdf(html, output_path, page_format=format, margin_mm=margin_mm)


def md_to_pdf(input_md: str, output_pdf: str, css_file: str = None, is_path: bool = False,
              enable_math: bool = False, page_format: str = 'A4', margin_mm: int = 20):
    """Legacy functions for backward compatibility."""
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
    will be Markdown Convert To PDF Handy function for byte data.

    Args:
        input_md: Markdown File path (if is_path=True or:  Markdown String
        css_file: Optional customizations CSS FilePath
        is_path: input_md Is file path
        enable_math: enabled MathJax Math expression support
        page_format: Post Format (A4, A3, A5, Letter, Legal, Tabloid)
        margin_mm: Margins (in mm)

    Returns:
        PDF Bytes data of the file

    Raises:
        MarkdownToPdfError: If the conversion fails
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
