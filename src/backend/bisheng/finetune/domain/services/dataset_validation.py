"""Bounded, side-effect-free inspection before persisting a training version."""

import io
import json
import zipfile
from pathlib import PurePosixPath

from PIL import Image

UPLOAD_MAX_BYTES = 2 * 1024**3  # one package uploaded from the browser
TEXT_MAX_BYTES = 200 * 1024**2  # JSON / JSONL manifests are parsed whole
MEDIA_MAX_BYTES = 200 * 1024**2  # one image or video
UNPACKED_MAX_BYTES = 8 * 1024**3  # every member of one ZIP after decompression
MAX_MEMBERS = 200_000
PREVIEW_SAMPLES = 3
# Versions stored before preview packages existed are previewed from their full bytes.
LEGACY_PREVIEW_MAX_BYTES = 20 * 1024 * 1024
MANIFEST_NAMES = ("train.json", "train.jsonl", "data.json", "data.jsonl")


def safe_path(value: str) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and not any(part in {"", ".", ".."} for part in value.split("/")) and ":" not in value


def validate_records(records, modality="text"):
    if not isinstance(records, list) or not records:
        raise ValueError("Dataset must be a non-empty JSON list")
    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("audios"):
            raise ValueError(f"Record {index}: expected an object without audio")
        images, videos = record.get("images", []), record.get("videos", [])
        if not isinstance(images, list) or not isinstance(videos, list):
            raise ValueError(f"Record {index}: media references must be lists")
        if modality == "text" and (images or videos):
            raise ValueError(f"Record {index}: text data cannot contain media")
        if modality == "image_text" and (not images or videos):
            raise ValueError(f"Record {index}: image data requires images only")
        if modality == "video_text" and (not videos or images):
            raise ValueError(f"Record {index}: video data requires videos only")
        messages = record.get("messages")
        if messages is None and modality == "text":
            if (
                not isinstance(record.get("instruction"), str)
                or not record["instruction"].strip()
                or not isinstance(record.get("output"), str)
                or not record["output"].strip()
            ):
                raise ValueError(f"Record {index}: instruction and output are required")
            continue
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError(f"Record {index}: messages need a question and answer")
        if any(not isinstance(message, dict) for message in messages):
            raise ValueError(f"Record {index}: messages must be objects")
        turns = messages[1:] if messages[0].get("role") == "system" else messages
        if len(turns) < 2 or len(turns) % 2:
            raise ValueError(f"Record {index}: messages must end in an assistant answer")
        for turn, message in enumerate(messages):
            if (
                not isinstance(message, dict)
                or not isinstance(message.get("content"), str)
                or not message["content"].strip()
            ):
                raise ValueError(f"Record {index}: message content must be non-empty text")
            expected = "system" if turn == 0 and messages is not turns else None
            if expected and message.get("role") != expected:
                raise ValueError(f"Record {index}: invalid system message")
        if any(message.get("role") != ("user" if turn % 2 == 0 else "assistant") for turn, message in enumerate(turns)):
            raise ValueError(f"Record {index}: user and assistant roles must alternate")
        content = "".join(message["content"] for message in messages)
        if content.count("<image>") != len(images) or content.count("<video>") != len(videos) or "<audio>" in content:
            raise ValueError(f"Record {index}: media placeholders do not match references")


def parse_manifest(raw: bytes, name: str):
    text = raw.decode("utf-8-sig")
    return (
        [json.loads(line) for line in text.splitlines() if line.strip()]
        if name.endswith(".jsonl")
        else json.loads(text)
    )


def _archive(source):
    return zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes | bytearray) else source)


def _package_records(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS or sum(item.file_size for item in members) > UNPACKED_MAX_BYTES:
        raise ValueError("Uncompressed dataset exceeds the 8 GiB validation limit")
    names = set()
    for item in members:
        name = item.filename.rstrip("/") if item.is_dir() else item.filename
        if not safe_path(name) or ((item.external_attr >> 16) & 0o170000) == 0o120000 or item.filename in names:
            raise ValueError(f"Unsafe ZIP member: {item.filename}")
        names.add(item.filename)
    manifests = [name for name in MANIFEST_NAMES if name in names]
    if len(manifests) != 1:
        raise ValueError("ZIP root must contain exactly one train.json or train.jsonl manifest")
    if archive.getinfo(manifests[0]).file_size > TEXT_MAX_BYTES:
        raise ValueError("Manifest exceeds 200 MiB")
    records = parse_manifest(archive.read(manifests[0]), manifests[0])
    if not isinstance(records, list) or not records or not isinstance(records[0], dict):
        raise ValueError("Manifest must contain a non-empty list")
    return records, names


def inspect_package(source):
    """Validate a ZIP given as bytes or a seekable binary file, reading one member at a time."""
    with _archive(source) as archive:
        records, names = _package_records(archive)
        modality = "video_text" if records[0].get("videos") else "image_text" if records[0].get("images") else "text"
        validate_records(records, modality)
        referenced = set()
        for record in records:
            for name in record.get("images", []) + record.get("videos", []):
                if not safe_path(name) or name not in names:
                    raise ValueError(f"Missing or unsafe media reference: {name}")
                if name not in referenced:
                    if archive.getinfo(name).file_size > MEDIA_MAX_BYTES:
                        raise ValueError(f"Media exceeds 200 MiB: {name}")
                    inspect_media(archive.read(name), name, modality)
                    referenced.add(name)
        return modality, len(records), len(referenced)


def build_preview(records, read_media) -> bytes:
    """A small ZIP with the first samples and only their media; the preview endpoints never load the full data."""
    sample = records[:PREVIEW_SAMPLES]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("train.json", json.dumps(sample, ensure_ascii=False))
        for name in dict.fromkeys(
            media for record in sample for media in record.get("images", []) + record.get("videos", [])
        ):
            archive.writestr(name, read_media(name))
    return buffer.getvalue()


def package_preview(source) -> bytes:
    with _archive(source) as archive:
        records, _ = _package_records(archive)
        return build_preview(records, archive.read)


def inspect_media(content: bytes, name: str, modality: str):
    if not content or len(content) > MEDIA_MAX_BYTES:
        raise ValueError(f"Media must be between 1 byte and 200 MiB: {name}")
    if modality == "image_text":
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
        except (OSError, SyntaxError, ValueError):
            # Pillow's own message names an in-memory buffer, which tells the user nothing.
            raise ValueError(f"Image cannot be decoded: {name}") from None
    elif modality == "video_text":
        # Full codec/frame validation occurs on the FT node with its pinned PyAV runtime.
        if not name.lower().endswith(".mp4") or len(content) < 12 or content[4:8] != b"ftyp":
            raise ValueError("Video must be an MP4 file; FT preflight validates decoded frames")
    else:
        raise ValueError("Text tasks do not accept media")
