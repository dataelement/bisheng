import docx
from docx.shared import RGBColor
from docx.enum.dml import MSO_THEME_COLOR_INDEX

def add_hyperlink(paragraph, url, text):
    """
    Reference from：https://github.com/python-openxml/python-docx/issues/384

    A function that places a hyperlink within a paragraph object.
    :param paragraph: The paragraph we are adding the hyperlink to.
    :param url: A string containing the required url
    :param text: The text displayed for the url
    :return: The hyperlink object
    """
    # This gets access to the document.xml.rels file and gets a new relation id value
    part = paragraph.part
    r_id = part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    # Create the w:hyperlink tag and add needed values
    hyperlink = docx.oxml.shared.OxmlElement('w:hyperlink')
    hyperlink.set(docx.oxml.shared.qn('r:id'), r_id, )
    # Create a w:r element
    new_run = docx.oxml.shared.OxmlElement('w:r')
    # Create a new w:rPr element
    rPr = docx.oxml.shared.OxmlElement('w:rPr')
    # Join all the xml elements together add add the required text to the w:r element
    new_run.append(rPr)
    if text:
        new_run.text = text
    else:
        new_run.text = url
    # new_run.font.color.rgb = RGBColor(0,0,255)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    # paragraph.text = text

    r = paragraph.add_run()
    r._r.append(hyperlink)
    # A workaround for the lack of a hyperlink style (doesn't go purple after using the link)
    # Delete this if using a template that has the hyperlink style in it
    r.font.color.theme_color = MSO_THEME_COLOR_INDEX.HYPERLINK
    r.font.color.rgb = RGBColor(0, 0, 255)
    r.font.underline = True
    return hyperlink
