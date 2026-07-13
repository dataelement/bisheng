import re

import nh3

ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "ul",
    "li",
    "blockquote",
    "pre",
    "code",
}


def sanitize_question_description(value: str | None) -> str:
    """净化专家问答问题描述, 仅保留受控富文本结构。"""
    if not value:
        return ""
    return nh3.clean(value, tags=ALLOWED_TAGS, attributes={}, strip_comments=True).strip()


def question_description_to_plain_text(value: str | None) -> str:
    """将已净化的描述转换为纯文本, 供内容检查和摘要使用。"""
    clean_html = sanitize_question_description(value)
    text = re.sub(r"</(?:p|li|blockquote|pre)>", " ", clean_html, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())
