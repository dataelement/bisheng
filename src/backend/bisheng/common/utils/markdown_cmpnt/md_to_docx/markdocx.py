from bisheng.common.utils.markdown_cmpnt.md_to_pdf import sanitize_html_for_pdf
from bisheng.common.utils.markdown_cmpnt.md_to_docx.config.default_style import style_conf
from bisheng.common.utils.markdown_cmpnt.md_to_docx.parser.md_parser import md2html
from bisheng.common.utils.markdown_cmpnt.md_to_docx.provider.docx_processor import DocxProcessor


class MarkDocx:
    def __init__(self):
        self.docx_processor = DocxProcessor(style_conf=style_conf)

    def __call__(self, md_input: str):
        """
        Convert markdown file to docx file
        :param md_input:
        :return:
        """

        html_text = sanitize_html_for_pdf(md2html(md_input))

        # BuatdocxDoc.
        docx_file_byte, title_text = self.docx_processor.html2docx(html_text)

        return docx_file_byte, title_text
