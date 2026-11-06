"""Pure input rules shared by existing subject-search entry points."""

import re

MAX_KEYWORD_CODEPOINTS = 255
_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def normalize_keyword(value: str | None) -> str:
    keyword = re.sub(r"\r\n|\r|\n", " ", value or "").strip(_WHITESPACE)
    if len(keyword) > MAX_KEYWORD_CODEPOINTS:
        raise ValueError("Search keyword exceeds 255 Unicode code points")
    return keyword


def escape_like(value: str) -> str:
    """Use an explicit slash escape, independent of MySQL backslash mode."""
    return value.replace("/", "//").replace("%", "/%").replace("_", "/_")


def numeric_prefix_ranges(value: str, max_value: int = 2147483647) -> list[tuple[int, int]]:
    """Convert canonical decimal prefixes into bounded primary-key ranges."""
    if not value or not value.isascii() or not value.isdigit() or (len(value) > 1 and value[0] == "0"):
        return []
    if len(value) > len(str(max_value)):
        return []
    prefix = int(value)
    if prefix > max_value:
        return []
    if prefix == 0:
        return [(0, 0)]
    ranges = []
    factor = 1
    while prefix * factor <= max_value:
        ranges.append((prefix * factor, min((prefix + 1) * factor - 1, max_value)))
        factor *= 10
    return ranges
