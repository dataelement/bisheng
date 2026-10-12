"""Signed, short-lived usage policy; private key stays on the BISHENG server."""

import base64
import json
import os


def signing_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    pem = os.environ.get("BISHENG_DSH_MARKET_SIGNING_KEY", "").replace("\\n", "\n")
    if not pem:
        raise RuntimeError("Configure BISHENG_DSH_MARKET_SIGNING_KEY to enable Desktop distribution")
    key = load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("Marketplace signing key must use Ed25519")
    return key


def verification_key():
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return signing_key().public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def sign_policy(payload):
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()

    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    return {"payload": encode(serialized), "signature": encode(signing_key().sign(serialized))}
