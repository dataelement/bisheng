from bisheng.pptx2md import convert, ConversionConfig
from pathlib import Path
from uuid import uuid4


def parser_pptx2md(
    pptx_file: str,
    md_file: str,
    image_dir: str = None,
):
    """
    Convert a PowerPoint file to Markdown format.
    Args:
        pptx_file (str): Path to the PowerPoint file.
        md_file (str): Path to the output Markdown file.
        image_dir (str, optional): Directory to save images. Defaults to None
    """
    # Basic usage
    convert(
        ConversionConfig(
            pptx_path=Path(pptx_file),
            output_path=Path(md_file),
            image_dir=Path(image_dir),
            disable_notes=True,
        )
    )


def handler(
    cache_dir,
    file_name,
):
    doc_id = str(uuid4())
    md_file_name = f"{cache_dir}/{doc_id}.md"
    image_dir = f"{cache_dir}/{doc_id}"
    parser_pptx2md(
        pptx_file=file_name,
        md_file=md_file_name,
        image_dir=image_dir,
    )
    # 上传图片,可以用异步
    # 替换md文件中的图片路径
    return md_file_name, image_dir, doc_id


if __name__ == "__main__":
    pptx_file = "/Users/tju/Resources/docs/ppt/you-lian.pptx"
    cache_dir = "/Users/tju/Desktop"

    md_file_name, image_dir, doc_id = handler(cache_dir, pptx_file)
    print(f"Markdown file: {md_file_name}")
    print(f"Image directory: {image_dir}")
    print(f"Document ID: {doc_id}")
