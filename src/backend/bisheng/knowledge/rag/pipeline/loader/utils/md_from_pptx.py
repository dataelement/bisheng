import os
import re
from pathlib import Path
from uuid import uuid4

from bisheng.pptx2md import convert, ConversionConfig


def parser_pptx2md(
        pptx_file: str,
        md_file: str,
        image_dir: str = None,
        enable_slides: bool = False,
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
            enable_slides=enable_slides,
        )
    )


def handler(
        cache_dir,
        file_path,
        enable_slides: bool = False,
):
    doc_id = str(uuid4())
    md_file_name = f"{cache_dir}/{doc_id}.md"
    image_dir = f"{cache_dir}/{doc_id}"
    parser_pptx2md(
        pptx_file=file_path,
        md_file=md_file_name,
        image_dir=image_dir,
        enable_slides=enable_slides,
    )

    if os.path.exists(md_file_name):
        with open(md_file_name, 'r', encoding='utf-8') as f:
            content = f.read()

        # pptx2md generates paths relative to the common path of md_file and image_dir,
        # which evaluates to `doc_id/img_name.ext`. Here we replace them with `image_dir/`.
        content = re.sub(rf'\]\({doc_id}/', f']({image_dir}/', content)
        content = re.sub(rf'src="{doc_id}/', f'src="{image_dir}/', content)

        with open(md_file_name, 'w', encoding='utf-8') as f:
            f.write(content)

    # Image,Can be used asynchronously
    # GantimdPicture path in file
    return md_file_name, image_dir, doc_id


if __name__ == "__main__":
    pptx_file = "/Users/tju/Resources/docs/ppt/you-lian.pptx"
    cache_dir = "/Users/tju/Desktop"

    md_file_name, image_dir, doc_id = handler(cache_dir, pptx_file)
    print(f"Markdown file: {md_file_name}")
    print(f"Image directory: {image_dir}")
    print(f"Document ID: {doc_id}")
