"""Bounded, untrusted provenance. Never copy arbitrary producer source payloads."""

import json
import re

SOURCE_BYTES = 12288
SOURCE_ITEMS = 128
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z", re.ASCII)


def identifier(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum and IDENTIFIER.fullmatch(value) is not None


def normalize_message_sources(raw, message_count=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list) or type(raw.get("truncated")) is not bool:
        return None, "INVALID"
    partial = raw["truncated"] or len(raw["items"]) > SOURCE_ITEMS
    items, seen, duplicate = [], set(), set()
    for item in raw["items"][:SOURCE_ITEMS]:
        if not isinstance(item, dict):
            partial = True
            continue
        index, sources = item.get("message_index"), item.get("sources")
        if (
            type(index) is not int
            or index < 0
            or index > 9007199254740991
            or (message_count is not None and index >= message_count)
        ):
            partial = True
            continue
        if index in seen:
            duplicate.add(index)
            partial = True
            continue
        seen.add(index)
        if not isinstance(sources, list) or not sources:
            partial = True
            continue
        partial |= len(sources) > 4
        clean = []
        for source in sources[:4]:
            if not isinstance(source, dict) or not identifier(source.get("kind"), 64):
                partial = True
                continue
            value = {"kind": source["kind"]}
            if "form" in source:
                if identifier(source["form"], 32):
                    value["form"] = source["form"]
                else:
                    partial = True
            if value not in clean:
                clean.append(value)
        if clean:
            items.append({"message_index": index, "sources": clean})
    items = sorted(
        (item for item in items if item["message_index"] not in duplicate), key=lambda item: item["message_index"]
    )
    accepted = []
    for item in items:
        candidate = {"items": [*accepted, item], "truncated": True}
        if len(json.dumps(candidate, separators=(",", ":"), ensure_ascii=False).encode("utf8")) > SOURCE_BYTES:
            partial = True
            break
        accepted.append(item)
    if not accepted and raw["items"] and not raw["truncated"]:
        return None, "INVALID"
    return {"items": accepted, "truncated": bool(partial)}, "PARTIAL" if partial else "AVAILABLE"
