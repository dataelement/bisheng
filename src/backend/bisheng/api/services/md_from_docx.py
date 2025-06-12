import pypandoc
from loguru import logger
from pathlib import Path
from uuid import uuid4

try:
    # 尝试检查 pandoc 版本，如果失败则尝试下载
    pandoc_path = pypandoc.get_pandoc_path()
    logger.debug(f"Pandoc found at: {pandoc_path}")
except OSError:  # OSError 是 get_pandoc_path 在找不到时抛出的
    logger.debug("Pandoc not found. Attempting to download pandoc...")
    try:
        pypandoc.download_pandoc()  # 这会下载到 pypandoc 的包目录中
        logger.debug("Pandoc downloaded successfully by pypandoc.")
        # 你可能需要重新获取路径或 pypandoc 之后会自动找到
    except Exception as e_download:
        logger.debug(f"Failed to download pandoc using pypandoc: {e_download}")
        exit()  # 如果无法下载，则退出


def convert_doc_to_md_pandoc_high_quality(
    doc_path_str: str, output_md_str: str, image_dir_name: str = "media"
):
    """
    使用 Pandoc 将 .doc 或 .docx 文件高质量地转换为 Markdown，并提取图片。

    参数:
    doc_path_str (str): 输入的 Word 文档路径。
    output_md_str (str): 输出的 Markdown 文件路径。
    image_dir_name (str): 用于存放提取图片的子目录名称。此目录将创建在 Markdown 文件旁边。
    """
    doc_path = Path(doc_path_str)
    output_md_path = Path(output_md_str)

    if not doc_path.exists():
        logger.debug(f"错误：输入文件 {doc_path} 不存在。")
        return

    # 确保输出 Markdown 文件的父目录存在
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    # Pandoc 输出格式选项 (gfm 通常是好选择)
    pandoc_format_to = "gfm"

    # Pandoc 额外参数
    # --extract-media=目录名: 告诉 Pandoc 提取所有媒体文件（如图片）到指定的子目录。
    #                         Pandoc 会自动创建此目录，并使 Markdown 中的图片链接指向此目录。
    # --atx-headers: 如果你的 Pandoc 版本支持，此选项会使用 '#' 样式的标题。
    #                如果之前因版本问题报错，而你没有升级 Pandoc，可以注释掉此行。
    extra_args = [
        "--wrap=none",
        # '--atx-headers', # 如果 Pandoc 版本较旧导致此选项报错，请注释掉或升级 Pandoc
        f"--extract-media={image_dir_name}",  # 关键：提取图片到指定子目录
    ]

    # 图片将被提取到 output_md_path 同级目录下的 image_dir_name 子目录中
    # 例如：如果 output_md_path 是 "output/document.md" 且 image_dir_name 是 "images",
    # 图片将存放在 "output/images/" 目录下，链接会是 "images/image1.png"

    try:
        pypandoc.convert_file(
            source_file=str(doc_path),
            to=pandoc_format_to,
            outputfile=str(output_md_path),
            extra_args=extra_args,
        )
        logger.debug(f"Pandoc 转换完成: {output_md_path}")

    except RuntimeError as e:  # Pandoc 未找到或执行错误时常抛出 RuntimeError
        if "Unknown option --atx-headers" in str(e):
            logger.debug(
                "   错误提示 '--atx-headers' 选项未知，这通常意味着您的 Pandoc 版本较旧。"
            )
    except Exception as e:  # 其他潜在错误
        logger.debug(f"转换文件 {doc_path} 时发生未知错误: {e}")


def handler(cache_dir, file_name):
    """
    处理文件转换的主函数。

    参数:
    file_name (str): 输入的 Word 文档路径。
    knowledge_id (str): 知识 ID，用于生成输出文件名。
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
    # 定义测试参数
    test_cache_dir = "/Users/tju/Desktop"
    test_file_name = "/Users/tju/Resources/docs/docx/resume.docx"
    # test_file_name = "/Users/tju/Resources/docs/docx/2307.09288.docx"

    # 调用 handler 函数进行测试
    md_file_name, image_dir, doc_id = handler(
        cache_dir=test_cache_dir,
        file_name=test_file_name,
    )

    # 输出结果
    print(f"Markdown 文件路径: {md_file_name}")
    print(f"图片目录路径: {image_dir}")
    print(f"文档 ID: {doc_id}")
