import html
import os
import re

from bs4 import BeautifulSoup


def post_processing(file_path, retain_images=True):
    """
    (最终完整版)
    全面地将一个Markdown文件中的HTML标签转换为标准Markdown格式，并根据参数正确处理图片。
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        # 步骤 1: 图片处理 (最优先执行)
        if not retain_images:
            # 如果不保留图片，在任何转换前，先全局删除所有格式的图片
            content = re.sub(r"<img[^>]*>", "", content, flags=re.IGNORECASE)
            content = re.sub(
                r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", content, flags=re.DOTALL
            )
            content = re.sub(r"!\[.*?\]\(.*?\)", "", content, flags=re.DOTALL)
        else:
            # 如果保留图片，则只转换HTML的img标签为Markdown格式
            # 使用一个辅助函数来提取src和alt
            def _img_to_md(match):
                img_tag = match.group(0)
                src_match = re.search(r'src="([^"]+)"', img_tag, re.IGNORECASE)
                alt_match = re.search(r'alt="([^"]*)"', img_tag, re.IGNORECASE)
                src = src_match.group(1) if src_match else ""
                alt = alt_match.group(1) if alt_match else ""
                return f"![{alt}]({src})"

            content = re.sub(r"<img[^>]*>", _img_to_md, content, flags=re.IGNORECASE)

        # 步骤 2: 复杂HTML块级元素转换 (使用BeautifulSoup辅助)
        def _table_to_md(match):
            soup = BeautifulSoup(match.group(0), "html.parser")
            headers = [
                th.get_text(strip=True).replace("|", r"\|")
                for th in soup.find_all("th")
            ]
            if not headers:  # 如果没有<th>, 尝试把第一行<td>作为表头
                first_row = soup.find("tr")
                if not first_row:
                    return ""
                headers = [
                    td.get_text(strip=True).replace("|", r"\|")
                    for td in first_row.find_all("td")
                ]
                rows_html = soup.find_all("tr")[1:]
            else:
                rows_html = (
                    soup.find("tbody").find_all("tr")
                    if soup.find("tbody")
                    else soup.find_all("tr")[1:]
                )

            if not headers:
                return ""  # 空表格

            md_table = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            for row in rows_html:
                cols = [
                    td.get_text(strip=True).replace("\n", " ").replace("|", r"\|")
                    for td in row.find_all("td")
                ]
                # 补全单元格以匹配表头长度
                while len(cols) < len(headers):
                    cols.append("")
                md_table.append("| " + " | ".join(cols) + " |")
            return "\n\n" + "\n".join(md_table) + "\n\n"

        content = re.sub(
            r"<table[^>]*>.*?</table>",
            _table_to_md,
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 步骤 3: 其他块级和行内HTML标签转换 (主要使用正则)

        # 列表 (简化处理，将ul/ol/li转换为无序列表)
        content = re.sub(
            r"<li[^>]*>(.*?)</li>", r"\n- \1", content, flags=re.IGNORECASE | re.DOTALL
        )
        content = re.sub(r"</?(ul|ol)[^>]*>", "", content, flags=re.IGNORECASE)
        # 标题 h1-h6
        content = re.sub(
            r"<h([1-6]).*?>(.*?)</h\1>",
            lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2).strip() + "\n",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # 引用
        content = re.sub(
            r"<blockquote[^>]*>(.*?)</blockquote>",
            lambda m: "\n> " + m.group(1).strip().replace("\n", "\n> ") + "\n",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # 链接
        content = re.sub(
            r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
            r"[\2](\1)",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # 加粗
        content = re.sub(
            r"<(strong|b)>(.*?)</\1>",
            r"**\2**",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # 斜体
        content = re.sub(
            r"<(em|i)>(.*?)</\1>", r"*\2*", content, flags=re.IGNORECASE | re.DOTALL
        )
        # 删除线
        content = re.sub(
            r"<(del|s)>(.*?)</\1>", r"~~\2~~", content, flags=re.IGNORECASE | re.DOTALL
        )
        # 上标/下标
        content = re.sub(
            r"<sup>(.*?)</sup>", r"^\1^", content, flags=re.IGNORECASE | re.DOTALL
        )
        content = re.sub(
            r"<sub>(.*?)</sub>", r"~\1~", content, flags=re.IGNORECASE | re.DOTALL
        )
        # 行内代码
        content = re.sub(
            r"<code>(.*?)</code>", r"`\1`", content, flags=re.IGNORECASE | re.DOTALL
        )
        # 水平线
        content = re.sub(r"<hr[^>]*>", "\n---\n", content, flags=re.IGNORECASE)
        # 换行
        content = re.sub(r"<br\s*/?>", "  \n", content, flags=re.IGNORECASE)
        # 段落 (转换为换行)
        content = re.sub(r"</p>", "\n", content, flags=re.IGNORECASE)
        content = re.sub(r"<p[^>]*>", "\n", content, flags=re.IGNORECASE)
        # Span (移除标签，保留内容)
        content = re.sub(
            r"<span[^>]*>(.*?)</span>", r"\1", content, flags=re.IGNORECASE | re.DOTALL
        )

        # 步骤 4: 最终清理
        content = html.unescape(content)  # 解码HTML实体
        content = re.sub(r"\n{3,}", "\n\n", content.strip())  # 规范化空行

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)

    except FileNotFoundError:
        raise Exception(f"错误: 文件 {file_path} 未找到。")
    except Exception as e:
        raise Exception(f"处理文件时发生错误: {e}")


if __name__ == "__main__":
    # --- 使用方法 ---
    # 请将下面的路径替换为您要处理的.md文件的实际路径
    # markdown_file_to_process = "/path/to/your/markdown_file.md"
    markdown_file_to_process = (
        "/Users/tju/Desktop/d40c526e-2081-49c3-9603-83132ce88978.md"  # 示例，请替换
    )

    if os.path.exists(markdown_file_to_process):
        # 示例1: 转换HTML并保留图片
        post_processing(markdown_file_to_process, retain_images=True)

        # 示例2: 转换HTML并移除所有图片
        # post_processing_revised(markdown_file_to_process, retain_images=False)
    else:
        print(f"请将脚本中的 'your_markdown_file.md' 替换为真实的文件路径后再运行。")
