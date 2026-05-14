import html
import os
import re

from bs4 import BeautifulSoup


def post_processing(file_path, retain_images=True):
    """
    (Final full version)
    Comprehensively combine oneMarkdownin the fileHTMLConvert tags to standardMarkdownFormat and process the picture correctly according to the parameters.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()

        # Step 1: Image Handling (Top Priority Execution)
        if not retain_images:
            # If the image is not preserved, delete the image in all formats globally before any conversion
            content = re.sub(r"<img[^>]*>", "", content, flags=re.IGNORECASE)
            content = re.sub(
                r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", content, flags=re.DOTALL
            )
            content = re.sub(r"!\[.*?\]\(.*?\)", "", content, flags=re.DOTALL)
        else:
            # Convert only if image is preservedHTMLright of privacyimgTaggedMarkdownFormat
            # Use a helper function to extractsrcAndalt
            def _img_to_md(match):
                img_tag = match.group(0)
                src_match = re.search(r'src="([^"]+)"', img_tag, re.IGNORECASE)
                alt_match = re.search(r'alt="([^"]*)"', img_tag, re.IGNORECASE)
                src = src_match.group(1) if src_match else ""
                alt = alt_match.group(1) if alt_match else ""
                return f"![{alt}]({src})"

            content = re.sub(r"<img[^>]*>", _img_to_md, content, flags=re.IGNORECASE)

        # Step 2: ComplexityHTMLBlock Level Element Conversion (UseBeautifulSoupSupport)
        def _table_to_md(match):
            soup = BeautifulSoup(match.group(0), "html.parser")
            headers = [
                th.get_text(strip=True).replace("|", r"\|")
                for th in soup.find_all("th")
            ]
            if not headers:  # If no evidence of   microbial<th>, Try putting the first line<td>As table header
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
                return ""  # Empty forms

            md_table = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            for row in rows_html:
                cols = [
                    td.get_text(strip=True).replace("\n", " ").replace("|", r"\|")
                    for td in row.find_all("td")
                ]
                # Fill the cell to match the header length
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

        # Step 3: Other block level and inlineHTMLTag transformation (Mainly using regular)

        # Vertical (Simplify processing byul/ol/liConvert to unordered list)
        content = re.sub(
            r"<li[^>]*>(.*?)</li>", r"\n- \1", content, flags=re.IGNORECASE | re.DOTALL
        )
        content = re.sub(r"</?(ul|ol)[^>]*>", "", content, flags=re.IGNORECASE)
        # Title h1-h6
        content = re.sub(
            r"<h([1-6]).*?>(.*?)</h\1>",
            lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2).strip() + "\n",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Cite
        content = re.sub(
            r"<blockquote[^>]*>(.*?)</blockquote>",
            lambda m: "\n> " + m.group(1).strip().replace("\n", "\n> ") + "\n",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Links
        content = re.sub(
            r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
            r"[\2](\1)",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # bolded
        content = re.sub(
            r"<(strong|b)>(.*?)</\1>",
            r"**\2**",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Italic
        content = re.sub(
            r"<(em|i)>(.*?)</\1>", r"*\2*", content, flags=re.IGNORECASE | re.DOTALL
        )
        # Strikethrough
        content = re.sub(
            r"<(del|s)>(.*?)</\1>", r"~~\2~~", content, flags=re.IGNORECASE | re.DOTALL
        )
        # Subscript and superscript/Subscript
        content = re.sub(
            r"<sup>(.*?)</sup>", r"^\1^", content, flags=re.IGNORECASE | re.DOTALL
        )
        content = re.sub(
            r"<sub>(.*?)</sub>", r"~\1~", content, flags=re.IGNORECASE | re.DOTALL
        )
        # Inline code
        content = re.sub(
            r"<code>(.*?)</code>", r"`\1`", content, flags=re.IGNORECASE | re.DOTALL
        )
        # Horizontal Line
        content = re.sub(r"<hr[^>]*>", "\n---\n", content, flags=re.IGNORECASE)
        # Line Wrap
        content = re.sub(r"<br\s*/?>", "  \n", content, flags=re.IGNORECASE)
        # Paragraphs (Convert to Line Break)
        content = re.sub(r"</p>", "\n", content, flags=re.IGNORECASE)
        content = re.sub(r"<p[^>]*>", "\n", content, flags=re.IGNORECASE)
        # Span (Remove tags, keep content)
        content = re.sub(
            r"<span[^>]*>(.*?)</span>", r"\1", content, flags=re.IGNORECASE | re.DOTALL
        )

        # Step 4: Final cleanup
        content = html.unescape(content)  # Code BreakingHTMLEntity
        content = re.sub(r"\n{3,}", "\n\n", content.strip())  # Normalize Blank Rows

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)

    except FileNotFoundError:
        raise Exception(f"Error-free: Doc. {file_path} Nothing found.")
    except Exception as e:
        raise Exception(f"Error processing file: {e}")


if __name__ == "__main__":
    # --- Methods Used ---
    # Please replace the path below with the one you want to process.mdActual path of the file
    # markdown_file_to_process = "/path/to/your/markdown_file.md"
    markdown_file_to_process = (
        "/Users/tju/Desktop/d40c526e-2081-49c3-9603-83132ce88978.md"  # Example, please replace
    )

    if os.path.exists(markdown_file_to_process):
        # Examples1: TukarHTMLand keep the image
        post_processing(markdown_file_to_process, retain_images=True)

        # Examples2: TukarHTMLand remove all images
        # post_processing_revised(markdown_file_to_process, retain_images=False)
    else:
        print(f"Please refer to the 'your_markdown_file.md' Replace with the real file path before running.")
