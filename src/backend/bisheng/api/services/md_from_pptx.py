from pptx2md import convert, ConversionConfig
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
    file_name,
    knowledge_id,
):
    base_dir = f"/var/tmp/bisheng/{knowledge_id}"
    md_file_name = f"{base_dir}/{uuid4()}.md"
    image_dir = f"{base_dir}/images"
    parser_pptx2md(
        pptx_file=file_name,
        md_file=md_file_name,
        image_dir=image_dir,
    )
    # 上传图片,可以用异步
    # 替换md文件中的图片路径


if __name__ == "__main__":
    # Example usage:
    pptx_file = "/Users/tju/Resources/docs/ppt/you-lian.pptx"
    handler(pptx_file, "123456")
