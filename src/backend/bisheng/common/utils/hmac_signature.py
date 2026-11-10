"""Side-effect-free canonical request signing shared by Gateway trust adapters."""

import hashlib
import hmac
import re

_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


def compute_hmac_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Sign uppercase method, LF, exact path, LF and unmodified body bytes."""
    message = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def compare_hmac_signatures(expected: str, provided: str | None) -> bool:
    """Compare public hex formatting normally, and valid digests in constant time."""
    if not isinstance(expected, str) or not isinstance(provided, str):
        return False
    canonical = expected.lower()
    candidate = provided.strip().lower()
    if not _HEX_SHA256.fullmatch(canonical) or not _HEX_SHA256.fullmatch(candidate):
        return False
    return hmac.compare_digest(canonical, candidate)
