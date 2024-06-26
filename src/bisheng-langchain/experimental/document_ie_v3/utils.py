import io

from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage


# 提取PDF文本内容（使用pdfminer低级API）
def extract_text_with_pdfminer_low_level(pdf_path):
    resource_manager = PDFResourceManager()
    fake_file_handle = io.StringIO()
    converter = TextConverter(resource_manager, fake_file_handle, laparams=LAParams())
    interpreter = PDFPageInterpreter(resource_manager, converter)
    with open(pdf_path, 'rb') as pdf_file:
        for page in PDFPage.get_pages(pdf_file, caching=True, check_extractable=True):
            interpreter.process_page(page)
        text = fake_file_handle.getvalue()
    # 关闭资源
    converter.close()
    fake_file_handle.close()
    return text


if __name__ == '__main__':
    pdf_path = './销售-风电机组构件健康状态与运行风险预警技术研究应用项目技术服务合同(1).pdf'
    text_with_pdfminer_low_level = extract_text_with_pdfminer_low_level(pdf_path)
    print(type(text_with_pdfminer_low_level))
    print(text_with_pdfminer_low_level)
    # with ThreadPoolExecutor(max_workers=50) as executor:
    #     executor.map(extract_text_with_pdfminer_low_level, pdf_name)
