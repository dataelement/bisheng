from markdown.inlinepatterns import SimpleTagInlineProcessor
from markdown.extensions import Extension


class ExtMdSyntax(Extension):
    """
    Extended Format Parsing
    """
    def extendMarkdown(self, md):
        # ==With Highlighted Text==
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()==(.+?)==', 'highlight'), 'highlight', 175)
        # ~~Strikethrough~~
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()~~(.+?)~~', 'strike'), 'strike', 2)
        # ^Subscript and superscript^
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()\^(.+?)\^', 'sup'), 'sup', 188)
        # ~Subscript~
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()~(.+?)~', 'sub'), 'sub', 1)
