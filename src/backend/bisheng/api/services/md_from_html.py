import requests
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as md
import os
import re
import base64
from urllib.parse import urljoin, urlparse
import uuid
from loguru import logger
from email import message_from_bytes
from email.policy import default as default_policy
import shutil  # Added for file copying
from pathlib import Path  # Added for robust path handling

# Configure logger

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


class HTML2MarkdownConverter:
    def __init__(
        self,
        output_dir="output",
        image_dir_name_prefix="images",
        video_dir_name_prefix="videos",
        media_download_timeout=60,
    ):
        self.output_dir = output_dir
        self.image_dir_name_prefix = image_dir_name_prefix
        self.video_dir_name_prefix = video_dir_name_prefix
        self.MEDIA_DOWNLOAD_TIMEOUT = media_download_timeout
        os.makedirs(self.output_dir, exist_ok=True)

        self.current_image_absolute_path = None
        self.current_video_absolute_path = None
        self.base_url = None
        self.mhtml_resources = {}
        self.source_html_filepath = None

    def _clean_html(self, html_content):
        logger.debug("Starting HTML cleaning (refined logic).")
        soup = BeautifulSoup(html_content, "html.parser")
        for D_tag in soup.find_all(["script", "style", "link", "meta"]):
            D_tag.decompose()
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        potentially_problematic_container_tags = ["header", "footer", "nav", "aside"]
        non_content_patterns = re.compile(
            r"adsbygoogle|ad-slot|advertisement|promo(tion)?|banner-ad|popup-ad|cookie-notice|gdpr-banner|newsletter-signup|social-share-buttons|flyout-menu",
            re.IGNORECASE,
        )
        non_content_roles = [
            "banner",
            "navigation",
            "search",
            "complementary",
            "contentinfo",
            "dialog",
            "menubar",
            "toolbar",
            "directory",
            "log",
            "status",
            "timer",
        ]
        media_tags_to_check = ["img", "video", "picture", "figure", "svg", "audio"]
        for tag in list(soup.find_all(True)):
            if not tag.parent:
                continue
            decomposed_this_iteration = False
            if tag.name in potentially_problematic_container_tags:
                if not tag.find_all(media_tags_to_check):
                    tag.decompose()
                    decomposed_this_iteration = True
            if decomposed_this_iteration:
                continue
            if tag.name not in media_tags_to_check:
                class_match = any(
                    non_content_patterns.search(cls) for cls in tag.get("class", [])
                )
                id_match = (
                    non_content_patterns.search(tag.get("id", ""))
                    if tag.get("id")
                    else False
                )
                role_match = tag.get("role", "") in non_content_roles
                if class_match or id_match or role_match:
                    if not tag.find_all(media_tags_to_check):
                        tag.decompose()
                        decomposed_this_iteration = True
            if decomposed_this_iteration:
                continue
        form_elements_to_remove = [
            "form",
            "button",
            "input",
            "select",
            "textarea",
            "fieldset",
            "legend",
        ]
        for tag_name_to_remove in form_elements_to_remove:
            for form_tag in list(soup.find_all(tag_name_to_remove)):
                if not form_tag.parent:
                    continue
                if not form_tag.find_all(media_tags_to_check):
                    form_tag.decompose()
        for tag in soup.find_all(True):
            if not tag.parent and tag.name not in ["html", "head", "body"]:
                continue
            attrs_to_remove = [
                attr for attr in tag.attrs if attr.startswith("on") or attr == "style"
            ]
            for attr in attrs_to_remove:
                del tag.attrs[attr]
        logger.debug("HTML cleaning (refined logic) finished.")
        return str(soup)

    def _download_media_file(
        self,
        media_url,
        base_url_for_relative,
        media_absolute_save_dir,
        markdown_relative_media_folder,
        media_type_prefixes=("image/", "video/", "audio/"),
    ):
        if not media_absolute_save_dir:
            logger.error(
                f"Absolute path for saving media (media_absolute_save_dir) is not set for URL: {media_url}"
            )
            return None, media_url
        original_media_url_for_error_logger = media_url
        try:
            parsed_media_url = urlparse(media_url)
            if media_url.startswith("data:"):
                if not any(
                    prefix in media_url
                    for prefix in media_type_prefixes
                    if prefix == "image/"
                ):
                    return None, media_url
                try:
                    header, encoded = media_url.split(",", 1)
                    media_data = base64.b64decode(encoded)
                    ext_match = re.search(
                        r"data:(?P<type>image|video|audio)/(?P<ext>[a-zA-Z0-9+]+);",
                        header,
                    )
                    ext = ext_match.group("ext").lower() if ext_match else "png"
                    if ext == "svg+xml":
                        ext = "svg"
                    elif ext == "jpeg":
                        ext = "jpg"

                    if not ext or len(ext) > 5 or not ext.isalnum():
                        ext = "png"
                    unique_filename = f"media_{uuid.uuid4().hex}.{ext}"
                    absolute_filepath = os.path.join(
                        media_absolute_save_dir, unique_filename
                    )
                    markdown_path = os.path.join(
                        markdown_relative_media_folder, unique_filename
                    )
                    with open(absolute_filepath, "wb") as f:
                        f.write(media_data)
                    logger.info(f"Data URI media saved to {absolute_filepath}")
                    return markdown_path, media_url
                except Exception as e:
                    logger.error(
                        f"Failed to decode/save data URI media: {e}"
                    )
                    return None, media_url

            actual_media_url_str = media_url
            if not parsed_media_url.scheme or not parsed_media_url.netloc:
                if not base_url_for_relative:
                    logger.warning(
                        f"Cannot resolve relative media URL {actual_media_url_str} without a base URL."
                    )
                    return None, actual_media_url_str
                actual_media_url_str = urljoin(
                    base_url_for_relative, actual_media_url_str
                )

            parsed_actual_url = urlparse(actual_media_url_str)

            ext = None
            path_part_for_ext = parsed_actual_url.path
            filename_from_url_for_ext = os.path.basename(path_part_for_ext)
            if "." in filename_from_url_for_ext:
                candidate_ext = filename_from_url_for_ext.split(".")[-1].lower()
                if (
                    len(candidate_ext) <= 5
                    and candidate_ext.isalnum()
                    and candidate_ext
                    in [
                        "jpg",
                        "jpeg",
                        "png",
                        "gif",
                        "svg",
                        "webp",
                        "bmp",
                        "tiff",
                        "mp4",
                        "webm",
                        "ogg",
                        "mov",
                        "avi",
                        "mkv",
                        "mp3",
                        "wav",
                        "aac",
                    ]
                ):
                    ext = candidate_ext

            if parsed_actual_url.scheme == "file":
                local_file_path_str = parsed_actual_url.path
                if (
                    os.name == "nt"
                ):  # Windows: remove leading '/' if path starts like /C:/...
                    if (
                        len(local_file_path_str) > 2
                        and local_file_path_str[0] == "/"
                        and local_file_path_str[2] == ":"
                    ):
                        local_file_path_str = local_file_path_str[1:]

                local_file_to_copy = Path(local_file_path_str)

                if local_file_to_copy.exists() and local_file_to_copy.is_file():
                    if not ext:
                        ext = (
                            local_file_to_copy.suffix[1:].lower() or "dat"
                        )  # Get ext from local file if not from URL
                    unique_filename = f"media_{uuid.uuid4().hex}.{ext}"
                    absolute_filepath_dest = os.path.join(
                        media_absolute_save_dir, unique_filename
                    )
                    markdown_path = os.path.join(
                        markdown_relative_media_folder, unique_filename
                    )
                    shutil.copy(str(local_file_to_copy), absolute_filepath_dest)
                    logger.info(
                        f"Local media file '{local_file_to_copy}' copied to '{absolute_filepath_dest}'"
                    )
                    return (
                        markdown_path,
                        media_url,
                    )  # Return original media_url for consistency
                else:
                    logger.warning(
                        f"Local file '{local_file_to_copy}' referenced by '{actual_media_url_str}' not found or not a file."
                    )
                    return None, media_url

            elif parsed_actual_url.scheme in ["http", "https"]:
                response = requests.get(
                    actual_media_url_str,
                    headers={"User-Agent": USER_AGENT},
                    timeout=self.MEDIA_DOWNLOAD_TIMEOUT,
                    stream=True,
                )
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                if not ext:  # Try to get extension from Content-Type if not from URL
                    if any(
                        content_type.startswith(prefix)
                        for prefix in media_type_prefixes
                    ):
                        type_part = content_type.split(";")[0]
                        candidate_ext_ct = type_part.split("/")[-1]
                        if candidate_ext_ct == "svg+xml":
                            ext = "svg"
                        elif candidate_ext_ct == "jpeg":
                            ext = "jpg"
                        elif candidate_ext_ct in [
                            "png",
                            "gif",
                            "webp",
                            "bmp",
                            "tiff",
                            "mp4",
                            "webm",
                            "ogg",
                            "mov",
                            "avi",
                            "mkv",
                            "mp3",
                            "wav",
                            "aac",
                        ]:
                            ext = candidate_ext_ct

                ext = ext if ext else "dat"  # Final fallback extension
                unique_filename = f"media_{uuid.uuid4().hex}.{ext}"
                absolute_filepath = os.path.join(
                    media_absolute_save_dir, unique_filename
                )
                markdown_path = os.path.join(
                    markdown_relative_media_folder, unique_filename
                )
                with open(absolute_filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=81920):
                        f.write(chunk)
                logger.info(
                    f"HTTP/S media {actual_media_url_str} downloaded to {absolute_filepath}"
                )
                return (
                    markdown_path,
                    actual_media_url_str,
                )  # Return resolved URL for HTTP/S
            else:
                logger.warning(
                    f"Skipping download for unsupported scheme: {actual_media_url_str}"
                )
                return None, actual_media_url_str

        except requests.exceptions.Timeout:
            logger.error(
                f"Timeout processing media {original_media_url_for_error_logger}"
            )
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error {e.response.status_code} processing media {original_media_url_for_error_logger}: {e.response.reason}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(
                f"RequestException processing media {original_media_url_for_error_logger}: {e}"
            )
        except IOError as e:
            logger.error(
                f"IOError processing media {original_media_url_for_error_logger}: {e}"
            )
        except Exception as e:
            logger.error(
                f"Unexpected error processing media {original_media_url_for_error_logger}: {e}"
            )
        return None, original_media_url_for_error_logger

    def _process_images_in_html(
        self, html_content, base_url_for_relative, markdown_relative_image_folder
    ):
        logger.debug(
            f"Starting image processing. MD relative image folder: {markdown_relative_image_folder}"
        )
        soup = BeautifulSoup(html_content, "html.parser")
        for img_tag in soup.find_all("img"):
            original_src = img_tag.get("src")
            alt_text = img_tag.get("alt", "").strip()
            if not original_src:
                img_tag.decompose()
                continue
            original_src = original_src.strip()
            if not original_src:
                img_tag.decompose()
                continue
            if original_src.startswith("cid:"):
                cid = original_src[4:]
                if hasattr(self, "mhtml_resources") and cid in self.mhtml_resources:
                    media_data, resource_filename_ext = self.mhtml_resources[cid]
                    ext_from_mhtml = "png"
                    if "." in resource_filename_ext:
                        candidate_ext = resource_filename_ext.split(".")[-1].lower()
                        if len(candidate_ext) <= 5 and candidate_ext.isalnum():
                            ext_from_mhtml = candidate_ext
                    unique_filename = f"image_{uuid.uuid4().hex}.{ext_from_mhtml}"
                    absolute_filepath = os.path.join(
                        self.current_image_absolute_path, unique_filename
                    )
                    markdown_path = os.path.join(
                        markdown_relative_image_folder, unique_filename
                    )
                    try:
                        with open(absolute_filepath, "wb") as f:
                            f.write(media_data)
                        img_tag["src"] = markdown_path
                        if not alt_text:
                            alt_text = f"Embedded image {unique_filename}"
                        img_tag["alt"] = alt_text
                    except IOError as e:
                        img_tag.decompose()
                else:
                    img_tag.decompose()
                continue
            markdown_image_path, _ = self._download_media_file(
                original_src,
                base_url_for_relative,
                self.current_image_absolute_path,
                markdown_relative_image_folder,
                media_type_prefixes=("image/",),
            )
            if markdown_image_path:
                img_tag["src"] = markdown_image_path
                if not alt_text:
                    alt_text = (
                        f"Downloaded image {os.path.basename(markdown_image_path)}"
                    )
                img_tag["alt"] = alt_text
            else:
                img_tag.decompose()
        logger.debug("Image processing finished.")
        return str(soup)

    def _process_videos_in_html(
        self,
        html_content,
        base_url_for_relative,
        markdown_relative_video_folder,
        markdown_relative_image_folder_for_poster,
    ):
        logger.debug(
            f"Starting video processing. MD video folder: {markdown_relative_video_folder}, MD poster folder: {markdown_relative_image_folder_for_poster}"
        )
        soup = BeautifulSoup(html_content, "html.parser")
        for video_tag in soup.find_all("video"):
            original_poster_src = video_tag.get("poster")
            if original_poster_src:
                original_poster_src = original_poster_src.strip()
                if original_poster_src:
                    logger.info(f"Processing poster for video: {original_poster_src}")
                    if (
                        self.current_image_absolute_path
                    ):  # Ensure image path is set for saving posters
                        poster_md_path, _ = self._download_media_file(
                            original_poster_src,
                            base_url_for_relative,
                            self.current_image_absolute_path,  # Save posters in the image asset directory
                            markdown_relative_image_folder_for_poster,  # Use the image folder's relative path for MD link
                            media_type_prefixes=("image/",),
                        )
                        if poster_md_path:
                            video_tag["poster"] = poster_md_path
                        else:
                            if "poster" in video_tag.attrs:
                                del video_tag["poster"]
                    else:
                        logger.warning(
                            f"Cannot process poster {original_poster_src} as image asset path is not initialized."
                        )
            source_tags = video_tag.find_all("source")
            processed_source_successfully = False
            if source_tags:
                for source_tag in source_tags:
                    original_src = source_tag.get("src")
                    if original_src:
                        original_src = original_src.strip()
                        if not original_src:
                            continue
                        if original_src.startswith("cid:"):
                            cid = original_src[4:]
                            if (
                                hasattr(self, "mhtml_resources")
                                and cid in self.mhtml_resources
                            ):
                                media_data, resource_filename_ext = (
                                    self.mhtml_resources[cid]
                                )
                                ext_from_mhtml = "mp4"
                                if "." in resource_filename_ext:
                                    candidate_ext = resource_filename_ext.split(".")[
                                        -1
                                    ].lower()
                                    if (
                                        len(candidate_ext) <= 5
                                        and candidate_ext.isalnum()
                                    ):
                                        ext_from_mhtml = candidate_ext
                                unique_filename = (
                                    f"video_{uuid.uuid4().hex}.{ext_from_mhtml}"
                                )
                                absolute_filepath = os.path.join(
                                    self.current_video_absolute_path, unique_filename
                                )
                                markdown_path = os.path.join(
                                    markdown_relative_video_folder, unique_filename
                                )
                                try:
                                    with open(absolute_filepath, "wb") as f:
                                        f.write(media_data)
                                    source_tag["src"] = markdown_path
                                    processed_source_successfully = True
                                except IOError as e:
                                    source_tag.decompose()
                            else:
                                source_tag.decompose()
                            continue
                        markdown_video_path, _ = self._download_media_file(
                            original_src,
                            base_url_for_relative,
                            self.current_video_absolute_path,
                            markdown_relative_video_folder,
                            media_type_prefixes=("video/", "application/octet-stream"),
                        )
                        if markdown_video_path:
                            source_tag["src"] = markdown_video_path
                            processed_source_successfully = True
                        else:
                            source_tag.decompose()
            original_video_src_attr = video_tag.get("src")
            if original_video_src_attr and not processed_source_successfully:
                original_video_src_attr = original_video_src_attr.strip()
                if original_video_src_attr:
                    if original_video_src_attr.startswith("cid:"):
                        cid = original_video_src_attr[4:]
                        if (
                            hasattr(self, "mhtml_resources")
                            and cid in self.mhtml_resources
                        ):
                            media_data, resource_filename_ext = self.mhtml_resources[
                                cid
                            ]
                            ext_from_mhtml = "mp4"
                            if "." in resource_filename_ext:
                                candidate_ext = resource_filename_ext.split(".")[
                                    -1
                                ].lower()
                                if len(candidate_ext) <= 5 and candidate_ext.isalnum():
                                    ext_from_mhtml = candidate_ext
                            unique_filename = (
                                f"video_{uuid.uuid4().hex}.{ext_from_mhtml}"
                            )
                            absolute_filepath = os.path.join(
                                self.current_video_absolute_path, unique_filename
                            )
                            markdown_path = os.path.join(
                                markdown_relative_video_folder, unique_filename
                            )
                            try:
                                with open(absolute_filepath, "wb") as f:
                                    f.write(media_data)
                                video_tag["src"] = markdown_path
                                processed_source_successfully = True
                            except IOError as e:
                                if "src" in video_tag.attrs:
                                    del video_tag["src"]
                        else:
                            if "src" in video_tag.attrs:
                                del video_tag["src"]
                    else:
                        markdown_video_path, _ = self._download_media_file(
                            original_video_src_attr,
                            base_url_for_relative,
                            self.current_video_absolute_path,
                            markdown_relative_video_folder,
                            media_type_prefixes=("video/", "application/octet-stream"),
                        )
                        if markdown_video_path:
                            video_tag["src"] = markdown_video_path
                            processed_source_successfully = True
                        else:
                            if "src" in video_tag.attrs:
                                del video_tag["src"]
            if (
                not processed_source_successfully
                and not video_tag.find_all("source", src=True)
                and not video_tag.get("src")
            ):
                logger.warning(f"Video tag found with no downloadable sources.")
        logger.debug("Video processing finished.")
        return str(soup)

    def _fetch_url_content(self, url):
        try:
            headers = {"User-Agent": USER_AGENT}
            response = requests.get(
                url, headers=headers, timeout=self.MEDIA_DOWNLOAD_TIMEOUT
            )
            response.raise_for_status()
            html_text = None
            try:
                html_text = response.content.decode("utf-8")
            except UnicodeDecodeError:
                apparent_encoding = response.apparent_encoding
                try:
                    html_text = response.content.decode(apparent_encoding)
                except (UnicodeDecodeError, TypeError) as e:
                    html_text = response.text
            if "text/html" not in response.headers.get("content-type", "").lower():
                logger.warning(
                    f"URL {url} may not be HTML. Content-Type: {response.headers.get('content-type')}"
                )
            return html_text
        except requests.exceptions.Timeout:
            return f"# 错误：请求超时\n\n请求 {url} 的响应时间过长。"
        except requests.exceptions.ConnectionError:
            return f"# 错误：连接失败\n\n无法连接到 {url}。"
        except requests.exceptions.HTTPError as e:
            return f"# 错误：获取 URL 失败 ({e.response.status_code})\n\n页面 {url} 返回错误：{e.response.reason}。"
        except requests.exceptions.RequestException as e:
            return (
                f"# 错误：无法检索内容\n\n无法从 {url} 检索内容。\n\n详细信息：{str(e)}"
            )

    def _cleanup_markdown(self, markdown_text):
        logger.debug("Starting Markdown cleanup.")
        markdown_text = re.sub(r"\[\s*\]\(\s*\)", "", markdown_text)
        markdown_text = re.sub(r"!\[(.*?)\]\s+\((.*?)\)", r"![\1](\2)", markdown_text)
        markdown_text = re.sub(r"\[(.*?)\]\s+\((.*?)\)", r"[\1](\2)", markdown_text)
        markdown_text = re.sub(r"\n([*-+])(\S)", r"\n\1 \2", markdown_text)
        markdown_text = re.sub(r"\n(\d+\.)(\S)", r"\n\1 \2", markdown_text)
        markdown_text = re.sub(r"!\[\s*\]\((.*?)\)", r"![Image](\1)", markdown_text)
        markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text)
        lines = markdown_text.splitlines()
        stripped_lines = [line.strip() for line in lines]
        markdown_text = "\n".join(stripped_lines)
        logger.debug("Markdown cleanup finished.")
        return markdown_text.strip()

    def _parse_mhtml(self, mhtml_file_path):
        logger.info(f"Parsing MHTML file: {mhtml_file_path}")
        self.mhtml_resources = {}
        try:
            with open(mhtml_file_path, "rb") as f:
                mhtml_bytes = f.read()
            msg = message_from_bytes(mhtml_bytes, policy=default_policy)
            html_content = None
            start_cid = None
            if msg.is_multipart() and msg.get_content_type() == "multipart/related":
                start_param = msg.get_param("start", header="content-type")
                if start_param:
                    start_cid = start_param.strip("<>")
            for part_idx, part in enumerate(msg.walk()):
                content_type = part.get_content_type()
                content_id_header = part.get("Content-ID")
                content_location_header = part.get("Content-Location")
                current_cid = None
                if content_id_header:
                    current_cid = content_id_header.strip("<>")
                is_html_part = content_type == "text/html"
                if html_content is None:
                    if start_cid and current_cid == start_cid and is_html_part:
                        html_content = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                    elif (
                        not start_cid
                        and is_html_part
                        and (
                            not part.get_filename()
                            or (
                                content_location_header
                                and urlparse(content_location_header).path.endswith(
                                    (".htm", ".html")
                                )
                            )
                        )
                    ):
                        html_content = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                if current_cid and (
                    any(
                        content_type.startswith(p)
                        for p in ["image/", "video/", "audio/"]
                    )
                    or part.get_filename()
                ):
                    try:
                        resource_data = part.get_payload(decode=True)
                        resource_filename = (
                            part.get_filename()
                            or f"{current_cid}.{content_type.split('/')[-1].split('+')[0]}"
                        )
                        self.mhtml_resources[current_cid] = (
                            resource_data,
                            resource_filename,
                        )
                    except Exception as e:
                        logger.error(
                            f"Could not decode/store MHTML resource CID {current_cid}: {e}"
                        )
            if not html_content and start_cid:
                for part in msg.walk():
                    if (
                        part.get_content_type() == "text/html"
                        and not part.get_filename()
                    ):
                        html_content = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        break
            if not html_content:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_content = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        break
            if not html_content:
                return None, None
            return html_content, None
        except Exception as e:
            self.mhtml_resources = {}
            return None, None

    def convert(self, source, source_type="url", output_filename_stem=None):
        html_content = None
        self.base_url = None
        self.mhtml_resources = {}
        self.source_html_filepath = None

        if not output_filename_stem:
            if source_type == "url":
                parsed_url = urlparse(source)
                host_part = parsed_url.netloc.replace(".", "_")
                path_part = (
                    parsed_url.path.strip("/").replace("/", "_").replace(".", "_")
                )
                stem = f"{host_part}_{path_part}" if path_part else host_part
                stem = re.sub(r"[^a-zA-Z0-9_-]", "", stem)[:100]
                output_filename_stem = (
                    stem if stem else f"url_conversion_{uuid.uuid4().hex[:8]}"
                )
            else:
                stem = os.path.splitext(os.path.basename(source))[0]
                output_filename_stem = (
                    stem if stem else f"file_conversion_{uuid.uuid4().hex[:8]}"
                )

        logger.info(
            f"Starting conversion. Source: {source}, Type: {source_type}, Output stem: {output_filename_stem}"
        )

        if source_type == "url":
            self.base_url = source
            html_content = self._fetch_url_content(source)
            if html_content and html_content.startswith(("# 错误：", "# Error:")):
                error_md_path = os.path.join(
                    self.output_dir, f"{output_filename_stem}_error.md"
                )
                try:
                    with open(error_md_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    return error_md_path
                except IOError as e_io:
                    return None
        elif source_type == "html_file":
            self.source_html_filepath = os.path.abspath(
                source
            )  # Store absolute path of source HTML
            try:
                with open(
                    self.source_html_filepath, "r", encoding="utf-8", errors="replace"
                ) as f:
                    html_content = f.read()
                self.base_url = (
                    Path(self.source_html_filepath).parent.as_uri() + "/"
                )  # file:///path/to/containing_directory/
            except FileNotFoundError:
                logger.error(f"HTML file not found: {source}")
                return None
            except IOError as e:
                logger.error(f"Could not read HTML file {source}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error reading HTML file {source}: {e}")
                return None
        elif source_type == "mhtml_file":
            html_content, self.base_url = self._parse_mhtml(source)
        else:
            logger.error(f"Invalid source type: {source_type}")
            return None
        if not html_content:
            logger.error(f"No HTML content to process from {source}.")
            return None

        md_img_rel_folder = f"{output_filename_stem}_{self.image_dir_name_prefix}"
        self.current_image_absolute_path = os.path.join(
            self.output_dir, md_img_rel_folder
        )
        md_vid_rel_folder = f"{output_filename_stem}_{self.video_dir_name_prefix}"
        self.current_video_absolute_path = os.path.join(
            self.output_dir, md_vid_rel_folder
        )
        try:
            os.makedirs(self.current_image_absolute_path, exist_ok=True)
            os.makedirs(self.current_video_absolute_path, exist_ok=True)
        except OSError as e:
            logger.error(f"Could not create asset directories: {e}")
            return None

        logger.info("Cleaning HTML...")
        cleaned_html = self._clean_html(html_content)

        logger.info("Processing and downloading images...")
        html_after_images = self._process_images_in_html(
            cleaned_html, self.base_url, md_img_rel_folder
        )
        logger.info("Processing and downloading videos...")
        # Pass md_img_rel_folder for posters
        html_after_videos = self._process_videos_in_html(
            html_after_images, self.base_url, md_vid_rel_folder, md_img_rel_folder
        )

        logger.info("Converting HTML to Markdown...")
        try:
            markdown_output = md(
                html_after_videos,
                heading_style="atx",
                bullets="-",
                default_title=False,
                strip=[],
            )
        except Exception as e:
            logger.error(f"Error during Markdown conversion for {source}: {e}.")
            try:
                markdown_output = md(
                    html_after_images,
                    heading_style="atx",
                    bullets="-",
                    default_title=False,
                    strip=[],
                )  # Fallback
            except Exception as e2:
                debug_html_path = os.path.join(
                    self.output_dir, f"{output_filename_stem}_debug_processed.html"
                )
                try:
                    with open(debug_html_path, "w", encoding="utf-8") as f_debug:
                        f_debug.write(html_after_videos)
                except IOError:
                    pass
                return None

        logger.info("Cleaning Markdown...")
        final_markdown = self._cleanup_markdown(markdown_output)
        output_md_path = os.path.join(self.output_dir, f"{output_filename_stem}.md")
        try:
            with open(output_md_path, "w", encoding="utf-8") as f:
                f.write(final_markdown)
            logger.info(f"Markdown file saved to {output_md_path}")
            for asset_path in [
                self.current_image_absolute_path,
                self.current_video_absolute_path,
            ]:
                if os.path.exists(asset_path) and not os.listdir(asset_path):
                    try:
                        os.rmdir(asset_path)
                    except OSError as e_rmdir:
                        logger.warning(
                            f"Could not remove empty asset folder {asset_path}: {e_rmdir}"
                        )
            return output_md_path
        except IOError as e:
            logger.error(f"Could not write Markdown file {output_md_path}: {e}")
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error writing Markdown file {output_md_path}: {e}"
            )
            return None


def mhtml_handler(file_path, converter):

    if os.path.exists(file_path):
        md_path_mhtml = converter.convert(
            file_path, source_type="mhtml_file", output_filename_stem="test_mhtml"
        )
        if md_path_mhtml:
            logger.debug(f"MHTML file converted to: {md_path_mhtml}")
        else:
            logger.warning(f"Failed to convert MHTML file: {file_path}")
    else:
        logger.warning(
            f"\nTest MHTML file '{file_path}' not found. Skipping MHTML test."
        )


def url_handler(url, converter):
    md_path_url = converter.convert(
        url, source_type="url", output_filename_stem="url_test_sample"
    )
    if md_path_url:
        logger.debug(f"URL converted to: {md_path_url}")
    else:
        logger.warning(f"Failed to convert URL: {url}")


def html_handler(html_file_name, converter):
    if os.path.exists(html_file_name):
        md_path_local_html = converter.convert(
            html_file_name,
            source_type="html_file",
            output_filename_stem=Path(html_file_name).stem,
        )
        if not md_path_local_html:
            logger.warning(f"Failed to convert local HTML: {html_file_name}")
    else:
        logger.debug(
            f"\nLocal HTML test file not found at '{html_file_name}'. Please set up the test case as described in the comments."
        )


def handler(file_or_url: str, knowledge_id: int):

    base_dir = "/var/tmp/bisheng"  # Base directory for output
    output_dir = f"{base_dir}/html"

    converter = HTML2MarkdownConverter(
        output_dir=output_dir,
        image_dir_name_prefix="images",
        video_dir_name_prefix="videos",
        media_download_timeout=60,
    )

    if file_or_url.startswith("http://") or file_or_url.startswith("https://"):
        url_handler(file_or_url, converter)
    if file_or_url.endswith(".mhtml"):
        mhtml_handler(file_or_url, converter)
    if file_or_url.endswith(".html"):
        html_handler(file_or_url, converter)

    # replace image url
    # upload image and video to oss


# Example Usage
if __name__ == "__main__":
    local_html_file_path = (
        "/Users/tju/Resources/docs/html/f.html"  # <<-- UPDATE THIS PATH
    )
    test_url = "https://www.zaobao.com/news/china/story20250510-6319065"  # Example BBC Chinese article
    mhtml_file_path = (
        "/Users/tju/Resources/docs/html/a.mhtml"  # Replace with your MHTML file path
    )
