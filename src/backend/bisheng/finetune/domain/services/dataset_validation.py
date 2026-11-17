"""Bounded, side-effect-free inspection before persisting a training version."""

import io
import json
import zipfile
from pathlib import PurePosixPath

from PIL import Image

MAX_BYTES = 20 * 1024 * 1024


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


def inspect_package(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(item.file_size for item in members) > MAX_BYTES:
            raise ValueError("Uncompressed dataset exceeds 20 MiB validation limit")
        names = set()
        for item in members:
            name = item.filename.rstrip("/") if item.is_dir() else item.filename
            if not safe_path(name) or ((item.external_attr >> 16) & 0o170000) == 0o120000 or item.filename in names:
                raise ValueError(f"Unsafe ZIP member: {item.filename}")
            names.add(item.filename)
        manifests = [name for name in ("train.json", "train.jsonl", "data.json", "data.jsonl") if name in names]
        if len(manifests) != 1:
            raise ValueError("ZIP root must contain exactly one train.json or train.jsonl manifest")
        raw = archive.read(manifests[0]).decode("utf-8-sig")
        records = (
            [json.loads(line) for line in raw.splitlines() if line.strip()]
            if manifests[0].endswith("jsonl")
            else json.loads(raw)
        )
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            raise ValueError("Manifest must contain a non-empty list")
        modality = "video_text" if records[0].get("videos") else "image_text" if records[0].get("images") else "text"
        validate_records(records, modality)
        referenced = set()
        for record in records:
            for name in record.get("images", []) + record.get("videos", []):
                if not safe_path(name) or name not in names:
                    raise ValueError(f"Missing or unsafe media reference: {name}")
                if name not in referenced:
                    media = archive.read(name)
                    inspect_media(media, name, modality)
                    referenced.add(name)
        return modality, len(records), len(referenced)


def inspect_media(content: bytes, name: str, modality: str):
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Media must be between 1 byte and 20 MiB")
    if modality == "image_text":
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    elif modality == "video_text":
        # Full codec/frame validation occurs on the FT node with its pinned PyAV runtime.
        if not name.lower().endswith(".mp4") or len(content) < 12 or content[4:8] != b"ftyp":
            raise ValueError("Video must be an MP4 file; FT preflight validates decoded frames")
    else:
        raise ValueError("Text tasks do not accept media")
