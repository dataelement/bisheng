
from pptx2md import convert, ConversionConfig
from pathlib import Path

def parser_pptx2md(
    pptx_file: str,
    md_file: str,
    image_dir: str = None,):
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
