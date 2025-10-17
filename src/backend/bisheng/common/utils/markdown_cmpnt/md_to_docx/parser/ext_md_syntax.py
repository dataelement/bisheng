from markdown.inlinepatterns import SimpleTagInlineProcessor
from markdown.extensions import Extension


class ExtMdSyntax(Extension):
    """
    扩展格式解析
    """
    def extendMarkdown(self, md):
        # ==高亮文本==
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()==(.+?)==', 'highlight'), 'highlight', 175)
        # ~~删除线~~
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()~~(.+?)~~', 'strike'), 'strike', 2)
        # ^上标^
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()\^(.+?)\^', 'sup'), 'sup', 188)
        # ~下标~
        md.inlinePatterns.register(SimpleTagInlineProcessor(r'()~(.+?)~', 'sub'), 'sub', 1)
