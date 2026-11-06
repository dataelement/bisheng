"""Release-note input for a single deployment; independent of the backend package."""

import locale
import os
from pathlib import Path

from bisheng_cli.errors import EXIT_LOCAL_INVALID, CliError

MAX_CODEPOINTS = 2000
CONTRACT_VERSION = 1

_MESSAGES = {
    "en": {
        "text_help": "Release notes for this version (up to 2,000 characters)",
        "file_help": "Read release notes from a UTF-8 text file",
        "too_long": "Release notes must not exceed {limit} Unicode characters",
        "file_error": "Cannot read release notes as a regular UTF-8 text file: {path}",
        "unsupported": "The platform does not declare support for these release notes; nothing was uploaded",
        "next_step": "Upgrade the platform, or explicitly remove the release notes and retry.",
        "fix_input": "Shorten the release notes to 2,000 characters and retry.",
    },
    "zh": {
        "text_help": "本次版本的发布说明（最多 2,000 个字符）",
        "file_help": "从 UTF-8 文本文件读取本次发布说明",
        "too_long": "发布说明不能超过 {limit} 个 Unicode 字符",
        "file_error": "无法将发布说明文件作为普通 UTF-8 文本读取：{path}",
        "unsupported": "平台未声明支持本次发布说明，未上传应用包",
        "next_step": "请升级平台，或明确移除发布说明后重新提交。",
        "fix_input": "请将发布说明缩短至 2,000 个字符后重新提交。",
    },
    "ja": {
        "text_help": "このバージョンのリリースノート（最大2,000文字）",
        "file_help": "UTF-8テキストファイルからリリースノートを読み込む",
        "too_long": "リリースノートはUnicode {limit}文字以内で入力してください",
        "file_error": "通常のUTF-8テキストファイルとして読み込めません：{path}",
        "unsupported": "このリリースノートはプラットフォームでサポートされていません。アップロードしていません",
        "next_step": "プラットフォームを更新するか、リリースノートを明示的に削除して再実行してください。",
        "fix_input": "リリースノートを2,000文字以内にして再実行してください。",
    },
}


def message(key: str, **values: object) -> str:
    current = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG")
    current = current or locale.getlocale()[0] or "en"
    language = current.lower().split("_")[0].split("-")[0]
    return _MESSAGES.get(language, _MESSAGES["en"])[key].format(**values)


def normalize_release_notes(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_CODEPOINTS:
        raise CliError(
            message("too_long", limit=MAX_CODEPOINTS), exit_code=EXIT_LOCAL_INVALID, next_step=message("fix_input")
        )
    return normalized or None


def load_release_notes(text: str | None = None, file_path: str | None = None) -> str | None:
    if file_path is not None:
        path = Path(file_path)
        try:
            if not path.is_file():
                raise OSError("not a regular file")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CliError(message("file_error", path=path), exit_code=EXIT_LOCAL_INVALID) from exc
    return normalize_release_notes(text)
