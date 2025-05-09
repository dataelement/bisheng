
from pptx2md import convert, ConversionConfig
from pathlib import Path

def parser_pptx2md(
    pptx_file: str,
    md_file: str,
    image_dir: str = None,):

    # Basic usage
    convert(
        ConversionConfig(
            pptx_path=Path(pptx_file),
            output_path=Path(md_file),
            image_dir=Path(image_dir),
            disable_notes=True,
        )
    )