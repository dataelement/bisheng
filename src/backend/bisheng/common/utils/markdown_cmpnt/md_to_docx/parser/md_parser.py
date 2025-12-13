import markdown

from bisheng.common.utils.markdown_cmpnt.md_to_docx.parser.ext_md_syntax import ExtMdSyntax


def md2html(in_md: str):
    """
    Convert markdown file to html file
    :param in_md:
    :return:
    """
    html = markdown.markdown(in_md, extensions=[ExtMdSyntax(), 'tables', 'sane_lists', 'fenced_code'])

    return f"""<head><meta charset="utf-8"></head>\n<body>\n{html}</body>"""
