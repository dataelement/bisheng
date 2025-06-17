import fitz  # PyMuPDF
import pandas as pd
import os
from uuid import uuid4

def convert_pdf_to_md(output_dir, pdf_path, doc_id):
    """
    将指定的 PDF 文件转换为 Markdown 文件，并保持内容的原有顺序。

    这个函数会提取 PDF 中的文本、表格和图片，并根据它们在页面上的
    垂直位置进行排序，然后整合到一个 Markdown 文件中。
    图片会作为独立文件保存在指定的输出目录中。

    Args:
        pdf_path (str): 输入的 PDF 文件路径。
        output_dir (str): 保存 Markdown 文件和图片的目录。
    """
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    md_filename = f"{doc_id}.md"
    md_filepath = os.path.join(output_dir, md_filename)
    
    img_dir = os.path.join(output_dir, f"images")
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    doc = None
    try:
        doc = fitz.open(pdf_path)
        md_content = ""
        image_counter = 1

        print(f"正在处理 PDF: {pdf_path}...")

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            
            page_elements = []

            # --- 1. 提取表格 ---
            tables = page.find_tables()
            if tables.tables:
                print(f"在第 {page_num + 1} 页找到 {len(tables.tables)} 个表格。")
                for tab in tables.tables:
                    if not tab.to_pandas().empty:
                        md_table = tab.to_pandas().to_markdown(index=False)
                        # 【修正点】将表格的 bbox 元组也转换为 fitz.Rect 对象
                        table_bbox = fitz.Rect(tab.bbox)
                        page_elements.append({'type': 'table', 'bbox': table_bbox, 'content': md_table})

            # --- 2. 提取图片 ---
            image_info_list = page.get_image_info(xrefs=True)
            if image_info_list:
                print(f"在第 {page_num + 1} 页找到 {len(image_info_list)} 张图片。")
                for img_info in image_info_list:
                    xref = img_info['xref']
                    if xref == 0: continue

                    base_image = doc.extract_image(xref)
                    if not base_image: continue
                    
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]

                    img_filename = f"image_{page_num+1}_{image_counter}.{image_ext}"
                    img_path = os.path.join(img_dir, img_filename)
                    
                    with open(img_path, "wb") as img_file:
                        img_file.write(image_bytes)
                    
                    md_image = f"![{img_filename}]({img_dir}/{img_filename})"
                    
                    image_bbox = fitz.Rect(img_info['bbox'])
                    page_elements.append({'type': 'image', 'bbox': image_bbox, 'content': md_image})
                    image_counter += 1

            # --- 3. 提取文本 ---
            table_bboxes = [fitz.Rect(tab.bbox) for tab in tables.tables] if tables.tables else []
            
            text_blocks = page.get_text("blocks")
            for b in text_blocks:
                block_rect = fitz.Rect(b[:4])
                block_text = b[4].strip()
                
                is_in_table = False
                for table_bbox in table_bboxes:
                    if block_rect.intersects(table_bbox):
                        is_in_table = True
                        break
                
                if block_text and not is_in_table:
                    page_elements.append({'type': 'text', 'bbox': block_rect, 'content': block_text})

            # --- 4. 按垂直位置对所有元素进行排序 ---
            page_elements.sort(key=lambda el: el['bbox'].y0)

            # --- 5. 从排序后的元素构建 Markdown 内容 ---
            for elem in page_elements:
                md_content += elem['content'] + "\n\n"
        
        with open(md_filepath, "w", encoding="utf-8") as md_file:
            md_file.write(md_content)

        print(f"转换成功！Markdown 文件保存在: {md_filepath}")
        print(f"图片保存在: {img_dir}")

    except Exception as e:
        print(f"处理 PDF 时发生错误: {e}")
        raise
        

    finally:
        if doc:
            doc.close()



def handler(cache_dir, file_or_url: str):
    doc_id = uuid4()
    ouput_dir = f"{cache_dir}/{doc_id}"
    convert_pdf_to_md(ouput_dir, file_or_url, doc_id)
    return f"{ouput_dir}/{doc_id}.md", f"{ouput_dir}/images", doc_id


# --- 使用示例 ---
if __name__ == '__main__':
    pdf_path = "/Users/tju/Documents/Resources/bisheng/pdf/20250617.pdf"
    # pdf_path = "/Users/tju/Documents/Resources/bisheng/pdf/2307.09288.pdf"
    output_directory = '/Users/tju/Desktop/output'
    md_file, local_image, doc_id =  handler(output_directory, pdf_path)
    print(md_file, local_image, doc_id)