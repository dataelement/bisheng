import os
import threading
from uuid import uuid4

import fitz
from loguru import logger

pymu_lock = threading.Lock()


def convert_pdf_to_md(output_dir, pdf_path, doc_id):
    """
    will specify the PDF Convert file to Markdown files and keep the contents in their original order.

    This function extracts PDF Text, tables and pictures in and based on what they are on the page
    Vertical position to sort and then consolidate to one Markdown in the file.
    The image is saved as a separate file in the specified output directory.

    Args:
        pdf_path (str): Entered PDF FilePath
        output_dir (str): SAVING Markdown A directory of files and pictures.
    """
    # Make sure the output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    md_filename = f"{doc_id}.md"
    md_filepath = os.path.join(output_dir, md_filename)

    img_dir = os.path.join(output_dir, "images")
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    doc = None

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        raise Exception("The file is damaged.")
    try:
        md_content = ""
        image_counter = 1
        elements = []

        for page_num in range(len(doc)):
            with pymu_lock:
                page = doc.load_page(page_num)

                page_elements = []

                tables = page.find_tables()
                if tables.tables:
                    for tab in tables.tables:
                        if not tab.to_pandas().empty:
                            md_table = tab.to_pandas().to_markdown(index=False)
                            table_bbox = fitz.Rect(tab.bbox)
                            page_elements.append(
                                {
                                    "type": "table",
                                    "bbox": table_bbox,
                                    "content": md_table,
                                }
                            )

                image_info_list = page.get_image_info(xrefs=True)
                if image_info_list:
                    for img_info in image_info_list:
                        xref = img_info["xref"]
                        if xref == 0:
                            continue

                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        img_filename = f"image_{page_num + 1}_{image_counter}.{image_ext}"
                        img_path = os.path.join(img_dir, img_filename)

                        with open(img_path, "wb") as img_file:
                            img_file.write(image_bytes)

                        md_image = f"![{img_filename}]({img_dir}/{img_filename})"

                        image_bbox = fitz.Rect(img_info["bbox"])
                        page_elements.append(
                            {
                                "type": "image",
                                "bbox": image_bbox,
                                "content": md_image,
                                "image_filename": img_filename,
                            }
                        )
                        image_counter += 1

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
                        page_elements.append({"type": "text", "bbox": block_rect, "content": block_text})

            page_elements.sort(key=lambda el: el["bbox"].y0)

            for elem in page_elements:
                rect = elem["bbox"]
                layout_elem = {
                    "type": elem["type"],
                    "page": page_num,
                    "bbox": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    "content": elem["content"],
                }
                if elem.get("image_filename"):
                    layout_elem["image_filename"] = elem["image_filename"]
                elements.append(layout_elem)
                md_content += elem["content"] + "\n\n"

        with open(md_filepath, "w", encoding="utf-8") as md_file:
            md_file.write(md_content)
        return elements

    except Exception as e:
        logger.exception(f"Error processing pdf: {e}")
        raise Exception(
            f"Document parsing failed: {str(e)[-100:]}"
        )  # Capture last100characters to avoid overly long error messages
    finally:
        with pymu_lock:
            if doc:
                doc.close()


def align_pdf_elements(
    content: str,
    elements: list[dict],
    *,
    retain_images: bool = True,
) -> dict:
    """Map layout elements onto the final markdown so splitter indexes stay valid.

    Indexes are inclusive ``[start, end]`` and must be computed after
    post-processing / image-url rewrite: those steps can change string lengths.
    Image refs are located by alt text so a rewritten MinIO URL still matches.
    """
    bboxes: list[list[float]] = []
    pages: list[int] = []
    indexes: list[list[int]] = []
    types: list[str] = []
    search_from = 0

    for el in elements:
        if el.get("type") == "image" and not retain_images:
            continue
        needle = el.get("content") or ""
        if el.get("type") == "image" and el.get("image_filename"):
            needle = f"![{el['image_filename']}]"
        if not needle:
            continue

        pos = content.find(needle, search_from)
        if pos < 0:
            pos = content.find(needle)
        if pos < 0:
            continue

        if el.get("type") == "image" and needle.startswith("!["):
            close = content.find(")", pos + len(needle))
            end = close if close >= 0 else pos + len(needle) - 1
        else:
            end = pos + len(needle) - 1
        if end < pos:
            continue

        bbox = el.get("bbox") or []
        if len(bbox) < 4:
            continue

        bboxes.append([float(x) for x in bbox[:4]])
        pages.append(int(el.get("page", 0)))
        indexes.append([pos, end])
        types.append(el.get("type") or "text")
        search_from = end + 1

    return {
        "bboxes": bboxes,
        "pages": pages,
        "indexes": indexes,
        "types": types,
    }


def handler(cache_dir, file_or_url: str):
    doc_id = uuid4()
    ouput_dir = f"{cache_dir}/{doc_id}"
    elements = convert_pdf_to_md(ouput_dir, file_or_url, doc_id)
    return f"{ouput_dir}/{doc_id}.md", f"{ouput_dir}/images", doc_id, elements or []


def exec_thread_safe():
    pdf_path = "/Users/tju/Documents/Resources/pdf/bisheng/chen4.pdf"
    output_directory = "/Users/tju/Desktop/output"
    _md_file, _local_image, _doc_id, _elements = handler(output_directory, pdf_path)


if __name__ == "__main__":
    import multiprocessing

    processes = []
    for _ in range(10):
        process = multiprocessing.Process(target=exec_thread_safe)
        processes.append(process)
        process.start()

    for process in processes:
        process.join()

    threads = []
    for i in range(4):
        thread = threading.Thread(target=exec_thread_safe, name=f"Thread-{i}")
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()
