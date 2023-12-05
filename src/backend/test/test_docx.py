from docx import Document


def show_sec(sec):
    print('---sec info---')
    print('page height', sec.page_height)
    print('page width', sec.page_width)
    print('page left margin', sec.left_margin)
    print('page right margin', sec.right_margin)
    print('page top margin', sec.top_margin)
    print('page bottom margin', sec.bottom_margin)


def show_para(para, doc):
    print('\n\n---para info---')
    print('para style', para.style.name)
    font = doc.styles[para.style.name].font
    print('para font', font.name, font.size)

    print('align', para.paragraph_format.alignment)
    print('left indent', para.paragraph_format.left_indent)
    print('right indent', para.paragraph_format.right_indent)
    print('first line indent', para.paragraph_format.first_line_indent)
    print('line space', para.paragraph_format.line_spacing)
    print('space before', para.paragraph_format.space_before)
    print('space after', para.paragraph_format.space_after)


def show_run_info(run, doc):
    print('---run info---')
    print('run style', [run.style.type, run.style.name, run.style.font.size])

    print('run part', run.part)
    print('run element', run.element)
    print('run font name', run.font.name)
    print('run font size', run.font.size)


def test(document):
    print('-------------DEBUG---------')
    secs = document.sections
    for sec in secs:
        show_sec(sec)

    paras = document.paragraphs
    for para in paras:
        show_para(para, document)
        for run in para.runs:
            show_run_info(run, document)
            print('run.text', [run.text])

    styles = document.styles
    for s in styles:
        print('style', s)
    print('---------------')

    core_properties = document.core_properties
    for idx, uu in enumerate(dir(core_properties)[27:]):
        print(idx, uu)


document = Document('bisheng.docx')
test(document)
