import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pypandoc
from loguru import logger

if os.environ.get('BISHNEG_DOCX_MD_TIMEOUT'):
    CONVERT_TIMEOUT_SECONDS = int(os.environ.get('BISHNEG_DOCX_MD_TIMEOUT'))
else:
    CONVERT_TIMEOUT_SECONDS = 300

from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import convert_doc_to_docx

try:
    # Try checking pandoc version, try to download if it fails
    pandoc_path = pypandoc.get_pandoc_path()
    logger.debug(f"Pandoc found at: {pandoc_path}")
except OSError:  # OSError Yes  get_pandoc_path Thrown when not found
    logger.debug("Pandoc not found. Attempting to download pandoc...")
    try:
        pypandoc.download_pandoc()  # This will download to pypandoc in the package directory of
        logger.debug("Pandoc downloaded successfully by pypandoc.")
        # You may need to re-fetch the path or pypandoc After that, it will be automatically found
    except Exception as e_download:
        logger.debug(f"Failed to download pandoc using pypandoc: {e_download}")
        exit()  # Exit if unable to download


def convert_doc_to_md_pandoc_high_quality(
        doc_path_str: str, output_md_str: str, image_dir_name: str = "media", retry_convert_docx: bool = True,
):
    """
    Use Pandoc will be .doc OR .docx Convert files with high quality to Markdown, and extract the image.

    Parameters:
    doc_path_str (str): Entered Word Document path
    output_md_str (str): Output Markdown FilePath
    image_dir_name (str): The subdirectory name used to store the extracted image. This directory will be created in Markdown Next to the file.
    """
    doc_path = Path(doc_path_str)
    output_md_path = Path(output_md_str)

    if not doc_path.exists():
        logger.debug(f"Error: Input file {doc_path} %s does not exist.")
        return

    # Ensure Output Markdown The file's parent directory exists
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    # Pandoc Output Format Options (gfm Often a good choice)
    pandoc_format_to = "gfm"

    # Pandoc Extra arguments
    # --extract-media=Directory name: told Pandoc Extracts all media files, such as pictures, to the specified subdirectory.
    #                         Pandoc will automatically create this directory and Markdown The image link in points to this directory.
    # --atx-headers: If your Pandoc version support, this option will use '#' The title of the style.
    #                If you previously reported an error due to a version issue and you did not upgrade Pandoc, you can comment out this line.
    extra_args = [
        "--wrap=none",
        # '--atx-headers', # Automatically close purchase order after Pandoc Older version causes this option to report an error, please comment it out or upgrade Pandoc
        f"--extract-media={image_dir_name}",  # Key: Extract images to specified subdirectories
    ]

    # Images will be extracted to output_md_path Under the sibling directory image_dir_name In subdirectories
    # For example: if output_md_path Yes  "output/document.md" Dan image_dir_name Yes  "images",
    # Images will be stored in "output/images/" Under the directory, the link would be "images/image1.png"

    # Build the pandoc command directly so we can kill the process on timeout
    cmd = [
              pandoc_path,
              str(doc_path),
              "-t", pandoc_format_to,
              "-o", str(output_md_path),
          ] + extra_args

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _, stderr = proc.communicate(timeout=CONVERT_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            logger.debug(f"Pandoc exited with code {proc.returncode}: {err_msg}")
        else:
            logger.debug(f"Pandoc Conversion Complete: {output_md_path}")
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()  # drain pipes after kill
        logger.error(
            f"Convert File {doc_path} timed out after {CONVERT_TIMEOUT_SECONDS} seconds, pandoc process killed."
        )
        raise TimeoutError(
            f"Docx to Markdown conversion timed out after {CONVERT_TIMEOUT_SECONDS} seconds"
        )
    except Exception as e:
        logger.debug(f"Convert File {doc_path} An unknown error occurred while: {e}")

    # If the conversion fails, try todocxConvert to StandarddocxTry Again
    if not os.path.exists(output_md_path):
        if retry_convert_docx:
            output_dir = os.path.dirname(doc_path_str)
            output_dir = os.path.join(output_dir, "tmp")
            output_docx_path = convert_doc_to_docx(doc_path_str, output_dir)
            if not output_docx_path:
                raise RuntimeError("convert to docx failed")
            convert_doc_to_md_pandoc_high_quality(doc_path_str=output_docx_path, output_md_str=output_md_str,
                                                  image_dir_name=image_dir_name, retry_convert_docx=False)
            return
        raise RuntimeError("convert to md failed")


def handler(cache_dir, file_name):
    """
    The main function that handles file conversions.

    Parameters:
    file_name (str): Entered Word Document path
    knowledge_id (str): Knowledge ID, which is used to generate the output file name.
    """
    doc_id = str(uuid4())
    md_file_name = f"{cache_dir}/{doc_id}.md"
    local_image_dir = f"{cache_dir}/{doc_id}"
    convert_doc_to_md_pandoc_high_quality(
        doc_path_str=file_name,
        output_md_str=md_file_name,
        image_dir_name=local_image_dir,
    )
    return md_file_name, f"{local_image_dir}/media", doc_id


if __name__ == "__main__":
    # Define test parameters
    test_cache_dir = "/Users/tju/Desktop"
    test_file_name = "/Users/tju/Resources/docs/docx/resume.docx"
    # test_file_name = "/Users/tju/Resources/docs/docx/2307.09288.docx"

    # Recall handler Function is tested
    md_file_name, image_dir, doc_id = handler(
        cache_dir=test_cache_dir,
        file_name=test_file_name,
    )

    # Output Results
    print(f"Markdown FilePath: {md_file_name}")
    print(f"Picture directory path: {image_dir}")
    print(f"Documentation ID: {doc_id}")
